"""Assemble the per-session analysis artifacts written by the static pipeline.

The analysis itself lives in ``backend/app/analysis/`` and is shared verbatim
with the FastAPI service -- this module only names the artifacts and routes each
one to the right function.  See ``backend/app/analysis/__init__.py`` for why the
package is imported here under the ``backend.app.*`` root while the service
imports the same files as ``app.*``.
"""

from __future__ import annotations

from typing import Any

from backend.app.analysis.advanced import (
    calculate_car_performance,
    calculate_corner_analysis,
    calculate_fuel_adjusted_tyre_degradation,
    calculate_pace_prediction,
    calculate_track_dominance,
)
from backend.app.analysis.common import (
    NEUTRALIZED_STATUSES,
    clean_laps,
    grouped,
    lap_statistics,
    most_common,
    trimmed_mean,
)
from backend.app.analysis.ideal_laps import calculate_ideal_laps
from backend.app.analysis.position_replay import (
    MAX_REPLAY_FRAMES,
    REPLAY_INTERVAL_MS,
    build_position_replay,
)
from backend.app.analysis.race_pace import calculate_race_pace, pace_rows
from backend.app.analysis.strategy import calculate_strategy
from backend.app.analysis.teammate_comparison import calculate_teammate_comparison

__all__ = [
    "MAX_REPLAY_FRAMES",
    "NEUTRALIZED_STATUSES",
    "REPLAY_INTERVAL_MS",
    "build_position_replay",
    "calculate_car_performance",
    "calculate_corner_analysis",
    "calculate_fuel_adjusted_tyre_degradation",
    "calculate_ideal_laps",
    "calculate_pace_prediction",
    "calculate_race_pace",
    "calculate_strategy",
    "calculate_teammate_comparison",
    "calculate_track_dominance",
    "calculate_tyre_degradation",
    "clean_laps",
    "grouped",
    "lap_statistics",
    "lap_time_series",
    "most_common",
    "pace_rows",
    "precompute_position_replay",
    "precompute_session_analysis",
    "trimmed_mean",
]


def precompute_session_analysis(session_id: str, bundle: dict[str, Any]) -> dict[str, Any]:
    laps = bundle.get("laps", [])
    drivers = bundle.get("drivers", [])
    stints = bundle.get("stints", [])
    pit_stops = bundle.get("pit_stops", [])
    race_control = bundle.get("race_control", [])
    telemetry = bundle.get("telemetry", [])
    summary = bundle.get("summary", {})

    return {
        "lap-times": lap_time_series(laps, drivers),
        "race-pace": calculate_race_pace(session_id, laps),
        "tyre-degradation": calculate_fuel_adjusted_tyre_degradation(
            session_id, summary, laps
        ),
        "strategy": calculate_strategy(session_id, stints, pit_stops, laps, race_control),
        "ideal-laps": calculate_ideal_laps(session_id, laps),
        "team-mate-comparison": calculate_teammate_comparison(session_id, laps, drivers),
        "track-dominance": calculate_track_dominance(session_id, laps, telemetry),
        "corner-analysis": calculate_corner_analysis(session_id, laps, telemetry),
        "car-performance": calculate_car_performance(session_id, laps, telemetry, drivers),
        "pace-prediction": calculate_pace_prediction(session_id, summary, laps, drivers),
    }


def precompute_position_replay(session_id: str, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return build_position_replay(session_id, bundle.get("telemetry", []))


def lap_time_series(laps: list[dict[str, Any]], drivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_driver: dict[str, dict[str, Any]] = {}
    driver_colors = {
        driver["code"]: driver.get("team", {}).get("color")
        for driver in drivers
        if driver.get("code")
    }
    for lap in laps:
        if lap.get("lap_time_ms") is None:
            continue
        row = by_driver.setdefault(
            lap["driver_code"],
            {"x": [], "y": [], "color": driver_colors.get(lap["driver_code"])},
        )
        row["x"].append(lap["lap_number"])
        row["y"].append(lap["lap_time_ms"])
    return [
        {
            "name": driver,
            "x": row["x"],
            "y": row["y"],
            "color": row["color"],
            "metadata": {},
        }
        for driver, row in sorted(by_driver.items())
    ]


def calculate_tyre_degradation(session_id: str, laps: list[dict[str, Any]]) -> dict[str, Any]:
    return calculate_fuel_adjusted_tyre_degradation(session_id, {}, laps)
