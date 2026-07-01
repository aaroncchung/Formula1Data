from typing import Any

from fastapi import APIRouter

from app.config import get_settings
from app.models.responses import LiveDisabledResponse
from app.services.openf1_service import OpenF1Service

router = APIRouter()


def _disabled() -> LiveDisabledResponse:
    return LiveDisabledResponse(
        reason="Live mode is disabled by ENABLE_LIVE_MODE=false.",
        setup=[
            "Set ENABLE_LIVE_MODE=true in backend/.env.",
            "Set OPENF1_API_KEY if your OpenF1 access requires authentication.",
            "Restart the backend and keep CORS_ORIGINS restricted to trusted frontend URLs.",
        ],
    )


@router.get("/live/current-session")
async def current_session() -> dict[str, Any] | LiveDisabledResponse:
    if not get_settings().enable_live_mode:
        return _disabled()
    return await OpenF1Service().current_session()


@router.get("/live/timing")
async def timing() -> dict[str, Any] | LiveDisabledResponse:
    if not get_settings().enable_live_mode:
        return _disabled()
    return await OpenF1Service().live_timing()


@router.get("/live/race-control")
async def race_control() -> dict[str, Any] | LiveDisabledResponse:
    if not get_settings().enable_live_mode:
        return _disabled()
    return await OpenF1Service().race_control()


@router.get("/live/positions")
async def positions() -> dict[str, Any] | LiveDisabledResponse:
    if not get_settings().enable_live_mode:
        return _disabled()
    return await OpenF1Service().positions()


@router.get("/live/weather")
async def weather() -> dict[str, Any] | LiveDisabledResponse:
    if not get_settings().enable_live_mode:
        return _disabled()
    return await OpenF1Service().weather()

