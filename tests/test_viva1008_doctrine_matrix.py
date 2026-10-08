"""Viva Law 2026-10-08 — DOCTRINE MATRIX locks (his 13/14/15-مهر doctrine).

Setup × trigger-type law (verbatim «تکنوکلاسیک فقط شکستها رو میتونه
تابید بکنه»):
  • TECHCLASSIC: break + first valid close ONLY (or TOHOM-early).
    A bare zone touch + candle pattern with NO break is NEVER a confirm.
  • TLBREAK: same as TECHCLASSIC (its internal ceiling→floor lane survives
    as the NEXT position's pullback map, r52).
  • PINVAL / ALBROX: keep the zone lane (all lanes + zones allowed).
"""
from __future__ import annotations

import pandas as pd

from analysis.models import SignalCandidate
from analysis.quality_engine import evaluate_confirmation


def _zone_frame() -> pd.DataFrame:
    # 25 quiet bars, last two form a bullish engulfing AT the zone (99.5-100),
    # closing 99.90 — below the zone top, i.e. NO break anywhere.
    rows = []
    for i in range(23):
        rows.append((99.55, 99.75, 99.45, 99.60, 1000.0))
    rows.append((99.80, 99.85, 99.60, 99.65, 1000.0))   # red
    rows.append((99.64, 99.95, 99.62, 99.90, 1400.0))   # green engulfing, no break
    return pd.DataFrame([{"timestamp": pd.Timestamp("2026-10-08 10:00") + pd.Timedelta(minutes=15 * i),
                          "open": o, "high": h, "low": l, "close": c, "volume": v}
                         for i, (o, h, l, c, v) in enumerate(rows)])


def _cand(setup: str, **over) -> SignalCandidate:
    base = dict(signal_id="V1008-1", symbol="TESTUSDT", style="SWING", setup_code=setup,
                setup_name="t", strategy_fa="t", direction="LONG", score=8,
                status="NEAR_CONFIRM", entry_zone_bottom=99.5, entry_zone_top=100.0,
                planned_entry=99.9, sl=98.9, tp1=101.0, tp2=102.0, rr_tp1=1.0, rr_tp2=2.0,
                bias="BULL", trigger_timeframe="15m",
                created_at="2026-10-08 09:00:00+00:00",
                mandatory_gates={"zone": True},
                metadata={"atr": 1.0, "touched": True})
    base.update(over)
    return SignalCandidate(**base)


def test_technoclassic_zone_touch_without_break_never_confirms():
    ok, cand, reason = evaluate_confirmation(_cand("TECHCLASSIC"), _zone_frame())
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "NO_TRIGGER"
    assert "شکستِ خالص" in reason          # the doctrine gate fired


def test_tlbreak_zone_touch_without_break_never_confirms():
    ok, cand, reason = evaluate_confirmation(_cand("TLBREAK"), _zone_frame())
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "NO_TRIGGER"
    assert "شکستِ خالص" in reason


def test_albrox_keeps_the_zone_lane():
    ok, cand, reason = evaluate_confirmation(_cand("ALBROX"), _zone_frame())
    assert "شکستِ خالص" not in reason      # the pure-break gate never fires


def test_pinval_keeps_the_zone_lane():
    ok, cand, reason = evaluate_confirmation(_cand("PINVAL"), _zone_frame())
    assert "شکستِ خالص" not in reason


def test_tohom_early_opens_the_pure_break_gate():
    md = {"atr": 1.0, "touched": True, "tohom": 1, "tohom_pattern": "انگالفینگ"}
    ok, cand, reason = evaluate_confirmation(_cand("TECHCLASSIC", metadata=md), _zone_frame())
    assert "شکستِ خالص" not in reason      # TOHOM-early is a legal TC confirm


# ── structural locks (10-08): laws verified this round, pinned in source ──
def _repo_src(*parts):
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, *parts), encoding="utf-8") as f:
        return f.read()


def test_render_window_capped_at_render_count_never_detection():
    # his STX-15M «چرا ۳۰۰ کندل؟»: the focus window is capped at the RENDER
    # map (render_count), never the detection depth (candle_count).
    src = _repo_src("bot", "messages_v7.py")
    assert "max_n=_rc_target" in src
    assert "min(int(_lookback), _rc_target)" in src


def test_htf_range_boxes_never_drown_the_trigger_chart():
    # his FET-4H «باکس صورتی پهن»: a range taller than 2.5 ATR, or fully left
    # behind by price, is never drawn.
    src = _repo_src("bot", "messages_v7.py")
    assert "_r_height > 2.5 * _atrR9" in src
    assert "Retired range: price has completely moved past" in src


def test_confirmed_stamp_precedes_persistence():
    # his «Only a CONFIRMED candidate can be persisted» (BTC/XRP pinwall):
    # status + stamp land BEFORE save_confirmed_signal, never after.
    src = _repo_src("main.py")
    assert src.index('candidate.status = "CONFIRMED"') < src.index("save_confirmed_signal(candidate)")
    assert "candidate.confirmed_at = iso_now()" in src


def test_entry_band_follows_trade_direction_not_position():
    # his «لیبل وارونه»: the ENTRY band token is direction-based
    # (SHORT→SUPPLY, LONG→DEMAND); position paint stays for zones only.
    src = _repo_src("bot", "messages_v7.py")
    assert '"SUPPLY" if _entry_key == "SHORT" else "DEMAND"' in src


# ── Q1 (10-08): late confirms approve WITH a visible entry↔live gap warning ──
def test_late_confirm_warns_the_entry_live_gap():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
    from test_v7 import make_candidate
    from bot.messages_v7 import _confirmed_chart_caption
    cand = make_candidate()
    cand.planned_entry = 100.0
    cand.metadata["live_price"] = 103.0          # RENDER case: 3% late
    cap = _confirmed_chart_caption(cand)
    assert "فاصلهٔ ورود تا لایو" in cap and "3.00" in cap
    cand.metadata["live_price"] = 100.0          # on time: silent
    assert "فاصلهٔ ورود تا لایو" not in _confirmed_chart_caption(cand)
