"""R99q31i — zones confirm through PINVAL, every other setup by its own rule.

His 10-20: «نواحی رو به پین‌وال بسپری و بقیه طبق قوانین خودشون تایید انجام بدن».

The engine had ONE proof for everybody: a lower-TF close beyond the break
edge. That is the right proof for a LINE engine and the wrong one for a ZONE
lane — a zone is reacted to, not broken. Demanding a break there confirms late
or never.
"""
import numpy as np
import pandas as pd

from analysis.models import SignalCandidate
from analysis.tohom_policy import (ZONE_POLICY, confirm_by_policy,
                                   delegates_to_pinval, evaluate_zone_confirmation,
                                   policy_for)


def _cand(code="PINVAL", direction="LONG", lo=100.0, hi=102.0):
    return SignalCandidate(
        signal_id="z1", symbol="BTCUSDT", style="perp", setup_code=code,
        setup_name="s", strategy_fa="f", direction=direction, score=9,
        status="APPROACHING", entry_zone_bottom=lo, entry_zone_top=hi,
        planned_entry=(lo + hi) / 2, sl=lo * 0.97, tp1=hi * 1.05,
        tp2=hi * 1.1, rr_tp1=2.0, rr_tp2=3.0, bias="bull",
        trigger_timeframe="1h", metadata={})


def _subs(rows, tf="15min"):
    ts = pd.date_range("2026-10-20 08:00", periods=len(rows), freq=tf)
    o, h, l, c, v = zip(*rows)
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": l,
                         "close": c, "volume": v})


# ── ownership ─────────────────────────────────────────────────────────────
def test_zone_lanes_are_delegated_to_pinval():
    for code in ("PINVAL", "PINWALL", "PINWALLQ", "ZONE", "RANGE"):
        assert delegates_to_pinval(code) is True
        assert policy_for(code) == ZONE_POLICY


def test_line_and_pattern_lanes_keep_their_own_rule():
    assert policy_for("TLBREAK") == "LINE_BREAK"
    assert policy_for("TECHCLASSIC") == "PATTERN_BREAK"
    assert policy_for("ALBROX") == "BASE_BREAK"
    assert delegates_to_pinval("TLBREAK") is False


def test_an_unknown_code_never_gets_the_zone_rule():
    assert delegates_to_pinval("SOMETHING_NEW") is False


# ── the zone judge ────────────────────────────────────────────────────────
def test_a_pin_bar_reaction_on_the_band_confirms_without_a_break():
    # two quiet candles, then a hammer closing back UP out of the band
    df = _subs([(103, 103.2, 102.8, 103.1, 100),
                (103, 103.1, 102.6, 102.9, 100),
                (102.5, 102.6, 99.4, 102.4, 260)])
    cand = _cand()
    ok, reason, info = evaluate_zone_confirmation(cand, df)
    assert ok is True, info["why"]
    assert "ناحیه" in reason
    assert cand.metadata["tohom_policy"] == ZONE_POLICY
    assert cand.status == "CONFIRMED"


def test_price_that_never_reaches_the_zone_is_not_a_reaction():
    df = _subs([(110, 110.4, 109.6, 110.1, 100),
                (110, 110.2, 109.7, 110.0, 100),
                (109.9, 110.1, 109.4, 109.8, 300)])
    ok, why, _ = evaluate_zone_confirmation(_cand(), df)
    assert ok is False and "نرسیده" in why


def test_a_close_still_inside_the_band_downwards_is_not_confirmation():
    df = _subs([(101, 101.2, 100.8, 101.0, 100),
                (101, 101.1, 100.7, 100.9, 100),
                (101, 101.05, 100.02, 100.05, 260)])   # closes at the band bottom
    ok, why, _ = evaluate_zone_confirmation(_cand(), df)
    assert ok is False


def test_a_zone_touch_without_anatomy_or_volume_does_not_confirm():
    flat = _subs([(101, 101.5, 100.5, 101.0, 100),
                  (101, 101.4, 100.6, 101.0, 100),
                  (101, 101.3, 100.7, 101.0, 100)])
    ok, _why, _ = evaluate_zone_confirmation(_cand(), flat)
    assert ok is False


def test_a_short_zone_mirror_works():
    df = _subs([(99, 99.4, 98.6, 99.1, 100),
                (99, 99.9, 98.8, 99.2, 100),
                (99.6, 101.5, 99.5, 99.7, 280)])    # rally into the band, pin back out
    cand = _cand(direction="SHORT", lo=100.0, hi=102.0)
    ok, _why, info = evaluate_zone_confirmation(cand, df)
    assert ok is True, info["why"]


# ── routing ───────────────────────────────────────────────────────────────
def test_a_zone_code_goes_through_the_zone_judge_first():
    df = _subs([(103, 103.2, 102.8, 103.1, 100),
                (103, 103.1, 102.6, 102.9, 100),
                (102.5, 102.6, 99.4, 102.4, 260)])
    cand = _cand("PINWALLQ")
    ok, _c, reason = confirm_by_policy(cand, df)
    assert ok is True
    assert "پین‌وال" in reason


def test_a_line_code_is_left_to_the_generic_edge_engine():
    src = open("analysis/tohom_policy.py", encoding="utf-8").read()
    assert "from analysis.tohom import evaluate_tohom_confirmation as _gen" in src
