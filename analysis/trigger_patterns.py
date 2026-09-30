"""Multi-candle / higher-timeframe alternative trigger evaluation.

Motivation (live review): the strict engine only ever looks at *one* candle on
the trigger timeframe. A base built by 2-9 trigger bars can read as a perfectly
clear pin bar, doji-then-break or engulfing when aggregated to the next higher
timeframe (e.g. 6x5m = 30m, 12x5m = 1h) even though no single 5m candle shows
it. A close that dips into a zone and reclaims the level is equally valid —
the pin bar itself is only one possible sign of rejection, never a requirement.

This module is deliberately *additive*: the native single-candle trigger keeps
its precedence, and these cluster triggers are only consulted when the single
candle did not confirm. Nothing here relaxes invalidation, chase or R/R math.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

# Confluence levels used only for evidence text / notes.
FIB_LEVELS = (0.382, 0.5, 0.618, 0.705, 0.786)


@dataclass(frozen=True)
class AltTrigger:
    kind: str          # CLUSTER_PIN | CLUSTER_ENGULF | CLUSTER_BOS | RECLAIM | DOJI_BREAK | MTF_PIN | MTF_DOJI_BREAK
    size: int          # number of trigger bars inside the base
    extreme: float     # rejection wick extreme (wick low for LONG, wick high for SHORT)
    fibo: str = ""     # matched Fib confluence label, "" when none
    higher_tf_min: int = 0  # aggregation window in minutes for MTF kinds


def _is_bull(o: float, h: float, l: float, c: float) -> float:
    return 1.0 if c > o else 0.0


def _pin(o: float, h: float, l: float, c: float, direction: str,
         wick_min: float = 0.55, opp_max: float = 0.20) -> bool:
    rng = max(h - l, 1e-12)
    top, bottom = max(o, c), min(o, c)
    lower, upper = bottom - l, h - top
    if direction == "LONG":
        return lower >= wick_min * rng and upper <= opp_max * rng and c >= o
    return upper >= wick_min * rng and lower <= opp_max * rng and c <= o


def _doji(o: float, h: float, l: float, c: float, max_body: float = 0.15) -> bool:
    rng = max(h - l, 1e-12)
    return abs(c - o) <= max_body * rng


def _aggregate(window: pd.DataFrame) -> tuple:
    o = float(window.iloc[0]["open"])
    c = float(window.iloc[-1]["close"])
    h = float(window["high"].max())
    l = float(window["low"].min())
    return o, h, l, c


def _fibo_note(df: pd.DataFrame, direction: str, extreme: float, atr_value: float,
               lookback: int = 60, tol_atr: float = 0.25) -> str:
    if atr_value <= 0:
        return ""
    tail = df.tail(lookback)
    hi = float(tail["high"].max())
    lo = float(tail["low"].min())
    rng = hi - lo
    if rng <= 0:
        return ""
    for f in FIB_LEVELS:
        level = lo + f * rng if direction == "LONG" else hi - f * rng
        if abs(extreme - level) <= tol_atr * atr_value:
            return f"{f:.3f}"
    return ""


def multi_candle_trigger(
    df: pd.DataFrame,
    direction: str,
    zone_low: float,
    zone_high: float,
    atr_value: float,
    *,
    max_base: int = 9,
    min_body_atr: float = 0.30,
    require_zone_mid: bool = True,
    mtf_enabled: bool = True,
    fibo_enabled: bool = True,
) -> Optional[AltTrigger]:
    """Return an AltTrigger when the base of closed candles shows a valid
    higher-timeframe rejection, else None. `df` must contain only closed bars
    with open/high/low/close columns ordered oldest -> newest."""
    if df is None or len(df) < 3:
        return None
    is_long = direction == "LONG"
    last = df.iloc[-1]
    last_close = float(last["close"])
    zone_mid = (zone_low + zone_high) / 2.0
    if require_zone_mid:
        # Same discipline as the single-candle path: the confirming close must
        # already be past the zone midpoint in the trade direction.
        if is_long and last_close <= zone_mid:
            return None
        if not is_long and last_close >= zone_mid:
            return None

    fibo = ""
    # --- multi-candle cluster patterns over the base -----------------------
    max_k = min(int(max_base), len(df) - 1)
    for k in range(2, max_k + 1):
        window = df.tail(k)
        o, h, l, c = _aggregate(window)
        if not (min(l, zone_low) <= zone_high and max(h, zone_high) >= zone_low):
            continue  # base did not trade the zone at all
        extreme = l if is_long else h
        # pin across the base (the classic "چند‌کندلی بیس پین‌باری" read)
        if _pin(o, h, l, c, direction):
            if fibo_enabled and not fibo:
                fibo = _fibo_note(df, direction, extreme, atr_value)
            return AltTrigger("CLUSTER_PIN", k, extreme, fibo)
        # recovery close back beyond the far edge of the zone (reclaim)
        if is_long and l < zone_high and c > zone_high and (c - o) >= min_body_atr * atr_value:
            if fibo_enabled:
                fibo = _fibo_note(df, direction, extreme, atr_value)
            return AltTrigger("RECLAIM", k, extreme, fibo)
        if not is_long and h > zone_low and c < zone_low and (o - c) >= min_body_atr * atr_value:
            if fibo_enabled:
                fibo = _fibo_note(df, direction, extreme, atr_value)
            return AltTrigger("RECLAIM", k, extreme, fibo)
        # aggregate body engulfs the previous equal-sized stretch of candles
        if len(df) >= 2 * k:
            prev_o, prev_h, prev_l, prev_c = _aggregate(df.iloc[-2 * k:-k])
            if is_long and o <= prev_c and c >= prev_o and (c - o) > (prev_o - prev_c):
                return AltTrigger("CLUSTER_ENGULF", k, extreme, fibo)
            if not is_long and o >= prev_c and c <= prev_o and (o - c) > (prev_o - prev_c):
                return AltTrigger("CLUSTER_ENGULF", k, extreme, fibo)
        # structure break of the base window itself (close beyond prior highs)
        prior = df.iloc[-(k + 1):-k] if len(df) > k else window.iloc[:-1]
        if len(prior) >= 1:
            if is_long and c > float(prior["high"].max()) and (c - o) >= min_body_atr * atr_value:
                return AltTrigger("CLUSTER_BOS", k, extreme, fibo)
            if not is_long and c < float(prior["low"].min()) and (o - c) >= min_body_atr * atr_value:
                return AltTrigger("CLUSTER_BOS", k, extreme, fibo)

    # --- doji inside the zone followed by a directional break (2 bars) -----
    prev = df.iloc[-2]
    po, ph, pl, pc = (float(prev["open"]), float(prev["high"]),
                      float(prev["low"]), float(prev["close"]))
    lo_ = float(last["open"])
    doji_at_zone = _doji(po, ph, pl, pc) and pl <= zone_high and ph >= zone_low
    if doji_at_zone:
        broke = (last_close > max(ph, pc)) if is_long else (last_close < min(pl, pc))
        body_move = abs(last_close - lo_)
        if broke and body_move >= min_body_atr * atr_value:
            return AltTrigger("DOJI_BREAK", 2, pl if is_long else ph,
                              _fibo_note(df, direction, pl if is_long else ph, atr_value) if fibo_enabled else "")

    # --- native higher-timeframe candles rebuilt from trigger bars --------
    if mtf_enabled and len(df) >= 14:
        try:
            ts = pd.to_datetime(df["timestamp"])
            step_min = float((ts.iloc[1] - ts.iloc[0]).total_seconds()) / 60.0
        except Exception:
            step_min = 0.0
        if step_min > 0:
            indexed = df.copy()
            indexed.index = pd.to_datetime(df["timestamp"])
            for mult in (6, 12):
                minutes = int(step_min * mult)
                if len(df) < 2 * mult:
                    continue
                bars = (indexed
                        .resample(f"{minutes}min")
                        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                        .dropna(subset=["open", "close"]))
                if len(bars) < 2:
                    continue
                for pos in (-1, -2):
                    o, h, l, c = (float(bars.iloc[pos]["open"]), float(bars.iloc[pos]["high"]),
                                  float(bars.iloc[pos]["low"]), float(bars.iloc[pos]["close"]))
                    if l > zone_high or h < zone_low:
                        continue  # the higher-TF bar never traded the zone
                    extreme = l if is_long else h
                    if _pin(o, h, l, c, direction):
                        return AltTrigger("MTF_PIN", mult, extreme,
                                          _fibo_note(df, direction, extreme, atr_value) if fibo_enabled else "",
                                          higher_tf_min=minutes)
                    if pos == -2 and _doji(o, h, l, c):
                        nxt = bars.iloc[-1]
                        broke = float(nxt["close"]) > h if is_long else float(nxt["close"]) < l
                        if broke:
                            return AltTrigger("MTF_DOJI_BREAK", mult, extreme, "", higher_tf_min=minutes)
    return None


def describe(alt: AltTrigger, direction: str) -> str:
    """Persian evidence sentence describing the cluster trigger."""
    dir_fa = "صعودی" if direction == "LONG" else "نزولی"
    base = f"بیس {alt.size}‌کندلی"
    if alt.kind == "CLUSTER_PIN":
        text = (f"خودِ یک کندل پین نبود؛ اما {base} روی ناحیه در aggregate تایم بالاتر "
                f"یک Pin Bar کاملِ {dir_fa} با شدوی پایینی/بالایی معنادار ساخت.")
    elif alt.kind == "RECLAIM":
        text = (f"قیمت داخل ناحیه نفوذ کرد و سپس {base} را بالای لبه‌ی ناحیه بست "
                f"(Reclaim معتبرِ {dir_fa})؛ این خودش تاییدیه‌ی شکست/بازگشت است.")
    elif alt.kind == "CLUSTER_ENGULF":
        text = f"بدنه‌ی aggregate {base}، {base} قبلی را به‌طور کامل انگالف کرد."
    elif alt.kind == "CLUSTER_BOS":
        text = f"کلوزِ aggregate {base} از سقف/کفِ ساختار میکرو قبل عبور کرد (BOS ترکیبی)."
    elif alt.kind == "DOJI_BREAK":
        text = "یک Doji روی ناحیه شکل گرفت و کندل بعدی با بدنه از آن عبور کرد (Doji Break)."
    elif alt.kind == "MTF_PIN":
        text = (f"هیچ کندل تکی پین نداشت، ولی کندل native تایم بالاتر "
                f"(~{alt.higher_tf_min} دقیقه از aggregate {alt.size}×) یک Pin Bar {dir_fa} است.")
    elif alt.kind == "MTF_DOJI_BREAK":
        text = f"در تایم بالاتر (~{alt.higher_tf_min} دقیقه) Doji روی ناحیه و بعد شکستش دیده شد."
    else:
        text = alt.kind
    if alt.fibo:
        text += f" شدِ رد شدن روی فیبو {alt.fibo} ناحیه هم‌زمان است (Confluence)."
    return text
