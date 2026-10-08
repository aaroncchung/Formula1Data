"""Where everything lives in the bucket, and the two version numbers.

    archive/sessions/<session_key>/<snapshot_id>/   source archive, never served
    v<F>/pointers/<session_key>.json                one per published session
    v<F>/generations/<session_key>/<generation>/    immutable artifacts
    v<F>/index.json                                 derived from the pointers and the schedule
    v<F>/standings/<year>.json

Pointers sit under one prefix so that "which sessions are published" is one
list call (docs/architecture-review-findings.md, section 6, rule 3). The format
version is part of the path so that a frontend built for one format never reads
another (rule 7).
"""

from __future__ import annotations

import re

# The artifact format: file names, shapes and units. A change here is published
# under a new prefix before the frontend that reads it is deployed.
#
#   2  one model per artifact (f1data/models.py): columnar telemetry bundled
#      per driver, whole milliseconds, null for a missing value, floats
#      rounded as they are written, nothing taken from the calendar
FORMAT_VERSION = 2

# Everything that changes what a build produces without changing the format: an
# analysis fix, a coverage bar. A pointer written by an older pipeline version
# is rebuilt; one written by a newer version is never replaced (rule 2).
#
# A coverage bar counts: a pointer records whether its session met the bars,
# so a session judged complete under an old bar has to be judged again.
# tests/test_layout.py fails when a bar changes and this number does not.
#
#   2  the analysis method fixes of AR-08: pit loss, pace change across a
#      stop, track dominance, tyre degradation fits, team-mate comparison
#   3  coverage: no tolerance on timing laps, the tyre bar without tyre age,
#      bars for the pit-stop feed and the corner positions
#   4  a driver that today's classification leaves out carries no result
#      from the archive into a build; a corner count that is absent no
#      longer passes; the pointer records the calendar entry it was built
#      under, and a session is rebuilt when that changes
#   5  a build is made from the calendar row that was gathered, and reads
#      nothing over the network: the result and the first-lap times FastF1
#      used to fetch from Jolpica while loading are fetched beforehand and
#      are in the fingerprint; a record that disagrees with its feeds is
#      corrected before anything is decided from it
#   6  format 2: analyses read full-resolution telemetry, lap times are
#      rounded and not cut off, corners are the circuit's own where archived,
#      and nothing in a build comes from the calendar
#   7  rows FastF1 adds for a car missing from a feed are not samples, in
#      coverage or in telemetry, and a lap has telemetry only when its car
#      data carries it from end to end; stints are consecutive runs that
#      never overlap; the replay carries a car's positions without its car
#      data; a pit stop F1 reports with no lap is placed by when it was
#      reported; laps down only for a driver who took the flag; a wait in
#      the pit lane through a red flag is marked and left out of the
#      pit-lane figures
#   8  a driver is found by car number and never named by the word FastF1
#      writes for a missing code; a lap's car data is cut with padding from
#      nearby only; the replay's lap count is the timing's; a stop in F1's
#      pit-stop feed is followed by driver and place, and one with no lap is
#      placed only where the timing singles a stop out; a weather reading F1
#      did not send is null where the feed is archived to say so; the
#      telemetry index carries each lap's flags
#   9  a stop F1's pit-stop feed sends twice under two places is one stop,
#      in the count of stops the feed vouches for as in pit-stops.json; the
#      zero F1's weather sends for a sensor with no reading is no reading
#  10  a lap's distance never goes backwards
#  11  the car-performance figures say that they leave out the samples at
#      which a car stands still, which they always did
#  12  a car that goes through the pit lane and keeps its tyres is still on
#      the stint it was on; an entry to the pit lane says whether the tyres
#      were changed; the pit-lane figures are of the stops F1's pit-stop feed
#      reports, and pit loss and the pace change across a stop leave out an
#      entry the car came out of on the tyres it went in on
#  13  a wait in the pit lane through a red flag is neither a stop nor a
#      passage in the strategy analysis, as on the site: it is nobody's first
#      stop, and is left out of pit loss as a wait
#  14  words only: a stint with clean laps and no tyre ages is said to be
#      short of ages, and the pace change across a stop is "after the stop",
#      not "on the new tyres"
#  15  words only: where the laps either side of a stop are looked for, and
#      why none was found when the search stopped at the next stop; and that
#      the team-mate gap drops at least one lap each way
#  16  words only: a session with no pit-stop feed is said to be short of
#      stationary times for its entries to the pit lane, which are not all
#      stops
#  17  a sample F1's car feed marks as having no pedal reading (it sends 104
#      for the throttle and the brake) has no throttle and no brake, in a
#      published lap and in what the analyses read: it was published as full
#      throttle with the brake on
#  18  each pedal's mark for no reading is taken by itself, the brake's from
#      F1's raw car feed, which a build now reads out of the raw responses
#      kept with a snapshot: FastF1 hands a brake of 104 on as the brake on
#  19  a "gear" over 8 from F1's feed is no gear; a corner whose approach has
#      no brake reading says so, where it was a corner the driver "did not
#      brake for"
#  20  a braking's slowest point is looked for before the next braking
#      begins, so one corner's braking is not given to the next; a corner
#      row says what is seen of its braking, in four cases and not two
#  21  a corner's braking is looked for in the corner's own stretch of the
#      lap, so a braking through two corners is given for both, and two
#      brakings with the car driven on between them are two; a corner row
#      says where its own lap has the corner
#  22  a lap's corners are placed together, where its line passes them and
#      its own distance puts them, and one a whole lap is not seen to pass
#      has no figures; the brake going on again is the same braking only
#      if the car gathered no speed anywhere between
#  23  a corner is where a lap's line passes it, between two samples as
#      well as at one; a braking is a corner's when the car is still
#      slowing from it in the corner's stretch, which does not turn on
#      which side of a line one sample falls
PIPELINE_VERSION = 23

