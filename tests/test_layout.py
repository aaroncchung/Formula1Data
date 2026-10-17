"""The key layout, and the rules that tie the pipeline version to the bars and to what is published."""

from __future__ import annotations

import hashlib

import pytest

from f1data import coverage, layout
from f1data.store import MemoryStore
from tests.sample_bucket import write_sample

# What the sample race publishes (tests/sample_bucket.py), and the pipeline
# version it was recorded at. The test below tells what to set it to.
RECORDED_OUTPUT = (28, "d760ef249f84e4040f6b9e67f8b558ec7c9193d723dc7935aafcfb0a9cc1f8cd")


def published_output(monkeypatch, pipeline_version: int) -> str:
    """The SHA-256 of every object the sample writes, by key and as written, under ``pipeline_version``.

    The sample race is built by the real code from the session the tests are
    built on (tests/race.py): every artifact, the nine analyses among them,
    then the manifest, the pointer, the index and the standings.
    """
    with monkeypatch.context() as patched:
        patched.setattr(layout, "PIPELINE_VERSION", pipeline_version)
        store = MemoryStore()
        write_sample(store)
    digest = hashlib.sha256()
    for key in sorted(item.key for item in store.list("")):
        digest.update(key.encode("utf-8") + b"\0" + hashlib.sha256(store.get(key).data).digest())
    return digest.hexdigest()


def test_changing_what_a_build_publishes_needs_a_new_pipeline_version(monkeypatch):
    """A pointer written by this pipeline version is not built again. If what a
    build publishes changes and the version does not, every session published
    before the change stays as it was. Nothing else said so: the bars are held
    to the version by the test after this one, and the analyses were not.

    The pipeline version is in the manifest and the pointer, so the recorded
    output is of one version.
    """
    version, recorded = RECORDED_OUTPUT
    if layout.PIPELINE_VERSION != version:
        pytest.fail(
            f"PIPELINE_VERSION is {layout.PIPELINE_VERSION} and the output was recorded under {version}: set "
            f'RECORDED_OUTPUT in tests/test_layout.py to ({layout.PIPELINE_VERSION}, '
            f'"{published_output(monkeypatch, layout.PIPELINE_VERSION)}")'
        )
    if published_output(monkeypatch, version) != recorded:
        pytest.fail(
            f"output changed: bump PIPELINE_VERSION in f1data/layout.py to {version + 1}, say why in the list "
            f'above it, and set RECORDED_OUTPUT in tests/test_layout.py to ({version + 1}, '
            f'"{published_output(monkeypatch, version + 1)}")'
        )


def test_changing_a_coverage_bar_needs_a_new_pipeline_version():
    """A pointer records whether its session met the bars. If a bar changes and
    the pipeline version does not, every pointer judged under the old bar stays
    as it was: a review found exactly that after the timing tolerance was
    removed.

    When this fails, bump PIPELINE_VERSION in f1data/layout.py, say why in the
    list above it, then record the new pair here.
    """
    bars = repr(
        (
            coverage.MAX_SAMPLE_GAP_SECONDS,
            coverage.MIN_CAR_LAP_SHARE,
            coverage.MIN_POSITION_LAP_SHARE,
            coverage.MIN_TYRE_LAP_SHARE,
            coverage.CAR_CHANNELS,
            coverage.POSITION_CHANNELS,
            sorted(coverage.FEED_FILE_BY_BAR),
            sorted(coverage.RACE_LIKE_SESSION_TYPES),
            coverage.MEASUREMENT_VERSION,
            coverage.MOVING_ABOVE_KPH,
            coverage.MAX_REPEATED_SHARE_OF_A_LAP,
            coverage.MIN_MOVING_SAMPLES_TO_JUDGE_A_LAP,
            coverage.MAX_SECONDS_BETWEEN_PLACES,
            coverage.STANDING_MARGIN_SECONDS,
        )
    )
    recorded_bars = "9e25d20319f9"
    recorded_pipeline_version = 28

    assert (hashlib.sha256(bars.encode()).hexdigest()[:12], layout.PIPELINE_VERSION) == (
        recorded_bars,
        recorded_pipeline_version,
    )


def test_every_published_key_sits_under_the_format_version():
    generation = "a1" * 32

    for key in (
        layout.index_key(),
        layout.pointer_key(11315),
        layout.standings_key(2026),
        layout.generation_prefix(11315, generation),
    ):
        assert key.startswith(f"v{layout.FORMAT_VERSION}/")
    assert layout.pointer_key(11315).startswith(layout.pointers_prefix())


def test_the_archive_sits_outside_every_format_version():
    prefix = layout.snapshot_prefix(11315, "20261006T000433Z-a05afd6c")

    assert prefix == "archive/sessions/11315/20261006T000433Z-a05afd6c/"
    assert prefix.startswith(layout.session_archive_prefix(11315))


def test_a_pointer_key_gives_back_its_session_and_nothing_else_does():
    assert layout.session_key_from_pointer_key(layout.pointer_key(11315)) == 11315
    for key in ("v1/pointers/latest.json", "v1/pointers/11315.txt", "v1/index.json", "v2/pointers/11315.json"):
        assert layout.session_key_from_pointer_key(key, format_version=1) in (None,), key


@pytest.mark.parametrize("value", ["", "abc", "A1" * 32, "a1" * 31, None, 7])
def test_only_sixty_four_lowercase_hex_characters_name_a_generation(value):
    assert not layout.is_generation_id(value)
    with pytest.raises(ValueError):
        layout.generation_prefix(11315, value)


@pytest.mark.parametrize("value", ["", "2026-10-06", "20261006T000433Z", "20261006T000433Z-XYZ", "../x", None])
def test_a_snapshot_id_has_one_shape(value):
    assert not layout.is_snapshot_id(value)
    with pytest.raises(ValueError):
        layout.snapshot_prefix(11315, value)
