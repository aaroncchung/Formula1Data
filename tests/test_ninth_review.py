"""The cases the ninth review of this code found (GPT-6.1 Sol, 2026-10-06, at 1f0c88c).

Three are where the fixes of the round before stopped short: an identity
replaced whole when only its start time had to move, a correction checked for
its shape and not for whether it can be read, a disbelieved timestamp that
was still asked what F1 had answered last. The fourth is the starved fetch
batch once more, and this time the answer does not rest on a probe.
"""

from __future__ import annotations

import pathlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import requests

from f1data import cli as cli_module
from f1data import layout
from f1data.archive import dump_json, failed_fetches, list_snapshots, note_failed_fetch, write_snapshot
from f1data.build import Builder
from f1data.cli import main
from f1data.due import FetchPlan, least_recently_failed_first
from f1data.fetch import f1_is_answering
from f1data.policy import RETRY_INTERVAL, RETRY_WINDOW, SLOW_RETRY_INTERVAL
from f1data.publish import publish_session, read_pointer
from f1data.store import DirectoryStore, MemoryStore
from tests.building import FIRST_FETCH, Archive
from tests.fakes import make_session, measure
from tests.test_archive import ARCHIVE_PATH, fetched_session
from tests.test_eighth_review import MONDAY, Postponed
from tests.test_fifth_review import WINDOW_CLOSED, correction, correction_key
from tests.test_fourth_review import without_positions_for_one_driver
from tests.test_publish import AUSTRIA, snapshot
from tests.test_second_review import ONE_RACE, fetched_at, planned
from tests.test_seventh_review import AUSTRIA_ENTRY, CALENDAR, fetch_due

EVERYONE = {"1": 10, "2": 10, "3": 10}
MONDAY_PATH = "2026/2026-06-28_Austrian_Grand_Prix/2026-06-29_Race/"


# --- R9-1: a snapshot's feeds are where it filed them ------------------------------


def test_a_fetch_from_before_a_correction_is_loaded_from_where_it_was_filed(tmp_path, monkeypatch):
    """F1 moved the session's directory with its date. The fetch made since is
    the worse one, so the earlier is built: with the start the calendar now
    has, and from the path its own feeds are under."""
    world = Postponed(monkeypatch, EVERYONE)
    before = world.snapshot(tmp_path / "sunday")
    refetched = fetched_session(tmp_path / "monday", without_positions_for_one_driver(10))
    (refetched.cache_dir / ARCHIVE_PATH).rename(refetched.cache_dir / MONDAY_PATH)
    refetched = replace(
        refetched, identity=replace(refetched.identity, start_time_utc=MONDAY, archive_path=MONDAY_PATH)
    )
    since = write_snapshot(world.store, refetched, now=FIRST_FETCH + RETRY_INTERVAL)
    world.feeds[since.snapshot_id] = without_positions_for_one_driver(10)
    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)

    inputs = builder.gather(AUSTRIA)

    assert inputs.snapshot.snapshot_id == before.snapshot_id
    assert inputs.snapshot.identity.start_time_utc == MONDAY
    assert inputs.snapshot.identity.archive_path == ARCHIVE_PATH
    assert replace(inputs.snapshot.identity, start_time_utc=before.identity.start_time_utc) == before.identity

    assert publish_session(world.store, AUSTRIA, builder.gather, builder.build).action == "published"
    (built,) = world.built
    assert built.api_path == f"/static/{ARCHIVE_PATH}"
    assert read_pointer(world.store, AUSTRIA)[0].identity.start_time_utc == MONDAY


# --- R9-2: a record is a measurement only if it can be read as one -----------------


def with_a_broken_count(coverage: dict) -> dict:
    drivers = {code: dict(driver) for code, driver in coverage["drivers"].items()}
    drivers["AAA"]["timing_laps"] = "broken"
    return {**coverage, "drivers": drivers}


