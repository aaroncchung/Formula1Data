from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from pipeline.artifacts import (
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    SESSION_SECTION_FILES,
    build_incremental_artifacts,
    checksum_file,
    merge_catalog,
    merge_incremental_indexes,
    merge_season,
    read_json,
    write_json,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline process-queue",
        description="Process simulated Cloudflare Queue ingestion messages locally.",
    )
    parser.add_argument("--message-file", type=Path, help="Single queue message JSON file.")
    parser.add_argument("--queue-file", type=Path, help="JSONL file containing queue messages.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--artifact-destination", choices=["local", "r2"], default="local")
    parser.add_argument("--r2-bucket", help="R2 bucket name for artifact-destination=r2.")
    parser.add_argument("--r2-prefix", default="", help="Optional object key prefix for R2 uploads.")
    parser.add_argument("--callback-url", help="Worker base URL or full job status callback URL.")
    parser.add_argument("--callback-token", help="Bearer token for the Worker ingestion callback.")
    parser.add_argument(
        "--defer-terminal-callbacks",
        action="store_true",
        help="Leave success/failure reporting to the caller after additional verification.",
    )
    parser.add_argument("--success-payload-file", type=Path)
    parser.add_argument("--force", action="store_true", help="Force FastF1 reingestion.")
    args = parser.parse_args(argv)

    messages = list(load_messages(args.message_file, args.queue_file))
    if not messages:
        raise SystemExit("Provide --message-file or --queue-file with at least one message.")

    for message in messages:
        process_message(
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


def process_message(
    message: dict[str, Any],
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    artifact_destination: str = "local",
    r2_bucket: str | None = None,
    r2_prefix: str = "",
    callback_url: str | None = None,
    callback_token: str | None = None,
    force: bool = False,
    defer_terminal_callbacks: bool = False,
    success_payload_file: Path | None = None,
) -> dict[str, Any]:
    job_id = required(message, "job_id")
    kind = required(message, "kind")
    if kind not in {"ingest_session", "refresh_session"}:
        raise ValueError(f"Unsupported local queue job kind: {kind}")

    callback_job_status(callback_url, callback_token, job_id, {"status": "running"})
    configure_backend_data_dir(data_dir)

    try:
        session_id = expected_session_id(message)
        should_force = force or bool(message.get("force"))
        if not should_force and session_artifacts_exist(output_dir, session_id):
            summary = summarize_existing_artifacts(output_dir)
            publication_dir = output_dir
            print(f"Using existing static artifacts for {session_id}.")
        else:
            FastF1Ingestor = load_fastf1_ingestor()
            session_id = FastF1Ingestor().ingest_session(
                year=int(required(message, "year")),
                event=int(required(message, "round")),
                session_name=str(required(message, "session")),
                force=should_force,
            )
            with tempfile.TemporaryDirectory(prefix="f1-ingestion-") as temporary_directory:
                publication_dir = Path(temporary_directory) / "data"
                existing_indexes_dir = output_dir
                if artifact_destination == "r2":
                    existing_indexes_dir = Path(temporary_directory) / "existing"
                    hydrate_r2_indexes(
                        existing_indexes_dir,
                        required_value(r2_bucket, "--r2-bucket"),
                        r2_prefix,
                        int(required(message, "year")),
                    )
                summary = build_incremental_artifacts(
                    {session_id},
                    data_dir=data_dir,
                    output_dir=publication_dir,
                )
                merge_incremental_indexes(
                    existing_indexes_dir,
                    publication_dir,
                    {int(required(message, "year"))},
                )
                publish_artifacts(
                    publication_dir,
                    output_dir,
                    artifact_destination=artifact_destination,
                    r2_bucket=r2_bucket,
                    r2_prefix=r2_prefix,
                    session_id=session_id,
                    year=int(required(message, "year")),
                    source_dataset=(
                        data_dir / "processed" / "sessions" / session_id / "dataset.json"
                    ),
                )
                payload = build_success_payload(
                    publication_dir, session_id, summary["generated_at"]
                )
                write_success_payload(success_payload_file, payload)
                if not defer_terminal_callbacks:
                    callback_job_status(callback_url, callback_token, job_id, payload)
                artifacts = payload["artifacts"]
                return {"job_id": job_id, "session_id": session_id, "artifacts": len(artifacts)}

        if artifact_destination == "r2":
            generation_id = publication_generation_id(publication_dir, session_id)
            sync_artifacts_to_r2(
                publication_dir,
                required_value(r2_bucket, "--r2-bucket"),
                r2_prefix,
                session_id=session_id,
                year=int(required(message, "year")),
                include_indexes=False,
                generation_id=generation_id,
            )
            verify_remote_publication(
                publication_dir,
                required_value(r2_bucket, "--r2-bucket"),
                r2_prefix,
                session_id,
                generation_id=generation_id,
            )
            publish_active_generation(
                publication_dir,
                required_value(r2_bucket, "--r2-bucket"),
                r2_prefix,
                session_id,
                generation_id,
            )

        payload = build_success_payload(publication_dir, session_id, summary["generated_at"])
        write_success_payload(success_payload_file, payload)
        if not defer_terminal_callbacks:
            callback_job_status(callback_url, callback_token, job_id, payload)
        artifacts = payload["artifacts"]
        return {"job_id": job_id, "session_id": session_id, "artifacts": len(artifacts)}
    except Exception as exc:
        if not defer_terminal_callbacks:
            callback_job_status(
                callback_url,
                callback_token,
                job_id,
                {"status": "failed", "error_message": str(exc)},
            )
        raise


def load_messages(message_file: Path | None, queue_file: Path | None) -> Iterable[dict[str, Any]]:
    if message_file:
        yield read_json(message_file)
    if queue_file:
        with queue_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def expected_session_id(message: dict[str, Any]) -> str:
    session_id = str(message.get("session_id") or "").strip()
    if session_id:
        return session_id
    year = int(required(message, "year"))
    round_number = int(required(message, "round"))
    session = str(required(message, "session")).strip().lower()
    return f"{year}-{round_number:02d}-{session}"


def session_artifacts_exist(output_dir: Path, session_id: str) -> bool:
    return (output_dir / "sessions" / session_id / "manifest.json").exists()


def summarize_existing_artifacts(output_dir: Path) -> dict[str, Any]:
    artifacts = list(output_dir.rglob("*.json")) if output_dir.exists() else []
    catalog_path = output_dir / "catalog.json"
    generated_at = None
    if catalog_path.exists():
        generated_at = read_json(catalog_path).get("generated_at")
    return {
        "generated_at": generated_at,
        "artifact_count": len(artifacts),
        "total_size_bytes": sum(path.stat().st_size for path in artifacts),
    }


def collect_session_artifacts(output_dir: Path, session_id: str) -> list[dict[str, Any]]:
    manifest_path = output_dir / "sessions" / session_id / "manifest.json"
    manifest = read_json(manifest_path)
    generated_at = manifest.get("generated_at")
    sections = manifest.get("sections", [])
    artifacts = []
    telemetry_sections = [section for section in sections if section.get("kind") == "telemetry-lap"]
    for section in sections:
        if section.get("kind") == "telemetry-lap":
            continue
        artifact = {
            "kind": section.get("kind"),
            "path": section.get("path"),
            "size_bytes": section.get("size_bytes"),
            "checksum": section.get("checksum"),
            "generated_at": generated_at,
        }
        if section.get("kind") == "telemetry-index":
            artifact["metadata"] = {
                "lap_file_count": len(telemetry_sections),
                "lap_count": int(manifest.get("telemetry", {}).get("lap_count") or 0),
                "sample_count": int(manifest.get("telemetry", {}).get("sample_count") or 0),
                "max_samples_per_lap": int(
                    manifest.get("telemetry", {}).get("max_samples_per_lap") or 0
                ),
                "total_size_bytes": sum(
                    int(item.get("size_bytes") or 0) for item in telemetry_sections
                ),
            }
        artifacts.append(artifact)
    return artifacts


def build_success_payload(
    output_dir: Path, session_id: str, generated_at: str | None
) -> dict[str, Any]:
    manifest_path = output_dir / "sessions" / session_id / "manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("session_id") != session_id or not isinstance(manifest.get("sections"), list):
        raise ValueError(f"Invalid session manifest for {session_id}")
    sections = manifest["sections"]
    available = sorted(
        {
            str(section.get("kind"))
            for section in sections
            if section.get("kind") and section.get("kind") != "telemetry-lap"
        }
    )
    if "summary" not in available:
        raise ValueError(f"Session manifest for {session_id} is missing the core summary artifact")
    optional = (set(SESSION_SECTION_FILES) - {"summary"}) | {"telemetry-index"}
    missing = sorted(optional - set(available))
    return {
        "status": "succeeded",
        "generated_at": generated_at or manifest.get("generated_at"),
        "manifest": {
            "kind": "manifest",
            "path": f"sessions/{session_id}/manifest.json",
            "size_bytes": manifest_path.stat().st_size,
            "checksum": checksum_file(manifest_path),
            "generated_at": generated_at or manifest.get("generated_at"),
        },
        "artifacts": collect_session_artifacts(output_dir, session_id),
        "quality": {
            "status": "partial" if missing else "complete",
            "missing_sections": missing,
            "available_sections": available,
        },
    }


def write_success_payload(path: Path | None, payload: dict[str, Any]) -> None:
    if path:
        write_json(path, payload)


def sync_artifacts_to_r2(
    output_dir: Path,
    bucket: str,
    prefix: str = "",
    *,
    session_id: str,
    year: int,
    include_indexes: bool = True,
    generation_id: str | None = None,
) -> None:
    """Upload a session first and publish its indexes last."""
    normalized_prefix = prefix.strip("/")
    session_dir = output_dir / "sessions" / session_id
    session_files = sorted(session_dir.rglob("*.json")) if session_dir.exists() else []
    manifest = session_dir / "manifest.json"
    candidates = [path for path in session_files if path != manifest]
    if manifest.is_file():
        candidates.append(manifest)
    if include_indexes:
        candidates.extend([output_dir / "seasons" / f"{year}.json", output_dir / "catalog.json"])
    for path in candidates:
        if not path.is_file():
            continue
        key = path.relative_to(output_dir).as_posix()
        if generation_id and key.startswith(f"sessions/{session_id}/"):
            relative = key.removeprefix(f"sessions/{session_id}/")
            key = f"sessions/{session_id}/generations/{generation_id}/{relative}"
        if normalized_prefix:
            key = f"{normalized_prefix}/{key}"
        subprocess.run(
            ["wrangler", "r2", "object", "put", f"{bucket}/{key}", "--file", str(path), "--remote"],
            check=True,
        )


def publish_artifacts(
    publication_dir: Path,
    output_dir: Path,
    *,
    artifact_destination: str,
    r2_bucket: str | None,
    r2_prefix: str,
    session_id: str,
    year: int,
    source_dataset: Path,
) -> None:
    if artifact_destination == "r2":
        bucket = required_value(r2_bucket, "--r2-bucket")
        generation_id = publication_generation_id(publication_dir, session_id)
        if source_dataset.is_file():
            upload_r2_object(
                source_dataset,
                bucket,
                object_key(r2_prefix, f"source/sessions/{session_id}/dataset.json"),
            )
        sync_artifacts_to_r2(
            publication_dir,
            bucket,
            r2_prefix,
            session_id=session_id,
            year=year,
            include_indexes=False,
            generation_id=generation_id,
        )
        verify_remote_publication(
            publication_dir, bucket, r2_prefix, session_id, generation_id=generation_id
        )
        publish_active_generation(
            publication_dir, bucket, r2_prefix, session_id, generation_id
        )
        sync_shared_indexes_to_r2(publication_dir, bucket, r2_prefix, year=year)
        return
    publish_session_artifacts_locally(publication_dir, output_dir, session_id=session_id)
    verify_local_publication(output_dir, session_id)
    publish_shared_indexes_locally(publication_dir, output_dir, year=year)


def publish_session_artifacts_locally(
    publication_dir: Path,
    output_dir: Path,
    *,
    session_id: str,
) -> None:
    session_dir = publication_dir / "sessions" / session_id
    manifest = session_dir / "manifest.json"
    for path in sorted(session_dir.rglob("*.json")):
        if path != manifest:
            copy_file_atomic(path, output_dir / path.relative_to(publication_dir))
    if manifest.is_file():
        copy_file_atomic(manifest, output_dir / manifest.relative_to(publication_dir))


def publish_shared_indexes_locally(
    publication_dir: Path, output_dir: Path, *, year: int
) -> None:
    for path in [publication_dir / "seasons" / f"{year}.json", publication_dir / "catalog.json"]:
        if path.is_file():
            copy_file_atomic(path, output_dir / path.relative_to(publication_dir))


def sync_shared_indexes_to_r2(
    output_dir: Path, bucket: str, prefix: str = "", *, year: int
) -> None:
    for path in [output_dir / "seasons" / f"{year}.json", output_dir / "catalog.json"]:
        if path.is_file():
            upload_r2_object(path, bucket, object_key(prefix, path.relative_to(output_dir).as_posix()))


def copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def upload_r2_object(path: Path, bucket: str, key: str) -> None:
    subprocess.run(
        ["wrangler", "r2", "object", "put", f"{bucket}/{key}", "--file", str(path), "--remote"],
        check=True,
    )


def hydrate_r2_indexes(destination: Path, bucket: str, prefix: str, year: int) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    download_r2_object(
        bucket,
        object_key(prefix, "catalog.json"),
        destination / "catalog.json",
        required=True,
    )
    catalog = read_json(destination / "catalog.json")
    season_exists = any(int(row.get("year") or 0) == year for row in catalog.get("seasons", []))
    download_r2_object(
        bucket,
        object_key(prefix, f"seasons/{year}.json"),
        destination / "seasons" / f"{year}.json",
        required=season_exists,
    )


def download_r2_object(
    bucket: str,
    key: str,
    destination: Path,
    *,
    required: bool,
    error_context: str = "R2 index",
) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "wrangler",
            "r2",
            "object",
            "get",
            f"{bucket}/{key}",
            "--file",
            str(destination),
            "--remote",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if destination.exists():
        destination.unlink()
    if required:
        detail = (result.stderr or result.stdout or "unknown Wrangler error").strip()
        action = "hydrate" if error_context == "R2 index" else "download"
        raise RuntimeError(f"Could not {action} required {error_context} {key}: {detail}")
    return False


def verify_remote_manifest(
    output_dir: Path,
    bucket: str,
    prefix: str,
    session_id: str,
    generation_id: str | None = None,
) -> dict[str, Any]:
    local_path = output_dir / "sessions" / session_id / "manifest.json"
    if not local_path.is_file():
        raise RuntimeError(f"Local manifest is missing for {session_id}")
    with tempfile.TemporaryDirectory(prefix="f1-manifest-check-") as temporary_directory:
        remote_path = Path(temporary_directory) / "manifest.json"
        key = object_key(
            prefix,
            remote_session_artifact_path(session_id, "manifest.json", generation_id),
        )
        download_r2_object(
            bucket,
            key,
            remote_path,
            required=True,
            error_context="R2 manifest",
        )
        if remote_path.stat().st_size != local_path.stat().st_size:
            raise RuntimeError(f"Remote R2 manifest size mismatch for {session_id}")
        if checksum_file(remote_path) != checksum_file(local_path):
            raise RuntimeError(f"Remote R2 manifest checksum mismatch for {session_id}")
        manifest = read_json(remote_path)
        if manifest.get("session_id") != session_id or not isinstance(
            manifest.get("sections"), list
        ):
            raise RuntimeError(f"Remote R2 manifest is invalid for {session_id}")
        return manifest


def verify_remote_publication(
    output_dir: Path,
    bucket: str,
    prefix: str,
    session_id: str,
    generation_id: str | None = None,
) -> dict[str, Any]:
    """Verify every manifest-referenced R2 object before shared indexes are published."""
    manifest = verify_remote_manifest(
        output_dir, bucket, prefix, session_id, generation_id=generation_id
    )
    sections = validate_manifest_sections(output_dir, manifest, session_id)
    with tempfile.TemporaryDirectory(prefix="f1-publication-check-") as temporary_directory:
        remote_path = Path(temporary_directory) / "artifact.json"
        for section in sections:
            if remote_path.exists():
                remote_path.unlink()
            download_r2_object(
                bucket,
                object_key(
                    prefix,
                    remote_session_artifact_path(
                        session_id,
                        section["path"].removeprefix(f"sessions/{session_id}/"),
                        generation_id,
                    ),
                ),
                remote_path,
                required=True,
                error_context="R2 artifact",
            )
            verify_artifact_file(remote_path, section, "Remote R2")
    return {"session_id": session_id, "artifact_count": len(sections), "verified": True}


def verify_local_publication(output_dir: Path, session_id: str) -> dict[str, Any]:
    manifest_path = output_dir / "sessions" / session_id / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"Published manifest is missing for {session_id}")
    manifest = read_json(manifest_path)
    sections = validate_manifest_sections(output_dir, manifest, session_id)
    for section in sections:
        verify_artifact_file(output_dir / section["path"], section, "Published local")
    return {"session_id": session_id, "artifact_count": len(sections), "verified": True}


