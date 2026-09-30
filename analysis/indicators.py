"""Deterministic, dependency-light technical helpers for the quality engine."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX(period). Trend-strength only; direction-free."""
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff().fillna(0.0)
    down = (-low.diff()).fillna(0.0)
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr_s = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.fillna(50.0)


# r50 (Viva 09-27, verbatim: «شدوهای نویز رو نگیره بعنوان پیوت … ترند رو از
# بادی اونها بگیره»): a pivot candle whose wick is an OUTLIER against the
# tape's own normal shadows — wick >= 2x the MEDIAN wick of the last 20
# candles, AND >= 1x its body, AND >= 0.50x ATR14 — is a liquidity sweep,
# not a structure anchor: the trend/pattern lines anchor at that candle's
# BODY extreme. The criteria must stay strict so ordinary small-body candles
# never lose their legitimate wick pivots. Structural consumers (sweeps,
# stops, BOS) keep the raw wick: a sweep IS the wick. Only the line-fit
# call sites opt in.
WICK_NOISE_OUTLIER_MULT = 2.0
WICK_NOISE_BODY_MULT = 1.0
WICK_NOISE_ATR_FRAC = 0.50
WICK_NOISE_LOOKBACK = 20

# r58 (Viva, the hybrid shadow law — verbatim: «گفتم پینبارها کوچک گرفته بشه
# نگفتم که از بادی بگیر فقط .. بعضی کندل‌ها یک شدو خیلی خیلی بلند دارن که اگر
# ترند از نوک اون شدو رسم بشه اصلاً قابل ترسیم نیست — اونها رو از بادی بگیره
# اما در نقاط بعدی همون ترند شدوهای معقول رو محاسبه بکنه و وصل بکنه بهشون»):
# a pivot wick anchors AT THE WICK unless it is EXTREME (≥ WICK_EXTREME_MED_MULT
# × the recent median wick AND ≥ WICK_EXTREME_ATR_FRAC × ATR) — extreme wicks
# (liquidation spikes) anchor on the body; reasonable wicks stay wicks.
WICK_EXTREME_MED_MULT = 2.0
WICK_EXTREME_ATR_FRAC = 1.0


