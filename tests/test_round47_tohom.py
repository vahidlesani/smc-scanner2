"""r47 — TOHOM, the early-confirmation engine (Viva 2026-09-27).

His words: «یه انجین هوشمند واسه ورود قبل از کلوز تایم تریگر … همه تایم‌ها
از کلوز همراه با حجم بالا رفته محسوس … با کلوز سوم کندل تایم پایین‌ترش بتونه
تایید ورود بگیره … حتی ساعت دوم اگر اطمینان بالا بود … اسم خاصی واسه این
آپدیت بذار که اگر بد شد نتیجه بگم برگردونی».

Laws under test:
  1. Three directional sub-TF closes + noticeable rising volume + a
     confirming pattern beyond the SAME break edge = early confirm NOW.
  2. High-confidence lane: score ≥ 9 with volume ≥ 2× confirms on TWO subs.
  3. Fail-closed everywhere: missing volume rise, no pattern, not beyond the
     edge, or the engine switched off (TOHOM_ENABLED=0) all keep waiting for
     the one-close law. TOHOM only ADDS confirmations, never loosens.
  4. Routing by SETUP: PINVAL→short channel, TECHCLASSIC→long,
     r48 final: ALBROX/TLBREAK→mid only (the two-setup channel). LOG axis.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rows(start="2026-09-27 00:00", minutes=60.0, n=40, base=1.00, drift=0.0,
          vols=None, extra=None):
    ts = pd.Timestamp(start)
    rows = []
    px = base
    for i in range(n):
        op = px
        cl = px * (1 + drift)
        hi = max(op, cl) * 1.002
        lo = min(op, cl) * 0.998
        row = dict(timestamp=ts + pd.Timedelta(minutes=minutes * i),
                   open=op, close=cl, high=hi, low=lo,
                   volume=(vols[i] if vols else 1000.0))
        if extra and i in extra:
            row.update(extra[i])
        rows.append(row)
        px = cl
    return pd.DataFrame(rows)


def _cand(direction="LONG", tf="4h", score=8.0, zone=(1.02, 1.03), edge=None,
          setup="TECHCLASSIC"):
    md = {"atr": 0.01}
    if edge is not None:
        md["viva_breakout_line"] = edge
    return SimpleNamespace(direction=direction, trigger_timeframe=tf, score=score,
                           entry_zone_top=zone[1], entry_zone_bottom=zone[0],
                           planned_entry=(zone[0] + zone[1]) / 2.0,
                           setup_code=setup, metadata=md)


def _now(start="2026-09-27 00:00", minutes=60.0, n=40):
    return pd.Timestamp(start) + pd.Timedelta(minutes=minutes * (n - 1) + 5)


# ── 1. the core lane: 3 sub-closes + rising volume + pattern = NOW ─────────

def test_three_directional_closes_with_volume_confirm_early():
    from analysis.tohom import evaluate_tohom_confirmation
    # 37 quiet rising candles then 3 accelerating ones breaking the 1.03 edge
    vols = [1000.0] * 37 + [1500.0, 1900.0, 2600.0]
    frame = _rows(n=40, base=1.00, drift=0.0015, vols=vols,
                  extra={39: dict(open=1.055, close=1.075, high=1.078, low=1.052)})
    cand = _cand(edge=1.03)
    ok, cand, reason = evaluate_tohom_confirmation(cand, frame, now=_now())
    assert ok, reason
    md = cand.metadata
    assert md["tohom"] == 1 and md["tohom_subs"] == 3
    assert md["technical_confirmation_complete"] is True
    assert "توهم" in reason and "حجم" in reason


def test_short_mirror_confirms_on_three_red_closes():
    from analysis.tohom import evaluate_tohom_confirmation
    vols = [1000.0] * 37 + [1600.0, 2100.0, 2800.0]
    frame = _rows(n=40, base=1.00, drift=-0.0015, vols=vols,
                  extra={39: dict(open=0.945, close=0.925, high=0.948, low=0.922)})
    cand = _cand(direction="SHORT", edge=0.97)
    ok, cand, reason = evaluate_tohom_confirmation(cand, frame, now=_now())
    assert ok, reason


# ── 2. the high-confidence lane: score 9 + 2× volume = two subs suffice ────

def test_two_sub_candle_lane_for_high_confidence():
    from analysis.tohom import evaluate_tohom_confirmation
    # only TWO sub-candles have closed since the trigger candle opened
    vols = [1000.0] * 30 + [2400.0, 3200.0]
    frame = _rows(n=31, base=1.00, drift=0.002, vols=vols,
                  extra={30: dict(open=1.06, close=1.08, high=1.082, low=1.058)})
    cand = _cand(score=9.5, zone=(1.015, 1.025), edge=1.02)
    now = pd.Timestamp("2026-09-27 00:00") + pd.Timedelta(minutes=60 * 30 + 5)
    ok, cand, reason = evaluate_tohom_confirmation(cand, frame, now=now)
    assert ok, reason
    assert cand.metadata["tohom_subs"] == 2


# ── 3. fail-closed: every missing ingredient keeps waiting ────────────────

def test_flat_volume_rejects():
    from analysis.tohom import evaluate_tohom_confirmation
    frame = _rows(n=40, base=1.00, drift=0.0015,
                  extra={39: dict(open=1.055, close=1.075, high=1.078, low=1.052)})
    cand = _cand(edge=1.03)
    ok, cand, reason = evaluate_tohom_confirmation(cand, frame, now=_now())
    assert not ok and cand.metadata["last_reject_code"] == "TOHOM_VOL"


def test_not_beyond_edge_rejects():
    from analysis.tohom import evaluate_tohom_confirmation
    vols = [1000.0] * 37 + [1500.0, 1900.0, 2600.0]
    frame = _rows(n=40, base=1.00, drift=0.001, vols=vols)  # stays ~1.06? no:
    frame = _rows(n=40, base=1.00, drift=0.0005, vols=vols)  # ~1.02, under edge
    cand = _cand(edge=1.20)
    ok, cand, reason = evaluate_tohom_confirmation(cand, frame, now=_now())
    assert not ok and cand.metadata["last_reject_code"] == "TOHOM_BEYOND"


def test_engine_off_keeps_one_close_law():
    from analysis.tohom import evaluate_tohom_confirmation
    vols = [1000.0] * 37 + [1500.0, 1900.0, 2600.0]
    frame = _rows(n=40, base=1.00, drift=0.0015, vols=vols,
                  extra={39: dict(open=1.055, close=1.075, high=1.078, low=1.052)})
    cand = _cand(edge=1.03)
    import config
    orig = config.get_settings
    try:
        import types
        cfg = orig()
        object.__setattr__(cfg, "tohom_enabled", False)
        config.get_settings = lambda: cfg
        ok, cand, reason = evaluate_tohom_confirmation(cand, frame, now=_now())
        assert not ok and cand.metadata["last_reject_code"] == "TOHOM_OFF"
    finally:
        config.get_settings = orig
        # the settings object is the SHARED cached singleton — the mutated
        # flag must be restored too, or every later TOHOM test sees OFF.
        object.__setattr__(cfg, "tohom_enabled", True)


def test_once_per_candidate():
    from analysis.tohom import evaluate_tohom_confirmation
    vols = [1000.0] * 37 + [1500.0, 1900.0, 2600.0]
    frame = _rows(n=40, base=1.00, drift=0.0015, vols=vols,
                  extra={39: dict(open=1.055, close=1.075, high=1.078, low=1.052)})
    cand = _cand(edge=1.03)
    evaluate_tohom_confirmation(cand, frame, now=_now())
    ok2, _, _ = evaluate_tohom_confirmation(cand, frame, now=_now())
    assert not ok2


# ── 4. wiring: hook, routing map, spot log axis ────────────────────────────

def test_hook_sits_after_the_late_bound_retry():
    src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    part = src.split("candidate, _lf[1], htf_closed_df=_pat_frame)")[1][:900]
    assert "evaluate_tohom_confirmation" in part
    assert 'TOHOM_ENABLED' in open(os.path.join(REPO, "config.py"), encoding="utf-8").read()


def test_setup_routing_map():
    # r53: routing by SETUP ONLY via _setup_announce_channel — the mirror
    # table is gone (one signal, ONE announce channel, no TF dimension).
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    part = src.split("def _setup_announce_channel")[1].split("def tf_channel_publish_confirmed")[0]
    assert '"PINVAL", "PINWALLQ", "PINWALL"' in part and "CHAT_ID_SWING_SHORT" in part
    assert '"TECHCLASSIC"' in part and "CHAT_ID_SWING_LONG" in part
    assert '"ALBROX", "TLBREAK"' in part and "CHAT_ID_SWING_MID" in part
    assert "_setup_routes" not in src


def test_spot_chart_is_log_and_tohom_line_exists():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'ax.set_yscale("log")' in src
    assert '"3d": 300' in src and '"8h": 170' in src
    assert "_tohom_line" in src


def test_confirm_card_carries_tohom_row():
    from bot.messages_v7 import _tohom_line
    cand = _cand()
    assert _tohom_line(cand) == ""
    cand.metadata["tohom"] = 1
    cand.metadata["tohom_note_fa"] = "⚡ تأیید زودهنگام توهم: تست"
    assert "توهم" in _tohom_line(cand)
