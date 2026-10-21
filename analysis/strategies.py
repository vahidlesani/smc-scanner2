# analysis/strategies.py - استراتژی‌های جامع پرایس اکشن
# شامل: SMC, ICT, RTM, QM, Engulfing, PinBar, FVG, IFVG, FlipZone, etc.

import pandas as pd
import numpy as np
from typing import Optional, List, Dict
from dataclasses import dataclass, field


# ─────────────────────────────────────────────
# استراتژی‌های پایه
# ─────────────────────────────────────────────

@dataclass
class StrategySignal:
    """ساختار یکپارچه برای همه استراتژی‌ها"""
    strategy: str           # نام استراتژی (SMC, RTM, QM, etc.)
    strategy_fa: str        # نام فارسی
    direction: str          # LONG / SHORT
    entry: float
    sl: float
    tp1: float
    tp2: float
    zone_top: float = 0     # بالای ناحیه
    zone_bottom: float = 0  # پایین ناحیه
    strength: str = "NORMAL" # STRONG, NORMAL, WEAK
    confirmations: List[str] = field(default_factory=list)
    description: str = ""   # توضیحات آموزشی فارسی
    entry_conditions: List[str] = field(default_factory=list)
    score_bonus: int = 0    # امتیاز اضافی خاص استراتژی


# ─────────────────────────────────────────────
# ۱. Quasimodo (QM) - الگوی قوی بازگشتی
# ─────────────────────────────────────────────

def detect_quasimodo(df: pd.DataFrame, htf_bias: str,
                     lookback: int = 50) -> Optional[StrategySignal]:
    """
    Quasimodo (QM):
    الگوی بازگشتی قدرتمند که شامل:
    ۱. شکست سقف/کف قبلی (Sweep)
    ۲. برگشت سریع
    ۳. شکست ساختار (CHoCH)
    
    Bullish QM: LH → LL → Sweep Low → HH (شکست سقف قبلی)
    Bearish QM: HH → HL → Sweep High → LL (شکست کف قبلی)
    """
    if len(df) < lookback:
        return None
    
    candles = df.tail(lookback).reset_index(drop=True)
    highs = candles["high"].values
    lows = candles["low"].values
    closes = candles["close"].values
    
    # پیدا کردن swing points
    swing_highs = []
    swing_lows = []
    
    for i in range(3, len(candles) - 3):
        if highs[i] == max(highs[i-3:i+4]):
            swing_highs.append({"index": i, "price": highs[i]})
        if lows[i] == min(lows[i-3:i+4]):
            swing_lows.append({"index": i, "price": lows[i]})
    
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return None
    
    current_price = closes[-1]
    
    # Bearish QM: HH → HL → Sweep High → LL
    if htf_bias == "BEARISH":
        for i in range(len(swing_highs) - 2):
            h1 = swing_highs[i]
            h2 = swing_highs[i+1]
            l1 = swing_lows[i] if i < len(swing_lows) else None
            
            # شرط: HH (سقف بالاتر)
            if h2["price"] > h1["price"]:
                # شرط: قیمت سقف دوم رو زده ولی برگشته
                sweep_high = h2["price"]
                if (highs[h2["index"]+1:h2["index"]+5].max() > sweep_high and
                    closes[h2["index"]+4] < sweep_high):
                    
                    # پیدا کردن کف بین دو سقف
                    between_lows = [l for l in swing_lows 
                                   if h1["index"] < l["index"] < h2["index"]]
                    if between_lows:
                        base_low = min(l["price"] for l in between_lows)
                        
                        # ورود: بعد از شکست کف
                        entry_zone_top = sweep_high * 0.998
                        entry_zone_bottom = base_low * 1.002
                        
                        if entry_zone_bottom <= current_price <= entry_zone_top:
                            sl = sweep_high * 1.002
                            sl_dist = abs(current_price - sl)
                            
                            return StrategySignal(
                                strategy="QM",
                                strategy_fa="کوآزیمودو",
                                direction="SHORT",
                                entry=current_price,
                                sl=sl,
                                tp1=current_price - sl_dist * 2,
                                tp2=current_price - sl_dist * 3,
                                zone_top=entry_zone_top,
                                zone_bottom=entry_zone_bottom,
                                strength="STRONG",
                                confirmations=[
                                    "✅ سقف بالاتر (HH) شکل گرفته",
                                    "✅ Sweep High رخ داده",
                                    "✅ قیمت برگشته و در حال شکست کف"
                                ],
                                description=(
                                    "الگوی کوآزیمودو (QM) شناسایی شد. "
                                    "این الگو نشان می‌دهد بازار ابتدا یک سقف بالاتر "
                                    "ساخته، سپس نقدینگی بالای آن را جمع‌آوری کرده "
                                    "(Sweep) و حالا در حال برگشت قوی به سمت پایین است. "
                                    "این یکی از قوی‌ترین الگوهای بازگشتی در پرایس اکشن است."
                                ),
                                entry_conditions=[
                                    "等待 شکست کف محلی",
                                    "مشاهده کندل تاییدیه فروش",
                                    "ترجیحاً در ساعات لندن یا نیویورک"
                                ],
                                score_bonus=2
                            )
    
    # Bullish QM: LL → HL → Sweep Low → HH
    elif htf_bias == "BULLISH":
        for i in range(len(swing_lows) - 2):
            l1 = swing_lows[i]
            l2 = swing_lows[i+1]
            
            # شرط: LL (کف پایین‌تر)
            if l2["price"] < l1["price"]:
                # شرط: قیمت کف دوم رو زده ولی برگشته
                sweep_low = l2["price"]
                if (lows[l2["index"]+1:l2["index"]+5].min() < sweep_low and
                    closes[l2["index"]+4] > sweep_low):
                    
                    # پیدا کردن سقف بین دو کف
                    between_highs = [h for h in swing_highs 
                                    if l1["index"] < h["index"] < l2["index"]]
                    if between_highs:
                        base_high = max(h["price"] for h in between_highs)
                        
                        entry_zone_top = base_high * 0.998
                        entry_zone_bottom = sweep_low * 1.002
                        
                        if entry_zone_bottom <= current_price <= entry_zone_top:
                            sl = sweep_low * 0.998
                            sl_dist = abs(current_price - sl)
                            
                            return StrategySignal(
                                strategy="QM",
                                strategy_fa="کوآزیمودو",
                                direction="LONG",
                                entry=current_price,
                                sl=sl,
                                tp1=current_price + sl_dist * 2,
                                tp2=current_price + sl_dist * 3,
                                zone_top=entry_zone_top,
                                zone_bottom=entry_zone_bottom,
                                strength="STRONG",
                                confirmations=[
                                    "✅ کف پایین‌تر (LL) شکل گرفته",
                                    "✅ Sweep Low رخ داده",
                                    "✅ قیمت برگشته و در حال شکست سقف"
                                ],
                                description=(
                                    "الگوی کوآزیمودو (QM) شناسایی شد. "
                                    "این الگو نشان می‌دهد بازار ابتدا یک کف پایین‌تر "
                                    "ساخته، سپس نقدینگی پایین آن را جمع‌آوری کرده "
                                    "(Sweep) و حالا در حال برگشت قوی به سمت بالا است. "
                                    "این یکی از قوی‌ترین الگوهای بازگشتی در پرایس اکشن است."
                                ),
                                entry_conditions=[
                                    "等待 شکست سقف محلی",
                                    "مشاهده کندل تاییدیه خرید",
                                    "ترجیحاً در ساعات لندن یا نیویورک"
                                ],
                                score_bonus=2
                            )
    
    return None


