"""A loaded session as published rows: the defects of the old format, one test each.

docs/architecture-review-findings.md, AR-05 (pandas strings for times), AR-08
(lap times cut off, ``NaN`` passed through ``str``), AR-16 (one pit-stop
duration), AR-17 (no official corners), AR-20 (identity from the round).
"""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from f1data import normalize
from f1data.coverage import apply_classification, measure_coverage
from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES
from f1data.models import Compound, DistanceSource, artifact_json
from f1data.telemetry import SessionTelemetry, extract_telemetry
from tests.race import (
    CORNERS,
    IDENTITY,
    LAPS,
    PIT_LAP,
    RACE_START_SECONDS,
    TRACK_LENGTH_M,
    classification,
    extras,
    make_race,
)


def rows(models):
    return [artifact_json(model) for model in models]


def lap(session, code, number):
    return next(
        row for row in normalize.laps(session) if (row.driver_code, row.lap_number) == (code, number)
    )


# --- times ---------------------------------------------------------------------


def test_a_lap_time_is_rounded_to_the_millisecond_not_cut_off():
    """The old normaliser took ``int(seconds * 1000)``. FastF1 holds some
    durations a nanosecond short of the millisecond F1 sent, and 32.696 s as a
    float times 1000 is 32695.999..., so 152 sector times of the 2026 Austrian
    GP came out a millisecond low."""
    session = make_race()
    mine = (session.laps["Driver"] == "BBB") & (session.laps["LapNumber"] == 4)
    session.laps.loc[mine, "Sector2Time"] = pd.Timedelta(32_695_999_999, unit="ns")
    session.laps.loc[mine, "LapTime"] = pd.Timedelta(seconds=81.2345)

    row = lap(session, "BBB", 4)

    assert row.sector_2_ms == 32_696
    assert row.lap_time_ms == 81_234 or row.lap_time_ms == 81_235
    assert isinstance(row.lap_time_ms, int)


def test_no_time_is_a_pandas_string_anywhere():
    session = make_race()
    codes = normalize.driver_codes(session)
    everything = json.dumps(
        [
            rows(normalize.laps(session)),
            rows(normalize.pit_stops(session, extras(), codes)),
            rows(normalize.weather(session, "R")),
            rows(normalize.race_control(session)),
            rows(normalize.results(classification(), session, codes)),
        ]
    )

    for forbidden in ("0 days", "NaT", "NaN", "nan", "None", "Timedelta"):
        assert forbidden not in everything, forbidden


def test_positions_in_time_count_from_the_session_clock():
    session = make_race()

    stop = normalize.pit_stops(session, extras(), normalize.driver_codes(session))[0]
    messages = normalize.race_control(session)
    weather = normalize.weather(session, "R")

    came_in = session.laps.query("Driver == 'AAA' and LapNumber == @PIT_LAP").iloc[0]["PitInTime"]
    assert stop.entry_time_ms == round(came_in.total_seconds() * 1000)
    # Race control sends wall-clock times; they are put on the same clock.
    assert [message.time_ms for message in messages] == [540_000, 842_500]
    assert weather[0].time_ms == 30_000


# --- missing values ------------------------------------------------------------


def test_a_missing_value_is_null_never_a_string():
    session = make_race()
    mine = session.laps["Driver"] == "CCC"
    session.laps.loc[mine, "TrackStatus"] = np.nan
    session.laps.loc[mine, "Compound"] = np.nan
    session.laps.loc[mine, "Position"] = np.nan
    session.laps.loc[mine, "Stint"] = np.nan

    row = lap(session, "CCC", 2)

    assert (row.track_status, row.compound, row.position, row.stint) == (None, None, None, None)
    # A used set F1 gave no age for, and a lap F1 did not time.
    assert lap(session, "AAA", 8).tyre_age is None
    assert lap(session, "AAA", 1).lap_time_ms is None


