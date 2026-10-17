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

Smaller, and fixed with them: a failed run whose record was written twice
counted twice; one note of a fetch the store refused ended the fetch stage;
a session F1 served that waits for another store was only counted; and the
Cloudflare API token was handed to workflows that had an R2 key pair.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastf1.exceptions import RateLimitExceededError

from f1data import cli as cli_module
from f1data import layout, spool
from f1data.archive import failed_fetches, failing_fetches, list_snapshots, write_snapshot
from f1data.cli import main
from f1data.config import ConfigError, load_env_file, open_store
from f1data.due import plan_fetches
from f1data.extras import fetch_extras
from f1data.fetch import fastf1_limit_reached
from f1data.httplog import HttpRecorder
from f1data.identity import format_utc
from f1data.policy import RETRY_INTERVAL, RETRY_SLACK, RETRY_WINDOW, SLOW_RETRY_INTERVAL
from f1data.store import DirectoryStore, MemoryStore, PreconditionFailed
from tests.spooling import left_whole
from tests.test_archive import fetched_session
from tests.test_due import RACE_START, fetched_at, planned, without_position
from tests.test_extras import ARCHIVE_PATH
from tests.test_fifteenth_review import EIGHTH, SEVENTH, SIXTH, job, three_races  # noqa: F401  (fixtures)
from tests.test_publish import AUSTRIA, schedule_2026, snapshot
from tests.test_seventh_review import CALENDAR
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
    others = ("archive", "v2", "20260101T000000Z-0000ABCD", "20260101T000000Z-0000abcd.old", "x" + made.name)
    assert not any(spool.is_fetch_name(name) for name in others)


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

    message = copy_archive(source, destination)

    assert message == f"{source} holds no snapshot and nothing else to copy, so nothing was copied."


# --- 2: a short session is fetched again on every run of a six-hour schedule ---------

AUSTRIA_ONLY = [entry for entry in schedule_2026() if entry.round == 8]


def runs_that_fetch(builds, waits, fetch=timedelta(minutes=4)) -> list[int]:
    """Which runs of a task started every six hours fetch a session that stays short.

    A run builds first (``builds``, in minutes), and its fetch stage reads the
    clock then. It reaches the session after ``waits`` minutes of other work,
    and the fetch is stamped when it ends.
    """
    template = snapshot(session=without_position())
    first_run = RACE_START + timedelta(hours=5)
    snapshots, fetched = [], []
    for run, (build, wait) in enumerate(zip(builds, waits)):
        planned_at = first_run + run * RETRY_INTERVAL + timedelta(minutes=build)
        if plan_fetches(AUSTRIA_ONLY, snapshots, planned_at):
            ended = planned_at + timedelta(minutes=wait) + fetch
            stamp = f"{ended:%Y%m%dT%H%M%S}Z-{run:08x}"
            snapshots.append(replace(template, snapshot_id=stamp, fetched_at=format_utc(ended)))
            fetched.append(run)
    return fetched


def test_every_run_of_a_six_hour_schedule_fetches_a_short_session_again():
    """The finding. The interval was timed from the end of the last fetch, and
    the run six hours on read the clock after its build: a run found the
    session due only if its build took longer than the last run's build and
    fetch together. Five fetches in the 48 hours, where nine were meant."""
    one_minute = runs_that_fetch(builds=[1] * 10, waits=[0] * 10)
    assert one_minute == list(range(9))

    # Builds of different lengths, and the session reached part of the way
    # into a fetch stage.
    varied = runs_that_fetch(builds=[8, 1, 6, 2, 9, 1, 7, 3, 5, 2], waits=[0, 20, 5, 30, 0, 15, 10, 25, 0, 0])
    assert varied == list(range(9))


