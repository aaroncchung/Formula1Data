"""The cases a Claude review of pull request 11 found in building and publishing, 2026-10-17, at 5190b36.

An empty answer from Jolpica, after the retry window, had a session built
without its result: the order on track was published in place of the
official result, and the pointer still said complete, since the snapshots
kept the laps classified on the day they were fetched. On an old session's
quiet days the pointer with no result was then taken as settled. A session
published with a result now keeps it, and one published without a result is
partial for want of it and is asked about on every run.

The index was not derived, nor the standings published, when the calendar of
any one season would not load, as next year's will not on the first of
January. A pointer could name its own generation as the one before it.
Nothing held what a build publishes to the pipeline version: that test is in
tests/test_layout.py. And nothing removed a generation no page reads any
more: `prune` does, by rules that keep whatever a page may still be reading.

A pointer named the drivers a session is short of as the fetch's record
did, by car number where F1's driver list had not arrived, where coverage.json
names them by the generation's codes. And a value that is not a number reached
a published lap as -9223372036854775808, or as gear 0, DRS 0 or the brake off.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from f1data import cli, layout
from f1data.archive import Snapshot, dump_json
from f1data.artifacts import build_artifacts
from f1data.build import Builder
from f1data.classification import ClassificationMissing
from f1data.coverage import CLASSIFICATION_BAR, apply_classification, measure_coverage
from f1data.normalize import SessionDataError
from f1data.policy import CLASSIFICATION_RECHECK_WINDOW
from f1data.prune import PruneRefused, plan_prune, remove_generations
from f1data.publish import (
    CalendarUnavailable,
    Inputs,
    publish_index,
    publish_session,
    read_pointer,
    upload_generation,
)
from f1data.store import DirectoryStore, MemoryStore
from tests import race, sample_bucket
from tests.building import Archive
from tests.fakes import make_session
from tests.test_build_inputs import a_quiet_day, a_recheck_day
from tests.test_fifth_review import EVERYONE, WINDOW_CLOSED
from tests.test_publish import AUSTRIA, Publisher, identity, pointer_of


def jolpica_has_nothing(*args, **kwargs):
    raise ClassificationMissing("Jolpica has no classification for 2026 round 8 R")


def publish(world: Archive, moment):
    builder = Builder(world.store, None, now=lambda: moment)
    return publish_session(world.store, AUSTRIA, builder.gather, builder.build)


# --- 1: an empty answer from Jolpica --------------------------------------------


def test_an_empty_answer_about_a_session_published_with_its_result_leaves_the_result_published(
    tmp_path, monkeypatch
):
    """The finding. The snapshot recorded the laps classified at fetch time,
    so built with no result it met every bar."""
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path, make_session(), moment=WINDOW_CLOSED)
    later = WINDOW_CLOSED + timedelta(days=3)
    assert publish(world, later).action == "published"
    before = read_pointer(world.store, AUSTRIA)[0]
    assert before.classification_fingerprint is not None and before.complete

    monkeypatch.setattr("f1data.build.fetch_classification", jolpica_has_nothing)
    outcome = publish(world, later + timedelta(hours=6))

    assert outcome.action == "waiting"
    assert "published with a result, which is kept until Jolpica has one again" in outcome.reason
    assert read_pointer(world.store, AUSTRIA)[0] == before
    assert len(world.built) == 1


def test_on_an_old_sessions_recheck_day_an_empty_answer_changes_nothing_either(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path, make_session(), moment=WINDOW_CLOSED)
    assert publish(world, WINDOW_CLOSED + timedelta(days=3)).action == "published"
    before = read_pointer(world.store, AUSTRIA)[0]

    official = world.fetch_classification
    monkeypatch.setattr("f1data.build.fetch_classification", jolpica_has_nothing)
    recheck = a_recheck_day(WINDOW_CLOSED + timedelta(days=40))
    assert publish(world, recheck).action == "waiting"
    monkeypatch.setattr("f1data.build.fetch_classification", official)
    assert publish(world, a_quiet_day(recheck + timedelta(days=2))).action == "current"

    assert read_pointer(world.store, AUSTRIA)[0] == before


def test_a_session_that_never_had_a_result_is_published_as_partial_for_want_of_one(tmp_path, monkeypatch):
    """What the comment in the build always said. Every driver is short of
    the classification, whatever the snapshot recorded of it."""
    world = Archive(monkeypatch, EVERYONE)
    snapshot = world.snapshot(tmp_path, make_session(), moment=WINDOW_CLOSED - timedelta(days=2))
    assert snapshot.complete
    monkeypatch.setattr("f1data.build.fetch_classification", jolpica_has_nothing)

    outcome = publish(world, WINDOW_CLOSED)

    assert outcome.action == "published"
    pointer = read_pointer(world.store, AUSTRIA)[0]
    assert pointer.classification_fingerprint is None and not pointer.complete
    assert {(item["bar"], item["driver"]) for item in pointer.shortfalls} == {
        (CLASSIFICATION_BAR, code) for code in ("AAA", "BBB", "CCC")
    }
    # The record a pointer keeps is of the feeds, which have not changed.
    assert pointer.record == snapshot.record_fingerprint


def test_a_session_published_without_a_result_is_asked_about_on_its_quiet_days(tmp_path, monkeypatch):
    """Otherwise an old session published with no result would be taken as
    settled for twenty-eight days in every thirty."""
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path, make_session(), moment=WINDOW_CLOSED - timedelta(days=2))
    official = world.fetch_classification
    monkeypatch.setattr("f1data.build.fetch_classification", jolpica_has_nothing)
    assert publish(world, WINDOW_CLOSED).action == "published"
    asked = len(world.classification_requests)

    monkeypatch.setattr("f1data.build.fetch_classification", official)
    quiet = a_quiet_day(WINDOW_CLOSED + CLASSIFICATION_RECHECK_WINDOW + timedelta(days=5))
    outcome = publish(world, quiet)

    assert len(world.classification_requests) == asked + 1
    assert (outcome.action, outcome.reason) == ("published", "the classification changed")
    pointer = read_pointer(world.store, AUSTRIA)[0]
    assert pointer.classification_fingerprint is not None and pointer.complete
    # Once it has one, its quiet days are quiet again.
    assert publish(world, a_quiet_day(quiet + timedelta(days=1))).action == "current"
    assert len(world.classification_requests) == asked + 1


# --- 2: a season whose calendar will not load ---------------------------------------

NO_SCHEDULE = ValueError("Failed to load any schedule data.")


def calendars(*missing: int):
    """FastF1's schedule for the sample's season, and its error for any year in ``missing``."""

    def load(year, **_):
        if year in missing:
            raise NO_SCHEDULE
        return sample_bucket.season() if year == sample_bucket.IDENTITY.year else []

    return load


def test_next_years_calendar_not_being_out_leaves_it_out_of_the_index(caplog):
    """The finding. The workflow asks for this year's season, and on the first
    of January FastF1 has no calendar for it."""
    store = MemoryStore()
    sample_bucket.write_sample(store)
    before = store.get(layout.index_key()).data

    with caplog.at_level(logging.WARNING, logger="f1data.publish"):
        assert publish_index(store, calendars(2027), seasons=[2027]) == "current"

    assert store.get(layout.index_key()).data == before
    assert "The calendar of 2027 did not load, and nothing of 2027 is published" in caplog.text


def test_a_calendar_that_will_not_load_for_a_season_with_sessions_published_stops_the_index():
    store = MemoryStore()
    sample_bucket.write_sample(store)
    before = store.get(layout.index_key()).data

    with pytest.raises(CalendarUnavailable, match="The calendar of 2026 did not load, and sessions of 2026"):
        publish_index(store, calendars(2026), seasons=[2027])

    assert store.get(layout.index_key()).data == before


def build_args(store_path, season):
    return argparse.Namespace(
        store=str(store_path), session_key=None, shard=None, season=season, recheck=False
    )


@pytest.fixture
def jolpica_standings(monkeypatch):
    """Jolpica's standings, a point more for the winner than the sample has."""
    asked = []

    def fetch(fastf1, year):
        asked.append(year)
        if year != sample_bucket.IDENTITY.year:
            return None
        standings = sample_bucket.standings()
        standings["drivers"][0]["points"] += 1
        return standings

    monkeypatch.setattr("f1data.build.fetch_standings", fetch)
    return asked


