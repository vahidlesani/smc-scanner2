"""Round-23 law guard — the tz-plane hole that killed the BREAK-SIDE LAW.

Audit of the parallel-branch commits (09bd0a1 / 460a45c / f93f8f2) plus the
09-23/09-24 annotated screenshots exposed the REAL production defect: live
closed frames are tz-AWARE while metadata anchor timestamps are tz-NAIVE, so
`_project_watch_level` raised TypeError inside a silent `except: continue`
and the break-side veto NEVER ran in production — BTC/ADA/RENDER-style 1H
LONGs confirmed UNDER their broken support line («شکست این ترد نزولیه؛
ریجکتش هم نزولیه» violated). These tests pin the law on BOTH tz planes so a
tz regression can never silently kill it again.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.models import SignalCandidate
from analysis.quality_engine import (
    _project_watch_level,
    evaluate_confirmation,
)


def _frame(tz: str, closes_tail, base: float = 84300.0) -> pd.DataFrame:
    idx = pd.date_range(end="2026-09-23 18:00", periods=40, freq="1h", tz=tz)
    close = np.full(40, base)
    close[-len(closes_tail):] = closes_tail
    return pd.DataFrame({
        "timestamp": idx, "open": close - 100, "high": close + 400,
        "low": close - 500, "close": close, "volume": np.full(40, 1e6),
    })


def _candidate(direction: str, watch: list[dict], pin_hi: float, pin_lo: float,
               entry: float, sl: float, tp1: float, tp2: float) -> SignalCandidate:
    md = {"atr": 1200.0, "touched": True, "pin_low": pin_lo, "pin_high": pin_hi,
          "render_line_watch": watch}
    c = SignalCandidate(
        signal_id="lawguard-r23", symbol="BTCUSDT", style="SWING",
        setup_code="PINVAL", setup_name="پین‌بار", strategy_fa="تست",
        direction=direction, score=9, status="PENDING",
        entry_zone_bottom=entry * 0.997, entry_zone_top=entry * 1.001,
        planned_entry=entry, sl=sl, tp1=tp1, tp2=tp2,
        rr_tp1=1.5, rr_tp2=4.0,
        bias="BULLISH" if direction == "LONG" else "BEARISH",
        trigger_timeframe="1h", metadata=md, mandatory_gates={"zone": True})
    c.created_at = "2026-09-23 08:00:00+00:00"
    return c


_SUPPORT_LINE = [{"side": "LOW", "log_fit": False,
                  "p0": {"ts": "2026-09-20 12:00", "price": 81500.0},
                  "p1": {"ts": "2026-09-23 06:00", "price": 85480.0}}]


def test_watch_level_projection_same_on_both_tz_planes():
    """aware frame vs naive anchors must equal naive-vs-naive (the audit hole)."""
    aware = pd.Timestamp("2026-09-23 18:00", tz="UTC")
    naive = pd.Timestamp("2026-09-23 18:00")
    a = _project_watch_level(_SUPPORT_LINE[0], aware)
    n = _project_watch_level(_SUPPORT_LINE[0], naive)
    assert abs(a - n) < 1e-6
    assert abs(a - 86203.6) < 50.0  # chord extrapolation, not y1


def test_long_under_broken_support_is_rejected_tz_aware():
    """The exact BTC-1H K211718 scenario on a LIVE (tz-aware) frame."""
    df = _frame("UTC", [85000, 84800, 84600, 84400, 84350, 84279])
    ok, cand, _msg = evaluate_confirmation(_candidate(
        "LONG", _SUPPORT_LINE, 84100.0, 83800.0,
        84279.9, 81962.2, 85644.9, 87364.5), df, None)
    assert not ok
    assert cand.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH"


def test_long_under_broken_support_is_rejected_tz_naive():
    """Same scenario on a naive frame — both planes must veto identically."""
    df = _frame(None, [85000, 84800, 84600, 84400, 84350, 84279])
    ok, cand, _msg = evaluate_confirmation(_candidate(
        "LONG", _SUPPORT_LINE, 84100.0, 83800.0,
        84279.9, 81962.2, 85644.9, 87364.5), df, None)
    assert not ok
    assert cand.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH"


def test_short_over_broken_resistance_is_rejected_tz_aware():
    """Mirror law: SHORT after a close ABOVE the broken resistance line."""
    res_line = [{"side": "HIGH", "log_fit": False,
                 "p0": {"ts": "2026-09-20 12:00", "price": 89500.0},
                 "p1": {"ts": "2026-09-23 06:00", "price": 85200.0}}]
    df = _frame("UTC", [85600, 85700, 85800, 85900, 86000, 86100])
    ok, cand, _msg = evaluate_confirmation(_candidate(
        "SHORT", res_line, 86150.0, 85850.0,
        86100.0, 87200.0, 84800.0, 82900.0), df, None)
    assert not ok
    assert cand.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH"


def test_long_respecting_support_still_confirms():
    """No false veto: closes ABOVE the (unbroken) support must still confirm."""
    df = _frame("UTC", [86250, 86300, 86350, 86400, 86450, 86500], base=86200.0)
    ok, cand, _msg = evaluate_confirmation(_candidate(
        "LONG", _SUPPORT_LINE, 86150.0, 85900.0,
        86200.0, 84200.0, 87500.0, 89400.0), df, None)
    assert ok, cand.metadata.get("last_reject_code")


# ── r23 pill-column relayout (the ADA ENTRY×LIVE / RENDER ENTRY×TP1 /
#    TAO LIVE×chip overlaps on the fresh deploy) ────────────────────────────
from bot.messages_v7 import _relayout_pills


def test_relayout_pills_never_folds_two_rows():
    import random
    rng = random.Random(7)
    for _ in range(2000):
        lo, hi = 2.5, 97.5
        n = rng.randint(2, 8)
        rows = [[rng.uniform(0.0, 100.0), f"p{i}", "#000"] for i in range(n)]
        _relayout_pills(rows, lo, hi, 3.6)
        ys = [r[0] for r in rows]
        assert all(ys[i + 1] - ys[i] >= 3.6 - 1e-9 for i in range(len(ys) - 1)), ys
        assert ys[-1] <= hi + 1e-9
        assert ys[0] >= lo - 1e-9


def test_relayout_pills_dense_cluster_at_edge():
    """The live ADA case: ENTRY+LIVE clamped onto nearly the same y at the
    bottom edge — must separate, stay inside, keep every row present."""
    rows = [[10.0, " LIVE 0.237 ", "#111"], [10.05, " ENTRY 0.2392 ", "#00c"],
            [10.02, " TP1 0.2403 ", "#0a5"], [80.0, " FIRST STOP 0.2326 ", "#c33"]]
    _relayout_pills(rows, 2.5, 97.5, 3.6)
    ys = sorted(r[0] for r in rows)
    assert all(b - a >= 3.6 - 1e-9 for a, b in zip(ys, ys[1:]))
    assert 2.5 - 1e-9 <= ys[0] and ys[-1] <= 97.5 + 1e-9
    assert len(rows) == 4


def test_relayout_pills_degenerate_panel_never_collapses():
    """Impossible on real charts (3 pills in a 2.24-wide band): rows must stay
    DISTINCT, ordered and inside — reduced step, never one printed line."""
    rows = [[50.0, "a", ""], [50.0, "b", ""], [50.0, "c", ""]]
    _relayout_pills(rows, 0.0, 8.0, 3.6)
    ys = sorted(r[0] for r in rows)
    assert len(set(ys)) == 3
    assert ys[0] >= -1e-9 and ys[-1] <= 8.0 + 1e-9
