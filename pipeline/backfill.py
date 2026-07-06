from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import sys
from typing import Any

from pipeline.artifacts import DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR, build_static_artifacts


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"


@dataclass
class BackfillSummary:
    years: list[int]
    through_date: date
    force: bool
    dry_run: bool
    planned: list[str] = field(default_factory=list)
    ingested: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    skipped_future: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    artifact_summary: dict[str, Any] | None = None


def run_backfill(
    years: list[int],
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    sessions: list[str] | None = None,
    races_only: bool = False,
    force: bool = False,
    dry_run: bool = False,
    include_future: bool = False,
    through_date: date | None = None,
) -> BackfillSummary:
    configure_backend_data_dir(data_dir)
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from app.ingestion.fastf1_ingestor import FastF1Ingestor
    from app.ingestion.normalizer import normalize_fastf1_schedule, selected_session_codes
    from app.services.dataset_service import DatasetService
    from app.services.storage_service import StorageService

    through = through_date or date.today()
    storage = StorageService(root=data_dir)
    datasets = DatasetService(storage)
    ingestor = FastF1Ingestor()
    summary = BackfillSummary(
        years=years,
        through_date=through,
        force=force,
        dry_run=dry_run,
    )

    for year in years:
        try:
            schedule = ingestor.fastf1.get_schedule(year)
        except Exception as exc:
            summary.failed.append({"session_id": str(year), "error": str(exc)})
            print(f"Failed season schedule: {year}: {exc}")
            continue

        if not dry_run:
            datasets.write_season_dataset(year, normalize_fastf1_schedule(year, schedule))

        for _, event in schedule.iterrows():
            round_number = safe_int(get_value(event, "RoundNumber"), default=0) or 0
            event_name = str(get_value(event, "EventName", "") or "")
            if round_number <= 0 or not event_name:
                continue

            for session_code in selected_session_codes(
                event,
                sessions=sessions,
                races_only=races_only,
            ):
                candidate = backfill_candidate(year, event, session_code, through)
                if not include_future and candidate.is_future:
                    summary.skipped_future.append(candidate.session_id)
                    print(f"Skipped future session: {candidate.session_id}")
                    continue

                if not force and storage.exists(f"processed/sessions/{candidate.session_id}/dataset.json"):
                    summary.skipped_existing.append(candidate.session_id)
                    print(f"Skipped existing session: {candidate.session_id}")
                    continue

                summary.planned.append(candidate.session_id)
                if dry_run:
                    print(f"Would ingest session: {candidate.session_id}")
                    continue

                try:
                    ingested_session_id = ingestor.ingest_session(
                        year=year,
                        event=round_number,
                        session_name=session_code,
                        force=force,
                    )
                except Exception as exc:
                    summary.failed.append(
                        {
                            "session_id": candidate.session_id,
                            "error": str(exc),
                        }
                    )
                    print(f"Failed session: {candidate.session_id}: {exc}")
                    continue

                summary.ingested.append(ingested_session_id)
                print(f"Ingested session: {ingested_session_id}")

    if not dry_run:
        summary.artifact_summary = build_static_artifacts(data_dir=data_dir, output_dir=output_dir)

    return summary


@dataclass(frozen=True)
class BackfillCandidate:
    session_id: str
    start_date: date | None
    is_future: bool


def backfill_candidate(
    year: int,
    event: Any,
    session_code: str,
    through_date: date,
) -> BackfillCandidate:
    from app.ingestion.normalizer import session_code_for_name, session_start_time_from_event

    round_number = safe_int(get_value(event, "RoundNumber"), default=0) or 0
    code = session_code_for_name(session_code).lower()
    session_id = f"{year}-{round_number:02d}-{code}"
    start = parse_iso_date(session_start_time_from_event(event, session_code))
    return BackfillCandidate(
        session_id=session_id,
        start_date=start,
        is_future=bool(start and start > through_date),
    )


def print_backfill_summary(summary: BackfillSummary) -> None:
    print(
        "Backfill summary: "
        f"{len(summary.ingested)} ingested, "
        f"{len(summary.skipped_existing)} existing skipped, "
        f"{len(summary.skipped_future)} future skipped, "
        f"{len(summary.failed)} failed."
    )
    if summary.artifact_summary:
        print(
            "Generated "
            f"{summary.artifact_summary['artifact_count']} static JSON artifacts "
            f"for {summary.artifact_summary['session_count']} session(s)."
        )


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def safe_int(value: Any, default: int | None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except Exception:
        return getattr(obj, key, default)


def configure_backend_data_dir(data_dir: Path) -> None:
    import os

    data_dir = data_dir.resolve()
    os.environ.setdefault("DATA_DIR", str(data_dir))
    os.environ.setdefault("FASTF1_CACHE_DIR", str(data_dir / "cache" / "fastf1"))