def test_a_build_on_new_years_day_derives_the_index_and_publishes_the_standings(
    tmp_path, monkeypatch, capsys, jolpica_standings
):
    sample_bucket.write_sample(DirectoryStore(tmp_path))
    monkeypatch.setattr("f1data.build.load_schedule", lambda fastf1, year, **_: calendars(2027)(year))

    assert cli.run_build(build_args(tmp_path, [2027])) == 0

    out = capsys.readouterr().out
    assert f"index ({layout.index_key()}): current" in out
    assert f"standings 2026 ({layout.standings_key(2026)}): published" in out
    assert jolpica_standings == [2026, 2027]


def test_the_standings_are_published_when_the_index_cannot_be_derived_and_the_build_fails(
    tmp_path, monkeypatch, capsys, jolpica_standings
):
    store = DirectoryStore(tmp_path)
    sample_bucket.write_sample(store)
    before = store.get(layout.index_key()).data
    monkeypatch.setattr("f1data.build.load_schedule", lambda fastf1, year, **_: calendars(2026)(year))

    assert cli.run_build(build_args(tmp_path, [2026])) == 1

    out = capsys.readouterr().out
    assert (
        f"index ({layout.index_key()}): FAILED: CalendarUnavailable: The calendar of 2026 did not load" in out
    )
    assert f"standings 2026 ({layout.standings_key(2026)}): published" in out
    assert store.get(layout.index_key()).data == before


