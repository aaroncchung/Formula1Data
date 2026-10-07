"""The cases the fifteenth review of this code found (GPT-6.1 Sol, 2026-10-06, at cc79a2d).

It was asked what stops the job from running unattended: a scheduled task on
a Windows machine every six hours, for three race weekends, with nobody at
the keyboard. Nothing it found is about the data. A session that F1 served
and the archive would not take was thrown away and fetched again; a request
that never returned held a run until it was killed, and the next run began
with the same session; on the first of January last year's unfinished
sessions stopped being looked at; a copy made while a fetch was being
uploaded could carry a marker without its parts; and a run that did not
happen said so nowhere.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from f1data import cli as cli_module
from f1data import layout, spool
from f1data import store as store_module
from f1data.archive import (
    INTERRUPTED,
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
from f1data.fetch import FetchError
from f1data.httplog import request_timeouts
from f1data.policy import REQUEST_TIMEOUT_SECONDS
from f1data.store import DirectoryStore, MemoryStore
from tests.building import FIRST_FETCH
from tests.fakes import make_session, measure
from tests.test_archive import fetched_session
from tests.test_fourth_review import without_positions_for_one_driver
from tests.test_publish import AUSTRIA, snapshot
from tests.test_seventh_review import AUSTRIA_ENTRY, CALENDAR
from tests.test_sixth_review import copy

SIXTH, SEVENTH, EIGHTH = (entry.round for entry in CALENDAR)


class Flaky:
    """A directory store that can be told to refuse uploads, as a bucket does when the connection drops."""

    def __init__(self, root: Path) -> None:
        self._store = DirectoryStore(root)
        self.refusing: str | None = None
        self.uploads: list[str] = []

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def put_file(self, key: str, path: Path, **rest) -> None:
        if self.refusing is not None and key.endswith(self.refusing):
            raise ConnectionError(f"connection reset while uploading {key}")
        self.uploads.append(key)
        self._store.put_file(key, path, **rest)


class Job:
    """The command line with FastF1 and the network stood in for, and one store across runs."""

    def __init__(self, tmp_path, monkeypatch, capsys, calendar=CALENDAR) -> None:
        self.store = Flaky(tmp_path / "store")
        self.fetched: list[int] = []
        # The fetches that were made to finish one that was cut short.
        self.resumed: list[int] = []
        self.fails: set[int] = set()
        self.dies_in: int | None = None
        self._capsys = capsys

        @contextmanager
        def no_cache(cache_dir):
            yield None

        def fetch(year, event, session_type, cache_dir, resume=False):
            self.fetched.append(event)
            if resume:
                self.resumed.append(event)
            if event == self.dies_in:
                # Something of it had arrived.
                (cache_dir / "2026").mkdir(parents=True, exist_ok=True)
                raise KeyboardInterrupt("the scheduler stopped the task at its time limit")
            if event in self.fails:
                raise FetchError(f"F1 has no session information for {year} round {event}")
            # FastF1 reads back what a cut-short fetch left; this stand-in fetches it all again.
            shutil.rmtree(cache_dir, ignore_errors=True)
            return fetched_session(cache_dir.parent)

        monkeypatch.setattr(cli_module, "fastf1_cache", no_cache)
        monkeypatch.setattr(cli_module, "load_schedule", lambda fastf1, year: [e for e in calendar if e.year == year])
        monkeypatch.setattr(cli_module, "fetch_session", fetch)
        monkeypatch.setattr(cli_module, "f1_is_answering", lambda years: True)
        monkeypatch.setattr(cli_module, "_store", lambda spec: self.store)

    def run(self, *arguments: str) -> tuple[str, object]:
        self._capsys.readouterr()
        self.fetched.clear()
        self.resumed.clear()
        try:
            main(list(arguments) or ["fetch-due", "--store", "x", "--season", "2026"])
        except SystemExit as finished:
            return self._capsys.readouterr().out, finished.code
        except KeyboardInterrupt:
            return self._capsys.readouterr().out, "killed"
        raise AssertionError("the command returned")

    @property
    def spool(self) -> Path:
        return spool.spool_root()


@pytest.fixture
def job(tmp_path, monkeypatch, capsys):
    return Job(tmp_path, monkeypatch, capsys, calendar=[AUSTRIA_ENTRY])


@pytest.fixture
def three_races(tmp_path, monkeypatch, capsys):
    return Job(tmp_path, monkeypatch, capsys)


# --- R15-1: what F1 served is kept until the archive has it ------------------------


def test_a_session_the_archive_would_not_take_is_kept_and_archived_by_the_next_run(job):
    """F1 serves the session in full and the connection drops in the upload.
    The fetched feeds were in the run's scratch directory and went with it:
    the next run asked F1 again, and the first answers were gone."""
    job.store.refusing = "http-cache.sqlite.gz"

    output, code = job.run()

    assert job.fetched == [EIGHTH] and code == 1
    assert "FETCHED, NOT ARCHIVED: ConnectionError" in output
    assert list_snapshots(job.store) == []
    (kept,) = spool.waiting(job.spool)
    assert kept.fetched.identity.session_key == AUSTRIA and (kept.directory / "cache").is_dir()
    # F1 answered, so nothing says the fetch failed.
    assert failed_fetches(job.store, datetime.now(timezone.utc)) == {}

    job.store.refusing = None
    output, code = job.run()

    assert job.fetched == [] and code == 0
    assert "fetched earlier, archived now." in output
    (archived,) = list_snapshots(job.store)
    assert (archived.snapshot_id, archived.fetched_at) == (kept.snapshot_id, kept.fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert spool.waiting(job.spool) == [] and list(job.spool.iterdir()) == []
    # One snapshot, under one name: the second attempt wrote over the first's parts.
    prefix = layout.session_archive_prefix(AUSTRIA)
    assert {item.key.split("/")[3] for item in job.store.list(prefix)} == {archived.snapshot_id}


def test_f1_is_not_asked_again_for_a_session_that_is_waiting_to_be_archived(job):
    job.store.refusing = "fastf1-cache.tar.gz"
    job.run()

    output, code = job.run()

    assert job.fetched == [] and code == 1
    assert "still NOT ARCHIVED: ConnectionError" in output
    assert len(spool.waiting(job.spool)) == 1


def test_the_fetch_command_keeps_what_it_fetched_too(job):
    job.store.refusing = "fastf1-cache.tar.gz"

    output, code = job.run("fetch", "--store", "x", "--year", "2026", "--event", str(EIGHTH), "--session", "R")

    assert code == 1 and "FETCHED, NOT ARCHIVED" in output and len(spool.waiting(job.spool)) == 1


def test_an_upload_that_finished_unseen_is_not_made_again(tmp_path):
    """The run died between writing the marker and clearing the spool. The
    parts in the archive are the ones the marker's checksums are of; made
    again they would be other bytes under the same names."""
    store = Flaky(tmp_path / "store")
    fetched = fetched_session(tmp_path / "fetch")

    first = write_snapshot(store, fetched, now=FIRST_FETCH, snapshot_id="20260628T180000Z-0badcafe")
    uploaded = list(store.uploads)
    again = write_snapshot(store, fetched, now=FIRST_FETCH + timedelta(hours=6), snapshot_id="20260628T180000Z-0badcafe")

    assert again == first and store.uploads == uploaded
    with pytest.raises(Exception, match="Not a snapshot id"):
        write_snapshot(store, fetched, snapshot_id="../elsewhere")


def test_a_spooled_fetch_is_everything_a_snapshot_records(tmp_path):
    directory = spool.new_fetch_directory(tmp_path / "spool", 2026, 8, "R", "a store", FIRST_FETCH)
    fetched = fetched_session(directory)
    fetched = replace(fetched, feed_status={"SessionInfo.jsonStream": 200}, attempts=2)

    spool.keep(directory, fetched, FIRST_FETCH, "20260628T180000Z-0badcafe")
    (kept,) = spool.waiting(tmp_path / "spool")

    assert (kept.snapshot_id, kept.fetched_at, kept.store) == ("20260628T180000Z-0badcafe", FIRST_FETCH, "a store")
    for name in ("identity", "coverage", "versions", "extras", "feed_status", "attempts", "cache_dir"):
        assert getattr(kept.fetched, name) == getattr(fetched, name), name
    assert kept.fetched.http.summary() == fetched.http.summary()
    # Archived from the spool, it is the snapshot the fetch itself would have written.
    one, other = MemoryStore(), MemoryStore()
    assert write_snapshot(one, kept.fetched, kept.fetched_at, kept.snapshot_id).to_json() == write_snapshot(
        other, fetched, FIRST_FETCH, "20260628T180000Z-0badcafe"
    ).to_json()


def test_a_fetch_is_whole_only_once_it_says_so(tmp_path):
    root = tmp_path / "spool"
    started = spool.new_fetch_directory(root, 2026, 6, "R", "a store", FIRST_FETCH)
    whole = spool.new_fetch_directory(root, 2026, 8, "R", "a store", FIRST_FETCH + timedelta(seconds=1))
    spool.keep(whole, fetched_session(whole), FIRST_FETCH, "20260628T180000Z-0badcafe")
    unreadable = spool.new_fetch_directory(root, 2026, 7, "R", "a store", FIRST_FETCH + timedelta(seconds=2))
    (unreadable / spool.PENDING_NAME).write_text("{", encoding="utf-8")

    assert [kept.directory for kept in spool.waiting(root)] == [whole]
    assert [(cut.directory, cut.event, cut.resumes) for cut in spool.unfinished(root)] == [(started, 6, 0)]
    with pytest.raises(ValueError, match="was not made in"):
        spool.keep(whole, fetched_session(tmp_path / "elsewhere"), FIRST_FETCH, "20260628T180000Z-0badcafe")


def test_two_runs_do_not_archive_one_fetch_at_once(tmp_path):
    directory = spool.new_fetch_directory(tmp_path / "spool", 2026, 8, "R", "a store")

    with spool.uploading(directory) as mine:
        with spool.uploading(directory) as theirs:
            assert (mine, theirs) == (True, False)
    with spool.uploading(directory) as later:
        assert later is True


def test_the_spool_is_where_the_environment_says_or_a_directory_of_the_users_own():
    assert spool.spool_root({"F1DATA_SPOOL": "D:/kept"}) == Path("D:/kept")
    if os.name == "nt":
        assert spool.spool_root({"LOCALAPPDATA": "C:/Users/x/AppData/Local"}) == Path(
            "C:/Users/x/AppData/Local/f1data/spool"
        )
    assert spool.spool_root({}).name == "spool"


# --- R15-2: a request has a time limit, and a run that is killed has still said it tried ---


def test_a_request_with_no_time_limit_is_given_one(monkeypatch):
    """FastF1 asks for its feeds and its calendar with no limit. A connection
    that was accepted and then went quiet held the run until the scheduler
    killed it, two hours later."""
    seen: list[object] = []
    monkeypatch.setattr(requests.Session, "send", lambda self, request, **kwargs: seen.append(kwargs.get("timeout")))
    request = requests.Request("GET", "https://livetiming.formula1.com/static/x").prepare()

    with request_timeouts((3.0, 9.0)):
        requests.Session().send(request)
        requests.Session().send(request, timeout=None)
        requests.Session().send(request, timeout=1.5)
    requests.Session().send(request)

    assert seen == [(3.0, 9.0), (3.0, 9.0), 1.5, None]


def test_every_command_runs_with_the_time_limit(job, monkeypatch):
    limits: list[object] = []

    @contextmanager
    def recording(timeout):
        limits.append(timeout)
        yield

    monkeypatch.setattr(cli_module, "request_timeouts", recording)

    job.run("last-run", "--store", "x")

    assert limits == [REQUEST_TIMEOUT_SECONDS] and REQUEST_TIMEOUT_SECONDS[1] <= 300


def test_a_run_killed_in_the_middle_of_a_fetch_does_not_begin_the_next_with_the_same_session(three_races):
    """Nothing was noted of a fetch until it ended. A run that was stopped
    in the middle of one left no trace of it, so the next run took the same
    session first, and could be stopped there again: no later session had
    its turn."""
    three_races.dies_in = SIXTH

    _, code = three_races.run()

    assert code == "killed" and three_races.fetched == [SIXTH]
    ((key, (failures, error)),) = failing_fetches(three_races.store, datetime.now(timezone.utc)).items()
    assert key == layout.attempt_key(2026, "R", CALENDAR[0].start_time_utc)
    assert (failures, error) == (1, INTERRUPTED)
    # What had arrived is kept, and the next run finishes that fetch from it
    # before it starts another (tests/test_sixteenth_review.py). If it is
    # stopped in that too, the fetch is let go and the session waits its
    # turn, behind the ones that have not been tried.
    (cut_short,) = spool.unfinished(three_races.spool)
    assert (cut_short.event, cut_short.resumes) == (SIXTH, 0)

    _, code = three_races.run()
    assert code == "killed" and (three_races.fetched, three_races.resumed) == ([SIXTH], [SIXTH])

    three_races.dies_in = None
    output, _ = three_races.run()

    assert "a fetch that was cut short twice is let go" in output
    assert (three_races.fetched, three_races.resumed) == ([SEVENTH, EIGHTH, SIXTH], [])


def test_a_fetch_that_succeeds_has_no_failure_to_its_name(three_races):
    three_races.fails = {SIXTH}
    three_races.run()
    assert len(failed_fetches(three_races.store, datetime.now(timezone.utc))) == 1

    three_races.fails = set()
    three_races.run()

    assert failed_fetches(three_races.store, datetime.now(timezone.utc)) == {}


def test_a_session_that_has_failed_three_runs_running_is_named_at_the_end_of_the_run(three_races):
    three_races.fails = {SIXTH}

    outputs = [three_races.run()[0] for _ in range(3)]

    assert "ATTENTION" not in outputs[0] + outputs[1]
    assert "ATTENTION: 2026 round 6 Sixth Grand Prix Race has failed to fetch 3 times in a row. Last: FetchError" in outputs[2]


def test_the_count_of_failures_is_of_fetches_that_did_not_succeed_one_after_another():
    store = MemoryStore()
    entry = (2026, "R", "2026-05-03T13:00:00Z")
    at = FIRST_FETCH

    def count() -> int:
        return failing_fetches(store, at + timedelta(days=2)).get(layout.attempt_key(*entry), (0, ""))[0]

    first = note_fetch_started(store, *entry, at)
    note_failed_fetch(store, *entry, "FetchError: one", at + timedelta(seconds=5), first)
    assert count() == 1
    # A run that was killed: started, and never said how it ended.
    note_fetch_started(store, *entry, at + timedelta(hours=6))
    assert count() == 2
    third = note_fetch_started(store, *entry, at + timedelta(hours=12))
    note_failed_fetch(store, *entry, "FetchError: three", at + timedelta(hours=12, seconds=5), third)
    assert count() == 3
    # A failure noted with no start before it, as a version before this one noted them.
    note_failed_fetch(store, *entry, "FetchError: four", at + timedelta(hours=18))
    assert count() == 4
    note_fetch_succeeded(store, *entry, at + timedelta(hours=24))
    assert count() == 0
    note_fetch_started(store, *entry, at + timedelta(hours=30))
    assert count() == 1


# --- R15-3: the turn of the year drops nothing --------------------------------------


def of_year(year: int, session_key: int, session=None):
    return snapshot(session_key=session_key, session=session, start=f"{year}-06-28T13:00:00Z")


def test_a_session_still_short_is_looked_at_whatever_year_it_is_of():
    """The scheduled run looked at "this year". On the first of January a
    session of the year before that was still short of a feed stopped being
    fetched, though the rule is that it is fetched for as long as it is."""
    new_year = datetime(2027, 1, 2, tzinfo=timezone.utc)
    short = without_positions_for_one_driver(10)

    assert cli_module._seasons_in_scope(new_year, [], set()) == [2026, 2027]
    assert cli_module._seasons_in_scope(new_year, [of_year(2025, 9001)], set()) == [2026, 2027]
    assert cli_module._seasons_in_scope(new_year, [of_year(2025, 9001, short)], set()) == [2025, 2026, 2027]
    # Published as partial, and still on the list.
    assert cli_module._seasons_in_scope(new_year, [of_year(2024, 9001)], {9001}) == [2024, 2026, 2027]
    # The best snapshot of a session speaks for it.
    both = [of_year(2025, 9001, short), replace(of_year(2025, 9001), snapshot_id="20261006T200000Z-bbbbbbbb")]
    assert cli_module._seasons_in_scope(new_year, both, set()) == [2026, 2027]


def test_one_seasons_calendar_failing_does_not_stop_the_others(job, monkeypatch):
    def load(fastf1, year):
        if year == 2027:
            raise RuntimeError("no schedule for 2027 yet")
        return [AUSTRIA_ENTRY]

    monkeypatch.setattr(cli_module, "load_schedule", load)

    output, code = job.run("fetch-due", "--store", "x", "--season", "2026", "--season", "2027")

    assert "Could not load the calendar of 2027" in output and job.fetched == [EIGHTH] and code == 1

    monkeypatch.setattr(cli_module, "load_schedule", lambda fastf1, year: (_ for _ in ()).throw(RuntimeError("down")))
    output, code = job.run("fetch-due", "--store", "x", "--season", "2026")
    assert code == "Could not load any calendar, so nothing was fetched."


def test_a_run_whose_fetch_stage_cannot_start_still_builds_and_says_when_it_ended(job, monkeypatch):
    """The whole job stopped where the calendar could not be loaded, before
    its build stage: nothing the archive already held was published either."""
    built: list[object] = []
    monkeypatch.setattr(cli_module, "run_fetch_due", lambda args: (_ for _ in ()).throw(SystemExit("no calendar")))
    monkeypatch.setattr(cli_module, "run_build", lambda args: built.append(args.season) or 0)

    output, code = job.run("run", "--store", "x")

    assert built == [[datetime.now(timezone.utc).year]] and code == 1
    lines = output.splitlines()
    assert lines[0].endswith("] run started") and "no calendar" in lines
    assert "] run finished, exit 1, " in lines[-1] and lines[-1].endswith(" s")
    record = json.loads(job.store.get(layout.LAST_RUN_KEY).data)
    assert record["exit_code"] == 1 and record["started_at"] <= record["finished_at"]


# --- R15-4: a snapshot is copied as its marker describes it ---------------------------


class ListingTakenEarlier:
    """A source whose listing was read before some of its objects were written, as a paged listing is."""

    def __init__(self, store, not_yet_listed: str) -> None:
        self._store = store
        self._late = not_yet_listed

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def list(self, prefix: str):
        return (item for item in self._store.list(prefix) if self._late not in item.key or item.key.endswith("snapshot.json"))


def test_a_copy_made_while_a_snapshot_is_being_uploaded_carries_all_of_it_or_none(tmp_path, capsys, monkeypatch):
    """A listing of the bucket comes in pages. A fetch that writes its extras
    and its marker between two pages is in the listing as a marker without
    extras, and that is what was copied: a marker, last as ever, describing
    parts that were not there."""
    source, destination = DirectoryStore(tmp_path / "source"), DirectoryStore(tmp_path / "destination")
    written = write_snapshot(source, fetched_session(tmp_path), now=FIRST_FETCH)
    stores = {str(tmp_path / "source"): ListingTakenEarlier(source, "/extra/"), str(tmp_path / "destination"): destination}
    monkeypatch.setattr(cli_module, "_store", lambda spec: stores[spec])

    output = copy(tmp_path / "source", tmp_path / "destination", capsys)

    assert "Copied 5 object(s); 0 already there." in output
    (copied,) = list_snapshots(destination)
    assert copied == written
    prefix = layout.snapshot_prefix(AUSTRIA, written.snapshot_id)
    assert {item.key[len(prefix) :] for item in destination.list(prefix)} == {*written.objects, layout.SNAPSHOT_MARKER}


@pytest.mark.parametrize("damage", ["missing", "other bytes"])
def test_a_snapshot_that_is_not_whole_at_the_source_is_not_copied(damage, tmp_path, capsys):
    source = DirectoryStore(tmp_path / "source")
    written = write_snapshot(source, fetched_session(tmp_path / "one"), now=FIRST_FETCH)
    whole = write_snapshot(source, fetched_session(tmp_path / "two"), now=FIRST_FETCH + timedelta(hours=6))
    part = source.root / "archive" / "sessions" / str(AUSTRIA) / written.snapshot_id / "extra" / "circuit-info.json"
    part.unlink() if damage == "missing" else part.write_bytes(b"{}")

    capsys.readouterr()
    with pytest.raises(SystemExit) as finished:
        main(["copy-archive", "--from", str(tmp_path / "source"), "--to", str(tmp_path / "destination")])
    output = capsys.readouterr().out

    assert finished.value.code == 1
    assert "the source does not hold the snapshot as its marker describes it" in output
    assert "Left 1 snapshot(s) that are not whole at the source" in output
    assert list_snapshots(DirectoryStore(tmp_path / "destination")) == [whole]


def test_what_a_store_remembers_of_its_own_runs_is_not_copied(tmp_path, capsys):
    source = DirectoryStore(tmp_path / "source")
    write_snapshot(source, fetched_session(tmp_path), now=FIRST_FETCH)
    note_failed_fetch(source, 2026, "R", "2026-05-03T13:00:00Z", "FetchError: x", FIRST_FETCH)
    source.put(layout.LAST_RUN_KEY, dump_json({"finished_at": "2026-06-28T20:00:00Z"}))
    # Parts of a snapshot that has no marker: an upload that never finished.
    source.put("archive/sessions/11315/20260101T000000Z-00000000/extra/circuit-info.json", b"{}")

    copy(tmp_path / "source", tmp_path / "destination", capsys)

    keys = [item.key for item in DirectoryStore(tmp_path / "destination").list("")]
    assert len(keys) == 5 and all(key.startswith("archive/sessions/11315/") for key in keys)
    assert not any("20260101T000000Z" in key for key in keys)


# --- knowing that a run did not happen ------------------------------------------------


def test_the_last_run_is_written_down_and_a_job_that_has_stopped_running_is_said_to_have(job, monkeypatch):
    """A run that fails says so in its log and its exit code. A run that
    does not happen, because the task was disabled or the machine is off,
    says nothing anywhere."""
    output, code = job.run("last-run", "--store", "x")
    assert code == 1 and "No run of the whole job has been written down" in output

    monkeypatch.setattr(cli_module, "run_build", lambda args: 0)
    job.run("run", "--store", "x", "--season", "2026")
    output, code = job.run("last-run", "--store", "x")
    assert code == 0 and "hours ago, with exit code 0." in output

    record = json.loads(job.store.get(layout.LAST_RUN_KEY).data)
    stale = (datetime.now(timezone.utc) - timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    job.store.put(layout.LAST_RUN_KEY, dump_json({**record, "finished_at": stale}))
    output, code = job.run("last-run", "--store", "x")
    assert code == 1 and "the job is not running" in output
    output, code = job.run("last-run", "--store", "x", "--max-age-hours", "24")
    assert code == 0

    job.store.put(layout.LAST_RUN_KEY, b"not json")
    assert job.run("last-run", "--store", "x")[1] == 1


def test_a_meeting_with_an_accent_in_its_name_is_printed_whatever_the_code_page(monkeypatch):
    """A scheduled task has no console, and its output goes to a file in the
    machine's code page."""
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="ascii"))

    cli_module._write_utf8()
    print("2025 São Paulo Grand Prix Sprint ✓")
    sys.stdout.flush()

    assert raw.getvalue().decode("utf-8").strip() == "2025 São Paulo Grand Prix Sprint ✓"


