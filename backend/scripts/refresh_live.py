import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.openf1_service import OpenF1Service  # noqa: E402


async def main() -> None:
    service = OpenF1Service()
    timing = await service.live_timing()
    race_control = await service.race_control()
    weather = await service.weather()
    print(
        {
            "timing_records": len(timing.get("data", [])) if isinstance(timing.get("data"), list) else 0,
            "race_control_records": len(race_control.get("data", []))
            if isinstance(race_control.get("data"), list)
            else 0,
            "weather_records": len(weather.get("data", [])) if isinstance(weather.get("data"), list) else 0,
        }
    )


if __name__ == "__main__":
    asyncio.run(main())

