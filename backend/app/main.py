from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analysis, ingest, live, seasons, sessions, telemetry
from app.config import get_settings
from app.models.errors import (
    BadRequestError,
    NotFoundError,
    bad_request_handler,
    http_exception_handler,
    not_found_handler,
)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Formula 1 Data API",
        description="Personal-use Formula 1 analytics API powered by FastF1 and OpenF1.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(NotFoundError, not_found_handler)
    app.add_exception_handler(BadRequestError, bad_request_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)

    app.include_router(seasons.router, prefix="/api/v1", tags=["seasons"])
    app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
    app.include_router(analysis.router, prefix="/api/v1", tags=["analysis"])
    app.include_router(telemetry.router, prefix="/api/v1", tags=["telemetry"])
    app.include_router(live.router, prefix="/api/v1", tags=["live"])
    app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "formula-1-data-api"}

    return app


app = create_app()

