"""Run the analyses on a session's rows and full-resolution telemetry.

The analysis functions live in ``backend/app/analysis`` and take lists of
plain rows. Two things stand between them and the build:

* They are given the rows that are published, dumped from the models, so what
  is analysed is what a reader sees.
* The telemetry ones are given every sample of the laps they read, not the
  thinned copy that is published (docs/architecture-review-findings.md,
  AR-11). A race is about 750,000 samples, so they are handed the telemetry by
  lap (``LapRows``) and only the laps they pick are turned into rows.

Each result is then read into its model, which is where its numbers are
rounded and its shape is checked.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

from f1data.models import (
    CarPerformance,
    CornerAnalysis,
    Corners,
    DistanceSource,
    Driver,
    IdealLaps,
    Lap,
    LapTimes,
    PacePrediction,
    PitStop,
    PositionReplay,
    RaceControlMessage,
    RacePace,
    ReplayDriver,
    SessionSummary,
    SessionType,
    Stint,
    Strategy,
    TeammateComparison,
    TrackDominance,
    TyreDegradation,
    artifact_json,
)
from f1data.telemetry import LapSamples, SessionTelemetry, nan_as_none

# The analyses are imported as ``backend.app.analysis``, from the repository root.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from backend.app.analysis.advanced import (  # noqa: E402
    POSITION_UNITS_PER_METRE,  # noqa: F401  (f1data/normalize.py measures with it too)
    calculate_car_performance,
    calculate_corner_analysis,
    calculate_fuel_adjusted_tyre_degradation,
    calculate_pace_prediction,
    calculate_track_dominance,
)
from backend.app.analysis.ideal_laps import calculate_ideal_laps  # noqa: E402
from backend.app.analysis.lap_times import lap_time_series  # noqa: E402
from backend.app.analysis.position_replay import REPLAY_INTERVAL_MS, build_position_replay  # noqa: E402
from backend.app.analysis.race_pace import calculate_race_pace  # noqa: E402
from backend.app.analysis.strategy import calculate_strategy  # noqa: E402
from backend.app.analysis.teammate_comparison import calculate_teammate_comparison  # noqa: E402

_UNKNOWN_COMPOUND = "UNKNOWN"
_PRACTICE = frozenset({SessionType.FP1, SessionType.FP2, SessionType.FP3})
_REPLAY_CHANNELS = ("x", "y", "speed_kph", "distance_m")


class LapRows:
    """Full-resolution telemetry by lap, in the form the analyses take it.

    Implements what ``backend.app.analysis.advanced.telemetry_by_lap`` asks
    of telemetry that is not a flat list of rows.
    """

    def __init__(self, telemetry: SessionTelemetry) -> None:
        self._laps = telemetry.laps

    def lap_keys(self) -> list[tuple[str, int]]:
        return list(self._laps)

    def lap_sample_count(self, key: tuple[str, int]) -> int:
        lap = self._laps.get(key)
        return lap.sample_count if lap is not None else 0

    def lap_end_m(self, key: tuple[str, int]) -> float:
        return float(self._laps[key].distance_m.max())

    def lap_rows(self, key: tuple[str, int]) -> list[dict[str, Any]]:
        lap = self._laps.get(key)
        return sample_rows(lap) if lap is not None else []


def sample_rows(lap: LapSamples, indexes: np.ndarray | None = None) -> list[dict[str, Any]]:
    """A lap's samples as the rows the analyses read, all of them or those at ``indexes``."""
    chosen = slice(None) if indexes is None else indexes
    time_ms = lap.time_ms[chosen].tolist()
    columns = {
        "distance_m": lap.distance_m[chosen].tolist(),
        "speed_kph": lap.speed_kph[chosen].tolist(),
        "throttle_pct": lap.throttle_pct[chosen].tolist(),
        "brake": lap.brake[chosen].tolist(),
        "relative_time_ms": time_ms,
        "session_time_ms": [lap.start_ms + moment for moment in time_ms],
        "x": nan_as_none(lap.x[chosen]) if lap.x is not None else [None] * len(time_ms),
        "y": nan_as_none(lap.y[chosen]) if lap.y is not None else [None] * len(time_ms),
    }
    names = list(columns)
    return [
        {"driver_code": lap.driver_code, "lap_number": lap.lap_number, **dict(zip(names, values))}
        for values in zip(*columns.values())
    ]


