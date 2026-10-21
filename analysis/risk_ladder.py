"""r63 RISK-LADDER STOP — his 10-01 amendment, law ① (verbatim backing).

«استاپ اولیه پشتِ آخرین سوینگِ یک تایم‌فریم بالاتر از تایم‌فریم تریگر؛
اگر سوینگی نبود → پشتِ سوینگِ دو تایم‌فریم بالاتر؛ باز هم نبود → ۳٫۵ تا ۵٪
(سقف ۵٪ فعلاً)». The 3.5-vs-5 tie-break is HIS confirmed ruling: whichever
of the two is NEAREST to the structural (engine) stop distance.

Applies to confirmed-entry lanes (break/structure family). The pin/reject
family keeps law-④ stops (exactly behind the same-TF extreme + last swing —
the existing Brooks/liquidity rule already is that law).
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

# Trader-natural hops (not raw TF_ORDER steps): 30m rides the 1h rung,
# 12h/8h ride 1d — the swing that traders actually mark.
PLUS_ONE_TF = {
    "1m": "3m", "3m": "5m", "5m": "15m", "15m": "1h", "30m": "1h",
    "1h": "4h", "2h": "4h", "4h": "1d", "6h": "1d", "8h": "1d",
    "12h": "1d", "1d": "1w", "3d": "1w", "1w": None,
}
PCT_FALLBACK = (3.5, 5.0)   # his corridor; cap 5% for now
CAP_PCT = 5.0
BUFFER_ATR_FRAC = 0.10      # small cushion behind the swing, both sides


def _atr(df, n: int = 14) -> float:
    try:
        import numpy as np
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        c = df["close"].astype(float)
        pc = c.shift(1)
        tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
        tr = tr.to_numpy()[1:]
        return float(tr[-n:].mean()) if len(tr) else 0.0
    except Exception:
        return 0.0


def _last_swing(df, direction: str) -> float:
    """Most recent CONFIRMED fractal pivot (2/2) on the closed frame, on the
    protective side of ``direction`` (last swing low for a LONG stop, swing
    high for a SHORT stop). 0.0 when none exists."""
    try:
        lows = df["low"].astype(float).tolist()
        highs = df["high"].astype(float).tolist()
        n = len(lows)
        want_low = str(direction or "").upper() == "LONG"
        for i in range(n - 3, 1, -1):        # i+2 must exist → pivot confirmed
            if i + 2 >= n:
                continue
            if want_low:
                if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] \
                        and lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]:
                    return float(lows[i])
            else:
                if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] \
                        and highs[i] >= highs[i + 1] and highs[i] >= highs[i + 2]:
                    return float(highs[i])
    except Exception:
        pass
    return 0.0


def _side_ok(direction: str, entry: float, stop: float) -> bool:
    if stop <= 0 or entry <= 0:
        return False
    return stop < entry if str(direction).upper() == "LONG" else stop > entry


def _pct_fallback(entry: float, direction: str, structural_pct: float) -> float:
    """Nearest of 3.5% / 5% to the structural distance (his tie-break),
    capped at 5% for now."""
    sp = abs(float(structural_pct or 0.0))
    pick = min(PCT_FALLBACK, key=lambda p: abs(p - sp))
    pick = min(pick, CAP_PCT)
    return float(entry) * (1.0 - pick / 100.0) if str(direction).upper() == "LONG" \
        else float(entry) * (1.0 + pick / 100.0)


def pin_corridor_stop(entry: float, direction: str, pin_stop: float,
                      ladder_result: Optional[Dict] = None) -> tuple:
    """R67 PIN RISK CORRIDOR (Viva 10-03 round-7, verbatim: «قوانین استاپ
    ۳ تا ۵ درصد کجا رفت؟؟ … دوباره برگشتیم با هفته‌های قبل؟؟»).

    The 10-01 amendment-① ladder has governed every break lane since r63;
    the pin family kept the old micro stops and printed 0.70% (ETC) /
    1.80% (ENA) risks. Law: final distance = max(pin structure, corridor)
    where corridor = 3.5% floored, the +1TF swing anchors inside the
    corridor, cap 5%. The pin's OWN extreme keeps sanctity — a structural
    invalidation wider than 5% is never cut (basis PIN_EXTREME_WIDE).

    Returns ``(stop_price, meta_dict)``; ``meta`` carries the full audit
    (pin_pct / ladder_pct / final_pct / ladder_tf / basis) for the message.
    """
    try:
        entry = float(entry)
        pin_pct = abs(entry - float(pin_stop)) / entry * 100.0
        lad = dict(ladder_result or {})
        lad_px = float(lad.get("stop") or 0.0)
        lad_pct = 0.0
        if lad_px > 0:
            _d = abs(entry - lad_px) / entry * 100.0
            if _d <= CAP_PCT + 1.0:
                lad_pct = _d
        target = max(PCT_FALLBACK[0], lad_pct) if lad_pct else PCT_FALLBACK[0]
        target = min(target, CAP_PCT)
        if pin_pct > CAP_PCT:
            final_pct, basis = pin_pct, "PIN_EXTREME_WIDE"
        else:
            final_pct = min(max(pin_pct, target), CAP_PCT)
            if lad_pct >= PCT_FALLBACK[0]:
                basis = "SWING_" + str(lad.get("tf") or "").upper()
            elif lad_pct:
                basis = "SWING_LT_CORRIDOR"
            else:
                basis = "CORRIDOR"
        sign = 1.0 if str(direction or "").upper() == "LONG" else -1.0
        stop = entry * (1.0 - sign * final_pct / 100.0)
        meta = {"pin_pct": round(pin_pct, 3), "ladder_pct": round(lad_pct, 3),
                "final_pct": round(final_pct, 3),
                "ladder_tf": str(lad.get("tf") or ""), "basis": basis}
        return float(stop), meta
    except Exception:
        return float(pin_stop), {}


def ladder_stop(symbol: str, direction: str, entry: float, trigger_tf: str,
                structural_pct: float,
                get_klines_fn: Optional[Callable] = None,
                n_candles: int = 140) -> Optional[Dict]:
    """His 10-01 law ①: initial stop behind the last swing of trigger-TF+1,
    else +2 TFs, else the 3.5/5% nearest-to-structural fallback (cap 5%).

    Returns ``{"stop": float, "tf": str, "hop": 1|2|0, "basis": str}`` or
    None when the caller should keep the engine's own stop untouched
    (fail-open everywhere — a fetch problem never blocks a signal).
    """
    try:
        entry = float(entry)
        direction = str(direction or "").upper()
        if entry <= 0:
            return None
        tf = str(trigger_tf or "15m").lower()
        hops = []
        cur = tf
        for _ in range(2):
            cur = PLUS_ONE_TF.get(cur)
            if not cur:
                break
            hops.append(cur)
        fetch = get_klines_fn
        for hop, htf in enumerate(hops, start=1):
            if fetch is None:
                break
            try:
                df = fetch(str(symbol), htf, n_candles, closed_only=True, use_cache=True)
            except Exception:
                df = None
            if df is None or len(df) < 30:
                continue
            swing = _last_swing(df, direction)
            if swing <= 0:
                continue
            atr = _atr(df)
            buf = BUFFER_ATR_FRAC * (atr if atr > 0 else abs(swing) * 0.002)
            stop = swing - buf if direction == "LONG" else swing + buf
            if not _side_ok(direction, entry, stop):
                continue
            # sanity: a swing stop farther than 12% is a data fluke — skip it
            if abs(entry - stop) / entry > 0.12:
                continue
            return {"stop": float(stop), "tf": htf, "hop": hop, "basis": "SWING"}
        return {"stop": float(_pct_fallback(entry, direction, structural_pct)),
                "tf": "", "hop": 0, "basis": "PCT"}
    except Exception:
        return None
