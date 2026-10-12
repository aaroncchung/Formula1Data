"""The cases the fourteenth review of this code found (GPT-6.1 Sol, 2026-10-06, at ada5cc1).

The first round to read the site's reader as the other side of the contract.
Its one finding from real data is on both sides of it: a lap's distance, as
FastF1 computes it and as it was published, dips by a tenth of a metre while a
car stands in its pit box, and the site's comparison of two laps looked a
sample up by distance as if it never could. The publisher's half is here;
the reader's is in frontend/tests/telemetry-compare.test.mjs. The rest: two
kinds of key that could be taken for each other where F1's pit-stop feed is
read, and arrays that run side by side being allowed to differ in length.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from f1data.extras import parse_pit_stop_series
from f1data.models import PositionReplay, ReplayDriver, TelemetryDriverEntry, TelemetryLap
from f1data.telemetry import extract_telemetry
from tests.race import make_race
from tests.test_artifacts import built, read
from tests.test_twelfth_review import lap_times, pit_line, stop

# --- a lap's distance never goes backwards ------------------------------------------


def standing_still(session, number: str, from_seconds: float, until_seconds: float):
    """``session`` with one car at rest between two moments: no speed, and one position."""
    car = session.car_data[number]
    at_rest = (car["SessionTime"].dt.total_seconds() >= from_seconds) & (
        car["SessionTime"].dt.total_seconds() < until_seconds
    )
    car.loc[at_rest, ["Speed", "RPM", "Throttle"]] = 0.0
    car.loc[at_rest, "nGear"] = 0
    return session


def test_a_car_that_stands_still_in_mid_lap_does_not_go_backwards():
    """FastF1 fills in the distance at a position sample with a quadratic
    spline through the car samples. Where the car stops, the spline rings:
    Bearman's lap 30 of the 2026 Canadian GP read 4117.8, 4117.8, 4117.8,
    4117.7, 4118.7 metres, and 78 laps of nine published sessions have such a
    dip. The site's comparison of two laps looks a sample up by its distance,
    found the wrong one, and put a lap 23 seconds from itself."""
    session = make_race()
    start, end = lap_times(session, "BBB", 6)
    standing_still(session, "2", start + 30.0, start + 50.0)

    lap = extract_telemetry(session).laps[("BBB", 6)]

    steps = np.diff(lap.distance_m)
    assert (steps >= 0).all()
    # It did stand still, and for the twenty seconds it was meant to.
    still = lap.time_ms[1:][steps == 0]
    assert len(still) > 100 and 18_000 < still.max() - still.min() < 22_000

    published = next(row for row in read(built(session), "telemetry/BBB.json")["laps"] if row["lap_number"] == 6)
    assert published["distance_m"] == sorted(published["distance_m"])
    assert len(set(published["distance_m"])) < len(published["distance_m"])


def test_the_distance_of_a_lap_with_no_standstill_is_untouched():
    lap = extract_telemetry(make_race()).laps[("BBB", 6)]

    assert (np.diff(lap.distance_m) > 0).all()


# --- a place in a driver's list is not a lap -----------------------------------------


def test_a_stop_on_lap_one_and_a_report_with_no_lap_in_place_one_are_two_stops():
    """Stops that say their lap were told apart by driver and lap, and ones
    that do not by driver and place: two pairs of the same shape. A first
    stop on lap 1 and a second report, in place 1, with no lap were taken for
    one stop sent twice, and the first was dropped."""
    feed = pit_line("01:00:00.000", [stop("1", "2.4", "19.9", "2026-06-28T12:11:30.000Z")]) + pit_line(
        "01:05:00.000", {"1": stop("", "3.1", "20.4", "2026-06-28T12:17:10.000Z")}
    )

    stops = parse_pit_stop_series(feed)

    assert [(item["lap_number"], item["stationary_ms"]) for item in stops] == [(1, 2_400), (None, 3_100)]
    # And the other way about: a report with no lap in place 5, then a stop on lap 5.
    other_way = pit_line("01:00:00.000", {"5": stop("", "3.1", "20.4", "2026-06-28T12:17:10.000Z")}) + pit_line(
        "01:05:00.000", {"6": stop("5", "2.4", "19.9", "2026-06-28T12:30:00.000Z")}
    )
    assert [(item["lap_number"], item["stationary_ms"]) for item in parse_pit_stop_series(other_way)] == [
        (None, 3_100),
        (5, 2_400),
    ]


# --- arrays that run side by side are of one length, or nothing is published --------

LAP = {
    "lap_number": 1,
    "start_ms": 600_000,
    "time_ms": [0, 250],
    "distance_m": [0.0, 15.2],
    "speed_kph": [210.0, 212.0],
    "throttle_pct": [100, 100],
    "brake": [False, False],
    "rpm": [10_400, 10_450],
    "gear": [7, 7],
    "drs": None,
    "x": None,
    "y": None,
}


@pytest.mark.parametrize(
    "short",
    [{"brake": [True]}, {"drs": [12]}, {"x": [1.0], "y": [2.0]}, {"speed_kph": []}, {"time_ms": [0, 250, 500]}],
)
def test_a_lap_whose_channels_are_not_of_one_length_is_not_published(short):
    """The schema cannot say that two arrays have one length, and the site
    read a brake array one sample short as "not braking" at the last."""
    TelemetryLap.model_validate(LAP)
    TelemetryLap.model_validate({**LAP, "drs": [0, 0], "x": [1.0, None], "y": [2.0, None]})

    with pytest.raises(ValidationError, match="of one length"):
        TelemetryLap.model_validate({**LAP, **short})


def test_a_drivers_laps_in_the_index_have_every_figure_or_none():
    entry = {
        "driver_code": "AAA", "path": "telemetry/AAA.json", "lap_number": [1, 2], "lap_time_ms": [None, 80_022],
        "compound": ["MEDIUM", "MEDIUM"], "is_accurate": [False, True], "is_deleted": [False, False],
        "is_pit_in_lap": [False, False], "is_pit_out_lap": [False, False], "sample_count": [300, 300],
        "raw_sample_count": [671, 671], "has_position": [True, True],
    }
    TelemetryDriverEntry.model_validate(entry)

    for name in ("lap_time_ms", "is_deleted", "has_position"):
        with pytest.raises(ValidationError, match="of one length"):
            TelemetryDriverEntry.model_validate({**entry, name: entry[name][:1]})


def test_every_car_of_a_replay_has_an_entry_for_every_frame():
    car = {"driver_code": "AAA", "x": [1.0, 2.0], "y": [1.0, 2.0], "speed_kph": [None, 200.0], "distance_m": [None, 5.0]}
    replay = {"interval_ms": 5_000, "time_ms": [600_000, 605_000], "lap_number": [1, 1], "drivers": [car]}
    PositionReplay.model_validate(replay)
    assert isinstance(PositionReplay.model_validate(replay).drivers[0], ReplayDriver)

    with pytest.raises(ValidationError, match="2 frames and 1 lap numbers"):
        PositionReplay.model_validate({**replay, "lap_number": [1]})
    with pytest.raises(ValidationError, match="2 frames and, for AAA"):
        PositionReplay.model_validate({**replay, "drivers": [{**car, "speed_kph": [200.0]}]})
