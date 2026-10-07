"""The cases the eleventh review of this code found (GPT-6.1 Sol, 2026-10-06, at d6c0bc5).

The first review of format 2. Three of its five findings need nothing but a
feed with a hole in it: rows FastF1 adds for a car missing from the car feed
were published as the car standing still, a lap with no compound in the
middle of a stint made two runs that shared laps, and a car with positions
and no car data was left out of the replay. Two need an object in the archive
that nothing here wrote.

Checking the first against the archive found that the fix as first written
did nothing there: a loaded session holds the missing mark as the text
``nan``. It found two things more, which are closed here too: F1 reported
twenty of the 2026 Australian GP's twenty-eight pit stops with no lap, and
they were dropped; and a lap whose car data stops short was published anyway.
The frontend's move to format 2 found the last two: a driver classified
without finishing was shown laps down, and a wait through a red flag was
counted as a pit stop.
"""

from __future__ import annotations

import base64
import json
import zlib

import numpy as np
import pandas as pd
import pytest

from f1data import layout, normalize
from f1data.analyses import position_replay
from f1data.archive import dump_json, list_snapshots, write_snapshot
from f1data.build import Builder
from f1data.coverage import (
    FEED_FILE_BY_BAR,
    MEASUREMENT_VERSION,
    evaluate_coverage,
    f1_does_not_hold,
    measure_coverage,
    sent_by_f1,
)
from f1data.extras import PIT_STOP_SERIES, parse_pit_stop_series
from f1data.models import artifact_json
from f1data.policy import RETRY_INTERVAL, RETRY_WINDOW
from f1data.publish import publish_session, read_pointer
from f1data.store import MemoryStore
from f1data.telemetry import extract_telemetry
from tests.building import FIRST_FETCH, Archive
from tests.fakes import make_session, measure
from tests.race import CLOCK_ZERO, LAPS, PIT_LAP, TRACK_LENGTH_M, classification, extras, make_race
from tests.test_archive import fetched_session
from tests.test_artifacts import built, read
from tests.test_fifth_review import WINDOW_CLOSED, correction, correction_key
from tests.test_fourth_review import without_positions_for_one_driver
from tests.test_publish import AUSTRIA
from tests.test_second_review import planned

EVERYONE = {"1": 10, "2": 10, "3": 10}

# --- R11-1: a row FastF1 adds for a car missing from the feed is not a sample -------


def car_line(clock: str, utc: str, cars: dict[str, int]) -> str:
    """One line of F1's car feed: the session clock, then the cars' channels, deflated and in base 64."""
    entry = {
        "Utc": utc,
        "Cars": {
            number: {"Channels": {"0": 9000 + 10 * speed, "2": speed, "3": 5, "4": 80, "5": 0, "45": 0}}
            for number, speed in cars.items()
        },
    }
    packer = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    packed = packer.compress(json.dumps({"Entries": [entry]}).encode()) + packer.flush()
    return f'{clock}"{base64.b64encode(packed).decode()}"'


def test_fastf1_marks_the_rows_it_adds_and_a_loaded_session_still_tells_them_apart():
    """FastF1's own parser and its own session loading, on a feed where car 1
    is missing from two messages. The parser leaves ``Source`` empty on the
    rows it adds, and loading turns the empty mark into the text ``nan``: the
    fix first looked for an empty one, which no loaded session has."""
    from fastf1 import _api
    from fastf1.core import Telemetry

    feed = [
        car_line("00:00:01.000", "2026-06-28T12:00:01.000Z", {"1": 200, "2": 210}),
        car_line("00:00:01.240", "2026-06-28T12:00:01.240Z", {"2": 211}),
        car_line("00:00:01.480", "2026-06-28T12:00:01.480Z", {"2": 212}),
        car_line("00:00:01.720", "2026-06-28T12:00:01.720Z", {"1": 203, "2": 213}),
    ]

    parsed = _api.car_data.__wrapped__("", response=feed)
    # What Session._load_telemetry makes of each car's table.
    loaded = Telemetry(
        parsed["1"].drop(labels="Time", axis=1), drop_unknown_channels=True, _cast_default_cols=True
    )

    assert parsed["1"]["Speed"].tolist() == [200, 0, 0, 203] and parsed["1"]["RPM"].tolist()[1:3] == [0, 0]
    assert sent_by_f1(parsed["1"]).tolist() == [True, False, False, True]
    assert sent_by_f1(loaded).tolist() == [True, False, False, True]
    assert sent_by_f1(parsed["2"]).all()


