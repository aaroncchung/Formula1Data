"""The cases the seventh review of this code found (GPT-6.1 Sol, 2026-10-06, at 0d51442).

Both are outside what the rounds before had been circling. A batch of fetches
gave up after two failures in a row whatever had caused them, and the same
two were first in line on every run. And the directory store's conditional
writes held only inside one instance of it.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from f1data import cli as cli_module
from f1data.archive import list_snapshots
from f1data.cli import main
from f1data.fetch import FetchError
from f1data.store import DirectoryStore, PreconditionFailed
from tests.test_archive import fetched_session
from tests.test_publish import AUSTRIA
from tests.test_second_review import ONE_RACE

REPOSITORY = Path(__file__).resolve().parents[1]

# Two races before Austria that F1's archive does not hold, and Austria.
AUSTRIA_ENTRY = next(entry for entry in ONE_RACE if entry.session_type == "R")
CALENDAR = [
    replace(AUSTRIA_ENTRY, round=6, meeting_name="Sixth Grand Prix", start_time_utc="2026-05-03T13:00:00Z"),
    replace(AUSTRIA_ENTRY, round=7, meeting_name="Seventh Grand Prix", start_time_utc="2026-05-24T13:00:00Z"),
    AUSTRIA_ENTRY,
]


# --- two sessions that never fetch do not keep the rest from being fetched ---------


def fetch_due(tmp_path, monkeypatch, capsys, f1_answers) -> tuple[list[int], str, int]:
    """Run ``fetch-due`` once over a calendar whose first two races always fail.

    ``f1_answers`` is what the question "is F1 answering at all" is answered
    with, or a function that answers it.
    """
    attempted: list[int] = []

    @contextmanager
    def no_cache(cache_dir):
        yield None

    def fetch(year, event, session_type, cache_dir, resume=False):
        attempted.append(event)
        if event != AUSTRIA_ENTRY.round:
            raise FetchError(f"F1 has no session information for {year} round {event}")
        # Into the directory it was given, as a fetch is.
        return fetched_session(cache_dir.parent)

    monkeypatch.setattr(cli_module, "fastf1_cache", no_cache)
    monkeypatch.setattr(cli_module, "load_schedule", lambda fastf1, year: CALENDAR)
    monkeypatch.setattr(cli_module, "fetch_session", fetch)
    answering = f1_answers if callable(f1_answers) else (lambda years: f1_answers)
    monkeypatch.setattr(cli_module, "f1_is_answering", answering)
    capsys.readouterr()
    with pytest.raises(SystemExit) as finished:
        main(["fetch-due", "--store", str(tmp_path / "store"), "--season", "2026"])
    return attempted, capsys.readouterr().out, finished.value.code


def test_two_sessions_that_cannot_be_fetched_do_not_starve_the_ones_after_them(tmp_path, monkeypatch, capsys):
    """Nothing is archived for a fetch that fails, so the same two are planned
    first on every run. The batch used to stop at the second, every time."""
    store = DirectoryStore(tmp_path / "store")

    attempted, output, code = fetch_due(tmp_path, monkeypatch, capsys, f1_answers=True)

    assert attempted == [6, 7, 8]
    assert "F1's archive is answering, so the fault is with these sessions; carrying on." in output
    assert [snapshot.session_key for snapshot in list_snapshots(store)] == [AUSTRIA]
    # A failed fetch is still a failed run.
    assert code == 1

    # The next run tries the two again, and has nothing else to do.
    attempted, _, _ = fetch_due(tmp_path, monkeypatch, capsys, f1_answers=True)
    assert attempted == [6, 7]


def test_a_batch_still_stops_when_f1_is_not_answering_at_all(tmp_path, monkeypatch, capsys):
    attempted, output, code = fetch_due(tmp_path, monkeypatch, capsys, f1_answers=False)

    assert attempted == [6, 7]
    assert "Stopping: 2 fetches failed in a row and F1's archive is not answering. 1 session(s) left" in output
    assert code == 1
    assert list_snapshots(DirectoryStore(tmp_path / "store")) == []


# --- a directory's conditional writes hold for every writer ------------------------


class Pausing(DirectoryStore):
    """A directory store that stops inside a conditional write, after it has
    read what is there and before it writes."""

    def __init__(self, root):
        super().__init__(root)
        self.has_read = threading.Event()
        self.carry_on = threading.Event()

    def get(self, key):
        found = super().get(key)
        self.has_read.set()
        assert self.carry_on.wait(10)
        return found


def test_two_instances_on_one_directory_cannot_both_create_an_object(tmp_path):
    """A reads that the pointer is absent. Before A writes, B, another
    instance on the same directory, creates it. Each instance had a lock of
    its own, so both writes used to succeed and A's replaced B's."""
    a, b = Pausing(tmp_path), DirectoryStore(tmp_path)
    outcomes: dict[str, str] = {}

    def create(name: str, store: DirectoryStore) -> None:
        try:
            store.put("v1/pointers/11315.json", name.encode(), if_absent=True)
            outcomes[name] = "written"
        except PreconditionFailed:
            outcomes[name] = "refused"

    first = threading.Thread(target=create, args=("a", a))
    first.start()
    assert a.has_read.wait(10)
    second = threading.Thread(target=create, args=("b", b))
    second.start()
    # B waits for A's check and write to finish, as it would for the bucket's.
    second.join(0.3)
    assert second.is_alive() and outcomes == {}

    a.carry_on.set()
    first.join(10)
    second.join(10)

    assert outcomes == {"a": "written", "b": "refused"}
    assert DirectoryStore(tmp_path).get("v1/pointers/11315.json").data == b"a"


def test_two_instances_cannot_both_replace_the_version_they_read(tmp_path):
    etag = DirectoryStore(tmp_path).put("v1/index.json", b"first")
    a, b = Pausing(tmp_path), DirectoryStore(tmp_path)
    outcomes: dict[str, str] = {}

    def update(name: str, store: DirectoryStore) -> None:
        try:
            store.put("v1/index.json", name.encode(), if_match=etag)
            outcomes[name] = "written"
        except PreconditionFailed:
            outcomes[name] = "refused"

    first = threading.Thread(target=update, args=("a", a))
    first.start()
    assert a.has_read.wait(10)
    second = threading.Thread(target=update, args=("b", b))
    second.start()
    second.join(0.3)
    a.carry_on.set()
    first.join(10)
    second.join(10)

    assert outcomes == {"a": "written", "b": "refused"}


RACER = """
import sys, time
from pathlib import Path
from f1data.store import DirectoryStore, PreconditionFailed

