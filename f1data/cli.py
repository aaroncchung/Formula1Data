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
    select_snapshot,
    write_snapshot,
)
from f1data.classification import ClassificationUnavailable, fetch_classified_laps
from f1data.config import ConfigError, load_env_file, open_store
from f1data.coverage import evaluate_coverage
from f1data.due import least_recently_failed_first, plan_fetches
from f1data.fetch import F1_ARCHIVE_HOSTS, FetchError, f1_is_answering, fastf1_cache, fetch_session
from f1data.httplog import request_timeouts
from f1data.policy import REQUEST_TIMEOUT_SECONDS, RUN_IS_OVERDUE_AFTER
from f1data.schedule import ScheduledSession, load_schedule
from f1data.spool import (
    CACHE_DIRECTORY,
    Spooled,
    describe,
    discard,
    keep,
    new_fetch_directory,
    spool_root,
    sweep,
    uploading,
    waiting,
)
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
        help="The whole job: fetch what is due, then build and publish. For a schedule on a machine F1 answers.",
    )
    _add_store_argument(both)
    both.add_argument(
        "--season",
        type=int,
        action="append",
        help="Season to look at. Repeatable. Defaults to this year, last year, and any year with a "
        "session the archive does not hold in full.",
    )
    both.set_defaults(func=run_job, limit=None, dry_run=False, session_key=None, shard=None)

    last = subparsers.add_parser(
        "last-run",
        help="Say when the whole job last finished on the machine that fetches. Fails if that is too long ago.",
    )
    _add_store_argument(last)
    last.add_argument(
        "--max-age-hours",
        type=float,
        default=RUN_IS_OVERDUE_AFTER.total_seconds() / 3600,
        help="How long ago the last run may have finished. Defaults to two turns of a six-hour schedule.",
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
    load_env_file(Path(".env"))
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
    would then raise where the name is printed.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[union-attr]
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
    """A session was fetched and could not be archived. It is in the spool."""


def _archive(store: ObjectStore, spooled: Spooled) -> Snapshot | None:
    """Archive a fetch from the spool and remove it from there. ``None`` when another run is at it."""
    with uploading(spooled.directory) as held:
        if not held:
            return None
        snapshot = write_snapshot(
            store, spooled.fetched, now=spooled.fetched_at, snapshot_id=spooled.snapshot_id
        )
    discard(spooled.directory)
    return snapshot


def _archive_what_is_waiting(store: ObjectStore, spool: Path) -> tuple[int, list[Spooled]]:
    """Upload the fetches an earlier run could not. Returns how many were, and the ones still waiting.

    Before anything is asked of F1: these have been fetched once already.
    """
    archived, still_waiting = 0, []
    for removed in sweep(spool):
        print(f"Removed {removed.name} from the spool: a fetch that never finished.")
    for spooled in waiting(spool):
        try:
            snapshot = _archive(store, spooled)
        except Exception as exc:
            print(f"{describe(spooled)}: fetched earlier, and still NOT ARCHIVED: {type(exc).__name__}: {exc}")
            still_waiting.append(spooled)
            continue
        if snapshot is None:
            print(f"{describe(spooled)}: fetched earlier, being archived by another run.")
            still_waiting.append(spooled)
            continue
        archived += 1
        print(f"{describe(spooled)}: fetched earlier, archived now.")
        _print_snapshot(snapshot)
    return archived, still_waiting


def _fetch_and_archive(store: ObjectStore, spool: Path, year: int, event: int | str, session_type: str) -> Snapshot:
    """Fetch one session into the spool and archive it from there.

    Raises whatever the fetch raises, and ``_NotArchived`` when the session
    was fetched and the archive would not take it: it then stays in the
    spool, and the next run uploads it before it fetches anything.
    """
    directory = new_fetch_directory(spool)
    try:
        fetched = fetch_session(year, event, session_type, directory / CACHE_DIRECTORY)
        fetched_at = datetime.now(timezone.utc)
        spooled = keep(directory, fetched, fetched_at, new_snapshot_id(fetched_at))
    except BaseException:
        # Not a whole fetch, so nothing a snapshot could be made of.
        discard(directory)
        raise
    try:
        snapshot = _archive(store, spooled)
    except Exception as exc:
        raise _NotArchived(f"{type(exc).__name__}: {exc}. Kept in {directory}") from exc
    if snapshot is None:
        raise _NotArchived(f"another run holds {directory}")
    return snapshot


def run_fetch(args: argparse.Namespace) -> int:
    store = _store(args.store)
    event = int(args.event) if str(args.event).isdigit() else args.event
    try:
        snapshot = _fetch_and_archive(store, spool_root(), args.year, event, args.session)
    except _NotArchived as exc:
        print(f"FETCHED, NOT ARCHIVED: {exc}. `fetch-due` or `run` uploads it before it fetches anything.")
        return 1
    _print_snapshot(snapshot)
    return 0


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
        by_session.setdefault(snapshot.session_key, []).append(snapshot)
    for session_key, group in by_session.items():
        best = select_snapshot(group)
        if best is not None and (not best.complete or session_key in published_short):
            years.add(best.identity.year)
    return sorted(years)


def run_fetch_due(args: argparse.Namespace) -> int:
    store = _store(args.store)
    now = datetime.now(timezone.utc)
    spool = spool_root()
    failed = failed_in_a_row = not_archived = 0
    still_waiting: list[Spooled] = []
    if not args.dry_run:
        _, still_waiting = _archive_what_is_waiting(store, spool)
        not_archived = len(still_waiting)
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

            def classified_laps(session: ScheduledSession) -> dict[str, int] | None:
                try:
                    return fetch_classified_laps(
                        fastf1, session.year, session.round, session.session_type, session.start_time.date()
                    )
                except ClassificationUnavailable:
                    return None

            plans = plan_fetches(
                schedule,
                snapshots,
                now,
                classified_laps,
                published_short=published_short,
            )
            # A session that is in the spool has been fetched. It has only to
            # be archived, and asking F1 for it again would not help that.
            in_the_spool = {
                layout.attempt_key(
                    spooled.fetched.identity.year,
                    spooled.fetched.identity.session_type,
                    spooled.fetched.identity.start_time_utc,
                )
                for spooled in still_waiting
            }
            plans = [plan for plan in plans if plan.attempt_key not in in_the_spool]
            # A batch can be cut short. So that the same sessions are not the
            # ones it reaches every time, those that failed last time wait
            # behind those that have not been tried.
            plans = least_recently_failed_first(plans, failed_fetches(store, now))
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
                entry = (session.year, session.session_type, session.start_time_utc or "")
                # Before the fetch, so that a run that ends in the middle of
                # it has still said that it tried.
                note_fetch_started(store, *entry, datetime.now(timezone.utc))
                try:
                    snapshot = _fetch_and_archive(store, spool, session.year, session.round, session.session_type)
                except _NotArchived as exc:
                    # F1 answered. The fault is the archive's, and the session
                    # is not fetched again: the next run uploads what was kept.
                    not_archived += 1
                    failed_in_a_row = 0
                    note_fetch_succeeded(store, *entry, datetime.now(timezone.utc))
                    print(f"  FETCHED, NOT ARCHIVED: {exc}. The next run uploads it before it fetches anything.")
                except Exception as exc:
                    # One session failing must not stop the others. The next
                    # run plans it again, since nothing was archived. A fetch
                    # can fail in more ways than FetchError: with the network
                    # down FastF1 cannot even load its schedule.
                    failed += 1
                    failed_in_a_row += 1
                    print(f"  FAILED: {type(exc).__name__}: {exc}")
                    note_failed_fetch(store, *entry, f"{type(exc).__name__}: {exc}", datetime.now(timezone.utc))
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
                    note_fetch_succeeded(store, *entry, datetime.now(timezone.utc))
                    _print_snapshot(snapshot)
    if not args.dry_run:
        _say_what_keeps_failing(store, schedule, now)
    return 1 if failed or not_archived else 0


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
    """Fetch, then build. Each stage is idempotent, so a run that is cut short,
    or a machine that was off for a weekend, is made good by the next run."""
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    print(f"[{format_utc(started)}] run started")
    status = 1
    try:
        try:
            fetched = run_fetch_due(args)
        except SystemExit as stopped:
            # The fetch stage could not start. That is no reason to hold back
            # what the archive already has, any more than one failed fetch is.
            print(stopped)
            fetched = 1
        if args.season is None:
            args.season = [started.year]
        built = run_build(args)
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
    """
    try:
        _store(spec).put(
            layout.LAST_RUN_KEY,
            dump_json(
                {
                    "started_at": format_utc(started),
                    "finished_at": format_utc(finished),
                    "exit_code": status,
                    "host": platform.node(),
                }
            ),
        )
    except Exception as exc:
        print(f"Could not write down that the run ended: {type(exc).__name__}: {exc}")


def run_last_run(args: argparse.Namespace) -> int:
    found = _store(args.store).get(layout.LAST_RUN_KEY)
    if found is None:
        print("No run of the whole job has been written down in this store.")
        return 1
    try:
        record = json.loads(found.data)
        finished = parse_utc(record["finished_at"])
    except Exception as exc:
        print(f"The record of the last run cannot be read: {type(exc).__name__}: {exc}")
        return 1
    hours = (datetime.now(timezone.utc) - finished).total_seconds() / 3600
    print(
        f"The last run finished at {record['finished_at']} on {record.get('host') or 'an unnamed machine'}, "
        f"{hours:.1f} hours ago, with exit code {record.get('exit_code')}."
    )
    if hours > args.max_age_hours:
        print(f"That is more than {args.max_age_hours:g} hours: the job is not running.")
        return 1
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
