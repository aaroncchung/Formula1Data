"""The cases the tenth review of this code found (GPT-6.1 Sol, 2026-10-06, at e3ad833).

It was asked to say which need a fault outside this code and which do not.
One does not: two runs noting the same failed fetch could leave the older
note. The rest need an object in the archive that nothing here wrote, or a
machine whose clock is wrong. They are closed all the same, and where they
could be closed as a class they are: a marker or a correction is read only if
every part of it is what it should be.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from f1data import layout
from f1data.archive import (
    dump_json,
    failed_fetches,
    list_snapshots,
    note_failed_fetch,
    partial_publication_time,
    plausible_fetch_time,
    write_snapshot,
)
from f1data.build import BuildError, Builder
from f1data.coverage import is_measurement
from f1data.identity import archived_start_time
from f1data.policy import RETRY_INTERVAL, RETRY_WINDOW
from f1data.publish import Hold, publish_session, read_pointer
from f1data.store import MemoryStore
from tests.building import FIRST_FETCH, Archive
from tests.fakes import make_session, measure
from tests.test_archive import fetched_session
from tests.test_fifth_review import WINDOW_CLOSED, correction_key
from tests.test_fourth_review import without_positions_for_one_driver
from tests.test_publish import AUSTRIA, Interposing, snapshot
from tests.test_second_review import fetched_at, planned

EVERYONE = {"1": 10, "2": 10, "3": 10}
ITALYS_START = "2026-09-06T13:00:00Z"


# --- R10-1: the feeds say which meeting they are of --------------------------------


class TwoRaces(Archive):
    """Jolpica with a result for Austria, and another for Italy, dated as each race was."""

    def fetch_classification(self, fastf1, year, round_number, session_type):
        classification = super().fetch_classification(fastf1, year, round_number, session_type)
        if round_number == self.austria_round + 6:
            return replace(classification, fingerprint="sha256:italy", race_date=date(2026, 9, 6))
        return classification


def test_a_marker_with_another_races_start_does_not_send_the_build_to_that_race(tmp_path, monkeypatch):
    """Only the start time in Austria's marker is changed, to Italy's. The key,
    the place it is filed, the feeds and their checksums are Austria's. The
    start time is how the calendar entry is found, and the entry is how the
    result is found: Italy's result used to be merged into Austria's timing."""
    world = TwoRaces(monkeypatch, EVERYONE)
    fetched = fetched_session(tmp_path)
    fetched = replace(fetched, identity=replace(fetched.identity, start_time_utc=ITALYS_START))
    written = write_snapshot(world.store, fetched, now=FIRST_FETCH + timedelta(days=80))
    world.feeds[written.snapshot_id] = make_session()
    builder = Builder(world.store, fastf1=None, now=lambda: FIRST_FETCH + timedelta(days=90))

    inputs = builder.gather(AUSTRIA)
    assert inputs.context.scheduled.meeting_name == "Italian Grand Prix"
    assert inputs.classification_fingerprint == "sha256:italy"

    with pytest.raises(BuildError, match="started at 2026-06-28T13:00:00Z, not the R of Italian Grand Prix"):
        publish_session(world.store, AUSTRIA, builder.gather, builder.build)
    assert read_pointer(world.store, AUSTRIA) == (None, None)
    assert world.built == []


def test_the_archive_says_when_its_session_started():
    session = SimpleNamespace(
        session_info={"StartDate": datetime(2025, 4, 6, 14, 0), "GmtOffset": timedelta(hours=9)}
    )

    assert archived_start_time(session).isoformat() == "2025-04-06T05:00:00+00:00"
    assert archived_start_time(SimpleNamespace(session_info={"StartDate": "soon"})) is None
    assert archived_start_time(SimpleNamespace()) is None


def test_feeds_with_no_start_of_their_own_are_not_tied_to_a_calendar_entry(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    written = world.snapshot(tmp_path)
    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)
    inputs = builder.gather(AUSTRIA)
    event = inputs.context.scheduled.event
    get_session = event.get_session

    def without_a_start(name):
        loaded = get_session(name)
        del loaded.session_info["StartDate"]
        return loaded

    event.get_session = without_a_start

    with pytest.raises(BuildError, match="no stated time"):
        builder.build(inputs)
    assert written.snapshot_id == inputs.snapshot.snapshot_id


# --- R10-2: every figure of a measurement is a figure ------------------------------


def with_driver(coverage: dict, code: str, **figures) -> dict:
    drivers = {name: dict(driver) for name, driver in coverage["drivers"].items()}
    drivers[code].update(figures)
    return {**coverage, "drivers": drivers}


@pytest.mark.parametrize(
    "broken",
    [
        {"classified_laps": 0, "car_laps": "broken"},
        {"classified_laps": 0, "position_laps": 4.5},
        {"timing_laps": -1},
        {"tyre_laps": True},
        {"number": None},
        {"in_driver_list": "yes"},
    ],
)
def test_a_figure_nothing_reads_today_still_has_to_be_a_figure(broken, tmp_path):
    """A driver with no laps to account for has their counts skipped by
    everything that judges a measurement. On the day a result gives that
    driver laps the counts are read, in the fetch planner, for every session."""
    good = measure(make_session())
    bad = with_driver(good, "CCC", **broken)

    assert is_measurement(good)
    assert not is_measurement(bad)

    store = MemoryStore()
    kept = write_snapshot(store, fetched_session(tmp_path / "good"), now=FIRST_FETCH)
    spoiled = fetched_session(tmp_path / "bad")
    write_snapshot(store, replace(spoiled, coverage=bad), now=FIRST_FETCH + RETRY_INTERVAL)
    assert list_snapshots(store) == [kept]
    judged = [item.judged_against({"1": 10, "2": 10, "3": 10}) for item in list_snapshots(store)]
    assert planned(judged, FIRST_FETCH + RETRY_WINDOW) == []


@pytest.mark.parametrize(
    "not_a_measurement",
    [None, [], {"feeds": {}, "drivers": {}}, {"session_type": "R", "feeds": {"position": "yes"}, "drivers": {}},
     {"session_type": "R", "feeds": {}, "drivers": {"AAA": []}},
     {"session_type": "R", "feeds": {}, "drivers": {}, "total_laps": "many"},
     {"session_type": "R", "feeds": {}, "drivers": {}, "session_ended": 1}],
)
def test_what_is_not_a_measurement(not_a_measurement):
    assert not is_measurement(not_a_measurement)


def test_a_record_from_before_a_figure_was_counted_is_still_a_measurement():
    old = measure(make_session())
    for key in ("pit_stops_in_timing", "pit_stops_in_series", "circuit_corners"):
        del old[key]
    for driver in old["drivers"].values():
        del driver["tyre_age_laps"]
        driver["classified_laps"] = None

    assert is_measurement({**old, "measurement_version": 1})


# --- R10-4 and R10-5: anything unreadable in a marker or a correction ---------------


@pytest.mark.parametrize(
    "spoil",
    [
        lambda marker: {**marker, "fetched_at": "broken"},
        lambda marker: {**marker, "fetched_at": None},
        lambda marker: {**marker, "identity": {**marker["identity"], "start_time_utc": "sometime"}},
        lambda marker: {**marker, "identity": {**marker["identity"], "session_type": "Race"}},
        lambda marker: {**marker, "identity": {**marker["identity"], "archive_path": None}},
        lambda marker: {**marker, "identity": {**marker["identity"], "year": "2026"}},
        lambda marker: {**marker, "objects": {"fastf1-cache.tar.gz": "here"}},
        lambda marker: {**marker, "attempts": 1e309},
    ],
)
def test_a_marker_with_anything_unreadable_in_it_is_passed_over(spoil, tmp_path):
    """One such marker used to raise out of the listing, which both stages
    read before they start on any session."""
    store = MemoryStore()
    kept = write_snapshot(store, fetched_session(tmp_path / "good"), now=FIRST_FETCH)
    other = write_snapshot(store, fetched_session(tmp_path / "other"), now=FIRST_FETCH + RETRY_INTERVAL)
    key = f"{layout.snapshot_prefix(AUSTRIA, other.snapshot_id)}{layout.SNAPSHOT_MARKER}"
    store.put(key, dump_json(spoil(other.to_json())))

    assert list_snapshots(store) == [kept]
    assert planned(list_snapshots(store), FIRST_FETCH + RETRY_WINDOW) == []


@pytest.mark.parametrize("version", [1e309, -1, 2.5, True, "6", None])
def test_a_correction_whose_version_is_no_version_has_no_say(version, tmp_path):
    store = MemoryStore()
    written = write_snapshot(store, fetched_session(tmp_path), now=FIRST_FETCH)
    short = measure(without_positions_for_one_driver(10))
    for payload in (
        {"pipeline_version": version, "coverage": short},
        {"pipeline_version": layout.PIPELINE_VERSION, "coverage": {**short, "measurement_version": version}},
    ):
        text = dump_json({"schema_version": 1, "snapshot_id": written.snapshot_id, **payload})
        store.put(correction_key(written), text.replace(b"Infinity", b"1e309"))

        (listed,) = list_snapshots(store)

        assert (listed.corrected_by, listed.coverage) == (None, written.coverage)


# --- R10-6: a session cannot have been fetched before it started -------------------


def test_a_fetch_stamped_before_its_session_does_not_close_the_retry_window(tmp_path, monkeypatch):
    """A machine whose clock is a year slow stamps a short session's fetch
    with a time before the race was run. The 48 hours used to be over at once,
    for that fetch and for every one after it."""
    now = FIRST_FETCH + timedelta(hours=1)
    damaged = make_session()
    del damaged.pos_data["1"]
    stamped_early = snapshot(snapshot_id=fetched_at(FIRST_FETCH - timedelta(days=365)), session=damaged)
    fresh = snapshot(snapshot_id=fetched_at(FIRST_FETCH), session=damaged)

    assert plausible_fetch_time(stamped_early, now) is None
    assert plausible_fetch_time(fresh, now) == FIRST_FETCH
    assert partial_publication_time([stamped_early, fresh], now=now) == FIRST_FETCH + RETRY_WINDOW
    assert planned([stamped_early, fresh], FIRST_FETCH + RETRY_INTERVAL) == [8]
    assert planned([stamped_early, fresh], FIRST_FETCH + RETRY_INTERVAL - timedelta(hours=1)) == []

    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path / "early", recorded=damaged, moment=FIRST_FETCH - timedelta(days=365))
    world.snapshot(tmp_path / "fresh", recorded=damaged)
    held = Builder(world.store, fastf1=None, now=lambda: now).gather(AUSTRIA)
    assert isinstance(held, Hold)


# --- R10-3: the later of two notes of a failed fetch is the one kept ---------------


def test_an_older_note_of_a_failed_fetch_does_not_replace_a_newer_one():
    """Two runs fail the same session two seconds apart, and the one that
    failed first finishes its write last."""
    store = Interposing(MemoryStore())
    entry = (2026, "R", "2026-05-03T13:00:00Z")
    key = layout.attempt_key(*entry)
    at = FIRST_FETCH

    def the_later_failure_is_noted_first():
        note_failed_fetch(store, *entry, "FetchError: later", at + timedelta(seconds=2))

    store.before_put[key] = the_later_failure_is_noted_first
    note_failed_fetch(store, *entry, "FetchError: earlier", at)

    assert failed_fetches(store, at + timedelta(minutes=1)) == {key: at + timedelta(seconds=2)}

    # A later failure replaces it, and a note that cannot be read is replaced too.
    note_failed_fetch(store, *entry, "FetchError: again", at + timedelta(hours=3))
    assert failed_fetches(store, at + timedelta(hours=4)) == {key: at + timedelta(hours=3)}
    store.put(key, b"not a note")
    note_failed_fetch(store, *entry, "FetchError: once more", at + timedelta(hours=6))
    assert failed_fetches(store, at + timedelta(hours=7)) == {key: at + timedelta(hours=6)}


def test_a_note_stamped_in_the_future_does_not_stop_later_failures_being_noted():
    store = MemoryStore()
    entry = (2026, "R", "2026-05-03T13:00:00Z")
    note_failed_fetch(store, *entry, "FetchError", FIRST_FETCH + timedelta(days=30))

    note_failed_fetch(store, *entry, "FetchError", FIRST_FETCH)

    assert failed_fetches(store, FIRST_FETCH + timedelta(minutes=1)) == {
        layout.attempt_key(*entry): FIRST_FETCH
    }
