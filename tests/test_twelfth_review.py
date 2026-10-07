"""The cases the twelfth review of this code found (GPT-6.1 Sol, 2026-10-06, at 2b0ebe5).

It was asked to compare the stand-in sessions these tests are built on with
what FastF1 really leaves on a loaded session, after a fix in the round
before passed every test and did nothing on a real one. Two of its findings
are of that kind: FastF1 writes the word ``None`` where a driver has no code,
and an empty code on every lap when F1's driver list did not arrive. A third
is what FastF1 does with a weather line that leaves a sensor out. The rest
are in what the round before added: the cut of a lap's car data, the placing
of a pit-stop report that names no lap, the replay's lap count, and a
correction of a snapshot's record that claims a measurement this code cannot
read.

Where a finding turns on the form FastF1 gives a value, the test makes that
form with FastF1's own code and not by hand.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from f1data import layout, normalize
from f1data.analyses import position_replay
from f1data.archive import dump_json, list_snapshots, write_remeasurement, write_snapshot
from f1data.artifacts import build_artifacts
from f1data.build import Builder
from f1data.classification import merge_into_session
from f1data.coverage import MEASUREMENT_VERSION, apply_classification, evaluate_coverage, measure_coverage
from f1data.extras import PIT_STOP_SERIES, WEATHER_SERIES, parse_pit_stop_series, weather_readings_sent
from f1data.loaded import MISSING_AS_TEXT, driver_codes, present, text
from f1data.models import artifact_json
from f1data.publish import publish_session, read_pointer
from f1data.store import DirectoryStore
from f1data.telemetry import extract_telemetry
from tests.building import FIRST_FETCH, Archive
from tests.fakes import make_session, measure
from tests.race import CLOCK_ZERO, IDENTITY, LAPS, TRACK_LENGTH_M, classification, extras, make_race
from tests.test_archive import fetched_session
from tests.test_artifacts import built, read
from tests.test_eleventh_review import missing_from_the_car_feed
from tests.test_fifth_review import WINDOW_CLOSED, correction, correction_key
from tests.test_fourth_review import without_positions_for_one_driver
from tests.test_publish import AUSTRIA
from tests.test_sixth_review import copy

EVERYONE = {"1": 10, "2": 10, "3": 10}


def lap_times(session, code: str, number: int) -> tuple[float, float]:
    row = session.laps[(session.laps["Driver"] == code) & (session.laps["LapNumber"] == number)].iloc[0]
    return row["LapStartTime"].total_seconds(), row["Time"].total_seconds()


# --- R12-1: a car sample from long before a lap is not the lap's neighbour ----------


@pytest.mark.parametrize("mark", [np.nan, "nan"], ids=["as parsed", "as loaded"])
def test_a_lap_that_follows_a_hole_in_the_car_data_starts_at_its_own_first_sample(mark):
    """A lap is cut from the car data with one sample either side. With the
    rows FastF1 adds left out, the one before a lap can be a minute back, and
    the lap's first sample was then given a minute's travel: lap 3 was
    published from 2,501 m to 7,503 m of a 5,000 m track."""
    session = make_race()
    start, _ = lap_times(session, "AAA", 3)
    missing_from_the_car_feed(session, "1", start - 60.0, start + 0.2, mark)

    telemetry = extract_telemetry(session)

    # The lap before has the hole in it, and none of this one is missing but
    # its first fifth of a second.
    assert ("AAA", 2) not in telemetry.laps
    lap = telemetry.laps[("AAA", 3)]
    whole = extract_telemetry(make_race()).laps[("AAA", 3)]
    assert 0.0 <= float(lap.distance_m[0]) < 25.0
    assert float(lap.distance_m[-1]) == pytest.approx(float(whole.distance_m[-1]), abs=25.0)
    assert float(lap.distance_m[-1]) == pytest.approx(TRACK_LENGTH_M, rel=0.01)
    assert float(lap.speed_kph[0]) == pytest.approx(float(whole.speed_kph[0]), abs=10.0)

    published = read(built(session), "telemetry/AAA.json")["laps"]
    third = next(row for row in published if row["lap_number"] == 3)
    assert third["distance_m"][0] < 25.0 and third["distance_m"][-1] < TRACK_LENGTH_M * 1.01


def test_the_sample_after_a_lap_is_its_neighbour_only_when_it_is_near():
    """The same at the far end: the car's data stops four seconds before the
    lap does and resumes a minute later."""
    session = make_race()
    _, end = lap_times(session, "BBB", 6)
    frame = session.car_data["2"]
    seconds = frame["SessionTime"].dt.total_seconds()
    session.car_data["2"] = frame[(seconds < end - 4.0) | (seconds > end + 60.0)]

    lap = extract_telemetry(session).laps[("BBB", 6)]
    whole = extract_telemetry(make_race()).laps[("BBB", 6)]

    # Past the car's last sample its speed is held for those four seconds,
    # and not drawn towards a sample from a minute into the next lap.
    after_the_last = lap.time_ms > lap.time_ms[-1] - 3_900
    assert after_the_last.sum() > 5 and len(set(lap.speed_kph[after_the_last].tolist())) == 1
    assert float(lap.distance_m[-1]) == pytest.approx(float(whole.distance_m[-1]), rel=0.01)


# --- R12-2: a stop in F1's pit-stop feed is followed by its driver and its place ----


def pit_line(clock: str, updates: object) -> bytes:
    return f"{clock}{json.dumps({'PitTimes': {'1': updates}})}\r\n".encode()


def stop(lap: str | None = None, stationary: str | None = None, lane: str | None = None, at: str | None = None):
    fields = {"RacingNumber": "1", "Lap": lap, "PitStopTime": stationary, "PitLaneTime": lane}
    entry: dict = {"PitStop": {name: value for name, value in fields.items() if value is not None}}
    if at is not None:
        entry["Timestamp"] = at
    return entry


def test_a_correction_that_gives_only_what_changed_corrects_the_stop_it_is_keyed_to():
    """F1's streams send a thing once and then only what changes. A new
    stationary time for a stop arrives as that one field, keyed by the stop's
    place. Read as a stop of its own it has no lap and no time and was
    dropped: the first figure stood."""
    feed = pit_line("01:00:00.000", [stop("5", "2.4", "19.9", "2026-06-28T13:00:00.000Z")]) + pit_line(
        "01:00:30.000", {"0": {"PitStop": {"PitStopTime": "2.5"}}}
    )

    assert parse_pit_stop_series(feed) == [
        {
            "driver_number": "1",
            "lap_number": 5,
            "stationary_ms": 2_500,
            "pit_lane_ms": 19_900,
            "time_utc": "2026-06-28T13:00:00.000Z",
        }
    ]


def test_a_correction_with_no_lap_is_not_placed_by_its_time_against_another_stop():
    """Two stops, laps 5 and 6. Then a correction of the first, keyed to it,
    with an empty lap and the time it was made, just after the second stop.
    Placed by that time it went to lap 6: lap 5 kept the old figure and lap 6
    lost its own."""
    feed = (
        pit_line("01:00:00.000", [stop("5", "2.4", "19.9", "2026-06-28T13:00:00.000Z")])
        + pit_line("01:01:40.000", {"1": stop("6", "3.2", "21.0", "2026-06-28T13:01:40.000Z")})
        + pit_line("01:01:42.000", {"0": stop("", "2.5", None, "2026-06-28T13:01:42.000Z")})
    )

    first, second = parse_pit_stop_series(feed)

    assert (first["lap_number"], first["stationary_ms"], first["pit_lane_ms"]) == (5, 2_500, 19_900)
    # When the stop was first reported, which is what places one with no lap.
    assert first["time_utc"] == "2026-06-28T13:00:00.000Z"
    assert (second["lap_number"], second["stationary_ms"], second["pit_lane_ms"]) == (6, 3_200, 21_000)


def test_a_stop_is_one_stop_however_many_lines_describe_it():
    feed = (
        # Reported with nothing to publish, then filled in; the list sent again; a lap added late.
        pit_line("01:00:00.000", [stop(None, None, None, "2026-06-28T13:00:00.000Z")])
        + pit_line("01:00:01.000", {"0": stop(None, "2.4", "19.9")})
        + pit_line("01:00:02.000", [stop("", "2.4", "19.9"), stop("9", "3.0", "20.5", "2026-06-28T13:09:00.000Z")])
        + pit_line("01:00:03.000", {"0": stop("5")})
        # Keys that are no place, and an entry that is no entry.
        + pit_line("01:00:04.000", {"_deleted": [0], "2": "gone"})
    )

    stops = parse_pit_stop_series(feed)

    assert [(item["lap_number"], item["stationary_ms"], item["time_utc"]) for item in stops] == [
        (5, 2_400, "2026-06-28T13:00:00.000Z"),
        (9, 3_000, "2026-06-28T13:09:00.000Z"),
    ]
    # A place that only ever gets a figure, with no lap and no time, cannot be put anywhere.
    assert parse_pit_stop_series(pit_line("01:00:00.000", {"3": {"PitStop": {"PitStopTime": "2.0"}}})) == []


# --- R12-3: a report with no lap is placed only where the timing singles a stop out ---


def report(at_ms: int, lane_ms: int | None = None) -> dict:
    moment = CLOCK_ZERO + pd.Timedelta(milliseconds=at_ms)
    return {"time_utc": moment.isoformat() + "Z", "pit_lane_ms": lane_ms}


ZERO = int(CLOCK_ZERO.value)


def test_a_car_the_timing_does_not_show_leaving_has_not_finished_a_stop():
    """In again on lap 6 and not seen to come out. A report made twenty
    seconds after it went in was put against lap 6, as if entering the pit
    lane were leaving it."""
    timed = {5: (1_000_000, 20_000), 6: (1_100_000, None)}

    assert normalize._lap_of_a_late_report(report(1_120_000), timed, ZERO) == 5
    assert normalize._lap_of_a_late_report(report(1_120_000), {6: (1_100_000, None)}, ZERO) is None


def test_a_report_two_stops_could_have_made_is_of_neither_unless_its_own_figure_tells_them_apart():
    timed = {5: (1_000_000, 20_000), 6: (1_090_000, 26_000)}

    # Both cars... both stops were left within two minutes of the report.
    assert normalize._lap_of_a_late_report(report(1_120_000), timed, ZERO) is None
    assert normalize._lap_of_a_late_report(report(1_120_000, lane_ms=25_800), timed, ZERO) == 6
    assert normalize._lap_of_a_late_report(report(1_120_000, lane_ms=20_300), timed, ZERO) == 5
    # Its figure is neither stop's.
    assert normalize._lap_of_a_late_report(report(1_120_000, lane_ms=45_000), timed, ZERO) is None
    # Alike to within the tolerance: still two.
    alike = {5: (1_000_000, 20_000), 6: (1_090_000, 21_000)}
    assert normalize._lap_of_a_late_report(report(1_120_000, lane_ms=20_500), alike, ZERO) is None
    # Made between the two, it can only be of the first.
    assert normalize._lap_of_a_late_report(report(1_050_000), timed, ZERO) == 5
    # A time that is no time places nothing, and nor does a session with no clock.
    assert normalize._lap_of_a_late_report({"time_utc": "soon"}, timed, ZERO) is None
    assert normalize._lap_of_a_late_report(report(1_050_000), timed, None) is None


def test_a_stop_another_report_names_is_not_taken_by_one_that_names_none():
    """The stand-in's one stop, reported with its lap; and a second report,
    with no lap, made half a minute after the car left. The timing has no
    other stop for it to be of, and it is not this one's: F1 said whose
    this one's figures are."""
    session = make_race()
    (timed,) = normalize.pit_stops(session, extras(pit_stops=False), normalize.driver_codes(session))
    left = CLOCK_ZERO + pd.Timedelta(milliseconds=timed.entry_time_ms + timed.duration_ms)
    late = (left + pd.Timedelta(seconds=30)).isoformat(timespec="milliseconds") + "Z"
    feed = pit_line("01:00:00.000", [stop("5", "2.4", "19.9", left.isoformat(timespec="milliseconds") + "Z")]) + pit_line(
        "01:00:40.000", {"1": stop("", "9.9", "20.1", late)}
    )

    (published,) = normalize.pit_stops(
        session, {**extras(pit_stops=False), PIT_STOP_SERIES: feed}, normalize.driver_codes(session)
    )

    assert (published.lap_number, published.stationary_ms, published.pit_lane_ms) == (5, 2_400, 19_900)
    assert normalize._lap_of_a_late_report(report(1_050_000), {5: (1_000_000, 20_000)}, ZERO, taken={5}) is None


