"""The source archive: each fetch of a session, kept as it arrived.

A fetch is stored as a snapshot under a name of its own and never overwritten
(docs/architecture-review-findings.md, section 6, rules 4 and 6):

    archive/sessions/<session_key>/<snapshot_id>/fastf1-cache.tar.gz    parsed feeds
    archive/sessions/<session_key>/<snapshot_id>/http-cache.sqlite.gz   raw responses
    archive/sessions/<session_key>/<snapshot_id>/snapshot.json          written last
    archive/sessions/<session_key>/<snapshot_id>/remeasured.json        only if a build
                                                                        found the record wrong

``snapshot.json`` is the marker: a snapshot without one did not finish
uploading and is ignored. The parsed feeds are what a build reads. The raw
responses are kept because FastF1 discards parsed feeds written under another
cache version (AR-11), and F1 may not answer a second time.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import secrets
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from f1data import layout
from f1data.coverage import (
    CLASSIFICATION_BAR,
    MEASUREMENT_VERSION,
    Shortfall,
    apply_classification,
    evaluate_coverage,
    f1_does_not_hold,
    feed_figures,
    is_measurement,
    weakest_share,
)
from f1data.extras import CIRCUIT_INFO, circuit_corner_count
from f1data.fetch import HTTP_CACHE_FILE, FetchedSession
from f1data.identity import SESSION_TYPES, SessionIdentity, format_utc, parse_utc
from f1data.policy import CLOCK_TOLERANCE, RETRY_WINDOW
from f1data.store import ObjectStore, PreconditionFailed

SNAPSHOT_SCHEMA_VERSION = 1
PARSED_ARCHIVE = "fastf1-cache.tar.gz"
HTTP_ARCHIVE = "http-cache.sqlite.gz"
EXTRA_PREFIX = "extra/"
_LEGACY_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_logger = logging.getLogger(__name__)


class ArchiveError(RuntimeError):
    """A snapshot is missing a part, or a part does not match its checksum."""


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    identity: SessionIdentity
    fetched_at: str
    coverage: dict[str, Any]
    versions: dict[str, Any] = field(default_factory=dict)
    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    attempts: int = 1
    requests_by_host: dict[str, dict[str, int]] = field(default_factory=dict)
    # What F1 last answered for each feed it was asked for, by file name.
    feed_status: dict[str, Any] = field(default_factory=dict)
    # Set when the snapshot is listed, about the correction beside it, if
    # there is one: the version of that object, and the pipeline version that
    # wrote it. Neither is part of the snapshot.
    correction_etag: str | None = field(default=None, compare=False, repr=False)
    corrected_by: int | None = field(default=None, compare=False, repr=False)

    @property
    def session_key(self) -> int:
        return self.identity.session_key

    @property
    def record_fingerprint(self) -> str:
        """Of what the record says about the feeds. A pointer keeps it, so a
        record corrected after a session was published is noticed."""
        return f"sha256:{hashlib.sha256(dump_json(feed_figures(self.coverage))).hexdigest()}"

    def shortfalls(self) -> list[Shortfall]:
        # Judged with the bars in this code, not the ones at fetch time, so a
        # bar can change without a re-fetch.
        return evaluate_coverage(self.coverage)

    @property
    def complete(self) -> bool:
        return not self.shortfalls()

    def missing_only_what_f1_does_not_hold(self) -> bool:
        """Whether every shortfall is a feed F1 answered that it does not have.

        Such a session is as whole as it can be, and asking again is pointless.
        A missing classification is left out of the reckoning: it is Jolpica's.
        """
        short = [shortfall for shortfall in self.shortfalls() if shortfall.bar != CLASSIFICATION_BAR]
        return bool(short) and all(
            f1_does_not_hold(shortfall, self.feed_status, self.coverage) for shortfall in short
        )

    def judged_against(self, classified_laps: dict[str, int]) -> "Snapshot":
        """This snapshot as it stands against today's classification.

        What a snapshot recorded of the classification is what Jolpica had when
        it was fetched, which for a session fetched soon after it ended is
        nothing. Timing is compared with the laps classified now.
        """
        return replace(self, coverage=apply_classification(self.coverage, classified_laps))

    @property
    def measured_in_full(self) -> bool:
        """Whether the fetch collected everything today's bars ask about."""
        return self.coverage.get("measurement_version") == MEASUREMENT_VERSION

    def rank(self) -> tuple[bool, bool, int, float, str]:
        """Higher is better. The order in which build picks a snapshot (rule 6).

        A snapshot that meets every bar beats one that does not. Among those
        that fall short, one that was measured in full beats one from before a
        feed was collected, whose shortfalls cannot be counted. Then fewer
        shortfalls wins, then the higher weakest share. Only then does the
        later fetch win, so a retry that does worse changes nothing.
        """
        return (
            self.complete,
            self.measured_in_full,
            -len(self.shortfalls()),
            weakest_share(self.coverage),
            self.fetched_at,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "session_key": self.session_key,
            "identity": self.identity.to_json(),
            "fetched_at": self.fetched_at,
            "versions": self.versions,
            "attempts": self.attempts,
            "requests_by_host": self.requests_by_host,
            "feed_status": self.feed_status,
            "objects": self.objects,
            "coverage": self.coverage,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "Snapshot":
        if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
            raise ArchiveError(f"Unsupported snapshot schema: {payload.get('schema_version')!r}")
        return cls(
            snapshot_id=str(payload["snapshot_id"]),
            identity=SessionIdentity.from_json(payload["identity"]),
            fetched_at=str(payload["fetched_at"]),
            coverage=dict(payload["coverage"]),
            versions=dict(payload.get("versions") or {}),
            objects=dict(payload.get("objects") or {}),
            attempts=int(payload.get("attempts") or 1),
            requests_by_host=dict(payload.get("requests_by_host") or {}),
            feed_status=dict(payload.get("feed_status") or {}),
        )


def new_snapshot_id(now: datetime | None = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def write_snapshot(
    store: ObjectStore, fetched: FetchedSession, now: datetime | None = None, snapshot_id: str | None = None
) -> Snapshot:
    """Archive a fetched session. Call after the fetch has released its cache.

    ``now`` is when the session was fetched. ``snapshot_id`` names a snapshot
    whose upload may have been started before (f1data/spool.py): its parts are
    then written over what the earlier attempt left, and its marker written
    once. If the marker is there already the earlier attempt finished, and
    the snapshot is returned as it stands with nothing written.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if snapshot_id is None:
        snapshot_id = new_snapshot_id(now)
    elif not layout.is_snapshot_id(snapshot_id):
        raise ArchiveError(f"Not a snapshot id: {snapshot_id!r}")
    prefix = layout.snapshot_prefix(fetched.identity.session_key, snapshot_id)
    finished = store.get(f"{prefix}{layout.SNAPSHOT_MARKER}")
    if finished is not None:
        # Read as every reader of the archive reads it. A marker in this
        # place that is not this snapshot's is nothing to take for an upload
        # that finished: the fetch it would be taken for is the only copy.
        archived = _snapshot_at(f"{prefix}{layout.SNAPSHOT_MARKER}", finished.data)
        if archived is None:
            raise ArchiveError(
                f"{prefix}{layout.SNAPSHOT_MARKER} is there and is not the marker of this snapshot. "
                "Nothing was written."
            )
        return archived
    session_dir = fetched.cache_dir / fetched.identity.archive_path
    if not session_dir.is_dir() or not any(session_dir.glob("*.ff1pkl")):
        raise ArchiveError(f"No parsed feeds to archive under {session_dir}")

    objects: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="f1data-snapshot-") as scratch:
        parsed = Path(scratch) / PARSED_ARCHIVE
        with tarfile.open(parsed, "w:gz", compresslevel=6) as archive:
            for path in sorted(session_dir.glob("*.ff1pkl")):
                archive.add(path, arcname=f"{fetched.identity.archive_path}{path.name}")
        objects[PARSED_ARCHIVE] = _describe(parsed)
        store.put_file(f"{prefix}{PARSED_ARCHIVE}", parsed, content_type="application/gzip")

        http_cache = fetched.cache_dir / HTTP_CACHE_FILE
        if http_cache.is_file():
            compressed = Path(scratch) / HTTP_ARCHIVE
            with http_cache.open("rb") as source, gzip.open(compressed, "wb", compresslevel=6) as sink:
                shutil.copyfileobj(source, sink, length=1024 * 1024)
            objects[HTTP_ARCHIVE] = _describe(compressed)
            store.put_file(f"{prefix}{HTTP_ARCHIVE}", compressed, content_type="application/gzip")

    for name, data in sorted(fetched.extras.items()):
        objects[f"{EXTRA_PREFIX}{name}"] = {
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        store.put(f"{prefix}{EXTRA_PREFIX}{name}", data, content_type=_extra_content_type(name))

    snapshot = Snapshot(
        snapshot_id=snapshot_id,
        identity=fetched.identity,
        fetched_at=format_utc(now),
        coverage=fetched.coverage,
        versions=fetched.versions,
        objects=objects,
        attempts=fetched.attempts,
        requests_by_host=fetched.http.summary(),
        feed_status=fetched.feed_status,
    )
    store.put(f"{prefix}{layout.SNAPSHOT_MARKER}", dump_json(snapshot.to_json()), if_absent=True)
    return snapshot


def list_snapshots(store: ObjectStore, session_key: int | None = None) -> list[Snapshot]:
    """Every finished snapshot, for one session or for all of them."""
    prefix = (
        layout.session_archive_prefix(session_key)
        if session_key is not None
        else f"{layout.ARCHIVE_PREFIX}sessions/"
    )
    markers: list[str] = []
    remeasured: set[str] = set()
    # This version's corrections and no other's (f1data/layout.py).
    correction_name = layout.remeasurement_name(MEASUREMENT_VERSION)
    for item in store.list(prefix):
        if item.key.endswith(f"/{layout.SNAPSHOT_MARKER}"):
            markers.append(item.key)
        elif item.key.endswith(f"/{correction_name}"):
            remeasured.add(item.key)
    snapshots = []
    for key in markers:
        found = store.get(key)
        if found is None:
            continue
        snapshot = _snapshot_at(key, found.data)
        if snapshot is None:
            continue
        correction = f"{key[: -len(layout.SNAPSHOT_MARKER)]}{correction_name}"
        if correction in remeasured:
            snapshot = _as_remeasured(store, snapshot, correction)
        snapshots.append(_with_corner_count(store, snapshot))
    return snapshots


def _snapshot_at(key: str, data: bytes) -> Snapshot | None:
    """The snapshot a marker describes, if it is the snapshot its key says.

    Everything after this trusts the marker: which session it is listed
    under, where its parts are restored from, whose pointer it is published
    to. A marker that describes another session than the one it is filed
    under, or that is not a marker at all, is no snapshot. It is passed over
    and said so, as an upload that never finished is, and the rest of the
    archive is read as usual.
    """
    placed = layout.snapshot_from_marker_key(key)
    # Whatever goes wrong reading it, it is not a marker: the archive is read
    # by both stages before either has started on any session.
    try:
        snapshot = Snapshot.from_json(json.loads(data)) if placed is not None else None
        described = snapshot is not None and _is_described(snapshot)
    except Exception as exc:
        _logger.error("%s is not a snapshot marker and is passed over: %s", key, exc)
        return None
    if snapshot is None or (snapshot.session_key, snapshot.snapshot_id) != placed:
        _logger.error("%s does not describe the snapshot it is filed as, and is passed over", key)
        return None
    if not described or not _is_measurement(snapshot.coverage):
        _logger.error("%s records something that cannot be read, and is passed over", key)
        return None
    return snapshot


def _is_described(snapshot: Snapshot) -> bool:
    """Whether everything a marker says besides its measurement can be read.

    When it was fetched and when its session started are compared with the
    clock; its parts are looked up by name. Raises, or answers no, for a
    marker that would make any of that raise later.
    """
    identity = snapshot.identity
    parse_utc(snapshot.fetched_at)
    identity.start_time
    return (
        isinstance(identity.year, int)
        and not isinstance(identity.year, bool)
        and identity.session_type in SESSION_TYPES
        and isinstance(identity.archive_path, str)
        and bool(identity.archive_path)
        and all(isinstance(name, str) and isinstance(part, dict) for name, part in snapshot.objects.items())
        # What F1 answered for a feed is a status or nothing. It is looked up
        # in a set of statuses once a session's retry window has closed.
        and all(
            isinstance(name, str) and (status is None or (isinstance(status, int) and not isinstance(status, bool)))
            for name, status in snapshot.feed_status.items()
        )
    )


def _is_measurement(coverage: Any) -> bool:
    """Whether everything that reads a measurement can read this one.

    Found out by reading it. A figure that is text where a count belongs
    raises wherever it is first used, which is the fetch planner, before it
    has planned anything, or the choice of snapshot: one unreadable record
    would stop every session.
    """
    if not is_measurement(coverage):
        return False
    try:
        evaluate_coverage(coverage)
        weakest_share(coverage)
        feed_figures(coverage)
        apply_classification(coverage, {})
    except Exception:
        return False
    return True


def _whole_number(value: Any) -> int:
    """A version number as one, or ``ValueError`` for anything a version cannot be."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"not a version: {value!r}")
    return value


def write_remeasurement(
    store: ObjectStore, snapshot: Snapshot, coverage: dict[str, Any], now: datetime | None = None
) -> None:
    """Record that a snapshot's feeds, measured again, are not what its record says.

    A snapshot is never rewritten. This goes beside it, and from then on
    every reader of the archive is given the snapshot with these figures:
    the fetch planner, snapshot selection and the next build judge what the
    feeds hold, not what a faulty record claimed (rules 3 and 6).

    The figures are a function of the archived feeds and of the code that
    measures them, so two builds of one pipeline version write the same
    thing. Builds of two versions may not, and then the newer one is right:
    a correction written by a newer pipeline version is never replaced
    (``ValueError``; the caller is expected to have looked). And the write is
    made against the correction this snapshot was listed with, so that one
    another build has written since is not replaced unread
    (``PreconditionFailed``).

    That is among builds that measure alike. The object is this version of
    the measurement's own; another version's is a different object, which
    this never reads and never writes.
    """
    if (snapshot.corrected_by or 0) > layout.PIPELINE_VERSION:
        raise ValueError(
            f"Snapshot {snapshot.snapshot_id} was measured by pipeline version {snapshot.corrected_by}"
        )
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    key = (
        f"{layout.snapshot_prefix(snapshot.session_key, snapshot.snapshot_id)}"
        f"{layout.remeasurement_name(MEASUREMENT_VERSION)}"
    )
    data = dump_json(
        {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "session_key": snapshot.session_key,
            "measured_at": format_utc(now),
            "pipeline_version": layout.PIPELINE_VERSION,
            "coverage": coverage,
        }
    )
    if snapshot.correction_etag is None:
        store.put(key, data, if_absent=True)
    else:
        store.put(key, data, if_match=snapshot.correction_etag)


def _as_remeasured(store: ObjectStore, snapshot: Snapshot, key: str) -> Snapshot:
    """The snapshot with the figures a build measured from its feeds, if they can be read."""
    found = store.get(key)
    if found is None:
        return snapshot
    # Whatever is there, a build that writes a correction writes it against
    # this version, and leaves it alone if a newer pipeline version wrote it.
    snapshot = replace(snapshot, correction_etag=found.etag)
    # A build loads its session with Jolpica out of reach, so what it measured
    # says nothing of the classification. That stays as the fetch recorded it.
    recorded = {
        str(driver.get("number")): driver.get("classified_laps")
        for driver in snapshot.coverage.get("drivers", {}).values()
    }
    try:
        payload = json.loads(found.data)
        if payload["schema_version"] != SNAPSHOT_SCHEMA_VERSION or payload["snapshot_id"] != snapshot.snapshot_id:
            return snapshot
        written_by = _whole_number(payload["pipeline_version"])
        coverage = payload["coverage"]
        measured_by = _whole_number(coverage["measurement_version"])
        if measured_by != MEASUREMENT_VERSION:
            # Under this version's name and not this version's. Another
            # version of the measurement keeps its corrections in an object
            # of its own, so nothing that says so here was written by one.
            # It used to be believed, as far as "a newer version has been
            # here, stand aside": a claim that cannot be checked, which
            # however little it was allowed to hold could shut this version
            # out of the snapshot for good.
            raise ValueError("not this version's measurement")
        corrected = {
            **coverage,
            "drivers": {
                code: {**driver, "classified_laps": recorded.get(str(driver.get("number")))}
                for code, driver in coverage["drivers"].items()
            },
        }
        if not _is_measurement(corrected):
            raise ValueError("the figures cannot be read")
    except Exception:
        # Not something a build wrote. The snapshot stands as it was recorded,
        # and the next build of it writes the figures again. Nothing the
        # object claims is believed, the pipeline version least of all: a
        # broken correction that passed for a newer version's would never be
        # replaced.
        return snapshot
    return replace(snapshot, coverage=corrected, corrected_by=written_by)


def _with_corner_count(store: ObjectStore, snapshot: Snapshot) -> Snapshot:
    """The snapshot with its corners counted, if its fetch did not count them.

    The count was added to the measurement after the first snapshots were
    taken. It can be worked out from the circuit file archived with them, so
    it is, here, where every reader of the archive gets its snapshots: the
    fetch planner, snapshot selection and the build then judge the same
    figure. Left unknown, it would have to be taken as passing or as failing,
    and either is a guess about a file that is there to be read.
    """
    if "circuit_corners" in snapshot.coverage:
        return snapshot
    name = f"{EXTRA_PREFIX}{CIRCUIT_INFO}"
    described = snapshot.objects.get(name)
    data = b""
    if described:
        found = store.get(f"{layout.snapshot_prefix(snapshot.session_key, snapshot.snapshot_id)}{name}")
        if found is not None and hashlib.sha256(found.data).hexdigest() == described.get("sha256"):
            data = found.data
    return replace(snapshot, coverage={**snapshot.coverage, "circuit_corners": circuit_corner_count(data)})


def select_snapshot(snapshots: list[Snapshot]) -> Snapshot | None:
    """The snapshot a build should use, or ``None`` when there is none."""
    return max(snapshots, key=Snapshot.rank, default=None)


def partial_publication_time(snapshots: list[Snapshot], now: datetime | None = None) -> datetime:
    """When a session still short of a bar may be published as partial (rule 6).

    Until then later fetches may still do better, and a partial publication is
    not what anyone is waiting for. The window runs from the first fetch that
    was measured in full, the same clock the fetch planner retries by; before
    there is one, from the first fetch of any kind.

    ``now`` is this machine's clock. A fetch stamped with a time that has not
    come was stamped by a clock that was wrong, and counts as made now: the
    window is then still open, and the fetch planner, which cannot tell when
    such a fetch was made either, fetches again at once.
    """
    counted = [snapshot for snapshot in snapshots if snapshot.measured_in_full] or snapshots
    if now is None:
        return min(parse_utc(snapshot.fetched_at) for snapshot in counted) + RETRY_WINDOW
    now = now.astimezone(timezone.utc)
    return min(plausible_fetch_time(snapshot, now) or now for snapshot in counted) + RETRY_WINDOW


# What a note says of a fetch that was started and not seen to end.
INTERRUPTED = "interrupted: the run ended before this fetch did"


def note_fetch_started(store: ObjectStore, year: int, session_type: str, start_time_utc: str, now: datetime) -> str:
    """Note that a fetch of this calendar entry is being made, before it is.

    A run can end without a word: the scheduler stops it at its time limit,
    the machine goes to sleep, a request never returns. Nothing was then
    noted of the fetch it was in, so the next run took the same session
    first and could end the same way, and no later session had its turn. The
    note is written as a failure before the fetch starts, and is replaced by
    what happened when the fetch ends: its error, or that it succeeded.

    Each one counts: ``failures`` is how many fetches of the entry in a row
    have not succeeded, this one included until it does.

    Returns a name for this attempt, to be given back with its outcome. Two
    runs can be fetching one session at once, and each one's outcome is the
    outcome of its own start and of no other's.
    """
    attempt = secrets.token_hex(4)
    _note(store, year, session_type, start_time_utc, now, INTERRUPTED, attempt, "started")
    return attempt


def note_failed_fetch(
    store: ObjectStore,
    year: int,
    session_type: str,
    start_time_utc: str,
    error: str,
    now: datetime,
    attempt: str | None = None,
) -> None:
    """Note that a fetch of this calendar entry failed just now.

    A failed fetch archives nothing, so without this a run could not tell a
    session that failed an hour ago from one never tried, and would try the
    same ones first every time. ``attempt`` is what ``note_fetch_started``
    returned for it.
    """
    _note(store, year, session_type, start_time_utc, now, error, attempt, "failed")


def note_fetch_succeeded(
    store: ObjectStore, year: int, session_type: str, start_time_utc: str, now: datetime, attempt: str | None = None
) -> None:
    """Note that the entry was fetched: it has no failure to its name, and its count starts again."""
    _note(store, year, session_type, start_time_utc, now, "", attempt, "succeeded")


def _note(
    store: ObjectStore,
    year: int,
    session_type: str,
    start_time_utc: str,
    now: datetime,
    error: str,
    attempt: str | None,
    what: str,
) -> None:
    key = layout.attempt_key(year, session_type, start_time_utc)
    now = now.astimezone(timezone.utc)
    # Written against what is there, like everything else that changes in
    # place (rule 2): two runs can note the same session a moment apart and
    # finish their writes in either order.
    for _ in range(3):
        current = store.get(key)
        noted, failures, theirs = None, 0, None
        try:
            if current is not None:
                payload = json.loads(current.data)
                noted = parse_utc(payload["failed_at"])
                failures = _whole_number(payload.get("failures", 1))
                theirs = payload.get("attempt") if isinstance(payload.get("attempt"), str) else None
        except Exception:
            noted, failures, theirs = None, 0, None
        # The note of a fetch that has started and not ended, when that fetch
        # is not the one being noted now.
        another_is_going = noted is not None and theirs is not None and theirs != attempt
        if what == "started":
            # Counted from the start, and until it succeeds.
            written: dict[str, Any] | None = {
                "failed_at": format_utc(now), "error": error, "failures": failures + 1, "attempt": attempt,
            }
            # Only over an older note: a clock that is behind does not undo
            # what a clock that is right has written.
            if noted is not None and now <= noted <= now + CLOCK_TOLERANCE:
                return
        elif what == "failed":
            if another_is_going:
                # This fetch was counted when it started, and the note is now
                # of a later one. Its failure changes nothing in it.
                return
            if noted is None and attempt is not None:
                # Its start is no longer noted: the session has been fetched
                # since, by another run. That is the last word.
                if current is not None:
                    return
            mine = noted is not None and theirs is not None and theirs == attempt
            if not mine and noted is not None and now <= noted <= now + CLOCK_TOLERANCE:
                return
            written = {
                "failed_at": format_utc(now),
                "error": error[:500],
                # Its own start counted it already.
                "failures": failures if mine else failures + 1,
                # It has ended: the note is of no fetch that is still going.
                "attempt": None,
            }
        else:
            if another_is_going:
                # Fetched, and another fetch of it is still going. That one
                # is all there is left to count.
                written = {**json.loads(current.data), "failures": 1}  # type: ignore[union-attr]
            elif current is None:
                return
            else:
                written = {"succeeded_at": format_utc(now)}
        data = dump_json(written)
        try:
            if current is None:
                store.put(key, data, if_absent=True)
            else:
                store.put(key, data, if_match=current.etag)
            return
        except PreconditionFailed:
            continue


def failing_fetches(store: ObjectStore, now: datetime) -> dict[str, tuple[int, str]]:
    """How many fetches in a row have failed for each calendar entry that is failing, and the last error."""
    failing: dict[str, tuple[int, str]] = {}
    for key in failed_fetches(store, now):
        found = store.get(key)
        try:
            payload = json.loads(found.data) if found is not None else {}
            failing[key] = (_whole_number(payload.get("failures", 1)), str(payload.get("error") or ""))
        except Exception:
            continue
    return failing


def failed_fetches(store: ObjectStore, now: datetime) -> dict[str, datetime]:
    """When the last fetch of each calendar entry failed, by ``layout.attempt_key``.

    A note that cannot be read, or that is stamped with a time that has not
    come, is left out: the entry then counts as never having failed.
    """
    now = now.astimezone(timezone.utc)
    failed: dict[str, datetime] = {}
    for item in store.list(layout.ATTEMPTS_PREFIX):
        found = store.get(item.key)
        try:
            at = parse_utc(json.loads(found.data)["failed_at"]) if found is not None else None
        except Exception:
            continue
        if at is not None and at <= now + CLOCK_TOLERANCE:
            failed[item.key] = at
    return failed


def plausible_fetch_time(snapshot: Snapshot, now: datetime) -> datetime | None:
    """When the snapshot was fetched, or ``None`` if its stamp cannot be right.

    The stamp is the fetching machine's. One whose clock ran two weeks fast
    would otherwise put off every retry, and the partial publication, by two
    weeks on every other machine. One whose clock ran slow would close the
    retry window before it had opened: a session cannot have been fetched
    before it started.
    """
    try:
        fetched = parse_utc(snapshot.fetched_at)
        started = snapshot.identity.start_time
    except Exception:
        return None
    return fetched if started - CLOCK_TOLERANCE <= fetched <= now + CLOCK_TOLERANCE else None


def restore_snapshot(store: ObjectStore, snapshot: Snapshot, cache_dir: Path) -> Path:
    """Unpack a snapshot's parsed feeds into ``cache_dir`` as a FastF1 cache."""
    described = snapshot.objects.get(PARSED_ARCHIVE)
    if not described:
        raise ArchiveError(f"Snapshot {snapshot.snapshot_id} lists no parsed feeds")
    key = f"{layout.snapshot_prefix(snapshot.session_key, snapshot.snapshot_id)}{PARSED_ARCHIVE}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f1data-restore-") as scratch:
        archive_path = Path(scratch) / PARSED_ARCHIVE
        if not store.download_file(key, archive_path):
            raise ArchiveError(f"Snapshot {snapshot.snapshot_id} is missing {PARSED_ARCHIVE}")
        actual = _describe(archive_path)
        if actual != {"size_bytes": described.get("size_bytes"), "sha256": described.get("sha256")}:
            raise ArchiveError(
                f"{key} does not match its snapshot: expected {described}, found {actual}"
            )
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(cache_dir, filter="data")
    return cache_dir


def archive_directory(
    store: ObjectStore, source: Path, name: str, now: datetime | None = None
) -> dict[str, Any]:
    """Keep a whole directory in the archive as one compressed file.

    For data that exists on one machine only and is not yet in snapshot form:
    the FastF1 cache the sessions before the rewrite were built from (AR-11).
    Nothing is parsed, so nothing has to load for the copy to succeed. A
    description of the contents is written beside it, last.
    """
    if not _LEGACY_NAME.match(name):
        raise ValueError(f"Use lowercase letters, digits and hyphens for the name, not {name!r}")
    source = source.resolve()
    if not source.is_dir():
        raise ArchiveError(f"{source} is not a directory")
    files = sorted(path for path in source.rglob("*") if path.is_file())
    if not files:
        raise ArchiveError(f"{source} holds no files")

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # The random part is what keeps two copies started in the same second
    # from landing on one key, where the second would replace the first.
    key = f"{layout.ARCHIVE_PREFIX}legacy/{name}-{new_snapshot_id(now)}"
    with tempfile.TemporaryDirectory(prefix="f1data-legacy-") as scratch:
        packed = Path(scratch) / "directory.tar.gz"
        with tarfile.open(packed, "w:gz", compresslevel=6) as archive:
            for path in files:
                archive.add(path, arcname=path.relative_to(source).as_posix())
        description = {
            "name": name,
            "created_at": format_utc(now),
            "archive": {"key": f"{key}.tar.gz", **_describe(packed)},
            "file_count": len(files),
            "total_bytes": sum(path.stat().st_size for path in files),
            "files": [
                {"path": path.relative_to(source).as_posix(), "size_bytes": path.stat().st_size}
                for path in files
            ],
        }
        store.put_file(f"{key}.tar.gz", packed, content_type="application/gzip")
    uploaded = store.head(f"{key}.tar.gz")
    if uploaded is None or uploaded.size != description["archive"]["size_bytes"]:
        raise ArchiveError(f"{key}.tar.gz did not arrive whole")
    store.put(f"{key}.json", dump_json(description), if_absent=True)
    return description


def read_extras(store: ObjectStore, snapshot: Snapshot) -> dict[str, bytes]:
    """The feeds archived beside the FastF1 cache, by name, checked against the snapshot."""
    extras: dict[str, bytes] = {}
    prefix = layout.snapshot_prefix(snapshot.session_key, snapshot.snapshot_id)
    for name, described in sorted(snapshot.objects.items()):
        if not name.startswith(EXTRA_PREFIX):
            continue
        found = store.get(f"{prefix}{name}")
        if found is None:
            raise ArchiveError(f"Snapshot {snapshot.snapshot_id} is missing {name}")
        if hashlib.sha256(found.data).hexdigest() != described.get("sha256"):
            raise ArchiveError(f"{prefix}{name} does not match its snapshot")
        extras[name[len(EXTRA_PREFIX):]] = found.data
    return extras


def _extra_content_type(name: str) -> str:
    return "application/json; charset=utf-8" if name.endswith(".json") else "application/octet-stream"


def dump_json(payload: Any) -> bytes:
    """Minified, key-sorted JSON with a trailing newline, the same on every platform."""
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _describe(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return {"size_bytes": path.stat().st_size, "sha256": digest.hexdigest()}
