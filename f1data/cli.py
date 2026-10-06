from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from f1data import layout
from f1data.archive import ArchiveError, Snapshot, archive_directory, list_snapshots, write_snapshot
from f1data.classification import ClassificationUnavailable, fetch_classified_laps
from f1data.config import ConfigError, load_env_file, open_store
from f1data.coverage import evaluate_coverage
from f1data.due import plan_fetches
from f1data.fetch import F1_ARCHIVE_HOSTS, FetchError, fastf1_cache, fetch_session
from f1data.schedule import ScheduledSession, load_schedule
from f1data.store import JSON_CONTENT_TYPE, ObjectStore, file_etag

# A batch of fetches stops here rather than fail its way through every session.
_GIVE_UP_AFTER_FAILURES_IN_A_ROW = 2

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
        "--season", type=int, action="append", help="Season to look at. Repeatable. Defaults to this year."
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
        "--season", type=int, action="append", help="Season to look at. Repeatable. Defaults to this year."
    )
    both.set_defaults(func=run_job, limit=None, dry_run=False, session_key=None, shard=None)

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
    load_env_file(Path(".env"))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(name)-14s %(levelname)-7s %(message)s",
    )
    # FastF1 installs its own handler; without this every line prints twice.
    logging.getLogger("fastf1").propagate = False
    raise SystemExit(args.func(args))


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


def run_fetch(args: argparse.Namespace) -> int:
    store = _store(args.store)
    event = int(args.event) if str(args.event).isdigit() else args.event
    with tempfile.TemporaryDirectory(prefix="f1data-fetch-", ignore_cleanup_errors=True) as scratch:
        fetched = fetch_session(args.year, event, args.session, Path(scratch) / "cache")
        snapshot = write_snapshot(store, fetched)
    _print_snapshot(snapshot)
    return 0


def run_fetch_due(args: argparse.Namespace) -> int:
    store = _store(args.store)
    now = datetime.now(timezone.utc)
    seasons = args.season or [now.year]
    failed = failed_in_a_row = 0
    with tempfile.TemporaryDirectory(prefix="f1data-run-", ignore_cleanup_errors=True) as scratch:
        with fastf1_cache(Path(scratch) / "run") as fastf1:
            try:
                schedule = [session for year in seasons for session in load_schedule(fastf1, year)]
            except Exception as exc:
                raise SystemExit(f"Could not load the calendar, so nothing was fetched: {exc}") from exc

            def classified_laps(session: ScheduledSession) -> dict[str, int] | None:
                try:
                    return fetch_classified_laps(
                        fastf1, session.year, session.round, session.session_type
                    )
                except ClassificationUnavailable:
                    return None

            plans = plan_fetches(
                schedule,
                list_snapshots(store),
                now,
                classified_laps,
                published_short=_published_short(store),
            )
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
                cache_dir = Path(scratch) / f"fetch-{number}"
                try:
                    fetched = fetch_session(session.year, session.round, session.session_type, cache_dir)
                    snapshot = write_snapshot(store, fetched)
                except Exception as exc:
                    # One session failing must not stop the others. The next
                    # run plans it again, since nothing was archived. A fetch
                    # can fail in more ways than FetchError: with the network
                    # down FastF1 cannot even load its schedule.
                    failed += 1
                    failed_in_a_row += 1
                    print(f"  FAILED: {type(exc).__name__}: {exc}")
                    if failed_in_a_row >= _GIVE_UP_AFTER_FAILURES_IN_A_ROW:
                        print(
                            f"Stopping: {failed_in_a_row} fetches failed in a row, so the network "
                            f"or F1 is not answering. {len(plans) - number - 1} session(s) left for the next run."
                        )
                        break
                else:
                    failed_in_a_row = 0
                    _print_snapshot(snapshot)
                finally:
                    shutil.rmtree(cache_dir, ignore_errors=True)
    return 1 if failed else 0


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
    if args.season is None:
        args.season = [datetime.now(timezone.utc).year]
    fetched = run_fetch_due(args)
    # A failed fetch is no reason to hold back what the archive already has.
    built = run_build(args)
    return 1 if fetched or built else 0


def run_copy_archive(args: argparse.Namespace) -> int:
    source, destination = _store(args.source), _store(args.destination)
    items = sorted(source.list(layout.ARCHIVE_PREFIX), key=lambda item: item.key)
    # The marker goes last, as it did when the snapshot was first written: a
    # snapshot is only visible once all of it is there.
    ordered = [item for item in items if not _is_marker(item.key)]
    ordered += [item for item in items if _is_marker(item.key)]
    copied = skipped = 0
    with tempfile.TemporaryDirectory(prefix="f1data-copy-") as scratch:
        for item in ordered:
            local = Path(scratch) / "object"
            if not source.download_file(item.key, local):
                raise SystemExit(f"{item.key} disappeared from the source while copying")
            existing = destination.head(item.key)
            if existing is not None and _same_bytes(destination, existing, local, Path(scratch) / "theirs"):
                skipped += 1
                continue
            content_type = JSON_CONTENT_TYPE if item.key.endswith(".json") else "application/gzip"
            destination.put_file(item.key, local, content_type=content_type)
            copied += 1
            print(f"copied {item.key} ({item.size} bytes)")
    print(f"Copied {copied} object(s); {skipped} already there.")
    return 0


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
