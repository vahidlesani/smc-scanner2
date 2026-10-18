"""Regression tests for bounded smart-chart framing.

The viewport must prioritize live candles over stale pattern anchors. These
contracts intentionally test the real choose_view implementation without
requiring network data.
"""
import numpy as np
import pandas as pd

from analysis import viva_geometry as vg


def _frame(n=500):
    close = np.linspace(100.0, 120.0, n)
    return pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.005,
        "low": close * 0.995,
        "close": close,
        "volume": np.full(n, 1000.0),
    })


def _pattern(x0, x1, leg_bars=0):
    upper = vg.Line(0.0001, np.log(125.0), "upper", (x0, x1), x0)
    lower = vg.Line(0.0001, np.log(115.0), "lower", (x0, x1), x0)
    return vg.PatternResult(
        "CHANNEL_ASCENDING", upper, lower, x0, x1,
        10.0, vg.Leg(direction=vg.UP if leg_bars else vg.NONE,
                     bars=leg_bars), {"du": 0.1, "dl": 0.1},
    )


def test_choose_view_never_expands_history_to_reach_stale_pattern_start():
    frame = _frame(500)
    # Simulate a legacy/global anchor older than the timeframe's chart budget.
    res = _pattern(15, 80, leg_bars=400)
    view = vg.choose_view(frame, res, tf="1d")

    assert view["x_from"] >= len(frame) - vg.TF_VIEW_BARS["1d"]
    assert view["x_to"] >= len(frame) - 1
    assert view["pad_right"] > 0
    assert view["bars"] == view["x_to"] - view["x_from"] + 1


def test_choose_view_keeps_recent_pattern_and_live_candles_in_same_frame():
    frame = _frame(500)
    x0 = 420
    res = _pattern(x0, 499, leg_bars=20)
    view = vg.choose_view(frame, res, tf="15m")

    assert view["x_from"] >= len(frame) - vg.TF_VIEW_BARS["15m"]
    assert view["x_from"] <= x0
    assert view["x_to"] >= len(frame) - 1
    assert view["y_min"] > 0
    assert view["y_max"] > view["y_min"]


def test_choose_view_does_not_use_unbounded_leg_history_for_left_padding():
    frame = _frame(500)
    res = _pattern(420, 499, leg_bars=10000)
    view = vg.choose_view(frame, res, tf="4h")

    assert view["x_from"] >= len(frame) - vg.TF_VIEW_BARS["4h"]
    assert view["x_to"] - (len(frame) - 1) <= max(
        8, int(round(vg.TF_VIEW_BARS["4h"] * vg.RIGHT_PROJ))
    )

def test_choose_view_vertical_range_contains_selected_pattern_lines():
    frame = _frame(500)
    x0, x1 = 420, 499
    # Lines are deliberately just outside the candle extrema at the visible
    # endpoints; the final price axis must still contain the selected geometry.
    upper = vg.Line(0.0001, np.log(130.0), "upper", (x0, x1), x0)
    lower = vg.Line(0.0001, np.log(90.0), "lower", (x0, x1), x0)
    res = vg.PatternResult(
        "CHANNEL_ASCENDING", upper, lower, x0, x1,
        10.0, vg.Leg(), {"du": 0.1, "dl": 0.1},
    )
    view = vg.choose_view(frame, res, tf="15m")

    assert view["y_min"] <= lower.price_at(x0)
    assert view["y_min"] <= lower.price_at(x1)
    assert view["y_max"] >= upper.price_at(x0)
    assert view["y_max"] >= upper.price_at(x1)


def test_choose_view_ignores_extrapolated_line_values_outside_visible_window():
    frame = _frame(500)
    # The old anchor is far outside the viewport; an extreme extrapolation at
    # that anchor must not stretch the price axis or squeeze the live candles.
    upper = vg.Line(0.02, np.log(125.0) - 0.02 * 10, "upper", (10, 40), 10)
    lower = vg.Line(0.01, np.log(90.0) - 0.01 * 10, "lower", (10, 40), 10)
    res = vg.PatternResult(
        "CHANNEL_ASCENDING", upper, lower, 10, 40,
        10.0, vg.Leg(direction=vg.UP, bars=10000), {"du": 0.1, "dl": 0.1},
    )
    view = vg.choose_view(frame, res, tf="1d")

    assert view["y_min"] > 0
    assert view["y_max"] / view["y_min"] < 2.0

def test_classify_geometry_rejects_converging_pattern_with_exhausted_apex():
    # Both edges slope down and converge, but their intersection is only one
    # bar after x1. This must not be promoted as a live falling wedge.
    x0, x1 = 100, 200
    upper = vg.Line(-0.002, np.log(120.0) + 0.002 * x0,
                    "upper", (x0, x1), x0)
    lower = vg.Line(-0.00101, upper.at(x0) - 0.1,
                    "lower", (x0, x1), x0)
    slug, meta = vg.classify_geometry(upper, lower, x0, x1)

    assert slug == "NONE"
    assert "رأس الگوی همگرا" in meta["reason"]