# ─────────────────────────────────────────────
# ۲. Engulfing - کندل پوششی
# ─────────────────────────────────────────────

def detect_engulfing(df: pd.DataFrame, htf_bias: str,
                     lookback: int = 30) -> Optional[StrategySignal]:
    """
    Engulfing Pattern:
    کندل پوششی صعودی: کندل فعلی کل کندل قبلی رو پوشش میده
    کندل پوششی نزولی: کندل فعلی کل کندل قبلی رو پوشش میده
    
    مهم: باید در ناحیه حمایت/مقاومت باشه
    """
    if len(df) < lookback:
        return None
    
    candles = df.tail(lookback).reset_index(drop=True)
    current = candles.iloc[-1]
    prev = candles.iloc[-2]
    
    current_body_top = max(current["open"], current["close"])
    current_body_bottom = min(current["open"], current["close"])
    prev_body_top = max(prev["open"], prev["close"])
    prev_body_bottom = min(prev["open"], prev["close"])
    
    current_body = abs(current["close"] - current["open"])
    prev_body = abs(prev["close"] - prev["open"])
    avg_body = abs(candles["close"] - candles["open"]).mean()
    
    # Bullish Engulfing
    if (htf_bias == "BULLISH" and
        prev["close"] < prev["open"] and  # کندل قبلی نزولی
        current["close"] > current["open"] and  # کندل فعلی صعودی
        current_body_top > prev_body_top and  # سقف بالاتر
        current_body_bottom < prev_body_bottom and  # کف پایین‌تر
        current_body > prev_body * 1.2):  # بدنه بزرگتر
        
        sl = min(current["low"], prev["low"]) * 0.998
        sl_dist = abs(current["close"] - sl)
        
        return StrategySignal(
            strategy="ENGULFING",
            strategy_fa="کندل پوششی",
            direction="LONG",
            entry=current["close"],
            sl=sl,
            tp1=current["close"] + sl_dist * 2,
            tp2=current["close"] + sl_dist * 3,
            zone_top=current_body_top,
            zone_bottom=current_body_bottom,
            strength="STRONG" if current_body > avg_body * 2 else "NORMAL",
            confirmations=[
                "✅ کندل پوششی صعودی",
                f"✅ بدنه {current_body/avg_body:.1f}x بزرگتر از میانگین",
                "✅ در جهت روند اصلی"
            ],
            description=(
                "الگوی کندل پوششی صعودی (Bullish Engulfing) شناسایی شد. "
                "این الگو زمانی تشکیل می‌شود که یک کندل صعودی بزرگ، "
                "کل کندل نزولی قبلی را پوشش دهد. این نشان‌دهنده "
                "قدرت خریداران و احتمال ادامه حرکت صعودی است."
            ),
            entry_conditions=[
                "بسته شدن کندل پوششی",
                "ترجیحاً در ناحیه حمایتی",
                "تأیید با حجم معاملات"
            ],
            score_bonus=1
        )
    
    # Bearish Engulfing
    elif (htf_bias == "BEARISH" and
          prev["close"] > prev["open"] and  # کندل قبلی صعودی
          current["close"] < current["open"] and  # کندل فعلی نزولی
          current_body_top > prev_body_top and
          current_body_bottom < prev_body_bottom and
          current_body > prev_body * 1.2):
        
        sl = max(current["high"], prev["high"]) * 1.002
        sl_dist = abs(current["close"] - sl)
        
        return StrategySignal(
            strategy="ENGULFING",
            strategy_fa="کندل پوششی",
            direction="SHORT",
            entry=current["close"],
            sl=sl,
            tp1=current["close"] - sl_dist * 2,
            tp2=current["close"] - sl_dist * 3,
            zone_top=current_body_top,
            zone_bottom=current_body_bottom,
            strength="STRONG" if current_body > avg_body * 2 else "NORMAL",
            confirmations=[
                "✅ کندل پوششی نزولی",
                f"✅ بدنه {current_body/avg_body:.1f}x بزرگتر از میانگین",
                "✅ در جهت روند اصلی"
            ],
            description=(
                "الگوی کندل پوششی نزولی (Bearish Engulfing) شناسایی شد. "
                "این الگو زمانی تشکیل می‌شود که یک کندل نزولی بزرگ، "
                "کل کندل صعودی قبلی را پوشش دهد. این نشان‌دهنده "
                "قدرت فروشندگان و احتمال ادامه حرکت نزولی است."
            ),
            entry_conditions=[
                "بسته شدن کندل پوششی",
                "ترجیحاً در ناحیه مقاومتی",
                "تأیید با حجم معاملات"
            ],
            score_bonus=1
        )
    
    return None


# ─────────────────────────────────────────────
# ۳. Pin Bar / K-Bar - کندل‌های بازگشتی
# ─────────────────────────────────────────────

