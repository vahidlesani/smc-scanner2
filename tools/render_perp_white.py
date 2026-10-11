"""رندر پرپچوآل با ظاهر چارت‌های سفید فعلی ویوا — هندسه از هستهٔ جدید.

کرمِ روشن، کندل جوهری، ترند بالایی قرمز / پایینی سبز (جامد تا LIVE و بعد خط‌چین)،
برچسب‌های POI/ENTRY و FIRST STOP و TARGET در حاشیهٔ راست (هرگز روی کندل)،
تگ LIVE، پنل حجم، و بج برند — قالب پیام/برند دست نمی‌خورد.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from analysis import viva_geometry as vg
from tools.render_spot_cryptocove import _ts_axis

BG = "#F6F1E7"
INK = "#26221C"
RED, GREEN = "#C43B4B", "#177E6C"


def render(df: pd.DataFrame, a: dict, path: str, symbol: str = "") -> str:
    v = a["view"]
    n = len(df)
    x_from, x_to = v["x_from"], min(v["x_to"], n - 1 + v["pad_right"])
    fig, (ax, av) = plt.subplots(2, 1, figsize=(16, 9), dpi=110,
                                 gridspec_kw={"height_ratios": [4, 1], "hspace": 0.06})
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=0.02, right=0.90, top=0.93, bottom=0.10)
    for axx in (ax, av):
        axx.set_facecolor(BG)

    ax.set_yscale("log")
    ax.set_xlim(x_from - 1, x_to + 1)
    ax.set_ylim(v["y_min"], v["y_max"])
    o = df["open"].astype(float).to_numpy()
    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()
    for i in range(max(0, x_from), n):
        up = c[i] >= o[i]
        ax.vlines(i, l[i], h[i], color="#6b655c", lw=0.7, zorder=3)
        ax.add_patch(plt.Rectangle((i - 0.32, min(o[i], c[i])), 0.64,
                     abs(c[i] - o[i]) + 1e-12,
                     facecolor=BG if up else INK, edgecolor=INK, lw=0.8, zorder=4))

    # ترندها: جامد تا LIVE، خط‌چین تا لبهٔ بوم (قانون r59.2)
    for ln, col in ((a["upper"], RED), (a["lower"], GREEN)):
        xs1 = np.array([max(a["x0"], x_from), n - 1])
        ax.plot(xs1, [ln.price_at(x) for x in xs1], color=col, lw=1.8, zorder=5)
        xs2 = np.array([n - 1, x_to])
        ax.plot(xs2, [ln.price_at(x) for x in xs2], color=col, lw=1.4, ls="--",
                zorder=5)
    if a.get("neckline") is not None and a["kind"] == "pivot_pattern":
        nk = a["neckline"]
        xs = np.array([nk.first_index, min(n - 1, x_to)])
        ax.plot(xs, [nk.price_at(x) for x in xs], color="#8a8378", lw=1.0,
                ls=":", zorder=5)

    # سطوح ورود/استاپ/هدف — فقط حاشیهٔ راست
    side = a.get("side")
    if a["breakout"]["status"] not in ("BREAK_UP_CLOSED","RETEST_UP","BREAK_DOWN_CLOSED","RETEST_DOWN"):
        side = None
    if side:
        ecol = GREEN if side == "LONG" else RED
        scol = RED if side == "LONG" else GREEN
        for val, txt, col in ((a["entry"], f"{'DEMAND' if side == 'LONG' else 'SUPPLY'} · POI / ENTRY", ecol),
                              (a["stop"], "FIRST STOP", scol),
                              (a["target"], "TARGET", "#8a8378")):
            if not val:
                continue
            ax.hlines(val, n - 1, x_to, colors=col, linestyles="--", lw=1.0, zorder=5)
            ax.text(x_to + 1, val, f" {txt}", color=col, fontsize=8, weight="bold",
                    va="center", zorder=7)
        ax.text(x_to - (x_to - n + 1) / 2, v["y_max"] * 0.995,
                f"LIVE {c[-1]:,.4g}", ha="center", va="top", fontsize=8.5,
                color="white", weight="bold", zorder=8,
                bbox=dict(boxstyle="round,pad=0.25", fc="#20242B", ec="none"))

    # حجم
    if "volume" in df.columns:
        vol = df["volume"].astype(float).to_numpy()
        av.bar(np.arange(n), vol[max(0, x_from - n):] if False else vol, width=0.7,
               color="#C8A886", alpha=0.8)
        av.set_xlim(x_from - 1, x_to + 1)
    av.set_yticks([])
    _ts_axis(ax, df, v, a["tf"])
    ax.set_xticklabels([])
    _ts_axis(av, df, v, a["tf"])
    ax.yaxis.tick_right()
    av.yaxis.tick_right()
    def _pf(y, _):
        return f"{y:,.0f}" if y >= 1000 else f"{y:,.4f}"
    ax.yaxis.set_major_formatter(FuncFormatter(_pf))
    ax.yaxis.set_minor_formatter(FuncFormatter(_pf))
    ax.tick_params(labelsize=7.5)
    av.tick_params(labelsize=7.5)

    ax.text(0.01, 1.06, f"{symbol}  •  {a['tf']}  •  {a.get('style', '')}  •  {side or 'WATCH'}",
            transform=ax.transAxes, fontsize=14, weight="bold", color=INK)
    ax.text(0.01, 1.015, f"{a.get('brand', '')} · {a['fa']} · LOG", transform=ax.transAxes,
            fontsize=8.5, color="#8a8378")
    ax.text(0.985, 1.05, a.get("brand", "VIVA"), transform=ax.transAxes, ha="right",
            fontsize=9, weight="bold", color="white",
            bbox=dict(boxstyle="round,pad=0.4", fc="#1B2430", ec="#C9A227"))
    fig.savefig(path)
    plt.close(fig)
    return path
