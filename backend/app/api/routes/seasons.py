from fastapi import APIRouter

from app.models.domain import Meeting, Season, Session
from app.services.dataset_service import DatasetService

router = APIRouter()


@router.get("/seasons", response_model=list[Season])
async def list_seasons() -> list[Season]:
    return [Season(**season) for season in DatasetService().list_seasons()]


@router.get("/seasons/{year}/meetings", response_model=list[Meeting])
async def list_meetings(year: int) -> list[Meeting]:
    return [Meeting(**meeting) for meeting in DatasetService().list_meetings(year)]


@router.get("/meetings/{year}/{round}/sessions", response_model=list[Session])
async def list_sessions(year: int, round: int) -> list[Session]:
    return [Session(**session) for session in DatasetService().list_sessions(year, round)]