def detect_pinbar(df: pd.DataFrame, htf_bias: str,
                  lookback: int = 30) -> Optional[StrategySignal]:
    """
    Pin Bar:
    کندلی با سایه بلند و بدنه کوچک
    نشان‌دهنده رد قیمت توسط بازار
    
    Bullish Pin Bar: سایه بلند پایین (چکش)
    Bearish Pin Bar: سایه بلند بالا (ستاره دنباله‌دار)
    """
    if len(df) < lookback:
        return None
    
    candles = df.tail(lookback).reset_index(drop=True)
    current = candles.iloc[-1]
    
    high = current["high"]
    low = current["low"]
    open_p = current["open"]
    close = current["close"]
    
    body_top = max(open_p, close)
    body_bottom = min(open_p, close)
    body_size = abs(close - open_p)
    total_range = high - low
    
    if total_range == 0:
        return None
    
    upper_shadow = high - body_top
    lower_shadow = body_bottom - low
    
    body_ratio = body_size / total_range
    avg_body = abs(candles["close"] - candles["open"]).mean()
    
    # Bullish Pin Bar (Hammer)
    if (htf_bias == "BULLISH" and
        lower_shadow > total_range * 0.6 and  # سایه پایین بلند
        upper_shadow < total_range * 0.15 and  # سایه بالا کوتاه
        body_ratio < 0.3):  # بدنه کوچک
        
        sl = low * 0.998
        sl_dist = abs(close - sl)
        
        return StrategySignal(
            strategy="PINBAR",
            strategy_fa="پین بار",
            direction="LONG",
            entry=close,
            sl=sl,
            tp1=close + sl_dist * 2,
            tp2=close + sl_dist * 3,
            zone_top=body_top,
            zone_bottom=low,
            strength="STRONG" if lower_shadow > total_range * 0.7 else "NORMAL",
            confirmations=[
                "✅ پین بار صعودی (چکش)",
                f"✅ سایه پایین {lower_shadow/total_range*100:.0f}% کل کندل",
                "✅ رد قیمت توسط بازار"
            ],
            description=(
                "الگوی پین بار صعودی (Bullish Pin Bar / Hammer) شناسایی شد. "
                "این کندل با سایه بلند پایین نشان می‌دهد فروشندگان قیمت را "
                "پایین برده‌اند اما خریداران قوی‌تر بوده و قیمت را برگردانده‌اند. "
                "این یک سیگنال بازگشتی قوی است."
            ),
            entry_conditions=[
                "بسته شدن کندل",
                "ترجیحاً در ناحیه حمایتی",
                "تأیید کندل بعدی"
            ],
            score_bonus=1
        )
    
    # Bearish Pin Bar (Shooting Star)
    elif (htf_bias == "BEARISH" and
          upper_shadow > total_range * 0.6 and
          lower_shadow < total_range * 0.15 and
          body_ratio < 0.3):
        
        sl = high * 1.002
        sl_dist = abs(close - sl)
        
        return StrategySignal(
            strategy="PINBAR",
            strategy_fa="پین بار",
            direction="SHORT",
            entry=close,
            sl=sl,
            tp1=close - sl_dist * 2,
            tp2=close - sl_dist * 3,
            zone_top=high,
            zone_bottom=body_bottom,
            strength="STRONG" if upper_shadow > total_range * 0.7 else "NORMAL",
            confirmations=[
                "✅ پین بار نزولی (ستاره دنباله‌دار)",
                f"✅ سایه بالا {upper_shadow/total_range*100:.0f}% کل کندل",
                "✅ رد قیمت توسط بازار"
            ],
            description=(
                "الگوی پین بار نزولی (Bearish Pin Bar / Shooting Star) شناسایی شد. "
                "این کندل با سایه بلند بالا نشان می‌دهد خریداران قیمت را بالا برده‌اند "
                "اما فروشندگان قوی‌تر بوده و قیمت را برگردانده‌اند. "
                "این یک سیگنال بازگشتی قوی است."
            ),
            entry_conditions=[
                "بسته شدن کندل",
                "ترجیحاً در ناحیه مقاومتی",
                "تأیید کندل بعدی"
            ],
            score_bonus=1
        )
    
    return None


# ─────────────────────────────────────────────
# ۴. FVG (Fair Value Gap) - شکاف قیمتی
# ─────────────────────────────────────────────

