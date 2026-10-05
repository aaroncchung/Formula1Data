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
    measure_coverage,
    weakest_share,
)
from tests.fakes import LAP_SECONDS, RACE_START, make_session, thin_to_one_sample_per_lap


def shortfalls(session, session_type="R"):
    return {(item.bar, item.driver) for item in evaluate_coverage(measure_coverage(session, session_type))}


def test_a_whole_session_meets_every_bar():
    measurement = measure_coverage(make_session(), "R")

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


@pytest.mark.parametrize("timed_laps", [3, 10, 60])
def test_one_lap_short_of_the_classification_is_tolerated_on_every_bar(timed_laps):
    session = make_session(laps_per_driver=timed_laps)
    session.results["Laps"] = float(timed_laps + 1)

    assert shortfalls(session) == set()


def test_two_laps_short_of_the_classification_is_not():
    session = make_session(laps_per_driver=3)
    session.results["Laps"] = 5.0

    assert ("timing_data", "AAA") in shortfalls(session)


def test_a_lap_fastf1_generated_for_a_retirement_is_not_a_timing_lap():
    session = make_session()
    generated = session.laps.iloc[[-1]].copy()
    generated["LapNumber"] = 11.0
    generated["FastF1Generated"] = True
    generated["LapStartTime"] = generated["Time"]
    generated["Time"] = generated["Time"] + pd.Timedelta(seconds=150)
    session.laps = pd.concat([session.laps, generated], ignore_index=True)

    measurement = measure_coverage(session, "R")

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


def test_weakest_share_orders_two_incomplete_sessions():
    slightly_short = make_session()
    slightly_short.car_data["1"] = slightly_short.car_data["1"][
        slightly_short.car_data["1"]["SessionTime"].dt.total_seconds() < RACE_START + 8 * LAP_SECONDS
    ]
    badly_short = make_session()
    del badly_short.pos_data["1"]

    assert weakest_share(measure_coverage(slightly_short, "R")) == pytest.approx(0.8)
    assert weakest_share(measure_coverage(badly_short, "R")) == 0.0


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
