"""The cases the seventeenth review of this code found (GPT-6.1 Sol, 2026-10-07, at b9aedef).

The round before made a fetch recoverable from before it starts: a lock on
its directory, a mark when F1 has served it, and a fetch that was stopped
carried on by the next run. This round was of that. Two runs at once could
remove a session F1 had served, because each decided what a directory was
before it took the lock and acted on that afterwards. And carrying a fetch
on was a second fetch under the first one's name: it asked the calendar of
today which session a round was, replaced responses that had gone stale,
and made requests where the stage's time limit did not look.

What was changed is the design and not the cases. A directory has one lock,
taken before the directory exists and held through everything done to it,
and what a directory is, is read under it. A fetch that was stopped part of
the way is removed and made again. A session F1 served is read back from
its own cache with every request refused. The build has its turn before
anything is asked of F1. And the note of a session's fetches lists them,
each with its own outcome, so that it says the same whoever wrote first.
"""

from __future__ import annotations

import itertools
import json
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from f1data import build as build_module
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
from f1data.build import Builder
from f1data.classification import ClassificationMissing, ClassificationUnavailable
from f1data.extras import WEATHER_SERIES
from f1data.fetch import fastf1_cache
from f1data.httplog import ForbiddenHostError, HttpRecorder
from f1data.policy import A_FETCH_IS_OVER_AFTER
from f1data.publish import Hold
from f1data.store import MemoryStore
from tests.building import FIRST_FETCH, Archive
from tests.race import extras, make_race
from tests.spooling import SNAPSHOT_ID, a_fetch_in_hand, left_served, left_started, left_whole
from tests.test_archive import fetched_session
from tests.test_extras import ARCHIVE_PATH
from tests.test_fifteenth_review import EIGHTH, SEVENTH, SIXTH, Job, job, three_races  # noqa: F401
from tests.test_fifth_review import EVERYONE, WINDOW_CLOSED
from tests.test_publish import AUSTRIA
from tests.test_seventh_review import AUSTRIA_ENTRY
from tests.test_sixteenth_review import NOW, STAMP, STORE, always

# --- R17-1: what a directory is, is read under its lock ------------------------------


def test_the_directory_of_a_fetch_is_held_from_before_it_exists(job, monkeypatch):
    """A run made its directory, wrote what the fetch was of, and then took
    the lock. In between, another run found a fetch nobody held, carried it
    on, was served the session and failed to upload it; the first then took
    the lock, found the cache not empty, and removed the lot."""
    real_begin, real_fetch = cli_module.begin, cli_module.fetch_session
    seen: list[tuple[str, bool, bool]] = []

    def another_run_cannot_take(directory: Path) -> bool:
        with spool.holding(directory) as theirs:
            return not theirs

    def begin(directory, *rest, **more):
        seen.append(("begin", directory.exists(), another_run_cannot_take(directory)))
        return real_begin(directory, *rest, **more)

    def fetch(year, event, session_type, cache_dir):
        seen.append(("fetch", (cache_dir.parent / spool.INTENT_NAME).is_file(), another_run_cannot_take(cache_dir.parent)))
        return real_fetch(year, event, session_type, cache_dir)

    monkeypatch.setattr(cli_module, "begin", begin)
    monkeypatch.setattr(cli_module, "fetch_session", fetch)
    monkeypatch.setattr(cli_module, "write_snapshot", always(ConnectionError("the upload failed")))

    _, code = job.run()

    # Held before there was a directory, and still held while it was fetched into.
    assert seen == [("begin", False, True), ("fetch", True, True)] and code == 1
    (waiting,) = spool.waiting(job.spool)
    # Once the run is done with it, it is there for the next to take.
    with spool.holding(waiting.directory) as mine:
        assert mine
    with pytest.raises(RuntimeError, match="without its lock being held"):
        spool.begin(job.spool / "not-held", 2026, EIGHTH, "R", STORE)