@pytest.mark.parametrize("value", ["", "None", "nan", "UNKNOWN", "TEST_UNKNOWN", None, np.nan])
def test_a_compound_f1_did_not_report_is_null(value):
    session = make_race()
    session.laps["Compound"] = value

    assert {row.compound for row in normalize.laps(session)} == {None}
    assert {stint.compound for stint in normalize.stints(normalize.laps(session))} == {None}


def test_a_driver_with_no_country_or_team_has_null_not_an_empty_string():
    session = make_race()
    session.results.loc["3", "TeamName"] = np.nan
    session.results.loc["3", "TeamColor"] = np.nan

    drivers = {driver.code: driver for driver in normalize.drivers(session, normalize.driver_codes(session))}

    assert drivers["AAA"].country is None
    assert drivers["CCC"].team is None
    assert artifact_json(drivers["AAA"].team) == {"team_id": "alpha-racing", "name": "Alpha Racing", "color": "#FF8000"}
    assert (drivers["BBB"].driver_id, drivers["BBB"].number, drivers["BBB"].full_name) == ("bbb", 2, "Ben Baker")


# --- laps and stints -----------------------------------------------------------


def test_laps_keep_their_flags_and_a_lap_fastf1_added_is_still_a_lap():
    session = make_race()

    built = normalize.laps(session)

    assert len(built) == len(session.laps)
    assert (lap(session, "AAA", PIT_LAP).is_pit_in_lap, lap(session, "AAA", PIT_LAP + 1).is_pit_out_lap) == (True, True)
    assert lap(session, "BBB", 7).is_deleted and not lap(session, "BBB", 6).is_deleted
    assert lap(session, "AAA", 3).track_status == "12"
    added = lap(session, "CCC", 10)
    assert (added.lap_time_ms, added.is_accurate, added.position) == (None, False, None)


def test_a_session_with_no_timing_cannot_be_published():
    session = make_race()
    session.laps = session.laps.iloc[0:0]

    with pytest.raises(normalize.SessionDataError, match="no laps"):
        normalize.laps(session)


def test_stints_follow_the_tyres_and_an_unknown_compound_is_its_own_run():
    stints = rows(normalize.stints(normalize.laps(make_race())))

    assert [stint for stint in stints if stint["driver_code"] == "AAA"] == [
        {"driver_code": "AAA", "stint": 1, "compound": "MEDIUM", "start_lap": 1, "end_lap": 5, "lap_count": 5},
        {"driver_code": "AAA", "stint": 2, "compound": "HARD", "start_lap": 6, "end_lap": 9, "lap_count": 4},
        {"driver_code": "AAA", "stint": 2, "compound": None, "start_lap": 10, "end_lap": 12, "lap_count": 3},
    ]
    assert normalize.laps(make_race())[0].compound is Compound.MEDIUM


# --- the result ----------------------------------------------------------------


def test_the_result_is_the_classification_with_a_time_for_the_winner_and_gaps_behind():
    session = make_race()

    result = rows(normalize.results(classification(), session, normalize.driver_codes(session)))

    assert result == [
        {
            "position": 1, "driver_code": "AAA", "classified_position": "1", "status": "Finished", "points": 25.0,
            "grid": 2, "time_ms": 990_500, "gap_ms": None, "laps_down": None, "behind_at_flag_ms": None,
            "laps": 12, "provisional": False,
        },
        {
            "position": 2, "driver_code": "BBB", "classified_position": "2", "status": "Finished", "points": 18.0,
            "grid": 1, "time_ms": None, "gap_ms": 4_000, "laps_down": None, "behind_at_flag_ms": None,
            "laps": 12, "provisional": False,
        },
        {
            "position": 3, "driver_code": "CCC", "classified_position": "R", "status": "Retired", "points": 0.0,
            "grid": 3, "time_ms": None, "gap_ms": None, "laps_down": None, "behind_at_flag_ms": None,
            "laps": 9, "provisional": False,
        },
    ]


