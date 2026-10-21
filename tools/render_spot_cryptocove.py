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
6. هدر: SYMBOL • TF • SPOTBREAK / STAGE • Pattern • Log Scale (R99q23: brand word removed)
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
# ── R99q35 (his 10-20, verbatim: «حاشیه پشت محور قیمت‌ها باید به چارت نمودار
# اضافه بشه … پشت محور قیمت‌ها حدود ۱۵ درصد از چارت کندل‌ها کم کردی و فقط به
# خاطر جدول ورود خروج فضای کندل‌ها رو کوچک کردی … این قسمت سفید پشت قیمت‌ها
# باید به فضای نمودار کندل‌ها اضافه بشه و جدول ورود و خروج و تی پی‌ها پایین
# چارت روی جایی که فلش زدم قرار بگیره»). The panel used to stop at 0.870 of the
# figure and the whole right column (13 %) was DEAD WHITE — candle space thrown
# away for a price ladder and a floating table. Now:
#   • the canvas reaches the right edge (SPOT_PANEL_RIGHT) and the price ladder
#     is printed ON the gradient, inside the panel (his ENA reference);
#   • the trade table lives INSIDE that panel, in the bottom-right corner level
#     with the histogram — the empty strip his arrow pointed at;
#   • the empty strip is a LAW, not a leftover: ≥11.5 % of the visible window,
#     so the table can never land on a candle or a volume bar.
SPOT_PANEL_RIGHT = 0.9955
SPOT_RIGHT_PAD_FRAC = 0.128
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


def enforce_block_share(ax, d_lo: float, d_hi: float,
                        target: float = 0.72) -> tuple:
    """The candle block owns ≤ `target` of the price panel — enforced LAST.

    그의 law (10-16 and again 10-20: «ارتفاع پایین‌ترین پیوت تا بالاترین پیوت
    نباید بیشتر از ۷۰ تا ۷۵ درصد ارتفاع چارت را بگیرد») was applied while the
    window was being BUILT, so anything that touched the y-limits afterwards
    (a target box, a near level, a live-price nudge) could quietly take the
    block back over it. This runs at the very end, on the FINAL limits, and
    only ever ADDS air — symmetrically, so the approved centering survives.
    Returns the (lo, hi) actually in force.
    """
    try:
        _lo, _hi = ax.get_ylim()
        _lo, _hi = float(min(_lo, _hi)), float(max(_lo, _hi))
        _blk = math.log(max(float(d_hi), 1e-12)) - math.log(max(float(d_lo), 1e-12))
        _span = math.log(max(_hi, 1e-12)) - math.log(max(_lo, 1e-12))
        if _blk <= 0 or _span <= 0 or _blk / _span <= target:
            return _lo, _hi
        _need = _blk / float(target)
        _mid = 0.5 * (math.log(max(_hi, 1e-12)) + math.log(max(_lo, 1e-12)))
        _lo2 = math.exp(_mid - 0.5 * _need)
        _hi2 = math.exp(_mid + 0.5 * _need)
        ax.set_ylim(_lo2, _hi2)
        return _lo2, _hi2
    except Exception as _eb:
        print(f"spot block-share guard skipped: {_eb}")
        return ax.get_ylim()


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


# R99q30 (his 10-20 reference set): every spot file in the reference folder
# shows a TEAL up-bar and a RED down-bar. The live renderer had drifted to
# hollow-white / solid-black — that is his «اصلا رنگ لیبل‌ها هم تغییر کرده».
SPOT_UP = "#26A69A"
SPOT_DN = "#EF5350"


def spot_candle_colors(is_up: bool) -> tuple:
    """(body, edge/wick): teal bullish candle, red bearish candle."""
    return (SPOT_UP if bool(is_up) else SPOT_DN,
            SPOT_UP if bool(is_up) else SPOT_DN)


# ── R99q30 brand mark loader ────────────────────────────────────────────────
_LOGO_CACHE: dict = {}


