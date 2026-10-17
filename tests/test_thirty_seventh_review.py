"""The case the thirty-seventh review of this code found (a comment on pull request 11, 2026-10-12, at 6048bf0).

One finding, of the second rank, in what round thirty-five added. A run
writes down how it ended and how many runs have failed one after another,
counting from the record it read, and wrote that over whatever was there. Two
runs that ended together, the schedule's and one started by hand, both read
the same record: both failed, each wrote "one", and the check on the fetch
job saw one failure where there were two. A run that ended first and wrote
last also put its own times and exit code over those of the run after it.

The record is now written only over the one that was read, and a run that
loses reads again. The record stays that of the run that ended last.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from f1data import cli as cli_module
from f1data import layout
from f1data.archive import dump_json
from f1data.policy import THE_JOB_IS_FAILING_AFTER_RUNS
from tests.test_fifteenth_review import job  # noqa: F401  (a fixture)
from tests.test_thirty_fifth_review import record_of, run_the_job
from tests.test_thirty_sixth_review import write_down


class Interleaved:
    """A store in which something else happens between a run reading the record and writing it."""

    def __init__(self, store) -> None:
        self._store = store
        self.between: list = []
        self.every_time = None
        self.reads = 0
        self._busy = False

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def get(self, key: str):
        found = self._store.get(key)
        if key == layout.LAST_RUN_KEY and not self._busy:
            self.reads += 1
            other = self.between.pop(0) if self.between else self.every_time
            if other is not None:
                self._busy = True
                try:
                    other()
                finally:
                    self._busy = False
        return found


@pytest.fixture
def overlapping(job):  # noqa: F811
    job.store = Interleaved(job.store)
    return job


def stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def another_run_ends(at: datetime, status: int):
    return lambda: cli_module._note_the_run("x", at - timedelta(minutes=30), at, status)


@pytest.mark.parametrize("to_begin_with", ["nothing", "a run that worked"])
def test_two_runs_that_fail_together_are_two_failures(overlapping, monkeypatch, to_begin_with):
    """Both read a record of no failures and each wrote "one": the second
    write was over the first, whatever it said."""
    assert THE_JOB_IS_FAILING_AFTER_RUNS == 2
    if to_begin_with != "nothing":
        write_down(overlapping, datetime.now(timezone.utc) - timedelta(hours=6))
    overlapping.store.between = [another_run_ends(datetime.now(timezone.utc) - timedelta(seconds=30), 1)]

    assert run_the_job(overlapping, monkeypatch, built=1) == 1

    # Read once, lost the write, and read again.
    assert overlapping.store.reads == 2
    assert (record_of(overlapping)["exit_code"], record_of(overlapping)["failed_runs"]) == (1, 2)
    output, code = overlapping.run("last-run", "--store", "x")
    assert code == 1 and "FAILING: the last 2 run(s) failed, one after another." in output


@pytest.mark.parametrize(
    ("earlier", "later", "failed_runs"),
    [(1, 1, 2), (1, 0, 0), (0, 1, 1), (0, 0, 0)],
)
def test_a_run_that_ended_first_and_writes_last_leaves_the_later_run_written_down(job, earlier, later, failed_runs):  # noqa: F811
    """The record is of the run that ended last, and `last-run` reads when
    that was. The earlier run's failure is one more in a row with a failure
    after it, and nothing to a success after it."""
    now = datetime.now(timezone.utc)
    cli_module._note_the_run("x", now - timedelta(hours=1), now - timedelta(minutes=10), later)
    written = record_of(job)

    cli_module._note_the_run("x", now - timedelta(hours=2), now - timedelta(minutes=20), earlier)

    # The record also names the runs it has counted (tests/test_pr_review_ops.py).
    rest = {name: value for name, value in record_of(job).items() if name != "counted"}
    assert rest == {**written, "failed_runs": failed_runs}
    assert (record_of(job)["finished_at"], record_of(job)["exit_code"]) == (stamp(now - timedelta(minutes=10)), later)


def test_a_run_that_ended_first_loses_the_write_to_the_one_that_ended_after_it(overlapping):
    """It read the record before the later run wrote, so by what it read it
    was the last to end."""
    now = datetime.now(timezone.utc)
    write_down(overlapping, now - timedelta(hours=6))
    overlapping.store.between = [another_run_ends(now - timedelta(minutes=10), 1)]

    cli_module._note_the_run("x", now - timedelta(hours=2), now - timedelta(minutes=20), 1)

    record = record_of(overlapping)
    assert (record["finished_at"], record["exit_code"], record["failed_runs"]) == (stamp(now - timedelta(minutes=10)), 1, 2)


def test_a_run_that_worked_and_lost_the_write_is_written_down_all_the_same(overlapping, monkeypatch):
    overlapping.store.between = [another_run_ends(datetime.now(timezone.utc) - timedelta(minutes=5), 1)]

    assert run_the_job(overlapping, monkeypatch, built=0) == 0

    assert (record_of(overlapping)["exit_code"], record_of(overlapping)["failed_runs"]) == (0, 0)
    assert overlapping.run("last-run", "--store", "x")[1] == 0


def test_a_record_stamped_by_a_clock_that_was_wrong_is_not_a_later_run(job, monkeypatch):  # noqa: F811
    """A record a day ahead ended after every run until the day comes round.
    Left standing as the later run, no run would be written down till then."""
    write_down(job, datetime.now(timezone.utc) + timedelta(days=1))
    assert job.run("last-run", "--store", "x")[1] == 1

    assert run_the_job(job, monkeypatch, built=0) == 0

    output, code = job.run("last-run", "--store", "x")
    assert code == 0 and "0.0 hours ago, with exit code 0." in output


def test_a_run_that_loses_the_write_every_time_says_so_and_ends_as_it_would_have(overlapping, monkeypatch):
    turns = iter(range(100))

    def something_else_writes() -> None:
        overlapping.store.put(layout.LAST_RUN_KEY, dump_json({"turn": next(turns)}))

    overlapping.store.every_time = something_else_writes

    assert run_the_job(overlapping, monkeypatch, built=0) == 0

    assert overlapping.store.reads == cli_module.NOTE_ATTEMPTS
    assert record_of(overlapping) == {"turn": cli_module.NOTE_ATTEMPTS - 1}


def test_losing_the_write_every_time_is_printed(overlapping, monkeypatch):
    overlapping.store.every_time = lambda: overlapping.store.put(
        layout.LAST_RUN_KEY, dump_json({"at": overlapping.store.reads})
    )
    monkeypatch.setattr(cli_module, "run_build", lambda args: 0)

    output, code = overlapping.run("run", "--store", "x", "--season", "2026")

    assert code == 0
    assert f"Could not write down that the run ended: another run wrote its own, {cli_module.NOTE_ATTEMPTS} times running." in output
