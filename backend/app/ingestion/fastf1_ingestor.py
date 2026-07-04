from app.ingestion.normalizer import (
    normalize_fastf1_schedule,
    normalize_fastf1_session,
    selected_session_codes,
    session_code_for_name,
)
from app.services.dataset_service import DatasetService
from app.services.fastf1_service import FastF1Service
from app.services.storage_service import StorageService


class FastF1Ingestor:
    def __init__(self) -> None:
        self.fastf1 = FastF1Service()
        self.storage = StorageService()
        self.datasets = DatasetService(self.storage)

    def ingest_session(self, year: int, event: str | int, session_name: str, force: bool = False) -> str:
        existing_id = self._guess_session_id(year, event, session_name)
        if not force and self.storage.exists(f"processed/sessions/{existing_id}/dataset.json"):
            return existing_id

        session = self.fastf1.load_session(year, event, session_name)
        dataset = normalize_fastf1_session(year, event, session_name, session)
        session_id = next(iter(dataset["session_data"].keys()))
        if not force and self.storage.exists(f"processed/sessions/{session_id}/dataset.json"):
            return session_id

        self.storage.write_json(f"raw/{session_id}/metadata.json", {"year": year, "event": event})
        self.datasets.write_session_dataset(session_id, dataset)
        return session_id

    def ingest_season(
        self,
        year: int,
        force: bool = False,
        sessions: list[str] | None = None,
        races_only: bool = False,
    ) -> int:
        schedule = self.fastf1.get_schedule(year)
        schedule_dataset = normalize_fastf1_schedule(year, schedule)
        self.datasets.write_season_dataset(year, schedule_dataset)
        count = 0
        for _, row in schedule.iterrows():
            round_number = int(row.get("RoundNumber") or 0)
            if round_number <= 0:
                continue
            event_name = str(row.get("EventName") or "")
            if not event_name:
                continue
            for session_code in selected_session_codes(row, sessions=sessions, races_only=races_only):
                try:
                    self.ingest_session(year, round_number, session_code, force=force)
                except Exception as exc:
                    print(
                        f"Skipped {year} round {round_number} {session_code} "
                        f"({event_name}): {exc}"
                    )
                    continue
                else:
                    count += 1
        return count

    def _guess_session_id(self, year: int, event: str | int, session_name: str) -> str:
        code = session_code_for_name(session_name).lower()
        if isinstance(event, int) or str(event).isdigit():
            return f"{year}-{int(event):02d}-{code}"
        slug = "".join(char.lower() if char.isalnum() else "-" for char in str(event)).strip("-")
        return f"{year}-{slug}-{code}"

