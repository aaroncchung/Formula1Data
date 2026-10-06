"""Build a session's artifacts from its archive snapshot.

A build reads the archive, Jolpica and FastF1's schedule file, and nothing from
F1 (docs/architecture-review-findings.md, section 6, rule 4). That is enforced,
not assumed: requests to F1's hosts are refused while a build runs, so a feed
missing from a snapshot stays missing instead of being fetched behind the
archive's back.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from f1data import legacy
from f1data.archive import Snapshot, list_snapshots, restore_snapshot, select_snapshot
from f1data.classification import (
    Classification,
    fetch_classification,
    is_classified_session,
    merge_into_session,
)
from f1data.coverage import measure_coverage
from f1data.fetch import F1_ARCHIVE_HOSTS, fastf1_cache
from f1data.httplog import HttpRecorder
from f1data.identity import identity_from_fastf1
from f1data.publish import Inputs
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


class Builder:
    """Gathers inputs for sessions and builds them, for one run of the job.

    Must be used inside ``fastf1_cache``: the schedule and the classification
    go through FastF1, which needs a cache directory of its own for the run.
    """

    def __init__(self, store: ObjectStore, fastf1: Any) -> None:
        self._store = store
        self._fastf1 = fastf1
        self._schedules: dict[int, list[ScheduledSession]] = {}

    def schedule(self, year: int) -> list[ScheduledSession]:
        if year not in self._schedules:
            self._schedules[year] = load_schedule(self._fastf1, year)
        return self._schedules[year]

    def gather(self, session_key: int) -> Inputs | None:
        """Select the snapshot and fetch the classification, as of now (rules 3 and 6)."""
        snapshot = select_snapshot(list_snapshots(self._store, session_key))
        if snapshot is None:
            return None
        identity = snapshot.identity
        scheduled = find_scheduled_session(self.schedule(identity.year), identity)
        if scheduled is None:
            raise BuildError(
                f"No calendar entry for session {session_key} "
                f"({identity.meeting_name} {identity.session_name}, {identity.start_time_utc})"
            )
        classification = None
        if is_classified_session(identity.session_type):
            classification = fetch_classification(
                self._fastf1, scheduled.year, scheduled.round, identity.session_type
            )
        return Inputs(
            snapshot=snapshot,
            classification_fingerprint=classification.fingerprint if classification else None,
            context=BuildContext(scheduled=scheduled, classification=classification),
        )

    def build(self, inputs: Inputs) -> tuple[dict[str, bytes], Snapshot]:
        """The generation's files, and the snapshot re-measured from the archive."""
        snapshot = inputs.snapshot
        context: BuildContext = inputs.context
        guard = HttpRecorder(forbid_hosts=F1_ARCHIVE_HOSTS)
        with tempfile.TemporaryDirectory(prefix="f1data-build-") as scratch:
            cache_dir = restore_snapshot(self._store, snapshot, Path(scratch) / "cache")
            with fastf1_cache(cache_dir) as fastf1, guard:
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
                coverage = measure_coverage(session, snapshot.identity.session_type)
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