def test_a_lapped_driver_has_laps_down_and_no_gap():
    """The old format published one duration for everyone. For a lapped driver
    Jolpica's is the time they took the flag after the winner, a lap short: in
    the 2026 Austrian GP ninth place, a lap down, showed 15.3 s against 45.7 s
    for eighth."""
    session = make_race()
    official = classification()
    official.rows[1].update(laps=11, status="Lapped", totalRaceTime=15_334)
    official.rows[2].update(laps=11, positionText="3", status="Lapped", totalRaceTime=None)

    _, lapped, no_time = normalize.results(official, session, normalize.driver_codes(session))

    assert (lapped.gap_ms, lapped.laps_down, lapped.behind_at_flag_ms) == (None, 1, 15_334)
    assert (no_time.gap_ms, no_time.laps_down, no_time.behind_at_flag_ms) == (None, 1, None)


def test_a_driver_todays_classification_omits_is_unclassified_whatever_the_archive_recorded():
    """Taken out of the result after the session was fetched: the archived
    result still has them second with 18 points. They are published as a
    driver with no result, not with zeros and not with what the archive said."""
    session = make_race()
    official = classification()
    official.rows[:] = [official.rows[0], {**official.rows[2], "position": 2, "positionText": "2"}]

    result = rows(normalize.results(official, session, normalize.driver_codes(session)))

    assert [(row["position"], row["driver_code"]) for row in result] == [(1, "AAA"), (2, "CCC"), (None, "BBB")]
    assert result[2] == {
        "position": None, "driver_code": "BBB", "classified_position": None, "status": None, "points": None,
        "grid": None, "time_ms": None, "gap_ms": None, "laps_down": None, "behind_at_flag_ms": None,
        "laps": None, "provisional": False,
    }
    # They are still a driver of the session, with laps and telemetry.
    assert "BBB" in {driver.code for driver in normalize.drivers(session, normalize.driver_codes(session))}


def test_a_driver_who_set_no_lap_and_is_not_classified_has_no_row():
    session = make_race()
    session.laps = session.laps[session.laps["Driver"] != "CCC"]
    official = classification()
    official.rows.pop()

    result = normalize.results(official, session, normalize.driver_codes(session))

    assert [row.driver_code for row in result] == ["AAA", "BBB"]


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda rows: rows[1].update(position=1), "unique positions"),
        (lambda rows: rows[1].update(status=None), "missing status for BBB"),
        (lambda rows: rows[2].update(points=float("nan")), "missing points for CCC"),
        (lambda rows: rows.pop(), "unique positions"),
        (lambda rows: rows[1].update(number=1, driverCode="AAA"), "names a driver twice"),
    ],
)
def test_a_broken_classification_is_not_published(damage, message):
    official = classification()
    damage(official.rows)
    if len(official.rows) == 2:
        official.rows.pop()
    session = make_race()

    with pytest.raises(normalize.SessionDataError, match=message):
        normalize.results(official, session, normalize.driver_codes(session))


def test_with_no_classification_the_result_is_the_order_on_track_and_says_so():
    """Jolpica has had no result for the whole retry window. The session is
    published as partial, and its result comes from the timing alone."""
    session = make_race()

    result = normalize.results(None, session, normalize.driver_codes(session))

    assert [(row.position, row.driver_code, row.laps) for row in result] == [(1, "BBB", 12), (2, "AAA", 12), (3, "CCC", 9)]
    assert all(row.provisional for row in result)
    assert {(row.classified_position, row.status, row.points, row.grid, row.time_ms) for row in result} == {
        (None, None, None, None, None)
    }
    finished = session.laps[session.laps["LapNumber"] == LAPS].set_index("Driver")["Time"]
    behind = round((finished["AAA"] - finished["BBB"]).total_seconds() * 1000)
    # The leader has no gap, a finisher the time they took the flag behind, a retirement none.
    assert [row.gap_ms for row in result] == [None, behind, None]
    assert {(row.laps_down, row.behind_at_flag_ms) for row in result} == {(None, None)}


