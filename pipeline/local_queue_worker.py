from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from pipeline.artifacts import DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR, build_static_artifacts, read_json


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
            print(f"Using existing static artifacts for {session_id}.")
        else:
            FastF1Ingestor = load_fastf1_ingestor()
            session_id = FastF1Ingestor().ingest_session(
                year=int(required(message, "year")),
                event=int(required(message, "round")),
                session_name=str(required(message, "session")),
                force=should_force,
            )
            summary = build_static_artifacts(data_dir=data_dir, output_dir=output_dir)

        if artifact_destination == "r2":
            sync_artifacts_to_r2(output_dir, required_value(r2_bucket, "--r2-bucket"), r2_prefix)

        artifacts = collect_session_artifacts(output_dir, session_id)
        payload = {
            "status": "succeeded",
            "generated_at": summary["generated_at"],
            "artifacts": artifacts,
        }
        callback_job_status(callback_url, callback_token, job_id, payload)
        return {"job_id": job_id, "session_id": session_id, "artifacts": len(artifacts)}
    except Exception as exc:
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
    artifacts = []
    for section in manifest.get("sections", []):
        artifacts.append(
            {
                "kind": section.get("kind"),
                "path": section.get("path"),
                "size_bytes": section.get("size_bytes"),
                "checksum": section.get("checksum"),
                "generated_at": generated_at,
            }
        )
    return artifacts


def sync_artifacts_to_r2(output_dir: Path, bucket: str, prefix: str = "") -> None:
    normalized_prefix = prefix.strip("/")
    for path in output_dir.rglob("*.json"):
        key = path.relative_to(output_dir).as_posix()
        if normalized_prefix:
            key = f"{normalized_prefix}/{key}"
        subprocess.run(
            ["wrangler", "r2", "object", "put", f"{bucket}/{key}", "--file", str(path), "--remote"],
            check=True,
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
