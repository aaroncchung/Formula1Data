from typing import Any


def lap_time_series(
    laps: list[dict[str, Any]], drivers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Pivot laps into one chart series per driver, ordered by driver code.

    Returns plain dictionaries shaped like ``ChartSeries``; the API route wraps
    them in the model, the pipeline serialises them directly.
    """
    by_driver: dict[str, dict[str, Any]] = {}
    # `if driver.get("code")` matters: a driver record without a code would
    # otherwise raise KeyError here rather than simply having no colour.
    driver_colors = {
        driver["code"]: driver.get("team", {}).get("color")
        for driver in drivers
        if driver.get("code")
    }
    for lap in laps:
        if lap.get("lap_time_ms") is None:
            continue
        row = by_driver.setdefault(
            lap["driver_code"],
            {"x": [], "y": [], "color": driver_colors.get(lap["driver_code"])},
        )
        row["x"].append(lap["lap_number"])
        row["y"].append(lap["lap_time_ms"])
    return [
        {
            "name": driver,
            "x": row["x"],
            "y": row["y"],
            "color": row["color"],
            "metadata": {},
        }
        for driver, row in sorted(by_driver.items())
    ]
