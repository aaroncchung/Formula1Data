"""Each lap's telemetry at full resolution, built once from a loaded session.

The normaliser this replaces called ``lap.get_telemetry()`` for every lap. That
took about 0.3 s a lap, six minutes for a race, nearly all of it working out
the car ahead, which nothing published uses. It then cut every lap to 300
samples before any analysis saw it
(docs/architecture-review-findings.md, AR-11).

``extract_telemetry`` produces what ``Lap.get_telemetry`` produces, for the
channels that are published, in about two milliseconds a lap. It is the same
procedure, step for step, on NumPy arrays:

1. Cut the driver's car data and position data to the lap, with one sample of
   padding either side.
2. Integrate speed over the padded car data to get distance.
3. Merge the two on their timestamps. A channel missing at a timestamp is
   filled the way FastF1 fills it: speed, RPM and throttle linearly in time;
   distance and position with a quadratic spline; gear, brake and DRS with the
   last value seen.
4. Add a sample at the exact start and end of the lap, filled the same way,
   and drop what lies outside.

The interpolation goes through the calls pandas makes for FastF1
(``numpy.interp`` and ``scipy.interpolate.interp1d``) with the same arguments,
so the result is not an approximation of FastF1's: on the 2026 Austrian GP it
is the same number for every sample of every lap
(tests/test_recorded_race.py).

Two things differ from FastF1 on purpose, both where the position feed is
broken:

* F1 sends (0, 0) while it has no position for a car. Those samples are not
  positions (f1data/coverage.py) and are left out before anything is merged.
* A position is only ever interpolated between two real samples, never
  extrapolated past the last. FastF1 extrapolates the spline for as long as
  the lap lasts, which in the 2026 Monaco race, whose position feed stops in
  lap 5, draws a car a minute away from where it was. Here a lap has position
  when its samples pass the test coverage is measured by (they reach from its
  start to its end with no long hole), and within such a lap a sample has
  none where the feed had not yet started or had already stopped: the first
  two and a half seconds of that race, when F1 was still sending (0, 0) for
  the cars on the grid, and the last seconds of the leader's fifth lap. A lap
  that fails the test has no position at all and is built from the car data
  alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.interpolate import interp1d

from f1data.coverage import MAX_SAMPLE_GAP_SECONDS, lap_is_usable

# The published resolution. Analyses read every sample (AR-11).
MAX_PUBLISHED_SAMPLES_PER_LAP = 300

# A quadratic spline needs three points.
_MIN_SPLINE_POINTS = 3
_NS_PER_MS = 1_000_000
_NS_PER_SECOND = 1_000_000_000
_MAX_GAP_NS = int(MAX_SAMPLE_GAP_SECONDS * _NS_PER_SECOND)


@dataclass(frozen=True)
class LapSamples:
    """One lap of one driver, every sample, as parallel arrays."""

    driver_code: str
    lap_number: int
    # When the lap started, in milliseconds on the session clock.
    start_ms: int
    # Milliseconds since the lap started. The first sample is 0 and the last is the lap's length.
    time_ms: np.ndarray
    distance_m: np.ndarray
    speed_kph: np.ndarray
    throttle_pct: np.ndarray
    rpm: np.ndarray
    gear: np.ndarray
    brake: np.ndarray
    drs: np.ndarray
    # None when the lap has no usable position data. NaN in a sample taken
    # before the position feed started or after it stopped.
    x: np.ndarray | None
    y: np.ndarray | None

    @property
    def sample_count(self) -> int:
        return int(len(self.time_ms))

    @property
    def has_position(self) -> bool:
        return self.x is not None


@dataclass(frozen=True)
class SessionTelemetry:
    """Every lap that has telemetry, by driver code and lap number, in timing order."""

    laps: dict[tuple[str, int], LapSamples]

    def driver_codes(self) -> list[str]:
        return sorted({driver for driver, _ in self.laps})

    def of_driver(self, driver_code: str) -> list[LapSamples]:
        return sorted(
            (lap for (driver, _), lap in self.laps.items() if driver == driver_code),
            key=lambda lap: lap.lap_number,
        )

    def drs_values(self) -> set[int]:
        """Every value the DRS channel takes in the session."""
        values: set[int] = set()
        for lap in self.laps.values():
            values.update(int(value) for value in np.unique(lap.drs))
        return values


@dataclass(frozen=True)
class _Feed:
    """One driver's samples from one feed, in time order."""

    # Nanoseconds since the epoch. FastF1 merges feeds on this.
    date: np.ndarray
    # Nanoseconds on the session clock. A lap is cut out by this.
    session: np.ndarray
    channels: dict[str, np.ndarray]

    def __len__(self) -> int:
        return int(len(self.date))


