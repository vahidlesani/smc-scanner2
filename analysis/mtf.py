# analysis/mtf.py - Multi-Timeframe Analysis
# 4H → 1H → 15M (Swing) / 15M → 5M (Scalp)

import pandas as pd
from typing import Optional, Dict, Tuple
from data.fetcher import get_klines, get_multi_tf
from analysis.structure import find_swing_points, classify_structure, detect_bos_choch


def analyze_mtf_swing(symbol: str) -> Dict:
    """
    تحلیل چند تایم فریمی برای سوئینگ:
    4H (Bias) → 1H (Confirmation) → 15M (Entry)
    
    خروجی:
    - bias: جهت کلی بازار
    - htf_confirmed: آیا HTF تایید شده
    - ltf_ready: آیا LTF آماده ورود
    - trade_style: SWING
    - tf_info: اطلاعات هر تایم فریم
    """
    result = {
        "bias": None,
        "htf_confirmed": False,
        "ltf_ready": False,
        "trade_style": "SWING",
        "tf_info": {},
        "scalp_tf": "",
        "swing_tf": "4H",
    }
    
    # ─── 4H: Bias اصلی ───
    df_4h = get_klines(symbol, "4h", 100)
    if df_4h is None:
        return result
    
    sh_4h, sl_4h = find_swing_points(df_4h, lookback=5)
    structure_4h = classify_structure(sh_4h, sl_4h)
    bias_4h = structure_4h["bias"]
    
    result["tf_info"]["4h"] = {
        "bias": bias_4h,
        "last_high": structure_4h.get("last_high"),
        "last_low": structure_4h.get("last_low"),
    }
    
    if not bias_4h or "NEUTRAL" in bias_4h:
        return result
    
    result["bias"] = bias_4h
    
    # ─── 1H: تایید ساختار ───
    df_1h = get_klines(symbol, "1h", 100)
    if df_1h is not None:
        sh_1h, sl_1h = find_swing_points(df_1h, lookback=3)
        structure_1h = classify_structure(sh_1h, sl_1h)
        bias_1h = structure_1h["bias"]
        
        result["tf_info"]["1h"] = {
            "bias": bias_1h,
            "last_high": structure_1h.get("last_high"),
            "last_low": structure_1h.get("last_low"),
        }
        
        # HTF confirmed = هم‌جهت بودن 4H و 1H
        if bias_1h == bias_4h:
            result["htf_confirmed"] = True
    
    # ─── 15M: ورود ───
    df_15m = get_klines(symbol, "15m", 100)
    if df_15m is not None:
        sh_15m, sl_15m = find_swing_points(df_15m, lookback=3)
        structure_15m = classify_structure(sh_15m, sl_15m)
        bias_15m = structure_15m["bias"]
        
        result["tf_info"]["15m"] = {
            "bias": bias_15m,
            "last_high": structure_15m.get("last_high"),
            "last_low": structure_15m.get("last_low"),
            "current_price": df_15m["close"].iloc[-1],
        }
        
        result["ltf_ready"] = True
    
    result["scalp_tf"] = "15m"
    
    return result


def analyze_mtf_scalp(symbol: str) -> Dict:
    """
    تحلیل چند تایم فریمی برای اسکلپ:
    1H (Bias) → 15M (Confirmation) → 5M (Entry)
    """
    result = {
        "bias": None,
        "htf_confirmed": False,
        "ltf_ready": False,
        "trade_style": "SCALP",
        "tf_info": {},
        "scalp_tf": "5m",
        "swing_tf": "1h",
    }
    
    # ─── 1H: Bias ───
    df_1h = get_klines(symbol, "1h", 100)
    if df_1h is None:
        return result
    
    sh_1h, sl_1h = find_swing_points(df_1h, lookback=5)
    structure_1h = classify_structure(sh_1h, sl_1h)
    bias_1h = structure_1h["bias"]
    
    result["tf_info"]["1h"] = {
        "bias": bias_1h,
        "last_high": structure_1h.get("last_high"),
        "last_low": structure_1h.get("last_low"),
    }
    
    if not bias_1h or "NEUTRAL" in bias_1h:
        return result
    
    result["bias"] = bias_1h
    
    # ─── 15M: تایید ───
    df_15m = get_klines(symbol, "15m", 100)
    if df_15m is not None:
        sh_15m, sl_15m = find_swing_points(df_15m, lookback=3)
        structure_15m = classify_structure(sh_15m, sl_15m)
        bias_15m = structure_15m["bias"]
        
        result["tf_info"]["15m"] = {
            "bias": bias_15m,
            "last_high": structure_15m.get("last_high"),
            "last_low": structure_15m.get("last_low"),
        }
        
        if bias_15m == bias_1h:
            result["htf_confirmed"] = True
    
    # ─── 5M: Entry ───
    df_5m = get_klines(symbol, "5m", 100)
    if df_5m is not None:
        sh_5m, sl_5m = find_swing_points(df_5m, lookback=3)
        structure_5m = classify_structure(sh_5m, sl_5m)
        
        result["tf_info"]["5m"] = {
            "bias": structure_5m["bias"],
            "last_high": structure_5m.get("last_high"),
            "last_low": structure_5m.get("last_low"),
            "current_price": df_5m["close"].iloc[-1],
        }
        
        result["ltf_ready"] = True
    
    return result


def get_mtf_confirmation_text(mtf_data: Dict) -> str:
    """متن تأیید چند تایم فریمی برای سیگنال"""
    tf_info = mtf_data.get("tf_info", {})
    bias = mtf_data.get("bias", "")
    trade_style = mtf_data.get("trade_style", "SWING")
    
    lines = []
    
    # 4H یا 1H (بسته به استایل)
    htf_key = "4h" if trade_style == "SWING" else "1h"
    if htf_key in tf_info:
        htf = tf_info[htf_key]
        htf_bias = htf.get("bias", "")
        emoji = "🟢" if htf_bias == "BULLISH" else "🔴" if htf_bias == "BEARISH" else "⚪"
        lines.append(f"{htf_key.upper()}: {htf_bias} {emoji}")
    
    # 1H یا 15M
    mtf_key = "1h" if trade_style == "SWING" else "15m"
    if mtf_key in tf_info:
        mtf = tf_info[mtf_key]
        mtf_bias = mtf.get("bias", "")
        emoji = "🟢" if mtf_bias == "BULLISH" else "🔴" if mtf_bias == "BEARISH" else "⚪"
        lines.append(f"{mtf_key.upper()}: {mtf_bias} {emoji}")
    
    # 15M یا 5M
    ltf_key = "15m" if trade_style == "SWING" else "5m"
    if ltf_key in tf_info:
        ltf = tf_info[ltf_key]
        ltf_bias = ltf.get("bias", "")
        emoji = "🟢" if ltf_bias == "BULLISH" else "🔴" if ltf_bias == "BEARISH" else "⚪"
        lines.append(f"{ltf_key.upper()}: {ltf_bias} {emoji}")
    
    return " → ".join(lines) if lines else "نامشخص"


def get_mtf_bias_text(mtf_data: Dict) -> str:
    """متن بایاس برای نمایش در سیگنال"""
    bias = mtf_data.get("bias", "")
    confirmed = mtf_data.get("htf_confirmed", False)
    
    if not bias:
        return "❓ بدون بایاس"
    
    emoji = "🟢" if bias == "BULLISH" else "🔴"
    conf = "✅" if confirmed else "⚠️"
    
    return f"{bias} {emoji} {conf}"
