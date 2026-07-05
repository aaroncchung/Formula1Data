from pathlib import Path
import sys
import time
from typing import Any

from app.config import get_settings


class FastF1LoadError(RuntimeError):
    """Raised when FastF1 cannot load the required timing data for a session."""


class FastF1Service:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._fastf1: Any | None = None
        self._sleep = time.sleep

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
        label = f"{year} event={event} session={session_name}"
        attempts = max(1, int(self.settings.fastf1_load_attempts))
        last_error: BaseException | None = None

        for attempt in range(1, attempts + 1):
            try:
                self._load_required_session_data(session)
                self._ensure_laps_loaded(session, label)
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                delay = self._retry_delay(attempt)
                print(
                    "FastF1 required data load failed "
                    f"for {label} on attempt {attempt}/{attempts}: {exc}. "
                    f"Retrying in {delay:g}s.",
                    file=sys.stderr,
                )
                if delay > 0:
                    self._sleep(delay)
                continue

            self._load_optional_session_data(session, label)
            return session

        cache_dir = Path(self.settings.fastf1_cache_dir)
        raise FastF1LoadError(
            "FastF1 could not load required lap data "
            f"for {label} after {attempts} attempt(s). "
            f"Cache directory: {cache_dir}. "
            "Try rerunning after warming/restoring the FastF1 cache, or from a runner "
            "whose network can reach the FastF1 timing data endpoints."
        ) from last_error

    def _load_required_session_data(self, session: Any) -> None:
        session.load(
            laps=True,
            telemetry=False,
            weather=False,
            messages=False,
            livedata=None,
        )

    def _load_optional_session_data(self, session: Any, label: str) -> None:
        delay = max(0.0, float(self.settings.fastf1_optional_load_delay_seconds))
        if delay > 0:
            self._sleep(delay)
        try:
            session.load(
                laps=False,
                telemetry=True,
                weather=True,
                messages=True,
                livedata=None,
            )
        except Exception as exc:
            print(
                f"FastF1 optional telemetry/weather/message data failed for {label}: {exc}. "
                "Continuing with required lap data only.",
                file=sys.stderr,
            )

    def _ensure_laps_loaded(self, session: Any, label: str) -> None:
        try:
            laps = getattr(session, "laps")
        except Exception as exc:
            raise FastF1LoadError(
                f"FastF1 session.load returned without populated laps for {label}."
            ) from exc
        if laps is None or bool(getattr(laps, "empty", False)):
            raise FastF1LoadError(f"FastF1 returned empty lap data for {label}.")

    def _retry_delay(self, failed_attempt: int) -> float:
        base_delay = max(0.0, float(self.settings.fastf1_retry_base_delay_seconds))
        return base_delay * (2 ** (failed_attempt - 1))

