"""r61.3-R62 round-2 (his 10-01 gallery + correction).

* TECHCLASSIC/TLBREAK revival: the r61.2 source-kill is GONE — a break whose
  newest close pulled back through the line still emits its event (the
  confirm-stage BREAK_RECLAIMED gate + ONE-BREAK law own the veto now).
* Pre-break ceiling law: a PINVAL/rejection chain may not CONFIRM toward a
  facing untouched wall (ATOM/VVV/LIT/JUP class) — CEILING_AHEAD, chain
  alive; a close beyond the wall confirms.
* Earlier-pivot law: a fitted trendline absorbs earlier collinear pivots
  (VVV: «به پیوت‌های قبل‌تر هم برخورد می‌کنند باید رسم بشن»).
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 1. source-kill removed (contract) ───────────────────────────────────────

def test_reclaim_source_kill_removed():
    src = open("analysis/pattern_engine.py", encoding="utf-8").read()
    seg = src[src.index("RECLAIM REBALANCE"):]
    seg = seg[:seg.index("def ", 1)]
    assert "if not _still61:\n                continue" not in src, (
        "the r61.2 source-kill still suppresses break events")
    assert "_reclaim61 = bool(state == STATE_BREAK and not _still61)" in src
    assert '"reclaimed_seen": _reclaim61' in src


# ── 2. pre-break ceiling gate ───────────────────────────────────────────────

def _cand(setup="PINVAL", direction="LONG"):
    from analysis.models import SignalCandidate
    return SignalCandidate(
        signal_id="R613B-1", symbol="VVVUSDT", style="SWING",
        setup_code=setup, setup_name="t", strategy_fa="t",
        direction=direction, score=9, status="APPROACHING",
        entry_zone_bottom=27.9, entry_zone_top=28.15,
        planned_entry=28.05, sl=27.5, tp1=28.6, tp2=29.0,
        rr_tp1=1.5, rr_tp2=2.5, bias="BULL", trigger_timeframe="15m",
        mandatory_gates={"zone": True},
        created_at="2026-10-01T09:00:00+00:00",
        metadata={"atr": 0.35, "touched": True, "confirm_tf": "15m"})


def _frame(closes, walls=None, start="2026-10-01 09:00", freq="15min"):
    """closes + a supply shelf: `walls` = list of bar offsets whose HIGH pins
    the wall price (three+ pivots make a real wall for the polarity engine)."""
    n = len(closes)
    ts = pd.date_range(start, periods=n, freq=freq)
    base_lo = min(closes) - 1.0
    highs = [c + 0.10 for c in closes]
    lows = [c - 0.10 for c in closes]
    opens = [c - 0.02 for c in closes]
    for off, px in (walls or []):
        off = int(off)
        if off < 0:
            off = n + off
        if 0 <= off < n:
            highs[off] = px
            opens[off] = px - 0.12
            lows[off] = px - 0.18
            closes[off] = px - 0.14
    return pd.DataFrame({"timestamp": ts, "open": opens, "high": highs,
                         "low": lows, "close": closes,
                         "volume": [900.0] * n})


def _pad(closes, walls=None):
    vals = [float(c) for c in closes]
    pads = [vals[0] - 1.6 - 0.01 * i for i in range(70)]
    allc = pads + vals
    w = [(i + len(pads), px) for i, px in (walls or [])]
    return _frame(allc, walls=w)


def test_long_toward_untouched_supply_is_rejected_ceiling_ahead():
    from analysis.quality_engine import evaluate_confirmation
    # confirming close 28.05; wall (supply shelf) at ~28.45 ≈ 1.15 ATR ahead
    closed = _pad([27.85, 27.95, 28.05], walls=[(-12, 28.30), (-9, 28.44),
                                                (-6, 28.30), (-3, 28.44)])
    closed = closed.set_index(pd.DatetimeIndex(closed["timestamp"]))
    ok, c2, reason = evaluate_confirmation(_cand(), closed)
    assert ok is False, reason
    assert c2.metadata.get("last_reject_code") == "CEILING_AHEAD", reason


def test_long_beyond_the_wall_confirms():
    from analysis.quality_engine import evaluate_confirmation
    # confirming close 29.05 clears the 28.615 wall-top by a ≥0.5·ATR body
    # → the wall is VALIDLY BROKEN → the break is the law
    cand = _cand()
    cand.metadata["atr"] = 0.5
    cand.entry_zone_bottom, cand.entry_zone_top = 28.95, 29.15
    cand.planned_entry = 29.05
    cand.tp1, cand.tp2 = 29.5, 29.9
    closed = _pad([28.85, 28.95, 29.05], walls=[(-14, 28.45), (-8, 28.45),
                                                (-6, 28.45), (-4, 28.45)])
    # the breakout candle must carry a directional body ≥ 0.5·ATR
    closed.iloc[-1, closed.columns.get_loc("open")] = 28.55
    closed = closed.set_index(pd.DatetimeIndex(closed["timestamp"]))
    ok, c2, reason = evaluate_confirmation(cand, closed)
    assert ok is True, reason


# ── 3. earlier-pivot absorption in the fitter ────────────────────────────────

def _liftape():
    ts = pd.date_range("2026-09-20", periods=90, freq="15min")
    # rising support through four LOW pivots at i=2,15,40,65 — the dips sit
    # exactly on y = 98.8 + 0.1·i; neighbours stay clearly above the line.
    closes, highs, lows = [], [], []
    for i in range(90):
        base = 100.0 + i * 0.1
        bump = -0.8 if i in (2, 15, 40, 65) else 0.0
        lows.append(base - 0.4 + bump)
        closes.append(base + 0.6)
        highs.append(base + 1.0)
    return pd.DataFrame({"timestamp": ts, "open": [c - 0.05 for c in closes],
                         "high": highs, "low": lows, "close": closes,
                         "volume": [100.0] * 90})


def test_fit_absorbs_earlier_collinear_pivot():
    import dataclasses as dc
    from analysis.viva_tlbreak import fit_validated_line, load_config
    f = _liftape().reset_index(drop=True)
    cfg = dc.replace(load_config(), pivot_left=3, pivot_right=3,
                     min_touches=2, touch_tolerance_atr=0.25,
                     max_fit_residual_atr=0.60, require_alive=False,
                     wick_policy="hybrid")
    ln = fit_validated_line(f, "LOW", cfg)
    assert ln is not None
    # the line through the three lows: 100 + i*0.1 (± tol) — the earliest
    # collinear pivot (i=15) must be INSIDE the line's anchor span
    assert int(ln.first_index) <= 16, (
        f"fitter anchored late at {ln.first_index}; earlier pivot not absorbed")
    assert ln.touch_count >= 3
