"""R62-ARENA — confirmation ladder, shared sloped edge, continuous TOHOM,
stale disarm, pattern classifier and candle-vocabulary fixes.

Every test names the audit ID it locks (docs/R62_ARENA_CHANGES.md)."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

import sys

sys.path.insert(0, __import__("os").path.dirname(__file__))

from test_v7 import make_candidate  # noqa: E402


# ── C7: every trigger TF listens ONE step below itself ─────────────────────
@pytest.mark.parametrize("trig,conf,sub", [
    ("15m", "5m", "1m"), ("30m", "15m", "5m"), ("1h", "15m", "5m"),
    ("2h", "30m", "5m"), ("4h", "1h", "15m"), ("1d", "4h", "1h"),
])
def test_confirm_ladder_follows_trigger(trig, conf, sub):
    from analysis.confirm_r62 import confirm_tf_for_trigger, tohom_sub_tf
    assert confirm_tf_for_trigger(trig) == conf
    assert tohom_sub_tf(trig) == sub


def test_old_chain_is_repointed_to_the_ladder():
    from analysis.confirm_r62 import normalize_confirm_tf
    c = make_candidate()
    c.trigger_timeframe = "1h"
    c.metadata["confirm_tf"] = "4h"          # pre-R62 pattern-keyed value
    assert normalize_confirm_tf(c) == "15m"
    assert c.metadata["confirm_tf"] == "15m"
    assert c.metadata["confirm_tf_legacy"] == "4h"


def test_setups_v7_confirm_tf_uses_trigger_ladder():
    from analysis.setups_v7 import confirm_timeframe_for_pattern
    # SWING 1h alert on a 4h pattern used to be confirmed on 4h (≈5–6h late)
    assert confirm_timeframe_for_pattern("4h", "SWING", "1h") == "15m"
    assert confirm_timeframe_for_pattern("1d", "SWING", "4h") == "1h"


# ── C1 / TH4 / W7: ONE sloped edge everywhere ───────────────────────────────
def _geo_candidate(direction="LONG"):
    c = make_candidate()
    c.direction = direction
    c.setup_code = "TECHCLASSIC"
    c.trigger_timeframe = "1h"
    t0 = datetime(2026, 9, 30, 12, 0)
    # a falling resistance: 100 twenty bars ago → 90 at t0 (−0.5 / bar)
    c.metadata.update({
        "viva_breakout_line": 90.0, "atr": 1.0,
        "break_line_geo": {"ts": str(t0), "price": 90.0, "price_back": 100.0,
                           "back_bars": 20, "tf_min": 60.0, "log": False},
    })
    return c, t0


def test_edge_is_projected_on_its_own_slope():
    from analysis.confirm_r62 import confirm_edge_at
    c, t0 = _geo_candidate()
    assert confirm_edge_at(c, t0) == pytest.approx(90.0)
    assert confirm_edge_at(c, t0 + timedelta(hours=4)) == pytest.approx(88.0)
    # a runaway projection falls back to the static level
    assert confirm_edge_at(c, t0 + timedelta(days=30)) == pytest.approx(90.0)


def test_live_watch_and_structural_edge_share_the_core():
    import main
    c, t0 = _geo_candidate()
    assert main._watch_edge_at(c, t0 + timedelta(hours=2)) == pytest.approx(89.0)


def test_pin_family_stays_a_level():
    from analysis.confirm_r62 import confirm_edge_at
    c, t0 = _geo_candidate()
    c.setup_code = "PINVAL"
    c.metadata["pin_high"] = 95.0
    assert confirm_edge_at(c, t0 + timedelta(hours=6)) == 95.0


# ── lower-TF candle vocabulary of a valid break ─────────────────────────────
def test_valid_break_candle_vocabulary():
    from analysis.confirm_r62 import valid_break_candle
    ok, name = valid_break_candle({"open": 100, "high": 103, "low": 99.8, "close": 102.9},
                                  None, "LONG", 101.0)
    assert ok and "ماروبوزو" in name
    # shooting star on the break = fake-out
    ok, name = valid_break_candle({"open": 101.2, "high": 104, "low": 101.0, "close": 101.3},
                                  None, "LONG", 101.0)
    assert not ok
    # SHORT mirror: strong bearish body
    ok, _ = valid_break_candle({"open": 100, "high": 100.2, "low": 97, "close": 97.1},
                               None, "SHORT", 99.0)
    assert ok


def test_break_established_markers():
    from analysis.confirm_r62 import break_established
    assert not break_established({})
    assert break_established({"technoclassic": {"kind": "break"}})
    assert break_established({"viva_state": "S2_BREAKOUT_CLOSED"})
    assert not break_established({"viva_state": "S0_WATCH"})


# ── TH1–TH3: TOHOM is a continuous listener ─────────────────────────────────
def _sub_frame(t0, closes, vols, opens=None):
    rows = []
    for i in range(25):
        rows.append({"timestamp": t0 - timedelta(minutes=5 * (25 - i)), "open": 89.0,
                     "high": 89.2, "low": 88.8, "close": 89.0, "volume": 100.0})
    for i, cl in enumerate(closes):
        op = opens[i] if opens else cl - 0.3
        rows.append({"timestamp": t0 + timedelta(minutes=5 * i), "open": op,
                     "high": max(op, cl) + 0.05, "low": min(op, cl) - 0.05,
                     "close": cl, "volume": vols[i]})
    return pd.DataFrame(rows)


def test_tohom_is_not_one_shot():
    from analysis.tohom import evaluate_tohom_confirmation
    c, t0 = _geo_candidate()
    c.score = 8
    # cycle 1: price still under the line → no confirm, no permanent stamp
    df1 = _sub_frame(t0, [89.1, 89.3, 89.4], [100, 105, 110])
    ok1, c, _ = evaluate_tohom_confirmation(c, df1, trigger_open=t0,
                                            now=t0 + timedelta(minutes=16), sub_tf="5m")
    assert ok1 is False
    assert not c.metadata.get("tohom_checked")
    # cycle 2 (a NEW sub-candle): directional closes beyond, rising volume
    df2 = _sub_frame(t0, [89.1, 90.4, 91.0, 91.6], [100, 140, 170, 210])
    ok2, c, why = evaluate_tohom_confirmation(c, df2, trigger_open=t0,
                                              now=t0 + timedelta(minutes=21), sub_tf="5m")
    assert ok2 is True, why
    assert c.metadata.get("tohom_confirm_close") == pytest.approx(91.6)
    # the same sub-bar is never re-judged
    ok3, c, _ = evaluate_tohom_confirmation(c, df2, trigger_open=t0,
                                            now=t0 + timedelta(minutes=21), sub_tf="5m")
    assert ok3 is False


def test_tohom_frame_tf_is_one_step_below_confirm():
    from analysis.tohom import tohom_frame_tf
    c = make_candidate()
    c.trigger_timeframe = "1h"
    assert tohom_frame_tf(c) == "5m"
    c.trigger_timeframe = "4h"
    assert tohom_frame_tf(c) == "15m"


def test_main_runs_tohom_outside_fetch_windows():
    import inspect
    import main
    src = inspect.getsource(main)
    seg = src.split("elif not have_frames:")[1][:1400]
    assert "_r62_tohom_attempt" in seg
    helper = inspect.getsource(main._r62_tohom_attempt)
    assert "use_cache=False" in helper and "iloc[:-1]" in helper


# ── C5: stale confirmation is disarmed once ─────────────────────────────────
def test_stale_reset_disarms_the_old_bar():
    import main
    c = make_candidate()
    c.status = "CONFIRMED"
    c.metadata.update({"technical_confirmation_complete": True, "tl_fast_break": True,
                       "fast_break_bar": "2026-09-30 13:00:00", "viva_state": "S6_CONFIRMED"})
    main._r62_reset_stale(c)
    md = c.metadata
    assert md["stale_after_bar"] == "2026-09-30 13:00:00"
    assert not md.get("technical_confirmation_complete")
    assert not md.get("fast_break_bar")
    assert md["viva_state"] == "S2_BREAKOUT_CLOSED"
    assert c.status == "APPROACHING"


def test_stale_minutes_measured_from_bar_close():
    import main
    c = make_candidate()
    c.metadata["confirm_tf"] = "15m"
    now = pd.Timestamp.utcnow().tz_localize(None)
    # a 15m bar that OPENED 40 min ago closed 25 min ago → not stale (≤ 30)
    c.metadata["fast_break_bar"] = str(now - pd.Timedelta(minutes=40))
    c.metadata["fast_break_tf_min"] = 15
    assert main._confirmation_stale_minutes(c, None) is None
    c.metadata["fast_break_bar"] = str(now - pd.Timedelta(minutes=60))
    assert main._confirmation_stale_minutes(c, None) is not None


# ── P1: flat edges are judged against pattern HEIGHT ────────────────────────
def _ln(slope, intercept, first=0):
    return SimpleNamespace(slope=slope, intercept=intercept, first_index=first,
                           last_index=100, price_at=lambda x, s=slope, i=intercept: s * x + i)


def test_ascending_triangle_near_apex_is_not_a_rising_wedge():
    from analysis.pattern_engine import classify_shape
    # flat-ish top (tiny noise slope) at 110, rising floor 100 → 108.5 over 100 bars
    upper = _ln(0.004, 109.8)
    lower = _ln(0.085, 100.0)
    shape = classify_shape(upper, lower, 100)
    assert shape == "TRIANGLE_ASCENDING", shape


def test_classify16_widths_use_the_lower_edge():
    from analysis.patterns16 import classify16
    upper = _ln(-0.05, 110.0)
    lower = _ln(0.05, 100.0)
    slug, meta = classify16(upper, lower, 60)
    assert slug != "NONE"


# ── P5: double-top neckline is SUPPORT ──────────────────────────────────────
def test_double_top_neckline_is_low_side():
    import numpy as np
    from analysis.patterns16 import detect_pivot_patterns
    xs = np.arange(80)
    base = 100 + 8 * np.exp(-((xs - 30) / 5.0) ** 2) + 8 * np.exp(-((xs - 55) / 5.0) ** 2)
    df = pd.DataFrame({"open": base, "high": base + 0.3, "low": base - 0.3,
                       "close": base, "volume": 1.0})
    found = [p for p in detect_pivot_patterns(df, 1.0) if p["type"] == "DOUBLE_TOP"]
    assert found, "fixture must form a double top"
    assert found[0]["lines"][0]["side"] == "LOW"


# ── K1 / K2: candle vocabulary honesty ─────────────────────────────────────
def test_cluster_requires_zone_overlap():
    from analysis.trigger_patterns import multi_candle_trigger
    import inspect
    src = inspect.getsource(multi_candle_trigger)
    assert "min(l, zone_low) <= zone_high" not in src
    assert "l <= zone_high and h >= zone_low" in src


def test_cluster_engulf_needs_opposite_prior():
    import inspect
    from analysis.trigger_patterns import multi_candle_trigger
    src = inspect.getsource(multi_candle_trigger)
    assert "prev_c < prev_o" in src and "prev_c > prev_o" in src


# ── G3: LONG mirror of the contradiction filter ─────────────────────────────
def test_line_contradicts_long_mirror():
    from analysis.render_kit import _line_contradicts
    n = 60
    closes = [100 + 0.2 * i for i in range(n)]
    df = pd.DataFrame({"open": closes, "high": [c + 0.5 for c in closes],
                       "low": [c - 0.5 for c in closes], "close": closes})
    # a FALLING support far below a rallying price → contradicts a LONG
    falling_low = {"slope": -0.1, "intercept": 100.0, "side": "LOW", "x0": 0, "x1": 30}
    assert _line_contradicts(falling_low, "LOW", "LONG", df) is True
    # a rising support right under price → fine
    rising_low = {"slope": 0.2, "intercept": 99.5, "side": "LOW", "x0": 0, "x1": 30}
    assert _line_contradicts(rising_low, "LOW", "LONG", df) is False


# ── smart zoom: the tool is never crushed by an old swing ──────────────────
def test_smart_zoom_trims_old_swing_but_keeps_anchor():
    from bot.messages_v7 import _r62_tool_fit_lookback
    t0 = datetime(2026, 9, 1)
    n = 150
    closes = [150.0 - 0.5 * i if i < 40 else 100.0 + 0.02 * (i - 40) for i in range(n)]
    df = pd.DataFrame({"timestamp": [t0 + timedelta(hours=i) for i in range(n)],
                       "open": closes, "high": [c * 1.003 for c in closes],
                       "low": [c * 0.997 for c in closes], "close": closes, "volume": 1.0})
    c = make_candidate()
    c.sl, c.entry_zone_bottom, c.entry_zone_top = 101.0, 102.0, 102.4
    c.tp1, c.tp2 = 104.0, 106.0
    c.metadata["target_ladder"] = {"targets": [104.0, 105.0, 106.0, 107.0, 108.0]}
    c.metadata["pattern_geo"] = {"upper": {"a_ts": str(t0 + timedelta(hours=60))}}
    got = _r62_tool_fit_lookback(df, c, 150, True)
    assert 105 <= got < 150            # trimmed, inside the dictated band
    assert got >= n - 60 + 3           # the pattern anchor stays on canvas
    assert _r62_tool_fit_lookback(df, c, 150, False) == 150   # alert chart untouched


# ── W1 / W2 / P10 wiring guards ─────────────────────────────────────────────
def test_budget_checked_before_supersede_and_ghost_retired():
    import inspect
    import main
    src = inspect.getsource(main)
    i_budget = src.index('if _edu_budget["left"] <= 0 or (_is_watch62')
    i_super = src.index("for prior in supersede_alert_lineage(candidate):")
    assert i_budget < i_super
    assert '_set_st62(candidate.signal_id, "UNPOSTED")' in src


def test_mint_guard_allows_never_persisted_ids():
    import inspect
    import analysis.pattern_engine as pe
    src = inspect.getsource(pe)
    assert '_st60 == "" and _sid60 and _age62 > 20 * 60' in src
    assert '"UNPOSTED"' in src


def test_break_reclaimed_is_terminal():
    import inspect
    import main
    src = inspect.getsource(main)
    seg = src.split('== "BREAK_RECLAIMED"')[1][:1500]
    assert 'candidate.status = "CANCELLED"' in seg
    assert "send_candidate_cancelled(" in seg


# ── the DOT case end-to-end: 1h chain confirmed by the first valid 15m close ─
def test_dot_case_1h_chain_confirms_on_first_valid_15m_close():
    from analysis.quality_engine import evaluate_confirmation
    t0 = datetime(2026, 9, 30, 6, 0)
    rows = []
    for i in range(36):                          # 15m bars 06:00 → 14:45
        ts = t0 + timedelta(minutes=15 * i)
        if i < 25:
            o, h, l, c = 99.6, 99.8, 99.4, 99.6   # under the line (100)
        elif i == 25:                             # 12:15 — shooting star on the line
            o, h, l, c = 99.9, 101.6, 99.85, 100.15
        elif i == 26:                             # 12:30 — strong bullish close beyond
            o, h, l, c = 100.1, 100.95, 100.05, 100.9
        else:
            o, h, l, c = 100.9, 101.1, 100.7, 100.95
        rows.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c,
                     "volume": 1000.0})
    df = pd.DataFrame(rows).iloc[:28]            # evaluated at 13:00 (bar 12:45 closed)
    c = make_candidate()
    c.setup_code = "TECHCLASSIC"
    c.trigger_timeframe = "1h"
    c.status = "NEAR_CONFIRM"
    c.entry_zone_bottom, c.entry_zone_top = 99.6, 100.4
    c.planned_entry, c.sl = 100.0, 99.0
    c.tp1, c.tp2 = 103.0, 105.0
    c.created_at = (t0 + timedelta(hours=6, minutes=5)).isoformat()   # alert 12:05
    c.metadata.update({"atr": 1.0, "confirm_tf": "15m", "touched": False,
                       "viva_breakout_line": 100.0})
    ok, c2, reason = evaluate_confirmation(c, df, frame_tf_minutes=15.0)
    assert ok is True, reason
    md = c2.metadata
    # the fake-out star at 12:15 is skipped; the 12:30 strong close confirms
    assert str(md.get("fast_break_bar"))[:16] == "2026-09-30 12:30"
    assert md.get("last_fakeout_candle")


# ── K4 / K5 / K6 / S3 ───────────────────────────────────────────────────────
def test_r28_rejection_wick_is_directional():
    from analysis.execution_integrity_r28 import confirm_closed_candle
    star = {"open": 100.0, "high": 104.0, "low": 99.8, "close": 100.6}   # upper wick
    hammer = {"open": 100.0, "high": 100.8, "low": 96.0, "close": 100.6}  # lower wick
    assert not confirm_closed_candle(star, "LONG", "REJECTION_CONFIRMATION").confirmed
    assert confirm_closed_candle(hammer, "LONG", "REJECTION_CONFIRMATION").confirmed


def test_zone_trigger_needs_the_zone():
    from analysis.setups_v7 import detect_zone_trigger
    rows = [{"open": 110 + i * 0.01, "high": 110.3, "low": 109.7, "close": 110.1} for i in range(8)]
    rows[-2] = {"open": 110.4, "high": 110.5, "low": 109.8, "close": 109.9}
    rows[-1] = {"open": 109.85, "high": 110.9, "low": 109.8, "close": 110.8}
    df = pd.DataFrame(rows)
    assert detect_zone_trigger(df, "LONG", 100.0, 101.0, 1.0) is None       # far from zone
    assert detect_zone_trigger(df, "LONG", 109.0, 109.9, 1.0) is not None   # on the zone


def test_mtf_candle_text_respects_direction():
    from analysis.mtf_candles import _describe
    c = {"body_frac": 0.2, "upper_wick": 3.0, "lower_wick": 0.1, "range": 4.0, "body": 0.8,
         "bull": False, "bear": True, "close": 100.0, "open": 100.8, "high": 103.8, "low": 99.9}
    out = _describe("1h", c, None, "LONG", True, False)
    assert out and "قابل تفسیر" not in out["text"]
    out2 = _describe("1h", c, None, "SHORT", False, True)
    assert out2 and "قابل تفسیر" in out2["text"]


def test_spot_freshness_is_one_candle():
    import inspect
    from analysis import spot_engine
    assert "_limit_h = float(_tf_hours) if tf in" in inspect.getsource(spot_engine._fresh)
