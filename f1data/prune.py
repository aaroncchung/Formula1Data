"""Remove the generations no page can be reading any more.

A generation is never changed and is named by its content, so a publication
that changes a session's files writes a new one, and a new pipeline version
publishes every session again: some 43 sessions of up to 21 MB each. Nothing
else removes a generation. ``prune`` does, by these rules:

- Every pointer is read first. If any cannot be read, nothing is removed:
  which generations it keeps is not known.
- A pointer's generation is kept, and the one it names as the generation
  before: a page that read the pointer just before the last publication is
  reading that one.
- A generation with an object written within the retention period, 30 days
  unless told otherwise and never less than one, is kept whatever names it. A
  page reads the generation it opened for as long as it stays open, and a
  build uploads a generation before its pointer names it.
- Only objects in a generation's place under the published format's prefix
  are removed (``layout.generation_of_key``). Never a pointer, the index, the
  standings, the archive, another format's prefix, or any other key.

A generation's manifest is removed before its files, so one that is part
removed is, by the layout's rule, an upload that never finished. A page that
finds its generation gone reads the pointer again and opens the generation it
names now (frontend/src/lib/published/session.ts).

What the rules cannot see is a build that points a session at a generation
older than the retention period while this runs, which it does when it builds
the same files again and finds them in place. Each session's pointer is read
again just before its generations are removed, and a generation it names then
is left; one it names only afterwards is reported. Run it when no build is
running.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from f1data import layout
from f1data.publish import Pointer, PointerError, read_pointer
from f1data.store import ObjectInfo, ObjectStore

KEEP_FOR = timedelta(days=30)
# A build uploads a generation and then writes the pointer to it. Nothing
# written more recently than this is removed, whatever is asked.
LEAST_KEEP_FOR = timedelta(days=1)


class PruneRefused(RuntimeError):
    """Nothing can be removed safely, and why."""


@dataclass(frozen=True)
class Generation:
    session_key: int
    generation: str
    objects: tuple[ObjectInfo, ...]

    @property
    def size_bytes(self) -> int:
        return sum(item.size for item in self.objects)

    @property
    def written(self) -> datetime | None:
        """When an object of it was last written. ``None`` when the store does not say for every one."""
        times = [item.modified for item in self.objects]
        if any(moment is None for moment in times):
            return None
        return max(moment for moment in times if moment is not None)


@dataclass(frozen=True)
class Plan:
    """What a prune would remove, and what it keeps and why."""

    pointers: int
    kept: list[tuple[Generation, str]]
    removable: list[Generation]
    # Under the generations' prefix and not where a generation's files go.
    # Left alone.
    stray: list[ObjectInfo]


@dataclass
class Removed:
    generations: list[Generation] = field(default_factory=list)
    # Named by their session's pointer when it was read again, and left.
    left: list[Generation] = field(default_factory=list)
    # A pointer that named a generation once it had been removed.
    attention: list[str] = field(default_factory=list)
    # Why removing stopped before the end, if it did.
    stopped: str | None = None


def plan_prune(store: ObjectStore, now: datetime, keep_for: timedelta = KEEP_FOR) -> Plan:
    """Decide what to remove. Reads every pointer and lists every generation; writes nothing.

    Raises ``PruneRefused`` when a pointer cannot be read.
    """
    if keep_for < LEAST_KEEP_FOR:
        raise ValueError(f"A generation written in the last {LEAST_KEEP_FOR} is always kept")
    named, pointers = _named_by_pointers(store)
    kept: list[tuple[Generation, str]] = []
    removable: list[Generation] = []
    generations, stray = _generations(store)
    for generation in generations:
        why = named.get((generation.session_key, generation.generation)) or _recent(generation, now, keep_for)
        if why is None:
            removable.append(generation)
        else:
            kept.append((generation, why))
    return Plan(pointers=pointers, kept=kept, removable=removable, stray=stray)


def remove_generations(store: ObjectStore, plan: Plan) -> Removed:
    """Remove what ``plan`` found removable, a session at a time, reading its pointer again first."""
    removed = Removed()
    by_session: dict[int, list[Generation]] = defaultdict(list)
    for generation in plan.removable:
        by_session[generation.session_key].append(generation)
    for session_key, generations in sorted(by_session.items()):
        try:
            named = _named_now(store, session_key)
            gone = []
            for generation in generations:
                if generation.generation in named:
                    removed.left.append(generation)
                    continue
                # The manifest first: what is left of a generation part
                # removed is then an upload that never finished.
                for item in sorted(generation.objects, key=lambda item: not _is_manifest(item)):
                    store.delete(item.key)
                removed.generations.append(generation)
                gone.append(generation)
            named = _named_now(store, session_key)
        except Exception as exc:  # noqa: BLE001 - whatever stops it, what was done is said
            removed.stopped = f"session {session_key}: {type(exc).__name__}: {exc}"
            return removed
        for generation in gone:
            if generation.generation in named:
                removed.attention.append(
                    f"the pointer of session {session_key} names generation {generation.generation}, which "
                    "was removed: a build pointed at it while this ran"
                )
    return removed


def _named_by_pointers(store: ObjectStore) -> tuple[dict[tuple[int, str], str], int]:
    """Every generation a pointer names, with how, and how many pointers there are."""
    named: dict[tuple[int, str], str] = {}
    pointers = 0
    for item in store.list(layout.pointers_prefix()):
        session_key = layout.session_key_from_pointer_key(item.key)
        if session_key is None:
            # Not a pointer by its key, so nothing reads it as one.
            continue
        pointer = _read(store, session_key)
        if pointer is None:
            raise PruneRefused(f"The pointer of session {session_key} was listed and could not be found")
        pointers += 1
        named.setdefault((session_key, pointer.generation), "named by its pointer")
        if pointer.previous_generation is not None:
            named.setdefault(
                (session_key, pointer.previous_generation), "named by its pointer as the one before"
            )
    return named, pointers


def _recent(generation: Generation, now: datetime, keep_for: timedelta) -> str | None:
    """Why a generation no pointer names is kept for its age, if it is."""
    written = generation.written
    if written is None:
        return "the store does not say when it was written"
    if now - written < keep_for:
        return f"written in the last {_days(keep_for)}"
    return None


def _named_now(store: ObjectStore, session_key: int) -> set[str]:
    """The generations the session's pointer names as it is now."""
    pointer = _read(store, session_key)
    if pointer is None:
        return set()
    return {name for name in (pointer.generation, pointer.previous_generation) if name is not None}


def _is_manifest(item: ObjectInfo) -> bool:
    return item.key.endswith(f"/{layout.MANIFEST_NAME}")


def _read(store: ObjectStore, session_key: int) -> Pointer | None:
    try:
        pointer, _ = read_pointer(store, session_key)
    except PointerError as exc:
        raise PruneRefused(str(exc)) from exc
    if (
        pointer is not None
        and pointer.previous_generation is not None
        and not layout.is_generation_id(pointer.previous_generation)
    ):
        raise PruneRefused(
            f"The pointer of session {session_key} names something that is not a generation as the one before"
        )
    return pointer


def _generations(store: ObjectStore) -> tuple[list[Generation], list[ObjectInfo]]:
    found: dict[tuple[int, str], list[ObjectInfo]] = defaultdict(list)
    stray: list[ObjectInfo] = []
    for item in store.list(layout.generations_prefix()):
        place = layout.generation_of_key(item.key)
        if place is None:
            stray.append(item)
        else:
            found[place].append(item)
    generations = [
        Generation(key, generation, tuple(items)) for (key, generation), items in sorted(found.items())
    ]
    return generations, stray


def _days(period: timedelta) -> str:
    days = period / timedelta(days=1)
    return f"{days:g} day{'' if days == 1 else 's'}"