# --- R12-4: the word FastF1 writes where a driver has no code is not a code ---------


def test_fastf1s_cast_writes_a_word_where_a_text_is_missing_and_no_reader_takes_it_for_one():
    """FastF1's own table of drivers, made as FastF1 makes it, with one
    driver F1's list gives a number and no code, broadcast name or country."""
    from fastf1.core import SessionResults

    listed = pd.DataFrame(
        {
            "DriverNumber": ["1", "2"],
            "Abbreviation": ["AAA", None],
            "BroadcastName": ["A ABLE", None],
            "FirstName": [None, "Ben"],
            "LastName": ["Able", "Baker"],
            "FullName": ["None Able", "Ben Baker"],
            "TeamName": ["Alpha Racing", np.nan],
            "CountryCode": ["NED", None],
        },
        index=["1", "2"],
    )

    results = SessionResults(listed, _force_default_cols=True)

    words = {results.loc["2", column] for column in ("Abbreviation", "BroadcastName", "CountryCode", "TeamName")}
    assert words and words <= MISSING_AS_TEXT
    assert results.loc["1", "FirstName"] in MISSING_AS_TEXT
    for column in ("Abbreviation", "BroadcastName", "CountryCode", "TeamName"):
        assert text(results.loc["2", column]) is None and not present(results.loc["2", column])
        assert text(results.loc["1", column]) is not None
    assert driver_codes(results, pd.DataFrame()) == {"1": "AAA", "2": "2"}
    assert normalize._full_name(results.loc["1"]) == "Able"
    assert normalize._full_name(results.loc["2"]) == "Ben Baker"


