import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional

@dataclass
class SwingPoint:
    index: int
    price: float
    type: str      # 'HH', 'HL', 'LH', 'LL'
    timestamp: pd.Timestamp

@dataclass
class StructureBreak:
    type: str           # 'BOS' یا 'CHoCH'
    direction: str      # 'BULLISH' یا 'BEARISH'
    level: float        # قیمت شکسته شده
    candle_index: int
    timestamp: pd.Timestamp


def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> Tuple[List, List]:
    """
    Swing High و Swing Low واقعی پیدا میکنه
    lookback: تعداد کندل چپ و راست برای تایید
    """
    swing_highs = []
    swing_lows = []
    
    highs = df["high"].values
    lows = df["low"].values
    
    for i in range(lookback, len(df) - lookback):
        # Swing High: بالاترین نقطه در پنجره
        if highs[i] == max(highs[i - lookback: i + lookback + 1]):
            swing_highs.append({
                "index": i,
                "price": highs[i],
                "timestamp": df["timestamp"].iloc[i]
            })
        
        # Swing Low: پایین‌ترین نقطه در پنجره
        if lows[i] == min(lows[i - lookback: i + lookback + 1]):
            swing_lows.append({
                "index": i,
                "price": lows[i],
                "timestamp": df["timestamp"].iloc[i]
            })
    
    return swing_highs, swing_lows


def classify_structure(swing_highs: List, swing_lows: List) -> dict:
    """
    ساختار رو طبقه‌بندی میکنه:
    HH/HL = Bullish
    LH/LL = Bearish
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {"bias": None, "last_high": None, "last_low": None}
    
    # آخرین دو سوئینگ های
    h1 = swing_highs[-2]["price"]
    h2 = swing_highs[-1]["price"]
    
    # آخرین دو سوئینگ لو
    l1 = swing_lows[-2]["price"]
    l2 = swing_lows[-1]["price"]
    
    hh = h2 > h1   # Higher High
    hl = l2 > l1   # Higher Low
    lh = h2 < h1   # Lower High
    ll = l2 < l1   # Lower Low
    
    if hh and hl:
        bias = "BULLISH"
    elif lh and ll:
        bias = "BEARISH"
    elif hh and ll:
        bias = "NEUTRAL_EXPANSION"
    else:
        bias = "NEUTRAL"
    
    return {
        "bias": bias,
        "last_high": swing_highs[-1],
        "last_low": swing_lows[-1],
        "prev_high": swing_highs[-2],
        "prev_low": swing_lows[-2],
        "hh": hh, "hl": hl, "lh": lh, "ll": ll
    }


def detect_bos_choch(df: pd.DataFrame, swing_highs: List, 
                      swing_lows: List) -> Optional[StructureBreak]:
    """
    BOS: Break of Structure - ادامه ترند
    CHoCH: Change of Character - تغییر جهت (مهم‌تر!)
    
    منطق:
    - در ترند صعودی، شکست Low = CHoCH (تغییر جهت به نزولی)
    - در ترند نزولی، شکست High = CHoCH (تغییر جهت به صعودی)
    - شکست در جهت ترند = BOS
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None
    
    structure = classify_structure(swing_highs, swing_lows)
    current_bias = structure["bias"]
    
    closes = df["close"].values
    current_close = closes[-1]
    
    # آخرین سوئینگ‌های مهم
    last_high = swing_highs[-1]["price"]
    last_low = swing_lows[-1]["price"]
    prev_high = swing_highs[-2]["price"]
    prev_low = swing_lows[-2]["price"]
    
    # در ترند صعودی
    if current_bias == "BULLISH":
        # BOS: شکست بالای High قبلی (ادامه)
        if current_close > last_high:
            return StructureBreak(
                type="BOS",
                direction="BULLISH",
                level=last_high,
                candle_index=len(df)-1,
                timestamp=df["timestamp"].iloc[-1]
            )
        # CHoCH: شکست زیر Low قبلی (تغییر جهت به نزولی)
        if current_close < prev_low:
            return StructureBreak(
                type="CHoCH",
                direction="BEARISH",
                level=prev_low,
                candle_index=len(df)-1,
                timestamp=df["timestamp"].iloc[-1]
            )
    
    # در ترند نزولی
    elif current_bias == "BEARISH":
        # BOS: شکست زیر Low قبلی (ادامه)
        if current_close < last_low:
            return StructureBreak(
                type="BOS",
                direction="BEARISH",
                level=last_low,
                candle_index=len(df)-1,
                timestamp=df["timestamp"].iloc[-1]
            )
        # CHoCH: شکست بالای High قبلی (تغییر جهت به صعودی)
        if current_close > prev_high:
            return StructureBreak(
                type="CHoCH",
                direction="BULLISH",
                level=prev_high,
                candle_index=len(df)-1,
                timestamp=df["timestamp"].iloc[-1]
            )
    
    return None
