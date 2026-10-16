"""R99q22 — the PATTERN SELECTION law (his 10-17 seven conditions).

Verbatim: «باید پترنی انتخاب بشه که حتما قیمت ۱- داخل پترن باشه ۲- نزدیک به ضلع
بالا یا پایین پترن باشه ۳- در حال ریتست روی ضلع بالای پترن باشه ۴- در حال ریتست
و برخورد از پایین به سمت زیر ضلع پترن باشه … ۵- ضلع بالا یا پایین پترن رو بریک
کرده اما در همون کندل یا چند کندل بعدش دوباره وارد پترن شده … ۶- ترند بالایی و
پایینی پترن … باید اکستند بشه به پیوت‌های جدید بالا و پایین … ۷- همین شرایط
برای ترندلاین‌های سینگل هم برقرار باید شود».

Each test below is one of those seven sentences, encoded.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.pattern_law import (      # noqa: E402
    ACTIONABLE_STATES, SELECTION_STATES, select_state, trendline_state,
    selection_for_shape)
from analysis.render_kit import extend_lines_to_live   # noqa: E402

ATR = 1.0


def _frame(closes, highs=None, lows=None):
    n = len(closes)
    closes = [float(c) for c in closes]
    highs = [float(h) for h in (highs or [c + 0.2 for c in closes])]
    lows = [float(l) for l in (lows or [c - 0.2 for c in closes])]
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-10-01", periods=n, freq="15min"),
        "open": closes, "high": highs, "low": lows, "close": closes,
        "volume": [1.0] * n,
    })


def _wedge_edges(n=120):
    """A converging pair: upper 130-0.25·x (slope -0.25), lower 100-0.10·x."""
    up = {"slope": -0.25, "intercept": 130.0, "x0": 0, "x1": n - 1, "side": "HIGH"}
    lo = {"slope": -0.10, "intercept": 100.0, "x0": 0, "x1": n - 1, "side": "LOW"}
    return up, lo


def _up_at(up, x):  return up["slope"] * x + up["intercept"]
def _lo_at(lo, x):  return lo["slope"] * x + lo["intercept"]


def _path_below_upper(up, lo, n=120, gap=0.4):
    """Price rides 0.4 ATR under the UPPER edge, well inside the band."""
    return [_up_at(up, x) - gap for x in range(n)]


# ─────────────────── ۱) price INSIDE the pattern ───────────────────
def test_condition_1_price_inside_the_pattern_is_selectable():
    up, lo = _wedge_edges()
    mid = [(_up_at(up, x) + _lo_at(lo, x)) / 2.0 for x in range(120)]
    info = select_state(_frame(mid), up, lo, ATR)
    assert info["ok"] is True
    assert info["state"] in ("INSIDE", "AT_EDGE")
    assert info["dist_atr"] is not None


# ─────────────────── ۲) price NEAR an edge ───────────────────
def test_condition_2_price_near_the_upper_edge_is_at_edge():
    up, lo = _wedge_edges()
    info = select_state(_frame(_path_below_upper(up, lo, gap=0.4)), up, lo, ATR)
    assert info["state"] == "AT_EDGE" and info["side"] == "UPPER"
    # and the same law works from under the lower edge
    under = [_lo_at(lo, x) + 0.4 for x in range(120)]
    info2 = select_state(_frame(under), up, lo, ATR)
    assert info2["state"] == "AT_EDGE" and info2["side"] == "LOWER"


# ─────────────────── ۳) RETEST of the broken UPPER edge ───────────────────
def test_condition_3_retest_of_the_broken_upper_edge_from_above():
    up, lo = _wedge_edges()
    n = 120
    closes = []
    for x in range(n):
        u = _up_at(up, x)
        if x < n - 40:
            closes.append(u - 1.0)                 # inside, under the edge
        elif x < n - 30:
            closes.append(u + 1.5)                 # the break (first entry)
        else:
            closes.append(u + 0.45)                # pulled back to the edge
    info = select_state(_frame(closes), up, lo, ATR)
    assert info["state"] == "RETEST_UPPER"
    assert info["retest_from"] == "ABOVE"
    assert info["ok"] is True


# ─────────────────── ۴) RETEST of the broken LOWER edge ───────────────────
def test_condition_4_retest_of_the_broken_lower_edge_from_below():
    up, lo = _wedge_edges()
    n = 120
    closes = []
    for x in range(n):
        l = _lo_at(lo, x)
        if x < n - 40:
            closes.append(l + 1.0)                 # inside, above the lower edge
        elif x < n - 30:
            closes.append(l - 1.5)                 # broke DOWN
        else:
            closes.append(l - 0.45)                # came back up to the edge
    info = select_state(_frame(closes), up, lo, ATR)
    assert info["state"] == "RETEST_LOWER"
    assert info["retest_from"] == "BELOW"
    assert info["ok"] is True


# ─────────────────── ۵) break then RE-ENTRY in a candle or two ────────────
def test_condition_5_break_that_reenters_the_pattern_stays_live():
    up, lo = _wedge_edges()
    n = 120
    closes = []
    for x in range(n):
        u = _up_at(up, x)
        if x < n - 40:
            closes.append(u - 1.0)
        elif x == n - 40:
            closes.append(u + 0.4)                  # pierced the edge…
        elif x == n - 39:
            closes.append(u - 0.6)                  # …and closed back INSIDE
        else:
            closes.append(u + 1.6)                  # then drifted away above
    info = select_state(_frame(closes), up, lo, ATR)
    assert info["failed_break"] is True
    assert info["state"] == "FAILED_BREAK"
    assert info["ok"] is True, "a failed break is still a live pattern, not past-market"


def test_only_a_pattern_price_left_behind_is_stale():
    up, lo = _wedge_edges()
    n = 120
    closes = [_up_at(up, x) - 1.0 for x in range(n - 40)] + \
             [_up_at(up, x) + 6.0 for x in range(n - 40, n)]   # left long ago
    info = select_state(_frame(closes), up, lo, ATR)
    assert info["state"] == "STALE" and info["ok"] is False


# ─────────────────── ۶) lines extend to the new pivots ───────────────────
def test_condition_6_pattern_lines_extend_to_the_live_bar():
    up, lo = _wedge_edges()
    n = 120
    shape = {"type": "WEDGE_FALLING",
             "lines": [dict(up, x1=n - 30), dict(lo, x1=n - 30)]}
    closes = [(_up_at(up, x) + _lo_at(lo, x)) / 2.0 for x in range(n)]
    extend_lines_to_live(shape, _frame(closes), ATR)
    assert shape["lines"][0]["x1"] == n - 1 and shape["lines"][1]["x1"] == n - 1
    assert shape.get("lines_extended") is True


def test_condition_6_a_destroyed_boundary_is_reanchored_not_sliced():
    """His condition 6 in full: «اکستند بشه به پیوت‌های جدید بالا و پایین
    بشرط اینکه اعتبار اون ترندها از بین نره». When price blasts through the
    edge and builds a new base there, the line is RE-ANCHORED to the new
    pivots (the R73 law he gave on 10-12) instead of being blindly extended —
    and it must never end up slicing through the live price."""
    from analysis.render_kit import line_y
    up, lo = _wedge_edges()
    n = 120
    shape = {"type": "WEDGE_FALLING",
             "lines": [dict(up, x1=n - 30), dict(lo, x1=n - 30)]}
    closes = [(_up_at(up, x) + _lo_at(lo, x)) / 2.0 for x in range(n - 10)]
    closes += [_up_at(up, x) + 3.0 for x in range(n - 10, n)]   # blasted through
    extend_lines_to_live(shape, _frame(closes), ATR)
    ln = shape["lines"][0]
    assert ln["x1"] == n - 1, "the boundary still has to reach the live bar"
    assert ln["slope"] != up["slope"], "it was re-anchored to the new pivots"
    assert line_y(ln, n - 1) - closes[-1] <= 0.75 * ATR, \
        "the re-anchored boundary must sit on the new base, not cut price"


# ─────────────────── ۷) the single-trendline lane ───────────────────
def _line(slope=-0.20, intercept=120.0, n=120):
    return {"slope": slope, "intercept": intercept, "x0": 0, "x1": n - 1,
            "side": "HIGH"}


def test_condition_7_single_line_fresh_break_and_touch_and_retest():
    n = 120
    ln = _line()
    lv = lambda x: -0.20 * x + 120.0
    # (a) price hugging the line from below = TOUCH (approaching the resistance)
    touch = [lv(x) - 0.4 for x in range(n)]
    info = trendline_state(_frame(touch), ln, ATR)
    assert info["state"] in ("TOUCH", "NEAR") and info["role"] == "RESISTANCE"
    # (b) a closed breakthrough two bars ago = FRESH_BREAK
    brk = [lv(x) - 1.5 for x in range(n - 3)] + [lv(x) + 0.9 for x in range(n - 3, n)]
    info2 = trendline_state(_frame(brk), ln, ATR)
    assert info2["state"] == "FRESH_BREAK" and info2["role"] == "SUPPORT"
    # (c) broke 30 bars ago, now magnetised back to the break-even = RETEST_BE
    back = [lv(x) - 1.0 for x in range(n - 40)] + \
           [lv(x) + 1.4 for x in range(n - 40, n - 6)] + \
           [lv(x) + 0.35 for x in range(n - 6, n)]
    info3 = trendline_state(_frame(back), ln, ATR)
    assert info3["state"] == "RETEST_BE"


def test_condition_7_touch_and_reject_and_compression_and_candle_evidence():
    n = 120
    ln = _line()
    lv = lambda x: -0.20 * x + 120.0
    # touch then close away (rejection) — the wick kisses, the body leaves
    closes = [lv(x) - 2.0 for x in range(n - 4)] + [lv(n - 1) - 2.0] * 4
    highs = [c + 0.2 for c in closes]
    highs[-1] = lv(n - 1) - 0.1          # the last wick reached the line
    frame = _frame(closes, highs=highs)
    info = trendline_state(frame, ln, ATR)
    assert info["state"] in ("REJECTED", "NEAR", "TOUCH")
    # compression: three shrinking candles hugging the line
    closes2 = [lv(x) - 1.0 for x in range(n - 3)]
    closes2 += [lv(x) - 0.8 for x in range(n - 3, n)]
    highs2 = [c + (0.9 if i < n - 3 else 0.25) for i, c in enumerate(closes2)]
    lows2 = [c - (0.9 if i < n - 3 else 0.25) for i, c in enumerate(closes2)]
    info2 = trendline_state(_frame(closes2, highs=highs2, lows=lows2), ln, ATR)
    assert info2["state"] in ("COMPRESSION", "TOUCH", "NEAR")
    assert info2["candle"] in ("DOJI", "PINBAR", "INV_PINBAR", None)


def test_condition_7_a_lone_line_is_never_deleted():
    n = 120
    ln = _line()
    far = [_line()["intercept"] + 30.0] * n          # price 30 ATR away
    shape = {"type": "TRENDLINE", "lines": [ln]}
    info = selection_for_shape(shape, _frame(far), ATR)
    assert info["state"] == "STALE" and info["one_line"] is True
    assert info["ok"] is True, "context lines stay on the chart"


def test_the_vocabulary_and_the_only_veto():
    assert "STALE" in SELECTION_STATES
    assert "RETEST_UPPER" in ACTIONABLE_STATES and "RETEST_LOWER" in ACTIONABLE_STATES
    assert set(ACTIONABLE_STATES) == set(SELECTION_STATES) - {"STALE"}


def test_spot_engine_raises_the_retest_stage():
    from analysis.spot_engine import _stage_for_pattern, STAGE_RANK
    assert STAGE_RANK.get("RETEST") is not None
    up, lo = _wedge_edges()
    n = 120
    closes = [_up_at(up, x) - 1.0 for x in range(n - 40)] + \
             [_up_at(up, x) + 1.4 for x in range(n - 40, n - 8)] + \
             [_up_at(up, x) + 0.30 for x in range(n - 8, n)]
    frame = _frame(closes)
    pat = {"type": "WEDGE_FALLING",
           "lines": [dict(up, x1=n - 1), dict(lo, x1=n - 1)],
           "select_state": "RETEST_UPPER"}
    atr = 1.0
    c, o = closes[-1], closes[-1]
    frame.loc[frame.index[-1], "open"] = o
    frame.loc[frame.index[-1], "close"] = c
    stage = _stage_for_pattern(pat, frame, atr, n)
    assert stage and stage["stage"] == "RETEST" and stage["side"] == "HIGH"
