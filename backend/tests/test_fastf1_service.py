from __future__ import annotations

import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace

try:
    import pandas as pd
except ImportError:
    pd = None


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

        result = service.load_session(2024, 9, "FP1")

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
            "FastF1 could not load required lap data for 2024 event=9 session=FP1",
        ):
            service.load_session(2024, 9, "FP1")

        self.assertEqual(session.required_loads, 3)
        self.assertEqual(session.optional_loads, 0)

    def test_optional_load_failure_does_not_fail_required_session(self):
        session = FakeSession(optional_error=RuntimeError("optional unavailable"))
        service = fake_service(session)

        result = service.load_session(2024, 9, "FP1")

        self.assertIs(result, session)
        self.assertEqual(session.required_loads, 1)
        self.assertEqual(session.optional_loads, 1)

    def test_race_load_requires_fresh_authoritative_results(self):
        session = FakeSession()
        service = fake_service(session)

        with self.assertRaisesRegex(
            FastF1LoadError, "Authoritative final classification is unavailable"
        ):
            service.load_session(2024, 9, "R")

    @unittest.skipIf(pd is None, "pandas is required for result refresh tests")
    def test_authoritative_results_replace_cached_classification(self):
        session = SimpleNamespace(
            results=pd.DataFrame(
                [
                    {"DriverNumber": "12", "Abbreviation": "ANT", "Position": 1.0},
                    {"DriverNumber": "1", "Abbreviation": "VER", "Position": 2.0},
                    {"DriverNumber": "4", "Abbreviation": "NOR", "Position": 3.0},
                ]
            )
        )
        official = pd.DataFrame(
            [
                {"number": 12, "driverCode": "ANT", "position": 1, "positionText": "1"},
                {"number": 4, "driverCode": "NOR", "position": 2, "positionText": "2"},
                {"number": 1, "driverCode": "VER", "position": 3, "positionText": "3"},
            ]
        )

        FastF1Service._merge_authoritative_results(session, official)

        self.assertEqual(session._results["Abbreviation"].tolist(), ["ANT", "NOR", "VER"])
        self.assertEqual(session._results["Position"].tolist(), [1, 2, 3])


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
    Cache = SimpleNamespace(disabled=lambda: nullcontext())
    ergast = SimpleNamespace(
        Ergast=lambda **_kwargs: SimpleNamespace(
            get_race_results=lambda **_query: SimpleNamespace(content=[]),
            get_sprint_results=lambda **_query: SimpleNamespace(content=[]),
        )
    )

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
