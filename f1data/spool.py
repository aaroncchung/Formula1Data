"""A fetched session, kept on this machine until the archive has it.

Fetching is the half of the job that cannot be done again at will: it takes
minutes, F1 answers only some networks, and what F1 serves for a session can
change. Everything after the fetch can fail on its own account: the disk
fills, the connection drops in a hundred megabytes of upload, the scheduler
stops the task. The fetched feeds used to live in the run's scratch directory
and went with it, so a session F1 had served in full was asked for again on
a later run, and its first answers were gone.

A fetch is made in a directory of the spool, and stays there until its
snapshot's marker is in the archive:

    <spool>/<stamp>-<id>.lock    held by the run that is working on the fetch
    <spool>/<stamp>-<id>/
        intent.json      written first: which session, for which store
        cache/           FastF1's cache
        serving          empty; made with the directory, and renamed
        served           when the fetch has run to its end
        extra/<name>     the feeds fetched beside it
        pending.json     written last: everything else a snapshot records
        discarded        empty; made first when the directory is being removed

One lock, for everything. A run takes it before the directory exists and
holds it while it fetches, writes the fetch down, uploads it and removes it.
Any other run that wants to do anything to the directory takes the lock
first and only then reads what the directory is, so what it acts on is what
is there and not what was there when it looked. The lock is the operating
system's and goes with the process that held it: no fetch is taken for
abandoned by its age, and none for alive by a file a dead run left. It is
beside the directory and not in it, so that the run holding it can remove
the directory whole.

A run that takes the lock of a directory it did not make finds one of these.

* ``pending.json``: a whole fetch waiting to be archived. It is uploaded
  under the snapshot id and the fetch time it was given, so that a second
  attempt writes over the parts of the first and leaves nothing behind
  without a marker.
* ``served`` and no ``pending.json``: F1 served the session, and the run was
  stopped, or the disk was full, before that could be written down. The
  session is read back out of ``cache/`` with every request refused, so that
  what is archived is what that fetch was served and nothing fetched since,
  and is written down then. That is tried on every run until it works.
  Nothing the program does removes such a directory; if it can never be
  read back it stays, and its session is not fetched again, until someone
  looks.
* ``intent.json`` alone: a fetch that was stopped before F1 had served the
  session. What it holds is part of a session, as a failed fetch leaves,
  and it is removed; the session is fetched again from the start in its
  turn. A fetch is never carried on from where it stopped: a snapshot is of
  one fetch, made into an empty cache.
* ``discarded``: a removal that was itself stopped. It is finished.
* None of them: not a fetch. It is removed once it is an hour old.

The mark that F1 served the session has to be made at the moment a disk is
likeliest to be full, since a fetch is what fills it. So it is an empty file
that is there from the start, under the name ``serving``, and marking is a
rename, which needs no room at all. Its date is set to when the fetch ended.

A fetch is for the store it was started for. A run against another store
leaves it as it is.
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
from f1data.store import _rename, _try_lock, _unlock

INTENT_NAME = "intent.json"
PENDING_NAME = "pending.json"
SERVING_NAME = "serving"
SERVED_NAME = "served"
DISCARDED_NAME = "discarded"
CACHE_DIRECTORY = "cache"
EXTRA_DIRECTORY = "extra"
LOCK_SUFFIX = ".lock"
# What is written, and what is read: the records of the version before this
# one say the same things, and a fetch it left is as good as one of this
# version's.
_SCHEMA_VERSION = 2
_SCHEMA_VERSIONS_READ = (1, 2)
_LOCK_TRIES = 5
# A directory with no record in it is one that something other than a fetch
# left. So is a lock with no directory, once the run that made it has had
# time to make the directory.
_NOT_A_FETCH_AFTER_SECONDS = 60 * 60
_STAMP = "%Y-%m-%dT%H:%M:%SZ"

# The directories whose lock this process holds.
_HELD: set[str] = set()


class UnreadableError(ValueError):
    """A directory of the spool is a fetch by the record in it, and that record cannot be read."""


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
    # What the fetch was begun as, where the directory still says.
    started: "Unfinished | None" = None


@dataclass(frozen=True)
class Unfinished:
    """A fetch that was started and has not been written down as whole."""

    directory: Path
    year: int
    event: int | str
    session_type: str
    store: str
    started_at: datetime
    # When the fetch ran to its end: F1 served the session. None if it did not.
    served_at: datetime | None = None
    # The calendar entry's start, when the fetch was planned from the
    # calendar: what the note of its outcome is filed under.
    start_time_utc: str | None = None
    # The name the note of the fetch knows it by (f1data/archive.py).
    attempt: str | None = None

    @property
    def served(self) -> bool:
        return self.served_at is not None


@dataclass(frozen=True)
class Discarded:
    """A directory whose removal was begun."""

    directory: Path


# --- the lock ---------------------------------------------------------------


@contextmanager
def holding(directory: Path) -> Iterator[bool]:
    """Hold the lock of a directory of the spool, which need not exist yet. Yields False when another holds it.

    Everything that changes a directory is done inside this, and so is the
    reading that decides what to do with it.
    """
    directory = Path(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    lock = directory.with_name(directory.name + LOCK_SUFFIX)
    name = _name(directory)
    # A second hold in this process is refused like another process's.
    handle = None if name in _HELD else _take(lock)
    held, gone = handle is not None, False
    try:
        if held:
            _HELD.add(name)
        try:
            yield held
        finally:
            if handle is not None:
                _HELD.discard(name)
                gone = not directory.exists()
                _unlock(handle)
    finally:
        if handle is not None:
            handle.close()
        if gone:
            # With the directory gone the lock guards nothing. Whoever
            # opened it meanwhile takes it, finds it is no longer the file
            # of that name or finds no directory, and does nothing.
            try:
                lock.unlink()
            except OSError:
                pass


def _take(lock: Path) -> Any:
    """Open a lock file and lock it. The open file, or ``None`` when another holds the lock.

    A lock file is removed when its directory is gone, and where a file can
    be removed while it is open, a process that opened it before that and
    locks it after holds a lock on a file nobody else can reach: the next to
    come makes a new file of the same name and holds that. So a lock counts
    only if, once it is held, the name still leads to the file that was
    locked. If it does not, the file was removed in between, and the lock
    is taken again on whatever the name leads to now.
    """
    for _ in range(_LOCK_TRIES):
        handle = lock.open("a+b")
        if not _try_lock(handle):
            handle.close()
            return None
        if _is_the_file_named(handle, lock):
            return handle
        _unlock(handle)
        handle.close()
    return None


def _is_the_file_named(handle: Any, path: Path) -> bool:
    try:
        held, named = os.fstat(handle.fileno()), os.stat(path)
    except OSError:
        return False
    return (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)


def _name(directory: Path) -> str:
    return os.path.normcase(os.path.abspath(directory))


def _must_hold(directory: Path) -> None:
    if _name(directory) not in _HELD:
        raise RuntimeError(f"{directory} is changed without its lock being held")


# --- what a run does with the directory it holds ----------------------------


def new_fetch_path(root: Path, now: datetime | None = None) -> Path:
    """A name for a fetch that is about to be made. Nothing is created."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return Path(root) / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def begin(
    directory: Path,
    year: int,
    event: int | str,
    session_type: str,
    store: str,
    now: datetime | None = None,
    start_time_utc: str | None = None,
    attempt: str | None = None,
) -> Path:
    """Make the directory of a fetch and write into it what the fetch is of. Returns where its cache goes.

    Under the lock, which the caller took before the directory existed:
    there is no moment at which another run can find the directory and not
    find it held.
    """
    directory = Path(directory)
    _must_hold(directory)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    directory.mkdir(parents=True)
    (directory / SERVING_NAME).touch()
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
            "attempt": attempt,
        },
    )
    return directory / CACHE_DIRECTORY


