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
  key. No artifact takes anything from the calendar: a round number moves when
  the calendar changes, so pages look it up in the index.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, RootModel, model_validator
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
    CAR_DATA_REPEATS = "car_data_repeats"
    POSITION_REPEATS = "position_repeats"
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
    RED_FLAG_WAIT = "red_flag_wait"
    NO_STOP = "no_stop"
    MISSING_LAP_TIME = "missing_lap_time"
    FIRST_LAP = "first_lap"
    BACK_TO_BACK_STOPS = "back_to_back_stops"
    NOT_GREEN = "not_green"
    TOO_FEW_BASELINE_LAPS = "too_few_baseline_laps"


class Braking(str, Enum):
    """What F1's car feed shows of a driver's braking for a corner."""

    SEEN = "seen"
    NONE = "none"
    BEGAN_UNREAD = "began_unread"
    UNREAD = "unread"


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
    lap_count: int = Field(
        description="Laps in laps.json, over every driver. That counts the lap a car stopped on, which "
        "FastF1 adds a row for and F1's timing has none of: one or two in most races."
    )
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
    code: str = Field(
        description="The code that names the driver in every other artifact: F1's three letters, or the "
        "car number as text for a driver neither F1's driver list nor the classification names."
    )
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
        description="Laps the set had done at the end of this lap, a set that went on used included. Null "
        "where F1's tyre data gives no age."
    )
    stint: int | None = Field(
        description="Which of the driver's sets of tyres the lap was run on, counted as F1 counts them "
        "but for one thing: F1 gives a new number to a car that went through the pit lane and kept its "
        "tyres, and such a lap keeps the number of the set it is still on."
    )
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
        description="Laps behind the winner, for a driver who took the flag one or more down. Null for "
        "one who did not finish, classified or not. Null "
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
    under_red_flag: bool = Field(
        description="Whether the session was red-flagged while the car was in the pit lane. The duration "
        "is then a wait for the restart and not a pit stop, and the strategy analysis leaves it out of its "
        "pit-lane figures."
    )
    stationary_ms: int | None = Field(
        description="Milliseconds the car stood still, from F1's pit-stop feed."
    )
    pit_lane_ms: int | None = Field(description="Milliseconds in the pit lane, from F1's pit-stop feed.")
    tyres_changed: bool | None = Field(
        description="Whether the car went out on another set of tyres than it came in on, by F1's tyre "
        "data. False for a car that kept its tyres: a drive-through penalty, a penalty served in the pit "
        "box, a passage behind the safety car. Null where the tyre data does not say: it names no "
        "compound for the lap the car came in on or the one after, or the car did not go out again. "
        "The tyre data can lag a stop by some laps, so false beside a stationary time is still a stop."
    )
    sources: PitStopSources


class PitStops(RootModel[list[PitStop]]):
    """``pit-stops.json``: every entry to the pit lane, with F1's own figures where it gives them.

    Not every entry is a pit stop. One is known to be a stop when F1's pit-stop
    feed gives it a stationary time or its tyres were changed, and is taken
    not to be when the feed gives it none and the tyre data says the car kept
    its tyres.
    """


class WeatherSample(Model):
    time_ms: int = Field(description="Milliseconds on the session clock.")
    lap_number: int | None = Field(
        description="In a race or sprint, the lap the leader was on. Null before the start, after the flag, "
        "and in any other session."
    )
    air_temp_c: Decimal1 | None = Field(
        description="Degrees Celsius. Null, like the track temperature and the humidity, when F1's feed gave no value for "
        "it, or gave the zero it sends for a sensor with no reading: exactly 0 between readings twenty or "
        "more from it."
    )
    track_temp_c: Decimal1 | None
    humidity_pct: Decimal1 | None
    rainfall: bool | None = Field(
        description="Null, like any other reading of a sample, when F1's feed gave no value for it."
    )
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
    car_repeating_laps: int | None = Field(
        description="Timed laps on which more than a quarter of the car samples sent while the car was moving "
        "have the speed and the engine speed of the sample before. The car data of such a lap arrived and is "
        "counted in car_laps, and is not to be relied on. Null when it was not counted."
    )
    position_repeating_laps: int | None = Field(
        description="The same for position data: samples with the place of the sample before."
    )