def _logo_img():
    """The brand mark at its highest available resolution.

    The shipped asset is only 280×296 px — drawing it on a 240-dpi canvas
    upscales a tiny bitmap and every edge goes soft. `assets/vivasignals-logo@4x.png`
    is the same artwork pre-scaled (lanczos, cropped to the mark) so matplotlib
    always has real pixels. Falls back to the 1× file.
    """
    try:
        key = str(logo_path_global())
        got = _LOGO_CACHE.get(key)
        if got is not None:
            return got
        hi = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "assets", "vivasignals-logo@4x.png")
        use = hi if os.path.isfile(hi) else key
        img = mpimg.imread(use)
        _LOGO_CACHE[key] = img
        return img
    except Exception:
        return mpimg.imread(logo_path_global())


def logo_path_global() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "vivasignals-logo.png")


def _log_ticks(lo: float, hi: float, target: int = 11):
    """ROUND labels for a log price axis.

    Two regimes, because one ladder cannot serve both:
      • a short span (≤ 25×, XMR 380–680) — a uniform LINEAR round step reads
        perfectly even and every label is a number a human writes;
      • a wide span (INJ 0.40–12.9, 32×) — only decade rungs survive on a log
        axis, so step through round mantissas 1 · 1.5 · 2 · 2.5 · 3 · 4 · 5 ·
        6 · 8 per decade.
    Never returns "nice" floats like 12.59 or 2.51.
    """
    import math as _m
    try:
        lo, hi = float(lo), float(hi)
        if not (hi > lo > 0):
            return [], 4
        out = []
        if hi / lo <= 25.0:
            raw = (hi - lo) / max(4.0, float(target) - 1.0)
            mag = 10.0 ** _m.floor(_m.log10(raw))
            step = mag
            for mm in (1.0, 2.0, 2.5, 5.0, 10.0, 20.0):
                if 7 <= (hi - lo) / (mm * mag) + 1 <= 13:
                    step = mm * mag
                    break
            v = _m.ceil(lo / step) * step
            while v <= hi * 1.0005 and len(out) < 40:
                out.append(round(v, 12))
                v += step
        else:
            mant = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)
            for e in range(int(_m.floor(_m.log10(lo))), int(_m.ceil(_m.log10(hi))) + 1):
                for mm in mant:
                    v = mm * (10.0 ** e)
                    if lo * 0.995 <= v <= hi * 1.005:
                        out.append(round(v, 12))
            out = sorted(set(out))
            if len(out) > target:
                want = int(target)
                stepi = (len(out) - 1) / float(want - 1)
                out = [out[int(round(k * stepi))] for k in range(want)]
        if len(out) < 5:
            return [], 4
        dec = 0
        while dec < 8 and any(abs(v - round(v, dec)) > 1e-9 for v in out):
            dec += 1
        return out, dec
    except Exception:
        return [], 4