def test_a_provisional_result_tells_a_lapped_finisher_from_a_retirement():
    session = make_race()
    # CCC is still running at the end, three laps down, and takes the flag after the leader.
    flag = session.laps[session.laps["LapNumber"] == LAPS]["Time"].min()
    mine = (session.laps["Driver"] == "CCC") & (session.laps["LapNumber"] == 9)
    session.laps.loc[mine, "Time"] = flag + pd.Timedelta(seconds=30)

    result = normalize.results(None, session, normalize.driver_codes(session))

    assert [(row.driver_code, row.gap_ms, row.laps_down, row.behind_at_flag_ms) for row in result][2] == (
        "CCC", None, 3, 30_000,
    )


def test_a_driver_who_set_no_lap_is_last_in_a_provisional_result():
    session = make_race()
    session.laps = session.laps[session.laps["Driver"] != "AAA"]

    result = normalize.results(None, session, normalize.driver_codes(session))

    assert [(row.driver_code, row.laps, row.gap_ms) for row in result][-1] == ("AAA", 0, None)


# --- pit stops -----------------------------------------------------------------


def test_a_pit_stop_carries_both_of_f1s_figures_beside_the_timings_and_says_which_is_which():
    session = make_race()

    stops = rows(normalize.pit_stops(session, extras(), normalize.driver_codes(session)))

    assert stops == [
        {
            "driver_code": "AAA",
            "lap_number": PIT_LAP,
            "entry_time_ms": stops[0]["entry_time_ms"],
            "duration_ms": 20_000,
            "stationary_ms": 2_400,
            "pit_lane_ms": 19_900,
            "sources": {"duration_ms": "timing", "stationary_ms": "pit_stop_series", "pit_lane_ms": "pit_stop_series"},
        }
    ]


def test_a_stop_f1s_feed_does_not_cover_has_the_timings_figure_only():
    """Three drivers of the 2026 Austrian GP are not in F1's pit-stop feed at all."""
    session = make_race()

    (stop,) = normalize.pit_stops(session, extras(pit_stops=False), normalize.driver_codes(session))

    assert (stop.duration_ms, stop.stationary_ms, stop.pit_lane_ms) == (20_000, None, None)
    assert artifact_json(stop.sources) == {"duration_ms": "timing", "stationary_ms": None, "pit_lane_ms": None}


def test_a_car_that_does_not_come_back_out_has_no_duration():
    session = make_race()
    session.laps.loc[session.laps["PitOutTime"].notna(), "PitOutTime"] = pd.NaT

    (stop,) = normalize.pit_stops(session, extras(pit_stops=False), normalize.driver_codes(session))

    assert stop.duration_ms is None and stop.sources.duration_ms is None and stop.entry_time_ms is not None


def test_stops_are_matched_by_driver_and_lap_and_one_only_the_feed_has_is_kept():
    session = make_race()
    feed = {
        PIT_STOP_SERIES: (
            b'01:00:00.000{"PitTimes":{"1":[{"PitStop":{"RacingNumber":"1","PitStopTime":"9.9","PitLaneTime":"30.0","Lap":"5"}}]}}\r\n'
            # F1 corrects the same stop, then reports one for another lap and one for another driver.
            b'01:00:05.000{"PitTimes":{"1":[{"PitStop":{"RacingNumber":"1","PitStopTime":"2.4","PitLaneTime":"19.9","Lap":"5"}}]}}\r\n'
            b'01:00:09.000{"PitTimes":{"1":{"1":{"PitStop":{"RacingNumber":"1","PitStopTime":"2.0","PitLaneTime":"18.0","Lap":"6"}}}}}\r\n'
            b'01:00:10.000{"PitTimes":{"2":[{"PitStop":{"RacingNumber":"2","PitStopTime":"3.1","PitLaneTime":"21.0","Lap":"8"}}]}}\r\n'
            b'01:00:11.000{"PitTimes":{"99":[{"PitStop":{"RacingNumber":"99","PitStopTime":"3.1","PitLaneTime":"21.0","Lap":"8"}}]}}\r\n'
        )
    }

    stops = normalize.pit_stops(session, feed, normalize.driver_codes(session))

    assert [
        (stop.driver_code, stop.lap_number, stop.duration_ms, stop.stationary_ms, stop.entry_time_ms is None)
        for stop in stops
    ] == [
        ("AAA", 5, 20_000, 2_400, False),
        ("AAA", 6, None, 2_000, True),
        ("BBB", 8, None, 3_100, True),
    ]


