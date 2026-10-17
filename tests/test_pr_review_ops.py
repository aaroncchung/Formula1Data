"""The cases a Claude review of pull request 11 found in the fetch stage, 2026-10-17, at 5190b36.

None of them is about the data. The spool's sweep removed whatever was in
``F1DATA_SPOOL`` and not a fetch, a directory store pointed there included.
A short session was retried every twelve hours on a six-hour schedule, since
a retry was timed from when the last fetch ended and runs start six hours
apart. A catch-up run reached FastF1's limit of 500 requests an hour, and
every fetch after that failed and was noted as failed. ``.env`` as
PowerShell writes it, or with a comment after a value, named the wrong store,
and a store that is not ``r2`` was a directory made on the first write. The
one check on the job at home was skipped whenever the build before it
failed, and GitHub turns a schedule off after sixty days of a quiet
repository.
"""

from __future__ import annotations

import os
import time

import pytest

from f1data import spool
from f1data.archive import list_snapshots
from f1data.cli import main
from f1data.store import DirectoryStore
from tests.spooling import left_whole
from tests.test_fifteenth_review import EIGHTH, job  # noqa: F401  (a fixture)
from tests.test_sixteenth_review import STORE

LONG_AGO = time.time() - 2 * 3600


def aged(*paths) -> None:
    for path in paths:
        os.utime(path, (LONG_AGO, LONG_AGO))


# --- 1: the spool sweeps only what a fetch leaves -----------------------------------


def test_a_directory_store_in_the_spool_is_left_alone(job):
    """``F1DATA_SPOOL`` pointed at the directory the stopgap workflow archives
    into: every directory there an hour old was "not a fetch", and was removed
    with all that was in it."""
    root = job.spool
    store = DirectoryStore(root)
    store.put("archive/sessions/9839/20260628T180000Z-0badcafe/snapshot.json", b"{}")
    store.put("v2/index.json", b"{}")
    (root / "photos").mkdir()
    (root / "photos" / "holiday.jpg").write_bytes(b"\xff\xd8")
    (root / "notes.lock").write_bytes(b"")
    aged(root / "archive", root / "v2", root / "photos", root / "notes.lock")

    output, code = job.run()

    assert store.get("archive/sessions/9839/20260628T180000Z-0badcafe/snapshot.json").data == b"{}"
    assert store.get("v2/index.json").data == b"{}"
    assert (root / "photos" / "holiday.jpg").is_file() and (root / "notes.lock").is_file()
    assert "are not fetches, and are left as they are: .f1data-lock, archive, notes.lock, ..." in output
    assert "Removed" not in output
    # The run itself went as it would have in a spool of its own.
    assert code == 0 and job.fetched == [EIGHTH] and len(list_snapshots(job.store)) == 1
    assert spool.directories(root) == [] and spool.not_fetches(root) == sorted(
        root / name for name in (".f1data-lock", "archive", "notes.lock", "photos", "v2")
    )


def test_what_a_stopped_fetch_leaves_is_still_swept(job):
    """A directory named as a fetch with no record in it, and a lock with no
    directory, are what a run that was stopped leaves. Those are still the
    spool's to remove."""
    empty = job.spool / "20260101T000000Z-0000abcd"
    empty.mkdir(parents=True)
    orphan = job.spool / "20260101T000000Z-00000000.lock"
    orphan.write_bytes(b"")
    aged(empty, orphan)

    output, _ = job.run()

    assert "Removed 20260101T000000Z-0000abcd from the spool: it held no record of a fetch." in output
    assert not empty.exists() and not orphan.exists() and "are not fetches" not in output
    assert list(job.spool.iterdir()) == []


def test_only_the_names_a_fetch_is_given_are_a_fetchs():
    made = spool.new_fetch_path(spool.spool_root())
    assert spool.is_fetch_name(made.name)
    for name in ("archive", "v2", "20260101T000000Z-0000ABCD", "20260101T000000Z-0000abcd.old", "x20260101T000000Z-0000abcd"):
        assert not spool.is_fetch_name(name)


def copy_archive(source, destination) -> str:
    with pytest.raises(SystemExit) as finished:
        main(["copy-archive", "--from", str(source), "--to", str(destination)])
    return str(finished.value.code)


def test_copying_from_the_spool_is_refused_and_says_why(tmp_path):
    """It copied nothing and exited 0, and the spool could then be thrown away
    as uploaded, with a session F1 had served in it."""
    destination = tmp_path / "bucket"
    destination.mkdir()
    whole = left_whole(spool.spool_root(), store=STORE)

    message = copy_archive(spool.spool_root(), destination)

    assert "is a spool of fetches, not a store, and nothing in it is copied" in message
    assert "keep the spool until one has" in message
    assert (whole / spool.PENDING_NAME).is_file() and list(destination.iterdir()) == []

    # A copy of it somewhere else is a spool all the same.
    elsewhere = tmp_path / "copied-spool"
    elsewhere.mkdir()
    (elsewhere / whole.name).mkdir()
    assert "is a spool of fetches" in copy_archive(elsewhere, destination)


def test_copying_from_a_store_with_nothing_to_copy_fails(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "bucket"
    source.mkdir()
    destination.mkdir()

    assert copy_archive(source, destination) == f"{source} holds no snapshot and nothing else to copy, so nothing was copied."