def detect_fvg_signal(df: pd.DataFrame, htf_bias: str,
                      lookback: int = 50) -> Optional[StrategySignal]:
    """
    Fair Value Gap (FVG):
    شکاف قیمتی بین سه کندل متوالی
    وقتی high کندل اول از low کندل سوم پایین‌تر باشه = Bullish FVG
    وقتی low کندل اول از high کندل سوم بالاتر باشه = Bearish FVG
    
    قیمت تمایل داره این شکاف‌ها رو پر کنه
    """
    if len(df) < lookback:
        return None
    
    candles = df.tail(lookback).reset_index(drop=True)
    current_price = candles["close"].iloc[-1]
    
    fvgs = []
    
    for i in range(len(candles) - 2):
        c1_high = candles["high"].iloc[i]
        c1_low = candles["low"].iloc[i]
        c3_high = candles["high"].iloc[i+2]
        c3_low = candles["low"].iloc[i+2]
        
        # Bullish FVG: gap up
        if c3_low > c1_high:
            gap_top = c3_low
            gap_bottom = c1_high
            fvgs.append({
                "type": "BULLISH",
                "top": gap_top,
                "bottom": gap_bottom,
                "index": i+1
            })
        
        # Bearish FVG: gap down
        elif c1_low > c3_high:
            gap_top = c1_low
            gap_bottom = c3_high
            fvgs.append({
                "type": "BEARISH",
                "top": gap_top,
                "bottom": gap_bottom,
                "index": i+1
            })
    
    # پیدا کردن FVG‌های پر نشده
    for fvg in reversed(fvgs):
        # چک کن آیا قیمت در ناحیه FVG هست
        if fvg["bottom"] <= current_price <= fvg["top"]:
            gap_size = fvg["top"] - fvg["bottom"]
            
            if fvg["type"] == "BULLISH" and htf_bias == "BULLISH":
                sl = fvg["bottom"] * 0.998
                sl_dist = abs(current_price - sl)
                
                return StrategySignal(
                    strategy="FVG",
                    strategy_fa="شکاف قیمتی (FVG)",
                    direction="LONG",
                    entry=current_price,
                    sl=sl,
                    tp1=current_price + sl_dist * 2,
                    tp2=current_price + sl_dist * 3,
                    zone_top=fvg["top"],
                    zone_bottom=fvg["bottom"],
                    strength="STRONG" if gap_size > current_price * 0.005 else "NORMAL",
                    confirmations=[
                        "✅ FVG صعودی شناسایی شد",
                        "✅ قیمت در ناحیه شکاف",
                        "✅ هم‌راستا با روند اصلی"
                    ],
                    description=(
                        "شکاف قیمتی صعودی (Bullish FVG) شناسایی شد. "
                        "این شکاف زمانی ایجاد می‌شود که بازار با قدرت حرکت کرده "
                        "و قیمت نتوانسته تعادل پیدا کند. بازار تمایل دارد "
                        "این شکاف‌ها را پر کند، که فرصت ورود خوبی فراهم می‌کند."
                    ),
                    entry_conditions=[
                        "等待 قیمت به ناحیه FVG برگردد",
                        "مشاهده کندل تأییدیه",
                        "بسته شدن بالای ناحیه FVG"
                    ],
                    score_bonus=1
                )
            
            elif fvg["type"] == "BEARISH" and htf_bias == "BEARISH":
                sl = fvg["top"] * 1.002
                sl_dist = abs(current_price - sl)
                
                return StrategySignal(
                    strategy="FVG",
                    strategy_fa="شکاف قیمتی (FVG)",
                    direction="SHORT",
                    entry=current_price,
                    sl=sl,
                    tp1=current_price - sl_dist * 2,
                    tp2=current_price - sl_dist * 3,
                    zone_top=fvg["top"],
                    zone_bottom=fvg["bottom"],
                    strength="STRONG" if gap_size > current_price * 0.005 else "NORMAL",
                    confirmations=[
                        "✅ FVG نزولی شناسایی شد",
                        "✅ قیمت در ناحیه شکاف",
                        "✅ هم‌راستا با روند اصلی"
                    ],
                    description=(
                        "شکاف قیمتی نزولی (Bearish FVG) شناسایی شد. "
                        "این شکاف زمانی ایجاد می‌شود که بازار با قدرت نزول کرده "
                        "و قیمت نتوانسته تعادل پیدا کند. بازار تمایل دارد "
                        "این شکاف‌ها را پر کند، که فرصت ورود خوبی فراهم می‌کند."
                    ),
                    entry_conditions=[
                        "等待 قیمت به ناحیه FVG برگردد",
                        "مشاهده کندل تأییدیه",
                        "بسته شدن زیر ناحیه FVG"
                    ],
                    score_bonus=1
                )
    
    return None


# ─────────────────────────────────────────────
# ۵. IFVG (Inverse Fair Value Gap)
# ─────────────────────────────────────────────

def detect_ifvg_signal(df: pd.DataFrame, htf_bias: str,
                       lookback: int = 50) -> Optional[StrategySignal]:
    """
    Inverse FVG:
    وقتی FVG پر بشه و قیمت از اون رد بشه، تبدیل به حمایت/مقاومت میشه
    
    Bullish IFVG: FVG نزولی پر شده و قیمت بالای اون برگشته
    Bearish IFVG: FVG صعودی پر شده و قیمت زیر اون برگشته
    """
    if len(df) < lookback:
        return None
    
    candles = df.tail(lookback).reset_index(drop=True)
    current_price = candles["close"].iloc[-1]
    
    # پیدا کردن FVG‌های قدیمی که پر شدن
    for i in range(len(candles) - 10):
        c1_high = candles["high"].iloc[i]
        c1_low = candles["low"].iloc[i]
        c3_high = candles["high"].iloc[i+2]
        c3_low = candles["low"].iloc[i+2]
        
        # Bullish FVG قدیمی
        if c3_low > c1_high:
            fvg_top = c3_low
            fvg_bottom = c1_high
            
            # چک کن آیا پر شده
            filled = False
            for j in range(i+3, len(candles)):
                if candles["low"].iloc[j] <= fvg_bottom:
                    filled = True
                    break
            
            if filled:
                # حالا چک کن قیمت بالای FVG برگشته
                if current_price > fvg_top and htf_bias == "BULLISH":
                    sl = fvg_bottom * 0.998
                    sl_dist = abs(current_price - sl)
                    
                    return StrategySignal(
                        strategy="IFVG",
                        strategy_fa="معکوس شکاف قیمتی",
                        direction="LONG",
                        entry=current_price,
                        sl=sl,
                        tp1=current_price + sl_dist * 2,
                        tp2=current_price + sl_dist * 3,
                        zone_top=fvg_top,
                        zone_bottom=fvg_bottom,
                        strength="STRONG",
                        confirmations=[
                            "✅ IFVG صعودی شناسایی شد",
                            "✅ FVG قبلی پر شده",
                            "✅ قیمت بالای ناحیه برگشته"
                        ],
                        description=(
                            "معکوس شکاف قیمتی صعودی (Bullish IFVG) شناسایی شد. "
                            "یک شکاف قیمتی نزولی قبلی پر شده و قیمت بالای آن "
                            "برگشته است. این نشان می‌دهد ناحیه قبلی حالا "
                            "به حمایت تبدیل شده و فرصت خرید خوبی است."
                        ),
                        entry_conditions=[
                            "بسته شدن قیمت بالای ناحیه IFVG",
                            "مشاهده کندل تأییدیه صعودی",
                            "ترجیحاً در ناحیه حمایتی"
                        ],
                        score_bonus=2
                    )
        
        # Bearish FVG قدیمی
        elif c1_low > c3_high:
            fvg_top = c1_low
            fvg_bottom = c3_high
            
            filled = False
            for j in range(i+3, len(candles)):
                if candles["high"].iloc[j] >= fvg_top:
                    filled = True
                    break
            
            if filled:
                if current_price < fvg_bottom and htf_bias == "BEARISH":
                    sl = fvg_top * 1.002
                    sl_dist = abs(current_price - sl)
                    
                    return StrategySignal(
                        strategy="IFVG",
                        strategy_fa="معکوس شکاف قیمتی",
                        direction="SHORT",
                        entry=current_price,
                        sl=sl,
                        tp1=current_price - sl_dist * 2,
                        tp2=current_price - sl_dist * 3,
                        zone_top=fvg_top,
                        zone_bottom=fvg_bottom,
                        strength="STRONG",
                        confirmations=[
                            "✅ IFVG نزولی شناسایی شد",
                            "✅ FVG قبلی پر شده",
                            "✅ قیمت زیر ناحیه برگشته"
                        ],
                        description=(
                            "معکوس شکاف قیمتی نزولی (Bearish IFVG) شناسایی شد. "
                            "یک شکاف قیمتی صعودی قبلی پر شده و قیمت زیر آن "
                            "برگشته است. این نشان می‌دهد ناحیه قبلی حالا "
                            "به مقاومت تبدیل شده و فرصت فروش خوبی است."
                        ),
                        entry_conditions=[
                            "بسته شدن قیمت زیر ناحیه IFVG",
                            "مشاهده کندل تأییدیه نزولی",
                            "ترجیحاً در ناحیه مقاومتی"
                        ],
                        score_bonus=2
                    )
    
    return None