def test_a_correction_with_a_figure_that_cannot_be_read_is_not_a_correction(tmp_path, monkeypatch):
    """The right shape, the current measurement version, a claim to a newer
    pipeline version, and text where a lap count belongs. It was accepted,
    and the first thing to read the count raised: the fetch planner, before
    it had planned anything."""
    world = Archive(monkeypatch, EVERYONE)
    written = world.snapshot(tmp_path, recorded=make_session(), feeds=without_positions_for_one_driver(10))
    world.store.put(
        correction_key(written),
        dump_json(
            {
                "schema_version": 1,
                "snapshot_id": written.snapshot_id,
                "pipeline_version": layout.PIPELINE_VERSION + 1,
                "coverage": with_a_broken_count(written.coverage),
            }
        ),
    )

    (listed,) = list_snapshots(world.store)

    assert listed.corrected_by is None and listed.coverage == written.coverage
    assert planned([listed], FIRST_FETCH + RETRY_INTERVAL) == []
    # And the build, which finds the record wrong, is free to put it right.
    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)
    assert publish_session(world.store, AUSTRIA, builder.gather, builder.build).action == "published"
    assert correction(world.store, written)["pipeline_version"] == layout.PIPELINE_VERSION


def test_a_marker_whose_measurement_cannot_be_read_is_not_a_snapshot(tmp_path):
    store = MemoryStore()
    good = write_snapshot(store, fetched_session(tmp_path / "good"), now=FIRST_FETCH)
    bad = fetched_session(tmp_path / "bad")
    bad = replace(bad, coverage=with_a_broken_count(bad.coverage))
    write_snapshot(store, bad, now=FIRST_FETCH + RETRY_INTERVAL)
    for nonsense in ({"feeds": []}, {"drivers": [1, 2]}, {"drivers": {"AAA": "nobody"}}):
        worse = fetched_session(tmp_path / f"worse-{len(nonsense)}-{next(iter(nonsense))}-{id(nonsense)}")
        write_snapshot(store, replace(worse, coverage={**worse.coverage, **nonsense}), now=FIRST_FETCH)

    assert list_snapshots(store) == [good]
    assert planned(list_snapshots(store), FIRST_FETCH + SLOW_RETRY_INTERVAL) == []


# --- R9-3: a fetch stamped in the future is nobody's latest word --------------------


def test_what_f1_answered_last_is_taken_from_a_fetch_whose_stamp_can_be_believed():
    """Stamped far ahead by a clock that was wrong: no positions at all, with
    F1 refusing that one feed. Then a fetch by a good clock: positions for all
    but one driver. The first is not the latest, whatever its stamp says."""
    not_held = {"SessionInfo.jsonStream": 200, "Position.z.jsonStream": 403}
    nothing = make_session()
    nothing.pos_data = {}
    stamped_ahead = replace(
        snapshot(snapshot_id=fetched_at(FIRST_FETCH + timedelta(days=400)), session=nothing),
        feed_status=not_held,
    )
    believable = replace(
        snapshot(snapshot_id=fetched_at(FIRST_FETCH), session=without_positions_for_one_driver(10)),
        feed_status={"SessionInfo.jsonStream": 200, "Position.z.jsonStream": 200},
    )
    assert stamped_ahead.missing_only_what_f1_does_not_hold()
    weeks_later = FIRST_FETCH + 3 * SLOW_RETRY_INTERVAL

    assert planned([believable], weeks_later) == [8]
    assert planned([stamped_ahead, believable], weeks_later) == [8]


# --- R9-4: every session has its turn before any has a second ----------------------


def test_sessions_that_failed_wait_behind_the_ones_not_yet_tried():
    sixth, seventh, austria = (FetchPlan(entry, "not in the archive") for entry in CALENDAR)
    earlier, later = FIRST_FETCH, FIRST_FETCH + timedelta(hours=3)

    def order(failed_at):
        return [plan.session.round for plan in least_recently_failed_first([sixth, seventh, austria], failed_at)]

    assert order({}) == [6, 7, 8]
    assert order({sixth.attempt_key: later, seventh.attempt_key: earlier}) == [8, 7, 6]
    assert order({austria.attempt_key: earlier}) == [6, 7, 8]
    assert sixth.attempt_key == "archive/attempts/2026/20260503T130000Z-R.json"


