from typing import Any

import numpy as np

from app.analysis.common import clean_laps, grouped
from app.models.domain import TyreDegradationResult, TyreDegradationRow


def calculate_tyre_degradation(session_id: str, laps: list[dict[str, Any]]) -> TyreDegradationResult:
    rows: list[TyreDegradationRow] = []
    groups = grouped(clean_laps(laps), ("driver_code", "stint", "compound"))
    for (driver_code, stint, compound), group_laps in groups.items():
        samples = [
            (lap.get("tyre_age"), lap.get("lap_time_ms"))
            for lap in group_laps
            if lap.get("tyre_age") is not None and lap.get("lap_time_ms") is not None
        ]
        caveats: list[str] = []
        if len(samples) < 3:
            rows.append(
                TyreDegradationRow(
                    driver_code=str(driver_code),
                    compound=str(compound),
                    stint=int(stint or 0),
                    degradation_ms_per_lap=None,
                    r_squared=None,
                    sample_count=len(samples),
                    stint_length=len(group_laps),
                    caveats=["At least three clean laps are required for a degradation fit."],
                )
            )
            continue

        x = np.array([sample[0] for sample in samples], dtype=float)
        y = np.array([sample[1] for sample in samples], dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        fitted = slope * x + intercept
        residual = float(np.sum((y - fitted) ** 2))
        total = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1 - residual / total if total else None
        if r_squared is not None and r_squared < 0.5:
            caveats.append("Low fit quality; treat the slope as directional only.")
        rows.append(
            TyreDegradationRow(
                driver_code=str(driver_code),
                compound=str(compound),
                stint=int(stint or 0),
                degradation_ms_per_lap=round(float(slope), 2),
                r_squared=round(float(r_squared), 3) if r_squared is not None else None,
                sample_count=len(samples),
                stint_length=len(group_laps),
                caveats=caveats,
            )
        )
    return TyreDegradationResult(session_id=session_id, rows=rows)

