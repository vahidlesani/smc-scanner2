"""R99q18 — SPOT CHART REPAIR (Viva 10-16).

Verbatim: «در تایم‌فریم‌های اسپات بیشترشون هم هندسه خرابه هم توضیحات هم تشخیص
پترن هم زوم خرابه هم ارتفاع ۷۲ درصد رعایت نشده ... ببین ستاپ‌ها رو خراب نکرده
باشی». Three laws are pinned here:

  1. ONE ENGINE PER PICTURE — the spot chart draws the ALERT's own render
     commands (the geometry its message speaks about); the second engine
     (`engine_spot.analyze`) survives only as the no-geometry fallback.
  2. THE BOX FOLLOWS THE STAGE — TOUCH never gets a target box; a BREAK stage
     may take the alert's own `spot_box_top`.
  3. THE 72 % ENVELOPE — a far target box can never squeeze the candle block
     below 60 % of the price panel.
"""
import math
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.models import SignalCandidate          # noqa: E402
import bot.messages_v7 as B7                          # noqa: E402


def _df(n=200, base=100.0, swing=1.0):
    ts = pd.date_range("2026-01-01", periods=n, freq="12h")
    px = [base * (1.0 + swing * 0.004 * math.sin(i / 7.0)) for i in range(n)]
    return pd.DataFrame({"timestamp": ts,
                         "open": px, "high": [p * 1.01 for p in px],
                         "low": [p * 0.99 for p in px], "close": px,
                         "volume": [1000.0] * n})


def _cand(stage="TOUCH", box_top=None, direction="LONG"):
    md = {"pattern_type": "DOUBLE_BOTTOM", "spot_alert_stage": stage,
          "spot_alert_side": "HIGH", "atr": 1.0,
          "render_patterns": [{"type": "DOUBLE_BOTTOM", "lines": [
              {"side": "HIGH", "log_fit": False, "slope": 0.0, "intercept": 99.0,
               "x0": 40, "x1": 190,
               "points": [{"ts": "2026-01-01 00:00:00", "price": 99.0},
                          {"ts": "2026-01-20 00:00:00", "price": 99.0}]}]}]}
    if box_top is not None:
        md["spot_box_top"] = box_top
    c = SignalCandidate(signal_id="T-STQ18", symbol="XMRUSDT", style="SWING",
                        setup_code="SPOTBREAK", setup_name="SPOT BREAKOUT",
                        strategy_fa="اسپات", direction=direction, score=8,
                        status="ACTIVE", entry_zone_bottom=98.0,
                        entry_zone_top=99.0, planned_entry=98.5, sl=95.0,
                        tp1=105.0, tp2=110.0, rr_tp1=1.5, rr_tp2=2.5, bias="BULL",
                        trigger_timeframe="12h")
    c.metadata = md
    return c


def test_r99q18_spot_chart_draws_the_alerts_own_geometry():
    """Law 1: the level on the chart IS the alert's own line, not a second engine."""
    df = _df()
    a = B7._spot_alert_view(_cand(box_top=None), df, "12h")
    assert a, "alert-driven view must exist when the candidate carries geometry"
    n = len(df) - 1
    from analysis.render_kit import line_y
    _cmd = _cand().metadata["render_patterns"][0]["lines"][0]
    assert abs(a["level"] - line_y(_cmd, n)) < 1e-9
    # the chart title comes from the alert's own pattern slug
    from tools.render_spot_cryptocove import pattern_title
    assert pattern_title(a["name_slug"]) == "Double Bottom"
    # the zoom anchor is the alert's own first pivot — never a fixed 200-bar cut
    _stamps = pd.to_datetime(df["timestamp"])
    _first_pivot_row = int(_stamps.searchsorted(pd.Timestamp("2026-01-01 00:00:00")))
    assert a["x0"] == min(_first_pivot_row, n) and a["x1"] == n


def test_r99q18_touch_never_gets_a_box():
    """His box law: باکس فقط برای شکست — a TOUCH stage charts stage=INSIDE."""
    a = B7._spot_alert_view(_cand(stage="TOUCH", box_top=110.0), _df(), "12h")
    assert a["target"] is None
    assert a["breakout"]["status"] == "INSIDE"