# --- 4: a pointer never names its own generation as the one before ------------------

OTHER_FILES = {"summary.json": b'{"meeting":"Austrian Grand Prix","laps":71}\n', "laps.json": b"[]\n"}


def test_a_rebuild_that_lands_on_the_published_generation_keeps_the_one_before():
    """The finding: an input moved and the files did not, so the build is the
    generation already published. A pruner that keeps a pointer's generation
    and the one before would have kept one generation of the two."""
    store = MemoryStore()
    first = Publisher(store).publish().generation
    second = Publisher(store, fingerprint="sha256:second", files=OTHER_FILES).publish().generation
    assert pointer_of(store).previous_generation == first

    outcome = Publisher(store, fingerprint="sha256:after-a-penalty", files=OTHER_FILES).publish()

    assert (outcome.action, outcome.reason, outcome.generation) == (
        "published",
        "the classification changed",
        second,
    )
    assert (pointer_of(store).generation, pointer_of(store).previous_generation) == (second, first)


def test_a_first_publication_built_again_to_the_same_files_has_none_before_it():
    store = MemoryStore()
    first = Publisher(store).publish().generation

    Publisher(store, fingerprint="sha256:after-a-penalty").publish()

    assert (pointer_of(store).generation, pointer_of(store).previous_generation) == (first, None)


def test_a_pointer_written_naming_itself_as_the_one_before_is_put_right():
    store = MemoryStore()
    first = Publisher(store).publish().generation
    payload = json.loads(store.get(layout.pointer_key(AUSTRIA)).data)
    store.put(layout.pointer_key(AUSTRIA), dump_json({**payload, "previous_generation": first}))

    Publisher(store, fingerprint="sha256:after-a-penalty").publish()

    assert pointer_of(store).previous_generation is None


# --- 5: prune -----------------------------------------------------------------------

DAY_0 = datetime(2026, 7, 1, tzinfo=timezone.utc)
NOW = DAY_0 + timedelta(days=60)


def files(laps: int) -> dict[str, bytes]:
    return {"summary.json": f'{{"laps":{laps}}}\n'.encode(), "telemetry/AAA.json": b"[]\n"}


def publish_on(store: MemoryStore, day: int, laps: int) -> str:
    """Publish files of their own on that day."""
    store.clock = lambda: DAY_0 + timedelta(days=day)
    return Publisher(store, files=files(laps), fingerprint=f"sha256:{laps}").publish().generation


