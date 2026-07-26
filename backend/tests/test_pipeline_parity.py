from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

import app.analysis.advanced as backend_advanced
import app.analysis.common as backend_common
import app.analysis.ideal_laps as backend_ideal_laps
import app.analysis.position_replay as backend_position_replay
import app.analysis.race_pace as backend_race_pace
import app.analysis.strategy as backend_strategy
import app.analysis.teammate_comparison as backend_teammate_comparison
import pipeline.analysis.precompute as pipeline_precompute
from app.analysis.advanced import (
    calculate_car_performance,
    calculate_corner_analysis,
    calculate_fuel_adjusted_tyre_degradation,
    calculate_pace_prediction,
    calculate_track_dominance,
)
from app.analysis.common import clean_laps as clean_backend_laps
from app.ingestion.normalizer import _bounded_frame, _pit_stops, _telemetry, pd
from pipeline.analysis.precompute import (
    build_position_replay,
    clean_laps as clean_pipeline_laps,
    precompute_session_analysis,
)


# The ten functions that F-12 found duplicated between ``backend/app/analysis``
# and ``pipeline/analysis/precompute.py``. Each entry is
# (name, backend module, pipeline module).
DEDUPLICATED_ANALYSIS_FUNCTIONS = [
    ("clean_laps", backend_common, pipeline_precompute),
    ("grouped", backend_common, pipeline_precompute),
    ("trimmed_mean", backend_common, pipeline_precompute),
    ("most_common", backend_common, pipeline_precompute),
    ("lap_statistics", backend_common, pipeline_precompute),
    ("calculate_race_pace", backend_race_pace, pipeline_precompute),
    ("calculate_strategy", backend_strategy, pipeline_precompute),
    ("calculate_ideal_laps", backend_ideal_laps, pipeline_precompute),
    ("calculate_teammate_comparison", backend_teammate_comparison, pipeline_precompute),
    ("build_position_replay", backend_position_replay, pipeline_precompute),
]


class SharedAnalysisSourceTests(unittest.TestCase):
    """The structural guard that replaces value-by-value parity checking.

    The analysis package is deliberately loaded twice -- as ``app.analysis.*`` by
    the FastAPI service and as ``backend.app.analysis.*`` by the pipeline -- so
    the two sides are *not* the same objects and ``is`` comparisons fail. What
    can be asserted, and what actually rules out drift, is that both names
    resolve to the same file on disk. If someone reintroduces a private copy in
    ``precompute.py``, this fails.
    """

    def test_every_deduplicated_function_resolves_to_one_source_file(self):
        for name, backend_module, pipeline_module in DEDUPLICATED_ANALYSIS_FUNCTIONS:
            with self.subTest(function=name):
                backend_function = getattr(backend_module, name)
                pipeline_function = getattr(pipeline_module, name)
                self.assertEqual(
                    Path(inspect.getsourcefile(backend_function)).resolve(),
                    Path(inspect.getsourcefile(pipeline_function)).resolve(),
                )
                self.assertEqual(
                    inspect.getsource(backend_function),
                    inspect.getsource(pipeline_function),
                )

    def test_advanced_module_uses_the_shared_lap_filter(self):
        # advanced.py carried a third copy of the filter as ``_clean_laps``.
        self.assertIs(backend_advanced.clean_laps, backend_common.clean_laps)
        self.assertFalse(hasattr(backend_advanced, "_clean_laps"))

    def test_shared_analysis_modules_do_not_import_outside_their_package(self):
        # ``app.models`` only resolves when ``backend/`` is on sys.path, so a
        # shared module importing it would break ``python -m pipeline`` from the
        # repository root.
        shared = [
            backend_common,
            backend_advanced,
            backend_race_pace,
            backend_strategy,
            backend_ideal_laps,
            backend_teammate_comparison,
            backend_position_replay,
        ]
        for module in shared:
            with self.subTest(module=module.__name__):
                source = Path(inspect.getsourcefile(module)).read_text(encoding="utf-8")
                self.assertNotIn("from app.", source)
                self.assertNotIn("import app.", source)


class AdvancedAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.laps = [
            _lap("AAA", 2, 89_000),
            _lap("BBB", 2, 90_000),
        ]
        self.telemetry = _telemetry_rows("AAA", 2, time_factor=10.0) + _telemetry_rows(
            "BBB", 2, time_factor=11.0
        )

    def test_minisector_winner_is_computed_from_interpolated_elapsed_time(self):
        result = calculate_track_dominance(
            "2026-01-q", self.laps, self.telemetry, minisector_count=5
        )

        self.assertEqual(result["minisector_count"], 5)
        self.assertEqual(
            {sector["winner_driver_code"] for sector in result["minisectors"]}, {"AAA"}
        )
        self.assertTrue(all(sector["gap_to_next_ms"] > 0 for sector in result["minisectors"]))

    def test_missing_telemetry_returns_explicit_empty_analysis(self):
        dominance = calculate_track_dominance("2026-01-q", self.laps, [])
        corners = calculate_corner_analysis("2026-01-q", self.laps, [])

        self.assertEqual(dominance["minisectors"], [])
        self.assertIn("No usable telemetry", " ".join(dominance["caveats"]))
        self.assertEqual(corners["corners"], [])
        self.assertTrue(corners["caveats"])

    def test_corner_analysis_reports_braking_and_apex_metrics(self):
        result = calculate_corner_analysis("2026-01-q", self.laps, self.telemetry)

        self.assertTrue(result["corners"])
        first_corner = result["corners"][0]
        self.assertEqual(
            {row["driver_code"] for row in first_corner["drivers"]}, {"AAA", "BBB"}
        )
        self.assertTrue(all(row["speed_loss_kph"] > 8 for row in first_corner["drivers"]))

    def test_car_percentages_use_only_samples_with_valid_channels(self):
        telemetry = _telemetry_rows("AAA", 2, time_factor=10.0)
        for row in telemetry:
            row["throttle_pct"] = None
            row["brake"] = None
        telemetry[0]["throttle_pct"] = 100
        telemetry[1]["throttle_pct"] = 50
        telemetry[0]["brake"] = True
        telemetry[1]["brake"] = False

        result = calculate_car_performance(
            "2026-01-q", [self.laps[0]], telemetry, [_driver("AAA", "Alpha")]
        )

        self.assertEqual(result["drivers"][0]["full_throttle_pct"], 50.0)
        self.assertEqual(result["drivers"][0]["braking_pct"], 50.0)

    def test_fuel_adjusted_degradation_filters_large_outlier(self):
        laps = []
        for tyre_age in range(1, 7):
            lap_time = 90_000 + 45 * tyre_age
            if tyre_age == 4:
                lap_time += 5_000
            laps.append(_lap("AAA", tyre_age + 1, lap_time, tyre_age=tyre_age, stint=1))

        result = calculate_fuel_adjusted_tyre_degradation(
            "2026-01-r", {"session": "Race"}, laps
        )
        row = result["rows"][0]

        self.assertEqual(row["raw_slope_ms_per_lap"], 45.0)
        self.assertEqual(row["degradation_ms_per_lap"], 100.0)
        self.assertEqual(row["excluded_outlier_count"], 1)
        self.assertEqual(row["fuel_correction_ms_per_lap"], 55.0)

    def test_pace_prediction_is_practice_only_and_requires_long_run(self):
        laps = [
            _lap("AAA", number, 90_000 + number * 50, tyre_age=number, stint=1)
            for number in range(2, 8)
        ]
        drivers = [_driver("AAA", "Alpha")]

        practice = calculate_pace_prediction(
            "2026-01-fp1", {"session": "Practice 1"}, laps, drivers
        )
        race = calculate_pace_prediction("2026-01-r", {"session": "Race"}, laps, drivers)

        self.assertTrue(practice["available"])
        self.assertEqual(practice["drivers"][0]["sample_count"], 6)
        self.assertFalse(race["available"])
        self.assertEqual(race["drivers"], [])

    def test_precompute_exposes_stable_advanced_artifact_names(self):
        result = precompute_session_analysis(
            "2026-01-q",
            {
                "summary": {"session": "Qualifying"},
                "laps": self.laps,
                "drivers": [_driver("AAA", "Alpha"), _driver("BBB", "Beta")],
                "telemetry": self.telemetry,
            },
        )

        self.assertTrue(
            {"track-dominance", "corner-analysis", "car-performance", "pace-prediction"}
            <= result.keys()
        )
        for name in ["track-dominance", "corner-analysis", "car-performance", "pace-prediction"]:
            self.assertEqual(result[name]["session_id"], "2026-01-q")
            self.assertIn("caveats", result[name])

    def test_fastf1_numeric_neutralization_codes_are_excluded(self):
        # Both names now resolve to one implementation (see
        # SharedAnalysisSourceTests), so this no longer compares two copies. It
        # is kept because the behaviour it pins down -- FastF1 concatenating
        # status codes, e.g. "14" for clear+SC -- is the regression that
        # motivated it, and that behaviour still needs a test.
        clear = _lap("AAA", 2, 90_000)
        safety_car = {**_lap("AAA", 3, 110_000), "track_status": "14"}

        self.assertEqual(clean_backend_laps([clear, safety_car]), [clear])
        self.assertEqual(clean_pipeline_laps([clear, safety_car]), [clear])


