from __future__ import annotations

from typing import Any


class InvalidSessionResultsError(ValueError):
    """Raised when a final classification is incomplete or internally inconsistent."""


def validate_final_results(session_id: str, results: list[dict[str, Any]]) -> None:
    if len(results) < 2:
        raise InvalidSessionResultsError(
            f"Final classification for {session_id} is missing or has too few drivers."
        )

    positions = [row.get("position") for row in results]
    expected_positions = list(range(1, len(results) + 1))
    invalid_positions = any(not isinstance(position, int) for position in positions)
    if invalid_positions or sorted(positions) != expected_positions:
        raise InvalidSessionResultsError(
            f"Final classification for {session_id} must contain unique positions "
            f"1 through {len(results)}."
        )

    driver_codes = [str(row.get("driver_code") or "").strip() for row in results]
    if any(_is_missing(code) for code in driver_codes) or len(set(driver_codes)) != len(
        driver_codes
    ):
        raise InvalidSessionResultsError(
            f"Final classification for {session_id} has missing or duplicate drivers."
        )

    required_fields = ("classified_position", "status", "points", "grid", "laps")
    for row in results:
        missing = [field for field in required_fields if _is_missing(row.get(field))]
        if missing:
            raise InvalidSessionResultsError(
                f"Final classification for {session_id} is missing {', '.join(missing)} "
                f"for {row.get('driver_code') or 'an unknown driver'}."
            )


def is_final_session(session_id: str, session_name: str | None = None) -> bool:
    code = str(session_name or session_id.rsplit("-", 1)[-1]).strip().upper()
    return code in {"R", "RACE", "S", "SPRINT"}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "nan", "nat", "none", "null"}
    return False
