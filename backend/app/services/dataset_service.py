from copy import deepcopy
from typing import Any

from app.models.errors import NotFoundError
from app.services.storage_service import StorageService


class DatasetService:
    def __init__(self, storage: StorageService | None = None) -> None:
        self.storage = storage or StorageService()

    def load_all(self) -> dict[str, Any]:
        merged = self._empty_dataset()
        if self.storage.exists("processed/sample/dataset.json"):
            merged = self._merge(merged, self.storage.read_json("processed/sample/dataset.json"))

        for session_dir in self.storage.list("processed/sessions"):
            artifact = f"processed/sessions/{session_dir}/dataset.json"
            if self.storage.exists(artifact):
                merged = self._merge(merged, self.storage.read_json(artifact))
        return merged

    def list_seasons(self) -> list[dict[str, Any]]:
        return self.load_all()["seasons"]

    def list_meetings(self, year: int) -> list[dict[str, Any]]:
        return [meeting for meeting in self.load_all()["meetings"] if meeting["year"] == year]

    def list_sessions(self, year: int, round_number: int) -> list[dict[str, Any]]:
        return [
            session
            for session in self.load_all()["sessions"]
            if session["year"] == year and session["round"] == round_number
        ]

    def get_session_bundle(self, session_id: str) -> dict[str, Any]:
        session_data = self.load_all()["session_data"]
        if session_id not in session_data:
            raise NotFoundError(
                "Session data has not been ingested",
                {
                    "session_id": session_id,
                    "action": "Use POST /api/v1/ingest/session or run scripts/ingest_session.py.",
                },
            )
        return session_data[session_id]

    def get_session_section(self, session_id: str, section: str) -> Any:
        bundle = self.get_session_bundle(session_id)
        if section not in bundle:
            raise NotFoundError(
                "Session section is unavailable",
                {"session_id": session_id, "section": section},
            )
        return bundle[section]

    def write_session_dataset(self, session_id: str, dataset: dict[str, Any]) -> None:
        self.storage.write_json(f"processed/sessions/{session_id}/dataset.json", dataset)

    def _empty_dataset(self) -> dict[str, Any]:
        return {"seasons": [], "meetings": [], "sessions": [], "session_data": {}}

    def _merge(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        output = deepcopy(left)
        output["seasons"] = self._dedupe(left["seasons"] + right.get("seasons", []), "year")
        output["meetings"] = self._dedupe(left["meetings"] + right.get("meetings", []), "meeting_id")
        output["sessions"] = self._dedupe(left["sessions"] + right.get("sessions", []), "session_id")
        output["session_data"] = {**left["session_data"], **right.get("session_data", {})}
        return output

    def _dedupe(self, rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        values: dict[Any, dict[str, Any]] = {}
        for row in rows:
            values[row[key]] = row
        return list(values.values())

