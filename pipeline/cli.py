from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from pipeline.artifacts import DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR, build_static_artifacts
from pipeline.backfill import print_backfill_summary, run_backfill


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="Ingest Formula 1 data and generate static frontend artifacts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser(
        "generate",
        help="Generate static artifacts. Use --sample for the committed offline sample dataset.",
    )
    add_artifact_args(generate)
    generate.add_argument("--sample", action="store_true", help="Use only backend/data/processed/sample.")
    generate.set_defaults(func=generate_artifacts)

    build = subparsers.add_parser("build-artifacts", help="Build static artifacts from processed datasets.")
    add_artifact_args(build)
    build.add_argument("--sample", action="store_true", help="Use only backend/data/processed/sample.")
    build.set_defaults(func=generate_artifacts)

    ingest_session = subparsers.add_parser("ingest-session", help="Ingest one FastF1 session.")
    add_artifact_args(ingest_session)
    ingest_session.add_argument("--year", type=int, required=True)
    ingest_session.add_argument("--event", required=True)
    ingest_session.add_argument("--session", required=True)
    ingest_session.add_argument("--force", action="store_true")
    ingest_session.add_argument(
        "--no-build-artifacts",
        action="store_true",
        help="Only update backend/data; skip frontend/public/data generation.",
    )
    ingest_session.set_defaults(func=ingest_one_session)

    ingest_season = subparsers.add_parser("ingest-season", help="Ingest FastF1 sessions for one season.")
    add_artifact_args(ingest_season)
    ingest_season.add_argument("--year", type=int, required=True)
    ingest_season.add_argument("--force", action="store_true")
    ingest_season.add_argument(
        "--sessions",
        nargs="+",
        help="Optional session codes or names to ingest, such as FP1 Q R.",
    )
    ingest_season.add_argument(
        "--races-only",
        action="store_true",
        help="Ingest only race sessions, matching the original workflow.",
    )
    ingest_season.add_argument(
        "--no-build-artifacts",
        action="store_true",
        help="Only update backend/data; skip frontend/public/data generation.",
    )
    ingest_season.set_defaults(func=ingest_one_season)

    backfill = subparsers.add_parser(
        "backfill",
        help="Backfill processed datasets for historical seasons and rebuild static artifacts.",
    )
    add_artifact_args(backfill)
    backfill.add_argument("--years", nargs="+", type=int, required=True)
    backfill.add_argument("--sessions", nargs="+", help="Optional session codes or names, such as Q R.")
    backfill.add_argument("--races-only", action="store_true")
    backfill.add_argument("--force", action="store_true")
    backfill.add_argument("--dry-run", action="store_true")
    backfill.add_argument(
        "--include-future",
        action="store_true",
        help="Attempt sessions after --through-date if they appear in the FastF1 schedule.",
    )
    backfill.add_argument(
        "--through-date",
        help="Latest session date to ingest in YYYY-MM-DD format. Defaults to today.",
    )
    backfill.set_defaults(func=backfill_sessions)

    process_queue = subparsers.add_parser(
        "process-queue",
        help="Process simulated Cloudflare Queue ingestion messages locally.",
    )
    add_artifact_args(process_queue)
    process_queue.add_argument("--message-file", type=Path, help="Single queue message JSON file.")
    process_queue.add_argument("--queue-file", type=Path, help="JSONL file containing queue messages.")
    process_queue.add_argument("--artifact-destination", choices=["local", "r2"], default="local")
    process_queue.add_argument("--r2-bucket", help="R2 bucket name for artifact-destination=r2.")
    process_queue.add_argument("--r2-prefix", default="", help="Optional object key prefix for R2 uploads.")
    process_queue.add_argument("--callback-url", help="Worker base URL or full job status callback URL.")
    process_queue.add_argument("--callback-token", help="Bearer token for the Worker callback.")
    process_queue.add_argument(
        "--defer-terminal-callbacks",
        action="store_true",
        help="Leave success/failure reporting to the caller after additional verification.",
    )
    process_queue.add_argument("--success-payload-file", type=Path)
    process_queue.add_argument("--force", action="store_true", help="Force FastF1 reingestion.")
    process_queue.set_defaults(func=process_queue_messages)

    args = parser.parse_args(argv)
    args.func(args)


def add_artifact_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)


def generate_artifacts(args: argparse.Namespace) -> None:
    summary = build_static_artifacts(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        sample_only=bool(args.sample),
    )
    print_summary(summary)


def ingest_one_session(args: argparse.Namespace) -> None:
    configure_backend_data_dir(args.data_dir)
    FastF1Ingestor = load_fastf1_ingestor()
    event = int(args.event) if str(args.event).isdigit() else args.event
    session_id = FastF1Ingestor().ingest_session(
        year=args.year,
        event=event,
        session_name=args.session,
        force=args.force,
    )
    print(f"Ingested session: {session_id}")
    if not args.no_build_artifacts:
        summary = build_static_artifacts(data_dir=args.data_dir, output_dir=args.output_dir)
        print_summary(summary)


def ingest_one_season(args: argparse.Namespace) -> None:
    configure_backend_data_dir(args.data_dir)
    FastF1Ingestor = load_fastf1_ingestor()
    count = FastF1Ingestor().ingest_season(
        year=args.year,
        force=args.force,
        sessions=args.sessions,
        races_only=args.races_only,
    )
    scope = "race sessions" if args.races_only else "sessions"
    print(f"Ingested {count} {scope} for {args.year}.")
    if not args.no_build_artifacts:
        summary = build_static_artifacts(data_dir=args.data_dir, output_dir=args.output_dir)
        print_summary(summary)


def backfill_sessions(args: argparse.Namespace) -> None:
    from datetime import date

    through_date = date.fromisoformat(args.through_date) if args.through_date else None
    summary = run_backfill(
        years=args.years,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        sessions=args.sessions,
        races_only=args.races_only,
        force=args.force,
        dry_run=args.dry_run,
        include_future=args.include_future,
        through_date=through_date,
    )
    print_backfill_summary(summary)
    if summary.failed:
        raise SystemExit(1)


def process_queue_messages(args: argparse.Namespace) -> None:
    from pipeline.local_queue_worker import load_messages, process_message

    messages = list(load_messages(args.message_file, args.queue_file))
    if not messages:
        raise SystemExit("Provide --message-file or --queue-file with at least one message.")
    for message in messages:
        result = process_message(
            message=message,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            artifact_destination=args.artifact_destination,
            r2_bucket=args.r2_bucket,
            r2_prefix=args.r2_prefix,
            callback_url=args.callback_url,
            callback_token=args.callback_token,
            force=args.force,
            defer_terminal_callbacks=args.defer_terminal_callbacks,
            success_payload_file=args.success_payload_file,
        )
        print(f"Processed {result['job_id']} for {result['session_id']} ({result['artifacts']} artifacts).")


def configure_backend_data_dir(data_dir: Path) -> None:
    data_dir = data_dir.resolve()
    os.environ.setdefault("DATA_DIR", str(data_dir))
    os.environ.setdefault("FASTF1_CACHE_DIR", str(data_dir / "cache" / "fastf1"))


def load_fastf1_ingestor() -> Any:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.ingestion.fastf1_ingestor import FastF1Ingestor

    return FastF1Ingestor


def print_summary(summary: dict[str, Any]) -> None:
    print(
        "Generated "
        f"{summary['artifact_count']} static JSON artifacts "
        f"for {summary['session_count']} session(s) at {summary['output_dir']} "
        f"({summary['total_size_bytes']} bytes)."
    )