def upload_on(store: MemoryStore, day: int, laps: int) -> str:
    """Upload a generation no pointer names yet, as a build does before it writes the pointer."""
    store.clock = lambda: DAY_0 + timedelta(days=day)
    generation, _ = upload_generation(store, identity(), files(laps))
    return generation


NEVER_REMOVED = {
    layout.index_key(): b"{}\n",
    layout.standings_key(2026): b"{}\n",
    "archive/sessions/11315/20260628T180000Z-aaaaaaaa/snapshot.json": b"{}\n",
    "v2/pointers/latest.json": b"{}\n",
    # Another format's generations, and keys under this one's that are not
    # where a generation's files go.
    f"v1/generations/11315/{'b' * 64}/summary.json": b"{}\n",
    "v2/generations/11315/not-a-generation/summary.json": b"{}\n",
    f"v2/generations/011315/{'c' * 64}/summary.json": b"{}\n",
}


@pytest.fixture
def bucket():
    """Four generations of one session, all but one old: one nothing names, the
    two its pointer names, and one uploaded yesterday that nothing names yet."""
    store = MemoryStore(clock=lambda: DAY_0)
    for key, data in NEVER_REMOVED.items():
        store.put(key, data)
    named = {
        "oldest": publish_on(store, 0, 70),
        "before": publish_on(store, 10, 71),
        "current": publish_on(store, 20, 72),
        "in flight": upload_on(store, 59, 73),
    }
    return store, named


def keys(store) -> set[str]:
    return {item.key for item in store.list("")}


def of(store, generation: str) -> set[str]:
    return {item.key for item in store.list(layout.generation_prefix(AUSTRIA, generation))}


def test_only_a_generation_no_pointer_names_and_nothing_wrote_for_thirty_days_is_removable(bucket):
    store, named = bucket

    plan = plan_prune(store, NOW)

    assert [generation.generation for generation in plan.removable] == [named["oldest"]]
    assert {generation.generation: why for generation, why in plan.kept} == {
        named["current"]: "named by its pointer",
        named["before"]: "named by its pointer as the one before",
        named["in flight"]: "written in the last 30 days",
    }
    assert sorted(item.key for item in plan.stray) == sorted(
        key for key in NEVER_REMOVED if key.startswith(layout.generations_prefix())
    )


def test_prune_removes_that_generation_and_nothing_else(bucket):
    store, named = bucket
    oldest = of(store, named["oldest"])
    everything = keys(store)

    removed = remove_generations(store, plan_prune(store, NOW))

    assert [generation.generation for generation in removed.generations] == [named["oldest"]]
    assert (removed.left, removed.attention, removed.stopped) == ([], [], None)
    assert keys(store) == everything - oldest
    for key, data in NEVER_REMOVED.items():
        assert store.get(key).data == data


def test_a_longer_retention_keeps_it_too(bucket):
    store, _ = bucket

    assert plan_prune(store, NOW, keep_for=timedelta(days=61)).removable == []


def test_nothing_is_removed_when_any_pointer_cannot_be_read(bucket):
    """Which generations that pointer keeps is not known."""
    store, _ = bucket
    store.put(layout.pointer_key(99999), b"not json")

    with pytest.raises(PruneRefused, match="Pointer for session 99999 is not JSON"):
        plan_prune(store, NOW)


def test_a_pointer_that_names_something_else_as_the_one_before_stops_it_too(bucket):
    store, _ = bucket
    payload = json.loads(store.get(layout.pointer_key(AUSTRIA)).data)
    store.put(layout.pointer_key(AUSTRIA), dump_json({**payload, "previous_generation": "the last one"}))

    with pytest.raises(PruneRefused, match="names something that is not a generation as the one before"):
        plan_prune(store, NOW)


def test_the_generation_of_a_pointer_the_build_passes_over_is_kept(bucket):
    """A pointer to a practice session, which a version before the rule could
    write, is passed over wherever the published sessions are counted. It is
    still a pointer, and a page may still be reading what it names."""
    store, named = bucket
    payload = json.loads(store.get(layout.pointer_key(AUSTRIA)).data)
    practice = {**payload["identity"], "session_type": "FP1", "session_name": "Practice 1"}
    manifest = {**payload["manifest"], "sha256": named["oldest"]}
    store.put(
        layout.pointer_key(AUSTRIA),
        dump_json({**payload, "identity": practice, "generation": named["oldest"], "manifest": manifest}),
    )

    kept = {generation.generation: why for generation, why in plan_prune(store, NOW).kept}

    assert kept[named["oldest"]] == "named by its pointer"


