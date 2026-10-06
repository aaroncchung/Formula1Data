"""Championship standings, from Jolpica.

The site used to add up points over the sessions it had ingested. On
2026-10-05 that was wrong for 12 of 22 drivers: sprints were not ingested, and
a result corrected after a race was never picked up
(docs/architecture-review-findings.md, AR-15). Standings are taken whole from
Jolpica instead, on every run.

They are one object per season that changes in place, so they are written
against the version that was read (section 6, rule 2). A run that lost the
write fetches again and decides again. What it fetched replaces the stored
copy if it differs and is not behind it: a correction within a round is
published, and a slow run cannot move the standings back a round.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from f1data import layout
from f1data.archive import dump_json
from f1data.store import ObjectStore, PreconditionFailed

STANDINGS_SCHEMA_VERSION = 1
MAX_ATTEMPTS = 5
_RETRY_PAUSES_SECONDS = (2.0, 6.0)

_logger = logging.getLogger(__name__)


def fetch_standings(fastf1: Any, year: int, sleep: Any = time.sleep) -> dict[str, Any] | None:
    """The standings of ``year`` as Jolpica has them now, or ``None`` before the first round."""
    ergast = fastf1.ergast.Ergast(result_type="pandas", auto_cast=True)
    drivers = _ask(lambda: ergast.get_driver_standings(season=year), fastf1, sleep)
    constructors = _ask(lambda: ergast.get_constructor_standings(season=year), fastf1, sleep)
    driver_rows, driver_round = _rows(drivers)
    constructor_rows, constructor_round = _rows(constructors)
    if not driver_rows or not constructor_rows or driver_round is None or constructor_round is None:
        return None
    return {
        "schema_version": STANDINGS_SCHEMA_VERSION,
        "format_version": layout.FORMAT_VERSION,
        "year": int(year),
        # The two tables are two requests and can be a round apart for a moment.
        "rounds": {"drivers": driver_round, "constructors": constructor_round},
        "drivers": [
            {
                "position": _plain(row.get("position")),
                "points": _plain(row.get("points")),
                "wins": _plain(row.get("wins")),
                "driver_code": _plain(row.get("driverCode")),
                "driver_number": _plain(row.get("driverNumber")),
                "given_name": _plain(row.get("givenName")),
                "family_name": _plain(row.get("familyName")),
                "constructors": [str(name) for name in (row.get("constructorNames") or [])],
            }
            for row in driver_rows
        ],
        "constructors": [
            {
                "position": _plain(row.get("position")),
                "points": _plain(row.get("points")),
                "wins": _plain(row.get("wins")),
                "constructor_id": _plain(row.get("constructorId")),
                "name": _plain(row.get("constructorName")),
            }
            for row in constructor_rows
        ],
    }


def publish_standings(
    store: ObjectStore,
    year: int,
    fetch: Callable[[int], dict[str, Any] | None],
    max_attempts: int = MAX_ATTEMPTS,
) -> str:
    """Bring the stored standings of ``year`` up to date. Returns what happened:

    ``published``, ``current`` (nothing to change), ``behind`` (what was
    fetched is from an earlier round than what is stored), ``unavailable``
    (Jolpica has none) or ``conflict`` (lost the write every time).
    """
    key = layout.standings_key(year)
    for _ in range(max_attempts):
        # The stored copy is read first, then fetched afresh on every attempt.
        current = store.get(key)
        fetched = fetch(year)
        if fetched is None:
            return "unavailable"
        payload = dump_json(fetched)
        if current is not None:
            if current.data == payload:
                return "current"
            if _is_behind(fetched, json.loads(current.data)):
                return "behind"
        try:
            if current is None:
                store.put(key, payload, if_absent=True)
            else:
                store.put(key, payload, if_match=current.etag)
        except PreconditionFailed:
            _logger.info("Lost the standings write for %s; fetching and deciding again", year)
            continue
        return "published"
    return "conflict"


def _is_behind(fetched: dict[str, Any], stored: dict[str, Any]) -> bool:
    stored_rounds = stored.get("rounds") or {}
    return any(
        int(fetched["rounds"][table]) < int(stored_rounds.get(table) or 0)
        for table in ("drivers", "constructors")
    )


def _ask(request: Callable[[], Any], fastf1: Any, sleep: Any) -> Any:
    for pause in (*_RETRY_PAUSES_SECONDS, None):
        try:
            with fastf1.Cache.disabled():
                return request()
        except Exception:
            # Jolpica answers 429 beyond four requests a second.
            if pause is None:
                raise
            sleep(pause)
    raise AssertionError("unreachable")


def _rows(response: Any) -> tuple[list[dict[str, Any]], int | None]:
    frames = getattr(response, "content", None) or []
    if not frames or frames[0].empty:
        return [], None
    try:
        round_number = int(response.description["round"].iloc[0])
    except Exception:
        return [], None
    return frames[0].to_dict("records"), round_number


def _plain(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)
