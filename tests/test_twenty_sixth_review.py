"""The cases the twenty-sixth review of this code found (GPT-6.1 Sol, 2026-10-07, at dcf382d).

The round confirmed the three fixes of the one before over all 51 archived
sessions, and was asked to read every sentence the analyses publish beside
their figures and say whether it is true of the data it is published with.
Three were not, in one race or another:

- "each within 3 laps of the driver's first stop", of a lap four lap numbers
  after it: the three are counted from the out-lap.
- "No clean green-flag lap within 3 laps after the stop", of a driver who ran
  one: it was after their next stop, which is where the search ends.
- "the 10% of matched laps with the largest difference each way are dropped",
  of five matched laps, of which one each way is a fifth.

The fourth finding is the site's: lap B's "Maximum speed" was read from lap B
as it is laid under lap A, and so was lower than the lap's own
(frontend/tests/telemetry-compare.test.mjs).
"""

from __future__ import annotations

from backend.app.analysis.teammate_comparison import calculate_teammate_comparison
from f1data import normalize
from f1data.models import artifact_json
from tests.test_recorded_race import recorded
from tests.test_twenty_third_review import strategy_of

AUSTRALIA_2026 = 11234
QATAR_2025 = 9850


def test_the_lap_after_a_stop_is_looked_for_from_the_out_lap_and_the_caveat_says_so(tmp_path):
    """The 2026 Australian GP: Alonso stops on lap 11 and is compared across laps 10 and 15."""
    session, found, _ = recorded(tmp_path, AUSTRALIA_2026)

    _, _, strategy = strategy_of(session, found)

    (row,) = [row for row in strategy["undercut_overcut"] if row["driver_code"] == "ALO"]
    assert (row["stop_lap"], row["before_lap_number"], row["after_lap_number"]) == (11, 10, 15)
    assert row["first_clean_lap_gain_ms"] == 1_762
    said = " ".join(strategy["caveats"])
    assert "in the 3 laps before the in-lap minus the first one in the 3 laps after the out-lap" in said
    assert "within 3 laps of" not in said


def test_a_search_cut_short_by_the_next_stop_says_that_and_not_that_no_lap_was_there(tmp_path):
    """The 2025 Qatar GP: Ocon stops on laps 8 and 9, and runs a clean lap 11."""
    session, found, _ = recorded(tmp_path, QATAR_2025)

    _, stops, strategy = strategy_of(session, found)

    assert [stop.lap_number for stop in stops if stop.driver_code == "OCO"][:2] == [8, 9]
    (row,) = [row for row in strategy["undercut_overcut"] if row["driver_code"] == "OCO"]
    assert (row["stop_lap"], row["first_clean_lap_gain_ms"], row["after_lap_number"]) == (8, None, None)
    assert "after the out-lap and before the next stop, on lap 9" in row["caveat"]
    # No row of the race still says a lap was not there within "3 laps after the stop".
    assert not any("laps after the stop" in row["caveat"] for row in strategy["undercut_overcut"])


def test_the_trimming_is_said_to_be_of_at_least_one_lap_each_way(tmp_path):
    """The 2025 Qatar GP: Hulkenberg and Bortoleto have five matched laps, and one is dropped each way."""
    session, _, _ = recorded(tmp_path, QATAR_2025)

    laps = [artifact_json(lap) for lap in normalize.laps(session)]
    drivers = [
        {"code": driver.code, "team": {"name": driver.team.name, "color": driver.team.color} if driver.team else {}}
        for driver in normalize.drivers(session, normalize.driver_codes(session))
    ]
    result = calculate_teammate_comparison("recorded", laps, drivers)

    (row,) = [row for row in result["rows"] if {driver["driver_code"] for driver in row["drivers"]} == {"HUL", "BOR"}]
    assert (row["matched_lap_count"], row["trimmed_lap_count"], row["gap_ms"]) == (5, 2, 518.7)
    assert "and never fewer than one lap each way, are dropped" in " ".join(result["caveats"])
