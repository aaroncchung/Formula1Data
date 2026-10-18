"""The case the sixth review of this code found (GPT-6.1 Sol, 2026-10-06, at 00a1d28).

A correction of a snapshot's record is written against the one before it, and
one a newer pipeline version wrote is never replaced. ``copy-archive`` copied
corrections like any other object, with neither check.
"""

from __future__ import annotations

import pytest

from f1data import layout
from f1data.archive import list_snapshots, write_remeasurement, write_snapshot
from f1data.cli import main
from f1data.store import DirectoryStore
from tests.building import FIRST_FETCH
from tests.fakes import make_session, measure
from tests.test_archive import fetched_session
from tests.test_fourth_review import without_positions_for_one_driver
from tests.test_publish import AUSTRIA


def copy(source, destination, capsys) -> str:
    capsys.readouterr()
    with pytest.raises(SystemExit) as finished:
        main(["copy-archive", "--from", str(source), "--to", str(destination)])
    assert finished.value.code == 0
    return capsys.readouterr().out


def test_copying_an_archive_leaves_corrections_where_they_are(tmp_path, capsys, monkeypatch):
    """The spool holds a snapshot and an old correction of it. The bucket holds
    the same snapshot, corrected since by a newer pipeline version."""
    spool, bucket = DirectoryStore(tmp_path / "spool"), DirectoryStore(tmp_path / "bucket")
    written = write_snapshot(spool, fetched_session(tmp_path), now=FIRST_FETCH)
    assert "Copied 5 object(s); 0 already there." in copy(tmp_path / "spool", tmp_path / "bucket", capsys)
    key = f"{layout.snapshot_prefix(AUSTRIA, written.snapshot_id)}{layout.REMEASUREMENT_NAME}"

    (in_the_spool,) = list_snapshots(spool)
    write_remeasurement(spool, in_the_spool, measure(make_session()))
    (in_the_bucket,) = list_snapshots(bucket)
    with monkeypatch.context() as newer:
        newer.setattr(layout, "PIPELINE_VERSION", layout.PIPELINE_VERSION + 1)
        write_remeasurement(bucket, in_the_bucket, measure(without_positions_for_one_driver(10)))
    theirs = bucket.get(key).data

    output = copy(tmp_path / "spool", tmp_path / "bucket", capsys)

    assert "Copied 0 object(s); 5 already there." in output
    assert "Left 1 correction(s) of a snapshot's record where they are" in output
    assert bucket.get(key).data == theirs
    (still,) = list_snapshots(bucket)
    assert not still.complete and still.corrected_by == layout.PIPELINE_VERSION + 1


def test_a_correction_is_not_carried_to_a_store_that_has_none(tmp_path, capsys):
    """The destination's own build measures the snapshot. Until it does, the
    snapshot stands there as it was recorded."""
    spool = DirectoryStore(tmp_path / "spool")
    written = write_snapshot(spool, fetched_session(tmp_path), now=FIRST_FETCH)
    (as_listed,) = list_snapshots(spool)
    write_remeasurement(spool, as_listed, measure(without_positions_for_one_driver(10)))
    key = f"{layout.snapshot_prefix(AUSTRIA, written.snapshot_id)}{layout.REMEASUREMENT_NAME}"

    output = copy(tmp_path / "spool", tmp_path / "bucket", capsys)

    bucket = DirectoryStore(tmp_path / "bucket")
    assert "Copied 5 object(s); 0 already there." in output
    assert bucket.get(key) is None
    assert list_snapshots(bucket) == [written]
    assert list_snapshots(bucket)[0].correction_etag is None
