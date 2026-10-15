"""رندر واحد اسپات — دیزاین قفل‌شدهٔ ویوا (رفرنس ENAUSDT-4H، ۱۰-۱۵).

قانونِ تک‌رندر (Viva): اسپات دقیقاً یک مسیر رندر دارد؛ هیچ fallback زنجیره‌ای
نداریم. این ماژول همان مسیر است.

دیزاینِ قفل‌شده (از رفرنس ENA + اصلاحاتی که ویوا گفت):
1. گرادیان لیمو→آسمان تمام‌قاب، گِرید محو، واترمارک «SYMBOL, TF» وسط.
2. کندل سبز/قرمز (MINT #26A69A / CORAL #EF5350)، بدون پنل حجم (خود رفرنس‌ها
   پنل حجم ندارند).
3. خطوط الگو فقط از هندسهٔ تأییدشدهٔ انجین (engine_spot → viva_geometry):
   ضلعِ ورود پررنگِ مشکی توپر، ضلع مقابل نازک نقطه‌چین؛ ادامهٔ تصویر به آینده.
4. دایره‌های توخالی روی همهٔ پیوت‌های معتبر همان خط (major pivot circles) —
   همان چیزی که در رفرنس‌ها هست.
5. باکس هدف: لانگ = سبز با پیکان بالا؛ هشدار نزولی = قرمز با پیکان پایین؛
   برچسب «delta (pct%)» بالای باکس.
6. هدر: `SYMBOL • TF • SPOTBREAK` / `VIVA SIGNALS PRO • STAGE • Pattern • Log Scale`
   / خط OHLC قرمز با تگ BINANCE SPOT.
7. پیل قیمت لایو روی محور راست + خط نقطه‌ای لایو + پیل مشکی زمان (تهران).
8. فوتر: چپ `SYMBOL • VIVA • SPOT • BINANCE SPOT`، راست برند + نشان طلایی.
9. زوم از `vg.choose_view` (فاصلهٔ آیندهٔ باکس طبق همان قانون؛ نه ۱۰ روز هوای
   خالی).
"""
from __future__ import annotations

import io
import math
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.patches import Rectangle, Circle
from matplotlib.ticker import FuncFormatter

from analysis import viva_geometry as vg

GREEN, RED = "#26A69A", "#EF5350"
INK = "#1F2328"
MUTED = "#6B675F"
LIVE_PINK = "#E0197D"

# عنوان انگلیسی الگو از اسلاگ انجین (زبان رفرنس‌ها)
EN_TITLE = {
    "CHANNEL_FLAT": "Parallel Channel", "CHANNEL": "Parallel Channel",
    "CHANNEL_ASCENDING": "Ascending Channel",
    "CHANNEL_DESCENDING": "Descending Channel",
    "CHANNEL_ASCENDING_BROAD": "Broadening Ascending Channel",
    "CHANNEL_DESCENDING_BROAD": "Broadening Descending Channel",
    "BROADENING": "Broadening Pattern",
    "BROADENING_WEDGE_ASC": "Broadening Wedge",
    "BROADENING_WEDGE_DESC": "Broadening Wedge",
    "WEDGE_RISING": "Rising Wedge", "WEDGE_FALLING": "Falling Wedge",
    "TRIANGLE_ASCENDING": "Ascending Triangle",
    "TRIANGLE_DESCENDING": "Descending Triangle",
    "TRIANGLE_SYMMETRICAL": "Symmetrical Triangle",
    "TRENDLINE": "Major Trendline",
    "DOUBLE_TOP": "Double Top", "DOUBLE_BOTTOM": "Double Bottom",
    "HEAD_SHOULDERS": "Head & Shoulders",
    "INV_HEAD_SHOULDERS": "Inverse Head & Shoulders",
    "CUP_HANDLE": "Cup & Handle", "INV_CUP_HANDLE": "Inverse Cup & Handle",
}

_STAGE_LABEL = {
    "BREAK_UP_CLOSED": "BREAK UP", "RETEST_UP": "RETEST",
    "BREAK_DOWN_CLOSED": "BREAK DOWN", "RETEST_DOWN": "RETEST",
    "INSIDE": "PUBLISH",
}


def pattern_title(slug: str) -> str:
    s = str(slug or "").upper()
    if s in EN_TITLE:
        return EN_TITLE[s]
    for k in sorted(EN_TITLE, key=len, reverse=True):
        if k in s:
            return EN_TITLE[k]
    return s.replace("_", " ").title() or "Macro Structure"


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
            return t.strftime("%b %d")
        if mins >= 240:
            return t.strftime("%m-%d")
        return t.strftime("%m-%d %H:%M")
    ax.xaxis.set_major_formatter(FuncFormatter(fmt))