def mark_served(directory: Path, at: datetime | None = None) -> None:
    """Mark a fetch as one F1 has served, when it has run to its end and before anything else is written.

    ``at`` is when it ended, which the mark is dated with: a run that reads
    the session back later archives it as fetched then.
    """
    _must_hold(directory)
    serving, served = Path(directory) / SERVING_NAME, Path(directory) / SERVED_NAME
    if served.is_file():
        return
    try:
        if at is not None:
            os.utime(serving, (at.timestamp(), at.timestamp()))
        _rename(serving, served)
    except OSError:
        # The file made for this is gone, or something has it open. Made
        # afresh, then: that needs a little room, and may fail for the want
        # of it, which is raised.
        served.touch()
        if at is not None:
            os.utime(served, (at.timestamp(), at.timestamp()))


def keep(directory: Path, fetched: FetchedSession, fetched_at: datetime, snapshot_id: str) -> Spooled:
    """Write a fetch down as whole: a thing this run or a later one can archive.

    ``fetched.cache_dir`` has to be ``<directory>/cache``. If this fails the
    directory is left as it is, with everything F1 sent in its cache.
    """
    directory = Path(directory)
    _must_hold(directory)
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


def discard(directory: Path) -> None:
    """Remove a directory: a fetch that is in the archive, one F1 did not serve, or what is not a fetch.

    Marked first, so that a removal that is stopped part of the way is not
    afterwards taken for a fetch with some of its files missing. If it
    cannot be marked nothing is removed, and that is raised.
    """
    directory = Path(directory)
    _must_hold(directory)
    if not directory.is_dir():
        return
    marker = directory / DISCARDED_NAME
    marker.touch()
    for child in directory.iterdir():
        if child.name == DISCARDED_NAME:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass
    # Something may be held open by an indexer or a scanner for the moment
    # it takes to look. Then the mark stays, and a later run finishes this.
    if not any(child.name != DISCARDED_NAME for child in directory.iterdir()):
        try:
            marker.unlink()
            directory.rmdir()
        except OSError:
            pass