class Coverage(Model):
    """``coverage.json``: what arrived for this session, and what it is short of."""

    complete: bool = Field(description="True when shortfalls is empty.")
    shortfalls: list[Shortfall]
    feeds: CoverageFeeds
    session_ended: bool
    total_laps: int | None = Field(description="The race distance in laps.")
    pit_stops_in_timing: int = Field(
        description="Entries to the pit lane the timing shows, whether or not the car stopped: a wait "
        "through a red flag and a drive-through penalty are each one."
    )
    pit_stops_in_series: int = Field(
        description="Stops F1's pit-stop feed gives a stationary time or a pit-lane time for."
    )
    circuit_corners: int
    max_sample_gap_seconds: Decimal1 = Field(
        description="The longest hole between two samples that a lap's car or position data may have and "
        "still count."
    )
    drivers: list[DriverCoverage]


# --- telemetry ----------------------------------------------------------------


class TelemetryDriverEntry(Model):
    """One driver's laps that have telemetry, as parallel arrays with one entry per lap."""

    @model_validator(mode="after")
    def _a_lap_has_every_figure(self) -> "TelemetryDriverEntry":
        _one_length(
            self,
            (
                "lap_number", "lap_time_ms", "compound", "is_accurate", "is_deleted", "is_pit_in_lap",
                "is_pit_out_lap", "sample_count", "raw_sample_count", "has_position",
            ),
        )
        return self

    driver_code: str
    path: str = Field(description="The driver's file, relative to the generation.")
    lap_number: list[int]
    lap_time_ms: list[int | None] = Field(
        description="Each lap's time as in laps.json, so that a lap can be picked from here alone."
    )
    compound: list[CompoundOrNull]
    is_accurate: list[bool | None] = Field(
        description="Each lap's four flags as in laps.json, so that a page can offer a clean lap first: "
        "one that is timed accurately, was not deleted, and neither enters nor leaves the pits."
    )
    is_deleted: list[bool | None]
    is_pit_in_lap: list[bool | None]
    is_pit_out_lap: list[bool | None]
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


def _one_length(model: BaseModel, names: tuple[str, ...]) -> None:
    """Arrays that run side by side have one entry each for the same things, or the file is not published."""
    lengths = {name: len(getattr(model, name)) for name in names if getattr(model, name) is not None}
    if len(set(lengths.values())) > 1:
        raise ValueError(f"arrays that should be of one length are not: {lengths}")


class TelemetryLap(Model):
    """One lap as parallel arrays, one entry per sample."""

    @model_validator(mode="after")
    def _a_sample_has_every_channel(self) -> "TelemetryLap":
        _one_length(
            self,
            ("time_ms", "distance_m", "speed_kph", "throttle_pct", "brake", "rpm", "gear", "drs", "x", "y"),
        )
        return self

    lap_number: int
    start_ms: int = Field(description="When the lap started, in milliseconds on the session clock.")
    time_ms: list[int] = Field(
        description="Milliseconds since the lap started. Add start_ms for the session clock."
    )
    distance_m: Decimals1 = Field(description="Metres since the lap started, integrated from speed.")
    speed_kph: Decimals1
    throttle_pct: list[int | None] = Field(
        description="0 to 100. Null at a sample F1's car feed gave no reading of the throttle for (it "
        "sends 104, most often for both pedals at once while it repeats the speed it last had), and "
        "between such a sample and the one before or after."
    )
    brake: list[bool | None] = Field(
        description="Whether the brake was on. Null from a sample F1's car feed gave no reading of the "
        "brake for (it sends 104) until the next that has one. FastF1 reads that mark as the brake on, "
        "so it is taken from F1's raw feed."
    )
    rpm: list[int]
    gear: list[int | None] = Field(
        description="0 for neutral, 1 to 8. Null from a sample for which F1's car feed sent a number "
        "that is no gear until the next that is one."
    )
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
    """``telemetry/<driver_code>.json``: every lap of one driver that has car data from end to end.

    A lap with a hole of more than a few seconds in its car data is not here
    (``max_sample_gap_seconds`` in ``coverage.json``), and the coverage counts
    it as missing.
    """

    driver_code: str
    laps: list[TelemetryLap]


