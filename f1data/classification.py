"""The official result of a race or sprint, from Jolpica.

Fetched without a cache on every run, because a classification can change
after the session: the committed Monaco result has a driver third whom Jolpica
has seventh (docs/architecture-review-findings.md, AR-15). The fingerprint of
what was used is stored in the session's pointer, and a session is rebuilt when
it no longer matches (section 6, rule 3).

Everything a build takes from Jolpica is fetched here, before the build, and
is in that fingerprint. FastF1 would otherwise fetch two things itself while
it loads a session: the result, and each driver's time for the first lap of a
race, which F1's timing does not give. A build that let it would depend on
what Jolpica answered at that moment, with nothing in the pointer to say so.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from f1data.coverage import RACE_LIKE_SESSION_TYPES

# Jolpica's column and the FastF1 result column it replaces. Every column that
# reaches a build is in the fingerprint, so that a correction to any of them,
# a constructor's name as much as a position, rebuilds the session.
_RESULT_COLUMNS = {
    "number": "DriverNumber",
    "driverCode": "Abbreviation",
    "givenName": "FirstName",
    "familyName": "LastName",
    "constructorName": "TeamName",
    "position": "Position",
    "positionText": "ClassifiedPosition",
    "grid": "GridPosition",
    "status": "Status",
    "points": "Points",
    "totalRaceTime": "Time",
    "laps": "Laps",
}

# The columns that say how a driver was classified, as opposed to who the
# driver is, each with what it holds for a driver who was not classified.
_NOT_CLASSIFIED = {
    "Position": float("nan"),
    "ClassifiedPosition": "",
    "GridPosition": float("nan"),
    "Status": "",
    "Points": float("nan"),
    "Time": None,
    "Laps": float("nan"),
}


_RETRY_PAUSES_SECONDS = (2.0, 6.0)


class ClassificationUnavailable(RuntimeError):
    """Jolpica did not answer. Nothing is known about the result."""


class ClassificationMissing(ClassificationUnavailable):
    """Jolpica answered, and has no result for the session."""


@dataclass(frozen=True)
class Classification:
    rows: list[dict[str, Any]]
    fingerprint: str
    # As Jolpica returned it, for merging into a FastF1 session's results.
    frame: Any = field(default=None, compare=False, repr=False)
    # The date of the race this is the result of. A sprint's is its Sunday race.
    race_date: date | None = field(default=None, compare=False)
    # Each driver's time for the first lap, in milliseconds, by driver number.
    # Races only, and empty until Jolpica has lap times for the race.
    first_lap_ms: dict[str, int] = field(default_factory=dict)

    @property
    def laps_by_number(self) -> dict[str, int]:
        """Driver number to classified laps, for judging a snapshot's timing."""
        return {
            str(row["number"]): int(row["laps"])
            for row in self.rows
            if row.get("number") is not None and row.get("laps") is not None
        }


def is_classified_session(session_type: str) -> bool:
    return session_type.upper() in RACE_LIKE_SESSION_TYPES


def fetch_classification(
    fastf1: Any, year: int, round_number: int, session_type: str, sleep: Any = time.sleep
) -> Classification:
    """Ask Jolpica for everything a build takes from it, uncached.

    That is the result of the race (``R``) or sprint (``S``), and for a race
    each driver's time for the first lap.
    """
    code = session_type.upper()
    ergast = fastf1.ergast.Ergast(result_type="pandas", auto_cast=True)
    response, frame, rows = _result(fastf1, ergast, year, round_number, code, sleep)
    first_lap_ms: dict[str, int] = {}
    if code == "R":
        laps = _ask(
            fastf1,
            lambda: ergast.get_lap_times(season=year, round=round_number, lap_number=1),
            f"first-lap times for {year} round {round_number}",
            sleep,
        )
        first_lap_ms = _first_lap_ms(laps, frame)
    return Classification(
        rows=rows,
        fingerprint=fingerprint(rows, first_lap_ms),
        frame=frame,
        race_date=_race_date(response),
        first_lap_ms=first_lap_ms,
    )


def fetch_classified_laps(
    fastf1: Any, year: int, round_number: int, session_type: str, sleep: Any = time.sleep
) -> dict[str, int]:
    """Driver number to the laps Jolpica classifies the driver with, uncached.

    For judging a snapshot. It is the one request of the two that says how
    many laps a driver should have, and the fetch planner asks it of a
    session on every run: it has no use for first-lap times.
    """
    ergast = fastf1.ergast.Ergast(result_type="pandas", auto_cast=True)
    _, _, rows = _result(fastf1, ergast, year, round_number, session_type.upper(), sleep)
    return Classification(rows=rows, fingerprint="").laps_by_number


def _result(
    fastf1: Any, ergast: Any, year: int, round_number: int, code: str, sleep: Any
) -> tuple[Any, Any, list[dict[str, Any]]]:
    """Jolpica's answer, its table, and the table as plain rows."""
    if not is_classified_session(code):
        raise ValueError(f"Session type {code!r} has no classification")

    def results() -> Any:
        if code == "R":
            return ergast.get_race_results(season=year, round=round_number)
        return ergast.get_sprint_results(season=year, round=round_number)

    response = _ask(fastf1, results, f"a classification for {year} round {round_number} {code}", sleep)
    frames = getattr(response, "content", None) or []
    if not frames or frames[0].empty:
        raise ClassificationMissing(
            f"Jolpica has no classification for {year} round {round_number} {code}"
        )
    frame = frames[0]
    rows = [
        {column: _plain(row.get(column)) for column in _RESULT_COLUMNS if column in frame.columns}
        for _, row in frame.iterrows()
    ]
    return response, frame, rows