def validate_manifest_sections(
    output_dir: Path, manifest: dict[str, Any], session_id: str
) -> list[dict[str, Any]]:
    if manifest.get("session_id") != session_id or not isinstance(manifest.get("sections"), list):
        raise RuntimeError(f"Manifest is invalid for {session_id}")
    expected_prefix = f"sessions/{session_id}/"
    sections: list[dict[str, Any]] = []
    paths: set[str] = set()
    for section in manifest["sections"]:
        if not isinstance(section, dict):
            raise RuntimeError(f"Manifest contains an invalid section for {session_id}")
        path = str(section.get("path") or "")
        if (
            not path.startswith(expected_prefix)
            or ".." in Path(path).parts
            or path in paths
            or not isinstance(section.get("size_bytes"), int)
            or int(section["size_bytes"]) < 0
            or not str(section.get("checksum") or "").startswith("sha256:")
        ):
            raise RuntimeError(f"Manifest contains an invalid artifact record for {session_id}: {path}")
        paths.add(path)
        sections.append(section)

    if not any(section.get("kind") == "summary" for section in sections):
        raise RuntimeError(f"Manifest is missing the core summary artifact for {session_id}")

    telemetry_indexes = [section for section in sections if section.get("kind") == "telemetry-index"]
    telemetry_laps = {section["path"] for section in sections if section.get("kind") == "telemetry-lap"}
    if len(telemetry_indexes) != 1:
        raise RuntimeError(f"Manifest must contain one telemetry index for {session_id}")
    telemetry_index_path = output_dir / telemetry_indexes[0]["path"]
    if not telemetry_index_path.is_file():
        raise RuntimeError(f"Local telemetry index is missing for {session_id}")
    telemetry_index = read_json(telemetry_index_path)
    indexed_laps = {
        f"sessions/{session_id}/{lap.get('path')}"
        for lap in telemetry_index.get("laps", [])
        if isinstance(lap, dict) and lap.get("path")
    }
    if indexed_laps != telemetry_laps:
        raise RuntimeError(f"Telemetry index and manifest disagree for {session_id}")
    return sections


