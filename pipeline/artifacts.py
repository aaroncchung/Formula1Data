from __future__ import annotations

import copy
import json
import hashlib
import math
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.analysis.precompute import precompute_position_replay, precompute_session_analysis
from backend.app.ingestion.result_validation import is_final_session, validate_final_results


SCHEMA_VERSION = 1
DEFAULT_DATA_DIR = Path("backend/data")
DEFAULT_OUTPUT_DIR = Path("frontend/public/data")
MAX_TELEMETRY_SAMPLES_PER_LAP = 300

SESSION_SECTION_FILES = {
    "summary": "summary.json",
    "drivers": "drivers.json",
    "laps": "laps.json",
    "results": "results.json",
    "stints": "stints.json",
    "pit_stops": "pit-stops.json",
    "weather": "weather.json",
    "race_control": "race-control.json",
}


def build_static_artifacts(
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    sample_only: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    dataset, dataset_sources = load_merged_dataset(data_dir, sample_only=sample_only)

    reset_directory(output_dir)
    write_catalog(output_dir, dataset, dataset_sources, generated_at, sample_only)
    write_season_artifacts(output_dir, dataset, generated_at)

    session_manifests = []
    for session_id, bundle in sorted(dataset.get("session_data", {}).items()):
        session_manifests.append(
            write_session_artifacts(
                output_dir=output_dir,
                session_id=session_id,
                bundle=bundle,
                generated_at=generated_at,
                source_files=dataset_sources,
            )
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "source_files": [str(path) for path in dataset_sources],
        "season_count": len(dataset.get("seasons", [])),
        "meeting_count": len(dataset.get("meetings", [])),
        "session_count": len(dataset.get("sessions", [])),
        "artifact_count": len(list(output_dir.rglob("*.json"))),
        "total_size_bytes": sum(path.stat().st_size for path in output_dir.rglob("*.json")),
        "sessions": session_manifests,
    }


def build_incremental_artifacts(
    session_ids: set[str],
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Rebuild selected sessions and their shared indexes without touching other sessions."""
    if not session_ids:
        raise ValueError("At least one session_id is required for an incremental build")

    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    dataset, dataset_sources = load_merged_dataset(data_dir, session_ids=session_ids)
    bundles = dataset.get("session_data", {})
    missing = sorted(session_ids - set(bundles))
    if missing:
        raise ValueError(f"Processed datasets are missing sessions: {', '.join(missing)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    affected_years = {
        int(session["year"])
        for session in dataset.get("sessions", [])
        if session.get("session_id") in session_ids
    }
    session_manifests = []
    with tempfile.TemporaryDirectory(prefix="f1-artifacts-") as temporary_directory:
        staging_dir = Path(temporary_directory) / "data"
        for session_id in sorted(session_ids):
            session_manifests.append(
                write_session_artifacts(
                    output_dir=staging_dir,
                    session_id=session_id,
                    bundle=bundles[session_id],
                    generated_at=generated_at,
                    source_files=dataset_sources,
                )
            )
        write_season_artifacts(staging_dir, dataset, generated_at, years=affected_years)
        write_catalog(staging_dir, dataset, dataset_sources, generated_at, False)
        merge_incremental_indexes(output_dir, staging_dir, affected_years)

        for session_id in sorted(session_ids):
            source = staging_dir / "sessions" / session_id
            destination = output_dir / "sessions" / session_id
            reset_directory(destination)
            shutil.copytree(source, destination, dirs_exist_ok=True)
        for year in sorted(affected_years):
            source = staging_dir / "seasons" / f"{year}.json"
            destination = output_dir / "seasons" / f"{year}.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        shutil.copy2(staging_dir / "catalog.json", output_dir / "catalog.json")

    changed_paths = [output_dir / "catalog.json"]
    changed_paths.extend(output_dir / "seasons" / f"{year}.json" for year in affected_years)
    for session_id in session_ids:
        changed_paths.extend((output_dir / "sessions" / session_id).rglob("*.json"))
    changed_artifacts = [path for path in changed_paths if path.is_file()]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "source_files": [str(path) for path in dataset_sources],
        "season_count": len(affected_years),
        "meeting_count": len(
            [meeting for meeting in dataset.get("meetings", []) if int(meeting["year"]) in affected_years]
        ),
        "session_count": len(session_ids),
        "artifact_count": len(changed_artifacts),
        "total_size_bytes": sum(path.stat().st_size for path in changed_artifacts),
        "sessions": session_manifests,
        "incremental": True,
    }


def load_merged_dataset(
    data_dir: Path,
    sample_only: bool = False,
    session_ids: set[str] | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    dataset = empty_dataset()
    sources: list[Path] = []

    sample_dataset = data_dir / "processed" / "sample" / "dataset.json"
    if sample_only and sample_dataset.exists():
        dataset = merge_datasets(dataset, read_json(sample_dataset))
        sources.append(sample_dataset)

    if not sample_only:
        if session_ids is None:
            seasons_dir = data_dir / "processed" / "seasons"
            if seasons_dir.exists():
                for artifact in sorted(seasons_dir.glob("*/dataset.json")):
                    dataset = merge_datasets(dataset, read_json(artifact))
                    sources.append(artifact)

        sessions_dir = data_dir / "processed" / "sessions"
        if sessions_dir.exists():
            for artifact in sorted(sessions_dir.glob("*/dataset.json")):
                if session_ids is not None and artifact.parent.name not in session_ids:
                    continue
                dataset = merge_datasets(dataset, read_json(artifact))
                sources.append(artifact)

        if session_ids is None and not sources and sample_dataset.exists():
            dataset = merge_datasets(dataset, read_json(sample_dataset))
            sources.append(sample_dataset)

    return dataset, sources


def write_catalog(
    output_dir: Path,
    dataset: dict[str, Any],
    dataset_sources: list[Path],
    generated_at: str,
    sample_only: bool,
) -> None:
    seasons = sorted(dataset.get("seasons", []), key=lambda row: row["year"])
    meetings = sorted(dataset.get("meetings", []), key=lambda row: (row["year"], row["round"]))
    sessions = sorted(dataset.get("sessions", []), key=lambda row: (row["year"], row["round"], row["type"]))
    write_json(
        output_dir / "catalog.json",
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "source": {
                "mode": "sample" if sample_only else "processed",
                "files": [path.as_posix() for path in dataset_sources],
            },
            "artifact_strategy": {
                "session_sections": "Split by session and domain section.",
                "analysis": "Precomputed per session during pipeline generation.",
                "telemetry": (
                    "Split by driver and lap with a maximum of "
                    f"{MAX_TELEMETRY_SAMPLES_PER_LAP} samples per lap artifact."
                ),
            },
            "seasons": seasons,
            "meetings": meetings,
            "sessions": sessions,
            "totals": {
                "seasons": len(seasons),
                "meetings": len(meetings),
                "sessions": len(sessions),
            },
        },
    )


def write_season_artifacts(
    output_dir: Path,
    dataset: dict[str, Any],
    generated_at: str,
    years: set[int] | None = None,
) -> None:
    seasons = sorted(dataset.get("seasons", []), key=lambda row: row["year"])
    meetings = dataset.get("meetings", [])
    sessions = dataset.get("sessions", [])

    for season in seasons:
        year = season["year"]
        if years is not None and int(year) not in years:
            continue
        season_meetings = sorted(
            [meeting for meeting in meetings if meeting["year"] == year],
            key=lambda row: row["round"],
        )
        season_sessions = sorted(
            [session for session in sessions if session["year"] == year],
            key=lambda row: (row["round"], row["type"]),
        )
        write_json(
            output_dir / "seasons" / f"{year}.json",
            {
                "schema_version": SCHEMA_VERSION,
                "generated_at": generated_at,
                "season": season,
                "meetings": season_meetings,
                "sessions": season_sessions,
            },
        )


def write_session_artifacts(
    output_dir: Path,
    session_id: str,
    bundle: dict[str, Any],
    generated_at: str,
    source_files: list[Path],
) -> dict[str, Any]:
    if is_final_session(session_id, bundle.get("summary", {}).get("session")):
        validate_final_results(session_id, bundle.get("results", []))
    session_dir = output_dir / "sessions" / session_id
    artifacts = []

    for section, file_name in SESSION_SECTION_FILES.items():
        if section not in bundle:
            continue
        path = session_dir / file_name
        size = write_json(path, bundle.get(section))
        artifacts.append(artifact_entry(output_dir, path, section, size))

    analysis_dir = session_dir / "analysis"
    for name, payload in precompute_session_analysis(session_id, bundle).items():
        path = analysis_dir / f"{name}.json"
        size = write_json(path, payload)
        artifacts.append(artifact_entry(output_dir, path, f"analysis:{name}", size))

    replay_path = session_dir / "position-replay.json"
    replay_size = write_json(replay_path, precompute_position_replay(session_id, bundle))
    artifacts.append(artifact_entry(output_dir, replay_path, "position-replay", replay_size))

    telemetry_index = write_telemetry_artifacts(
        output_dir=output_dir,
        session_dir=session_dir,
        session_id=session_id,
        telemetry=bundle.get("telemetry", []),
        generated_at=generated_at,
    )
    artifacts.extend(telemetry_index["artifacts"])

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "session_id": session_id,
        "source": {"files": [path.as_posix() for path in source_files]},
        "sections": artifacts,
        "telemetry": {
            "lap_count": len(telemetry_index["laps"]),
            "sample_count": sum(lap["sample_count"] for lap in telemetry_index["laps"]),
            "max_samples_per_lap": MAX_TELEMETRY_SAMPLES_PER_LAP,
        },
    }
    manifest_path = session_dir / "manifest.json"
    manifest_size = write_json(manifest_path, manifest)
    artifacts.append(artifact_entry(output_dir, manifest_path, "manifest", manifest_size))
    return {
        "session_id": session_id,
        "artifact_count": len(artifacts),
        "size_bytes": sum(item["size_bytes"] for item in artifacts),
    }


def write_telemetry_artifacts(
    output_dir: Path,
    session_dir: Path,
    session_id: str,
    telemetry: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    telemetry_dir = session_dir / "telemetry"
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in telemetry:
        driver_code = str(row.get("driver_code") or "").upper()
        lap_number = int(row.get("lap_number") or 0)
        if not driver_code or lap_number <= 0:
            continue
        grouped.setdefault((driver_code, lap_number), []).append(row)

    laps = []
    artifacts = []
    for (driver_code, lap_number), rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda row: row.get("distance_m") or row.get("relative_time_ms") or 0)
        step = max(1, math.ceil(len(ordered) / MAX_TELEMETRY_SAMPLES_PER_LAP))
        downsampled = ordered[::step]
        file_name = f"{driver_code.lower()}-lap-{lap_number}.json"
        path = telemetry_dir / file_name
        size = write_json(path, downsampled)
        relative_path = path.relative_to(session_dir).as_posix()
        laps.append(
            {
                "driver_code": driver_code,
                "lap_number": lap_number,
                "path": relative_path,
                "sample_count": len(downsampled),
                "raw_sample_count": len(ordered),
                "size_bytes": size,
            }
        )
        artifacts.append(artifact_entry(output_dir, path, "telemetry-lap", size))

    index_path = telemetry_dir / "index.json"
    index_size = write_json(
        index_path,
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "session_id": session_id,
            "max_samples_per_lap": MAX_TELEMETRY_SAMPLES_PER_LAP,
            "laps": laps,
        },
    )
    artifacts.append(artifact_entry(output_dir, index_path, "telemetry-index", index_size))
    return {"laps": laps, "artifacts": artifacts}


def artifact_entry(output_dir: Path, path: Path, kind: str, size_bytes: int) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": path.relative_to(output_dir).as_posix(),
        "size_bytes": size_bytes,
        "checksum": checksum_file(path),
    }


def checksum_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def empty_dataset() -> dict[str, Any]:
    return {"seasons": [], "meetings": [], "sessions": [], "session_data": {}}


def merge_datasets(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    meetings = dedupe(left.get("meetings", []) + right.get("meetings", []), "meeting_id")
    return {
        "seasons": merge_seasons(left.get("seasons", []) + right.get("seasons", []), meetings),
        "meetings": meetings,
        "sessions": dedupe(left.get("sessions", []) + right.get("sessions", []), "session_id"),
        "session_data": {**left.get("session_data", {}), **right.get("session_data", {})},
    }


def merge_incremental_indexes(
    existing_dir: Path, publication_dir: Path, years: set[int]
) -> None:
    catalog_path = publication_dir / "catalog.json"
    existing_catalog_path = existing_dir / "catalog.json"
    if existing_catalog_path.is_file() and catalog_path.is_file():
        write_json(
            catalog_path,
            merge_catalog(read_json(existing_catalog_path), read_json(catalog_path)),
        )

    for year in sorted(years):
        season_path = publication_dir / "seasons" / f"{year}.json"
        existing_season_path = existing_dir / "seasons" / f"{year}.json"
        if existing_season_path.is_file() and season_path.is_file():
            write_json(
                season_path,
                merge_season(read_json(existing_season_path), read_json(season_path)),
            )


def merge_catalog(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(existing)
    result["schema_version"] = max(
        int(existing.get("schema_version") or 0), int(incoming.get("schema_version") or 0)
    )
    result["generated_at"] = incoming.get("generated_at") or existing.get("generated_at")
    result["artifact_strategy"] = incoming.get("artifact_strategy") or existing.get(
        "artifact_strategy"
    )
    result["source"] = merge_source(existing.get("source"), incoming.get("source"))
    result["meetings"] = merge_rows(
        existing.get("meetings"), incoming.get("meetings"), "meeting_id"
    )
    result["sessions"] = merge_rows(
        existing.get("sessions"), incoming.get("sessions"), "session_id"
    )
    result["seasons"] = merge_season_rows(
        existing.get("seasons"), incoming.get("seasons"), result["meetings"]
    )
    result["meetings"].sort(
        key=lambda row: (int(row.get("year") or 0), int(row.get("round") or 0))
    )
    result["sessions"].sort(key=session_sort_key)
    result["seasons"].sort(key=lambda row: int(row.get("year") or 0))
    result["totals"] = {
        "seasons": len(result["seasons"]),
        "meetings": len(result["meetings"]),
        "sessions": len(result["sessions"]),
    }
    return result


def merge_season(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(existing)
    result["schema_version"] = max(
        int(existing.get("schema_version") or 0), int(incoming.get("schema_version") or 0)
    )
    result["generated_at"] = incoming.get("generated_at") or existing.get("generated_at")
    result["meetings"] = merge_rows(
        existing.get("meetings"), incoming.get("meetings"), "meeting_id"
    )
    result["sessions"] = merge_rows(
        existing.get("sessions"), incoming.get("sessions"), "session_id"
    )
    result["meetings"].sort(key=lambda row: int(row.get("round") or 0))
    result["sessions"].sort(key=session_sort_key)
    season_rows = merge_season_rows(
        [existing.get("season")], [incoming.get("season")], result["meetings"]
    )
    result["season"] = (
        season_rows[0] if season_rows else incoming.get("season") or existing.get("season")
    )
    return result


def merge_rows(existing: Any, incoming: Any, key: str) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in list(existing or []) + list(incoming or []):
        if isinstance(row, dict) and row.get(key) is not None:
            rows[str(row[key])] = copy.deepcopy(row)
    return list(rows.values())


def merge_season_rows(
    existing: Any, incoming: Any, meetings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = merge_rows(existing, incoming, "year")
    for row in rows:
        season_meetings = [
            meeting
            for meeting in meetings
            if int(meeting.get("year") or 0) == int(row["year"])
        ]
        row["meeting_count"] = len(season_meetings)
        row["ingested_meeting_count"] = sum(
            bool(meeting.get("is_ingested")) for meeting in season_meetings
        )
        row["is_sample"] = bool(season_meetings) and all(
            bool(meeting.get("is_sample")) for meeting in season_meetings
        )
    return rows


def merge_source(existing: Any, incoming: Any) -> Any:
    if not isinstance(existing, dict) or not isinstance(incoming, dict):
        return copy.deepcopy(incoming or existing)
    result = {**existing, **incoming}
    files = list(existing.get("files") or []) + list(incoming.get("files") or [])
    result["files"] = list(dict.fromkeys(files))
    return result


def session_sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
    session_order = {"FP1": 1, "FP2": 2, "FP3": 3, "SQ": 4, "S": 5, "Q": 6, "R": 7}
    return (
        int(row.get("year") or 0),
        int(row.get("round") or 0),
        session_order.get(str(row.get("type") or "").upper(), 0),
    )


def merge_seasons(seasons: list[dict[str, Any]], meetings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_year: dict[int, dict[str, Any]] = {}
    for season in seasons:
        year = int(season["year"])
        current = by_year.setdefault(
            year,
            {"year": year, "meeting_count": 0, "ingested_meeting_count": 0, "is_sample": True},
        )
        current["meeting_count"] = max(
            int(current.get("meeting_count") or 0),
            int(season.get("meeting_count") or 0),
        )
        current["ingested_meeting_count"] = max(
            int(current.get("ingested_meeting_count") or 0),
            int(season.get("ingested_meeting_count") or 0),
        )
        current["is_sample"] = bool(current.get("is_sample")) and bool(season.get("is_sample"))

    for year, season in by_year.items():
        year_meetings = [meeting for meeting in meetings if meeting["year"] == year]
        ingested_count = sum(1 for meeting in year_meetings if meeting.get("is_ingested"))
        if year_meetings:
            season["meeting_count"] = max(season["meeting_count"], len(year_meetings))
            season["ingested_meeting_count"] = max(season["ingested_meeting_count"], ingested_count)
    return list(by_year.values())


def dedupe(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    values: dict[Any, dict[str, Any]] = {}
    for row in rows:
        values[row[key]] = row
    return list(values.values())


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_jsonable(data)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path.stat().st_size


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return to_jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value