def without_a_code(session, *numbers: str):
    """``session`` as FastF1 loads it when F1's driver list has these drivers and gives them no code."""
    for number in numbers:
        session.results.loc[number, ["Abbreviation", "BroadcastName", "CountryCode"]] = "None"
        session.laps.loc[session.laps["DriverNumber"] == number, "Driver"] = "None"
    return session


def test_a_driver_f1s_list_gives_no_code_is_known_by_the_car_number():
    """Published as driver ``NONE`` from ``telemetry/NONE.json``, of country
    ``None``, and counted as being in the driver list because the word is a
    broadcast name. Two such drivers were one driver."""
    session = without_a_code(make_race(), "2", "3")

    codes = normalize.driver_codes(session)
    measured = measure_coverage(session, "R", extras())
    files = built(session)

    assert codes == {"1": "AAA", "2": "2", "3": "3"}
    assert {(row["code"], row["country"], row["full_name"]) for row in read(files, "drivers.json")} == {
        ("AAA", None, "Anna Able"),
        ("2", None, "Ben Baker"),
        ("3", None, "Cara Cole"),
    }
    assert {"telemetry/2.json", "telemetry/3.json"} <= set(files) and "telemetry/NONE.json" not in files
    assert {row["driver_code"] for row in read(files, "laps.json")} == {"AAA", "2", "3"}
    assert not any(b"NONE" in data or b'"None"' in data for data in files.values())
    # An entry with no name in it is not an entry in the driver list.
    assert (measured["drivers"]["2"]["in_driver_list"], measured["drivers"]["AAA"]["in_driver_list"]) == (False, True)
    assert ("driver_list", "2") in {(item.bar, item.driver) for item in evaluate_coverage(measured)}
    assert measured["drivers"]["2"]["car_laps"] == LAPS and measured["drivers"]["3"]["timing_laps"] == 9