def verify_artifact_file(path: Path, section: dict[str, Any], source: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{source} artifact is missing: {section['path']}")
    if path.stat().st_size != int(section["size_bytes"]):
        raise RuntimeError(f"{source} artifact size mismatch: {section['path']}")
    if checksum_file(path) != section["checksum"]:
        raise RuntimeError(f"{source} artifact checksum mismatch: {section['path']}")


def publication_generation_id(output_dir: Path, session_id: str) -> str:
    manifest_path = output_dir / "sessions" / session_id / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"Local manifest is missing for {session_id}")
    return checksum_file(manifest_path).removeprefix("sha256:")


def remote_session_artifact_path(
    session_id: str, relative_path: str, generation_id: str | None
) -> str:
    if generation_id:
        return f"sessions/{session_id}/generations/{generation_id}/{relative_path}"
    return f"sessions/{session_id}/{relative_path}"


def publish_active_generation(
    output_dir: Path,
    bucket: str,
    prefix: str,
    session_id: str,
    generation_id: str,
) -> dict[str, Any]:
    manifest_path = output_dir / "sessions" / session_id / "manifest.json"
    pointer = {
        "schema_version": 1,
        "session_id": session_id,
        "artifact_base_path": f"sessions/{session_id}/generations/{generation_id}",
        "generated_at": read_json(manifest_path).get("generated_at"),
        "manifest": {
            "size_bytes": manifest_path.stat().st_size,
            "checksum": checksum_file(manifest_path),
        },
    }
    with tempfile.TemporaryDirectory(prefix="f1-active-generation-") as temporary_directory:
        local_pointer = Path(temporary_directory) / "active.json"
        remote_pointer = Path(temporary_directory) / "active-remote.json"
        write_json(local_pointer, pointer)
        key = object_key(prefix, f"sessions/{session_id}/active.json")
        upload_r2_object(local_pointer, bucket, key)
        download_r2_object(
            bucket,
            key,
            remote_pointer,
            required=True,
            error_context="R2 active generation",
        )
        if (
            remote_pointer.stat().st_size != local_pointer.stat().st_size
            or checksum_file(remote_pointer) != checksum_file(local_pointer)
        ):
            raise RuntimeError(f"Remote R2 active generation mismatch for {session_id}")
    return pointer


