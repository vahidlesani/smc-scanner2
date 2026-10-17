"""Behavioral contracts for the canonical pattern-law registry."""
import pandas as pd

from analysis.pattern_law import (
    PATTERN_LAW,
    canonical_pattern_slug,
    dominant_slug,
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
    # A generic CHANNEL label does not prove a horizontal channel; it must not
    # borrow that pattern's reference or be treated as a live named shape.
    assert canonical_pattern_slug("CHANNEL") == "CHANNEL"
    assert pattern_law_entry("CHANNEL") == {}
    assert pattern_is_live("RANGE") is True
    assert pattern_is_live("CHANNEL") is False
    assert pattern_is_live("TRIANGLE") is False
    assert dominant_slug([{"type": "TRIANGLE"}]) == ""
    assert dominant_slug([{"type": "TRIANGLE"}, {"type": "WEDGE_FALLING"}]) == "WEDGE_FALLING"


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


def test_engine_stamp_does_not_borrow_an_unrelated_shape_when_label_mismatches():
    md = {
        "setup_code": "TECHCLASSIC",
        "pattern_type": "TRIANGLE_ASCENDING",
        "render_patterns": [
            {"type": "WEDGE_FALLING", "near_break": True, "lines": [{"side": "HIGH"}]},
            {"type": "WEDGE_RISING", "near_break": True, "lines": [{"side": "HIGH"}]},
        ],
    }
    stamp = engine_stamp(md, setup_code="TECHCLASSIC")
    assert stamp["pattern_ref"] == ""
    assert md.get("pattern_ref") is None


class _Line:
    def __init__(self, intercept, slope, first_index=10):
        self.intercept = float(intercept)
        self.slope = float(slope)
        self.first_index = first_index
        self.points = [{"index": 10}, {"index": 50}, {"index": 90}]

    def price_at(self, x):
        return self.intercept + self.slope * float(x)


def test_pair_geometry_distinguishes_falling_wedge_from_parallel_channel():
    from analysis.pattern_law import pair_metrics, classify_pair

    # Both edges descend, but the upper edge descends materially faster and
    # the gap contracts: this is a falling wedge, not a descending channel.
    wedge_upper = _Line(130, -0.25)
    wedge_lower = _Line(100, -0.10)
    wedge = pair_metrics(wedge_upper, wedge_lower, 100)
    assert wedge["ok"] is True
    assert classify_pair(wedge) == "WEDGE_FALLING"

    # Similar relative edge speeds and a stable band must remain a channel.
    channel_upper = _Line(130, -0.20)
    channel_lower = _Line(100, -0.17)
    channel = pair_metrics(channel_upper, channel_lower, 100)
    assert channel["ok"] is True
    assert classify_pair(channel) == "CHANNEL_DESCENDING"


def test_generic_triangle_fallback_is_diagnostic_not_a_trade_event(monkeypatch):
    from analysis import pattern_engine

    n = 50
    frame = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h"),
        "open": [100.0] * n,
        "high": [101.0] * n,
        "low": [99.0] * n,
        "close": [100.0] * n,
        "volume": [1000.0] * n,
    })
    monkeypatch.setattr(pattern_engine, "fit_edge_line",
                        lambda df, side, cfg, idx: _Line(130 if side == "HIGH" else 100, -0.1))
    monkeypatch.setattr(pattern_engine, "classify_shape", lambda *args, **kwargs: "TRIANGLE")
    assert pattern_engine.scan_edges(frame, frame.tail(10), "4h") == []


def test_engine_stamp_does_not_promote_generic_triangle_to_a_live_reference():
    md = {
        "pattern_type": "TRIANGLE",
        "render_patterns": [{"type": "TRIANGLE", "near_break": True, "lines": [{"side": "HIGH"}, {"side": "LOW"}]}],
    }
    stamp = engine_stamp(md, setup_code="TECHCLASSIC")
    assert stamp["pattern_ref"] == ""
    assert md.get("pattern_ref") is None


def test_generic_channel_has_no_live_edge_rule_or_reference():
    from analysis.pattern_engine import _EDGE_RULES

    md = {
        "pattern_type": "CHANNEL",
        "render_patterns": [{"type": "CHANNEL", "near_break": True, "lines": [{"side": "HIGH"}, {"side": "LOW"}]}],
    }
    stamp = engine_stamp(md, setup_code="TECHCLASSIC")
    assert "CHANNEL" not in _EDGE_RULES
    assert stamp["pattern_ref"] == ""
    assert md.get("pattern_ref") is None


def test_single_trendline_rapid_return_is_failed_break_not_opposite_fresh_break():
    from analysis.pattern_law import trendline_state

    closes = [99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 101.0, 100.5, 99.0, 99.0]
    frame = pd.DataFrame({
        "open": [v - 0.1 for v in closes],
        "high": [v + 0.4 for v in closes],
        "low": [v - 0.4 for v in closes],
        "close": closes,
    })
    info = trendline_state(frame, _Line(100, 0.0), atr=1.0)
    assert info["state"] == "FAILED_BREAK"
    assert info["break_direction"] == "UP"


def test_single_trendline_valid_close_break_keeps_its_direction():
    from analysis.pattern_law import trendline_state

    closes = [99.0] * 9 + [101.0]
    frame = pd.DataFrame({
        "open": [v - 0.1 for v in closes],
        "high": [v + 0.4 for v in closes],
        "low": [v - 0.4 for v in closes],
        "close": closes,
    })
    info = trendline_state(frame, _Line(100, 0.0), atr=1.0)
    assert info["state"] == "FRESH_BREAK"
    assert info["break_direction"] == "UP"
