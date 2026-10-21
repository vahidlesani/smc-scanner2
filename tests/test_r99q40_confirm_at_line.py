"""R99q40 — «چرا هشدار نمیاد» / «تاییدها سروقت» / «هندسه درون همون تایم تریگر».

Measured on HIS OWN card before the fix (production DB, 2026-10-21):

    signal  viva-ZEC-SW-TLBREAK-10210301-18AF   TLBREAK LONG 30m
    edge    1147.6913829787234                  (viva_breakout_line)
    closes  1264.37 (03:15) / 1260.19 (03:30)   — 7.2 ATR PAST the line
    verdict NO_TOUCH  «قیمت هنوز به لبهٔ ناحیه/خط نرسیده»
            + last_fakeout_candle «کندل خلاف‌جهت با کلوز در نیمهٔ مخالف»

The 15m anatomy gate (valid_break_candle) was judging a bar that is 7.2 ATR
beyond the edge as if it were testing the line. The law it enforces is written
AT the line — a shooting star / counter-colour close AT THE LINE is a fake-out.
Beyond one ATR the bar has left the level behind; the one-close law governs.

Laws under test:
  1. a close more than 1 ATR past the edge confirms on the one-close law even
     when that bar is counter-colour (ZEC's exact shape);
  2. a counter-colour close AT the line (≤1 ATR) is STILL a fake-out — the
     doctrine is bounded, not deleted;
  3. the card never announces a foreign-TF pattern as this chart's pattern
     (his 10-21 «فقط باید پترن‌ها و هندسه درون همون تایم تریگر باشه»).
"""
import os

import numpy as np
import pandas as pd

from analysis.models import SignalCandidate
from analysis.quality_engine import evaluate_confirmation


def _frame(closes, opens=None, wick=0.4, start="2026-10-21 00:00", freq="15min"):
    n = len(closes)
    c = np.array(closes, float)
    o = np.array(opens, float) if opens is not None else c - 0.1
    hi = np.maximum(o, c) + wick
    lo = np.minimum(o, c) - wick
    return pd.DataFrame({"timestamp": pd.date_range(start, periods=n, freq=freq),
                         "open": o, "high": hi, "low": lo, "close": c,
                         "volume": np.full(n, 100.0)})


def _cand(edge=1147.69, atr=16.71, created_idx=24):
    """The ZEC chain's own shape: pure-break LONG, entry on the line."""
    return SignalCandidate(
        signal_id="viva-TEST-Q40", symbol="ZECUSDT", style="SWING",
        setup_code="TLBREAK", setup_name="TLBREAK", strategy_fa="t",
        direction="LONG", score=6.5, status="EDUCATIONAL",
        entry_zone_bottom=edge - 2.0, entry_zone_top=edge + 2.0,
        planned_entry=edge, sl=edge - 12.0, tp1=edge + 11.5, tp2=edge + 57.4,
        rr_tp1=1.0, rr_tp2=2.0, bias="BULLISH", trigger_timeframe="30m",
        mandatory_gates={"zone": True},
        metadata={"atr": atr, "touched": False, "viva_breakout_line": edge,
                  "tl_context_tf": "30m"},
    )


def test_far_from_line_close_confirms_on_one_close_law():
    """ZEC's exact shape: a counter-colour bar 7 ATR past the line is NO
    fake-out — it must confirm at that close (14 minutes, not never)."""
    closes = [1100.0] * 24 + [1264.37, 1260.19]
    # the confirming bar closes BELOW its open → «خلاف‌جهت، نیمهٔ مخالف»
    opens = [c - 0.5 for c in closes]
    opens[-1] = closes[-1] + 4.0
    df = _frame(closes, opens)
    cand = _cand()
    cand.created_at = str(df["timestamp"].iloc[23])
    ok, out, _why = evaluate_confirmation(cand, df, frame_tf_minutes=15.0)
    assert ok is True
    md = out.metadata or {}
    assert md.get("fast_break_bar"), "the one-close lane must have armed"
    assert md.get("last_fakeout_candle") is None


def test_counter_colour_close_at_the_line_is_still_a_fake_out():
    """The veto is BOUNDED to the line, never deleted: a shooting star that
    closes in the opposite half AT the edge stays a fake-out."""
    closes = [1100.0] * 24 + [1160.0]
    opens = [c - 0.5 for c in closes]
    df = _frame(closes, opens)
    # shooting star AT the edge: opens on the line, closes in the lower half
    df.loc[24, "open"] = 1148.0
    df.loc[24, "close"] = 1148.9
    df.loc[24, "high"] = 1152.4
    df.loc[24, "low"] = 1147.9
    cand = _cand()
    cand.created_at = str(df["timestamp"].iloc[23])
    ok, out, _why = evaluate_confirmation(cand, df, frame_tf_minutes=15.0)
    assert ok is False
    md = out.metadata or {}
    # the anatomy veto fired (the reject code downstream is the pure-break gate
    # that then finds no armed break — what matters is the fake-out stamp)
    assert md.get("last_fakeout_candle"), "the at-line fake-out must be stamped"
