"""Keeping a directory that exists on one machine only (AR-11, step 1)."""

from __future__ import annotations

import io
import json
import tarfile
from datetime import datetime, timezone

import pytest

from f1data.archive import ArchiveError, archive_directory
from f1data.store import MemoryStore

NOW = datetime(2026, 10, 5, 20, 0, 0, tzinfo=timezone.utc)


def old_cache(tmp_path):
    cache = tmp_path / "fastf1"
    race = cache / "2026" / "2026-06-28_Austrian_Grand_Prix" / "2026-06-28_Race"
    race.mkdir(parents=True)
    (race / "car_data.ff1pkl").write_bytes(b"car data " * 2000)
    (race / "session_info.ff1pkl").write_bytes(b"session info")
    (cache / "fastf1_http_cache.sqlite").write_bytes(b"raw responses " * 100)
    return cache


def test_a_directory_is_kept_whole_with_a_description_beside_it(tmp_path):
    store = MemoryStore()
    cache = old_cache(tmp_path)

    description = archive_directory(store, cache, "legacy-fastf1-cache", now=NOW)

    key = "archive/legacy/legacy-fastf1-cache-20261005T200000Z"
    assert sorted(item.key for item in store.list("archive/")) == [f"{key}.json", f"{key}.tar.gz"]
    assert json.loads(store.get(f"{key}.json").data) == description
    assert description["file_count"] == 3
    assert description["total_bytes"] == 18000 + 12 + 1400
    assert description["archive"]["key"] == f"{key}.tar.gz"
    assert description["archive"]["size_bytes"] == len(store.get(f"{key}.tar.gz").data)

    with tarfile.open(fileobj=io.BytesIO(store.get(f"{key}.tar.gz").data), mode="r:gz") as archive:
        names = sorted(member.name for member in archive.getmembers())
        car_data = archive.extractfile(
            "2026/2026-06-28_Austrian_Grand_Prix/2026-06-28_Race/car_data.ff1pkl"
        ).read()
    assert names == [
        "2026/2026-06-28_Austrian_Grand_Prix/2026-06-28_Race/car_data.ff1pkl",
        "2026/2026-06-28_Austrian_Grand_Prix/2026-06-28_Race/session_info.ff1pkl",
        "fastf1_http_cache.sqlite",
    ]
    assert car_data == b"car data " * 2000


def test_it_never_reaches_a_served_prefix(tmp_path):
    store = MemoryStore()

    archive_directory(store, old_cache(tmp_path), "legacy-fastf1-cache", now=NOW)

    assert all(item.key.startswith("archive/") for item in store.list(""))


@pytest.mark.parametrize("name", ["", "../escape", "Has Spaces", "v1/pointers", "trailing-"])
def test_the_name_cannot_steer_the_key(tmp_path, name):
    with pytest.raises(ValueError):
        archive_directory(MemoryStore(), old_cache(tmp_path), name, now=NOW)


def test_an_empty_or_missing_directory_is_refused(tmp_path):
    (tmp_path / "empty").mkdir()

    with pytest.raises(ArchiveError):
        archive_directory(MemoryStore(), tmp_path / "empty", "legacy-fastf1-cache")
    with pytest.raises(ArchiveError):
        archive_directory(MemoryStore(), tmp_path / "missing", "legacy-fastf1-cache")
