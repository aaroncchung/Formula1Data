"""One contract, run against every store.

The publisher this replaces was tested only against a fake of ``wrangler`` and
never completed a real run (docs/architecture-review-findings.md, AR-04). These
tests are the answer to that: the fakes used elsewhere in the suite pass the
same cases the real bucket does, and the real bucket is one of the parameters.

The R2 case runs when ``F1DATA_TEST_R2=1`` and the bucket is configured in the
environment (see ``f1data/config.py``). It writes only under a prefix of its
own, which the Worker does not serve, and deletes what it wrote.
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest

from f1data.store import DirectoryStore, MemoryStore, PreconditionFailed

STORES = ["memory", "directory", "r2"]


@pytest.fixture(params=STORES)
def store(request, tmp_path):
    if request.param == "memory":
        yield MemoryStore()
    elif request.param == "directory":
        yield DirectoryStore(tmp_path / "store")
    else:
        if os.environ.get("F1DATA_TEST_R2") != "1":
            pytest.skip("set F1DATA_TEST_R2=1 and the R2 environment to test the real bucket")
        from f1data.config import open_r2_store, r2_settings

        r2 = open_r2_store(r2_settings(), prefix=f"contract-tests/{uuid.uuid4().hex}/")
        try:
            yield r2
        finally:
            for item in list(r2.list("")):
                r2.delete(item.key)


def test_a_missing_object_is_none_not_an_error(store, tmp_path):
    assert store.get("v1/pointers/1.json") is None
    assert store.head("v1/pointers/1.json") is None
    assert store.download_file("v1/pointers/1.json", tmp_path / "out.json") is False
    assert list(store.list("v1/")) == []


def test_put_then_get_returns_the_bytes_and_one_version(store):
    etag = store.put("v1/index.json", b'{"a":1}')

    found = store.get("v1/index.json")
    assert found is not None
    assert (found.key, found.data, found.etag) == ("v1/index.json", b'{"a":1}', etag)
    info = store.head("v1/index.json")
    assert info is not None and (info.size, info.etag) == (7, etag)


def test_if_absent_writes_once(store):
    store.put("v1/pointers/1.json", b"first", if_absent=True)

    with pytest.raises(PreconditionFailed):
        store.put("v1/pointers/1.json", b"second", if_absent=True)
    assert store.get("v1/pointers/1.json").data == b"first"


def test_if_match_writes_only_over_the_version_that_was_read(store):
    first = store.put("v1/pointers/1.json", b"first")
    second = store.put("v1/pointers/1.json", b"second", if_match=first)
    assert second != first

    with pytest.raises(PreconditionFailed):
        store.put("v1/pointers/1.json", b"stale writer", if_match=first)
    assert store.get("v1/pointers/1.json").data == b"second"


def test_if_match_fails_when_the_object_is_gone(store):
    with pytest.raises(PreconditionFailed):
        store.put("v1/pointers/1.json", b"data", if_match='"0123456789abcdef0123456789abcdef"')
    assert store.get("v1/pointers/1.json") is None


def test_an_unconditional_put_replaces(store):
    store.put("v1/index.json", b"one")
    store.put("v1/index.json", b"two")

    assert store.get("v1/index.json").data == b"two"


def test_list_returns_only_the_prefix(store):
    store.put("v1/pointers/11315.json", b"{}")
    store.put("v1/pointers/11361.json", b"{}{}")
    store.put("v1/index.json", b"{}")
    store.put("archive/sessions/11315/x/snapshot.json", b"{}")

    listed = sorted((item.key, item.size) for item in store.list("v1/pointers/"))

    assert listed == [("v1/pointers/11315.json", 2), ("v1/pointers/11361.json", 4)]


def test_files_go_up_and_come_back(store, tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(bytes(range(256)) * 512)

    store.put_file("archive/sessions/1/x/fastf1-cache.tar.gz", source)
    target = tmp_path / "nested" / "target.bin"

    assert store.download_file("archive/sessions/1/x/fastf1-cache.tar.gz", target) is True
    assert target.read_bytes() == source.read_bytes()
    assert store.head("archive/sessions/1/x/fastf1-cache.tar.gz").size == 256 * 512


@pytest.mark.parametrize("starting_point", ["absent", "present"])
def test_of_several_writers_that_read_the_same_version_exactly_one_wins(store, starting_point):
    """Rule 2 in one test: the store, not the callers, keeps publishers apart."""
    key = "v1/pointers/11315.json"
    etag = store.put(key, b"original") if starting_point == "present" else None
    writers = 6
    barrier = threading.Barrier(writers)
    outcomes: list[str] = []

    def write(number: int) -> None:
        barrier.wait(timeout=30)
        try:
            if etag is None:
                store.put(key, f"writer {number}".encode(), if_absent=True)
            else:
                store.put(key, f"writer {number}".encode(), if_match=etag)
        except PreconditionFailed:
            outcomes.append("lost")
        else:
            outcomes.append(f"writer {number}")

    threads = [threading.Thread(target=write, args=(number,)) for number in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    winners = [outcome for outcome in outcomes if outcome != "lost"]
    assert len(outcomes) == writers
    assert len(winners) == 1
    assert store.get(key).data == winners[0].encode()


def test_a_directory_store_refuses_a_key_that_leaves_its_root(tmp_path):
    directory = DirectoryStore(tmp_path / "store")

    for key in ("../outside.json", "v1/../../outside.json", "/absolute.json", "v1//double.json", ""):
        with pytest.raises(ValueError):
            directory.put(key, b"{}")