def official():
    """The stand-in's classification as a build has it: with the table that is merged into the session."""
    result = classification()
    frame = pd.DataFrame(result.rows)
    frame["totalRaceTime"] = pd.to_timedelta(frame["totalRaceTime"], unit="ms")
    return type(result)(rows=result.rows, fingerprint=result.fingerprint, frame=frame)


def built_as_a_build_does(session, result, found=None):
    found = extras() if found is None else found
    measurement = measure_coverage(session, "R", found)
    if result is not None:
        measurement = apply_classification(measurement, result.laps_by_number)
        merge_into_session(session, result)
        # A FastF1 session gives out the table the merge leaves in ``_results``.
        session.results = session._results
    return build_artifacts(session, IDENTITY, result, found, measurement)


def test_the_classification_names_a_driver_the_list_does_not():
    session = without_a_code(make_race(), "2")

    files = built_as_a_build_does(session, official())

    assert {row["code"] for row in read(files, "drivers.json")} == {"AAA", "BBB", "CCC"}
    assert "telemetry/BBB.json" in files and "telemetry/2.json" not in files
    assert [row["driver_code"] for row in read(files, "results.json")] == ["AAA", "BBB", "CCC"]
    # The record was made when the fetch knew the car by number only, and the
    # generation says of it what the record says, under the name it now has.
    coverage = read(files, "coverage.json")
    assert [row["driver_code"] for row in coverage["drivers"]] == ["AAA", "BBB", "CCC"]
    assert {"bar": "driver_list", "driver": "BBB", "detail": "driver is missing from F1's driver list"} in coverage[
        "shortfalls"
    ]


