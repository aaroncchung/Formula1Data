import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingestion.fastf1_ingestor import FastF1Ingestor  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest one FastF1 session.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        session_id = FastF1Ingestor().ingest_session(
            year=args.year,
            event=args.event,
            session_name=args.session,
            force=args.force,
        )
    except Exception as exc:
        raise SystemExit(f"Ingestion failed: {exc}") from exc

    print(f"Ingested session: {session_id}")


if __name__ == "__main__":
    main()

