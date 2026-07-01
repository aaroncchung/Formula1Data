import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingestion.fastf1_ingestor import FastF1Ingestor  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest race sessions for one season.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        count = FastF1Ingestor().ingest_season(year=args.year, force=args.force)
    except Exception as exc:
        raise SystemExit(f"Season ingestion failed: {exc}") from exc

    print(f"Ingested {count} race sessions for {args.year}.")


if __name__ == "__main__":
    main()