def read(directory: Path) -> Spooled | Unfinished | Discarded | None:
    """What a directory of the spool is, by what is in it now. ``None`` when it is not a fetch.

    Raises ``UnreadableError`` when it is one by its record and the record
    cannot be read. To act on the answer, ask under ``holding``.
    """
    directory = Path(directory)
    if (directory / DISCARDED_NAME).is_file():
        return Discarded(directory)
    try:
        if (directory / PENDING_NAME).is_file():
            return _whole(directory)
        if (directory / INTENT_NAME).is_file():
            return _started(directory)
        if (directory / SERVED_NAME).is_file():
            # Not what a fetch leaves, and not rubbish either: something F1
            # served may be in it.
            raise ValueError("marked as a session F1 served, with nothing to say which")
    except Exception as exc:
        raise UnreadableError(f"{directory}: {type(exc).__name__}: {exc}") from exc
    return None


def is_stale(directory: Path, now: float | None = None) -> bool:
    """Whether a directory that is not a fetch has been there long enough to be removed."""
    now = time.time() if now is None else now
    try:
        return now - Path(directory).stat().st_mtime > _NOT_A_FETCH_AFTER_SECONDS
    except OSError:
        return False


# --- looking at the spool without holding anything --------------------------


def directories(root: Path) -> list[Path]:
    """Every directory of the spool, oldest first."""
    root = Path(root)
    return sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


def waiting(root: Path, store: str | None = None) -> list[Spooled]:
    """Every whole fetch in the spool, oldest first; with ``store``, those made for it.

    As it stood when it was looked at: another run may be at any of them.
    """
    return [
        found
        for found in _readable(root)
        if isinstance(found, Spooled) and (store is None or is_for(found.store, store))
    ]


def unfinished(root: Path, store: str | None = None) -> list[Unfinished]:
    """Every fetch that was started and not written down as whole, oldest first, as it stood when looked at."""
    return [
        found
        for found in _readable(root)
        if isinstance(found, Unfinished) and (store is None or is_for(found.store, store))
    ]


