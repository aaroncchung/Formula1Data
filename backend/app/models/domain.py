from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class Season(BaseModel):
    year: int
    meeting_count: int
    ingested_meeting_count: int = 0
    is_sample: bool = False


class Circuit(BaseModel):
    circuit_id: str
    name: str
    country: str
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class Meeting(BaseModel):
    meeting_id: str
    year: int
    round: int
    name: str
    official_name: str | None = None
    circuit: Circuit
    start_date: date | None = None
    country: str
    sessions_available: list[str] = Field(default_factory=list)
    is_ingested: bool = False
    is_sample: bool = False


class Session(BaseModel):
    session_id: str
    year: int
    round: int
    meeting_id: str
    name: str
    type: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: Literal["available", "missing", "sample"] = "missing"
    is_sample: bool = False


class Team(BaseModel):
    team_id: str
    name: str
    color: str | None = None


class Driver(BaseModel):
    driver_id: str
    code: str
    full_name: str
    number: int | None = None
    team: Team
    country: str | None = None


class Lap(BaseModel):
    session_id: str
    driver_code: str
    lap_number: int
    lap_time_ms: int | None = None
    sector_1_ms: int | None = None
    sector_2_ms: int | None = None
    sector_3_ms: int | None = None
    compound: str | None = None
    tyre_age: int | None = None
    stint: int | None = None
    position: int | None = None
    is_pit_in_lap: bool = False
    is_pit_out_lap: bool = False
    is_deleted: bool = False
    is_accurate: bool = True
    track_status: str | None = None


class Stint(BaseModel):
    session_id: str
    driver_code: str
    stint: int
    compound: str
    start_lap: int
    end_lap: int
    lap_count: int


class PitStop(BaseModel):
    session_id: str
    driver_code: str
    lap_number: int
    duration_ms: int | None = None
    local_time: str | None = None


class WeatherSample(BaseModel):
    session_id: str
    lap_number: int | None = None
    timestamp: str | None = None
    air_temp_c: float | None = None
    track_temp_c: float | None = None
    humidity_pct: float | None = None
    rainfall: bool = False
    wind_speed_kph: float | None = None


class RaceControlMessage(BaseModel):
    session_id: str
    lap_number: int | None = None
    timestamp: str | None = None
    category: str
    message: str
    flag: str | None = None
    scope: str | None = None


class Result(BaseModel):
    session_id: str
    position: int
    driver_code: str
    classified_position: str | None = None
    status: str | None = None
    points: float | None = None
    grid: int | None = None
    gap: str | None = None
    laps: int | None = None


class TelemetrySample(BaseModel):
    session_id: str
    driver_code: str
    lap_number: int
    distance_m: float
    speed_kph: float | None = None
    throttle_pct: float | None = None
    brake: bool | None = None
    rpm: int | None = None
    gear: int | None = None
    drs: int | None = None
    x: float | None = None
    y: float | None = None
    relative_time_ms: int | None = None
    session_time_ms: int | None = None


class ChartSeries(BaseModel):
    name: str
    x: list[Any]
    y: list[Any]
    color: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TelemetryDriverMeta(BaseModel):
    driver_code: str
    team: str | None = None
    lap_time_ms: int | None = None
    compound: str | None = None
    session: str | None = None
    lap_number: int


class TelemetryComparison(BaseModel):
    session_id: str
    driver_a: TelemetryDriverMeta
    driver_b: TelemetryDriverMeta
    distance_m: list[float]
    speed_a: list[float | None]
    speed_b: list[float | None]
    throttle_a: list[float | None]
    throttle_b: list[float | None]
    brake_a: list[int | None]
    brake_b: list[int | None]
    rpm_a: list[int | None]
    rpm_b: list[int | None]
    gear_a: list[int | None]
    gear_b: list[int | None]
    drs_a: list[int | None]
    drs_b: list[int | None]
    delta_speed_kph: list[float | None]
    delta_time_ms: list[float | None] = Field(default_factory=list)
    track_x: list[float | None] = Field(default_factory=list)
    track_y: list[float | None] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class RacePaceDriverRow(BaseModel):
    driver_code: str
    median_lap_ms: float | None
    mean_lap_ms: float | None
    trimmed_mean_lap_ms: float | None
    fastest_clean_lap_ms: int | None
    lap_count: int
    compound: str | None = None
    stint: int | None = None
    gap_to_best_ms: float | None = None


class RacePaceResult(BaseModel):
    session_id: str
    drivers: list[RacePaceDriverRow]
    stints: list[RacePaceDriverRow]
    caveats: list[str] = Field(default_factory=list)


class TyreDegradationRow(BaseModel):
    driver_code: str
    compound: str | None
    stint: int
    degradation_ms_per_lap: float | None
    raw_slope_ms_per_lap: float | None = None
    fuel_correction_ms_per_lap: float | None = None
    r_squared: float | None
    sample_count: int
    stint_length: int
    excluded_outlier_count: int = 0
    caveats: list[str] = Field(default_factory=list)


class TyreDegradationResult(BaseModel):
    session_id: str
    rows: list[TyreDegradationRow]
    model: dict[str, Any] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)


class QualifyingDeltaResult(BaseModel):
    session_id: str
    driver_a: str
    driver_b: str
    sector_delta_ms: dict[str, int | None]
    telemetry: TelemetryComparison | None = None
    caveats: list[str] = Field(default_factory=list)


class PositionReplayFrame(BaseModel):
    session_id: str
    frame_index: int
    lap_number: int | None = None
    timestamp_ms: int | None = None
    positions: list[dict[str, Any]]


class LiveTimingEntry(BaseModel):
    driver_code: str
    position: int | None = None
    gap_to_leader: str | None = None
    interval: str | None = None
    last_lap_ms: int | None = None
    compound: str | None = None
    pit_count: int | None = None