def test_a_generation_its_pointer_names_by_the_time_it_is_removed_is_left(bucket):
    """A build that builds the same files again finds them in place and points
    at them, after the plan found them removable."""
    store, named = bucket
    plan = plan_prune(store, NOW)
    payload = json.loads(store.get(layout.pointer_key(AUSTRIA)).data)
    store.put(layout.pointer_key(AUSTRIA), dump_json({**payload, "previous_generation": named["oldest"]}))
    oldest = of(store, named["oldest"])

    removed = remove_generations(store, plan)

    assert [generation.generation for generation in removed.left] == [named["oldest"]]
    assert removed.generations == []
    assert of(store, named["oldest"]) == oldest


class PointsBack(MemoryStore):
    """A store in which a build points the session at a generation while its manifest is removed."""

    def __init__(self, store: MemoryStore, generation: str) -> None:
        super().__init__(clock=store.clock)
        self._objects, self._modified = dict(store._objects), dict(store._modified)
        self._generation = generation

    def delete(self, key: str) -> None:
        if key == f"{layout.generation_prefix(AUSTRIA, self._generation)}{layout.MANIFEST_NAME}":
            pointer = json.loads(self.get(layout.pointer_key(AUSTRIA)).data)
            pointer["previous_generation"] = self._generation
            self.put(layout.pointer_key(AUSTRIA), dump_json(pointer))
        super().delete(key)


def test_a_pointer_that_names_a_generation_only_once_it_is_being_removed_is_said(bucket):
    store, named = bucket
    plan = plan_prune(store, NOW)

    removed = remove_generations(PointsBack(store, named["oldest"]), plan)

    assert removed.attention == [
        f"the pointer of session {AUSTRIA} names generation {named['oldest']}, which was removed: "
        "a build pointed at it while this ran"
    ]


def test_the_manifest_goes_first(bucket):
    store, named = bucket
    order = []

    class Watched(MemoryStore):
        def delete(self, key):
            order.append(key)
            super().delete(key)

    watched = Watched()
    watched._objects, watched._modified = store._objects, store._modified
    oldest = of(store, named["oldest"])

    remove_generations(watched, plan_prune(watched, NOW))

    assert order[0] == f"{layout.generation_prefix(AUSTRIA, named['oldest'])}{layout.MANIFEST_NAME}"
    assert sorted(order) == sorted(oldest) and len(order) == 3


def test_the_command_says_what_it_would_remove_and_removes_it_only_when_told(tmp_path, capsys):
    """On a directory, whose files are as old as when each was written."""
    directory = tmp_path / "bucket"
    store = DirectoryStore(directory)
    oldest, _ = upload_generation(store, identity(), files(70))
    for path in (directory / "v2").rglob("*"):
        if path.is_file():
            os.utime(path, (DAY_0.timestamp(), DAY_0.timestamp()))
    Publisher(store, files=files(71)).publish()
    everything = keys(store)
    removable = of(store, oldest)
    size = sum(item.size for item in store.list(layout.generation_prefix(AUSTRIA, oldest)))

    with pytest.raises(SystemExit) as dry:
        cli.main(["prune", "--store", str(directory)])

    assert dry.value.code == 0
    out = capsys.readouterr().out
    assert "1 pointer(s) read." in out
    assert f"Would remove: 1 generation(s), 3 object(s), {size / 1024**2:,.1f} MB" in out
    assert f"session {AUSTRIA} generation {oldest[:12]}: 3 object(s)" in out
    assert "last written 2026-07-01T00:00:00Z" in out
    assert "Nothing removed: run again with --delete to remove these." in out
    assert keys(store) == everything

    with pytest.raises(SystemExit) as deleting:
        cli.main(["prune", "--store", str(directory), "--delete"])

    assert deleting.value.code == 0
    assert "Removed: 1 generation(s), 3 object(s)" in capsys.readouterr().out
    assert keys(store) == everything - removable
    # And the directories that held it, as a bucket has none.
    assert not (directory / "v2" / "generations" / str(AUSTRIA) / oldest).exists()


