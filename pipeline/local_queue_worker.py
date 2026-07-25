from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

from pipeline.artifacts import (
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    SESSION_SECTION_FILES,
    build_static_artifacts,
    checksum_file,
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
                summary = build_static_artifacts(
                    data_dir=data_dir,
                    output_dir=publication_dir,
                    session_ids={session_id},
                )
                merge_incremental_indexes(
                    existing_indexes_dir, publication_dir, int(required(message, "year"))
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
                if artifact_destination == "r2":
                    verify_remote_manifest(
                        publication_dir,
                        required_value(r2_bucket, "--r2-bucket"),
                        r2_prefix,
                        session_id,
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
            sync_artifacts_to_r2(
                publication_dir,
                required_value(r2_bucket, "--r2-bucket"),
                r2_prefix,
                session_id=session_id,
                year=int(required(message, "year")),
                include_indexes=False,
            )
            verify_remote_manifest(
                publication_dir,
                required_value(r2_bucket, "--r2-bucket"),
                r2_prefix,
                session_id,
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
) -> None:
    """Upload a session first and publish its indexes last."""
    normalized_prefix = prefix.strip("/")
    session_dir = output_dir / "sessions" / session_id
    session_files = sorted(session_dir.rglob("*.json")) if session_dir.exists() else []
    manifest = session_dir / "manifest.json"

    # The manifest and the season/catalog indexes are commit markers: readers
    # treat them as the signal that a session is complete, so they must land
    # only after every file they reference. Bodies upload concurrently; the
    # markers stay strictly ordered and serial behind them.
    bodies = [path for path in session_files if path != manifest and path.is_file()]
    markers = [manifest] if manifest.is_file() else []
    if include_indexes:
        markers.extend([output_dir / "seasons" / f"{year}.json", output_dir / "catalog.json"])

    def object_key(path: Path) -> str:
        key = path.relative_to(output_dir).as_posix()
        return f"{normalized_prefix}/{key}" if normalized_prefix else key

    # One wrangler invocation costs a full Node process start, so a session's
    # ~1k telemetry files took ~28 minutes serially. Overlap them instead.
    #
    # The default is deliberately conservative. R2's REST API is rate limited
    # per account, and a session issues on the order of a thousand PUTs; at
    # roughly a second per upload, four in flight stays well inside the budget
    # while still cutting the wall clock by about 4x.
    max_workers = max(1, int(os.getenv("R2_UPLOAD_CONCURRENCY", "4")))
    if bodies:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(upload_r2_object, path, bucket, object_key(path)) for path in bodies
            ]
            try:
                for future in as_completed(futures):
                    future.result()
            except Exception:
                # Bodies are overwritten in place over the live session, so a
                # failure part-way leaves the published manifest pointing at a
                # mix of old and new files. Cancelling drops uploads that have
                # not started yet; ones already running still finish, because
                # leaving the executor shuts it down with wait=True. This only
                # narrows the window. Publishing to immutable per-generation
                # keys is the actual fix and is not done here.
                for pending in futures:
                    pending.cancel()
                raise

    for path in markers:
        if path.is_file():
            upload_r2_object(path, bucket, object_key(path))


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
        )
        return
    publish_artifacts_locally(publication_dir, output_dir, session_id=session_id, year=year)


def publish_artifacts_locally(
    publication_dir: Path,
    output_dir: Path,
    *,
    session_id: str,
    year: int,
) -> None:
    session_dir = publication_dir / "sessions" / session_id
    manifest = session_dir / "manifest.json"
    for path in sorted(session_dir.rglob("*.json")):
        if path != manifest:
            copy_file_atomic(path, output_dir / path.relative_to(publication_dir))
    if manifest.is_file():
        copy_file_atomic(manifest, output_dir / manifest.relative_to(publication_dir))
    for path in [publication_dir / "seasons" / f"{year}.json", publication_dir / "catalog.json"]:
        if path.is_file():
            copy_file_atomic(path, output_dir / path.relative_to(publication_dir))


def copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


class _RequestPacer:
    """Spaces request starts so concurrent uploads cannot outrun R2's budget.

    Cloudflare meters its REST API per account over a rolling window, so what
    matters is the request *rate*, not how many uploads are in flight. Worker
    count alone does not bound the rate: if wrangler returns quickly, N workers
    simply issue N times as many requests per second. This paces every start.
    """

    def __init__(self, per_second: float) -> None:
        self._interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next_start = 0.0

    def acquire(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start_at = max(now, self._next_start)
            self._next_start = start_at + self._interval
        delay = start_at - now
        if delay > 0:
            # Sleep outside the lock so other workers can claim later slots.
            time.sleep(delay)


def _build_request_pacer() -> _RequestPacer:
    # R2's documented ceiling is 1200 REST operations per five minutes (4/s).
    # Default below it for headroom; 0 disables pacing entirely.
    return _RequestPacer(float(os.getenv("R2_UPLOAD_RATE_PER_SECOND", "3")))


_REQUEST_PACER = _build_request_pacer()

# Signals that a failure was throttling rather than a genuine error. Cloudflare
# blocks further calls for the remainder of the window once the quota is spent,
# so these back off on a much longer scale than an ordinary retry.
_THROTTLE_MARKERS = ("429", "rate limit", "rate-limit", "too many requests", "quota")


def upload_r2_object(path: Path, bucket: str, key: str) -> None:
    # Output is captured rather than inherited: uploads now run concurrently, so
    # wrangler's per-invocation banner would interleave into unreadable noise,
    # and a session emits roughly a thousand of them. Surface it only on failure.
    #
    # Retried with backoff because R2's REST API is rate limited per account and
    # a session issues on the order of a thousand PUTs. A throttled upload
    # should wait and retry rather than fail the whole ingestion, which would
    # otherwise leave the session half-overwritten.
    attempts = max(1, int(os.getenv("R2_UPLOAD_ATTEMPTS", "3")))
    for attempt in range(1, attempts + 1):
        _REQUEST_PACER.acquire()
        result = subprocess.run(
            ["wrangler", "r2", "object", "put", f"{bucket}/{key}", "--file", str(path), "--remote"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
        # str() rather than a bare join: callers patch subprocess.run in tests,
        # and a non-string stdout should not turn a failure into a TypeError.
        detail = "\n".join(str(part) for part in (result.stdout, result.stderr) if part).strip()
        if attempt == attempts:
            raise RuntimeError(
                f"wrangler failed to upload {key} after {attempts} attempt(s) "
                f"(exit {result.returncode}):\n{detail}"
            )
        lowered = detail.lower()
        if any(marker in lowered for marker in _THROTTLE_MARKERS):
            # Wrangler does not surface Retry-After, and the quota window is
            # five minutes, so wait on that scale rather than seconds.
            time.sleep(min(60 * attempt, 300))
        else:
            time.sleep(min(2**attempt, 30))


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
    output_dir: Path, bucket: str, prefix: str, session_id: str
) -> dict[str, Any]:
    local_path = output_dir / "sessions" / session_id / "manifest.json"
    if not local_path.is_file():
        raise RuntimeError(f"Local manifest is missing for {session_id}")
    with tempfile.TemporaryDirectory(prefix="f1-manifest-check-") as temporary_directory:
        remote_path = Path(temporary_directory) / "manifest.json"
        key = object_key(prefix, f"sessions/{session_id}/manifest.json")
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


def object_key(prefix: str, path: str) -> str:
    normalized_prefix = prefix.strip("/")
    return f"{normalized_prefix}/{path}" if normalized_prefix else path


def merge_incremental_indexes(existing_dir: Path, publication_dir: Path, year: int) -> None:
    catalog_path = publication_dir / "catalog.json"
    existing_catalog_path = existing_dir / "catalog.json"
    if existing_catalog_path.is_file() and catalog_path.is_file():
        write_json(
            catalog_path,
            merge_catalog(read_json(existing_catalog_path), read_json(catalog_path)),
        )

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
    result["meetings"].sort(key=lambda row: (int(row.get("year") or 0), int(row.get("round") or 0)))
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