class IngestionParityTests(unittest.TestCase):
    @unittest.skipIf(pd is None, "pandas is required for normalization tests")
    def test_telemetry_keeps_every_usable_lap_and_bounds_each_lap(self):
        session = _TelemetrySession(
            [
                _TelemetryLap("AAA", 1, sample_count=450),
                _TelemetryLap("AAA", 2, sample_count=20),
                _TelemetryLap("BBB", 1, sample_count=12),
                _TelemetryLap("BBB", 2, sample_count=12, deleted=True),
            ]
        )

        rows = _telemetry(session, "2026-01-r")
        keys = {(row["driver_code"], row["lap_number"]) for row in rows}

        self.assertEqual(keys, {("AAA", 1), ("AAA", 2), ("BBB", 1)})
        self.assertEqual(sum(row["driver_code"] == "AAA" and row["lap_number"] == 1 for row in rows), 300)
        first_lap = [row for row in rows if row["driver_code"] == "AAA" and row["lap_number"] == 1]
        self.assertEqual(first_lap[0]["distance_m"], 0)
        self.assertEqual(first_lap[-1]["distance_m"], 4_490)
        self.assertIsNotNone(first_lap[0]["session_time_ms"])

    @unittest.skipIf(pd is None, "pandas is required for normalization tests")
    def test_telemetry_falls_back_to_car_data_when_position_data_is_missing(self):
        rows = _telemetry(_TelemetrySession([_CarOnlyTelemetryLap("AAA", 6, sample_count=20)]), "2026-01-r")

        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[-1]["distance_m"], 190)
        self.assertIsNone(rows[0]["x"])

    @unittest.skipIf(pd is None, "pandas is required for normalization tests")
    def test_pit_duration_uses_only_adjacent_pit_out_lap(self):
        laps = pd.DataFrame(
            [
                {"Driver": "AAA", "LapNumber": 10, "PitInTime": pd.Timedelta(seconds=600), "PitOutTime": None},
                {"Driver": "AAA", "LapNumber": 11, "PitInTime": None, "PitOutTime": pd.Timedelta(seconds=625)},
                {"Driver": "BBB", "LapNumber": 10, "PitInTime": pd.Timedelta(seconds=600), "PitOutTime": None},
                {"Driver": "BBB", "LapNumber": 11, "PitInTime": None, "PitOutTime": None},
                {"Driver": "BBB", "LapNumber": 12, "PitInTime": None, "PitOutTime": pd.Timedelta(seconds=700)},
            ]
        )

        stops = _pit_stops(laps, "2026-01-r")
        by_driver = {stop["driver_code"]: stop for stop in stops}

        self.assertEqual(by_driver["AAA"]["duration_ms"], 25_000)
        self.assertIsNone(by_driver["BBB"]["duration_ms"])

    @unittest.skipIf(pd is None, "pandas is required for normalization tests")
    def test_bounded_frame_handles_single_sample_limit(self):
        frame = pd.DataFrame([{"value": 1}, {"value": 2}])
        bounded = _bounded_frame(frame, 1)
        self.assertEqual(len(bounded), 1)
        self.assertEqual(bounded.iloc[0]["value"], 1)


