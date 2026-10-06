"""Which sessions the fetch stage should ask F1 for on this run.

The job is idempotent: it is given the calendar and what the archive already
holds, and it works out what is still owed. A machine that was off when a
session finished catches up on its next run, because F1's archive keeps past
sessions (docs/architecture-review-findings.md, section 8, decision 2).

Fetching stops only for a session the archive holds in full (section 6,
rule 3). One that fell short is fetched again, from an empty cache: every few
hours while its retry window is open, and rarely after that, since F1 does
repair its archive. The one thing that ends the retries of a short session is
F1 answering that it does not hold what is missing.

"In full" is judged here from the archive's record of each snapshot. A build
measures the snapshot it is about to publish and, if the feeds are not what the
record says, corrects the record before it decides anything
(``f1data/archive.py``, ``write_remeasurement``). So the record read here is
the one a build would publish from, and the two cannot disagree for long.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timezone

from f1data.archive import Snapshot
from f1data.coverage import CLASSIFICATION_BAR, refetch_could_help
from f1data.identity import parse_utc
from f1data.policy import (
    AVAILABLE_AFTER,
    CLASSIFICATION_RECHECK_WINDOW,
    DEFAULT_AVAILABLE_AFTER,
    IN_SCOPE_SESSION_TYPES,
    RETRY_INTERVAL,
    RETRY_WINDOW,
    SLOW_RETRY_INTERVAL,
)
from f1data.schedule import ScheduledSession


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
    published_short: Collection[int] = frozenset(),
) -> list[FetchPlan]:
    """The sessions to fetch now, oldest first, each with the reason.

    ``classified_laps`` is not asked for every session. It judges snapshots
    against the classification of today: a snapshot taken before Jolpica had
    the result cannot tell that its timing is cut short, and a correction
    after the race can leave a snapshot that was whole short of the laps now
    classified.

    ``published_short`` holds the keys of the sessions whose pointer says they
    are published short of a bar.
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

        # A snapshot measured before a feed was added says nothing about that
        # feed. The retries, and their window, are counted afresh from the
        # first fetch that looked for it.
        current = [snapshot for snapshot in mine if snapshot.measured_in_full]
        if not current:
            plans.append(FetchPlan(session, "fetched before the measured feeds changed"))
            continue

        # Recent sessions, because a result can still be corrected. And any
        # session with a snapshot fetched before there was a result at all,
        # however old: such a snapshot records only that the classification
        # was missing, and cannot show timing cut short until it is judged.
        # And any session published as short, however old. A build judges
        # against the result of its own day; when a result corrected months
        # later is what left the session short, the pointer says so and
        # nothing in the archive does.
        recent = now - start <= CLASSIFICATION_RECHECK_WINDOW
        unjudged = any(
            shortfall.bar == CLASSIFICATION_BAR
            for snapshot in current
            for shortfall in snapshot.shortfalls()
        )
        short_as_published = any(snapshot.session_key in published_short for snapshot in current)
        if recent or unjudged or short_as_published:
            laps = classified_laps(session)
            if laps:
                current = [snapshot.judged_against(laps) for snapshot in current]
        if any(snapshot.complete for snapshot in current):
            continue
        best = max(current, key=Snapshot.rank)
        if not refetch_could_help(best.shortfalls()):
            # Only the classification is missing, and that is not F1's to give.
            continue

        fetched = [parse_utc(snapshot.fetched_at) for snapshot in current]
        if now < min(fetched) + RETRY_WINDOW:
            interval = RETRY_INTERVAL
        else:
            latest = max(current, key=lambda snapshot: snapshot.fetched_at)
            if latest.missing_only_what_f1_does_not_hold():
                continue
            interval = SLOW_RETRY_INTERVAL
        if now < max(fetched) + interval:
            continue
        short = sorted({shortfall.bar for shortfall in best.shortfalls()})
        plans.append(
            FetchPlan(session, f"best of {len(current)} snapshot(s) is short on {', '.join(short)}")
        )
    return plans
