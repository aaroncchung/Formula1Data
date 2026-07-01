from typing import Any

from app.models.domain import TelemetryComparison, TelemetryDriverMeta


def telemetry_lap(
    telemetry: list[dict[str, Any]], driver: str, lap_number: int
) -> list[dict[str, Any]]:
    driver = driver.upper()
    rows = [
        row
        for row in telemetry
        if row.get("driver_code") == driver and int(row.get("lap_number", -1)) == lap_number
    ]
    return sorted(rows, key=lambda row: row.get("distance_m", 0))


def compare_telemetry(
    session_id: str,
    telemetry: list[dict[str, Any]],
    laps: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    driver_a: str,
    lap_a: int,
    driver_b: str,
    lap_b: int,
) -> TelemetryComparison | None:
    samples_a = telemetry_lap(telemetry, driver_a, lap_a)
    samples_b = telemetry_lap(telemetry, driver_b, lap_b)
    if not samples_a or not samples_b:
        return None

    step = max(1, len(samples_a) // 300)
    aligned_a = samples_a[::step]
    aligned_b = [_nearest_by_distance(samples_b, sample["distance_m"]) for sample in aligned_a]
    distance = [float(sample.get("distance_m", 0)) for sample in aligned_a]

    def values(rows: list[dict[str, Any]], field: str) -> list[Any]:
        return [row.get(field) for row in rows]

    speed_a = values(aligned_a, "speed_kph")
    speed_b = values(aligned_b, "speed_kph")
    delta_speed = [
        round(float(a) - float(b), 2) if a is not None and b is not None else None
        for a, b in zip(speed_a, speed_b, strict=True)
    ]

    return TelemetryComparison(
        session_id=session_id,
        driver_a=_driver_meta(driver_a, lap_a, laps, drivers),
        driver_b=_driver_meta(driver_b, lap_b, laps, drivers),
        distance_m=distance,
        speed_a=speed_a,
        speed_b=speed_b,
        throttle_a=values(aligned_a, "throttle_pct"),
        throttle_b=values(aligned_b, "throttle_pct"),
        brake_a=[_bool_to_int(value) for value in values(aligned_a, "brake")],
        brake_b=[_bool_to_int(value) for value in values(aligned_b, "brake")],
        rpm_a=values(aligned_a, "rpm"),
        rpm_b=values(aligned_b, "rpm"),
        gear_a=values(aligned_a, "gear"),
        gear_b=values(aligned_b, "gear"),
        drs_a=values(aligned_a, "drs"),
        drs_b=values(aligned_b, "drs"),
        delta_speed_kph=delta_speed,
        caveats=["Telemetry is aligned by nearest distance sample and downsampled for UI performance."],
    )


def _nearest_by_distance(rows: list[dict[str, Any]], distance: float) -> dict[str, Any]:
    return min(rows, key=lambda row: abs(float(row.get("distance_m", 0)) - float(distance)))


def _driver_meta(
    driver_code: str, lap_number: int, laps: list[dict[str, Any]], drivers: list[dict[str, Any]]
) -> TelemetryDriverMeta:
    lap = next(
        (
            row
            for row in laps
            if row.get("driver_code") == driver_code.upper()
            and int(row.get("lap_number", -1)) == lap_number
        ),
        {},
    )
    driver = next((row for row in drivers if row.get("code") == driver_code.upper()), {})
    team = driver.get("team", {}).get("name") if isinstance(driver.get("team"), dict) else None
    return TelemetryDriverMeta(
        driver_code=driver_code.upper(),
        team=team,
        lap_time_ms=lap.get("lap_time_ms"),
        compound=lap.get("compound"),
        session=lap.get("session_id"),
        lap_number=lap_number,
    )


def _bool_to_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0

