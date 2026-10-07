"""The cases the sixteenth review of this code found (GPT-6.1 Sol, 2026-10-07, at 63ce4d5).

The round before gave fetched sessions a spool, so that one the archive would
not take was not thrown away. This round was of the spool itself, and of the
instructions for setting the job up. A fetch that was whole and could not be
written down as whole was still thrown away; a fetch that took longer than a
day could be swept away by another run; and the record of the store in
``.env`` was read too late to be found.

What stands of the answer is this. The spool says what a fetch is of before
the fetch starts, and a run holds a lock on it for as long as it is at it. A
session F1 has served is marked as that at once, and from then on is never
removed before it is archived: a later run reads it back from its cache and
writes it down. The first answer went further and carried on, over the
network, a fetch that had been stopped part of the way; the review after
this one showed what that cost (tests/test_seventeenth_review.py), and such
a fetch is now made again from the start.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from f1data import cli as cli_module
from f1data import fetch as fetch_module
from f1data import layout, spool
from f1data.archive import (
    INTERRUPTED,
    ArchiveError,
    dump_json,
    failed_fetches,
    failing_fetches,
    list_snapshots,
    note_failed_fetch,
    note_fetch_started,
    note_fetch_succeeded,
    write_snapshot,
)
from f1data.cli import main
from f1data.due import FetchPlan, least_recently_failed_first
from f1data.extras import WEATHER_SERIES
from f1data.policy import FETCH_STAGE_BUDGET
from f1data.store import MemoryStore
from tests.building import FIRST_FETCH
from tests.race import extras, make_race
from tests.spooling import a_fetch_in_hand, left_served, left_started, left_whole
from tests.test_extras import ARCHIVE_PATH
from tests.test_fifteenth_review import EIGHTH, SEVENTH, SIXTH, Job, job, three_races  # noqa: F401
from tests.test_publish import AUSTRIA, snapshot
from tests.test_seventh_review import AUSTRIA_ENTRY, CALENDAR

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731
STORE = cli_module._store_name("x")
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def failing_once(function, error):
    """``function``, but raising ``error`` the first time it is called."""
    calls = []

    def wrapped(*arguments, **keywords):
        calls.append(arguments)
        if len(calls) == 1:
            raise error
        return function(*arguments, **keywords)

    return wrapped


def always(error):
    def failing(*arguments, **keywords):
        raise error

    return failing


# --- R16-1: once F1 has served a session, nothing that goes wrong removes it -------


def served_and_not_written_down(job, monkeypatch) -> spool.Unfinished:
    """A run in which F1 serves the session and the record of it cannot be written."""
    monkeypatch.setattr(cli_module, "keep", always(OSError(28, "No space left on device")))
    output, code = job.run()
    (left,) = spool.unfinished(job.spool)
    assert code == 1 and left.served and "FETCHED, NOT ARCHIVED: OSError" in output
    return left


def test_a_fetch_that_could_not_be_written_down_is_read_back_from_what_it_left(job, monkeypatch):
    """F1 serves the session, and the disk is full when the record that makes
    the fetch whole is written. One handler caught that with every failure of
    the fetch itself and removed the directory: the session F1 had just
    served was gone, and was asked for again."""
    monkeypatch.setattr(cli_module, "keep", failing_once(spool.keep, OSError(28, "No space left on device")))

    output, code = job.run()

    assert code == 1 and "FETCHED, NOT ARCHIVED: OSError" in output and "What F1 sent is in" in output
    assert list_snapshots(job.store) == [] and spool.waiting(job.spool) == []
    (left,) = spool.unfinished(job.spool)
    assert (left.event, left.store, left.start_time_utc) == (EIGHTH, STORE, AUSTRIA_ENTRY.start_time_utc)
    assert left.served and any((left.directory / "cache").rglob("*.ff1pkl"))
    # F1 answered: nothing says the fetch of it failed.
    assert failed_fetches(job.store, NOW()) == {}

    output, code = job.run()

    # Read back, and not asked of F1 again.
    assert (job.fetched, job.read_back, code) == ([], [EIGHTH], 0)
    assert "a fetch that F1 served, written down from its cache and archived." in output
    (archived,) = list_snapshots(job.store)
    # Fetched when the fetch ended, whenever it was written down.
    assert archived.fetched_at == left.served_at.strftime(STAMP)
    assert list(job.spool.iterdir()) == []


def test_a_run_stopped_after_a_fetch_was_written_down_leaves_it_whole(job, monkeypatch):
    """The scheduler stops the task while the snapshot is being uploaded."""
    monkeypatch.setattr(
        cli_module, "write_snapshot", failing_once(write_snapshot, KeyboardInterrupt("the task was stopped"))
    )

    _, code = job.run()

    assert code == "killed" and list_snapshots(job.store) == []
    assert len(spool.waiting(job.spool)) == 1 and spool.unfinished(job.spool) == []

    output, code = job.run()

    assert (job.fetched, code) == ([], 0) and "fetched earlier, archived now." in output
    assert len(list_snapshots(job.store)) == 1


def test_a_fetch_f1_would_not_serve_leaves_nothing_in_the_spool(job):
    job.fails = {EIGHTH}

    output, code = job.run()

    assert code == 1 and "FAILED: FetchError" in output and list(job.spool.iterdir()) == []


def test_a_fetch_is_made_into_an_empty_cache_and_read_back_from_the_one_it_filled(monkeypatch, tmp_path):
    """A snapshot is of one fetch. A cache that holds anything is not
    fetched into; it can be read back, which asks F1 for nothing."""
    loaded = make_race()
    loaded.load = lambda **kwargs: None

    @contextmanager
    def cache(cache_dir):
        yield SimpleNamespace(get_session=lambda year, event, code: loaded)

    monkeypatch.setattr(fetch_module, "fastf1_cache", cache)
    monkeypatch.setattr(fetch_module, "identity_from_fastf1", lambda found: SimpleNamespace(archive_path=ARCHIVE_PATH))
    monkeypatch.setattr(fetch_module, "_versions", lambda module: {})
    monkeypatch.setattr(
        fetch_module, "fetch_extras", lambda module, found, path: {**extras(), WEATHER_SERIES: b"00:00:38.376{}"}
    )
    left = tmp_path / "cache"
    with pytest.raises(fetch_module.FetchError, match="no parsed feeds to read back"):
        fetch_module.read_back(2026, 8, "R", left)
    (left / ARCHIVE_PATH).mkdir(parents=True)
    (left / ARCHIVE_PATH / "session_info.ff1pkl").write_bytes(b"what F1 served")

    with pytest.raises(fetch_module.FetchError, match="needs an empty cache directory"):
        fetch_module.fetch_session(2026, 8, "R", left)
    fetched = fetch_module.read_back(2026, 8, "R", left)

    assert fetched.cache_dir == left and (fetched.attempts, fetched.feed_status, fetched.http.summary()) == (1, {}, {})
    assert (left / ARCHIVE_PATH / "session_info.ff1pkl").read_bytes() == b"what F1 served"


# The first fix of that kept the fetch for one more run and no longer. Read
# again before it went back for review, it lost the same session a run later:
# a disk that is full when a fetch ends is usually still full six hours on.


def test_a_fetch_f1_served_outlasts_a_disk_that_stays_full(job, monkeypatch):
    left = served_and_not_written_down(job, monkeypatch)

    for _ in range(3):
        output, code = job.run()

        assert code == 1 and "a fetch that F1 served could still not be written down: OSError" in output
        # Read back from what it left, and not asked of F1 as a new fetch.
        assert (job.fetched, job.read_back) == ([], [EIGHTH])
        (still,) = spool.unfinished(job.spool)
        # As it was: there is no number of times after which it goes, and
        # when it was fetched does not move.
        assert (still.directory, still.served_at) == (left.directory, left.served_at)
        assert any((left.directory / "cache").rglob("*.ff1pkl"))

    monkeypatch.setattr(cli_module, "keep", spool.keep)
    output, code = job.run()

    assert code == 0 and "a fetch that F1 served, written down from its cache and archived." in output
    (archived,) = list_snapshots(job.store)
    assert archived.fetched_at == left.served_at.strftime(STAMP)
    assert list(job.spool.iterdir()) == []


def test_a_fetch_f1_served_is_not_removed_because_reading_it_back_failed(job, monkeypatch):
    left = served_and_not_written_down(job, monkeypatch)
    monkeypatch.setattr(cli_module, "keep", spool.keep)
    job.cannot_be_read_back = {EIGHTH}

    output, code = job.run()

    assert code == 1 and "could still not be written down: reading it back failed (FetchError" in output
    assert (job.fetched, job.read_back) == ([], [EIGHTH])
    assert any((left.directory / "cache").rglob("*.ff1pkl"))
    # F1 served it: its fetch has not failed.
    assert failed_fetches(job.store, NOW()) == {}

    job.cannot_be_read_back = set()
    _, code = job.run()

    assert code == 0 and len(list_snapshots(job.store)) == 1 and list(job.spool.iterdir()) == []


def test_a_run_killed_while_reading_a_fetch_back_leaves_it_to_be_read_back(job, monkeypatch):
    left = served_and_not_written_down(job, monkeypatch)
    monkeypatch.setattr(cli_module, "keep", spool.keep)
    job.dies_reading_back = EIGHTH

    assert job.run()[1] == "killed"
    assert job.run()[1] == "killed"
    job.dies_reading_back = None
    output, code = job.run()

    assert (job.fetched, job.read_back, code) == ([], [EIGHTH], 0)
    (archived,) = list_snapshots(job.store)
    assert archived.fetched_at == left.served_at.strftime(STAMP)


def test_a_fetch_stopped_before_f1_had_served_the_session_is_made_again_from_the_start(job):
    job.dies_in = EIGHTH
    assert job.run()[1] == "killed"
    (left,) = spool.unfinished(job.spool)
    assert not left.served
    job.dies_in = None

    output, code = job.run()

    assert "a fetch that was stopped before F1 had served the session is removed." in output
    assert (job.fetched, job.read_back, code) == ([EIGHTH], [], 0)
    assert not left.directory.exists() and len(list_snapshots(job.store)) == 1


def test_what_is_in_the_spool_is_seen_through_on_a_disk_with_no_room_for_a_fetch(three_races, monkeypatch):
    """Uploading what is whole is what makes room. Reading a served fetch
    back writes a few kilobytes, and if even that fails it stays as it was."""
    left_whole(three_races.spool, 2026, EIGHTH, "R", STORE)
    left_served(three_races.spool, 2026, EIGHTH, "R", STORE, now=FIRST_FETCH + timedelta(hours=6))
    monkeypatch.setattr(cli_module, "free_bytes", lambda root: 10 * 1024**2)

    output, code = three_races.run()

    assert "fetched earlier, archived now." in output
    assert "a fetch that F1 served, written down from its cache and archived." in output
    assert len(list_snapshots(three_races.store)) == 2 and spool.directories(three_races.spool) == []
    assert three_races.fetched == [] and code == 1
    assert "Stopping: 10 MB free where the spool is" in output and "2 session(s) left." in output


def test_a_fetch_written_down_and_not_archived_is_not_asked_of_f1_again_in_that_run(job, monkeypatch):
    served_and_not_written_down(job, monkeypatch)
    monkeypatch.setattr(cli_module, "keep", spool.keep)
    job.store.refusing = "fastf1-cache.tar.gz"

    output, code = job.run()

    assert code == 1 and "a fetch that F1 served is written down now, and NOT ARCHIVED" in output
    assert (job.fetched, job.read_back) == ([], [EIGHTH])
    assert len(spool.waiting(job.spool)) == 1 and list_snapshots(job.store) == []

    job.store.refusing = None
    output, code = job.run()

    assert (job.fetched, job.read_back, code) == ([], [], 0) and "fetched earlier, archived now." in output


def test_a_run_names_what_it_cannot_read_in_the_spool_and_leaves_it(job):
    """The guide said that a run says when a fetch's record cannot be read.
    Nothing did: the directory was passed over in silence, for ever."""
    whole = left_whole(job.spool, 2026, EIGHTH, "R", STORE)
    (whole / spool.PENDING_NAME).write_text("{ cut off in the mid", encoding="utf-8")
    started = left_started(job.spool, 2026, EIGHTH, "R", STORE)
    # Written by another version of this program, which may mean something else by it.
    intent = json.loads((started / spool.INTENT_NAME).read_text(encoding="utf-8"))
    (started / spool.INTENT_NAME).write_text(json.dumps({**intent, "schema_version": 99}), encoding="utf-8")

    output, code = job.run()

    assert sorted(spool.unreadable(job.spool)) == sorted([whole, started])
    for directory in (whole, started):
        assert f"ATTENTION: {directory} is a fetch whose record cannot be read" in output
    assert (whole / "cache").is_dir() and started.is_dir()
    # Nothing is known of them, so the session is fetched like any the spool does not hold.
    # The run has left something behind that it could not deal with, and says so by failing.
    assert (job.fetched, job.read_back, code) == ([EIGHTH], [], 1)


# --- R16-5: a fetch is alive while something holds it, however long it takes --------


def test_a_fetch_another_run_is_making_is_neither_touched_nor_planned(job):
    """A fetch with no record of being whole was swept away once it was a day
    old, by its directory's date: a fetch that took longer, or a clock that
    jumped, and another run removed the feeds from under it."""
    with a_fetch_in_hand(
        job.spool, 2026, EIGHTH, "R", STORE, start_time_utc=AUSTRIA_ENTRY.start_time_utc
    ) as theirs:
        (theirs / "cache").mkdir()
        long_ago = time.time() - 30 * 86400
        os.utime(theirs, (long_ago, long_ago))

        output, code = job.run()

        assert (job.fetched, job.read_back) == ([], []) and "Nothing to fetch" in output
        assert (theirs / spool.INTENT_NAME).is_file() and (theirs / "cache").is_dir()


def test_only_what_is_not_a_fetch_is_swept_and_not_while_anything_holds_it(job):
    stray = job.spool / "left-by-something-else"
    stray.mkdir(parents=True)
    (stray / "a file").write_text("of something else", encoding="utf-8")
    orphan = job.spool / "20260101T000000Z-00000000.lock"
    orphan.write_bytes(b"")

    # A directory made a moment ago may be one a run has yet to write into,
    # and so may a lock.
    job.run()
    assert stray.is_dir() and orphan.is_file()

    long_ago = time.time() - 2 * 3600
    os.utime(stray, (long_ago, long_ago))
    os.utime(orphan, (long_ago, long_ago))
    with spool.holding(stray):
        output, _ = job.run()
        assert stray.is_dir() and "it was not a fetch" not in output

    output, _ = job.run()

    assert "Removed left-by-something-else from the spool: it was not a fetch." in output
    assert not stray.exists() and not orphan.exists()
    # The fetch the run made is gone with its lock: nothing is left behind.
    assert list(job.spool.iterdir()) == []


def test_a_removal_that_was_stopped_is_finished_and_not_taken_for_a_fetch(job):
    """Removing a directory takes many steps. Stopped after the record that
    said the fetch was whole had gone, what was left looked like a fetch
    that had been served and not written down, with half its feeds."""
    directory = left_served(job.spool, 2026, EIGHTH, "R", STORE)
    (directory / spool.DISCARDED_NAME).touch()

    output, code = job.run()

    # Not read back: it was being removed, so its session is in the archive
    # or was never served. It is fetched as any session the spool does not hold.
    assert (job.fetched, job.read_back, code) == ([EIGHTH], [], 0) and not directory.exists()
    with spool.holding(job.spool / "never-there") as mine:
        assert mine
        spool.discard(job.spool / "never-there")
    with pytest.raises(RuntimeError, match="without its lock being held"):
        spool.discard(job.spool)


def test_a_fetch_made_for_one_store_is_not_seen_through_by_a_run_against_another(job):
    """The spool is one directory on the machine. A run started by hand
    against a directory would have uploaded there what the scheduled run had
    fetched for the bucket, and removed it."""
    theirs = "r2:an-account/another-bucket"
    whole = left_whole(job.spool, 2026, SEVENTH, "R", theirs)
    served = left_served(job.spool, 2026, SIXTH, "R", theirs)
    started = left_started(job.spool, 2026, SIXTH, "R", theirs)

    output, _ = job.run()

    assert "3 fetch(es) in the spool are for another store, and are left for it." in output
    assert job.read_back == [] and (whole / spool.PENDING_NAME).is_file()
    assert (served / spool.SERVED_NAME).is_file() and (started / spool.INTENT_NAME).is_file()
    assert [item.store for item in spool.waiting(job.spool)] == [theirs]
    assert spool.waiting(job.spool, STORE) == [] and spool.unfinished(job.spool, STORE) == []


# --- R16-2: the store named in .env is the store ------------------------------------


def test_a_store_named_only_in_the_environment_file_is_found(tmp_path, monkeypatch, capsys):
    """`--store` defaults to F1DATA_STORE, and a default is read when the
    arguments are described. The file was read after that: with the store
    named there and nowhere else, as the instructions say to, every command
    answered "Say which store to use"."""
    monkeypatch.setenv("F1DATA_STORE", "set, so that removing it is undone after the test")
    monkeypatch.delenv("F1DATA_STORE")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"F1DATA_STORE={(tmp_path / 'store').as_posix()}\n", encoding="utf-8")

    with pytest.raises(SystemExit) as finished:
        main(["last-run"])

    assert "No run of the whole job has been written down in this store." in capsys.readouterr().out
    assert finished.value.code == 1


# --- R16-3: the build has its turn in every run -------------------------------------


def test_the_fetch_stage_starts_no_new_fetch_once_its_time_is_up(three_races, monkeypatch):
    """Sessions that fail slowly could take the whole of the two hours the
    scheduler allows a run, on every run, before the build was reached:
    nothing already in the archive was published."""
    output, code = three_races.run("fetch-due", "--store", "x", "--season", "2026", "--budget-minutes", "0")

    assert three_races.fetched == [] and code == 0
    assert "Stopping: the fetch stage has had its 0 minutes. 3 session(s) left for the next run." in output

    seen = []
    monkeypatch.setattr(cli_module, "_fetch_due", lambda args: (seen.append(args.budget_minutes) or 0, 0))
    monkeypatch.setattr(cli_module, "run_build", lambda args: 0)
    three_races.run("run", "--store", "x")
    assert seen == [FETCH_STAGE_BUDGET.total_seconds() / 60] and 0 < seen[0] <= 90


def test_no_fetch_is_started_on_a_disk_with_no_room_for_it(three_races, monkeypatch):
    monkeypatch.setattr(cli_module, "free_bytes", lambda root: 10 * 1024**2)

    output, code = three_races.run()

    assert three_races.fetched == [] and code == 1
    assert "Stopping: 10 MB free where the spool is" in output and "3 session(s) left." in output
    assert spool.free_bytes(three_races.spool / "not" / "made" / "yet") > 0


# --- R16-7: every session has its turn, whether its last fetch failed or arrived ----


def test_a_session_fetched_last_week_and_still_short_goes_behind_one_never_fetched():
    """The order was by when a fetch last failed. A session that is fetched
    every week and is short every time never fails, so it was first every
    time: with a limit of one it was the only session ever fetched."""
    sixth, seventh, eighth = (FetchPlan(session=entry, reason="") for entry in CALENDAR)
    week = timedelta(days=7)

    order = least_recently_failed_first(
        [sixth, seventh, eighth],
        failed_at={seventh.attempt_key: FIRST_FETCH - week},
        fetched_at={sixth.attempt_key: FIRST_FETCH - 2 * week, seventh.attempt_key: FIRST_FETCH - 3 * week},
    )

    assert [plan.session.round for plan in order] == [EIGHTH, SIXTH, SEVENTH]
    # With nothing known of any fetch the order is the plan's.
    assert least_recently_failed_first([sixth, seventh, eighth], {}) == [sixth, seventh, eighth]


def test_when_a_session_was_last_fetched_is_what_its_snapshots_say_as_far_as_they_can_be_believed():
    now = FIRST_FETCH + timedelta(days=30)
    key = layout.attempt_key(2026, "R", "2026-06-28T13:00:00Z")
    snapshots = [
        snapshot(snapshot_id="20260628T180000Z-aaaaaaaa"),
        snapshot(snapshot_id="20260705T180000Z-bbbbbbbb"),
        # Stamped by a clock a year ahead.
        snapshot(snapshot_id="20270705T180000Z-cccccccc"),
    ]

    assert cli_module._last_fetched(snapshots, now) == {key: datetime(2026, 7, 5, 18, tzinfo=timezone.utc)}


# --- R16-6: the outcome of a fetch is the outcome of its own start -------------------

ENTRY = (2026, "R", "2026-05-03T13:00:00Z")


def noted(store, after: timedelta = timedelta(days=1)) -> tuple[int, str]:
    return failing_fetches(store, FIRST_FETCH + after).get(layout.attempt_key(*ENTRY), (0, ""))


def test_two_runs_failing_one_session_at_once_are_two_failures():
    """A starts, B starts, A fails, B fails. Each start counted one and each
    failure another where the note was not its own start's: three."""
    store, at = MemoryStore(), FIRST_FETCH
    a = note_fetch_started(store, *ENTRY, at)
    b = note_fetch_started(store, *ENTRY, at + timedelta(seconds=1))

    note_failed_fetch(store, *ENTRY, "FetchError: A", at + timedelta(seconds=2), a)
    # Two that have not succeeded: A, which failed, and B, of which nothing more is known.
    assert noted(store) == (2, "FetchError: A")
    note_failed_fetch(store, *ENTRY, "FetchError: B", at + timedelta(seconds=3), b)

    assert noted(store) == (2, "FetchError: B")
    # Both have ended: a later failure, noted with no start, counts as one more.
    note_failed_fetch(store, *ENTRY, "FetchError: C", at + timedelta(hours=6))
    assert noted(store) == (3, "FetchError: C")


