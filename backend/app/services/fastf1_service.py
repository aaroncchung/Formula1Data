from pathlib import Path
from typing import Any

from app.config import get_settings


class FastF1Service:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._fastf1: Any | None = None

    @property
    def fastf1(self) -> Any:
        if self._fastf1 is None:
            try:
                import fastf1
            except ImportError as exc:
                raise RuntimeError(
                    "FastF1 is not installed. Run `pip install -r backend/requirements.txt`."
                ) from exc
            self._fastf1 = fastf1
            Path(self.settings.fastf1_cache_dir).mkdir(parents=True, exist_ok=True)
            fastf1.Cache.enable_cache(str(self.settings.fastf1_cache_dir))
        return self._fastf1

    def get_schedule(self, year: int) -> Any:
        return self.fastf1.get_event_schedule(year)

    def load_session(self, year: int, event: str | int, session_name: str) -> Any:
        session = self.fastf1.get_session(year, event, session_name)
        session.load(
            laps=True,
            telemetry=True,
            weather=True,
            messages=True,
            livedata=None,
        )
        return session

