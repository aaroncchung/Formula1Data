from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.ingestion.fastf1_ingestor import FastF1Ingestor

router = APIRouter()


class IngestSessionRequest(BaseModel):
    year: int = Field(..., ge=2018, le=2100)
    event: str = Field(..., min_length=2)
    session: str = Field(..., min_length=1, max_length=4)
    force: bool = False


class IngestSeasonRequest(BaseModel):
    year: int = Field(..., ge=2018, le=2100)
    force: bool = False
    sessions: list[str] | None = None
    races_only: bool = False


@router.post("/ingest/session")
async def ingest_session(request: IngestSessionRequest) -> dict[str, str]:
    session_id = FastF1Ingestor().ingest_session(
        year=request.year,
        event=request.event,
        session_name=request.session,
        force=request.force,
    )
    return {"status": "ok", "session_id": session_id}


@router.post("/ingest/season")
async def ingest_season(request: IngestSeasonRequest) -> dict[str, str | int]:
    count = FastF1Ingestor().ingest_season(
        year=request.year,
        force=request.force,
        sessions=request.sessions,
        races_only=request.races_only,
    )
    return {"status": "ok", "year": request.year, "sessions_ingested": count}

