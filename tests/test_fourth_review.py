"""The cases the fourth review of this code found (GPT-6.1 Sol, 2026-10-06, at 0651e58).

Each test is one finding, reproduced, or something the fix for one rests on.
Three of the four come to the same thing: what a build is made from has to be
what was decided on. The calendar row, the result and the first-lap times are
gathered once and handed to the build, which can reach nothing else; and a
record that turns out not to describe its feeds is put right before anything
is decided from it.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from f1data import layout
from f1data.archive import dump_json, list_snapshots, write_remeasurement, write_snapshot
from f1data.build import Builder
from f1data.classification import ClassificationUnavailable, fetch_classification, fetch_classified_laps
from f1data.coverage import apply_classification, feed_figures
from f1data.extras import PIT_STOP_SERIES, circuit_corner_count, parse_pit_stop_series
from f1data.httplog import ForbiddenHostError, HttpRecorder
from f1data.policy import RETRY_INTERVAL, RETRY_WINDOW, SLOW_RETRY_INTERVAL
from f1data.publish import DecideAgain, Inputs, publish_session, read_pointer
from f1data.schedule import load_schedule
from f1data.store import MemoryStore
from tests.building import FIRST_FETCH, Archive
from tests.fakes import EXTRAS, LAP_SECONDS, make_session, measure
from tests.fakes import RACE_START as FEEDS_START
from tests.test_archive import fetched_session
from tests.test_build_inputs import SOON_AFTER
from tests.test_classification import Jolpica as JolpicaClient
from tests.test_classification import result_frame
from tests.test_publish import AUSTRIA, snapshot
from tests.test_second_review import fetched_at, planned

EVERYONE = {"1": 10, "2": 10, "3": 10}


# --- R1: a build is made from the calendar row that was gathered -----------------


def test_a_build_makes_its_session_from_the_calendar_row_it_gathered(tmp_path, monkeypatch):
    """Gathered with Austria at round 8. Before the build runs a race is
    inserted ahead of it, and round 8 is another race. Asked for "2026, round
    8", FastF1 would now hand back that other race's event."""
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path)
    builder = Builder(world.store, fastf1=None, now=lambda: SOON_AFTER)
    inputs = builder.gather(AUSTRIA)
    calendar_reads = len(world.schedule_reads)

    world.renumber()
    files, built_from = builder.build(inputs)

    (built,) = world.built
    assert built.event == {"RoundNumber": 8, "EventName": "Austrian Grand Prix"}
    assert files == {"summary.json": b"round 8"}
    assert inputs.context.scheduled.round == 8
    assert built_from is inputs.snapshot
    # The build read no calendar of its own.
    assert len(world.schedule_reads) == calendar_reads


def test_nothing_is_reachable_while_a_session_is_loaded_and_built(tmp_path, monkeypatch):
    """FastF1 asks Jolpica for the result, and for the first-lap times, on
    every load. A build that let it would be made partly of whatever Jolpica
    answered then, which is in no pointer."""
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path)
    builder = Builder(world.store, fastf1=None, now=lambda: SOON_AFTER)

    assert publish_session(world.store, AUSTRIA, builder.gather, builder.build).action == "published"

    (built,) = world.built
    assert built.refused == ["This stage must not contact jolpica.invalid"]


def test_a_recorder_can_refuse_every_host():
    with HttpRecorder(forbid_all=True) as guard:
        with pytest.raises(ForbiddenHostError):
            requests.Session().get("https://anything.invalid/x", timeout=5)

    assert guard.forbidden == ["https://anything.invalid/x"]


def test_a_change_in_the_calendar_row_builds_nothing_again(tmp_path, monkeypatch):
    """The old artifact writer read the round, the country, the dates and the
    weekend's other sessions out of the row, so the pointer recorded a checksum
    of all of it and a change anywhere built the session again. Format 2 takes
    nothing from the row: a session is described by F1's own session
    information, and the build records nothing of the calendar in the pointer."""
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path)
    builder = Builder(world.store, fastf1=None, now=lambda: SOON_AFTER)
    publish = lambda: publish_session(world.store, AUSTRIA, builder.gather, builder.build)
    assert publish().action == "published"
    assert read_pointer(world.store, AUSTRIA)[0].also is None
    assert publish().action == "current"

    world.row_fingerprint = "sha256:the-row-with-its-country-corrected"
    outcome = publish()

    assert outcome.action == "current"
    assert len(world.built) == 1


