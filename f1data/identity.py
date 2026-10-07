"""Who a session is, independent of where it sits in the calendar.

A session used to be ``{year}-{round}-{type}``. Round numbers move when the
calendar changes: on 2026-10-05 round 16 became a different race and every
later round shifted by one (docs/architecture-review-findings.md, AR-20). F1's
own session key does not move, so it names the session in storage, and year,
round and names are attributes looked up from the current schedule.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

SESSION_TYPE_BY_NAME = {
    "practice 1": "FP1",
    "practice 2": "FP2",
    "practice 3": "FP3",
    "qualifying": "Q",
    "sprint qualifying": "SQ",
    "sprint shootout": "SQ",
    "sprint": "S",
    "race": "R",
}
SESSION_TYPES = frozenset(SESSION_TYPE_BY_NAME.values())

# Two sessions of one type are never this close together, and a schedule
# correction to a session that has already run is far smaller.
START_TIME_TOLERANCE = timedelta(hours=12)


class IdentityError(ValueError):
    """F1's session information is missing a field that identity depends on."""


# FastF1's own code for the 2023 sprint shootout, which is this code's SQ.
_OTHER_CODES = {"SS": "SQ"}
# The one season in which F1 called the sprint itself "Sprint Qualifying".
# From 2024 that name is the qualifying session for the sprint.
_SPRINT_WAS_CALLED_SPRINT_QUALIFYING = 2021


def session_type_code(value: Any, year: int | None = None) -> str:
    """Normalise a session name or code (``Race``, ``r``, ``FP1``) to its code.

    ``year`` is the season the name is F1's own for, when it is: one name
    has meant two kinds of session.
    """
    raw = str(value or "").strip()
    code = SESSION_TYPE_BY_NAME.get(raw.lower(), raw.upper())
    code = _OTHER_CODES.get(code, code)
    if code not in SESSION_TYPES:
        raise ValueError(f"Unknown session type: {value!r}")
    if code == "SQ" and year == _SPRINT_WAS_CALLED_SPRINT_QUALIFYING and raw.lower() == "sprint qualifying":
        return "S"
    return code


@dataclass(frozen=True)
class SessionIdentity:
    session_key: int
    meeting_key: int
    year: int
    session_type: str
    session_name: str
    start_time_utc: str
    meeting_name: str
    meeting_official_name: str | None
    location: str | None
    country: str | None
    circuit_key: int | None
    circuit_name: str | None
    # F1's archive path, e.g. ``2026/2026-06-28_Austrian_Grand_Prix/2026-06-28_Race/``.
    # FastF1 files its cache under the same path.
    archive_path: str
    # The round when the session was fetched. Informational: the current
    # schedule decides the round a page shows.
    round_at_fetch: int | None = None

    @property
    def start_time(self) -> datetime:
        return parse_utc(self.start_time_utc)

    def matches_schedule_entry(self, year: int, session_type: str, start_time: datetime) -> bool:
        """Whether a schedule entry is this session, without using the round."""
        if year != self.year or session_type_code(session_type) != self.session_type:
            return False
        return abs(_as_utc(start_time) - self.start_time) <= START_TIME_TOLERANCE

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "SessionIdentity":
        known = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in payload.items() if key in known})


def identity_from_fastf1(session: Any) -> SessionIdentity:
    """Read the identity of a loaded FastF1 session from F1's session information."""
    try:
        info = session.session_info
    except Exception as exc:
        raise IdentityError("F1's session information did not load") from exc
    meeting = info.get("Meeting") or {}
    session_key = info.get("Key")
    meeting_key = meeting.get("Key")
    archive_path = str(info.get("Path") or "")
    if not session_key or not meeting_key or not archive_path:
        raise IdentityError("F1's session information has no session key, meeting key or path")

    event = session.event
    start = _as_utc(session.date.to_pydatetime() if hasattr(session.date, "to_pydatetime") else session.date)
    circuit = meeting.get("Circuit") or {}
    country = meeting.get("Country") or {}
    round_number = _int_or_none(_get(event, "RoundNumber"))
    return SessionIdentity(
        session_key=int(session_key),
        meeting_key=int(meeting_key),
        year=start.year,
        session_type=session_type_code(info.get("Name") or session.name, year=start.year),
        session_name=str(info.get("Name") or session.name),
        start_time_utc=format_utc(start),
        meeting_name=str(meeting.get("Name") or _get(event, "EventName") or ""),
        meeting_official_name=_str_or_none(meeting.get("OfficialName")),
        location=_str_or_none(meeting.get("Location")),
        country=_str_or_none(country.get("Name")),
        circuit_key=_int_or_none(circuit.get("Key")),
        circuit_name=_str_or_none(circuit.get("ShortName")),
        archive_path=archive_path if archive_path.endswith("/") else f"{archive_path}/",
        round_at_fetch=round_number if round_number else None,
    )


def archived_start_time(session: Any) -> datetime | None:
    """When the session started, by F1's own session information.

    A loaded FastF1 session takes its date from the calendar row it was made
    from. This is the other source: what F1 filed with the feeds. ``None``
    when the session information does not say.
    """
    try:
        info = session.session_info
        start, offset = info["StartDate"], info["GmtOffset"]
        return _as_utc((start - offset).replace(tzinfo=None))
    except Exception:
        return None


def format_utc(value: datetime) -> str:
    return _as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _as_utc(value: datetime) -> datetime:
    # FastF1 gives session dates as naive UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _get(obj: Any, key: str) -> Any:
    try:
        return obj[key]
    except Exception:
        return getattr(obj, key, None)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