def test_two_sessions_that_keep_failing_do_not_keep_the_rest_waiting_whatever_the_probe_says(
    tmp_path, monkeypatch, capsys
):
    """The first two sessions are in neither F1's archive nor its mirror, and
    the question "is F1 answering" comes back no, rightly or wrongly. The batch
    stops, as it should when nothing answers. It used to stop at the same two
    on every run after."""
    store = DirectoryStore(tmp_path / "store")

    first, output, _ = fetch_due(tmp_path, monkeypatch, capsys, f1_answers=False)
    assert first == [6, 7] and "Stopping" in output
    assert len(failed_fetches(store, datetime.now(timezone.utc))) == 2

    second, _, _ = fetch_due(tmp_path, monkeypatch, capsys, f1_answers=False)

    assert second == [8, 6, 7]
    assert [item.session_key for item in list_snapshots(store)] == [AUSTRIA]


def test_a_note_of_a_failed_fetch_that_cannot_be_believed_counts_for_nothing():
    store = MemoryStore()
    now = FIRST_FETCH
    note_failed_fetch(store, 2026, "R", "2026-05-03T13:00:00Z", "FetchError: nothing there", now - timedelta(hours=3))
    note_failed_fetch(store, 2026, "R", "2026-05-24T13:00:00Z", "FetchError: nothing there", now + timedelta(days=30))
    store.put(layout.attempt_key(2026, "S", "2026-05-23T10:00:00Z"), b"not a note")
    store.put(layout.attempt_key(2026, "Q", "2026-05-23T14:00:00Z"), dump_json({"failed_at": 7}))

    assert failed_fetches(store, now) == {
        "archive/attempts/2026/20260503T130000Z-R.json": now - timedelta(hours=3)
    }


def test_notes_of_failed_fetches_are_not_copied_between_stores(tmp_path, capsys):
    spool = DirectoryStore(tmp_path / "spool")
    write_snapshot(spool, fetched_session(tmp_path), now=FIRST_FETCH)
    note_failed_fetch(spool, 2026, "R", "2026-05-03T13:00:00Z", "FetchError", FIRST_FETCH)

    with pytest.raises(SystemExit):
        main(["copy-archive", "--from", str(tmp_path / "spool"), "--to", str(tmp_path / "bucket")])

    assert "Copied 5 object(s); 0 already there." in capsys.readouterr().out
    assert list(DirectoryStore(tmp_path / "bucket").list(layout.ATTEMPTS_PREFIX)) == []


def test_the_mirror_answering_is_f1_answering(monkeypatch):
    asked = []

    class Answer:
        def __init__(self, status):
            self.status_code = status

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

    def get(url, **kwargs):
        asked.append(url.split("/static/")[0])
        return Answer(200 if "mirror" in url else 403)

    monkeypatch.setattr(requests, "get", get)

    assert f1_is_answering((2026, 2025)) is True
    assert asked == ["https://livetiming.formula1.com"] * 2 + ["https://livetiming-mirror.fastf1.dev"]


# --- R9-5: a listing walks what its prefix names -----------------------------------


def test_a_directory_listing_does_not_walk_the_rest_of_the_store(tmp_path, monkeypatch):
    store = DirectoryStore(tmp_path)
    for key in ("archive/sessions/11315/a/snapshot.json", "archive/sessions/11361/b/snapshot.json",
                "v1/generations/11315/x/laps.json", "v1/pointers/11315.json", "v1/pointers/11361.json"):
        store.put(key, b"{}")
    walked = []
    rglob = pathlib.Path.rglob

    def watching(self, pattern):
        walked.append(self.relative_to(tmp_path).as_posix())
        return rglob(self, pattern)

    monkeypatch.setattr(pathlib.Path, "rglob", watching)

    def keys(prefix):
        return [item.key for item in store.list(prefix)]

    assert keys("archive/sessions/11315/") == ["archive/sessions/11315/a/snapshot.json"]
    assert keys("v1/pointers/113") == ["v1/pointers/11315.json", "v1/pointers/11361.json"]
    assert keys("v1/pointers/11361") == ["v1/pointers/11361.json"]
    assert keys("archive/sessions/99999/") == []
    assert len(keys("")) == 5 and len(keys("v1")) == 3
    assert walked == ["archive/sessions/11315", "v1/pointers", "v1/pointers", ".", "."]
