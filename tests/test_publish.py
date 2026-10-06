"""The publication rules, exercised with two publishers that interleave.

docs/architecture-review-findings.md, section 6, rules 1 to 3 and the fourth
"done when" criterion. The store here is the in-memory one, which passes the
same contract as the real bucket (tests/test_store.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from f1data import layout
from f1data.archive import Snapshot
from f1data.coverage import measure_coverage
from f1data.identity import SessionIdentity
from f1data.publish import (
    Inputs,
    Pointer,
    PointerError,
    derive_index,
    publish_index,
    publish_session,
    read_pointer,
    read_published,
    upload_generation,
)
from f1data.schedule import ScheduledSession
from f1data.store import MemoryStore
from tests.fakes import make_session

NOW = datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)
AUSTRIA = 11315
ITALY = 11361


def identity(session_key: int = AUSTRIA, start: str = "2026-06-28T13:00:00Z", name: str = "Austrian Grand Prix"):
    return SessionIdentity(
        session_key=session_key,
        meeting_key=session_key - 10000,
        year=int(start[:4]),
        session_type="R",
        session_name="Race",
        start_time_utc=start,
        meeting_name=name,
        meeting_official_name=None,
        location=None,
        country=None,
        circuit_key=None,
        circuit_name=None,
        archive_path=f"{start[:4]}/{start[:10]}_{name.replace(' ', '_')}/{start[:10]}_Race/",
        round_at_fetch=8,
    )


def snapshot(session_key: int = AUSTRIA, snapshot_id: str = "20261005T200000Z-aaaaaaaa", session=None, **kwargs):
    return Snapshot(
        snapshot_id=snapshot_id,
        identity=identity(session_key, **kwargs),
        fetched_at=f"{snapshot_id[:4]}-{snapshot_id[4:6]}-{snapshot_id[6:8]}T{snapshot_id[9:11]}:00:00Z",
        coverage=measure_coverage(session or make_session(), "R"),
    )


class Publisher:
    """One run of the job: what it would gather and build, and how often it built."""

    def __init__(self, store, snap=None, fingerprint="sha256:first", files=None):
        self.store = store
        self.snapshot = snap or snapshot()
        self.fingerprint = fingerprint
        self.files = files or {"summary.json": b'{"meeting":"Austrian Grand Prix"}\n', "laps.json": b"[]\n"}
        self.builds = 0

    def gather(self, session_key):
        return Inputs(self.snapshot, self.fingerprint)

    def build(self, inputs):
        self.builds += 1
        return dict(self.files), None

    def publish(self, **kwargs):
        return publish_session(
            self.store, self.snapshot.session_key, self.gather, self.build, now=lambda: NOW, **kwargs
        )


class Interposing:
    """A store that lets a test run something at a chosen moment in a publish."""

    def __init__(self, store):
        self._store = store
        self.operations: list[tuple[str, str]] = []
        self.before_put: dict[str, object] = {}
        self.after_list: dict[str, object] = {}

    def __getattr__(self, name):
        return getattr(self._store, name)

    def get(self, key):
        self.operations.append(("get", key))
        return self._store.get(key)

    def list(self, prefix):
        self.operations.append(("list", prefix))
        listed = list(self._store.list(prefix))
        action = self.after_list.pop(prefix, None)
        if action is not None:
            action()
        return iter(listed)

    def put(self, key, data, **kwargs):
        action = self.before_put.pop(key, None)
        if action is not None:
            action()
        self.operations.append(("put", key))
        return self._store.put(key, data, **kwargs)


def pointer_of(store, session_key=AUSTRIA) -> Pointer:
    pointer, _ = read_pointer(store, session_key)
    assert pointer is not None
    return pointer


# --- a single publisher -------------------------------------------------------


def test_a_first_publication_uploads_a_generation_and_then_points_at_it():
    store = MemoryStore()

    outcome = Publisher(store).publish()

    assert outcome.action == "published" and outcome.reason == "not published"
    pointer = pointer_of(store)
    assert pointer.generation == outcome.generation
    assert pointer.snapshot_id == "20261005T200000Z-aaaaaaaa"
    assert pointer.classification_fingerprint == "sha256:first"
    assert pointer.complete is True and pointer.shortfalls == []
    assert (pointer.format_version, pointer.pipeline_version) == (layout.FORMAT_VERSION, layout.PIPELINE_VERSION)
    assert pointer.published_at == "2026-10-05T20:00:00Z"
    prefix = layout.generation_prefix(AUSTRIA, pointer.generation)
    assert store.get(f"{prefix}summary.json").data == b'{"meeting":"Austrian Grand Prix"}\n'
    manifest = json.loads(store.get(f"{prefix}manifest.json").data)
    assert manifest["schema_version"] == layout.FORMAT_VERSION
    assert [item["path"] for item in manifest["files"]] == ["laps.json", "summary.json"]


def test_a_second_run_over_the_same_inputs_builds_nothing():
    store = MemoryStore()
    Publisher(store).publish()
    again = Publisher(store)

    outcome = again.publish()

    assert outcome.action == "current"
    assert again.builds == 0


def test_the_pointer_records_an_incomplete_session_as_incomplete():
    store = MemoryStore()
    damaged = make_session()
    del damaged.pos_data["2"]

    Publisher(store, snap=snapshot(session=damaged)).publish()

    pointer = pointer_of(store)
    assert pointer.complete is False
    assert pointer.shortfalls == [
        {"bar": "position", "driver": "BBB", "detail": "0 of 10 expected laps usable"}
    ]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"fingerprint": "sha256:after-a-penalty"}, "the classification changed"),
        ({"snap": snapshot(snapshot_id="20261006T080000Z-bbbbbbbb")}, "a different snapshot is now selected"),
    ],
)
def test_a_changed_input_republishes_and_keeps_the_old_generation(change, reason):
    store = MemoryStore()
    first = Publisher(store).publish()

    second = Publisher(store, files={"summary.json": b'{"rebuilt":true}\n'}, **change).publish()

    assert second.action == "published" and second.reason == reason
    assert second.generation != first.generation
    assert pointer_of(store).previous_generation == first.generation
    # A page that pinned the first generation still reads it (rule 1).
    old = f"{layout.generation_prefix(AUSTRIA, first.generation)}summary.json"
    assert store.get(old).data == b'{"meeting":"Austrian Grand Prix"}\n'


def test_a_pointer_from_an_older_pipeline_version_is_rebuilt(monkeypatch):
    store = MemoryStore()
    first = Publisher(store).publish()
    monkeypatch.setattr(layout, "PIPELINE_VERSION", layout.PIPELINE_VERSION + 1)

    second = Publisher(store).publish()

    assert second.action == "published"
    assert second.reason.startswith("pipeline version")
    # Same files, but the manifest carries the pipeline version, so it is a new generation.
    assert second.generation != first.generation


def test_the_same_inputs_built_anywhere_land_on_the_same_generation():
    one, other = MemoryStore(), MemoryStore()

    assert Publisher(one).publish().generation == Publisher(other).publish().generation


def test_nothing_in_the_archive_means_nothing_to_publish():
    store = MemoryStore()

    outcome = publish_session(store, AUSTRIA, lambda key: None, lambda inputs: ({}, None))

    assert outcome.action == "no_snapshot"
    assert read_pointer(store, AUSTRIA) == (None, None)


# --- two publishers -----------------------------------------------------------


def test_the_loser_of_a_pointer_write_drops_its_build_when_the_winner_did_the_job():
    store = Interposing(MemoryStore())
    winner = Publisher(store)
    loser = Publisher(store)
    store.before_put[layout.pointer_key(AUSTRIA)] = winner.publish

    outcome = loser.publish()

    assert outcome.action == "superseded"
    assert loser.builds == 1


def test_the_loser_publishes_its_build_when_it_is_still_what_the_inputs_select():
    """The winner built from an older snapshot; the loser's better one must not be lost."""
    store = Interposing(MemoryStore())
    better = snapshot(snapshot_id="20261006T080000Z-bbbbbbbb")
    winner = Publisher(store, files={"summary.json": b'{"from":"older snapshot"}\n'})
    loser = Publisher(store, snap=better)
    store.before_put[layout.pointer_key(AUSTRIA)] = winner.publish

    outcome = loser.publish()

    assert outcome.action == "published"
    assert pointer_of(store).snapshot_id == better.snapshot_id
    # Not rebuilt: the candidate was already what these inputs build.
    assert loser.builds == 1