# --- weather and race control --------------------------------------------------


def test_weather_is_every_sample_with_the_lap_the_leader_was_on():
    """The old format kept about 25 samples and never filled in the lap."""
    session = make_race()

    weather = normalize.weather(session, "R")

    assert len(weather) == len(session.weather_data)
    by_time = {sample.time_ms: sample.lap_number for sample in weather}
    assert by_time[30_000] is None  # before the start
    assert by_time[int(RACE_START_SECONDS * 1000) + 30_000] == 1
    assert by_time[int(RACE_START_SECONDS * 1000) + 90_000] == 2
    assert max(number for number in by_time.values() if number) == LAPS
    assert weather[-1].lap_number is None  # after the flag
    assert {sample.lap_number for sample in normalize.weather(session, "Q")} == {None}


def test_wind_speed_is_in_the_unit_its_name_says():
    """F1 reports metres a second. The old format published that as wind_speed_kph."""
    sample = normalize.weather(make_race(), "R")[0]

    assert sample.wind_speed_kph == 9.0
    assert (sample.air_temp_c, sample.track_temp_c, sample.humidity_pct, sample.rainfall) == (21.0, 38.0, 40.0, False)


def test_race_control_keeps_what_f1_sent_and_nulls_what_it_did_not():
    messages = rows(normalize.race_control(make_race()))

    assert messages == [
        {"time_ms": 540_000, "lap_number": 1, "category": "Flag", "message": "GREEN LIGHT - PIT EXIT OPEN", "flag": "GREEN", "scope": "Track"},
        {"time_ms": 842_500, "lap_number": 3, "category": "Other", "message": "INCIDENT NOTED", "flag": None, "scope": None},
    ]


# --- the circuit ---------------------------------------------------------------


def corners_of(session, found):
    return normalize.circuit_corners(found, extract_telemetry(session), normalize.laps(session))


def test_archived_corner_positions_are_published_as_they_are():
    corners = corners_of(make_race(), extras())

    assert corners.distance_source is DistanceSource.ARCHIVE
    assert corners.rotation == 12.0
    # They are checked against the fastest lap all the same, and lie on its track.
    assert (corners.reference_lap.driver_code, corners.reference_lap.lap_number) == ("AAA", 2)
    assert corners.fits_track is True and corners.off_track_m < 5.0
    assert [(corner.number, corner.letter, corner.distance_m) for corner in corners.corners] == [
        (1, None, 1250.0),
        (2, "A", 2500.0),
        (3, None, 3750.0),
    ]
    assert corners.corners[0].x == round(CORNERS[0]["x"], 1)


def test_corners_archived_without_distances_are_placed_along_the_fastest_lap():
    """What a fetch leaves when FastF1 cannot place the corners: the 2026
    Monaco race, whose position data stops in lap 5."""
    session = make_race()

    corners = corners_of(session, extras(corner_distances=False))

    assert corners.distance_source is DistanceSource.TELEMETRY
    # The quickest accurate lap of the race.
    assert (corners.reference_lap.driver_code, corners.reference_lap.lap_number) == ("AAA", 2)
    assert corners.reference_lap.length_m == pytest.approx(TRACK_LENGTH_M, rel=0.01)
    for corner, expected in zip(corners.corners, (1250.0, 2500.0, 3750.0)):
        assert corner.distance_m == pytest.approx(expected, abs=25.0)