# --- Windows: a path of any length, and a file something else has open for a moment ----


def test_a_store_in_a_deep_directory_holds_a_generation(tmp_path):
    """A generation is filed under the 64 characters of its name. Under a
    directory already 200 characters deep that is past what Windows takes,
    unless the path is written in its long form."""
    deep = tmp_path
    while len(str(deep)) < 200:
        deep = deep / ("d" * 40)
    store = DirectoryStore(deep)
    key = layout.generation_prefix(AUSTRIA, "a1" * 32) + "analysis/corner-analysis.json"
    assert len(str(deep)) + len(key) > 260

    store.put(key, b"{}")
    store.put(key, b'{"again": true}', if_match=store.get(key).etag)

    assert store.get(key).data == b'{"again": true}'
    assert [item.key for item in store.list(layout.format_prefix())] == [key]
    assert store.download_file(key, tmp_path / "copy.json") and (tmp_path / "copy.json").read_bytes() == b'{"again": true}'


def test_a_rename_refused_for_a_moment_is_tried_again(tmp_path, monkeypatch):
    """An indexer or a virus scanner has the old file open for the moment it
    takes to look, and Windows refuses to replace an open file."""
    store = DirectoryStore(tmp_path)
    store.put("v2/index.json", b"old")
    refusals = iter([PermissionError("in use"), PermissionError("in use")])
    replace_file = os.replace

    def busy(source, target):
        refusal = next(refusals, None)
        if refusal is not None:
            raise refusal
        return replace_file(source, target)

    monkeypatch.setattr(store_module.os, "replace", busy)
    monkeypatch.setattr(store_module.time, "sleep", lambda seconds: None)

    store.put("v2/index.json", b"new")
    assert store.get("v2/index.json").data == b"new"

    monkeypatch.setattr(store_module.os, "replace", lambda source, target: (_ for _ in ()).throw(PermissionError("held")))
    with pytest.raises(PermissionError):
        store.put("v2/index.json", b"newer")
    assert store.get("v2/index.json").data == b"new" and [item.key for item in store.list("")] == ["v2/index.json"]
