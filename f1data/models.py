"""The published format, version 2: every object a reader can fetch, as a model.

These models are the contract between the build and whatever reads what it
publishes (docs/architecture-review-findings.md, AR-09). Every session artifact
is built as one of them and written from it, so a field that is not declared
here cannot be published and a value of the wrong kind stops the build.
``python -m f1data schema`` exports them as JSON Schema, which is what the
frontend's types are generated from.

Conventions, which hold for every artifact:

* A missing value is ``null``. There is no ``NaN``, no ``"nan"``, no
  ``"None"`` and no empty string standing in for one.
* Every declared field is always present. A field that can be ``null`` says so.
  The one exception is the index, whose shape predates this format.
* Times are whole milliseconds: lap and sector times, gaps and durations
  (``*_ms``), and positions in time (``time_ms``, ``start_ms``), which count
  from the moment the session clock read zero. That is FastF1's
  ``SessionTime``; ``summary.json`` says when it was in UTC. Statistics over
  times (a median, a mean, a fitted rate) are not whole, and are given to the
  precision each field states.
* Every other number that is not whole is rounded to the precision its field
  states, here and nowhere else. That is what makes two builds of one snapshot
  the same bytes on every platform.
* A session is the one whose generation is being read. No artifact repeats its
  identity row by row; ``summary.json`` and the manifest carry F1's session
  key. Nothing is taken from the calendar: a round number moves when the
  calendar changes, so pages look it up in the index.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, RootModel
from typing_extensions import NotRequired, TypedDict

# --- numbers ------------------------------------------------------------------


def _to(digits: int) -> Any:
    def rounded(value: float) -> float:
        # Adding zero turns -0.0 into 0.0, which would otherwise print
        # differently from the 0.0 a build a hair the other side of zero gives.
        return round(value, digits) + 0.0

    return rounded


def _each_to(digits: int) -> Any:
    def rounded(values: list[Any]) -> list[Any]:
        return [None if value is None else round(value, digits) + 0.0 for value in values]

    return rounded


def _decimal(digits: int) -> Any:
    return Annotated[float, AfterValidator(_to(digits)), Field(json_schema_extra={"x-decimals": digits})]


def _decimals(digits: int) -> Any:
    return Annotated[
        list[float], AfterValidator(_each_to(digits)), Field(json_schema_extra={"x-decimals": digits})
    ]


def _decimals_or_null(digits: int) -> Any:
    return Annotated[
        list[float | None], AfterValidator(_each_to(digits)), Field(json_schema_extra={"x-decimals": digits})
    ]


# A number with a stated count of decimal places. Every float in the format is
# one of these; tests/test_models.py fails on a bare ``float``.
Decimal1 = _decimal(1)
Decimal2 = _decimal(2)
Decimal3 = _decimal(3)
Decimals1 = _decimals(1)
Decimals1OrNull = _decimals_or_null(1)

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


# --- closed sets --------------------------------------------------------------


class SessionType(str, Enum):
    """The session's code."""

    FP1 = "FP1"
    FP2 = "FP2"
    FP3 = "FP3"
    Q = "Q"
    SQ = "SQ"
    S = "S"
    R = "R"


class Compound(str, Enum):
    """A tyre compound, as F1's timing names it."""

    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"
    # The 2018 season, the first FastF1 has timing for, named three more.
    SUPERSOFT = "SUPERSOFT"
    ULTRASOFT = "ULTRASOFT"
    HYPERSOFT = "HYPERSOFT"


_COMPOUNDS = frozenset(compound.value for compound in Compound)


def known_compound(value: Any) -> str | None:
    """A compound's name, or ``None`` for anything that is not one.

    F1 leaves the compound out for some laps and FastF1 passes that on as an
    empty string, ``None``, ``"UNKNOWN"`` or ``"TEST_UNKNOWN"``.
    """
    if isinstance(value, Compound):
        return value.value
    text = str(value).strip().upper() if value is not None else ""
    return text if text in _COMPOUNDS else None


CompoundOrNull = Annotated[Compound | None, BeforeValidator(known_compound)]


