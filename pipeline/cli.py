from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from pipeline.artifacts import DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR, build_static_artifacts


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

    ingest_season = subparsers.add_parser("ingest-season", help="Ingest race sessions for one FastF1 season.")
    add_artifact_args(ingest_season)
    ingest_season.add_argument("--year", type=int, required=True)
    ingest_season.add_argument("--force", action="store_true")
    ingest_season.add_argument(
        "--no-build-artifacts",
        action="store_true",
        help="Only update backend/data; skip frontend/public/data generation.",
    )
    ingest_season.set_defaults(func=ingest_one_season)

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
    session_id = FastF1Ingestor().ingest_session(
        year=args.year,
        event=args.event,
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
    count = FastF1Ingestor().ingest_season(year=args.year, force=args.force)
    print(f"Ingested {count} race sessions for {args.year}.")
    if not args.no_build_artifacts:
        summary = build_static_artifacts(data_dir=args.data_dir, output_dir=args.output_dir)
        print_summary(summary)


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

