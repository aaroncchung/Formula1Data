from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from f1data import layout
from f1data.archive import (
    ArchiveError,
    Snapshot,
    archive_directory,
    dump_json,
    failed_fetches,
    failing_fetches,
    format_utc,
    list_snapshots,
    new_snapshot_id,
    note_failed_fetch,
    note_fetch_started,
    note_fetch_succeeded,
    parse_utc,
    plausible_fetch_time,
    select_snapshot,
    write_snapshot,
)
from f1data.classification import ClassificationMissing, ClassificationUnavailable, fetch_classified_laps
from f1data.config import ConfigError, load_env_file, open_store
from f1data.coverage import evaluate_coverage
from f1data.due import least_recently_failed_first, plan_fetches
from f1data.fetch import (
    F1_ARCHIVE_HOSTS,
    FetchError,
    f1_is_answering,
    fastf1_cache,
    fetch_session,
    read_back,
)
from f1data.httplog import request_timeouts
from f1data.policy import (
    FETCH_STAGE_BUDGET,
    IN_SCOPE_SESSION_TYPES,
    NOT_ANSWERING_AFTER,
    REQUEST_TIMEOUT_SECONDS,
    RUN_IS_OVERDUE_AFTER,
    THE_JOB_IS_FAILING_AFTER_RUNS,
    SPOOL_NEEDS_FREE_BYTES,
)
from f1data.schedule import ScheduledSession, load_schedule
from f1data.spool import (
    CACHE_DIRECTORY,
    Discarded,
    Spooled,
    Unfinished,
    UnreadableError,
    begin,
    describe,
    directories,
    discard,
    free_bytes,
    holding,
    is_stale,
    keep,
    mark_served,
    new_fetch_path,
    spool_root,
    sweep_locks,
)
from f1data.spool import read as read_spool
from f1data.store import JSON_CONTENT_TYPE, ObjectStore, file_etag

# After this many fetches of one session have failed one after the other, a
# run says so at its end, apart from the line it prints for each.
_SAY_SO_AFTER_FAILURES = 3

# After this many fetches have failed one after the other, the batch asks
# whether F1 is answering at all, and stops if it is not, rather than fail its
# way through every session.
_ASK_AFTER_FAILURES_IN_A_ROW = 2

# The feeds whose absence the old loader tolerated or could not see (AR-13, AR-21).
_RAW_CHECK_FEEDS = (
    "SessionInfo.jsonStream",
    "TimingData.jsonStream",
    "TimingAppData.jsonStream",
    "CarData.z.jsonStream",
    "Position.z.jsonStream",
)


def main(argv: list[str] | None = None) -> None:
    # Before the arguments are described: `--store` defaults to F1DATA_STORE,
    # and a default is read when the parser is built. Read afterwards, a
    # store named only in .env was no store at all.
    load_env_file(Path(".env"))
    parser = argparse.ArgumentParser(
        prog="python -m f1data",
        description="Fetch Formula 1 sessions, archive them and publish artifacts.",
    )
    parser.add_argument("--verbose", action="store_true", help="Log at debug level.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser(
        "probe",
        help="Fetch one session from an empty cache and report whether F1 answered in full.",
    )
    probe.add_argument("--year", type=int, required=True)
    probe.add_argument("--event", required=True, help="Round number or event name.")
    probe.add_argument("--session", required=True, help="Session code or name, such as R.")
    probe.add_argument("--cache-dir", type=Path, help="Empty directory to fetch into and keep.")
    probe.add_argument("--report", type=Path, help="Write the full report here as JSON.")
    probe.set_defaults(func=run_probe)

    fetch = subparsers.add_parser(
        "fetch",
        help="Fetch one session from F1 and archive it as a new snapshot. Needs a network F1 answers.",
    )
    _add_store_argument(fetch)
    fetch.add_argument("--year", type=int, required=True)
    fetch.add_argument("--event", required=True, help="Round number or event name.")
    fetch.add_argument("--session", required=True, help="Session code or name, such as R.")
    fetch.set_defaults(func=run_fetch)

    due = subparsers.add_parser(
        "fetch-due",
        help="Fetch every finished session the archive does not yet hold in full. Needs a network F1 answers.",
    )
    _add_store_argument(due)
    due.add_argument(
        "--season",
        type=int,
        action="append",
        help="Season to look at. Repeatable. Defaults to this year, last year, and any year with a "
        "session the archive does not hold in full.",
    )
    due.add_argument("--limit", type=int, help="Fetch at most this many sessions.")
    due.add_argument(
        "--budget-minutes",
        type=float,
        help="Start nothing new after this long: no upload, no question to Jolpica and no fetch. The rest "
        f"is left for the next run. `run` allows {FETCH_STAGE_BUDGET.total_seconds() / 60:g} minutes.",
    )
    due.add_argument("--dry-run", action="store_true", help="Say what would be fetched and stop.")
    due.set_defaults(func=run_fetch_due)

    build = subparsers.add_parser(
        "build",
        help="Build and publish every archived session that needs it, then the index. Never contacts F1.",
    )
    _add_store_argument(build)
    build.add_argument(
        "--session-key", type=int, action="append", help="Limit to these F1 session keys. Repeatable."
    )
    build.add_argument(
        "--season",
        type=int,
        action="append",
        help="List this season in the index even with nothing published. Repeatable.",
    )
    build.add_argument(
        "--recheck",
        action="store_true",
        help="Ask Jolpica for the classification of every session, not only recent ones. "
        "For a result corrected long after its race.",
    )
    build.add_argument(
        "--shard",
        type=_shard,
        help="Build only part I of N, written I/N with I from 0. Sessions are split by key, "
        "so the parts can run side by side; every part still derives the index.",
    )
    build.set_defaults(func=run_build)

    both = subparsers.add_parser(
        "run",
        help="The whole job: build and publish what the archive holds, fetch what is due, and build that. "
        "For a schedule on a machine F1 answers.",
    )
    _add_store_argument(both)
    both.add_argument(
        "--season",
        type=int,
        action="append",
        help="Season to look at. Repeatable. Defaults to this year, last year, and any year with a "
        "session the archive does not hold in full.",
    )
    both.set_defaults(
        func=run_job,
        limit=None,
        dry_run=False,
        session_key=None,
        shard=None,
        budget_minutes=FETCH_STAGE_BUDGET.total_seconds() / 60,
    )

    last = subparsers.add_parser(
        "last-run",
        help="Say when the whole job last finished on the machine that fetches, and how. Fails if that is "
        "too long ago, if it never has, or if its last runs all failed.",
    )
    _add_store_argument(last)
    last.add_argument(
        "--max-age-hours",
        type=float,
        default=RUN_IS_OVERDUE_AFTER.total_seconds() / 3600,
        help="How long ago the last run may have finished. Defaults to two turns of a six-hour schedule.",
    )
    last.add_argument(
        "--max-failed-runs",
        type=int,
        default=THE_JOB_IS_FAILING_AFTER_RUNS,
        help="How many runs in a row may have failed before the job is said to be failing. Defaults to two: "
        "one failed run is said and let pass.",
    )
    last.add_argument(
        "--allow-never",
        action="store_true",
        help="Do not fail when no run has ever been written down. Only for the days between a check being put "
        "in place and the job's first run: a job that is never installed looks the same.",
    )
    last.set_defaults(func=run_last_run)

    copy = subparsers.add_parser(
        "copy-archive",
        help="Copy archive snapshots from one store to another, such as a local spool to R2.",
    )
    copy.add_argument("--from", dest="source", required=True, help="Directory, or r2.")
    copy.add_argument("--to", dest="destination", required=True, help="Directory, or r2.")
    copy.set_defaults(func=run_copy_archive)

    keep = subparsers.add_parser(
        "archive-directory",
        help="Keep a whole directory in the archive as one compressed file, such as an old FastF1 cache.",
    )
    _add_store_argument(keep)
    keep.add_argument("--path", type=Path, required=True, help="The directory to keep.")
    keep.add_argument("--name", required=True, help="A short name, such as legacy-fastf1-cache.")
    keep.set_defaults(func=run_archive_directory)

    schema = subparsers.add_parser(
        "schema",
        help="Write the published format's JSON Schema from the models. Commit the result.",
    )
    schema.add_argument(
        "--check", action="store_true", help="Write nothing; fail if the committed file is out of date."
    )
    schema.set_defaults(func=run_schema)

    args = parser.parse_args(argv)
    _write_utf8()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(name)-14s %(levelname)-7s %(message)s",
    )
    # FastF1 installs its own handler; without this every line prints twice.
    logging.getLogger("fastf1").propagate = False
    with request_timeouts(REQUEST_TIMEOUT_SECONDS):
        raise SystemExit(args.func(args))