class CoverageBar(str, Enum):
    """Something a session has to have to count as complete (f1data/coverage.py)."""

    SESSION_INFO = "session_info"
    DRIVER_LIST = "driver_list"
    TIMING_DATA = "timing_data"
    TYRE_DATA = "tyre_data"
    TRACK_STATUS = "track_status"
    LAP_COUNT = "lap_count"
    SESSION_STATUS = "session_status"
    WEATHER = "weather"
    RACE_CONTROL = "race_control"
    CAR_DATA = "car_data"
    POSITION = "position"
    PIT_STOP_SERIES = "pit_stop_series"
    CIRCUIT_INFO = "circuit_info"
    CLASSIFICATION = "classification"
    MEASUREMENT = "measurement"


class FitStatus(str, Enum):
    """Whether a tyre degradation rate is reported for a stint, and if not, why."""

    OK = "ok"
    TOO_FEW_LAPS = "too_few_laps"
    POOR_FIT = "poor_fit"


class PitLossExclusion(str, Enum):
    """Why a stop is left out of the pit-loss estimate."""

    NO_LAP_NUMBER = "no_lap_number"
    MISSING_LAP_TIME = "missing_lap_time"
    FIRST_LAP = "first_lap"
    BACK_TO_BACK_STOPS = "back_to_back_stops"
    NOT_GREEN = "not_green"
    TOO_FEW_BASELINE_LAPS = "too_few_baseline_laps"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CornerSource(str, Enum):
    """Where the corners of a corner analysis come from."""

    OFFICIAL = "official"
    INFERRED = "inferred"


class DistanceSource(str, Enum):
    """Who placed the circuit's corners along the lap."""

    # FastF1, when the session was fetched, from the session's fastest lap.
    ARCHIVE = "archive"
    # The build, from the lap named in ``reference_lap``.
    TELEMETRY = "telemetry"


class TelemetryChannel(str, Enum):
    """A per-sample array of a telemetry lap."""

    TIME_MS = "time_ms"
    DISTANCE_M = "distance_m"
    SPEED_KPH = "speed_kph"
    THROTTLE_PCT = "throttle_pct"
    BRAKE = "brake"
    RPM = "rpm"
    GEAR = "gear"
    DRS = "drs"
    X = "x"
    Y = "y"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


# --- the session --------------------------------------------------------------


class SessionSummary(Model):
    """``summary.json``: what the session is, in F1's own words."""

    session_key: int = Field(description="F1's key for the session. It names the session everywhere.")
    year: int
    meeting: str = Field(description="The meeting's name as F1's session information gives it.")
    session: str = Field(description="The session's name, such as Race or Sprint.")
    session_type: SessionType
    circuit: str | None = Field(description="F1's short name for the circuit.")
    country: str | None
    driver_count: int
    lap_count: int = Field(description="Laps in laps.json, over every driver.")
    weather_summary: str = Field(
        description="One line for a heading: the air and track temperature ranges, and rain or dry."
    )
    clock_zero_utc: str | None = Field(
        description="When the session clock read zero, in UTC to the millisecond. "
        "Every position in time in this generation is milliseconds after it."
    )
    is_sample: bool = Field(description="True only for the invented session used in local development.")


class Team(Model):
    team_id: str = Field(description="The team's name in lower case with hyphens.")
    name: str
    color: str | None = Field(description="The team's colour as #RRGGBB.")


class Driver(Model):
    driver_id: str = Field(description="The driver's code in lower case.")
    code: str = Field(description="The three-letter code that names the driver in every other artifact.")
    full_name: str
    number: int | None = Field(description="The racing number.")
    team: Team | None = Field(description="Null when F1's driver list names no team.")
    country: str | None = Field(
        description="F1's country code for the driver. F1 left it empty throughout 2026."
    )


class Drivers(RootModel[list[Driver]]):
    """``drivers.json``: everyone in F1's driver list or the classification."""


class Lap(Model):
    driver_code: str
    lap_number: int
    lap_time_ms: int | None = Field(description="Milliseconds. Null for a lap F1 did not time.")
    sector_1_ms: int | None
    sector_2_ms: int | None
    sector_3_ms: int | None
    compound: CompoundOrNull = Field(description="Null where F1 reported none.")
    tyre_age: int | None = Field(
        description="Laps the set had done at the end of this lap. Null for a set that went on used: F1 "
        "does not report its age."
    )
    stint: int | None
    position: int | None = Field(description="Position at the end of the lap.")
    is_pit_in_lap: bool
    is_pit_out_lap: bool
    is_deleted: bool = Field(description="The lap time was deleted by the stewards.")
    is_accurate: bool = Field(description="FastF1's judgement that the lap's timing is whole and consistent.")
    track_status: str | None = Field(
        description="Every track status code seen during the lap, run together: 1 clear, 2 yellow, "
        "4 safety car, 5 red flag, 6 virtual safety car, 7 virtual safety car ending."
    )