def pivots(df: pd.DataFrame, left: int = 3, right: int = 3,
           wick_noise_filter: bool = False,
           wick_policy: str = "outlier") -> Tuple[List[Dict], List[Dict]]:
    """wick_policy (r57, Viva: «شدوهای خیلی بلند رو گفتم نگیره برای رسم الگو
    و ترند .. الان همه شدوها رو رد میکنه اینجوری ترندها گاهی وقتا خطا مده»):
      • "outlier" — the old r50 law (only OUTLIER wicks demote to body);
        keeps the futures TRADE edges exactly as they were.
      • "bodies"  — drawing anchors are ALWAYS the candle BODY; a trend or
        pattern edge is drawn where the mass of the candle is, never where a
        liquidation wick poked (DASH/ARB 3d mega-wicks bent the lines)."""

    highs: List[Dict] = []
    lows: List[Dict] = []
    if df is None or len(df) < left + right + 1:
        return highs, lows
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    # fail-open: frames without open/close (rare legacy tapes) keep raw pivots
    has_body = "open" in df.columns and "close" in df.columns
    o = df["open"].to_numpy(dtype=float) if has_body else None
    c = df["close"].to_numpy(dtype=float) if has_body else None
    atr14 = float((df["high"] - df["low"]).tail(14).mean()) if len(df) >= 14 else 0.0
    if not has_body:
        wick_noise_filter = False
    _med_wick = 0.0
    if wick_noise_filter and has_body:
        _tail = df.tail(WICK_NOISE_LOOKBACK)
        _med_wick = float(np.median(np.maximum(
            (_tail["high"] - np.maximum(_tail["open"], _tail["close"])).to_numpy(dtype=float),
            (np.minimum(_tail["open"], _tail["close"]) - _tail["low"]).to_numpy(dtype=float))))
    for i in range(left, len(df) - right):
        if h[i] >= np.max(h[i - left : i + right + 1]):
            _price = float(h[i])
            _anchor = "wick"
            if wick_policy in ("bodies", "hybrid") and has_body:
                _wick_up = float(h[i] - max(o[i], c[i]))
                if wick_policy == "bodies" or (
                        wick_policy == "hybrid" and atr14 > 0 and
                        _wick_up >= WICK_EXTREME_MED_MULT * _med_wick and
                        _wick_up >= WICK_EXTREME_ATR_FRAC * atr14):
                    _price = float(max(o[i], c[i]))
                    _anchor = "body"
            elif wick_noise_filter and atr14 > 0:
                _wick = float(h[i] - max(o[i], c[i]))
                _body = abs(float(c[i] - o[i]))
                if (_wick >= WICK_NOISE_OUTLIER_MULT * _med_wick
                        and _wick >= WICK_NOISE_BODY_MULT * _body
                        and _wick >= WICK_NOISE_ATR_FRAC * atr14):
                    _price = float(max(o[i], c[i]))
                    _anchor = "body"
            highs.append({"index": i, "price": _price, "raw_price": float(h[i]),
                          "anchor": _anchor, "timestamp": df["timestamp"].iloc[i]})
        if l[i] <= np.min(l[i - left : i + right + 1]):
            _price = float(l[i])
            _anchor = "wick"
            if wick_policy in ("bodies", "hybrid") and has_body:
                _wick_dn = float(min(o[i], c[i]) - l[i])
                if wick_policy == "bodies" or (
                        wick_policy == "hybrid" and atr14 > 0 and
                        _wick_dn >= WICK_EXTREME_MED_MULT * _med_wick and
                        _wick_dn >= WICK_EXTREME_ATR_FRAC * atr14):
                    _price = float(min(o[i], c[i]))
                    _anchor = "body"
            elif wick_noise_filter and atr14 > 0:
                _wick = float(min(o[i], c[i]) - l[i])
                _body = abs(float(c[i] - o[i]))
                if (_wick >= WICK_NOISE_OUTLIER_MULT * _med_wick
                        and _wick >= WICK_NOISE_BODY_MULT * _body
                        and _wick >= WICK_NOISE_ATR_FRAC * atr14):
                    _price = float(min(o[i], c[i]))
                    _anchor = "body"
            lows.append({"index": i, "price": _price, "raw_price": float(l[i]),
                         "anchor": _anchor, "timestamp": df["timestamp"].iloc[i]})
    return highs, lows


def structure_bias(df: pd.DataFrame, pivot_size: int = 3) -> Dict:
    ph, pl = pivots(df, pivot_size, pivot_size)
    if len(ph) < 2 or len(pl) < 2:
        return {"bias": "NEUTRAL", "highs": ph, "lows": pl}
    hh = ph[-1]["price"] > ph[-2]["price"]
    hl = pl[-1]["price"] > pl[-2]["price"]
    lh = ph[-1]["price"] < ph[-2]["price"]
    ll = pl[-1]["price"] < pl[-2]["price"]
    if hh and hl:
        bias = "BULLISH"
    elif lh and ll:
        bias = "BEARISH"
    else:
        # A close outside the most recent structural range can resolve mixed pivots.
        close = float(df["close"].iloc[-1])
        if close > ph[-1]["price"]:
            bias = "BULLISH"
        elif close < pl[-1]["price"]:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"
    return {
        "bias": bias,
        "highs": ph,
        "lows": pl,
        "last_high": ph[-1],
        "last_low": pl[-1],
        "previous_high": ph[-2],
        "previous_low": pl[-2],
    }