def test_what_a_run_does_with_a_directory_is_decided_by_what_it_is_under_the_lock(job, monkeypatch):
    """A run looked at a directory, saw part of a session, and waited for the
    lock. The run that held it was served the session and marked it; the
    first then removed it as the part of a session it had seen."""
    real_holding = cli_module.holding
    with a_fetch_in_hand(job.spool, 2026, EIGHTH, "R", STORE, start_time_utc=AUSTRIA_ENTRY.start_time_utc) as theirs:
        (theirs / spool.CACHE_DIRECTORY / "2026").mkdir(parents=True)
    assert [left.served for left in spool.unfinished(job.spool)] == [False]

    @contextmanager
    def after_the_other_run_has_finished(directory):
        if directory == theirs and not (theirs / spool.SERVED_NAME).exists():
            # The other run, between this one's look and its taking the lock.
            with spool.holding(theirs) as held:
                assert held
                (theirs / spool.CACHE_DIRECTORY / "2026").rmdir()
                fetched_session(theirs)
                spool.mark_served(theirs, FIRST_FETCH)
        with real_holding(directory) as mine:
            yield mine

    monkeypatch.setattr(cli_module, "holding", after_the_other_run_has_finished)

    output, code = job.run()

    assert "is removed" not in output and "written down from its cache and archived" in output
    assert (job.fetched, job.read_back, code) == ([], [EIGHTH], 0)
    assert [found.fetched_at for found in list_snapshots(job.store)] == [FIRST_FETCH.strftime(STAMP)]


def test_a_directory_another_process_holds_is_left_alone(job):
    """The lock is the operating system's, between processes as between runs."""
    served = left_served(job.spool, 2026, EIGHTH, "R", STORE, start_time_utc=AUSTRIA_ENTRY.start_time_utc)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "from f1data import spool\n"
            "with spool.holding(sys.argv[1]) as mine:\n"
            "    print('held' if mine else 'refused', flush=True)\n"
            "    sys.stdin.readline()\n",
            str(served),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        with spool.holding(served) as mine:
            assert not mine

        output, code = job.run()

        # Neither read back nor removed, and its session not asked of F1 again.
        assert (job.fetched, job.read_back, code) == ([], [], 0) and "Nothing to fetch" in output
        assert (served / spool.SERVED_NAME).is_file()
    finally:
        holder.stdin.write("\n")
        holder.stdin.close()
        holder.wait(timeout=30)
    with spool.holding(served) as mine:
        assert mine


def test_a_run_holds_one_directory_once(tmp_path):
    directory = left_whole(tmp_path / "spool")

    with spool.holding(directory) as mine, spool.holding(directory) as again:
        assert (mine, again) == (True, False)
        # The second look did not give the first's hold away.
        spool.mark_served(directory)
    with pytest.raises(RuntimeError, match="without its lock being held"):
        spool.mark_served(directory)


def test_marking_a_fetch_as_served_needs_no_room_on_the_disk(tmp_path, monkeypatch):
    """The mark is what keeps a served session from being taken for part of
    one, and it is made when the disk is likeliest to be full. It was a new
    file; a new file can be refused where a rename cannot."""
    with a_fetch_in_hand(tmp_path / "spool") as directory:
        assert (directory / spool.SERVING_NAME).is_file()
        monkeypatch.setattr(Path, "touch", always(OSError(28, "No space left on device")))
        monkeypatch.setattr(Path, "write_text", always(OSError(28, "No space left on device")))

        spool.mark_served(directory, FIRST_FETCH + timedelta(minutes=3))
        # Said again by a later run that reads it back, it does not move.
        spool.mark_served(directory, FIRST_FETCH + timedelta(days=3))

    (left,) = spool.unfinished(tmp_path / "spool")
    assert left.served_at == FIRST_FETCH + timedelta(minutes=3)
    assert not (directory / spool.SERVING_NAME).exists()
    monkeypatch.undo()
    # Without the file that was made for it, it is made afresh.
    with a_fetch_in_hand(tmp_path / "spool", now=FIRST_FETCH + timedelta(hours=1)) as other:
        (other / spool.SERVING_NAME).unlink()
        spool.mark_served(other, FIRST_FETCH + timedelta(hours=2))
    assert [found.served_at for found in spool.unfinished(tmp_path / "spool")][1] == FIRST_FETCH + timedelta(hours=2)