def test_corners_cannot_be_placed_without_a_lap_that_has_position_data():
    session = make_race()
    session.pos_data = {}

    corners = corners_of(session, extras(corner_distances=False))

    assert corners.distance_source is None and corners.reference_lap is None
    assert [corner.distance_m for corner in corners.corners] == [None, None, None]
    assert len(corners.corners) == 3
    # Nor can they be checked against the track.
    assert (corners.fits_track, corners.off_track_m) == (None, None)


def repeating_itself(lap, from_m, to_m):
    """The lap with its position held where it was at ``from_m`` until ``to_m``: F1's
    position feed in the 2026 Hungarian race, which repeats itself for seconds at a time."""
    held = (lap.distance_m >= from_m) & (lap.distance_m <= to_m)
    x, y = lap.x.copy(), lap.y.copy()
    x[held], y[held] = x[held][0], y[held][0]
    return replace(lap, x=x, y=y)


def test_the_corners_are_checked_against_a_lap_whose_position_data_is_whole():
    """In the 2026 Hungarian race the fastest lap's position data has a hole
    of 347 m. Measured against it the corners looked up to 116 m off a track
    they are within a metre of."""
    session = make_race()
    telemetry = extract_telemetry(session)
    # The fastest lap's position data stops for 300 m around the first corner.
    laps = {**telemetry.laps, ("AAA", 2): repeating_itself(telemetry.laps[("AAA", 2)], 1_100.0, 1_400.0)}

    corners = normalize.circuit_corners(extras(), SessionTelemetry(laps), normalize.laps(session))

    assert (corners.reference_lap.driver_code, corners.reference_lap.lap_number) != ("AAA", 2)
    assert corners.fits_track is True and corners.off_track_m < 5.0


def test_with_no_lap_whose_position_data_is_whole_the_corners_are_measured_against_what_there_is():
    session = make_race()
    telemetry = extract_telemetry(session)
    laps = {key: repeating_itself(lap, 1_100.0, 1_400.0) for key, lap in telemetry.laps.items()}

    corners = normalize.circuit_corners(extras(), SessionTelemetry(laps), normalize.laps(session))

    # The fastest lap again, and the corner in the hole is 150 m from its nearest sample.
    assert (corners.reference_lap.driver_code, corners.reference_lap.lap_number) == ("AAA", 2)
    assert corners.fits_track is False and corners.off_track_m == pytest.approx(150.0, abs=15.0)


def test_archived_distances_that_do_not_go_round_the_lap_in_order_are_measured_again():
    """Hungary again: FastF1 placed the corners along that fastest lap, and
    put two pairs of them at one point of it."""
    archived = [dict(CORNERS[0]), dict(CORNERS[1], distance_m=CORNERS[0]["distance_m"]), dict(CORNERS[2])]
    found = {CIRCUIT_INFO: json.dumps({"corners": archived}).encode()}

    corners = corners_of(make_race(), found)

    assert corners.distance_source is DistanceSource.TELEMETRY
    for corner, expected in zip(corners.corners, (1250.0, 2500.0, 3750.0)):
        assert corner.distance_m == pytest.approx(expected, abs=25.0)


def test_corners_of_another_layout_are_published_as_not_fitting_this_track():
    """No session has had such a map yet. If one does, its corners are tens
    of metres from every lap, and are not what the laps are segmented by."""
    elsewhere = [{**corner, "x": corner["x"] * 1.12, "y": corner["y"] * 1.12} for corner in CORNERS]
    found = {CIRCUIT_INFO: json.dumps({"rotation": 12.0, "corners": elsewhere}).encode()}

    corners = corners_of(make_race(), found)

    # 12% further from the middle of a circle 796 m in radius.
    assert corners.fits_track is False
    assert corners.off_track_m == pytest.approx(0.12 * TRACK_LENGTH_M / (2 * np.pi), abs=2.0)
    # They are still what the archive holds, and are published as that.
    assert len(corners.corners) == 3 and corners.distance_source is DistanceSource.ARCHIVE


