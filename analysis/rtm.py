import pandas as pd
import numpy as np
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class RTMPattern:
    type: str       # 'RBR', 'DBD', 'RBD', 'DBR'
    cap_top: float
    cap_bottom: float
    base_top: float
    base_bottom: float
    strength: str   # 'STRONG', 'NORMAL', 'WEAK'
    is_fresh: bool  # تست نشده = بهتره


def detect_caps_and_base(df: pd.DataFrame, lookback: int = 50) -> dict:
    """
    RTM Concepts:
    
    CAP: کندل‌های با بدنه بزرگ (Engulfing یا Impulse)
    BASE: کندل‌های با بدنه کوچک (تجمیع، رنج)
    
    الگوها:
    RBR: Rally-Base-Rally (Bullish continuation)
    DBD: Drop-Base-Drop (Bearish continuation)
    RBD: Rally-Base-Drop (Bearish reversal - مهم!)
    DBR: Drop-Base-Rally (Bullish reversal - مهم!)
    """
    candles = df.tail(lookback).reset_index(drop=True)
    
    bodies = abs(candles["close"] - candles["open"])
    avg_body = bodies.mean()
    
    # CAP: بدنه بیشتر از 2 برابر میانگین
    # BASE: بدنه کمتر از 0.5 برابر میانگین
    
    patterns = []
    i = 0
    
    while i < len(candles) - 3:
        body = bodies.iloc[i]
        
        # پیدا کردن CAP اول
        if body > avg_body * 2:
            cap1_idx = i
            cap1_dir = "UP" if candles["close"].iloc[i] > candles["open"].iloc[i] else "DOWN"
            cap1_top = candles["high"].iloc[i]
            cap1_bottom = candles["low"].iloc[i]
            
            # پیدا کردن BASE بعدش
            base_start = i + 1
            base_end = base_start
            
            while base_end < len(candles) - 1:
                if bodies.iloc[base_end] > avg_body * 1.5:
                    break
                base_end += 1
            
            if base_end <= base_start:
                i += 1
                continue
            
            # محدوده BASE
            base_highs = candles["high"].iloc[base_start:base_end]
            base_lows = candles["low"].iloc[base_start:base_end]
            base_top = base_highs.max()
            base_bottom = base_lows.min()
            
            # CAP دوم
            if base_end < len(candles):
                cap2_body = bodies.iloc[base_end]
                cap2_dir = "UP" if candles["close"].iloc[base_end] > candles["open"].iloc[base_end] else "DOWN"
                
                if cap2_body > avg_body * 1.5:
                    # تعیین نوع الگو
                    if cap1_dir == "UP" and cap2_dir == "UP":
                        pattern_type = "RBR"
                    elif cap1_dir == "DOWN" and cap2_dir == "DOWN":
                        pattern_type = "DBD"
                    elif cap1_dir == "UP" and cap2_dir == "DOWN":
                        pattern_type = "RBD"
                    elif cap1_dir == "DOWN" and cap2_dir == "UP":
                        pattern_type = "DBR"
                    else:
                        i += 1
                        continue
                    
                    # تعیین قدرت
                    cap2_size = bodies.iloc[base_end]
                    if cap2_size > avg_body * 3:
                        strength = "STRONG"
                    elif cap2_size > avg_body * 2:
                        strength = "NORMAL"
                    else:
                        strength = "WEAK"
                    
                    # چک Fresh بودن
                    # آیا قیمت بعد از الگو به Base برگشته؟
                    future_data = candles.iloc[base_end+1:]
                    is_fresh = True
                    
                    if pattern_type in ["RBR", "DBR"]:
                        for _, row in future_data.iterrows():
                            if row["low"] <= base_top:
                                is_fresh = False
                                break
                    else:
                        for _, row in future_data.iterrows():
                            if row["high"] >= base_bottom:
                                is_fresh = False
                                break
                    
                    patterns.append(RTMPattern(
                        type=pattern_type,
                        cap_top=cap1_top,
                        cap_bottom=cap1_bottom,
                        base_top=base_top,
                        base_bottom=base_bottom,
                        strength=strength,
                        is_fresh=is_fresh
                    ))
                    
                    i = base_end + 1
                    continue
        
        i += 1
    
    return patterns


def is_price_at_rtm_base(current_price: float, 
                          pattern: RTMPattern,
                          buffer_pct: float = 0.002) -> bool:
    """
    چک میکنه قیمت در ناحیه Base الگوی RTM هست یا نه
    buffer: کمی بالا/پایین‌تر از Base هم قبول میکنه
    """
    buffer = current_price * buffer_pct
    return (pattern.base_bottom - buffer) <= current_price <= (pattern.base_top + buffer)


def get_rtm_signal(df: pd.DataFrame, 
                   htf_bias: str) -> Optional[dict]:
    """
    سیگنال RTM بر اساس بایاس HTF
    
    اگر HTF Bullish باشه: دنبال DBR یا RBR میگردیم
    اگر HTF Bearish باشه: دنبال RBD یا DBD میگردیم
    """
    patterns = detect_caps_and_base(df)
    current_price = df["close"].iloc[-1]
    
    if not patterns:
        return None
    
    for pattern in reversed(patterns):  # آخرین الگو مهم‌تره
        # فقط Fresh الگوها
        if not pattern.is_fresh:
            continue
        
        # تطبیق با bias
        if htf_bias == "BULLISH" and pattern.type in ["DBR", "RBR"]:
            if is_price_at_rtm_base(current_price, pattern):
                return {
                    "pattern": pattern.type,
                    "base_top": pattern.base_top,
                    "base_bottom": pattern.base_bottom,
                    "strength": pattern.strength,
                    "direction": "LONG",
                    "source": "RTM"
                }
        
        elif htf_bias == "BEARISH" and pattern.type in ["RBD", "DBD"]:
            if is_price_at_rtm_base(current_price, pattern):
                return {
                    "pattern": pattern.type,
                    "base_top": pattern.base_top,
                    "base_bottom": pattern.base_bottom,
                    "strength": pattern.strength,
                    "direction": "SHORT",
                    "source": "RTM"
                }
    
    return None