def test_a_build_reads_the_calendar_from_one_source(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path)

    Builder(world.store, fastf1=None, now=lambda: SOON_AFTER).gather(AUSTRIA)

    assert world.backends == ["fastf1"]


def calendar_frame(**changes) -> pd.DataFrame:
    row = {
        "RoundNumber": 8,
        "Country": "Austria",
        "Location": "Spielberg",
        "OfficialEventName": "FORMULA 1 AUSTRIAN GRAND PRIX 2026",
        "EventDate": pd.Timestamp("2026-06-28"),
        "EventName": "Austrian Grand Prix",
        "EventFormat": "conventional",
        "Session1": "Practice 1",
        "Session1DateUtc": pd.Timestamp("2026-06-26 11:30"),
        "Session4": "Qualifying",
        "Session4DateUtc": pd.Timestamp("2026-06-27 14:00"),
        "Session5": "Race",
        "Session5DateUtc": pd.Timestamp("2026-06-28 13:00"),
        "F1ApiSupport": True,
    }
    return pd.DataFrame([{**row, **changes}])


class ScheduleFile:
    """Stands in for ``fastf1``: its schedule and its cache switch."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.backends: list[str | None] = []
        self.Cache = SimpleNamespace(disabled=self._disabled)

    @contextmanager
    def _disabled(self):
        yield

    def get_event_schedule(self, year, include_testing=True, backend=None):
        self.backends.append(backend)
        return self.frame


def race_of(frame: pd.DataFrame, **kwargs):
    return next(entry for entry in load_schedule(ScheduleFile(frame), 2026, **kwargs) if entry.session_type == "R")


def test_a_calendar_entry_carries_its_row_and_a_checksum_of_all_of_it():
    race = race_of(calendar_frame())

    assert race.event["EventName"] == "Austrian Grand Prix" and race.event["Session1"] == "Practice 1"
    assert race.row_fingerprint.startswith("sha256:") and len(race.row_fingerprint) == 71
    assert race_of(calendar_frame()).row_fingerprint == race.row_fingerprint
    # Columns nothing here reads by name are in it too.
    for change in (
        {"Country": "Osterreich"},
        {"Session1DateUtc": pd.Timestamp("2026-06-26 12:30")},
        {"F1ApiSupport": False},
        {"RoundNumber": 9},
    ):
        assert race_of(calendar_frame(**change)).row_fingerprint != race.row_fingerprint, change
    # The row and its checksum are not what makes two entries the same entry.
    assert race_of(calendar_frame(Country="Osterreich")) != race
    assert replace(race, row_fingerprint=None) == replace(race_of(calendar_frame()), row_fingerprint=None)


def test_the_calendar_is_asked_of_the_source_named_and_of_any_when_none_is():
    pinned, unpinned = ScheduleFile(calendar_frame()), ScheduleFile(calendar_frame())

    load_schedule(pinned, 2026, fresh=True, backend="fastf1")
    load_schedule(unpinned, 2026)

    assert (pinned.backends, unpinned.backends) == (["fastf1"], [None])


# --- what a build takes from Jolpica is gathered, and is in the fingerprint -------


def results_with_ids() -> pd.DataFrame:
    frame = result_frame()
    frame["driverId"] = ["russell", "max_verstappen", "bottas"]
    return frame


def first_laps(**seconds) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "number": 1,
            "driverId": list(seconds),
            "position": range(1, len(seconds) + 1),
            "time": [pd.Timedelta(seconds=value) for value in seconds.values()],
        }
    )


def test_first_lap_times_are_fetched_with_the_result_and_are_in_its_fingerprint():
    """F1's timing gives no time for the first lap of a race. Jolpica does,
    hours after the race or days."""
    without = fetch_classification(JolpicaClient([results_with_ids()]), 2026, 8, "R")
    jolpica = JolpicaClient([results_with_ids()], first_laps=[first_laps(russell=78.505, max_verstappen=79.1)])

    with_times = fetch_classification(jolpica, 2026, 8, "R")

    assert without.first_lap_ms == {}
    assert with_times.first_lap_ms == {"3": 79100, "63": 78505}
    # Asked for the first lap only, and not from a cache.
    assert jolpica.lap_calls == [(2026, 8, 1, True)]
    assert with_times.rows == without.rows
    assert with_times.fingerprint != without.fingerprint
    corrected = fetch_classification(
        JolpicaClient([results_with_ids()], first_laps=[first_laps(russell=78.6, max_verstappen=79.1)]),
        2026,
        8,
        "R",
    )
    assert corrected.fingerprint != with_times.fingerprint


def test_a_sprint_has_no_first_lap_times_to_ask_for():
    jolpica = JolpicaClient([results_with_ids()])

    assert fetch_classification(jolpica, 2026, 9, "S").first_lap_ms == {}
    assert jolpica.lap_calls == []


def test_the_fetch_planner_asks_for_classified_laps_and_nothing_more():
    """It asks about a session on every run, and Jolpica counts requests."""
    jolpica = JolpicaClient([results_with_ids()], first_laps=[first_laps(russell=78.505)])

    assert fetch_classified_laps(jolpica, 2026, 8, "R") == {"63": 71, "3": 71, "77": 2}
    assert (jolpica.calls, jolpica.lap_calls) == ([("race", 2026, 8)], [])
    assert jolpica.cache_disabled_during_calls == [True]


def test_first_lap_times_that_cannot_be_fetched_leave_nothing_known():
    """Publishing with the result and without them would be a build that
    depends on which request Jolpica happened to refuse."""
    jolpica = JolpicaClient([results_with_ids()], first_laps=[RuntimeError("429 Too Many Requests")] * 3)

    with pytest.raises(ClassificationUnavailable, match="first-lap times for 2026 round 8"):
        fetch_classification(jolpica, 2026, 8, "R", sleep=lambda seconds: None)


def test_the_first_lap_time_is_put_into_the_session_a_build_loaded(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE, first_lap_ms={"1": 91500, "2": 92250})
    feeds = make_session()
    feeds.laps["LapTime"] = pd.Series(pd.NaT, index=feeds.laps.index, dtype="timedelta64[ns]")
    world.snapshot(tmp_path, recorded=make_session(), feeds=feeds)
    builder = Builder(world.store, fastf1=None, now=lambda: SOON_AFTER)
    publish = lambda: publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert publish().action == "published"

    (built,) = world.built
    first = built.laps[built.laps["LapNumber"] == 1].set_index("DriverNumber")["LapTime"]
    assert first["1"] == pd.Timedelta(milliseconds=91500)
    assert first["2"] == pd.Timedelta(milliseconds=92250)
    assert pd.isna(first["3"])
    assert built.laps[built.laps["LapNumber"] > 1]["LapTime"].isna().all()

    # A time that arrives later changes the fingerprint, and so the session.
    world.first_lap_ms["3"] = 93000
    outcome = publish()
    assert (outcome.action, outcome.reason) == ("published", "the classification changed")


# --- R2: a record that does not describe its feeds is corrected for everyone -------


def with_a_lap_to_spare_for_nobody():
    """Twenty-five laps, and for one driver car data for twenty-four of them:
    every bar met, with the weakest share at 0.96."""
    session = make_session(laps_per_driver=25)
    car = session.car_data["1"]
    seconds = car["SessionTime"].dt.total_seconds()
    inside_lap_12 = (seconds > FEEDS_START + 11 * LAP_SECONDS + 1) & (seconds < FEEDS_START + 12 * LAP_SECONDS - 1)
    session.car_data["1"] = car[~inside_lap_12].reset_index(drop=True)
    return session


def without_positions_for_one_driver(laps_per_driver=25):
    session = make_session(laps_per_driver=laps_per_driver)
    del session.pos_data["2"]
    return session


def test_a_snapshot_found_short_by_a_build_does_not_stand_in_the_way_of_a_whole_one(tmp_path, monkeypatch):
    """Snapshot A's record says whole, with nothing to spare, and its feeds
    have no positions for one driver. It is published as partial once its
    window closes. Then B arrives, which meets every bar by a smaller margin
    than A's record claims: by the records, A is still the better of the two."""
    world = Archive(monkeypatch, {"1": 25, "2": 25, "3": 25})
    store = world.store
    a = world.snapshot(
        tmp_path / "a", recorded=make_session(laps_per_driver=25), feeds=without_positions_for_one_driver()
    )
    clock = [FIRST_FETCH + RETRY_WINDOW]
    builder = Builder(store, fastf1=None, now=lambda: clock[0])
    publish = lambda: publish_session(store, AUSTRIA, builder.gather, builder.build, now=lambda: clock[0])
    assert publish().action == "published"
    assert read_pointer(store, AUSTRIA)[0].complete is False

    clock[0] = FIRST_FETCH + SLOW_RETRY_INTERVAL
    b = world.snapshot(tmp_path / "b", recorded=with_a_lap_to_spare_for_nobody(), moment=clock[0])
    assert a.complete and b.complete and a.rank() > b.rank()

    # Nothing more is owed by the fetch stage, and the build publishes B.
    assert planned(list_snapshots(store), clock[0] + timedelta(days=1)) == []
    outcome = publish()

    assert (outcome.action, outcome.reason) == ("published", "a different snapshot is now selected")
    pointer, _ = read_pointer(store, AUSTRIA)
    assert (pointer.snapshot_id, pointer.complete) == (b.snapshot_id, True)
    assert publish().action == "current"


