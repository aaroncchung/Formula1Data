from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

config_stub = ModuleType("app.config")
config_stub.get_settings = lambda: SimpleNamespace(
    fastf1_cache_dir=Path("test-cache"),
    fastf1_load_attempts=3,
    fastf1_retry_base_delay_seconds=0,
    fastf1_optional_load_delay_seconds=0,
)
sys.modules.setdefault("app.config", config_stub)

from app.services.fastf1_service import FastF1LoadError, FastF1Service


class FastF1ServiceTests(unittest.TestCase):
    def test_load_session_retries_until_laps_are_available(self):
        session = FakeSession(required_failures=1)
        service = fake_service(session)

        result = service.load_session(2024, 9, "R")

        self.assertIs(result, session)
        self.assertEqual(session.required_loads, 2)
        self.assertEqual(session.optional_loads, 1)
        self.assertFalse(session.load_calls[0]["telemetry"])
        self.assertTrue(session.load_calls[-1]["telemetry"])

    def test_load_session_raises_clear_error_when_laps_never_load(self):
        session = FakeSession(required_failures=5)
        service = fake_service(session)

        with self.assertRaisesRegex(
            FastF1LoadError,
            "FastF1 could not load required lap data for 2024 event=9 session=R",
        ):
            service.load_session(2024, 9, "R")

        self.assertEqual(session.required_loads, 3)
        self.assertEqual(session.optional_loads, 0)

    def test_optional_load_failure_does_not_fail_required_session(self):
        session = FakeSession(optional_error=RuntimeError("optional unavailable"))
        service = fake_service(session)

        result = service.load_session(2024, 9, "R")

        self.assertIs(result, session)
        self.assertEqual(session.required_loads, 1)
        self.assertEqual(session.optional_loads, 1)


def fake_service(session: "FakeSession") -> FastF1Service:
    service = FastF1Service.__new__(FastF1Service)
    service._fastf1 = FakeFastF1(session)
    service._sleep = lambda _seconds: None
    service.settings = SimpleNamespace(
        fastf1_cache_dir=Path("test-cache"),
        fastf1_load_attempts=3,
        fastf1_retry_base_delay_seconds=0,
        fastf1_optional_load_delay_seconds=0,
    )
    return service


class FakeFastF1:
    def __init__(self, session: "FakeSession") -> None:
        self.session = session

    def get_session(self, year: int, event: str | int, session_name: str) -> "FakeSession":
        return self.session


class FakeSession:
    def __init__(
        self,
        required_failures: int = 0,
        optional_error: Exception | None = None,
    ) -> None:
        self.required_failures = required_failures
        self.optional_error = optional_error
        self.required_loads = 0
        self.optional_loads = 0
        self.load_calls: list[dict[str, bool]] = []
        self._laps_loaded = False

    def load(
        self,
        laps: bool,
        telemetry: bool,
        weather: bool,
        messages: bool,
        livedata: object | None,
    ) -> None:
        self.load_calls.append(
            {
                "laps": laps,
                "telemetry": telemetry,
                "weather": weather,
                "messages": messages,
            }
        )
        if laps:
            self.required_loads += 1
            self._laps_loaded = self.required_loads > self.required_failures
            return
        self.optional_loads += 1
        if self.optional_error:
            raise self.optional_error

    @property
    def laps(self) -> "FakeFrame":
        if not self._laps_loaded:
            raise RuntimeError("laps unavailable")
        return FakeFrame(empty=False)


class FakeFrame:
    def __init__(self, empty: bool) -> None:
        self.empty = empty


if __name__ == "__main__":
    unittest.main()