def test_a_fetch_that_could_be_neither_marked_nor_written_down_says_what_becomes_of_it(job, monkeypatch):
    monkeypatch.setattr(cli_module, "mark_served", always(OSError(13, "Access is denied")))

    # Written down all the same, it is whole, and the mark is not missed.
    assert job.run()[1] == 0 and len(list_snapshots(job.store)) == 1

    # The same again with an archive that does not hold the session yet.
    shutil.rmtree(job.store.root / "archive")
    monkeypatch.setattr(cli_module, "keep", always(OSError(28, "No space left on device")))
    output, code = job.run()

    assert code == 1 and "It could not be marked as served either: a later run will take it for a fetch" in output
    assert [left.served for left in spool.unfinished(job.spool)] == [False]


def test_a_directory_is_marked_as_being_removed_before_anything_in_it_goes(tmp_path, monkeypatch):
    directory = left_whole(tmp_path / "spool")
    marked: list[bool] = []
    real_rmtree = spool.shutil.rmtree

    def rmtree(path, **more):
        marked.append((directory / spool.DISCARDED_NAME).is_file())
        raise KeyboardInterrupt("stopped in the middle of removing it")

    monkeypatch.setattr(spool.shutil, "rmtree", rmtree)
    with pytest.raises(KeyboardInterrupt), spool.holding(directory):
        spool.discard(directory)

    assert marked == [True] and isinstance(spool.read(directory), spool.Discarded)
    assert spool.waiting(tmp_path / "spool") == [] and spool.unfinished(tmp_path / "spool") == []
    monkeypatch.setattr(spool.shutil, "rmtree", real_rmtree)
    with spool.holding(directory):
        spool.discard(directory)
    assert list((tmp_path / "spool").iterdir()) == []


def test_a_directory_that_cannot_be_removed_is_said_and_the_run_goes_on(job, monkeypatch):
    left_started(job.spool, 2026, SIXTH, "R", STORE)
    real_discard = cli_module.discard
    monkeypatch.setattr(cli_module, "discard", always(OSError(13, "Access is denied")))

    output, code = job.run()

    assert "could not be removed from the spool: [Errno 13] Access is denied. A later run tries again." in output
    assert "is removed" not in output and (job.fetched, code) == ([EIGHTH], 0)
    monkeypatch.setattr(cli_module, "discard", real_discard)
    assert "a fetch that was stopped before F1 had served the session is removed." in job.run()[0]


# --- R17-2, R17-3: a session F1 served is read back, and nothing else ----------------


class _Feed(BaseHTTPRequestHandler):
    body = b"what F1 served the fetch"

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *arguments) -> None:
        pass


@pytest.fixture
def feed():
    """A host that serves one thing until it is told to serve another, as F1 does when it revises a feed."""
    _Feed.body = b"what F1 served the fetch"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Feed)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/static/WeatherData.jsonStream"
    finally:
        server.shutdown()
        server.server_close()