class Laps(RootModel[list[Lap]]):
    """``laps.json``: every lap of every driver, in timing order."""


class Result(Model):
    position: int | None = Field(
        description="Null for a driver who took part and whom the classification leaves out. Such rows come "
        "last."
    )
    driver_code: str
    classified_position: str | None = Field(
        description="The position as the classification prints it: a number, or a letter such as R for "
        "retired."
    )
    status: str | None
    points: Decimal1 | None
    grid: int | None = Field(description="Starting position. 0 for a start from the pit lane.")
    time_ms: int | None = Field(description="The winner's race time in milliseconds. Null for everyone else.")
    gap_ms: int | None = Field(
        description="Milliseconds behind the winner, for a driver who finished on the same lap. Null for "
        "everyone else."
    )
    laps_down: int | None = Field(
        description="Laps behind the winner, for a classified driver who finished one or more down. Null "
        "for everyone else."
    )
    behind_at_flag_ms: int | None = Field(
        description="For a driver with laps_down: milliseconds after the winner that they took the flag. "
        "Not a gap, since they had fewer laps to run: it only orders the cars on one lap."
    )
    laps: int | None = Field(description="Laps completed. Null for a driver the classification leaves out.")
    provisional: bool = Field(
        description="True when Jolpica has no classification for the session. The rows are then the order "
        "on track from the timing alone, with no status, points or grid."
    )


class Results(RootModel[list[Result]]):
    """``results.json``: the classification in finishing order, then anyone it leaves out."""


class Stint(Model):
    driver_code: str
    stint: int | None
    compound: CompoundOrNull
    start_lap: int
    end_lap: int
    lap_count: int


class Stints(RootModel[list[Stint]]):
    """``stints.json``: each run of laps a driver did on one set of tyres."""


class PitStopSources(Model):
    """Where each figure of a pit stop comes from. Null beside a figure that is null."""

    duration_ms: Literal["timing"] | None = Field(
        description="timing: the gap between the timing's pit-entry and pit-exit times."
    )
    stationary_ms: Literal["pit_stop_series"] | None = Field(
        description="pit_stop_series: F1's own pit-stop feed."
    )
    pit_lane_ms: Literal["pit_stop_series"] | None = Field(
        description="pit_stop_series: F1's own pit-stop feed."
    )


class PitStop(Model):
    driver_code: str
    lap_number: int = Field(description="The lap the car came in on.")
    entry_time_ms: int | None = Field(
        description="When the car crossed the pit entry, in milliseconds on the session clock. "
        "Null for a stop only F1's pit-stop feed reports."
    )
    duration_ms: int | None = Field(
        description="Milliseconds from pit entry to pit exit, from the timing. Null when the car did not "
        "come back out."
    )
    stationary_ms: int | None = Field(
        description="Milliseconds the car stood still, from F1's pit-stop feed."
    )
    pit_lane_ms: int | None = Field(description="Milliseconds in the pit lane, from F1's pit-stop feed.")
    sources: PitStopSources


class PitStops(RootModel[list[PitStop]]):
    """``pit-stops.json``: every entry to the pit lane, with F1's own figures where it gives them."""


class WeatherSample(Model):
    time_ms: int = Field(description="Milliseconds on the session clock.")
    lap_number: int | None = Field(
        description="In a race or sprint, the lap the leader was on. Null before the start, after the flag, "
        "and in any other session."
    )
    air_temp_c: Decimal1 | None
    track_temp_c: Decimal1 | None
    humidity_pct: Decimal1 | None
    rainfall: bool
    wind_speed_kph: Decimal1 | None = Field(description="Kilometres an hour. F1 reports metres a second.")


class Weather(RootModel[list[WeatherSample]]):
    """``weather.json``: every weather sample F1 sent, about one a minute."""


class RaceControlMessage(Model):
    time_ms: int | None = Field(description="Milliseconds on the session clock.")
    lap_number: int | None
    category: str
    message: str
    flag: str | None
    scope: str | None


