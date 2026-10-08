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


def driven(profile, length_m=2_000, driver="AAA"):
    """A lap along a straight line, sampled every ten metres, and the time it takes.

    ``profile`` gives the car's speed at a place and whether the brake is on
    there, or None for a sample with no brake reading.
    """
    rows, elapsed = [], 0.0
    for step in range(length_m // 10 + 1):
        place = step * 10.0
        speed, braking = profile(place)
        if step:
            elapsed += 10.0 / (speed / 3.6) * 1000
        rows.append(
            {
                "driver_code": driver, "lap_number": 5, "distance_m": place, "relative_time_ms": elapsed,
                "speed_kph": speed, "brake": braking, "throttle_pct": 0 if braking else 100,
                "x": place * 10, "y": 0.0,
            }
        )
    return rows, round(elapsed)


def between(place, start, end, from_kph, to_kph):
    """The speed at ``place`` of a car going steadily from one speed at ``start`` to another at ``end``."""
    return from_kph + (to_kph - from_kph) * (place - start) / (end - start)


def corners_at(*places):
    return [
        {"number": number, "letter": "", "x": place * 10.0, "y": 0.0, "distance_m": float(place)}
        for number, place in enumerate(places, start=1)
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

    def test_a_corner_with_no_brake_reading_on_the_way_in_is_not_a_corner_nobody_braked_for(self):
        """Gasly's lap 56 of the 2026 Australian GP, turn 9: no brake reading from 311 km/h down to 218.

        F1's car feed has stretches with no reading of the brake. With none
        on the approach, no braking is seen, and the corner was published
        with a null brake point, which the page reads out as "no braking".
        """
        rows = lap_rows("AAA")
        for row in rows:
            if 800 <= row["distance_m"] <= 1_000:
                row["brake"] = None

        result = calculate_corner_analysis("s", [lap("AAA")], rows, CORNERS)
        first, kink, third = (by_corner(result)[key]["AAA"] for key in ((1, None), (2, "A"), (3, None)))

        self.assertEqual(first["braking"], "unread")
        for field in ("brake_start_m", "braking_distance_m", "entry_speed_kph", "speed_loss_kph", "brake_duration_ms"):
            self.assertIsNone(first[field], field)
        # What the speed shows of the corner is still there.
        self.assertEqual((first["apex_distance_m"], first["apex_speed_kph"]), (1000.0, 90.0))
        # A corner nobody braked for, with the brake read all the way, is known to be that.
        self.assertEqual(kink["braking"], "none")
        self.assertIsNone(kink["brake_start_m"])
        # And a corner that was braked for, with every reading, has its figures.
        self.assertEqual(third["braking"], "seen")
        self.assertEqual(third["brake_start_m"], 2850.0)
        self.assertIn(
            "no brake reading on part of the approach to a corner, and shows no braking for it, for: AAA. "
            "Whether the driver braked there is not known",
            result["caveats"][-1],
        )
        self.assertNotIn("The driver braked", " ".join(result["caveats"]))

    def test_the_reading_may_come_back_before_the_corner_with_the_braking_already_done(self):
        """As it was for Gasly: the brake is read again 50 m before the slowest point, and is off."""
        rows = lap_rows("AAA")
        for row in rows:
            if 780 <= row["distance_m"] <= 920:
                row["brake"] = None
            elif 920 < row["distance_m"] <= 1_000:
                row["brake"] = False

        first = by_corner(calculate_corner_analysis("s", [lap("AAA")], rows, CORNERS))[(1, None)]["AAA"]

        # Nothing within 75 m of the corner lacks a reading, and none of it is
        # braking. The car still arrived 210 km/h slower than it set out.
        self.assertIsNone(first["brake_start_m"])
        self.assertEqual(first["braking"], "unread")
        self.assertEqual(first["apex_speed_kph"], 90.0)

    def test_braking_that_is_first_seen_where_the_reading_comes_back_did_not_begin_there(self):
        rows = lap_rows("AAA")
        # No reading for the first hundred metres of the braking for turn 1,
        # which begins at 850 m: it comes back at 950 m with the brake on.
        for row in rows:
            if 800 <= row["distance_m"] < 950:
                row["brake"] = None

        result = calculate_corner_analysis("s", [lap("AAA")], rows, CORNERS)
        first = by_corner(result)[(1, None)]["AAA"]

        # The braking is found, by its slowest point. Where it began is not
        # 950 m, and nothing counted from there is given.
        self.assertEqual(first["braking"], "began_unread")
        # He braked, and it is said that he did: Russell into turn 1 of the
        # 2026 Australian GP was said not to be known to have braked at all.
        said = " ".join(result["caveats"])
        self.assertIn("no brake reading where the braking for a corner began", said)
        self.assertIn("for: AAA. The driver braked, from a point that is not known", said)
        self.assertNotIn("Whether the driver braked", said)
        self.assertEqual((first["apex_distance_m"], first["apex_speed_kph"]), (1000.0, 90.0))
        for field in ("brake_start_m", "braking_distance_m", "entry_speed_kph", "speed_loss_kph", "brake_duration_ms"):
            self.assertIsNone(first[field], field)
        self.assertIsNotNone(first["exit_speed_kph"])

    def test_a_reading_lost_after_the_braking_began_leaves_where_it_began(self):
        rows = lap_rows("AAA")
        # The reading goes at 1,010 m, straight after the last sample braked on.
        for row in rows:
            if 1_000 < row["distance_m"] <= 1_100:
                row["brake"] = None

        first = by_corner(calculate_corner_analysis("s", [lap("AAA")], rows, CORNERS))[(1, None)]["AAA"]

        self.assertEqual(first["braking"], "seen")
        self.assertEqual((first["brake_start_m"], first["entry_speed_kph"], first["apex_speed_kph"]), (850.0, 300.0, 90.0))
        # How long the brake was on is not known: it may have stayed on.
        self.assertIsNone(first["brake_duration_ms"])

    def test_a_stretch_with_no_reading_away_from_any_corner_changes_nothing(self):
        rows = lap_rows("AAA")
        for row in rows:
            if 300 <= row["distance_m"] <= 500:
                row["brake"] = None

        marked = calculate_corner_analysis("s", [lap("AAA")], rows, CORNERS)
        plain = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA"), CORNERS)

        self.assertEqual(marked["corners"], plain["corners"])
        self.assertEqual(
            {row["braking"] for corner in plain["corners"] for row in corner["drivers"]}, {"seen", "none"}
        )
        # And nothing is said of a brake that was read wherever it mattered.
        self.assertEqual(marked["caveats"], plain["caveats"])
        self.assertNotIn("no brake reading", " ".join(plain["caveats"]))

    def test_inferred_corners_that_cannot_be_placed_on_a_map_are_counted(self):
        """The 2026 Monaco race built without its circuit file: one corner of nine has a position."""
        whole = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA"))
        part = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA", position_until=1_500))
        none = calculate_corner_analysis("s", [lap("AAA")], lap_rows("AAA", position=False))

        self.assertEqual([corner["x"] is None for corner in part["corners"]], [False, True])
        self.assertIn("1 of the 2 corners cannot be placed on a map", part["caveats"][-1])
        self.assertIn("The laps compared have no position data, so the corners cannot be placed", none["caveats"][-1])
        self.assertNotIn("position data", " ".join(whole["caveats"]))

    def test_a_brakings_slowest_point_is_before_the_next_braking_begins(self):
        """Albon's lap 36 of the 2026 Australian GP: a light braking for turn 12, and 180 m on a heavy one for turn 13.

        The slowest point of a braking was looked for up to 250 m past where
        the brake came off, whatever lay there. The first braking found the
        second one's corner: turn 12 was published as not braked for, and
        turn 13 with turn 12's brake point, 287 m before it.
        """
        rows, elapsed = [], 0.0
        for step in range(301):
            place = step * 10.0
            speed, braking = 204.0, False
            if 1_000 <= place <= 1_040:
                speed, braking = 204.0 - 16.0 * (place - 1_000) / 40, True
            elif 1_040 < place <= 1_070:
                # Off the brake and still slowing, as a car is through a corner.
                speed = 188.0 - 8.0 * (place - 1_040) / 30
            elif 1_070 < place < 1_220:
                speed = 180.0 + 19.0 * (place - 1_070) / 150
            elif 1_220 <= place <= 1_290:
                speed, braking = 199.0 - 91.0 * (place - 1_220) / 70, True
            elif 1_290 < place <= 1_500:
                speed = 108.0 + 96.0 * (place - 1_290) / 210
            if step:
                elapsed += 10.0 / (speed / 3.6) * 1000
            rows.append(
                {
                    "driver_code": "AAA", "lap_number": 5, "distance_m": place, "relative_time_ms": elapsed,
                    "speed_kph": speed, "brake": braking, "throttle_pct": 0 if braking else 100,
                    "x": place * 10, "y": 0.0,
                }
            )
        corners = [
            {"number": 12, "letter": "", "x": 10_400.0, "y": 0.0, "distance_m": 1_040.0},
            {"number": 13, "letter": "", "x": 12_900.0, "y": 0.0, "distance_m": 1_290.0},
        ]

        result = calculate_corner_analysis("s", [lap("AAA", lap_time_ms=round(elapsed))], rows, corners)
        twelve, thirteen = (by_corner(result)[key]["AAA"] for key in ((12, None), (13, None)))

        self.assertEqual(twelve["braking"], "seen")
        self.assertEqual((twelve["brake_start_m"], twelve["entry_speed_kph"]), (1000.0, 204.0))
        # Its slowest point is past where the brake came off, and short of the next braking.
        self.assertEqual((twelve["apex_distance_m"], twelve["apex_speed_kph"]), (1070.0, 180.0))
        self.assertEqual(thirteen["braking"], "seen")
        self.assertEqual((thirteen["brake_start_m"], thirteen["entry_speed_kph"]), (1220.0, 199.0))
        self.assertEqual((thirteen["apex_distance_m"], thirteen["apex_speed_kph"], thirteen["braking_distance_m"]), (1290.0, 108.0, 70.0))

    def test_two_brakings_for_two_corners_close_together_are_each_corners_own(self):
        """Albon's lap 78 of the 2026 Monaco GP: off the brake at 79 km/h for turn 5, on again 74 m later at 140.

        Any two applications within 80 m were one braking, and the corner
        its slowest point fell in had it: the hairpin, with a brake point
        before turn 5, and turn 5 was published as not braked for.
        """

        def profile(place):
            if place < 1_010:
                return 212.0, False
            if place <= 1_090:
                return between(place, 1_010, 1_090, 212, 79), True
            if place <= 1_100:
                return between(place, 1_090, 1_100, 79, 72), False
            if place < 1_160:
                return between(place, 1_100, 1_160, 72, 140), False
            if place <= 1_220:
                return between(place, 1_160, 1_220, 140, 45), True
            if place <= 1_230:
                return between(place, 1_220, 1_230, 45, 43), False
            return min(250.0, between(place, 1_230, 1_400, 43, 150)), False

        rows, lap_time = driven(profile)

        result = calculate_corner_analysis("s", [lap("AAA", lap_time_ms=lap_time)], rows, corners_at(1_100, 1_230))
        five, hairpin = (by_corner(result)[key]["AAA"] for key in ((1, None), (2, None)))

        self.assertEqual((five["braking"], five["brake_start_m"], five["entry_speed_kph"]), ("seen", 1010.0, 212.0))
        self.assertEqual((five["apex_distance_m"], five["apex_speed_kph"]), (1100.0, 72.0))
        self.assertEqual(
            (hairpin["braking"], hairpin["brake_start_m"], hairpin["entry_speed_kph"]), ("seen", 1160.0, 140.0)
        )
        self.assertEqual((hairpin["apex_distance_m"], hairpin["apex_speed_kph"]), (1230.0, 43.0))
        self.assertEqual(hairpin["braking_distance_m"], 70.0)
        # How long the brake was on for turn 5 ends where it came off for turn 5.
        on_at = {row["distance_m"]: row["relative_time_ms"] for row in rows}
        self.assertAlmostEqual(five["brake_duration_ms"], on_at[1_090.0] - on_at[1_010.0], places=0)

    def test_a_braking_taken_up_again_while_the_car_still_slows_is_one_braking_and_both_corners_have_it(self):
        """Alonso's lap 15 of the 2026 Australian GP: 250 km/h to 222 for turn 9, off for 67 m, on again for turn 10.

        The car never gathers speed between the two, so they are one braking.
        Its slowest point is turn 10's, which alone was given it, and turn 9
        was published as not braked for, beside a speed 40 km/h down.
        """

        def profile(place):
            if place < 1_200:
                return 250.0, False
            if place <= 1_260:
                return between(place, 1_200, 1_260, 250, 222), True
            if place < 1_330:
                return between(place, 1_260, 1_330, 222, 211), False
            if place <= 1_340:
                return between(place, 1_330, 1_340, 211, 206), True
            if place <= 1_390:
                return between(place, 1_340, 1_390, 206, 193), False
            return min(250.0, between(place, 1_390, 1_600, 193, 250)), False

        rows, lap_time = driven(profile)

        result = calculate_corner_analysis("s", [lap("AAA", lap_time_ms=lap_time)], rows, corners_at(1_260, 1_380))
        nine, ten = (by_corner(result)[key]["AAA"] for key in ((1, None), (2, None)))

        self.assertEqual((nine["braking"], nine["brake_start_m"], nine["entry_speed_kph"]), ("seen", 1200.0, 250.0))
        # Turn 9's slowest point is the slowest in turn 9's stretch, which ends half-way to turn 10.
        self.assertEqual(nine["apex_distance_m"], 1310.0)
        self.assertAlmostEqual(nine["apex_speed_kph"], 214.1, places=1)
        self.assertEqual((ten["braking"], ten["brake_start_m"]), ("seen", 1200.0))
        self.assertEqual((ten["apex_distance_m"], ten["apex_speed_kph"]), (1390.0, 193.0))
        # For turn 9 the brake was last on where it came off before turn 9's
        # slowest point, and for turn 10 where it came off the second time.
        on_at = {row["distance_m"]: row["relative_time_ms"] for row in rows}
        self.assertAlmostEqual(nine["brake_duration_ms"], on_at[1_260.0] - on_at[1_200.0], places=0)
        self.assertAlmostEqual(ten["brake_duration_ms"], on_at[1_340.0] - on_at[1_200.0], places=0)

    def test_both_parts_of_a_chicane_have_the_braking_for_it(self):
        """The first chicane at Monza: off the brake before the half-way point, slowest at the second part.

        The braking was the second part's alone, and the first part, braked
        for from 320 km/h, was published as not braked for. Looking only at
        where the brake is on would turn that round.
        """

        def profile(place):
            if place < 750:
                return 320.0, False
            if place <= 910:
                return between(place, 750, 910, 320, 80), True
            if place <= 950:
                return between(place, 910, 950, 80, 70), False
            return min(320.0, between(place, 950, 1_300, 70, 250)), False

        rows, lap_time = driven(profile)

        result = calculate_corner_analysis("s", [lap("AAA", lap_time_ms=lap_time)], rows, corners_at(900, 950))
        first, second = (by_corner(result)[key]["AAA"] for key in ((1, None), (2, None)))

        self.assertEqual((first["braking"], first["brake_start_m"], first["entry_speed_kph"]), ("seen", 750.0, 320.0))
        self.assertEqual((first["apex_distance_m"], first["apex_speed_kph"]), (920.0, 77.5))
        self.assertEqual((second["braking"], second["brake_start_m"]), ("seen", 750.0))
        self.assertEqual((second["apex_distance_m"], second["apex_speed_kph"]), (950.0, 70.0))
        self.assertIn("is given for both, from the one brake point", result["caveats"][1])

    def test_the_end_of_a_braking_for_the_corner_before_is_not_a_braking_for_this_one(self):
        def profile(place):
            if place < 850:
                return 300.0, False
            if place <= 1_000:
                return between(place, 850, 1_000, 300, 60), True
            # Still on the brake, lightly, for 40 m out of the hairpin, past half-way to the kink.
            return min(300.0, between(place, 1_000, 1_400, 60, 300)), place <= 1_040

        rows, lap_time = driven(profile)

        result = calculate_corner_analysis("s", [lap("AAA", lap_time_ms=lap_time)], rows, corners_at(1_000, 1_060))
        hairpin, kink = (by_corner(result)[key]["AAA"] for key in ((1, None), (2, None)))

        self.assertEqual((hairpin["braking"], hairpin["brake_start_m"], hairpin["apex_speed_kph"]), ("seen", 850.0, 60.0))
        self.assertEqual((kink["braking"], kink["brake_start_m"]), ("none", None))
        self.assertEqual(kink["apex_distance_m"], 1030.0)

    def test_a_brake_that_reads_on_while_the_car_gathers_speed_is_not_where_the_braking_began(self):
        """Stroll's lap 36 of the 2026 Australian GP: the brake reads on for 636 m, most of it at full throttle.

        From 150 km/h up to 253 and down to 189 for turn 6. Counted from
        where the reading went on the car lost nothing, so turn 6 was
        published as not braked for.
        """

        def profile(place):
            if place < 400:
                return 150.0, False
            if place <= 800:
                return between(place, 400, 800, 150, 250), True
            if place <= 980:
                return between(place, 800, 980, 250, 195), True
            if place <= 1_000:
                return between(place, 980, 1_000, 195, 190), False
            return min(300.0, between(place, 1_000, 1_300, 190, 300)), False

        rows, lap_time = driven(profile)

        result = calculate_corner_analysis("s", [lap("AAA", lap_time_ms=lap_time)], rows, corners_at(1_000))
        row = by_corner(result)[(1, None)]["AAA"]

        self.assertEqual((row["braking"], row["apex_distance_m"], row["apex_speed_kph"]), ("began_unread", 1000.0, 190.0))
        for field in ("brake_start_m", "braking_distance_m", "entry_speed_kph", "speed_loss_kph", "brake_duration_ms"):
            self.assertIsNone(row[field], field)
        self.assertIn(
            "or has the brake on there while the car gathers speed, for: AAA. The driver braked",
            " ".join(result["caveats"]),
        )

    def test_a_brake_that_reads_on_from_one_corner_to_the_next_is_a_braking_for_each_and_begins_at_the_first(self):
        """Sainz's lap 24 of the 2026 Belgian GP: the brake reads on for 769 m, through Pouhon and on to turn 12.

        The car slows for the first corner from where the reading goes on,
        which is the first corner's brake point. It then gathers speed with
        the reading still on, to more than it came in at before it is out of
        the first corner's stretch, and where the driver began to brake for
        the second corner is not known.
        """

        def profile(place):
            if place < 600:
                return 270.0, False
            if place <= 700:
                return between(place, 600, 700, 270, 245), True
            if place <= 1_100:
                return between(place, 700, 1_100, 245, 290), True
            if place <= 1_290:
                return between(place, 1_100, 1_290, 290, 155), True
            if place <= 1_300:
                return between(place, 1_290, 1_300, 155, 150), False
            return min(300.0, between(place, 1_300, 1_600, 150, 300)), False

        rows, lap_time = driven(profile)

        result = calculate_corner_analysis("s", [lap("AAA", lap_time_ms=lap_time)], rows, corners_at(700, 1_300))
        first, second = (by_corner(result)[key]["AAA"] for key in ((1, None), (2, None)))

        self.assertEqual((first["braking"], first["brake_start_m"], first["entry_speed_kph"]), ("seen", 600.0, 270.0))
        self.assertEqual((first["apex_distance_m"], first["apex_speed_kph"]), (700.0, 245.0))
        self.assertEqual((second["braking"], second["brake_start_m"]), ("began_unread", None))
        self.assertEqual((second["apex_distance_m"], second["apex_speed_kph"]), (1300.0, 150.0))

    def test_a_row_of_an_inferred_corner_is_placed_where_its_own_driver_was_slowest(self):
        # Two laps of one track that disagree about distance by 5%: the corner
        # they share is put between them, and each row where its own lap has it.
        laps = [lap("AAA"), lap("BBB")]
        rows = lap_rows("AAA") + lap_rows("BBB", stretch=1.05)

        result = calculate_corner_analysis("s", laps, rows)

        self.assertEqual(result["corner_source"], "inferred")
        first = result["corners"][0]
        placed = {row["driver_code"]: (row["corner_distance_m"], row["apex_distance_m"]) for row in first["drivers"]}
        self.assertEqual(placed, {"AAA": (1000.0, 1000.0), "BBB": (1050.0, 1050.0)})
        self.assertEqual(first["distance_m"], 1025.0)

    def test_a_corner_not_braked_for_has_its_slowest_point_before_the_braking_for_the_next(self):
        def profile(place):
            if place < 1_020:
                return 300.0, False
            if place <= 1_150:
                return between(place, 1_020, 1_150, 300, 80), True
            return min(300.0, between(place, 1_150, 1_500, 80, 300)), False

        rows, lap_time = driven(profile)

        result = calculate_corner_analysis("s", [lap("AAA", lap_time_ms=lap_time)], rows, corners_at(1_000, 1_150))
        kink, hairpin = (by_corner(result)[key]["AAA"] for key in ((1, None), (2, None)))

        # The brake goes on 20 m past the kink, in the kink's stretch of the
        # lap. That is the braking for the hairpin, and the kink's slowest
        # point is not 70 m into it.
        self.assertEqual((kink["braking"], kink["brake_start_m"]), ("none", None))
        self.assertEqual((kink["apex_distance_m"], kink["apex_speed_kph"]), (1000.0, 300.0))
        self.assertEqual(
            (hairpin["braking"], hairpin["brake_start_m"], hairpin["entry_speed_kph"], hairpin["apex_speed_kph"]),
            ("seen", 1020.0, 300.0, 80.0),
        )

    def test_a_brake_that_is_on_where_its_reading_comes_back_is_a_driver_who_braked_however_little_is_seen(self):
        rows = lap_rows("AAA")
        # No reading for all but the last sample of the braking for turn 1,
        # which comes back on: too little of it to count, and yet braking.
        for row in rows:
            if 800 <= row["distance_m"] < 1_000:
                row["brake"] = None

        result = calculate_corner_analysis("s", [lap("AAA")], rows, CORNERS)
        first = by_corner(result)[(1, None)]["AAA"]

        self.assertEqual((first["braking"], first["brake_start_m"], first["apex_speed_kph"]), ("began_unread", None, 90.0))
        self.assertNotIn("Whether the driver braked", " ".join(result["caveats"]))

    def test_a_braking_that_takes_less_than_the_least_off_the_car_is_not_counted_and_the_result_says_what_the_least_is(self):
        def profile(place):
            if 960 <= place <= 990:
                return between(place, 960, 990, 300, 294), True
            if 990 < place <= 1_000:
                return 294.0, False
            return 300.0, False

        rows, lap_time = driven(profile)

        result = calculate_corner_analysis("s", [lap("AAA", lap_time_ms=lap_time)], rows, corners_at(1_000))
        row = by_corner(result)[(1, None)]["AAA"]

        self.assertEqual((row["braking"], row["brake_start_m"], row["apex_speed_kph"]), ("none", None, 294.0))
        self.assertIn("A braking that takes less than 8 km/h off the car is not counted", result["caveats"][2])

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
        # Each row says where its own lap has the corner, which is not where
        # the lap the corners were placed on has it: the table put the second
        # beside the first lap's brake point, 150 m from where it belongs.
        self.assertEqual(
            [corners[key]["BBB"]["corner_distance_m"] for key in ((1, None), (2, "A"), (3, None))],
            [1150.0, 2300.0, 3450.0],
        )
        self.assertEqual([corner["distance_m"] for corner in result["corners"]], [1000.0, 2000.0, 3000.0])
        self.assertEqual(corners[(1, None)]["AAA"]["corner_distance_m"], 1000.0)
        self.assertEqual(len(result["caveats"]), 4)

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