def extract_telemetry(session: Any) -> SessionTelemetry:
    """Full-resolution telemetry for every lap of a loaded FastF1 session that has any."""
    laps = _frame(session, "laps")
    if len(laps) == 0 or not {"DriverNumber", "Driver", "LapNumber", "LapStartTime", "Time"} <= set(laps.columns):
        return SessionTelemetry({})
    car_data = _mapping(session, "car_data")
    position_data = _mapping(session, "pos_data")
    clock_zero = _clock_zero(session)
    if clock_zero is None:
        return SessionTelemetry({})

    starts = laps["LapStartTime"].to_numpy(dtype="timedelta64[ns]")
    ends = laps["Time"].to_numpy(dtype="timedelta64[ns]")
    known = ~(np.isnat(starts) | np.isnat(ends))
    start_ns = starts.astype("int64")
    end_ns = ends.astype("int64")
    numbers = laps["DriverNumber"].astype(str).to_numpy()
    codes = laps["Driver"].to_numpy()
    lap_numbers = pd.to_numeric(laps["LapNumber"], errors="coerce").to_numpy(dtype=float)

    feeds: dict[str, tuple[_Feed | None, _Feed | None, np.ndarray | None]] = {}
    found: dict[tuple[str, int], LapSamples] = {}
    for row in range(len(laps)):
        code = str(codes[row] or "").strip().upper() if _present(codes[row]) else ""
        if not code or not known[row] or not np.isfinite(lap_numbers[row]) or lap_numbers[row] <= 0:
            continue
        key = (code, int(lap_numbers[row]))
        if key in found or end_ns[row] <= start_ns[row]:
            continue
        number = numbers[row]
        if number not in feeds:
            position = _position_feed(position_data.get(number), clock_zero)
            feeds[number] = (
                _car_feed(car_data.get(number), clock_zero),
                position,
                position.session / _NS_PER_SECOND if position is not None else None,
            )
        car, position, position_seconds = feeds[number]
        if car is None:
            continue
        # The test that decides whether a lap counts as having position data
        # when coverage is measured.
        located = position is not None and lap_is_usable(
            position_seconds, start_ns[row] / _NS_PER_SECOND, end_ns[row] / _NS_PER_SECOND
        )
        samples = _lap_samples(car, position if located else None, int(start_ns[row]), int(end_ns[row]), clock_zero)
        if samples is None and located:
            samples = _lap_samples(car, None, int(start_ns[row]), int(end_ns[row]), clock_zero)
        if samples is None:
            continue
        found[key] = LapSamples(
            driver_code=code,
            lap_number=key[1],
            start_ms=_round_ms(int(start_ns[row])),
            **samples,
        )
    return SessionTelemetry(found)


def thinned_indexes(count: int, limit: int = MAX_PUBLISHED_SAMPLES_PER_LAP) -> np.ndarray:
    """Which of ``count`` samples to publish: at most ``limit``, evenly spread, both ends kept.

    Integer arithmetic throughout, so the choice is the same on every platform.
    """
    if count <= 0 or limit <= 0:
        return np.zeros(0, dtype=np.int64)
    if count <= limit:
        return np.arange(count, dtype=np.int64)
    if limit == 1:
        return np.zeros(1, dtype=np.int64)
    steps = np.arange(limit, dtype=np.int64)
    # round(step * (count - 1) / (limit - 1)), halves rounded up. Strictly
    # increasing, because count > limit makes each step more than one sample.
    return (2 * steps * (count - 1) + (limit - 1)) // (2 * (limit - 1))