class RaceControl(RootModel[list[RaceControlMessage]]):
    """``race-control.json``: race control's messages, in order."""


# --- the circuit --------------------------------------------------------------


class Corner(Model):
    number: int
    letter: str | None = Field(description="Set where one number covers several corners, such as 1A.")
    x: Decimal1 = Field(description="In the units of the position data, tenths of a metre.")
    y: Decimal1
    angle: Decimal1 | None = Field(
        description="Degrees. Which way to draw the corner's label from its position."
    )
    distance_m: Decimal1 | None = Field(
        description="Metres from the start line. Null when the corner could not be placed along the lap."
    )


class ReferenceLap(Model):
    driver_code: str
    lap_number: int
    length_m: Decimal1 = Field(description="The lap's length as its own telemetry measures it, in metres.")


class Corners(Model):
    """``corners.json``: the circuit's official corner positions. Empty when none were archived."""

    rotation: Decimal1 | None = Field(
        description="Degrees to turn the position data by so the map sits as F1 draws it."
    )
    corners: list[Corner]
    distance_source: DistanceSource | None = Field(description="Null when no corner has a distance.")
    reference_lap: ReferenceLap | None = Field(
        description="The lap the corners were checked against, and placed along when distance_source "
        "is telemetry: the fastest clean lap whose position data is whole, or failing that the fastest "
        "that has any. Null when no lap has any."
    )
    off_track_m: Decimal1 | None = Field(
        description="Metres from the track, as reference_lap drove it, of the corner furthest from it. "
        "Null when there is no lap to check against."
    )
    fits_track: bool | None = Field(
        description="False when the corner positions do not lie on the line reference_lap drove: the "
        "archived map is not of this track, or no lap of the session has position data that is whole. "
        "They should not be drawn over this session's position data, and the corner analysis infers "
        "its corners instead. Null when there is no lap to check against."
    )


# --- coverage -----------------------------------------------------------------


class Shortfall(Model):
    bar: CoverageBar
    driver: str | None = Field(description="The driver's code, or null when the whole session is short.")
    detail: str


class CoverageFeeds(Model):
    """Whether each feed arrived at all."""

    session_info: bool
    timing_data: bool
    car_data: bool
    position: bool
    weather: bool
    race_control: bool
    track_status: bool
    session_status: bool
    lap_count: bool
    pit_stop_series: bool
    circuit_info: bool


class DriverCoverage(Model):
    driver_code: str
    number: str
    in_driver_list: bool
    classified_laps: int | None = Field(description="Laps in the classification. Null when there is none.")
    timing_laps: int = Field(description="Laps F1 timed.")
    generated_laps: int = Field(
        description="Laps FastF1 added for a retirement. They are in laps.json and were never timed."
    )
    car_laps: int = Field(description="Timed laps whose car data runs from start to end with no long hole.")
    position_laps: int = Field(description="The same for position data.")
    tyre_laps: int = Field(description="Timed laps with a compound and a stint.")
    tyre_age_laps: int = Field(description="Timed laps with a tyre age as well.")


class Coverage(Model):
    """``coverage.json``: what arrived for this session, and what it is short of."""

    complete: bool = Field(description="True when shortfalls is empty.")
    shortfalls: list[Shortfall]
    feeds: CoverageFeeds
    session_ended: bool
    total_laps: int | None = Field(description="The race distance in laps.")
    pit_stops_in_timing: int
    pit_stops_in_series: int
    circuit_corners: int
    max_sample_gap_seconds: Decimal1 = Field(
        description="The longest hole between two samples that a lap's car or position data may have and "
        "still count."
    )
    drivers: list[DriverCoverage]


# --- telemetry ----------------------------------------------------------------


class TelemetryDriverEntry(Model):
    """One driver's laps that have telemetry, as parallel arrays with one entry per lap."""

    driver_code: str
    path: str = Field(description="The driver's file, relative to the generation.")
    lap_number: list[int]
    lap_time_ms: list[int | None] = Field(
        description="Each lap's time as in laps.json, so that a lap can be picked from here alone."
    )
    compound: list[CompoundOrNull]
    sample_count: list[int] = Field(description="Samples published for each lap.")
    raw_sample_count: list[int] = Field(
        description="Samples each lap has at full resolution, which is what the analyses read."
    )
    has_position: list[bool] = Field(
        description="False for a lap with no usable position data, and so no x and y."
    )


