"""engine_perp — انجین کامل و واحد پرپچوآل (جایگزین سه انجین تکه‌تکه).

یک کلاس سیاست برای همهٔ برندها؛ تفاوت برندها فقط در آداپتور (تایم‌فریم تریگر،
سبک روزمعامله/سویینگ) است — هندسه از همان هستهٔ واحد viva_geometry.
ورود از هر دو سمت: جهت شکست سمت را تعیین می‌کند؛ ماهیت الگو بایاس است و trades
خلاف ماهیت فقط با کندل شکست STRONG/OK و کلوز معتبر (قانون r54).
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from analysis import viva_geometry as vg
from analysis.engine_spot import _fa, _pivot_gate

BRANDS = {
    "PINVAL": {"style": "DAYTRADE", "trig_tfs": ["15m", "30m"], "pat_tf": "4h"},
    "ALBROX": {"style": "SWING", "trig_tfs": ["15m", "30m", "1h"], "pat_tf": "4h"},
    "TECHCLASSIC": {"style": "SWING", "trig_tfs": ["15m", "2h"], "pat_tf": "1d"},
    "TLBREAK": {"style": "SWING", "trig_tfs": ["30m", "1h", "2h"], "pat_tf": "4h"},
}


def analyze(df: pd.DataFrame, tf: str, brand: str = "PINVAL",
            lookback: Optional[int] = None) -> Optional[Dict]:
    if brand not in BRANDS:
        raise ValueError(f"برند نامعتبر: {brand} — مجاز: {list(BRANDS)}")
    cfg = BRANDS[brand]
    two = vg.fit_patterns(df, lookback=lookback)
    piv = vg.detect_pivot_patterns(df, lookback=lookback)
    allp = sorted(two + piv, key=lambda r: -r.score)
    if not allp:
        return None
    res = allp[0]
    L = vg.log_ohlc(df)
    atr = vg.atr_log(L)
    n = len(df)
    brk = _pivot_gate(res, vg.breakout_lifecycle(df, res, atr))
    if brk["status"] == "INSIDE":
        side = None
    elif brk["edge"] == "UPPER":
        side = "LONG"
    else:
        side = "SHORT"

    # دروازهٔ ماهیت (r54): خلاف ذات فقط با شکست قوی و کلوز معتبر
    bias = res.outlook.get("bias")
    against = (side == "LONG" and bias == vg.DOWN) or (side == "SHORT" and bias == vg.UP)
    gate_ok = brk["quality"] in ("STRONG", "OK")
    if side and against and not gate_ok:
        side = None
        note = "شکست خلاف ماهیت با کندل ضعیف — بدون پوزیشن"
    else:
        note = None

    entry = stop = target = None
    if side:
        ev = brk["event_index"] or n - 1
        if side == "LONG":
            entry = res.upper.price_at(ev)
            stop = res.lower.price_at(ev) * math_exp(-0.25 * atr)
            target = vg.measured_target(res.slug, res.meta, entry, vg.UP)
        else:
            entry = res.lower.price_at(ev)
            stop = res.upper.price_at(ev) * math_exp(0.25 * atr)
            target = vg.measured_target(res.slug, res.meta, entry, vg.DOWN)
    view = vg.choose_view(df, res,
                                target if brk["status"] != "INSIDE" else None, tf=tf)
    return {
        "engine": "PERP", "brand": brand, "style": cfg["style"], "tf": tf,
        "slug": res.slug, "fa": _fa(res.slug), "kind": res.kind, "result": res,
        "upper": res.upper, "lower": res.lower, "neckline": res.neckline,
        "x0": res.x0, "x1": res.x1, "entry_side": res.leg.direction,
        "bias": bias, "breakout": brk, "side": side, "gate_note": note,
        "entry": entry, "stop": stop, "target": target, "view": view,
        "atr": atr, "roles": res.outlook,
    }


def math_exp(x: float) -> float:
    import math
    return math.exp(x)