# --- R12-5: with no driver list a lap is still its car's ----------------------------


def without_a_driver_list(session):
    """``session`` as FastF1 loads it when F1's driver list did not arrive and Jolpica is out of reach."""
    from fastf1.core import SessionResults

    session.results = SessionResults(_force_default_cols=True)
    session.laps["Driver"] = ""
    session.laps["Team"] = ""
    return session


def test_a_session_with_no_driver_list_is_built_from_the_classification():
    """The Austrian race loaded with ``driver_info`` taken out of its archive
    has 1,339 laps and 22 cars' data, and an empty code on every lap. The
    result was merged in and named everyone; the laps were read by their
    empty code, every one was skipped, and the build failed for good with
    "the session's timing names no driver and lap"."""
    session = without_a_driver_list(make_race())

    files = built_as_a_build_does(session, official())

    assert {(row["code"], row["full_name"]) for row in read(files, "drivers.json")} == {
        ("AAA", "Anna Able"),
        ("BBB", "Ben Baker"),
        ("CCC", "Cara Cole"),
    }
    assert len(read(files, "laps.json")) == len(read(built(), "laps.json"))
    assert {"telemetry/AAA.json", "telemetry/BBB.json", "telemetry/CCC.json"} <= set(files)
    assert read(files, "pit-stops.json") == read(built(), "pit-stops.json")
    assert read(files, "stints.json") == read(built(), "stints.json")
    coverage = read(files, "coverage.json")
    assert coverage["complete"] is False
    assert {(item["bar"], item["driver"]) for item in coverage["shortfalls"]} >= {
        ("driver_list", "AAA"),
        ("driver_list", "BBB"),
        ("driver_list", "CCC"),
    }


def test_with_no_driver_list_and_no_classification_the_cars_are_known_by_number():
    session = without_a_driver_list(make_race())

    files = built_as_a_build_does(session, None)

    assert [(row["code"], row["full_name"], row["number"], row["team"]) for row in read(files, "drivers.json")] == [
        ("1", "1", 1, None),
        ("2", "2", 2, None),
        ("3", "3", 3, None),
    ]
    assert {"telemetry/1.json", "telemetry/2.json", "telemetry/3.json"} <= set(files)
    results = read(files, "results.json")
    assert all(row["provisional"] for row in results) and {row["driver_code"] for row in results} == {"1", "2", "3"}
    assert len(read(files, "laps.json")) == len(read(built(), "laps.json"))
    replay = read(files, "position-replay.json")
    assert [driver["driver_code"] for driver in replay["drivers"]] == ["1", "2", "3"]


# --- R12-6: the lap a session has reached is the timing's to say --------------------


