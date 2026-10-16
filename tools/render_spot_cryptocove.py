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

# زوم اسپات — قانون ۱۰-۱۵ (verbatim): «تعداد کندل ۵۰ تا است .. کمه ... باید
# از ۱۲۵ باشه به بالا بر اساس پترن .. زیر ۱۰۰ خیلی». پس قاب اسپات:
#   کفِ سخت = ۱۲۵ کندل (env: VIVA_SPOT_CANDLE_MIN)، پهن‌تر اگر خودِ پترن
#   بخواهد (اسپن پترن + پدها)، و سقفِ نرم per تایم‌فریم.
# چپ = پیوت اول الگو منهای این تعداد کندل کانتکست؛ راست = کندلِ آینده.
PAD_LEFT_BARS = 8
PAD_RIGHT_BARS = 14
MAX_BARS = 240                      # سقفِ کلی (بالاترین سقف per-TF)
SPOT_WINDOW_CAP = {"1m": 200, "3m": 200, "5m": 200, "15m": 220, "30m": 220,
                   "1h": 230, "2h": 230, "4h": 220, "6h": 230, "8h": 260,
                   "12h": 260, "1d": 260, "3d": 300, "1w": 300}



# ── R99q14 SPOT ENVELOPE LAW (his 10-16, verbatim: «ارتفاع کندل‌های اسپات هم
# درست کردی؟؟ … بیشتر از ۷۰ تا ۷۵ درصد نشه از کل ارتفاع چارت»): the visible
# candle block owns at most ~72% of the price panel — the old pads
# (−0.17 / +0.06 of the log span) left the block at 81% of the window.
# Pads now total 0.39·span → 1/1.39 = 71.9%; the target box may open it further.
SPOT_PAD_BELOW_FRAC = 0.60
SPOT_ENVELOPE_TARGET = 0.72


def spot_y_window(d_lo: float, d_hi: float, d_span: float = None) -> tuple:
    """(y_lo, y_hi) with the candle block ≤72% of the panel. Log-space span."""
    try:
        _lo, _hi = float(d_lo), float(d_hi)
        _sp = float(d_span) if d_span is not None else (
            math.log(max(_hi, 1e-12)) - math.log(max(_lo, 1e-12)))
        # the total pad is what the law needs; it is split bottom-heavy
        # (his reference frames keep more air under the tape than above it)
        _pad_total = max(0.0, (1.0 / SPOT_ENVELOPE_TARGET) - 1.0)
        return (_lo * math.exp(-_pad_total * SPOT_PAD_BELOW_FRAC * _sp),
                _hi * math.exp(_pad_total * (1.0 - SPOT_PAD_BELOW_FRAC) * _sp))
    except Exception:
        return float(d_lo), float(d_hi)


