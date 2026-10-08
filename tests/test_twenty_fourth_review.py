"""The cases the twenty-fourth review of this code found (GPT-6.1 Sol, 2026-10-07, at b1a6aed).

The round before taught the strategy analysis and the site what an entry to
the pit lane was, each in its own words, and they did not agree about a car
that waited there through a red flag. The site calls that a wait whatever was
done to the car. The analysis took one whose tyres were changed for the
driver's first stop (Norris, lap 2 of the 2026 Dutch GP, whose stop on lap 21
was never compared across), and one whose tyres were not for a car that went
through without stopping (three cars of the 2025 Sao Paulo sprint, 22 minutes
each). It now reads the stop list in the site's order.

And a driver whose stint numbers from F1 go back down keeps them: taking the
passages out of numbers that are not a count gave two sets one number.

The site's half (an unnamed compound counted as a compound, and the clock
note said of laps whose clocks are out by the same amount) is in
frontend/tests/strategy-view.test.mjs and telemetry-compare.test.mjs.
"""

from __future__ import annotations

import pytest

from f1data import normalize
from tests.race import LAPS, PIT_LAP, extras, make_race
from tests.test_artifacts import built, read
from tests.test_eleventh_review import red_flag
from tests.test_recorded_race import recorded
from tests.test_twenty_third_review import NEW, numbers, runs, strategy_of, tyre_data

SAO_PAULO_SPRINT_2025 = 9864
DUTCH_2026 = 11353


# --- a wait through a red flag is a wait in the analysis too --------------------------


def stopped_under_a_red_flag(tyres: list[tuple[int, str | None, float | None]] | None = None):
    """The race with a red flag out while AAA is in the pit lane on lap 5, and AAA's tyres as given."""
    session = make_race()
    (stop,) = normalize.pit_stops(session, {}, normalize.driver_codes(session))
    red_flag(session, stop.entry_time_ms + 5_000, stop.entry_time_ms + 15_000)
    return tyre_data(session, "AAA", tyres) if tyres else session


@pytest.mark.parametrize(
    ("tyres", "changed", "reported"),
    [
        # As the race is: MEDIUM to HARD while the car waited, and F1's
        # pit-stop feed with a "stationary time" for it.
        (None, True, True),
        # The wait of a car that kept the tyres it had, which F1's pit-stop
        # feed says nothing of: by its two feeds alone, a car going through.
        ([(1, "MEDIUM", NEW)] * LAPS, False, False),
        ([(1, "MEDIUM", NEW)] * LAPS, False, True),
        (None, True, False),
    ],
)
def test_a_wait_through_a_red_flag_is_neither_a_stop_nor_a_passage(tyres, changed, reported):
    files = built(stopped_under_a_red_flag(tyres), found=extras(pit_stops=reported))

    (stop,) = read(files, "pit-stops.json")
    strategy = read(files, "analysis/strategy.json")

    assert (stop["under_red_flag"], stop["tyres_changed"]) == (True, changed)
    assert (stop["stationary_ms"] is not None) is reported
    assert strategy["pit_loss"]["stops"][0]["excluded_reason"] == "red_flag_wait"
    assert strategy["pit_loss"]["excluded_stop_counts"] == {"red_flag_wait": 1}
    assert "Left out: 1 for the car waiting in the pit lane through a red flag." in strategy["caveats"][0]
    # It is nobody's first stop, tyres changed or not.
    assert strategy["undercut_overcut"] == []


def test_a_stop_with_no_red_flag_is_still_a_stop():
    strategy = read(built(), "analysis/strategy.json")

    assert strategy["pit_loss"]["stops"][0]["excluded_reason"] not in ("red_flag_wait", "no_stop")
    assert [(row["driver_code"], row["stop_lap"]) for row in strategy["undercut_overcut"]] == [("AAA", PIT_LAP)]


def test_the_2026_dutch_gps_first_stops_are_not_the_wait_through_its_red_flag(tmp_path):
    """The race was red-flagged on lap 2 with the field in the pit lane, and tyres were changed there."""
    session, found, _ = recorded(tmp_path, DUTCH_2026)

    _, stops, strategy = strategy_of(session, found)

    waited = {stop.driver_code for stop in stops if stop.under_red_flag and stop.lap_number == 2}
    assert {"NOR", "HAM"} <= waited
    firsts = {row["driver_code"]: row for row in strategy["undercut_overcut"]}
    # Lap 2 for both, with no pace change to report across it.
    assert (firsts["NOR"]["stop_lap"], firsts["NOR"]["first_clean_lap_gain_ms"]) == (21, 1_852)
    assert (firsts["HAM"]["stop_lap"], firsts["HAM"]["first_clean_lap_gain_ms"]) == (25, 1_733)
    assert not any(row["stop_lap"] == 2 for code, row in firsts.items() if code in waited)


def test_the_2025_sao_paulo_sprints_waits_are_not_counted_as_cars_going_through(tmp_path):
    """Three cars waited 22 minutes in the pit lane on the tyres they had."""
    session, found, _ = recorded(tmp_path, SAO_PAULO_SPRINT_2025)

    _, stops, strategy = strategy_of(session, found)

    waits = [stop for stop in stops if stop.under_red_flag and stop.tyres_changed is False]
    assert sorted(stop.driver_code for stop in waits) == ["ALB", "LAW", "TSU"]
    assert all(stop.duration_ms > 20 * 60 * 1000 for stop in waits)
    priced = {(row["driver_code"], row["lap_number"]): row["excluded_reason"] for row in strategy["pit_loss"]["stops"]}
    assert all(priced[(stop.driver_code, stop.lap_number)] == "red_flag_wait" for stop in waits)
    # Four were said to have gone through without stopping.
    assert strategy["pit_loss"]["excluded_stop_counts"].get("no_stop", 0) == 1


# --- numbers from F1 that go back down are left as they are ------------------------


@pytest.mark.parametrize(
    "from_f1",
    [
        # A passage, then a number F1 had already used: taken down by the
        # passage it came out as 0.
        [(1, "HARD", 1.0), (2, "HARD", 2.0), (1, "HARD", 1.0)],
        # And here two different sets, F1's 1 and its second 2, both came out as 1.
        [(1, "HARD", 1.0), (2, "HARD", 2.0), (3, "HARD", 1.0), (2, "HARD", 1.0)],
    ],
)
def test_a_driver_whose_numbers_from_f1_go_back_down_keeps_them(from_f1):
    per_lap = from_f1 + [(from_f1[-1][0], "HARD", float(age)) for age in range(2, LAPS - len(from_f1) + 2)]
    session = tyre_data(make_race(), "BBB", per_lap)

    assert numbers(session, "BBB") == [number for number, _, _ in per_lap]
    # No two runs of the driver are one set, and none is numbered nought.
    found = runs(session, "BBB")
    assert len(found) == len(from_f1) and all(run[0] >= 1 for run in found)
    # The driver beside them is numbered as ever.
    assert numbers(session, "AAA") == [1] * PIT_LAP + [2] * (LAPS - PIT_LAP)
