"""The current calendar, read fresh on every run.

Round numbers are looked up here and never stored as identity: a published
session is matched to its calendar entry by type and start time
(docs/architecture-review-findings.md, AR-20; section 6, rule 5). FastF1 takes
the schedule from its own file on GitHub and falls back to Jolpica, so this
needs nothing from F1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from f1data.identity import SESSION_TYPE_BY_NAME, SessionIdentity, format_utc


@dataclass(frozen=True)
class ScheduledSession:
    year: int
    round: int
    meeting_name: str
    meeting_official_name: str | None
    country: str | None
    location: str | None
    meeting_date: str | None
    meeting_format: str | None
    session_type: str
    session_name: str
    start_time_utc: str | None

    @property
    def start_time(self) -> datetime | None:
        if not self.start_time_utc:
            return None
        return datetime.fromisoformat(self.start_time_utc.replace("Z", "+00:00"))


def load_schedule(fastf1: Any, year: int) -> list[ScheduledSession]:
    """Every session of every race weekend in ``year``, in calendar order."""
    schedule = fastf1.get_event_schedule(year, include_testing=False)
    sessions: list[ScheduledSession] = []
    for _, event in schedule.iterrows():
        round_number = _int(event.get("RoundNumber"))
        name = _text(event.get("EventName"))
        if not round_number or not name:
            continue
        for index in range(1, 6):
            session_name = _text(event.get(f"Session{index}"))
            session_type = SESSION_TYPE_BY_NAME.get((session_name or "").lower())
            if not session_name or not session_type:
                continue
            sessions.append(
                ScheduledSession(
                    year=int(year),
                    round=round_number,
                    meeting_name=name,
                    meeting_official_name=_text(event.get("OfficialEventName")),
                    country=_text(event.get("Country")),
                    location=_text(event.get("Location")),
                    meeting_date=_date(event.get("EventDate")),
                    meeting_format=_text(event.get("EventFormat")),
                    session_type=session_type,
                    session_name=session_name,
                    start_time_utc=_utc(event.get(f"Session{index}DateUtc")),
                )
            )
    return sessions


def find_scheduled_session(
    schedule: list[ScheduledSession], identity: SessionIdentity
) -> ScheduledSession | None:
    """The calendar entry for a fetched session, whatever its round is now."""
    matches = [
        entry
        for entry in schedule
        if entry.start_time is not None
        and identity.matches_schedule_entry(entry.year, entry.session_type, entry.start_time)
    ]
    if not matches:
        return None
    return min(matches, key=lambda entry: abs((entry.start_time - identity.start_time).total_seconds()))


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(value != value)  # NaN and NaT are the only values unequal to themselves
    except (TypeError, ValueError):
        return False


def _text(value: Any) -> str | None:
    if _missing(value):
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    if _missing(value):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _date(value: Any) -> str | None:
    if _missing(value):
        return None
    return value.date().isoformat() if hasattr(value, "date") else str(value)[:10]


def _utc(value: Any) -> str | None:
    if _missing(value):
        return None
    moment = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    return format_utc(moment) if isinstance(moment, datetime) else None
