"""Round-23 MODEL LAW — «هزاربار این مدلی باید شناسایی بشه».

Viva's hand-drawn model (the ZK 1D annotated chart, 09-21): a FALLING WEDGE
(two converging falling edges, 3+ touches each) whose UPPER edge breaks with a
closing candle → LONG only, never SHORT. These tests replay that exact
sequence on a realistic pivot-zigzag frame through the REAL pipeline
(detect_patterns → enrich_render → evaluate_confirmation) so the model can
never silently regress again.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.models import SignalCandidate
from analysis.quality_engine import evaluate_confirmation, _project_watch_level
from analysis.render_kit import detect_patterns, enrich_render

N = 150
LOW_TOUCHES = [(10, 0.2040), (40, 0.1930), (70, 0.1820), (100, 0.1715), (130, 0.1610)]
HIGH_TOUCHES = [(20, 0.2270), (52, 0.2115), (84, 0.1965), (114, 0.1820), (140, 0.1680)]
TS = pd.date_range(end="2026-09-24 12:00", periods=N, freq="1d", tz="UTC")


def _mid() -> np.ndarray:
    rng = np.random.default_rng(4)
    anchors = sorted(LOW_TOUCHES + HIGH_TOUCHES)
    xs = np.array([p[0] for p in anchors], float)
    ys = np.array([p[1] for p in anchors], float)
    mid = np.interp(np.arange(N, dtype=float), xs, ys)
    mid += rng.normal(0, 0.0003, N)
    mid[141:] = np.linspace(0.1680, 0.1645, 9)   # the breakout rally
    return mid


_MID = _mid()


def _frame(a: int, b: int, last_close: float) -> pd.DataFrame:
    seg = _MID[a:b].copy()
    seg[-1] = last_close
    return pd.DataFrame({
        "timestamp": TS[a:b], "open": seg * 0.999, "high": seg * (1 + 0.012),
        "low": seg * (1 - 0.012), "close": seg, "volume": np.ones(len(seg)) * 1e6})


def _watch() -> list[dict]:
    alert = _frame(0, 141, _MID[140])
    c = SignalCandidate(
        signal_id="model-law", symbol="ZKUSDT", style="SWING", setup_code="PINVAL",
        setup_name="پین‌بار", strategy_fa="مدل وج", direction="LONG", score=9,
        status="PENDING", entry_zone_bottom=0.1630, entry_zone_top=0.1655,
        planned_entry=0.1650, sl=0.1558, tp1=0.1752, tp2=0.1940,
        rr_tp1=1.5, rr_tp2=4.0, bias="BULLISH", trigger_timeframe="1d",
        metadata={"atr": 0.004, "touched": True}, mandatory_gates={"zone": True})
    enrich_render(c, alert, None)
    return c.metadata.get("render_line_watch") or []


def test_falling_wedge_model_is_detected_by_name():
    """The engine must NAME the hand-drawn model WEDGE_FALLING with both edges
    carrying real touches — two anonymous trendlines is a regression."""
    alert = _frame(0, 141, _MID[140])
    pats = detect_patterns(alert, "LONG")
    kinds = [p["type"] for p in pats]
    assert "WEDGE_FALLING" in kinds, kinds
    wedge = next(p for p in pats if p["type"] == "WEDGE_FALLING")
    sides = {ln.get("side") for ln in (wedge.get("lines") or [])}
    assert sides == {"HIGH", "LOW"}
    for ln in wedge["lines"]:
        assert len(ln.get("points") or []) >= 2


def test_wedge_upper_break_confirms_long_and_never_short():
    """Break + close beyond the fitted upper edge → LONG confirms on the live
    (tz-aware) frame; the mirrored SHORT is rejected BREAK_SIDE_MISMATCH."""
    watch = _watch()
    up = [l for l in watch if l.get("side") == "HIGH"]
    assert up, "upper edge must travel on render_line_watch"
    t_end = TS[-1]
    lvl = _project_watch_level(up[0], t_end)
    break_close = float(lvl) + 0.0020
    zone_top = float(lvl) - 0.0005
    closed = _frame(110, 150, break_close)
    base = dict(signal_id="model-law", symbol="ZKUSDT", style="SWING",
                setup_code="PINVAL", setup_name="پین‌بار", strategy_fa="مدل وج",
                score=9, status="PENDING", rr_tp1=1.5, rr_tp2=4.0,
                trigger_timeframe="1d", mandatory_gates={"zone": True})
    long = SignalCandidate(
        direction="LONG", bias="BULLISH",
        entry_zone_bottom=zone_top - 0.0035, entry_zone_top=zone_top,
        planned_entry=zone_top - 0.0015, sl=0.1558,
        tp1=break_close * 1.012, tp2=break_close * 1.030,
        metadata={"atr": 0.004, "touched": True, "render_line_watch": watch}, **base)
    ok, cand, _msg = evaluate_confirmation(long, closed, None)
    assert ok, cand.metadata.get("last_reject_code")

    short = SignalCandidate(
        direction="SHORT", bias="BEARISH",
        entry_zone_bottom=break_close + 0.0010, entry_zone_top=break_close + 0.0035,
        planned_entry=break_close + 0.0020, sl=float(lvl) + 0.0080,
        tp1=break_close - 0.0120, tp2=break_close - 0.0240,
        metadata={"atr": 0.004, "touched": True, "render_line_watch": watch}, **base)
    ok2, cand2, _m2 = evaluate_confirmation(short, closed, None)
    assert not ok2
    assert cand2.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH"
