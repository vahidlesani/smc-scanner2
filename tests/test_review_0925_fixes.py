"""Regression tests for the 09-25 code review fixes.

1. Fast-lane edge: the trendline is evaluated at the bar's real timestamp and
   extrapolated (was: integer row index → first anchor price; TypeError on
   tz-aware frames).
2. A rejected evaluation restores the plan (entry/SL/TP) and never leaves
   technical_confirmation_complete behind (counter-trend gate bypass).
3. ALBROX fires only on a FRESH base break.
4. PINWALLQ first-visit credit is measured on the tape, not granted for free.
5. No undefined names / use-before-assignment anywhere in the runtime code.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
import pytest

from analysis.models import SignalCandidate
from analysis.quality_engine import evaluate_confirmation

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """The counter-trend gate fetches the parent TF — keep tests hermetic."""
    import data.fetcher as fetcher
    monkeypatch.setattr(fetcher, "get_klines", lambda *a, **k: None)


# ── 1. fast-lane trendline edge ─────────────────────────────────────────────

def _tl_frame(tz, last_close=101.8):
    idx = pd.date_range(end="2026-09-23 18:00", periods=40, freq="1h", tz=tz)
    close = np.full(40, 100.0)
    close[-1] = last_close
    return pd.DataFrame({"timestamp": idx, "open": close - 0.3, "high": close + 0.5,
                         "low": close - 0.5, "close": close, "volume": 1e6})


def _tl_candidate(df):
    ts = df["timestamp"]
    # descending resistance: 120 at bar 0 → 110 at bar 20 → 100.5 at bar 39
    md = {"atr": 1.0, "touched": True,
          "tl_a_ts": str(ts.iloc[0]), "tl_a_price": 120.0,
          "tl_b_ts": str(ts.iloc[20]), "tl_b_price": 110.0,
          "viva_breakout_line": 101.0}
    c = SignalCandidate(
        signal_id="r0925-tl", symbol="XUSDT", style="SWING", setup_code="TLBREAK",
        setup_name="t", strategy_fa="t", direction="LONG", score=9, status="PENDING",
        entry_zone_bottom=100.5, entry_zone_top=101.0, planned_entry=101.0, sl=99.5,
        tp1=103.0, tp2=105.0, rr_tp1=1.5, rr_tp2=3.0, bias="BULLISH",
        trigger_timeframe="1h", metadata=md, mandatory_gates={"zone": True})
    c.created_at = str(ts.iloc[30])
    return c


@pytest.mark.parametrize("tz", [None, "UTC"])
def test_fast_lane_uses_projected_trendline_at_bar_time(tz):
    df = _tl_frame(tz)
    ok, cand, msg = evaluate_confirmation(_tl_candidate(df), df)
    assert ok, (cand.metadata.get("last_reject_code"), msg)
    # the level is the line AT the break bar (≈100.5), not the first anchor (120)
    assert abs(float(cand.metadata["confirm_level_used"]) - 100.5) < 0.05
    assert str(cand.metadata["fast_break_bar"]).startswith("2026-09-23")


@pytest.mark.parametrize("tz", [None, "UTC"])
def test_fast_lane_ignores_close_still_under_the_line(tz):
    df = _tl_frame(tz, last_close=100.3)          # line at the bar ≈ 100.5
    ok, cand, _ = evaluate_confirmation(_tl_candidate(df), df)
    assert not cand.metadata.get("tl_fast_break")


# ── 2. rejected evaluation leaves no trace ─────────────────────────────────

def _pin_frame(closes_tail, base=86200.0):
    idx = pd.date_range(end="2026-09-23 18:00", periods=40, freq="1h", tz="UTC")
    close = np.full(40, base)
    close[-len(closes_tail):] = closes_tail
    return pd.DataFrame({"timestamp": idx, "open": close - 100, "high": close + 400,
                         "low": close - 500, "close": close, "volume": np.full(40, 1e6)})


def _pin_candidate(sl=84200.0, score=9, **md_extra):
    md = {"atr": 1200.0, "touched": True, "pin_low": 85900.0, "pin_high": 86150.0}
    md.update(md_extra)
    c = SignalCandidate(
        signal_id="r0925-pin", symbol="BTCUSDT", style="SWING", setup_code="PINVAL",
        setup_name="p", strategy_fa="p", direction="LONG", score=score, status="PENDING",
        entry_zone_bottom=86200.0 * 0.997, entry_zone_top=86200.0 * 1.001,
        planned_entry=86200.0, sl=sl, tp1=87500.0, tp2=89400.0, rr_tp1=1.5, rr_tp2=4.0,
        bias="BULLISH", trigger_timeframe="1h", metadata=md,
        mandatory_gates={"zone": True})
    c.created_at = "2026-09-23 08:00:00+00:00"
    return c


def test_baseline_pin_candidate_confirms():
    df = _pin_frame([86250, 86300, 86350, 86400, 86450, 86500])
    ok, cand, _ = evaluate_confirmation(_pin_candidate(), df)
    assert ok, cand.metadata.get("last_reject_code")
    assert cand.status == "CONFIRMED"
    assert cand.metadata.get("technical_confirmation_complete") is True


def test_counter_trend_reject_does_not_arm_publication_retry():
    df = _pin_frame([86250, 86300, 86350, 86400, 86450, 86500])
    cand = _pin_candidate(tl_context_conflict=True)
    ok, cand, _ = evaluate_confirmation(cand, df)
    assert not ok
    assert cand.metadata.get("last_reject_code") == "COUNTER_TREND_TOUCH_ONLY"
    # main.monitor_candidates republishes anything with this flag set
    assert not cand.metadata.get("technical_confirmation_complete")
    assert cand.status == "PENDING"
    assert not cand.confirmed_at


def test_rejected_evaluation_restores_clamped_stop():
    df = _pin_frame([86250, 86300, 86350, 86400, 86450, 86500])
    far_sl = 80000.0                        # 7% away → clamped at the 1h ceiling
    cand = _pin_candidate(sl=far_sl, score=4)   # 4+1 < EXECUTION_MIN_SCORE → reject
    ok, cand, _ = evaluate_confirmation(cand, df)
    assert not ok
    assert cand.sl == far_sl
    assert cand.planned_entry == 86200.0
    assert "stop_clamped" not in cand.metadata


# ── 3. ALBROX fresh break ───────────────────────────────────────────────────

def _albrox_df(stale: bool):
    n = 130
    idx = pd.date_range(end="2026-09-23 18:00", periods=n, freq="15min")
    close = np.full(n, 100.0) + np.sin(np.arange(n)) * 0.1
    high, low, open_ = close + 0.5, close - 0.5, close - 0.1
    s = n - 15                                   # spike bar
    low[s], high[s], open_[s], close[s] = 90.0, 100.5, 100.0, 97.0
    for i in range(s + 1, n - 1):                # compact base 96.5–97.5
        open_[i], close[i], high[i], low[i] = 96.9, 97.0, 97.5, 96.5
    if stale:                                    # an EARLIER close broke the base
        close[n - 3], high[n - 3] = 98.2, 98.4
    open_[-1], close[-1], high[-1], low[-1] = 97.2, 98.6, 98.7, 97.1
    return pd.DataFrame({"timestamp": idx, "open": open_, "high": high, "low": low,
                         "close": close, "volume": 1e6})


def _run_albrox(monkeypatch, df):
    import analysis.setups_experimental as se
    from analysis.setups_v7 import timeframe_profile
    from data.fetcher import MarketBundle

    def fake_base(bundle, style, code, direction, *a, **k):
        return SignalCandidate(
            signal_id="alb", symbol=bundle.symbol, style=style, setup_code=code,
            setup_name=code, strategy_fa=code, direction=direction, score=8,
            status="EDUCATIONAL", entry_zone_bottom=96.5, entry_zone_top=97.5,
            planned_entry=float(df["close"].iloc[-1]), sl=96.0, tp1=100.0, tp2=102.0,
            rr_tp1=1.0, rr_tp2=2.0, bias="BULLISH", trigger_timeframe="15m",
            metadata={}, mandatory_gates={})

    monkeypatch.setattr(se, "_base_candidate", fake_base)
    monkeypatch.setattr(se, "detect_pinbar_zone", lambda *a, **k: None)
    tfs = set(timeframe_profile("DAYTRADE"))
    bundle = MarketBundle(symbol="XUSDT", frames={tf: df for tf in tfs})
    return se.detect_albrox(bundle, "DAYTRADE")


def test_albrox_fires_on_fresh_base_break(monkeypatch):
    cand = _run_albrox(monkeypatch, _albrox_df(stale=False))
    assert cand is not None and cand.direction == "LONG"


def test_albrox_ignores_stale_base_break(monkeypatch):
    assert _run_albrox(monkeypatch, _albrox_df(stale=True)) is None


# ── 4. PINWALLQ first visit ─────────────────────────────────────────────────

def _visit_df(prior_low: float):
    n = 40
    close = np.full(n, 105.0)
    df = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5,
                       "close": close})
    df.loc[10, "low"] = prior_low           # an earlier visit (or not)
    df.loc[n - 1, ["open", "high", "low", "close"]] = [100.6, 101.0, 100.0, 100.8]
    return df


def test_first_visit_true_on_untested_level():
    from analysis.setups_experimental import _pin_first_visit
    assert _pin_first_visit(_visit_df(prior_low=104.5), "LONG", 1.0) is True


def test_first_visit_false_when_level_was_already_tested():
    from analysis.setups_experimental import _pin_first_visit
    assert _pin_first_visit(_visit_df(prior_low=99.9), "LONG", 1.0) is False


def test_first_visit_credited_for_sweep_and_reclaim():
    from analysis.setups_experimental import _pin_first_visit
    # prior low 100.2, pin probes 100.0 and closes back above → liquidity grab
    assert _pin_first_visit(_visit_df(prior_low=100.2), "LONG", 1.0) is True


# ── 5. static safety net ────────────────────────────────────────────────────

def test_no_undefined_names_in_runtime_code():
    """NameError / UnboundLocalError class bugs hide behind broad `except`
    blocks in this codebase (F1/F2 in the 09-14 audit, `_atr`/`_pos` in the
    09-25 review). pyflakes catches them statically."""
    pyflakes_api = pytest.importorskip("pyflakes.api")
    from pyflakes import messages as m
    from pyflakes.checker import Checker
    import ast

    bad_types = (m.UndefinedName, m.UndefinedLocal, m.UndefinedExport)
    offenders = []
    for p in REPO.rglob("*.py"):
        rel = p.relative_to(REPO)
        if rel.parts[0] in {"tests", ".git"} or "__pycache__" in rel.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(rel))
        for msg in Checker(tree, filename=str(rel)).messages:
            if isinstance(msg, bad_types):
                offenders.append(str(msg))
    assert not offenders, "\n".join(offenders)
    assert pyflakes_api  # imported for the skip guard
