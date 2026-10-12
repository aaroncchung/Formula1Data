"""Directories of the spool as runs leave them, for the tests of what the next run does with them."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from f1data import spool
from f1data.fetch import FetchedSession
from f1data.httplog import HttpRecorder
from tests.building import FIRST_FETCH
from tests.fakes import make_session, measure
from tests.test_archive import EXTRAS, fetched_session, identity

SNAPSHOT_ID = "20260628T180000Z-0badcafe"


@contextmanager
def a_fetch_in_hand(
    root: Path,
    year: int = 2026,
    event: int | str = 8,
    session_type: str = "R",
    store: str = "a store",
    now: datetime = FIRST_FETCH,
    **more: str | None,
) -> Iterator[Path]:
    """The directory of a fetch that has begun, held as the run making it holds it."""
    directory = spool.new_fetch_path(root, now)
    with spool.holding(directory) as mine:
        assert mine
        spool.begin(directory, year, event, session_type, store, now, **more)
        yield directory


def left_started(root: Path, *of: object, **more: object) -> Path:
    """What a run leaves when it is stopped in the middle of a fetch: part of a session."""
    with a_fetch_in_hand(root, *of, **more) as directory:  # type: ignore[arg-type]
        (directory / spool.CACHE_DIRECTORY / "2026").mkdir(parents=True)
    return directory


def left_served(root: Path, *of: object, served_at: datetime = FIRST_FETCH, **more: object) -> Path:
    """What a run leaves when F1 served the session and it could not be written down."""
    with a_fetch_in_hand(root, *of, **more) as directory:  # type: ignore[arg-type]
        fetched_session(directory)
        spool.mark_served(directory, served_at)
    return directory


def left_whole(
    root: Path, *of: object, fetched_at: datetime = FIRST_FETCH, snapshot_id: str = SNAPSHOT_ID, **more: object
) -> Path:
    """What a run leaves when the session was fetched and the archive would not take it."""
    with a_fetch_in_hand(root, *of, **more) as directory:  # type: ignore[arg-type]
        spool.keep(directory, fetched_session(directory), fetched_at, snapshot_id)
    return directory


def as_read_back(cache_dir: Path) -> FetchedSession:
    """What reading ``fetched_session``'s cache back gives: the same session, and nothing written."""
    return FetchedSession(
        session=None,
        identity=identity(),
        coverage=measure(make_session()),
        cache_dir=cache_dir,
        http=HttpRecorder(),
        attempts=1,
        versions={"fastf1": "3.8.3", "fastf1_cache": 15},
        extras=dict(EXTRAS),
    )
