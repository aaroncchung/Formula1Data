"""Fetch one session from F1's timing archive into a FastF1 cache directory.

This is the only stage that needs a network F1 answers. Everything it reads is
left in ``cache_dir`` in the two forms FastF1 keeps: the parsed feeds
(``*.ff1pkl``) and the raw HTTP responses (``fastf1_http_cache.sqlite``).

Every fetch starts from an empty directory. FastF1 reuses a cached feed for as
long as its cache version matches, so a second fetch over the same directory
returns the first one's data without asking F1, incomplete or not
(docs/architecture-review-findings.md, section 6, rule 6). A fetch that was
stopped part of the way is therefore not carried on: it is made again.

``read_back`` is the other way into a cache: it loads again a session that a
fetch was served, from that fetch's cache and with every request refused. It
asks F1 for nothing and so adds nothing; it is for a fetch that ran to its
end and was not written down (f1data/spool.py).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from f1data.coverage import measure_coverage
from f1data.extras import CIRCUIT_INFO, WEATHER_SERIES, fetch_extras, weather_lines_are_kept
from f1data.httplog import HttpRecorder
from f1data.identity import SessionIdentity, identity_from_fastf1, session_type_code

F1_ARCHIVE_HOSTS = frozenset({"livetiming.formula1.com", "livetiming-mirror.fastf1.dev"})
HTTP_CACHE_FILE = "fastf1_http_cache.sqlite"

DEFAULT_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 5.0

_logger = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """The session could not be fetched in a form worth keeping."""

    def __init__(self, message: str, http: HttpRecorder | None = None) -> None:
        super().__init__(message)
        # What F1 answered, for a caller that has to report why nothing arrived.
        self.http = http


@dataclass
class FetchedSession:
    session: Any
    identity: SessionIdentity
    coverage: dict[str, Any]
    cache_dir: Path
    http: HttpRecorder
    attempts: int
    versions: dict[str, Any] = field(default_factory=dict)
    # Feeds FastF1 does not load, by name (f1data/extras.py).
    extras: dict[str, bytes] = field(default_factory=dict)
    # What F1 last answered for each feed, by file name: a status, or None
    # when the request got no answer.
    feed_status: dict[str, Any] = field(default_factory=dict)


@contextmanager
def fastf1_cache(cache_dir: Path) -> Iterator[Any]:
    """Point FastF1's process-wide cache at ``cache_dir``, and put it back after.

    FastF1 keeps its HTTP cache open in SQLite. Until that is closed the
    directory cannot be archived reliably, or removed at all on Windows. The
    cache that was active before is restored, so a build of one session can
    run inside a command that keeps a cache of its own for the schedule.
    """
    import fastf1

    previous = fastf1.Cache._CACHE_DIR if fastf1.Cache._requests_session_cached is not None else None
    _close_http_cache(fastf1)
    cache_dir.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache_dir))
    try:
        yield fastf1
    finally:
        _close_http_cache(fastf1)
        if previous and Path(previous).is_dir():
            fastf1.Cache.enable_cache(previous)


def _close_http_cache(fastf1: Any) -> None:
    cached = fastf1.Cache._requests_session_cached
    if cached is not None:
        cached.close()
        fastf1.Cache._requests_session_cached = None


def fetch_session(
    year: int,
    event: int | str,
    session_type: str,
    cache_dir: Path,
    attempts: int = DEFAULT_ATTEMPTS,
    sleep: Any = time.sleep,
) -> FetchedSession:
    """Load a session from F1 into ``cache_dir``, which must be empty.

    Returns whatever arrived, with its coverage measured. Judging whether that
    is complete is the caller's job; a partial session is still worth keeping
    as a snapshot. Raises ``FetchError`` when F1's session information did
    not arrive, since without its session key there is nothing to file it
    under, and when the weather loaded and its own lines could not be kept
    beside it (``weather_lines_are_kept`` in f1data/extras.py).
    """
    code = session_type_code(session_type)
    if cache_dir.exists() and any(cache_dir.iterdir()):
        raise FetchError(f"Fetch needs an empty cache directory, and {cache_dir} is not empty")

    recorder = HttpRecorder()
    session: Any = None
    attempt = 0
    with fastf1_cache(cache_dir) as fastf1, recorder:
        for attempt in range(1, max(1, attempts) + 1):
            seen = len(recorder.records)
            # A new object each time: feeds that arrived are read back from the
            # cache, and only the ones that failed are requested again.
            session = fastf1.get_session(year, event, code)
            session.load(laps=True, telemetry=True, weather=True, messages=True)
            failed = [
                record
                for record in recorder.records[seen:]
                if record.failed and record.host in F1_ARCHIVE_HOSTS
            ]
            if not failed or attempt >= attempts:
                break
            delay = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            _logger.warning(
                "%d request(s) to F1 failed on attempt %d of %d; retrying in %gs",
                len(failed), attempt, attempts, delay,
            )
            sleep(delay)

        try:
            identity = identity_from_fastf1(session)
        except Exception as exc:
            raise FetchError(
                f"F1's session information did not arrive for {year} {event} {code}; "
                f"requests by host and status: {recorder.summary()}",
                http=recorder,
            ) from exc
        extras = fetch_extras(fastf1, session, identity.archive_path)
        if not weather_lines_are_kept(session, extras):
            # Nothing is archived, and the session is fetched again on a
            # later run like any fetch that failed.
            raise FetchError(
                f"FastF1 loaded the weather of {year} {event} {code} and {WEATHER_SERIES} could not be "
                "fetched to go with it. Without the feed's own lines a reading F1 left out is published as "
                f"a zero; requests by host and status: {recorder.summary()}",
                http=recorder,
            )
        coverage = measure_coverage(session, code, extras)
        versions = _versions(fastf1)

    return FetchedSession(
        session=session,
        identity=identity,
        coverage=coverage,
        cache_dir=cache_dir,
        http=recorder,
        attempts=attempt,
        versions=versions,
        extras=extras,
        feed_status=_feed_status(recorder),
    )


def read_back(year: int, event: int | str, session_type: str, cache_dir: Path) -> FetchedSession:
    """Load again a session that a fetch into ``cache_dir`` was served, from that cache alone.

    Every request is refused. FastF1 reads its parsed feeds back as they
    are, and answers out of its cache of responses what it would otherwise
    ask again: the calendar the fetch found the session in, the weather
    lines, the pit stops, the circuit. A response it holds is used however
    old it is, because the request that would replace it fails. So what
    comes back is what that fetch was served, whatever F1, the calendar or
    anything else has changed to since. Nothing is fetched into the cache;
    what FastF1 may write there, a parsed feed that could not be read made
    again from the response it was parsed from, comes out of the cache.

    What only the fetch itself knew is not there to read: what F1 answered
    for each feed, and how many tries it took. A feed that is absent is
    then taken as one F1 may yet supply, which is the cautious reading.

    Raises ``FetchError`` when the session cannot be read back as a fetch
    would have returned it.
    """
    code = session_type_code(session_type)
    if not cache_dir.is_dir() or not any(cache_dir.rglob("*.ff1pkl")):
        raise FetchError(f"There are no parsed feeds to read back under {cache_dir}")
    try:
        # Each request that is refused and answered from the cache is logged
        # by the cache as a failure, with its traceback. Here it is the plan.
        with _quietly("requests_cache"), fastf1_cache(cache_dir) as fastf1, HttpRecorder(forbid_all=True) as recorder:
            session = fastf1.get_session(year, event, code)
            session.load(laps=True, telemetry=True, weather=True, messages=True)
            identity = identity_from_fastf1(session)
            extras = fetch_extras(fastf1, session, identity.archive_path)
            if not weather_lines_are_kept(session, extras):
                raise FetchError(f"The weather was loaded and {WEATHER_SERIES} is not in the cache beside it")
            coverage = measure_coverage(session, code, extras)
            versions = _versions(fastf1)
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"{year} {event} {code} could not be read back from {cache_dir}: {exc}") from exc
    session_dir = cache_dir / identity.archive_path
    if not session_dir.is_dir() or not any(session_dir.glob("*.ff1pkl")):
        # The calendar in the cache led to a session whose feeds are not the
        # ones in the cache.
        raise FetchError(f"What was read back is {identity.archive_path}, and {cache_dir} holds no feeds of it")
    return FetchedSession(
        session=session,
        identity=identity,
        coverage=coverage,
        cache_dir=cache_dir,
        http=recorder,
        attempts=1,
        versions=versions,
        extras=extras,
        feed_status={},
    )


@contextmanager
def _quietly(name: str) -> Iterator[None]:
    """Only errors from a logger and those under it, for as long as the block runs."""
    logger = logging.getLogger(name)
    level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(level)


def f1_is_answering(years: Iterable[int], timeout: float = 30.0) -> bool:
    """Whether F1's archive answers at all just now, asked for a season's index.

    For telling "these sessions cannot be fetched" from "nothing can": a
    network that is down and a host that refuses this address (AR-13) fail
    every session alike, and neither answers this.

    ``years`` are seasons whose index should exist, and one answer is enough.
    The season of the sessions that failed is the wrong one to ask about: a
    season F1 does not hold at all fails every session of its own and says
    nothing of the others.
    """
    import requests
    from fastf1 import _api

    # FastF1 fetches from its mirror when F1 refuses, so the mirror answering
    # is the archive answering.
    for base in (_api.base_url, _api.base_url_mirror):
        for year in years:
            try:
                with requests.get(
                    f"{base}/static/{year}/Index.json", headers=_api.headers, stream=True, timeout=timeout
                ) as response:
                    if response.status_code == 200:
                        return True
            except requests.RequestException:
                continue
    return False


def _feed_status(recorder: HttpRecorder) -> dict[str, Any]:
    """F1's own last answer for each feed, and MultiViewer's for the circuit.

    FastF1's mirror is left out: when F1 says 403 and the mirror then says
    404, the answer that says whether F1 holds the feed is F1's.
    """
    status: dict[str, Any] = {}
    for record in recorder.records:
        if record.host == "livetiming.formula1.com":
            status[record.path.rsplit("/", 1)[-1]] = record.status
        elif record.host == "api.multiviewer.app":
            status[CIRCUIT_INFO] = record.status
    return status


def _versions(fastf1: Any) -> dict[str, Any]:
    import numpy
    import pandas

    return {
        "fastf1": fastf1.__version__,
        # FastF1 discards parsed feeds written under another cache version.
        "fastf1_cache": fastf1.Cache._API_CORE_VERSION,
        "pandas": pandas.__version__,
        "numpy": numpy.__version__,
    }