class TelemetryIndex(Model):
    """``telemetry/index.json``: which laps have telemetry, and where."""

    max_samples_per_lap: int = Field(
        description="A lap with more samples is thinned evenly to this many, keeping both ends."
    )
    channels: list[TelemetryChannel] = Field(
        description="The arrays a lap carries. DRS is absent when it never changes in the session, as in "
        "2026, which has no DRS."
    )
    drivers: list[TelemetryDriverEntry]


class TelemetryLap(Model):
    """One lap as parallel arrays, one entry per sample."""

    lap_number: int
    start_ms: int = Field(description="When the lap started, in milliseconds on the session clock.")
    time_ms: list[int] = Field(
        description="Milliseconds since the lap started. Add start_ms for the session clock."
    )
    distance_m: Decimals1 = Field(description="Metres since the lap started, integrated from speed.")
    speed_kph: Decimals1
    throttle_pct: list[int] = Field(description="0 to 100.")
    brake: list[bool]
    rpm: list[int]
    gear: list[int]
    drs: list[int] | None = Field(
        description="F1's DRS code. Null when the channel is left out of the session."
    )
    x: Decimals1OrNull | None = Field(
        description="Tenths of a metre. Null when the lap has no usable position data. Within a lap that "
        "has, "
        "null for a sample taken before the position feed started or after it stopped, which can only be "
        "within a few seconds of either end of the lap."
    )
    y: Decimals1OrNull | None


class DriverTelemetry(Model):
    """``telemetry/<driver_code>.json``: every lap of one driver."""

    driver_code: str
    laps: list[TelemetryLap]


class ReplayDriver(Model):
    """One car's track, one entry per frame. Null in a frame the car has no position for."""

    driver_code: str
    x: Decimals1OrNull = Field(description="Tenths of a metre.")
    y: Decimals1OrNull
    speed_kph: Decimals1OrNull
    distance_m: Decimals1OrNull = Field(description="Metres into the car's current lap.")


class PositionReplay(Model):
    """``position-replay.json``: where every car was, every few seconds.

    Empty arrays when the session has no position data. A session whose
    position feed stops part-way has frames up to where it stops.
    """

    interval_ms: int = Field(description="The length of a frame's window in milliseconds.")
    time_ms: list[int] = Field(
        description="The start of each frame's window, in milliseconds on the session clock."
    )
    lap_number: list[int | None] = Field(
        description="The lap the session had reached: the highest any car had started."
    )
    drivers: list[ReplayDriver]


# --- analyses -----------------------------------------------------------------


class LapTimeSeries(Model):
    name: str = Field(description="The driver's code.")
    x: list[int] = Field(description="Lap numbers.")
    y: list[int] = Field(description="Lap times in milliseconds.")
    color: str | None


class LapTimes(RootModel[list[LapTimeSeries]]):
    """``analysis/lap-times.json``: each driver's timed laps, ready to chart."""


class RacePaceRow(Model):
    driver_code: str
    compound: CompoundOrNull = Field(description="The compound most of the laps were on.")
    stint: int | None = Field(description="Null in a row for the whole race.")
    median_lap_ms: Decimal1 | None
    mean_lap_ms: Decimal1 | None
    trimmed_mean_lap_ms: Decimal1 | None
    fastest_clean_lap_ms: int | None
    lap_count: int
    gap_to_best_ms: Decimal1 | None


class RacePace(Model):
    """``analysis/race-pace.json``."""

    drivers: list[RacePaceRow]
    stints: list[RacePaceRow]
    caveats: list[str]


class TyreDegradationRow(Model):
    driver_code: str
    compound: CompoundOrNull
    stint: int
    sample_count: int
    stint_length: int
    degradation_ms_per_lap: Decimal2 | None = Field(description="Null unless fit_status is ok.")
    raw_slope_ms_per_lap: Decimal2 | None
    fuel_correction_ms_per_lap: Decimal1
    r_squared: Decimal3 | None
    residual_spread_ms: Decimal1 | None
    slope_standard_error_ms_per_lap: Decimal2 | None
    excluded_outlier_count: int
    fit_status: FitStatus
    caveats: list[str]


