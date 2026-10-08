"""The cases the thirty-second review of this code found (GPT-6.1 Sol, 2026-10-08, at 8e31d99), and one beside them.

The round confirmed the three fixes of the round before and found two
things in what they had added.

- Whether the brake going on again is the same braking was judged by the
  car's speed at the two ends, and missed a car that goes on slowing after
  the brake comes off and then gathers speed: Bearman in the chicane of the
  2025 Japanese GP, whose second part was published as braked for from 255
  km/h.
- The telemetry chart looked for a corner within 200 m of the corner map's
  distance, on a lap whose own distance was 247 m out: Alonso's first lap of
  the 2026 Austrian GP.

The second was in the site alone. Looked for in the analysis, the same rule
was there and did the same to whole laps whose distance runs long after a
stretch with no car data: Colapinto's lap 53 of the 2026 Italian GP has the
first Lesmo 37 m before where his line passes it. And a lap that has
position data where a corner should be, nowhere near the corner, was given
figures for it by distance: Antonelli's lap 9 of the 2025 British GP, which
ends down the pit entry.

The stand-in cases are in backend/tests/test_corner_analysis.py and
frontend/tests/circuit-layout.test.mjs; these are the races, from the
archive.
"""

from __future__ import annotations

from tests.test_thirty_first_review import corner_analysis, lap_of, rows_of

JAPAN_2025 = 10006
BRITAIN_2025 = 9947
ITALY_2026 = 11361


def test_bearmans_chicane_at_suzuka_is_two_brakings(tmp_path):
    """Lap 49: off the brake at 91 km/h, down to 85, up to 103, and on again at 97 for 8 m."""
    result = corner_analysis(tmp_path, JAPAN_2025)

    assert lap_of(result, "BEA") == 49
    first, second = rows_of(result, 16)["BEA"], rows_of(result, 17)["BEA"]
    assert (first["braking"], first["brake_start_m"], first["entry_speed_kph"]) == ("seen", 5268.1, 255.0)
    assert (first["apex_distance_m"], first["apex_speed_kph"], first["brake_duration_ms"]) == (5373.3, 85.0, 2397.0)
    # The second application takes 97 km/h to 93, which is not counted, and the first is not the second part's:
    # it was, from 255 km/h and 144 m back.
    assert (second["braking"], second["brake_start_m"]) == ("none", None)
    assert (second["apex_distance_m"], second["apex_speed_kph"]) == (5411.7, 93.0)


def test_a_lap_whose_distance_runs_long_has_its_corners_where_its_line_passes_them(tmp_path):
    """Colapinto's lap 53 of the 2026 Italian GP: the first Lesmo is 2,757 m round it, 233 m on from its official distance."""
    result = corner_analysis(tmp_path, ITALY_2026)

    assert lap_of(result, "COL") == 53
    lesmo, ascari = rows_of(result, 6)["COL"], rows_of(result, 9)["COL"]
    # It was put at 2,720.1 m, a sample 32 m from the corner that was within 200 m of the official distance.
    assert (lesmo["corner_distance_m"], lesmo["brake_start_m"], lesmo["apex_distance_m"]) == (2757.0, 2653.2, 2730.6)
    assert ascari["corner_distance_m"] == 4220.8
    assert "Not seen at a corner" not in " ".join(result["caveats"])


def test_a_lap_that_ends_down_the_pit_entry_has_no_figures_for_the_corners_it_did_not_take(tmp_path):
    """Antonelli's lap 9 of the 2025 British GP is 99 m from turn 17 and 92 m from turn 18 where they should be."""
    result = corner_analysis(tmp_path, BRITAIN_2025)

    assert lap_of(result, "ANT") == 9
    assert "ANT" in rows_of(result, 16)
    # He was given figures for both, read at their distance along a lap he was not on the track for.
    assert "ANT" not in rows_of(result, 17) and "ANT" not in rows_of(result, 18)
    assert (
        "Not seen at a corner on the lap compared: ANT at turn 17, 18. The lap's position data does not come "
        "within 50 m of the corner"
    ) in " ".join(result["caveats"])
    # Everyone else took them.
    assert len(rows_of(result, 17)) == len(rows_of(result, 16)) - 1
