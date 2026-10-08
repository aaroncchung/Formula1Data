"""The cases the twenty-fifth review of this code found (GPT-6.1 Sol, 2026-10-07, at 3b539af).

The round confirmed the five fixes of the one before, and was asked to go
through every number the site prints for a session that no earlier round had
checked against the archive. Three had words beside them that said something
else. None is a wrong number: each is a number under the wrong name.

- "Laps fitted: 23" beside "Outliers: 1", for a slope fitted to 22.
- "Quicker on the new tyres" across a stop the car left on the tyres it came
  in on.
- "0 clean laps" for a stint of 19 clean laps on a set F1 gives no age for.

The words of the first two are the site's (frontend/tests/tyre-chart.test.mjs
and strategy-view.test.mjs); these are the figures behind all three, in the
races they were found in, from the archive.
"""

from __future__ import annotations

from backend.app.analysis.advanced import MIN_DEGRADATION_LAPS, calculate_fuel_adjusted_tyre_degradation
from f1data import normalize
from f1data.models import artifact_json
from tests.test_recorded_race import recorded
from tests.test_twenty_third_review import strategy_of

AUSTRIA_2026 = 11315
BARCELONA_2026 = 11307
DUTCH_SPRINT_2026 = 11348


def degradation_of(session, session_type: str = "R") -> dict[tuple[str, int], dict]:
    laps = [artifact_json(lap) for lap in normalize.laps(session)]
    result = calculate_fuel_adjusted_tyre_degradation("recorded", {"type": session_type}, laps)
    return {(row["driver_code"], row["stint"]): row for row in result["rows"]}


def test_the_laps_a_fit_was_left_without_are_counted_apart_from_the_laps_it_is_of(tmp_path):
    """The 2026 Austrian GP, Antonelli's second stint, on hards."""
    session, _, _ = recorded(tmp_path, AUSTRIA_2026)

    row = degradation_of(session)[("ANT", 2)]

    assert (row["compound"], row["fit_status"]) == ("HARD", "ok")
    # 23 clean laps with a tyre age, of which one was left out: the slope is of 22.
    assert (row["sample_count"], row["excluded_outlier_count"]) == (23, 1)
    assert row["raw_slope_ms_per_lap"] == 34.1


def test_a_stint_on_a_set_f1_gives_no_age_for_is_short_of_ages_and_not_of_clean_laps(tmp_path):
    """The 2026 Barcelona GP, Bearman's third stint: laps 41 to 59 on softs that went on used."""
    session, _, _ = recorded(tmp_path, BARCELONA_2026)

    row = degradation_of(session)[("BEA", 3)]

    assert (row["compound"], row["fit_status"]) == ("SOFT", "too_few_laps")
    assert (row["sample_count"], row["stint_length"]) == (0, 19)
    assert row["caveats"] == [
        "No rate reported: F1 gives a tyre age for 0 of the stint's 19 clean laps, and at least "
        f"{MIN_DEGRADATION_LAPS} with one are required. It gives none for a set that went on used."
    ]


def test_a_stop_on_the_same_set_is_said_to_be_that_and_its_pace_change_is_not_of_new_tyres(tmp_path):
    """The 2026 Dutch sprint: Sainz stood for 8.4 s on lap 16 and kept his tyres."""
    session, found, _ = recorded(tmp_path, DUTCH_SPRINT_2026)

    stints, stops, strategy = strategy_of(session, found)

    sainz = next(stop for stop in stops if (stop.driver_code, stop.lap_number) == ("SAI", 16))
    assert (sainz.stationary_ms, sainz.tyres_changed, sainz.under_red_flag) == (8_400, False, False)
    # One stint from start to finish: he never changed.
    assert [(run.start_lap, run.end_lap) for run in stints if run.driver_code == "SAI"] == [(1, 23)]
    # It is a stop, and the pace change across it is what it was.
    (row,) = [row for row in strategy["undercut_overcut"] if row["driver_code"] == "SAI"]
    assert (row["stop_lap"], row["before_lap_number"], row["after_lap_number"]) == (16, 15, 18)
    assert row["first_clean_lap_gain_ms"] == 77
    # What is said of it no longer claims a change of tyres.
    said = " ".join(strategy["caveats"])
    assert "positive is quicker after the stop" in said and "new tyres" not in said
