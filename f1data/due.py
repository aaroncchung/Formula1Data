"""Which sessions the fetch stage should ask F1 for on this run.

The job is idempotent: it is given the calendar and what the archive already
holds, and it works out what is still owed. A machine that was off when a
session finished catches up on its next run, because F1's archive keeps past
sessions (docs/architecture-review-findings.md, section 8, decision 2).

A session is fetched when it is in scope, has finished, and the archive has no
snapshot of it that meets every bar. One that fell short is fetched again, from
an empty cache, at intervals until the retry window closes (section 6, rule 6).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from f1data.archive import RETRY_WINDOW, Snapshot
from f1data.coverage import refetch_could_help
from f1data.identity import parse_utc
from f1data.schedule import ScheduledSession

# Decision 5: races and sprints first. Qualifying and practice follow once they
# have a view of their own.
IN_SCOPE_SESSION_TYPES = frozenset({"R", "S"})

# From a session's scheduled start to when its feeds are expected to be in
# F1's archive in full: the session itself, a margin for a red flag, and the
# time the archive takes to settle.
AVAILABLE_AFTER = {"R": timedelta(hours=4), "S": timedelta(hours=2)}
DEFAULT_AVAILABLE_AFTER = timedelta(hours=3)

# Between two fetches of a session that is still short of a bar.
RETRY_INTERVAL = timedelta(hours=6)


@dataclass(frozen=True)
class FetchPlan:
    session: ScheduledSession
    reason: str


def plan_fetches(
    schedule: list[ScheduledSession],
    snapshots: list[Snapshot],
    now: datetime,
    classified_laps: Callable[[ScheduledSession], dict[str, int] | None] = lambda session: None,
    session_types: frozenset[str] = IN_SCOPE_SESSION_TYPES,
) -> list[FetchPlan]:
    """The sessions to fetch now, oldest first, each with the reason.

    ``classified_laps`` is asked only for a session whose snapshots all fall
    short, to judge them against the classification of today: a snapshot taken
    before Jolpica had the result cannot tell that its timing is cut short.
    """
    now = now.astimezone(timezone.utc)
    plans: list[FetchPlan] = []
    for session in sorted(schedule, key=lambda item: item.start_time_utc or ""):
        start = session.start_time
        if session.session_type not in session_types or start is None:
            continue
        if now < start + AVAILABLE_AFTER.get(session.session_type, DEFAULT_AVAILABLE_AFTER):
            continue
        mine = [
            snapshot
            for snapshot in snapshots
            if snapshot.identity.matches_schedule_entry(session.year, session.session_type, start)
        ]
        if not mine:
            plans.append(FetchPlan(session, "not in the archive"))
            continue
        if any(snapshot.complete for snapshot in mine):
            continue

        laps = classified_laps(session)
        if laps:
            mine = [snapshot.judged_against(laps) for snapshot in mine]
            if any(snapshot.complete for snapshot in mine):
                continue
        if not any(refetch_could_help(snapshot.shortfalls()) for snapshot in mine):
            # Only the classification is missing, and that is not F1's to give.
            continue

        fetched = [parse_utc(snapshot.fetched_at) for snapshot in mine]
        if now >= min(fetched) + RETRY_WINDOW:
            continue
        if now < max(fetched) + RETRY_INTERVAL:
            continue
        best = max(mine, key=Snapshot.rank)
        short = sorted({shortfall.bar for shortfall in best.shortfalls()})
        plans.append(FetchPlan(session, f"best of {len(mine)} snapshot(s) is short on {', '.join(short)}"))
    return plans
