import pandas as pd
from datetime import datetime, time
from typing import Optional, List
from dataclasses import dataclass


# ICT Killzones (UTC)
KILLZONES = {
    "London": (time(7, 0), time(10, 0)),
    "NewYork": (time(13, 0), time(16, 0)),
    "Asian": (time(0, 0), time(3, 0)),
    "LondonClose": (time(15, 0), time(17, 0)),
}


@dataclass
class ICTSetup:
    type: str           # 'OTE', 'FVG_Entry', 'Breaker', 'Mitigation'
    direction: str
    entry_zone_top: float
    entry_zone_bottom: float
    killzone: Optional[str]
    pdl: Optional[float]    # Previous Day Low
    pdh: Optional[float]    # Previous Day High
    is_in_killzone: bool


def get_previous_day_levels(df_1d: pd.DataFrame) -> dict:
    """
    PDH/PDL: Previous Day High/Low
    این سطوح خیلی مهم هستن در ICT
    """
    if df_1d is None or len(df_1d) < 2:
        return {"pdh": None, "pdl": None, "pdm": None}
    
    prev_day = df_1d.iloc[-2]
    pdh = prev_day["high"]
    pdl = prev_day["low"]
    
    return {
        "pdh": pdh,
        "pdl": pdl,
        "pdm": (pdh + pdl) / 2   # Mid Point
    }


def get_weekly_levels(df_1d: pd.DataFrame) -> dict:
    """PWH/PWL: Previous Week High/Low"""
    if df_1d is None or len(df_1d) < 7:
        return {"pwh": None, "pwl": None}
    
    last_week = df_1d.iloc[-8:-1]
    return {
        "pwh": last_week["high"].max(),
        "pwl": last_week["low"].min()
    }


def is_in_killzone(timestamp: pd.Timestamp) -> Optional[str]:
    """چک میکنه آیا الان در Killzone هستیم"""
    current_time = timestamp.time()
    
    for zone_name, (start, end) in KILLZONES.items():
        if start <= current_time <= end:
            return zone_name
    
    return None


def calculate_ote(swing_high: float, swing_low: float, 
                   direction: str) -> dict:
    """
    OTE: Optimal Trade Entry
    فیبوناچی 62%-79% از یک swing
    
    Bullish OTE: pullback به 62-79% از Low به High
    Bearish OTE: pullback به 62-79% از High به Low
    """
    range_size = swing_high - swing_low
    
    if direction == "BULLISH":
        # Retracement از High به پایین
        ote_top = swing_high - range_size * 0.62
        ote_bottom = swing_high - range_size * 0.79
    else:
        # Retracement از Low به بالا
        ote_top = swing_low + range_size * 0.79
        ote_bottom = swing_low + range_size * 0.62
    
    return {
        "ote_top": ote_top,
        "ote_bottom": ote_bottom,
        "fib_62": swing_low + range_size * 0.382 if direction == "BULLISH" else swing_high - range_size * 0.382,
        "fib_705": swing_low + range_size * 0.295 if direction == "BULLISH" else swing_high - range_size * 0.295,
    }


def detect_mss(df: pd.DataFrame, direction: str) -> bool:
    """
    MSS: Market Structure Shift (LTF)
    تایید ورود در LTF
    
    Bullish MSS: شکست Higher High در LTF
    Bearish MSS: شکست Lower Low در LTF
    """
    if len(df) < 10:
        return False
    
    recent = df.tail(10)
    closes = recent["close"].values
    highs = recent["high"].values
    lows = recent["low"].values
    
    if direction == "BULLISH":
        # شکست آخرین High در LTF
        prev_high = max(highs[:-3])
        return closes[-1] > prev_high
    
    elif direction == "BEARISH":
        # شکست آخرین Low در LTF
        prev_low = min(lows[:-3])
        return closes[-1] < prev_low
    
    return False


def get_ict_signal(df_4h: pd.DataFrame, df_15m: pd.DataFrame,
                   df_1d: pd.DataFrame, htf_bias: str) -> Optional[dict]:
    """
    ICT Entry Signal:
    1. HTF Bias مشخص باشه
    2. PDH/PDL به عنوان target/magnet
    3. OTE در LTF
    4. ترجیحاً در Killzone
    5. MSS تایید کنه
    """
    if df_4h is None or df_15m is None:
        return None
    
    # سطوح مهم روز قبل
    pd_levels = get_previous_day_levels(df_1d)
    
    # آخرین کندل 15m
    last_candle = df_15m.iloc[-1]
    current_price = last_candle["close"]
    current_time = last_candle["timestamp"]
    
    # چک Killzone
    kz = is_in_killzone(current_time)
    
    # Swing های 4h برای OTE
    from analysis.structure import find_swing_points
    sh_4h, sl_4h = find_swing_points(df_4h, lookback=5)
    
    if not sh_4h or not sl_4h:
        return None
    
    last_high_4h = sh_4h[-1]["price"]
    last_low_4h = sl_4h[-1]["price"]
    
    # MSS در 15m
    mss = detect_mss(df_15m, htf_bias)
    
    if htf_bias == "BULLISH":
        ote = calculate_ote(last_high_4h, last_low_4h, "BULLISH")
        
        # قیمت در OTE Zone هست؟
        in_ote = ote["ote_bottom"] <= current_price <= ote["ote_top"]
        
        if in_ote and mss:
            return {
                "direction": "LONG",
                "entry_top": ote["ote_top"],
                "entry_bottom": ote["ote_bottom"],
                "killzone": kz,
                "is_in_killzone": kz is not None,
                "pdh": pd_levels["pdh"],
                "pdl": pd_levels["pdl"],
                "mss_confirmed": mss,
                "source": "ICT_OTE"
            }
    
    elif htf_bias == "BEARISH":
        ote = calculate_ote(last_high_4h, last_low_4h, "BEARISH")
        
        in_ote = ote["ote_bottom"] <= current_price <= ote["ote_top"]
        
        if in_ote and mss:
            return {
                "direction": "SHORT",
                "entry_top": ote["ote_top"],
                "entry_bottom": ote["ote_bottom"],
                "killzone": kz,
                "is_in_killzone": kz is not None,
                "pdh": pd_levels["pdh"],
                "pdl": pd_levels["pdl"],
                "mss_confirmed": mss,
                "source": "ICT_OTE"
            }
    
    return None
