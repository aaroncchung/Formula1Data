"""Each test damages one feed and checks the session stops counting as complete.

The cases are the ones the plan review found a session could slip through with
(docs/architecture-review-findings.md, section 9, points 4, 18, 20, 23, 25, 28).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from f1data.coverage import (
    MAX_SAMPLE_GAP_SECONDS,
    evaluate_coverage,
    lap_is_usable,
    weakest_share,
)
from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES, parse_pit_stop_series
from tests.fakes import EXTRAS, LAP_SECONDS, RACE_START, make_session, measure, thin_to_one_sample_per_lap


def shortfalls_with(session, extras, session_type="R"):
    return {(item.bar, item.driver) for item in evaluate_coverage(measure(session, session_type, extras))}


def shortfalls(session, session_type="R"):
    return {(item.bar, item.driver) for item in evaluate_coverage(measure(session, session_type))}


def test_a_whole_session_meets_every_bar():
    measurement = measure(make_session())

    assert evaluate_coverage(measurement) == []
    assert measurement["drivers"]["AAA"] == {
        "number": "1",
        "in_driver_list": True,
        "classified_laps": 10,
        "timing_laps": 10,
        "generated_laps": 0,
        "car_laps": 10,
        "position_laps": 10,
        "tyre_laps": 10,
        "tyre_age_laps": 10,
    }
    assert weakest_share(measurement) == 1.0


@pytest.mark.parametrize(
    ("feed", "bar"), [("car_data", "car_data"), ("pos_data", "position")]
)
def test_one_sample_per_lap_is_not_telemetry(feed, bar):
    session = make_session()
    thin_to_one_sample_per_lap(session, feed)

    found = shortfalls(session)

    assert found == {(bar, "AAA"), (bar, "BBB"), (bar, "CCC")}


def test_timing_cut_short_is_noticed_against_the_classification():
    session = make_session(laps_per_driver=50)
    session.laps = session.laps[session.laps["LapNumber"] <= 1]

    found = shortfalls(session)

    assert {("timing_data", "AAA"), ("timing_data", "BBB"), ("timing_data", "CCC")} <= found
    # The shares are taken against the laps expected, so one lap out of fifty
    # with full telemetry is still a telemetry shortfall.
    assert ("car_data", "AAA") in found


def test_a_driver_one_lap_short_of_the_classification_is_short():
    session = make_session()
    session.results["Laps"] = 11.0

    assert ("timing_data", "AAA") in shortfalls(session)


def test_a_driver_classified_with_one_lap_and_no_data_at_all_is_short():
    """Found in review: with a lap of tolerance this driver met every bar."""
    session = make_session()
    session.results.loc["3", "Laps"] = 1.0
    session.laps = session.laps[session.laps["DriverNumber"] != "3"]
    del session.car_data["3"]
    del session.pos_data["3"]

    assert shortfalls(session) == {
        ("timing_data", "CCC"),
        ("car_data", "CCC"),
        ("position", "CCC"),
        ("tyre_data", "CCC"),
    }


def test_one_more_timed_lap_than_classified_is_not_a_shortfall():
    # A retirement: Alonso was classified with 21 laps of the 2026 Australian
    # GP and timed over 22.
    session = make_session(laps_per_driver=22)
    session.results["Laps"] = 21.0

    assert shortfalls(session) == set()


def test_a_lap_fastf1_generated_for_a_retirement_is_not_a_timing_lap():
    session = make_session()
    generated = session.laps.iloc[[-1]].copy()
    generated["LapNumber"] = 11.0
    generated["FastF1Generated"] = True
    generated["LapStartTime"] = generated["Time"]
    generated["Time"] = generated["Time"] + pd.Timedelta(seconds=150)
    session.laps = pd.concat([session.laps, generated], ignore_index=True)

    measurement = measure(session)

    assert measurement["drivers"]["CCC"]["timing_laps"] == 10
    assert measurement["drivers"]["CCC"]["generated_laps"] == 1
    assert evaluate_coverage(measurement) == []


@pytest.mark.parametrize(
    ("attribute", "bar"),
    [
        ("track_status", "track_status"),
        ("weather_data", "weather"),
        ("race_control_messages", "race_control"),
        ("session_status", "session_status"),
    ],
)
def test_a_session_feed_that_did_not_arrive_is_a_shortfall(attribute, bar):
    session = make_session()
    setattr(session, attribute, pd.DataFrame())

    assert (bar, None) in shortfalls(session)


def test_a_feed_fastf1_never_set_is_a_shortfall_not_a_crash():
    session = make_session()
    del session.weather_data

    assert ("weather", None) in shortfalls(session)


def test_a_session_that_has_not_ended_is_a_shortfall():
    session = make_session()
    session.session_status = pd.DataFrame({"Status": ["Inactive", "Started"]})

    assert ("session_status", None) in shortfalls(session)


def test_missing_lap_count_matters_for_a_race_only():
    session = make_session()
    session.total_laps = None

    assert ("lap_count", None) in shortfalls(session, "R")
    assert ("lap_count", None) not in shortfalls(session, "Q")


def test_one_driver_without_car_data_is_named():
    session = make_session()
    del session.car_data["2"]

    assert shortfalls(session) == {("car_data", "BBB")}


def test_position_data_without_coordinates_does_not_count():
    session = make_session()
    session.pos_data["3"][["X", "Y"]] = 0.0

    assert shortfalls(session) == {("position", "CCC")}


def test_car_data_with_a_channel_missing_does_not_count():
    session = make_session()
    session.car_data["1"]["Throttle"] = np.nan

    assert shortfalls(session) == {("car_data", "AAA")}


def test_one_driver_without_tyre_data_is_named():
    # What FastF1 leaves when a driver's TimingAppData is missing: an empty
    # compound, no tyre age and a single stint (fastf1/core.py, 1532-1539).
    session = make_session()
    mine = session.laps["DriverNumber"] == "2"
    session.laps.loc[mine, "Compound"] = ""
    session.laps.loc[mine, "TyreLife"] = np.nan

    assert shortfalls(session) == {("tyre_data", "BBB")}


def test_a_used_set_with_no_reported_age_is_measured_but_is_not_a_shortfall():
    # Bearman's third stint at Barcelona in 2026: a used set of softs, with a
    # compound and a stint and no age, however often it is fetched.
    session = make_session()
    used_set = (session.laps["DriverNumber"] == "2") & (session.laps["LapNumber"] > 6)
    session.laps.loc[used_set, "TyreLife"] = np.nan
    session.laps.loc[used_set, "Stint"] = 2.0

    measurement = measure(session)

    assert measurement["drivers"]["BBB"]["tyre_laps"] == 10
    assert measurement["drivers"]["BBB"]["tyre_age_laps"] == 6
    assert evaluate_coverage(measurement) == []


def test_a_driver_known_only_from_jolpica_is_a_shortfall():
    session = make_session()
    session.results["BroadcastName"] = None

    assert ("driver_list", "AAA") in shortfalls(session)


def test_a_race_without_a_classification_cannot_be_judged_complete():
    session = make_session()
    session.results["Laps"] = np.nan

    assert ("classification", "AAA") in shortfalls(session)


def test_a_session_without_a_lap_count_to_compare_needs_laps_for_every_driver():
    session = make_session()
    session.results["Laps"] = np.nan
    session.laps = session.laps[session.laps["DriverNumber"] != "3"]

    assert shortfalls(session, "Q") == {("timing_data", "CCC")}


def test_a_race_with_stops_and_no_stationary_times_is_a_shortfall():
    # What F1 answers for a race before late 2024: timing that shows the stops,
    # and no pit-stop feed.
    session = make_session()
    without_feed = {CIRCUIT_INFO: EXTRAS[CIRCUIT_INFO]}

    found = {(item.bar, item.driver, item.detail) for item in evaluate_coverage(measure(session, "R", without_feed))}

    assert found == {
        (
            "pit_stop_series",
            None,
            "no stationary time from F1's pit-stop feed, and the timing has 1 entry to the pit lane",
        )
    }


def test_a_session_nobody_pitted_in_has_no_pit_stop_feed_to_miss():
    session = make_session()
    session.laps["PitInTime"] = pd.NaT

    assert evaluate_coverage(measure(session, "S", {CIRCUIT_INFO: EXTRAS[CIRCUIT_INFO]})) == []


def test_missing_corner_positions_are_a_shortfall():
    session = make_session()

    found = shortfalls_with(session, {PIT_STOP_SERIES: EXTRAS[PIT_STOP_SERIES]})

    assert found == {("circuit_info", None)}


def test_the_pit_stop_feed_is_read_whether_a_stop_is_a_driver_s_first_or_a_later_one():
    feed = (
        b'\xef\xbb\xbf01:12:03.942{"PitTimes":{"44":[{"Timestamp":"2026-06-28T13:18:16.017Z",'
        b'"PitStop":{"RacingNumber":"44","PitStopTime":"2.4","PitLaneTime":"21.369","Lap":"12"}}]}}\r\n'
        b'01:28:29.134{"PitTimes":{"44":{"1":{"Timestamp":"2026-06-28T13:34:41.209Z",'
        b'"PitStop":{"RacingNumber":"44","PitStopTime":"2.2","PitLaneTime":"21.250","Lap":"25"}}}}}\r\n'
        b"not a stream line\r\n"
    )

    assert parse_pit_stop_series(feed) == [
        {
            "driver_number": "44",
            "lap_number": 12,
            "stationary_ms": 2400,
            "pit_lane_ms": 21369,
            "time_utc": "2026-06-28T13:18:16.017Z",
        },
        {
            "driver_number": "44",
            "lap_number": 25,
            "stationary_ms": 2200,
            "pit_lane_ms": 21250,
            "time_utc": "2026-06-28T13:34:41.209Z",
        },
    ]
    assert parse_pit_stop_series(b"") == []


def test_weakest_share_orders_two_incomplete_sessions():
    slightly_short = make_session()
    slightly_short.car_data["1"] = slightly_short.car_data["1"][
        slightly_short.car_data["1"]["SessionTime"].dt.total_seconds() < RACE_START + 8 * LAP_SECONDS
    ]
    badly_short = make_session()
    del badly_short.pos_data["1"]

    assert weakest_share(measure(slightly_short)) == pytest.approx(0.8)
    assert weakest_share(measure(badly_short)) == 0.0


def test_lap_is_usable_needs_samples_from_start_to_end_without_a_long_hole():
    full = np.arange(100.0, 180.0, 0.25)

    assert lap_is_usable(full, 100.0, 180.0)
    # A hole in the middle.
    holed = full[(full < 130.0) | (full > 130.0 + MAX_SAMPLE_GAP_SECONDS + 1)]
    assert not lap_is_usable(holed, 100.0, 180.0)
    # Samples that stop before the lap does.
    assert not lap_is_usable(full[full < 170.0], 100.0, 180.0)
    # Samples that start after the lap does.
    assert not lap_is_usable(full[full > 110.0], 100.0, 180.0)
    assert not lap_is_usable(np.array([140.0]), 100.0, 180.0)
    assert not lap_is_usable(full, float("nan"), 180.0)