def test_a_build_that_corrects_a_record_decides_again_in_the_same_run(tmp_path, monkeypatch):
    """Both snapshots are there before anything is published. The first choice
    is the one whose record flatters it."""
    world = Archive(monkeypatch, {"1": 25, "2": 25, "3": 25})
    a = world.snapshot(
        tmp_path / "a", recorded=make_session(laps_per_driver=25), feeds=without_positions_for_one_driver()
    )
    b = world.snapshot(
        tmp_path / "b", recorded=with_a_lap_to_spare_for_nobody(), moment=FIRST_FETCH + RETRY_INTERVAL
    )
    builder = Builder(world.store, fastf1=None, now=lambda: FIRST_FETCH + RETRY_INTERVAL + timedelta(hours=1))

    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    pointer, _ = read_pointer(world.store, AUSTRIA)
    assert (pointer.snapshot_id, pointer.complete) == (b.snapshot_id, True)
    # A was loaded, found wanting and not built from. B was built from.
    assert (len(world.loaded), len(world.built)) == (2, 1)
    corrected = {item.snapshot_id: item for item in list_snapshots(world.store)}
    assert not corrected[a.snapshot_id].complete and corrected[b.snapshot_id].complete


def test_a_decision_that_never_settles_is_left_for_the_next_run():
    store = MemoryStore()

    def never_agrees(inputs):
        raise DecideAgain("corrected the record of snapshot 20261005T200000Z-aaaaaaaa")

    outcome = publish_session(
        store, AUSTRIA, lambda key, **_: Inputs(snapshot(), "sha256:first"), never_agrees, max_attempts=3
    )

    assert outcome.action == "conflict"
    assert outcome.reason == (
        "not settled after 3 attempts: corrected the record of snapshot 20261005T200000Z-aaaaaaaa"
    )
    assert read_pointer(store, AUSTRIA) == (None, None)