def object_key(prefix: str, path: str) -> str:
    normalized_prefix = prefix.strip("/")
    return f"{normalized_prefix}/{path}" if normalized_prefix else path


def callback_job_status(
    callback_url: str | None,
    callback_token: str | None,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    if not callback_url:
        return
    endpoint = callback_endpoint(callback_url, job_id)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Formula1Data-IngestionRunner/1.0",
    }
    if callback_token:
        headers["Authorization"] = f"Bearer {callback_token}"
    access_client_id = os.getenv("CF_ACCESS_CLIENT_ID")
    access_client_secret = os.getenv("CF_ACCESS_CLIENT_SECRET")
    if access_client_id and access_client_secret:
        headers["CF-Access-Client-Id"] = access_client_id
        headers["CF-Access-Client-Secret"] = access_client_secret
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status >= 400:
                raise RuntimeError(f"Callback returned {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Callback returned {exc.code}: {detail}") from exc


def callback_endpoint(callback_url: str, job_id: str) -> str:
    if "{job_id}" in callback_url:
        return callback_url.format(job_id=urllib.parse.quote(job_id, safe=""))
    if callback_url.rstrip("/").endswith("/status"):
        return callback_url
    encoded_job_id = urllib.parse.quote(job_id, safe="")
    return f"{callback_url.rstrip('/')}/api/ingestion/jobs/{encoded_job_id}/status"


def configure_backend_data_dir(data_dir: Path) -> None:
    data_dir = data_dir.resolve()
    os.environ.setdefault("DATA_DIR", str(data_dir))
    os.environ.setdefault("FASTF1_CACHE_DIR", str(data_dir / "cache" / "fastf1"))


def load_fastf1_ingestor() -> Any:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.ingestion.fastf1_ingestor import FastF1Ingestor

    return FastF1Ingestor


def required(message: dict[str, Any], key: str) -> Any:
    value = message.get(key)
    if value is None or value == "":
        raise ValueError(f"Queue message is missing {key}")
    return value


def required_value(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"{name} is required")
    return value


if __name__ == "__main__":
    main()
