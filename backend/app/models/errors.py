from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.models.domain import ErrorResponse


class NotFoundError(Exception):
    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details


class BadRequestError(Exception):
    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details


async def not_found_handler(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(code="not_found", message=exc.message, details=exc.details).model_dump(),
    )


async def bad_request_handler(_: Request, exc: BadRequestError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(
            code="bad_request", message=exc.message, details=exc.details
        ).model_dump(),
    )


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(code="http_error", message=detail).model_dump(),
    )

