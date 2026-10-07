"""A fetched session, kept on this machine until the archive has it.

Fetching is the half of the job that cannot be done again at will: it takes
minutes, F1 answers only some networks, and what F1 serves for a session can
change. The upload that follows can fail on its own account: the connection
drops in a hundred megabytes, the bucket answers 5xx until the SDK gives up,
the machine is put to sleep. The fetched feeds used to live in the run's
scratch directory and went with it, so a session F1 had served in full was
asked for again on the next run, and its first answers were gone.

A fetch is now made in a directory of the spool, and stays there until its
snapshot's marker is in the archive:

    <spool>/<stamp>-<id>/
        cache/           FastF1's cache, as the fetch left it
        extra/<name>     the feeds fetched beside it
        pending.json     written last: everything else a snapshot records

A directory with ``pending.json`` is a whole fetch waiting to be archived. A
run uploads those before it asks F1 for anything, under the snapshot id and
the fetch time they were given when they were fetched, so that a second
attempt writes over the parts of the first and leaves nothing behind without
a marker. A directory without one is a fetch that never finished; it holds
nothing a snapshot could be made of and is swept away once it is a day old.

Two runs do not upload one fetch at once: each takes a lock on the directory
first, and the one that finds it taken leaves it to the other.
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

PENDING_NAME = "pending.json"
CACHE_DIRECTORY = "cache"
EXTRA_DIRECTORY = "extra"
_LOCK_NAME = ".uploading"
_SCHEMA_VERSION = 1
# A directory with no pending.json may be a fetch another run is making now.
_ABANDONED_AFTER_SECONDS = 24 * 60 * 60


def spool_root(environ: dict[str, str] | None = None) -> Path:
    """Where fetched sessions wait: ``F1DATA_SPOOL``, or a directory of this user's own."""
    environ = dict(os.environ) if environ is None else environ
    if environ.get("F1DATA_SPOOL"):
        return Path(environ["F1DATA_SPOOL"])
    if os.name == "nt" and environ.get("LOCALAPPDATA"):
        return Path(environ["LOCALAPPDATA"]) / "f1data" / "spool"
    return Path.home() / ".cache" / "f1data" / "spool"


class _Requests:
    """The requests a fetch made, by host and status, as its recorder summed them up."""

    def __init__(self, by_host: dict[str, dict[str, int]]) -> None:
        self._by_host = by_host

    def summary(self) -> dict[str, dict[str, int]]:
        return self._by_host


@dataclass(frozen=True)
class Spooled:
    """A fetch waiting in the spool: what ``write_snapshot`` takes, and the name it is to be archived under."""

    directory: Path
    fetched: FetchedSession
    fetched_at: datetime
    snapshot_id: str


def new_fetch_directory(root: Path, now: datetime | None = None) -> Path:
    """A directory of the spool for one fetch. FastF1's cache goes in ``<directory>/cache``."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    directory = Path(root) / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    directory.mkdir(parents=True)
    return directory


def keep(directory: Path, fetched: FetchedSession, fetched_at: datetime, snapshot_id: str) -> Spooled:
    """Make a finished fetch a thing that can be archived later, by this run or the next.

    ``fetched.cache_dir`` has to be ``<directory>/cache``. From the moment
    this returns, the directory is whole and is not removed until the
    snapshot's marker is in the archive.
    """
    directory = Path(directory)
    if Path(fetched.cache_dir).resolve() != (directory / CACHE_DIRECTORY).resolve():
        raise ValueError(f"The fetch was not made in {directory / CACHE_DIRECTORY}")
    fetched_at = fetched_at.astimezone(timezone.utc)
    extras = directory / EXTRA_DIRECTORY
    extras.mkdir(exist_ok=True)
    for name, data in fetched.extras.items():
        (extras / name).write_bytes(data)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "fetched_at": fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "identity": fetched.identity.to_json(),
        "coverage": fetched.coverage,
        "versions": fetched.versions,
        "attempts": fetched.attempts,
        "requests_by_host": fetched.http.summary(),
        "feed_status": fetched.feed_status,
        "extras": sorted(fetched.extras),
    }
    # Beside its place and then renamed: a reader sees all of it or none.
    temporary = directory / f"{PENDING_NAME}.tmp"
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(temporary, directory / PENDING_NAME)
    return Spooled(directory, fetched, fetched_at, snapshot_id)


def waiting(root: Path) -> list[Spooled]:
    """Every whole fetch in the spool, oldest first. One that cannot be read is left where it is."""
    root = Path(root)
    if not root.is_dir():
        return []
    found: list[Spooled] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        try:
            payload = json.loads((directory / PENDING_NAME).read_text(encoding="utf-8"))
            if payload["schema_version"] != _SCHEMA_VERSION:
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
            fetched_at = datetime.strptime(payload["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            found.append(Spooled(directory, fetched, fetched_at, str(payload["snapshot_id"])))
        except Exception:
            continue
    return found


@contextmanager
def uploading(directory: Path) -> Iterator[bool]:
    """Hold a spooled fetch while it is archived. Yields False when another run already holds it."""
    with (Path(directory) / _LOCK_NAME).open("a+b") as handle:
        held = _try_lock(handle)
        try:
            yield held
        finally:
            if held:
                _unlock(handle)


def discard(directory: Path) -> None:
    """Remove a fetch that is in the archive, or that failed before it was whole."""
    shutil.rmtree(directory, ignore_errors=True)


def sweep(root: Path, now: float | None = None) -> list[Path]:
    """Remove what a killed fetch left: directories a day old that never became whole fetches."""
    root = Path(root)
    if not root.is_dir():
        return []
    now = time.time() if now is None else now
    removed: list[Path] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        if (directory / PENDING_NAME).is_file():
            continue
        try:
            age = now - directory.stat().st_mtime
        except OSError:
            continue
        if age > _ABANDONED_AFTER_SECONDS:
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(directory)
    return removed


def describe(spooled: Spooled) -> str:
    identity: Any = spooled.fetched.identity
    return f"{identity.year} {identity.meeting_name} {identity.session_name} (session {identity.session_key})"
