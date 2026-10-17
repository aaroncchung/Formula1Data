"""The cases the nineteenth review of this code found (GPT-6.1 Sol, 2026-10-07, at 04d0c66).

One of the first rank, and nowhere near the spool the five rounds before had
been about. `fetch` archives whatever session it is asked for, the build
built every session in the archive, and what it builds is a race's files: a
practice session fetched by hand was published with an order by laps
completed and gaps at a flag it never had. Only a race or a sprint is built
now, published, or shown.

The rest were of the round before's fixes. A lock file was still removed
after the lock on it was released, which left a moment for another run to
take it and have its name removed from under it. And reading the records of
the version before, which that round had been asked for, turned out to be
the wrong answer: its directories were kept by other rules, and two of them
could be destroyed by reading them as this version's. They are not read.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from datetime import timedelta

import pytest

from backend.app.analysis.advanced import calculate_car_performance
from f1data import build as build_module
from f1data import cli as cli_module
from f1data import layout, spool
from f1data.archive import list_snapshots, write_snapshot
from f1data.build import Builder
from f1data.publish import (
    Inputs,
    NotPublished,
    PointerError,
    derive_index,
    publish_session,
    read_pointer,
    read_published,
)
from f1data.store import MemoryStore
from tests.building import FIRST_FETCH, Archive
from tests.spooling import left_served, left_started, left_whole
from tests.test_archive import fetched_session
from tests.test_eighteenth_review import lock_of
from tests.test_fifteenth_review import EIGHTH, SIXTH, Job, job, three_races  # noqa: F401
from tests.test_fifth_review import EVERYONE, WINDOW_CLOSED
from tests.test_publish import AUSTRIA, NOW, Publisher, schedule_2026, snapshot
from tests.test_sixteenth_review import STORE

PRACTICE = 9902


def practice(found):
    """The same fetch as a second practice session's: what `fetch --session FP2` archives."""
    return replace(
        found, identity=replace(found.identity, session_key=PRACTICE, session_type="FP2", session_name="Practice 2")
    )


# --- R19-6: only a race or a sprint is built, published or shown ----------------------


def test_a_practice_session_in_the_archive_is_not_built(tmp_path, monkeypatch):
    """`fetch` takes any session, and `build` built every session the archive
    held. What it builds is a race's: the result of a practice session was
    the order by laps completed, with each driver's laps down and gap at the
    flag, and the site showed it as that."""
    world = Archive(monkeypatch, EVERYONE)
    write_snapshot(world.store, practice(fetched_session(tmp_path)), now=FIRST_FETCH)
    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)

    declined = builder.gather(PRACTICE)
    outcome = publish_session(world.store, PRACTICE, builder.gather, builder.build)

    assert isinstance(declined, NotPublished) and "only races and sprints are published" in declined.reason
    assert (outcome.action, outcome.generation) == ("out_of_scope", None) and "Practice 2" in outcome.reason
    assert read_pointer(world.store, PRACTICE)[0] is None and world.built == []
    assert list(world.store.list(f"v{layout.FORMAT_VERSION}/")) == []
    # Nothing was looked up for it either.
    assert world.classification_requests == []


def test_nothing_but_a_race_or_a_sprint_is_given_a_pointer_whatever_hands_it_over():
    store = MemoryStore()
    stray = Publisher(store, snap=replace(snapshot(), identity=replace(snapshot().identity, session_type="Q", session_name="Qualifying")))

    with pytest.raises(PointerError, match="is a Qualifying session, and only races and sprints are published"):
        stray.publish()

    assert stray.builds == 0 and list(store.list("")) == []
    assert Publisher(store, snap=replace(snapshot(), identity=replace(snapshot().identity, session_type="S", session_name="Sprint"))).publish().action == "published"


def test_a_pointer_to_anything_else_is_not_shown_in_the_index():
    store = MemoryStore()
    Publisher(store).publish()
    (race,) = read_published(store)
    stray = replace(race, identity=replace(race.identity, session_type="FP2", session_name="Practice 2"))

    with_it = derive_index([race, stray], {2026: schedule_2026()})

    assert with_it == derive_index([race], {2026: schedule_2026()})
    assert "Practice 2" not in json.dumps(with_it)


