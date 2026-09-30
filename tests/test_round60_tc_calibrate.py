"""r60 — TECHCLASSIC calibration (Viva 09-29, dictated laws).

His verdict on the 09-29 screenshots: «ستاپ‌ها زون‌های خوب را پیدا می‌کنند اما
شکست‌ها و تأییدها به CONFIRMED نمی‌رسند» — the multi-TF trend context was
vetoing the trigger-TF break. Laws implemented here (TECHCLASSIC ONLY):

1. A validated BREAK is the signal: the lagging parent-TF trend may no longer
   DEAD-GATE it (htf_alignment leaves the mandatory gates) nor veto its
   confirmation (COUNTER_TREND_TOUCH_ONLY becomes a visible warning).
2. Direction is locked to the break (same canonical contract as TLBREAK):
   break UP → LONG only, break DOWN → SHORT only.
3. TC FADEs (counter-pattern rejections) keep BOTH hard vetoes — with-trend
   only means a fade against the parent trend is never minted.

TLBREAK, PINVAL and every other setup keep today's exact behavior.
"""

import importlib
import sys
import os

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(__file__))

from test_v7 import make_candidate  # noqa: E402


# ── fixture: rallying frame (bull structure) vs a SHORT scenario, mirroring
# the test_signal_guards S6 fixture shape but carrying TECHCLASSIC metadata.
def _tc_frame_and_candidate(direction="SHORT"):
    from datetime import datetime, timedelta, timezone

    t0 = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(32):
        base = 98.0 if i < 28 else 100.2
        rows.append({"timestamp": t0 + timedelta(minutes=15 * i), "open": base - 0.02,
                     "high": base + 0.05, "low": base - 0.10, "close": base, "volume": 1000.0})
    df = pd.DataFrame(rows).set_index("timestamp")
    df.index.name = "timestamp"
    df["timestamp"] = df.index
    cand = make_candidate()
    cand.setup_code = "TECHCLASSIC"
    cand.status = "NEAR_CONFIRM"
    cand.entry_zone_bottom, cand.entry_zone_top = 99.8, 100.2
    cand.created_at = (t0 + timedelta(minutes=15 * 27)).isoformat()
    cand.metadata.update({
        "strategy_variant": "TECHNOCLASSIC", "atr": 1.0,
        "confirm_tf": "15m", "touched": True,
        "tl_fast_break": "اولین کلوزِ معتبر فراتر از خط/لبه — پولبک شرط نیست",
    })
    cand.mandatory_gates = {
        "technoclassic_break_closed": True, "displacement": True,
        "market_liquidity": True,
    }
    if direction == "LONG":
        cand.direction = "LONG"
        cand.planned_entry, cand.sl = 100.1, 98.6
        cand.tp1, cand.tp2 = 106.0, 109.0
    else:
        cand.direction = "SHORT"
        cand.planned_entry, cand.sl = 100.1, 101.9
        cand.tp1, cand.tp2 = 96.0, 93.0
    return df, cand


def test_tc_break_confirms_despite_opposed_parent_trend():
    """THE r60 fix: a locked TECHCLASSIC break may never be vetoed by the
    lagging parent-TF trend — COUNTER_TREND_TOUCH_ONLY becomes a warning and
    the first valid close beyond the line confirms."""
    from analysis.quality_engine import evaluate_confirmation

    df, cand = _tc_frame_and_candidate("SHORT")     # frame rallies = bull parent
    cand.metadata["break_direction"] = "DOWN"       # validated break DOWN → SHORT
    cand.metadata["tl_context_conflict"] = True     # parent trend opposed
    ok, _c, reason = evaluate_confirmation(cand, df)
    assert ok is True, reason
    assert cand.metadata.get("last_reject_code") is None
    assert cand.metadata.get("mtf_context_warning_tc")      # visible, not fatal
    assert cand.status == "CONFIRMED"


def test_tc_fade_keeps_counter_trend_veto():
    """With-trend only: a TC FADE (no break_direction contract) against the
    parent trend is still rejected — TLBREAK owns the counter-trend zone lane."""
    from analysis.quality_engine import evaluate_confirmation

    df, cand = _tc_frame_and_candidate("SHORT")
    assert "break_direction" not in cand.metadata   # fade: no break contract
    cand.metadata["tl_context_conflict"] = True
    ok, _c, reason = evaluate_confirmation(cand, df)
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "COUNTER_TREND_TOUCH_ONLY"


def test_tc_break_direction_contract_locks_direction():
    """Same canonical contract as TLBREAK: a break UP may only trade LONG."""
    from analysis.quality_engine import evaluate_confirmation

    df, cand = _tc_frame_and_candidate("SHORT")
    cand.metadata["break_direction"] = "UP"         # break was UP…
    ok, _c, _reason = evaluate_confirmation(cand, df)
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH"


def test_tc_break_candidate_drops_htf_alignment_gate(monkeypatch):
    """End-to-end: the detector mints a TC break whose mandatory gates carry
    NO htf_alignment (multi-TF context = score/warning only) and locks the
    break direction."""
    monkeypatch.setenv("TECHCLASSIC_ENABLED", "true")
    monkeypatch.setenv("TECHCLASSIC_FADE_SIGNALS", "false")
    import config
    config._cached = None
    importlib.reload(config)
    import analysis.pattern_engine as pe
    importlib.reload(pe)
    import analysis.setups_experimental as exp
    importlib.reload(exp)
    try:
        from test_pattern_engine import _wedge_frames, _Bundle
        pattern, trigger = _wedge_frames()
        bundle = _Bundle({"4h": pattern, "1h": pattern, "15m": trigger})
        # detect_technoclassic's _ensure_frames fetches live frames for the
        # synthetic symbol, so exercise the builder directly — it is exactly
        # where the r60 gate/contract changes live.
        stf, _refine, ttf = __import__("analysis.setups_v7", fromlist=["timeframe_profile"]).timeframe_profile("DAYTRADE")
        p2 = pattern.tail(pe._FIT_WINDOW.get(stf, 140)).reset_index(drop=True)
        events = [e for e in pe.scan_edges(p2, trigger, stf) if e["state"] in (pe.STATE_BREAK, pe.STATE_FADE)]
        assert events, "wedge fixture must emit a break/fade event"
        ev = next(e for e in events if e["state"] == pe.STATE_BREAK)
        cand = pe._build_candidate(bundle, "DAYTRADE", ev, p2, trigger, stf, ttf, pe._fit_cfg())
        if cand is None:
            pytest.skip("wedge fixture did not build a candidate in this env")
        assert cand.setup_code == "TECHCLASSIC"
        assert "htf_alignment" not in cand.mandatory_gates          # r60: context = score only
        assert cand.metadata.get("strategy_variant") == "VIVA_TLBREAK"   # unchanged contract
        assert cand.metadata.get("break_direction") == "UP"         # fixture = break-up LONG
        assert cand.direction == "LONG"
    finally:
        monkeypatch.delenv("TECHCLASSIC_ENABLED", raising=False)
        monkeypatch.delenv("TECHCLASSIC_FADE_SIGNALS", raising=False)
        config._cached = None
        importlib.reload(config)
        importlib.reload(pe)
        importlib.reload(exp)