def test_with_requests_refused_fastf1_answers_from_its_cache_however_old_and_leaves_it(feed, tmp_path):
    """Carrying a fetch on let FastF1 ask again for whatever in its cache of
    responses had gone stale, which is everything after twelve hours. A feed
    F1 had revised meanwhile replaced the one the fetch was served, beside
    parsed feeds that were not replaced."""
    with fastf1_cache(tmp_path / "cache") as fastf1:
        assert fastf1.Cache.requests_get(feed).content == b"what F1 served the fetch"
        fastf1.Cache._requests_session_cached.cache.reset_expiration(timedelta(hours=-1))
    _Feed.body = b"what F1 serves today"

    with fastf1_cache(tmp_path / "cache") as fastf1, HttpRecorder(forbid_all=True) as guard:
        read_back = fastf1.Cache.requests_get(feed).content
    with fastf1_cache(tmp_path / "cache") as fastf1, HttpRecorder(forbid_all=True):
        again = fastf1.Cache.requests_get(feed).content

    assert (read_back, again) == (b"what F1 served the fetch", b"what F1 served the fetch")
    assert guard.forbidden == [feed] and guard.records == []
    # What reading back does not do, and carrying on did.
    with fastf1_cache(tmp_path / "cache") as fastf1:
        assert fastf1.Cache.requests_get(feed).content == b"what F1 serves today"


def reading_back(monkeypatch, tmp_path, archive_path: str = ARCHIVE_PATH):
    """``read_back`` over a stand-in for FastF1 whose load asks F1 for a feed, as FastF1's does."""
    asked: list[object] = []

    def load(**kwargs):
        try:
            requests.Session().get("https://livetiming.invalid/static/2026/TimingData.jsonStream", timeout=5)
        except Exception as exc:
            asked.append(exc)

    loaded = make_race()
    loaded.load = load

    @contextmanager
    def cache(cache_dir):
        yield SimpleNamespace(get_session=lambda year, event, code: loaded)

    monkeypatch.setattr(fetch_module, "fastf1_cache", cache)
    monkeypatch.setattr(fetch_module, "identity_from_fastf1", lambda found: SimpleNamespace(archive_path=archive_path, session_type="R"))
    monkeypatch.setattr(fetch_module, "_versions", lambda module: {})
    monkeypatch.setattr(
        fetch_module, "fetch_extras", lambda module, found, path: {**extras(), WEATHER_SERIES: b"00:00:38.376{}"}
    )
    left = tmp_path / "cache"
    (left / ARCHIVE_PATH).mkdir(parents=True)
    (left / ARCHIVE_PATH / "session_info.ff1pkl").write_bytes(b"what F1 served")
    return left, asked


def test_reading_a_session_back_sends_nothing(monkeypatch, tmp_path):
    left, asked = reading_back(monkeypatch, tmp_path)

    fetched = fetch_module.read_back(2026, 8, "R", left)

    assert [type(error) for error in asked] == [ForbiddenHostError]
    assert fetched.http.forbidden == ["https://livetiming.invalid/static/2026/TimingData.jsonStream"]
    assert (fetched.http.summary(), fetched.feed_status, fetched.attempts) == ({}, {}, 1)


def test_a_session_whose_feeds_the_cache_does_not_hold_is_not_what_is_read_back(monkeypatch, tmp_path):
    """Carrying a fetch on asked the calendar of the day which session the
    round was. After a renumbering that is another race: it was fetched into
    the same cache, archived, and the directory with the first race's feeds
    removed. Read back, a session is found by the calendar the fetch itself
    was served, and has to be the one whose feeds are there."""
    left, _ = reading_back(monkeypatch, tmp_path, archive_path="2026/2026-07-05_British_Grand_Prix/2026-07-05_Race/")

    with pytest.raises(fetch_module.FetchError, match="holds no feeds of it"):
        fetch_module.read_back(2026, 8, "R", left)

    assert (left / ARCHIVE_PATH / "session_info.ff1pkl").read_bytes() == b"what F1 served"


