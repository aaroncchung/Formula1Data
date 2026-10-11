"""The cases the thirty-fifth review of this code found (a comment on pull request 11, 2026-10-11, at 6c82ca7).

Three findings, none of them about what a build makes of feeds that are
sound. Two are about knowing that the job that fetches is working: the check
that asks when it last ran passed for a job that had never run, since it was
told to, and passed for one that ran on time and failed every time, since it
read when a run ended and not how. The third is the one thing these rounds
had written down as known and not built: a feed that arrives on time and
repeats itself meets every bar, and the session is published as whole, or as
partial for something else.

How many laps repeat themselves in a real race was counted from FastF1's own
tables for the nine races of 2026 from Australia to Britain. The share of
samples that repeat comes to what the earlier rounds counted from F1's raw
feed: 14.3% of the Chinese GP and 12.8% of the Japanese.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from f1data import cli as cli_module
from f1data import layout, normalize
from f1data.archive import dump_json, list_snapshots, write_snapshot
from f1data.build import Builder
from f1data.coverage import (
    CAR_REPEATS_BAR,
    POSITION_REPEATS_BAR,
    apply_classification,
    evaluate_coverage,
    is_measurement,
    refetch_could_help,
)
from f1data.policy import THE_JOB_IS_FAILING_AFTER_RUNS
from f1data.publish import publish_session, read_pointer
from tests.building import Archive
from tests.fakes import LAP_SECONDS, RACE_START, make_session, measure
from tests.test_archive import fetched_session
from tests.test_fifteenth_review import job  # noqa: F401  (a fixture)
from tests.test_fifth_review import WINDOW_CLOSED, correction
from tests.test_publish import AUSTRIA

EVERYONE = {"1": 10, "2": 10, "3": 10}
WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish.yml"


# --- 1: a job that has never run is not a job that is running ---------------------


def test_the_hosted_check_does_not_let_a_job_that_never_ran_pass_unless_it_is_told_to():
    """It ran `last-run --allow-never` on every schedule, for good. A fetch
    job that was never installed has never run, and the workflow stayed green
    while no race was fetched."""
    text = WORKFLOW.read_text(encoding="utf-8")
    step = text[text.index("- name: Check that the fetch job is running"):text.index("- name: Summarise")]

    assert "python -m f1data last-run" in step
    # Only inside the branch a repository variable opens, which says so each time.
    before, _, inside = step.partition('if [ "$NOT_YET_RUN" = "true" ]; then')
    assert "--allow-never" not in before and "NOT_YET_RUN: ${{ vars.F1DATA_FETCH_JOB_NOT_YET_RUN }}" in before
    opened, _, after = inside.partition("fi\n")
    assert "--allow-never" in opened and "::warning" in opened and "--allow-never" not in after


def test_a_job_that_has_never_run_fails_the_check_and_being_let_pass_is_said(job):
    output, code = job.run("last-run", "--store", "x")
    assert code == 1 and "No run of the whole job has been written down" in output

    output, code = job.run("last-run", "--store", "x", "--allow-never")
    assert code == 0 and "A job that was never installed looks the same." in output


# --- 2: a job that runs and fails is not working either ---------------------------


def run_the_job(job, monkeypatch, built: int):
    monkeypatch.setattr(cli_module, "run_build", lambda args: built)
    return job.run("run", "--store", "x", "--season", "2026")[1]


def record_of(job) -> dict:
    return json.loads(job.store.get(layout.LAST_RUN_KEY).data)


def test_one_failed_run_is_said_and_two_running_fail_the_check(job, monkeypatch):
    """The check read when the last run finished and printed how. A job
    failing every six hours had finished minutes ago, every time."""
    assert THE_JOB_IS_FAILING_AFTER_RUNS == 2

    assert run_the_job(job, monkeypatch, built=1) == 1
    assert (record_of(job)["exit_code"], record_of(job)["failed_runs"]) == (1, 1)
    output, code = job.run("last-run", "--store", "x")
    assert code == 0 and "with exit code 1." in output
    assert "DEGRADED: that run failed." in output and "FAILING" not in output

    assert run_the_job(job, monkeypatch, built=1) == 1
    assert record_of(job)["failed_runs"] == 2
    output, code = job.run("last-run", "--store", "x")
    assert code == 1 and "FAILING: the last 2 run(s) failed, one after another." in output

    # A run that works is a job that works, whatever came before it.
    assert run_the_job(job, monkeypatch, built=0) == 0
    assert (record_of(job)["exit_code"], record_of(job)["failed_runs"]) == (0, 0)
    output, code = job.run("last-run", "--store", "x")
    assert code == 0 and "DEGRADED" not in output and "FAILING" not in output

    # And the count starts again from one.
    assert run_the_job(job, monkeypatch, built=1) == 1
    assert record_of(job)["failed_runs"] == 1


def test_a_check_can_be_told_that_one_failed_run_is_one_too_many(job, monkeypatch):
    run_the_job(job, monkeypatch, built=1)

    output, code = job.run("last-run", "--store", "x", "--max-failed-runs", "1")

    assert code == 1 and "FAILING: the last 1 run(s) failed" in output


def test_a_job_that_fails_and_has_also_stopped_is_said_to_have_stopped(job, monkeypatch):
    run_the_job(job, monkeypatch, built=1)
    run_the_job(job, monkeypatch, built=1)
    stale = (datetime.now(timezone.utc) - timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    job.store.put(layout.LAST_RUN_KEY, dump_json({**record_of(job), "finished_at": stale}))

    output, code = job.run("last-run", "--store", "x")

    assert code == 1 and "the job is not running" in output


def test_a_record_from_before_failures_were_counted_is_one_failure_and_the_count_goes_on_from_it(job, monkeypatch):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    older = {"started_at": now, "finished_at": now, "exit_code": 1, "host": "home"}
    job.store.put(layout.LAST_RUN_KEY, dump_json(older))

    output, code = job.run("last-run", "--store", "x")
    assert code == 0 and "DEGRADED" in output

    run_the_job(job, monkeypatch, built=1)
    assert record_of(job)["failed_runs"] == 2
    assert job.run("last-run", "--store", "x")[1] == 1


@pytest.mark.parametrize("exit_code", [None, "0", True, 1.0])
def test_a_record_that_does_not_say_how_its_run_ended_vouches_for_nothing(job, exit_code):
    """Its exit code was printed and not read: a record with none passed."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {"started_at": now, "finished_at": now, "host": "home"}
    job.store.put(layout.LAST_RUN_KEY, dump_json(record if exit_code is None else {**record, "exit_code": exit_code}))

    output, code = job.run("last-run", "--store", "x")

    assert code == 1 and "The record of the last run cannot be read" in output


