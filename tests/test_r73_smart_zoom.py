"""R73-VIVA (2026-10-12) — smart zoom engine + design invariants.

His verbatim: «رندر نباید دیزاین چارت های من رو تغییر بده .. بکگراند .. رنگ کندلها
. رنگ خطوط .. اندازه قاب چارت کندلها .. لوگو های من در واترمارک و پایین صفحه …
پرپچوال زومش کاملا غلط بود .. باید بهترین پیوتها رو انتخاب بکنه و بعدش کندلها رو
هم از نظر ارتفاع هم از نظر تعداد در حدی انتخاب بکنه که همه جای ابزار لانگ شورت
باشه هم بهترین شکل پترن یا ترندلاین رسم بشه .. نه اینکه کل ارتفاع چارت رو از سقف
تا کف بیاره .. باید لگاریتمی باشه .. اگر شورت است … جای ابزار بمونه پایین نه ابزار
له بشه نه کندلها له بشن یا نباید از چارت بیرون بزنن .. اگر لانگ هم هست برعکس …
نباید محدودیت بذاریم .. باید موتور بهترین حالت و شرایط رو انتخاب بکنه که قیمت به
واکنش به اون پترن یا ترندلاین نزدیک باشه» + «ترندلاین های سینگل نباید روی هوا
شروع بشن بلکه باید بشینه روی پیوت .. چه بادی چه شدو».
"""

import math
import os
import sys

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from analysis.smart_zoom import (  # noqa: E402
    snap_points_to_pivots, solve_zoom, MAX_N,
)


def _tape(n=400, base=100.0, seed=7, spike_at=None, spike_frac=0.45):
    import numpy as np
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-09-01 00:00", periods=n, freq="1h")
    drift = np.cumsum(rng.normal(0, 0.4, n))
    close = base + drift
    high = close + rng.uniform(0.1, 0.6, n)
    low = close - rng.uniform(0.1, 0.6, n)
    if spike_at is not None:                       # old capitulation wick
        low[spike_at] = base * spike_frac
        high[spike_at] = base * (spike_frac + 0.05)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": high,
                         "low": low, "close": close,
                         "volume": rng.uniform(10, 90, n)})


def _cand(direction="LONG", **md):
    import uuid
    from analysis.models import SignalCandidate
    meta = {"atr": 0.6, "touched": True}
    meta.update(md)
    return SignalCandidate(
        signal_id="R73-" + uuid.uuid4().hex[:8], symbol="BTCUSDT", style="DAYTRADE",
        setup_code="TLBREAK", setup_name="t", strategy_fa="t",
        direction=direction, score=8, status="CONFIRMED",
        entry_zone_bottom=99.0, entry_zone_top=100.0, planned_entry=99.5,
        sl=97.0 if direction == "LONG" else 103.0,
        tp1=104.0 if direction == "LONG" else 95.0,
        tp2=108.0 if direction == "LONG" else 92.0,
        rr_tp1=1.5, rr_tp2=2.5, bias="BULL", trigger_timeframe="1h",
        mandatory_gates={"zone": True},
        created_at="2026-09-17T05:00:00+00:00",
        confirmed_at="2026-09-17T05:10:00+00:00", metadata=meta)


def _pats(ts0="2026-09-12 00:00", ts1="2026-09-16 00:00", p0=98.0, p1=101.0):
    """render_patterns dialect: points carry ``ts`` + the line carries the
    detection-time slope/intercept (exactly what detect_patterns stores)."""
    return [{"type": "CHANNEL_ASCENDING", "lines": [
        {"side": "HIGH", "slope": (p1 - p0) / 96.0, "intercept": p0,
         "points": [
             {"ts": ts0, "price": p0},
             {"ts": ts1, "price": p1}]}]}]


def _viva_pts(ts0="2026-09-12 00:00", ts1="2026-09-16 00:00", p0=98.0, p1=101.0):
    """viva_*_points dialect: ``timestamp`` keys."""
    return [{"timestamp": ts0, "price": p0}, {"timestamp": ts1, "price": p1}]


# ── 1) pivot snap: mid-air endpoints settle on wick/body, deterministically ──

def test_floating_endpoint_snaps_onto_the_bars_wick_or_body():
    df = _tape(200)
    i = 120
    ts = str(df["timestamp"].iloc[i])
    row = df.iloc[i]
    mid = (float(row["high"]) + float(row["low"])) / 2
    pts = snap_points_to_pivots(df, [{"timestamp": ts, "price": mid}])
    assert pts[0]["price"] in (float(row["high"]), float(row["low"]),
                               float(row["open"]), float(row["close"]))
    assert pts[0]["pivot_snapped"]


