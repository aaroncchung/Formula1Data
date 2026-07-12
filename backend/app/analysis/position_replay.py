from collections import defaultdict
from typing import Any

from app.models.domain import PositionReplayFrame

REPLAY_INTERVAL_MS = 5000
MAX_REPLAY_FRAMES = 2000


def build_position_replay(session_id: str, telemetry: list[dict[str, Any]]) -> list[PositionReplayFrame]:
    with_position = [
        row
        for row in telemetry
        if row.get("x") is not None and row.get("y") is not None
        and (row.get("session_time_ms") is not None or row.get("relative_time_ms") is not None)
    ]
    if not with_position:
        return []

    session_timed = [row for row in with_position if row.get("session_time_ms") is not None]
    use_session_time = bool(session_timed)
    rows = session_timed if use_session_time else with_position
    by_frame = _group_replay_rows(rows, use_session_time)
    frames = []
    ordered_frames = _bounded_frames(sorted(by_frame.items()))
    for frame_index, (frame_key, positions_by_driver) in enumerate(ordered_frames):
        positions = []
        for position in sorted(positions_by_driver.values(), key=lambda row: row["driver_code"]):
            positions.append({key: value for key, value in position.items() if not key.startswith("_")})
        lap_numbers = {position.get("_lap_number") for position in positions_by_driver.values()}
        lap_number = next(iter(lap_numbers)) if len(lap_numbers) == 1 else None
        if use_session_time:
            timestamp_ms = int(frame_key) * REPLAY_INTERVAL_MS
        else:
            timestamp_ms = frame_index * REPLAY_INTERVAL_MS
            for position in positions:
                position["timing_basis"] = "lap-relative approximation"
                position["timing_caveat"] = (
                    "SessionTime was unavailable; drivers are aligned by lap number and lap-relative time."
                )
        frames.append(
            PositionReplayFrame(
                session_id=session_id,
                frame_index=frame_index,
                lap_number=lap_number,
                timestamp_ms=timestamp_ms,
                positions=positions,
            )
        )
    return frames


def _group_replay_rows(
    rows: list[dict[str, Any]], use_session_time: bool
) -> dict[Any, dict[str, dict[str, Any]]]:
    by_frame: dict[Any, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        lap_number = int(row.get("lap_number") or 0)
        driver = str(row.get("driver_code") or "").upper()
        timing = row.get("session_time_ms") if use_session_time else row.get("relative_time_ms")
        if not driver or timing is None or (not use_session_time and lap_number <= 0):
            continue
        timing = int(timing)
        time_bin = timing // REPLAY_INTERVAL_MS
        key = time_bin if use_session_time else (lap_number, time_bin)
        candidate = {
            "driver_code": driver,
            "x": row["x"],
            "y": row["y"],
            "speed_kph": row.get("speed_kph"),
            "distance_m": row.get("distance_m"),
            "_timing_ms": timing,
            "_lap_number": lap_number or None,
        }
        current = by_frame[key].get(driver)
        target = (time_bin + 0.5) * REPLAY_INTERVAL_MS
        if current is None or abs(timing - target) < abs(current["_timing_ms"] - target):
            by_frame[key][driver] = candidate
    return by_frame


def _bounded_frames(frames: list[Any]) -> list[Any]:
    if len(frames) <= MAX_REPLAY_FRAMES:
        return frames
    return [
        frames[round(index * (len(frames) - 1) / (MAX_REPLAY_FRAMES - 1))]
        for index in range(MAX_REPLAY_FRAMES)
    ]