def test_a_record_that_cannot_be_read_does_not_stop_the_next_run_being_written_down(job, monkeypatch):
    job.store.put(layout.LAST_RUN_KEY, b"not json")

    assert run_the_job(job, monkeypatch, built=1) == 1

    assert (record_of(job)["exit_code"], record_of(job)["failed_runs"]) == (1, 1)


# --- 3: a feed that repeats itself arrived, and says nothing ----------------------


def lap_rows(telemetry, lap: int, share: float = 1.0):
    """The rows of a fake feed in the first ``share`` of a lap, counted from 1."""
    seconds = telemetry["SessionTime"].dt.total_seconds()
    start = RACE_START + (lap - 1) * LAP_SECONDS
    return (seconds >= start) & (seconds < start + share * LAP_SECONDS)


def car_feed_repeats(session, number: str, laps, share: float = 1.0) -> None:
    """The car feed sends the sample it last had, with the car going on round: Hungary, from lap 7."""
    car = session.car_data[number]
    for lap in laps:
        rows = lap_rows(car, lap, share)
        held = car.loc[rows].iloc[0]
        car.loc[rows, ["Speed", "RPM"]] = [held["Speed"], held["RPM"]]


def position_feed_repeats(session, number: str, laps, share: float = 1.0) -> None:
    position = session.pos_data[number]
    for lap in laps:
        rows = lap_rows(position, lap, share)
        held = position.loc[rows].iloc[0]
        position.loc[rows, ["X", "Y"]] = [held["X"], held["Y"]]