def test_r99q18_break_stage_takes_the_alerts_box_top():
    a = B7._spot_alert_view(_cand(stage="BREAK_UP", box_top=110.0), _df(), "12h")
    assert a["breakout"]["status"] == "BREAK_UP_CLOSED"
    assert a["target"] == pytest.approx(110.0)


def test_r99q18_second_engine_is_only_a_fallback():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "bot", "messages_v7.py"), encoding="utf-8").read()
    i_view = src.index("_a2 = _spot_alert_view(candidate, df, _tf2)")
    i_eng = src.index("_a2 = _es2.analyze(df, _tf2)")
    assert i_view < i_eng, "the alert's geometry must be tried BEFORE the engine"


def _ylim_spy():
    """Capture every ylim the renderer sets (the price panel is the one that
    brackets the visible candles)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.axes as _Ax
    seen = []
    _orig = _Ax.Axes.set_ylim

    def _spy(self, *a, **kw):
        r = _orig(self, *a, **kw)
        try:
            lo, hi = [float(v) for v in self.get_ylim()]
            seen.append((min(lo, hi), max(lo, hi)))
        except Exception:
            pass
        return r
    return _Ax, _orig, _spy, seen


def _visible_block(yml, d_lo, d_hi):
    cands = [(a, b) for (a, b) in yml if a > 0 and a <= d_lo and b >= d_hi]
    a, b = min(cands, key=lambda t: math.log(t[1]) - math.log(t[0]))
    return (math.log(d_hi) - math.log(d_lo)) / (math.log(b) - math.log(a))


def test_r99q18_envelope_guard_keeps_the_candles_at_72pct():
    """Law 3: a far target box may not squeeze the candle block below 60 %."""
    from tools import render_spot_cryptocove as RS

    _Ax, _orig, _spy, seen = _ylim_spy()
    _Ax.Axes.set_ylim = _spy
    try:
        df = _df(n=200, base=100.0, swing=0.09)
        d_lo, d_hi = float(df["low"].min()), float(df["high"].max())
        d_span = math.log(d_hi) - math.log(d_lo)
        target = 100.0 * math.exp(1.40 * d_span)          # box near the 1.5× ceiling
        a = B7._spot_alert_view(_cand(stage="BREAK_UP", box_top=target), df, "12h")
        a["target"] = target
        assert a["level"] > 0
        # the RAW (pre-guard) envelope: the box stretch alone leaves < 60 %
        raw_hi = max(RS.spot_y_window(d_lo, d_hi, d_span)[1],
                     target * math.exp(0.035 * d_span))
        raw_block = (math.log(d_hi) - math.log(d_lo)) / (
            math.log(raw_hi) - math.log(RS.spot_y_window(d_lo, d_hi, d_span)[0]))
        assert raw_block < 0.60, f"test setup did not stretch: {raw_block:.3f}"
        png = RS.render(df, a, None, symbol="XMRUSDT", stage="BREAK_UP")
    finally:
        _Ax.Axes.set_ylim = _orig
    assert png and len(png) > 1000
    assert _visible_block(seen, d_lo, d_hi) >= 0.599


def test_r99q18_base_spot_envelope_is_72pct():
    """A TOUCH chart carries no box, so the picture must sit exactly on the law."""
    from tools import render_spot_cryptocove as RS

    _Ax, _orig, _spy, seen = _ylim_spy()
    _Ax.Axes.set_ylim = _spy
    try:
        df = _df(n=200, base=100.0, swing=0.09)
        d_lo, d_hi = float(df["low"].min()), float(df["high"].max())
        a = B7._spot_alert_view(_cand(stage="TOUCH", box_top=110.0), df, "12h")
        assert a["target"] is None
        RS.render(df, a, None, symbol="XMRUSDT", stage="TOUCH")
    finally:
        _Ax.Axes.set_ylim = _orig
    blk = _visible_block(seen, d_lo, d_hi)
    assert 0.70 <= blk <= 0.76, f"base envelope {blk:.3f} off the 72 % law"