def test_a_fetch_is_archived_as_made_when_it_ended_whichever_run_writes_it_down(job, monkeypatch):
    """A fetch written down by the run that made it was stamped with when it
    ended, and one finished by a later run with when it started."""
    ended: list[object] = []
    real_mark = spool.mark_served

    def mark(directory, at=None):
        ended.append(at)
        real_mark(directory, at)

    monkeypatch.setattr(cli_module, "mark_served", mark)
    job.run()
    (by_its_own_run,) = list_snapshots(job.store)

    assert by_its_own_run.fetched_at == ended[0].strftime(STAMP)
    served = left_served(job.spool, 2026, EIGHTH, "R", STORE, served_at=FIRST_FETCH + timedelta(minutes=7))
    assert [left.served_at for left in spool.unfinished(job.spool)] == [FIRST_FETCH + timedelta(minutes=7)]
    job.run()

    assert not served.exists()
    assert (FIRST_FETCH + timedelta(minutes=7)).strftime(STAMP) in {
        found.fetched_at for found in list_snapshots(job.store)
    }


# --- R17-4: the build has its turn, and the stage's time is asked before everything ---


def stages(job, monkeypatch, fetch=lambda args: (0, 0), build=lambda args: 0) -> list[str]:
    ran: list[str] = []
    monkeypatch.setattr(cli_module, "_fetch_due", lambda args: (ran.append("fetch"), fetch(args))[1])
    monkeypatch.setattr(cli_module, "run_build", lambda args: (ran.append("build"), build(args))[1])
    return ran


def test_a_run_builds_before_it_asks_anything_of_f1_and_again_if_it_fetched(job, monkeypatch):
    """The build came second. Whatever kept the fetch stage past the two
    hours a run is allowed, on every run, kept the build from ever running:
    reading sessions back, uploads, and questions to Jolpica were all outside
    the stage's own limit."""
    ran = stages(job, monkeypatch)
    assert job.run("run", "--store", "x")[1] == 0 and ran == ["build", "fetch"]

    ran = stages(job, monkeypatch, fetch=lambda args: (0, 2))
    assert job.run("run", "--store", "x")[1] == 0 and ran == ["build", "fetch", "build"]

    ran = stages(job, monkeypatch, fetch=always(RuntimeError("the fetch stage broke")))
    output, code = job.run("run", "--store", "x")
    assert ran == ["build", "fetch", "build"] and code == 1 and "The fetch stage stopped: RuntimeError" in output

    ran = stages(job, monkeypatch, build=always(RuntimeError("the build broke")))
    output, code = job.run("run", "--store", "x")
    assert ran == ["build", "fetch"] and code == 1 and "The build stopped: RuntimeError" in output
    assert "] run finished, exit 1, " in output.splitlines()[-1]


def test_nothing_is_started_once_the_fetch_stage_has_had_its_time(three_races, monkeypatch):
    whole = left_whole(three_races.spool, 2026, EIGHTH, "R", STORE)
    served = left_served(three_races.spool, 2026, SEVENTH, "R", STORE, now=FIRST_FETCH + timedelta(hours=1))
    asked: list[int] = []
    monkeypatch.setattr(cli_module, "fetch_classified_laps", lambda fastf1, year, round_number, *rest: asked.append(round_number))
    monkeypatch.setattr(cli_module, "plan_fetches", lambda schedule, snapshots, now, classified, **more: [
        classified(entry) for entry in schedule
    ] and [])

    output, code = three_races.run("fetch-due", "--store", "x", "--season", "2026", "--budget-minutes", "0")

    assert output.count("fetched earlier, and left in the spool: the fetch stage's time is up.") == 2
    assert (three_races.fetched, three_races.read_back, asked, code) == ([], [], [], 1)
    assert (whole / spool.PENDING_NAME).is_file() and (served / spool.SERVED_NAME).is_file()


