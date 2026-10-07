"""The key layout, and the rule that ties the coverage bars to the pipeline version."""

from __future__ import annotations

import hashlib

import pytest

from f1data import coverage, layout


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
        )
    )
    recorded_bars = "8c2dd541e136"
    recorded_pipeline_version = 9

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
