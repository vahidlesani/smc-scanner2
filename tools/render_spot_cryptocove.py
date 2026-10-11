"""رندر اسپات به سبک دقیق رفرنس‌های CryptoCove — بدون واترمارک CryptoCove.

گرادیان لیمو→آسمان، کندل سبز/قرمز، خطوط مشکیِ لاگ-دقیق، باکس هدف سبز/قرمز با
پیکان و برچسب «delta (pct%) target»، محور قیمت راست، حاشیه‌های بیرونی طبق قانون
(چپ ≤۸٪، راست ≤۱۰٪، بالا ۵–۷٪، پایین ≈۲٫۵سانتی‌متر) و برند خود ویوا.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

from analysis import viva_geometry as vg

GREEN, RED = "#1f9d55", "#d23f5c"


def _ts_axis(ax, df, view, tf):
    mins = vg.TF_MINUTES.get(tf, 240)
    n = len(df)
    base = None
    if "timestamp" in df.columns:
        base = pd.to_datetime(df["timestamp"])
    elif df.index.name == "timestamp" or isinstance(df.index, pd.DatetimeIndex):
        base = pd.to_datetime(df.index)

    def fmt(x, _pos):
        i = int(round(x))
        if base is not None and 0 <= i < n:
            t = base[i]
        elif base is not None:
            t = base[n - 1] + pd.Timedelta(minutes=mins * (i - n + 1))
        else:
            return str(i)
        if mins >= 1440:
            return t.strftime("%b") if t.day <= 7 else t.strftime("%d")
        if mins >= 60:
            return t.strftime("%m-%d %H:%M") if i % 6 == 0 else t.strftime("%m-%d")
        return t.strftime("%m-%d %H:%M")
    ax.xaxis.set_major_formatter(FuncFormatter(fmt))


def render(df: pd.DataFrame, a: dict, path: str, symbol: str = "") -> str:
    v = a["view"]
    n = len(df)
    x_from, x_to = v["x_from"], min(v["x_to"], n - 1 + v["pad_right"])
    fig, ax = plt.subplots(figsize=(16, 9), dpi=110)
    # حاشیه‌های بیرونی طبق قانون: چپ ≤۸٪ راست ≤۱۰٪ بالا ۵–۷٪ پایین ≈۲٫۵cm
    fig.subplots_adjust(left=0.02, right=0.925, top=0.94, bottom=0.10)

    top_rgb = np.array([253, 244, 159]) / 255.0   # لیمو
    bot_rgb = np.array([145, 203, 248]) / 255.0   # آسمان
    grad = np.linspace(top_rgb, bot_rgb, 256).reshape(256, 1, 3)
    ax.imshow(grad, extent=[0, 1, 0, 1], transform=ax.transAxes, aspect="auto",
              origin="upper", zorder=0)
    ax.set_yscale("log")
    ax.set_xlim(x_from - 1, x_to + 1)
    ax.set_ylim(v["y_min"], v["y_max"])

    o = df["open"].astype(float).to_numpy()
    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()
    for i in range(max(0, x_from), n):
        col = GREEN if c[i] >= o[i] else RED
        ax.vlines(i, l[i], h[i], color=col, lw=0.9, zorder=3)
        ax.add_patch(Rectangle((i - 0.33, min(o[i], c[i])), 0.66,
                               abs(c[i] - o[i]) + 1e-12, color=col, zorder=4))

    # خطوط الگو: لاگ-دقیق (در محور log دو نقطه کافی و دقیق است)
    x_end_solid = n - 1 + int(v["pad_right"] * 0.35)
    for ln in (a["upper"], a["lower"]):
        xs = np.array([max(a["x0"], x_from), x_end_solid])
        ax.plot(xs, [ln.price_at(x) for x in xs], color="#101010", lw=1.5, zorder=5)
    if a.get("neckline") is not None and a["kind"] == "pivot_pattern":
        nk = a["neckline"]
        xs = np.array([nk.first_index, x_end_solid])
        ax.plot(xs, [nk.price_at(x) for x in xs], color="#101010", lw=1.1,
                ls="--", zorder=5)

    # باکس هدف از سطحِ کندلِ شکست
    brk = a["breakout"]
    if a["target"] and brk["status"] in ("BREAK_UP_CLOSED", "RETEST_UP",
                                   "BREAK_DOWN_CLOSED", "RETEST_DOWN"):
        level, target = a["level"], a["target"]
        up_dir = target > level
        bx0 = n - 1 + int(v["pad_right"] * 0.18)
        bw = max(6, int(v["pad_right"] * 0.55))
        lo_, hi_ = sorted([level, target])
        ax.add_patch(Rectangle((bx0, lo_), bw, hi_ - lo_,
                               color="#7fbf7a" if up_dir else "#e58f82",
                               alpha=0.62, zorder=2))
        ax.plot([bx0, bx0 + bw], [hi_, hi_], color="#333", lw=0.8, zorder=3)
        ax.plot([bx0, bx0 + bw], [lo_, lo_], color="#333", lw=0.8, zorder=3)
        ax.annotate("", xy=(bx0 + bw / 2, target), xytext=(bx0 + bw / 2, level),
                    arrowprops=dict(arrowstyle="-|>", color="#222", lw=1.1), zorder=6)
        delta = abs(target - level)
        pct = (target / level - 1) * 100
        lab = f"{delta:,.2f} ({pct:.2f}%) {target:,.3f}"
        ax.text(bx0 + bw / 2, hi_ * 1.015 if up_dir else lo_ * 0.985, lab,
                ha="center", va="bottom" if up_dir else "top", fontsize=8.5, zorder=7)

    # واترمارک نماد/تایم‌فریم — بدون هیچ برند بیرونی
    ax.text(0.5, 0.52, f"{symbol} , {a['tf']}" if symbol else a["tf"],
            transform=ax.transAxes, ha="center", va="center", fontsize=30,
            color="#5a5a5a", alpha=0.35, zorder=1)
    ax.text(0.86, 0.06, "VIVA SIGNALS PRO", transform=ax.transAxes, ha="right",
            fontsize=13, style="italic", weight="bold", color="#111", zorder=7)

    ax.yaxis.tick_right()
    def _pf(y, _):
        return f"{y:,.0f}" if y >= 1000 else f"{y:,.4f}"
    ax.yaxis.set_major_formatter(FuncFormatter(_pf))
    ax.yaxis.set_minor_formatter(FuncFormatter(_pf))
    _ts_axis(ax, df, v, a["tf"])
    ax.tick_params(labelsize=7.5)
    for s in ("top", "left"):
        ax.spines[s].set_visible(False)
    fig.savefig(path)
    plt.close(fig)
    return path