class TyreDegradationModel(Model):
    method: str
    race_fuel_correction_ms_per_lap: Decimal1
    sprint_fuel_correction_ms_per_lap: Decimal1
    minimum_laps: int
    max_slope_standard_error_ms_per_lap: Decimal1
    max_slope_relative_standard_error: Decimal2


class TyreDegradation(Model):
    """``analysis/tyre-degradation.json``."""

    rows: list[TyreDegradationRow]
    model: TyreDegradationModel
    caveats: list[str]


class StopPitLoss(Model):
    driver_code: str | None
    lap_number: int | None
    pit_loss_ms: Decimal1 | None
    in_lap_ms: int | None
    out_lap_ms: int | None
    baseline_lap_ms: Decimal1 | None
    baseline_lap_count: int
    excluded_reason: PitLossExclusion | None


class PitLoss(Model):
    estimate_ms: Decimal1 | None
    spread_ms: Decimal1 | None
    qualifying_stop_count: int
    stop_count: int
    minimum_stop_count: int
    baseline_window_laps: int
    excluded_stop_counts: dict[PitLossExclusion, int]
    stops: list[StopPitLoss]


class PitLaneTime(Model):
    """Pit-lane transit times from the timing, summarised."""

    median_ms: Decimal1 | None
    fastest_ms: int | None
    slowest_ms: int | None
    timed_stop_count: int
    stop_count: int


class PaceChangeAcrossStop(Model):
    driver_code: str
    stop_lap: int
    first_clean_lap_gain_ms: int | None = Field(
        description="The lap before the stop minus the lap after it, in milliseconds. Positive is quicker "
        "on the new tyres."
    )
    before_lap_number: int | None
    before_lap_ms: int | None
    after_lap_number: int | None
    after_lap_ms: int | None
    caveat: str


class Strategy(Model):
    """``analysis/strategy.json``. The stints and stops themselves are in stints.json and pit-stops.json."""

    compound_usage: dict[str, int] = Field(
        description="Stints by compound. The key UNKNOWN counts stints whose compound F1 did not report."
    )
    pit_loss_estimate_ms: Decimal1 | None
    pit_loss: PitLoss
    pit_lane_time: PitLaneTime
    undercut_overcut: list[PaceChangeAcrossStop]
    caveats: list[str]


class IdealLapRow(Model):
    driver_code: str
    best_sector_1_ms: int | None
    best_sector_2_ms: int | None
    best_sector_3_ms: int | None
    ideal_lap_ms: int | None
    best_lap_ms: int | None
    delta_to_ideal_ms: int | None


class IdealLaps(Model):
    """``analysis/ideal-laps.json``."""

    rows: list[IdealLapRow]


class TeammateComparisonDriver(Model):
    driver_code: str
    average_lap_ms: Decimal1 | None
    lap_count: int
    clean_lap_count: int


class TeammateComparisonRow(Model):
    team: str
    drivers: list[TeammateComparisonDriver]
    gap_ms: Decimal1 | None
    gap_spread_ms: Decimal1 | None
    matched_lap_count: int
    trimmed_lap_count: int
    caveat: str | None


class TeammateComparison(Model):
    """``analysis/team-mate-comparison.json``."""

    rows: list[TeammateComparisonRow]
    caveats: list[str]


class RepresentativeLap(Model):
    driver_code: str
    lap_number: int
    lap_time_ms: int | None


class Point(Model):
    x: Decimal1 | None
    y: Decimal1 | None


class Minisector(Model):
    index: int
    start_distance_m: Decimal1
    end_distance_m: Decimal1
    midpoint: Point
    winner_driver_code: str | None
    segment_time_ms: Decimal1 | None
    gap_to_next_ms: Decimal1 | None
    driver_times_ms: dict[str, Decimal1] = Field(
        description="Milliseconds through the minisector, by driver code."
    )


class TrackDominance(Model):
    """``analysis/track-dominance.json``."""

    representative_laps: list[RepresentativeLap]
    excluded_drivers: list[str]
    minisector_count: int
    minisectors: list[Minisector]
    caveats: list[str]


class CornerDriver(Model):
    driver_code: str
    brake_start_m: Decimal1 | None = Field(description="Null where the driver did not brake for the corner.")
    apex_distance_m: Decimal1
    braking_distance_m: Decimal1 | None
    entry_speed_kph: Decimal1 | None
    apex_speed_kph: Decimal1
    exit_speed_kph: Decimal1 | None
    speed_loss_kph: Decimal1 | None
    brake_duration_ms: Decimal1 | None