def _write_utf8() -> None:
    """Print in UTF-8 whatever the console's code page is.

    A scheduled task has no console, and its output is sent to a file in the
    machine's code page: a meeting with an accent in its name (São Paulo)
    would then raise where the name is printed. And a line at a time: sent
    to a file, output is otherwise held back in blocks, and a run that is
    killed takes its last block with it, the line that says it started
    included.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)  # type: ignore[union-attr]
        except Exception:
            pass


def run_probe(args: argparse.Namespace) -> int:
    """Exit 0 only when every feed arrived and every coverage bar is met."""
    event = int(args.event) if str(args.event).isdigit() else args.event
    temporary = args.cache_dir is None
    cache_dir = Path(tempfile.mkdtemp(prefix="f1data-probe-")) if temporary else args.cache_dir
    report: dict[str, Any] = {"year": args.year, "event": event, "session": args.session}
    try:
        try:
            fetched = fetch_session(args.year, event, args.session, cache_dir)
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, FetchError) and exc.http is not None:
                report["requests_by_host"] = exc.http.summary()
                report["failures"] = exc.http.failure_kinds()
            _print_probe(report)
            _write_report(args.report, report)
            return 1

        shortfalls = evaluate_coverage(fetched.coverage)
        report.update(
            {
                "identity": fetched.identity.to_json(),
                "versions": fetched.versions,
                "attempts": fetched.attempts,
                "requests_by_host": fetched.http.summary(),
                "failures": fetched.http.failure_kinds(),
                "raw_check": _raw_check(fetched.identity.archive_path),
                "coverage": fetched.coverage,
                "shortfalls": [shortfall.to_json() for shortfall in shortfalls],
                "complete": not shortfalls,
            }
        )
        _print_probe(report)
        _write_report(args.report, report)
        return 0 if not shortfalls else 1
    finally:
        if temporary:
            shutil.rmtree(cache_dir, ignore_errors=True)


class _NotArchived(RuntimeError):
    """A session was fetched and could not be archived. It is whole, in the spool."""


class _NotKept(RuntimeError):
    """F1 served a session and it could not be written down as whole. What F1 sent is in the spool."""


class _NoRoom(RuntimeError):
    """A fetch was not started: there is too little room where the spool is."""


def _store_name(spec: str | None) -> str:
    """A name for the store a fetch is made for: the same on every run that uses it, and no other store's.

    A bucket is one account's. Two accounts can each have a bucket of the
    same name, and a fetch made for the one is not the other's to take.
    """
    if (spec or "").strip().lower() == "r2":
        account = os.environ.get("R2_ACCOUNT_ID") or os.environ.get("CLOUDFLARE_ACCOUNT_ID") or ""
        return f"r2:{account}/{os.environ.get('R2_BUCKET', '')}"
    return str(Path(spec or "").resolve())


def _no_room(spool: Path) -> str:
    """Why a fetch is not started for want of room, or nothing when there is room."""
    free = free_bytes(spool)
    if free >= SPOOL_NEEDS_FREE_BYTES:
        return ""
    return (
        f"{free // 1024**2} MB free where the spool is ({spool}), and a fetch is not started with "
        f"less than {SPOOL_NEEDS_FREE_BYTES // 1024**2}"
    )


def _remove(directory: Path) -> bool:
    """Remove from the spool what is not a session F1 served. The caller holds it. False if it could not be."""
    try:
        discard(directory)
    except OSError as exc:
        print(f"{directory} could not be removed from the spool: {exc}. A later run tries again.")
        return False
    return True


def _archive(store: ObjectStore, spooled: Spooled) -> Snapshot:
    """Archive a whole fetch from the spool and remove it from there. The caller holds its directory."""
    snapshot = write_snapshot(store, spooled.fetched, now=spooled.fetched_at, snapshot_id=spooled.snapshot_id)
    try:
        discard(spooled.directory)
    except OSError as exc:
        # It is in the archive. The next run finds its marker there, and
        # removes this then.
        print(f"  Archived, and {spooled.directory} could not be removed from the spool yet: {exc}")
    return snapshot


def _write_down_and_archive(
    store: ObjectStore, directory: Path, fetched: Any, fetched_at: datetime, marked: bool = True
) -> Snapshot:
    """See a session F1 served through to the archive. The caller holds its directory.

    ``_NotKept`` when it could not be written down as whole: a later run
    reads it back from its cache. ``_NotArchived`` when the archive would
    not take it: a later run uploads it. Either way it stays in the spool.
    """
    try:
        spooled = keep(directory, fetched, fetched_at, new_snapshot_id(fetched_at))
    except Exception as exc:
        unmarked = (
            ""
            if marked
            else " It could not be marked as served either: a later run will take it for a fetch that was "
            "stopped part of the way, and remove it."
        )
        raise _NotKept(f"{type(exc).__name__}: {exc}. What F1 sent is in {directory}.{unmarked}") from exc
    try:
        return _archive(store, spooled)
    except Exception as exc:
        raise _NotArchived(f"{type(exc).__name__}: {exc}. Kept in {directory}") from exc


def _fetch_and_archive(
    store: ObjectStore,
    name: str,
    spool: Path,
    year: int,
    event: int | str,
    session_type: str,
    start_time_utc: str | None = None,
    attempt: str | None = None,
) -> Snapshot:
    """Fetch one session into the spool and archive it from there.

    Raises whatever the fetch raises, when F1 did not serve the session:
    nothing is then left in the spool. Once F1 has served it, it stays in
    the spool until it is archived, whatever happens: ``_NotKept`` or
    ``_NotArchived`` say how far it got. A run that is stopped in the middle
    of the fetch leaves part of a session, which the next run removes.

    ``_NoRoom`` when the fetch was not started, for want of room.
    """
    no_room = _no_room(spool)
    if no_room:
        raise _NoRoom(no_room)
    directory = new_fetch_path(spool)
    # Taken before the directory exists and kept until it is gone or the run
    # is done with it: no other run ever finds it and finds it free, unless
    # this one has ended.
    with holding(directory) as mine:
        if not mine:
            raise RuntimeError(f"{directory} is new and is already held")
        cache = begin(directory, year, event, session_type, name, start_time_utc=start_time_utc, attempt=attempt)
        try:
            fetched = fetch_session(year, event, session_type, cache)
        except Exception:
            # Not a session F1 served, so nothing a snapshot could be made of.
            _remove(directory)
            raise
        fetched_at = datetime.now(timezone.utc).replace(microsecond=0)
        # First of all, and needing no room on the disk: from here on the
        # directory is a session F1 served.
        try:
            mark_served(directory, fetched_at)
            marked = True
        except OSError:
            marked = False
        return _write_down_and_archive(store, directory, fetched, fetched_at, marked)


def run_fetch(args: argparse.Namespace) -> int:
    store = _store(args.store)
    event = int(args.event) if str(args.event).isdigit() else args.event
    try:
        snapshot = _fetch_and_archive(store, _store_name(args.store), spool_root(), args.year, event, args.session)
    except _NoRoom as exc:
        print(f"NOT FETCHED: {exc}.")
        return 1
    except (_NotArchived, _NotKept) as exc:
        print(f"FETCHED, NOT ARCHIVED: {exc}. `fetch-due` or `run` sees it through before it fetches anything.")
        return 1
    _print_snapshot(snapshot)
    if snapshot.identity.session_type not in IN_SCOPE_SESSION_TYPES:
        print(
            f"  A {snapshot.identity.session_name} session is kept in the archive and nothing is made of it: "
            "only races and sprints are built and published."
        )
    return 0


@dataclass
class _Seen:
    """What a run found in the spool, and what it could not see through."""

    failed: int = 0
    archived: int = 0
    # The sessions with a fetch still in the spool, which are not to be
    # asked of F1 again: by the key of the calendar entry, and by what the
    # fetch asked for.
    entries: set[str] = field(default_factory=set)
    asked: set[tuple[int, int | str, str]] = field(default_factory=set)

    def keeps(self, found: Spooled | Unfinished) -> None:
        if isinstance(found, Spooled):
            identity = found.fetched.identity
            self.entries.add(layout.attempt_key(identity.year, identity.session_type, identity.start_time_utc))
            if found.started is not None:
                self.keeps(found.started)
            return
        self.asked.add((found.year, found.event, found.session_type.upper()))
        if found.start_time_utc is not None:
            self.entries.add(layout.attempt_key(found.year, found.session_type, found.start_time_utc))

    def has(self, plan: Any) -> bool:
        session = plan.session
        return (
            plan.attempt_key in self.entries
            or (session.year, session.round, session.session_type.upper()) in self.asked
        )


def _see_the_spool_through(
    store: ObjectStore, name: str, spool: Path, time_is_up: Callable[[], bool] = lambda: False
) -> _Seen:
    """Deal with whatever earlier runs left in the spool, before anything is asked of F1.

    Each directory is taken under its lock, and what is done with it is
    decided by what it is found to be then (f1data/spool.py). A session F1
    served is archived, or stays: uploaded if it is whole, read back from
    its cache and written down first if it is not. What is part of a
    session, and what is not a fetch, is removed.
    """
    seen = _Seen()
    elsewhere = 0
    sweep_locks(spool)
    for directory in directories(spool):
        with holding(directory) as mine:
            if not mine:
                # Another run is at it, and sees to it. Whatever it is a
                # fetch of is not fetched again meanwhile.
                try:
                    theirs = read_spool(directory)
                except UnreadableError:
                    continue
                if isinstance(theirs, (Spooled, Unfinished)):
                    if theirs.store == name:
                        seen.keeps(theirs)
                    else:
                        elsewhere += 1
                continue
            try:
                found = read_spool(directory)
            except UnreadableError as exc:
                # Nothing is known of it, so nothing is done with it, and its
                # session is fetched like any other. But a run that leaves
                # one behind has not done all it was for.
                seen.failed += 1
                print(
                    f"ATTENTION: {directory} is a fetch whose record cannot be read ({exc.__cause__}). "
                    "It is left as it is, for someone to look at."
                )
                continue
            if found is None:
                if is_stale(directory) and _remove(directory):
                    print(f"Removed {directory.name} from the spool: it was not a fetch.")
                continue
            if isinstance(found, Discarded):
                _remove(directory)
                continue
            if found.store != name:
                elsewhere += 1
                continue
            if isinstance(found, Unfinished):
                label = f"{found.year} round {found.event} {found.session_type}"
                if not found.served:
                    if _remove(directory):
                        print(
                            f"{label}: a fetch that was stopped before F1 had served the session is removed. "
                            "The session is fetched again in its turn."
                        )
                    continue
            else:
                label = describe(found)
            # A session F1 served. It is archived now, or it stays.
            seen.keeps(found)
            # And the fetch of it succeeded. The run that made it may have
            # been stopped before it could say so, at any point after the
            # mark; said twice, it is said once.
            begun = found.started if isinstance(found, Spooled) else found
            if begun is not None and begun.start_time_utc is not None:
                note_fetch_succeeded(
                    store,
                    begun.year,
                    begun.session_type,
                    begun.start_time_utc,
                    datetime.now(timezone.utc),
                    begun.attempt,
                )
            if time_is_up():
                seen.failed += 1
                print(f"{label}: fetched earlier, and left in the spool: the fetch stage's time is up.")
                continue
            if isinstance(found, Spooled):
                try:
                    snapshot = _archive(store, found)
                except Exception as exc:
                    seen.failed += 1
                    print(f"{label}: fetched earlier, and still NOT ARCHIVED: {type(exc).__name__}: {exc}")
                    continue
                seen.archived += 1
                print(f"{label}: fetched earlier, archived now.")
                _print_snapshot(snapshot)
                continue
            try:
                fetched = read_back(found.year, found.event, found.session_type, directory / CACHE_DIRECTORY)
                snapshot = _write_down_and_archive(store, directory, fetched, found.served_at)
            except _NotArchived as exc:
                seen.failed += 1
                print(f"{label}: a fetch that F1 served is written down now, and NOT ARCHIVED: {exc}")
            except _NotKept as exc:
                seen.failed += 1
                print(f"{label}: a fetch that F1 served could still not be written down: {exc}")
            except Exception as exc:
                # It stays as it is, whatever went wrong: it is the only
                # copy of what F1 served.
                seen.failed += 1
                print(
                    f"{label}: a fetch that F1 served could still not be written down: "
                    f"reading it back failed ({type(exc).__name__}: {exc}). What F1 sent is in {directory}."
                )
            else:
                seen.archived += 1
                print(f"{label}: a fetch that F1 served, written down from its cache and archived.")
                _print_snapshot(snapshot)
    if elsewhere:
        print(f"{elsewhere} fetch(es) in the spool are for another store, and are left for it.")
    return seen


def _last_fetched(snapshots: list[Snapshot], now: datetime) -> dict[str, datetime]:
    """When each calendar entry was last fetched, by ``FetchPlan.attempt_key``, as far as the stamps can be believed."""
    fetched: dict[str, datetime] = {}
    for snapshot in snapshots:
        at = plausible_fetch_time(snapshot, now)
        if at is None:
            continue
        identity = snapshot.identity
        key = layout.attempt_key(identity.year, identity.session_type, identity.start_time_utc)
        fetched[key] = max(fetched.get(key, at), at)
    return fetched


def _seasons_in_scope(now: datetime, snapshots: list[Snapshot], published_short: set[int]) -> list[int]:
    """The seasons a run looks at when it is not told which.

    This year and last, so that the turn of the year drops nothing that
    finished in December. And any year with a session the archive does not
    hold in full: such a session is fetched again for as long as that is so
    (rule 3), however old it is, and it used to stop being looked at on the
    first of January.
    """
    years = {now.year, now.year - 1}
    by_session: dict[int, list[Snapshot]] = {}
    for snapshot in snapshots:
        # Only the sessions the job fetches. A practice session someone
        # archived by hand is never fetched again, short or not, and is no
        # reason to look at its season.
        if snapshot.identity.session_type in IN_SCOPE_SESSION_TYPES:
            by_session.setdefault(snapshot.session_key, []).append(snapshot)
    for session_key, group in by_session.items():
        best = select_snapshot(group)
        if best is not None and (not best.complete or session_key in published_short):
            years.add(best.identity.year)
    return sorted(years)


def run_fetch_due(args: argparse.Namespace) -> int:
    return _fetch_due(args)[0]


def _fetch_due(args: argparse.Namespace) -> tuple[int, int]:
    """The fetch stage. Returns its exit status, and how many sessions it put in the archive."""
    store = _store(args.store)
    now = datetime.now(timezone.utc)
    spool, name = spool_root(), _store_name(args.store)
    failed = failed_in_a_row = not_archived = archived = 0
    budget = getattr(args, "budget_minutes", None)
    out_of_time = time.monotonic() + budget * 60 if budget is not None else None

    def time_is_up() -> bool:
        # Asked before each thing the stage starts: an upload, a reading
        # back, a question to Jolpica, a fetch.
        return out_of_time is not None and time.monotonic() >= out_of_time

    seen = _Seen()
    if not args.dry_run:
        # What has been fetched comes before what has not.
        seen = _see_the_spool_through(store, name, spool, time_is_up)
        failed, archived = seen.failed, seen.archived
    snapshots = list_snapshots(store)
    published_short = _published_short(store)
    seasons = args.season or _seasons_in_scope(now, snapshots, published_short)
    with tempfile.TemporaryDirectory(prefix="f1data-run-", ignore_cleanup_errors=True) as scratch:
        with fastf1_cache(Path(scratch) / "run") as fastf1:
            schedule: list[ScheduledSession] = []
            loaded = 0
            for year in seasons:
                # One season's calendar failing is no reason to leave the
                # others unlooked at: the new year's may not be out yet.
                try:
                    schedule += load_schedule(fastf1, year)
                    loaded += 1
                except Exception as exc:
                    failed += 1
                    print(f"Could not load the calendar of {year}, so nothing of it is fetched: {exc}")
            if not loaded:
                raise SystemExit("Could not load any calendar, so nothing was fetched.")

            unanswered = 0

            def classified_laps(session: ScheduledSession) -> dict[str, int] | None:
                # Without an answer a session is judged by what its
                # snapshots recorded, as it is when Jolpica has no result.
                # Jolpica not answering is not asked about every session in
                # turn, each to its last retry: that alone could outlast a
                # run.
                nonlocal unanswered
                if unanswered >= NOT_ANSWERING_AFTER or time_is_up():
                    return None
                try:
                    laps = fetch_classified_laps(
                        fastf1, session.year, session.round, session.session_type, session.start_time.date()
                    )
                except ClassificationMissing:
                    unanswered = 0
                    return None
                except ClassificationUnavailable:
                    unanswered += 1
                    if unanswered >= NOT_ANSWERING_AFTER:
                        print(
                            f"Jolpica did not answer {unanswered} times running. The sessions still to be "
                            "looked at are judged by what their snapshots recorded, until the next run."
                        )
                    return None
                unanswered = 0
                return laps

            plans = plan_fetches(
                schedule,
                snapshots,
                now,
                classified_laps,
                published_short=published_short,
            )
            # A session that is in the spool has been fetched, or is being.
            # It has only to be archived, and asking F1 for it again would
            # not help that.
            plans = [plan for plan in plans if not seen.has(plan)]
            # A batch can be cut short. So that the same sessions are not the
            # ones it reaches every time, the ones tried longest ago go first,
            # and before them the ones never tried.
            plans = least_recently_failed_first(plans, failed_fetches(store, now), _last_fetched(snapshots, now))
            if args.limit is not None:
                plans = plans[: args.limit]
            if not plans:
                print("Nothing to fetch: the archive holds every finished session in scope.")
            for number, plan in enumerate(plans):
                session = plan.session
                label = f"{session.year} round {session.round} {session.meeting_name} {session.session_name}"
                print(f"{label}: {plan.reason}")
                if args.dry_run:
                    continue
                left = len(plans) - number
                if time_is_up():
                    print(
                        f"  Stopping: the fetch stage has had its {budget:g} minutes. "
                        f"{left} session(s) left for the next run."
                    )
                    break
                no_room = _no_room(spool)
                if no_room:
                    failed += 1
                    print(f"  Stopping: {no_room}. {left} session(s) left.")
                    break
                entry = (session.year, session.session_type, session.start_time_utc or "")
                # Before the fetch, so that a run that ends in the middle of
                # it has still said that it tried.
                attempt = note_fetch_started(store, *entry, datetime.now(timezone.utc))
                try:
                    snapshot = _fetch_and_archive(
                        store,
                        name,
                        spool,
                        session.year,
                        session.round,
                        session.session_type,
                        start_time_utc=session.start_time_utc,
                        attempt=attempt,
                    )
                except _NoRoom as exc:
                    # The room went between the look and the fetch.
                    failed += 1
                    note_failed_fetch(store, *entry, f"no room: {exc}", datetime.now(timezone.utc), attempt)
                    print(f"  Stopping: {exc}. {left} session(s) left.")
                    break
                except (_NotArchived, _NotKept) as exc:
                    # F1 answered. The fault is this side of it, and the
                    # session is not asked for again: the next run sees
                    # through what is in the spool.
                    not_archived += 1
                    failed_in_a_row = 0
                    note_fetch_succeeded(store, *entry, datetime.now(timezone.utc), attempt)
                    print(f"  FETCHED, NOT ARCHIVED: {exc}. The next run sees it through before it fetches anything.")
                except Exception as exc:
                    # One session failing must not stop the others. The next
                    # run plans it again, since nothing was archived. A fetch
                    # can fail in more ways than FetchError: with the network
                    # down FastF1 cannot even load its schedule.
                    failed += 1
                    failed_in_a_row += 1
                    print(f"  FAILED: {type(exc).__name__}: {exc}")
                    note_failed_fetch(
                        store, *entry, f"{type(exc).__name__}: {exc}", datetime.now(timezone.utc), attempt
                    )
                    if failed_in_a_row >= _ASK_AFTER_FAILURES_IN_A_ROW:
                        # This year's index and last year's: one of the two
                        # exists on any day of any year.
                        if f1_is_answering((now.year, now.year - 1)):
                            # These sessions failed on their own account, and
                            # the rest of the batch need not wait for a later
                            # run to find that out.
                            print("  F1's archive is answering, so the fault is with these sessions; carrying on.")
                            failed_in_a_row = 0
                        else:
                            print(
                                f"Stopping: {failed_in_a_row} fetches failed in a row and F1's archive is not "
                                f"answering. {len(plans) - number - 1} session(s) left for the next run."
                            )
                            break
                else:
                    failed_in_a_row = 0
                    archived += 1
                    note_fetch_succeeded(store, *entry, datetime.now(timezone.utc), attempt)
                    _print_snapshot(snapshot)
    if not args.dry_run:
        _say_what_keeps_failing(store, schedule, now)
    return (1 if failed or not_archived else 0), archived


def _say_what_keeps_failing(store: ObjectStore, schedule: list[ScheduledSession], now: datetime) -> None:
    """Name the sessions whose fetch has failed several times running, where an operator will see it."""
    failing = failing_fetches(store, datetime.now(timezone.utc))
    for session in schedule:
        count, error = failing.get(
            layout.attempt_key(session.year, session.session_type, session.start_time_utc or ""), (0, "")
        )
        if count >= _SAY_SO_AFTER_FAILURES:
            print(
                f"ATTENTION: {session.year} round {session.round} {session.meeting_name} {session.session_name} "
                f"has failed to fetch {count} times in a row. Last: {error}"
            )


def _published_short(store: ObjectStore) -> set[int]:
    """The sessions published short of a bar, for the planner to look at again."""
    from f1data.publish import PointerError, read_published

    try:
        return {pointer.session_key for pointer in read_published(store) if not pointer.complete}
    except PointerError as exc:
        # The build stage reads the same pointers and fails on this one. It
        # is no reason to fetch nothing.
        logging.getLogger(__name__).warning("Could not read what is published: %s", exc)
        return set()


def _print_snapshot(snapshot: Snapshot) -> None:
    identity = snapshot.identity
    print(
        f"Archived session {identity.session_key} ({identity.meeting_name} {identity.session_name}, "
        f"{identity.start_time_utc}) as snapshot {snapshot.snapshot_id}"
    )
    shortfalls = snapshot.shortfalls()
    if not shortfalls:
        print("  complete: every feed arrived and every coverage bar is met")
    else:
        print(f"  incomplete: {len(shortfalls)} shortfall(s); a later fetch will try again")
        for shortfall in shortfalls:
            print(f"    {shortfall.bar} {shortfall.driver or 'session'}: {shortfall.detail}")


def run_build(args: argparse.Namespace) -> int:
    # Imported here so that fetching does not load the analyses.
    from f1data.build import Builder
    from f1data.publish import publish_index, publish_session, read_published
    from f1data.standings import publish_standings

    store = _store(args.store)
    session_keys = args.session_key or sorted({snapshot.session_key for snapshot in list_snapshots(store)})
    if args.shard is not None:
        part, parts = args.shard
        session_keys = [key for key in session_keys if key % parts == part]
    failed = 0
    with tempfile.TemporaryDirectory(prefix="f1data-run-", ignore_cleanup_errors=True) as scratch:
        with fastf1_cache(Path(scratch)) as fastf1:
            builder = Builder(store, fastf1, recheck=bool(getattr(args, "recheck", False)))
            for session_key in session_keys:
                try:
                    outcome = publish_session(store, session_key, builder.gather, builder.build)
                except Exception as exc:
                    # One session failing must not stop the others, or the index.
                    failed += 1
                    logging.getLogger(__name__).exception("Session %s failed", session_key)
                    print(f"session {session_key}: FAILED: {type(exc).__name__}: {exc}")
                    continue
                detail = f" ({outcome.reason})" if outcome.reason else ""
                generation = f", generation {outcome.generation[:12]}" if outcome.generation else ""
                print(f"session {session_key}: {outcome.action}{detail}{generation}")
                if outcome.action == "conflict":
                    failed += 1
            index = publish_index(store, builder.schedule, seasons=args.season)
            print(f"index ({layout.index_key()}): {index}")
            if index == "conflict":
                failed += 1

            seasons = set(args.season or []) | {pointer.identity.year for pointer in read_published(store)}
            for year in sorted(seasons):
                try:
                    standings = publish_standings(store, year, builder.standings)
                except Exception as exc:
                    failed += 1
                    logging.getLogger(__name__).exception("Standings for %s failed", year)
                    print(f"standings {year}: FAILED: {type(exc).__name__}: {exc}")
                    continue
                print(f"standings {year} ({layout.standings_key(year)}): {standings}")
                if standings == "conflict":
                    failed += 1
    return 1 if failed else 0


def run_job(args: argparse.Namespace) -> int:
    """Build, fetch, and build again what the fetch brought.

    Each stage is idempotent, so a run that is cut short, or a machine that
    was off for a weekend, is made good by the next run.

    The build comes first, so that it has its turn in every run whatever the
    fetch stage meets. Fetching waits on F1, on Jolpica and on uploads; each
    wait has its limit and the stage has its own, but a run is stopped from
    outside after two hours, and a stage that came second could be the one
    it never reaches, run after run. What the archive held when a run began
    is published by that run before it asks anything of F1.
    """
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    print(f"[{format_utc(started)}] run started")
    status = 1
    try:
        building = argparse.Namespace(**{**vars(args), "season": args.season or [started.year]})

        def build() -> int:
            try:
                return run_build(building)
            except Exception as exc:
                # Whatever stopped it is no reason not to fetch: what F1 has
                # today it may not have tomorrow.
                logging.getLogger(__name__).exception("The build stopped")
                print(f"The build stopped: {type(exc).__name__}: {exc}")
                return 1

        print("Building what the archive holds.")
        built = build()
        print("Fetching what is due.")
        try:
            fetched, archived = _fetch_due(args)
        except SystemExit as stopped:
            # The fetch stage could not start.
            print(stopped)
            fetched, archived = 1, 0
        except Exception as exc:
            logging.getLogger(__name__).exception("The fetch stage stopped")
            print(f"The fetch stage stopped: {type(exc).__name__}: {exc}")
            # It may have archived something before it did.
            fetched, archived = 1, 1
        if archived:
            print("Building what was fetched.")
            built = build()
        status = 1 if fetched or built else 0
    finally:
        finished = datetime.now(timezone.utc)
        print(f"[{format_utc(finished)}] run finished, exit {status}, {time.monotonic() - clock:.0f} s")
        _note_the_run(args.store, started, finished, status)
    return status


def _note_the_run(spec: str | None, started: datetime, finished: datetime, status: int) -> None:
    """Write down that a run of the whole job ended, where something else can see that one has not.

    A run that fails says so in its log and its exit code. A run that does
    not happen says nothing anywhere, and this is what `last-run` reads.

    The log is on the machine that fetches, where nobody is looking, so the
    record also counts the runs that have failed one after another: a job
    that runs on time and fails every time is no better than one that does
    not run.
    """
    try:
        store = _store(spec)
        failed_runs = 0
        if status:
            try:
                before = store.get(layout.LAST_RUN_KEY)
                failed_runs = _failed_runs(json.loads(before.data)) if before is not None else 0
            except Exception:
                # Whatever is there is not a record. The count starts here.
                failed_runs = 0
            failed_runs += 1
        store.put(
            layout.LAST_RUN_KEY,
            dump_json(
                {
                    "started_at": format_utc(started),
                    "finished_at": format_utc(finished),
                    "exit_code": status,
                    "failed_runs": failed_runs,
                    "host": platform.node(),
                }
            ),
        )
    except Exception as exc:
        print(f"Could not write down that the run ended: {type(exc).__name__}: {exc}")


def _failed_runs(record: Any) -> int:
    """How many runs a record says have failed one after another, its own included.

    Raises for a record that does not say how its run ended. One written
    before the count was kept says only that: a run that failed is one.
    """
    code = record["exit_code"]
    if isinstance(code, bool) or not isinstance(code, int):
        raise ValueError(f"not an exit code: {code!r}")
    if code == 0:
        return 0
    counted = record.get("failed_runs")
    if isinstance(counted, bool) or not isinstance(counted, int) or counted < 1:
        return 1
    return counted


def run_last_run(args: argparse.Namespace) -> int:
    found = _store(args.store).get(layout.LAST_RUN_KEY)
    if found is None:
        print("No run of the whole job has been written down in this store.")
        if args.allow_never:
            print("That is let pass, as asked. A job that was never installed looks the same.")
            return 0
        return 1
    try:
        record = json.loads(found.data)
        finished = parse_utc(record["finished_at"])
        failed_runs = _failed_runs(record)
    except Exception as exc:
        print(f"The record of the last run cannot be read: {type(exc).__name__}: {exc}")
        return 1
    hours = (datetime.now(timezone.utc) - finished).total_seconds() / 3600
    print(
        f"The last run finished at {record['finished_at']} on {record.get('host') or 'an unnamed machine'}, "
        f"{hours:.1f} hours ago, with exit code {record['exit_code']}."
    )
    if hours > args.max_age_hours:
        print(f"That is more than {args.max_age_hours:g} hours: the job is not running.")
        return 1
    if failed_runs >= max(1, args.max_failed_runs):
        print(
            f"FAILING: the last {failed_runs} run(s) failed, one after another. "
            "The log on that machine says what of."
        )
        return 1
    if failed_runs:
        # A fetch F1 refused once fails a run, and the next run makes it
        # good. That is said, and is not yet a job that does not work.
        print(f"DEGRADED: that run failed. {args.max_failed_runs} in a row is a job that is failing.")
    return 0


def run_copy_archive(args: argparse.Namespace) -> int:
    source, destination = _store(args.source), _store(args.destination)
    items = sorted(source.list(layout.ARCHIVE_PREFIX), key=lambda item: item.key)
    # A snapshot is copied; what a build has since written about it is not.
    # A correction belongs to the store whose builds measured the snapshot,
    # and is written there against the one before it. Copied in from another
    # store it would replace whatever the destination holds, a newer pipeline
    # version's included. The destination's own build measures the snapshot
    # and writes its own.
    corrections = [item for item in items if _is_correction(item.key)]
    # The same goes for the notes of fetches that failed: they are this
    # store's memory of its own runs.
    # The same goes for the notes of fetches that failed and of runs that
    # ended: they are this store's memory of its own runs.
    sessions = f"{layout.ARCHIVE_PREFIX}sessions/"
    markers = [item for item in items if item.key.startswith(sessions) and _is_marker(item.key)]
    # Whatever else the archive holds that is not part of a session: a whole
    # directory kept as one file, with its description last.
    others = [
        item
        for item in items
        if not item.key.startswith((sessions, layout.ATTEMPTS_PREFIX, layout.RUNS_PREFIX))
        and not _is_correction(item.key)
    ]
    others = [item for item in others if not item.key.endswith(".json")] + [
        item for item in others if item.key.endswith(".json")
    ]
    copied = skipped = not_whole = 0
    with tempfile.TemporaryDirectory(prefix="f1data-copy-") as scratch:
        local, theirs = Path(scratch) / "object", Path(scratch) / "theirs"

        def copy(key: str, described: dict[str, Any] | None = None) -> bool:
            """Copy one object. False when the source does not hold it as ``described``."""
            nonlocal copied, skipped
            if not source.download_file(key, local):
                return False
            if described is not None and (
                local.stat().st_size != described.get("size_bytes") or _sha256(local) != described.get("sha256")
            ):
                return False
            existing = destination.head(key)
            if existing is not None and _same_bytes(destination, existing, local, theirs):
                skipped += 1
                return True
            content_type = JSON_CONTENT_TYPE if key.endswith(".json") else "application/gzip"
            destination.put_file(key, local, content_type=content_type)
            copied += 1
            print(f"copied {key} ({local.stat().st_size} bytes)")
            return True

        for marker in markers:
            # A snapshot is what its marker says it is: the parts it names,
            # with the sizes and checksums it gives them. Those are copied,
            # each checked, and the marker after them. A listing of the
            # source is not a snapshot of it: taken while a fetch is being
            # uploaded there, it can hold a marker and not the parts that
            # were written a moment before it.
            prefix = marker.key[: -len(layout.SNAPSHOT_MARKER)]
            found = source.get(marker.key)
            try:
                parts = Snapshot.from_json(json.loads(found.data)).objects if found is not None else None
            except Exception:
                parts = None
            if parts is None or not all(copy(f"{prefix}{name}", described) for name, described in sorted(parts.items())):
                not_whole += 1
                print(f"left {marker.key}: the source does not hold the snapshot as its marker describes it")
                continue
            copy(marker.key)
        for item in others:
            if not copy(item.key):
                raise SystemExit(f"{item.key} disappeared from the source while copying")
    print(f"Copied {copied} object(s); {skipped} already there.")
    if corrections:
        print(
            f"Left {len(corrections)} correction(s) of a snapshot's record where they are: "
            "the destination measures for itself."
        )
    if not_whole:
        print(f"Left {not_whole} snapshot(s) that are not whole at the source. Copy again when they are.")
    return 1 if not_whole else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run_archive_directory(args: argparse.Namespace) -> int:
    store = _store(args.store)
    print(f"Packing {args.path} ...")
    try:
        description = archive_directory(store, args.path, args.name)
    except (ArchiveError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    archive = description["archive"]
    print(
        f"Archived {description['file_count']} file(s), {description['total_bytes']} bytes, "
        f"as {archive['key']} ({archive['size_bytes']} bytes, sha256 {archive['sha256']})"
    )
    return 0


def run_schema(args: argparse.Namespace) -> int:
    from f1data import schema
    from f1data.schema import render_schema, write_schema

    # Read when the command runs, so that a test can point it elsewhere.
    SCHEMA_PATH = schema.SCHEMA_PATH
    if args.check:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.is_file() else None
        if current != render_schema():
            print(f"{SCHEMA_PATH} is out of date: run `python -m f1data schema` and commit it.")
            return 1
        print(f"{SCHEMA_PATH} matches the models.")
        return 0
    changed = write_schema(SCHEMA_PATH)
    print(f"{'Wrote' if changed else 'Already current:'} {SCHEMA_PATH}")
    return 0


def _shard(value: str) -> tuple[int, int]:
    try:
        part, parts = (int(number) for number in value.split("/"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("write the shard as I/N, such as 0/4") from exc
    if parts < 1 or not 0 <= part < parts:
        raise argparse.ArgumentTypeError("the shard I/N needs 0 <= I < N")
    return part, parts


def _same_bytes(destination: ObjectStore, existing: Any, local: Path, scratch: Path) -> bool:
    """Whether the object already at the destination is the file about to be copied.

    Size alone is not enough: an object of the right length and the wrong
    bytes would be skipped on every run, under a marker that describes the
    right ones. An ETag is the content's MD5 unless the object went up in
    parts, in which case there is nothing for it but to fetch it and look.
    """
    if existing.size != local.stat().st_size:
        return False
    if "-" not in existing.etag:
        return existing.etag == file_etag(local)
    if not destination.download_file(existing.key, scratch):
        return False
    return file_etag(scratch) == file_etag(local)


def _is_marker(key: str) -> bool:
    return key.endswith(f"/{layout.SNAPSHOT_MARKER}")


def _is_correction(key: str) -> bool:
    return layout.is_remeasurement_key(key)


def _add_store_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        default=os.environ.get("F1DATA_STORE"),
        help="Where the archive and published data live: a directory, or r2. Defaults to F1DATA_STORE.",
    )


def _store(spec: str | None) -> ObjectStore:
    if not spec:
        raise SystemExit("Say which store to use with --store (a directory, or r2) or F1DATA_STORE.")
    try:
        return open_store(spec)
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc


def _raw_check(archive_path: str) -> dict[str, dict[str, Any]]:
    """Ask each archive host for the main feeds directly and record the status.

    FastF1 only tries its mirror after F1 fails, so this is the one place that
    shows what each host answers on its own.
    """
    import requests
    from fastf1 import _api

    results: dict[str, dict[str, Any]] = {}
    for base in (_api.base_url, _api.base_url_mirror):
        statuses: dict[str, Any] = {}
        for feed in _RAW_CHECK_FEEDS:
            url = f"{base}/static/{archive_path}{feed}"
            try:
                with requests.get(url, headers=_api.headers, stream=True, timeout=30) as response:
                    statuses[feed] = response.status_code
            except requests.RequestException as exc:
                statuses[feed] = f"{type(exc).__name__}: {exc}"
        results[base] = statuses
    return results


def _print_probe(report: dict[str, Any]) -> None:
    print(f"Probe: {report['year']} event={report['event']} session={report['session']}")
    if "error" in report:
        print(f"  FAILED: {report['error']}")
        _print_requests(report)
        return
    identity = report["identity"]
    print(
        f"  session key {identity['session_key']}, meeting key {identity['meeting_key']}: "
        f"{identity['meeting_name']} {identity['session_name']} at {identity['start_time_utc']}"
    )
    print(f"  versions: {report['versions']}, attempts: {report['attempts']}")
    _print_requests(report)
    print("  direct requests for the main feeds:")
    for host, statuses in report["raw_check"].items():
        print(f"    {host}: {statuses}")

    coverage = report["coverage"]
    missing = sorted(feed for feed, arrived in coverage["feeds"].items() if not arrived)
    print(f"  feeds missing: {missing or 'none'}; session ended: {coverage['session_ended']}")
    print("  driver  classified  timing  car  position  tyre")
    for code, driver in coverage["drivers"].items():
        print(
            f"  {code:<6}  {str(driver['classified_laps']):>10}  {driver['timing_laps']:>6}  "
            f"{driver['car_laps']:>3}  {driver['position_laps']:>8}  {driver['tyre_laps']:>4}"
        )
    if report["complete"]:
        print("  COMPLETE: every feed arrived and every coverage bar is met.")
    else:
        print(f"  INCOMPLETE: {len(report['shortfalls'])} shortfall(s)")
        for shortfall in report["shortfalls"]:
            print(f"    {shortfall['bar']} {shortfall['driver'] or 'session'}: {shortfall['detail']}")


def _print_requests(report: dict[str, Any]) -> None:
    if "requests_by_host" not in report:
        return
    print("  requests by host and status:")
    for host, counts in report["requests_by_host"].items():
        marker = " (F1 archive)" if host in F1_ARCHIVE_HOSTS else ""
        print(f"    {host}{marker}: {counts}")
    for kind in report["failures"]:
        print(f"    failed x{kind['count']}: {json.dumps(kind, sort_keys=True)}")


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")


if __name__ == "__main__":
    main(sys.argv[1:])
