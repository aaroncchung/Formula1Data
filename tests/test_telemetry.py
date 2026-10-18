"""Full-resolution telemetry by lap, and the thinning that is applied only to what is published.

That the numbers are FastF1's is checked against FastF1 itself on a recorded
race (tests/test_recorded_race.py). These are the properties that hold for any
session, on one small enough to reason about.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from f1data.telemetry import MAX_PUBLISHED_SAMPLES_PER_LAP, extract_telemetry, nan_as_none, thinned_indexes
from tests.race import DRIVERS, RACE_START_SECONDS, TRACK_LENGTH_M, make_race


def lap_of(session, code="AAA", number=2):
    return extract_telemetry(session).laps[(code, number)]


def test_every_lap_with_car_data_has_telemetry_and_none_is_thinned():
    session = make_race()

    telemetry = extract_telemetry(session)

    assert len(telemetry.laps) == len(session.laps)
    assert telemetry.driver_codes() == ["AAA", "BBB", "CCC"]
    # Two feeds at about four samples a second each, merged: about 700 a lap.
    assert all(lap.sample_count > 2 * MAX_PUBLISHED_SAMPLES_PER_LAP for lap in telemetry.of_driver("BBB"))


def test_a_lap_runs_from_its_first_instant_to_its_last():
    session = make_race()
    timed = session.laps[(session.laps["Driver"] == "AAA") & (session.laps["LapNumber"] == 2)].iloc[0]

    lap = lap_of(session)

    assert lap.start_ms == round(timed["LapStartTime"].total_seconds() * 1000)
    assert (lap.time_ms[0], lap.time_ms[-1]) == (0, round(timed["LapTime"].total_seconds() * 1000))
    assert (np.diff(lap.time_ms) > 0).all()
    # Distance is speed integrated over the lap, so it ends a lap's length on.
    assert abs(lap.distance_m[0]) < 1.0
    assert lap.distance_m[-1] == pytest.approx(TRACK_LENGTH_M, rel=0.01)
    assert (np.diff(lap.distance_m) >= 0).all()


def test_the_two_feeds_are_merged_onto_each_others_timestamps():
    session = make_race()
    car = session.car_data["1"]
    position = session.pos_data["1"]

    lap = lap_of(session)
    on_clock = lap.start_ms + lap.time_ms

    for feed in (car, position):
        theirs = (feed["SessionTime"].dt.total_seconds() * 1000).round().astype(int)
        inside = theirs[(theirs >= on_clock[0]) & (theirs <= on_clock[-1])]
        assert set(inside) <= set(on_clock.tolist())
    # A car sample keeps the value the car sent.
    sent = car[car["SessionTime"] > pd.Timedelta(milliseconds=int(on_clock[0]))].iloc[100]
    at = on_clock.tolist().index(round(sent["SessionTime"].total_seconds() * 1000))
    assert (lap.speed_kph[at], lap.rpm[at], lap.gear[at], bool(lap.brake[at])) == (
        sent["Speed"],
        sent["RPM"],
        sent["nGear"],
        bool(sent["Brake"]),
    )
    # Position between two position samples lies between them, on the circle.
    radius = np.hypot(lap.x, lap.y)
    assert radius.min() > 0.999 * radius.max()


def test_a_lap_the_position_feed_does_not_cover_has_car_data_only():
    """The 2026 Monaco race: position stops in lap 5 of 78."""
    stops_in = make_race().laps.query("Driver == 'AAA' and LapNumber == 5").iloc[0]
    stopped = (stops_in["LapStartTime"] + (stops_in["Time"] - stops_in["LapStartTime"]) / 2).total_seconds()

    telemetry = extract_telemetry(make_race(position_until=stopped))

    assert [lap.has_position for lap in telemetry.of_driver("AAA")] == [True] * 4 + [False] * 8
    lost = telemetry.laps[("AAA", 7)]
    assert lost.x is None and lost.y is None
    # Car data alone is about half the samples, and still measures the lap.
    assert lost.sample_count > 300 and lost.distance_m[-1] == pytest.approx(TRACK_LENGTH_M, rel=0.02)
    assert (lost.time_ms[0], np.isnan(lost.distance_m).any()) == (0, False)


def test_a_position_is_never_extrapolated_past_the_last_sample():
    """The feed stops two seconds before a lap ends. The lap still counts as
    having position, and its last two seconds have none rather than a guess."""
    timed = make_race().laps.query("Driver == 'AAA' and LapNumber == 4").iloc[0]
    stopped = timed["Time"].total_seconds() - 2.0

    lap = lap_of(make_race(position_until=stopped), number=4)

    unplaced = np.isnan(lap.x)
    assert lap.has_position and unplaced.any()
    assert (np.isnan(lap.y) == unplaced).all()
    assert lap.time_ms[unplaced].min() > 1000 * (stopped - timed["LapStartTime"].total_seconds())
    assert not np.isnan(lap.distance_m).any()
    assert nan_as_none(lap.x[-3:]) == [None, None, None]


def test_the_zeros_f1_sends_before_it_has_a_position_are_not_positions():
    session = make_race()
    # As at Monaco in 2026: (0, 0) for the cars on the grid, into the first seconds of the race.
    for frame in session.pos_data.values():
        early = frame["SessionTime"].dt.total_seconds() < RACE_START_SECONDS + 2.0
        frame.loc[early, ["X", "Y"]] = 0.0

    lap = lap_of(session, number=1)

    placed = ~np.isnan(lap.x)
    assert lap.has_position
    # Unplaced up to the first real position, a little over two seconds in, and placed from there on.
    assert 2000 <= lap.time_ms[placed].min() < 2300
    assert lap.time_ms[~placed].max() < lap.time_ms[placed].min()
    assert np.hypot(lap.x[placed], lap.y[placed]).min() > 1000.0


def test_a_driver_with_no_car_data_has_no_telemetry_and_a_missing_feed_is_not_an_error():
    session = make_race()
    del session.car_data["2"]
    del session.pos_data["3"]

    telemetry = extract_telemetry(session)

    assert telemetry.of_driver("BBB") == []
    assert all(not lap.has_position for lap in telemetry.of_driver("CCC"))
    del session.car_data
    assert extract_telemetry(session).laps == {}


def test_drs_is_reported_as_the_set_of_values_it_takes():
    assert extract_telemetry(make_race()).drs_values() == {0}
    assert extract_telemetry(make_race(drs=True)).drs_values() == {0, 12}


@pytest.mark.parametrize("count", [1, 2, 299, 300, 301, 557, 600, 601, 5000])
def test_thinning_keeps_both_ends_and_never_more_than_the_limit(count):
    kept = thinned_indexes(count)

    assert len(kept) == min(count, MAX_PUBLISHED_SAMPLES_PER_LAP)
    assert (kept[0], kept[-1]) == (0, count - 1)
    assert (np.diff(kept) > 0).all()
    # Evenly: no two neighbours are further apart than the next whole stride.
    if count > MAX_PUBLISHED_SAMPLES_PER_LAP:
        assert np.diff(kept).max() <= -(-count // MAX_PUBLISHED_SAMPLES_PER_LAP) + 1


def test_thinning_is_the_same_everywhere():
    # Pinned, so that a change of arithmetic that moves one index is noticed.
    assert thinned_indexes(7, 4).tolist() == [0, 2, 4, 6]
    assert thinned_indexes(10, 4).tolist() == [0, 3, 6, 9]
    assert thinned_indexes(557)[:6].tolist() == [0, 2, 4, 6, 7, 9]
    assert thinned_indexes(0).tolist() == []


def test_every_driver_of_the_small_race_is_there():
    assert {driver["code"] for driver in DRIVERS.values()} == set(extract_telemetry(make_race()).driver_codes())
