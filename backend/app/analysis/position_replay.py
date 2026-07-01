from collections import defaultdict
from typing import Any

from app.models.domain import PositionReplayFrame


def build_position_replay(session_id: str, telemetry: list[dict[str, Any]]) -> list[PositionReplayFrame]:
    with_position = [
        row
        for row in telemetry
        if row.get("x") is not None and row.get("y") is not None and row.get("relative_time_ms") is not None
    ]
    if not with_position:
        return []

    by_frame: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in with_position:
        frame_index = int(row["relative_time_ms"] // 5000)
        by_frame[frame_index].append(
            {
                "driver_code": row["driver_code"],
                "x": row["x"],
                "y": row["y"],
                "speed_kph": row.get("speed_kph"),
                "distance_m": row.get("distance_m"),
            }
        )

    frames = []
    for frame_index, positions in sorted(by_frame.items()):
        lap_number = min((row.get("lap_number") for row in with_position), default=None)
        frames.append(
            PositionReplayFrame(
                session_id=session_id,
                frame_index=frame_index,
                lap_number=lap_number,
                timestamp_ms=frame_index * 5000,
                positions=positions,
            )
        )
    return frames

