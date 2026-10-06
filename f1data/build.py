"""Build a session's artifacts from its archive snapshot.

A build reads the archive, Jolpica and FastF1's schedule file, and nothing from
F1 (docs/architecture-review-findings.md, section 6, rule 4). That is enforced,
not assumed: requests to F1's hosts are refused while a build looks anything
up, so a feed missing from a snapshot stays missing instead of being fetched
behind the archive's back, and a calendar that will not load from its file is
not quietly taken from F1.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from f1data import layout, legacy
from f1data.archive import (
    Snapshot,
    list_snapshots,
    partial_publication_time,
    read_extras,
    restore_snapshot,
    select_snapshot,
)
from f1data.classification import (
    Classification,
    ClassificationUnavailable,
    fetch_classification,
    is_classified_session,
    merge_into_session,
)
from f1data.coverage import measure_coverage
from f1data.fetch import F1_ARCHIVE_HOSTS, fastf1_cache
from f1data.httplog import HttpRecorder
from f1data.identity import SessionIdentity, format_utc, identity_from_fastf1
from f1data.policy import CLASSIFICATION_DATE_TOLERANCE, CLASSIFICATION_RECHECK_WINDOW
from f1data.publish import Hold, Inputs, Pointer
from f1data.schedule import ScheduledSession, find_scheduled_session, load_schedule
from f1data.store import ObjectStore

_logger = logging.getLogger(__name__)


class BuildError(RuntimeError):
    """The archive could not be turned into artifacts."""


@dataclass(frozen=True)
class BuildContext:
    """What ``gather`` looked up and ``build`` needs again."""

    scheduled: ScheduledSession
    classification: Classification | None


@contextmanager
def no_requests_to_f1() -> Iterator[HttpRecorder]:
    """Refuse requests to F1's hosts for as long as the block runs (rule 4)."""
    with HttpRecorder(forbid_hosts=F1_ARCHIVE_HOSTS) as guard:
        yield guard