def missing_from_the_car_feed(session, number: str, from_seconds: float, until_seconds: float, mark):
    """``session`` as FastF1 leaves it when a car is missing from the car feed between two moments.

    ``mark`` is what the added rows have for a source: nothing, as the parser
    leaves them, or the text a loaded session has in its place.
    """
    for frame in session.car_data.values():
        frame["Source"] = "car"
    frame = session.car_data[number]
    seconds = frame["SessionTime"].dt.total_seconds()
    added = (seconds >= from_seconds) & (seconds < until_seconds)
    frame.loc[added, ["Speed", "RPM", "Throttle"]] = 0.0
    frame.loc[added, ["nGear", "DRS"]] = 0
    frame.loc[added, "Brake"] = False
    frame.loc[added, "Source"] = mark
    assert added.sum() > 1
    return session


# Laps 4 and 5 of the stand-in race's first driver run from 840 s to 1010 s.
LONG_HOLE = (850.0, 980.0)
SHORT_HOLE = (850.0, 852.0)
MARKS = pytest.mark.parametrize("mark", [np.nan, "nan"], ids=["as parsed", "as loaded"])


@MARKS
def test_added_rows_do_not_count_as_car_data_when_a_session_is_measured(mark):
    """Sol took car 1 out of the feed for 130 seconds, through FastF1's own
    parser. Every channel of an added row is a number, so the measurement
    counted twelve usable car laps of twelve and nothing was short."""
    whole = measure_coverage(make_race(), "R", extras())
    holed = measure_coverage(missing_from_the_car_feed(make_race(), "1", *LONG_HOLE, mark), "R", extras())

    assert whole["drivers"]["AAA"]["car_laps"] == LAPS
    assert holed["drivers"]["AAA"]["car_laps"] == LAPS - 2
    assert holed["drivers"]["BBB"]["car_laps"] == LAPS
    assert ("car_data", "AAA") in {(item.bar, item.driver) for item in evaluate_coverage(holed)}


@MARKS
def test_a_lap_with_a_long_hole_in_its_car_data_has_no_telemetry_and_its_positions_are_kept(mark):
    """Published lap 5 held zero speed and zero RPM and came to 1,894 m of a
    5,000 m track. With the added rows gone the hole is two minutes of
    nothing, and a line drawn across it would be as much of an invention."""
    session = missing_from_the_car_feed(make_race(), "1", *LONG_HOLE, mark)

    telemetry = extract_telemetry(session)

    published = {number for code, number in telemetry.laps if code == "AAA"}
    assert published == set(range(1, LAPS + 1)) - {4, 5}
    assert {key for key in telemetry.positions_only} == {("AAA", 4), ("AAA", 5)}
    # The stand-in's engine never turns slower than 6,000 rpm: a zero is an added row.
    assert min(float(lap.rpm.min()) for lap in telemetry.of_driver("AAA")) >= 6000.0
    # What is published is what the coverage counts.
    coverage = measure_coverage(session, "R", extras())
    assert coverage["drivers"]["AAA"]["car_laps"] == len(published)

    files = built(session)
    assert [lap["lap_number"] for lap in read(files, "telemetry/AAA.json")["laps"]] == sorted(published)
    assert ("car_data", "AAA") in {
        (item["bar"], item["driver"]) for item in read(files, "coverage.json")["shortfalls"]
    }
    # The car was still somewhere on those two laps, and the replay shows it.
    replay = read(files, "position-replay.json")
    anna = next(driver for driver in replay["drivers"] if driver["driver_code"] == "AAA")
    during = [index for index, moment in enumerate(replay["time_ms"]) if 860_000 <= moment < 970_000]
    assert during and all(anna["x"][index] is not None and anna["speed_kph"][index] is None for index in during)


@MARKS
def test_a_short_hole_is_bridged_between_the_samples_either_side_and_never_through_a_zero(mark):
    whole = extract_telemetry(make_race()).laps[("AAA", 4)]
    holed = extract_telemetry(missing_from_the_car_feed(make_race(), "1", *SHORT_HOLE, mark)).laps[("AAA", 4)]

    assert float(holed.speed_kph.min()) == pytest.approx(float(whole.speed_kph.min()), abs=5.0)
    assert float(holed.speed_kph.min()) > 100.0 and float(holed.rpm.min()) >= 6000.0
    assert float(holed.distance_m[-1]) == pytest.approx(TRACK_LENGTH_M, rel=0.01)
    # Inside the hole the lap is sampled where the position feed ticked, and
    # nowhere the car feed would have.
    on_clock = holed.time_ms + holed.start_ms
    in_the_hole = (on_clock > SHORT_HOLE[0] * 1000) & (on_clock < SHORT_HOLE[1] * 1000)
    position_ticks = np.rint(make_race().pos_data["1"]["SessionTime"].dt.total_seconds().to_numpy() * 1000)
    assert in_the_hole.any() and np.isin(on_clock[in_the_hole], position_ticks).all()
    assert len(holed.time_ms) < len(whole.time_ms)