def test_the_command_removes_nothing_when_a_pointer_cannot_be_read(tmp_path, capsys):
    directory = tmp_path / "bucket"
    store = DirectoryStore(directory)
    Publisher(store).publish()
    store.put(layout.pointer_key(99999), b"not json")
    everything = keys(store)

    with pytest.raises(SystemExit) as refused:
        cli.main(["prune", "--store", str(directory), "--delete"])

    assert refused.value.code == 1
    assert "Nothing removed: Pointer for session 99999 is not JSON" in capsys.readouterr().out
    assert keys(store) == everything


@pytest.mark.parametrize("days", ["0", "-3", "half"])
def test_the_retention_is_a_whole_number_of_days_and_at_least_one(days, tmp_path):
    with pytest.raises(SystemExit) as refused:
        cli.main(["prune", "--store", str(tmp_path), "--keep-days", days])

    assert refused.value.code == 2


# --- 6: the pointer names a driver as the generation does ---------------------------


def test_a_pointer_names_the_drivers_it_is_short_of_by_the_generations_codes():
    """A record made before F1's driver list arrived names each driver by car
    number. coverage.json names them by the codes the rest of the generation
    uses, and the pointer named them by the record."""
    session, found, result = race.make_race(), race.extras(), race.classification()
    measured = apply_classification(measure_coverage(session, "R", found), result.laps_by_number)
    drivers = {str(driver["number"]): driver for driver in measured["drivers"].values()}
    by_number = {**measured, "drivers": drivers}
    files = build_artifacts(session, race.IDENTITY, result, found, by_number)
    snapshot = Snapshot(
        snapshot_id="20260628T180000Z-5a3b1e00",
        identity=race.IDENTITY,
        fetched_at="2026-06-28T18:00:00Z",
        coverage=by_number,
    )
    assert {shortfall.driver for shortfall in snapshot.shortfalls()} == {"1"}
    store = MemoryStore()

    publish_session(
        store,
        race.IDENTITY.session_key,
        lambda key, **_: Inputs(snapshot, result.fingerprint),
        lambda _: (files, None),
    )

    pointer = pointer_of(store, race.IDENTITY.session_key)
    built = json.loads(files["coverage.json"])
    assert {item["driver"] for item in pointer.shortfalls} == {"AAA"}
    assert (pointer.complete, pointer.shortfalls) == (built["complete"], built["shortfalls"])


# --- 7: a value that is not a number stops the build --------------------------------


def built_race(session) -> dict[str, bytes]:
    found = race.extras()
    measured = measure_coverage(session, "R", found)
    return build_artifacts(session, race.IDENTITY, race.classification(), found, measured)


def test_a_lap_with_no_engine_speed_stops_the_build():
    """It was published as -9223372036854775808 in every sample."""
    session = race.make_race()
    session.car_data["1"]["RPM"] = np.nan

    with pytest.raises(SessionDataError, match="engine speed has a sample that is not a number"):
        built_race(session)


@pytest.mark.parametrize(
    "channel, missing", [("nGear", np.nan), ("DRS", np.nan), ("Brake", None), ("nGear", "N")]
)
def test_a_sample_with_no_gear_drs_or_brake_stops_the_build(channel, missing):
    """They were published as gear 0, DRS 0 and the brake off."""
    session = race.make_race()
    feed = session.car_data["2"]
    feed[channel] = feed[channel].astype(object)
    feed.loc[3000, channel] = missing

    with pytest.raises(SessionDataError, match=f"Car 2's feed has a sample whose {channel} is not a number"):
        built_race(session)


def test_a_row_that_is_no_sample_may_have_nothing_in_it():
    """A row with no speed is left out of every lap, whatever else it lacks."""
    session = race.make_race()
    feed = session.car_data["2"]
    feed["nGear"] = feed["nGear"].astype(float)
    feed.loc[3000, ["Speed", "nGear"]] = np.nan

    assert "telemetry/BBB.json" in built_race(session)