def test_the_replay_counts_a_lap_the_leader_started_with_neither_feed_to_show_it():
    """BBB leads onto lap 8 and neither of its feeds has anything for that
    lap. The count was taken from the laps that have samples in a frame, so
    the session stayed on lap 7 until the next car started the eighth."""
    session = make_race()
    leader, _ = lap_times(session, "BBB", 8)
    next_car = min(lap_times(session, code, 8)[0] for code in ("AAA", "CCC"))
    assert next_car - leader > 3.0
    for feed in (session.car_data, session.pos_data):
        seconds = feed["2"]["SessionTime"].dt.total_seconds()
        feed["2"] = feed["2"][(seconds < leader - 15.0) | (seconds > leader + 40.0)]

    replay = artifact_json(position_replay(extract_telemetry(session)))

    whole = artifact_json(position_replay(extract_telemetry(make_race())))
    assert replay["lap_number"] == whole["lap_number"]
    frame = replay["time_ms"].index(int(leader * 1000) // replay["interval_ms"] * replay["interval_ms"])
    assert int(next_car * 1000) >= replay["time_ms"][frame] + replay["interval_ms"]
    assert replay["lap_number"][frame] == 8
    ben = next(driver for driver in replay["drivers"] if driver["driver_code"] == "BBB")
    assert ben["x"][frame] is None and replay["drivers"][0]["x"][frame] is not None


def test_a_lap_fastf1_added_for_a_car_that_stopped_is_not_one_the_session_reached():
    telemetry = extract_telemetry(make_race())

    # CCC retired after lap 9, and FastF1 gives it a tenth.
    assert sorted(telemetry.lap_started_ms) == list(range(1, LAPS + 1))
    assert telemetry.lap_started_ms[10] == round(min(lap_times(make_race(), code, 10)[0] for code in ("AAA", "BBB")) * 1000)


# --- R12-7: a reading F1 did not send is not a zero ---------------------------------

# The first lines of the 2026 Austrian GP's weather feed, as F1 sent them.
AUSTRIAN_WEATHER = (
    b'\xef\xbb\xbf00:00:38.376{"AirTemp":"33.6","Humidity":"30.3","Pressure":"941.8","Rainfall":"0",'
    b'"TrackTemp":"53.2","WindDirection":"67","WindSpeed":"1.0"}\r\n'
    b'00:01:38.372{"AirTemp":"33.8","Humidity":"29.8","Pressure":"941.8","Rainfall":"0",'
    b'"TrackTemp":"53.3","WindDirection":"285","WindSpeed":"0.9"}\r\n'
)
EVERY_READING = frozenset({"AirTemp", "Humidity", "Pressure", "Rainfall", "TrackTemp", "WindDirection", "WindSpeed"})


def test_every_line_of_a_real_weather_feed_gives_every_reading():
    assert weather_readings_sent(AUSTRIAN_WEATHER) == {38_376: EVERY_READING, 98_372: EVERY_READING}


@pytest.mark.parametrize("junk", [b"", b"not a stream line\r\n", b"00:00:01.000[]\r\n", b"\xff\xfe\x00", b"00:00:01.000" + b"[" * 5000])
def test_reading_the_weather_feed_never_raises(junk):
    assert weather_readings_sent(junk) == {}


def weather_as_fastf1_parses(lines: bytes) -> pd.DataFrame:
    """The weather table FastF1's own parser makes of these lines of the feed."""
    from fastf1 import _api

    response = [
        [line[:12], json.loads(line[12:])] for line in lines.decode("utf-8-sig").splitlines() if line.strip()
    ]
    return pd.DataFrame(_api.weather_data.__wrapped__("", response=response))


SENSORS_OUT = (
    b'00:10:00.000{"AirTemp":"21.0"}\r\n'
    b'00:11:00.000{"AirTemp":"21.2","Humidity":"","Pressure":"1000.1","Rainfall":"1","TrackTemp":"",'
    b'"WindDirection":"10","WindSpeed":"0.0"}\r\n'
    b'00:12:00.000{"AirTemp":"21.4","Humidity":"40.0","Pressure":"1000.2","Rainfall":"0","TrackTemp":"0.0",'
    b'"WindDirection":"12","WindSpeed":"0.0"}\r\n'
)


def test_a_reading_f1_left_out_is_published_as_nothing_and_a_zero_it_sent_as_zero():
    """FastF1's parser writes 0 for a reading a line leaves out or sends
    empty, and "no rain". A line with the air temperature and nothing else
    was published as a track at 0 degrees, 0% humidity, still air and dry."""
    session = make_race()
    session.weather_data = weather_as_fastf1_parses(SENSORS_OUT)
    # What FastF1 made of the first line.
    assert session.weather_data.iloc[0][["TrackTemp", "Humidity", "WindSpeed", "Rainfall"]].tolist() == [0.0, 0.0, 0.0, False]

    samples = [
        artifact_json(sample)
        for sample in normalize.weather(session, "P1", {WEATHER_SERIES: SENSORS_OUT})
    ]

    assert samples == [
        {"time_ms": 600_000, "lap_number": None, "air_temp_c": 21.0, "track_temp_c": None,
         "humidity_pct": None, "rainfall": None, "wind_speed_kph": None},
        {"time_ms": 660_000, "lap_number": None, "air_temp_c": 21.2, "track_temp_c": None,
         "humidity_pct": None, "rainfall": True, "wind_speed_kph": 0.0},
        {"time_ms": 720_000, "lap_number": None, "air_temp_c": 21.4, "track_temp_c": 0.0,
         "humidity_pct": 40.0, "rainfall": False, "wind_speed_kph": 0.0},
    ]


def test_a_sample_with_no_line_of_the_feed_to_its_name_has_no_readings():
    session = make_race()
    session.weather_data = weather_as_fastf1_parses(SENSORS_OUT)

    first, *_ = normalize.weather(session, "P1", {WEATHER_SERIES: SENSORS_OUT.split(b"\r\n", 1)[1]})

    assert (first.time_ms, first.air_temp_c, first.rainfall) == (600_000, None, None)


def test_a_snapshot_from_before_the_feed_was_kept_is_published_as_fastf1_has_it():
    session = make_race()
    session.weather_data = weather_as_fastf1_parses(SENSORS_OUT)

    first, *_ = normalize.weather(session, "P1", extras())

    assert (first.air_temp_c, first.track_temp_c, first.rainfall, first.wind_speed_kph) == (21.0, 0.0, False, 0.0)


def test_the_summary_says_nothing_of_what_no_sample_has():
    session = make_race()
    session.weather_data = weather_as_fastf1_parses(SENSORS_OUT[: SENSORS_OUT.index(b"\r\n") + 2])

    files = built(session, found={**extras(), WEATHER_SERIES: SENSORS_OUT})

    assert read(files, "summary.json")["weather_summary"] == "air 21.0-21.0C"
    assert read(files, "weather.json")[0]["rainfall"] is None


def test_the_stand_in_race_builds_the_same_with_its_weather_feed_beside_it():
    session = make_race()

    def clock(moment: pd.Timedelta) -> str:
        seconds, milliseconds = divmod(round(moment.total_seconds() * 1000), 1000)
        return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}.{milliseconds:03d}"

    feed = b"".join(
        (
            f"{clock(row.Time)}"
            f'{{"AirTemp":"{row.AirTemp}","Humidity":"{row.Humidity}","Pressure":"1000.0","Rainfall":"0",'
            f'"TrackTemp":"{row.TrackTemp}","WindDirection":"0","WindSpeed":"{row.WindSpeed}"}}\r\n'
        ).encode()
        for row in session.weather_data.itertuples()
    )

    assert built(make_race(), found={**extras(), WEATHER_SERIES: feed}) == built()


