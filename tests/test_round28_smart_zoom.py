"""r28: the smart-chart round — «لطفا دقیق بررسی کن ببین اشکال از کجاست».

Root causes found in code (evidence, not guesswork):
- DASH 1D crammed into the top 5%: the old y-finalize took min()/max() of
  candles ∪ entry ∪ SL ∪ TP with only 6% padding — a far stop (13.3 vs price
  62) stretched the axis 5×.
- WLD 1H 80%-filled 5-cent span: no floor, no occupancy target at all.
- RENDER 4H «X»: TECHCLASSIC pattern lines reused the TLBREAK full-frame
  left-extension and cut a chart-edge diagonal across the whole tape.
- Update spam: heartbeat = one «🕐 این کندل بسته شد…» per closed candle per
  chain, capped at 12, each with a NEW countdown → content-hash never
  swallowed it; each carried a full chart re-render (Railway CPU).
"""
from __future__ import annotations

import importlib
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


def _win():
    from bot.messages_v7 import _smart_y_window
    return _smart_y_window


def test_dash_case_candles_never_crammed_at_top():
    """The live evidence: DASH 1D, candles 55–65, stop dragged to 13.3.
    The window must keep the candle box mid-frame (occupancy ≥ 35%) instead
    of stretching to 10–80."""
    f = _win()
    out = f(55.0, 65.0, atr=4.0, ov_lo=13.3, ov_hi=65.0)
    assert out is not None
    ylo, yhi = out
    span = yhi - ylo
    occ = 10.0 / span
    assert occ >= 0.34, (ylo, yhi, occ)
    assert ylo > 40.0, "a far stop may not drag the axis to the basement"
    assert ylo < 55.0 < yhi


def test_wld_case_tight_span_gets_structure_room():
    """The live evidence: WLD 1H, ~5-cent span filling 80% of the frame.
    The floor (4×ATR) + 72% occupancy must open the window so patterns and
    the long/short tool read sensibly."""
    f = _win()
    out = f(0.42, 0.48, atr=0.008)
    ylo, yhi = out
    span = yhi - ylo
    assert span >= 4.0 * 0.008 * 0.98, "4×ATR floor"
    occ = 0.06 / span
    assert occ <= 0.80, (span, occ)
    # r37 (Viva 09-26, «کندلها تا حد امکان در مرکز صفحه چارت»): the window is
    # now CENTERED on the candle block, so the pad is symmetric — ylo may sit
    # a hair under the old one-sided 0.40 bound.
    assert 0.39 <= ylo and yhi <= 0.51


def test_nearby_levels_are_included_fully():
    """Healthy case: entry/SL/TP close to the tape stay inside the window —
    the cap only fights FAR overlays, never the normal plan."""
    f = _win()
    ylo, yhi = f(97.0, 103.0, atr=1.2, ov_lo=95.8, ov_hi=104.5)
    assert ylo <= 95.8 and yhi >= 104.5


def test_degenerate_inputs_return_none_and_fallback_keeps_working():
    f = _win()
    assert f(5.0, 5.0, atr=1.0) is None
    assert f(float("nan"), 10.0, atr=1.0) is None
    # atr garbage → span/10 fallback, still a sane window
    ylo, yhi = f(100.0, 106.0, atr=float("nan"))
    assert 94 <= ylo and yhi <= 112


def test_heartbeat_cap_is_three():
    """«حتما نباید اینقدر آپدیت‌های بی‌خاصیت بیاد» — the per-candle heartbeat
    default drops 12 → 3 (env MAX_CHAIN_HEARTBEATS still overrides)."""
    import subprocess
    assert config.Settings.max_chain_heartbeats == 3
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "main.py"), encoding="utf-8").read()
    assert "max_chain_heartbeats" in src, "main must read the config knob"


def test_smart_zoom_wired_and_tc_lines_pivot_local():
    """Law + test same commit: the finalize block calls _smart_y_window and
    TECHCLASSIC (tc_clean) lines skip the full-frame left extension."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "ax.set_ylim(*_win28)" in src
    assert 'if md.get("tc_clean"):' in src
    assert "_smart_y_window(" in src