class PositionReplayTests(unittest.TestCase):
    def test_replay_prefers_global_session_time_and_deduplicates_driver_per_frame(self):
        telemetry = [
            _position("AAA", 1, 10_100, 100, x=1),
            _position("AAA", 1, 12_400, 2_400, x=2),
            _position("BBB", 2, 12_600, 100, x=3),
        ]

        frames = build_position_replay("2026-01-r", telemetry)

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["timestamp_ms"], 10_000)
        self.assertIsNone(frames[0]["lap_number"])
        self.assertEqual([row["driver_code"] for row in frames[0]["positions"]], ["AAA", "BBB"])
        self.assertEqual(frames[0]["positions"][0]["x"], 2)

    def test_replay_lap_relative_fallback_separates_laps_and_carries_caveat(self):
        telemetry = [
            _position("AAA", 1, None, 1_000, x=1),
            _position("AAA", 2, None, 1_000, x=2),
        ]

        frames = build_position_replay("2026-01-r", telemetry)

        self.assertEqual([frame["lap_number"] for frame in frames], [1, 2])
        self.assertIn("SessionTime was unavailable", frames[0]["positions"][0]["timing_caveat"])


def _lap(
    driver: str,
    lap_number: int,
    lap_time_ms: int,
    *,
    tyre_age: int = 2,
    stint: int = 1,
) -> dict[str, object]:
    return {
        "driver_code": driver,
        "lap_number": lap_number,
        "lap_time_ms": lap_time_ms,
        "compound": "MEDIUM",
        "tyre_age": tyre_age,
        "stint": stint,
        "is_pit_in_lap": False,
        "is_pit_out_lap": False,
        "is_deleted": False,
        "is_accurate": True,
        "track_status": "1",
    }


def _driver(code: str, team: str) -> dict[str, object]:
    return {"code": code, "team": {"name": team, "color": "#123456"}}


def _telemetry_rows(driver: str, lap_number: int, *, time_factor: float) -> list[dict[str, object]]:
    rows = []
    for index, distance in enumerate(range(0, 1_001, 100)):
        speed = 280
        brake = False
        if 300 <= distance <= 500:
            brake = True
            speed = 280 - (distance - 300) * 0.9
        elif distance > 500:
            speed = min(280, 100 + (distance - 500) * 0.5)
        rows.append(
            {
                "driver_code": driver,
                "lap_number": lap_number,
                "distance_m": distance,
                "relative_time_ms": distance * time_factor,
                "speed_kph": speed,
                "throttle_pct": 0 if brake else 100,
                "brake": brake,
                "x": distance,
                "y": index,
            }
        )
    return rows


def _position(
    driver: str,
    lap_number: int,
    session_time_ms: int | None,
    relative_time_ms: int,
    *,
    x: int,
) -> dict[str, object]:
    return {
        "driver_code": driver,
        "lap_number": lap_number,
        "session_time_ms": session_time_ms,
        "relative_time_ms": relative_time_ms,
        "x": x,
        "y": x,
        "speed_kph": 200,
        "distance_m": x * 100,
    }


class _TelemetryLap(dict):
    def __init__(self, driver: str, lap_number: int, *, sample_count: int, deleted: bool = False):
        super().__init__(Driver=driver, LapNumber=lap_number, Deleted=deleted)
        self.sample_count = sample_count

    def get_telemetry(self):
        return pd.DataFrame(
            [
                {
                    "Distance": index * 10,
                    "Speed": 200,
                    "Throttle": 90,
                    "Brake": False,
                    "RPM": 10_000,
                    "nGear": 7,
                    "DRS": 0,
                    "X": index,
                    "Y": index,
                    "Time": pd.Timedelta(milliseconds=index * 20),
                    "SessionTime": pd.Timedelta(seconds=100, milliseconds=index * 20),
                }
                for index in range(self.sample_count)
            ]
        )


class _CarOnlyTelemetryLap(_TelemetryLap):
    def get_telemetry(self):
        raise KeyError("position telemetry is unavailable")

    def get_car_data(self):
        frame = super().get_telemetry()
        return frame.drop(columns=["X", "Y"])


class _TelemetryLaps:
    empty = False

    def __init__(self, laps: list[_TelemetryLap]):
        self.laps = laps

    def iterlaps(self):
        yield from enumerate(self.laps)


class _TelemetrySession:
    def __init__(self, laps: list[_TelemetryLap]):
        self.laps = _TelemetryLaps(laps)


if __name__ == "__main__":
    unittest.main()