# ─────────────────────────────────────────────
# ۶. Flip Zone - تبدیل حمایت به مقاومت و بالعکس
# ─────────────────────────────────────────────

def detect_flipzone(df: pd.DataFrame, htf_bias: str,
                    lookback: int = 50) -> Optional[StrategySignal]:
    """
    Flip Zone:
    وقتی یک سطح حمایت شکسته بشه، تبدیل به مقاومت میشه
    و بالعکس
    
    Bullish Flip: مقاومت شکسته → حمایت جدید
    Bearish Flip: حمایت شکسته → مقاومت جدید
    """
    if len(df) < lookback:
        return None
    
    candles = df.tail(lookback).reset_index(drop=True)
    current_price = candles["close"].iloc[-1]
    
    # پیدا کردن سطوح مهم
    swing_highs = []
    swing_lows = []
    
    for i in range(2, len(candles) - 2):
        if candles["high"].iloc[i] == max(candles["high"].iloc[i-2:i+3]):
            swing_highs.append({"index": i, "price": candles["high"].iloc[i]})
        if candles["low"].iloc[i] == min(candles["low"].iloc[i-2:i+3]):
            swing_lows.append({"index": i, "price": candles["low"].iloc[i]})
    
    # Bullish Flip: مقاومت قبلی → حمایت فعلی
    if htf_bias == "BULLISH":
        for sh in swing_highs[:-1]:
            resistance = sh["price"]
            # شکست مقاومت
            broken = False
            for j in range(sh["index"]+1, len(candles)):
                if candles["close"].iloc[j] > resistance:
                    broken = True
                    break
            
            if broken:
                # قیمت برگشته به تست مقاومت شکسته شده
                if (abs(current_price - resistance) / resistance < 0.01 and
                    current_price >= resistance * 0.99):
                    
                    sl = resistance * 0.995
                    sl_dist = abs(current_price - sl)
                    
                    return StrategySignal(
                        strategy="FLIPZONE",
                        strategy_fa="فیلیپ زون",
                        direction="LONG",
                        entry=current_price,
                        sl=sl,
                        tp1=current_price + sl_dist * 2,
                        tp2=current_price + sl_dist * 3,
                        zone_top=resistance * 1.002,
                        zone_bottom=resistance * 0.998,
                        strength="STRONG",
                        confirmations=[
                            "✅ مقاومت قبلی شکسته شده",
                            "✅ قیمت در حال تست سطح شکسته",
                            "✅ تبدیل مقاومت به حمایت"
                        ],
                        description=(
                            "فیلیپ زون صعودی شناسایی شد. "
                            "یک سطح مقاومت قبلی شکسته شده و حالا قیمت "
                            "در حال بازگشت به تست آن سطح است. "
                            "این سطح حالا به حمایت تبدیل شده و "
                            "فرصت ورود با ریسک کم فراهم می‌کند."
                        ),
                        entry_conditions=[
                            "بازگشت قیمت به سطح شکسته شده",
                            "مشاهده کندل تأییدیه صعودی",
                            "بسته شدن بالای سطح"
                        ],
                        score_bonus=1
                    )
    
    # Bearish Flip: حمایت قبلی → مقاومت فعلی
    elif htf_bias == "BEARISH":
        for sl_point in swing_lows[:-1]:
            support = sl_point["price"]
            # شکست حمایت
            broken = False
            for j in range(sl_point["index"]+1, len(candles)):
                if candles["close"].iloc[j] < support:
                    broken = True
                    break
            
            if broken:
                if (abs(current_price - support) / support < 0.01 and
                    current_price <= support * 1.01):
                    
                    sl = support * 1.005
                    sl_dist = abs(current_price - sl)
                    
                    return StrategySignal(
                        strategy="FLIPZONE",
                        strategy_fa="فیلیپ زون",
                        direction="SHORT",
                        entry=current_price,
                        sl=sl,
                        tp1=current_price - sl_dist * 2,
                        tp2=current_price - sl_dist * 3,
                        zone_top=support * 1.002,
                        zone_bottom=support * 0.998,
                        strength="STRONG",
                        confirmations=[
                            "✅ حمایت قبلی شکسته شده",
                            "✅ قیمت در حال تست سطح شکسته",
                            "✅ تبدیل حمایت به مقاومت"
                        ],
                        description=(
                            "فیلیپ زون نزولی شناسایی شد. "
                            "یک سطح حمایت قبلی شکسته شده و حالا قیمت "
                            "در حال بازگشت به تست آن سطح است. "
                            "این سطح حالا به مقاومت تبدیل شده و "
                            "فرصت ورود با ریسک کم فراهم می‌کند."
                        ),
                        entry_conditions=[
                            "بازگشت قیمت به سطح شکسته شده",
                            "مشاهده کندل تأییدیه نزولی",
                            "بسته شدن زیر سطح"
                        ],
                        score_bonus=1
                    )
    
    return None


# ─────────────────────────────────────────────
# ۷. Break of Dynamic/Static Resistance
# ─────────────────────────────────────────────

