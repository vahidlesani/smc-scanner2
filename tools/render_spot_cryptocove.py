"""رندر واحد اسپات — دیزاین قفل‌شدهٔ ویوا (رفرنس‌های praised: ENAUSDT-4H + ETHFI-12H).

قانونِ تک‌رندر: اسپات دقیقاً یک مسیر رندر دارد؛ هیچ fallback زنجیره‌ای نداریم.

قوانینِ زوم/هندسه/دیزاین (از رفرنس‌های خودش + یادداشت‌های ۱۰-۱۵):
1. زوم از پیوت اولِ همان الگو (داخل چارت، نه ۲۰۰ کندل قبل): چند کندل کانتکست
   چپ + ادامهٔ تصویرِ خط تا ته قاب؛ تعداد کندل کم = کندل‌های درشت (رفرنس‌ها).
2. خطوط فقط هندسهٔ تأییدشدهٔ انجین: ضلع ورود مشکیِ توپر، ضلع مقابل نازک
   نقطه‌چین؛ دایره‌های توخالی روی همهٔ پیوت‌های همان خط (refs).
3. باکس هدف فقط برای شکست صعودی (اسپات لانگ است)؛ شکست نزولی = بدون باکس
   (دقیقاً رفرنس praised ETHFI: BREAK DOWN بدون هیچ باکسی).
4. هیستوگرام ولوم کم‌رنگ در پایین پنل (یادداشت خودش: «هیستوگرام ولوم کجاست؟»).
5. واترمارک: لوگوی VIVA محو وسط + نام «Vahid Lesani» بالا-راست + متن محو
   SYMBOL,TF (رفرنس ENA).
6. هدر: SYMBOL • TF • SPOTBREAK / VIVA SIGNALS PRO • STAGE • Pattern • Log Scale
   / خط OHLC قرمز + BINANCE SPOT. فوتر: چپ SYMBOL • VIVA • SPOT • BINANCE SPOT.
7. پیل قیمت لایو (صورتی، رفرنس ENA) روی محور راست + خط نقطه‌ای لایو +
   استمپ «LIVE: dd Mon yyyy • HH:MM (Tehran)» (سبک رفرنس‌ها).
8. حاشیه‌ها کم (یادداشت خودش: «حاشیه پشت محور و پایین صفحه رو کم کن»).
9. قانون GEO (۱۰-۱۲ خودش): باکسِ دور کندل‌ها را له نمی‌کند.
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
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

from analysis import viva_geometry as vg

GREEN, RED = "#26A69A", "#EF5350"
INK = "#1F2328"
MUTED = "#6B675F"
LIVE_PINK = "#E0197D"

# زوم: چپ = پیوت اول الگو منهای این تعداد کندل کانتکست؛ راست = این تعداد
# کندلِ تصویرِ آینده (رفرنس‌ها: قابِ جمع و کندلِ درشت، نه شش هفته تاریخ).
PAD_LEFT_BARS = 8
PAD_RIGHT_BARS = 14
MAX_BARS = 120

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


def _ts_axis(ax, df, tf):
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
        return t.strftime("%m-%d")
    ax.xaxis.set_major_formatter(FuncFormatter(fmt))


def _price_fmt(v: float) -> str:
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 10:
        return f"{v:,.2f}"
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
    """رندر واحد اسپات. اگر path خالی باشد بایت PNG برمی‌گرداند."""
    n = len(df)
    tf = str(a.get("tf") or "4h").lower()
    sym = str(symbol or "").upper() or "SPOT"
    title = title or pattern_title(a.get("name_slug") or a.get("slug"))

    o = df["open"].astype(float).to_numpy()
    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()

    # ── 1) قاب: از پیوت اول همین الگو تا کمی بعد از آخرین کندل
    x0p = int(a.get("x0") or 0)
    x_from = max(0, x0p - PAD_LEFT_BARS)
    x_to = n - 1 + PAD_RIGHT_BARS
    if x_to - x_from > MAX_BARS:
        x_from = max(0, x_to - MAX_BARS)
    n_show = slice(x_from, n)
    d_lo, d_hi = float(np.min(l[n_show])), float(np.max(h[n_show]))
    d_span = math.log(max(d_hi, 1e-12)) - math.log(max(d_lo, 1e-12))
    y_lo, y_hi = d_lo * math.exp(-0.17 * d_span), d_hi * math.exp(0.06 * d_span)

    brk = a.get("breakout") or {}
    target, level = a.get("target"), a.get("level")
    up_dir = bool(target and level and float(target) > float(level))
    box_drawn = bool(target and level and brk.get("status") not in (None, "INSIDE")
                     and up_dir)
    # باکس هدف «نازک و دراز» عین رفرنس‌ها: اگر طولش تا ۱٫۵ برابر دامنهٔ
    # کندل‌ها باشد، قاب کمی باز می‌شود تا باکس کامل (دراز) دیده شود؛ بیشتر از
    # آن = قانون GEO (کندل‌ها له نمی‌شوند) و باکس از لبه بیرون می‌زند.
    if box_drawn:
        _t_span = abs(math.log(max(float(target), 1e-12))
                      - math.log(max(float(level), 1e-12)))
        if _t_span <= 1.5 * d_span:
            y_hi = max(y_hi, float(target) * math.exp(0.035 * d_span))

    fig, ax = plt.subplots(figsize=(16, 9), dpi=130)
    fig.patch.set_facecolor("#FFFFFF")
    # حاشیهٔ کم (یادداشت خودش: «حاشیهٔ پشت محور و پایین صفحه رو کم کن»)
    fig.subplots_adjust(left=0.016, right=0.952, top=0.915, bottom=0.066)

    top_rgb = np.array([253, 244, 159]) / 255.0
    bot_rgb = np.array([145, 203, 248]) / 255.0
    grad = np.linspace(top_rgb, bot_rgb, 256).reshape(256, 1, 3)
    ax.imshow(grad, extent=[0, 1, 0, 1], transform=ax.transAxes, aspect="auto",
              origin="upper", zorder=0)
    ax.set_yscale("log")
    ax.set_xlim(x_from - 1, x_to + 1)
    ax.set_ylim(y_lo, y_hi)
    ax.grid(True, which="major", color="#D8D2C2", alpha=0.45, linewidth=0.6,
            linestyle="-", zorder=1)

    # ── 2) واترمارک‌ها: متن محو نماد + لوگوی VIVA (وسط)
    ax.text(0.5, 0.545, f"{sym},{tf}", transform=ax.transAxes, ha="center",
            va="center", fontsize=50, fontweight="bold", color="#BFB9AB",
            alpha=0.52, zorder=1)
    # برند وسط چارت (مثل چارت ستاپ‌ها) — محو، پشت کندل‌ها
    ax.text(0.5, 0.50, "VIVA SIGNALS PRO", transform=ax.transAxes,
            ha="center", va="center", fontsize=30, fontweight="bold",
            color="#B9B3A5", alpha=0.14, zorder=1)
    logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "assets", "vivasignals-logo.png")
    if os.path.isfile(logo_path):
        try:
            _w_ax = ax.inset_axes([0.40, 0.30, 0.20, 0.38], zorder=1)
            _w_ax.imshow(mpimg.imread(logo_path), alpha=0.17)
            _w_ax.set_axis_off()
            _w_ax.patch.set_alpha(0)
        except Exception:
            pass

    # ── 3) هیستوگرام ولوم کم‌رنگ، چسبیده به کف پنل (یادداشت خودش)
    try:
        v = df["volume"].astype(float).to_numpy()
        vmax = float(np.max(v[n_show])) if len(v) else 0.0
        if vmax > 0:
            _base = y_lo * math.exp(0.004 * d_span)
            _hgt = 0.062 * d_span
            for i in range(x_from, n):
                _vh = (_hgt * (float(v[i]) / vmax)) if vmax else 0.0
                if _vh <= 0:
                    continue
                # ارتفاع در فضای قیمت: کمیت لگاریتمی → ضرب در پایه (نه exp
                # روی قیمت؛ آن باگ کل پنل را پر می‌کرد)
                _hbar = _base * (math.exp(_vh) - 1.0)
                ax.add_patch(Rectangle((i - 0.33, _base), 0.66, _hbar,
                                       facecolor=GREEN if c[i] >= o[i] else RED,
                                       edgecolor="none", alpha=0.30, zorder=2))
    except Exception:
        pass

    # ── 4) کندل‌ها
    for i in range(x_from, n):
        col = GREEN if c[i] >= o[i] else RED
        ax.vlines(i, l[i], h[i], color=col, lw=1.0, zorder=3)
        ax.add_patch(Rectangle((i - 0.33, min(o[i], c[i])), 0.66,
                               max(abs(c[i] - o[i]), 1e-12), facecolor=col,
                               edgecolor=col, linewidth=0.6, zorder=4))

    # ── 5) خطوط الگو از هندسهٔ انجین + دایره‌های توخالی روی پیوت‌ها
    entry_edge = str(brk.get("edge") or "")
    if not entry_edge:
        entry_edge = "UPPER" if str(a.get("direction") or "").upper() in ("UP", "LONG") else "LOWER"
    for side, ln in (("upper", a.get("upper")), ("lower", a.get("lower"))):
        if ln is None:
            continue
        is_entry = (side.upper() == entry_edge)
        # رفرنس‌ها: هر دو ضلع از پیوت اول تا آخرین تاچِ خودشان «توپر» هستند
        # (ضلع ورود پررنگ‌تر) و فقط ادامهٔ تصویر به آینده نقطه‌چین می‌شود.
        _last_t = max(list(getattr(ln, "touches", ()) or [n - 1]) or [n - 1])
        _span_end = min(n - 1, max(_last_t, int(getattr(ln, "first_index", x_from))))
        xs = np.array([max(int(getattr(ln, "first_index", x_from)), x_from), _span_end])
        ax.plot(xs, [ln.price_at(x) for x in xs], color=INK,
                lw=2.0 if is_entry else 1.4,
                alpha=1.0 if is_entry else 0.92, zorder=6, solid_capstyle="round")
        if x_to > _span_end:   # ادامهٔ تصویر تا ته قاب (رفرنس‌ها)
            xs_p = np.array([_span_end, x_to - 1])
            ax.plot(xs_p, [ln.price_at(x) for x in xs_p], color=INK,
                    lw=1.2 if is_entry else 1.0, ls=(0, (5, 4)), alpha=0.75,
                    zorder=6)
        _tix = [int(t) for t in (getattr(ln, "touches", ()) or ())
                if x_from <= int(t) <= n - 1]
        if _tix:
            ax.scatter(_tix, [ln.price_at(t) for t in _tix], s=46, zorder=7,
                       facecolors="#FDF49F", edgecolors=INK, linewidths=1.3)
    if a.get("neckline") is not None and a.get("kind") == "pivot_pattern":
        nk = a["neckline"]
        xs = np.array([max(int(getattr(nk, "first_index", x_from)), x_from), n - 1])
        ax.plot(xs, [nk.price_at(x) for x in xs], color=INK, lw=1.6,
                ls=(0, (6, 4)), zorder=6)
        _nix = [int(t) for t in (getattr(nk, "touches", ()) or ())
                if x_from <= int(t) <= n - 1]
        if _nix:
            ax.scatter(_nix, [nk.price_at(t) for t in _nix], s=46, zorder=7,
                       facecolors="#FDF49F", edgecolors=INK, linewidths=1.3)

    # ── 6) باکس هدف — فقط شکست صعودی (رفرنس‌ها: نازک، چسبیده به آخرین کندل)
    if box_drawn:
        bx0 = n + 1
        bx1 = n + 7
        lo_, hi_ = sorted([float(level), float(target)])
        ax.add_patch(Rectangle((bx0, lo_), bx1 - bx0, hi_ - lo_,
                               facecolor="#A8D49B", edgecolor="#388E3C",
                               linewidth=1.4, alpha=0.65, zorder=5))
        ax.plot([bx0, bx1], [float(level)] * 2, color=INK, lw=1.2, zorder=6)
        ax.plot([bx0, bx1], [float(target)] * 2, color="#388E3C", lw=1.2, zorder=6)
        ax.annotate("", xy=((bx0 + bx1) / 2, float(target)),
                    xytext=((bx0 + bx1) / 2, float(level)),
                    arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.4,
                                    mutation_scale=14), zorder=7)
        delta = abs(float(target) - float(level))
        pct = (float(target) / float(level) - 1.0) * 100.0
        ax.text((bx0 + bx1) / 2, float(target) * math.exp(0.05 * d_span),
                f"{delta:.4g} ({pct:+.2f}%)", ha="center", va="bottom",
                fontsize=9.5, fontweight="bold", color="#1B5E20", zorder=8)

    # ── 7) خط لایو + پیل قیمت (صورتی، رفرنس ENA)
    live = float(c[-1])
    ax.axhline(live, color=INK, ls=":", lw=1.0, alpha=0.55, zorder=2)
    ax.text(x_to + 0.4, live, f" {_price_fmt(live)} ", ha="left", va="center",
            fontsize=9.5, fontweight="bold", color="#FFFFFF", zorder=9,
            bbox=dict(boxstyle="square,pad=0.28", facecolor=LIVE_PINK,
                      edgecolor=LIVE_PINK))

    # ── 8) استمپ زندهٔ تهران (سبک رفرنس‌ها: جعبهٔ روشن، پایین-راست داخل پنل)
    try:
        _now = datetime.now(ZoneInfo("Asia/Tehran"))
        ax.text(0.995, 0.012,
                f" LIVE: {_now.strftime('%d %b %Y')} • {_now.strftime('%H:%M')} (Tehran) ",
                transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5,
                color=INK, zorder=12,
                bbox=dict(boxstyle="round,pad=0.28", facecolor="#FFFDF2",
                          edgecolor="#B9B29F", linewidth=0.8))
    except Exception:
        pass

    # ── 9) هدر (شکلِ رفرنس ENA)
    last_o, last_h, last_l, last_c = o[-1], h[-1], l[-1], c[-1]
    prev_c = c[-2] if n > 1 else c[-1]
    chg = last_c - prev_c
    chg_pct = (chg / prev_c * 100.0) if prev_c else 0.0
    stage_lab = str(stage or _STAGE_LABEL.get(str(brk.get("status") or ""), "PUBLISH")).upper()
    fig.text(0.020, 0.968, f"{sym}  •  {tf.upper()}  •  SPOTBREAK",
             fontsize=16, fontweight="bold", color=INK)
    fig.text(0.020, 0.941, f"VIVA SIGNALS PRO  •  {stage_lab}  •  {title}  •  Log Scale",
             fontsize=11, color=MUTED)
    fig.text(0.020, 0.916,
             f"O {_price_fmt(last_o)}   H {_price_fmt(last_h)}   "
             f"L {_price_fmt(last_l)}   C {_price_fmt(last_c)}   "
             f"{chg:+.4f} ({chg_pct:+.2f}%)   •   BINANCE SPOT",
             fontsize=10, fontweight="bold", color="#B3261E")
    fig.text(0.976, 0.968, "by: Vahid Lesani", fontsize=12.5,
             fontweight="bold", color=INK, ha="right")

    # ── 10) فوتر
    fig.text(0.020, 0.024, f"{sym}  •  VIVA  •  SPOT  •  BINANCE SPOT",
             fontsize=11, color=INK)
    fig.text(0.952, 0.024, "VIVA SIGNALS PRO", fontsize=13, fontweight="bold",
             color=INK, ha="right")
    if os.path.isfile(logo_path):
        try:
            b_ax = fig.add_axes([0.956, 0.010, 0.026, 0.046], zorder=10)
            b_ax.imshow(mpimg.imread(logo_path), alpha=0.95)
            b_ax.axis("off")
        except Exception:
            pass

    # ── 11) محورها
    ax.yaxis.tick_right()
    # چگالی لیبل قیمت (قانون ۱۰-۱۵ خودش: «محور قیمت‌ها خالیه باید قیمت‌ها دقیق
    # نوشته بشه»): تیک‌های رُندِ مشترک از هستهٔ هندسه — ۱۰ تا ۱۸ لیبل با دقتی
    # متناسب با گام (BTC صفر اعشار، ENA/DOGE سه اعشار).
    try:
        from matplotlib.ticker import FixedLocator as _FL99
        _tk99, _dp99 = vg.nice_price_ticks(*ax.get_ylim())
        if len(_tk99) >= 6:
            ax.yaxis.set_major_locator(_FL99(_tk99))
            ax.yaxis.set_minor_locator(_FL99([]))
            _f99 = "{:,.%df}" % _dp99
            ax.yaxis.set_major_formatter(
                FuncFormatter(lambda _v, _p=None, _f=_f99: _f.format(_v)))
            ax.yaxis.set_minor_formatter(
                FuncFormatter(lambda _v, _p=None: ""))
        else:
            ax.yaxis.set_major_formatter(FuncFormatter(_fmt_axis))
            ax.yaxis.set_minor_formatter(FuncFormatter(_fmt_axis))
    except Exception:
        ax.yaxis.set_major_formatter(FuncFormatter(_fmt_axis))
        ax.yaxis.set_minor_formatter(FuncFormatter(_fmt_axis))
    _ts_axis(ax, df, tf)
    ax.tick_params(axis="x", labelsize=10.5, colors="#3A362F", pad=4)
    ax.tick_params(axis="y", labelsize=9, colors=MUTED)
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
