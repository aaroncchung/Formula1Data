"""The cases the sixteenth review of this code found (GPT-6.1 Sol, 2026-10-07, at 63ce4d5).

The round before gave fetched sessions a spool, so that one the archive would
not take was not thrown away. This round was of the spool itself, and of the
instructions for setting the job up. A fetch that was whole and could not be
written down as whole was still thrown away; a fetch that took longer than a
day could be swept away by another run; and the record of the store in
``.env`` was read too late to be found. The spool now says what a fetch is
of before the fetch starts, is held by a lock for as long as a run is at
it, and what a run leaves in it, at any point, is finished by the next.
"""

from __future__ import annotations

import io
import sys
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
from tests.test_archive import fetched_session
from tests.test_extras import ARCHIVE_PATH
from tests.test_fifteenth_review import EIGHTH, SEVENTH, SIXTH, Job, job, three_races  # noqa: F401
from tests.test_publish import AUSTRIA, snapshot
from tests.test_seventh_review import AUSTRIA_ENTRY, CALENDAR

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731
STORE = cli_module._store_name("x")


def failing_once(function, error):
    """``function``, but raising ``error`` the first time it is called."""
    calls = []

    def wrapped(*arguments, **keywords):
        calls.append(arguments)
        if len(calls) == 1:
            raise error
        return function(*arguments, **keywords)

    return wrapped


# --- R16-1: once F1 has served a session, nothing that goes wrong removes it -------


def test_a_fetch_that_could_not_be_written_down_is_finished_from_what_it_left(job, monkeypatch):
    """F1 serves the session, and the disk is full when the record that makes
    the fetch whole is written. One handler caught that with every failure of
    the fetch itself and removed the directory: the session F1 had just
    served was gone, and was asked for again."""
    monkeypatch.setattr(cli_module, "keep", failing_once(spool.keep, OSError(28, "No space left on device")))

    output, code = job.run()

    assert code == 1 and "FETCHED, NOT ARCHIVED: OSError" in output and "What F1 sent is in" in output
    assert list_snapshots(job.store) == [] and spool.waiting(job.spool) == []
    (cut_short,) = spool.unfinished(job.spool)
    assert (cut_short.event, cut_short.store, cut_short.start_time_utc) == (EIGHTH, STORE, AUSTRIA_ENTRY.start_time_utc)
    assert any((cut_short.directory / "cache").rglob("*.ff1pkl"))
    # F1 answered: nothing says the fetch of it failed.
    assert failed_fetches(job.store, NOW()) == {}

    output, code = job.run()

    assert (job.fetched, job.resumed, code) == ([EIGHTH], [EIGHTH], 0)
    assert "a fetch that was cut short, finished from what it left." in output
    (archived,) = list_snapshots(job.store)
    # Fetched when it was first fetched, whenever it was written down.
    assert archived.fetched_at == cut_short.started_at.strftime("%Y-%m-%dT%H:%M:%SZ")
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


def test_a_fetch_is_finished_in_the_directory_it_was_started_in(monkeypatch, tmp_path):
    """``fetch_session`` asks for an empty directory, so that a snapshot is of
    one fetch. Finishing a fetch that was cut short is that same fetch."""
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
    (left / "2026").mkdir(parents=True)
    (left / "2026" / "session_info.ff1pkl").write_bytes(b"what had arrived")

    with pytest.raises(fetch_module.FetchError, match="needs an empty cache directory"):
        fetch_module.fetch_session(2026, 8, "R", left)
    fetched = fetch_module.fetch_session(2026, 8, "R", left, resume=True)

    assert fetched.cache_dir == left and (left / "2026" / "session_info.ff1pkl").is_file()


# --- R16-5: a fetch is alive while something holds it, however long it takes --------


def test_a_fetch_another_run_is_making_is_neither_finished_nor_planned_nor_swept(job):
    """A fetch with no record of being whole was swept away once it was a day
    old, by its directory's date: a fetch that took longer, or a clock that
    jumped, and another run removed the feeds from under it."""
    theirs = spool.new_fetch_directory(
        job.spool, 2026, EIGHTH, "R", STORE, FIRST_FETCH, start_time_utc=AUSTRIA_ENTRY.start_time_utc
    )
    (theirs / "cache").mkdir()

    with spool.fetching(theirs) as held:
        assert held
        output, code = job.run()
        assert spool.sweep(job.spool, now=theirs.stat().st_mtime + 30 * 86400) == []

    assert job.fetched == [] and "Nothing to fetch" in output
    assert [cut.directory for cut in spool.unfinished(job.spool)] == [theirs]


