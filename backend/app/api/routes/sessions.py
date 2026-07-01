from typing import Any

from fastapi import APIRouter

from app.models.domain import (
    Driver,
    Lap,
    PitStop,
    RaceControlMessage,
    Result,
    Stint,
    WeatherSample,
)
from app.services.dataset_service import DatasetService

router = APIRouter()


@router.get("/sessions/{session_id}/summary")
async def get_summary(session_id: str) -> dict[str, Any]:
    return DatasetService().get_session_section(session_id, "summary")


@router.get("/sessions/{session_id}/drivers", response_model=list[Driver])
async def get_drivers(session_id: str) -> list[Driver]:
    return [Driver(**driver) for driver in DatasetService().get_session_section(session_id, "drivers")]


@router.get("/sessions/{session_id}/laps", response_model=list[Lap])
async def get_laps(session_id: str) -> list[Lap]:
    return [Lap(**lap) for lap in DatasetService().get_session_section(session_id, "laps")]


@router.get("/sessions/{session_id}/results", response_model=list[Result])
async def get_results(session_id: str) -> list[Result]:
    return [Result(**result) for result in DatasetService().get_session_section(session_id, "results")]


@router.get("/sessions/{session_id}/stints", response_model=list[Stint])
async def get_stints(session_id: str) -> list[Stint]:
    return [Stint(**stint) for stint in DatasetService().get_session_section(session_id, "stints")]


@router.get("/sessions/{session_id}/pit-stops", response_model=list[PitStop])
async def get_pit_stops(session_id: str) -> list[PitStop]:
    return [PitStop(**stop) for stop in DatasetService().get_session_section(session_id, "pit_stops")]


@router.get("/sessions/{session_id}/weather", response_model=list[WeatherSample])
async def get_weather(session_id: str) -> list[WeatherSample]:
    return [
        WeatherSample(**sample) for sample in DatasetService().get_session_section(session_id, "weather")
    ]


@router.get("/sessions/{session_id}/race-control", response_model=list[RaceControlMessage])
async def get_race_control(session_id: str) -> list[RaceControlMessage]:
    return [
        RaceControlMessage(**message)
        for message in DatasetService().get_session_section(session_id, "race_control")
    ]

