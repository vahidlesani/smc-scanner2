"""R99q18: measure ZOOM + ENVELOPE of the spot chart exactly as production renders it."""
import sys, os, math
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.axes as _Ax

STATE = {"ylim": None, "xlim": None, "candles": []}
_o_plot, _o_ylim, _o_xlim = _Ax.Axes.plot, _Ax.Axes.set_ylim, _Ax.Axes.set_xlim
_o_vlines = _Ax.Axes.vlines


def _p(self, *a, **kw):
    return _o_plot(self, *a, **kw)


def _y(self, *a, **kw):
    try:
        if a and a[0] is not None and self.get_position().height >= 0.30:
            STATE["ylim"] = (float(a[0]), float(a[1]))
    except Exception:
        pass
    return _o_ylim(self, *a, **kw)


def _x(self, *a, **kw):
    try:
        if a and a[0] is not None and self.get_position().height >= 0.30:
            STATE["xlim"] = (float(a[0]), float(a[1]))
    except Exception:
        pass
    return _o_xlim(self, *a, **kw)


def _v(self, x, ymin, ymax, **kw):
    try:
        yy = np.atleast_1d(ymin)
        STATE["candles"].append((min(yy), max(yy)))
    except Exception:
        pass
    return _o_vlines(self, x, ymin, ymax, **kw)


_Ax.Axes.plot, _Ax.Axes.set_ylim, _Ax.Axes.set_xlim, _Ax.Axes.vlines = _p, _y, _x, _v

from data.fetcher import get_market_bundle
from analysis.spot_engine import (SPOT_TRIGGERS, scan_spot_alerts,
                                  build_spot_alert_candidate)
from analysis.candle_counts import fetch_limits
import bot.messages_v7 as B7

for t in (sys.argv[1:] or ["STXUSDT:12h"]):
    sym, _, tf = t.partition(":")
    b = get_market_bundle(sym, tuple(SPOT_TRIGGERS), limits=fetch_limits())
    frame = b.get(tf)
    items = [i for i in scan_spot_alerts(sym, b) if str(i.get("tf")) == tf]
    if not items:
        print(f"{sym} {tf}: no ladder item now"); continue
    cand = build_spot_alert_candidate(items[0])
    STATE.update({"ylim": None, "xlim": None, "candles": []})
    png = B7.generate_chart(frame, cand, confirmed=False)
    n = len(frame)
    yl = STATE["ylim"]; xl = STATE["xlim"]; cds = STATE["candles"]
    if not yl or not cds:
        print(f"{sym} {tf}: no measurement (png={len(png or b'')})"); continue
    lo = min(c[0] for c in cds); hi = max(c[1] for c in cds)
    frac = (math.log(hi) - math.log(lo)) / (math.log(yl[1]) - math.log(yl[0]))
    print(f"{sym} {tf}: png={len(png or b'')}  candles_drawn={len(cds)}/{n}  "
          f"xlim=({xl[0]:.0f}..{xl[1]:.0f})  candle-block={frac*100:.1f}%  "
          f"ylim=({yl[0]:.6g}..{yl[1]:.6g})")
