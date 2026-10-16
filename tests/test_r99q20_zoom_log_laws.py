"""R99q20 — PATTERN-COMPLETENESS ZOOM + LOG-FIT TRUTH (Viva 10-16 evening).

Verbatim: «کندل‌ها و وج از بالای وسط چارت وارد شده بودند .. در این مواقع باید تعداد
بیشتری کندل وارد چارت کرد .. زوم رو طوری تنظیم کرد که … حتی اگر از بالا وارد می‌شه
از گوشهٔ بالای سمت چپ وارد بشه تا اون پترن بهترین نما رو داشته باشه و کامل باشه.
بعد اینکه دقت بکن ببین الان از نماگر کندل بصورت هوشمند لگاریتمی استفاده می‌شه؟؟»

  1. LOG-FIT TRUTH — the fit space IS the paint space: every chart is painted on a
     log axis (r57), so every fit must be log-calibrated; the old conditional test
     left 15m/30m frames fitted LINEAR and painted LOG (a line that bows away from
     its own pivots). `VIVA_LOG_FIT_OFF=1` is the emergency escape.
  2. PATTERN-COMPLETENESS ZOOM — the x-window must contain every stored edge's
     first anchor (+ context candles): a wedge may never enter the picture from the
     TOP border mid-frame (LIT 1h: first pivot 18 bars left of the window edge).
"""
import math
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.render_kit import _chart_will_be_log, pattern_live_index  # noqa: E402


def _df(n=240, base=100.0, span=0.35):
    ts = pd.date_range("2026-08-01", periods=n, freq="1h")
    px = [base * (1.0 + span * (i / n)) for i in range(n)]
    return pd.DataFrame({"timestamp": ts, "open": px, "high": [p * 1.01 for p in px],
                         "low": [p * 0.99 for p in px], "close": px, "volume": [1.0] * n})


class _C:
    def __init__(self, tf="15m", setup="TECHCLASSIC", md=None):
        self.trigger_timeframe = tf
        self.setup_code = setup
        self.metadata = md or {}


def test_r99q20_log_fit_is_the_paint_space_on_every_tf(monkeypatch):
    """15m/30m with a <35 % span used to fit LINEAR while painting LOG."""
    monkeypatch.delenv("VIVA_LOG_FIT_OFF", raising=False)
    for tf in ("15m", "30m", "1h", "4h", "1d"):
        assert _chart_will_be_log(_C(tf=tf), _df()) is True, tf
    # a flat tape is still log-fittable (the axis stays log — r57 law)
    assert _chart_will_be_log(_C(tf="15m"), _df(span=0.005)) is True
    # spot: always log (unchanged)
    assert _chart_will_be_log(_C(tf="4h", md={"log_scale": True}), _df()) is True
    # emergency escape keeps the legacy conditional behaviour
    monkeypatch.setenv("VIVA_LOG_FIT_OFF", "1")
    flat = _df(span=0.005)
    assert _chart_will_be_log(_C(tf="15m"), flat) is False


def _df(n=400, base=3.2, span=0.16, freq="1h", start="2026-08-01"):
    ts = pd.date_range(start, periods=n, freq=freq)
    px = [base * (1.0 + span * (i / n)) for i in range(n)]
    return pd.DataFrame({"timestamp": ts, "open": px, "high": [p * 1.01 for p in px],
                         "low": [p * 0.99 for p in px], "close": px, "volume": [1.0] * n})


def test_r99q20_anchors_map_by_pivot_time_not_fit_space():
    """LIT 1h measured: stored x0 99 + offset 135 = 234, while the pivot's true
    row was 94 of 200 — the fit-space sum is a DIFFERENT tape's coordinate."""
    from bot.messages_v7 import pattern_frame_anchors
    tape = _df(200, start="2026-10-08 06:00")
    md = {"render_patterns": [{"type": "WEDGE_FALLING", "lines": [
        {"side": "HIGH", "x0": 99, "x1": 204, "log_fit": True,
         "points": [{"ts": "2026-10-12 05:00", "price": 3.99}]},
        {"side": "LOW", "x0": 35, "x1": 204, "log_fit": True,
         "points": [{"ts": "2026-10-09 13:00", "price": 3.52}]}]}]}
    rows = pattern_frame_anchors(md, tape["timestamp"])
    assert rows, "no anchors mapped"
    # 10-09 13:00 -> row 31, 10-12 05:00 -> row 95 (the real LIT frame had
    # 94/30 in a 200-row paint frame; the fit-space sum gave 234 instead)
    assert min(rows) == 31 and max(rows) == 95
    assert 234 not in rows and 135 + 99 not in rows     # the old wrong math
    # a pattern whose pivots are all off-frame contributes nothing
    md2 = {"render_patterns": [{"type": "X", "ts0": "2020-01-01 00:00",
                                "lines": [{"points": [{"ts": "2020-01-02 00:00"}]}]}]}
    assert all(r in (0, len(tape)) for r in pattern_frame_anchors(md2, tape["timestamp"]))


def test_r99q20_lift_brings_the_pattern_head_on_canvas():
    """An upper edge above the window at the VISIBLE LEFT EDGE must pull the
    y-window up (entry at the top-left corner); the same for a lower edge at
    the floor — and a FAR edge (beyond 8 ATR) must never crush the candles."""
    from bot.messages_v7 import pattern_window_lift
    tape = _df(200, base=3.2, span=0.16)
    atr = float((tape["high"] - tape["low"]).tail(14).mean())
    top = 4.26   # tape top is ~3.7 here
    up = {"type": "WEDGE_FALLING", "lines": [
        {"side": "HIGH", "log_fit": True, "log_slope": 0.0,
         "log_intercept": math.log10(top), "points": []}]}
    lift, drop = pattern_window_lift(tape, [up], {}, 54.0, cap_mult=8.0)
    assert lift is not None and abs(lift - top) < 1e-6, lift
    assert drop is None
    # same edge, but 20 ATR above the tape → far context, no lift
    far = {"type": "WEDGE", "lines": [
        {"side": "HIGH", "log_fit": True, "log_slope": 0.0,
         "log_intercept": math.log10(float(tape["high"].max()) + 20 * atr),
         "points": []}]}
    assert pattern_window_lift(tape, [far], {}, 54.0, cap_mult=8.0)[0] is None
    # the r613 shell pair is honoured too (that is the bold line the eye reads)
    fits = {"viva_upper_points": (None, None, "log", 0.0, math.log10(top)),
            "viva_lower_points": (None, None, "log", 0.0,
                                  math.log10(float(tape["low"].min()) - 2 * atr))}
    lift2, drop2 = pattern_window_lift(tape, [], fits, 54.0, cap_mult=8.0)
    assert lift2 is not None and abs(lift2 - top) < 1e-6
    assert drop2 is not None


