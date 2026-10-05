from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from f1data.coverage import evaluate_coverage
from f1data.fetch import F1_ARCHIVE_HOSTS, FetchError, fetch_session

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

    args = parser.parse_args(argv)
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