ARCHIVE_PREFIX = "archive/"
# Notes of fetches that failed, by calendar entry. Not part of the archive:
# they order the next run's fetches and nothing else reads them.
ATTEMPTS_PREFIX = f"{ARCHIVE_PREFIX}attempts/"
# When the whole job last finished on the machine that fetches. Not part of
# the archive either: it is how a job that has stopped running is noticed.
RUNS_PREFIX = f"{ARCHIVE_PREFIX}runs/"
LAST_RUN_KEY = f"{RUNS_PREFIX}last.json"
SNAPSHOT_MARKER = "snapshot.json"
# Beside a snapshot whose record a build found to disagree with its feeds.
# There is one such object for each version of the measurement, and code
# reads and writes only its own version's: figures it cannot read are then
# never something it has to believe, or to stand aside for. Version 2's has
# the name that was in use when there was only one.
REMEASUREMENT_NAME = "remeasured.json"
_REMEASUREMENT_KEY = re.compile(r"/remeasured(-m[0-9]+)?\.json$")
MANIFEST_NAME = "manifest.json"

_GENERATION_ID = re.compile(r"^[a-f0-9]{64}$")
_SNAPSHOT_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")


def attempt_key(year: int, session_type: str, start_time_utc: str) -> str:
    """Where a failed fetch of a calendar entry is noted.

    By what the calendar says of the session, since a session that has never
    been fetched has no session key yet.
    """
    start = "".join(character for character in start_time_utc if character.isalnum())
    if not start or not session_type.isalnum():
        raise ValueError(f"Not a calendar entry: {session_type!r} at {start_time_utc!r}")
    return f"{ATTEMPTS_PREFIX}{int(year)}/{start}-{session_type.upper()}.json"


def snapshot_from_marker_key(key: str) -> tuple[int, str] | None:
    """The session key and snapshot id a marker's key places it under, or ``None``
    for a key that is not where a snapshot's marker goes."""
    prefix = f"{ARCHIVE_PREFIX}sessions/"
    parts = key[len(prefix):].split("/") if key.startswith(prefix) else []
    if len(parts) != 3 or parts[2] != SNAPSHOT_MARKER or not parts[0].isdigit() or not is_snapshot_id(parts[1]):
        return None
    return int(parts[0]), parts[1]


def remeasurement_name(measurement_version: int) -> str:
    """The name of the correction of a snapshot's record that one version of the measurement keeps."""
    if isinstance(measurement_version, bool) or not isinstance(measurement_version, int) or measurement_version < 1:
        raise ValueError(f"Not a measurement version: {measurement_version!r}")
    return REMEASUREMENT_NAME if measurement_version == 2 else f"remeasured-m{measurement_version}.json"


def is_remeasurement_key(key: str) -> bool:
    """Whether a key is a correction of a snapshot's record, of any version of the measurement."""
    return _REMEASUREMENT_KEY.search(key) is not None


def format_prefix(format_version: int = FORMAT_VERSION) -> str:
    return f"v{format_version}/"


def pointers_prefix(format_version: int = FORMAT_VERSION) -> str:
    return f"{format_prefix(format_version)}pointers/"


def pointer_key(session_key: int, format_version: int = FORMAT_VERSION) -> str:
    return f"{pointers_prefix(format_version)}{int(session_key)}.json"


def session_key_from_pointer_key(key: str, format_version: int = FORMAT_VERSION) -> int | None:
    prefix = pointers_prefix(format_version)
    name = key[len(prefix):] if key.startswith(prefix) else ""
    stem = name[: -len(".json")] if name.endswith(".json") else ""
    return int(stem) if stem.isdigit() else None


def generation_prefix(session_key: int, generation: str, format_version: int = FORMAT_VERSION) -> str:
    if not is_generation_id(generation):
        raise ValueError(f"Not a generation id: {generation!r}")
    return f"{format_prefix(format_version)}generations/{int(session_key)}/{generation}/"


def index_key(format_version: int = FORMAT_VERSION) -> str:
    return f"{format_prefix(format_version)}index.json"


def standings_key(year: int, format_version: int = FORMAT_VERSION) -> str:
    return f"{format_prefix(format_version)}standings/{int(year)}.json"


def session_archive_prefix(session_key: int) -> str:
    return f"{ARCHIVE_PREFIX}sessions/{int(session_key)}/"


def snapshot_prefix(session_key: int, snapshot_id: str) -> str:
    if not is_snapshot_id(snapshot_id):
        raise ValueError(f"Not a snapshot id: {snapshot_id!r}")
    return f"{session_archive_prefix(session_key)}{snapshot_id}/"


def is_generation_id(value: object) -> bool:
    return isinstance(value, str) and bool(_GENERATION_ID.match(value))


def is_snapshot_id(value: object) -> bool:
    return isinstance(value, str) and bool(_SNAPSHOT_ID.match(value))