def test_a_retry_is_not_due_much_before_its_interval():
    """The slack is for runs that start an interval apart, not a retry at every run started by hand."""
    first_fetch = RACE_START + timedelta(hours=5)
    short = snapshot(snapshot_id=fetched_at(first_fetch), session=without_position())

    due_from = first_fetch + RETRY_INTERVAL - RETRY_SLACK
    assert planned(AUSTRIA_ONLY, [short], due_from - timedelta(minutes=1)) == []
    assert planned(AUSTRIA_ONLY, [short], due_from) == [(8, "R")]


def test_the_weekly_retry_has_the_same_slack():
    """A weekly task, or the six-hourly one, reaches the weekly retry on the run that is a week on."""
    first_fetch = RACE_START + timedelta(hours=5)
    short = snapshot(snapshot_id=fetched_at(first_fetch), session=without_position())
    later = first_fetch + RETRY_WINDOW + timedelta(days=1)
    again = snapshot(snapshot_id=fetched_at(later), session=without_position())

    a_week_on = later + SLOW_RETRY_INTERVAL - timedelta(minutes=30)
    assert planned(AUSTRIA_ONLY, [short, again], a_week_on) == [(8, "R")]
    assert planned(AUSTRIA_ONLY, [short, again], a_week_on - RETRY_SLACK) == []


# --- 3: FastF1's hourly limit stops the fetch stage, and fails nothing -----------------

THE_LIMIT = "any API: 500 calls/h"


def refusing(job, monkeypatch, events: set[int]) -> set[int]:
    """FastF1 refusing these rounds for its hourly limit, part of the way in. Empty the set to stop."""
    fetch = cli_module.fetch_session

    def limited(year, event, session_type, cache_dir):
        if event not in events:
            return fetch(year, event, session_type, cache_dir)
        job.fetched.append(event)
        # Something of the session had arrived.
        (cache_dir / "2026").mkdir(parents=True)
        raise RateLimitExceededError(THE_LIMIT)

    monkeypatch.setattr(cli_module, "fetch_session", limited)
    return events


def attempts(store, entry) -> list[dict]:
    found = store.get(layout.attempt_key(entry.year, entry.session_type, entry.start_time_utc))
    return list(json.loads(found.data)["attempts"].values())


def test_the_batch_stops_at_fastf1s_hourly_limit_and_nothing_is_counted_as_failed(three_races, monkeypatch):
    """The finding. FastF1 raises before the request is sent, and goes on
    raising for the rest of the hour. Each fetch after the first refused
    failed and was noted as failed; F1's archive answered the batch's
    question, so the batch carried on, and three runs of it named every
    session as one that keeps failing."""
    events = refusing(three_races, monkeypatch, {SIXTH})

    output, code = three_races.run()

    assert three_races.fetched == [SIXTH] and code == 0
    assert (
        "  Stopping: FastF1 makes at most 500 requests an hour in one process and refused more "
        f"(RateLimitExceededError: {THE_LIMIT}). Not counted as a failed fetch. "
        "3 session(s) left for the next run."
    ) in output
    assert "FAILED" not in output and "ATTENTION" not in output
    now = datetime.now(timezone.utc)
    assert failed_fetches(three_races.store, now) == {} and failing_fetches(three_races.store, now) == {}
    # The note says what stopped it.
    (entry,) = attempts(three_races.store, CALENDAR[0])
    assert entry["outcome"] == "stopped" and entry["error"] == f"RateLimitExceededError: {THE_LIMIT}"
    # What it had of the session went, as for any fetch F1 had not served in full.
    assert list(three_races.spool.iterdir()) == []

    # The next run is a process of its own. Every session is due, the one that
    # was stopped first.
    events.clear()
    output, code = three_races.run()
    assert three_races.fetched == [SIXTH, SEVENTH, EIGHTH] and code == 0