@pytest.mark.parametrize(
    ("answer", "asked", "said"),
    [
        (ClassificationUnavailable("Jolpica timed out"), 2, True),
        # It answered, and has no result: that is an answer.
        (ClassificationMissing("no result yet"), 3, False),
    ],
)
def test_jolpica_not_answering_is_not_asked_about_every_session_in_turn(three_races, monkeypatch, answer, asked, said):
    """Twenty sessions to judge, and three tries of two minutes each for
    every one of them, is longer than a run is allowed."""
    calls: list[int] = []

    def classified(fastf1, year, round_number, *rest):
        calls.append(round_number)
        raise answer

    monkeypatch.setattr(cli_module, "fetch_classified_laps", classified)
    monkeypatch.setattr(cli_module, "plan_fetches", lambda schedule, snapshots, now, classified, **more: [
        classified(entry) for entry in schedule
    ] and [])

    output, _ = three_races.run()

    assert len(calls) == asked and ("Jolpica did not answer 2 times running." in output) is said


def test_a_build_does_not_ask_jolpica_about_every_session_once_it_has_stopped_answering(tmp_path, monkeypatch):
    """The build is first in a run, and waits on Jolpica for every session
    that is not settled: all of them, after a change of pipeline version."""
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path)
    asked: list[int] = []
    answer: list[Exception | None] = [ClassificationUnavailable("Jolpica did not answer after 3 attempts")]

    def classification(fastf1, year, round_number, session_type):
        asked.append(round_number)
        if answer[0] is not None:
            raise answer[0]
        return Archive.fetch_classification(world, fastf1, year, round_number, session_type)

    monkeypatch.setattr(build_module, "fetch_classification", classification)
    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)

    held = [builder.gather(AUSTRIA) for _ in range(4)]

    assert len(asked) == 2 and all(isinstance(hold, Hold) for hold in held)
    assert [hold.reason for hold in held[2:]] == ["Jolpica is not answering, and is not asked again until the next run"] * 2
    # The next run asks again. And an answer that there is no result is an answer.
    again = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)
    answer[0] = ClassificationMissing("Jolpica has no classification for 2026 round 8")
    for _ in range(3):
        again.gather(AUSTRIA)
    assert len(asked) == 5


# --- R17-5: the note of a session's fetches says the same whoever wrote first --------

ENTRY = (2026, "R", "2026-05-03T13:00:00Z")
KEY = layout.attempt_key(*ENTRY)
SOON = timedelta(minutes=5)


def count(store, after: timedelta = timedelta(days=1)) -> tuple[int, str]:
    return failing_fetches(store, FIRST_FETCH + after).get(KEY, (0, ""))


def test_two_fetches_that_fail_are_two_failures_in_whichever_order_they_are_noted():
    """A starts, B starts, B fails, A fails. One record held the last start
    only: B's failure cleared it, A could not tell that its own start had
    been counted, and two fetches made three failures."""
    events = ["start A", "start B", "fail A", "fail B"]
    orders = [
        order
        for order in itertools.permutations(events)
        if order.index("start A") < order.index("fail A") and order.index("start B") < order.index("fail B")
    ]
    assert len(orders) == 6

    for order in orders:
        store, names = MemoryStore(), {}
        for second, event in enumerate(order):
            what, who = event.split()
            at = FIRST_FETCH + timedelta(seconds=second)
            if what == "start":
                names[who] = note_fetch_started(store, *ENTRY, at)
            else:
                note_failed_fetch(store, *ENTRY, f"FetchError: {who}", at, names[who])
        assert count(store) == (2, f"FetchError: {order[-1].split()[1]}"), order
        # And each has ended once: saying so again changes nothing.
        note_failed_fetch(store, *ENTRY, "FetchError: again", FIRST_FETCH + timedelta(minutes=1), names["A"])
        assert count(store)[0] == 2


