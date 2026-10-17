"""Publish a built session, and derive the index.

The publication rules of docs/architecture-review-findings.md, section 6, live
here:

1. A generation is immutable. It is named by the SHA-256 of its manifest, so
   the same inputs built twice land on the same keys, and a page that pinned a
   generation keeps reading it after a later publication. Nothing here removes
   one. ``prune`` (f1data/prune.py), run by hand, removes a generation no
   pointer names that nothing has written for 30 days.
2. The pointer and the index are written against the version that was read.
   The loser of a conditional write reads again and decides again from current
   inputs; it never resends what it built. A pointer written by a newer
   pipeline version is never replaced.
3. A session is published when its pointer exists. The index is derived from
   the pointers and the schedule on every run, and never merged from files.
7. Everything sits under the format version's prefix.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from f1data import layout
from f1data.archive import Snapshot, dump_json
from f1data.identity import SessionIdentity, format_utc
from f1data.policy import IN_SCOPE_SESSION_TYPES
from f1data.schedule import ScheduledSession, find_scheduled_session
from f1data.store import (
    BINARY_CONTENT_TYPE,
    JSON_CONTENT_TYPE,
    ObjectStore,
    PreconditionFailed,
    content_etag,
)

POINTER_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1
MAX_POINTER_BYTES = 64 * 1024
MAX_ATTEMPTS = 5
UPLOAD_WORKERS = 16

_logger = logging.getLogger(__name__)


class PointerError(RuntimeError):
    """A pointer exists but cannot be trusted. Never treated as "not published"."""


class CalendarUnavailable(RuntimeError):
    """The calendar of a season with sessions published in it did not load, so the index cannot be derived."""


@dataclass(frozen=True)
class Inputs:
    """What a build of one session would be made from, as of now."""

    snapshot: Snapshot
    classification_fingerprint: str | None
    # Carried to the build; not part of what makes two sets of inputs equal.
    context: Any = field(default=None, compare=False, repr=False)
    # Everything else the build takes from outside the archive, as plain JSON
    # that compares equal only when the build would come out the same. Today
    # that is the calendar entry: its round and names go into the artifacts.
    # It is recorded in the pointer, so it has to survive being written and
    # read back unchanged: mappings, strings and whole numbers only.
    also: Any = None

    @property
    def key(self) -> tuple[str, str | None, Any, str]:
        """What a candidate was built from, and judged by. A candidate built
        before a lost write is published only if this has not moved.

        The last part is the snapshot's record as judged. It can move with
        the rest standing still, when a record is corrected in between, and a
        pointer says whether its session met the bars.
        """
        judged_by = hashlib.sha256(dump_json(self.snapshot.coverage)).hexdigest()
        return (self.snapshot.snapshot_id, self.classification_fingerprint, self.also, judged_by)


@dataclass(frozen=True)
class Hold:
    """The session cannot be published yet, and why.

    Either Jolpica has no classification for it, or its best snapshot is short
    of a bar while later fetches may still do better (rule 6).
    """

    reason: str


class NotPublished(Hold):
    """The session is not of a kind that is published at all, and why.

    The build is a race's: a result ranked by laps completed, gaps at the
    flag, stints, pit stops. Made of a practice or a qualifying session it
    gives numbers that mean nothing there. Such a session can be in the
    archive, where it does no harm; nothing is made of it (decision 5).
    """


class DecideAgain(RuntimeError):
    """Raised by a build that found its inputs are not what ``gather`` described.

    A build measures the snapshot it was given. If the feeds are not what the
    archive's record of the snapshot says, the build corrects the record and
    raises this, and the decision is taken again from the corrected record:
    which snapshot is best, and whether the session may be published yet
    (rules 3 and 6). Nothing is published from a judgement that turned out to
    be about some other state of the archive.
    """


class NewerPipeline(RuntimeError):
    """Raised by a build that found a newer pipeline version has been at its inputs.

    The same rule as for a pointer a newer version wrote (rule 2): what the
    newer version did is left alone, and the session is this run's no longer.
    """


@dataclass(frozen=True)
class Pointer:
    session_key: int
    identity: SessionIdentity
    generation: str
    manifest_sha256: str
    manifest_size_bytes: int
    format_version: int
    pipeline_version: int
    snapshot_id: str
    classification_fingerprint: str | None
    complete: bool
    shortfalls: list[dict[str, Any]]
    published_at: str
    previous_generation: str | None = None
    # ``Inputs.also`` of the build this points at. With the snapshot and the
    # classification it is everything the generation was made from.
    also: Any = None
    # The snapshot's record of its feeds, as it stood when this was written:
    # ``Snapshot.record_fingerprint``. A record can be corrected afterwards.
    record: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": POINTER_SCHEMA_VERSION,
            "format_version": self.format_version,
            "pipeline_version": self.pipeline_version,
            "session_key": self.session_key,
            "identity": self.identity.to_json(),
            "generation": self.generation,
            "manifest": {"sha256": self.manifest_sha256, "size_bytes": self.manifest_size_bytes},
            "snapshot_id": self.snapshot_id,
            "classification_fingerprint": self.classification_fingerprint,
            "also": self.also,
            "record": self.record,
            "coverage": {"complete": self.complete, "shortfalls": self.shortfalls},
            "published_at": self.published_at,
            "previous_generation": self.previous_generation,
        }

    @classmethod
    def from_json(cls, payload: Any, session_key: int) -> "Pointer":
        try:
            if payload["schema_version"] != POINTER_SCHEMA_VERSION:
                raise ValueError(f"unsupported schema {payload['schema_version']!r}")
            manifest = payload["manifest"]
            coverage = payload["coverage"]
            pointer = cls(
                session_key=int(payload["session_key"]),
                identity=SessionIdentity.from_json(payload["identity"]),
                generation=payload["generation"],
                manifest_sha256=str(manifest["sha256"]),
                manifest_size_bytes=int(manifest["size_bytes"]),
                format_version=int(payload["format_version"]),
                pipeline_version=int(payload["pipeline_version"]),
                snapshot_id=str(payload["snapshot_id"]),
                classification_fingerprint=payload.get("classification_fingerprint"),
                complete=bool(coverage["complete"]),
                shortfalls=list(coverage.get("shortfalls") or []),
                published_at=str(payload["published_at"]),
                previous_generation=payload.get("previous_generation"),
                also=payload.get("also"),
                record=payload.get("record"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PointerError(f"Pointer for session {session_key} is invalid: {exc}") from exc
        # The generation is named by its manifest's checksum, so a pointer
        # whose two halves disagree cannot be followed either way.
        if (
            pointer.session_key != int(session_key)
            or pointer.identity.session_key != pointer.session_key
            or not layout.is_generation_id(pointer.generation)
            or pointer.generation != pointer.manifest_sha256
        ):
            raise PointerError(f"Pointer for session {session_key} is inconsistent")
        return pointer


@dataclass(frozen=True)
class Candidate:
    """A generation that has been uploaded and is waiting for its pointer."""

    inputs_key: tuple[str, str | None, Any, str]
    generation: str
    manifest_size_bytes: int
    complete: bool
    shortfalls: list[dict[str, Any]]
    record: str


@dataclass(frozen=True)
class Outcome:
    """What a publish attempt did. ``action`` is one of:

    ``published``   the pointer now names a new generation
    ``current``     the published session already matches the inputs
    ``superseded``  another publisher got there first with what was needed
    ``newer``       a newer pipeline version published it, or corrected the
                    record it would be built from; left alone
    ``waiting``     not publishable yet: no classification, or short of a bar
                    with the retry window still open
    ``out_of_scope`` not a race or a sprint: archived, and nothing is made of it
    ``no_snapshot`` nothing in the archive to build from
    ``conflict``    not settled: the pointer write was lost, or the archive's
                    record corrected, on every attempt; the next run decides again
    """

    action: str
    session_key: int
    reason: str | None = None
    generation: str | None = None


def read_pointer(store: ObjectStore, session_key: int) -> tuple[Pointer | None, str | None]:
    """The pointer and its ETag. ``(None, None)`` when the session is not published."""
    found = store.get(layout.pointer_key(session_key))
    if found is None:
        return None, None
    if len(found.data) > MAX_POINTER_BYTES:
        raise PointerError(f"Pointer for session {session_key} is too large")
    try:
        payload = json.loads(found.data)
    except ValueError as exc:
        raise PointerError(f"Pointer for session {session_key} is not JSON") from exc
    return Pointer.from_json(payload, session_key), found.etag


def read_published(store: ObjectStore) -> list[Pointer]:
    """Every published session: one list call, then one read each (rule 3).

    A race or a sprint. A pointer to any other kind of session, which a
    version before this one could write, is passed over here, and so counts
    for nothing wherever the published sessions are counted: the index, the
    seasons whose standings are kept, the sessions looked at again for being
    short. The site does not open one either.
    """
    pointers = []
    for item in store.list(layout.pointers_prefix()):
        session_key = layout.session_key_from_pointer_key(item.key)
        if session_key is None:
            continue
        pointer, _ = read_pointer(store, session_key)
        if pointer is None:
            continue
        if pointer.identity.session_type not in IN_SCOPE_SESSION_TYPES:
            _logger.warning(
                "Session %s has a pointer and is a %s session; nothing but a race or a sprint is published, "
                "and it is passed over",
                session_key,
                pointer.identity.session_name,
            )
            continue
        pointers.append(pointer)
    return sorted(pointers, key=lambda pointer: pointer.session_key)


def rebuild_reason(pointer: Pointer | None, inputs: Inputs) -> str | None:
    """Why the session needs building from ``inputs``, or ``None`` when it does not (rule 3)."""
    if pointer is None:
        return "not published"
    if pointer.pipeline_version < layout.PIPELINE_VERSION:
        return f"pipeline version {pointer.pipeline_version} is older than {layout.PIPELINE_VERSION}"
    if pointer.classification_fingerprint != inputs.classification_fingerprint:
        return "the classification changed"
    if pointer.snapshot_id != inputs.snapshot.snapshot_id:
        return "a different snapshot is now selected"
    if pointer.also != inputs.also:
        # The same snapshot and the same result, built under another calendar
        # entry, is a build with another round or another name in it.
        return "the calendar entry changed"
    if pointer.record != inputs.snapshot.record_fingerprint:
        # Someone has corrected the record since. Whether they were right is
        # for a build to find out, by measuring the feeds again.
        return "the snapshot's record changed"
    return None


def build_manifest(identity: SessionIdentity, files: dict[str, bytes]) -> bytes:
    """The manifest of a generation. Its SHA-256 is the generation's name.

    Nothing in it varies between two builds of the same inputs: no timestamp,
    no host. That is what makes a rebuild land on the same keys.
    """
    if layout.MANIFEST_NAME in files:
        raise ValueError(f"{layout.MANIFEST_NAME} is written by the publisher, not the build")
    return dump_json(
        {
            "format_version": layout.FORMAT_VERSION,
            "pipeline_version": layout.PIPELINE_VERSION,
            "session_key": identity.session_key,
            "identity": identity.to_json(),
            "files": [
                {
                    "path": path,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                for path, data in sorted(files.items())
            ],
        }
    )


def upload_generation(
    store: ObjectStore, identity: SessionIdentity, files: dict[str, bytes]
) -> tuple[str, int]:
    """Upload a generation and return its id and its manifest's size.

    The manifest goes last, so a generation with a manifest is whole. A file
    already there is left only if it is the same bytes; anything missing or
    different is uploaded, whether or not a manifest is present.
    """
    for path in files:
        if not path or path.startswith("/") or ".." in path.split("/") or "\\" in path:
            raise ValueError(f"Invalid artifact path: {path!r}")
    manifest = build_manifest(identity, files)
    generation = hashlib.sha256(manifest).hexdigest()
    prefix = layout.generation_prefix(identity.session_key, generation)
    # Every store names a single-part object by the MD5 of its bytes, so the
    # listing says what is there as well as how much of it.
    present = {item.key[len(prefix):]: item.etag for item in store.list(prefix)}
    pending = [
        (path, data) for path, data in sorted(files.items()) if present.get(path) != content_etag(data)
    ]

    def upload(item: tuple[str, bytes]) -> None:
        path, data = item
        store.put(f"{prefix}{path}", data, content_type=_content_type(path))

    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        # list() so that the first failed upload is raised here.
        list(pool.map(upload, pending))
    if present.get(layout.MANIFEST_NAME) != content_etag(manifest):
        store.put(f"{prefix}{layout.MANIFEST_NAME}", manifest)
    return generation, len(manifest)


def publish_session(
    store: ObjectStore,
    session_key: int,
    gather: Callable[..., Inputs | Hold | None],
    build: Callable[[Inputs], tuple[dict[str, bytes], Snapshot | None]],
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    max_attempts: int = MAX_ATTEMPTS,
) -> Outcome:
    """Bring one session's publication up to date with the archive.

    ``gather(session_key, pointer=..., retry=...)`` selects the snapshot and
    looks up the calendar and the classification, as of the moment it is
    called: it must not answer from anything it looked up before the pointer
    was read. It is given the pointer now in place, and ``retry`` is true on
    every attempt after the first. ``build`` turns those inputs into the
    generation's files; it may also return a snapshot whose coverage is then
    what the pointer records in place of the inputs', and it may raise
    ``DecideAgain``.
    """
    candidate: Candidate | None = None
    unsettled = "lost the pointer write"
    for attempt in range(max_attempts):
        # The guarded read comes first, then everything derived (rule 2). A
        # publisher that decided from a calendar it read earlier could replace
        # a pointer built from a later one, and the write would not conflict.
        pointer, etag = read_pointer(store, session_key)
        # After a lost write no shortcut is taken either: another publisher
        # got in, possibly because something outside the archive moved.
        inputs = gather(session_key, pointer=pointer, retry=attempt > 0)
        if inputs is None:
            return Outcome("no_snapshot", session_key)
        if isinstance(inputs, Hold):
            return Outcome(
                "out_of_scope" if isinstance(inputs, NotPublished) else "waiting",
                session_key,
                reason=inputs.reason,
                generation=pointer.generation if pointer is not None else None,
            )
        if inputs.snapshot.identity.session_type not in IN_SCOPE_SESSION_TYPES:
            # Whatever chose it. A pointer is what makes a session one the
            # site shows, and what is built of any other kind of session is
            # a race's figures for something that was not a race.
            raise PointerError(
                f"Session {session_key} is a {inputs.snapshot.identity.session_name} session, "
                "and only races and sprints are published"
            )
        if inputs.snapshot.session_key != int(session_key):
            # Never one session's snapshot under another session's pointer,
            # whatever handed it over.
            raise PointerError(
                f"Snapshot {inputs.snapshot.snapshot_id} is of session {inputs.snapshot.session_key}, "
                f"not session {session_key}"
            )
        if pointer is not None and pointer.pipeline_version > layout.PIPELINE_VERSION:
            return Outcome(
                "newer",
                session_key,
                reason=f"published by pipeline version {pointer.pipeline_version}",
                generation=pointer.generation,
            )
        reason = rebuild_reason(pointer, inputs)
        if reason is None:
            assert pointer is not None
            action = "superseded" if candidate is not None else "current"
            return Outcome(action, session_key, generation=pointer.generation)

        # A candidate built before a lost write is published only if it is
        # what these inputs would build; otherwise it is dropped and rebuilt.
        if candidate is None or candidate.inputs_key != inputs.key:
            try:
                files, measured = build(inputs)
            except DecideAgain as exc:
                _logger.info("Session %s: %s; deciding again", session_key, exc)
                unsettled = str(exc)
                continue
            except NewerPipeline as exc:
                return Outcome(
                    "newer",
                    session_key,
                    reason=str(exc),
                    generation=pointer.generation if pointer is not None else None,
                )
            generation, manifest_size = upload_generation(store, inputs.snapshot.identity, files)
            judged = measured or inputs.snapshot
            candidate = Candidate(
                inputs_key=inputs.key,
                generation=generation,
                manifest_size_bytes=manifest_size,
                complete=judged.complete,
                shortfalls=[shortfall.to_json() for shortfall in judged.shortfalls()],
                record=judged.record_fingerprint,
            )

        replacement = Pointer(
            session_key=session_key,
            identity=inputs.snapshot.identity,
            generation=candidate.generation,
            manifest_sha256=candidate.generation,
            manifest_size_bytes=candidate.manifest_size_bytes,
            format_version=layout.FORMAT_VERSION,
            pipeline_version=layout.PIPELINE_VERSION,
            snapshot_id=inputs.snapshot.snapshot_id,
            classification_fingerprint=inputs.classification_fingerprint,
            complete=candidate.complete,
            shortfalls=candidate.shortfalls,
            published_at=format_utc(now()),
            previous_generation=_previous(pointer, candidate.generation),
            also=inputs.also,
            record=candidate.record,
        )
        try:
            _conditional_put(store, layout.pointer_key(session_key), dump_json(replacement.to_json()), etag)
        except PreconditionFailed:
            _logger.info("Lost the pointer write for session %s; deciding again", session_key)
            unsettled = "lost the pointer write"
            continue
        return Outcome("published", session_key, reason=reason, generation=candidate.generation)
    return Outcome(
        "conflict",
        session_key,
        reason=f"not settled after {max_attempts} attempts: {unsettled}",
    )


def _previous(pointer: Pointer | None, generation: str) -> str | None:
    """The generation a page could still be reading once the pointer names ``generation``.

    Never ``generation`` itself. A rebuild for an input that does not reach
    the files, such as a change to the calendar row, is the generation
    already published, and the one before it is still the one before. A
    pointer written before this was so can name its own generation there;
    that is dropped.
    """
    if pointer is None:
        return None
    if pointer.generation == generation:
        return pointer.previous_generation if pointer.previous_generation != generation else None
    return pointer.generation


def derive_index(
    pointers: list[Pointer], schedules: dict[int, list[ScheduledSession]]
) -> dict[str, Any]:
    """The index: the calendar, with each published session attached to its entry.

    Only a race or a sprint is attached. Nothing else is published, and a
    pointer to anything else, however it came to be there, is not shown.
    """
    for stray in [pointer for pointer in pointers if pointer.identity.session_type not in IN_SCOPE_SESSION_TYPES]:
        _logger.warning(
            "Session %s is a %s session with a pointer; it is left out of the index",
            stray.session_key,
            stray.identity.session_name,
        )
    pointers = [pointer for pointer in pointers if pointer.identity.session_type in IN_SCOPE_SESSION_TYPES]
    placed: dict[tuple[int, int, str], Pointer] = {}
    unscheduled: list[Pointer] = []
    for pointer in pointers:
        entry = find_scheduled_session(schedules.get(pointer.identity.year, []), pointer.identity)
        if entry is None:
            unscheduled.append(pointer)
            continue
        key = (entry.year, entry.round, entry.session_type)
        # Two pointers on one calendar entry should not happen. If it does,
        # keep the one that started closest and show the other, not drop it.
        other = placed.get(key)
        if other is None:
            placed[key] = pointer
        else:
            closest, displaced = sorted(
                (other, pointer),
                key=lambda item: abs((item.identity.start_time - entry.start_time).total_seconds()),
            )
            placed[key] = closest
            unscheduled.append(displaced)

    seasons = []
    for year in sorted(schedules):
        meetings: dict[int, dict[str, Any]] = {}
        for entry in schedules[year]:
            meeting = meetings.setdefault(
                entry.round,
                {
                    "round": entry.round,
                    "name": entry.meeting_name,
                    "official_name": entry.meeting_official_name,
                    "country": entry.country,
                    "location": entry.location,
                    "date": entry.meeting_date,
                    "format": entry.meeting_format,
                    # F1's own keys for the meeting and its circuit, which a
                    # calendar change does not move as it does the round. The
                    # calendar has neither: they come from a published session
                    # of the meeting, and are null until there is one.
                    "meeting_key": None,
                    "circuit_key": None,
                    "circuit_name": None,
                    "sessions": [],
                },
            )
            session: dict[str, Any] = {
                "type": entry.session_type,
                "name": entry.session_name,
                "start_time_utc": entry.start_time_utc,
                # Whether sessions of this type are published at all. One that
                # is in scope and has no key yet is on its way; one that is
                # not in scope will not come.
                "in_scope": entry.session_type in IN_SCOPE_SESSION_TYPES,
            }
            pointer = placed.get((entry.year, entry.round, entry.session_type))
            if pointer is not None:
                session["session_key"] = pointer.session_key
                session["complete"] = pointer.complete
                if meeting["meeting_key"] is None:
                    meeting["meeting_key"] = pointer.identity.meeting_key
                    meeting["circuit_key"] = pointer.identity.circuit_key
                    meeting["circuit_name"] = pointer.identity.circuit_name
            meeting["sessions"].append(session)
        seasons.append({"year": year, "meetings": [meetings[number] for number in sorted(meetings)]})

    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "format_version": layout.FORMAT_VERSION,
        "seasons": seasons,
        "unscheduled": [
            {
                "session_key": pointer.session_key,
                "year": pointer.identity.year,
                "type": pointer.identity.session_type,
                "name": pointer.identity.session_name,
                "meeting_name": pointer.identity.meeting_name,
                "start_time_utc": pointer.identity.start_time_utc,
                "complete": pointer.complete,
            }
            for pointer in sorted(unscheduled, key=lambda item: item.session_key)
        ],
    }


def publish_index(
    store: ObjectStore,
    load_schedule: Callable[..., list[ScheduledSession]],
    seasons: list[int] | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> str:
    """Rebuild the index from the pointers and the schedule. Returns what happened.

    The index is read before the pointers are listed. Listing first would let
    another publisher's pointer and index land in between; this write would
    then succeed and drop that publisher's session with no conflict raised
    (rule 2). On a conflict the whole sequence starts again from the read.

    The calendar is an input like the pointers, so ``load_schedule(year)`` has
    to read it as it stands when called, on every call. A copy from earlier in
    the run would let this write put an older calendar over the newer one
    another publisher had just derived from, again with no conflict.

    Each season's calendar is read by itself. One asked for in ``seasons``
    with nothing published in it is left out of the index when it will not
    load, as next year's will not before its calendar is out. One with a
    session published in it raises ``CalendarUnavailable``: without it the
    index would move those sessions out of their meetings.
    """
    for _ in range(max_attempts):
        current = store.get(layout.index_key())
        pointers = read_published(store)
        schedules = _schedules(load_schedule, pointers, seasons or [])
        payload = dump_json(derive_index(pointers, schedules))
        if current is not None and current.data == payload:
            return "current"
        try:
            _conditional_put(store, layout.index_key(), payload, current.etag if current else None)
        except PreconditionFailed:
            _logger.info("Lost the index write; deriving it again")
            continue
        return "published"
    return "conflict"


def _schedules(
    load_schedule: Callable[..., list[ScheduledSession]], pointers: list[Pointer], seasons: list[int]
) -> dict[int, list[ScheduledSession]]:
    """The calendar of every season with a session published in it, and of each one asked for that loads."""
    published = {pointer.identity.year for pointer in pointers}
    schedules = {}
    for year in sorted(published | set(seasons)):
        try:
            schedules[year] = load_schedule(year)
        except Exception as exc:
            if year in published:
                raise CalendarUnavailable(
                    f"The calendar of {year} did not load, and sessions of {year} are published: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            _logger.warning(
                "The calendar of %s did not load, and nothing of %s is published; "
                "it is left out of the index: %s: %s",
                year,
                year,
                type(exc).__name__,
                exc,
            )
    return schedules


def _conditional_put(store: ObjectStore, key: str, data: bytes, etag: str | None) -> None:
    if etag is None:
        store.put(key, data, if_absent=True)
    else:
        store.put(key, data, if_match=etag)


def _content_type(path: str) -> str:
    return JSON_CONTENT_TYPE if path.endswith(".json") else BINARY_CONTENT_TYPE