class AnalysedCorner(Model):
    corner_number: int = Field(
        description="The circuit's own number when corner_source is official, otherwise the order found."
    )
    letter: str | None
    distance_m: Decimal1 | None
    x: Decimal1 | None
    y: Decimal1 | None
    drivers: list[CornerDriver]


class CornerAnalysis(Model):
    """``analysis/corner-analysis.json``."""

    corner_source: CornerSource
    representative_laps: list[RepresentativeLap]
    corners: list[AnalysedCorner]
    caveats: list[str]


class CarPerformanceDriver(Model):
    driver_code: str
    team: str
    lap_number: int | None
    max_speed_kph: Decimal1
    p95_speed_kph: Decimal1
    low_speed_avg_kph: Decimal1 | None
    medium_speed_avg_kph: Decimal1 | None
    high_speed_avg_kph: Decimal1 | None
    full_throttle_pct: Decimal1 | None
    braking_pct: Decimal1 | None


class CarPerformanceTeam(Model):
    team: str
    drivers: list[str]
    max_speed_kph: Decimal1 | None
    p95_speed_kph: Decimal1 | None
    low_speed_avg_kph: Decimal1 | None
    medium_speed_avg_kph: Decimal1 | None
    high_speed_avg_kph: Decimal1 | None
    full_throttle_pct: Decimal1 | None
    braking_pct: Decimal1 | None


class CarPerformance(Model):
    """``analysis/car-performance.json``."""

    drivers: list[CarPerformanceDriver]
    teams: list[CarPerformanceTeam]
    caveats: list[str]


class PacePredictionDriver(Model):
    driver_code: str
    team: str
    estimated_race_pace_ms: Decimal1
    gap_to_best_ms: Decimal1 | None
    sample_count: int
    stint_count: int
    variability_ms: Decimal1
    confidence: Confidence
    compounds: list[str]


class PacePredictionTeam(Model):
    team: str
    drivers: list[str]
    estimated_race_pace_ms: Decimal1
    gap_to_best_ms: Decimal1 | None
    sample_count: int
    confidence: Confidence


class PacePrediction(Model):
    """``analysis/pace-prediction.json``. Published for practice sessions only: a race has no such file."""

    available: bool
    session_type: str
    drivers: list[PacePredictionDriver]
    teams: list[PacePredictionTeam]
    caveats: list[str]


# --- what the publisher writes around a generation ------------------------------


class Identity(Model):
    """Who a session is, from F1's own session information (f1data/identity.py)."""

    session_key: int
    meeting_key: int
    year: int
    session_type: SessionType
    session_name: str
    start_time_utc: str
    meeting_name: str
    meeting_official_name: str | None
    location: str | None
    country: str | None
    circuit_key: int | None
    circuit_name: str | None
    archive_path: str
    round_at_fetch: int | None = Field(
        description="The round when the session was fetched. The index has the round as it is now."
    )


class ManifestFile(Model):
    path: str
    size_bytes: int
    sha256: Sha256


class Manifest(Model):
    """``manifest.json``: every file of a generation. Its SHA-256 is the generation's name."""

    format_version: int
    pipeline_version: int
    session_key: int
    identity: Identity
    files: list[ManifestFile]


class ManifestReference(Model):
    sha256: Sha256
    size_bytes: int


class PointerCoverage(Model):
    complete: bool
    shortfalls: list[Shortfall]


class Pointer(Model):
    """``pointers/<session_key>.json``: which generation is the published one."""

    schema_version: int
    format_version: int
    pipeline_version: int
    session_key: int
    identity: Identity
    generation: Sha256
    manifest: ManifestReference
    snapshot_id: str
    classification_fingerprint: str | None
    also: dict[str, Any] | None = Field(
        description="Anything else the generation was built from, outside the archive and the "
        "classification. "
        "Null in this format, where a build takes nothing from the calendar."
    )
    record: str | None = Field(
        description="A checksum of what the snapshot's record said of its feeds when the session was "
        "judged. A record corrected afterwards has the session decided again."
    )
    coverage: PointerCoverage
    published_at: str
    previous_generation: Sha256 | None