def test_a_lap_whose_car_data_stops_before_the_lap_does_has_no_telemetry():
    """The 2025 São Paulo sprint: Bortoleto's car stops sending 6.7 seconds
    before the end of his last lap. The coverage never counted the lap, and
    the telemetry published it with an end that was made up."""
    session = make_race()
    last = session.laps.query("Driver == 'BBB' and LapNumber == @LAPS").iloc[0]
    frame = session.car_data["2"]
    session.car_data["2"] = frame[frame["SessionTime"] < last["Time"] - pd.Timedelta(seconds=7)]

    telemetry = extract_telemetry(session)

    assert ("BBB", LAPS) not in telemetry.laps and ("BBB", LAPS - 1) in telemetry.laps
    assert measure_coverage(session, "R", extras())["drivers"]["BBB"]["car_laps"] == LAPS - 1


# --- R11-2: the runs of a driver's tyres never share a lap -----------------------


def tyres(session, code: str, per_lap: list[tuple[int, str | None]]):
    """``session`` with one driver's stint number and compound set lap by lap."""
    for lap_number, (stint, compound) in enumerate(per_lap, start=1):
        mine = (session.laps["Driver"] == code) & (session.laps["LapNumber"] == lap_number)
        session.laps.loc[mine, "Stint"] = float(stint)
        session.laps.loc[mine, "Compound"] = compound
    return session


def runs(session, code: str) -> list[tuple[int, str | None, int, int, int]]:
    return [
        (run.stint, run.compound.value if run.compound else None, run.start_lap, run.end_lap, run.lap_count)
        for run in normalize.stints(normalize.laps(session))
        if run.driver_code == code
    ]


def test_a_lap_with_no_compound_in_the_middle_of_a_stint_does_not_split_it():
    """Laps were grouped by stint number and compound across the whole
    session. One lap of BBB's with no compound made a run of that lap, and
    left the other eleven as a run from lap 1 to lap 12 that spanned it."""
    session = tyres(make_race(), "BBB", [(1, "MEDIUM")] * 5 + [(1, None)] + [(1, "MEDIUM")] * 6)

    assert runs(session, "BBB") == [(1, "MEDIUM", 1, 12, 12)]

    strategy = read(built(session), "analysis/strategy.json")
    assert strategy["compound_usage"] == {"HARD": 1, "MEDIUM": 3}


@pytest.mark.parametrize(
    ("per_lap", "expected"),
    [
        # F1 names a set's compound some laps after it goes on.
        ([(1, None)] * 3 + [(1, "HARD")] * 9, [(1, "HARD", 1, 12, 12)]),
        # F1 corrects the compound under one number: two runs, one after the other.
        ([(1, "MEDIUM")] * 4 + [(1, "SOFT")] * 8, [(1, "MEDIUM", 1, 4, 4), (1, "SOFT", 5, 12, 8)]),
        # Unnamed laps between two compounds stay with the set before them.
        (
            [(1, "MEDIUM")] * 4 + [(1, None)] * 2 + [(1, "SOFT")] * 6,
            [(1, "MEDIUM", 1, 6, 6), (1, "SOFT", 7, 12, 6)],
        ),
        # No compound at all.
        ([(1, None)] * 12, [(1, None, 1, 12, 12)]),
        # A number that comes back is not the run it was before.
        (
            [(1, "MEDIUM")] * 4 + [(2, "HARD")] * 4 + [(1, "MEDIUM")] * 4,
            [(1, "MEDIUM", 1, 4, 4), (2, "HARD", 5, 8, 4), (1, "MEDIUM", 9, 12, 4)],
        ),
        # A new number is a new set, whatever its compound.
        ([(1, "HARD")] * 6 + [(2, "HARD")] * 6, [(1, "HARD", 1, 6, 6), (2, "HARD", 7, 12, 6)]),
    ],
)
def test_the_runs_of_a_driver_are_consecutive_and_never_share_a_lap(per_lap, expected):
    session = tyres(make_race(), "BBB", per_lap)

    found = runs(session, "BBB")

    assert found == expected
    covered = [number for _, _, start, end, _ in found for number in range(start, end + 1)]
    assert covered == list(range(1, LAPS + 1))