root, start_at, name = sys.argv[1], float(sys.argv[2]), sys.argv[3]
store = DirectoryStore(Path(root))
while time.time() < start_at:
    pass
try:
    store.put("v1/pointers/11315.json", name.encode(), if_absent=True)
except PreconditionFailed:
    sys.exit(3)
"""


def test_of_several_processes_creating_one_object_exactly_one_wins(tmp_path):
    """Separate runs of the command against one directory, started together."""
    start_at = time.time() + 2.0
    racers = [
        subprocess.Popen([sys.executable, "-c", RACER, str(tmp_path), str(start_at), f"writer-{number}"], cwd=REPOSITORY)
        for number in range(4)
    ]

    codes = sorted(racer.wait(60) for racer in racers)

    assert codes == [0, 3, 3, 3]
    assert DirectoryStore(tmp_path).get("v1/pointers/11315.json").data.startswith(b"writer-")


def test_the_lock_is_not_an_object(tmp_path):
    store = DirectoryStore(tmp_path)
    store.put("v1/index.json", b"{}")

    assert [item.key for item in store.list("")] == ["v1/index.json"]
    assert (tmp_path / ".f1data-lock").is_file()
    with pytest.raises(ValueError):
        store.put(".f1data-lock", b"mine")
    with pytest.raises(ValueError):
        store.get(".f1data-lock/x")


def test_a_refused_write_leaves_nothing_behind(tmp_path):
    store = DirectoryStore(tmp_path)
    store.put("v1/index.json", b"first")

    with pytest.raises(PreconditionFailed):
        store.put("v1/index.json", b"second", if_absent=True)

    assert sorted(path.name for path in (tmp_path / "v1").iterdir()) == ["index.json"]
    assert store.get("v1/index.json").data == b"first"