def session_analyses(
    summary: SessionSummary,
    drivers: list[Driver],
    laps: list[Lap],
    stints: list[Stint],
    pit_stops: list[PitStop],
    race_control: list[RaceControlMessage],
    corners: Corners,
    telemetry: SessionTelemetry,
) -> dict[str, Any]:
    """Every analysis artifact of a session, by its name under ``analysis/``."""
    # The analyses echo an id back in each result, which is dropped again
    # below, and read the session type from the summary.
    session_id = str(summary.session_key)
    summary_row = {"session": summary.session, "type": summary.session_type.value}
    lap_rows = [artifact_json(lap) for lap in laps]
    driver_rows = [
        {
            "code": driver.code,
            "team": {"name": driver.team.name, "color": driver.team.color} if driver.team else {},
        }
        for driver in drivers
    ]
    by_lap = LapRows(telemetry)
    # Corners that do not lie on this track would put every driver's figures
    # under the wrong corner, so they are not offered to the analysis.
    fitting = corners.fits_track is not False
    official = [artifact_json(corner) for corner in corners.corners] if fitting else []
    # Distances the build placed are along the reference lap, whose length
    # scales them to another lap. The archive's are along a lap it does not name.
    placed_here = corners.distance_source is DistanceSource.TELEMETRY and corners.reference_lap is not None
    reference_length = corners.reference_lap.length_m if placed_here else None
    corner_analysis = calculate_corner_analysis(session_id, lap_rows, by_lap, official, reference_length)
    if not fitting:
        corner_analysis["caveats"].append(
            "The circuit's archived corner positions do not lie on the line of the lap they were "
            f"checked against (up to {corners.off_track_m:.0f} m off it), so they are not used."
        )

    strategy = calculate_strategy(
        session_id,
        [artifact_json(stint) for stint in stints],
        [artifact_json(stop) for stop in pit_stops],
        lap_rows,
        [artifact_json(message) for message in race_control],
    )
    strategy["compound_usage"] = {
        (compound if compound is not None else _UNKNOWN_COMPOUND): count
        for compound, count in strategy["compound_usage"].items()
    }
    teammates = calculate_teammate_comparison(session_id, lap_rows, driver_rows)
    for row in teammates["rows"]:
        row.setdefault("caveat", None)

    analyses: dict[str, Any] = {
        "lap-times": LapTimes.model_validate(
            [_without(series, "metadata") for series in lap_time_series(lap_rows, driver_rows)]
        ),
        "race-pace": RacePace.model_validate(_result(calculate_race_pace(session_id, lap_rows))),
        "tyre-degradation": TyreDegradation.model_validate(
            _result(calculate_fuel_adjusted_tyre_degradation(session_id, summary_row, lap_rows))
        ),
        # The analysis echoes the stints, the stops and race control's
        # messages it was given. They are artifacts of their own.
        "strategy": Strategy.model_validate(
            {
                name: value
                for name, value in _result(strategy).items()
                if name not in ("stints", "pit_stops", "race_control_overlays")
            }
        ),
        "ideal-laps": IdealLaps.model_validate(_result(calculate_ideal_laps(session_id, lap_rows))),
        "team-mate-comparison": TeammateComparison.model_validate(_result(teammates)),
        "track-dominance": TrackDominance.model_validate(
            _result(calculate_track_dominance(session_id, lap_rows, by_lap))
        ),
        "corner-analysis": CornerAnalysis.model_validate(_result(corner_analysis)),
        "car-performance": CarPerformance.model_validate(
            _result(calculate_car_performance(session_id, lap_rows, by_lap, driver_rows))
        ),
    }
    if summary.session_type in _PRACTICE:
        # A long-run estimate is made from practice only. For any other
        # session the analysis says "not available", and a file that never
        # has anything in it is not published.
        analyses["pace-prediction"] = PacePrediction.model_validate(
            _result(calculate_pace_prediction(session_id, summary_row, lap_rows, driver_rows))
        )
    return analyses


def position_replay(telemetry: SessionTelemetry) -> PositionReplay:
    """Where every car was every few seconds, as one array per car over a common time base.

    ``build_position_replay`` cuts the session into windows and keeps, for
    each car in each window, the sample nearest the window's middle. It is
    given exactly those samples from the full-resolution telemetry, chosen the
    same way, so it returns what it would for every sample of the session
    without being handed three quarters of a million rows.
    """
    rows: list[dict[str, Any]] = []
    leader_lap: dict[int, int] = {}
    for lap in telemetry.laps.values():
        if not lap.has_position:
            continue
        # Only a sample with a position can stand for the car.
        placed = np.flatnonzero(~(np.isnan(lap.x) | np.isnan(lap.y)))
        if len(placed) == 0:
            continue
        on_clock = lap.start_ms + lap.time_ms[placed]
        window = on_clock // REPLAY_INTERVAL_MS
        from_middle = np.abs(on_clock - (window * REPLAY_INTERVAL_MS + REPLAY_INTERVAL_MS // 2))
        # The first sample of each window that is nearest its middle.
        order = np.lexsort((np.arange(len(window)), from_middle, window))
        first_of_window = np.concatenate(([True], np.diff(window[order]) != 0))
        rows.extend(sample_rows(lap, placed[np.sort(order[first_of_window])]))
        for number in np.unique(window).tolist():
            leader_lap[number] = max(leader_lap.get(number, 0), lap.lap_number)

    frames = build_position_replay("", rows)
    codes = sorted({position["driver_code"] for frame in frames for position in frame["positions"]})
    tracks: dict[str, dict[str, list[float | None]]] = {
        code: {channel: [None] * len(frames) for channel in _REPLAY_CHANNELS} for code in codes
    }
    for index, frame in enumerate(frames):
        for position in frame["positions"]:
            for channel in _REPLAY_CHANNELS:
                tracks[position["driver_code"]][channel][index] = position.get(channel)
    # The lap the session had reached. It does not fall back when the
    # leader finishes and only lapped cars are still running.
    reached: list[int | None] = []
    for frame in frames:
        lap_number = leader_lap.get(int(frame["timestamp_ms"]) // REPLAY_INTERVAL_MS)
        previous = reached[-1] if reached else None
        reached.append(max(lap_number, previous) if lap_number and previous else lap_number or previous)
    return PositionReplay(
        interval_ms=REPLAY_INTERVAL_MS,
        time_ms=[int(frame["timestamp_ms"]) for frame in frames],
        lap_number=reached,
        drivers=[ReplayDriver(driver_code=code, **tracks[code]) for code in codes],
    )


def _result(result: dict[str, Any]) -> dict[str, Any]:
    return _without(result, "session_id")


def _without(row: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in row.items() if name != key}