# --- R12-8: each version of the measurement keeps its own corrections ---------------


def test_a_corrections_name_carries_the_measurement_it_is_of():
    assert layout.remeasurement_name(2) == layout.REMEASUREMENT_NAME == "remeasured.json"
    assert layout.remeasurement_name(3) == "remeasured-m3.json"
    for key in ("archive/sessions/1/a/remeasured.json", "archive/sessions/1/a/remeasured-m3.json"):
        assert layout.is_remeasurement_key(key)
    for key in ("archive/sessions/1/a/snapshot.json", "archive/sessions/1/a/remeasured-m3.json.bak", "remeasured.json"):
        assert not layout.is_remeasurement_key(key)
    for version in (0, -1, True, "3", 2.0):
        with pytest.raises(ValueError):
            layout.remeasurement_name(version)


def whole_measurement_of_a_newer_version(written) -> dict:
    return {**written.coverage, "measurement_version": MEASUREMENT_VERSION + 1}


@pytest.mark.parametrize(
    "claimed",
    [
        lambda written: {"measurement_version": MEASUREMENT_VERSION + 1, "feeds": {}, "drivers": {}},
        lambda written: {"measurement_version": MEASUREMENT_VERSION + 1, "feeds": {"x": True}, "drivers": {"A": {}}},
        whole_measurement_of_a_newer_version,
    ],
    ids=["an empty outline", "an outline with something in it", "a whole measurement"],
)
def test_nothing_under_this_versions_name_has_a_say_unless_it_is_this_versions(claimed, tmp_path, monkeypatch):
    """A correction that named a newer measurement was not read, and was
    stood aside for. However much of an outline it was asked to have, an
    object with that outline and nothing true in it answered "newer" for its
    session on every run. A newer measurement's corrections are now another
    object, so anything under this name that is not this version's is not a
    correction."""
    world = Archive(monkeypatch, EVERYONE)
    written = world.snapshot(tmp_path, recorded=make_session(), feeds=without_positions_for_one_driver(10))
    world.store.put(
        correction_key(written),
        dump_json(
            {
                "schema_version": 1,
                "snapshot_id": written.snapshot_id,
                "pipeline_version": layout.PIPELINE_VERSION + 1,
                "coverage": claimed(written),
            }
        ),
    )

    (listed,) = list_snapshots(world.store)
    assert (listed.corrected_by, listed.complete) == (None, True)

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert read_pointer(world.store, AUSTRIA)[0].complete is False
    assert correction(world.store, written)["pipeline_version"] == layout.PIPELINE_VERSION
    assert correction(world.store, written)["coverage"]["measurement_version"] == MEASUREMENT_VERSION


