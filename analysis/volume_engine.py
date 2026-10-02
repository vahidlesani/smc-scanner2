"""Institutional Volume & Order Flow Engine — standard klines only (no paid APIs).

Viva R66 (2026-10-03): «طراحی موتور حجم و فلو هوشمند با داده‌های رایگان صرافی
(Z-Score حجم، ناهنجاری اسپرد/حجم VSA، برآورد تیکر بای/سل بدون API پولی)».

Algorithms:
  1. Volume Z-Score & Surge Ratio:
     Normalizes volume over lookback window (default 20 candles):
     Z = (V - μ) / σ. Detects statistical surges (Z >= 2.0 = Smart Money Expansion,
     Z >= 3.0 = Whale Footprint).
  2. Volume Spread Analysis (VSA) & Price Action Anomalies:
     - Absorption / Stopping Volume: Massive volume + narrow spread at support/resistance.
     - Effort vs Result Anomaly: Giant volume but tiny price progress (accumulation/distribution).
     - Climactic Volume: Extreme volume + wide spread + long opposing wick.
     - Low Volume Test (No Supply / No Demand): Dry volume pullback to broken level.
  3. Bar-Internal Order Flow & Taker Buy/Sell Estimation:
     Derived strictly from OHLCV + Turnover without external paid orderbook APIs:
       • VWAP = Turnover / Volume.
       • Relative position of VWAP within candle [L, H].
       • Bulk Volume Classification (BVC / tick-rule proxy):
         V_buy = V * (C - L + H - O) / (2 * (H - L))
         Delta% = (V_buy - V_sell) / V * 100.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass
class VolumeAnalysisResult:
    volume_zscore: float = 0.0
    volume_ratio: float = 1.0
    spread: float = 0.0
    spread_ratio: float = 1.0
    body: float = 0.0
    body_ratio: float = 0.0
    taker_buy_ratio: float = 0.50
    taker_delta_pct: float = 0.0
    vwap: float = 0.0
    flags: List[str] = field(default_factory=list)
    score: float = 5.0
    bias: str = "NEUTRAL"
    summary_fa: str = ""

    def to_dict(self) -> dict:
        return {
            "volume_zscore": round(self.volume_zscore, 2),
            "volume_ratio": round(self.volume_ratio, 2),
            "spread_ratio": round(self.spread_ratio, 2),
            "taker_buy_ratio": round(self.taker_buy_ratio, 3),
            "taker_delta_pct": round(self.taker_delta_pct, 1),
            "flags": list(self.flags),
            "score": round(self.score, 1),
            "bias": self.bias,
            "summary_fa": self.summary_fa,
        }


def analyze_volume_profile(
    df: pd.DataFrame,
    direction: str = "LONG",
    lookback: int = 20,
) -> VolumeAnalysisResult:
    """Analyze volume, VSA spread anomalies, and taker flow on the latest candle."""
    res = VolumeAnalysisResult()
    if df is None or len(df) < max(5, lookback // 2):
        return res

    try:
        vols = df["volume"].astype(float).to_numpy()
        highs = df["high"].astype(float).to_numpy()
        lows = df["low"].astype(float).to_numpy()
        opens = df["open"].astype(float).to_numpy()
        closes = df["close"].astype(float).to_numpy()
    except Exception:
        return res

    n = len(df)
    v_last = float(vols[-1])
    h_last = float(highs[-1])
    l_last = float(lows[-1])
    o_last = float(opens[-1])
    c_last = float(closes[-1])
    spread_last = max(h_last - l_last, 1e-12)
    body_last = abs(c_last - o_last)

    res.spread = spread_last
    res.body = body_last
    res.body_ratio = body_last / spread_last

    # 1. Volume Z-Score & Moving Average Ratio
    window = min(lookback, n - 1)
    if window >= 3:
        v_hist = vols[-(window + 1):-1]
        v_mean = float(np.mean(v_hist))
        v_std = float(np.std(v_hist))
        # If std is near zero (e.g. flat synthetic volume), use 20% of mean as baseline std
        eff_std = v_std if v_std > 1e-6 else max(0.20 * v_mean, 1e-6)
        res.volume_zscore = float((v_last - v_mean) / eff_std)
        res.volume_ratio = float(v_last / max(v_mean, 1e-9))

        s_hist = (highs[-(window + 1):-1] - lows[-(window + 1):-1])
        s_med = float(np.median(s_hist))
        res.spread_ratio = float(spread_last / max(s_med, 1e-9))
    else:
        res.volume_ratio = 1.0
        res.spread_ratio = 1.0

    # 2. Bar-Internal Order Flow & Taker Imbalance
    # Using turnover (quote volume) if available, otherwise tick-proxy BVC
    has_turnover = "turnover" in df.columns
    t_last = float(df["turnover"].iloc[-1]) if has_turnover else 0.0
    if has_turnover and t_last > 0 and v_last > 0:
        res.vwap = t_last / v_last
        # Relative position of VWAP in the candle range [0, 1]
        vwap_pos = (res.vwap - l_last) / spread_last
        vwap_pos = min(max(vwap_pos, 0.0), 1.0)
    else:
        res.vwap = (h_last + l_last + c_last) / 3.0
        vwap_pos = 0.5

    # BVC (Bulk Volume Classification) approximation:
    # Buyers dominate when close is near high and open near low.
    buy_fraction = ((c_last - l_last) + (h_last - o_last)) / (2.0 * spread_last)
    buy_fraction = min(max(buy_fraction, 0.02), 0.98)

    # Blend VWAP position and BVC
    blended_buy = 0.60 * buy_fraction + 0.40 * vwap_pos
    res.taker_buy_ratio = float(blended_buy)
    res.taker_delta_pct = float((blended_buy - (1.0 - blended_buy)) * 100.0)

    # 3. VSA Pattern & Anomaly Detection
    flags = []
    base_score = 5.0
    dir_upper = str(direction or "").upper()

    # Extreme institutional volume surge
    if res.volume_zscore >= 3.0 or res.volume_ratio >= 3.0:
        flags.append("WHALE_VOLUME_SURGE")
        base_score += 2.0
    elif res.volume_zscore >= 1.8 or res.volume_ratio >= 1.8:
        flags.append("INSTITUTIONAL_SURGE")
        base_score += 1.2

    # VSA Absorption / Stopping Volume: massive volume with narrow spread
    if (res.volume_zscore >= 1.5 or res.volume_ratio >= 1.5) and res.spread_ratio <= 0.85:
        flags.append("VOLUME_ABSORPTION")
        base_score += 1.0

    # VSA Effort vs Result: heavy volume but price closed mid-range with tiny body
    if (res.volume_zscore >= 1.6 or res.volume_ratio >= 1.6) and res.body_ratio <= 0.35:
        flags.append("EFFORT_VS_RESULT")

    # Climactic Exhaustion: huge spread + huge volume + long opposing wick
    upper_wick = h_last - max(o_last, c_last)
    lower_wick = min(o_last, c_last) - l_last
    if res.volume_zscore >= 2.0 and res.spread_ratio >= 1.6:
        if dir_upper == "LONG" and upper_wick >= 0.45 * spread_last:
            flags.append("BUYING_CLIMAX_EXHAUSTION")
            base_score -= 1.5
        elif dir_upper == "SHORT" and lower_wick >= 0.45 * spread_last:
            flags.append("SELLING_CLIMAX_EXHAUSTION")
            base_score -= 1.5

    # Low Volume Test (No Supply / No Demand): healthy low volume test on pullback
    if res.volume_zscore <= -0.7 and res.spread_ratio <= 0.80:
        if dir_upper == "LONG" and c_last >= l_last + 0.4 * spread_last:
            flags.append("NO_SUPPLY_TEST")
            base_score += 1.2
        elif dir_upper == "SHORT" and c_last <= h_last - 0.4 * spread_last:
            flags.append("NO_DEMAND_TEST")
            base_score += 1.2

    # Bias and alignment
    if res.taker_delta_pct >= 20.0 and res.volume_ratio >= 1.2:
        res.bias = "BULLISH"
    elif res.taker_delta_pct <= -20.0 and res.volume_ratio >= 1.2:
        res.bias = "BEARISH"
    else:
        res.bias = "NEUTRAL"

    # Direction alignment bonus/penalty
    if dir_upper == "LONG":
        if res.bias == "BULLISH":
            base_score += 1.2
        elif res.bias == "BEARISH":
            base_score -= 1.5
    elif dir_upper == "SHORT":
        if res.bias == "BEARISH":
            base_score += 1.2
        elif res.bias == "BULLISH":
            base_score -= 1.5

    res.score = min(max(base_score, 1.0), 10.0)
    res.flags = flags

    # Persian summary formatting
    notes = []
    if "WHALE_VOLUME_SURGE" in flags:
        notes.append(f"ورود حجم سنگین نهنگ (Z-Score: +{res.volume_zscore:.1f}σ)")
    elif "INSTITUTIONAL_SURGE" in flags:
        notes.append(f"افزایش محسوس حجم نهادی ({res.volume_ratio:.1f}x میانگین)")

    if "VOLUME_ABSORPTION" in flags:
        notes.append("جذب کامل اردرها با وجود اسپرد فشرده (Absorption)")
    if "NO_SUPPLY_TEST" in flags:
        notes.append("تست موفق عدم عرضه با حجم خشک (No Supply Test)")
    elif "NO_DEMAND_TEST" in flags:
        notes.append("تست موفق عدم تقاضا با حجم خشک (No Demand Test)")

    if abs(res.taker_delta_pct) >= 15.0:
        dir_fa = "خریداران تیکر" if res.taker_delta_pct > 0 else "فروشندگان تیکر"
        notes.append(f"غلبهٔ {dir_fa} (دلتا: {res.taker_delta_pct:+.0f}%)")

    res.summary_fa = " • ".join(notes) if notes else "حجم و فلو متعادل"
    return res
