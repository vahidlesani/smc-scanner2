"""Round-12 rulings (Viva 09-21) — break side, honest stops, stop horizon.

His questions, verbatim:
  • «چرا بعد از شکست ترند رو به بالا پوزیشن شورت اعلان میشه توی برخی ستاپها؟»
  • «چرا بعد از شکست الگوها یا ترند به سمت پایین و کلوز بعدش … لانگ اعلام میکنه؟»
  • «حدود ۱۲ درصد استاپ؟؟ … جای استاپ ها هم امیدوارم فهمیده باشی چی بذاری»
"""
from __future__ import annotations

import io

import pandas as pd

from analysis.trade_management import target_distance_cap_pct


def _candidate(direction="SHORT", **over):
    from analysis.models import SignalCandidate
    base = dict(signal_id="R12", symbol="TESTUSDT", style="DAYTRADE", setup_code="TLBREAK",
                setup_name="t", strategy_fa="t", direction=direction, score=8,
                status="NEAR_CONFIRM", entry_zone_bottom=99.0, entry_zone_top=100.0,
                planned_entry=100.0, sl=98.0 if direction == "LONG" else 102.0,
                tp1=101.0 if direction == "LONG" else 99.0,
                tp2=104.0 if direction == "LONG" else 96.0,
                rr_tp1=1.0, rr_tp2=2.0, bias="BEAR" if direction == "SHORT" else "BULL",
                trigger_timeframe="15m", mandatory_gates={"zone": True},
                metadata={"atr": 1.0, "touched": True})
    base.update(over)
    return SignalCandidate(**base)


def _frame(rows):
    return pd.DataFrame([{"timestamp": pd.Timestamp("2026-09-21 10:00") + pd.Timedelta(minutes=15 * i),
                          "open": o, "high": h, "low": l, "close": c, "volume": v}
                         for i, (o, h, l, c, v) in enumerate(rows)])


# ── the break-side law ───────────────────────────────────────────────────
def test_short_after_an_upward_break_is_rejected():
    """His DASH case: the descending trend was broken UP with a close, yet a
    short was announced. The projection of the high-side line at the confirm
    bar sits BELOW the close → the premise is gone."""
    from analysis.quality_engine import evaluate_confirmation
    rows = [(100.0, 100.2, 99.8, 100.0, 1000.0)] * 24
    rows.append((100.1, 101.4, 100.0, 101.2, 1800.0))       # closes ABOVE the line
    df = _frame(rows)
    cand = _candidate("SHORT", sl=103.0)                     # stop far above
    cand.metadata["render_line_watch"] = [{
        "side": "HIGH", "slope": -0.01, "intercept": 100.9,
        "p0": {"ts": "2026-09-21 09:00", "price": 101.1},
        "p1": {"ts": "2026-09-21 15:45", "price": 100.7}}]
    ok, cand, _r = evaluate_confirmation(cand, df)
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH"


def test_long_after_a_downward_break_is_rejected():
    from analysis.quality_engine import evaluate_confirmation
    rows = [(100.0, 100.2, 99.8, 100.0, 1000.0)] * 24
    rows.append((100.0, 100.1, 98.6, 98.8, 1800.0))         # closes BELOW the support
    df = _frame(rows)
    cand = _candidate("LONG", sl=97.0)                       # stop far below
    cand.metadata["render_line_watch"] = [{
        "side": "LOW", "slope": 0.0, "intercept": 99.9,
        "p0": {"ts": "2026-09-21 09:00", "price": 99.9},
        "p1": {"ts": "2026-09-21 15:45", "price": 99.9}}]
    ok, cand, _r = evaluate_confirmation(cand, df)
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH"


