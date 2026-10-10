"""10-12 chart honesty (his GEO/JUP/ZEC/ONDO/ETC annotations):
  H1  spot axis: dense version-proof ticks on sub-decade views (his ETC).
  H2  _spot_is_breakdown: ONDO (desc-channel LONG) keeps its box; ETHFI skips.
  H3  box ceiling bounded to the pattern window (ancient highs ignored).
  H4  far boxes clip without squashing candles; near boxes fit whole.
  H5  extend_line_to_new_base: cross+base extends; wick fakeout ignored.
"""
import io

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd


def _frame(n=90, start=11.0, end=8.4, seed=7):
    rng = np.random.default_rng(seed)
    base = np.linspace(start, end, n) + rng.normal(0, 0.12, n).cumsum() * 0.15
    o = base + rng.normal(0, 0.05, n)
    c = base + rng.normal(0, 0.05, n)
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.08, n))
    l = np.minimum(o, c) - np.abs(rng.normal(0, 0.08, n))
    ts = pd.date_range("2026-09-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": l,
                         "close": c, "volume": rng.uniform(50, 150, n)})


def _cand(symbol="ETCUSDT", tf="4h", stage="BREAK_UP", box_top=0.0,
          pat_type="TRENDLINE", name_fa="", lines=None):
    from analysis.models import SignalCandidate
    return SignalCandidate(
        signal_id="h12", symbol=symbol, style="x", setup_code="SPOTBREAK",
        setup_name="s", strategy_fa="f", direction="LONG", score=1,
        status="WATCH", entry_zone_bottom=1.0, entry_zone_top=1.0,
        planned_entry=1.0, sl=1.0, tp1=1.0, tp2=1.0, rr_tp1=1.0, rr_tp2=1.0,
        bias="LONG", trigger_timeframe=tf,
        market={"asset_class": "CRYPTO", "venue": "BYBIT"},
        metadata={"market": "SPOT", "engine": "SPOT", "log_scale": True,
                  "spot_alert_stage": stage, "spot_alert_side": "HIGH",
                  "pattern_type": pat_type, "spot_box_top": box_top,
                  "render_patterns": [{"type": pat_type, "name_fa": name_fa,
                                       "lines": lines or []}]},
    )


def _render_capture(frame, cand, confirmed=False):
    """Render through the spot renderer, capturing the live figure."""
    from matplotlib.figure import Figure
    from analysis.spot_pattern_engine import render_cryptocove_spot_chart as R
    figs = []
    orig = Figure.savefig

    def _cap(self, *a, **k):
        figs.append(self)
        return orig(self, *a, **k)

    Figure.savefig = _cap
    try:
        png = R(frame, cand, confirmed=confirmed)
    finally:
        Figure.savefig = orig
    assert png and len(png) > 1000
    return figs[-1]


def _inview_ticks(ax):
    lo, hi = ax.get_ylim()
    return [float(t) for t in ax.get_yticks() if lo <= t <= hi]


# ── H1 ────────────────────────────────────────────────────────────────
def test_spot_axis_dense_on_subdecade():
    fr = _frame()
    ts = list(fr["timestamp"])
    line = {"side": "HIGH", "slope": -0.03, "intercept": 11.0, "x0": 5,
            "x1": 89, "points": [{"ts": str(ts[5]), "price": 10.9},
                                 {"ts": str(ts[40]), "price": 9.8}]}
    fig = _render_capture(fr, _cand(box_top=11.3, lines=[line]))
    ax = fig.axes[0]
    assert type(ax.yaxis.get_major_locator()).__name__ == "FixedLocator"
    assert len(_inview_ticks(ax)) >= 5


# ── H2 ────────────────────────────────────────────────────────────────
def test_is_breakdown_only_on_stage():
    from analysis.spot_pattern_engine import _spot_is_breakdown as B
    assert B("CONFIRMED") is False          # ONDO keeps its box
    assert B("BREAK_UP") is False           # ZEC keeps its box
    assert B("TOUCH") is False
    assert B("BREAK_DOWN") is True          # ETHFI still skips
    assert B("CONFIRMED", "SHORT") is True


def test_ondo_box_drawn_zec_box_drawn():
    fr = _frame()
    ts = list(fr["timestamp"])
    line = {"side": "HIGH", "slope": -0.02, "intercept": 10.0, "x0": 5,
            "x1": 89, "points": [{"ts": str(ts[5]), "price": 9.9}]}
    fig = _render_capture(
        fr, _cand(stage="CONFIRMED", pat_type="CHANNEL_DESCENDING",
                  name_fa="کانال نزولی", box_top=12.0, lines=[line]),
        confirmed=True)   # the real confirm path renders confirmed=True
    ax = fig.axes[0]
    assert any("%" in (t.get_text() or "") for t in ax.texts)


# ── H3 ────────────────────────────────────────────────────────────────
def test_ceiling_bounded_to_pattern_window():
    from analysis.spot_engine import _structural_high_above as S
    n = 120
    px = np.full(n, 1.00)
    px[40] = 1.80     # old spike: inside the 90-lookback, before the floor
    px[100] = 1.08    # recent minor high inside the pattern window
    d = pd.DataFrame({"high": px})
    assert S(d, 1.0, floor_idx=66) == 1.08
    d2 = pd.DataFrame({"high": np.where(np.arange(n) == 40, 1.80, 1.00)})
    assert S(d2, 1.0, floor_idx=66) is None     # pre-window ignored ...
    assert S(d2, 1.0, floor_idx=0) == 1.80      # ... unless unbounded


