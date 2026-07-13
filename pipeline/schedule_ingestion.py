from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any


DEFAULT_CATALOG = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "public"
    / "data"
    / "catalog.json"
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Queue completed catalog sessions through the Worker API."
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--worker-url", default=os.getenv("WORKER_BASE_URL"))
    parser.add_argument(
        "--through-date", type=date.fromisoformat, default=date.today() - timedelta(days=1)
    )
    parser.add_argument("--lookback-days", type=int, default=4)
    parser.add_argument("--years", nargs="*", type=int)
    parser.add_argument("--sessions", nargs="*")
    parser.add_argument("--races-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    candidates = select_candidates(
        catalog,
        through_date=args.through_date,
        lookback_days=None if args.years else args.lookback_days,
        years=set(args.years or []),
        sessions={value.upper() for value in args.sessions or []},
        races_only=args.races_only,
    )
    if args.dry_run:
        for candidate in candidates:
            print(
                f"Would queue {candidate['year']} round {candidate['round']} "
                f"{candidate['session']}"
            )
        print(f"Planned {len(candidates)} session(s).")
        return
    if not args.worker_url:
        raise SystemExit("--worker-url or WORKER_BASE_URL is required unless --dry-run is used.")

    headers = request_headers()
    queued = 0
    skipped = 0
    for candidate in candidates:
        status = get_status(args.worker_url, candidate, headers)
        if status.get("status") in {"queued", "ingesting"} or (
            status.get("status") == "ready" and not args.force
        ):
            skipped += 1
            continue
        post_json(
            f"{args.worker_url.rstrip('/')}/api/ingestion/session",
            {**candidate, "force": args.force},
            headers,
        )
        queued += 1
    print(f"Queued {queued} session(s); skipped {skipped} already active or ready session(s).")


def select_candidates(
    catalog: dict[str, Any],
    *,
    through_date: date,
    lookback_days: int | None,
    years: set[int],
    sessions: set[str],
    races_only: bool,
) -> list[dict[str, Any]]:
    earliest = (
        through_date - timedelta(days=max(0, lookback_days or 0))
        if lookback_days is not None
        else None
    )
    selected = []
    for meeting in catalog.get("meetings", []):
        meeting_date = date.fromisoformat(str(meeting["start_date"])[:10])
        year = int(meeting["year"])
        if (
            meeting_date > through_date
            or (earliest and meeting_date < earliest)
            or (years and year not in years)
        ):
            continue
        available = [str(value).upper() for value in meeting.get("sessions_available", [])]
        if races_only:
            available = ["R"] if "R" in available else []
        elif sessions:
            available = [value for value in available if value in sessions]
        for session in available:
            selected.append(
                {
                    "year": year,
                    "round": int(meeting["round"]),
                    "session": session,
                    "meeting_id": meeting.get("meeting_id"),
                    "meeting_name": meeting.get("name"),
                }
            )
    return selected


def request_headers() -> dict[str, str]:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": "Formula1DataIngestion/1.0",
    }
    access_id = os.getenv("CF_ACCESS_CLIENT_ID")
    access_secret = os.getenv("CF_ACCESS_CLIENT_SECRET")
    if access_id and access_secret:
        headers["CF-Access-Client-Id"] = access_id
        headers["CF-Access-Client-Secret"] = access_secret
    else:
        token = os.getenv("INGESTION_API_TOKEN")
        if token:
            headers["authorization"] = f"Bearer {token}"
    return headers


def get_status(
    worker_url: str, candidate: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {key: candidate[key] for key in ("year", "round", "session")}
    )
    request = urllib.request.Request(
        f"{worker_url.rstrip('/')}/api/session-status?{query}",
        headers={
            name: value
            for name, value in headers.items()
            if name.lower() not in {"cf-access-client-id", "cf-access-client-secret"}
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            detail = body.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"Ingestion API returned a non-JSON response from {response.url}: {detail[:500]}"
            ) from error


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


if __name__ == "__main__":
    main()