def test_a_fetch_seen_through_by_a_later_run_is_the_fetch_that_was_begun(job, monkeypatch):
    """A's run is stopped as it writes the session down. A later run sees the
    fetch through and notes that it succeeded, with no name: the note took
    A's start for another fetch still going, and went on saying interrupted
    of a session that was in the archive."""
    monkeypatch.setattr(cli_module, "keep", always(KeyboardInterrupt("the scheduler stopped the task")))
    assert job.run()[1] == "killed"
    (left,) = spool.unfinished(job.spool)
    assert left.served and left.attempt is not None
    assert list(failing_fetches(job.store, NOW()).values()) == [(1, INTERRUPTED)]

    monkeypatch.setattr(cli_module, "keep", spool.keep)
    assert job.run()[1] == 0

    assert failing_fetches(job.store, NOW()) == {} and failed_fetches(job.store, NOW()) == {}
    (noted,) = json.loads(job.store.get(layout.attempt_key(2026, "R", AUSTRIA_ENTRY.start_time_utc)).data)["attempts"].items()
    assert noted[0] == left.attempt and noted[1]["outcome"] == "succeeded"


def test_a_fetch_that_never_ended_is_still_in_the_note_after_another_succeeded():
    """A starts, B starts, B succeeds, A's run is stopped. B's success
    replaced the record, and nothing said A had ever started."""
    store = MemoryStore()
    a = note_fetch_started(store, *ENTRY, FIRST_FETCH)
    b = note_fetch_started(store, *ENTRY, FIRST_FETCH + timedelta(seconds=1))
    note_fetch_succeeded(store, *ENTRY, FIRST_FETCH + timedelta(seconds=2), b)

    attempts = json.loads(store.get(KEY).data)["attempts"]
    assert attempts[b]["outcome"] == "succeeded" and "outcome" not in attempts[a]
    # For as long as A could still be going it is one fetch that has not succeeded.
    assert count(store, after=SOON) == (1, INTERRUPTED)
    # After that it was cut short when it started, which was before the session was fetched.
    assert count(store, after=A_FETCH_IS_OVER_AFTER + SOON) == (0, "")
    # If it does end, late, that is what it is.
    note_failed_fetch(store, *ENTRY, "FetchError: A, in the end", FIRST_FETCH + timedelta(hours=1), a)
    assert count(store) == (1, "FetchError: A, in the end")


def test_a_note_keeps_its_latest_fetches_and_reads_one_written_before_it_listed_them():
    store = MemoryStore()
    for hour in range(20):
        note_failed_fetch(store, *ENTRY, f"FetchError: {hour}", FIRST_FETCH + timedelta(hours=hour))
    assert len(json.loads(store.get(KEY).data)["attempts"]) == 12 and count(store) == (12, "FetchError: 19")
    note_fetch_succeeded(store, *ENTRY, FIRST_FETCH + timedelta(hours=20))
    assert count(store) == (0, "")

    at = FIRST_FETCH.strftime(STAMP)
    before = MemoryStore()
    before.put(KEY, dump_json({"failed_at": at, "error": "FetchError: old", "failures": 2, "attempt": None}))
    assert count(before) == (1, "FetchError: old")
    # A word stamped with a time that has not come is not counted.
    assert failing_fetches(before, FIRST_FETCH - timedelta(days=1)) == {}
    going = MemoryStore()
    going.put(KEY, dump_json({"failed_at": at, "error": INTERRUPTED, "failures": 1, "attempt": "0badcafe"}))
    assert count(going) == (1, INTERRUPTED)
    note_fetch_succeeded(going, *ENTRY, FIRST_FETCH + timedelta(days=200), "0badcafe")
    assert count(going, after=timedelta(days=201)) == (0, "")
    unreadable = MemoryStore()
    unreadable.put(KEY, b"not json")
    assert count(unreadable) == (0, "") and failed_fetches(unreadable, FIRST_FETCH) == {}


# --- R17-6: a bucket is one account's ------------------------------------------------


def test_a_fetch_made_for_one_accounts_bucket_is_not_another_accounts_of_the_same_name(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "formula-1-data-artifacts")
    monkeypatch.setenv("R2_ACCOUNT_ID", "one-account")
    one = cli_module._store_name("r2")
    monkeypatch.setenv("R2_ACCOUNT_ID", "another-account")
    other = cli_module._store_name(" R2")

    assert one == "r2:one-account/formula-1-data-artifacts" and other != one
    monkeypatch.delenv("R2_ACCOUNT_ID")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "one-account")
    assert cli_module._store_name("r2") == one


