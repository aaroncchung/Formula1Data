"""The case the twenty-eighth review of this code found (GPT-6.1 Sol, 2026-10-07, at 4af8d80).

The round found one thing, and rated it by what it saw of it: the schema
says a lap's throttle is "0 to 100", and Albon's lap 2 of the 2026 Australian
GP is published with 104.

Looked at over the nine sessions in the local store, 104 is not a throttle.
It is what F1's car feed sends, for the throttle and for the brake, of a
sample it has no pedal reading for; meanwhile it repeats the speed and the
engine speed it last had. FastF1 passes the throttle on and makes the brake
"on". So 422 of 10,458 published laps had a stretch, most under two seconds,
drawn as full throttle and braking at once: Albon's lap 7 of that race for
1.6 s at 302 km/h. The analyses counted those samples as braking.

A lap's throttle and brake are now unknown at such a sample, in what is
published and in what the analyses read, and everything else of the sample is
as F1 sent it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from f1data.analyses import sample_rows
from f1data.telemetry import extract_telemetry
from tests.race import RACE_START_SECONDS, make_race
from tests.test_artifacts import built, read
from tests.test_recorded_race import recorded

AUSTRALIA_2026 = 11234
# The second lap of BBB in the stand-in race runs from 80.5 s to 161 s after the start.
STRETCH = (RACE_START_SECONDS + 100.0, RACE_START_SECONDS + 101.5)


def without_a_pedal_reading(session, number: str = "2", stretch: tuple[float, float] = STRETCH):
    """``session`` with one car's feed as F1 sends it when it has no pedal reading for a stretch."""
    frame = session.car_data[number]
    seconds = frame["SessionTime"].dt.total_seconds()
    marked = (seconds >= stretch[0]) & (seconds <= stretch[1])
    assert marked.sum() >= 4
    held = frame.loc[marked, ["Speed", "RPM", "nGear"]].iloc[0]
    frame.loc[marked, "Throttle"] = 104.0
    frame.loc[marked, "Brake"] = True
    # And the rest of the sample is the last one repeated.
    frame.loc[marked, "Speed"] = held["Speed"]
    frame.loc[marked, "RPM"] = held["RPM"]
    return session


def lap_of(session, code: str = "BBB", number: int = 2):
    return extract_telemetry(session).laps[(code, number)]


def test_a_sample_f1_marks_as_having_no_pedal_reading_has_neither_a_throttle_nor_a_brake():
    lap = lap_of(without_a_pedal_reading(make_race()))

    session_seconds = (lap.start_ms + lap.time_ms) / 1000
    inside = (session_seconds >= STRETCH[0]) & (session_seconds <= STRETCH[1])
    throttle, braking = lap.throttle(), lap.braking()

    assert inside.sum() >= 4
    assert all(throttle[index] is None and braking[index] is None for index in np.flatnonzero(inside))
    # Nor do the samples between a marked one and the next, whose throttle is
    # on a line drawn to or from the mark.
    unknown = np.array([value is None for value in throttle])
    assert (unknown == np.array([value is None for value in braking])).all()
    around = (session_seconds > STRETCH[0] - 0.3) & (session_seconds < STRETCH[1] + 0.3)
    assert not unknown[~around].any()
    car_seconds = make_race().car_data["2"]["SessionTime"].dt.total_seconds().to_numpy()
    last_reading = car_seconds[car_seconds < STRETCH[0]].max()
    next_reading = car_seconds[car_seconds > STRETCH[1]].min()
    leading = (session_seconds > last_reading) & (session_seconds < STRETCH[0])
    trailing = (session_seconds > STRETCH[1]) & (session_seconds < next_reading)
    # The position feed ticks at another rate, so the lap has samples there.
    assert leading.sum() + trailing.sum() > 0
    assert unknown[leading].all() and unknown[trailing].all()
    # At the readings either side the pedals are known again.
    assert not unknown[np.isclose(session_seconds, last_reading)].any()
    assert not unknown[np.isclose(session_seconds, next_reading)].any()
    # Nothing that is a reading is over 100.
    assert max(value for value in throttle if value is not None) <= 100
    # And the rest of each sample is as it was sent: the speed the feed repeated.
    assert not np.isnan(lap.speed_kph[inside]).any() and np.ptp(lap.speed_kph[inside]) < 1.5