# ── H4 ────────────────────────────────────────────────────────────────
def test_far_box_clips_without_squash_near_box_fits():
    fr = _frame()
    ts = list(fr["timestamp"])
    line = {"side": "HIGH", "slope": -0.03, "intercept": 11.0, "x0": 5,
            "x1": 89, "points": [{"ts": str(ts[5]), "price": 10.9}]}
    dtop = float(fr["high"].max())
    fig = _render_capture(fr, _cand(box_top=dtop * 2.0, lines=[line]))
    assert fig.axes[0].get_ylim()[1] < dtop * 1.5     # candles fill
    assert any("%" in (t.get_text() or "") for t in fig.axes[0].texts)
    fig2 = _render_capture(fr, _cand(box_top=dtop * 1.1, lines=[line]))
    assert fig2.axes[0].get_ylim()[1] >= dtop * 1.1   # whole box fits


# ── H5 ────────────────────────────────────────────────────────────────
def _ext_frame(fakeout=False):
    n = 60
    ts = pd.date_range("2026-09-01", periods=n, freq="4h", tz="UTC")
    line = lambda x: 100.0 - 0.2 * (x - 10)   # anchor (10, 100), slope -0.2
    c = np.array([line(x) - 0.5 for x in range(n)])
    h = c + 0.3
    l = c - 0.3
    if not fakeout:
        for x in range(40, 56):                # cross + base beyond
            c[x] = line(x) + 1.0
            h[x] = c[x] + 0.3
            l[x] = c[x] - 0.3
        h[50] = line(50) + 2.0                 # new extreme swing high (94)
        c[50] = line(50) + 1.5
    else:
        h[45] = line(45) + 2.0                 # lone wick pierce, body inside
    return (pd.DataFrame({"timestamp": ts, "open": c, "high": h, "low": l,
                          "close": c, "volume": np.full(n, 100.0)}), line)


def test_extend_cross_and_base_wick_fakeout_ignored():
    from analysis.render_kit import extend_line_to_new_base as E
    df, _ = _ext_frame()
    ln = {"side": "HIGH", "slope": -0.2, "intercept": 102.0, "x0": 10,
          "x1": 59, "points": [{"ts": "2026-09-01", "price": 100.0}]}
    out = E(ln, df, "HIGH")
    assert out.get("extended73") is True
    assert abs(out["slope"] - (-0.15)) < 0.02   # (10,100)->(50,94)
    assert len(out["points"]) == 2
    df2, _ = _ext_frame(fakeout=True)
    assert E(ln, df2, "HIGH") is ln


def test_extend_low_side_mirror():
    from analysis.render_kit import extend_line_to_new_base as E
    n = 60
    ts = pd.date_range("2026-09-01", periods=n, freq="4h", tz="UTC")
    line = lambda x: 50.0 + 0.1 * (x - 10)
    c = np.array([line(x) + 0.5 for x in range(n)])
    h = c + 0.3
    l = c - 0.3
    for x in range(40, 56):
        c[x] = line(x) - 1.0
        l[x] = c[x] - 0.3
        h[x] = c[x] + 0.3
    l[50] = line(50) - 2.0                    # new extreme swing low (52)
    c[50] = line(50) - 1.5
    df = pd.DataFrame({"timestamp": ts, "open": c, "high": h, "low": l,
                       "close": c, "volume": np.full(n, 100.0)})
    ln = {"side": "LOW", "slope": 0.1, "intercept": 49.0, "x0": 10,
          "x1": 59, "points": [{"ts": "2026-09-01", "price": 50.0}]}
    out = E(ln, df, "LOW")
    assert out.get("extended73") is True
    assert abs(out["slope"] - 0.05) < 0.02    # (10,50)->(50,52)


# ── H6 ────────────────────────────────────────────────────────────────
def test_extend_never_flips_slope_sign():
    """A sign-flip is a different move (R67 pole vs drift), not an extension:
    the descending line stays untouched when the only base sits higher."""
    from analysis.render_kit import extend_line_to_new_base as E
    n = 60
    ts = pd.date_range("2026-09-01", periods=n, freq="4h", tz="UTC")
    line = lambda x: 100.0 - 0.2 * (x - 10)
    c = np.array([line(x) - 0.5 for x in range(n)])
    h = c + 0.3
    l = c - 0.3
    for x in range(40, 56):                    # base ABOVE the anchor high
        c[x] = 104.0
        h[x] = c[x] + 0.3
        l[x] = c[x] - 0.3
    h[50] = 106.0
    c[50] = 105.0
    df = pd.DataFrame({"timestamp": ts, "open": c, "high": h, "low": l,
                       "close": c, "volume": np.full(n, 100.0)})
    ln = {"side": "HIGH", "slope": -0.2, "intercept": 102.0, "x0": 10,
          "x1": 59, "points": [{"ts": "2026-09-01", "price": 100.0}]}
    assert E(ln, df, "HIGH") is ln


def test_flag_vocabulary_survives_extension():
    """R67 pole+flag still classifies FLAG (the extension must not eat it)."""
    from analysis.render_kit import detect_patterns
    close = np.concatenate([np.full(40, 100.0), 100 + np.linspace(0, 7, 12),
                            np.linspace(107, 105.4, 30), np.full(8, 105.4)])
    n = len(close)
    df = pd.DataFrame({"close": close, "open": close, "high": close + 0.4,
                       "low": close - 0.4, "volume": [100.0] * n,
                       "timestamp": pd.date_range("2026-10-01", periods=n,
                                                  freq="15min")})
    pats = detect_patterns(df.reset_index(drop=True), "LONG")
    assert any(p["type"] in ("FLAG_BULL", "FLAG_BEAR",
                             "PENNANT_BULL", "PENNANT_BEAR") for p in pats)
