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

def best_pattern(df: pd.DataFrame, tf: str, lookback: Optional[int] = None):
    two = vg.fit_patterns(df, lookback=lookback)
    piv = vg.detect_pivot_patterns(df, lookback=lookback)
    allp = sorted(two + piv, key=lambda r: -r.score)
    return allp[0] if allp else None


def analyze(df: pd.DataFrame, tf: str, lookback: Optional[int] = None) -> Optional[Dict]:
    """خروجی کامل برای رندر و کارت اسپات؛ هندسه از هستهٔ واحد، بدون کشف دوم."""
    if tf not in SPOT_TFS:
        raise ValueError(f"TF اسپات نامعتبر: {tf} — مجاز: {SPOT_TFS}")
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

    return {
        "engine": "SPOT", "tf": tf, "slug": res.slug, "fa": _fa(res.slug),
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
