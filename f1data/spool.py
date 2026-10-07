"""A fetched session, kept on this machine until the archive has it.

Fetching is the half of the job that cannot be done again at will: it takes
minutes, F1 answers only some networks, and what F1 serves for a session can
change. Everything after the fetch can fail on its own account: the disk
fills, the connection drops in a hundred megabytes of upload, the scheduler
stops the task. The fetched feeds used to live in the run's scratch directory
and went with it, so a session F1 had served in full was asked for again on
a later run, and its first answers were gone.

A fetch is made in a directory of the spool, which says what it is from
before it starts until its snapshot's marker is in the archive:

    <spool>/<stamp>-<id>/
        intent.json      written first: which session, for which store
        .fetching        locked for as long as a run is fetching into it
        cache/           FastF1's cache
        extra/<name>     the feeds fetched beside it
        pending.json     written last: everything else a snapshot records

and a run finds each directory in one of three states.

* ``pending.json`` is there: a whole fetch waiting to be archived. A run
  uploads those before it asks F1 for anything, under the snapshot id and
  the fetch time they were given, so that a second attempt writes over the
  parts of the first and leaves nothing behind without a marker.
* No ``pending.json``, and nobody holds ``.fetching``: a fetch that was cut
  short, by a kill, a full disk or a crash, at any point up to the last. It
  is fetched again into the same directory. FastF1 reads back from its cache
  whatever had arrived and asks F1 only for the rest, so a session that was
  fetched in full and could not be written down costs F1 nothing more. This
  is done once for a fetch. One that is cut short a second time is let go,
  and its session waits its turn like any other that failed: finishing what
  was started must not become the thing every run begins with and dies in.
* Somebody holds ``.fetching``: another run is at it, and it is left alone.
  The lock is the operating system's and goes with the process that held
  it, so no fetch is taken for abandoned by its age, and none for alive by
  a file a dead run left.

A fetch is for the store it was started for. A run against another store
neither uploads it nor finishes it.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from f1data.fetch import FetchedSession
from f1data.identity import SessionIdentity
from f1data.store import _try_lock, _unlock

INTENT_NAME = "intent.json"
PENDING_NAME = "pending.json"
CACHE_DIRECTORY = "cache"
EXTRA_DIRECTORY = "extra"
_FETCHING_LOCK = ".fetching"
_UPLOADING_LOCK = ".uploading"
_SCHEMA_VERSION = 1
# A directory with no intent in it is one a run has made and not yet written
# its intent into, for an instant, or something that is not a fetch at all.
_NOT_A_FETCH_AFTER_SECONDS = 60 * 60
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def spool_root(environ: dict[str, str] | None = None) -> Path:
    """Where fetched sessions wait: ``F1DATA_SPOOL``, or a directory of this user's own."""
    environ = dict(os.environ) if environ is None else environ
    if environ.get("F1DATA_SPOOL"):
        return Path(environ["F1DATA_SPOOL"])
    if os.name == "nt" and environ.get("LOCALAPPDATA"):
        return Path(environ["LOCALAPPDATA"]) / "f1data" / "spool"
    return Path.home() / ".cache" / "f1data" / "spool"


def free_bytes(root: Path) -> int:
    """How much room the spool's disk has, by its nearest directory that exists."""
    place = Path(root)
    while not place.exists() and place.parent != place:
        place = place.parent
    return shutil.disk_usage(place).free


class _Requests:
    """The requests a fetch made, by host and status, as its recorder summed them up."""

    def __init__(self, by_host: dict[str, dict[str, int]]) -> None:
        self._by_host = by_host

    def summary(self) -> dict[str, dict[str, int]]:
        return self._by_host


@dataclass(frozen=True)
class Spooled:
    """A whole fetch waiting in the spool: what ``write_snapshot`` takes, and the name it is to be archived under."""

    directory: Path
    fetched: FetchedSession
    fetched_at: datetime
    snapshot_id: str
    store: str


@dataclass(frozen=True)
class Unfinished:
    """A fetch that was started and has not been written down as whole."""

    directory: Path
    year: int
    event: int | str
    session_type: str
    store: str
    started_at: datetime
    # How many times a run has already set out to finish it.
    resumes: int = 0
    # The calendar entry's start, when the fetch was planned from the
    # calendar: what the note of its outcome is filed under.
    start_time_utc: str | None = None


