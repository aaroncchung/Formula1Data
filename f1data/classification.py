"""The official result of a race or sprint, from Jolpica.

Fetched without a cache on every run, because a classification can change
after the session: the committed Monaco result has a driver third whom Jolpica
has seventh (docs/architecture-review-findings.md, AR-15). The fingerprint of
what was used is stored in the session's pointer, and a session is rebuilt when
it no longer matches (section 6, rule 3).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

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
    """Ask Jolpica for the result of a race (``R``) or sprint (``S``), uncached."""
    code = session_type.upper()
    if not is_classified_session(code):
        raise ValueError(f"Session type {session_type!r} has no classification")
    ergast = fastf1.ergast.Ergast(result_type="pandas", auto_cast=True)
    frames = None
    for attempt, pause in enumerate((*_RETRY_PAUSES_SECONDS, None)):
        try:
            with fastf1.Cache.disabled():
                if code == "R":
                    response = ergast.get_race_results(season=year, round=round_number)
                else:
                    response = ergast.get_sprint_results(season=year, round=round_number)
            frames = getattr(response, "content", None) or []
            break
        except Exception as exc:
            # Jolpica allows four requests a second and answers 429 beyond
            # that; a batch of sessions can reach it. Wait and ask again.
            if pause is None:
                raise ClassificationUnavailable(
                    f"Jolpica did not return a classification for {year} round {round_number} {code} "
                    f"after {attempt + 1} attempts"
                ) from exc
            sleep(pause)
    if not frames or frames[0].empty:
        raise ClassificationMissing(
            f"Jolpica has no classification for {year} round {round_number} {code}"
        )
    frame = frames[0]
    rows = [
        {column: _plain(row.get(column)) for column in _RESULT_COLUMNS if column in frame.columns}
        for _, row in frame.iterrows()
    ]
    return Classification(
        rows=rows, fingerprint=fingerprint(rows), frame=frame, race_date=_race_date(response)
    )


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


def fingerprint(rows: list[dict[str, Any]]) -> str:
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def merge_into_session(session: Any, classification: Classification) -> None:
    """Replace the result columns of a loaded FastF1 session with Jolpica's.

    FastF1 fills these from whatever it fetched when the session was loaded,
    which for a build is the archive. The classification is the one input a
    build takes from today, and it is the whole answer: a driver it does not
    list is not classified, whatever the session was loaded with. Such a
    driver stays in the table, since the timing may still hold their laps,
    with no position, points, status or lap count to their name.
    """
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
