"""R99q33e — ZEC 4H WATCH card: his handwritten «جای … / اطلاعات … / ورود … /
و خروج ..» in the bottom-right corner. Every SETUP chart carries the
entry/stop/TP/LIVE ledger — not only the confirmed ones. The ladder used to be
born inside the confirmed tool block, so a WATCH card raised
UnboundLocalError and printed no ledger at all."""
import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd
from matplotlib.figure import Figure


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


def test_every_setup_chart_carries_the_ledger():
    fig = _render(confirmed=False)
    joined = "\n".join(t.get_text() for t in fig.texts)
    assert "ENTRY" in joined and "INITIAL STOP" in joined
    assert "LIVE" in joined and "TP1" in joined


def test_the_ladder_is_born_before_both_paths():
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    i_lad = src.index('ladder = (candidate.metadata or {}).get("target_ladder") or {}')
    i_cfm = src.index("if _cfm73 and not _is_spot:")
    assert i_lad < i_cfm                       # hoisted above the tool block
    assert "if not _is_spot:\n            try:\n                _pl32" in src