def _lap_samples(
    car: _Feed, position: _Feed | None, start: int, end: int, clock_zero: int
) -> dict[str, Any] | None:
    """What ``Lap.get_telemetry`` returns for the lap from ``start`` to ``end``.

    Times are nanoseconds on the session clock. Returns ``None`` when the car
    data cannot carry a lap, or when ``position`` was given and cannot.
    """
    cut = _padded_cut(car.session, start, end)
    if cut is None or cut[1] - cut[0] < _MIN_SPLINE_POINTS:
        return None
    first, last = cut
    car_dates = car.date[first:last]
    # Distance since the first sample, as Telemetry.integrate_distance has it:
    # each sample adds its own speed times the time since the one before. The
    # first, which is the padding before the lap, counts from the lap's start
    # and so starts the lap a fraction of a metre below zero.
    seconds = (car.session[first:last] - start) / _NS_PER_SECOND
    elapsed = np.diff(seconds, prepend=0.0)
    # FastF1 takes this one value from a pandas Timedelta, whose total_seconds
    # is a unit in the last place away from the array's for a negative time
    # (-0.158 s comes out as -0.15800000000000003). Following it costs nothing
    # and keeps every distance identical to FastF1's, not merely close.
    elapsed[0] = pd.Timedelta(int(car.session[first] - start), unit="ns").total_seconds()
    distance = np.cumsum(car.channels["Speed"][first:last] / 3.6 * elapsed)

    if position is None:
        dates = car_dates
        located = None
    else:
        position_cut = _padded_cut(position.session, start, end, within=_MAX_GAP_NS)
        if position_cut is None or position_cut[1] - position_cut[0] < _MIN_SPLINE_POINTS:
            return None
        position_dates = position.date[position_cut[0]:position_cut[1]]
        dates = np.union1d(car_dates, position_dates)
        located = {
            name: _fill_quadratic(dates, _spread(dates, position_dates, position.channels[name][position_cut[0]:position_cut[1]]))
            for name in ("X", "Y")
        }

    continuous = {
        name: _fill_linear(dates, _spread(dates, car_dates, car.channels[name][first:last]))
        for name in ("Speed", "RPM", "Throttle")
    }
    lap_distance = _fill_quadratic(dates, _spread(dates, car_dates, distance))
    held = np.clip(np.searchsorted(car_dates, dates, side="right") - 1, 0, None)
    discrete = {name: car.channels[name][first:last][held] for name in ("nGear", "Brake", "DRS")}

    # The lap's own first and last sample: Telemetry.slice_by_time with
    # interpolate_edges, which merges two empty rows in and fills them from
    # everything merged so far.
    edges = np.array([start + clock_zero, end + clock_zero], dtype=np.int64)
    with_edges = np.union1d(dates, edges)
    continuous = {
        name: _fill_linear(with_edges, _spread(with_edges, dates, values)) for name, values in continuous.items()
    }
    lap_distance = _fill_quadratic(with_edges, _spread(with_edges, dates, lap_distance))
    if located is not None:
        # Outside the samples the spline was drawn through it is a guess.
        beyond = (with_edges < position_dates[0]) | (with_edges > position_dates[-1])
        located = {
            name: np.where(beyond, np.nan, _fill_quadratic(with_edges, _spread(with_edges, dates, values)))
            for name, values in located.items()
        }
    held = np.clip(np.searchsorted(dates, with_edges, side="right") - 1, 0, None)
    discrete = {name: values[held] for name, values in discrete.items()}

    on_clock = with_edges - clock_zero
    # Distance is unknown before the first car sample, which can only be the
    # lap's own first sample when the car data starts inside the lap. The lap
    # then begins where its data does.
    inside = (on_clock >= start) & (on_clock <= end) & ~np.isnan(lap_distance)
    if int(inside.sum()) < _MIN_SPLINE_POINTS:
        return None
    return {
        "time_ms": _round_ms(on_clock[inside] - start),
        "distance_m": lap_distance[inside],
        "speed_kph": continuous["Speed"][inside],
        "throttle_pct": continuous["Throttle"][inside],
        "rpm": continuous["RPM"][inside],
        "gear": discrete["nGear"][inside],
        "brake": discrete["Brake"][inside],
        "drs": discrete["DRS"][inside],
        "x": located["X"][inside] if located is not None else None,
        "y": located["Y"][inside] if located is not None else None,
    }


def _padded_cut(times: np.ndarray, start: int, end: int, within: int | None = None) -> tuple[int, int] | None:
    """The slice of sorted ``times`` within the lap, with one sample either side.

    ``Telemetry.slice_by_mask`` with ``pad=1``. ``None`` when no sample falls
    inside the lap. With ``within``, a sample of padding is taken only if it
    is that close to the lap's own nearest sample: one from the far side of an
    outage is no neighbour, and a spline drawn through it bends every sample
    near it.
    """
    first = int(np.searchsorted(times, start, side="left"))
    last = int(np.searchsorted(times, end, side="right"))
    if last <= first:
        return None
    before = first > 0 and (within is None or times[first] - times[first - 1] <= within)
    after = last < len(times) and (within is None or times[last] - times[last - 1] <= within)
    return first - int(before), last + int(after)


def _spread(dates: np.ndarray, own_dates: np.ndarray, values: np.ndarray) -> np.ndarray:
    """``values`` placed at their own timestamps among ``dates``, with NaN everywhere else."""
    spread = np.full(len(dates), np.nan)
    spread[np.searchsorted(dates, own_dates)] = values
    return spread