def detect_breakout(df: pd.DataFrame, htf_bias: str,
                    lookback: int = 50) -> Optional[StrategySignal]:
    """
    Breakout:
    شکست سطوح استاتیک (حمایت/مقاومت افقی)
    یا داینامیک (خط روند)
    """
    if len(df) < lookback:
        return None
    
    candles = df.tail(lookback).reset_index(drop=True)
    current_price = candles["close"].iloc[-1]
    prev_close = candles["close"].iloc[-2]
    
    # Static Resistance (مقاومت افقی)
    highs = candles["high"].values[:-1]
    resistance_levels = []
    
    for i in range(2, len(highs) - 2):
        if highs[i] == max(highs[i-2:i+3]):
            resistance_levels.append(highs[i])
    
    # Bullish Breakout
    if htf_bias == "BULLISH":
        for res in sorted(set(resistance_levels), reverse=True):
            # شکست مقاومت
            if prev_close < res and current_price > res:
                # بازگشت به تست
                sl = res * 0.995
                sl_dist = abs(current_price - sl)
                
                return StrategySignal(
                    strategy="BREAKOUT",
                    strategy_fa="شکست مقاومت",
                    direction="LONG",
                    entry=current_price,
                    sl=sl,
                    tp1=current_price + sl_dist * 2,
                    tp2=current_price + sl_dist * 3,
                    zone_top=res * 1.002,
                    zone_bottom=res * 0.998,
                    strength="STRONG",
                    confirmations=[
                        f"✅ شکست مقاومت {res:.4f}",
                        "✅ بسته شدن بالای سطح",
                        "✅ در جهت روند اصلی"
                    ],
                    description=(
                        f"شکست مقاومت استاتیک در سطح {res:.4f} شناسایی شد. "
                        "قیمت با قدرت از این سطح عبور کرده و "
                        "نشان‌دهنده قدرت خریداران است. "
                        "پولبک به این سطح می‌تواند فرصت ورود خوبی باشد."
                    ),
                    entry_conditions=[
                        "پولبک به سطح شکسته شده",
                        "مشاهده کندل تأییدیه صعودی",
                        "بسته شدن بالای سطح"
                    ],
                    score_bonus=1
                )
    
    # Bearish Breakout
    elif htf_bias == "BEARISH":
        lows = candles["low"].values[:-1]
        support_levels = []
        
        for i in range(2, len(lows) - 2):
            if lows[i] == min(lows[i-2:i+3]):
                support_levels.append(lows[i])
        
        for sup in sorted(set(support_levels)):
            if prev_close > sup and current_price < sup:
                sl = sup * 1.005
                sl_dist = abs(current_price - sl)
                
                return StrategySignal(
                    strategy="BREAKOUT",
                    strategy_fa="شکست حمایت",
                    direction="SHORT",
                    entry=current_price,
                    sl=sl,
                    tp1=current_price - sl_dist * 2,
                    tp2=current_price - sl_dist * 3,
                    zone_top=sup * 1.002,
                    zone_bottom=sup * 0.998,
                    strength="STRONG",
                    confirmations=[
                        f"✅ شکست حمایت {sup:.4f}",
                        "✅ بسته شدن زیر سطح",
                        "✅ در جهت روند اصلی"
                    ],
                    description=(
                        f"شکست حمایت استاتیک در سطح {sup:.4f} شناسایی شد. "
                        "قیمت با قدرت از این سطح عبور کرده و "
                        "نشان‌دهنده قدرت فروشندگان است. "
                        "پولبک به این سطح می‌تواند فرصت ورود خوبی باشد."
                    ),
                    entry_conditions=[
                        "پولبک به سطح شکسته شده",
                        "مشاهده کندل تأییدیه نزولی",
                        "بسته شدن زیر سطح"
                    ],
                    score_bonus=1
                )
    
    return None


# ─────────────────────────────────────────────
# ۸. Order Block
# ─────────────────────────────────────────────

