from typing import Any

from fastapi import APIRouter, Query

from app.analysis.position_replay import build_position_replay
from app.analysis.telemetry_compare import compare_telemetry, telemetry_lap
from app.models.domain import PositionReplayFrame, TelemetryComparison, TelemetrySample
from app.models.responses import EmptyStateResponse
from app.services.dataset_service import DatasetService

router = APIRouter()


@router.get("/telemetry/compare", response_model=TelemetryComparison | EmptyStateResponse)
async def compare(
    session_id: str = Query(...),
    driver_a: str = Query(..., min_length=2, max_length=3),
    lap_a: int = Query(..., ge=1),
    driver_b: str = Query(..., min_length=2, max_length=3),
    lap_b: int = Query(..., ge=1),
) -> TelemetryComparison | EmptyStateResponse:
    bundle = DatasetService().get_session_bundle(session_id)
    result = compare_telemetry(
        session_id,
        bundle.get("telemetry", []),
        bundle.get("laps", []),
        bundle.get("drivers", []),
        driver_a,
        lap_a,
        driver_b,
        lap_b,
    )
    if result is None:
        return EmptyStateResponse(
            reason="Telemetry is unavailable for one or both selected laps.",
            action="Ingest the session with telemetry enabled or choose laps with telemetry artifacts.",
        )
    return result


@router.get("/telemetry/lap", response_model=list[TelemetrySample] | EmptyStateResponse)
async def lap(
    session_id: str = Query(...),
    driver: str = Query(..., min_length=2, max_length=3),
    lap: int = Query(..., ge=1),
) -> list[TelemetrySample] | EmptyStateResponse:
    bundle = DatasetService().get_session_bundle(session_id)
    rows = telemetry_lap(bundle.get("telemetry", []), driver, lap)
    if not rows:
        return EmptyStateResponse(
            reason="Telemetry is missing for this driver and lap.",
            action="Try the sample VER lap 6 or LEC lap 7, or ingest a real session.",
        )
    return [TelemetrySample(**row) for row in rows]


@router.get("/position/replay", response_model=list[PositionReplayFrame] | EmptyStateResponse)
async def position_replay(session_id: str = Query(...)) -> list[PositionReplayFrame] | EmptyStateResponse:
    bundle = DatasetService().get_session_bundle(session_id)
    frames = build_position_replay(session_id, bundle.get("telemetry", []))
    if not frames:
        return EmptyStateResponse(
            reason="Position/location data is unavailable for this session.",
            action="Ingest position data through FastF1 or OpenF1.",
        )
    return [PositionReplayFrame(**frame) for frame in frames]