def render(df: pd.DataFrame, a: dict, path: str = None, symbol: str = "",
           stage: str = "", title: str = "", trade: dict = None,
           uid: str = "") -> "str | bytes":
    """رندر واحد اسپات. اگر path خالی باشد بایت PNG برمی‌گرداند.

    `trade` (R99q30, his 10-20: «اطلاعات ورود به پوزیشن هم بیاد روبروی
    هیستوگرام های حجم هم در ستاپ ها هم در اسپات»): an optional dict with
    entry / stop / targets / direction. It is DRAWN ONLY — it never changes the
    detected geometry, the stage or the message.
    """
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
    # R99q35: the right strip must stay wide enough for the trade table — it is
    # empty by construction (it is the future), so growing it costs no candle.
    _need_pad35 = int(math.ceil((x_to - x_from) * SPOT_RIGHT_PAD_FRAC / (1.0 - SPOT_RIGHT_PAD_FRAC)))
    if (x_to - (n - 1)) < _need_pad35:
        x_to = (n - 1) + _need_pad35
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

    # ── R99q30 (his 10-20: «لوگو من … کیفیتش بالا بره»): spot printed at 180 dpi
    # while the setups canvas printed at 240 — same chart, 1.8× fewer pixels,
    # so every mark (logo included) came out soft. One resolution now.
    fig, ax = plt.subplots(figsize=(16, 9), dpi=240)
    fig.patch.set_facecolor("#FFFFFF")
    # حاشیهٔ کم (یادداشت خودش: «حاشیهٔ پشت محور و پایین صفحه رو کم کن»)
    # R99q30: the top band grew (0.915 -> 0.898) — the credit used to sit level
    # with the topmost price tick («بردی روی محور قیمت»).
    # R99q31b: bottom grew to 0.084 so the time-axis labels and the trade box
    # have their own bands and neither lands on the other.
    # R99q31b: `right` 0.952 reserved only the price ladder; the trade box needs
    # its own column. The panel ends at 0.868 so the box (0.872..0.984) sits in
    # genuinely empty space — never over a candle, never over the histogram.
    # ── R99q33g (his 10-20 WLFI/XRP, verbatim: «حاشیه چارت پشت قیمت رو سریع به
    # حالت قبلی برگردون» + «این جا رو به چارت اضافه کن» + «حاشیه ستاپ‌ها هم
    # زیاده قیمت به چارت اضافه بشه»). R99q31b shrank the panel to 0.826 to give
    # the trade box a whole column — a dead white band he circled twice. The
    # panel is back near its former reach (0.870); the trade box stays, compact
    # and grouped, in the narrow strip that remains.
    # ── R99q35 (his 10-20: «پشت محور قیمت‌ها حدود ۱۵ درصد از چارت کندل‌ها کم
    # کردی … این قسمت سفید پشت قیمت‌ها باید به فضای نمودار کندل‌ها اضافه بشه»):
    # the panel now runs to the canvas edge. The ladder is printed INSIDE it and
    # the table sits in the panel's own bottom-right corner — nothing is drawn
    # in a white gutter any more, so the candles get the whole width back.
    fig.subplots_adjust(left=0.016, right=SPOT_PANEL_RIGHT, top=0.898, bottom=0.084)

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

    # ── R99q35 PRICE LADDER INSIDE THE PANEL (his 10-20: «این قسمت سفید پشت
    # قیمت‌ها باید به فضای نمودار کندل‌ها اضافه بشه»، his ENA reference: the
    # digits sit ON the gradient, left-aligned under a thin spine). The ladder is
    # built BEFORE the live pill and the trade table because both are placed
    # against its measured left edge — that is what keeps the pill beside the
    # digits and the table clear of them on every symbol (BTC's «81,766.50» is
    # three times wider than ARB's «0.19»).
    ax.yaxis.tick_right()
    _ladder_x0 = None
    try:
        from matplotlib.ticker import FixedLocator as _FL99
        # چگالی لیبل قیمت (قانون ۱۰-۱۵ خودش): ۱۰ تا ۱۸ لیبل، دقت متناسب گام.
        # R99q30: LOG-space ticks (a linear ladder bunched the cheap levels).
        _tk99, _dp99 = _log_ticks(*ax.get_ylim())
        if len(_tk99) < 6:
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
        # a negative pad prints the digits INSIDE the frame; how far inside is
        # measured from the widest label, never guessed (that guess is what put
        # «81,766.50» on top of the candles).
        from matplotlib import font_manager as _fm35
        _prop35 = _fm35.FontProperties(size=9.2)
        _rd35 = fig.canvas.get_renderer()
        _w35 = 0.0
        for _t35 in ax.get_yticklabels():
            _s35 = (_t35.get_text() or "").strip()
            if not _s35:
                continue
            try:
                _w35 = max(_w35, float(_rd35.get_text_width_height_descent(
                    _s35, _prop35, False)[0]))
            except Exception:
                pass
        _pad35 = -(_w35 * 72.0 / float(fig.dpi) + 7.0)
        ax.tick_params(axis="y", labelsize=9.2, colors="#3A362F", pad=_pad35)
        fig.canvas.draw()
        _rd35b = fig.canvas.get_renderer()
        _xs35 = [float(_t35.get_window_extent(_rd35b).x0)
                 for _t35 in ax.get_yticklabels()
                 if (_t35.get_text() or "").strip()]
        if _xs35:
            _ladder_x0 = min(_xs35) / float(fig.bbox.width)
    except Exception as _ax35:
        print(f"spot price ladder warning: {_ax35}")
        ax.tick_params(axis="y", labelsize=9.2, colors="#3A362F", pad=-34)
    _ts_axis(ax, df, tf)
    ax.tick_params(axis="x", labelsize=10.5, colors="#3A362F", pad=4)
    for s in ("top", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["right"].set_color("#8A857D")
    ax.spines["bottom"].set_color("#8A857D")
    if _ladder_x0 is None:
        _ladder_x0 = SPOT_PANEL_RIGHT - 0.020

    # ── R99q21 CENTRE-WATERMARK LAW (his 10-16 evening: «ویوا سیگنالز پرو رو از
    # وسطش بردار» + «وحید لسانی با همون اندازهٔ ستاپ‌ها، توی اسپات یه خرده
    # پررنگ‌تر»): «VIVA SIGNALS PRO» is GONE from the centre — the AUTHOR's name
    # stands there instead, at the SETUPS chart's own size (38, bold), spot a
    # touch bolder (α .26 vs .20) because spot photos get re-compressed harder.
    ax.text(0.5, 0.245, "VAHID LESANI ANALYSIS", transform=ax.transAxes,
            ha="center", va="center", fontsize=34, fontweight="bold",
            color="#B9B3A5", alpha=0.42, zorder=1)
    logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "assets", "vivasignals-logo.png")
    if os.path.isfile(logo_path):
        try:
            _w_ax = ax.inset_axes([0.40, 0.30, 0.20, 0.38], zorder=1)
            _w_ax.imshow(_logo_img(), alpha=0.10, interpolation="lanczos", resample=True)
            _w_ax.set_axis_off()
            _w_ax.patch.set_alpha(0)
        except Exception:
            pass

    # ── 3) هیستوگرام ولوم کم‌رنگ، چسبیده به کف پنل (یادداشت خودش)
    try:
        v = df["volume"].astype(float).to_numpy()
        vmax = float(np.max(v[n_show])) if len(v) else 0.0
        if vmax > 0:
            # R99q30 (his reference set + «چرا هیستوگرام‌های اسپات رو از روی
            # چارت جدا کردی؟»): the histogram lives INSIDE the price panel,
            # stands on its floor, is tinted with its own candle colour and is
            # tall enough to read. The old grey 6.2% dashes read as tick marks.
            _base = y_lo * math.exp(0.004 * d_span)
            _hgt = 0.088 * d_span
            for i in range(x_from, n):
                _vh = (_hgt * (float(v[i]) / vmax)) if vmax else 0.0
                if _vh <= 0:
                    continue
                # ارتفاع در فضای قیمت: کمیت لگاریتمی → ضرب در پایه (نه exp
                # روی قیمت؛ آن باگ کل پنل را پر می‌کرد)
                _hbar = _base * (math.exp(_vh) - 1.0)
                ax.add_patch(Rectangle((i - 0.33, _base), 0.66, _hbar,
                                       facecolor=SPOT_UP if c[i] >= o[i] else SPOT_DN,
                                       edgecolor="none", alpha=0.34, zorder=2))
    except Exception:
        pass

    # ── 4) monochrome candles: hollow white up-bars and solid black down-bars.
    for i in range(x_from, n):
        body, edge = spot_candle_colors(c[i] >= o[i])
        ax.vlines(i, l[i], h[i], color=edge, lw=1.0, zorder=3)
        ax.add_patch(Rectangle((i - 0.33, min(o[i], c[i])), 0.66,
                               max(abs(c[i] - o[i]), 1e-12), facecolor=body,
                               edgecolor=edge, linewidth=0.75, zorder=4))

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
        _first_i = max(int(getattr(ln, "first_index", x_from)), x_from)
        _last_t = max(list(getattr(ln, "touches", ()) or [n - 1]) or [n - 1])
        # R99q30 (his 10-20: «پترن کج و داغون بی هویت»): the solid part must
        # reach the LAST VALIDATED TOUCH. The old code took max(last_touch,
        # first_index) — on a line whose pivots sit outside the visible window
        # that collapses to ONE BAR and matplotlib then joins the projection's
        # first point to it, drawing a visibly tilted segment that no pivot sits
        # on. A solid edge now always spans first pivot → last touch.
        _span_end = min(n - 1, max(_last_t, _first_i + 1))
        if _span_end <= _first_i:
            _span_end = min(n - 1, _first_i + 1)
        xs = np.array([_first_i, _span_end])
        ax.plot(xs, [ln.price_at(x) for x in xs], color=INK,
                lw=2.55 if is_entry else 2.0,
                alpha=1.0 if is_entry else 0.92, zorder=6, solid_capstyle="round")
        if x_to > _span_end:   # faint, thin projection only — not a traded edge
            xs_p = np.array([_span_end, x_to - 1])
            ax.plot(xs_p, [ln.price_at(x) for x in xs_p], color=INK,
                    lw=0.82 if is_entry else 0.72, ls=(0, (5, 4)), alpha=0.38,
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

    # ── 5b) SPOT RENDERS NO ZONES ─────────────────────────────────────────
    # His 10-21, verbatim: «آقا اسپات نباید نواحی رو رندر بگیره.. نواحی فقط
    # ستاپ‌ها است». The R99q32a POI boxes that lived here (SUPPLY/DEMAND/FVG/
    # FLIP at the live edge) are gone: spot is a BREAK canvas — the shape's
    # two edges, the target strip and the trade box. Zones belong to the five
    # setup engines, and there only the same-TF refined ones are drawn.

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
    # ── R99q33f (his 10-20 WLFI, verbatim: «حاشیه چارت پشت قیمت رو سریع به
    # حالت قبلی برگردون» + «سریعا این جا رو به چارت اضافه کن»). The live pill
    # used to be stuffed at x_to+0.4 INSIDE the panel, where it landed on the
    # price ladder and ate a tick number («0.054»). It is back in the white
    # margin BEHIND the price now — the ENA reference placement — measured so
    # it never touches the ladder digits.
    # R99q35: the ladder now lives INSIDE the panel, so the pill does too —
    # right-aligned just before the digits (his ENA reference), never in a dead
    # white gutter.
    _live_x, _live_ha = 0.995, "right"
    try:
        ax.figure.canvas.draw()
        _rd0 = ax.figure.canvas.get_renderer()
        _ab0 = ax.get_window_extent(_rd0)
        _lbl_px = float(_ladder_x0) * float(fig.bbox.width)
        if _ab0.width > 1 and _lbl_px > _ab0.x0:
            _live_x = (_lbl_px - 6.0 - _ab0.x0) / float(_ab0.width)
    except Exception:
        _live_x = 0.995
    _live_x = max(0.60, min(_live_x, 0.99))
    import matplotlib.transforms as _mtr33
    _tr33 = _mtr33.blended_transform_factory(ax.transAxes, ax.transData)
    _live_art = ax.text(_live_x, live, f" {_price_fmt(live)} ",
                        transform=_tr33, ha=_live_ha, va="center", clip_on=False,
                        fontsize=9.5, fontweight="bold", color="#FFFFFF", zorder=21,
                        bbox=dict(boxstyle="square,pad=0.28", facecolor=LIVE_PINK,
                                  edgecolor=LIVE_PINK))
    # ── R99q35b LABEL-COLLISION LAW (his standing rule: «برچسب‌ها همدیگه رو
    # نپوشونن»). The pill rides the live price, so sooner or later it lands on the
    # tick that carries the same level — the last render printed «2,388» straight
    # through «2,400». When the pill's box meets a tick's box, the TICK steps
    # aside: the pill already states that price (his ENA reference does exactly
    # this), and the pill itself is never hidden because it is the live number.
    try:
        fig.canvas.draw()
        _rdp = fig.canvas.get_renderer()
        _pb = _live_art.get_window_extent(_rdp)
        for _tp in ax.get_yticklabels():
            if not (_tp.get_text() or "").strip():
                continue
            _tb = _tp.get_window_extent(_rdp)
            if _pb.x1 > (_tb.x0 - 7.0) and _pb.x0 < _tb.x1 \
                    and _pb.y0 < _tb.y1 and _pb.y1 > _tb.y0:
                _tp.set_visible(False)
    except Exception as _cp:
        print(f"spot label collision warning: {_cp}")

    # ── 8) استمپ زمان تهران — R99q33b (his 10-20, verbatim: «کلمه live رو از
    # برچسب زمان حذف بکن تا روی هیستوگرام ولوم رو نپوشونه»). The word is gone
    # and the stamp now lives BELOW the panel, right-aligned under the price
    # ladder: inside the panel it sat on the volume bars on every tight chart.
    try:
        _now = datetime.now(ZoneInfo("Asia/Tehran"))
        fig.text(0.826, 0.052,
                 f" {_now.strftime('%d %b %Y')} • {_now.strftime('%H:%M')} ",
                 ha="right", va="center", fontsize=8.2, color=INK, zorder=12,
                 bbox=dict(boxstyle="round,pad=0.26", facecolor="#FFFDF2",
                           edgecolor="#B9B29F", linewidth=0.7))
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
    # R99q23 (his 10-17: «ویوا سیگنالز پرو رو از هر دو دیزاین ستاپ‌ها و اسپات
    # حذف کن»): the brand word is GONE from the header as well — the stage line
    # now starts with the fact, and the author's own mark carries the chart.
    fig.text(0.020, 0.941, f"{stage_lab}  •  {title}  •  Log Scale",
             fontsize=11, color=MUTED)
    fig.text(0.020, 0.916,
             f"O {_price_fmt(last_o)}   H {_price_fmt(last_h)}   "
             f"L {_price_fmt(last_l)}   C {_price_fmt(last_c)}   "
             f"{chg:+.4f} ({chg_pct:+.2f}%)   •   BINANCE SPOT",
             fontsize=10, fontweight="bold", color="#B3261E")
    # ── R99q23 TOP-RIGHT CREDIT (his 10-17, verbatim: «اون برچسب جدید چند دور
    # قبل هم نمی‌خواد، فقط به کنار اسم من بالای سمت راست چارت لوگو رو اضافه
    # کن»): no banner, no badge, no extra label — the NAME and the LOGO, side
    # by side, in the top-right corner of both designs.
    # ── R99q30 (his 10-20, verbatim: «لوگو من در بالای چارت همونی که قبلا بود
    # در اسپات و ستاپ‌ها اندازه و کیفیتش بالا بره ... و متن اسم خودم و برندم
    # فقط جلوش بیاد ... اونم خیلی کوچیک و بی کیفیت»): the mark is BIGGER, drawn
    # from the 4× asset with a lanczos resample, and the NAME + BRAND line sits
    # BESIDE it — the credit block ends inside the header band, never on the
    # price axis (top moved to 0.898 above).
    # ── R99q31b (his 10-20: «گوشه سمت راست بالا اسم و برند و لوگو من از کادر
    # خارج شده .. باید کمی بیاد پایین‌تر و کالیبره بشه در اسپات»). The figure
    # ended at x=1.000 with the mark's right edge at 0.990 + its own width —
    # it clipped. The block is now measured INSIDE a safe right margin and sits
    # lower, level with the header's second line instead of over the title.
    _brand30 = "VAHID LESANI — VIVA SIGNALS PRO"
    _lh30 = 0.062
    _right30 = 0.982                 # hard right edge, inside the canvas
    if os.path.isfile(logo_path):
        try:
            _lim = _logo_img()
            _lw30 = _lh30 * (float(_lim.shape[1]) / float(_lim.shape[0])) \
                * (float(fig.get_figheight()) / float(fig.get_figwidth()))
            _lx30 = _right30 - _lw30
            _lax = fig.add_axes([_lx30, 0.958 - _lh30 / 2.0, _lw30, _lh30], zorder=12)
            _lax.imshow(_lim, alpha=1.0, interpolation="lanczos", resample=True)
            _lax.axis("off")
            _lax.patch.set_alpha(0)
            fig.text(_lx30 - 0.008, 0.958, _brand30, fontsize=11.5,
                     fontweight="bold", color=INK, ha="right", va="center")
        except Exception as _e23:
            print(f"spot credit logo warning: {_e23}")
    else:
        fig.text(_right30, 0.958, _brand30, fontsize=11.5, fontweight="bold",
                 color=INK, ha="right", va="center")

    # ── 10) فوتر
    fig.text(0.020, 0.010, f"{sym}  •  VIVA  •  SPOT  •  BINANCE SPOT",
             fontsize=10, color=INK)
    # R99q23: the footer brand word is GONE too — only the mark remains.
    if os.path.isfile(logo_path):
        try:
            b_ax = fig.add_axes([0.956, 0.010, 0.026, 0.046], zorder=10)
            b_ax.imshow(_logo_img(), alpha=0.95, interpolation="lanczos", resample=True)
            b_ax.axis("off")
        except Exception:
            pass

    # ── 10b) R99q31b TRADE BOX — one grouped pill column on the RIGHT, beside
    # the volume histogram (his 10-20, verbatim: «در مورد برچسب های ورود و خروج
    # اسپات یک باکس کلی کوچک مثل ستاپ‌ها درست بکن و روبروی هیستوگرام های ولوم
    # در سمت راست چارت مقابلش فرار بده اونجا هیچوقت نه کندل وجود داره نه ابزار
    # شورت یا باکس هیستوگرام ها هم زیر نمیره»).
    #
    # The 10-19 version printed loose pills along the bottom-left, straight over
    # the time axis. This is ONE framed block in the bottom-right corner: the
    # right margin past the last candle is always empty, so nothing is covered.
    if trade:
        try:
            _rows30 = []
            _e30 = float(trade.get("entry") or 0)
            _s30 = float(trade.get("stop") or 0)
            if _e30 > 0:
                _rows30.append(("ENTRY", _e30, "#1F6FEB"))
            if _s30 > 0:
                _rows30.append(("STOP", _s30, "#C62828"))
            for _i30, _k30 in enumerate(("tp1", "tp2", "tp3")):
                _v30 = float(trade.get(_k30) or 0)
                if _v30 > 0:
                    _rows30.append((f"TP{_i30 + 1}", _v30, "#2E7D32"))
            _d30 = str(trade.get("direction") or "LONG").upper()
            _tag30 = "SHORT" if _d30 in ("SHORT", "DOWN", "BEAR", "BEARISH") else "LONG"
            if _rows30:
                _row_h30 = 0.0215
                # R99q35: the table moved INTO the panel's own bottom-right
                # corner (his arrow), left of the price digits and fully inside
                # the empty future strip — never over a candle, never over a
                # volume bar, never in a white gutter.
                # width is whatever fits between the last candle and the
                # ladder's measured left edge (BTC-safe), capped for looks
                try:
                    _last_px = ax.transData.transform((n - 1, float(c[-1])))[0]
                    _last_frac = _last_px / float(fig.bbox.width)
                except Exception:
                    _last_frac = 0.86
                _room30 = max(0.0, float(_ladder_x0) - _last_frac - 0.012)
                _box_w30 = max(0.060, min(0.086, _room30))
                _box_h30 = _row_h30 * len(_rows30) + 0.020
                _bx30 = float(_ladder_x0) - 0.008 - _box_w30
                _by30 = 0.096           # sits on the panel floor, clear of the axis
                # the frame: one grouped box, exactly like the setup charts
                fig.patches.append(Rectangle(
                    (_bx30, _by30), _box_w30, _box_h30,
                    transform=fig.transFigure, facecolor="#FFFFFF",
                    edgecolor="#D8D2C2", linewidth=0.9, alpha=0.94, zorder=13))
                fig.text(_bx30 + 0.010, _by30 + _box_h30 - 0.012,
                         f"TRADE  ·  {_tag30}", fontsize=7.6, fontweight="bold",
                         color=MUTED, ha="left", va="center", zorder=14)
                for _r30, (_lab30, _val30, _col30) in enumerate(_rows30):
                    _yy30 = _by30 + _box_h30 - 0.028 - _r30 * _row_h30
                    fig.patches.append(Rectangle(
                        (_bx30 + 0.008, _yy30 - 0.0082), 0.008, 0.0164,
                        transform=fig.transFigure, facecolor=_col30,
                        edgecolor="none", zorder=14))
                    fig.text(_bx30 + 0.021, _yy30, _lab30, fontsize=7.8,
                             fontweight="bold", color=_col30, ha="left",
                             va="center", zorder=14)
                    fig.text(_bx30 + _box_w30 - 0.010, _yy30, _price_fmt(_val30),
                             fontsize=8.4, fontweight="bold", color=INK,
                             ha="right", va="center", zorder=14)
                # R99q33g: the live pill keeps its TRUE level, but if that level
                # falls inside the trade box the pill slides to the box's top
                # edge — never a price badge printed through a table.
                try:
                    fig.canvas.draw()
                    _rr = fig.canvas.get_renderer()
                    _pb = _live_art.get_window_extent(_rr)
                    _fbb = fig.bbox
                    if _pb.y0 < (_by30 + _box_h30) * _fbb.height and \
                            _pb.y1 > _by30 * _fbb.height:
                        _ynew = (_by30 + _box_h30 + 0.012) * _fbb.height
                        _pv = ax.transData.inverted().transform((_pb.x0, _ynew))[1]
                        _live_art.set_position((_live_x, float(_pv)))
                except Exception as _lp:
                    print(f"spot live pill nudge warning: {_lp}")
        except Exception as _t30e:
            print(f"spot trade box warning: {_t30e}")

    # ── 10c) R99q31b UNIQUE ID, bottom-LEFT, BELOW the time-axis labels so it
    # can never cover a date (his 10-20: «پایین سمت چپ اسپات قرار بود شماره
    # شناسه یکتا زده بشه جوری که روی اعداد محور زمان رو نپوشاند»). The footer
    # line sits at y=0.024; the ticks render above it at ~0.045.
    if uid:
        try:
            fig.text(0.020, 0.032, f"ID  {uid}", fontsize=8.6,
                     fontweight="bold", color=INK, ha="left", va="bottom",
                     zorder=14)
        except Exception as _u30e:
            print(f"spot uid warning: {_u30e}")


    # ── the envelope law, enforced on the FINAL limits (his 10-20 restatement)
    _yl_fin = enforce_block_share(ax, d_lo, d_hi, SPOT_ENVELOPE_TARGET)

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