def test_snap_is_deterministic_across_windows_and_zooms():
    df = _tape(400)
    ts = str(df["timestamp"].iloc[250])
    raw = [{"timestamp": ts, "price": float(df["close"].iloc[250]) + 0.13}]
    a = snap_points_to_pivots(df.tail(200).reset_index(drop=True), raw)
    b = snap_points_to_pivots(df.tail(320).reset_index(drop=True), raw)
    c = snap_points_to_pivots(df, raw)
    assert a[0]["price"] == b[0]["price"] == c[0]["price"]


# ── 2) the solver: no peak-to-floor drag, tool inside, directional band ──

def test_old_capitulation_wick_does_not_drag_the_window():
    df = _tape(400, spike_at=40)          # ancient spike, recent tight tape
    cand = _cand("LONG")
    plan = solve_zoom(df, cand, patterns=_pats())
    assert plan
    n = int(plan["n"])
    w = df.tail(n)
    assert float(w["low"].min()) > df["low"].iloc[40] * 1.2   # spike excluded
    assert plan["y_lo"] > 0 and plan["y_hi"] > plan["y_lo"]   # log-space sane


def test_tool_fully_inside_and_long_keeps_headroom_on_top():
    df = _tape(400)
    cand = _cand("LONG")
    plan = solve_zoom(df, cand, patterns=_pats())
    assert plan
    lo, hi = plan["y_lo"], plan["y_hi"]
    for v in (97.0, 99.0, 100.0, 104.0, 108.0):               # sl..tp2
        assert lo < v < hi
    w = df.tail(int(plan["n"]))
    assert float(w["low"].min()) >= lo and float(w["high"].max()) <= hi
    top = math.log10(hi) - math.log10(float(w["high"].max()))
    bot = math.log10(float(w["low"].min())) - math.log10(lo)
    assert top > bot                                            # LONG band top


def test_short_keeps_the_clean_band_at_the_bottom():
    df = _tape(400, seed=11)
    cand = _cand("SHORT")
    plan = solve_zoom(df, cand, patterns=_pats())
    assert plan
    w = df.tail(int(plan["n"]))
    top = math.log10(plan["y_hi"]) - math.log10(float(w["high"].max()))
    bot = math.log10(float(w["low"].min())) - math.log10(plan["y_lo"])
    assert bot > top                                            # SHORT band bottom


def test_no_hard_cap_deep_pattern_wins_a_deep_window():
    df = _tape(400, seed=3)
    ts0 = str(df["timestamp"].iloc[110])
    ts1 = str(df["timestamp"].iloc[330])
    pats = _pats(ts0, ts1, float(df["low"].iloc[110]), float(df["high"].iloc[330]))
    cand = _cand("LONG")
    plan = solve_zoom(df, cand, patterns=pats)
    assert plan and int(plan["n"]) >= 240        # 90/140 would cut the shape
    assert int(plan["n"]) <= MAX_N


def test_short_tape_falls_back_to_none():
    df = _tape(40)
    assert solve_zoom(df, _cand(), patterns=_pats()) is None


# ── 3) production fallback law: solver down → the old renderer still draws ──

def test_generate_chart_survives_a_boom_in_the_solver(monkeypatch):
    import analysis.smart_zoom as sz
    import bot.messages_v7 as M

    def boom(*a, **k):
        raise RuntimeError("solver offline")

    monkeypatch.setattr(sz, "solve_zoom", boom)
    df = _tape(250)
    # no hand-made patterns: the production safety-net enrich builds the real
    # render commands, exactly like an old alert reaching the chart
    png = M.generate_chart(df, _cand("LONG"), confirmed=True)
    assert png and len(png) > 5000


# ── 4) design invariants: his background / colours / frame / logos untouched ──

def test_design_tokens_are_untouched_by_the_zoom_round():
    src = open(os.path.join(_ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'figsize=(15, 8.5)' in src                      # frame size
    assert 'inset_axes([0.395, 0.315, 0.21, 0.37]' in src  # center logo watermark
    assert "alpha=0.050" in src                            # watermark subtlety
    assert 'os.getenv("CHART_BRAND_NAME", "VIVA SIGNALS PRO")' in src
    assert "assets\", \"vivasignals-logo.png" in src.replace("'", '"') or \
           'vivasignals-logo.png' in src
    import bot.messages_v7 as M
    assert os.path.isfile(M.CHART_LOGO_PATH)               # his logo file exists
    assert M.CHART_BRAND_NAME == "VIVA SIGNALS PRO"
    # the zoom module must carry NO design tokens at all
    szsrc = open(os.path.join(_ROOT, "analysis", "smart_zoom.py"), encoding="utf-8").read()
    for token in ("color", "figsize", "watermark", "theme", "logo"):
        assert token not in szsrc.lower(), token