def unreadable(root: Path) -> list[Path]:
    """The directories that are a fetch by the record in them, where that record cannot be read."""
    found: list[Path] = []
    for directory in directories(root):
        try:
            read(directory)
        except UnreadableError:
            found.append(directory)
    return found


def sweep_locks(root: Path, now: float | None = None) -> None:
    """Remove the locks of directories that are gone.

    Not a lock a run has just made for a directory it is about to make.
    """
    root = Path(root)
    now = time.time() if now is None else now
    if not root.is_dir():
        return
    for lock in root.glob(f"*{LOCK_SUFFIX}"):
        directory = lock.with_name(lock.name[: -len(LOCK_SUFFIX)])
        try:
            if directory.exists() or now - lock.stat().st_mtime <= _NOT_A_FETCH_AFTER_SECONDS:
                continue
        except OSError:
            continue
        # Taking it and finding no directory is all it takes: ``holding``
        # removes the lock of a directory that is gone.
        with holding(directory):
            pass


def describe(spooled: Spooled) -> str:
    identity: Any = spooled.fetched.identity
    return f"{identity.year} {identity.meeting_name} {identity.session_name} (session {identity.session_key})"


def _readable(root: Path) -> list[Spooled | Unfinished]:
    found: list[Spooled | Unfinished] = []
    for directory in directories(root):
        try:
            state = read(directory)
        except UnreadableError:
            continue
        if isinstance(state, (Spooled, Unfinished)):
            found.append(state)
    return found


def _whole(directory: Path) -> Spooled:
    payload = json.loads((directory / PENDING_NAME).read_text(encoding="utf-8"))
    if payload["schema_version"] not in _SCHEMA_VERSIONS_READ or not isinstance(payload["store"], str):
        raise ValueError(f"written down in a form this version does not read (schema {payload['schema_version']!r})")
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
    try:
        started: Unfinished | None = _started(directory)
    except Exception:
        # A whole fetch is whole without it. Only the note of the fetch
        # cannot then be found.
        started = None
    return Spooled(directory, fetched, fetched_at, str(payload["snapshot_id"]), payload["store"], started)


def _started(directory: Path) -> Unfinished:
    intent = _intent(directory)
    served = directory / SERVED_NAME
    return Unfinished(
        directory=directory,
        year=int(intent["year"]),
        event=intent["event"] if isinstance(intent["event"], (int, str)) else str(intent["event"]),
        session_type=str(intent["session_type"]),
        store=intent["store"],
        started_at=datetime.strptime(intent["started_at"], _STAMP).replace(tzinfo=timezone.utc),
        served_at=(
            datetime.fromtimestamp(served.stat().st_mtime, timezone.utc).replace(microsecond=0)
            if served.is_file()
            else None
        ),
        start_time_utc=intent.get("start_time_utc") if isinstance(intent.get("start_time_utc"), str) else None,
        attempt=intent.get("attempt") if isinstance(intent.get("attempt"), str) else None,
    )


def _intent(directory: Path) -> dict[str, Any]:
    intent = json.loads((Path(directory) / INTENT_NAME).read_text(encoding="utf-8"))
    if intent["schema_version"] not in _SCHEMA_VERSIONS_READ or not isinstance(intent["store"], str):
        raise ValueError(f"says what it is a fetch of in a form this version does not read (schema {intent['schema_version']!r})")
    return intent


def is_for(recorded: str, store: str) -> bool:
    """Whether a fetch recorded as made for ``recorded`` is for ``store``.

    The version before this one named a bucket without its account,
    ``r2:<bucket>``. A fetch it left is taken for the bucket of that name in
    the account now in use: there was one account then.
    """
    if recorded == store:
        return True
    return (
        recorded.startswith("r2:")
        and "/" not in recorded
        and store.startswith("r2:")
        and store.partition("/")[2] == recorded[3:]
    )


def _write_whole(path: Path, payload: dict[str, Any]) -> None:
    """Beside its place and then renamed: a reader sees all of it or none."""
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=1), encoding="utf-8")
    # Tried again for a moment where a scanner has the file open (f1data/store.py).
    _rename(temporary, path)