class Builder:
    """Gathers inputs for sessions and builds them, for one run of the job.

    Must be used inside ``fastf1_cache``: the schedule and the classification
    go through FastF1, which needs a cache directory of its own for the run.
    """

    def __init__(
        self,
        store: ObjectStore,
        fastf1: Any,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._store = store
        self._fastf1 = fastf1
        self._now = now
        self._schedules: dict[int, list[ScheduledSession]] = {}

    def schedule(self, year: int, fresh: bool = False) -> list[ScheduledSession]:
        """The calendar, read once per run, and read again when asked for fresh.

        A publisher that lost a conditional write has to decide again from
        current inputs (rule 2), and the calendar is one of them: a round
        renumbered while this run was building is exactly when another
        publisher gets in first.
        """
        if fresh or year not in self._schedules:
            # FastF1 falls back from its schedule file to F1's own site.
            with no_requests_to_f1():
                self._schedules[year] = load_schedule(self._fastf1, year, fresh=fresh)
        return self._schedules[year]

    def gather(
        self, session_key: int, pointer: Pointer | None = None, fresh: bool = False
    ) -> Inputs | Hold | None:
        """Select the snapshot and fetch the classification, as of now (rules 3 and 6).

        ``pointer`` is what is published now, if anything. ``fresh`` asks for
        the calendar to be read again rather than taken from this run's copy.
        """
        snapshots = list_snapshots(self._store, session_key)
        if not snapshots:
            return None
        identity = snapshots[0].identity

        if self._is_settled(pointer, identity):
            # An old session, published by this pipeline version. Its
            # classification is no longer asked for on every run; it is built
            # again only if a different snapshot would now be picked.
            assert pointer is not None
            settled = select_snapshot(snapshots)
            if settled is not None and settled.snapshot_id == pointer.snapshot_id:
                return Inputs(snapshot=settled, classification_fingerprint=pointer.classification_fingerprint)

        scheduled = find_scheduled_session(self.schedule(identity.year, fresh=fresh), identity)
        if scheduled is None:
            raise BuildError(
                f"No calendar entry for session {session_key} "
                f"({identity.meeting_name} {identity.session_name}, {identity.start_time_utc})"
            )
        classification = None
        if is_classified_session(identity.session_type):
            try:
                with no_requests_to_f1():
                    classification = fetch_classification(
                        self._fastf1, scheduled.year, scheduled.round, identity.session_type
                    )
            except ClassificationUnavailable as exc:
                # Usual in the hours after a race. Not a failure: the next run asks again.
                return Hold(str(exc))
            _check_same_event(classification, identity, scheduled)
            # A snapshot knows the classification of the day it was fetched,
            # which may be none. Timing is compared with the laps classified now.
            snapshots = [snapshot.judged_against(classification.laps_by_number) for snapshot in snapshots]

        snapshot = select_snapshot(snapshots)
        assert snapshot is not None
        shortfalls = snapshot.shortfalls()
        publishable_from = partial_publication_time(snapshots)
        if shortfalls and self._now() < publishable_from:
            short = ", ".join(sorted({shortfall.bar for shortfall in shortfalls}))
            return Hold(
                f"short on {short}; to be fetched again, and published as partial "
                f"from {format_utc(publishable_from)} if still short"
            )
        return Inputs(
            snapshot=snapshot,
            classification_fingerprint=classification.fingerprint if classification else None,
            context=BuildContext(scheduled=scheduled, classification=classification),
        )

    def _is_settled(self, pointer: Pointer | None, identity: SessionIdentity) -> bool:
        return (
            pointer is not None
            and pointer.pipeline_version == layout.PIPELINE_VERSION
            and self._now() - identity.start_time > CLASSIFICATION_RECHECK_WINDOW
        )

    def build(self, inputs: Inputs) -> tuple[dict[str, bytes], Snapshot]:
        """The generation's files, and the snapshot re-measured from the archive."""
        snapshot = inputs.snapshot
        context: BuildContext = inputs.context
        with tempfile.TemporaryDirectory(prefix="f1data-build-") as scratch:
            cache_dir = restore_snapshot(self._store, snapshot, Path(scratch) / "cache")
            extras = read_extras(self._store, snapshot)
            with fastf1_cache(cache_dir) as fastf1, no_requests_to_f1() as guard:
                session = fastf1.get_session(
                    context.scheduled.year, context.scheduled.round, context.scheduled.session_name
                )
                # FastF1 derives this path from the calendar's current event
                # name and date. The snapshot's own path is the one its feeds
                # are filed under, whatever the calendar says today.
                session.api_path = f"/static/{snapshot.identity.archive_path}"
                session.load(laps=True, telemetry=True, weather=True, messages=True)

                loaded = identity_from_fastf1(session)
                if loaded.session_key != snapshot.session_key:
                    raise BuildError(
                        f"Snapshot {snapshot.snapshot_id} holds session {loaded.session_key}, "
                        f"not {snapshot.session_key}"
                    )
                if context.classification is not None:
                    merge_into_session(session, context.classification)
                # Measured again here, against the classification of today, so
                # the pointer records what this generation was built from.
                coverage = measure_coverage(session, snapshot.identity.session_type, extras)
                files = legacy.build_legacy_artifacts(
                    session,
                    snapshot.identity,
                    context.scheduled.round,
                    generated_at=snapshot.fetched_at,
                    scratch=Path(scratch) / "artifacts",
                )
        if guard.forbidden:
            # Refused, not sent. Expected for a snapshot that lacks a feed.
            _logger.warning(
                "Build of session %s wanted %d feed(s) the snapshot lacks; F1 was not contacted",
                snapshot.session_key,
                len(guard.forbidden),
            )
        return files, replace(snapshot, coverage=coverage)


def _check_same_event(
    classification: Classification, identity: SessionIdentity, scheduled: ScheduledSession
) -> None:
    """Refuse a classification that is another race's.

    The round asked for comes from the calendar, and a calendar can be out of
    date: the 2026 season gained a race at round 16 in October and every later
    round moved by one. A result is tied to the session by date, never by the
    round number alone, or one race's timing could be published with
    another's result.
    """
    session_date = identity.start_time.date()
    if classification.race_date is None:
        raise BuildError(
            f"Jolpica's result for {scheduled.year} round {scheduled.round} carries no race date, "
            f"so it cannot be tied to session {identity.session_key}"
        )
    if abs(classification.race_date - session_date) > CLASSIFICATION_DATE_TOLERANCE:
        raise BuildError(
            f"Jolpica's {scheduled.year} round {scheduled.round} is a race on "
            f"{classification.race_date.isoformat()}, not session {identity.session_key} "
            f"({identity.meeting_name}, {session_date.isoformat()}); the calendar this run read is out of date"
        )