# --- R17-7: a marker in the way is this upload's only with its parts ------------------


def test_a_marker_without_its_parts_is_not_an_upload_that_finished(tmp_path):
    """A marker that read as a snapshot's was taken for the upload having
    finished, and the copy in the spool removed. Whether the parts it named
    were in the archive was not looked at."""
    store = MemoryStore()
    directory = left_whole(tmp_path / "spool")
    (spooled,) = spool.waiting(tmp_path / "spool")
    prefix = layout.snapshot_prefix(AUSTRIA, SNAPSHOT_ID)
    with spool.holding(tmp_path / "elsewhere"):
        write_snapshot(store, spooled.fetched, now=spooled.fetched_at, snapshot_id=SNAPSHOT_ID)
    parts = {item.key: store.get(item.key).data for item in store.list(prefix)}

    def archive() -> None:
        with spool.holding(directory):
            cli_module._archive(store, spooled)

    del store._objects[f"{prefix}http-cache.sqlite.gz"]
    with pytest.raises(ArchiveError, match="http-cache.sqlite.gz is not in the archive"):
        archive()
    store._objects[f"{prefix}http-cache.sqlite.gz"] = b"cut short"
    with pytest.raises(ArchiveError, match="http-cache.sqlite.gz is 9 bytes in the archive"):
        archive()
    store._objects.update(parts)
    marker = json.loads(parts[f"{prefix}{layout.SNAPSHOT_MARKER}"])
    store._objects[f"{prefix}{layout.SNAPSHOT_MARKER}"] = dump_json({**marker, "fetched_at": "2026-06-29T00:00:00Z"})
    with pytest.raises(ArchiveError, match="it describes another fetch"):
        archive()
    assert (directory / spool.PENDING_NAME).is_file()

    # All of it there, as its own upload left it: taken for finished, and the copy removed.
    store._objects.update(parts)
    archive()
    assert not directory.exists() and len(list_snapshots(store)) == 1


# --- R17-8: no fetch is started without room, by any command -------------------------


def test_the_fetch_command_starts_no_fetch_without_room_either(job, monkeypatch):
    monkeypatch.setattr(cli_module, "free_bytes", lambda root: 10 * 1024**2)

    output, code = job.run("fetch", "--store", "x", "--year", "2026", "--event", str(EIGHTH), "--session", "R")

    assert code == 1 and "NOT FETCHED: 10 MB free where the spool is" in output
    assert job.fetched == [] and spool.directories(job.spool) == []
    # And a fetch that was not started is not noted as one that was.
    job.run()
    assert job.fetched == [] and failed_fetches(job.store, NOW()) == {}


# --- what the guide said that the code did not do ------------------------------------


def test_every_fetch_left_for_another_store_is_counted_whole_or_not(job):
    left_served(job.spool, 2026, SIXTH, "R", "r2:an-account/another-bucket")

    output, code = job.run()

    assert "1 fetch(es) in the spool are for another store, and are left for it." in output and code == 0


def test_a_session_that_could_not_be_read_back_makes_the_run_fail(job):
    """A run in which seeing the spool through failed, and nothing after it
    did, ended with exit 0."""
    left_served(job.spool, 2026, EIGHTH, "R", STORE, start_time_utc=AUSTRIA_ENTRY.start_time_utc)
    job.cannot_be_read_back = {EIGHTH}

    output, code = job.run()

    assert code == 1 and "Nothing to fetch" in output
    left_started(job.spool, 2026, SIXTH, "R", STORE, now=FIRST_FETCH + timedelta(hours=1))
    assert job.run()[1] == 1 and [left.served for left in spool.unfinished(job.spool)] == [True]