def test_the_fetch_command_says_what_becomes_of_a_session_that_is_not_built(job, monkeypatch):
    real = cli_module.fetch_session
    monkeypatch.setattr(cli_module, "fetch_session", lambda *asked: practice(real(*asked)))

    output, code = job.run("fetch", "--store", "x", "--year", "2026", "--event", str(EIGHTH), "--session", "FP2")

    assert code == 0 and "A Practice 2 session is kept in the archive and nothing is made of it" in output
    assert [found.identity.session_type for found in list_snapshots(job.store)] == ["FP2"]
    monkeypatch.setattr(cli_module, "fetch_session", real)
    assert "nothing is made of it" not in job.run("fetch", "--store", "x", "--year", "2026", "--event", str(EIGHTH), "--session", "R")[0]


# --- R19-1: a lock is removed while it is held -----------------------------------------


def test_a_run_that_takes_a_lock_as_it_is_released_does_not_have_it_removed_from_under_it(tmp_path, monkeypatch):
    """A run sweeping an old lock released it and then removed its file. In
    between, the run the lock was made for took it, found its name still
    leading to it, and went on; the name was then removed, the next run made
    a new file of that name, and both held the fetch."""
    directory = spool.new_fetch_path(tmp_path / "spool")
    real_unlock, real_lock = spool._unlock, spool._try_lock
    taken: list[object] = []

    def release_and_let_the_other_run_in(handle):
        real_unlock(handle)
        if not taken:
            # The run this lock was made for, at the moment it comes free.
            taken.append(spool._take(lock_of(directory)))

    monkeypatch.setattr(spool, "_unlock", release_and_let_the_other_run_in)
    with spool.holding(directory) as sweeping:
        assert sweeping
    monkeypatch.setattr(spool, "_unlock", real_unlock)

    try:
        # What that run holds is still what the name leads to: nobody else can take it.
        assert taken[0] is not None and lock_of(directory).is_file()
        with lock_of(directory).open("a+b") as third:
            assert not real_lock(third)
    finally:
        real_unlock(taken[0])
        taken[0].close()


def test_a_lock_is_removed_before_it_is_released_where_an_open_file_can_be(tmp_path, monkeypatch):
    directory = spool.new_fetch_path(tmp_path / "spool")
    there_when_released: list[bool] = []
    real = spool._unlock
    monkeypatch.setattr(
        spool, "_unlock", lambda handle: (there_when_released.append(lock_of(directory).exists()), real(handle))[1]
    )

    with spool.holding(directory) as mine:
        assert mine

    # Windows does not remove a file that is open, and for the same reason
    # cannot remove one from under a run that has opened it since.
    assert there_when_released == [os.name == "nt"] and not lock_of(directory).exists()


def test_where_files_cannot_be_told_apart_no_lock_file_is_removed(tmp_path, monkeypatch):
    """The lock is known for the file of its name by the file system's number
    for it. One that gives every file the same number would call any file
    the right one."""
    monkeypatch.setattr(spool, "_has_an_identity", lambda handle: False)
    directory = spool.new_fetch_path(tmp_path / "spool")

    with spool.holding(directory) as mine:
        assert mine

    assert lock_of(directory).is_file()


# --- R19-2, R19-3: a record that is not this version's is not acted on -----------------


def as_schema_one(directory) -> None:
    for name in (spool.INTENT_NAME, spool.PENDING_NAME):
        record = directory / name
        if record.is_file():
            payload = json.loads(record.read_text(encoding="utf-8"))
            record.write_text(json.dumps({**payload, "schema_version": 1}), encoding="utf-8")


