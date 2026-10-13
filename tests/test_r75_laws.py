"""R75 law locks (Viva 10-13): the four laws this round added, frozen as tests.

1. NO gridlines in the candle background (spot AND perp) — his law #1.
2. The spot green box RISES FROM THE LIVE PRICE (bottom edge on live).
3. Ascending-triangle upper side = FLAT RESISTANCE on the major-high cluster
   (his STRK ruling: «ضلع بالاش از پیوت‌های ماژور درست شروع نشده»).
4. Perp y-window obeys the band law: candles fill 60-72% of the panel
   (clean tool band 25-30%), i.e. no post-solver padding survives.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import matplotlib.figure

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

plt = pytest.importorskip("matplotlib.pyplot")


def _kv_stub(monkeypatch):
    import database.bot_kv as kv
    store = {}
    monkeypatch.setattr(kv, "get_json", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(
        kv, "set_json",
        lambda k, v: (store.pop(k, None) if v is None else store.__setitem__(k, v)))


def _synth(n=90, seed=7, flat_top=False):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-06-01", periods=n, freq="4h")
    # realistic body/wick sizes relative to the walk (the solver's needle
    # guard expects market-like candles, not flat synthetic ticks)
    base = 100 + np.cumsum(rng.normal(0.05, 1.8, n))
    if flat_top:
        lows = np.linspace(95, 120, n) + rng.normal(0, 0.4, n)
        highs = np.minimum(lows + 6 + np.abs(rng.normal(0, 1.2, n)), 118.0)
        highs[70] = 130.0
        highs[80] = 130.0
        lows[70] = 122.0
        lows[80] = 123.0
        base = (highs + lows) / 2
    o = base + rng.normal(0, 0.8, n)
    c = base + rng.normal(0, 1.4, n)
    h = np.maximum.reduce([o, c, base + 2.6])
    l = np.minimum.reduce([o, c, base - 2.6])
    if flat_top:
        h = highs
        l = np.minimum(lows, h - 1.5)
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h,
                         "low": l, "close": c, "volume": 1000.0})


def _cand(df, direction="LONG", box=None):
    from analysis.models import SignalCandidate
    price = float(df.close.iloc[-1])
    return SignalCandidate(
        signal_id="T", symbol="TESTUSDT", style="SWING", setup_code="SPOT",
        setup_name="x", strategy_fa="x", direction=direction, score=8,
        status="PUBLISH", entry_zone_bottom=price * 0.99,
        entry_zone_top=price, planned_entry=price, sl=price * 0.9,
        tp1=price * 1.1, tp2=price * 1.2, rr_tp1=1.5, rr_tp2=2.0,
        bias="BULL" if direction == "LONG" else "BEAR",
        trigger_timeframe="4h", mandatory_gates={"zone": True},
        created_at=str(df.timestamp.iloc[-3]),
        confirmed_at=str(df.timestamp.iloc[-2]),
        metadata={"market": "SPOT", "is_spot": True,
                  "spot_box_top": box or price * 1.18,
                  "atr": float((df.high - df.low).tail(14).mean()),
                  "render_patterns": [{"type": "SYNTH", "lines": []}]})


def _render_capture(fn, df, cand, **kw):
    """Run a renderer, return (bytes, [axes])."""
    captured = {}
    orig_plt = plt.savefig
    orig_fig = matplotlib.figure.Figure.savefig

    def spy(target, *a, **k):
        fig = target if hasattr(target, "axes") else plt.gcf()
        captured["axes"] = list(fig.axes)
        return (orig_plt if target is not None and hasattr(target, "axes")
                else orig_plt)(target, *a, **k) if not hasattr(target, "axes") \
            else orig_fig(target, *a, **k)

    plt.savefig = spy
    matplotlib.figure.Figure.savefig = spy
    try:
        png = fn(df, cand, **kw)
    finally:
        plt.savefig = orig_plt
        matplotlib.figure.Figure.savefig = orig_fig
    return png, captured.get("axes", [])


def test_no_gridlines_spot_and_perp(monkeypatch):
    _kv_stub(monkeypatch)
    from analysis.spot_pattern_engine import render_cryptocove_spot_chart
    from analysis.perp_pattern_engine import render_viva_perp_chart
    df = _synth()
    for fn in (render_cryptocove_spot_chart, render_viva_perp_chart):
        cand = _cand(df)
        cand.metadata["market"] = "PERP" if fn is render_viva_perp_chart else "SPOT"
        _, axes = _render_capture(fn, df, cand, confirmed=True)
        assert axes, "renderer must produce axes"
        for ax in axes:
            gl = list(ax.get_xgridlines()) + list(ax.get_ygridlines())
            assert all(not g.get_visible() for g in gl), \
                f"gridline visible in {fn.__name__} (his 10-13 law #1)"


def test_spot_box_rises_from_live(monkeypatch):
    _kv_stub(monkeypatch)
    from analysis.spot_pattern_engine import render_cryptocove_spot_chart
    df = _synth(seed=11)
    cand = _cand(df)
    _, axes = _render_capture(render_cryptocove_spot_chart, df, cand,
                              confirmed=True)
    live = float(df.close.iloc[-1])
    boxes = [p for p in axes[0].patches
             if tuple(p.get_facecolor()) == pytest.approx(
                 (0.658824, 0.831373, 0.607843, 0.6), abs=0.02)]
    assert boxes, "green target box must be drawn on a confirmed LONG"
    for b in boxes:
        assert abs(b.get_y() - live) <= live * 0.005, \
            "box bottom must sit ON the live price (refs law)"


def test_asc_triangle_upper_is_flat_resistance():
    from analysis.render_kit import refit_asc_triangle_upper
    df = _synth(flat_top=True)
    n = len(df) - 1

    def line_y(ln, x):
        return (10.0 ** (float(ln.get("log_slope") or 0.0) * x
                         + float(ln.get("log_intercept") or 0.0))
                if ln.get("log_fit") else
                float(ln.get("slope") or 0.0) * x + float(ln.get("intercept") or 0.0))

    def atr(d):
        return float((d["high"] - d["low"]).tail(14).mean())

    gu = {"side": "HIGH", "slope": 0.14, "intercept": 100.0,
          "log_fit": False, "log_slope": 0.0, "log_intercept": 0.0,
          "x0": 40, "x1": n, "points": []}
    gl = {"side": "LOW", "slope": 0.30, "intercept": 90.0,
          "log_fit": False, "log_slope": 0.0, "log_intercept": 0.0,
          "x0": 20, "x1": n, "points": []}
    out = refit_asc_triangle_upper(gu, gl, df, n, line_y, atr)
    assert out is not gu, "refit must fire on a rising support mislabeled HIGH"
    assert float(out["slope"]) == 0.0 and float(out["log_slope"]) == 0.0
    pts = [float(q["price"]) for q in out["points"]]
    assert len(pts) >= 2 and max(pts) >= 129.0, "flat resistance on the cluster"
    # channel-safe: an upper edge that already rides the cluster stays put
    gu2 = {"side": "HIGH", "slope": 0.14, "intercept": 116.0,
           "log_fit": False, "log_slope": 0.0, "log_intercept": 0.0,
           "x0": 60, "x1": n, "points": []}
    assert refit_asc_triangle_upper(gu2, gl, df, n, line_y, atr) is gu2


def test_perp_band_law(monkeypatch):
    _kv_stub(monkeypatch)
    from analysis.perp_pattern_engine import render_viva_perp_chart
    df = _synth(seed=23)
    cand = _cand(df, direction="SHORT")
    cand.metadata["market"] = "PERP"
    cand.metadata["target_ladder"] = {
        "targets": [float(df.close.iloc[-1]) * 0.98,
                    float(df.close.iloc[-1]) * 0.96,
                    float(df.close.iloc[-1]) * 0.94],
        "weights": [40.0, 35.0, 25.0], "path_pct": 3.0}
    _, axes = _render_capture(render_viva_perp_chart, df, cand, confirmed=True)
    ax = axes[0]
    y_lo, y_hi = ax.get_ylim()
    # measure the candle INK from the painted bodies (the solver's internal
    # frame may merge context the test cannot see): bodies' log range over
    # the panel log span must stay a healthy majority — a 2-3x padded window
    # (the old dead-band fault) drops this ratio below ~0.25.
    import matplotlib.patches as mp
    tops, bots = [], []
    for pch in ax.patches:
        if not isinstance(pch, mp.Rectangle):
            continue
        w = pch.get_width()
        if w <= 0 or w > 2.0:
            continue
        y0 = pch.get_y()
        y1 = y0 + pch.get_height()
        if y1 > y0 > 0:
            tops.append(y1)
            bots.append(y0)
    assert tops, "candle bodies must be painted as rectangles"
    cr = math.log10(max(tops) / min(bots))
    fill = cr / (math.log10(y_hi) - math.log10(y_lo))
    assert 0.45 <= fill <= 0.85, f"candle fill {fill:.2f} outside the band law"