def _price_fmt(v: float) -> str:
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 10:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:.4f}"
    return f"{v:.4f}"


def _fmt_axis(v, _p=None) -> str:
    if v >= 1000:
        return f"{v:,.4f}"
    if v >= 100:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:,.3f}"
    return f"{v:.4f}"


def render(df: pd.DataFrame, a: dict, path: str = None, symbol: str = "",
           stage: str = "", title: str = "") -> "str | bytes":
    """رندر واحد اسپات (رفرنس ENA). اگر path خالی باشد بایت PNG برمی‌گرداند."""
    v = a["view"]
    n = len(df)
    x_from = max(0, int(v["x_from"]))
    x_to = min(int(v["x_to"]), n - 1 + int(v["pad_right"]))
    tf = str(a.get("tf") or "4h").lower()
    sym = str(symbol or "").upper() or "SPOT"
    title = title or pattern_title(a.get("slug"))

    fig, ax = plt.subplots(figsize=(16, 9), dpi=130)
    fig.patch.set_facecolor("#FFFFFF")
    fig.subplots_adjust(left=0.018, right=0.925, top=0.895, bottom=0.085)

    # 1) گرادیان لیمو→آسمان روی کل محور
    top_rgb = np.array([253, 244, 159]) / 255.0
    bot_rgb = np.array([145, 203, 248]) / 255.0
    grad = np.linspace(top_rgb, bot_rgb, 256).reshape(256, 1, 3)
    ax.imshow(grad, extent=[0, 1, 0, 1], transform=ax.transAxes, aspect="auto",
              origin="upper", zorder=0)
    ax.set_yscale("log")
    ax.set_xlim(x_from - 1, x_to + 1)
    ax.set_ylim(v["y_min"], v["y_max"])
    ax.grid(True, which="major", color="#D8D2C2", alpha=0.45, linewidth=0.6,
            linestyle="-", zorder=1)
    ax.grid(True, which="minor", color="#D8D2C2", alpha=0.18, linewidth=0.4,
            linestyle="-", zorder=1)

    o = df["open"].astype(float).to_numpy()
    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()

    # 2) واترمارک وسط (پشت کندل‌ها)
    ax.text(0.5, 0.52, f"{sym},{tf}", transform=ax.transAxes, ha="center",
            va="center", fontsize=54, fontweight="bold", color="#C9C4B8",
            alpha=0.55, zorder=1)

    # 3) کندل‌ها
    for i in range(x_from, n):
        col = GREEN if c[i] >= o[i] else RED
        ax.vlines(i, l[i], h[i], color=col, lw=1.0, zorder=3)
        ax.add_patch(Rectangle((i - 0.33, min(o[i], c[i])), 0.66,
                               max(abs(c[i] - o[i]), 1e-12), facecolor=col,
                               edgecolor=col, linewidth=0.6, zorder=4))

    # 4) خطوط الگو از هندسهٔ انجین + دایرهٔ پیوت‌ها روی همان خط
    entry_edge = str(a.get("breakout", {}).get("edge") or "")
    if not entry_edge:
        entry_edge = "UPPER" if str(a.get("direction") or "").upper() in ("UP", "LONG") else "LOWER"
    x_solid_end = n - 1
    x_proj_end = x_to - 1
    for side, ln in (("upper", a.get("upper")), ("lower", a.get("lower"))):
        if ln is None:
            continue
        is_entry = (side.upper() == entry_edge)
        xs = np.array([max(int(getattr(ln, "first_index", x_from)), x_from), x_proj_end])
        ys = [ln.price_at(x) for x in xs]
        ax.plot(xs, ys, color=INK, lw=2.1 if is_entry else 1.2,
                ls="-" if is_entry else (0, (5, 4)),
                alpha=1.0 if is_entry else 0.85, zorder=6,
                solid_capstyle="round")
        # دایره‌های توخالی روی پیوت‌های معتبر (marker نقطه‌ای — نه پچ دیتایی،
        # چون شعاع در محور لگاریتمی به خط عمودی غول تبدیل می‌شد)
        _tix = [int(t) for t in (getattr(ln, "touches", ()) or ())
                if x_from <= int(t) <= n - 1]
        if _tix:
            ax.scatter(_tix, [ln.price_at(t) for t in _tix], s=52, zorder=7,
                       facecolors="#FDF49F", edgecolors=INK, linewidths=1.3)
    if a.get("neckline") is not None and a.get("kind") == "pivot_pattern":
        nk = a["neckline"]
        xs = np.array([max(int(getattr(nk, "first_index", x_from)), x_from), x_proj_end])
        ax.plot(xs, [nk.price_at(x) for x in xs], color=INK, lw=1.6,
                ls=(0, (6, 4)), zorder=6)
        _nix = [int(t) for t in (getattr(nk, "touches", ()) or ())
                if x_from <= int(t) <= n - 1]
        if _nix:
            ax.scatter(_nix, [nk.price_at(t) for t in _nix], s=52, zorder=7,
                       facecolors="#FDF49F", edgecolors=INK, linewidths=1.3)

    # 4b) قانون GEO (۱۰-۱۲ خودش: «کندل‌ها هرگز له نشن»): باکسِ دور قاب را باز
    #     نمی‌کند — دامنهٔ قیمت روی کندل‌ها می‌ماند و باکس از قاب بیرون می‌زند.
    #     (پیش از باکس اجرا می‌شود تا برچسبِ پین‌شده روی قابِ نهایی بنشیند.)
    _vlo, _vhi = float(v["y_min"]), float(v["y_max"])
    _seg = slice(x_from, n)
    _dlo = float(np.min(l[_seg])); _dhi = float(np.max(h[_seg]))
    _dspan = math.log(max(_dhi, 1e-12)) - math.log(max(_dlo, 1e-12))
    _gspan = math.log(max(_vhi, 1e-12)) - math.log(max(_vlo, 1e-12))
    if _dspan > 0 and _gspan > _dspan * 1.45:
        _glo = math.log(max(_dlo, 1e-12)) - 0.05 * _dspan
        _ghi = math.log(max(_dhi, 1e-12)) + 0.06 * _dspan
        ax.set_ylim(math.exp(_glo), math.exp(_ghi))

    # 5) باکس هدف — نسبت‌های رفرنس خودش: باکس باریک (۶ کندل) با فاصلهٔ ۱ کندل از
    #    لایو، پیکان داخلش، برچسب «delta (pct%)» بیرون باکس. باکسِ دور (هدف خیلی
    #    پایین‌تر/بالاتر از دامنهٔ کندل‌ها) قاب را خفه نمی‌کند: از قاب بیرون می‌زند
    #    (کلیپ) و برچسبش لبهٔ پایین قاب سنجاق می‌شود — قانون ۱۰-۱۲ خودش.
    brk = a.get("breakout") or {}
    target, level = a.get("target"), a.get("level")
    x_right = x_to
    if target and level and brk.get("status") not in (None, "INSIDE"):
        up_dir = float(target) > float(level)
        bx0 = n - 1 + 1
        bx1 = bx0 + 6
        x_right = max(x_to, bx1 + 2)
        lo_, hi_ = sorted([float(level), float(target)])
        ax.add_patch(Rectangle((bx0, lo_), bx1 - bx0, hi_ - lo_,
                               facecolor="#A8D49B" if up_dir else "#EBA9A2",
                               edgecolor="#388E3C" if up_dir else "#C0392B",
                               linewidth=1.4, alpha=0.62, zorder=5))
        ax.plot([bx0, bx1], [float(level)] * 2, color=INK, lw=1.2, zorder=6)
        ax.plot([bx0, bx1], [float(target)] * 2,
                color="#388E3C" if up_dir else "#C0392B", lw=1.2, zorder=6)
        ax.annotate("", xy=((bx0 + bx1) / 2, float(target)),
                    xytext=((bx0 + bx1) / 2, float(level)),
                    arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.4,
                                    mutation_scale=14), zorder=7)
        delta = abs(float(target) - float(level))
        pct = (float(target) / float(level) - 1.0) * 100.0
        lab = f"{delta:.4g} ({pct:+.2f}%)"
        _span_log = math.log(max(hi_, 1e-12)) - math.log(max(lo_, 1e-12))
        ylab = hi_ * math.exp(_span_log * 0.06) if up_dir else \
            lo_ * math.exp(-_span_log * 0.06)
        _va = "bottom" if up_dir else "top"
        # باکسِ کلیپ‌شده: برچسب بیرونِ قاب گم نشود — می‌آید داخلِ قاب، کنارِ لبهٔ
        # هدف (پایین برای نزولی، بالا برای صعودی) و رنگش سرِ همان رنگ باکس است.
        _lo9, _hi9 = ax.get_ylim()
        if ylab > _hi9:
            ylab, _va = _hi9 * 0.994, "top"
        elif ylab < _lo9:
            ylab, _va = _lo9 * 1.006, "bottom"
        ax.text((bx0 + bx1) / 2, ylab, lab, ha="center", va=_va,
                fontsize=10, fontweight="bold",
                color="#1B5E20" if up_dir else "#8E2418", zorder=8)


    # 6) خط لایو نقطه‌چین + پیل قیمت لایو روی محور راست
    live = float(c[-1])
    ax.axhline(live, color=INK, ls=":", lw=1.0, alpha=0.55, zorder=2)
    ax.text(x_to + 0.2, live, f" {_price_fmt(live)} ", ha="left", va="center",
            fontsize=9.5, fontweight="bold", color="#FFFFFF", zorder=9,
            bbox=dict(boxstyle="square,pad=0.28", facecolor=LIVE_PINK,
                      edgecolor=LIVE_PINK))

    # 7) پیل زمان تهران (گوشهٔ پایین-راست قاب، همیشه سر جایش — نه روی برچسب باکس)
    stamp = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%m-%d %H:%M")
    ax.text(0.995, 0.012, f" {stamp} ", transform=ax.transAxes, ha="right",
            va="bottom", fontsize=9.5, fontweight="bold", color="#FFFFFF",
            zorder=12, bbox=dict(boxstyle="round,pad=0.32", facecolor=INK,
                                 edgecolor=INK))

    # 8) هدر متنی (شکلِ رفرنس ENA)
    last = dict(o=o[-1], h=h[-1], l=l[-1], c=c[-1])
    prev_c = c[-2] if n > 1 else c[-1]
    chg = last["c"] - prev_c
    chg_pct = (chg / prev_c * 100.0) if prev_c else 0.0
    stage_lab = str(stage or _STAGE_LABEL.get(str(brk.get("status") or ""), "PUBLISH")).upper()
    fig.text(0.022, 0.965, f"{sym}  •  {tf.upper()}  •  SPOTBREAK",
             fontsize=16, fontweight="bold", color=INK)
    fig.text(0.022, 0.938, f"VIVA SIGNALS PRO  •  {stage_lab}  •  {title}  •  Log Scale",
             fontsize=11, color=MUTED)
    fig.text(0.022, 0.912,
             f"O {_price_fmt(last['o'])}   H {_price_fmt(last['h'])}   "
             f"L {_price_fmt(last['l'])}   C {_price_fmt(last['c'])}   "
             f"{chg:+.4f} ({chg_pct:+.2f}%)   •   BINANCE SPOT",
             fontsize=10, fontweight="bold", color="#B3261E")

    # 9) فوتر
    fig.text(0.022, 0.026, f"{sym}  •  VIVA  •  SPOT  •  BINANCE SPOT",
             fontsize=11, color=INK)
    fig.text(0.943, 0.026, "VIVA SIGNALS PRO", fontsize=13, fontweight="bold",
             color=INK, ha="right")
    logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "assets", "vivasignals-logo.png")
    if os.path.isfile(logo_path):
        try:
            b_ax = fig.add_axes([0.947, 0.012, 0.026, 0.046], zorder=10)
            b_ax.imshow(mpimg.imread(logo_path), alpha=0.95)
            b_ax.axis("off")
        except Exception:
            pass

    # 10) محورها — عرض قاب از باکس پیروی می‌کند (نه ۱۰ روز هوای خالی)
    ax.set_xlim(x_from - 1, x_right + 1)
    ax.yaxis.tick_right()
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_axis))
    ax.yaxis.set_minor_formatter(FuncFormatter(_fmt_axis))
    _ts_axis(ax, df, v, tf)
    ax.tick_params(labelsize=9, colors=MUTED)
    # چگالی لیبلِ قیمت مثل رفرنس‌های خودش (۱۳–۱۶ لیبل): قاب‌های زیر ۱٫۵ دهه
    # تیک خطیِ گرد می‌گیرند، قاب‌های بازتر لگِ کامل.
    try:
        from matplotlib.ticker import FixedLocator
        _lo, _hi = ax.get_ylim()
        _dec = math.log10(_hi) - math.log10(_lo)
        if _dec <= 1.5 and _lo > 0:
            import numpy as _np
            _raw = (_hi - _lo) / 14.0
            _mag = 10 ** math.floor(math.log10(_raw))
            _st = min([m * _mag for m in (1, 2, 2.5, 5, 10) if m * _mag >= _raw] or [_raw])
            _t0 = math.ceil(_lo / _st) * _st
            _ticks = []
            _t = _t0
            while _t <= _hi * 1.0001 and len(_ticks) < 40:
                _ticks.append(round(_t, 10))
                _t += _st
            if len(_ticks) >= 6:
                ax.yaxis.set_major_locator(FixedLocator(_ticks))
                ax.yaxis.set_minor_locator(FixedLocator([]))
        else:
            ax.yaxis.set_minor_locator(__import__("matplotlib").ticker.LogLocator(
                subs=(1.0, 2.0, 3.0, 5.0, 7.0), numticks=100))
    except Exception:
        pass
    for s in ("top", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["right"].set_color("#8A857D")
    ax.spines["bottom"].set_color("#8A857D")

    if path is None:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
        return buf.getvalue()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path