def spot_window_count(tf, x0p: int, n: int) -> int:
    """چند کندل در قاب اسپات؟ کف ۱۲۵، بر اساس اسپن پترن، سقف per تایم‌فریم."""
    import os as _os
    try:
        _floor = int(str(_os.getenv("VIVA_SPOT_CANDLE_MIN", "") or "").strip() or 125)
    except Exception:
        _floor = 125
    _floor = max(100, _floor)          # زیر ۱۰۰ «خیلی» غلط است — قفل سخت
    try:
        _span = max(0, int(n) - 1 - int(x0p or 0))
        _want = _span + PAD_LEFT_BARS + PAD_RIGHT_BARS
        _cap = SPOT_WINDOW_CAP.get(str(tf or "").lower(), 240)
        return int(max(_floor, min(_want, _cap)))
    except Exception:
        return 125

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

    # ── 1) قاب: کف ۱۲۵ کندل (قانون ۱۰-۱۵)، پهن‌تر اگر پترن بخواهد
    x0p = int(a.get("x0") or 0)
    x_to = n - 1 + PAD_RIGHT_BARS
    _want_count = spot_window_count(tf, x0p, n)
    _pat_from = max(0, x0p - PAD_LEFT_BARS)
    x_from = min(_pat_from, max(0, x_to - _want_count))
    if x_to - x_from > MAX_BARS:            # سقفِ کلی (when the pattern is huge)
        x_from = max(0, x_to - MAX_BARS)
    if x_to - x_from < min(125, n):         # قفل سخت: هرگز زیر کفِ قانون
        x_from = max(0, x_to - min(125, n))
    n_show = slice(x_from, n)
    d_lo, d_hi = float(np.min(l[n_show])), float(np.max(h[n_show]))
    d_span = math.log(max(d_hi, 1e-12)) - math.log(max(d_lo, 1e-12))
    y_lo, y_hi = spot_y_window(d_lo, d_hi, d_span)

    brk = a.get("breakout") or {}
    target, level = a.get("target"), a.get("level")
    up_dir = bool(target and level and float(target) > float(level))
    # قانون به‌روز ۱۰-۱۵ خودش: «برای شکست‌ها در اسپات هم باکس قرمز بذار» —
    # دیگر فقط شکست صعودی باکس ندارد؛ شکست نزولی هم باکس قرمز رو به پایین
    # می‌گیرد (لانگ‌نشدن اسپات یعنی خروج/حفاظت، نه بی‌باکسی).
    box_drawn = bool(target and level
                     and brk.get("status") not in (None, "INSIDE"))
    # باکس هدف «نازک و دراز» عین رفرنس‌ها: اگر طولش تا ۱٫۵ برابر دامنهٔ
    # کندل‌ها باشد، قاب کمی باز می‌شود تا باکس کامل (دراز) دیده شود؛ بیشتر از
    # آن = قانون GEO (کندل‌ها له نمی‌شوند) و باکس از لبه بیرون می‌زند.
    if box_drawn:
        _t_span = abs(math.log(max(float(target), 1e-12))
                      - math.log(max(float(level), 1e-12)))
        if _t_span <= 1.5 * d_span:
            y_hi = max(y_hi, float(target) * math.exp(0.035 * d_span))
    # ── R99q18 ENVELOPE GUARD (Viva 10-16 verbatim: «ارتفاع ۷۲ درصد رعایت نشده
    # … زوم خرابه» on spot TFs). A far target box used to stretch the price
    # window until the candles shrank to 34–57 % of the panel — the GEO law
    # («باکسِ دور کندل‌ها را له نمی‌کند») broken by the box the alert itself
    # asked for. The candle block now always owns ≥60 % of the panel; a taller
    # box is simply cut by the frame edge (its target line/label sit above the
    # picture), which is honest: the target is beyond the visible range.
    try:
        _block18 = (math.log(d_hi) - math.log(d_lo)) / (math.log(y_hi) - math.log(y_lo))
        if _block18 < 0.60:
            _y_hi_max = math.exp(math.log(y_lo)
                                 + (math.log(d_hi) - math.log(d_lo)) / 0.60)
            y_hi = min(y_hi, _y_hi_max)
        if os.getenv("VIVA_Q18_DEBUG"):
            _blk_after = (math.log(d_hi) - math.log(d_lo)) / (math.log(y_hi) - math.log(y_lo))
            print(f"[q18] blk={_blk_after*100:.1f}% before={_block18*100:.1f}% "
                  f"y=[{y_lo:.6g}..{y_hi:.6g}] d=[{d_lo:.6g}..{d_hi:.6g}] "
                  f"box={'YES' if box_drawn else 'NO'}")
    except Exception:
        pass

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

    # ── R99q21 CENTRE-WATERMARK LAW (his 10-16 evening: «ویوا سیگنالز پرو رو از
    # وسطش بردار» + «وحید لسانی با همون اندازهٔ ستاپ‌ها، توی اسپات یه خرده
    # پررنگ‌تر»): «VIVA SIGNALS PRO» is GONE from the centre — the AUTHOR's name
    # stands there instead, at the SETUPS chart's own size (38, bold), spot a
    # touch bolder (α .26 vs .20) because spot photos get re-compressed harder.
    ax.text(0.5, 0.245, "VAHID LESANI", transform=ax.transAxes,
            ha="center", va="center", fontsize=38, fontweight="bold",
            color="#B9B3A5", alpha=0.32, zorder=1)
    logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "assets", "vivasignals-logo.png")
    if os.path.isfile(logo_path):
        try:
            _w_ax = ax.inset_axes([0.40, 0.30, 0.20, 0.38], zorder=1)
            _w_ax.imshow(mpimg.imread(logo_path), alpha=0.20)
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

    # ── 6) باکس هدف — نازک و دراز، چسبیده به آخرین کندل.
    #     لانگ = سبز با پیکان بالا؛ شکست نزولی = قرمز با پیکان پایین (قانون
    #     به‌روز ۱۰-۱۵: «برای شکست‌ها در اسپات هم باکس قرمز بذار»).
    if box_drawn:
        bx0 = n + 1
        bx1 = n + 7
        # ── R99q14 BOX CALIBRATION (Viva 10-15, verbatim: «باکس باید در انتهای
        # پترن یا ترندلاین روی بالای ترند بالایی … برای لانگ و زیر ترند پایین
        # پترن یا زیر ترندلاین برای شورت بصورت کالیبره روی و زیر اضلاع پترن‌ها و
        # ترندلاین‌ها قرار بگیره»): the pattern-side edge of the box IS the
        # shape's own line evaluated at the box's own x. A sloped trendline is
        # not a flat number — the box rides the line (exactly ON it for a long,
        # exactly UNDER it for a short) at the END of the pattern, and the
        # target edge sits on the measured-move side. No floating, no gap.
        _edge_ln = a.get("upper") if up_dir else a.get("lower")
        _lvl14 = float(level)
        try:
            if _edge_ln is not None and hasattr(_edge_ln, "price_at"):
                _lvl14 = float(_edge_ln.price_at(bx0))
        except Exception:
            _lvl14 = float(level)
        _tgt14 = float(target)
        _min_h14 = abs(_lvl14) * max(d_span * 0.35, 0.012)
        if up_dir:
            lo_ = _lvl14
            hi_ = max(_tgt14, _lvl14 + _min_h14)          # box sits ON/above the edge
        else:
            hi_ = _lvl14
            lo_ = min(_tgt14, _lvl14 - _min_h14)          # box hangs UNDER the edge
        _fce, _ece, _tcol = (("#A8D49B", "#388E3C", "#1B5E20") if up_dir
                             else ("#F2B8B0", "#C0392B", "#8E2418"))
        ax.add_patch(Rectangle((bx0, lo_), bx1 - bx0, max(hi_ - lo_, 1e-12),
                               facecolor=_fce, edgecolor=_ece,
                               linewidth=1.4, alpha=0.65, zorder=5))
        ax.plot([bx0, bx1], [_lvl14] * 2, color=INK, lw=1.2, zorder=6)
        ax.plot([bx0, bx1], [_tgt14] * 2, color=_ece, lw=1.2, zorder=6)
        ax.annotate("", xy=((bx0 + bx1) / 2, _tgt14),
                    xytext=((bx0 + bx1) / 2, _lvl14),
                    arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.4,
                                    mutation_scale=14), zorder=7)
        delta = abs(_tgt14 - _lvl14)
        pct = (_tgt14 / _lvl14 - 1.0) * 100.0 if _lvl14 else 0.0
        _ytx = _tgt14 * math.exp(0.05 * d_span) if up_dir else \
            _tgt14 * math.exp(-0.05 * d_span)
        try:   # R99q18: keep the label inside the frame (a clipped box)
            _ylim_now = ax.get_ylim()
            if _ytx >= _ylim_now[1]:
                _ytx = _ylim_now[1] * math.exp(-0.03 * d_span)
            elif _ytx <= _ylim_now[0]:
                _ytx = _ylim_now[0] * math.exp(0.03 * d_span)
        except Exception:
            pass
        ax.text((bx0 + bx1) / 2, _ytx, f"{delta:.4g} ({pct:+.2f}%)",
                ha="center", va="bottom" if up_dir else "top",
                fontsize=9.5, fontweight="bold", color=_tcol, zorder=8)

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
    # R99q21 (his 10-16, verbatim: «اونی که بالا گذاشتی هم بردار قشنگ نشد ..
    # عکس خوب نشد شلوغ شد در اسپات و ستاپ‌ها»): the TOP-RIGHT CREDIT is GONE.
    # One clean signature only — the author's name over the faint logo in the
    # middle of the chart. Nothing else is stamped on the canvas.

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
        _png = buf.getvalue()
        # R99q20 RAILWAY LEVER: the 8-bit palette encode (same pixels, ~70 %
        # fewer bytes — ZEC 3d 197 KB → 52 KB) rides the futures encoder.
        try:
            from bot.messages_v7 import _encode_png as _enc20
            _png = _enc20(_png)
        except Exception:
            pass
        return _png
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path
