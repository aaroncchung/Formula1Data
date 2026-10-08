"""The cases the thirty-first review of this code found (GPT-6.1 Sol, 2026-10-08, at 03f26a7).

The round confirmed the two fixes of the round before, and found three
things more, all of them in the corner table.

- A corner the driver braked for was published as not braked for whenever
  its braking was counted for another corner. Brakings were found along the
  whole lap, two applications within 80 m were one, and the one corner its
  slowest point fell in was given it. Albon into turn 5 of the 2026 Monaco
  GP, and Alonso into turn 9 of the 2026 Australian GP, were the two it
  named. It was the rule and not the two laps: 16 of the 22 drivers at
  Monaco's turn 5, and 18 of 21 at the first corner of Monza.
- The site read only the newer word for what is known of a corner's braking,
  so a generation built with the older one said "No braking" again.
- The table put the corner's distance along the lap the corners were placed
  on beside a brake point along the driver's own lap.

The stand-in cases are in backend/tests/test_corner_analysis.py and
frontend/tests; these are the races, from the archive.
"""

from __future__ import annotations

import json

from f1data.archive import read_raw_response
from f1data.artifacts import build_artifacts
from f1data.carfeed import CAR_FEED
from f1data.coverage import measure_coverage
from tests.recorded import archive_store
from tests.test_recorded_race import recorded

AUSTRALIA_2026 = 11234
MONACO_2026 = 11299
AUSTRIA_2026 = 11315
ITALY_2026 = 11361


def corner_analysis(tmp_path, session_key: int) -> dict:
    session, found, snapshot = recorded(tmp_path, session_key)
    feed = read_raw_response(archive_store(), snapshot, CAR_FEED)
    files = build_artifacts(session, snapshot.identity, None, found, measure_coverage(session, "R", found), feed)
    return json.loads(files["analysis/corner-analysis.json"])


def rows_of(result: dict, turn: int) -> dict[str, dict]:
    corner = next(corner for corner in result["corners"] if corner["corner_number"] == turn and not corner["letter"])
    return {row["driver_code"]: row for row in corner["drivers"]}


def lap_of(result: dict, driver: str) -> int:
    return next(row["lap_number"] for row in result["representative_laps"] if row["driver_code"] == driver)


def test_monacos_turn_five_and_its_hairpin_each_have_their_own_braking(tmp_path):
    """Albon's lap 78: off the brake at 79 km/h for turn 5, and on again 74 m later, at 140 km/h, for the hairpin."""
    result = corner_analysis(tmp_path, MONACO_2026)

    assert result["corner_source"] == "official" and lap_of(result, "ALB") == 78
    five, hairpin = rows_of(result, 5)["ALB"], rows_of(result, 6)["ALB"]
    assert (five["braking"], five["brake_start_m"], five["entry_speed_kph"]) == ("seen", 1009.7, 212.0)
    assert (five["apex_distance_m"], five["apex_speed_kph"], five["brake_duration_ms"]) == (1105.8, 72.0, 2479.0)
    # The hairpin's braking is its own: it was turn 5's, from 212 km/h, with the brake "on" for 14 seconds.
    assert (hairpin["braking"], hairpin["brake_start_m"], hairpin["entry_speed_kph"]) == ("seen", 1163.4, 140.0)
    assert (hairpin["apex_distance_m"], hairpin["apex_speed_kph"], hairpin["brake_duration_ms"]) == (1226.4, 43.0, 1959.0)
    # Every driver braked for both, and it is said of every one: of turn 5
    # it was said of six of the twenty-two.
    for turn in (5, 6):
        assert {row["braking"] for row in rows_of(result, turn).values()} == {"seen"}, turn
    assert len(rows_of(result, 5)) == 22
    # And no hairpin has a brake point from before turn 5, 120 m and more back.
    assert max(row["corner_distance_m"] - row["brake_start_m"] for row in rows_of(result, 6).values()) < 100


def test_a_braking_through_two_corners_of_the_2026_australian_gp_is_given_for_both(tmp_path):
    """Alonso's lap 15: 250 km/h to 222 for turn 9, off the brake for 67 m with the car still slowing, on again for turn 10."""
    result = corner_analysis(tmp_path, AUSTRALIA_2026)

    assert lap_of(result, "ALO") == 15
    nine, ten = rows_of(result, 9)["ALO"], rows_of(result, 10)["ALO"]
    assert (nine["braking"], nine["brake_start_m"], nine["entry_speed_kph"]) == ("seen", 3206.5, 250.0)
    assert (nine["apex_distance_m"], nine["apex_speed_kph"], nine["brake_duration_ms"]) == (3306.5, 210.0, 906.0)
    assert (ten["braking"], ten["brake_start_m"], ten["apex_distance_m"], ten["apex_speed_kph"]) == (
        "seen", 3206.5, 3389.8, 193.0,
    )
    # Nobody is said not to have braked for turn 9, which six drivers were.
    assert "none" not in {row["braking"] for row in rows_of(result, 9).values()}

    # Stroll's lap 36: the brake reads on for 636 m, most of it at full
    # throttle, from 150 km/h up to 253 and down to 189 for turn 6. He braked,
    # and where he began to is not where the reading went on.
    assert lap_of(result, "STR") == 36
    stroll = rows_of(result, 6)["STR"]
    assert (stroll["braking"], stroll["brake_start_m"], stroll["apex_speed_kph"]) == ("began_unread", None, 189.0)
    said = " ".join(result["caveats"])
    began = said[said.index("where the braking for a corner began") :].split(".")[0]
    assert "has the brake on there while the car gathers speed" in began and "STR" in began


def test_the_first_chicane_of_the_2026_italian_gp_was_braked_for_at_both_its_corners(tmp_path):
    result = corner_analysis(tmp_path, ITALY_2026)

    assert lap_of(result, "PIA") == 45
    first, second = rows_of(result, 1)["PIA"], rows_of(result, 2)["PIA"]
    # From 305 km/h. The first corner was published with no brake reading, and for 18 other drivers as not braked for.
    assert (first["braking"], first["brake_start_m"], first["entry_speed_kph"]) == ("seen", 779.8, 305.0)
    assert (first["apex_distance_m"], first["apex_speed_kph"]) == (914.6, 74.6)
    assert (second["braking"], second["brake_start_m"], second["apex_distance_m"], second["apex_speed_kph"]) == (
        "seen", 779.8, 946.2, 67.0,
    )
    assert "none" not in {row["braking"] for row in rows_of(result, 1).values()}


def test_a_corner_row_of_the_2026_austrian_gp_says_where_its_own_lap_has_the_corner(tmp_path):
    """Stroll's lap 30 has turn 6 at 2,553.8 m; the lap the corners were placed on has it at 2,517.8 m."""
    result = corner_analysis(tmp_path, AUSTRIA_2026)

    assert lap_of(result, "STR") == 30
    turn_six = next(corner for corner in result["corners"] if corner["corner_number"] == 6)
    stroll = rows_of(result, 6)["STR"]
    assert turn_six["distance_m"] == 2517.8
    assert (stroll["corner_distance_m"], stroll["brake_start_m"], stroll["apex_distance_m"]) == (2553.8, 2424.9, 2567.7)
    # Every row of the race has one, and it is on that row's own lap: between where the driver braked and
    # where they were slowest, give or take the length of a corner.
    for corner in result["corners"]:
        for row in corner["drivers"]:
            assert abs(row["corner_distance_m"] - row["apex_distance_m"]) < 150, (corner["corner_number"], row)