def _ask(fastf1: Any, request: Any, what: str, sleep: Any) -> Any:
    """Make one request of Jolpica, uncached, and ask again if it fails."""
    for attempt, pause in enumerate((*_RETRY_PAUSES_SECONDS, None)):
        try:
            with fastf1.Cache.disabled():
                return request()
        except Exception as exc:
            # Jolpica allows four requests a second and answers 429 beyond
            # that; a batch of sessions can reach it. Wait and ask again.
            if pause is None:
                raise ClassificationUnavailable(
                    f"Jolpica did not return {what} after {attempt + 1} attempts"
                ) from exc
            sleep(pause)
    raise AssertionError("unreachable")


def _first_lap_ms(response: Any, results: Any) -> dict[str, int]:
    """Driver number to first-lap time. Empty when Jolpica has no lap times yet.

    Jolpica names the driver of a lap by its own id, and the result is where
    that id is tied to a number.
    """
    frames = getattr(response, "content", None) or []
    if not frames or frames[0].empty or not {"driverId", "number"} <= set(results.columns):
        return {}
    laps = frames[0]
    if not {"driverId", "time"} <= set(laps.columns):
        return {}
    numbers = {str(row["driverId"]): str(_plain(row["number"])) for _, row in results.iterrows()}
    times: dict[str, int] = {}
    for _, row in laps.iterrows():
        number = numbers.get(str(row["driverId"]))
        milliseconds = _plain(row["time"])
        if number is not None and isinstance(milliseconds, int):
            times[number] = milliseconds
    return dict(sorted(times.items()))


def _race_date(response: Any) -> date | None:
    description = getattr(response, "description", None)
    try:
        value = description["raceDate"].iloc[0]
    except Exception:
        return None
    try:
        return value.date() if hasattr(value, "date") else date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def fingerprint(rows: list[dict[str, Any]], first_lap_ms: dict[str, int] | None = None) -> str:
    """Of everything a build takes from Jolpica: the result and the first-lap times."""
    canonical = json.dumps(
        {"results": rows, "first_lap_ms": first_lap_ms or {}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def merge_into_session(session: Any, classification: Classification) -> None:
    """Put Jolpica's result, and its first-lap times, into a loaded FastF1 session.

    A build loads its session from the archive with Jolpica out of reach, so
    the result table holds F1's driver list and little else. The
    classification is the one input a build takes from today, and it is the
    whole answer: a driver it does not list is not classified, whatever the
    session was loaded with. Such a driver stays in the table, since the
    timing may still hold their laps, with no position, points, status or lap
    count to their name.
    """
    _set_first_lap_times(session, classification.first_lap_ms)
    rename = _RESULT_COLUMNS
    official = classification.frame
    official = official.rename(
        columns={key: value for key, value in rename.items() if key in official.columns}
    ).copy()
    if "DriverNumber" not in official or official.empty:
        return
    official = official[[column for column in rename.values() if column in official.columns]]
    official["DriverNumber"] = official["DriverNumber"].astype(str)
    if "FirstName" in official and "LastName" in official:
        official["FullName"] = official["FirstName"] + " " + official["LastName"]
    official = official.set_index("DriverNumber", drop=False)

    current = session.results.copy()
    if "DriverNumber" in current:
        current["DriverNumber"] = current["DriverNumber"].astype(str)
        current = current.set_index("DriverNumber", drop=False)
    else:
        current.index = current.index.astype(str)
    combined = current.reindex(current.index.union(official.index))
    omitted = combined.index.difference(official.index)
    for column, nothing in _NOT_CLASSIFIED.items():
        if column in combined and len(omitted):
            # Otherwise a result from the archive would be published under
            # the fingerprint of a result that no longer contains it.
            if isinstance(nothing, str) and combined[column].dtype.kind in "fiu":
                # A text column that loaded with nothing in it is numeric.
                combined[column] = combined[column].astype(object)
            combined.loc[omitted, column] = nothing
    for column in official.columns:
        if column not in combined:
            combined[column] = None
        combined.loc[official.index, column] = official[column]
    session._results = combined.sort_values("Position")


def _set_first_lap_times(session: Any, first_lap_ms: dict[str, int]) -> None:
    """What FastF1's ``_add_first_lap_time_from_ergast`` does, from times fetched beforehand."""
    laps = getattr(session, "laps", None)
    if not first_lap_ms or laps is None or not {"LapNumber", "DriverNumber", "LapTime"} <= set(laps.columns):
        return
    first = laps["LapNumber"] == 1
    numbers = laps["DriverNumber"].astype(str)
    for number, milliseconds in first_lap_ms.items():
        laps.loc[first & (numbers == number), "LapTime"] = pd.Timedelta(milliseconds=milliseconds)


def _plain(value: Any) -> Any:
    """A JSON value that prints the same on every platform and pandas version."""
    if value is None:
        return None
    try:
        if value != value:  # NaN, NaT
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "total_seconds"):
        return round(value.total_seconds() * 1000)
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)