def test_a_lap_with_every_pedal_reading_is_as_it_was():
    marked, plain = lap_of(without_a_pedal_reading(make_race()), number=3), lap_of(make_race(), number=3)

    assert marked.pedals_known is None and plain.pedals_known is None
    assert marked.throttle() == plain.throttle() and marked.braking() == plain.braking()
    assert None not in plain.throttle() and None not in plain.braking()
    # Another car's laps are not touched by this car's stretch.
    assert lap_of(without_a_pedal_reading(make_race()), code="AAA").pedals_known is None


def test_what_is_published_and_what_the_analyses_read_have_no_reading_there():
    session = without_a_pedal_reading(make_race())

    files = built(session)
    published = next(lap for lap in read(files, "telemetry/BBB.json")["laps"] if lap["lap_number"] == 2)
    rows = sample_rows(lap_of(session))

    assert None in published["throttle_pct"] and None in published["brake"]
    assert [value is None for value in published["throttle_pct"]] == [value is None for value in published["brake"]]
    assert max(value for value in published["throttle_pct"] if value is not None) <= 100
    # One length still, with every other channel whole.
    assert len({len(published[name]) for name in ("time_ms", "speed_kph", "throttle_pct", "brake", "rpm", "gear")}) == 1
    assert None not in published["speed_kph"] and None not in published["rpm"]
    assert sum(row["throttle_pct"] is None for row in rows) == sum(row["brake"] is None for row in rows) > 0
    # No other lap of the session has a hole in its pedals.
    for code in ("AAA", "BBB", "CCC"):
        for lap in read(files, f"telemetry/{code}.json")["laps"]:
            if (code, lap["lap_number"]) != ("BBB", 2):
                assert None not in lap["throttle_pct"] and None not in lap["brake"], (code, lap["lap_number"])


def test_the_car_is_not_counted_as_braking_while_f1_has_no_reading_of_its_brake():
    """The shares of a lap at full throttle and on the brake are of the samples that have a reading."""
    stretch = (RACE_START_SECONDS + 100.0, RACE_START_SECONDS + 104.0)
    session = without_a_pedal_reading(make_race(), stretch=stretch)

    (row,) = [row for row in read(built(session), "analysis/car-performance.json")["drivers"] if row["driver_code"] == "BBB"]
    lap = lap_of(session)
    braking, throttle = lap.braking(), lap.throttle()

    def share(values, test):
        known = [value for value in values if value is not None]
        return round(100 * sum(test(value) for value in known) / len(known), 1)

    # Lap 2 is BBB's quickest, so it is the lap the figures are of.
    assert row["lap_number"] == 2 and None in braking
    assert row["braking_pct"] == share(braking, bool)
    assert row["full_throttle_pct"] == share(throttle, lambda value: value >= 98)
    # Counted as FastF1 passes it on, the four seconds are braking at full throttle.
    as_sent = round(100 * float(lap.brake.mean()), 1)
    assert as_sent > row["braking_pct"]


@pytest.mark.parametrize("throttle", [101.0, 102.5, 104.0, 200.0])
def test_anything_over_the_scale_is_the_mark(throttle):
    session = without_a_pedal_reading(make_race())
    frame = session.car_data["2"]
    frame.loc[frame["Throttle"] > 100, "Throttle"] = throttle

    assert None in lap_of(session).throttle()


def test_a_throttle_of_exactly_one_hundred_is_a_reading():
    session = make_race()
    frame = session.car_data["2"]
    assert (frame["Throttle"] == 100.0).any()

    assert lap_of(session).pedals_known is None


def test_the_2026_australian_gp_has_no_throttle_over_one_hundred_and_no_braking_at_the_mark(tmp_path):
    session, _, _ = recorded(tmp_path, AUSTRALIA_2026)

    telemetry = extract_telemetry(session)

    marked = {key: lap for key, lap in telemetry.laps.items() if lap.pedals_known is not None}
    # 18 of the session's laps were published with a stretch of it at one mark.
    assert len(marked) > 100
    for lap in telemetry.laps.values():
        known = [value for value in lap.throttle() if value is not None]
        assert not known or max(known) <= 100
    # Albon's lap 7: 302 km/h down the straight, with the feed repeating itself.
    albon = telemetry.laps[("ALB", 7)]
    unknown = np.array([value is None for value in albon.throttle()])
    assert unknown.any() and (np.array([value is None for value in albon.braking()]) == unknown).all()
    stretch = albon.time_ms[unknown]
    assert 48_000 < stretch.min() and stretch.max() < 51_000
    assert set(np.round(albon.speed_kph[unknown])) == {302.0}
    # Before, each of those samples said the brake was on.
    assert albon.brake[unknown].any()