def shortfalls(measurement) -> set[tuple[str, str | None]]:
    return {(item.bar, item.driver) for item in evaluate_coverage(measurement)}


def test_a_car_feed_that_repeats_itself_meets_every_other_bar_and_not_this_one():
    """The samples come a quarter of a second apart, as they should, so every
    lap is "usable" and the session was complete."""
    session = make_session()
    car_feed_repeats(session, "1", laps=range(3, 11))

    measurement = measure(session)

    driver = measurement["drivers"]["AAA"]
    assert (driver["car_laps"], driver["car_repeating_laps"], driver["position_repeating_laps"]) == (10, 8, 0)
    assert measurement["drivers"]["BBB"]["car_repeating_laps"] == 0
    assert shortfalls(measurement) == {(CAR_REPEATS_BAR, "AAA")}
    (short,) = evaluate_coverage(measurement)
    assert short.detail == (
        "F1's car feed repeats itself on 8 of 10 expected laps, whose speed, pedals and gear cannot be relied on"
    )


def test_a_position_feed_that_repeats_itself_is_counted_apart():
    """Hadjar's lap 4 of the 2026 Miami GP: the car feed goes on and the position feed does not."""
    session = make_session()
    position_feed_repeats(session, "2", laps=[4])

    measurement = measure(session)

    driver = measurement["drivers"]["BBB"]
    assert (driver["position_laps"], driver["car_repeating_laps"], driver["position_repeating_laps"]) == (10, 0, 1)
    assert shortfalls(measurement) == {(POSITION_REPEATS_BAR, "BBB")}
    (short,) = evaluate_coverage(measurement)
    assert "F1's position feed repeats itself on 1 of 10 expected laps" in short.detail


@pytest.mark.parametrize(("share", "repeating"), [(0.2, 0), (0.3, 1)])
def test_a_lap_repeats_itself_when_more_than_a_quarter_of_it_does(share, repeating):
    session = make_session()
    car_feed_repeats(session, "1", laps=[5], share=share)

    assert measure(session)["drivers"]["AAA"]["car_repeating_laps"] == repeating


def test_a_car_that_is_standing_still_repeats_itself_truthfully():
    """A lap waited out in the pit lane under a red flag: every sample is the
    one before, and every one of them is right."""
    session = make_session()
    for feed in (session.car_data, session.pos_data):
        feed["1"] = feed["1"].copy()
    car, position = session.car_data["1"], session.pos_data["1"]
    car.loc[lap_rows(car, 6), ["Speed", "RPM"]] = [0.0, 4000.0]
    position_feed_repeats(session, "1", laps=[6])

    measurement = measure(session)

    driver = measurement["drivers"]["AAA"]
    assert (driver["car_repeating_laps"], driver["position_repeating_laps"]) == (0, 0)
    assert evaluate_coverage(measurement) == []


def test_as_many_laps_may_repeat_themselves_as_may_be_missing():
    """Two laps in forty may have no car data at all, and the same two may repeat."""
    within = make_session(laps_per_driver=40)
    car_feed_repeats(within, "1", laps=[7, 8])
    beyond = make_session(laps_per_driver=40)
    car_feed_repeats(beyond, "1", laps=[7, 8, 9])

    assert measure(within)["drivers"]["AAA"]["car_repeating_laps"] == 2
    assert evaluate_coverage(measure(within)) == []
    assert shortfalls(measure(beyond)) == {(CAR_REPEATS_BAR, "AAA")}


def before_repeats_were_counted(measurement: dict) -> dict:
    """A measurement as a fetch recorded it before this round."""
    return {
        **measurement,
        "drivers": {
            code: {
                key: value
                for key, value in driver.items()
                if key not in ("car_repeating_laps", "position_repeating_laps")
            }
            for code, driver in measurement["drivers"].items()
        },
    }