def test_a_directory_kept_by_the_version_befores_rules_is_left_exactly_as_it_is(job):
    """Its records say the same things, so the round before read them. But
    that version locked a file inside the directory, which this one does not
    look at, and for a time marked nothing when F1 had served a session:
    read as this version's, a directory a run of that version was still
    fetching into was removed, and so was a served session it had left to
    be carried on."""
    served_and_unmarked = left_started(job.spool, 2026, EIGHTH, "R", STORE)
    fetched_session(served_and_unmarked.parent / "elsewhere")
    (served_and_unmarked / "cache" / "kept.ff1pkl").write_bytes(b"what F1 served")
    whole = left_whole(job.spool, 2026, SIXTH, "R", STORE, now=FIRST_FETCH + timedelta(hours=1))
    marked = left_served(job.spool, 2026, SIXTH, "R", STORE, now=FIRST_FETCH + timedelta(hours=2))
    for directory in (served_and_unmarked, whole, marked):
        as_schema_one(directory)
        long_ago = time.time() - 30 * 86400
        os.utime(directory, (long_ago, long_ago))

    output, code = job.run()

    assert code == 1 and output.count("is a fetch whose record cannot be read") == 3 and "schema 1" in output
    assert "is removed" not in output and "archived now" not in output and job.read_back == []
    assert (served_and_unmarked / "cache" / "kept.ff1pkl").read_bytes() == b"what F1 served"
    assert (whole / spool.PENDING_NAME).is_file() and (marked / spool.SERVED_NAME).is_file()
    # Nothing is known of them to this version, so their sessions are fetched like any other.
    assert job.fetched == [EIGHTH]


# --- R19-4, R19-5: what the guide says to do with such a directory can be done --------


def test_a_directory_of_the_spool_can_be_kept_in_the_archive_as_the_guide_says(job):
    """The guide gave the name to keep it under as `spool-<its name>`. The
    names of the spool have capitals in them, and the command refuses one."""
    directory = left_served(job.spool, 2026, EIGHTH, "R", "r2:an-account/another-bucket")
    as_the_guide_says = f"spool-{directory.name.lower()}"

    output, code = job.run("archive-directory", "--store", "x", "--path", str(directory), "--name", as_the_guide_says)

    assert code == 0
    kept = [item.key for item in job.store.list(f"{layout.ARCHIVE_PREFIX}legacy/")]
    assert len(kept) == 2 and all(as_the_guide_says in key for key in kept)
    _, refused = job.run("archive-directory", "--store", "x", "--path", str(directory), "--name", f"spool-{directory.name}")
    assert "Use lowercase letters" in str(refused)


# --- R19-7: the car-performance figures say what they leave out ------------------------


def test_the_car_performance_figures_say_that_a_car_standing_still_is_left_out():
    """They are of each sample at a new distance. A car in its pit box sends
    samples at one distance, on the brake, and all but the first were left
    out while the file said every sample with the channel was counted."""
    def sample(at_ms: int, distance: float, speed: float, throttle: float, brake: bool) -> dict:
        return {
            "driver_code": "AAA", "lap_number": 5, "relative_time_ms": at_ms, "distance_m": distance,
            "speed_kph": speed, "throttle_pct": throttle, "brake": brake,
        }

    moving = [sample(0, 0.0, 200.0, 100.0, False), sample(250, 14.0, 200.0, 100.0, False)]
    standing = [sample(500 + 250 * n, 20.0, 0.0, 0.0, True) for n in range(8)]
    away = [sample(2500, 26.0, 90.0, 100.0, False), sample(2750, 33.0, 100.0, 100.0, False)]
    # A clean lap whose telemetry runs its time, which is the only kind profiled
    # (backend/tests/test_pr_review_analysis.py).
    laps = [{"driver_code": "AAA", "lap_number": 5, "lap_time_ms": 2750}]
    drivers = [{"code": "AAA", "team": {"name": "A Team"}}]

    made = calculate_car_performance("a session", laps, moving + standing + away, drivers)

    (row,) = made["drivers"]
    # Five samples: four on the move, and the first of the eight in the box.
    assert (row["braking_pct"], row["full_throttle_pct"]) == (20.0, 80.0)
    assert any("has not moved since the one before" in caveat for caveat in made["caveats"])