def test_one_runs_success_does_not_erase_the_start_of_anothers_fetch():
    """A starts, B starts, A succeeds, and B is killed. A's success replaced
    the note, which by then was of B's start: nothing said B was cut short."""
    store, at = MemoryStore(), FIRST_FETCH
    a = note_fetch_started(store, *ENTRY, at)
    b = note_fetch_started(store, *ENTRY, at + timedelta(seconds=1))

    note_fetch_succeeded(store, *ENTRY, at + timedelta(seconds=2), a)

    # The session has been fetched; B's is the one fetch still unaccounted for.
    assert noted(store, after=timedelta(minutes=5)) == (1, INTERRUPTED)
    note_fetch_succeeded(store, *ENTRY, at + timedelta(seconds=3), b)
    assert noted(store, after=timedelta(minutes=5)) == (0, "")
    # And a failure that comes after the session was fetched by another run says nothing.
    note_failed_fetch(store, *ENTRY, "FetchError: late", at + timedelta(seconds=4), a)
    assert noted(store) == (0, "")


# --- R16-8: a marker in the way is not an upload that finished ----------------------


def test_a_marker_that_is_not_the_snapshots_is_not_taken_for_its_upload_having_finished(tmp_path):
    """An upload that finished unseen is told by its marker being there. Any
    marker at that key was believed, and the fetch in the spool, the only
    whole copy, removed on the strength of it."""
    store = MemoryStore()
    directory = left_whole(tmp_path / "spool")
    (spooled,) = spool.waiting(tmp_path / "spool")
    key = f"{layout.snapshot_prefix(AUSTRIA, spooled.snapshot_id)}{layout.SNAPSHOT_MARKER}"
    foreign = {**snapshot(snapshot_id=spooled.snapshot_id).to_json(), "coverage": {}, "objects": {}}
    store.put(key, dump_json(foreign))

    with spool.holding(directory), pytest.raises(ArchiveError, match="is not the marker of this snapshot"):
        cli_module._archive(store, spooled)

    assert (directory / spool.PENDING_NAME).is_file() and list_snapshots(store) == []
    assert [item.key for item in store.list("")] == [key]


# --- knowing: a check that is in place before the job is, and a log a kill cannot empty ---


def test_a_job_that_has_never_run_can_be_let_pass(job):
    output, code = job.run("last-run", "--store", "x", "--allow-never")
    assert code == 0 and "No run of the whole job has been written down" in output
    assert job.run("last-run", "--store", "x")[1] == 1


def test_what_a_run_prints_is_written_a_line_at_a_time(monkeypatch):
    """Sent to a file, output is held back in blocks. A run that is killed
    took its last block with it: the line that said it had started."""
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="ascii"))

    print("held back")
    assert raw.getvalue() == b""
    cli_module._write_utf8()
    print("[2026-10-07T00:00:00Z] run started")

    assert raw.getvalue().decode("utf-8").splitlines() == ["held back", "[2026-10-07T00:00:00Z] run started"]
