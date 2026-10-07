"""The cases the twentieth review of this code found (GPT-6.1 Sol, 2026-10-07, at 196b59c).

The round before stopped anything but a race or a sprint from being
published. This one asked what became of one that had been published
already, and the answer was that the site still opened it: a page reached by
a session's key reads the pointer and never the index. The site now refuses
such a pointer itself (frontend/tests/published-data.test.mjs), and the
publisher counts it for nothing.

Also here: a lock file removed after its lock was released when removing it
under the lock had failed, the two names F1 has used for a sprint and the
two it has used for the session that sets a sprint's grid, and the sample
server serving what the Worker does not. The comparison of two laps'
telemetry, which took each lap's distance to start at nought, is in
frontend/tests/telemetry-compare.test.mjs.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from f1data import cli as cli_module
from f1data import fetch as fetch_module
from f1data import layout, spool
from f1data.archive import dump_json, write_snapshot
from f1data.build import Builder
from f1data.extras import WEATHER_SERIES
from f1data.identity import identity_from_fastf1, session_type_code
from f1data.publish import NotPublished, derive_index, read_pointer, read_published
from f1data.store import MemoryStore
from tests.building import FIRST_FETCH, Archive
from tests.race import extras, make_race
from tests.test_archive import fetched_session
from tests.test_eighteenth_review import lock_of
from tests.test_extras import ARCHIVE_PATH
from tests.test_fifth_review import EVERYONE, WINDOW_CLOSED
from tests.test_fourth_review import without_positions_for_one_driver
from tests.test_nineteenth_review import PRACTICE, practice
from tests.test_publish import AUSTRIA, Publisher, schedule_2026, snapshot

# --- R20-1: a pointer to anything but a race or a sprint counts for nothing -----------


def with_a_practice_pointer() -> MemoryStore:
    """A store with a race published, and beside it the pointer a version before this one could write."""
    store = MemoryStore()
    Publisher(store).publish()
    race = json.loads(store.get(layout.pointer_key(AUSTRIA)).data)
    stray = {
        **race,
        "session_key": PRACTICE,
        "identity": {
            **race["identity"],
            "session_key": PRACTICE,
            "session_type": "FP2",
            "session_name": "Practice 2",
            "year": 2023,
            "start_time_utc": "2023-07-01T11:30:00Z",
        },
    }
    store.put(layout.pointer_key(PRACTICE), dump_json(stray))
    return store


def test_a_pointer_written_before_the_rule_is_passed_over_wherever_the_published_are_counted():
    """A practice session published by the version before stayed published:
    its pointer was left, the index dropped it, and everything else that
    lists what is published still had it."""
    store = with_a_practice_pointer()
    assert read_pointer(store, PRACTICE)[0] is not None

    published = read_published(store)

    assert [pointer.session_key for pointer in published] == [AUSTRIA]
    # So its season is not one whose calendar and standings are kept on its account.
    assert {pointer.identity.year for pointer in published} == {2026}
    assert "Practice 2" not in json.dumps(derive_index(published, {2026: schedule_2026()}))


def test_the_build_says_of_such_a_session_that_it_has_a_pointer_nothing_opens(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    write_snapshot(world.store, practice(fetched_session(tmp_path)), now=FIRST_FETCH)
    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)
    stray, _ = read_pointer(with_a_practice_pointer(), PRACTICE)

    declined = builder.gather(PRACTICE, pointer=stray)

    assert isinstance(declined, NotPublished)
    assert "It has a pointer, written by a version before this one: the site does not open it" in declined.reason
    assert "pointer" not in builder.gather(PRACTICE).reason


def test_a_session_that_is_never_built_does_not_bring_its_season_into_what_a_run_looks_at():
    """A practice session of 2023, archived by hand and short of a feed, put
    2023 among the seasons the job fetches: every race and sprint of it."""
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    short = without_positions_for_one_driver(10)
    stray = snapshot(session_key=PRACTICE, session=short, start="2023-07-01T11:30:00Z")
    stray = replace(stray, identity=replace(stray.identity, session_type="FP2", session_name="Practice 2"))
    race = snapshot(session_key=9001, session=short, start="2024-07-01T13:00:00Z")

    assert not stray.complete
    assert cli_module._seasons_in_scope(now, [stray], set()) == [2025, 2026]
    assert cli_module._seasons_in_scope(now, [stray, race], set()) == [2024, 2025, 2026]


# --- R20-2: a lock is removed after its release only where an open file cannot be ------


@pytest.mark.parametrize(("cannot_remove_an_open_file", "tries"), [(False, 1), (True, 2)])
def test_a_lock_that_could_not_be_removed_while_held_is_left_where_that_would_not_be_safe(
    tmp_path, monkeypatch, cannot_remove_an_open_file, tries
):
    """Removing the lock while it was held failed, for a moment's want of
    permission. It was then removed after the lock was released, everywhere:
    where a file can be removed while another run has it open, that is the
    order the removal under the lock was there to prevent."""
    directory = spool.new_fetch_path(tmp_path / "spool")
    asked: list[bool] = []
    monkeypatch.setattr(spool, "_AN_OPEN_FILE_CANNOT_BE_REMOVED", cannot_remove_an_open_file)
    monkeypatch.setattr(spool, "_unlink", lambda path: bool(asked.append(True)))

    with spool.holding(directory) as mine:
        assert mine

    # Left for a later run to remove while it holds it.
    assert len(asked) == tries and lock_of(directory).is_file()


# --- R20-3: one name has meant two kinds of session -------------------------------------


def test_the_sprint_of_2021_is_a_sprint_though_f1_called_it_sprint_qualifying():
    """In 2021, and only then, F1's name for the sprint itself was Sprint
    Qualifying. Read as the session that sets a sprint's grid, a sprint of
    that season was never built, and never matched its calendar entry, so
    it was fetched on every run that looked at 2021."""
    assert session_type_code("Sprint Qualifying", year=2021) == "S"
    assert session_type_code("Sprint Qualifying", year=2024) == "SQ"
    assert session_type_code("Sprint Qualifying") == "SQ"
    # The code is this program's own, and means what it means in any year.
    assert session_type_code("SQ", year=2021) == "SQ" and session_type_code("Sprint", year=2021) == "S"

    def session_of(year: int) -> SimpleNamespace:
        return SimpleNamespace(
            session_info={
                "Key": 6110,
                "Name": "Sprint Qualifying",
                "Path": f"{year}/{year}-07-18_British_Grand_Prix/{year}-07-17_Sprint_Qualifying/",
                "Meeting": {"Key": 1064, "Name": "British Grand Prix"},
            },
            event={"RoundNumber": 10, "EventName": "British Grand Prix"},
            date=datetime(year, 7, 17, 15, 30),
            name="Sprint",
        )

    then, now = identity_from_fastf1(session_of(2021)), identity_from_fastf1(session_of(2025))

    assert (then.session_type, then.session_name) == ("S", "Sprint Qualifying")
    assert (now.session_type, now.session_name) == ("SQ", "Sprint Qualifying")


def test_fastf1_is_asked_for_a_session_in_the_words_that_were_given(monkeypatch, tmp_path):
    """`fetch --session "Sprint Shootout"` was turned into this program's
    code for it, SQ, and FastF1 asked for that: its own code for a shootout
    is SS, and SQ is a session a 2023 weekend does not have."""
    asked: list[object] = []
    loaded = make_race()
    loaded.load = lambda **kwargs: None

    @contextmanager
    def cache(cache_dir):
        yield SimpleNamespace(get_session=lambda year, event, identifier: asked.append(identifier) or loaded)

    monkeypatch.setattr(fetch_module, "fastf1_cache", cache)
    monkeypatch.setattr(fetch_module, "identity_from_fastf1", lambda found: SimpleNamespace(archive_path=ARCHIVE_PATH, session_type="R"))
    monkeypatch.setattr(fetch_module, "_versions", lambda module: {})
    monkeypatch.setattr(fetch_module, "fetch_extras", lambda module, found, path: {**extras(), WEATHER_SERIES: b"00:00:38.376{}"})

    for number, words in enumerate(["Sprint Shootout", " SS ", "R"]):
        fetch_module.fetch_session(2023, 4, words, tmp_path / f"cache-{number}")

    assert asked == ["Sprint Shootout", "SS", "R"]
    assert session_type_code("SS") == "SQ" and session_type_code("sprint shootout") == "SQ"
    with pytest.raises(ValueError, match="Unknown session type"):
        fetch_module.fetch_session(2023, 4, "Warm-up", tmp_path / "never")
