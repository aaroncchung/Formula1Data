"""Corner analysis by the circuit's official corners, and telemetry handed over by lap.

docs/architecture-review-findings.md, AR-17: corners used to be inferred from
where drivers braked and numbered in the order found, so "corner 3" was the
third place anyone braked. With the official corner positions the laps are
segmented by the real corners, and the inferred method is what is left when
there are none. AR-11: the telemetry analyses read whole laps at full
resolution, a few laps of a great many, so they can be given telemetry by lap.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.analysis.advanced import (
    OFFICIAL_CORNER_WINDOW_M,
    TelemetryByLap,
    calculate_car_performance,
    calculate_corner_analysis,
    calculate_track_dominance,
)

LAP_LENGTH_M = 4_000
# Two corners the cars brake for and, between them, a kink taken with a lift.
BRAKED = (1_000, 3_000)
KINK = 2_000
CORNERS = [
    {"number": 1, "letter": "", "x": 10_000.0, "y": 0.0, "distance_m": 1_000.0},
    {"number": 2, "letter": "A", "x": 20_000.0, "y": 0.0, "distance_m": 2_000.0},
    {"number": 3, "letter": "", "x": 30_000.0, "y": 0.0, "distance_m": 3_000.0},
]
# How the result names a lap that was not timed, or whose telemetry stops short.
SHORT_LAP = "Not a whole timed lap"


def lap_rows(
    driver, lap_number=5, stretch=1.0, apex_kph=90.0, position=True, stops_at=LAP_LENGTH_M, position_until=None
):
    """A lap along a straight line, sampled every ten metres of track.

    ``stretch`` is how much longer the lap's own distance says the track is:
    two laps of one track disagree by a per cent or so. Position is where the
    car really is, in tenths of a metre. The car stops ``stops_at`` metres
    round, and its position data ``position_until`` metres round.
    """
    rows = []
    elapsed = 0.0
    for step in range(stops_at // 10 + 1):
        place = step * 10.0
        speed, braking = 300.0, False
        for corner in BRAKED:
            if corner - 150 <= place <= corner:
                speed, braking = 300.0 - (300.0 - apex_kph) * (place - (corner - 150)) / 150, True
            elif corner < place <= corner + 200:
                speed = apex_kph + (300.0 - apex_kph) * (place - corner) / 200
        if abs(place - KINK) <= 50:
            speed = 280.0 - 20.0 * (1 - abs(place - KINK) / 50)
        if step:
            elapsed += 10.0 / (speed / 3.6) * 1000
        rows.append(
            {
                "driver_code": driver,
                "lap_number": lap_number,
                "distance_m": place * stretch,
                "relative_time_ms": elapsed,
                "speed_kph": speed,
                "brake": braking,
                "throttle_pct": 0 if braking else 100,
                "x": place * 10 if position else None,
                "y": 0.0 if position else None,
            }
        )
        if position_until is not None and place > position_until:
            rows[-1]["x"] = rows[-1]["y"] = None
    return rows


# What the lap above takes: a timed lap's telemetry runs the length of its time.
LAP_TIME_MS = round(lap_rows("AAA")[-1]["relative_time_ms"])


def passing_close_to(corner, rows, at_m=500):
    """The lap with a stretch of it, ``at_m`` round, moved to run 30 m from a corner it is not at."""
    return [
        {**row, "x": corner["x"] + (row["distance_m"] - at_m) * 10, "y": 300.0}
        if row["x"] is not None and abs(row["distance_m"] - at_m) <= 50
        else row
        for row in rows
    ]


def lap(driver, lap_number=5, lap_time_ms=LAP_TIME_MS):
    return {
        "driver_code": driver, "lap_number": lap_number, "lap_time_ms": lap_time_ms, "is_pit_in_lap": False,
        "is_pit_out_lap": False, "is_deleted": False, "is_accurate": True, "track_status": "1",
    }


def by_corner(result):
    return {
        (corner["corner_number"], corner["letter"]): {row["driver_code"]: row for row in corner["drivers"]}
        for corner in result["corners"]
    }


class OfficialCornerTests(unittest.TestCase):
    def test_laps_are_segmented_by_the_circuits_own_corners_when_they_are_given(self):
        result = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA"), CORNERS)

        self.assertEqual(result["corner_source"], "official")
        self.assertEqual(
            [(corner["corner_number"], corner["letter"], corner["distance_m"]) for corner in result["corners"]],
            [(1, None, 1000.0), (2, "A", 2000.0), (3, None, 3000.0)],
        )
        self.assertEqual((result["corners"][0]["x"], result["corners"][0]["y"]), (10_000.0, 0.0))
        first = by_corner(result)[(1, None)]["AAA"]
        self.assertEqual((first["brake_start_m"], first["apex_distance_m"]), (850.0, 1000.0))
        self.assertEqual((first["entry_speed_kph"], first["apex_speed_kph"], first["speed_loss_kph"]), (300.0, 90.0, 210.0))
        self.assertIn("official corner positions", result["caveats"][0])

    def test_a_corner_nobody_brakes_for_still_has_its_slowest_speed(self):
        """The inferred method cannot see it at all: there is no braking to find."""
        official = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA"), CORNERS)
        inferred = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA"))

        kink = by_corner(official)[(2, "A")]["AAA"]
        self.assertEqual((kink["apex_distance_m"], kink["apex_speed_kph"]), (2000.0, 260.0))
        for field in ("brake_start_m", "braking_distance_m", "entry_speed_kph", "speed_loss_kph", "brake_duration_ms"):
            self.assertIsNone(kink[field], field)
        self.assertIsNotNone(kink["exit_speed_kph"])
        self.assertEqual(len(inferred["corners"]), 2)
        self.assertLess(OFFICIAL_CORNER_WINDOW_M, 1000)

    def test_without_official_corners_they_are_inferred_as_before_and_the_result_says_so(self):
        for corners in (None, [], [{"number": 1}], [{"x": 1.0, "y": 2.0, "distance_m": 3.0}]):
            result = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA"), corners)

            self.assertEqual(result["corner_source"], "inferred")
            self.assertEqual([corner["corner_number"] for corner in result["corners"]], [1, 2])
            self.assertEqual({corner["letter"] for corner in result["corners"]}, {None})
            self.assertIn("inferred from brake application", result["caveats"][0])

    def test_a_corner_is_found_on_each_lap_by_position_whatever_the_lap_says_its_distance_is(self):
        """Two laps of one track disagree about distance. BBB's reads 5% long,
        so by distance its corner 3 is 150 m past where the circuit puts it."""
        laps = [lap("AAA"), lap("BBB")]
        telemetry = lap_rows("AAA") + lap_rows("BBB", stretch=1.05, apex_kph=100.0)

        result = calculate_corner_analysis("s", laps, telemetry, CORNERS)

        third = by_corner(result)[(3, None)]
        self.assertEqual(third["AAA"]["apex_distance_m"], 3000.0)
        self.assertEqual(third["BBB"]["apex_distance_m"], 3150.0)
        self.assertEqual((third["AAA"]["apex_speed_kph"], third["BBB"]["apex_speed_kph"]), (90.0, 100.0))
        # Every driver is in every corner, under the corner's own number.
        self.assertTrue(all(set(drivers) == {"AAA", "BBB"} for drivers in by_corner(result).values()))

    def test_a_timed_lap_is_read_by_position_however_far_out_its_distance_is(self):
        """The 2026 Chinese sprint: F1's car feed repeats itself on eight
        drivers' fastest laps, which then measure the lap from 8% short to 15%
        long. The lap went all the way round, so a sample at a corner is that
        corner."""
        laps = [lap("AAA"), lap("BBB")]
        telemetry = lap_rows("AAA") + lap_rows("BBB", stretch=1.15)

        result = calculate_corner_analysis("s", laps, telemetry, CORNERS)

        corners = by_corner(result)
        self.assertEqual(
            [corners[key]["BBB"]["apex_distance_m"] for key in ((1, None), (2, "A"), (3, None))],
            [1150.0, 2300.0, 3450.0],
        )
        self.assertEqual(corners[(3, None)]["BBB"]["apex_speed_kph"], 90.0)
        self.assertEqual(len(result["caveats"]), 3)

    def test_a_lap_with_no_position_data_is_matched_by_distance_and_the_result_names_it(self):
        """The 2026 Monaco race: no position data after lap 5."""
        laps = [lap("AAA"), lap("BBB")]
        telemetry = lap_rows("AAA") + lap_rows("BBB", stretch=1.05, position=False)

        result = calculate_corner_analysis("s", laps, telemetry, CORNERS, reference_lap_length_m=LAP_LENGTH_M)

        third = by_corner(result)[(3, None)]
        # Scaled to the lap's own length, the corner is where the lap braked for it.
        self.assertEqual(third["BBB"]["apex_distance_m"], 3150.0)
        self.assertIsNotNone(third["BBB"]["brake_start_m"])
        self.assertTrue(any("No position data on the lap of: BBB" in caveat for caveat in result["caveats"]))

    def test_a_lap_that_stops_short_has_no_figures_for_the_corners_it_never_reached(self):
        """The 2026 Monaco race: Verstappen's only lap ends at the chicane. The
        nearest of its samples to each later corner is somewhere else on the
        circuit, and was read as that corner."""
        laps = [lap("AAA"), lap("BBB"), lap("CCC", lap_number=1, lap_time_ms=None)]
        telemetry = lap_rows("AAA") + lap_rows("BBB") + lap_rows("CCC", lap_number=1, stops_at=2_500)

        result = calculate_corner_analysis("s", laps, telemetry, CORNERS, reference_lap_length_m=LAP_LENGTH_M)

        corners = by_corner(result)
        self.assertEqual(set(corners[(3, None)]), {"AAA", "BBB"})
        # The two it drove through are found where they are, not where a lap
        # 2,500 m long would have them.
        self.assertEqual(corners[(1, None)]["CCC"]["apex_distance_m"], 1000.0)
        self.assertEqual(
            (corners[(2, "A")]["CCC"]["apex_distance_m"], corners[(2, "A")]["CCC"]["apex_speed_kph"]), (2000.0, 260.0)
        )
        self.assertTrue(any(SHORT_LAP in caveat and "CCC" in caveat for caveat in result["caveats"]))
        self.assertFalse(any("No position data" in caveat for caveat in result["caveats"]))

    def test_a_lap_that_stops_short_and_has_no_position_data_is_in_no_corner(self):
        """Its distance says how far it got, not where the corners are on it."""
        laps = [lap("AAA"), lap("BBB"), lap("CCC", lap_number=1, lap_time_ms=None)]
        short = lap_rows("CCC", lap_number=1, stops_at=2_500, position=False)
        telemetry = lap_rows("AAA") + lap_rows("BBB") + short

        result = calculate_corner_analysis("s", laps, telemetry, CORNERS, reference_lap_length_m=LAP_LENGTH_M)

        self.assertEqual(result["corner_source"], "official")
        self.assertTrue(all(set(drivers) == {"AAA", "BBB"} for drivers in by_corner(result).values()))
        self.assertEqual([row["driver_code"] for row in result["representative_laps"]], ["AAA", "BBB", "CCC"])
        self.assertTrue(any(SHORT_LAP in caveat and "CCC" in caveat for caveat in result["caveats"]))

    def test_where_a_whole_laps_position_data_stops_its_corners_are_found_by_distance(self):
        """Not by the last sample that had a position, which is nowhere near them."""
        laps = [lap("AAA"), lap("BBB")]
        telemetry = lap_rows("AAA") + lap_rows("BBB", position_until=1_500)

        result = calculate_corner_analysis("s", laps, telemetry, CORNERS)

        corners = by_corner(result)
        self.assertEqual(corners[(1, None)]["BBB"], {**corners[(1, None)]["AAA"], "driver_code": "BBB"})
        self.assertEqual(
            (corners[(2, "A")]["BBB"]["apex_distance_m"], corners[(2, "A")]["BBB"]["apex_speed_kph"]), (2000.0, 260.0)
        )
        self.assertEqual(corners[(3, None)]["BBB"], {**corners[(3, None)]["AAA"], "driver_code": "BBB"})

    def test_a_stretch_of_track_that_passes_a_corner_it_is_not_is_never_taken_for_it(self):
        """Monaco again: Tabac and the swimming pool are within 50 m of the road
        out of Sainte Devote and of the grid. Here every lap runs 30 m from
        corner 3 when it is 500 m round, 2,500 m before it gets there."""
        third = CORNERS[2]
        laps = [lap("AAA"), lap("BBB"), lap("CCC", lap_number=1, lap_time_ms=None)]
        telemetry = (
            passing_close_to(third, lap_rows("AAA"))
            + lap_rows("BBB")
            + passing_close_to(third, lap_rows("CCC", lap_number=1, stops_at=2_500))
        )

        result = calculate_corner_analysis("s", laps, telemetry, CORNERS, reference_lap_length_m=LAP_LENGTH_M)

        corners = by_corner(result)
        # The lap that stopped at 2,500 m never reached the corner.
        self.assertEqual(set(corners[(3, None)]), {"AAA", "BBB"})
        self.assertEqual(set(corners[(2, "A")]), {"AAA", "BBB", "CCC"})
        # And a whole lap has it where it is, not where the lap first ran past it.
        self.assertEqual(corners[(3, None)]["AAA"], {**corners[(3, None)]["BBB"], "driver_code": "AAA"})
        self.assertEqual(corners[(3, None)]["AAA"]["apex_distance_m"], 3000.0)

    def test_a_corner_is_only_found_where_the_lap_passes_it(self):
        """A corner a kilometre off the track is on no lap by position. With a
        distance it is still read by that; with none it is not there at all."""
        elsewhere = [dict(CORNERS[0]), dict(CORNERS[1], y=10_000.0), dict(CORNERS[2])]

        by_distance = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA"), elsewhere)
        unplaced = calculate_corner_analysis(
            "s", [lap("AAA")], lap_rows("AAA"), [{**corner, "distance_m": None} for corner in elsewhere]
        )

        self.assertEqual(by_corner(by_distance)[(2, "A")]["AAA"]["apex_distance_m"], 2000.0)
        self.assertEqual(by_corner(unplaced)[(2, "A")], {})
        self.assertEqual(unplaced["corners"][1]["distance_m"], None)
        self.assertEqual(set(by_corner(unplaced)[(1, None)]), {"AAA"})

    def test_corners_with_no_distance_are_still_found_by_position(self):
        placed_only = [{**corner, "distance_m": None} for corner in CORNERS]

        result = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA"), placed_only)

        self.assertEqual(result["corner_source"], "official")
        # With no official distance, the corner's is where the laps put it.
        self.assertEqual([corner["distance_m"] for corner in result["corners"]], [1000.0, 2000.0, 3000.0])
        self.assertEqual(by_corner(result)[(1, None)]["AAA"]["apex_speed_kph"], 90.0)

    def test_official_corners_no_lap_can_place_fall_back_to_the_inferred_ones(self):
        placed_only = [{**corner, "distance_m": None} for corner in CORNERS]

        result = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA", position=False), placed_only)

        self.assertEqual(result["corner_source"], "inferred")
        self.assertEqual(len(result["corners"]), 2)
        self.assertTrue(any("no position data" in caveat for caveat in result["caveats"]))


class PositionCaveatTests(unittest.TestCase):
    def test_track_dominance_says_when_its_minisectors_cannot_be_drawn(self):
        laps = [lap("AAA"), lap("BBB", lap_time_ms=81_000)]
        for driver in laps:
            driver["lap_time_ms"] = round(lap_rows(driver["driver_code"])[-1]["relative_time_ms"])

        placed = calculate_track_dominance("s", laps, lap_rows("AAA") + lap_rows("BBB"))
        unplaced = calculate_track_dominance(
            "s", laps, lap_rows("AAA", position=False) + lap_rows("BBB", position=False)
        )

        self.assertFalse(any("no position data" in caveat for caveat in placed["caveats"]))
        self.assertTrue(any("no position data" in caveat for caveat in unplaced["caveats"]))
        self.assertEqual(unplaced["minisectors"][0]["midpoint"], {"x": None, "y": None})
        self.assertEqual(
            [sector["winner_driver_code"] for sector in unplaced["minisectors"]],
            [sector["winner_driver_code"] for sector in placed["minisectors"]],
        )


class Counting(TelemetryByLap):
    """Telemetry by lap that records which laps were turned into rows."""

    def __init__(self, telemetry):
        super().__init__(telemetry, lambda row: int(row.get("lap_number") or 0))
        self.asked_for: list[tuple[str, int]] = []

    def lap_rows(self, key):
        self.asked_for.append(key)
        return super().lap_rows(key)


class TelemetryByLapTests(unittest.TestCase):
    def setUp(self):
        self.laps, self.rows = [], []
        for driver in ("AAA", "BBB"):
            for number in range(2, 12):
                samples = lap_rows(driver, number, apex_kph=90.0 + number)
                self.rows += samples
                self.laps.append(lap(driver, number, lap_time_ms=round(samples[-1]["relative_time_ms"])))
        self.drivers = [{"code": "AAA", "team": {"name": "Alpha"}}, {"code": "BBB", "team": {"name": "Alpha"}}]

    def test_telemetry_by_lap_gives_what_the_flat_list_of_rows_gives(self):
        by_lap = Counting(self.rows)

        self.assertEqual(
            calculate_track_dominance("s", self.laps, by_lap), calculate_track_dominance("s", self.laps, self.rows)
        )
        self.assertEqual(
            calculate_corner_analysis("s", self.laps, by_lap, CORNERS),
            calculate_corner_analysis("s", self.laps, self.rows, CORNERS),
        )
        self.assertEqual(
            calculate_car_performance("s", self.laps, by_lap, self.drivers),
            calculate_car_performance("s", self.laps, self.rows, self.drivers),
        )

    def test_only_the_laps_an_analysis_reads_are_turned_into_rows(self):
        """Twenty laps here, 1,339 in a race: an analysis reads one a driver."""
        by_lap = Counting(self.rows)

        calculate_corner_analysis("s", self.laps, by_lap, CORNERS)
        calculate_car_performance("s", self.laps, by_lap, self.drivers)

        self.assertEqual(len(by_lap.lap_keys()), 20)
        self.assertEqual(sorted(set(by_lap.asked_for)), [("AAA", 11), ("BBB", 11)])

    def test_a_lap_with_no_telemetry_is_simply_not_there(self):
        by_lap = TelemetryByLap(self.rows, lambda row: int(row.get("lap_number") or 0))

        self.assertEqual(by_lap.lap_sample_count(("CCC", 1)), 0)
        self.assertEqual(by_lap.lap_rows(("CCC", 1)), [])
        self.assertEqual(by_lap.lap_end_m(("AAA", 2)), float(LAP_LENGTH_M))


if __name__ == "__main__":
    unittest.main()
