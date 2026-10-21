"""stage2_wiring — نقطهٔ اتصال واحد دو انجین به لایهٔ تایید/شناسایی پوزیشن.

هیچ قالب پیامی را لمس نمی‌کند؛ فقط خروجی ساخت‌یافته می‌دهد تا بوت/داشبورد/اپ
در مرحلهٔ بعد از آن بخوانند. اسپات: فقط لانگ/هشدار. پرپچوآل: لانگ/شورت با
استاپ و ابطال هندسی.
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from analysis import engine_perp, engine_spot


def spot_report(df: pd.DataFrame, tf: str) -> Optional[Dict]:
    a = engine_spot.analyze(df, tf)
    if not a:
        return None
    return {
        "market": "SPOT", "tf": tf, "symbol_pattern": a["slug"], "fa": a["fa"],
        "stage": a["breakout"]["status"], "quality": a["breakout"].get("quality"),
        "actionable_long": a["actionable_long"], "alert": a["alert"],
        "entry_if_break": round(a["level"], 8),
        "target": round(a["target"], 8) if a["target"] else None,
        "bias": a["bias"], "entry_side_of_pattern": a["entry_side"],
        "view_bars": a["view"]["bars"], "fill": round(a["view"]["fill"], 2),
    }


def perp_position_report(df: pd.DataFrame, tf: str, brand: str) -> Optional[Dict]:
    """شناسایی پوزیشن پرپچوآل: سمت، ورود، استاپ، هدف، ابطال و چرخهٔ شکست."""
    a = engine_perp.analyze(df, tf, brand)
    if not a:
        return None
    inv = None
    if a["side"] == "LONG":
        inv = "کلوز زیر ضلع پایین/استاپ = ابطال"
    elif a["side"] == "SHORT":
        inv = "کلوز بالای ضلع بالا/استاپ = ابطال"
    return {
        "market": "PERP", "brand": brand, "style": a["style"], "tf": tf,
        "pattern": a["slug"], "fa": a["fa"],
        "position": a["side"],                       # LONG / SHORT / None
        "stage": a["breakout"]["status"],
        "quality": a["breakout"].get("quality"),
        "entry": round(a["entry"], 8) if a["entry"] else None,
        "stop": round(a["stop"], 8) if a["stop"] else None,
        "target": round(a["target"], 8) if a["target"] else None,
        "invalidation": inv, "gate_note": a.get("gate_note"),
        "bias": a["bias"], "roles": a["roles"],
        "view_bars": a["view"]["bars"], "fill": round(a["view"]["fill"], 2),
    }


def scan_all(frames: Dict[str, pd.DataFrame], brands=("PINVAL", "ALBROX",
                            "TECHCLASSIC", "TLBREAK")) -> Dict:
    """خروجی ترکیبی برای بورد تأیید: اسپات همهٔ TFها + پرپچوآل هر برند/TF."""
    out = {"spot": [], "perp": []}
    for tf, df in frames.items():
        if df is None or len(df) < 60:
            continue
        s = spot_report(df, tf) if tf in engine_spot.SPOT_TFS else None
        if s:
            s["tf"] = tf
            out["spot"].append(s)
        for b in brands:
            p = perp_position_report(df, tf, b)
            if p:
                out["perp"].append(p)
    return out