def test_a_run_stopped_by_the_limit_leaves_its_second_build_to_the_next_run(three_races, monkeypatch):
    """A build asks FastF1 for the calendar of every session. Straight after
    the limit, in the same process, every session would fail to build, and a
    catch-up would fail every run until it was done."""
    refusing(three_races, monkeypatch, {SEVENTH})
    built = []
    monkeypatch.setattr(cli_module, "run_build", lambda args: built.append(args.season) or 0)

    output, code = three_races.run("run", "--store", "x")

    assert three_races.fetched == [SIXTH, SEVENTH] and len(list_snapshots(three_races.store)) == 1
    assert len(built) == 1 and code == 0
    assert "Not building again in this run: FastF1 makes no more requests in this process" in output


def test_fastf1_raises_its_limit_before_anything_is_sent_and_a_fetch_lets_it_through(tmp_path):
    """With FastF1's own count full, a fetch gets as far as the calendar and
    no further. Nothing reached the network, and the directory went."""
    import fastf1.req as req

    # The limit on every host, not the one on ergast.com alone.
    (general,) = [
        limiter
        for pattern, limiters in req._SessionWithRateLimiting._RATE_LIMITS.items()
        if pattern.match("https://livetiming.formula1.com/static/")
        for limiter in limiters
        if isinstance(limiter, req._CallsPerIntervalLimitRaise)
    ]
    saved = list(general._timestamps)
    general._timestamps.extend([time.time()] * general._timestamps.maxlen)
    root = tmp_path / "spool"
    try:
        with HttpRecorder(forbid_all=True) as guard:
            with pytest.raises(RateLimitExceededError) as refused:
                cli_module._fetch_and_archive(MemoryStore(), "a store", root, 2026, 8, "R")
        assert guard.forbidden == [] and guard.records == []
    finally:
        general._timestamps.clear()
        general._timestamps.extend(saved)
    assert fastf1_limit_reached(refused.value) and not fastf1_limit_reached(RuntimeError(THE_LIMIT))
    assert list(root.iterdir()) == []


def test_a_feed_fetched_beside_the_session_does_not_swallow_the_limit():
    """The pit stops, the weather lines and the circuit were each asked for
    under a catch-all. Refused by the limit after the session had loaded, a
    fetch was archived without them, as though F1 had not sent them."""

    def refused(*args, **kwargs):
        raise RateLimitExceededError(THE_LIMIT)

    with pytest.raises(RateLimitExceededError):
        fetch_extras(SimpleNamespace(Cache=SimpleNamespace(requests_get=refused)), None, ARCHIVE_PATH)

    absent = SimpleNamespace(status_code=404, content=b"")
    circuit = SimpleNamespace(
        session_info={"Meeting": {"Circuit": {"Key": 19, "ShortName": "Spielberg"}}},
        event=SimpleNamespace(year=2026),
    )
    by_mvapi = SimpleNamespace(
        Cache=SimpleNamespace(requests_get=lambda *args, **kwargs: absent),
        mvapi=SimpleNamespace(get_circuit_info=refused),
    )
    with pytest.raises(RateLimitExceededError):
        fetch_extras(by_mvapi, circuit, ARCHIVE_PATH)

    # Anything else is what it was: a feed that did not arrive.
    def reset(*args, **kwargs):
        raise ConnectionError("connection reset")

    assert fetch_extras(SimpleNamespace(Cache=SimpleNamespace(requests_get=reset)), None, ARCHIVE_PATH) == {}


# --- 4: .env names the store it was written to name -----------------------------------