def test_the_feeds_measure_the_same_whatever_the_result_of_the_day():
    session = make_session()
    as_fetched = measure(session)
    judged_later = apply_classification(as_fetched, {"1": 11, "2": 10, "44": 10})
    with_no_result = measure(session)
    for driver in with_no_result["drivers"].values():
        driver["classified_laps"] = None

    assert feed_figures(judged_later) == feed_figures(as_fetched) == feed_figures(with_no_result)
    assert feed_figures(measure(without_positions_for_one_driver(10))) != feed_figures(as_fetched)


def test_a_correction_gives_the_feeds_as_measured_and_the_result_as_recorded(tmp_path):
    store = MemoryStore()
    written = write_snapshot(store, fetched_session(tmp_path), now=FIRST_FETCH)
    # As a build measures: Jolpica out of reach, so nobody is classified.
    measured = measure(without_positions_for_one_driver(10))
    for driver in measured["drivers"].values():
        driver["classified_laps"] = None

    write_remeasurement(store, written, measured)

    (listed,) = list_snapshots(store, AUSTRIA)
    assert [(item.bar, item.driver) for item in listed.shortfalls()] == [("position", "BBB")]
    assert {driver["classified_laps"] for driver in listed.coverage["drivers"].values()} == {10}
    assert (listed.snapshot_id, listed.fetched_at, listed.objects) == (
        written.snapshot_id,
        written.fetched_at,
        written.objects,
    )


