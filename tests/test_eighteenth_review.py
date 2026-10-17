"""The cases the eighteenth review of this code found (GPT-6.1 Sol, 2026-10-07, at 2679564).

Nothing of the first rank. The round before had put everything done to a
fetch under one lock, and this round was of that lock and of what the next
run finds. Where a file can be removed while it is open, a lock that is
removed when its directory goes can be held twice. A whole fetch archived by
a later run than the one that made it was never noted as having succeeded.
And the version before this one wrote records this one refused to read,
though they say the same things.
"""

from __future__ import annotations

import json
import os
import time
from datetime import timedelta

import pytest

from f1data import cli as cli_module
from f1data import layout, spool
from f1data.archive import (
    INTERRUPTED,
    ArchiveError,
    failed_fetches,
    failing_fetches,
    list_snapshots,
    write_snapshot,
)
from f1data.store import MemoryStore
from tests.building import FIRST_FETCH
from tests.spooling import SNAPSHOT_ID, a_fetch_in_hand, left_served, left_started, left_whole
from tests.test_fifteenth_review import EIGHTH, SEVENTH, SIXTH, Job, job, three_races  # noqa: F401
from tests.test_publish import AUSTRIA
from tests.test_seventh_review import AUSTRIA_ENTRY
from tests.test_sixteenth_review import NOW, STAMP, STORE, always, failing_once

AUSTRIA_NOTE = layout.attempt_key(2026, "R", AUSTRIA_ENTRY.start_time_utc)

# --- R18-1: a lock is the file its name leads to --------------------------------------


def lock_of(directory):
    return directory.with_name(directory.name + spool.LOCK_SUFFIX)


def test_a_lock_on_a_file_that_was_removed_meanwhile_is_not_the_lock(tmp_path, monkeypatch):
    """A run opens the lock of the fetch it is about to make and is held up
    before it locks it. Another run sweeps the lock: no directory, an hour
    old. The first locks the file it has open, which no name leads to any
    more, and makes its directory; a third makes a new lock file beside that
    directory and holds that. Two runs, each sure it holds the fetch."""
    directory = spool.new_fetch_path(tmp_path / "spool")
    looked: list[bool] = []
    real = spool._is_the_file_named

    def the_first_was_swept(handle, path):
        looked.append(real(handle, path))
        # As it is found where an open file can be removed: not the file of that name.
        return len(looked) > 1 and looked[-1]

    monkeypatch.setattr(spool, "_is_the_file_named", the_first_was_swept)

    with spool.holding(directory) as mine:
        assert mine and looked == [True, True]
        # What is held is what the name leads to: nobody else can take it.
        with lock_of(directory).open("a+b") as theirs:
            assert not spool._try_lock(theirs)
        spool.begin(directory, 2026, EIGHTH, "R", "a store")

    # A name that never settles is not held, and nothing is done under it.
    monkeypatch.setattr(spool, "_is_the_file_named", lambda handle, path: False)
    with spool.holding(directory) as mine:
        assert not mine
        with pytest.raises(RuntimeError, match="without its lock being held"):
            spool.mark_served(directory)


@pytest.mark.skipif(os.name == "nt", reason="Windows does not remove a file that is open")
def test_a_lock_file_removed_between_its_opening_and_its_locking_is_taken_again(tmp_path, monkeypatch):
    directory = spool.new_fetch_path(tmp_path / "spool")
    real = spool._try_lock
    swept: list[bool] = []

    def lock_after_a_sweep(handle):
        if not swept:
            swept.append(True)
            lock_of(directory).unlink()
        return real(handle)

    monkeypatch.setattr(spool, "_try_lock", lock_after_a_sweep)

    with spool.holding(directory) as mine:
        assert mine and swept == [True] and lock_of(directory).is_file()
        with lock_of(directory).open("a+b") as theirs:
            assert not real(theirs)


# --- R18-2: F1 served it, whichever run sees it through -------------------------------


def test_a_whole_fetch_archived_by_a_later_run_is_noted_as_having_succeeded(job, monkeypatch):
    """The run is stopped in the upload, after the fetch was written down.
    The next run archives it, and that was all: the note of the fetch still
    said it had started and never ended. Three of those and the session is
    named as failing, with every fetch of it served."""
    monkeypatch.setattr(
        cli_module, "write_snapshot", failing_once(write_snapshot, KeyboardInterrupt("the task was stopped"))
    )
    assert job.run()[1] == "killed"
    (whole,) = spool.waiting(job.spool)
    assert whole.started is not None and whole.started.attempt is not None
    assert list(failing_fetches(job.store, NOW()).values()) == [(1, INTERRUPTED)]

    output, code = job.run()

    assert code == 0 and "fetched earlier, archived now." in output
    assert failing_fetches(job.store, NOW()) == {} and failed_fetches(job.store, NOW()) == {}
    (noted,) = json.loads(job.store.get(AUSTRIA_NOTE).data)["attempts"].items()
    assert noted[0] == whole.started.attempt and noted[1]["outcome"] == "succeeded"


