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

from f1data import layout
from f1data.artifacts import build_artifacts
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
    ClassificationMissing,
    ClassificationUnavailable,
    fetch_classification,
    is_classified_session,
    merge_into_session,
)
from f1data.coverage import Shortfall, apply_classification, evaluate_coverage, measure_coverage
from f1data.fetch import F1_ARCHIVE_HOSTS, fastf1_cache
from f1data.httplog import HttpRecorder
from f1data.identity import SessionIdentity, format_utc, identity_from_fastf1
from f1data.policy import (
    CLASSIFICATION_DATE_TOLERANCE,
    CLASSIFICATION_RECHECK_WINDOW,
    SETTLED_RECHECK_EVERY_DAYS,
    SETTLED_RECHECK_FOR_DAYS,
)
from f1data.publish import Hold, Inputs, NotYetPublishable, Pointer
from f1data.schedule import ScheduledSession, find_scheduled_session, load_schedule
from f1data.standings import fetch_standings
from f1data.store import ObjectStore

_logger = logging.getLogger(__name__)


class BuildError(RuntimeError):
    """The archive could not be turned into artifacts."""


@dataclass(frozen=True)
class BuildContext:
    """What ``gather`` looked up and ``build`` needs again."""

    scheduled: ScheduledSession
    classification: Classification | None
    # When the session may be published even if it is short of a bar.
    publishable_from: datetime


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
        recheck: bool = False,
    ) -> None:
        self._store = store
        self._fastf1 = fastf1
        self._now = now
        # Ask Jolpica about every session, however old.
        self._recheck = recheck

    def schedule(self, year: int) -> list[ScheduledSession]:
        """The calendar as it stands now, read from its source on every call.

        Nothing is kept between calls, and that is the point. A publisher
        writes against the version of a pointer or of the index that it read
        (rule 2), and that guard covers only what it looked up after the read.
        A calendar held from earlier in the run would let this publisher put a
        build, or an index, made from the old calendar over one that another
        publisher had made from the new, with no conflict to stop it.
        """
        # FastF1 falls back from its schedule file to F1's own site.
        with no_requests_to_f1():
            return load_schedule(self._fastf1, year, fresh=True)

    def gather(
        self, session_key: int, pointer: Pointer | None = None, retry: bool = False
    ) -> Inputs | Hold | None:
        """Select the snapshot and look up what else a build takes, as of now (rules 3 and 6).

        ``pointer`` is what is published now, if anything, read before this is
        called. ``retry`` says a write was just lost to another publisher.
        """
        snapshots = list_snapshots(self._store, session_key)
        if not snapshots:
            return None
        identity = snapshots[0].identity

        scheduled = find_scheduled_session(self.schedule(identity.year), identity)
        if scheduled is None:
            raise BuildError(
                f"No calendar entry for session {session_key} "
                f"({identity.meeting_name} {identity.session_name}, {identity.start_time_utc})"
            )
        # Nothing else. In format 2 no artifact carries anything from the
        # calendar: what a session is comes from F1's own session information,
        # and pages look the round up in the index. The calendar entry still
        # says which round to ask Jolpica about, but what Jolpica answers is
        # tied to the session by its date and recorded by its fingerprint, so a
        # build made while the calendar said another round is the same build.
        also = None

        # After a lost write nothing is taken on trust, the shortcut included.
        if not retry and self._is_settled(pointer, identity):
            # An old session, published by this pipeline version. Its
            # classification is not asked for on every run; between the days
            # it is, the session is built again only if a different snapshot
            # would now be picked or its calendar entry has changed.
            assert pointer is not None
            settled = select_snapshot(snapshots)
            if (
                settled is not None
                and settled.snapshot_id == pointer.snapshot_id
                and also == pointer.also
            ):
                return Inputs(
                    snapshot=settled,
                    classification_fingerprint=pointer.classification_fingerprint,
                    also=also,
                )

        publishable_from = partial_publication_time(snapshots)
        classification = None
        if is_classified_session(identity.session_type):
            try:
                with no_requests_to_f1():
                    classification = fetch_classification(
                        self._fastf1, scheduled.year, scheduled.round, identity.session_type
                    )
            except ClassificationMissing as exc:
                # Usual in the hours after a race: the next run asks again.
                # But not for ever. Once the retry window has closed the
                # session is published as partial like any other that is
                # short, with the classification named as what is missing.
                if self._now() < publishable_from:
                    return Hold(str(exc))
            except ClassificationUnavailable as exc:
                # Jolpica did not answer, so nothing is known. Never a reason
                # to publish without a result that may well exist.
                return Hold(str(exc))
            if classification is not None:
                _check_same_event(classification, identity, scheduled)
                # A snapshot knows the classification of the day it was
                # fetched, which may be none. Timing is compared with the laps
                # classified now.
                snapshots = [
                    snapshot.judged_against(classification.laps_by_number) for snapshot in snapshots
                ]

        snapshot = select_snapshot(snapshots)
        assert snapshot is not None
        shortfalls = snapshot.shortfalls()
        if shortfalls and self._now() < publishable_from:
            return Hold(_not_yet(shortfalls, publishable_from))
        return Inputs(
            snapshot=snapshot,
            classification_fingerprint=classification.fingerprint if classification else None,
            context=BuildContext(
                scheduled=scheduled, classification=classification, publishable_from=publishable_from
            ),
            also=also,
        )

    def _is_settled(self, pointer: Pointer | None, identity: SessionIdentity) -> bool:
        if self._recheck or pointer is None or pointer.pipeline_version != layout.PIPELINE_VERSION:
            return False
        now = self._now()
        if now - identity.start_time <= CLASSIFICATION_RECHECK_WINDOW:
            return False
        # On its days the session is asked about like a recent one.
        day = now.date().toordinal() + identity.session_key
        return day % SETTLED_RECHECK_EVERY_DAYS >= SETTLED_RECHECK_FOR_DAYS

    def standings(self, year: int) -> dict[str, Any] | None:
        """The championship standings of ``year`` as Jolpica has them now."""
        with no_requests_to_f1():
            return fetch_standings(self._fastf1, year)

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
                if context.classification is not None:
                    # By the same reckoning ``gather`` judged the snapshot by:
                    # today's result is the whole answer, driver by driver.
                    coverage = apply_classification(coverage, context.classification.laps_by_number)
                shortfalls = evaluate_coverage(coverage)
                recorded = set(snapshot.shortfalls())
                unrecorded = [shortfall for shortfall in shortfalls if shortfall not in recorded]
                if unrecorded:
                    # The two are the same bytes measured by the same code,
                    # so this is a fault somewhere. What was found stands: it
                    # goes into the pointer, and the fetch stage reads it there.
                    _logger.warning(
                        "Snapshot %s of session %s is short where its record is not: %s",
                        snapshot.snapshot_id,
                        snapshot.session_key,
                        "; ".join(
                            f"{item.bar} {item.driver or 'session'}: {item.detail}" for item in unrecorded
                        ),
                    )
                if shortfalls and self._now() < context.publishable_from:
                    # The record said whole, or less short than this. Rule 6
                    # holds either way: later fetches come first.
                    raise NotYetPublishable(_not_yet(shortfalls, context.publishable_from))
                files = build_artifacts(
                    session, snapshot.identity, context.classification, extras, coverage
                )
        if guard.forbidden:
            # Refused, not sent. Expected for a snapshot that lacks a feed.
            _logger.warning(
                "Build of session %s wanted %d feed(s) the snapshot lacks; F1 was not contacted",
                snapshot.session_key,
                len(guard.forbidden),
            )
        return files, replace(snapshot, coverage=coverage)


def _not_yet(shortfalls: list[Shortfall], publishable_from: datetime) -> str:
    short = ", ".join(sorted({shortfall.bar for shortfall in shortfalls}))
    return (
        f"short on {short}; to be fetched again, and published as partial "
        f"from {format_utc(publishable_from)} if still short"
    )


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
