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
                trigger_timeframe="1d", mandatory_gates={"zone": True},
                # wall-clock-proof (r28): the fixture tape ends 2026-09-24; a
                # default created_at=now() silently emptied `_bars_since_candidate`
                # once the calendar moved past the last bar (NO_NEW_BAR at
                # 09-25). The candidate is pinned BEFORE its own tape forever.
                created_at="2026-09-20T00:00:00+00:00")
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


# ── Round-24: the numeric tool — «ابزار لانگ و شورت در ۵ ستاپ فقط با
#    tp1 تا tp5 مشخص بشه» (no big labels over candles/tool) ─────────────────
def test_tool_pills_are_bare_numbers_with_axis_values(monkeypatch):
    # r32: no network — a real live candle would spike the frame range and
    # blow up the pill-grouping tolerance on this synthetic 100-tape.
    import data.fetcher as _f
    monkeypatch.setattr(_f, "get_klines", lambda *a, **k: None)
    import numpy as _np
    from datetime import datetime, timedelta, timezone
    import bot.messages_v7 as m7
    from analysis.models import SignalCandidate as _SC, EvidenceItem as _EV
    from analysis.trade_management import build_ladder as _bl
    rng = _np.random.default_rng(11)
    n = 90
    ts = [datetime(2026, 9, 19, tzinfo=timezone.utc) + timedelta(minutes=15 * i) for i in range(n)]
    close = 96.5 + _np.linspace(0, 8.0, n) + rng.normal(0, 0.05, n)
    frame = pd.DataFrame({"timestamp": ts, "open": close - 0.08, "high": close + 0.2,
                          "low": close - 0.2, "close": close, "volume": _np.full(n, 900.0)})
    now = datetime.now(timezone.utc).replace(microsecond=0)
    c = _SC(signal_id="NUM-TOOL-1", symbol="BTCUSDT", style="DAYTRADE",
            setup_code="TLBREAK", setup_name="VIVA-TLBREAK", strategy_fa="x",
            direction="LONG", score=8, status="CONFIRMED",
            entry_zone_bottom=99.4, entry_zone_top=99.6, planned_entry=99.5, sl=97.5,
            tp1=103.5, tp2=107.5, rr_tp1=2.0, rr_tp2=4.0, bias="BULLISH",
            trigger_timeframe="15m",
            evidence=[_EV("tlbreak", "t", "d", True, 2)],
            confirmations=[], warnings=[], mandatory_gates={"rr": True},
            market={"turnover24h": 1e9, "spread_pct": 0.02, "tick_size": 0.01},
            metadata={"atr": 1.0, "public_code": "NUM-1"},
            created_at=now.isoformat(timespec="seconds"),
            confirmed_at=now.isoformat(timespec="seconds"))
    c.metadata["target_ladder"] = _bl(c.planned_entry, c.sl, c.direction, c.market, c.tp2,
                                      structural_tp1=c.tp1, fee_pct=0.0018)
    tags = []
    orig = m7._level_tag
    def spy(ax, x, y, label, color):
        tags.append(label)
        return orig(ax, x, y, label, color)
    m7._level_tag = spy
    try:
        assert m7.generate_chart(frame, c, confirmed=True)
    finally:
        m7._level_tag = orig
    joined = " | ".join(tags)
    # bare numbers 1..3 (r40: TP4/TP5 removed; near-identical levels may
    # share one pill — the r22 _tol grouping); NO big TPxx labels on the tool.
    for i in range(1, 4):
        assert str(i) in joined, (i, joined)
    assert not any(t.strip().startswith("TP") for t in tags), joined
    # r32 (Viva 09-26, «لیبل‌های اطراف ابزار رو بردار»): ENTRY/FIRST STOP
    # pills are GONE from the tool column — numbers only; their values live
    # on the price axis + the bottom-right ledger.
    assert "ENTRY" not in joined and "FIRST STOP" not in joined


# ── Round-24b: the broken-blue-line law — «آیا این خط آبی شناسایی شده
#    بود؟؟» (five 09-24 schematics) ─────────────────────────────────────────
def test_recently_broken_rising_support_survives_and_travels():
    """A rising LOW line broken mid-frame with a close is the SHORT's evidence:
    detect_patterns must keep it (with break_x) and it must ride
    render_line_watch — the old anti-floating rules deleted it."""
    import dataclasses as dc
    from analysis.viva_tlbreak import fit_validated_line, load_config
    from analysis.render_kit import detect_patterns, _recently_broken
    n = 170
    rng = np.random.default_rng(31)
    # rising support touched 4×, broken down at bar 122 (mid-frame)
    lows = [(10, 100.0), (45, 101.6), (80, 103.2), (115, 104.8)]
    xs = np.array([p[0] for p in lows], float)
    ys = np.array([p[1] for p in lows], float)
    support = np.interp(np.arange(n, dtype=float), xs, ys)
    mid = support + 1.2 + rng.normal(0, 0.12, n)
    mid[122:] = support[122:] - 1.6 - np.linspace(0, 0.8, n - 122)
    df = pd.DataFrame({
        "timestamp": pd.date_range(end="2026-09-23 20:30", periods=n, freq="15min", tz="UTC"),
        "open": mid * 0.999, "high": mid * (1 + 0.004), "low": mid * (1 - 0.004),
        "close": mid, "volume": np.full(n, 1e6)})
    cfg = dc.replace(load_config(), pivot_left=3, pivot_right=3, min_touches=2,
                     touch_tolerance_atr=0.20, max_fit_residual_atr=0.45,
                     require_alive=True)
    ln = fit_validated_line(df, "LOW", cfg)
    assert ln is not None and ln.break_index is not None, "fixture must produce a broken line"
    assert _recently_broken(ln, n - 1)
    pats = detect_patterns(df, "SHORT")
    sides = [(p["type"], l.get("side"), l.get("break_x"))
             for p in pats for l in (p.get("lines") or [])]
    assert any(side == "LOW" and bx for _t, side, bx in sides), sides