def test_a_served_fetch_is_a_fetch_that_succeeded_however_far_seeing_it_through_gets(job, monkeypatch):
    monkeypatch.setattr(cli_module, "keep", always(KeyboardInterrupt("the scheduler stopped the task")))
    assert job.run()[1] == "killed"
    monkeypatch.setattr(cli_module, "keep", spool.keep)
    job.cannot_be_read_back = {EIGHTH}

    for _ in range(3):
        output, code = job.run()
        # The run fails, and says what with. The fetch did not.
        assert code == 1 and "could still not be written down" in output and "ATTENTION" not in output
        assert failing_fetches(job.store, NOW()) == {}


# --- R18-3: a record that is not this version's fails the run, and is never acted on ---
#
# The first answer was to read the version before's records, since they say
# the same things. The review after showed what that cost
# (tests/test_nineteenth_review.py): its directories were kept by other
# rules, and read as this version's, two of them could be destroyed. They are
# left as they are and reported, like any record this version did not write.


def test_a_fetch_that_cannot_be_read_fails_the_run_that_leaves_it(job):
    """A fetch nothing could be done with was named, and the run that named
    it exited 0: in the history of a scheduled task, a run with nothing to
    look at."""
    later = left_whole(job.spool, 2026, EIGHTH, "R", STORE)
    payload = json.loads((later / spool.PENDING_NAME).read_text(encoding="utf-8"))
    (later / spool.PENDING_NAME).write_text(json.dumps({**payload, "schema_version": 3}), encoding="utf-8")

    output, code = job.run()

    assert code == 1 and f"ATTENTION: {later} is a fetch whose record cannot be read" in output
    assert "schema 3" in output and (later / "cache").is_dir()
    # Nothing is known of it, so its session is fetched like any other.
    assert job.fetched == [EIGHTH] and len(list_snapshots(job.store)) == 1


# --- R18-4: a part is the marker's by its bytes --------------------------------------


def test_a_part_of_the_right_size_and_other_bytes_is_not_the_markers(tmp_path):
    store = MemoryStore()
    directory = left_whole(tmp_path / "spool")
    (spooled,) = spool.waiting(tmp_path / "spool")
    prefix = layout.snapshot_prefix(AUSTRIA, SNAPSHOT_ID)
    write_snapshot(store, spooled.fetched, now=spooled.fetched_at, snapshot_id=SNAPSHOT_ID)
    key = f"{prefix}fastf1-cache.tar.gz"
    good = store.get(key).data

    store._objects[key] = bytes(len(good))
    with spool.holding(directory), pytest.raises(ArchiveError, match="is not the bytes the marker describes"):
        cli_module._archive(store, spooled)
    assert (directory / spool.PENDING_NAME).is_file()

    store._objects[key] = good
    with spool.holding(directory):
        cli_module._archive(store, spooled)
    assert not directory.exists()


# --- R18-5: a mark with nothing to say what of is not rubbish -------------------------


def test_a_directory_marked_as_served_is_kept_though_nothing_says_what_it_is_of(job):
    left = left_served(job.spool, 2026, SIXTH, "R", STORE)
    (left / spool.INTENT_NAME).unlink()
    long_ago = time.time() - 30 * 86400
    os.utime(left, (long_ago, long_ago))

    output, code = job.run()

    assert code == 1 and f"ATTENTION: {left} is a fetch whose record cannot be read" in output
    assert "it held no record of a fetch" not in output and any((left / "cache").rglob("*.ff1pkl"))
    with pytest.raises(spool.UnreadableError, match="nothing to say which"):
        spool.read(left)
    # What is left of a fetch that never began is rubbish all the same.
    (left / spool.SERVED_NAME).rename(left / spool.SERVING_NAME)
    os.utime(left, (long_ago, long_ago))
    assert "it held no record of a fetch" in job.run()[0] and not left.exists()


# --- the guide --------------------------------------------------------------------


def test_a_fetch_for_another_store_is_counted_while_another_run_holds_it_too(job):
    left_started(job.spool, 2026, SIXTH, "R", "r2:an-account/another-bucket")
    with a_fetch_in_hand(job.spool, 2026, SEVENTH, "R", "r2:an-account/another-bucket", now=FIRST_FETCH + timedelta(hours=1)):
        output, code = job.run()

    assert "2 fetch(es) in the spool are for another store, and are left for it." in output and code == 0
    assert job.fetched == [EIGHTH]


def test_a_whole_fetch_keeps_its_session_out_of_the_plans_by_what_was_asked_too(three_races):
    """A whole fetch is known by the start time F1 files it under. Where the
    calendar's differs, it is still the fetch of the round that was asked."""
    whole = left_whole(three_races.spool, 2026, SIXTH, "R", STORE)
    three_races.store.refusing = "fastf1-cache.tar.gz"

    output, code = three_races.run()

    # Its identity is the Austrian race's, the stand-in's only one, and it
    # was asked as round six: neither is fetched while it waits.
    assert code == 1 and (whole / spool.PENDING_NAME).is_file()
    assert three_races.fetched == [SEVENTH]