def test_the_loser_rebuilds_when_the_inputs_moved_while_it_was_building():
    store = Interposing(MemoryStore())
    winner = Publisher(store, fingerprint="sha256:before-the-penalty")
    loser = Publisher(store, fingerprint="sha256:before-the-penalty")

    def winner_publishes_and_a_penalty_lands():
        winner.publish()
        loser.fingerprint = "sha256:after-the-penalty"
        loser.files = {"summary.json": b'{"penalty":"applied"}\n'}

    store.before_put[layout.pointer_key(AUSTRIA)] = winner_publishes_and_a_penalty_lands

    outcome = loser.publish()

    assert outcome.action == "published" and outcome.reason == "the classification changed"
    assert loser.builds == 2
    pointer = pointer_of(store)
    assert pointer.classification_fingerprint == "sha256:after-the-penalty"
    prefix = layout.generation_prefix(AUSTRIA, pointer.generation)
    assert store.get(f"{prefix}summary.json").data == b'{"penalty":"applied"}\n'


def test_an_older_pipeline_version_never_replaces_a_newer_pointer(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(layout, "PIPELINE_VERSION", 7)
    newer = Publisher(store).publish()
    monkeypatch.setattr(layout, "PIPELINE_VERSION", 6)
    old_checkout = Publisher(store, fingerprint="sha256:something-else")

    outcome = old_checkout.publish()

    assert outcome.action == "newer"
    assert old_checkout.builds == 0
    assert pointer_of(store).generation == newer.generation


def test_an_older_pipeline_version_that_loses_the_write_to_a_newer_one_backs_off(monkeypatch):
    """Criterion 4: started so that it loses the pointer write to a newer run."""
    store = Interposing(MemoryStore())
    old_checkout = Publisher(store)
    newer_generation = []

    def a_newer_version_publishes():
        monkeypatch.setattr(layout, "PIPELINE_VERSION", 7)
        newer_generation.append(Publisher(store).publish().generation)
        monkeypatch.setattr(layout, "PIPELINE_VERSION", 6)

    monkeypatch.setattr(layout, "PIPELINE_VERSION", 6)
    store.before_put[layout.pointer_key(AUSTRIA)] = a_newer_version_publishes

    outcome = old_checkout.publish()

    assert outcome.action == "newer"
    assert pointer_of(store).generation == newer_generation[0]
    assert pointer_of(store).pipeline_version == 7


def test_a_publisher_that_keeps_losing_gives_up_without_writing():
    store = Interposing(MemoryStore())
    stubborn = Publisher(store)
    rivals = iter(range(100))

    def a_rival_publishes_something_else():
        number = next(rivals)
        Publisher(store, fingerprint=f"sha256:rival-{number}").publish()
        store.before_put[layout.pointer_key(AUSTRIA)] = a_rival_publishes_something_else

    store.before_put[layout.pointer_key(AUSTRIA)] = a_rival_publishes_something_else

    outcome = stubborn.publish(max_attempts=3)

    assert outcome.action == "conflict"
    assert pointer_of(store).classification_fingerprint.startswith("sha256:rival-")


# --- the pointer itself -------------------------------------------------------


def test_an_unreadable_pointer_is_an_error_not_an_unpublished_session():
    store = MemoryStore()
    store.put(layout.pointer_key(AUSTRIA), b"not json")

    with pytest.raises(PointerError):
        read_pointer(store, AUSTRIA)
    with pytest.raises(PointerError):
        Publisher(store).publish()


def test_a_pointer_whose_generation_and_manifest_disagree_is_rejected():
    store = MemoryStore()
    Publisher(store).publish()
    payload = json.loads(store.get(layout.pointer_key(AUSTRIA)).data)
    payload["generation"] = "0" * 64
    store.put(layout.pointer_key(AUSTRIA), json.dumps(payload).encode())

    with pytest.raises(PointerError):
        read_pointer(store, AUSTRIA)


def test_a_pointer_filed_under_another_session_is_rejected():
    store = MemoryStore()
    Publisher(store).publish()
    store.put(layout.pointer_key(ITALY), store.get(layout.pointer_key(AUSTRIA)).data)

    with pytest.raises(PointerError):
        read_pointer(store, ITALY)


@pytest.mark.parametrize("path", ["../escape.json", "a/../../b.json", "/absolute.json", "back\\slash.json", ""])
def test_a_generation_refuses_a_path_outside_itself(path):
    with pytest.raises(ValueError):
        upload_generation(MemoryStore(), identity(), {path: b"{}"})


def test_the_build_cannot_supply_the_manifest():
    with pytest.raises(ValueError):
        upload_generation(MemoryStore(), identity(), {"manifest.json": b"{}"})


def test_an_interrupted_upload_is_finished_by_the_next_one():
    store = MemoryStore()
    files = {"summary.json": b"{}\n", "laps.json": b"[]\n"}
    generation, _ = upload_generation(store, identity(), files)
    prefix = layout.generation_prefix(AUSTRIA, generation)
    # As if the first upload had stopped before its last file and its manifest.
    del store._objects[f"{prefix}manifest.json"]
    del store._objects[f"{prefix}laps.json"]

    again, _ = upload_generation(store, identity(), files)

    assert again == generation
    assert store.get(f"{prefix}laps.json").data == b"[]\n"
    assert store.get(f"{prefix}manifest.json") is not None


# --- the index ----------------------------------------------------------------


def schedule_2026(austria_round: int = 8, italy_round: int = 14) -> list[ScheduledSession]:
    def entry(round_number, name, session_type, session_name, start):
        return ScheduledSession(
            year=2026,
            round=round_number,
            meeting_name=name,
            meeting_official_name=None,
            country=None,
            location=None,
            meeting_date=start[:10],
            meeting_format="conventional",
            session_type=session_type,
            session_name=session_name,
            start_time_utc=start,
        )

    return [
        entry(austria_round, "Austrian Grand Prix", "Q", "Qualifying", "2026-06-27T14:00:00Z"),
        entry(austria_round, "Austrian Grand Prix", "R", "Race", "2026-06-28T13:00:00Z"),
        entry(italy_round, "Italian Grand Prix", "R", "Race", "2026-09-06T13:00:00Z"),
    ]


def italy_snapshot():
    return snapshot(ITALY, start="2026-09-06T13:00:00Z", name="Italian Grand Prix")


def published_keys(index: dict) -> dict[tuple[int, str], int]:
    return {
        (meeting["round"], session["type"]): session["session_key"]
        for season in index["seasons"]
        for meeting in season["meetings"]
        for session in meeting["sessions"]
        if "session_key" in session
    }


def test_the_index_is_the_calendar_with_published_sessions_attached():
    store = MemoryStore()
    Publisher(store).publish()

    assert publish_index(store, lambda year: schedule_2026()) == "published"

    index = json.loads(store.get(layout.index_key()).data)
    assert index["format_version"] == layout.FORMAT_VERSION
    (season,) = index["seasons"]
    austria, italy = season["meetings"]
    assert (austria["round"], austria["name"]) == (8, "Austrian Grand Prix")
    assert austria["sessions"] == [
        {"type": "Q", "name": "Qualifying", "start_time_utc": "2026-06-27T14:00:00Z"},
        {
            "type": "R",
            "name": "Race",
            "start_time_utc": "2026-06-28T13:00:00Z",
            "session_key": AUSTRIA,
            "complete": True,
        },
    ]
    assert italy["sessions"] == [{"type": "R", "name": "Race", "start_time_utc": "2026-09-06T13:00:00Z"}]
    assert index["unscheduled"] == []


def test_a_session_follows_its_race_when_the_calendar_is_renumbered():
    """AR-20: a race inserted earlier in the season moves every later round by one."""
    pointers = read_published(_store_with(Publisher))

    index = derive_index(pointers, {2026: schedule_2026(austria_round=9, italy_round=15)})

    assert published_keys(index) == {(9, "R"): AUSTRIA}


def _store_with(publisher_class):
    store = MemoryStore()
    publisher_class(store).publish()
    return store


def test_a_published_session_the_calendar_no_longer_lists_is_shown_not_dropped():
    pointers = read_published(_store_with(Publisher))

    index = derive_index(pointers, {2026: [entry for entry in schedule_2026() if entry.round != 8]})

    assert published_keys(index) == {}
    assert [item["session_key"] for item in index["unscheduled"]] == [AUSTRIA]


def test_an_index_that_would_not_change_is_not_rewritten():
    store = Interposing(MemoryStore())
    Publisher(store).publish()
    publish_index(store, lambda year: schedule_2026())
    store.operations.clear()

    assert publish_index(store, lambda year: schedule_2026()) == "current"
    assert ("put", layout.index_key()) not in store.operations


def test_the_index_is_read_before_the_pointers_are_listed():
    store = Interposing(MemoryStore())
    Publisher(store).publish()
    store.operations.clear()

    publish_index(store, lambda year: schedule_2026())

    relevant = [op for op in store.operations if op in {("get", layout.index_key()), ("list", layout.pointers_prefix())}]
    assert relevant == [("get", layout.index_key()), ("list", layout.pointers_prefix())]


def test_two_publishers_started_together_both_end_up_in_the_index():
    """Criterion 4: one publisher's pointer and index writes land between the
    other's pointer listing and its index write, and both sessions survive."""
    store = Interposing(MemoryStore())
    austria = Publisher(store)
    italy = Publisher(store, snap=italy_snapshot())
    austria.publish()

    def italy_publishes_pointer_and_index():
        italy.publish()
        assert publish_index(store, lambda year: schedule_2026()) == "published"

    # Austria's run has read the index and listed the pointers (one session);
    # Italy's whole publication happens just before Austria's index write.
    store.before_put[layout.index_key()] = italy_publishes_pointer_and_index

    result = publish_index(store, lambda year: schedule_2026())

    index = json.loads(store.get(layout.index_key()).data)
    assert published_keys(index) == {(8, "R"): AUSTRIA, (14, "R"): ITALY}
    # Austria lost the write, derived again, and found nothing left to change.
    assert result == "current"


def test_a_session_published_right_after_the_pointers_were_listed_is_not_dropped():
    """The interleaving that a list-then-read order would lose (rule 2): the
    index this run read is no longer the one in the store, so its write fails."""
    store = Interposing(MemoryStore())
    Publisher(store).publish()
    publish_index(store, lambda year: schedule_2026())
    italy = Publisher(store, snap=italy_snapshot())

    def italy_publishes_pointer_and_index():
        italy.publish()
        publish_index(store, lambda year: schedule_2026())

    store.after_list[layout.pointers_prefix()] = italy_publishes_pointer_and_index

    publish_index(store, lambda year: schedule_2026(), seasons=[2026])

    index = json.loads(store.get(layout.index_key()).data)
    assert published_keys(index) == {(8, "R"): AUSTRIA, (14, "R"): ITALY}


def test_an_invalid_pointer_stops_the_index_from_being_derived_without_it():
    store = MemoryStore()
    Publisher(store).publish()
    store.put(layout.pointer_key(ITALY), b"{}")

    with pytest.raises(PointerError):
        publish_index(store, lambda year: schedule_2026())
    assert store.get(layout.index_key()) is None