def detect_orderblock_signal(df: pd.DataFrame, htf_bias: str,
                            lookback: int = 50) -> Optional[StrategySignal]:
    """
    Order Block:
    آخرین کندل مخالف قبل از حرکت قوی
    نشان‌دهنده ورود سفارشات بزرگ
    """
    if len(df) < lookback:
        return None
    
    candles = df.tail(lookback).reset_index(drop=True)
    current_price = candles["close"].iloc[-1]
    
    bodies = abs(candles["close"] - candles["open"])
    avg_body = bodies.mean()
    
    # Bullish OB: کندل نزولی قبل از حرکت صعودی قوی
    if htf_bias == "BULLISH":
        for i in range(len(candles) - 3, 1, -1):
            body = bodies.iloc[i]
            
            # کندل نزولی
            if candles["close"].iloc[i] < candles["open"].iloc[i]:
                # کندل بعدی صعودی قوی
                next_body = bodies.iloc[i+1]
                if (next_body > avg_body * 1.5 and
                    candles["close"].iloc[i+1] > candles["open"].iloc[i+1]):
                    
                    ob_top = max(candles["open"].iloc[i], candles["close"].iloc[i])
                    ob_bottom = min(candles["open"].iloc[i], candles["close"].iloc[i])
                    
                    # قیمت در ناحیه OB
                    if ob_bottom <= current_price <= ob_top:
                        sl = ob_bottom * 0.998
                        sl_dist = abs(current_price - sl)
                        
                        return StrategySignal(
                            strategy="ORDERBLOCK",
                            strategy_fa="اوردر بلاک",
                            direction="LONG",
                            entry=current_price,
                            sl=sl,
                            tp1=current_price + sl_dist * 2,
                            tp2=current_price + sl_dist * 3,
                            zone_top=ob_top,
                            zone_bottom=ob_bottom,
                            strength="STRONG" if next_body > avg_body * 2 else "NORMAL",
                            confirmations=[
                                "✅ اوردر بلاک صعودی شناسایی شد",
                                f"✅ قدرت: {next_body/avg_body:.1f}x میانگین",
                                "✅ قیمت در ناحیه OB"
                            ],
                            description=(
                                "اوردر بلاک صعودی شناسایی شد. "
                                "این ناحیه آخرین کندل نزولی قبل از حرکت صعودی قوی "
                                "بوده و نشان‌دهنده ورود سفارشات بزرگ خرید است. "
                                "بازگشت به این ناحیه فرصت ورود خوبی فراهم می‌کند."
                            ),
                            entry_conditions=[
                                "بازگشت قیمت به ناحیه OB",
                                "مشاهده کندل تأییدیه صعودی",
                                "بسته شدن بالای OB"
                            ],
                            score_bonus=1
                        )
    
    # Bearish OB: کندل صعودی قبل از حرکت نزولی قوی
    elif htf_bias == "BEARISH":
        for i in range(len(candles) - 3, 1, -1):
            body = bodies.iloc[i]
            
            if candles["close"].iloc[i] > candles["open"].iloc[i]:
                next_body = bodies.iloc[i+1]
                if (next_body > avg_body * 1.5 and
                    candles["close"].iloc[i+1] < candles["open"].iloc[i+1]):
                    
                    ob_top = max(candles["open"].iloc[i], candles["close"].iloc[i])
                    ob_bottom = min(candles["open"].iloc[i], candles["close"].iloc[i])
                    
                    if ob_bottom <= current_price <= ob_top:
                        sl = ob_top * 1.002
                        sl_dist = abs(current_price - sl)
                        
                        return StrategySignal(
                            strategy="ORDERBLOCK",
                            strategy_fa="اوردر بلاک",
                            direction="SHORT",
                            entry=current_price,
                            sl=sl,
                            tp1=current_price - sl_dist * 2,
                            tp2=current_price - sl_dist * 3,
                            zone_top=ob_top,
                            zone_bottom=ob_bottom,
                            strength="STRONG" if next_body > avg_body * 2 else "NORMAL",
                            confirmations=[
                                "✅ اوردر بلاک نزولی شناسایی شد",
                                f"✅ قدرت: {next_body/avg_body:.1f}x میانگین",
                                "✅ قیمت در ناحیه OB"
                            ],
                            description=(
                                "اوردر بلاک نزولی شناسایی شد. "
                                "این ناحیه آخرین کندل صعودی قبل از حرکت نزولی قوی "
                                "بوده و نشان‌دهنده ورود سفارشات بزرگ فروش است. "
                                "بازگشت به این ناحیه فرصت ورود خوبی فراهم می‌کند."
                            ),
                            entry_conditions=[
                                "بازگشت قیمت به ناحیه OB",
                                "مشاهده کندل تأییدیه نزولی",
                                "بسته شدن زیر OB"
                            ],
                            score_bonus=1
                        )
    
    return None


# ─────────────────────────────────────────────
# ۹. Structure Change (CHoCH/BOS)
# ─────────────────────────────────────────────

def detect_structure_change(df: pd.DataFrame, htf_bias: str,
                           lookback: int = 50) -> Optional[StrategySignal]:
    """
    Structure Change:
    CHoCH: تغییر جهت (مهم‌تر)
    BOS: شکست ساختار (ادامه)
    """
    if len(df) < lookback:
        return None
    
    candles = df.tail(lookback).reset_index(drop=True)
    current_price = candles["close"].iloc[-1]
    
    # پیدا کردن swing points
    swing_highs = []
    swing_lows = []
    
    for i in range(3, len(candles) - 3):
        if candles["high"].iloc[i] == max(candles["high"].iloc[i-3:i+4]):
            swing_highs.append({"index": i, "price": candles["high"].iloc[i]})
        if candles["low"].iloc[i] == min(candles["low"].iloc[i-3:i+4]):
            swing_lows.append({"index": i, "price": candles["low"].iloc[i]})
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None
    
    last_high = swing_highs[-1]
    prev_high = swing_highs[-2]
    last_low = swing_lows[-1]
    prev_low = swing_lows[-2]
    
    current_close = candles["close"].iloc[-1]
    
    # Bullish CHoCH: شکست سقف قبلی در روند نزولی
    if htf_bias == "BULLISH":
        # شکست بالای سقف قبلی
        if (last_high["price"] < prev_high["price"] and  # LH بوده
            current_close > last_high["price"]):  # حالا شکسته
            
            sl = last_low["price"] * 0.998
            sl_dist = abs(current_price - sl)
            
            return StrategySignal(
                strategy="CHOCH",
                strategy_fa="تغییر ساختار",
                direction="LONG",
                entry=current_price,
                sl=sl,
                tp1=current_price + sl_dist * 2,
                tp2=current_price + sl_dist * 3,
                zone_top=last_high["price"],
                zone_bottom=last_low["price"],
                strength="STRONG",
                confirmations=[
                    "✅ CHoCH صعودی شناسایی شد",
                    "✅ شکست سقف قبلی (LH → HH)",
                    "✅ تغییر جهت بازار"
                ],
                description=(
                    "تغییر ساختار صعودی (Bullish CHoCH) شناسایی شد. "
                    "بازار که در روند نزولی بوده، سقف قبلی را شکسته. "
                    "این نشان‌دهنده تغییر جهت احتمالی از نزولی به صعودی است. "
                    "یکی از مهم‌ترین سیگنال‌ها در پرایس اکشن."
                ),
                entry_conditions=[
                    "شکست قاطع سقف قبلی",
                    "بسته شدن بالای سطح شکست",
                    "ترجیحاً با حجم بالا"
                ],
                score_bonus=2
            )
    
    # Bearish CHoCH: شکست کف قبلی در روند صعودی
    elif htf_bias == "BEARISH":
        if (last_low["price"] > prev_low["price"] and  # HL بوده
            current_close < last_low["price"]):  # حالا شکسته
            
            sl = last_high["price"] * 1.002
            sl_dist = abs(current_price - sl)
            
            return StrategySignal(
                strategy="CHOCH",
                strategy_fa="تغییر ساختار",
                direction="SHORT",
                entry=current_price,
                sl=sl,
                tp1=current_price - sl_dist * 2,
                tp2=current_price - sl_dist * 3,
                zone_top=last_high["price"],
                zone_bottom=last_low["price"],
                strength="STRONG",
                confirmations=[
                    "✅ CHoCH نزولی شناسایی شد",
                    "✅ شکست کف قبلی (HL → LL)",
                    "✅ تغییر جهت بازار"
                ],
                description=(
                    "تغییر ساختار نزولی (Bearish CHoCH) شناسایی شد. "
                    "بازار که در روند صعودی بوده، کف قبلی را شکسته. "
                    "این نشان‌دهنده تغییر جهت احتمالی از صعودی به نزولی است. "
                    "یکی از مهم‌ترین سیگنال‌ها در پرایس اکشن."
                ),
                entry_conditions=[
                    "شکست قاطع کف قبلی",
                    "بسته شدن زیر سطح شکست",
                    "ترجیحاً با حجم بالا"
                ],
                score_bonus=2
            )
    
    return None


