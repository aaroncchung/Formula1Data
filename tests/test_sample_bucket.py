"""The sample for working on the site offline is what the publisher writes (tests/sample_bucket.py)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

from f1data import layout
from f1data.models import SESSION_ARTIFACTS
from f1data.schema import validate_published
from f1data.store import MemoryStore
from tests.sample_bucket import IDENTITY, SERVED_UNDER, _AsTheWorkerServes, main, write_sample


def test_the_sample_is_a_whole_published_season_and_every_object_is_what_its_model_says():
    store = MemoryStore()

    lines = write_sample(store)

    assert [line.split(":")[1].strip().split(",")[0] for line in lines] == ["published", "published", "published"]
    prefix = layout.format_prefix()
    keys = sorted(item.key for item in store.list(""))
    assert all(key.startswith(prefix) for key in keys)
    for key in keys:
        validate_published(key[len(prefix) :], json.loads(store.get(key).data))
    pointer = json.loads(store.get(layout.pointer_key(IDENTITY.session_key)).data)
    generation = layout.generation_prefix(IDENTITY.session_key, pointer["generation"])
    files = {key[len(generation) :] for key in keys if key.startswith(generation)}
    # Every artifact a race has, and a telemetry file for each driver.
    assert files >= (set(SESSION_ARTIFACTS) - {"analysis/pace-prediction.json"}) | {
        "manifest.json",
        "telemetry/AAA.json",
        "telemetry/BBB.json",
        "telemetry/CCC.json",
    }
    (season,) = json.loads(store.get(layout.index_key()).data)["seasons"]
    published, to_come = season["meetings"]
    assert published["sessions"][0]["session_key"] == IDENTITY.session_key
    assert "session_key" not in to_come["sessions"][0] and to_come["meeting_key"] is None
    assert json.loads(store.get(layout.standings_key(IDENTITY.year)).data)["drivers"][0]["driver_code"] == "AAA"


def test_writing_the_sample_twice_changes_nothing():
    store = MemoryStore()
    write_sample(store)
    before = {item.key: store.get(item.key).data for item in store.list("")}

    lines = write_sample(store)

    assert {item.key: store.get(item.key).data for item in store.list("")} == before
    assert "unchanged" in lines[0] or "current" in lines[0], lines


def test_the_command_writes_a_directory_a_file_server_can_serve_as_the_worker_does(tmp_path, capsys):
    assert main([str(tmp_path / "sample")]) == 0
    assert "session 9001: published" in capsys.readouterr().out

    handler = partial(_AsTheWorkerServes, directory=str(tmp_path / "sample"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(f"{base}{SERVED_UNDER}{layout.index_key()}", timeout=10) as response:
            assert response.status == 200
            assert response.headers["Access-Control-Allow-Origin"] == "*"
            assert json.loads(response.read())["format_version"] == layout.FORMAT_VERSION
        # Only under /data, never a listing of what is there, and nothing
        # but what is published: a directory that also holds an archive is
        # served as the Worker serves a bucket that does.
        archived = tmp_path / "sample" / "archive" / "sessions" / "9001" / "snapshot.json"
        archived.parent.mkdir(parents=True)
        archived.write_text("{}", encoding="utf-8")
        for path in (
            f"/{layout.index_key()}",
            SERVED_UNDER,
            f"{SERVED_UNDER}v2/pointers/",
            f"{SERVED_UNDER}archive/sessions/9001/snapshot.json",
        ):
            with pytest.raises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(base + path, timeout=10)
            assert refused.value.code == 404, path
    finally:
        server.shutdown()
        server.server_close()