R2_NAMES = ("R2_ACCOUNT_ID", "CLOUDFLARE_ACCOUNT_ID", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


def read_env(tmp_path, data: bytes) -> dict[str, str]:
    (tmp_path / ".env").write_bytes(data)
    environ: dict[str, str] = {}
    load_env_file(tmp_path / ".env", environ)
    return environ


def test_an_env_file_that_powershell_wrote_names_the_store(tmp_path):
    """Windows PowerShell 5.1 writes UTF-8 with a byte order mark. Read as
    part of the first name, it made the store `\\ufeffF1DATA_STORE`, which
    nothing asks for."""
    written = "F1DATA_STORE=r2\r\nR2_BUCKET=formula-1-data-artifacts\r\n".encode("utf-8-sig")
    assert written.startswith(b"\xef\xbb\xbf")

    assert read_env(tmp_path, written) == {"F1DATA_STORE": "r2", "R2_BUCKET": "formula-1-data-artifacts"}


def test_a_comment_after_a_value_is_not_part_of_it(tmp_path):
    written = (
        "F1DATA_STORE=r2   # the bucket\n"
        "R2_BUCKET=formula-1-data-artifacts\t# from the dashboard\n"
        'QUOTED="a # b"  # the quotes hold the value\n'
        "SINGLE='c d'\n"
        "JOINED=e#f\n"
        "NOTHING= # yet\n"
    )

    assert read_env(tmp_path, written.encode("utf-8")) == {
        "F1DATA_STORE": "r2",
        "R2_BUCKET": "formula-1-data-artifacts",
        "QUOTED": "a # b",
        "SINGLE": "c d",
        "JOINED": "e#f",
        "NOTHING": "",
    }


def test_a_store_that_is_neither_r2_nor_a_directory_is_refused(tmp_path, monkeypatch, capsys):
    """`F1DATA_STORE=r2  # bucket` was a directory store called `r2  # bucket`,
    made on the first write: every fetch archived there, every build
    published there, and nothing said so."""
    monkeypatch.chdir(tmp_path)
    for name in R2_NAMES:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ConfigError, match="is neither r2 nor a directory that exists"):
        open_store("r2  # bucket")
    with pytest.raises(SystemExit) as finished:
        main(["last-run", "--store", "r2  # bucket"])
    assert "'r2  # bucket' is neither r2 nor a directory that exists" in str(finished.value.code)
    with pytest.raises(SystemExit) as finished:
        main(["build", "--store", str(tmp_path / "not-made")])
    assert "make the directory first" in str(finished.value.code)
    assert list(tmp_path.iterdir()) == []

    # A directory that exists is a store, as it was.
    (tmp_path / "made").mkdir()
    assert isinstance(open_store(str(tmp_path / "made")), DirectoryStore)


