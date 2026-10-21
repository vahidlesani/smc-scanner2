"""Round 14b — a stop never collapses onto its own entry.

Live case that produced this file (Railway logs, deploy 2b9baa84, 09-21 00:16):

    🧱 SANITY_REJECT STOP_WRONG_SIDE • TRXUSDT DAYTRADE TLBREAK SHORT
       entry=0.34352 sl=0.34352 tp1=0.34077184 tp2=0.3297792 tf=15m

The lane had taken its stop from the last trigger candle's own extreme, and
that candle closed ON its high — so entry and stop were the same number and the
geometry net dropped the scenario. Viva's standing law is «استاپ … حذف نشه»:
the premise level must be rebuilt on the fatal side of the trigger frame
(structural extreme + the approved 0.10% buffer), not deleted and not left on
the entry.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analysis.setups_v7 as sv7
from analysis.models import SignalCandidate
from analysis.setups_v7 import _fatal_side_stop, drain_sanity_rejects, scan_setups
from analysis.trade_management import structural_buffer
from data.fetcher import MarketBundle

ENTRY = 0.34352  # the live TRXUSDT number, kept as a regression anchor


def _frame_last_close_at_high(n=40):
    """A rising 15m frame whose LAST candle closes exactly on its high — the
    exact shape that collapsed the stop onto the entry."""
    ts = pd.date_range("2026-09-21 00:00:00", periods=n, freq="15min")
    base = 0.3370
    rows = []
    for i in range(n):
        o = base + i * 0.00012
        c = o + 0.00018
        rows.append({"timestamp": ts[i], "open": o, "high": c + 0.00002,
                     "low": o - 0.00005, "close": c, "volume": 1000 + i})
    df = pd.DataFrame(rows)
    df.loc[df.index[-1], ["open", "high", "low", "close"]] = [0.34330, ENTRY, 0.34310, ENTRY]
    return df


def _degenerate_short():
    """The rejected candidate, reproduced."""
    return SignalCandidate(
        signal_id="test-round14b-short", symbol="TRXUSDT", style="DAYTRADE",
        setup_code="TLBREAK", setup_name="t", strategy_fa="t", direction="SHORT",
        score=7, status="WATCH", entry_zone_bottom=0.3430, entry_zone_top=0.3440,
        planned_entry=ENTRY, sl=ENTRY, tp1=0.34077184, tp2=0.3297792,
        rr_tp1=0.0, rr_tp2=0.0, bias="BEARISH", trigger_timeframe="15m",
        mandatory_gates={}, metadata={},
    )


# ── 1. the helper itself ───────────────────────────────────────────────────

def test_fatal_side_stop_short_is_above_entry_even_when_extreme_is_the_entry():
    df = _frame_last_close_at_high()
    buf = structural_buffer(ENTRY)
    sl = _fatal_side_stop(df, "SHORT", ENTRY, buf)
    assert sl > ENTRY, "a SHORT stop must sit above its entry"
    assert sl - ENTRY >= buf - 1e-12, "and at least one standard buffer away"


def test_fatal_side_stop_long_is_below_entry():
    df = _frame_last_close_at_high()
    low = float(df["low"].tail(8).min())  # the helper reads the last 8 bars
    buf = structural_buffer(ENTRY)
    sl = _fatal_side_stop(df, "LONG", ENTRY, buf)
    assert sl < ENTRY
    assert sl == pytest.approx(min(low, ENTRY) - buf, rel=1e-12)


def test_fatal_side_stop_prefers_the_structural_extreme_when_it_is_beyond_entry():
    df = _frame_last_close_at_high()
    buf = structural_buffer(ENTRY)
    # push one earlier candle well above the entry: the structural level must win
    df.loc[df.index[-4], "high"] = ENTRY * 1.004
    sl = _fatal_side_stop(df, "SHORT", ENTRY, buf)
    assert sl == pytest.approx(ENTRY * 1.004 + buf, rel=1e-12)


def test_fatal_side_stop_is_none_on_empty_input():
    assert _fatal_side_stop(None, "SHORT", ENTRY, 0.001) is None
    assert _fatal_side_stop(pd.DataFrame(), "SHORT", ENTRY, 0.001) is None


# ── 2. the funnel guard (the part that used to drop the scenario) ───────────

def _run_funnel(candidate, frame):
    drain_sanity_rejects()
    bundle = MarketBundle(symbol="TRXUSDT", frames={"15m": frame}, ticker={})
    original = sv7._active_detectors
    sv7._active_detectors = lambda: [lambda b, s: candidate]
    try:
        kept = scan_setups(bundle, "DAYTRADE")
    finally:
        sv7._active_detectors = original
    return kept, drain_sanity_rejects()


def test_funnel_reanchors_collapsed_stop_and_publishes():
    kept, rejects = _run_funnel(_degenerate_short(), _frame_last_close_at_high())
    assert rejects == [], rejects
    assert len(kept) == 1
    cand = kept[0]
    buf = structural_buffer(ENTRY)
    assert cand.sl > cand.planned_entry
    assert float(cand.sl) - float(cand.planned_entry) >= buf - 1e-12
    assert cand.metadata.get("stop_reanchored") is True
    # and the ceiling still owns the final number
    assert abs(float(cand.sl) - float(cand.planned_entry)) / float(cand.planned_entry) * 100 <= 1.25 + 1e-9


def test_funnel_leaves_a_healthy_stop_untouched():
    cand_in = _degenerate_short()
    cand_in.sl = ENTRY * 1.006  # a real structural stop, inside the 15m ceiling
    kept, rejects = _run_funnel(cand_in, _frame_last_close_at_high())
    assert rejects == []
    assert len(kept) == 1
    assert kept[0].sl == pytest.approx(cand_in.sl)
    assert not kept[0].metadata.get("stop_reanchored")


def test_funnel_reanchors_a_long_whose_stop_landed_on_the_entry():
    cand_in = _degenerate_short()
    cand_in.direction = "LONG"
    cand_in.planned_entry = ENTRY
    cand_in.sl = ENTRY
    cand_in.tp1 = ENTRY * 1.02
    cand_in.tp2 = ENTRY * 1.04
    kept, rejects = _run_funnel(cand_in, _frame_last_close_at_high())
    assert rejects == []
    assert len(kept) == 1
    assert kept[0].sl < kept[0].planned_entry
    assert kept[0].metadata.get("stop_reanchored") is True


def test_guard_is_silent_when_the_frame_is_missing():
    """Fail-open: no frame → nothing changes, and the sanity net still owns the
    final call (it is the only thing allowed to drop a scenario)."""
    cand_in = _degenerate_short()
    kept, rejects = _run_funnel(cand_in, _frame_last_close_at_high())
    assert len(kept) == 1
    # with no usable frame the guard must not invent a number
    assert kept[0].sl > 0
    assert rejects == []