def new_fetch_directory(
    root: Path,
    year: int,
    event: int | str,
    session_type: str,
    store: str,
    now: datetime | None = None,
    start_time_utc: str | None = None,
) -> Path:
    """A directory of the spool for one fetch, with what the fetch is of written into it.

    FastF1's cache goes in ``<directory>/cache``. The intent is written
    before anything is fetched, so that whatever stops the fetch, what it
    left can be picked up.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    directory = Path(root) / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    directory.mkdir(parents=True)
    _write_whole(
        directory / INTENT_NAME,
        {
            "schema_version": _SCHEMA_VERSION,
            "year": year,
            "event": event,
            "session_type": session_type,
            "store": store,
            "started_at": now.strftime(_STAMP),
            "start_time_utc": start_time_utc,
        },
    )
    return directory


def keep(directory: Path, fetched: FetchedSession, fetched_at: datetime, snapshot_id: str) -> Spooled:
    """Write a finished fetch down as whole: a thing this run or a later one can archive.

    ``fetched.cache_dir`` has to be ``<directory>/cache``. If this fails the
    directory is left as it is, an unfinished fetch with everything F1 sent
    in its cache.
    """
    directory = Path(directory)
    if Path(fetched.cache_dir).resolve() != (directory / CACHE_DIRECTORY).resolve():
        raise ValueError(f"The fetch was not made in {directory / CACHE_DIRECTORY}")
    store = _intent(directory)["store"]
    fetched_at = fetched_at.astimezone(timezone.utc)
    extras = directory / EXTRA_DIRECTORY
    extras.mkdir(exist_ok=True)
    for name, data in fetched.extras.items():
        (extras / name).write_bytes(data)
    _write_whole(
        directory / PENDING_NAME,
        {
            "schema_version": _SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "fetched_at": fetched_at.strftime(_STAMP),
            "store": store,
            "identity": fetched.identity.to_json(),
            "coverage": fetched.coverage,
            "versions": fetched.versions,
            "attempts": fetched.attempts,
            "requests_by_host": fetched.http.summary(),
            "feed_status": fetched.feed_status,
            "extras": sorted(fetched.extras),
        },
    )
    return Spooled(directory, fetched, fetched_at, snapshot_id, store)


def waiting(root: Path, store: str | None = None) -> list[Spooled]:
    """Every whole fetch in the spool, oldest first; with ``store``, those made for it.

    One whose record cannot be read is left where it is.
    """
    found: list[Spooled] = []
    for directory in _directories(root):
        try:
            payload = json.loads((directory / PENDING_NAME).read_text(encoding="utf-8"))
            if payload["schema_version"] != _SCHEMA_VERSION:
                continue
            if store is not None and payload["store"] != store:
                continue
            fetched = FetchedSession(
                session=None,
                identity=SessionIdentity.from_json(payload["identity"]),
                coverage=dict(payload["coverage"]),
                cache_dir=directory / CACHE_DIRECTORY,
                http=_Requests(dict(payload["requests_by_host"])),  # type: ignore[arg-type]
                attempts=int(payload["attempts"]),
                versions=dict(payload["versions"]),
                extras={name: (directory / EXTRA_DIRECTORY / name).read_bytes() for name in payload["extras"]},
                feed_status=dict(payload["feed_status"]),
            )
            fetched_at = datetime.strptime(payload["fetched_at"], _STAMP).replace(tzinfo=timezone.utc)
            found.append(Spooled(directory, fetched, fetched_at, str(payload["snapshot_id"]), str(payload["store"])))
        except Exception:
            continue
    return found


def unfinished(root: Path, store: str | None = None) -> list[Unfinished]:
    """Every fetch that was started and not written down as whole, oldest first.

    Whether a run is still at one of them is for ``fetching`` to say.
    """
    found: list[Unfinished] = []
    for directory in _directories(root):
        if (directory / PENDING_NAME).is_file():
            continue
        try:
            intent = _intent(directory)
            if store is not None and intent["store"] != store:
                continue
            found.append(
                Unfinished(
                    directory=directory,
                    year=int(intent["year"]),
                    event=intent["event"] if isinstance(intent["event"], (int, str)) else str(intent["event"]),
                    session_type=str(intent["session_type"]),
                    store=str(intent["store"]),
                    started_at=datetime.strptime(intent["started_at"], _STAMP).replace(tzinfo=timezone.utc),
                    resumes=int(intent.get("resumes") or 0),
                    start_time_utc=intent.get("start_time_utc")
                    if isinstance(intent.get("start_time_utc"), str)
                    else None,
                )
            )
        except Exception:
            continue
    return found


def note_resumed(directory: Path) -> None:
    """Write into a cut-short fetch that a run has set out to finish it, before it does."""
    intent = _intent(directory)
    _write_whole(Path(directory) / INTENT_NAME, {**intent, "resumes": int(intent.get("resumes") or 0) + 1})


@contextmanager
def fetching(directory: Path) -> Iterator[bool]:
    """Hold a directory of the spool while a session is fetched into it. Yields False when another run does."""
    with _held(Path(directory) / _FETCHING_LOCK) as held:
        yield held


@contextmanager
def uploading(directory: Path) -> Iterator[bool]:
    """Hold a spooled fetch while it is archived. Yields False when another run already holds it."""
    with _held(Path(directory) / _UPLOADING_LOCK) as held:
        yield held


def discard(directory: Path) -> None:
    """Remove a fetch that is in the archive, or one F1 would not serve."""
    shutil.rmtree(directory, ignore_errors=True)


def sweep(root: Path, now: float | None = None) -> list[Path]:
    """Remove what is in the spool and is not a fetch: a directory with neither record in it.

    Not one a run has just made: it is given an hour to say what it is, and
    is left alone for as long as anything holds it.
    """
    now = time.time() if now is None else now
    removed: list[Path] = []
    for directory in _directories(root):
        if (directory / PENDING_NAME).is_file() or (directory / INTENT_NAME).is_file():
            continue
        try:
            if now - directory.stat().st_mtime <= _NOT_A_FETCH_AFTER_SECONDS:
                continue
            with fetching(directory) as free:
                if not free:
                    continue
        except OSError:
            continue
        shutil.rmtree(directory, ignore_errors=True)
        removed.append(directory)
    return removed


def describe(spooled: Spooled) -> str:
    identity: Any = spooled.fetched.identity
    return f"{identity.year} {identity.meeting_name} {identity.session_name} (session {identity.session_key})"


def _directories(root: Path) -> list[Path]:
    root = Path(root)
    return sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


def _intent(directory: Path) -> dict[str, Any]:
    intent = json.loads((Path(directory) / INTENT_NAME).read_text(encoding="utf-8"))
    if intent["schema_version"] != _SCHEMA_VERSION or not isinstance(intent["store"], str):
        raise ValueError(f"{directory} does not say what it is a fetch of")
    return intent


def _write_whole(path: Path, payload: dict[str, Any]) -> None:
    """Beside its place and then renamed: a reader sees all of it or none."""
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _held(path: Path) -> Iterator[bool]:
    with path.open("a+b") as handle:
        held = _try_lock(handle)
        try:
            yield held
        finally:
            if held:
                _unlock(handle)
