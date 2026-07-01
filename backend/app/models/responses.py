from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    data: T
    is_sample: bool = False
    caveats: list[str] = Field(default_factory=list)


class EmptyStateResponse(BaseModel):
    reason: str
    action: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class LiveDisabledResponse(BaseModel):
    enabled: bool = False
    reason: str
    setup: list[str]

