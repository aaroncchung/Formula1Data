"""The cases the twenty-third review of this code found (GPT-6.1 Sol, 2026-10-07, at 2c663f7).

The round was asked one question of method, how to tell a pit stop from a car
that only went down the pit lane, and came back with what else counted the
second as the first. In the 2025 Canadian GP the field followed the safety
car down the pit lane three times in the last four laps: 49 of that race's 82
entries to the pit lane. Published of it were six stints for Verstappen where
he ran three, 83 pit stops, and a pit-lane median of 18.3 s that no stop took.
In the 2026 Dutch GP a drive-through penalty was priced as a pit stop, and was
the fastest "stop" of the race.

F1 says which is which in two feeds. Its tyre data gives a car that kept its
tyres a new stint number, and the same compound one lap older. Its pit-stop
feed gives a stationary time for a car that stopped.

The site's half, the lap comparison's delta at the line and a hole in lap B,
is in frontend/tests/telemetry-compare.test.mjs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.analysis.strategy import calculate_strategy
from f1data import normalize
from f1data.models import artifact_json
from tests.race import LAPS, PIT_LAP, extras, make_race
from tests.test_recorded_race import recorded
from tests.test_artifacts import built, read

CANADA_2025 = 9963
MIAMI_2025 = 10033
DUTCH_2026 = 11353

NEW = None  # In a row of tyre data: the age starts again, as on a set that goes on new.


def tyre_data(session, code: str, per_lap: list[tuple[int, str | None, float | None]]):
    """``session`` with one driver's stint number, compound and tyre age set lap by lap.

    An age of ``NEW`` counts up from 1 from the lap the number last changed.
    """
    age, before = 0.0, None
    for lap_number, (stint, compound, given) in enumerate(per_lap, start=1):
        age = age + 1 if stint == before else 1.0
        before = stint
        mine = (session.laps["Driver"] == code) & (session.laps["LapNumber"] == lap_number)
        session.laps.loc[mine, "Stint"] = float(stint)
        session.laps.loc[mine, "Compound"] = compound
        session.laps.loc[mine, "TyreLife"] = age if given is NEW else given
    return session


def drives_through(session, code: str, lap_number: int):
    """``session`` with a driver into the pit lane at the end of one lap and out of it on the next."""
    came_in = (session.laps["Driver"] == code) & (session.laps["LapNumber"] == lap_number)
    went_out = (session.laps["Driver"] == code) & (session.laps["LapNumber"] == lap_number + 1)
    session.laps.loc[came_in, "PitInTime"] = session.laps.loc[came_in, "Time"] - pd.Timedelta(seconds=8)
    session.laps.loc[went_out, "PitOutTime"] = session.laps.loc[went_out, "LapStartTime"] + pd.Timedelta(seconds=4)
    return session


def runs(session, code: str) -> list[tuple[int | None, str | None, int, int]]:
    return [
        (run.stint, run.compound.value if run.compound else None, run.start_lap, run.end_lap)
        for run in normalize.stints(normalize.laps(session))
        if run.driver_code == code
    ]


def numbers(session, code: str) -> list[int | None]:
    return [lap.stint for lap in normalize.laps(session) if lap.driver_code == code]


def stops_of(session, found=None) -> dict[tuple[str, int], bool | None]:
    laps = normalize.laps(session)
    stops = normalize.pit_stops(
        session, extras() if found is None else found, normalize.driver_codes(session), normalize.stints(laps)
    )
    return {(stop.driver_code, stop.lap_number): stop.tyres_changed for stop in stops}


# --- a stint is a set of tyres -----------------------------------------------------


def test_a_car_that_goes_through_the_pit_lane_is_still_on_the_set_it_was_on():
    """Verstappen in the 2025 Canadian GP: three passages behind the safety car, and six stints for three."""
    session = tyre_data(
        make_race(),
        "BBB",
        [(1, "MEDIUM", NEW)] * 4
        + [(2, "HARD", NEW)] * 5
        # F1's next three numbers: the compound it was, and each lap one older.
        + [(3, "HARD", 6.0), (4, "HARD", 7.0), (5, "HARD", 8.0)],
    )

    assert runs(session, "BBB") == [(1, "MEDIUM", 1, 4), (2, "HARD", 5, LAPS)]
    assert numbers(session, "BBB") == [1] * 4 + [2] * 8


def test_the_numbers_after_a_passage_close_up():
    session = tyre_data(
        make_race(),
        "BBB",
        [(1, "MEDIUM", NEW)] * 4 + [(2, "MEDIUM", 5.0), (2, "MEDIUM", 6.0)] + [(3, "HARD", NEW)] * 6,
    )

    assert runs(session, "BBB") == [(1, "MEDIUM", 1, 6), (2, "HARD", 7, LAPS)]
    assert numbers(session, "BBB") == [1] * 6 + [2] * 6


@pytest.mark.parametrize(
    ("after", "why"),
    [
        ((2, "HARD", NEW), "a new set of the same compound: its age starts again"),
        ((2, "MEDIUM", 7.0), "another compound, whatever age F1 gives it"),
        ((2, "HARD", np.nan), "a set that went on used, which F1 gives no age"),
        ((2, "HARD", 6.0), "an age that does not go on by one lap is not the same set going on"),
        ((2, None, 7.0), "no compound named: nothing says it is the same"),
    ],
)
def test_a_new_number_is_a_new_set_unless_the_tyre_data_says_it_is_the_same(after, why):
    session = tyre_data(make_race(), "BBB", [(1, "HARD", NEW)] * 6 + [after] * 6)

    found = runs(session, "BBB")

    assert [(run[0], run[2], run[3]) for run in found] == [(1, 1, 6), (2, 7, LAPS)], why
    assert numbers(session, "BBB") == [1] * 6 + [2] * 6


def test_a_set_that_went_on_used_is_not_joined_to_the_one_before_it():
    """F1 gives no age for a used set, so the lap before a passage on one has none to go on from."""
    session = tyre_data(make_race(), "BBB", [(1, "HARD", np.nan)] * 6 + [(2, "HARD", np.nan)] * 6)

    assert runs(session, "BBB") == [(1, "HARD", 1, 6), (2, "HARD", 7, LAPS)]


def test_one_drivers_passage_does_not_renumber_anothers_laps():
    session = tyre_data(make_race(), "BBB", [(1, "HARD", NEW)] * 6 + [(2, "HARD", float(lap)) for lap in range(7, 13)])

    # AAA stopped on lap 5 and went out on another compound.
    assert numbers(session, "AAA") == [1] * PIT_LAP + [2] * (LAPS - PIT_LAP)
    assert numbers(session, "BBB") == [1] * LAPS
    # CCC, whose laps come after BBB's, ran one set from start to finish.
    assert set(numbers(session, "CCC")) == {1}


# --- an entry to the pit lane says whether the tyres were changed -------------------


def test_a_stop_changed_tyres_and_a_passage_did_not():
    session = drives_through(make_race(), "BBB", 8)

    assert stops_of(session) == {("AAA", PIT_LAP): True, ("BBB", 8): False}


def test_a_passage_under_a_new_number_from_f1_did_not_change_tyres():
    """As F1 sends it: the lap after the passage has the next stint number."""
    session = drives_through(make_race(), "BBB", 8)
    tyre_data(session, "BBB", [(1, "MEDIUM", NEW)] * 8 + [(2, "MEDIUM", float(lap)) for lap in range(9, 13)])

    assert stops_of(session)[("BBB", 8)] is False


@pytest.mark.parametrize(
    ("per_lap", "why"),
    [
        ([(1, None, NEW)] * LAPS, "F1 sent no tyre data for the car"),
        ([(1, "MEDIUM", NEW)] * 8 + [(2, None, NEW)] * 4, "no compound named for the lap after"),
    ],
)
def test_where_the_tyre_data_does_not_say_neither_does_the_entry(per_lap, why):
    session = tyre_data(drives_through(make_race(), "BBB", 8), "BBB", per_lap)

    assert stops_of(session)[("BBB", 8)] is None, why


def test_a_car_that_did_not_go_out_again_is_not_said_to_have_kept_its_tyres():
    session = make_race()
    last = (session.laps["Driver"] == "BBB") & (session.laps["LapNumber"] == LAPS)
    session.laps.loc[last, "PitInTime"] = session.laps.loc[last, "Time"] - pd.Timedelta(seconds=8)

    assert stops_of(session)[("BBB", LAPS)] is None


def test_asked_without_the_stints_no_entry_says_anything_of_its_tyres():
    session = make_race()

    (stop,) = normalize.pit_stops(session, extras(), normalize.driver_codes(session))

    assert stop.tyres_changed is None


# --- what is made of the entries ---------------------------------------------------


def test_a_passage_is_in_no_figure_of_a_pit_stop():
    files = built(drives_through(make_race(), "BBB", 8))

    stops = {(stop["driver_code"], stop["lap_number"]): stop for stop in read(files, "pit-stops.json")}
    strategy = read(files, "analysis/strategy.json")
    reasons = {(row["driver_code"], row["lap_number"]): row["excluded_reason"] for row in strategy["pit_loss"]["stops"]}

    assert {key: stop["tyres_changed"] for key, stop in stops.items()} == {("AAA", PIT_LAP): True, ("BBB", 8): False}
    # The pit-lane figures are of the one stop F1's pit-stop feed reports.
    assert strategy["pit_lane_time"] == {
        "median_ms": stops[("AAA", PIT_LAP)]["duration_ms"],
        "fastest_ms": stops[("AAA", PIT_LAP)]["duration_ms"],
        "slowest_ms": stops[("AAA", PIT_LAP)]["duration_ms"],
        "timed_stop_count": 1,
        "stop_count": 2,
    }
    assert reasons[("BBB", 8)] == "no_stop" and reasons[("AAA", PIT_LAP)] != "no_stop"
    assert strategy["pit_loss"]["excluded_stop_counts"]["no_stop"] == 1
    # And the pace change is across a change of tyres: BBB made none.
    assert [(row["driver_code"], row["stop_lap"]) for row in strategy["undercut_overcut"]] == [("AAA", PIT_LAP)]
    assert [run["driver_code"] for run in read(files, "stints.json")].count("BBB") == 1


def test_a_stop_f1_times_is_a_stop_though_the_tyre_data_has_the_car_on_the_same_set():
    """A penalty served in the pit box, or tyre data that is late: either way the car stopped."""
    session = tyre_data(make_race(), "AAA", [(1, "MEDIUM", NEW)] * LAPS)

    files = built(session)
    (stop,) = read(files, "pit-stops.json")
    strategy = read(files, "analysis/strategy.json")

    assert (stop["stationary_ms"], stop["tyres_changed"]) == (2_400, False)
    assert strategy["pit_loss"]["stops"][0]["excluded_reason"] != "no_stop"
    assert strategy["pit_lane_time"]["timed_stop_count"] == 1
    assert [(row["driver_code"], row["stop_lap"]) for row in strategy["undercut_overcut"]] == [("AAA", PIT_LAP)]


def test_an_entry_f1_reports_no_stop_for_is_not_in_the_pit_lane_figures():
    """Whether or not the tyre data says the car kept its tyres: a time of a stop needs a stop."""
    files = built(found=extras(pit_stops=False))

    strategy = read(files, "analysis/strategy.json")

    assert strategy["pit_lane_time"] == {
        "median_ms": None,
        "fastest_ms": None,
        "slowest_ms": None,
        "timed_stop_count": 0,
        "stop_count": 1,
    }


# --- the races it was found in --------------------------------------------------------


def strategy_of(session, found) -> tuple[list, list, dict]:
    laps = normalize.laps(session)
    stints = normalize.stints(laps)
    stops = normalize.pit_stops(session, found, normalize.driver_codes(session), stints)
    strategy = calculate_strategy(
        "recorded",
        [artifact_json(stint) for stint in stints],
        [artifact_json(stop) for stop in stops],
        [artifact_json(lap) for lap in laps],
        [],
    )
    return stints, stops, strategy


def test_the_2025_canadian_gp_has_the_stints_and_the_stops_that_were_run(tmp_path):
    session, found, _ = recorded(tmp_path, CANADA_2025)

    stints, stops, strategy = strategy_of(session, found)

    verstappen = [(run.compound.value, run.start_lap, run.end_lap) for run in stints if run.driver_code == "VER"]
    assert verstappen == [("MEDIUM", 1, 12), ("HARD", 13, 37), ("HARD", 38, 70)]
    racing = [stop for stop in stops if stop.duration_ms is not None and not stop.under_red_flag]
    assert len(racing) == 82
    # F1 reports a stop for 33 of them, and its tyre data has the car on the
    # same set after each of the other 49.
    assert sum(1 for stop in racing if stop.stationary_ms is not None) == 33
    assert sum(1 for stop in racing if stop.tyres_changed is False) == 49
    assert not any(stop.stationary_ms is not None and stop.tyres_changed is False for stop in racing)
    # 18.3 s and 18.1 s over all 82, which is a car driving through.
    lane = strategy["pit_lane_time"]
    assert (lane["median_ms"], lane["fastest_ms"], lane["timed_stop_count"]) == (23_656.0, 23_047.0, 33)
    assert strategy["pit_loss"]["excluded_stop_counts"].get("no_stop") == 49
    # Nobody's first stop is a passage: each is the lap a stint of theirs ended on.
    ends = {(run.driver_code, run.end_lap) for run in stints}
    assert strategy["undercut_overcut"]
    assert all((row["driver_code"], row["stop_lap"]) in ends for row in strategy["undercut_overcut"])


def test_the_2025_miami_gps_stops_are_stops_though_its_tyre_data_is_late(tmp_path):
    """F1's tyre data for this race starts on lap 24 and shows each change of tyres eight laps after it.

    So it has the car on the same set after twelve stops that the pit-stop
    feed gives a stationary time for. Taken at its word alone, twelve drivers
    made no stop.
    """
    session, found, _ = recorded(tmp_path, MIAMI_2025)

    _, stops, strategy = strategy_of(session, found)

    late = [stop for stop in stops if stop.stationary_ms is not None and stop.tyres_changed is False]
    assert len(late) == 12
    priced = {(row["driver_code"], row["lap_number"]): row["excluded_reason"] for row in strategy["pit_loss"]["stops"]}
    assert all(priced[(stop.driver_code, stop.lap_number)] != "no_stop" for stop in late)
    assert "no_stop" not in strategy["pit_loss"]["excluded_stop_counts"]
    firsts = {row["driver_code"]: row["stop_lap"] for row in strategy["undercut_overcut"]}
    assert all(firsts[stop.driver_code] <= stop.lap_number for stop in late)
    assert firsts["ALB"] == 26


def test_the_2026_dutch_gps_drive_through_is_not_priced_as_a_pit_stop(tmp_path):
    session, found, _ = recorded(tmp_path, DUTCH_2026)

    _, stops, strategy = strategy_of(session, found)

    colapinto = next(stop for stop in stops if (stop.driver_code, stop.lap_number) == ("COL", 8))
    assert (colapinto.duration_ms, colapinto.stationary_ms, colapinto.tyres_changed) == (12_078, None, False)
    priced = {(row["driver_code"], row["lap_number"]): row for row in strategy["pit_loss"]["stops"]}
    assert priced[("COL", 8)]["excluded_reason"] == "no_stop" and priced[("COL", 8)]["pit_loss_ms"] is None
    # The fastest was that drive-through, at 12.1 s.
    assert strategy["pit_lane_time"]["fastest_ms"] > 15_000
    assert all(
        stop.stationary_ms is not None
        for stop in stops
        if stop.duration_ms == strategy["pit_lane_time"]["fastest_ms"]
    )