class ReplayDriver(Model):
    """One car's track, one entry per frame. Null in a frame the car has no position for."""

    driver_code: str
    x: Decimals1OrNull = Field(description="Tenths of a metre.")
    y: Decimals1OrNull
    speed_kph: Decimals1OrNull = Field(
        description="Null as well in a frame where the car has a position and no car data."
    )
    distance_m: Decimals1OrNull = Field(
        description="Metres into the car's current lap. Null as well in a frame where the car has a "
        "position and no car data."
    )


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

    @model_validator(mode="after")
    def _a_frame_has_every_car(self) -> "PositionReplay":
        frames = len(self.time_ms)
        if len(self.lap_number) != frames:
            raise ValueError(f"{frames} frames and {len(self.lap_number)} lap numbers")
        for driver in self.drivers:
            lengths = {name: len(getattr(driver, name)) for name in ("x", "y", "speed_kph", "distance_m")}
            if set(lengths.values()) != {frames}:
                raise ValueError(f"{frames} frames and, for {driver.driver_code}, {lengths}")
        return self


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
    """One stint, as stints.json has it. Clean laps F1's tyre data gives no stint for are in no row."""

    driver_code: str
    compound: CompoundOrNull = Field(
        description="The stint's compound: the one F1 names for any lap of it. Null where it names none."
    )
    stint: int
    sample_count: int = Field(
        description="The stint's clean laps that have a tyre age, which are the ones a fit can use. "
        "Those left out of the fit as outliers are still counted here: the fit is of this many less "
        "excluded_outlier_count."
    )
    stint_length: int = Field(description="The stint's clean laps, with a tyre age or without.")
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
    stop_count: int = Field(description="Every entry to the pit lane, a stop or not.")
    minimum_stop_count: int
    baseline_window_laps: int
    excluded_stop_counts: dict[PitLossExclusion, int]
    stops: list[StopPitLoss]


class PitLaneTime(Model):
    """Pit-lane transit times from the timing, summarised over the stops F1's pit-stop feed reports."""

    median_ms: Decimal1 | None
    fastest_ms: int | None
    slowest_ms: int | None
    timed_stop_count: int = Field(
        description="The stops the three figures are of: the entries to the pit lane that F1's pit-stop "
        "feed gives a stationary time for, that have a transit time, and that were not a wait through a "
        "red flag."
    )
    stop_count: int = Field(description="Every entry to the pit lane, a stop or not.")


class PaceChangeAcrossStop(Model):
    driver_code: str
    stop_lap: int = Field(
        description="The lap the driver first came in on, leaving out any entry to the pit lane the car "
        "went through without stopping or waited in through a red flag."
    )
    first_clean_lap_gain_ms: int | None = Field(
        description="The lap before the stop minus the lap after it, in milliseconds. Positive is quicker "
        "after the stop, which is on other tyres unless the stop list says the tyres were not changed."
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
    corner_distance_m: Decimal1 = Field(
        description="Where the corner is along this driver's own lap, which is what the other distances "
        "of the row are along: an official corner as it is found on the lap, and a corner inferred from "
        "the braking where this driver was slowest. Laps measure their own distance and disagree by "
        "tens of metres, so this is not the corner's distance_m."
    )
    brake_start_m: Decimal1 | None = Field(
        description="Null unless braking is seen: the driver did not brake for the corner, or where they "
        "began to is not known."
    )
    apex_distance_m: Decimal1
    braking_distance_m: Decimal1 | None
    entry_speed_kph: Decimal1 | None
    apex_speed_kph: Decimal1
    exit_speed_kph: Decimal1 | None
    speed_loss_kph: Decimal1 | None
    brake_duration_ms: Decimal1 | None
    braking: Braking = Field(
        description="seen: the driver braked, and the feed shows it from where it began. none: the brake "
        "was read all the way into the corner, and no braking that is the corner's took 8 km/h off the "
        "car. began_unread: the driver braked, and where it began the feed has no brake reading, or has "
        "the brake on while the car gathers speed, so the brake point and what is counted from it are "
        "null. unread: no braking that counts is seen and the feed has no brake reading for part of the "
        "approach, so whether the driver braked is not known."
    )


class AnalysedCorner(Model):
    corner_number: int = Field(
        description="The circuit's own number when corner_source is official, otherwise the order found."
    )
    letter: str | None
    distance_m: Decimal1 | None = Field(
        description="Along the lap the circuit's corners were placed on when corner_source is official, "
        "and otherwise the middle of where the drivers were slowest. A driver's own lap has the corner "
        "at that driver's corner_distance_m."
    )
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
    """Who a session is, from F1's own session information (f1data/identity.py).

    Two fields are the calendar's, as it stood when the session was fetched:
    the start time and the round.
    """

    session_key: int
    meeting_key: int
    year: int
    session_type: SessionType
    session_name: str
    start_time_utc: str = Field(description="When the calendar said the session starts.")
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
        description="What else the generation was built from, outside the archive and the "
        "classification: under calendar, the calendar entry the session was built as (year, round, "
        "names, and a checksum of the whole row). The publisher's own record, by which it knows to "
        "build again; a reader takes the round from the index."
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
