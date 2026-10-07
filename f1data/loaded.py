"""What FastF1 leaves on a loaded session where F1 sent nothing.

FastF1 casts the text columns of its tables as it builds them. A column with
nothing in it at all comes out empty, but one that is missing for some rows
only comes out as text all the way down, and where there was nothing it holds
the word ``None`` or ``nan``. A driver whom F1's driver list gives a number
and no three-letter code is then called ``None`` on every one of their laps,
and so is the next such driver. With no driver list at all the laps carry an
empty code, though the timing still says whose they are by car number.

So nothing here trusts a text for being a text, and a driver is found by
number. The stand-in sessions in the tests are built by hand and hold a plain
``None`` where a real session holds the word; the rules are checked against
FastF1's own tables as well (tests/test_twelfth_review.py).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# What a cast to text writes where a value was missing.
MISSING_AS_TEXT = frozenset({"None", "nan", "NaN", "NaT", "<NA>"})


def present(value: Any) -> bool:
    """Whether there is a value: not ``None``, not NaN or NaT, and not the text a cast made of one."""
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return not (isinstance(value, str) and value.strip() in MISSING_AS_TEXT)


def text(value: Any) -> str | None:
    """A string with something in it, or ``None``."""
    if not present(value):
        return None
    stripped = str(value).strip()
    return stripped or None


def result_numbers(results: pd.DataFrame) -> list[str | None]:
    """The driver number of each row of a result table, as text."""
    if len(results) == 0:
        return []
    numbers = results["DriverNumber"] if "DriverNumber" in results.columns else results.index
    return [text(number) for number in numbers]


def driver_codes(results: pd.DataFrame, laps: pd.DataFrame) -> dict[str, str]:
    """Driver number to the code that names the driver in everything that is measured or published.

    The timing's code comes first: FastF1 writes it on every lap from F1's
    driver list. Then the result's, which is the driver list's again, or the
    classification's once that has been merged in. A driver neither of them
    names is known by the car number, as text. That is F1's own name for the
    car in every feed, and two drivers without a code stay two drivers.
    """
    codes: dict[str, str] = {}
    lap_numbers: list[str | None] = []
    if len(laps) and "DriverNumber" in laps.columns:
        lap_numbers = [text(number) for number in laps["DriverNumber"]]
        if "Driver" in laps.columns:
            for number, code in zip(lap_numbers, laps["Driver"]):
                named = text(code)
                if number and named:
                    codes.setdefault(number, named.upper())
    listed = result_numbers(results)
    if len(results) and "Abbreviation" in results.columns:
        for number, code in zip(listed, results["Abbreviation"]):
            named = text(code)
            if number and named:
                codes.setdefault(number, named.upper())
    for number in [*lap_numbers, *listed]:
        if number:
            codes.setdefault(number, number)
    return codes