def _fill_linear(dates: np.ndarray, values: np.ndarray) -> np.ndarray:
    """``Series.interpolate(method="index", limit_direction="both")``."""
    known = ~np.isnan(values)
    if known.all() or not known.any():
        return values
    missing = ~known
    values[missing] = np.interp(dates[missing], dates[known], values[known])
    return values


def _fill_quadratic(dates: np.ndarray, values: np.ndarray) -> np.ndarray:
    """``Series.interpolate(method="quadratic", fill_value="extrapolate")``.

    pandas fills forwards only, so what comes before the first known value
    stays unknown. That is the padding before the lap, which is dropped.
    """
    known = ~np.isnan(values)
    if known.all() or known.sum() < _MIN_SPLINE_POINTS:
        return values
    missing = ~known
    spline = interp1d(dates[known], values[known], kind="quadratic", fill_value="extrapolate", bounds_error=False)
    values[missing] = spline(dates[missing])
    values[: int(np.argmax(known))] = np.nan
    return values


def _car_feed(frame: Any, clock_zero: int) -> _Feed | None:
    columns = ("Speed", "RPM", "Throttle", "nGear", "Brake", "DRS")
    if frame is None or len(frame) == 0 or not {"Date", *columns} <= set(frame.columns):
        return None
    channels = {
        "Speed": frame["Speed"].to_numpy(dtype=float),
        "RPM": frame["RPM"].to_numpy(dtype=float),
        "Throttle": frame["Throttle"].to_numpy(dtype=float),
        "nGear": pd.to_numeric(frame["nGear"], errors="coerce").fillna(0).to_numpy(dtype=np.int64),
        "Brake": frame["Brake"].fillna(False).to_numpy(dtype=bool),
        "DRS": pd.to_numeric(frame["DRS"], errors="coerce").fillna(0).to_numpy(dtype=np.int64),
    }
    # A sample with no speed cannot be integrated into distance.
    usable = ~np.isnan(channels["Speed"])
    return _feed(frame["Date"], channels, usable, clock_zero)


def _position_feed(frame: Any, clock_zero: int) -> _Feed | None:
    if frame is None or len(frame) == 0 or not {"Date", "X", "Y"} <= set(frame.columns):
        return None
    channels = {"X": frame["X"].to_numpy(dtype=float), "Y": frame["Y"].to_numpy(dtype=float)}
    present = ~(np.isnan(channels["X"]) | np.isnan(channels["Y"]))
    located = (channels["X"] != 0) | (channels["Y"] != 0)
    return _feed(frame["Date"], channels, present & located, clock_zero)


def _feed(dates: pd.Series, channels: dict[str, np.ndarray], usable: np.ndarray, clock_zero: int) -> _Feed | None:
    date = dates.to_numpy(dtype="datetime64[ns]")
    usable = usable & ~np.isnat(date)
    date = date.astype("int64")[usable]
    if len(date) == 0:
        return None
    # F1 sends each feed in time order with one sample per timestamp. Should
    # it ever not, the first sample at a timestamp is the one kept.
    date, order = np.unique(date, return_index=True)
    return _Feed(
        date=date,
        session=date - clock_zero,
        channels={name: values[usable][order] for name, values in channels.items()},
    )


def _round_ms(nanoseconds: Any) -> Any:
    """Nanoseconds to whole milliseconds, rounded half up. F1's timestamps are whole milliseconds."""
    if isinstance(nanoseconds, np.ndarray):
        return (nanoseconds + _NS_PER_MS // 2) // _NS_PER_MS
    return (int(nanoseconds) + _NS_PER_MS // 2) // _NS_PER_MS


def _clock_zero(session: Any) -> int | None:
    """When the session clock read zero, in nanoseconds since the epoch."""
    try:
        moment = pd.Timestamp(session.t0_date)
    except Exception:
        return None
    return None if pd.isna(moment) else int(moment.value)


def _frame(session: Any, attribute: str) -> pd.DataFrame:
    try:
        value = getattr(session, attribute)
    except Exception:
        return pd.DataFrame()
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _mapping(session: Any, attribute: str) -> dict[str, Any]:
    try:
        value = getattr(session, attribute)
    except Exception:
        return {}
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _present(value: Any) -> bool:
    if value is None:
        return False
    try:
        return not bool(pd.isna(value))
    except (TypeError, ValueError):
        return True


def nan_as_none(values: np.ndarray) -> list[float | None]:
    """A float array as a list, with ``None`` where it holds NaN."""
    listed = values.tolist()
    if not np.isnan(values).any():
        return listed
    return [None if value != value else value for value in listed]
