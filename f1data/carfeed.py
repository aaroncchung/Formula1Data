"""What F1's car feed says of the pedals that FastF1 does not hand on.

F1 sends 104, on a scale that ends at 100, for a pedal it has no reading of.
Most often it is both pedals at once, while the feed repeats the speed and
the engine speed it last had. But each channel carries the mark by itself
too: in the 2026 Australian GP 90,090 samples have it in both, 13 in the
throttle alone and 1,584 in the brake alone, and in the 2026 Hungarian GP the
brake has no reading for most of the race.

FastF1 keeps the throttle as it was sent, so that mark can be seen in a
loaded session. It makes the brake a yes or a no, and anything over nought is
a yes: a brake of 104 arrives as the brake on, with nothing to tell it from
braking. The archive keeps F1's raw responses beside FastF1's cache of them
(``http-cache.sqlite.gz`` in a snapshot), and this reads the marks from there.
"""

from __future__ import annotations

import base64
import binascii
import json
import zlib
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# The name F1 files the feed under, which is how its response is found.
CAR_FEED = "CarData.z.jsonStream"

# What F1 sends for a pedal it has no reading of is 104. Anything over the
# scale is taken for it.
NO_PEDAL_READING = 100.0

# A car has eight forward gears, and 0 is neutral. F1's feed now and then
# sends something else: car 1 in the 2026 Dutch GP has 52 samples with a
# "gear" between 9 and 40, standing in the pit lane through the red flag.
# Whatever those are, they are not gears.
HIGHEST_GEAR = 8

# F1's names for the channels of a car's sample. FastF1 leaves a sample out
# when it lacks any of the first five, and so does this.
_RPM, _SPEED, _GEAR, _THROTTLE, _BRAKE = "0", "2", "3", "4", "5"
_NEEDED = (_RPM, _SPEED, _GEAR, _THROTTLE, _BRAKE)

# Each line of an F1 stream starts with the session time, as HH:MM:SS.mmm.
_STREAM_TIMESTAMP_CHARS = 12
# FastF1 rounds a sample's date to the millisecond, after cutting it to the
# microsecond on the way, so its date for a sample can be a millisecond from
# the one F1 sent. Samples are a fifth of a second apart and more.
_SAME_SAMPLE_NS = 2_000_000


@dataclass(frozen=True)
class PedalMarks:
    """Of one car: when F1 sent each of its samples, and which carry the mark for no reading."""

    # Nanoseconds since the epoch, in order, one for each sample.
    instants: np.ndarray
    throttle: np.ndarray
    brake: np.ndarray

    def at(self, dates: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """For each of ``dates``: whether F1 sent a sample then, and whether each pedal of it is marked."""
        if len(self.instants) == 0 or len(dates) == 0:
            nothing = np.zeros(len(dates), dtype=bool)
            return nothing, nothing.copy(), nothing.copy()
        after = np.clip(np.searchsorted(self.instants, dates), 0, len(self.instants) - 1)
        before = np.clip(after - 1, 0, None)
        nearest = np.where(
            np.abs(self.instants[before] - dates) <= np.abs(self.instants[after] - dates), before, after
        )
        found = np.abs(self.instants[nearest] - dates) <= _SAME_SAMPLE_NS
        return found, found & self.throttle[nearest], found & self.brake[nearest]


def parse_pedal_marks(body: bytes) -> dict[str, PedalMarks]:
    """Each car's samples in F1's car feed, by car number, with the pedals F1 marks as unread.

    ``body`` is the feed as F1 serves it: a line for each message, the
    session time and then the message, compressed and in base 64. A line that
    cannot be read is passed over, as FastF1 passes it over.
    """
    sent_at: list[str] = []
    entries_of: dict[str, list[int]] = {}
    throttle_of: dict[str, list[bool]] = {}
    brake_of: dict[str, list[bool]] = {}
    for line in body.decode("utf-8-sig", errors="replace").split("\r\n"):
        message = _message(line)
        if message is None:
            continue
        for entry in message.get("Entries") or []:
            moment, cars = _said(entry)
            if moment is None:
                continue
            index = len(sent_at)
            sent_at.append(moment)
            for number, channels in cars:
                entries_of.setdefault(number, []).append(index)
                throttle_of.setdefault(number, []).append(_is_the_mark(channels[_THROTTLE]))
                brake_of.setdefault(number, []).append(_is_the_mark(channels[_BRAKE]))
    if not sent_at:
        return {}
    parsed = pd.to_datetime(pd.Series(sent_at, dtype="object"), utc=True, format="ISO8601", errors="coerce")
    instants = parsed.dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
    marks: dict[str, PedalMarks] = {}
    for number, indexes in entries_of.items():
        moments = instants[np.array(indexes, dtype=np.int64)]
        dated = ~np.isnat(moments)
        moments = moments.astype("int64")[dated]
        order = np.argsort(moments, kind="stable")
        marks[number] = PedalMarks(
            instants=moments[order],
            throttle=np.array(throttle_of[number], dtype=bool)[dated][order],
            brake=np.array(brake_of[number], dtype=bool)[dated][order],
        )
    return marks


def _message(line: str) -> dict[str, Any] | None:
    payload = line[_STREAM_TIMESTAMP_CHARS:].strip().strip('"')
    if not payload:
        return None
    try:
        message = json.loads(zlib.decompress(base64.b64decode(payload), -zlib.MAX_WBITS))
    except (binascii.Error, zlib.error, ValueError):
        return None
    return message if isinstance(message, dict) else None


def _said(entry: Any) -> tuple[str | None, list[tuple[str, dict[str, Any]]]]:
    """When an entry was sent, and the channels of each car in it that has them all."""
    if not isinstance(entry, dict) or not isinstance(entry.get("Utc"), str) or not isinstance(entry.get("Cars"), dict):
        return None, []
    cars = []
    for number, car in entry["Cars"].items():
        channels = car.get("Channels") if isinstance(car, dict) else None
        if isinstance(channels, dict) and all(name in channels for name in _NEEDED):
            cars.append((str(number), channels))
    return entry["Utc"], cars


def _is_the_mark(value: Any) -> bool:
    try:
        return float(value) > NO_PEDAL_READING
    except (TypeError, ValueError):
        return False
