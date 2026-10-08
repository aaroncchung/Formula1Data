"""Method tests for the analyses AR-08 found producing misleading numbers.

Each class pins one method down on a small synthetic input: what the figure
is, which laps may feed it, and when it must be withheld rather than guessed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.analysis.advanced import (
    MAX_BOUNDARY_SAMPLE_DISTANCE_M,
    MIN_DEGRADATION_LAPS,
    calculate_fuel_adjusted_tyre_degradation,
    calculate_track_dominance,
)
from app.analysis.common import has_yellow, is_neutralized
from app.analysis.strategy import PIT_LOSS_MIN_STOPS, calculate_strategy
from app.analysis.teammate_comparison import MIN_MATCHED_LAPS, calculate_teammate_comparison


class TrackStatusTests(unittest.TestCase):
    def test_fastf1_concatenated_codes_are_read_per_code(self):
        self.assertFalse(is_neutralized("1"))
        self.assertFalse(is_neutralized("12"))
        self.assertTrue(is_neutralized("14"))
        self.assertTrue(is_neutralized("671"))
        self.assertTrue(has_yellow("12"))
        self.assertFalse(has_yellow("1"))
        # A lap with no status recorded is not known to be anything but green.
        self.assertFalse(is_neutralized(None))
        self.assertFalse(has_yellow(""))


class PitLossTests(unittest.TestCase):
    def test_pit_loss_is_in_lap_plus_out_lap_minus_twice_the_baseline(self):
        laps, stops = [], []
        # Three stops costing 20 s, 21 s and 30 s against a 90 s baseline.
        for driver, loss in (("AAA", 20_000), ("BBB", 21_000), ("CCC", 30_000)):
            laps += _stint_with_stop(driver, stop_lap=8, baseline=90_000, loss=loss)
            stops.append(_stop(driver, 8, 22_000))

        result = calculate_strategy("2026-01-r", [], stops, laps, [])
        by_driver = {row["driver_code"]: row for row in result["pit_loss"]["stops"]}

        self.assertEqual(by_driver["AAA"]["pit_loss_ms"], 20_000)
        self.assertEqual(by_driver["AAA"]["baseline_lap_ms"], 90_000)
        self.assertEqual(by_driver["AAA"]["baseline_lap_count"], 10)
        # The median, so the one slow stop does not set the figure (mean 23,667).
        self.assertEqual(result["pit_loss_estimate_ms"], 21_000)
        self.assertEqual(result["pit_loss"]["estimate_ms"], 21_000)
        self.assertEqual(result["pit_loss"]["qualifying_stop_count"], 3)
        self.assertIn("median across 3 of 3 entries to the pit lane", result["caveats"][0])

    def test_pit_lane_time_is_reported_separately_and_never_becomes_pit_loss(self):
        laps, stops = [], []
        # One car sits in the lane for 400 s, as under a red flag. A mean of
        # lane times is how a committed race came to report 410,846 ms.
        for driver, lane in (("AAA", 22_000), ("BBB", 22_500), ("CCC", 400_000)):
            laps += _stint_with_stop(driver, stop_lap=8, baseline=90_000, loss=21_000)
            stops.append(_stop(driver, 8, lane, stationary_ms=2_500))
        stops.append(_stop("DDD", 3, None, stationary_ms=2_500))

        result = calculate_strategy("2026-01-r", [], stops, laps, [])

        self.assertEqual(result["pit_loss_estimate_ms"], 21_000)
        self.assertEqual(
            result["pit_lane_time"],
            {
                "median_ms": 22_500,
                "fastest_ms": 22_000,
                "slowest_ms": 400_000,
                "timed_stop_count": 3,
                "stop_count": 4,
            },
        )
        self.assertIn("not pit loss", " ".join(result["caveats"]))

    def test_only_stops_made_under_green_count(self):
        laps, stops = [], []
        for driver in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            laps += _stint_with_stop(driver, stop_lap=8, baseline=90_000, loss=21_000)
            stops.append(_stop(driver, 8, 22_000))
        # A safety car on the out-lap, a VSC on the in-lap and a yellow flag on
        # the in-lap each make the stop cheaper or dearer than a green one.
        _lap_of(laps, "CCC", 9)["track_status"] = "14"
        _lap_of(laps, "DDD", 8)["track_status"] = "16"
        _lap_of(laps, "EEE", 8)["track_status"] = "12"

        result = calculate_strategy("2026-01-r", [], stops, laps, [])
        reasons = {
            row["driver_code"]: row["excluded_reason"] for row in result["pit_loss"]["stops"]
        }

        self.assertEqual(
            reasons,
            {"AAA": None, "BBB": None, "CCC": "not_green", "DDD": "not_green", "EEE": "not_green"},
        )
        # Two stops qualify, one short of the minimum: no estimate, and why.
        self.assertEqual(PIT_LOSS_MIN_STOPS, 3)
        self.assertIsNone(result["pit_loss_estimate_ms"])
        self.assertIsNone(result["pit_loss"]["estimate_ms"])
        self.assertEqual(result["pit_loss"]["qualifying_stop_count"], 2)
        self.assertEqual(result["pit_loss"]["excluded_stop_counts"], {"not_green": 3})
        self.assertIn(
            "No pit-loss estimate: 2 of 5 entries to the pit lane qualified", result["caveats"][0]
        )
        self.assertIn("3 for a yellow flag, safety car, VSC or red flag", result["caveats"][0])

    def test_stops_with_no_usable_lap_times_are_left_out(self):
        retired = [_lap("AAA", number, 90_000) for number in range(2, 8)]
        retired.append(_lap("AAA", 8, 95_000, pit_in=True))
        first_lap = [_lap("BBB", 1, 99_000, pit_in=True), _lap("BBB", 2, 110_000, pit_out=True)]
        first_lap += [_lap("BBB", number, 90_000) for number in range(3, 9)]
        back_to_back = _stint_with_stop("CCC", stop_lap=8, baseline=90_000, loss=21_000)
        _lap_of(back_to_back, "CCC", 9)["is_pit_in_lap"] = True
        stops = [
            _stop("AAA", 8, None),
            _stop("BBB", 1, 30_000),
            _stop("CCC", 8, 22_000),
            _stop("CCC", 9, 22_000),
            _stop("DDD", None, 22_000),
        ]

        result = calculate_strategy("2026-01-r", [], stops, retired + first_lap + back_to_back, [])
        reasons = [
            (row["driver_code"], row["lap_number"], row["excluded_reason"])
            for row in result["pit_loss"]["stops"]
        ]

        self.assertEqual(
            reasons,
            [
                ("AAA", 8, "missing_lap_time"),
                ("BBB", 1, "first_lap"),
                ("CCC", 8, "back_to_back_stops"),
                ("CCC", 9, "back_to_back_stops"),
                ("DDD", None, "no_lap_number"),
            ],
        )
        self.assertIsNone(result["pit_loss_estimate_ms"])

    def test_baseline_is_the_clean_green_laps_next_to_the_stop(self):
        laps = _stint_with_stop("AAA", stop_lap=10, baseline=90_000, loss=21_000, last_lap=22)
        # Laps beyond five either side are on other fuel and tyres: unused.
        for number in (2, 3, 4, 17, 18, 19, 20, 21, 22):
            _lap_of(laps, "AAA", number)["lap_time_ms"] = 99_000
        # Inside the window, a safety-car lap, a yellow-flag lap and a deleted
        # lap are not the driver's pace either.
        _lap_of(laps, "AAA", 12).update(lap_time_ms=140_000, track_status="4")
        _lap_of(laps, "AAA", 13).update(lap_time_ms=93_000, track_status="12")
        _lap_of(laps, "AAA", 7).update(lap_time_ms=95_000, is_deleted=True)

        result = calculate_strategy("2026-01-r", [], [_stop("AAA", 10, 22_000)], laps, [])
        stop = result["pit_loss"]["stops"][0]

        self.assertEqual(stop["baseline_lap_ms"], 90_000)
        self.assertEqual(stop["baseline_lap_count"], 7)
        self.assertEqual(stop["pit_loss_ms"], 21_000)

    def test_a_stop_with_too_little_clean_running_around_it_is_left_out(self):
        laps = _stint_with_stop("AAA", stop_lap=8, baseline=90_000, loss=21_000)
        for lap in laps:
            if lap["lap_number"] not in (8, 9, 10, 11):
                lap["track_status"] = "4"

        result = calculate_strategy("2026-01-r", [], [_stop("AAA", 8, 22_000)], laps, [])
        stop = result["pit_loss"]["stops"][0]

        self.assertEqual(stop["excluded_reason"], "too_few_baseline_laps")
        self.assertEqual(stop["baseline_lap_count"], 2)
        self.assertIsNone(stop["pit_loss_ms"])

    def test_pit_lane_time_is_of_the_stops_f1_reports_and_no_other_entry(self):
        """The 2026 Dutch GP's fastest was a drive-through penalty, at 12.1 s.

        And the median of the 2025 Canadian GP was 18.3 s over 82 entries, 49
        of them the field following the safety car down the pit lane.
        """
        laps, stops = [], []
        for driver, lane in (("AAA", 22_000), ("BBB", 23_000), ("CCC", 24_000)):
            laps += _stint_with_stop(driver, stop_lap=8, baseline=90_000, loss=21_000)
            stops.append(_stop(driver, 8, lane, stationary_ms=2_500))
        # A drive-through, quicker than any stop, and two cars held in the
        # lane with no stop reported: none is a figure of a pit stop.
        stops.append(_stop("AAA", 12, 12_100))
        stops.append(_stop("BBB", 12, 60_000))
        stops.append(_stop("CCC", 12, 18_000))

        result = calculate_strategy("2026-01-r", [], stops, laps, [])

        self.assertEqual(
            result["pit_lane_time"],
            {
                "median_ms": 23_000,
                "fastest_ms": 22_000,
                "slowest_ms": 24_000,
                "timed_stop_count": 3,
                "stop_count": 6,
            },
        )
        self.assertIn("over the stops F1's pit-stop feed reports", result["caveats"][1])

    def test_a_session_f1_reports_no_stop_of_has_no_pit_lane_figures(self):
        laps = _stint_with_stop("AAA", stop_lap=8, baseline=90_000, loss=21_000)

        result = calculate_strategy("2026-01-r", [], [_stop("AAA", 8, 22_000)], laps, [])

        self.assertEqual(
            result["pit_lane_time"],
            {
                "median_ms": None,
                "fastest_ms": None,
                "slowest_ms": None,
                "timed_stop_count": 0,
                "stop_count": 1,
            },
        )

    def test_a_car_that_went_through_without_stopping_is_not_priced_as_a_stop(self):
        """A drive-through penalty was in the pit-loss median of the 2026 Dutch GP, priced at 13.0 s."""
        laps, stops = [], []
        for driver, loss in (("AAA", 20_000), ("BBB", 21_000), ("CCC", 22_000)):
            laps += _stint_with_stop(driver, stop_lap=8, baseline=90_000, loss=loss, last_lap=22)
            stops.append(_stop(driver, 8, 22_000, stationary_ms=2_500, tyres_changed=True))
        # Each then drives through the pit lane on lap 15, under green, at a
        # cost of 14 s, and goes out on the tyres it came in on.
        for driver in ("AAA", "BBB", "CCC"):
            _lap_of(laps, driver, 15).update(lap_time_ms=93_500, is_pit_in_lap=True, is_accurate=False)
            _lap_of(laps, driver, 16).update(lap_time_ms=100_500, is_pit_out_lap=True, is_accurate=False)
            stops.append(_stop(driver, 15, 12_100, tyres_changed=False))

        result = calculate_strategy("2026-01-r", [], stops, laps, [])
        reasons = {
            (row["driver_code"], row["lap_number"]): row["excluded_reason"]
            for row in result["pit_loss"]["stops"]
        }

        self.assertEqual(
            reasons,
            {
                ("AAA", 8): None,
                ("BBB", 8): None,
                ("CCC", 8): None,
                ("AAA", 15): "no_stop",
                ("BBB", 15): "no_stop",
                ("CCC", 15): "no_stop",
            },
        )
        # With the three drive-throughs priced as stops it was the median of
        # 14, 14, 14, 20, 21 and 22 s: 17 s, which is the cost of neither.
        self.assertEqual(result["pit_loss_estimate_ms"], 21_000)
        self.assertEqual(result["pit_loss"]["excluded_stop_counts"], {"no_stop": 3})
        self.assertIn(
            "Left out: 3 for the car going through without stopping.", result["caveats"][0]
        )

    def test_a_stop_f1_times_is_a_stop_whatever_the_tyre_data_says(self):
        """The 2025 Miami GP: the tyre data has no change at twelve stops, and shows each eight laps late."""
        laps, stops = [], []
        for driver, loss in (("AAA", 20_000), ("BBB", 21_000), ("CCC", 22_000)):
            laps += _stint_with_stop(driver, stop_lap=8, baseline=90_000, loss=loss)
            stops.append(_stop(driver, 8, 22_000, stationary_ms=2_500, tyres_changed=False))

        result = calculate_strategy("2026-01-r", [], stops, laps, [])

        self.assertEqual(result["pit_loss"]["qualifying_stop_count"], 3)
        self.assertEqual(result["pit_loss"]["excluded_stop_counts"], {})
        self.assertEqual([row["stop_lap"] for row in result["undercut_overcut"]], [8, 8, 8])

    def test_a_wait_through_a_red_flag_is_a_wait_whatever_was_done_to_the_car(self):
        """The 2026 Dutch GP was red-flagged on lap 2 with the field in the pit lane, and tyres were changed.

        Norris's first stop was taken to be that wait, and his stop on lap 21
        was never compared across. And in the 2025 Sao Paulo sprint three
        cars that waited 22 minutes on the tyres they had were counted as
        going through without stopping.
        """
        for changed in (True, False):
            with self.subTest(tyres_changed=changed):
                laps = _stint_with_stop("AAA", stop_lap=8, baseline=90_000, loss=21_000)
                wait = {**_stop("AAA", 3, 1_560_000, tyres_changed=changed), "under_red_flag": True}
                stops = [wait, _stop("AAA", 8, 22_000, stationary_ms=2_500)]

                result = calculate_strategy("2026-01-r", [], stops, laps, [])
                reasons = {row["lap_number"]: row["excluded_reason"] for row in result["pit_loss"]["stops"]}

                self.assertEqual(reasons, {3: "red_flag_wait", 8: None})
                self.assertEqual(result["pit_loss"]["excluded_stop_counts"], {"red_flag_wait": 1})
                self.assertIn(
                    "Left out: 1 for the car waiting in the pit lane through a red flag.",
                    result["caveats"][0],
                )
                self.assertEqual([row["stop_lap"] for row in result["undercut_overcut"]], [8])

    def test_an_entry_the_tyre_data_says_nothing_of_is_taken_for_a_stop(self):
        laps, stops = [], []
        for driver, loss in (("AAA", 20_000), ("BBB", 21_000), ("CCC", 22_000)):
            laps += _stint_with_stop(driver, stop_lap=8, baseline=90_000, loss=loss)
            # F1 sent no tyre data for the car, and that is not word that it
            # kept its tyres.
            stops.append(_stop(driver, 8, 22_000, tyres_changed=None))

        result = calculate_strategy("2026-01-r", [], stops, laps, [])

        self.assertEqual(result["pit_loss"]["qualifying_stop_count"], 3)
        self.assertEqual([row["stop_lap"] for row in result["undercut_overcut"]], [8, 8, 8])

    def test_no_stops_is_an_explicit_empty_result(self):
        result = calculate_strategy("2026-01-q", [], [], [], [])

        self.assertIsNone(result["pit_loss_estimate_ms"])
        self.assertEqual(result["pit_loss"]["stops"], [])
        self.assertIsNone(result["pit_lane_time"]["median_ms"])
        self.assertEqual(result["undercut_overcut"], [])
        self.assertIn("no pit stops were recorded", result["caveats"][0])


class PaceChangeAcrossStopTests(unittest.TestCase):
    def test_neutralised_inaccurate_and_pit_laps_are_never_compared(self):
        laps = [
            _lap("AAA", 8, 92_500),
            _lap("AAA", 9, 92_000),
            _lap("AAA", 10, 95_000, pit_in=True),
            _lap("AAA", 11, 108_000, pit_out=True),
            # The old method took this safety-car lap as "the lap after the
            # stop" and reported 92,000 - 140,000 = -48,000 ms.
            _lap("AAA", 12, 140_000, track_status="4"),
            _lap("AAA", 13, 96_000, accurate=False),
            _lap("AAA", 14, 90_500),
        ]

        row = _pace_change(laps, [_stop("AAA", 10, 22_000)])

        self.assertEqual(row["first_clean_lap_gain_ms"], 1_500)
        self.assertEqual((row["before_lap_number"], row["before_lap_ms"]), (9, 92_000))
        self.assertEqual((row["after_lap_number"], row["after_lap_ms"]), (14, 90_500))
        self.assertIn("Lap 9 against lap 14", row["caveat"])

    def test_a_yellow_flag_lap_is_passed_over_for_the_one_before(self):
        laps = [
            _lap("AAA", 8, 92_000),
            _lap("AAA", 9, 93_200, track_status="12"),
            _lap("AAA", 10, 95_000, pit_in=True),
            _lap("AAA", 11, 108_000, pit_out=True),
            _lap("AAA", 12, 90_500),
        ]

        row = _pace_change(laps, [_stop("AAA", 10, 22_000)])

        self.assertEqual(row["before_lap_number"], 8)
        self.assertEqual(row["first_clean_lap_gain_ms"], 1_500)

    def test_nothing_is_reported_when_the_laps_near_the_stop_are_not_clean(self):
        laps = [_lap("AAA", number, 92_000) for number in range(2, 10)]
        laps += [_lap("AAA", 10, 95_000, pit_in=True), _lap("AAA", 11, 108_000, pit_out=True)]
        # A long safety car: the first green lap comes six laps after the stop.
        laps += [_lap("AAA", number, 140_000, track_status="4") for number in range(12, 17)]
        laps += [_lap("AAA", number, 90_000) for number in range(17, 25)]

        row = _pace_change(laps, [_stop("AAA", 10, 22_000)])

        self.assertIsNone(row["first_clean_lap_gain_ms"])
        self.assertEqual(row["before_lap_number"], 9)
        self.assertIsNone(row["after_lap_number"])
        self.assertEqual(
            row["caveat"],
            "No clean green-flag lap in the 3 laps after the out-lap, so no pace change is reported.",
        )

    def test_a_stop_with_no_clean_lap_before_it_reports_nothing(self):
        laps = [_lap("AAA", 1, 99_000), _lap("AAA", 2, 95_000, pit_in=True)]
        laps += [_lap("AAA", 3, 108_000, pit_out=True), _lap("AAA", 4, 90_000)]

        row = _pace_change(laps, [_stop("AAA", 2, 22_000)])

        self.assertIsNone(row["first_clean_lap_gain_ms"])
        self.assertIn("in the 3 laps before the in-lap", row["caveat"])

    def test_a_lap_after_the_next_stop_is_not_the_lap_after_this_one(self):
        laps = [
            _lap("AAA", 9, 92_000),
            _lap("AAA", 10, 95_000, pit_in=True),
            _lap("AAA", 11, 108_000, pit_out=True, pit_in=True),
            _lap("AAA", 12, 108_000, pit_out=True),
            _lap("AAA", 13, 90_000),
        ]

        row = _pace_change(laps, [_stop("AAA", 10, 22_000), _stop("AAA", 11, 22_000)])

        self.assertEqual(row["stop_lap"], 10)
        self.assertIsNone(row["first_clean_lap_gain_ms"])
        # And it says so. Ocon in the 2025 Qatar GP stopped on laps 8 and 9
        # and ran a clean lap 11: "no clean green-flag lap within 3 laps
        # after the stop" was said of a lap that is there.
        self.assertEqual(
            row["caveat"],
            "No clean green-flag lap after the out-lap and before the next stop, on lap 11, so no "
            "pace change is reported.",
        )

    def test_a_next_stop_beyond_the_window_is_not_why_no_lap_was_found(self):
        laps = [_lap("AAA", number, 92_000) for number in range(7, 32)]
        _lap_of(laps, "AAA", 10)["is_pit_in_lap"] = True
        _lap_of(laps, "AAA", 11)["is_pit_out_lap"] = True
        for number in (12, 13, 14):
            _lap_of(laps, "AAA", number)["track_status"] = "4"

        row = _pace_change(laps, [_stop("AAA", 10, 22_000), _stop("AAA", 30, 22_000)])

        self.assertIsNone(row["first_clean_lap_gain_ms"])
        self.assertEqual(
            row["caveat"],
            "No clean green-flag lap in the 3 laps after the out-lap, so no pace change is reported.",
        )

    def test_the_lap_after_may_be_the_third_after_the_out_lap(self):
        laps = [
            _lap("AAA", 9, 92_000),
            _lap("AAA", 10, 95_000, pit_in=True),
            _lap("AAA", 11, 108_000, pit_out=True),
            _lap("AAA", 12, 140_000, track_status="4"),
            _lap("AAA", 13, 140_000, track_status="4"),
            _lap("AAA", 14, 90_500),
            _lap("AAA", 15, 90_000),
        ]

        row = _pace_change(laps, [_stop("AAA", 10, 22_000)])

        # Lap 14 is four lap numbers after the stop and three after the out-lap.
        self.assertEqual((row["before_lap_number"], row["after_lap_number"]), (9, 14))
        # And the fourth after the out-lap is not looked at.
        for lap in laps:
            if lap["lap_number"] == 14:
                lap["track_status"] = "4"
        row = _pace_change(laps, [_stop("AAA", 10, 22_000)])
        self.assertIsNone(row["after_lap_number"])
        self.assertIn("in the 3 laps after the out-lap", row["caveat"])

    def test_the_first_stop_is_the_first_the_car_changed_tyres_at(self):
        """In the 2025 Australian GP the field followed the safety car down the pit lane on laps 2 to 4.

        Each driver's first stop was taken to be lap 2, which had no clean lap
        before it, and the stop they did make was never compared across.
        """
        laps = [
            _lap("AAA", 2, 120_000, pit_in=True, track_status="4"),
            _lap("AAA", 3, 120_000, pit_out=True, pit_in=True, track_status="4"),
            _lap("AAA", 4, 120_000, pit_out=True, track_status="4"),
            _lap("AAA", 5, 92_500),
            _lap("AAA", 6, 92_000),
            _lap("AAA", 7, 95_000, pit_in=True),
            _lap("AAA", 8, 108_000, pit_out=True),
            _lap("AAA", 9, 90_500),
        ]
        stops = [
            _stop("AAA", 2, 14_000, tyres_changed=False),
            _stop("AAA", 3, 14_500, tyres_changed=False),
            _stop("AAA", 7, 22_000, stationary_ms=2_400, tyres_changed=True),
        ]

        row = _pace_change(laps, stops)

        self.assertEqual(row["stop_lap"], 7)
        self.assertEqual(row["first_clean_lap_gain_ms"], 1_500)
        self.assertEqual((row["before_lap_number"], row["after_lap_number"]), (6, 9))

    def test_a_driver_who_only_drove_through_has_no_stop_to_compare_across(self):
        laps = [_lap("AAA", number, 92_000) for number in range(2, 12)]
        _lap_of(laps, "AAA", 6)["is_pit_in_lap"] = True
        _lap_of(laps, "AAA", 7)["is_pit_out_lap"] = True

        result = calculate_strategy(
            "2026-01-r", [], [_stop("AAA", 6, 12_100, tyres_changed=False)], laps, []
        )

        self.assertEqual(result["undercut_overcut"], [])

    def test_the_method_is_stated_in_the_caveats(self):
        result = calculate_strategy("2026-01-r", [], [], [], [])
        text = " ".join(result["caveats"])

        # The window after the stop is counted from the out-lap: "within 3
        # laps of the stop" was said of Alonso in the 2026 Australian GP, who
        # stopped on lap 11 and was compared across laps 10 and 15.
        self.assertIn(
            "last clean green-flag lap in the 3 laps before the in-lap minus the first one in the "
            "3 laps after the out-lap, and before their next stop",
            text,
        )
        # And not "on the new tyres": Sainz in the 2026 Dutch sprint stood
        # for 8.4 s on lap 16 and went out on the set he came in on.
        self.assertIn("positive is quicker after the stop", text)
        self.assertNotIn("new tyres", text)
        self.assertIn("a stop on the same set", text)
        self.assertIn("no value is given when either lap is missing", text)


class TrackDominanceTests(unittest.TestCase):
    def test_a_driver_with_only_a_standing_start_lap_is_left_out(self):
        laps = [
            _lap("AAA", 2, 10_000),
            _lap("CCC", 2, 10_400),
            # Completed lap 1, pitted on lap 2 and retired.
            _lap("BBB", 1, 12_000, accurate=False),
            _lap("BBB", 2, 13_000, pit_in=True),
        ]
        telemetry = (
            _telemetry("AAA", 2, 10_000)
            + _telemetry("CCC", 2, 10_400)
            # From the grid the lap is longer and its fast and slow parts fall
            # in other minisectors, which is how such a lap used to win them.
            + _telemetry("BBB", 1, 12_000, length_m=1_050, shares=(0.05, 0.05, 0.3, 0.3, 0.3))
            + _telemetry("BBB", 2, 13_000)
        )

        result = calculate_track_dominance("2026-01-r", laps, telemetry, minisector_count=5)

        self.assertEqual(
            [row["driver_code"] for row in result["representative_laps"]], ["AAA", "CCC"]
        )
        self.assertEqual(result["excluded_drivers"], ["BBB"])
        self.assertIn("BBB", result["caveats"][-1])
        for sector in result["minisectors"]:
            self.assertNotIn("BBB", sector["driver_times_ms"])
            self.assertEqual(sector["winner_driver_code"], "AAA")

    def test_the_representative_lap_is_the_fastest_clean_lap_with_complete_telemetry(self):
        laps = [
            _lap("AAA", 2, 8_000, deleted=True),
            _lap("AAA", 3, 8_200, track_status="4"),
            _lap("AAA", 4, 8_400, accurate=False),
            _lap("AAA", 5, 8_600, pit_in=True),
            _lap("AAA", 6, 8_800, pit_out=True),
            _lap("AAA", 7, 9_000),  # telemetry stops 60% of the way round
            _lap("AAA", 8, 9_200),  # telemetry clock covers half the lap time
            _lap("AAA", 9, 9_400),  # complete
            _lap("AAA", 10, 9_600),  # complete, slower
            _lap("AAA", 11, 9_100),  # no telemetry at all
            _lap("BBB", 2, 9_900),
        ]
        telemetry = []
        for number, lap_time in ((2, 8_000), (3, 8_200), (4, 8_400), (5, 8_600), (6, 8_800)):
            telemetry += _telemetry("AAA", number, lap_time)
        telemetry += _telemetry("AAA", 7, 9_000, length_m=600)
        telemetry += _telemetry("AAA", 8, 4_600)
        telemetry += _telemetry("AAA", 9, 9_400)
        telemetry += _telemetry("AAA", 10, 9_600)
        telemetry += _telemetry("BBB", 2, 9_900)

        result = calculate_track_dominance("2026-01-q", laps, telemetry, minisector_count=5)

        self.assertEqual(
            result["representative_laps"],
            [
                {"driver_code": "AAA", "lap_number": 9, "lap_time_ms": 9_400},
                {"driver_code": "BBB", "lap_number": 2, "lap_time_ms": 9_900},
            ],
        )
        self.assertEqual(result["excluded_drivers"], [])

    def test_a_lap_cannot_win_a_minisector_its_telemetry_does_not_cover(self):
        laps = [_lap("AAA", 2, 10_000), _lap("BBB", 2, 11_000)]
        # AAA is the quicker car everywhere, but has no samples from 350 m to
        # 650 m. Boundaries at 400 m and 600 m fall in that hole, 50 m from
        # the nearest sample.
        hole = [
            row
            for row in _telemetry("AAA", 2, 10_000)
            if not 350 < row["distance_m"] < 650
        ]
        self.assertGreater(50, MAX_BOUNDARY_SAMPLE_DISTANCE_M)

        result = calculate_track_dominance(
            "2026-01-q", laps, hole + _telemetry("BBB", 2, 11_000), minisector_count=5
        )
        winners = [sector["winner_driver_code"] for sector in result["minisectors"]]
        covered = [sorted(sector["driver_times_ms"]) for sector in result["minisectors"]]

        self.assertEqual(winners, ["AAA", "BBB", "BBB", "BBB", "AAA"])
        self.assertEqual(
            covered, [["AAA", "BBB"], ["BBB"], ["BBB"], ["BBB"], ["AAA", "BBB"]]
        )
        # With nobody to beat there is no margin to report.
        self.assertIsNone(result["minisectors"][2]["gap_to_next_ms"])

    def test_minisectors_cover_the_whole_lap_whatever_each_lap_measures(self):
        laps = [_lap("AAA", 2, 10_000), _lap("BBB", 2, 10_200), _lap("CCC", 2, 10_400)]
        # The same lap, measured as 990 m, 1,000 m and 1,015 m by three cars.
        # Cutting all three at 990 m dropped the end of the longer two.
        telemetry = (
            _telemetry("AAA", 2, 10_000, length_m=990)
            + _telemetry("BBB", 2, 10_200, length_m=1_000)
            + _telemetry("CCC", 2, 10_400, length_m=1_015)
        )

        result = calculate_track_dominance("2026-01-q", laps, telemetry, minisector_count=5)

        self.assertEqual(result["minisectors"][-1]["end_distance_m"], 1_000)
        for driver, lap_time in (("AAA", 10_000), ("BBB", 10_200), ("CCC", 10_400)):
            total = sum(sector["driver_times_ms"][driver] for sector in result["minisectors"])
            self.assertAlmostEqual(total, lap_time, delta=0.5)
        # Three cars at a steady speed: each fifth of the lap takes a fifth of
        # the lap time, so the quickest lap wins every one by the same margin.
        for sector in result["minisectors"]:
            self.assertEqual(sector["winner_driver_code"], "AAA")
            self.assertAlmostEqual(sector["gap_to_next_ms"], 40, delta=0.2)

    def test_the_winner_is_the_car_quickest_through_that_part_of_the_lap(self):
        laps = [_lap("AAA", 2, 10_000), _lap("BBB", 2, 10_000)]
        telemetry = _telemetry("AAA", 2, 10_000, shares=(0.1, 0.3, 0.2, 0.2, 0.2)) + _telemetry(
            "BBB", 2, 10_000, shares=(0.3, 0.1, 0.2, 0.2, 0.2)
        )

        result = calculate_track_dominance("2026-01-q", laps, telemetry, minisector_count=5)

        self.assertEqual(
            [sector["winner_driver_code"] for sector in result["minisectors"]][:2], ["AAA", "BBB"]
        )
        self.assertEqual(result["minisectors"][0]["segment_time_ms"], 1_000)
        self.assertEqual(result["minisectors"][0]["gap_to_next_ms"], 2_000)

    def test_no_qualifying_lap_at_all_is_an_explicit_empty_result(self):
        laps = [_lap("AAA", 1, 12_000), _lap("AAA", 2, 13_000, pit_in=True)]
        telemetry = _telemetry("AAA", 1, 12_000) + _telemetry("AAA", 2, 13_000)

        result = calculate_track_dominance("2026-01-r", laps, telemetry)

        self.assertEqual(result["representative_laps"], [])
        self.assertEqual(result["excluded_drivers"], ["AAA"])
        self.assertEqual(result["minisectors"], [])
        self.assertIn("No usable telemetry laps", result["caveats"][-1])


class FuelCorrectionSessionTypeTests(unittest.TestCase):
    def test_only_races_and_sprints_are_fuel_corrected(self):
        cases = [
            ("2026-08-r", {"session": "Race"}, 55.0),
            ("2026-08-s", {"session": "Sprint"}, 35.0),
            # "sprint" is in the name, but these are qualifying sessions.
            ("2026-08-sq", {"session": "Sprint Qualifying"}, 0.0),
            ("2026-08-sq", {"session": "Sprint Shootout"}, 0.0),
            ("2026-08-q", {"session": "Qualifying"}, 0.0),
            ("2026-08-fp2", {"session": "Practice 2"}, 0.0),
            # The session code is accepted as the type too.
            ("2026-08-s", {"type": "S"}, 35.0),
            ("2026-08-sq", {"type": "SQ"}, 0.0),
            # No summary: the session id's last part is the code, matched whole.
            ("2026-08-r", {}, 55.0),
            ("2026-08-s", {}, 35.0),
            ("2026-08-sq", {}, 0.0),
            # A stated type wins over the id.
            ("2026-08-s", {"session": "Sprint Qualifying"}, 0.0),
        ]
        laps = _stint("AAA", range(1, 13), lambda age: 90_000 + 40 * age)

        for session_id, summary, expected in cases:
            with self.subTest(session_id=session_id, summary=summary):
                result = calculate_fuel_adjusted_tyre_degradation(session_id, summary, laps)
                row = result["rows"][0]
                self.assertEqual(row["fuel_correction_ms_per_lap"], expected)
                self.assertEqual(row["degradation_ms_per_lap"], 40.0 + expected)


class TyreDegradationFitTests(unittest.TestCase):
    def test_a_handful_of_laps_is_not_a_degradation_rate(self):
        # Seven laps on a perfect line: three used to be enough.
        laps = _stint("AAA", range(1, MIN_DEGRADATION_LAPS), lambda age: 90_000 + 60 * age)

        row = _degradation_row(laps)

        self.assertEqual(row["sample_count"], MIN_DEGRADATION_LAPS - 1)
        self.assertEqual(row["fit_status"], "too_few_laps")
        self.assertIsNone(row["degradation_ms_per_lap"])
        self.assertIsNone(row["raw_slope_ms_per_lap"])
        self.assertIn("at least 8 are required", row["caveats"][0])

    def test_a_stint_with_no_tyre_ages_is_not_said_to_have_no_clean_laps(self):
        """Bearman's third stint of the 2026 Barcelona GP: 19 clean laps on a set that went on used.

        F1 gives no age for such a set, so there is nothing to fit. The row
        said "0 clean laps, and at least 8 are required" beside a stint
        length of 19.
        """
        laps = _stint("AAA", range(1, 20), lambda age: 90_000 + 40 * age)
        for lap in laps:
            lap["tyre_age"] = None
        # Some of a stint's laps can have an age and the rest none.
        some = _stint("BBB", range(1, 20), lambda age: 90_000 + 40 * age)
        for lap in some[5:]:
            lap["tyre_age"] = None

        result = calculate_fuel_adjusted_tyre_degradation("2026-01-r", {"type": "R"}, laps + some)
        rows = {row["driver_code"]: row for row in result["rows"]}

        self.assertEqual((rows["AAA"]["sample_count"], rows["AAA"]["stint_length"]), (0, 19))
        self.assertEqual(
            rows["AAA"]["caveats"],
            [
                "No rate reported: F1 gives a tyre age for 0 of the stint's 19 clean laps, and at "
                f"least {MIN_DEGRADATION_LAPS} with one are required. It gives none for a set that "
                "went on used."
            ],
        )
        self.assertEqual((rows["BBB"]["sample_count"], rows["BBB"]["stint_length"]), (5, 19))
        self.assertIn("a tyre age for 5 of the stint's 19 clean laps", rows["BBB"]["caveats"][0])
        self.assertEqual({row["fit_status"] for row in rows.values()}, {"too_few_laps"})

    def test_a_stint_short_of_clean_laps_is_said_to_be_that(self):
        laps = _stint("AAA", range(1, 6), lambda age: 90_000 + 40 * age)

        (row,) = calculate_fuel_adjusted_tyre_degradation("2026-01-r", {"type": "R"}, laps)["rows"]

        self.assertEqual(
            row["caveats"],
            [f"No rate reported: 5 clean laps, and at least {MIN_DEGRADATION_LAPS} are required."],
        )

    def test_laps_lost_to_the_outlier_filter_do_not_count_towards_the_minimum(self):
        laps = _stint(
            "AAA", range(1, 10), lambda age: 90_000 + 60 * age + (4_000 if age in (3, 6) else 0)
        )

        row = _degradation_row(laps)

        self.assertEqual(row["sample_count"], 9)
        self.assertEqual(row["excluded_outlier_count"], 2)
        self.assertEqual(row["fit_status"], "too_few_laps")
        self.assertIsNone(row["degradation_ms_per_lap"])

    def test_every_fit_carries_its_quality_figures(self):
        laps = _stint("AAA", range(1, 13), lambda age: 90_000 + 60 * age + _wobble(age, 100))

        row = _degradation_row(laps)

        self.assertEqual(row["fit_status"], "ok")
        self.assertAlmostEqual(row["raw_slope_ms_per_lap"], 60, delta=10)
        self.assertEqual(
            row["degradation_ms_per_lap"], round(row["raw_slope_ms_per_lap"] + 55.0, 2)
        )
        # Laps sit 100 ms either side of the line, so the spread is about that
        # and twelve laps fix the slope to within about 9 ms/lap.
        self.assertAlmostEqual(row["residual_spread_ms"], 105, delta=10)
        self.assertAlmostEqual(row["slope_standard_error_ms_per_lap"], 9, delta=1.5)
        self.assertGreater(row["r_squared"], 0.7)

    def test_a_stint_too_scattered_to_fix_the_slope_reports_no_rate(self):
        laps = _stint("AAA", range(1, 11), lambda age: 90_000 + 40 * age + _wobble(age, 600))

        row = _degradation_row(laps)

        self.assertEqual(row["fit_status"], "poor_fit")
        self.assertIsNone(row["degradation_ms_per_lap"])
        self.assertIsNone(row["raw_slope_ms_per_lap"])
        # The quality figures stay, because they are the reason.
        self.assertGreater(row["slope_standard_error_ms_per_lap"], 60)
        self.assertGreater(row["residual_spread_ms"], 500)
        self.assertEqual(row["excluded_outlier_count"], 0)
        self.assertIn("scatter too much to fix the slope", row["caveats"][0])

    def test_a_clean_stint_with_no_degradation_is_reported_whatever_its_r_squared(self):
        laps = _stint("AAA", range(1, 21), lambda age: 90_000 + _wobble(age, 30))

        row = _degradation_row(laps)

        # R² is near zero because there is no trend to explain, not because
        # the fit is loose: the slope is known to about 1 ms/lap.
        self.assertLess(row["r_squared"], 0.1)
        self.assertLess(row["slope_standard_error_ms_per_lap"], 2)
        self.assertEqual(row["fit_status"], "ok")
        self.assertAlmostEqual(row["degradation_ms_per_lap"], 55.0, delta=2)

    def test_a_short_steep_stint_is_reported_when_its_slope_is_beyond_doubt(self):
        laps = _stint("AAA", range(1, 9), lambda age: 90_000 + 200 * age + _wobble(age, 180))

        row = _degradation_row(laps)

        # About 30 ms/lap of uncertainty: over the absolute limit, but an
        # eighth of a 200 ms/lap slope.
        self.assertGreater(row["slope_standard_error_ms_per_lap"], 20)
        self.assertLess(row["slope_standard_error_ms_per_lap"], 50)
        self.assertEqual(row["fit_status"], "ok")
        self.assertAlmostEqual(row["raw_slope_ms_per_lap"], 200, delta=40)

    def test_lap_times_falling_through_a_stint_are_flagged_as_not_the_tyres(self):
        laps = _stint("AAA", range(1, 13), lambda age: 90_000 - 100 * age)

        row = _degradation_row(laps)

        self.assertEqual(row["degradation_ms_per_lap"], -45.0)
        self.assertIn("reason other than the tyres", " ".join(row["caveats"]))

    def test_the_thresholds_are_published_with_the_result(self):
        result = calculate_fuel_adjusted_tyre_degradation("2026-01-r", {"session": "Race"}, [])

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["model"]["minimum_laps"], 8)
        self.assertEqual(result["model"]["max_slope_standard_error_ms_per_lap"], 20.0)
        self.assertEqual(result["model"]["max_slope_relative_standard_error"], 0.25)


class TeammateComparisonTests(unittest.TestCase):
    DRIVERS = [
        {"code": "AAA", "team": {"name": "Alpha"}},
        {"code": "BBB", "team": {"name": "Alpha"}},
    ]

    def test_only_laps_both_drivers_ran_are_compared(self):
        # Lap times fall 100 ms a lap as fuel burns off. BBB is 200 ms quicker
        # on every lap but retires after lap 11; AAA runs to lap 21.
        laps = [_lap("AAA", number, 100_000 - 100 * number) for number in range(2, 22)]
        laps += [_lap("BBB", number, 99_800 - 100 * number) for number in range(2, 12)]

        row = calculate_teammate_comparison("2026-01-r", laps, self.DRIVERS)["rows"][0]

        # Means over each driver's own laps put BBB 300 ms *behind*: 99,150
        # over the heavy-fuel laps against AAA's 98,850 over the whole race.
        self.assertEqual([driver["driver_code"] for driver in row["drivers"]], ["BBB", "AAA"])
        self.assertEqual(row["gap_ms"], 200)
        self.assertEqual(row["matched_lap_count"], 10)
        self.assertEqual(row["trimmed_lap_count"], 2)
        self.assertEqual([driver["lap_count"] for driver in row["drivers"]], [8, 8])
        self.assertEqual([driver["clean_lap_count"] for driver in row["drivers"]], [10, 20])

    def test_one_compromised_lap_does_not_move_the_gap(self):
        laps = [_lap("AAA", number, 90_000) for number in range(2, 22)]
        laps += [_lap("BBB", number, 90_100) for number in range(2, 22)]
        # BBB loses twenty seconds behind a slow car on one green-flag lap; a
        # mean of the differences would call the gap 1,100 ms.
        _lap_of(laps, "BBB", 12)["lap_time_ms"] = 110_100

        row = calculate_teammate_comparison("2026-01-r", laps, self.DRIVERS)["rows"][0]

        self.assertEqual(row["gap_ms"], 100)
        self.assertEqual(row["matched_lap_count"], 20)
        self.assertEqual(row["trimmed_lap_count"], 4)

    def test_the_gap_is_the_difference_between_the_two_averages_shown(self):
        laps = [_lap("AAA", number, 90_000 + 37 * number) for number in range(2, 32)]
        laps += [
            _lap("BBB", number, 90_250 + 31 * number + _wobble(number, 90))
            for number in range(2, 32)
        ]

        row = calculate_teammate_comparison("2026-01-r", laps, self.DRIVERS)["rows"][0]
        quicker, slower = row["drivers"]

        self.assertGreater(row["gap_ms"], 0)
        self.assertAlmostEqual(
            slower["average_lap_ms"] - quicker["average_lap_ms"], row["gap_ms"], delta=0.11
        )
        self.assertEqual(quicker["lap_count"], row["matched_lap_count"] - row["trimmed_lap_count"])
        self.assertGreater(row["gap_spread_ms"], 0)

    def test_a_lap_counts_only_when_it_is_clean_for_both(self):
        laps = [_lap("AAA", number, 90_000) for number in range(1, 13)]
        laps += [_lap("BBB", number, 90_300) for number in range(1, 13)]
        _lap_of(laps, "AAA", 5).update(is_pit_in_lap=True)
        _lap_of(laps, "BBB", 6).update(is_pit_out_lap=True)
        _lap_of(laps, "AAA", 7).update(track_status="4")
        _lap_of(laps, "BBB", 8).update(is_deleted=True)
        _lap_of(laps, "BBB", 9).update(is_accurate=False)

        row = calculate_teammate_comparison("2026-01-r", laps, self.DRIVERS)["rows"][0]

        # Laps 2 to 12, less the five above; lap 1 is never clean.
        self.assertEqual(row["matched_lap_count"], 6)
        self.assertEqual(row["gap_ms"], 300)

    def test_too_few_matched_laps_reports_no_gap(self):
        laps = [_lap("BBB", number, 90_000) for number in range(2, 30)]
        laps += [_lap("AAA", number, 91_000) for number in range(2, MIN_MATCHED_LAPS + 1)]

        row = calculate_teammate_comparison("2026-01-r", laps, self.DRIVERS)["rows"][0]

        self.assertEqual(row["matched_lap_count"], MIN_MATCHED_LAPS - 1)
        self.assertIsNone(row["gap_ms"])
        self.assertIsNone(row["gap_spread_ms"])
        # No gap means no quicker driver to list first.
        self.assertEqual([driver["driver_code"] for driver in row["drivers"]], ["AAA", "BBB"])
        self.assertEqual([driver["average_lap_ms"] for driver in row["drivers"]], [None, None])
        self.assertIn("Only 4 matched clean laps", row["caveat"])

    def test_drivers_without_a_team_are_not_each_others_team_mates(self):
        laps = [
            _lap(driver, number, 90_000)
            for driver in ("AAA", "BBB", "XXX", "YYY")
            for number in range(2, 12)
        ]
        drivers = self.DRIVERS + [{"code": "XXX"}, {"code": "YYY", "team": {}}]

        result = calculate_teammate_comparison("2026-01-r", laps, drivers)

        self.assertEqual([row["team"] for row in result["rows"]], ["Alpha"])
        self.assertEqual(result["rows"][0]["gap_ms"], 0)

    def test_the_method_and_an_empty_result_are_stated(self):
        result = calculate_teammate_comparison("2026-01-r", [], self.DRIVERS)
        text = " ".join(result["caveats"])

        self.assertEqual(result["rows"], [])
        self.assertIn("matched laps only", text)
        self.assertIn("trimmed mean of the lap-by-lap differences", text)
        # Of five matched laps one is dropped each way, which is a fifth and
        # not the tenth the sentence gave alone (Hulkenberg and Bortoleto in
        # the 2025 Qatar GP).
        self.assertIn("the 10% of matched laps with the largest difference each way, and never fewer than one lap each way, are dropped", text)
        self.assertIn("No team had two drivers with clean laps", text)


def _lap(
    driver: str,
    lap_number: int,
    lap_time_ms: int,
    *,
    tyre_age: int | None = None,
    stint: int = 1,
    track_status: str = "1",
    pit_in: bool = False,
    pit_out: bool = False,
    deleted: bool = False,
    accurate: bool = True,
) -> dict[str, object]:
    return {
        "driver_code": driver,
        "lap_number": lap_number,
        "lap_time_ms": lap_time_ms,
        "compound": "MEDIUM",
        "tyre_age": lap_number if tyre_age is None else tyre_age,
        "stint": stint,
        "is_pit_in_lap": pit_in,
        "is_pit_out_lap": pit_out,
        "is_deleted": deleted,
        "is_accurate": accurate,
        "track_status": track_status,
    }


def _lap_of(laps: list[dict[str, object]], driver: str, lap_number: int) -> dict[str, object]:
    return next(
        lap for lap in laps if lap["driver_code"] == driver and lap["lap_number"] == lap_number
    )


def _stop(
    driver: str,
    lap_number: int | None,
    duration_ms: int | None,
    stationary_ms: int | None = None,
    tyres_changed: bool | None = True,
) -> dict[str, object]:
    """An entry to the pit lane. ``stationary_ms`` is there for one F1 reports a stop for."""
    return {
        "driver_code": driver,
        "lap_number": lap_number,
        "duration_ms": duration_ms,
        "stationary_ms": stationary_ms,
        "tyres_changed": tyres_changed,
    }


def _stint_with_stop(
    driver: str, *, stop_lap: int, baseline: int, loss: int, last_lap: int | None = None
) -> list[dict[str, object]]:
    """Green laps at ``baseline`` with one stop that costs ``loss`` in total."""
    last_lap = stop_lap + 6 if last_lap is None else last_lap
    in_lap_loss = loss // 4
    laps = []
    for number in range(2, last_lap + 1):
        if number == stop_lap:
            laps.append(_lap(driver, number, baseline + in_lap_loss, pit_in=True, accurate=False))
        elif number == stop_lap + 1:
            laps.append(
                _lap(driver, number, baseline + loss - in_lap_loss, pit_out=True, accurate=False)
            )
        else:
            laps.append(_lap(driver, number, baseline))
    return laps


def _pace_change(laps: list[dict[str, object]], stops: list[dict[str, object]]) -> dict:
    result = calculate_strategy("2026-01-r", [], stops, laps, [])
    return result["undercut_overcut"][0]


def _stint(driver: str, tyre_ages, lap_time) -> list[dict[str, object]]:
    return [_lap(driver, age + 1, lap_time(age), tyre_age=age) for age in tyre_ages]


def _wobble(index: int, size: int) -> int:
    """Deterministic scatter: laps sit alternately above and below the trend."""
    return size if index % 2 else -size


def _degradation_row(laps: list[dict[str, object]]) -> dict:
    result = calculate_fuel_adjusted_tyre_degradation("2026-01-r", {"session": "Race"}, laps)
    return result["rows"][0]


def _telemetry(
    driver: str,
    lap_number: int,
    duration_ms: int,
    *,
    length_m: float = 1_000,
    shares: tuple[float, ...] = (0.2, 0.2, 0.2, 0.2, 0.2),
) -> list[dict[str, object]]:
    """One lap of samples every hundredth of ``length_m``.

    ``shares`` is the share of ``duration_ms`` spent in each equal part of the
    lap, so (0.1, 0.3, ...) is a car quick through the first fifth and slow
    through the second.
    """
    rows = []
    samples = 100
    for index in range(samples + 1):
        position = index / samples * len(shares)
        part = min(int(position), len(shares) - 1)
        elapsed = duration_ms * (sum(shares[:part]) + shares[part] * (position - part))
        rows.append(
            {
                "driver_code": driver,
                "lap_number": lap_number,
                "distance_m": length_m * index / samples,
                "relative_time_ms": elapsed,
                "speed_kph": 200,
                "x": index,
                "y": lap_number,
            }
        )
    return rows


if __name__ == "__main__":
    unittest.main()