class IndexSession(TypedDict):
    """A session of the calendar. The last two keys are there only once it is published."""

    __pydantic_config__ = ConfigDict(extra="forbid")  # type: ignore[misc]

    type: SessionType
    name: str
    start_time_utc: str | None
    # Whether sessions of this type are published at all. An unpublished one
    # that is in scope is on its way; one that is not will not come.
    in_scope: bool
    session_key: NotRequired[int]
    complete: NotRequired[bool]


class IndexMeeting(Model):
    round: int = Field(description="As the calendar has it now. It moves when the calendar changes.")
    name: str
    official_name: str | None
    country: str | None
    location: str | None
    date: str | None
    format: str | None
    meeting_key: int | None = Field(
        description="F1's key for the meeting, which does not move. Known once a session of the meeting is "
        "published."
    )
    circuit_key: int | None = Field(description="F1's key for the circuit, from the same source.")
    circuit_name: str | None
    sessions: list[IndexSession]


class IndexSeason(Model):
    year: int
    meetings: list[IndexMeeting]


class UnscheduledSession(Model):
    """A published session the calendar no longer lists."""

    session_key: int
    year: int
    type: SessionType
    name: str
    meeting_name: str
    start_time_utc: str
    complete: bool


class Index(Model):
    """``index.json``: the calendar as it is now, with each published session attached."""

    schema_version: int
    format_version: int
    seasons: list[IndexSeason]
    unscheduled: list[UnscheduledSession]


class StandingsRounds(Model):
    drivers: int
    constructors: int


class DriverStanding(Model):
    position: int | None
    points: int | float | None
    wins: int | None
    driver_code: str | None
    driver_number: int | None
    given_name: str | None
    family_name: str | None
    constructors: list[str]


class ConstructorStanding(Model):
    position: int | None
    points: int | float | None
    wins: int | None
    constructor_id: str | None
    name: str | None


class Standings(Model):
    """``standings/<year>.json``: the championship tables as Jolpica has them."""

    schema_version: int
    format_version: int
    year: int
    rounds: StandingsRounds = Field(description="The round each table stands after.")
    drivers: list[DriverStanding]
    constructors: list[ConstructorStanding]


# --- where each one is published -------------------------------------------------

TELEMETRY_INDEX_PATH = "telemetry/index.json"
TELEMETRY_PREFIX = "telemetry/"

# Session artifacts by their path inside a generation. A driver's telemetry is
# the one path that is not fixed; the telemetry index names each.
SESSION_ARTIFACTS: dict[str, type[BaseModel]] = {
    "summary.json": SessionSummary,
    "drivers.json": Drivers,
    "laps.json": Laps,
    "results.json": Results,
    "stints.json": Stints,
    "pit-stops.json": PitStops,
    "weather.json": Weather,
    "race-control.json": RaceControl,
    "corners.json": Corners,
    "coverage.json": Coverage,
    "position-replay.json": PositionReplay,
    TELEMETRY_INDEX_PATH: TelemetryIndex,
    "analysis/lap-times.json": LapTimes,
    "analysis/race-pace.json": RacePace,
    "analysis/tyre-degradation.json": TyreDegradation,
    "analysis/strategy.json": Strategy,
    "analysis/ideal-laps.json": IdealLaps,
    "analysis/team-mate-comparison.json": TeammateComparison,
    "analysis/track-dominance.json": TrackDominance,
    "analysis/corner-analysis.json": CornerAnalysis,
    "analysis/car-performance.json": CarPerformance,
    "analysis/pace-prediction.json": PacePrediction,
}


def telemetry_path(driver_code: str) -> str:
    return f"{TELEMETRY_PREFIX}{driver_code}.json"


def model_for_artifact(path: str) -> type[BaseModel] | None:
    """The model of a file inside a generation, or ``None`` for a path that is not one."""
    if path in SESSION_ARTIFACTS:
        return SESSION_ARTIFACTS[path]
    if path == "manifest.json":
        return Manifest
    if (
        path.startswith(TELEMETRY_PREFIX)
        and path.endswith(".json")
        and "/" not in path[len(TELEMETRY_PREFIX) :]
    ):
        return DriverTelemetry
    return None


def artifact_json(artifact: BaseModel) -> Any:
    """An artifact as plain JSON values, ready for ``dump_json``."""
    return artifact.model_dump(mode="json")