def volume_ratio(df: pd.DataFrame, period: int = 20, index: int = -1) -> float:
    if df is None or len(df) < 3:
        return 1.0
    volumes = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    idx = index if index >= 0 else len(df) + index
    start = max(0, idx - period)
    baseline = float(volumes.iloc[start:idx].median()) if idx > start else 0.0
    return float(volumes.iloc[idx] / baseline) if baseline > 0 else 1.0


def candle_displacement(df: pd.DataFrame, index: int = -1, atr_multiple: float = 0.8) -> Dict:
    idx = index if index >= 0 else len(df) + index
    if idx < 0 or idx >= len(df):
        return {"valid": False, "direction": "", "body_atr": 0.0, "volume_ratio": 0.0}
    atr_values = atr(df)
    atr_value = float(atr_values.iloc[idx]) if pd.notna(atr_values.iloc[idx]) else 0.0
    row = df.iloc[idx]
    body = abs(float(row["close"]) - float(row["open"]))
    body_atr = body / atr_value if atr_value > 0 else 0.0
    direction = "BULLISH" if row["close"] > row["open"] else "BEARISH"
    vr = volume_ratio(df, index=idx)
    return {
        "valid": body_atr >= atr_multiple and vr >= 0.8,
        "direction": direction,
        "body_atr": body_atr,
        "volume_ratio": vr,
        "atr": atr_value,
        "index": idx,
        "timestamp": row.get("timestamp"),
    }


def premium_discount(df: pd.DataFrame, lookback: int = 100) -> Dict:
    recent = df.tail(lookback)
    high = float(recent["high"].max())
    low = float(recent["low"].min())
    midpoint = (high + low) / 2
    price = float(recent["close"].iloc[-1])
    if price < midpoint * 0.998:
        location = "DISCOUNT"
    elif price > midpoint * 1.002:
        location = "PREMIUM"
    else:
        location = "EQUILIBRIUM"
    return {"high": high, "low": low, "midpoint": midpoint, "price": price, "location": location}


def session_name(timestamp) -> str:
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    hour = ts.hour
    if 7 <= hour < 10:
        return "LONDON"
    if 13 <= hour < 17:
        return "NEW_YORK"
    if 0 <= hour < 3:
        return "ASIA"
    if 12 <= hour < 16:
        return "LONDON_NY_OVERLAP"
    return "OFF_SESSION"


def detect_rsi_divergence(df: pd.DataFrame, direction: str, pivot_size: int = 3) -> Optional[Dict]:
    """Pivot-aligned regular/hidden RSI divergence. Confirmation only."""
    if df is None or len(df) < 40:
        return None
    values = rsi(df)
    ph, pl = pivots(df, pivot_size, pivot_size)
    if direction == "LONG" and len(pl) >= 2:
        a, b = pl[-2], pl[-1]
        r1, r2 = float(values.iloc[a["index"]]), float(values.iloc[b["index"]])
        if b["price"] < a["price"] and r2 > r1 + 1.5:
            return {"type": "REGULAR_BULLISH", "rsi_1": r1, "rsi_2": r2, "price_1": a["price"], "price_2": b["price"]}
        if b["price"] > a["price"] and r2 < r1 - 1.5:
            return {"type": "HIDDEN_BULLISH", "rsi_1": r1, "rsi_2": r2, "price_1": a["price"], "price_2": b["price"]}
    if direction == "SHORT" and len(ph) >= 2:
        a, b = ph[-2], ph[-1]
        r1, r2 = float(values.iloc[a["index"]]), float(values.iloc[b["index"]])
        if b["price"] > a["price"] and r2 < r1 - 1.5:
            return {"type": "REGULAR_BEARISH", "rsi_1": r1, "rsi_2": r2, "price_1": a["price"], "price_2": b["price"]}
        if b["price"] < a["price"] and r2 > r1 + 1.5:
            return {"type": "HIDDEN_BEARISH", "rsi_1": r1, "rsi_2": r2, "price_1": a["price"], "price_2": b["price"]}
    return None
