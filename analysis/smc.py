import pandas as pd
import numpy as np
from typing import Optional, List, dict
from dataclasses import dataclass


@dataclass  
class OrderBlock:
    type: str           # 'BULLISH' یا 'BEARISH'
    top: float
    bottom: float
    origin_index: int
    is_mitigated: bool = False
    strength: float = 0.0   # قدرت OB (بر اساس impulse بعدی)


@dataclass
class FairValueGap:
    type: str       # 'BULLISH' یا 'BEARISH'  
    top: float
    bottom: float
    index: int
    is_filled: bool = False


def find_order_blocks(df: pd.DataFrame, direction: str, 
                       lookback: int = 30) -> List[OrderBlock]:
    """
    Order Block واقعی:
    
    Bullish OB: آخرین کندل نزولی قبل از یک حرکت صعودی قوی
    Bearish OB: آخرین کندل صعودی قبل از یک حرکت نزولی قوی
    
    شرط impulse: کندل بعدی باید بدنه بزرگ داشته باشه
    """
    order_blocks = []
    candles = df.tail(lookback).reset_index(drop=True)
    
    for i in range(1, len(candles) - 2):
        o = candles["open"].iloc[i]
        h = candles["high"].iloc[i]
        l = candles["low"].iloc[i]
        c = candles["close"].iloc[i]
        
        # بدنه کندل بعدی (impulse candle)
        next_body = abs(candles["close"].iloc[i+1] - candles["open"].iloc[i+1])
        avg_body = abs(df["close"] - df["open"]).mean()
        
        # impulse باید بزرگ‌تر از میانگین باشه
        is_impulse = next_body > avg_body * 1.5
        
        if direction == "BULLISH":
            # کندل نزولی + impulse صعودی بعدش
            is_bearish_candle = c < o
            next_is_bullish = candles["close"].iloc[i+1] > candles["open"].iloc[i+1]
            
            if is_bearish_candle and next_is_bullish and is_impulse:
                # چک کن mitigate نشده باشه
                ob_top = max(o, c)
                ob_bottom = min(o, c)
                
                # آیا قیمت بعداً به این ناحیه برگشته؟
                future_lows = candles["low"].iloc[i+2:].values
                is_mitigated = any(low <= ob_top for low in future_lows)
                
                strength = next_body / avg_body
                
                order_blocks.append(OrderBlock(
                    type="BULLISH",
                    top=ob_top,
                    bottom=ob_bottom,
                    origin_index=i,
                    is_mitigated=is_mitigated,
                    strength=strength
                ))
        
        elif direction == "BEARISH":
            # کندل صعودی + impulse نزولی بعدش
            is_bullish_candle = c > o
            next_is_bearish = candles["close"].iloc[i+1] < candles["open"].iloc[i+1]
            
            if is_bullish_candle and next_is_bearish and is_impulse:
                ob_top = max(o, c)
                ob_bottom = min(o, c)
                
                future_highs = candles["high"].iloc[i+2:].values
                is_mitigated = any(high >= ob_bottom for high in future_highs)
                
                strength = next_body / avg_body
                
                order_blocks.append(OrderBlock(
                    type="BEARISH",
                    top=ob_top,
                    bottom=ob_bottom,
                    origin_index=i,
                    is_mitigated=is_mitigated,
                    strength=strength
                ))
    
    # فقط OBهای mitigate نشده برگردون، قوی‌ترین اول
    valid_obs = [ob for ob in order_blocks if not ob.is_mitigated]
    valid_obs.sort(key=lambda x: x.strength, reverse=True)
    
    return valid_obs


def find_fvg(df: pd.DataFrame, lookback: int = 50) -> List[FairValueGap]:
    """
    Fair Value Gap (Imbalance):
    سه کندل متوالی که بین کندل 1 و 3 گپ وجود داره
    
    Bullish FVG: Low کندل 3 > High کندل 1
    Bearish FVG: High کندل 3 < Low کندل 1
    """
    fvgs = []
    candles = df.tail(lookback).reset_index(drop=True)
    
    for i in range(len(candles) - 2):
        high_1 = candles["high"].iloc[i]
        low_1 = candles["low"].iloc[i]
        high_3 = candles["high"].iloc[i+2]
        low_3 = candles["low"].iloc[i+2]
        
        # Bullish FVG
        if low_3 > high_1:
            gap_size = low_3 - high_1
            # چک fill شدن
            future_lows = candles["low"].iloc[i+3:].values if i+3 < len(candles) else []
            is_filled = any(low <= low_3 for low in future_lows)
            
            fvgs.append(FairValueGap(
                type="BULLISH",
                top=low_3,
                bottom=high_1,
                index=i+1,
                is_filled=is_filled
            ))
        
        # Bearish FVG
        elif high_3 < low_1:
            future_highs = candles["high"].iloc[i+3:].values if i+3 < len(candles) else []
            is_filled = any(high >= high_3 for high in future_highs)
            
            fvgs.append(FairValueGap(
                type="BEARISH",
                top=low_1,
                bottom=high_3,
                index=i+1,
                is_filled=is_filled
            ))
    
    return [fvg for fvg in fvgs if not fvg.is_filled]


def detect_liquidity(df: pd.DataFrame, swing_highs: List, 
                      swing_lows: List) -> dict:
    """
    Liquidity Detection:
    - Equal Highs/Lows (BSL/SSL)
    - Stop Hunt تشخیص بده
    """
    current_high = df["high"].iloc[-1]
    current_low = df["low"].iloc[-1]
    current_close = df["close"].iloc[-1]
    
    result = {
        "sweep_type": None,
        "swept_level": None,
        "is_rejection": False
    }
    
    if len(swing_lows) >= 2:
        recent_lows = [sl["price"] for sl in swing_lows[-5:]]
        min_low = min(recent_lows)
        
        # قیمت پایین‌تر از Low رفت ولی بسته شد بالاتر = Sweep + Rejection
        if current_low < min_low and current_close > min_low:
            result["sweep_type"] = "SWEEP_LOW"
            result["swept_level"] = min_low
            result["is_rejection"] = True
    
    if len(swing_highs) >= 2:
        recent_highs = [sh["price"] for sh in swing_highs[-5:]]
        max_high = max(recent_highs)
        
        if current_high > max_high and current_close < max_high:
            result["sweep_type"] = "SWEEP_HIGH"
            result["swept_level"] = max_high
            result["is_rejection"] = True
    
    return result


def is_price_in_ob(current_price: float, ob: OrderBlock) -> bool:
    """چک میکنه قیمت در OB هست یا نه"""
    return ob.bottom <= current_price <= ob.top


def is_price_in_fvg(current_price: float, fvg: FairValueGap) -> bool:
    """چک میکنه قیمت در FVG هست یا نه"""
    return fvg.bottom <= current_price <= fvg.top
