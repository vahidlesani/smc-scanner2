"""R63: tradeable pivot patterns (P4) + Al Brooks entry-side engine."""
import numpy as np
import pandas as pd

from analysis.brooks_pa import (breakout_bar_quality, entry_side, first_cross_index,
                                follow_through)


def _frame(closes, freq="1h", start="2026-09-20", spread=0.5):
    closes = np.asarray(closes, dtype=float)
    opens = np.r_[closes[0], closes[:-1]]
    ts = pd.date_range(start, periods=len(closes), freq=freq)
    return pd.DataFrame({"timestamp": ts, "open": opens,
                         "high": np.maximum(opens, closes) + spread,
                         "low": np.minimum(opens, closes) - spread,
                         "close": closes, "volume": 1000.0})


def _double_top_path():
    up = np.linspace(80, 110, 71)            # bars 0..70  (top1 at 70)
    dn = np.linspace(110, 100, 11)[1:]       # 71..80     (valley at 80)
    up2 = np.linspace(100, 110, 11)[1:]      # 81..90     (top2 at 90)
    dn2 = np.linspace(110, 101.5, 30)[1:]    # 91..119
    return np.r_[up, dn, up2, dn2]


def _trigger_break(neck, strong=True):
    closes = [101.8, 101.6, 101.9, 101.7] * 9 + [101.6, 101.5, 101.6]
    df = _frame(closes, freq="15min", start="2026-09-24 22:00", spread=0.3)
    o = 101.5
    c = neck - 1.0 if strong else neck - 0.2
    h = o + 0.1 if strong else o + 0.1
    l = c - 0.1 if strong else c - 1.2
    if not strong:
        o, c = neck + 0.05, neck - 0.2      # doji-like, closes in the wrong half
        h, l = neck + 1.3, neck - 1.3
    row = {"timestamp": df["timestamp"].iloc[-1] + pd.Timedelta("15min"),
           "open": o, "high": h, "low": l, "close": c, "volume": 3000.0}
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


def test_brooks_strong_vs_weak_breakout_bar():
    t = _trigger_break(99.5, strong=True)
    bi = first_cross_index(t, 99.5, "SHORT", lookback=4)
    assert bi == len(t) - 1
    assert breakout_bar_quality(t, bi, "SHORT", 99.5)["grade"] == "STRONG"
    w = _trigger_break(99.5, strong=False)
    assert breakout_bar_quality(w, len(w) - 1, "SHORT", 99.5)["ok"] is False


def test_follow_through_failure_detected():
    t = _trigger_break(99.5, strong=True)
    row = t.iloc[-1].copy()
    row["timestamp"] = row["timestamp"] + pd.Timedelta("15min")
    row["open"], row["close"], row["high"], row["low"] = 98.6, 100.4, 100.6, 98.4
    t2 = pd.concat([t, pd.DataFrame([row])], ignore_index=True)
    assert follow_through(t2, len(t) - 1, "SHORT", 99.5)["status"] == "FAILED"


def test_entry_side_reversal_needs_prior_trend():
    p = _frame(_double_top_path())
    es = entry_side(p, 70, 99.5, 10.5)
    assert es["from"] == "BELOW" and es["prior_move"] >= 0.8


def test_double_top_is_traded_on_neckline_break():
    from analysis.pattern_engine import pivot_pattern_events
    p = _frame(_double_top_path())
    neck = float(p["low"].iloc[80])
    evs = pivot_pattern_events(p, _trigger_break(neck, strong=True), "1h")
    dt = [e for e in evs if e["pattern"] == "DOUBLE_TOP"]
    assert dt, evs
    ev = dt[0]
    assert ev["direction"] == "SHORT" and ev["side"] == "lower"
    assert ev["state"] == "BREAK_CLOSED"
    assert ev["stop_hint"] > 110.0                     # above the tops (Bulkowski)
    assert ev["measured"]["to"] < neck                  # height projected down
    assert ev["pivot_pattern"]["role"] == "REVERSAL"
    assert len(ev["pivot_pattern"]["pivots_ts"]) == 3
    assert ev["pattern_geo"]["lower"]["price"] == neck


def test_double_top_weak_breakout_bar_not_traded():
    from analysis.pattern_engine import pivot_pattern_events
    p = _frame(_double_top_path())
    neck = float(p["low"].iloc[80])
    evs = pivot_pattern_events(p, _trigger_break(neck, strong=False), "1h")
    assert not [e for e in evs if e["pattern"] == "DOUBLE_TOP"]


def test_double_top_without_prior_trend_is_not_a_reversal():
    from analysis.pattern_engine import pivot_pattern_events
    path = _double_top_path()
    path[:71] = np.r_[np.linspace(125, 111, 60), np.linspace(111, 110, 11)]   # came from ABOVE
    p = _frame(path)
    neck = float(p["low"].iloc[80])
    evs = pivot_pattern_events(p, _trigger_break(neck, strong=True), "1h")
    assert not [e for e in evs if e["pattern"] == "DOUBLE_TOP"]


def test_trade_geometry_survives_unify():
    from types import SimpleNamespace
    from analysis.pattern_engine import _attach_r63_geometry, pivot_pattern_events
    from analysis.snapshot_lock import unify_trade_geometry
    p = _frame(_double_top_path())
    neck = float(p["low"].iloc[80])
    ev = [e for e in pivot_pattern_events(p, _trigger_break(neck), "1h") if e["pattern"] == "DOUBLE_TOP"][0]
    cand = SimpleNamespace(metadata={"strategy_variant": "VIVA_TLBREAK",
                                     "viva_upper_points": ev["upper_points"],
                                     "viva_lower_points": ev["lower_points"],
                                     "render_patterns": [{"type": "WEDGE_RISING", "lines": [{}]}]},
                           evidence=[])
    _attach_r63_geometry(cand, ev, "1h")
    unify_trade_geometry(cand.metadata)
    kinds = [x["type"] for x in cand.metadata["render_patterns"]]
    assert kinds == ["DOUBLE_TOP"]
    assert cand.metadata["render_patterns"][0]["pivots_ts"]
    assert any(e.key == "pivot_pattern" for e in cand.evidence)
