"""Intra-team lap-time comparison. Returns plain dictionaries."""

from collections import defaultdict
from statistics import mean
from typing import Any

from .common import clean_laps


def calculate_teammate_comparison(
    session_id: str, laps: list[dict[str, Any]], drivers: list[dict[str, Any]]
) -> dict[str, Any]:
    driver_team = {
        driver["code"]: driver.get("team", {}).get("name", "Unknown")
        for driver in drivers
        if driver.get("code")
    }
    by_team: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for lap in clean_laps(laps):
        team = driver_team.get(lap["driver_code"], "Unknown")
        by_team[team][lap["driver_code"]].append(lap["lap_time_ms"])

    rows = []
    for team, team_drivers in by_team.items():
        if len(team_drivers) < 2:
            continue
        ordered = sorted(
            [
                {
                    "driver_code": driver,
                    "average_lap_ms": round(mean(values), 1),
                    "lap_count": len(values),
                }
                for driver, values in team_drivers.items()
                if values
            ],
            key=lambda row: row["average_lap_ms"],
        )
        if len(ordered) >= 2:
            rows.append(
                {
                    "team": team,
                    "drivers": ordered,
                    "gap_ms": round(ordered[1]["average_lap_ms"] - ordered[0]["average_lap_ms"], 1),
                }
            )
    return {
        "session_id": session_id,
        "rows": rows,
        "caveats": ["Sample data may include one driver per team, so this view can be empty."],
    }

