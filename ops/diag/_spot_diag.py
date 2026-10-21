"""R99q18 SPOT CHART DIAGNOSTIC — reproduce exactly what production renders.

usage: python3 /home/user/_spot_diag.py STXUSDT:12h [VVVUSDT:8h ...]

For each symbol/TF it prints:
  • what the LADDER engine detects (the message's pattern name + edge + dist)
  • what the CHART engine (engine_spot.analyze) detects (the chart title slug)
  • the drawn geometry (line endpoints in bar/price space)
  • the zoom window and the CANDLE-BLOCK envelope fraction of the panel
"""
import sys, os
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.axes as _Ax

PAINT = []
_orig_plot = _Ax.Axes.plot


def _tracer(self, *a, **kw):
    try:
        if a and hasattr(a[0], "__len__") and len(a) >= 2:
            xs = list(a[0]); ys = list(a[1])
            PAINT.append({"x0": float(xs[0]), "x1": float(xs[-1]),
                          "y0": float(ys[0]), "y1": float(ys[-1]),
                          "c": str(kw.get("color")), "lw": kw.get("linewidth"),
                          "ls": str(kw.get("linestyle"))[:14]})
    except Exception:
        pass
    return _orig_plot(self, *a, **kw)


_Ax.Axes.plot = _tracer

from data.fetcher import get_market_bundle
from analysis.spot_engine import (SPOT_TRIGGERS, scan_spot_alerts,
                                  build_spot_alert_candidate, _spot_count)
from analysis import engine_spot as ES
from analysis import viva_geometry as vg
import bot.messages_v7 as B7
from analysis.candle_counts import fetch_limits

targets = [t for t in sys.argv[1:]] or ["STXUSDT:12h"]
for t in targets:
    sym, _, tf = t.partition(":")
    print("=" * 100)
    print(f"### {sym} {tf}")
    try:
        bundle = get_market_bundle(sym, tuple(SPOT_TRIGGERS), limits=fetch_limits())
    except Exception as e:
        print("  bundle error:", e); continue
    frame = bundle.get(tf)
    if frame is None or not len(frame):
        print("  no frame"); continue
    print(f"  frame bars={len(frame)}  scan window={_spot_count(tf)}  "
          f"last={frame['timestamp'].iloc[-1]} close={float(frame['close'].iloc[-1]):.6g}")

    # ── 1) what the LADDER/message sees
    try:
        items = scan_spot_alerts(sym, bundle)
    except Exception as e:
        items = []
        print("  ladder error:", e)
    for it in items:
        if str(it.get("tf")) != tf:
            continue
        print(f"  LADDER: stage={it.get('stage')} pattern={it.get('pattern')} "
              f"edge={it.get('edge')} close={it.get('close')} "
              f"dist={((float(it.get('close') or 0) - float(it.get('edge') or 0)) / max(1e-12, float(it.get('close') or 1)) * 100):.2f}%")
    if not any(str(i.get("tf")) == tf for i in items):
        print("  LADDER: (no item for this TF now)")

    # ── 2) what the CHART engine sees
    d = frame.reset_index(drop=True)
    try:
        a = ES.analyze(d, tf)
    except Exception as e:
        a = None
        print("  chart analyze error:", e)
    if not a:
        print("  CHART ENGINE: analyze() -> None  ⇒ render returns b'' (text-only)")
    else:
        print(f"  CHART ENGINE: slug={a.get('name_slug')} name={a.get('slug')} "
              f"stage={a.get('stage')} view={a.get('view')}")
        up, lo = a.get("upper"), a.get("lower")
        for nm, ln in (("upper", up), ("lower", lo)):
            if ln is None:
                continue
            try:
                xs = getattr(ln, "xs", None); ys = getattr(ln, "ys", None)
                if xs is None:
                    print(f"     {nm}: {type(ln).__name__} keys={list(getattr(ln,'__dict__',{}))[:8]}")
                else:
                    print(f"     {nm}: n={len(xs)} x[{min(xs):.0f}..{max(xs):.0f}] "
                          f"y[{min(ys):.2f}..{max(ys):.2f}]")
            except Exception as e:
                print(f"     {nm}: <{e}>")

    # ── 3) render exactly like production and measure the envelope
    item = next((i for i in items if str(i.get("tf")) == tf), None)
    cand = None
    if item is not None:
        try:
            cand = build_spot_alert_candidate(item)
        except Exception as e:
            print("  build_spot_alert_candidate error:", e)
    if cand is None:
        print("  (no candidate → cannot reproduce the sent chart right now)")
        continue
    PAINT.clear()
    try:
        png = B7.generate_chart(frame, cand, confirmed=False)
    except Exception as e:
        print("  render error:", e); continue
    print(f"  chart bytes={len(png or b'')}  painted lines:")
    for p in PAINT:
        if abs(p["x1"] - p["x0"]) < 2:
            continue
        print(f"     c={p['c']:9s} lw={p['lw']} ls={p['ls']:14s} "
              f"x[{p['x0']:.0f}..{p['x1']:.0f}] y[{p['y0']:.6g}..{p['y1']:.6g}]")
    # envelope from the figure itself
    try:
        fig = plt.gcf()
        axs = [x for x in fig.axes if x.get_position().height >= 0.30]
        ax = max(axs, key=lambda x: x.get_position().height) if axs else None
        if ax is not None:
            ylo, yhi = ax.get_ylim()
            data = d.tail(300)
            blo, bhi = float(data["low"].min()), float(data["high"].max())
            frac = (np.log(bhi) - np.log(blo)) / (np.log(yhi) - np.log(ylo))
            print(f"  y-window=({float(ylo):.6g}..{float(yhi):.6g})  "
                  f"candle-block={frac*100:.1f}% of panel  xlim={ax.get_xlim()}")
    except Exception as e:
        print("  envelope measure failed:", e)
    try:
        open(f"/home/user/diag_spot_{sym}_{tf}.png", "wb").write(png)
        print(f"  → /home/user/diag_spot_{sym}_{tf}.png")
    except Exception:
        pass