def test_same_side_close_never_triggers_the_break_side_gate():
    from analysis.quality_engine import evaluate_confirmation
    rows = [(100.0, 100.2, 99.8, 100.0, 1000.0)] * 24
    rows.append((100.0, 100.1, 99.2, 99.4, 1500.0))         # closes BELOW the line
    df = _frame(rows)
    cand = _candidate("SHORT")
    cand.metadata["render_line_watch"] = [{
        "side": "HIGH", "slope": 0.0, "intercept": 100.2,
        "p0": {"ts": "2026-09-21 09:00", "price": 100.2},
        "p1": {"ts": "2026-09-21 15:45", "price": 100.2}}]
    _ok, cand, _r = evaluate_confirmation(cand, df)
    assert cand.metadata.get("last_reject_code") != "BREAK_SIDE_MISMATCH"


def test_dead_lines_projected_far_away_cannot_veto():
    from analysis.quality_engine import evaluate_confirmation
    rows = [(100.0, 100.2, 99.8, 100.0, 1000.0)] * 24
    rows.append((100.0, 100.1, 99.2, 99.4, 1500.0))
    df = _frame(rows)
    cand = _candidate("SHORT")
    cand.metadata["render_line_watch"] = [{
        "side": "HIGH", "slope": 0.0, "intercept": 120.0,   # 20×ATR away = history
        "p0": {"ts": "2026-09-21 09:00", "price": 120.0},
        "p1": {"ts": "2026-09-21 15:45", "price": 120.0}}]
    _ok, cand, _r = evaluate_confirmation(cand, df)
    assert cand.metadata.get("last_reject_code") != "BREAK_SIDE_MISMATCH"


# ── honest stops ─────────────────────────────────────────────────────────
def test_pinval_stop_uses_the_last_swing_not_the_six_pivot_extreme():
    src = io.open("analysis/setups_experimental.py", encoding="utf-8").read()
    assert 'max((float(pt["price"]) for pt in list(_ph)[-6:])' not in src
    assert '_above = [pt for pt in list(_ph)[-8:] if float(pt["price"]) > entry]' in src


def test_tlbreak_stop_never_widens_with_the_generic_stop():
    src = io.open("analysis/setups_experimental.py", encoding="utf-8").read()
    assert "min(candidate.sl, pattern_sl)" not in src
    assert "max(candidate.sl, pattern_sl)" not in src
    assert "candidate.sl = pattern_sl if pattern_sl" in src


def test_a_far_structural_stop_is_clamped_not_deleted():
    """His 09-21 ruling (verbatim): «استاپ اصلا ساختاری اگر فاصله داشت حذف نشه و
    تا ۱.۲۵ قیمت نماد محاسبه بشه» — the VVV 1h case (stop 15.193 against an 18.795
    entry) is now CUT at 1.25% instead of holding the chain «منتظر» for two days."""
    from analysis.trade_management import clamp_stop_price, MAX_STOP_PCT
    assert MAX_STOP_PCT == 1.25
    stop, clamped = clamp_stop_price(18.795, "LONG", 15.193)
    assert clamped is True
    assert abs((18.795 - stop) / 18.795 * 100 - 1.25) < 1e-9
    up, clamped_up = clamp_stop_price(18.795, "SHORT", 22.5)
    assert clamped_up is True and abs((up - 18.795) / 18.795 * 100 - 1.25) < 1e-9
    near, near_clamped = clamp_stop_price(18.795, "LONG", 18.60)   # ~1.04%
    assert near_clamped is False and near == 18.60
    # the alert lane records the clamp instead of dropping the setup, and the
    # confirmation lane still checks the stop side (unchanged laws)
    src = io.open("analysis/setups_v7.py", encoding="utf-8").read()
    assert "clamp_stop_price as _clamp_f" in src and '"stop_clamped"' in src
    qe = io.open("analysis/quality_engine.py", encoding="utf-8").read()
    assert "STOP_WRONG_SIDE" in qe
    assert target_distance_cap_pct("15m") == 5.0
    assert target_distance_cap_pct("4h") == 7.0
    assert target_distance_cap_pct("1d") == 15.0   # round 14: daily opened to 15%
