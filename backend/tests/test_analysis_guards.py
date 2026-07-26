from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.analysis.advanced import calculate_pace_prediction
from app.analysis.strategy import calculate_strategy
from app.analysis.telemetry_compare import compare_telemetry
from pipeline.analysis.precompute import calculate_strategy as calculate_pipeline_strategy


class TelemetryDownsamplingTests(unittest.TestCase):
    def test_comparison_is_capped_at_300_samples(self):
        """Floor division only capped exact multiples of 300."""
        telemetry = _telemetry("AAA", 5, 500) + _telemetry("BBB", 5, 500)

        result = compare_telemetry(
            "2026-01-q", telemetry, [], [], "AAA", 5, "BBB", 5
        )

        self.assertLessEqual(len(result.distance_m), 300)
        self.assertEqual(len(result.distance_m), 250)
        self.assertEqual(len(result.speed_b), len(result.distance_m))

    def test_short_laps_are_not_downsampled(self):
        telemetry = _telemetry("AAA", 5, 300) + _telemetry("BBB", 5, 300)

        result = compare_telemetry(
            "2026-01-q", telemetry, [], [], "AAA", 5, "BBB", 5
        )

        self.assertEqual(len(result.distance_m), 300)


class PitStopLapNumberTests(unittest.TestCase):
    def test_a_null_lap_number_does_not_raise(self):
        stops = [
            {"driver_code": "AAA", "lap_number": None, "duration_ms": 22_000},
            {"driver_code": "AAA", "lap_number": 20, "duration_ms": 22_000},
            {"driver_code": "BBB", "lap_number": None, "duration_ms": 22_000},
        ]
        laps = [
            _lap("AAA", 19, 92_000),
            _lap("AAA", 21, 90_000),
        ]

        for calculate in (calculate_strategy, calculate_pipeline_strategy):
            with self.subTest(implementation=calculate.__module__):
                result = calculate("2026-01-r", [], stops, laps, [])
                rows = {row["driver_code"]: row for row in result["undercut_overcut"]}

                # The usable stop is used; the driver with no usable stop is
                # dropped rather than crashing min()/int() on None.
                self.assertEqual(set(rows), {"AAA"})
                self.assertEqual(rows["AAA"]["stop_lap"], 20)
                self.assertEqual(rows["AAA"]["first_clean_lap_gain_ms"], 2_000)


class PaceGapTests(unittest.TestCase):
    def test_a_zero_best_pace_reports_a_zero_gap_not_a_missing_one(self):
        laps = [
            _lap(driver, number, 0, stint=1)
            for driver in ("AAA", "BBB")
            for number in range(2, 8)
        ]
        drivers = [
            {"code": "AAA", "team": {"name": "Alpha"}},
            {"code": "BBB", "team": {"name": "Beta"}},
        ]

        result = calculate_pace_prediction(
            "2026-01-fp1", {"session": "Practice 1"}, laps, drivers
        )

        self.assertTrue(result["available"])
        self.assertEqual([row["gap_to_best_ms"] for row in result["drivers"]], [0.0, 0.0])
        self.assertEqual([row["gap_to_best_ms"] for row in result["teams"]], [0.0, 0.0])


def _lap(
    driver: str, lap_number: int, lap_time_ms: int, *, stint: int = 1
) -> dict[str, object]:
    return {
        "driver_code": driver,
        "lap_number": lap_number,
        "lap_time_ms": lap_time_ms,
        "compound": "MEDIUM",
        "tyre_age": lap_number,
        "stint": stint,
        "is_pit_in_lap": False,
        "is_pit_out_lap": False,
        "is_deleted": False,
        "is_accurate": True,
        "track_status": "1",
    }


def _telemetry(driver: str, lap_number: int, sample_count: int) -> list[dict[str, object]]:
    return [
        {
            "driver_code": driver,
            "lap_number": lap_number,
            "distance_m": index * 10,
            "relative_time_ms": index * 100,
            "speed_kph": 200,
            "throttle_pct": 100,
            "brake": False,
            "rpm": 10_000,
            "gear": 7,
            "drs": 0,
            "x": index,
            "y": index,
        }
        for index in range(sample_count)
    ]


if __name__ == "__main__":
    unittest.main()
