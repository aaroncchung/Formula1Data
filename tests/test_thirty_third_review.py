"""The case the thirty-third review of this code found (GPT-6.1 Sol, 2026-10-08, at ce1b7d1), and what it showed.

The round confirmed both fixes of the round before and found one thing
left: the analysis put a corner at the nearest sample of the lap, where the
lap comparison's chart puts it where the line between two samples comes
nearest. Either feed can miss a second, and the two then stand tens of
metres apart: Piastri's lap 61 of the 2026 Dutch GP has turn 14 at 3,922 m
in the table and 3,884 m on the chart.

Putting the corners between samples moved every one of them by a metre or
so, and 35 rows went from braked for to not braked for. Which braking was
a corner's turned on which side of a line a sample fell: the corner itself,
and the half-way point to the next. That rule is replaced by one that turns
on how much the car slows in the corner's stretch.

The stand-in cases are in backend/tests/test_corner_analysis.py; these are
the races, from the archive.
"""

from __future__ import annotations

from tests.test_thirty_first_review import corner_analysis, lap_of, rows_of

JAPAN_2025 = 10006
BAHRAIN_2025 = 10014
DUTCH_2026 = 11353


def test_a_corner_the_feeds_miss_a_second_at_is_where_the_line_between_two_samples_passes_it(tmp_path):
    """Piastri's lap 61 of the 2026 Dutch GP, turn 14: the nearest sample is 37 m from the corner."""
    result = corner_analysis(tmp_path, DUTCH_2026)

    assert lap_of(result, "PIA") == 61
    # The chart of the published lap draws the corner at 3,883.8 m. The table said 3,922.4 m.
    assert rows_of(result, 14)["PIA"]["corner_distance_m"] == 3884.0


def test_albons_turn_seven_at_suzuka_is_where_his_line_passes_it(tmp_path):
    result = corner_analysis(tmp_path, JAPAN_2025)

    assert lap_of(result, "ALB") == 52
    # 1,872.4 m in the table, against 1,838.8 m on the chart of the published lap.
    assert rows_of(result, 7)["ALB"]["corner_distance_m"] == 1836.3


def test_a_brake_that_goes_on_three_metres_past_a_corner_is_not_a_corner_not_braked_for(tmp_path):
    """Albon's lap 47 of the 2025 Bahrain GP, turn 5: on at 1,759.7 m, and 33 km/h off in turn 5's stretch.

    With the corner at a sample, the brake went on "at" it and the row had
    the braking. With the corner where the line passes it, 3.5 m before,
    the brake went on past it and the row said "none".
    """
    result = corner_analysis(tmp_path, BAHRAIN_2025)

    assert lap_of(result, "ALB") == 47
    row = rows_of(result, 5)["ALB"]
    assert (row["braking"], row["corner_distance_m"], row["brake_start_m"]) == ("seen", 1756.2, 1759.7)
    assert (row["entry_speed_kph"], row["apex_distance_m"], row["apex_speed_kph"]) == (235.0, 1795.9, 202.2)
    assert "one that begins past a corner, in its stretch, is given for it" in result["caveats"][1]
