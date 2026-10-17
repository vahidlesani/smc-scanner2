"""engine_spot — انجین نهایی اسپات (لایهٔ سیاست روی viva_geometry).

قوانین: فقط لانگ؛ شکست نزولی = هشدار/ابطال، نه شورت. همهٔ تایم‌فریم‌های اسپات
(4h·8h·12h·1d·3d·1w) از همین یک انجین و همین یک هستهٔ هندسه استفاده می‌کنند.
چارت = ترید (G1): رندر فقط خروجی analyze() را می‌کشد، هرگز دوباره کشف نمی‌کند.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from analysis import viva_geometry as vg

SPOT_TFS = ["4h", "8h", "12h", "1d", "3d", "1w"]

# R99q (Viva 10-15, verbatim: «به پیوت ماژور داخل اون تایم‌فریم و چارتش احترام
# بذار .. نه اینکه از ۲۰۰ کندل قبل‌تر یک پیوت پیدا بکنی مثل جاده بی‌سر و ته یه
# دونه بکشی وسط چارت‌ها»): پنچرهٔ تحلیل هر TF کوچک‌تر از کل فریم است — پیوت‌ها
# فقط از داخل همین پنجره (که همان چیزی است که روی چارت دیده می‌شود) می‌آیند.
# offset داخلی fit_patterns ایندکس جهانی را حفظ می‌کند؛ چارت و انجین هم‌تراز
# می‌مانند و مولتی‌تایم‌فریم فقط «تحلیلی» می‌شود، نه یک خط از ماه‌ها قبل.
SPOT_LOOKBACK = {"4h": 150, "8h": 120, "12h": 100, "1d": 80, "3d": 60, "1w": 50}

_FA = {"CHANNEL_FLAT": "کانال افقی", "BROADENING": "گوهٔ پهن‌شونده",
       "BROADENING_WEDGE_ASC": "کانال پهن‌شوندهٔ صعودی",
       "BROADENING_WEDGE_DESC": "کانال پهن‌شوندهٔ نزولی",
       "CHANNEL_ASCENDING_BROAD": "کانال صعودی باز",
       "CHANNEL_DESCENDING_BROAD": "کانال نزولی باز",
       "DOUBLE_TOP": "سقف دوقلو", "DOUBLE_BOTTOM": "کف دوقلو",
       "HEAD_SHOULDERS": "سر و شانه", "INV_HEAD_SHOULDERS": "سر و شانهٔ معکوس",
       "CUP_HANDLE": "فنجان و دسته", "INV_CUP_HANDLE": "فنجان و دستهٔ معکوس"}


def _fa(slug: str) -> str:
    try:
        from analysis.patterns16 import PATTERN16_LIBRARY
        if slug in PATTERN16_LIBRARY:
            return PATTERN16_LIBRARY[slug]["fa"]
    except Exception:
        pass
    return _FA.get(slug, slug.replace("_", " ").title())



PIVOT_ENTRY_EDGE = {"DOUBLE_TOP": "LOWER", "HEAD_SHOULDERS": "LOWER",
                    "INV_CUP_HANDLE": "LOWER", "DOUBLE_BOTTOM": "UPPER",
                    "INV_HEAD_SHOULDERS": "UPPER", "CUP_HANDLE": "UPPER"}


def _pivot_gate(res, brk):
    """دکترین الگوهای پیوتی: ورود فقط از شکست خط گردن؛ شکست سمت مقابل = ابطال."""
    if res.kind != "pivot_pattern":
        return brk
    allowed = PIVOT_ENTRY_EDGE.get(res.slug)
    if allowed and brk["edge"] and brk["edge"] != allowed:
        return dict(brk, status="INVALIDATED", gate_note=f"شکست {brk['edge']} = ابطال الگو")
    return brk

def _shape_name(res) -> str:
    """نام هندسیِ واقعیِ الگو از خودِ دو ضلع (اسپات، فایل خودش).

    دسته‌بندِ عمومی گاهی «موازی/پهن‌شونده» می‌گوید در حالی که دو ضلع دارند به هم
    می‌رسند (همان «پترن غلط»). اینجا نسبتِ فاصلهٔ دو ضلع در ابتدا و انتهای الگو
    حساب می‌شود: نزدیک‌شونده = گوه/مثلث، دورشونده = پهن‌شونده، ثابت = کانال.
    """
    try:
        import math
        u, lo = res.upper, res.lower
        if u is None or lo is None:
            return res.slug
        x0, x1 = int(res.x0), int(res.x1)
        g0 = math.log(max(u.price_at(x0), 1e-12)) - math.log(max(lo.price_at(x0), 1e-12))
        g1 = math.log(max(u.price_at(x1), 1e-12)) - math.log(max(lo.price_at(x1), 1e-12))
        if g0 <= 0 or g1 <= 0:
            return res.slug
        ratio = g1 / g0
        both_down = float(u.slope) < 0 and float(lo.slope) < 0
        both_up = float(u.slope) > 0 and float(lo.slope) > 0
        if ratio <= 0.85:                      # نزدیک‌شونده
            if both_down:
                return "WEDGE_FALLING"
            if both_up:
                return "WEDGE_RISING"
            return "TRIANGLE_SYMMETRICAL"
        if ratio >= 1.18:                      # دورشونده = واقعاً پهن‌شونده
            return res.slug if "BROAD" in res.slug.upper() else (
                "CHANNEL_DESCENDING_BROAD" if both_down else
                "CHANNEL_ASCENDING_BROAD" if both_up else "BROADENING")
        if both_down:                          # موازی
            return "CHANNEL_DESCENDING"
        if both_up:
            return "CHANNEL_ASCENDING"
        return "CHANNEL_FLAT"
    except Exception:
        return res.slug


def best_pattern(df: pd.DataFrame, tf: str, lookback: Optional[int] = None):
    """بهترین پترن اسپات + اولویت کانال (R99q، یادداشت دستی ویوا روی ENA).

    روی چارتِ ENA، ویوا با دست دو خط «نزولی/نزولی» کشی: ضلع بالا روی سقف‌های
    ماژور و ضلع پایین موازی‌اش — یعنی ساختار عملیاتی = کانال/ترندِ نزولی، نه ضلع
    افقی. اگر کاندیدِ کانال تا ۳ امتیاز به صدر نزدیک باشد، کانال می‌برد
    (کانال = هر دو ضلع هم‌جهت؛ قانون خودش «ترند ماژور»). موتور فقط همین‌جای
    اسپات است — سراغ انجین‌های دیگر نمی‌رود (§5: جراحی در فایل خودِ ستاپ).
    """
    two = vg.fit_patterns(df, lookback=lookback)
    piv = vg.detect_pivot_patterns(df, lookback=lookback)
    # Viva 10-16: pivot-only families were retired from the live pattern set.
    # The geometry library still contains legacy detectors for compatibility,
    # so enforce the retirement at the consumer boundary before ranking. This
    # prevents a high-scoring DOUBLE_TOP / H&S / CUP_HANDLE from outranking a
    # valid live structure and leaking into the Spot chart or alert metadata.
    from analysis.pattern_law import pattern_is_live

    # Enforce the canonical live-pattern registry on BOTH geometry paths.
    # Filtering only retired pivot families left generic TRIANGLE/CHANNEL
    # fallbacks eligible for live Spot metadata despite lacking validated
    # shape rules. Keep those diagnostic-only candidates out before ranking.
    allp = sorted(
        [r for r in (two + piv)
         if pattern_is_live(str(getattr(r, "slug", "")).strip().upper())],
        key=lambda r: -r.score,
    )
    if not allp:
        return None
    top = allp[0]
    try:
        for r in allp:
            _up, _lo = float(r.upper.slope), float(r.lower.slope)
            if (r.slug.upper().startswith("CHANNEL")
                    and r.score >= top.score - 4.0          # پنجرهٔ نزدیک (ENA: 3.1)
                    and _up * _lo > 0                        # هر دو ضلع هم‌جهت = کانال واقعی
                    and abs(_up - _lo) < 0.012               # موازی‌مانند، نه پهن‌شونده
                    and len(r.upper.touches) >= 2 and len(r.lower.touches) >= 2):
                return r
    except Exception:
        pass
    return top


def analyze(df: pd.DataFrame, tf: str, lookback: Optional[int] = None) -> Optional[Dict]:
    """خروجی کامل برای رندر و کارت اسپات؛ هندسه از هستهٔ واحد، بدون کشف دوم."""
    if tf not in SPOT_TFS:
        raise ValueError(f"TF اسپات نامعتبر: {tf} — مجاز: {SPOT_TFS}")
    if lookback is None:
        lookback = SPOT_LOOKBACK.get(tf)
    res = best_pattern(df, tf, lookback)
    if res is None:
        return None
    L = vg.log_ohlc(df)
    atr = vg.atr_log(L)
    brk = _pivot_gate(res, vg.breakout_lifecycle(df, res, atr))
    edge = brk["edge"] or res.outlook.get("likely_edge")
    direction = vg.UP if edge == "UPPER" else vg.DOWN
    line = res.upper if edge == "UPPER" else res.lower
    ev = brk["event_index"]
    level = line.price_at(ev if ev is not None else len(df) - 1)
    target = vg.measured_target(res.slug, res.meta, level, direction)
    view = vg.choose_view(df, res,
                                target if brk["status"] != "INSIDE" else None, tf=tf)

    actionable = False
    alert = None
    if direction == vg.UP and brk["status"] in ("BREAK_UP_CLOSED", "RETEST_UP") \
            and brk["quality"] in ("STRONG", "OK"):
        actionable = True                      # لانگ اسپات
    elif direction == vg.DOWN and brk["status"] in ("BREAK_DOWN_CLOSED", "RETEST_DOWN"):
        alert = "هشدار نزولی: شکست ضلع پایین — اسپات شورت نمی‌زند؛ محافظت/خروج"
    elif brk["status"] == "INSIDE":
        c = float(L["close"][-1])
        if c > line.price_at(len(df) - 1) * (1 - 0.01) and edge == "UPPER":
            alert = "نزدیک به شکست صعودی — در انتظار کلوز معتبر"

    _name9 = _shape_name(res)
    return {
        "engine": "SPOT", "tf": tf, "slug": res.slug, "name_slug": _name9,
        "fa": _fa(_name9),
        "kind": res.kind, "result": res,
        "upper": res.upper, "lower": res.lower, "neckline": res.neckline,
        "x0": res.x0, "x1": res.x1,
        "entry_side": res.leg.direction, "bias": res.outlook.get("bias"),
        "breakout": brk, "direction": direction,
        "level": level, "target": target, "view": view, "atr": atr,
        "actionable_long": actionable, "alert": alert,
        "roles": res.outlook,
    }


def scan(frames: Dict[str, pd.DataFrame]) -> List[Dict]:
    """اسکن چند تایم‌فریم؛ هر TF مستقل (قانون r56: بریک هر TF مستقل منتشر می‌شود)."""
    out = []
    for tf in SPOT_TFS:
        df = frames.get(tf)
        if df is None or len(df) < 60:
            continue
        a = analyze(df, tf)
        if a:
            out.append(a)
    return out