def test_the_store_named_with_a_comment_in_env_is_the_bucket(tmp_path, monkeypatch):
    """The whole of it, through the command line. With no R2 settings it stops
    at asking for them, which is where a run against the bucket starts."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("F1DATA_STORE", "set, so that removing it is undone after the test")
    monkeypatch.delenv("F1DATA_STORE")
    for name in R2_NAMES:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_bytes("F1DATA_STORE=r2  # the bucket\r\n".encode("utf-8-sig"))

    with pytest.raises(SystemExit) as finished:
        main(["last-run"])

    assert finished.value.code == "Set R2_ACCOUNT_ID and R2_BUCKET to use the R2 store."
    assert os.environ["F1DATA_STORE"] == "r2" and list(tmp_path.iterdir()) == [tmp_path / ".env"]


def test_a_copy_still_makes_the_directory_it_is_told_to_copy_into(tmp_path, capsys):
    """The one place a new directory store is meant: the destination of a copy, named as such."""
    source = DirectoryStore(tmp_path / "source")
    write_snapshot(source, fetched_session(tmp_path / "fetched"))
    destination = tmp_path / "backup"

    with pytest.raises(SystemExit) as finished:
        main(["copy-archive", "--from", str(tmp_path / "source"), "--to", str(destination)])

    assert finished.value.code == 0
    assert f"Made {destination.resolve()} to copy into." in capsys.readouterr().out
    assert len(list_snapshots(DirectoryStore(destination))) == 1


def test_the_example_env_file_names_every_variable_the_data_plane_reads():
    example = Path(__file__).resolve().parents[1] / ".env.example"
    text = example.read_text(encoding="utf-8")
    for name in ("F1DATA_STORE", "F1DATA_SPOOL", *R2_NAMES, "CLOUDFLARE_API_TOKEN"):
        assert f"{name}=" in text, name
    environ: dict[str, str] = {}
    load_env_file(example, environ)
    assert environ["F1DATA_STORE"] == "r2" and environ["R2_BUCKET"] == "formula-1-data-artifacts"


# --- 5: the one check on the job at home keeps running ---------------------------------

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def jobs_of(text: str) -> dict[str, str]:
    """The text of each job of a workflow, by its key."""
    jobs: dict[str, str] = {}
    current = None
    for line in text[text.index("\njobs:\n") + len("\njobs:\n"):].splitlines(keepends=True):
        found = re.fullmatch(r"  ([A-Za-z_][\w-]*):\s*", line)
        if found:
            current = found.group(1)
            jobs[current] = ""
        elif current is not None:
            jobs[current] += line
    return jobs


def test_the_check_on_the_job_at_home_runs_whatever_the_build_did():
    """It had no condition of its own on the build, so GitHub's default held:
    a step runs only if every step before it succeeded. A build that failed
    on a scheduled run took the check with it."""
    text = workflow("publish.yml")
    step = text[text.index("- name: Check that the fetch job is running"):text.index("- name: Summarise")]

    (condition,) = re.findall(r"^\s+if: (.*)$", step, re.M)
    assert condition == "${{ !cancelled() && github.event_name == 'schedule' && matrix.part == 0 }}"
    # Nothing lets a failed build pass: a step that fails fails its job.
    assert "continue-on-error" not in jobs_of(text)["publish"]


def test_a_scheduled_run_keeps_the_schedule_on_with_a_permission_of_its_own():
    """GitHub turns a public repository's schedules off after sixty days with
    no activity, and the job at home writes to R2 alone: an off-season would
    have stopped publishing, and the check on the job, without a word."""
    text = workflow("publish.yml")
    jobs = jobs_of(text)

    keepalive = jobs["keepalive"]
    assert "    if: github.event_name == 'schedule'\n" in keepalive
    assert "    permissions:\n      actions: write\n    steps:" in keepalive
    assert "GH_TOKEN: ${{ github.token }}" in keepalive
    assert 'gh api --method PUT "repos/$GITHUB_REPOSITORY/actions/workflows/publish.yml/enable"' in keepalive
    # The permission is that job's alone.
    assert re.search(r"^permissions:\n  contents: read\n\n", text, re.M)
    assert "permissions:" not in jobs["publish"] and text.count("actions: write") == 1


@pytest.mark.parametrize("name", ["publish.yml", "upload-archive-spool.yml"])
def test_the_cloudflare_token_is_given_only_where_the_key_pair_is_not(name):
    (given,) = re.findall(r"^\s+CLOUDFLARE_API_TOKEN: (.*)$", workflow(name), re.M)
    assert given == (
        "${{ (secrets.R2_ACCESS_KEY_ID == '' || secrets.R2_SECRET_ACCESS_KEY == '') "
        "&& secrets.CLOUDFLARE_API_TOKEN || '' }}"
    )


# --- 6: a run is counted once in the record of runs -------------------------------------


class LostAnswers(MemoryStore):
    """A write of the record that goes through and whose answer is lost. The
    client sends it again (botocore's standard mode retries a read timeout or
    a dropped connection), and that gets 412: the record is no longer the one
    the write was guarded by."""

    def __init__(self) -> None:
        super().__init__()
        self.lose_next = False

    def put(self, key, data, **kwargs):  # type: ignore[override]
        etag = super().put(key, data, **kwargs)
        if self.lose_next and key == layout.LAST_RUN_KEY:
            self.lose_next = False
            raise PreconditionFailed(key)
        return etag


def last_run(store) -> dict:
    return json.loads(store.get(layout.LAST_RUN_KEY).data)


def test_a_failed_run_whose_write_was_sent_twice_is_one_failure(monkeypatch):
    """The finding. The run read the record again, found its own there, and
    counted itself a second time: one failure after a success said FAILING."""
    store = LostAnswers()
    monkeypatch.setattr(cli_module, "_store", lambda spec: store)
    now = datetime.now(timezone.utc)
    cli_module._note_the_run("r2", now - timedelta(hours=7), now - timedelta(hours=6, minutes=30), 0)

    store.lose_next = True
    cli_module._note_the_run("r2", now - timedelta(hours=1), now - timedelta(minutes=30), 1)

    record = last_run(store)
    assert (record["exit_code"], record["failed_runs"]) == (1, 1)
    # The record names the run before it as counted, besides its own.
    assert len(record["counted"]) == 1 and record["counted"][0] != record["run_id"]


def test_a_run_that_ended_first_and_writes_last_is_counted_once_too(monkeypatch):
    store = LostAnswers()
    monkeypatch.setattr(cli_module, "_store", lambda spec: store)
    now = datetime.now(timezone.utc)
    cli_module._note_the_run("r2", now - timedelta(hours=1), now - timedelta(minutes=10), 1)
    later = last_run(store)

    store.lose_next = True
    cli_module._note_the_run("r2", now - timedelta(hours=2), now - timedelta(minutes=20), 1)

    record = last_run(store)
    assert record["failed_runs"] == 2 and record["run_id"] == later["run_id"]
    assert record["finished_at"] == later["finished_at"] and len(record["counted"]) == 1


# --- 7: a note the store will not take does not end the fetch stage --------------------


def test_a_note_the_store_refuses_does_not_stop_the_fetches(three_races, monkeypatch):
    """Every note of a fetch was written outside the fetch's own handling of
    what went wrong, so one write the bucket refused ended the stage, and the
    fetches still to come with it."""
    store = three_races.store
    whole = left_whole(three_races.spool, 2026, EIGHTH, "R", STORE, start_time_utc=CALENDAR[2].start_time_utc)

    def put(key, data, **kwargs):
        if key.startswith(layout.ATTEMPTS_PREFIX):
            raise ConnectionError(f"connection reset while writing {key}")
        return DirectoryStore.put(store._store, key, data, **kwargs)

    monkeypatch.setattr(store, "put", put, raising=False)

    output, code = three_races.run()

    assert not whole.exists() and three_races.fetched == [SIXTH, SEVENTH]
    assert len(list_snapshots(store)) == 3 and code == 0
    served = f"2026 Austrian Grand Prix Race (session {AUSTRIA})"
    assert f"Could not note {served}: that it was fetched, and carried on" in output
    assert output.count("Could not note that the fetch started, and carried on: ConnectionError") == 2
    assert list(store.list(layout.ATTEMPTS_PREFIX)) == []


# --- 8: a session F1 served, waiting for another store, is reported -------------------


def test_a_whole_fetch_left_for_another_store_fails_the_runs_that_leave_it(job):
    """`fetch --store <dir>` by hand whose upload failed said that `fetch-due`
    or `run` would see it through. The scheduled run, against the bucket,
    counted it as "for another store" and exited 0, on every run for good."""
    job.store.refusing = "fastf1-cache.tar.gz"
    output, code = job.run("fetch", "--store", "x", "--year", "2026", "--event", str(EIGHTH), "--session", "R")
    assert code == 1 and "`fetch-due` or `run` against the same store sees it through" in output
    job.store.refusing = None
    (whole,) = spool.waiting(job.spool)

    output, code = job.run("fetch-due", "--store", "y", "--season", "2026")

    assert code == 1 and (whole.directory / spool.PENDING_NAME).is_file()
    assert (
        f"ATTENTION: 2026 Austrian Grand Prix Race (session {AUSTRIA}) was fetched for another store ({STORE}) "
        f"and waits in the spool ({whole.directory}) for a run against that store, which archives it."
    ) in output
    assert "are for another store, and are left for it" not in output

    # The run it was fetched for sees it through.
    output, code = job.run()
    assert code == 0 and "fetched earlier, archived now." in output and spool.waiting(job.spool) == []
