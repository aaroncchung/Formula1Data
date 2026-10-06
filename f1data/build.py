"""Build a session's artifacts from its archive snapshot.

A build reads the archive, Jolpica and FastF1's schedule file, and nothing from
F1 (docs/architecture-review-findings.md, section 6, rule 4). It does so in two
steps, and what each may reach is enforced, not assumed.

``gather`` looks up what comes from outside the archive: the calendar entry
and the classification. Requests to F1's hosts are refused while it does, so
a calendar that will not load from its file is not quietly taken from F1.
What it found is recorded in the pointer.

``build`` then turns the snapshot and what was gathered into artifacts with
every request refused, whatever its host. A feed missing from the snapshot
stays missing instead of being fetched behind the archive's back, and nothing
is looked up a second time: a build made of one calendar read and one
classification cannot come out as a mixture of two.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from f1data import layout, legacy
from f1data.archive import (
    Snapshot,
    list_snapshots,
    partial_publication_time,
    read_extras,
    restore_snapshot,
    select_snapshot,
    write_remeasurement,
)
from f1data.classification import (
    Classification,
    ClassificationMissing,
    ClassificationUnavailable,
    fetch_classification,
    is_classified_session,
    merge_into_session,
)
from f1data.coverage import feed_figures, measure_coverage
from f1data.fetch import F1_ARCHIVE_HOSTS, fastf1_cache
from f1data.httplog import HttpRecorder
from f1data.identity import SessionIdentity, format_utc, identity_from_fastf1
from f1data.policy import (
    CLASSIFICATION_DATE_TOLERANCE,
    CLASSIFICATION_RECHECK_WINDOW,
    SETTLED_RECHECK_EVERY_DAYS,
    SETTLED_RECHECK_FOR_DAYS,
)
from f1data.publish import DecideAgain, Hold, Inputs, Pointer
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


@contextmanager
def no_requests_to_f1() -> Iterator[HttpRecorder]:
    """Refuse requests to F1's hosts for as long as the block runs (rule 4)."""
    with HttpRecorder(forbid_hosts=F1_ARCHIVE_HOSTS) as guard:
        yield guard


@contextmanager
def no_requests_at_all() -> Iterator[HttpRecorder]:
    """Refuse every request for as long as the block runs."""
    with HttpRecorder(forbid_all=True) as guard:
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
        # One source, FastF1's schedule file. Left to itself FastF1 falls
        # back to F1's own site and then to Jolpica, and a build records the
        # row it was made from: the same race from another source is another
        # row, and every session would be built again each time they swapped.
        with no_requests_to_f1():
            return load_schedule(self._fastf1, year, fresh=True, backend="fastf1")

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
        # The calendar entry reaches the artifacts (the round, the names, the
        # dates), so a build made under another entry is not this build. The
        # four fields are there to be read; the checksum covers the whole row.
        also = {
            "calendar": {
                "year": scheduled.year,
                "round": scheduled.round,
                "meeting_name": scheduled.meeting_name,
                "session_name": scheduled.session_name,
                "row": scheduled.row_fingerprint,
            }
        }

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
            context=BuildContext(scheduled=scheduled, classification=classification),
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
        """The generation's files, and the snapshot they were built from.

        Raises ``DecideAgain`` when the snapshot's feeds are not what its
        record says, after correcting the record.
        """
        snapshot = inputs.snapshot
        context: BuildContext = inputs.context
        event = context.scheduled.event
        if event is None:
            raise BuildError(
                f"The calendar entry for session {snapshot.session_key} carries no FastF1 event to build from"
            )
        with tempfile.TemporaryDirectory(prefix="f1data-build-") as scratch:
            cache_dir = restore_snapshot(self._store, snapshot, Path(scratch) / "cache")
            extras = read_extras(self._store, snapshot)
            with fastf1_cache(cache_dir), no_requests_at_all() as guard:
                # Made from the calendar row that gather read. Asking FastF1
                # for the session by year and round would read the calendar
                # again, and after a change it answers with whichever race
                # holds that round now.
                session = event.get_session(context.scheduled.session_name)
                # FastF1 derives this path from the event's name and date.
                # The snapshot's own path is the one its feeds are filed
                # under, whatever the calendar says today.
                session.api_path = f"/static/{snapshot.identity.archive_path}"
                session.load(laps=True, telemetry=True, weather=True, messages=True)

                loaded = identity_from_fastf1(session)
                if loaded.session_key != snapshot.session_key:
                    raise BuildError(
                        f"Snapshot {snapshot.snapshot_id} holds session {loaded.session_key}, "
                        f"not {snapshot.session_key}"
                    )
                # Measured as a fetch would measure it, before anything from
                # today is put in. The feeds are the archive's, so this is
                # what the snapshot's record should say of them.
                measured = measure_coverage(session, snapshot.identity.session_type, extras)
                if snapshot.measured_in_full and feed_figures(measured) != feed_figures(snapshot.coverage):
                    # Gather chose this snapshot, and judged it fit to
                    # publish, from a record that is wrong. Neither judgement
                    # stands. The record is put right for every reader of the
                    # archive, the fetch planner included, and the decision is
                    # taken again.
                    write_remeasurement(self._store, snapshot, measured, now=self._now())
                    _logger.warning(
                        "Snapshot %s of session %s does not hold what its record says; "
                        "the record is corrected: %s",
                        snapshot.snapshot_id,
                        snapshot.session_key,
                        _differences(feed_figures(snapshot.coverage), feed_figures(measured)),
                    )
                    raise DecideAgain(
                        f"corrected the record of snapshot {snapshot.snapshot_id}, "
                        "which did not hold what it said"
                    )
                if context.classification is not None:
                    merge_into_session(session, context.classification)
                files = legacy.build_legacy_artifacts(
                    session,
                    snapshot.identity,
                    context.scheduled.round,
                    generated_at=snapshot.fetched_at,
                    scratch=Path(scratch) / "artifacts",
                )
        wanted_of_f1 = [url for url in guard.forbidden if _host(url) in F1_ARCHIVE_HOSTS]
        if wanted_of_f1:
            # Refused, not sent. Expected for a snapshot that lacks a feed.
            _logger.warning(
                "Build of session %s wanted %d feed(s) the snapshot lacks; F1 was not contacted",
                snapshot.session_key,
                len(wanted_of_f1),
            )
        # The record and the feeds agree, so the snapshot as gather judged it
        # is what this generation was built from.
        return files, snapshot


def _host(url: str) -> str:
    return urlsplit(url).netloc


def _differences(recorded: dict[str, Any], measured: dict[str, Any]) -> str:
    """Where two sets of feed figures part, in a line short enough to log."""
    found = [
        f"{key}: {recorded.get(key)!r} recorded, {measured.get(key)!r} measured"
        for key in sorted(set(recorded) | set(measured))
        if key != "drivers" and recorded.get(key) != measured.get(key)
    ]
    was, now = recorded.get("drivers", {}), measured.get("drivers", {})
    for number in sorted(set(was) | set(now)):
        if was.get(number) != now.get(number):
            found.append(f"driver {number}: {was.get(number)!r} recorded, {now.get(number)!r} measured")
    return "; ".join(found[:6]) + (f"; and {len(found) - 6} more" if len(found) > 6 else "")


def _not_yet(shortfalls: list[Any], publishable_from: datetime) -> str:
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