def test_one_corner_a_little_off_the_racing_line_still_fits():
    """Monza and Spa each have a corner 19 m from the fastest lap's line."""
    nudged = [dict(CORNERS[0], x=CORNERS[0]["x"] + 190.0), *CORNERS[1:]]
    found = {CIRCUIT_INFO: json.dumps({"corners": nudged}).encode()}

    corners = corners_of(make_race(), found)

    assert corners.fits_track is True and corners.off_track_m == pytest.approx(19.0, abs=1.0)


@pytest.mark.parametrize("found", [{}, {CIRCUIT_INFO: b"not json"}, {CIRCUIT_INFO: b"[]"}, {CIRCUIT_INFO: b'{"corners":[{"number":1}]}'}])
def test_no_usable_circuit_file_is_an_empty_list_of_corners(found):
    corners = corners_of(make_race(), found)

    assert artifact_json(corners) == {
        "rotation": None, "corners": [], "distance_source": None, "reference_lap": None,
        "off_track_m": None, "fits_track": None,
    }


# --- coverage and the summary ---------------------------------------------------


def test_coverage_is_published_as_measured_with_what_the_session_is_short_of():
    session = make_race()
    del session.pos_data["2"]
    measurement = apply_classification(
        measure_coverage(session, "R", extras(corners=False)), classification().laps_by_number
    )

    coverage = artifact_json(normalize.coverage(measurement))

    assert coverage["complete"] is False
    assert {(item["bar"], item["driver"]) for item in coverage["shortfalls"]} == {
        ("position", "BBB"),
        ("circuit_info", None),
        ("tyre_data", "AAA"),
    }
    assert coverage["feeds"]["circuit_info"] is False and coverage["feeds"]["pit_stop_series"] is True
    assert [driver["driver_code"] for driver in coverage["drivers"]] == ["AAA", "BBB", "CCC"]
    assert coverage["drivers"][1] == {
        "driver_code": "BBB", "number": "2", "in_driver_list": True, "classified_laps": 12, "timing_laps": 12,
        "generated_laps": 0, "car_laps": 12, "position_laps": 0, "tyre_laps": 12, "tyre_age_laps": 12,
    }
    assert coverage["drivers"][2]["generated_laps"] == 1


def test_a_record_written_before_a_figure_was_counted_is_still_published():
    """The coverage that is published is the snapshot's record, and a record
    can be older than a figure, or not this code's. What judges the bars has
    read it before a build starts; what only this reads must not stop one."""
    measurement = apply_classification(measure_coverage(make_race(), "R", extras()), classification().laps_by_number)
    for figure in ("pit_stops_in_timing", "pit_stops_in_series", "max_sample_gap_seconds"):
        del measurement[figure]
    older = measurement["drivers"]["AAA"]
    del older["tyre_age_laps"]
    older["generated_laps"] = "none"

    coverage = artifact_json(normalize.coverage(measurement))

    assert (coverage["pit_stops_in_timing"], coverage["pit_stops_in_series"]) == (0, 0)
    assert coverage["max_sample_gap_seconds"] == 0.0
    first = coverage["drivers"][0]
    assert (first["driver_code"], first["tyre_age_laps"], first["generated_laps"]) == ("AAA", 0, 0)
    assert first["timing_laps"] == 12


def test_the_summary_is_f1s_own_account_of_the_session_and_carries_no_round():
    session = make_race()
    codes = normalize.driver_codes(session)

    summary = artifact_json(
        normalize.summary(
            IDENTITY, session, normalize.drivers(session, codes), normalize.laps(session), normalize.weather(session, "R")
        )
    )

    assert summary == {
        "session_key": 9001,
        "year": 2026,
        "meeting": "Ring Grand Prix",
        "session": "Race",
        "session_type": "R",
        "circuit": "The Ring",
        "country": "Ringland",
        "driver_count": 3,
        "lap_count": 34,
        "weather_summary": "air 21.0-21.3C, track 38.0-38.0C, dry",
        "clock_zero_utc": "2026-06-28T12:00:00.000Z",
        "is_sample": False,
    }
    assert "round" not in summary and "session_id" not in summary