def test_only_what_is_not_a_fetch_is_swept_and_not_while_anything_holds_it(tmp_path):
    root = tmp_path / "spool"
    started = spool.new_fetch_directory(root, 2026, 6, "R", "a store", FIRST_FETCH)
    stray = root / "left-by-something-else"
    stray.mkdir()
    old = stray.stat().st_mtime + 2 * 3600

    # A directory a run made a moment ago has not yet said what it is.
    assert spool.sweep(root) == []
    with spool.fetching(stray):
        assert spool.sweep(root, now=old) == []
    assert spool.sweep(root, now=old + 365 * 86400) == [stray]
    # A fetch that was started is never swept, however old: it is finished.
    assert [path.name for path in root.iterdir()] == [started.name]


def test_a_fetch_made_for_one_store_is_not_seen_through_by_a_run_against_another(job):
    """The spool is one directory on the machine. A run started by hand
    against a directory would have uploaded there what the scheduled run had
    fetched for the bucket, and removed it."""
    whole = spool.new_fetch_directory(job.spool, 2026, 7, "R", "r2:another-bucket", FIRST_FETCH)
    spool.keep(whole, fetched_session(whole), FIRST_FETCH, "20260628T180000Z-0badcafe")
    cut_short = spool.new_fetch_directory(job.spool, 2026, 6, "R", "r2:another-bucket", FIRST_FETCH)

    output, _ = job.run()

    assert "1 fetch(es) in the spool are waiting for another store, and are left for it." in output
    assert job.resumed == [] and (whole / spool.PENDING_NAME).is_file() and cut_short.is_dir()
    assert [item.store for item in spool.waiting(job.spool)] == ["r2:another-bucket"]
    assert spool.waiting(job.spool, STORE) == [] and spool.unfinished(job.spool, STORE) == []
    assert cli_module._store_name("r2").startswith("r2:") and cli_module._store_name("R2 ") == cli_module._store_name("r2")


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
    monkeypatch.setattr(cli_module, "run_fetch_due", lambda args: seen.append(args.budget_minutes) or 0)
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


def noted(store) -> tuple[int, str]:
    return failing_fetches(store, FIRST_FETCH + timedelta(days=1)).get(layout.attempt_key(*ENTRY), (0, ""))


def test_two_runs_failing_one_session_at_once_are_two_failures():
    """A starts, B starts, A fails, B fails. Each start counted one and each
    failure another where the note was not its own start's: three."""
    store, at = MemoryStore(), FIRST_FETCH
    a = note_fetch_started(store, *ENTRY, at)
    b = note_fetch_started(store, *ENTRY, at + timedelta(seconds=1))

    note_failed_fetch(store, *ENTRY, "FetchError: A", at + timedelta(seconds=2), a)
    assert noted(store) == (2, INTERRUPTED)
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
    assert noted(store) == (1, INTERRUPTED)
    note_fetch_succeeded(store, *ENTRY, at + timedelta(seconds=3), b)
    assert noted(store) == (0, "")
    # And a failure that comes after the session was fetched by another run says nothing.
    note_failed_fetch(store, *ENTRY, "FetchError: late", at + timedelta(seconds=4), a)
    assert noted(store) == (0, "")


# --- R16-8: a marker in the way is not an upload that finished ----------------------


def test_a_marker_that_is_not_the_snapshots_is_not_taken_for_its_upload_having_finished(tmp_path):
    """An upload that finished unseen is told by its marker being there. Any
    marker at that key was believed, and the fetch in the spool, the only
    whole copy, removed on the strength of it."""
    store = MemoryStore()
    directory = spool.new_fetch_directory(tmp_path / "spool", 2026, 8, "R", "a store", FIRST_FETCH)
    spooled = spool.keep(directory, fetched_session(directory), FIRST_FETCH, "20260628T180000Z-0badcafe")
    key = f"{layout.snapshot_prefix(AUSTRIA, spooled.snapshot_id)}{layout.SNAPSHOT_MARKER}"
    foreign = {**snapshot(snapshot_id=spooled.snapshot_id).to_json(), "coverage": {}, "objects": {}}
    store.put(key, dump_json(foreign))

    with pytest.raises(ArchiveError, match="is not the marker of this snapshot"):
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