def test_a_newer_measurements_correction_is_never_read_written_or_copied(tmp_path, monkeypatch, capsys):
    spool, bucket = DirectoryStore(tmp_path / "spool"), DirectoryStore(tmp_path / "bucket")
    written = write_snapshot(spool, fetched_session(tmp_path), now=FIRST_FETCH)
    theirs = f"{layout.snapshot_prefix(AUSTRIA, written.snapshot_id)}{layout.remeasurement_name(MEASUREMENT_VERSION + 1)}"
    newer = dump_json(
        {
            "schema_version": 1,
            "snapshot_id": written.snapshot_id,
            "pipeline_version": layout.PIPELINE_VERSION + 1,
            "coverage": whole_measurement_of_a_newer_version(written),
        }
    )
    spool.put(theirs, newer)

    (listed,) = list_snapshots(spool)
    write_remeasurement(spool, listed, measure(without_positions_for_one_driver(10)))
    (corrected,) = list_snapshots(spool)

    assert (listed.corrected_by, listed.correction_etag) == (None, None)
    assert corrected.complete is False and corrected.corrected_by == layout.PIPELINE_VERSION
    assert spool.get(theirs).data == newer
    output = copy(tmp_path / "spool", tmp_path / "bucket", capsys)
    assert "Left 2 correction(s) of a snapshot's record where they are" in output
    assert bucket.get(theirs) is None and bucket.get(correction_key(written)) is None


# --- the laps of the telemetry index say which of them are clean -------------------


def test_the_telemetry_index_carries_each_laps_flags_from_the_timing():
    """The frontend opened a comparison on a deleted lap: the index gave a
    lap's time and compound and nothing to tell a clean lap by."""
    files = built()
    laps = {(row["driver_code"], row["lap_number"]): row for row in read(files, "laps.json")}

    for entry in read(files, "telemetry/index.json")["drivers"]:
        for position, number in enumerate(entry["lap_number"]):
            timed = laps[(entry["driver_code"], number)]
            for flag in ("is_accurate", "is_deleted", "is_pit_in_lap", "is_pit_out_lap"):
                assert entry[flag][position] is timed[flag], (entry["driver_code"], number, flag)
    ben = next(entry for entry in read(files, "telemetry/index.json")["drivers"] if entry["driver_code"] == "BBB")
    assert ben["is_deleted"].count(True) == 1 and ben["is_deleted"][ben["lap_number"].index(7)] is True


# --- what the real archive showed when each feed was taken out in turn --------------


def test_a_driver_with_half_a_name_is_not_called_none():
    session = without_a_code(make_race(), "2")
    session.results["FirstName"] = ["Anna", "None", "Cara"]
    session.results["LastName"] = ["Able", "Baker", "Cole"]
    session.results.loc["2", "FullName"] = "None Baker"

    drivers = {row["code"]: row["full_name"] for row in read(built(session), "drivers.json")}

    assert drivers == {"AAA": "Anna Able", "2": "Baker", "CCC": "Cara Cole"}


def test_a_lap_fastf1_added_does_not_start_a_lap_for_the_session_however_early_it_is_put():
    session = make_race()
    added = session.laps["FastF1Generated"].astype(bool)
    assert int(added.sum()) == 1 and session.laps.loc[added, "LapNumber"].iloc[0] == 10
    session.laps.loc[added, "LapStartTime"] = pd.Timedelta(seconds=1000)

    started = extract_telemetry(session).lap_started_ms

    assert started[10] > 1_300_000 and started == extract_telemetry(make_race()).lap_started_ms


class NoLaps:
    """A FastF1 session whose laps could not be made: asking for them raises, as FastF1 does."""

    def __init__(self, session) -> None:
        self.__dict__.update({name: value for name, value in vars(session).items() if name != "laps"})

    @property
    def laps(self):
        raise RuntimeError("The data you are trying to access has not been loaded yet. See `Session.load`")


def test_a_session_fastf1_made_no_laps_of_fails_as_a_session_with_no_laps():
    """With the track status, the tyre data or the session status out of the
    Austrian race's archive, FastF1 makes no laps and raises when asked for
    them. Putting the first-lap times in asked, and the build failed there
    with FastF1's error and not with the reason."""
    session = NoLaps(make_race())

    merge_into_session(session, type(official())(rows=official().rows, fingerprint="x", frame=official().frame, first_lap_ms={"1": 95_000}))
    session.results = session._results

    assert session.results.loc["1", "Abbreviation"] == "AAA"
    with pytest.raises(normalize.SessionDataError, match="The session has no laps"):
        build_artifacts(session, IDENTITY, official(), extras(), measure_coverage(session, "R", extras()))
