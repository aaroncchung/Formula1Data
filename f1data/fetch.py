"""Fetch one session from F1's timing archive into a FastF1 cache directory.

This is the only stage that needs a network F1 answers. Everything it reads is
left in ``cache_dir`` in the two forms FastF1 keeps: the parsed feeds
(``*.ff1pkl``) and the raw HTTP responses (``fastf1_http_cache.sqlite``).

Every fetch starts from an empty directory. FastF1 reuses a cached feed for as
long as its cache version matches, so a second fetch over the same directory
returns the first one's data without asking F1, incomplete or not
(docs/architecture-review-findings.md, section 6, rule 6).
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
    resume: bool = False,
) -> FetchedSession:
    """Load a session from F1 into ``cache_dir``, which must be empty.

    Unless ``resume`` says that the directory holds a fetch of this session
    that was cut short (f1data/spool.py). FastF1 then reads back whatever had
    arrived and asks F1 for the rest, as it does between its own attempts.
    Only the requests made this time are in the record of them, so a feed
    read back has no status of F1's beside it: one that is absent is then
    taken as one F1 may yet supply, which is the cautious reading.

    Returns whatever arrived, with its coverage measured. Judging whether that
    is complete is the caller's job; a partial session is still worth keeping
    as a snapshot. Raises ``FetchError`` when F1's session information did
    not arrive, since without its session key there is nothing to file it
    under, and when the weather loaded and its own lines could not be kept
    beside it (``weather_lines_are_kept`` in f1data/extras.py).
    """
    code = session_type_code(session_type)
    if not resume and cache_dir.exists() and any(cache_dir.iterdir()):
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
