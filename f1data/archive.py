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
    weakest_share,
)
from f1data.extras import CIRCUIT_INFO, circuit_corner_count
from f1data.fetch import HTTP_CACHE_FILE, FetchedSession
from f1data.identity import SessionIdentity, format_utc, parse_utc
from f1data.policy import RETRY_WINDOW
from f1data.store import ObjectStore

SNAPSHOT_SCHEMA_VERSION = 1
PARSED_ARCHIVE = "fastf1-cache.tar.gz"
HTTP_ARCHIVE = "http-cache.sqlite.gz"
EXTRA_PREFIX = "extra/"
_LEGACY_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


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

    @property
    def session_key(self) -> int:
        return self.identity.session_key

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


def write_snapshot(store: ObjectStore, fetched: FetchedSession, now: datetime | None = None) -> Snapshot:
    """Archive a fetched session. Call after the fetch has released its cache."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    snapshot_id = new_snapshot_id(now)
    prefix = layout.snapshot_prefix(fetched.identity.session_key, snapshot_id)
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
    for item in store.list(prefix):
        if item.key.endswith(f"/{layout.SNAPSHOT_MARKER}"):
            markers.append(item.key)
        elif item.key.endswith(f"/{layout.REMEASUREMENT_NAME}"):
            remeasured.add(item.key)
    snapshots = []
    for key in markers:
        found = store.get(key)
        if found is None:
            continue
        snapshot = Snapshot.from_json(json.loads(found.data))
        correction = f"{key[: -len(layout.SNAPSHOT_MARKER)]}{layout.REMEASUREMENT_NAME}"
        if correction in remeasured:
            snapshot = _as_remeasured(store, snapshot, correction)
        snapshots.append(_with_corner_count(store, snapshot))
    return snapshots


def write_remeasurement(
    store: ObjectStore, snapshot: Snapshot, coverage: dict[str, Any], now: datetime | None = None
) -> None:
    """Record that a snapshot's feeds, measured again, are not what its record says.

    A snapshot is never rewritten. This goes beside it, and from then on
    every reader of the archive is given the snapshot with these figures:
    the fetch planner, snapshot selection and the next build judge what the
    feeds hold, not what a faulty record claimed (rules 3 and 6).

    The figures are a function of the archived feeds and of the code that
    measures them, so two builds writing here write the same thing.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    store.put(
        f"{layout.snapshot_prefix(snapshot.session_key, snapshot.snapshot_id)}{layout.REMEASUREMENT_NAME}",
        dump_json(
            {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "session_key": snapshot.session_key,
                "measured_at": format_utc(now),
                "pipeline_version": layout.PIPELINE_VERSION,
                "coverage": coverage,
            }
        ),
    )


def _as_remeasured(store: ObjectStore, snapshot: Snapshot, key: str) -> Snapshot:
    """The snapshot with the figures a build measured from its feeds, if they can be read."""
    found = store.get(key)
    # A build loads its session with Jolpica out of reach, so what it measured
    # says nothing of the classification. That stays as the fetch recorded it.
    recorded = {
        str(driver.get("number")): driver.get("classified_laps")
        for driver in snapshot.coverage.get("drivers", {}).values()
    }
    try:
        payload = json.loads(found.data) if found is not None else None
        coverage = payload["coverage"]
        if (
            payload["schema_version"] != SNAPSHOT_SCHEMA_VERSION
            or payload["snapshot_id"] != snapshot.snapshot_id
            or coverage["measurement_version"] != MEASUREMENT_VERSION
        ):
            return snapshot
        drivers = {
            code: {**driver, "classified_laps": recorded.get(str(driver.get("number")))}
            for code, driver in coverage["drivers"].items()
        }
    except (ValueError, KeyError, TypeError, AttributeError):
        # Not something a build wrote. The snapshot stands as it was recorded,
        # and the next build of it writes the figures again.
        return snapshot
    return replace(snapshot, coverage={**coverage, "drivers": drivers})


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


def partial_publication_time(snapshots: list[Snapshot]) -> datetime:
    """When a session still short of a bar may be published as partial (rule 6).

    Until then later fetches may still do better, and a partial publication is
    not what anyone is waiting for. The window runs from the first fetch that
    was measured in full, the same clock the fetch planner retries by; before
    there is one, from the first fetch of any kind.
    """
    counted = [snapshot for snapshot in snapshots if snapshot.measured_in_full] or snapshots
    return min(parse_utc(snapshot.fetched_at) for snapshot in counted) + RETRY_WINDOW


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
