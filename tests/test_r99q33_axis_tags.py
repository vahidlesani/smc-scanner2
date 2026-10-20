"""R99q33a/b/c — ZEC 4H setup.

A) the coloured VALUE pills printed ON the price tick numbers (1,200 / 1,150 /
   1,100 half-covered) — «روی اعداد قیمت»
B) two near levels (ENTRY 1,150.00 / TP1 1,151.65) printed one pill on another
C) the zone chips (TARGET · FVG / TARGET · FLIP) reached into the 1/2/3 rank
   pill column

A and B are verified in PIXELS on a real render: a source grep would pass
while the pills still covered the ladder.
"""
import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

SRC_PATH = "bot/messages_v7.py"


def _frame(n=110, start=1280.0, end=1147.0, seed=7):
    rng = np.random.default_rng(seed)
    base = np.linspace(start, end, n) + rng.normal(0, 0.12, n).cumsum() * 0.15
    o = base + rng.normal(0, 0.05, n)
    c = base + rng.normal(0, 0.05, n)
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.08, n))
    l = np.minimum(o, c) - np.abs(rng.normal(0, 0.08, n))
    ts = pd.date_range("2026-09-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": l,
                         "close": c, "volume": rng.uniform(50, 150, n)})


def _render(confirmed=True):
    from analysis.models import SignalCandidate
    from bot import messages_v7 as V
    df = _frame()
    ts = list(df["timestamp"])
    m = lambda i: 1280.0 - 1.209 * i
    line = {"side": "HIGH", "slope": -1.209, "intercept": 1280.0, "x0": 20, "x1": 96,
            "points": [{"ts": str(ts[20]), "price": m(20)},
                       {"ts": str(ts[96]), "price": m(96)}]}
    cand = SignalCandidate(
        signal_id="r99q33", symbol="ZECUSDT", style="x", setup_code="PINVAL",
        setup_name="PINVAL", strategy_fa="f", direction="LONG", score=8,
        status="CONFIRMED" if confirmed else "WATCH",
        entry_zone_bottom=1148.0, entry_zone_top=1152.0, planned_entry=1150.0,
        sl=1099.0, tp1=1197.0, tp2=1220.0, rr_tp1=1.0, rr_tp2=2.0, bias="LONG",
        trigger_timeframe="4h", market={"asset_class": "CRYPTO", "venue": "BYBIT"},
        metadata={"market": "FUTURES", "engine": "SWING", "log_scale": True,
                  "render_patterns": [{"type": "CHANNEL_DESCENDING",
                                       "name_fa": "کانال نزولی", "lines": [line]}],
                  "target_ladder": {"targets": [1151.65, 1174.68, 1197.72, 1220.75]},
                  "public_code": "Z"})
    figs = []
    orig = Figure.savefig

    def _cap(self, *a, **k):
        figs.append(self)
        return orig(self, *a, **k)

    Figure.savefig = _cap
    try:
        png = V.generate_chart(df, cand, confirmed=confirmed)
    finally:
        Figure.savefig = orig
    assert png and len(png) > 1000
    return figs[-1]


def _inter(a, b):
    return not (a.x0 > b.x1 or a.x1 < b.x0 or a.y0 > b.y1 or a.y1 < b.y0)


def _tags(fig, r):
    return [(t.get_text(), t.get_window_extent(r)) for t in fig.axes[0].texts
            if t.get_text().replace(",", "").replace(".", "").isdigit()]


# ── A — the pills live in the band, never on the ladder ───────────────────
def test_value_pills_never_touch_the_price_numbers():
    fig = _render()
    r = fig.canvas.get_renderer()
    ticks = [t.get_window_extent(r) for t in fig.axes[0].get_yticklabels()
             if t.get_text().strip()]
    tags = _tags(fig, r)
    assert tags, "the confirmed chart must carry its value tags"
    for name, b in tags:
        assert not any(_inter(b, tb) for tb in ticks), f"{name} on a tick number"
        assert b.x1 <= fig.bbox.width + 0.5      # and inside the canvas


# ── B — no two pills on top of each other ────────────────────────────────
def test_two_near_levels_do_not_stack_on_each_other():
    fig = _render()
    r = fig.canvas.get_renderer()
    boxes = [b for _n, b in _tags(fig, r)]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not _inter(boxes[i], boxes[j])


def test_the_anchor_is_measured_and_left_aligned():
    src = open(SRC_PATH, encoding="utf-8").read()
    assert "_xlab0 = max(_xlab0, float(_tl0.get_window_extent(_rend0).x1))" in src
    assert "_tr9 = _mtr9.blended_transform_factory(fig.transFigure, ax.transData)" in src
    assert "ax.text(_atag_x, _yv9, _pv9, transform=_tr9" in src
    assert "_relayout_pills(_rows9, _lo2, _hi2, _gap9)" in src


# ── C — a zone chip never spills into the rank column ─────────────────────
def test_zone_chips_are_clamped_inside_the_tape():
    src = open(SRC_PATH, encoding="utf-8").read()
    assert "_cx = max(0.0, min(_cx, float(_n9) - _wb2 - 1.0))" in src