def test_a_record_from_before_repeats_were_counted_can_be_read_and_says_nothing_of_them():
    session = make_session()
    car_feed_repeats(session, "1", laps=range(3, 11))
    older = before_repeats_were_counted(measure(session))

    assert is_measurement(older) and evaluate_coverage(older) == []
    # A driver known from the result alone has no laps that could repeat.
    judged = apply_classification(older, {"1": 10, "2": 10, "3": 10, "4": 10})
    assert (judged["drivers"]["#4"]["car_repeating_laps"], judged["drivers"]["#4"]["position_repeating_laps"]) == (0, 0)


def test_a_feed_that_repeats_itself_is_asked_for_again_like_any_other_that_arrived_short():
    """F1 does repair its archive, and nothing here can tell that it will not."""
    session = make_session()
    car_feed_repeats(session, "1", laps=range(3, 11))

    assert refetch_could_help(evaluate_coverage(measure(session)))


def test_what_is_published_gives_the_count_and_nothing_where_there_is_none():
    session = make_session()
    car_feed_repeats(session, "1", laps=range(3, 11))
    measurement = apply_classification(measure(session), EVERYONE)

    published = json.loads(normalize.coverage(measurement).model_dump_json())
    older = json.loads(normalize.coverage(before_repeats_were_counted(measurement)).model_dump_json())

    assert published["complete"] is False
    assert [(item["bar"], item["driver"]) for item in published["shortfalls"]] == [("car_data_repeats", "AAA")]
    assert [(d["car_repeating_laps"], d["position_repeating_laps"]) for d in published["drivers"]] == [
        (8, 0), (0, 0), (0, 0),
    ]
    assert older["complete"] is True
    assert {(d["car_repeating_laps"], d["position_repeating_laps"]) for d in older["drivers"]} == {(None, None)}


def test_a_session_archived_before_repeats_were_counted_is_counted_by_the_build_and_published_as_partial(
    tmp_path, monkeypatch
):
    """Every session in the archive was fetched before this round, and none
    is fetched again for it: the feeds are there to be counted. A build
    counts them once it has loaded them, writes the count beside the
    snapshot, and decides again with it."""
    world = Archive(monkeypatch, EVERYONE)
    session = make_session()
    car_feed_repeats(session, "1", laps=range(3, 11))
    fetched = fetched_session(tmp_path, session)
    written = write_snapshot(
        world.store, replace(fetched, coverage=before_repeats_were_counted(fetched.coverage)), now=WINDOW_CLOSED
    )
    world.feeds[written.snapshot_id] = session
    (listed,) = list_snapshots(world.store)
    assert listed.complete and listed.measured_in_full

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED + timedelta(days=3))
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    pointer = read_pointer(world.store, AUSTRIA)[0]
    assert pointer.complete is False
    assert [(item["bar"], item["driver"]) for item in pointer.shortfalls] == [(CAR_REPEATS_BAR, "AAA")]
    corrected = correction(world.store, written)
    assert corrected["pipeline_version"] == layout.PIPELINE_VERSION
    assert corrected["coverage"]["drivers"]["AAA"]["car_repeating_laps"] == 8
    (listed,) = list_snapshots(world.store)
    assert not listed.complete


def test_a_whole_session_archived_before_repeats_were_counted_is_published_as_whole(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    session = make_session()
    fetched = fetched_session(tmp_path, session)
    written = write_snapshot(
        world.store, replace(fetched, coverage=before_repeats_were_counted(fetched.coverage)), now=WINDOW_CLOSED
    )
    world.feeds[written.snapshot_id] = session

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED + timedelta(days=3))
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published" and read_pointer(world.store, AUSTRIA)[0].complete is True
    assert correction(world.store, written)["coverage"]["drivers"]["AAA"]["car_repeating_laps"] == 0
