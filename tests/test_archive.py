"""The source archive: snapshots are written once, selected by a fixed order,
and restored as a FastF1 cache (docs/architecture-review-findings.md, section 6,
rules 4 and 6).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from f1data import layout
from f1data.archive import (
    HTTP_ARCHIVE,
    PARSED_ARCHIVE,
    ArchiveError,
    Snapshot,
    list_snapshots,
    restore_snapshot,
    select_snapshot,
    write_snapshot,
)
from f1data.cli import main
from f1data.coverage import measure_coverage
from f1data.fetch import HTTP_CACHE_FILE, FetchedSession
from f1data.httplog import HttpRecorder
from f1data.store import DirectoryStore, MemoryStore
from tests.fakes import LAP_SECONDS, RACE_START, make_session
from tests.test_publish import AUSTRIA, identity, snapshot

ARCHIVE_PATH = "2026/2026-06-28_Austrian_Grand_Prix/2026-06-28_Race/"


def fetched_session(tmp_path: Path, session=None) -> FetchedSession:
    cache_dir = tmp_path / "cache"
    session_dir = cache_dir / ARCHIVE_PATH
    session_dir.mkdir(parents=True)
    (session_dir / "car_data.ff1pkl").write_bytes(b"car data " * 1000)
    (session_dir / "session_info.ff1pkl").write_bytes(b"session info")
    (cache_dir / HTTP_CACHE_FILE).write_bytes(b"raw responses " * 500)
    return FetchedSession(
        session=None,
        identity=identity(),
        coverage=measure_coverage(session or make_session(), "R"),
        cache_dir=cache_dir,
        http=HttpRecorder(),
        attempts=1,
        versions={"fastf1": "3.8.3", "fastf1_cache": 15},
    )


def test_a_snapshot_is_three_objects_and_restores_as_a_fastf1_cache(tmp_path):
    store = MemoryStore()
    now = datetime(2026, 10, 5, 20, 0, 0, tzinfo=timezone.utc)

    written = write_snapshot(store, fetched_session(tmp_path), now=now)

    assert layout.is_snapshot_id(written.snapshot_id) and written.snapshot_id.startswith("20261005T200000Z-")
    prefix = layout.snapshot_prefix(AUSTRIA, written.snapshot_id)
    assert sorted(item.key[len(prefix):] for item in store.list(prefix)) == sorted(
        [PARSED_ARCHIVE, HTTP_ARCHIVE, layout.SNAPSHOT_MARKER]
    )
    (listed,) = list_snapshots(store, AUSTRIA)
    assert listed == written
    assert listed.fetched_at == "2026-10-05T20:00:00Z"
    assert listed.versions == {"fastf1": "3.8.3", "fastf1_cache": 15}
    assert listed.complete

    restored = restore_snapshot(store, listed, tmp_path / "restored")
    assert (restored / ARCHIVE_PATH / "car_data.ff1pkl").read_bytes() == b"car data " * 1000
    assert (restored / ARCHIVE_PATH / "session_info.ff1pkl").read_bytes() == b"session info"


def test_an_upload_that_did_not_finish_is_not_a_snapshot(tmp_path):
    store = MemoryStore()
    written = write_snapshot(store, fetched_session(tmp_path))
    prefix = layout.snapshot_prefix(AUSTRIA, written.snapshot_id)
    del store._objects[f"{prefix}{layout.SNAPSHOT_MARKER}"]

    assert list_snapshots(store, AUSTRIA) == []
    assert list_snapshots(store) == []


def test_every_fetch_is_a_new_snapshot_and_nothing_is_overwritten(tmp_path):
    store = MemoryStore()
    first = write_snapshot(store, fetched_session(tmp_path / "one"))
    second = write_snapshot(store, fetched_session(tmp_path / "two"))

    assert first.snapshot_id != second.snapshot_id
    assert {item.snapshot_id for item in list_snapshots(store)} == {first.snapshot_id, second.snapshot_id}


def test_a_restored_archive_that_does_not_match_its_checksum_is_refused(tmp_path):
    store = MemoryStore()
    written = write_snapshot(store, fetched_session(tmp_path))
    key = f"{layout.snapshot_prefix(AUSTRIA, written.snapshot_id)}{PARSED_ARCHIVE}"
    data = bytearray(store.get(key).data)
    data[len(data) // 2] ^= 0xFF
    store.put(key, bytes(data))

    with pytest.raises(ArchiveError, match="does not match its snapshot"):
        restore_snapshot(store, written, tmp_path / "restored")


def test_a_fetch_with_no_parsed_feeds_is_not_archived(tmp_path):
    fetched = fetched_session(tmp_path)
    for path in (fetched.cache_dir / ARCHIVE_PATH).glob("*.ff1pkl"):
        path.unlink()

    with pytest.raises(ArchiveError):
        write_snapshot(MemoryStore(), fetched)


# --- which snapshot a build uses (rule 6) -------------------------------------


def without_position(driver_numbers):
    session = make_session()
    for number in driver_numbers:
        del session.pos_data[number]
    return session


def car_data_cut_to(laps: int):
    session = make_session()
    for number, telemetry in session.car_data.items():
        seconds = telemetry["SessionTime"].dt.total_seconds()
        session.car_data[number] = telemetry[seconds < RACE_START + laps * LAP_SECONDS]
    return session


def test_a_complete_snapshot_beats_a_later_incomplete_one():
    complete = snapshot(snapshot_id="20261005T200000Z-aaaaaaaa")
    later_but_short = snapshot(snapshot_id="20261006T200000Z-bbbbbbbb", session=without_position(["1"]))

    assert select_snapshot([later_but_short, complete]) == complete


def test_among_incomplete_snapshots_the_one_meeting_more_bars_wins():
    one_short = snapshot(snapshot_id="20261005T200000Z-aaaaaaaa", session=without_position(["1"]))
    two_short = snapshot(snapshot_id="20261006T200000Z-bbbbbbbb", session=without_position(["1", "2"]))

    assert select_snapshot([two_short, one_short]) == one_short


def test_with_the_same_number_of_shortfalls_the_higher_weakest_share_wins():
    """A retry that improved one feed and lost ground on another (rule 6)."""
    # Three shortfalls each: car data for every driver.
    eight_of_ten = snapshot(snapshot_id="20261005T200000Z-aaaaaaaa", session=car_data_cut_to(8))
    four_of_ten = snapshot(snapshot_id="20261006T200000Z-bbbbbbbb", session=car_data_cut_to(4))
    assert len(eight_of_ten.shortfalls()) == len(four_of_ten.shortfalls()) == 3

    assert select_snapshot([four_of_ten, eight_of_ten]) == eight_of_ten


def test_only_between_equals_does_the_later_fetch_win():
    earlier = snapshot(snapshot_id="20261005T200000Z-aaaaaaaa")
    later = snapshot(snapshot_id="20261006T200000Z-bbbbbbbb")

    assert select_snapshot([later, earlier]) == later
    assert select_snapshot([]) is None


def test_a_snapshot_is_judged_by_the_bars_of_the_code_reading_it(monkeypatch):
    """A bar can be tightened without a re-fetch: the measurement is what is stored."""
    from f1data import coverage

    almost = snapshot(session=car_data_cut_to(9))
    monkeypatch.setattr(coverage, "MIN_CAR_LAP_SHARE", 0.85)
    assert Snapshot.from_json(almost.to_json()).complete
    monkeypatch.setattr(coverage, "MIN_CAR_LAP_SHARE", 1.0)
    monkeypatch.setattr(coverage, "TIMING_LAP_TOLERANCE", 0)
    assert not Snapshot.from_json(almost.to_json()).complete


# --- copying a local spool to the bucket --------------------------------------


def test_copy_archive_moves_snapshots_between_stores_and_is_safe_to_repeat(tmp_path, capsys):
    spool, bucket = tmp_path / "spool", tmp_path / "bucket"
    written = write_snapshot(DirectoryStore(spool), fetched_session(tmp_path))
    # Published data in the source is not the archive and must stay behind.
    DirectoryStore(spool).put(layout.pointer_key(AUSTRIA), b"{}")

    with pytest.raises(SystemExit) as first:
        main(["copy-archive", "--from", str(spool), "--to", str(bucket)])
    assert first.value.code == 0
    output = capsys.readouterr().out
    assert "Copied 3 object(s); 0 already there." in output
    # The marker is copied last, so a half-copied snapshot is never visible.
    copied = [line for line in output.splitlines() if line.startswith("copied ")]
    assert copied[-1].startswith(f"copied {layout.snapshot_prefix(AUSTRIA, written.snapshot_id)}snapshot.json")

    assert list_snapshots(DirectoryStore(bucket)) == [written]
    assert DirectoryStore(bucket).get(layout.pointer_key(AUSTRIA)) is None

    with pytest.raises(SystemExit):
        main(["copy-archive", "--from", str(spool), "--to", str(bucket)])
    assert "Copied 0 object(s); 3 already there." in capsys.readouterr().out
