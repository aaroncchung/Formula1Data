from typing import Any

from fastapi import APIRouter, Query

from app.analysis.advanced import (
    calculate_car_performance,
    calculate_corner_analysis,
    calculate_pace_prediction,
    calculate_track_dominance,
)
from app.analysis.ideal_laps import calculate_ideal_laps
from app.analysis.lap_times import lap_time_series as calculate_lap_time_series
from app.analysis.qualifying_delta import calculate_qualifying_delta
from app.analysis.race_pace import calculate_race_pace
from app.analysis.strategy import calculate_strategy
from app.analysis.teammate_comparison import calculate_teammate_comparison
from app.analysis.tyre_degradation import calculate_tyre_degradation
from app.models.domain import ChartSeries, QualifyingDeltaResult, RacePaceResult, TyreDegradationResult
from app.services.dataset_service import DatasetService

router = APIRouter()


@router.get("/analysis/race-pace", response_model=RacePaceResult)
async def race_pace(session_id: str = Query(...)) -> RacePaceResult:
    bundle = DatasetService().get_session_bundle(session_id)
    return RacePaceResult(**calculate_race_pace(session_id, bundle["laps"]))


@router.get("/analysis/lap-times", response_model=list[ChartSeries])
async def lap_times(session_id: str = Query(...)) -> list[ChartSeries]:
    bundle = DatasetService().get_session_bundle(session_id)
    series = calculate_lap_time_series(bundle["laps"], bundle.get("drivers", []))
    return [ChartSeries(**row) for row in series]


@router.get("/analysis/stints")
async def stints(session_id: str = Query(...)) -> dict[str, Any]:
    bundle = DatasetService().get_session_bundle(session_id)
    return {
        "session_id": session_id,
        "stints": bundle.get("stints", []),
        "pit_stops": bundle.get("pit_stops", []),
    }


@router.get("/analysis/tyre-degradation", response_model=TyreDegradationResult)
async def tyre_degradation(session_id: str = Query(...)) -> TyreDegradationResult:
    bundle = DatasetService().get_session_bundle(session_id)
    return calculate_tyre_degradation(session_id, bundle["laps"], bundle.get("summary"))


@router.get("/analysis/qualifying-delta", response_model=QualifyingDeltaResult)
async def qualifying_delta(
    session_id: str = Query(...),
    driver_a: str = Query(..., min_length=2, max_length=3),
    driver_b: str = Query(..., min_length=2, max_length=3),
) -> QualifyingDeltaResult:
    bundle = DatasetService().get_session_bundle(session_id)
    return calculate_qualifying_delta(
        session_id,
        bundle["laps"],
        bundle.get("telemetry", []),
        bundle.get("drivers", []),
        driver_a,
        driver_b,
    )


@router.get("/analysis/ideal-laps")
async def ideal_laps(session_id: str = Query(...)) -> dict[str, Any]:
    bundle = DatasetService().get_session_bundle(session_id)
    return calculate_ideal_laps(session_id, bundle["laps"])


@router.get("/analysis/team-mate-comparison")
async def teammate_comparison(session_id: str = Query(...)) -> dict[str, Any]:
    bundle = DatasetService().get_session_bundle(session_id)
    return calculate_teammate_comparison(session_id, bundle["laps"], bundle.get("drivers", []))


@router.get("/analysis/strategy")
async def strategy(session_id: str = Query(...)) -> dict[str, Any]:
    bundle = DatasetService().get_session_bundle(session_id)
    return calculate_strategy(
        session_id,
        bundle.get("stints", []),
        bundle.get("pit_stops", []),
        bundle.get("laps", []),
        bundle.get("race_control", []),
    )


@router.get("/analysis/track-dominance")
async def track_dominance(session_id: str = Query(...)) -> dict[str, Any]:
    bundle = DatasetService().get_session_bundle(session_id)
    return calculate_track_dominance(
        session_id, bundle.get("laps", []), bundle.get("telemetry", [])
    )


@router.get("/analysis/corner-analysis")
async def corner_analysis(session_id: str = Query(...)) -> dict[str, Any]:
    bundle = DatasetService().get_session_bundle(session_id)
    return calculate_corner_analysis(
        session_id, bundle.get("laps", []), bundle.get("telemetry", [])
    )


@router.get("/analysis/car-performance")
async def car_performance(session_id: str = Query(...)) -> dict[str, Any]:
    bundle = DatasetService().get_session_bundle(session_id)
    return calculate_car_performance(
        session_id,
        bundle.get("laps", []),
        bundle.get("telemetry", []),
        bundle.get("drivers", []),
    )


@router.get("/analysis/pace-prediction")
async def pace_prediction(session_id: str = Query(...)) -> dict[str, Any]:
    bundle = DatasetService().get_session_bundle(session_id)
    return calculate_pace_prediction(
        session_id,
        bundle.get("summary", {}),
        bundle.get("laps", []),
        bundle.get("drivers", []),
    )

