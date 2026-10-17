"""Behavioral contracts for the canonical pattern-law registry."""
from analysis.pattern_law import (
    PATTERN_LAW,
    canonical_pattern_slug,
    engine_stamp,
    pattern_is_live,
    pattern_law_entry,
    pattern_ref_fa,
)


def test_every_active_shape_has_a_reference_and_rule():
    active = {
        "WEDGE_FALLING", "WEDGE_RISING",
        "TRIANGLE_SYMMETRICAL", "TRIANGLE_ASCENDING", "TRIANGLE_DESCENDING",
        "CHANNEL_ASCENDING", "CHANNEL_DESCENDING", "CHANNEL_FLAT",
        "RECTANGLE", "FLAG_BULL", "FLAG_BEAR", "PENNANT_BULL", "PENNANT_BEAR",
        "BROADENING", "TRENDLINE",
    }
    for slug in active:
        law = pattern_law_entry(slug)
        assert law, f"missing law entry for {slug}"
        assert law.get("ref"), f"missing external reference for {slug}"
        assert law.get("rule"), f"missing explicit rule for {slug}"


def test_range_and_generic_channel_use_explicit_canonical_aliases():
    assert canonical_pattern_slug("RANGE") == "RECTANGLE"
    assert pattern_law_entry("RANGE") == PATTERN_LAW["RECTANGLE"]
    assert canonical_pattern_slug("CHANNEL") == "CHANNEL_FLAT"
    assert pattern_law_entry("CHANNEL") == PATTERN_LAW["CHANNEL_FLAT"]


def test_retired_pivot_shapes_cannot_be_reactivated_by_the_law_registry():
    for slug in (
        "DOUBLE_TOP", "DOUBLE_BOTTOM", "HEAD_SHOULDERS",
        "INV_HEAD_SHOULDERS", "INVERSE_HEAD_SHOULDERS", "CUP_HANDLE", "INV_CUP_HANDLE",
    ):
        assert not pattern_is_live(slug)
        assert pattern_law_entry(slug) == {}
        assert pattern_ref_fa(slug) == ""


def test_engine_stamp_uses_the_candidate_selected_shape_not_first_near_break():
    md = {
        "setup_code": "TECHCLASSIC",
        "pattern_type": "WEDGE_RISING",
        "render_patterns": [
            {"type": "WEDGE_FALLING", "near_break": True, "lines": [{"side": "HIGH"}]},
            {"type": "WEDGE_RISING", "near_break": True, "lines": [{"side": "HIGH"}]},
        ],
    }
    stamp = engine_stamp(md, setup_code="TECHCLASSIC")
    assert stamp["law_slug"] == "WEDGE_RISING"
    assert md["pattern_ref"] == PATTERN_LAW["WEDGE_RISING"]["ref"]
    assert md["pattern_rule_fa"] == PATTERN_LAW["WEDGE_RISING"]["rule"]