# ─────────────────────────────────────────────
# ۱۰. Return to Area (بازگشت به ناحیه)
# ─────────────────────────────────────────────

def detect_return_to_area(df: pd.DataFrame, htf_bias: str,
                         lookback: int = 50) -> Optional[StrategySignal]:
    """
    Return to Area:
    بازگشت قیمت به ناحیه‌ای که قبلاً از آن حرکت کرده
    مثل بازگشت به ناحیه عرضه/تقاضا
    """
    if len(df) < lookback:
        return None
    
    candles = df.tail(lookback).reset_index(drop=True)
    current_price = candles["close"].iloc[-1]
    
    # پیدا کردن ناحیه‌های مهم
    bodies = abs(candles["close"] - candles["open"])
    avg_body = bodies.mean()
    
    # Bullish Return: بازگشت به ناحیه تقاضا
    if htf_bias == "BULLISH":
        for i in range(len(candles) - 5, 0, -1):
            # پیدا کردن کندل‌های با بدنه بزرگ صعودی
            if (candles["close"].iloc[i] > candles["open"].iloc[i] and
                bodies.iloc[i] > avg_body * 1.5):
                
                zone_top = candles["high"].iloc[i]
                zone_bottom = candles["low"].iloc[i]
                
                # قیمت از این ناحیه حرکت کرده
                moved_away = False
                for j in range(i+1, len(candles) - 2):
                    if candles["low"].iloc[j] > zone_top:
                        moved_away = True
                        break
                
                if moved_away:
                    # قیمت برگشته به ناحیه
                    if zone_bottom <= current_price <= zone_top:
                        sl = zone_bottom * 0.998
                        sl_dist = abs(current_price - sl)
                        
                        return StrategySignal(
                            strategy="RETURN_AREA",
                            strategy_fa="بازگشت به ناحیه",
                            direction="LONG",
                            entry=current_price,
                            sl=sl,
                            tp1=current_price + sl_dist * 2,
                            tp2=current_price + sl_dist * 3,
                            zone_top=zone_top,
                            zone_bottom=zone_bottom,
                            strength="NORMAL",
                            confirmations=[
                                "✅ بازگشت به ناحیه تقاضا",
                                "✅ ناحیه قبلی معتبر",
                                "✅ فرصت ورود با ریسک کم"
                            ],
                            description=(
                                "بازگشت به ناحیه تقاضا شناسایی شد. "
                                "قیمت قبلاً از این ناحیه حرکت صعودی قوی داشته "
                                "و حالا به این ناحیه برگشته. "
                                "این ناحیه هنوز معتبر است و فرصت ورود خوبی فراهم می‌کند."
                            ),
                            entry_conditions=[
                                "ورود قیمت به ناحیه",
                                "مشاهده کندل تأییدیه صعودی",
                                "بسته شدن بالای ناحیه"
                            ],
                            score_bonus=0
                        )
    
    # Bearish Return: بازگشت به ناحیه عرضه
    elif htf_bias == "BEARISH":
        for i in range(len(candles) - 5, 0, -1):
            if (candles["close"].iloc[i] < candles["open"].iloc[i] and
                bodies.iloc[i] > avg_body * 1.5):
                
                zone_top = candles["high"].iloc[i]
                zone_bottom = candles["low"].iloc[i]
                
                moved_away = False
                for j in range(i+1, len(candles) - 2):
                    if candles["high"].iloc[j] < zone_bottom:
                        moved_away = True
                        break
                
                if moved_away:
                    if zone_bottom <= current_price <= zone_top:
                        sl = zone_top * 1.002
                        sl_dist = abs(current_price - sl)
                        
                        return StrategySignal(
                            strategy="RETURN_AREA",
                            strategy_fa="بازگشت به ناحیه",
                            direction="SHORT",
                            entry=current_price,
                            sl=sl,
                            tp1=current_price - sl_dist * 2,
                            tp2=current_price - sl_dist * 3,
                            zone_top=zone_top,
                            zone_bottom=zone_bottom,
                            strength="NORMAL",
                            confirmations=[
                                "✅ بازگشت به ناحیه عرضه",
                                "✅ ناحیه قبلی معتبر",
                                "✅ فرصت ورود با ریسک کم"
                            ],
                            description=(
                                "بازگشت به ناحیه عرضه شناسایی شد. "
                                "قیمت قبلاً از این ناحیه حرکت نزولی قوی داشته "
                                "و حالا به این ناحیه برگشته. "
                                "این ناحیه هنوز معتبر است و فرصت ورود خوبی فراهم می‌کند."
                            ),
                            entry_conditions=[
                                "ورود قیمت به ناحیه",
                                "مشاهده کندل تأییدیه نزولی",
                                "بسته شدن زیر ناحیه"
                            ],
                            score_bonus=0
                        )
    
    return None


# ─────────────────────────────────────────────
# تابع اصلی: اجرای همه استراتژی‌ها
# ─────────────────────────────────────────────

def run_all_strategies(df: pd.DataFrame, htf_bias: str) -> List[StrategySignal]:
    """
    همه استراتژی‌ها رو اجرا میکنه و سیگنال‌ها رو برمیگردونه
    """
    signals = []
    
    strategies = [
        detect_quasimodo,
        detect_engulfing,
        detect_pinbar,
        detect_fvg_signal,
        detect_ifvg_signal,
        detect_flipzone,
        detect_breakout,
        detect_orderblock_signal,
        detect_structure_change,
        detect_return_to_area,
    ]
    
    for strategy_func in strategies:
        try:
            result = strategy_func(df, htf_bias)
            if result:
                signals.append(result)
        except Exception as e:
            print(f"Strategy error: {e}")
    
    return signals