def test_a_correction_that_cannot_be_trusted_leaves_the_record_as_it_was(tmp_path):
    store = MemoryStore()
    written = write_snapshot(store, fetched_session(tmp_path), now=FIRST_FETCH)
    key = f"{layout.snapshot_prefix(AUSTRIA, written.snapshot_id)}{layout.REMEASUREMENT_NAME}"
    short = measure(without_positions_for_one_driver(10))
    good = {"schema_version": 1, "snapshot_id": written.snapshot_id, "coverage": short}

    for unusable in (
        b"not json",
        b"[]",
        dump_json({**good, "snapshot_id": "20260101T000000Z-bbbbbbbb"}),
        dump_json({**good, "schema_version": 2}),
        dump_json({**good, "coverage": {**short, "measurement_version": 1}}),
        dump_json({**good, "coverage": {**short, "drivers": [1, 2]}}),
        dump_json({**good, "coverage": "none"}),
    ):
        store.put(key, unusable)
        assert list_snapshots(store, AUSTRIA) == [written], unusable[:40]

    store.put(key, dump_json(good))
    assert list_snapshots(store, AUSTRIA) != [written]


# --- R3: a feed absent for everyone is absent, however the shortfalls are counted --


@pytest.mark.parametrize(
    ("attribute", "bar", "feed"),
    [("pos_data", "position", "Position.z.jsonStream"), ("car_data", "car_data", "CarData.z.jsonStream")],
)
def test_telemetry_f1_does_not_hold_at_all_ends_the_retries_once_the_window_closes(attribute, bar, feed):
    """F1 answers the session information and refuses the whole feed, and its
    mirror has nothing. The shortfall shows once for each driver."""
    nothing = make_session()
    setattr(nothing, attribute, {})
    not_held = replace(
        snapshot(snapshot_id=fetched_at(FIRST_FETCH), session=nothing),
        feed_status={"SessionInfo.jsonStream": 200, feed: 403},
    )
    assert not_held.coverage["feeds"][bar] is False
    assert {(item.bar, item.driver) for item in not_held.shortfalls()} == {(bar, "AAA"), (bar, "BBB"), (bar, "CCC")}

    assert not_held.missing_only_what_f1_does_not_hold()
    # While the window is open the answer may only mean "not yet".
    assert planned([not_held], FIRST_FETCH + RETRY_INTERVAL) == [8]
    for weeks in (1, 10, 100):
        assert planned([not_held], FIRST_FETCH + weeks * SLOW_RETRY_INTERVAL) == []

    # Refused by an origin that was refusing everything, it proves nothing.
    refused = replace(not_held, feed_status={"SessionInfo.jsonStream": 403, feed: 403})
    assert planned([refused], FIRST_FETCH + SLOW_RETRY_INTERVAL) == [8]


def test_tyre_data_absent_for_everyone_is_absent_and_for_one_driver_is_not():
    status = {"SessionInfo.jsonStream": 200, "TimingAppData.jsonStream": 404}
    nobody = make_session()
    nobody.laps["Compound"] = None
    one_driver = make_session()
    one_driver.laps.loc[one_driver.laps["DriverNumber"] == "2", "Compound"] = None

    absent = replace(snapshot(snapshot_id=fetched_at(FIRST_FETCH), session=nobody), feed_status=status)
    short = replace(snapshot(snapshot_id=fetched_at(FIRST_FETCH), session=one_driver), feed_status=status)

    assert absent.missing_only_what_f1_does_not_hold()
    assert planned([absent], FIRST_FETCH + SLOW_RETRY_INTERVAL) == []
    assert not short.missing_only_what_f1_does_not_hold()
    assert planned([short], FIRST_FETCH + SLOW_RETRY_INTERVAL) == [8]


# --- R4: no input stops a fetch from being measured -------------------------------


def test_a_duration_too_large_to_be_a_number_is_left_out_and_the_stop_kept():
    feed = (
        b'01:12:03.942{"PitTimes":{"1":[{"PitStop":{"Lap":"12","PitStopTime":1'
        + b"0" * 400
        + b',"PitLaneTime":"21.3"}}]}}'
    )

    (stop,) = parse_pit_stop_series(feed)

    assert (stop["stationary_ms"], stop["pit_lane_ms"]) == (None, 21300)
    assert measure(make_session(), "R", {**EXTRAS, PIT_STOP_SERIES: feed})["pit_stops_in_series"] == 1


def test_a_line_nested_too_deep_to_read_costs_only_itself():
    too_deep = b"01:12:03.942" + b"[" * 100_000
    readable = EXTRAS[PIT_STOP_SERIES].removeprefix(b"\xef\xbb\xbf")

    assert len(parse_pit_stop_series(too_deep + b"\r\n" + readable)) == 1
    assert circuit_corner_count(b"[" * 100_000) == 0