def test_a_lap_the_timing_has_no_row_for_leaves_a_run_one_lap_short_and_still_one_run():
    session = make_race()
    session.laps = session.laps[~((session.laps["Driver"] == "BBB") & (session.laps["LapNumber"] == 6))]

    assert runs(session, "BBB") == [(1, "MEDIUM", 1, 12, 11)]


# --- R11-3: a car with positions and no car data is still in the replay ------------


def replay_of(session) -> dict:
    return artifact_json(position_replay(extract_telemetry(session)))


def placed(replay: dict, code: str) -> list[int]:
    driver = next((item for item in replay["drivers"] if item["driver_code"] == code), None)
    return [index for index, x in enumerate(driver["x"]) if x is not None] if driver else []


def test_a_car_with_positions_and_no_car_data_is_still_in_the_replay():
    """The replay was made from the laps that have car data. With driver 1's
    car data gone the coverage still counted twelve laps of positions for
    AAA, and the replay had BBB and CCC in it."""
    whole = replay_of(make_race())
    session = make_race()
    del session.car_data["1"]

    replay = replay_of(session)

    assert measure_coverage(session, "R", extras())["drivers"]["AAA"]["position_laps"] == LAPS
    assert [driver["driver_code"] for driver in replay["drivers"]] == ["AAA", "BBB", "CCC"]
    assert replay["time_ms"] == whole["time_ms"] and replay["lap_number"] == whole["lap_number"]
    assert placed(replay, "AAA") == placed(whole, "AAA")
    anna = replay["drivers"][0]
    # Where the car was, from the position feed's own samples: within a
    # sample's travel of where the merged telemetry puts it.
    for index in placed(replay, "AAA")[:: len(replay["time_ms"]) // 20]:
        there = whole["drivers"][0]
        assert np.hypot(anna["x"][index] - there["x"][index], anna["y"][index] - there["y"][index]) < 250.0
    # Its speed and its distance round the lap are not known, and are not made up.
    assert set(anna["speed_kph"]) == {None} and set(anna["distance_m"]) == {None}
    assert replay["drivers"][1] == whole["drivers"][1]

    files = built(session)
    assert "telemetry/AAA.json" not in files
    assert read(files, "position-replay.json") == replay


def test_with_no_car_data_at_all_the_replay_is_every_car_from_the_position_feed():
    whole = replay_of(make_race())
    session = make_race()
    session.car_data = {}

    replay = replay_of(session)

    assert replay["time_ms"] == whole["time_ms"] and replay["lap_number"] == whole["lap_number"]
    assert [driver["driver_code"] for driver in replay["drivers"]] == ["AAA", "BBB", "CCC"]
    assert all(placed(replay, code) == placed(whole, code) for code in ("AAA", "BBB", "CCC"))


# --- R11-4: what F1 answered for a feed is a status or nothing ---------------------


@pytest.mark.parametrize("answered", [[], {}, "403", True, 403.5])
def test_a_marker_whose_feed_status_is_no_status_is_passed_over(answered, tmp_path):
    """A list where a status should be was looked up in a set of statuses once
    the session's retry window had closed, and the planner stopped there:
    before any session was attempted, on every run."""
    store = MemoryStore()
    kept = write_snapshot(store, fetched_session(tmp_path / "good"), now=FIRST_FETCH)
    other = write_snapshot(store, fetched_session(tmp_path / "other"), now=FIRST_FETCH + RETRY_INTERVAL)
    key = f"{layout.snapshot_prefix(AUSTRIA, other.snapshot_id)}{layout.SNAPSHOT_MARKER}"
    marker = other.to_json()
    spoiled = {**marker, "feed_status": {**marker["feed_status"], FEED_FILE_BY_BAR["weather"]: answered}}
    store.put(key, dump_json(spoiled))

    assert list_snapshots(store) == [kept]
    assert planned(list_snapshots(store), FIRST_FETCH + RETRY_WINDOW) == []


@pytest.mark.parametrize(("answered", "not_held"), [(403, True), (404, True), (200, False), ([], False), ("403", False), (True, False), (None, False)])
def test_only_a_status_f1_gave_says_f1_does_not_hold_a_feed(answered, not_held):
    session = make_session()
    session.weather_data = session.weather_data.iloc[0:0]
    measurement = measure(session)
    (shortfall,) = [item for item in evaluate_coverage(measurement) if item.bar == "weather"]
    status = {FEED_FILE_BY_BAR["session_info"]: 200, FEED_FILE_BY_BAR["weather"]: answered}

    assert f1_does_not_hold(shortfall, status, measurement) is not_held


# --- R11-5: a correction this version cannot read, and nobody could ----------------


@pytest.mark.parametrize(
    "coverage",
    [
        {"measurement_version": MEASUREMENT_VERSION + 1, "drivers": "broken"},
        {"measurement_version": MEASUREMENT_VERSION + 1},
        {"measurement_version": MEASUREMENT_VERSION + 1, "feeds": [], "drivers": {}},
        {"measurement_version": MEASUREMENT_VERSION + 1, "feeds": {}, "drivers": None},
    ],
)
def test_a_broken_correction_by_a_measurement_this_version_does_not_know_has_no_say(coverage, tmp_path, monkeypatch):
    """A correction of a measurement version this one cannot read keeps its
    authority, so that a newer version's work is not replaced. That was
    granted before anything else in it was looked at: an object claiming a
    newer version and holding nothing shut this version out of the snapshot,
    and the session answered "newer" on every run without ever being built."""
    world = Archive(monkeypatch, EVERYONE)
    written = world.snapshot(tmp_path, recorded=make_session(), feeds=without_positions_for_one_driver(10))
    claim = {
        "schema_version": 1,
        "snapshot_id": written.snapshot_id,
        "pipeline_version": layout.PIPELINE_VERSION + 1,
        "coverage": coverage,
    }
    world.store.put(correction_key(written), dump_json(claim))

    (listed,) = list_snapshots(world.store)
    assert (listed.corrected_by, listed.complete) == (None, True)

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert read_pointer(world.store, AUSTRIA)[0].complete is False
    assert correction(world.store, written)["pipeline_version"] == layout.PIPELINE_VERSION


# --- a classified driver who did not finish is not laps down -----------------------


@pytest.mark.parametrize(
    ("status", "laps_down"),
    [
        ("Lapped", 1),
        ("+1 Lap", 1),
        ("Finished", 1),
        ("Retired", None),
        ("Accident", None),
        ("Power Unit", None),
        ("Did not finish", None),
        ("", None),
    ],
)
def test_laps_down_is_for_a_driver_who_took_the_flag(status, laps_down):
    """The 2025 Dutch GP: Norris retired seven laps from the end and is
    classified eighteenth, having covered nine tenths of the distance. He was
    published as seven laps down, like a car that was lapped seven times."""
    session = make_race()
    official = classification()
    official.rows[2].update(laps=LAPS - 1, positionText="3", status=status, totalRaceTime=None)

    *_, row = normalize.results(official, session, normalize.driver_codes(session))

    assert (row.classified_position, row.laps, row.laps_down) == ("3", LAPS - 1, laps_down)
    assert row.gap_ms is None and row.behind_at_flag_ms is None


# --- a wait through a red flag is not a pit stop ----------------------------------


def red_flag(session, shown_at_ms: int, lifted_at_ms: int | None):
    changes = [(0, "1"), (shown_at_ms, "5")] + ([(lifted_at_ms, "1")] if lifted_at_ms is not None else [])
    session.track_status = pd.DataFrame(
        {"Time": [pd.Timedelta(milliseconds=moment) for moment, _ in changes], "Status": [status for _, status in changes]}
    )
    return session


def the_stop(session):
    (stop,) = normalize.pit_stops(session, extras(), normalize.driver_codes(session))
    return stop


def test_a_wait_in_the_pit_lane_through_a_red_flag_is_marked_and_left_out_of_the_pit_lane_figures():
    """The 2026 Dutch GP was stopped with the field in the pit lane. Every car
    had a "pit stop" of twenty-six minutes, and the slowest stop of the race
    was one of them."""
    came_in = the_stop(make_race()).entry_time_ms
    session = red_flag(make_race(), came_in + 5_000, came_in + 15_000)

    assert the_stop(session).under_red_flag is True
    assert the_stop(make_race()).under_red_flag is False

    times = read(built(session), "analysis/strategy.json")["pit_lane_time"]
    assert times == {"median_ms": None, "fastest_ms": None, "slowest_ms": None, "timed_stop_count": 0, "stop_count": 1}
    assert read(built(), "analysis/strategy.json")["pit_lane_time"]["timed_stop_count"] == 1


@pytest.mark.parametrize(
    ("shown", "lifted", "waited"),
    [
        # Shown and lifted before the car came in, and shown after it had left.
        (-60_000, -30_000, False),
        (25_000, 90_000, False),
        # Out when the car came in, and shown as it was leaving.
        (-60_000, 5_000, True),
        (19_000, 90_000, True),
        # Still out when the feed stops.
        (-60_000, None, True),
        (30_000, None, False),
    ],
)
def test_a_stop_is_under_a_red_flag_when_the_two_overlap(shown, lifted, waited):
    came_in = the_stop(make_race()).entry_time_ms
    session = red_flag(make_race(), came_in + shown, came_in + lifted if lifted is not None else None)

    assert the_stop(session).under_red_flag is waited


# --- a stop F1 reports late and with no lap ---------------------------------------

# The first of the 2026 Australian GP's pit-stop feed, as F1 sent it.
AUSTRALIA_WITHOUT_A_LAP = (
    b'\xef\xbb\xbf01:16:19.949{"PitTimes":{"43":[{"Timestamp":"2026-03-08T04:17:26.571Z","PitStop":'
    b'{"RacingNumber":"43","PitStopTime":"12.5","PitLaneTime":"27.733","Lap":""}}]}}\r\n'
)


def test_a_stop_reported_with_no_lap_is_kept_with_the_time_it_was_reported():
    """It used to be dropped where the feed is read: twenty of the race's
    twenty-eight stops had no stationary time in what was published."""
    assert parse_pit_stop_series(AUSTRALIA_WITHOUT_A_LAP) == [
        {
            "driver_number": "43",
            "lap_number": None,
            "stationary_ms": 12_500,
            "pit_lane_ms": 27_733,
            "time_utc": "2026-03-08T04:17:26.571Z",
        }
    ]
    # With neither a lap nor a time there is nothing to place it by.
    nowhere = AUSTRALIA_WITHOUT_A_LAP.replace(b'"Timestamp":"2026-03-08T04:17:26.571Z",', b"")
    assert parse_pit_stop_series(nowhere) == []


def late_report(seconds_after_the_car_left: float, lap: str = "") -> dict[str, bytes]:
    stop = the_stop(make_race())
    at = CLOCK_ZERO + pd.Timedelta(milliseconds=stop.entry_time_ms + stop.duration_ms) + pd.Timedelta(seconds=seconds_after_the_car_left)
    line = (
        '01:00:00.000{"PitTimes":{"1":[{"Timestamp":"%sZ","PitStop":{"RacingNumber":"1",'
        '"PitStopTime":"3.3","PitLaneTime":"20.1","Lap":"%s"}}]}}\r\n' % (at.isoformat(timespec="milliseconds"), lap)
    )
    return {**extras(pit_stops=False), PIT_STOP_SERIES: line.encode()}


@pytest.mark.parametrize("seconds", [0.0, 1.4, 65.7, 119.0])
def test_a_report_with_no_lap_is_of_the_stop_the_driver_had_just_finished(seconds):
    """The Australian reports came between one second and 66 seconds after
    the car left the pit lane."""
    session = make_race()

    (stop,) = normalize.pit_stops(session, late_report(seconds), normalize.driver_codes(session))

    assert (stop.lap_number, stop.duration_ms, stop.stationary_ms, stop.pit_lane_ms) == (PIT_LAP, 20_000, 3_300, 20_100)
    assert stop.sources.stationary_ms == "pit_stop_series"


@pytest.mark.parametrize("seconds", [-30.0, 121.0, 3600.0])
def test_a_report_with_no_lap_that_no_stop_in_the_timing_answers_to_is_not_published(seconds, caplog):
    session = make_race()

    with caplog.at_level("WARNING", logger="f1data.normalize"):
        (stop,) = normalize.pit_stops(session, late_report(seconds), normalize.driver_codes(session))

    assert (stop.lap_number, stop.stationary_ms, stop.pit_lane_ms) == (PIT_LAP, None, None)
    assert "with no lap" in caplog.text


def test_a_late_report_still_counts_as_a_stop_the_feed_vouches_for():
    session = make_race()

    assert measure_coverage(session, "R", late_report(30.0))["pit_stops_in_series"] == 1

