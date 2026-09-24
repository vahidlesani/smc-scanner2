"""Round-24 nature law — «ما بر اساس ماهیت هر الگو سیگنال تایید میکنیم».

Viva's 09-24 reference sheets (سقف/شانه، دوقلو، ویج، مثلث، پرچم، مستطیل،
کانال + نقاط ورود رنگی و ENTRY/SL/TP): a pattern's NATURE decides which edge
break can confirm a signal. The opposite-side break of a one-nature pattern is
a VIOLATION: it warns and explains — it NEVER becomes a signal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.pattern_engine import (
    _EDGE_RULES,
    STATE_VIOLATED,
    scan_edges,
)

TS = pd.date_range(end="2026-09-24 10:00", periods=150, freq="15min", tz="UTC")


def _frame(mid: np.ndarray, wick=0.012, opens_prev=False) -> pd.DataFrame:
    rng = np.random.default_rng(4)
    open_ = np.roll(mid, 1) if opens_prev else mid * 0.999
    open_[0] = mid[0] * 0.999
    rng_ = np.abs(rng.normal(1.0, 0.1, len(mid))) * np.abs(mid) * wick
    return pd.DataFrame({
        "timestamp": TS, "open": open_,
        "high": np.maximum(open_, mid) + rng_,
        "low": np.minimum(open_, mid) - rng_,
        "close": mid, "volume": np.full(len(mid), 1e6)})


def _zigzag(anchors, n=150, seed=4, noise=0.0003):
    rng = np.random.default_rng(seed)
    xs = np.array([a[0] for a in anchors], float)
    ys = np.array([a[1] for a in anchors], float)
    mid = np.interp(np.arange(n, dtype=float), xs, ys)
    return mid + rng.normal(0, noise, n)


def test_directional_triangles_and_channels_are_one_nature():
    """His sheets: مثلث صعودی → فقط بریک بالا؛ مثلث نزولی → فقط بریک پایین؛
    کانال صعودی/نزولی likewise. The opposite side must carry NO rule."""
    assert _EDGE_RULES["TRIANGLE_ASCENDING"] == {"upper": "LONG"}
    assert _EDGE_RULES["TRIANGLE_DESCENDING"] == {"lower": "SHORT"}
    assert _EDGE_RULES["CHANNEL_ASCENDING"] == {"upper": "LONG"}
    assert _EDGE_RULES["CHANNEL_DESCENDING"] == {"lower": "SHORT"}
    # continuation shapes stay two-sided (his «از هر طرف بشکنه و کلوز بده»)
    assert _EDGE_RULES["TRIANGLE_SYMMETRICAL"]["upper"] == "LONG"
    assert _EDGE_RULES["TRIANGLE_SYMMETRICAL"]["lower"] == "SHORT"
    assert _EDGE_RULES["WEDGE_FALLING"] == {"upper": "LONG"}
    assert _EDGE_RULES["WEDGE_RISING"] == {"lower": "SHORT"}


def test_falling_wedge_wrong_side_break_warns_and_never_signals():
    """Falling wedge closed BELOW its lower edge = nature violated: exactly a
    WARN event (no direction), and NO LONG/SHORT event from that side."""
    low_touches = [(10, 0.2040), (40, 0.1930), (70, 0.1820), (100, 0.1715), (130, 0.1610)]
    high_touches = [(20, 0.2270), (52, 0.2115), (84, 0.1965), (114, 0.1820), (140, 0.1680)]
    mid = _zigzag(sorted(low_touches + high_touches))
    mid[146:] = [0.1570, 0.1550, 0.1532, 0.1515]      # close breaks the LOWER edge
    df = _frame(mid)
    events = scan_edges(df.tail(150).reset_index(drop=True), df.tail(6).reset_index(drop=True), "15m")
    violated = [e for e in events if e.get("warn_only")]
    assert violated, events
    v = violated[0]
    assert v["state"] == STATE_VIOLATED and v["direction"] is None
    assert v["side"] == "lower" and v["break_edge"] == "LOWER"
    assert "هیچ سیگنالی" in (v.get("violation_fa") or "")
    wrong = [e for e in events
             if e.get("side") == "lower" and not e.get("warn_only")
             and e.get("direction") in ("LONG", "SHORT")]
    assert not wrong, wrong


def test_ascending_triangle_upper_break_confirms_long_only():
    """Flat resistance + rising lows, closed ABOVE the flat top → the ONLY
    direction the engine may emit is LONG (upper edge)."""
    upper_touches = [(20, 110.0), (50, 110.0), (80, 110.0), (110, 110.0)]
    lower_touches = [(10, 95.0), (50, 99.0), (90, 102.5), (130, 106.0)]
    anchors = sorted(upper_touches + lower_touches)
    mid = _zigzag(anchors, seed=9, noise=0.02)
    mid[146:] = [110.5, 110.9, 111.2, 111.6]          # breakout + close above
    df = _frame(mid, wick=0.004, opens_prev=True)
    events = scan_edges(df.tail(150).reset_index(drop=True), df.tail(6).reset_index(drop=True), "15m")
    dirs = {(e.get("side"), e.get("direction")) for e in events
            if e.get("state") in ("BREAK_CLOSED", "BREAK_READY")}
    assert ("upper", "LONG") in dirs, dirs
    assert ("lower", "SHORT") not in dirs and ("upper", "SHORT") not in dirs
