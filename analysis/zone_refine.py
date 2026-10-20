"""R99q31c — SAME-TF ZONE REFINEMENT (his 10-20, verbatim).

«اصلا نمی‌خوام یک زون تایم یا تایم‌های بالاتر بیاد توی تایم‌های کوچیک‌تر ...
 وقتی وارد هر تایم شدیم باید زون‌های همون تایم فریم نمایش داده بشه .. در واقع
 بصورت مالتی تایم هر تایم پایینتر که میاد ریفاین بشه»

«شاید یک زون مهم ۱ ساعته در ۱۵ دقیقه هم مهم باشه اما باید در ۱۵ دقیقه ریفاین
 شده نمایش داده بشه نه اینکه یه باکس یا چندتا باکس خیلی عریض و بزرگ بپره وسط
 چارت ۱۵ دقیقه»

The failure this cures: a zone detected on a 4h tape was stamped with a bar
INDEX (`x0`). When that command is painted on a 15m chart the index points at a
completely different moment, and the box is 16× too wide — a giant band across
the 15m candles. Two laws fix it, and both are geometric, not cosmetic:

  1. **TIME, NOT INDEX.** A zone carries `ts0`/`ts1`. Painting maps timestamps
     onto the frame it is painting. If the zone's origin is older than the
     visible window, the box is CLIPPED to the window edge — never stretched
     back to bar 0.
  2. **REFINE, NOT IMPORT.** A zone whose origin belongs to a higher TF is
     re-derived from the LOWER TF's own tape inside the same price band. The
     refined box is the sub-range the lower TF actually traded: tighter edges,
     same idea. That is his «ریفاین بشه».

Never vetoes, never invents a level outside the original band, always
fail-open.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# a zone wider than this fraction of the visible price range is a poster, not a
# level — his «باگ بزرگ و عریض وسط چارت»
MAX_ZONE_FRACTION = 0.28
# a refined zone narrower than this many ATR is noise
MIN_REFINE_ATR = 0.18


def _atr(df: pd.DataFrame, n: int = 14) -> float:
    try:
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        return float((h - l).tail(int(n)).mean() or 0.0)
    except Exception:
        return 0.0


def frame_times(df: pd.DataFrame) -> List[pd.Timestamp]:
    """The frame's own bar stamps, coerced once."""
    try:
        col = df["timestamp"] if "timestamp" in df.columns else df.index
        return [pd.Timestamp(x) for x in pd.to_datetime(pd.Series(col))]
    except Exception:
        return []


def _ts_of(zone: Dict) -> Optional[pd.Timestamp]:
    for key in ("ts0", "ts1"):
        v = zone.get(key)
        if not v:
            continue
        try:
            return pd.Timestamp(v)
        except Exception:
            continue
    return None


def clip_zone_to_frame(zone: Dict, df: pd.DataFrame) -> Optional[Dict]:
    """Re-anchor a zone by TIME on the frame being painted.

    Returns a copy with `x0`/`x1` as real indices of THIS frame, or None when
    the zone has no usable timestamp (caller then keeps the old behaviour).
    """
    times = frame_times(df)
    if not times:
        return None
    start = _ts_of(zone)
    if start is None:
        return None
    n = len(times)
    try:
        i0 = int(np.searchsorted(np.array(times, dtype="datetime64[ns]"),
                                 start.to_datetime64(), side="left"))
    except Exception:
        return None
    # the zone's origin predates the window: clip it to the first visible bar
    # instead of stretching it back to bar 0 (that stretch is the wide box)
    i0 = max(0, min(n - 1, i0))
    out = dict(zone)
    out["x0"] = i0
    out["x1"] = n - 1
    out["clipped"] = bool(i0 == 0 and start < times[0])
    return out


def refine_zone_same_tf(zone: Dict, df: pd.DataFrame,
                        lookback: int = 90) -> Optional[Dict]:
    """Re-derive a zone from THIS frame's own tape inside the same price band.

    The band is kept (that is the level he wants); the EDGES are re-measured
    from the lower TF's candles inside it. A zone that the lower TF never
    visited is returned untouched — we never invent a level.
    """
    try:
        if df is None or len(df) < 30:
            return None
        lo = float(zone.get("bottom") or 0)
        hi = float(zone.get("top") or 0)
        if not (hi > lo > 0):
            return None
        atr = _atr(df)
        if atr <= 0:
            return None
        tail = df.tail(max(30, int(lookback))).reset_index(drop=True)
        highs = tail["high"].astype(float).to_numpy()
        lows = tail["low"].astype(float).to_numpy()
        closes = tail["close"].astype(float).to_numpy()
        # every bar that traded INSIDE the band is the lower TF's own evidence
        touch = np.where((lows <= hi) & (highs >= lo))[0]
        if touch.size < 2:
            return None
        b = float(max(lo, float(lows[touch].max())))
        t = float(min(hi, float(highs[touch].min())))
        if t - b < MIN_REFINE_ATR * atr:
            # the lower TF only grazed it: keep the original edges, just clip
            b, t = lo, hi
        if not (t > b):
            return None
        out = dict(zone)
        out.update({"bottom": b, "top": t, "refined": True,
                    "refined_from": [lo, hi],
                    "refine_tf_bars": int(tail.shape[0])})
        # anchor at the first bar in the window that actually touched it
        out["x0"] = int(touch[0])
        out["x1"] = int(touch[-1])
        try:
            col = "timestamp" if "timestamp" in tail.columns else None
            if col is not None:
                out["ts0"] = str(pd.Timestamp(tail[col].iloc[int(touch[0])]))
        except Exception:
            pass
        _ = closes
        return out
    except Exception:
        return None


def prepare_zones(zones: List[Dict], df: pd.DataFrame,
                  lookback: int = 90, refine: bool = True) -> List[Dict]:
    """The one entry point the renderer calls.

    1. clip every zone onto this frame by TIME;
    2. re-measure its edges from this frame's tape (refine);
    3. drop a box that is still wider than MAX_ZONE_FRACTION of the visible
       price range — that is the poster he refuses to see mid-chart.

    Order matters: clipping first stops the 16×-wide stamp, refining second
    makes the box honest on the TF being drawn.
    """
    out: List[Dict] = []
    if not zones or df is None or len(df) < 20:
        return list(zones or [])
    try:
        px_lo = float(df["low"].astype(float).tail(lookback).min())
        px_hi = float(df["high"].astype(float).tail(lookback).max())
        span = max(1e-12, px_hi - px_lo)
    except Exception:
        span = 0.0
    for z in zones:
        if not isinstance(z, dict) or not z:
            continue                          # empty/garbage command: skip it
        cur = dict(z)
        clipped = clip_zone_to_frame(cur, df)
        if clipped is not None:
            cur = clipped
        if refine:
            ref = refine_zone_same_tf(cur, df, lookback=lookback)
            if ref is not None:
                cur = ref
        if span > 0:
            try:
                width = float(cur.get("top") or 0) - float(cur.get("bottom") or 0)
            except (TypeError, ValueError):
                continue                      # unreadable zone: drop, never crash
            if width > MAX_ZONE_FRACTION * span:
                # a real level on this TF is never a third of the whole chart
                continue
        out.append(cur)
    return out


def zone_report(zones: List[Dict]) -> str:
    """One-line audit string for the log (observability only)."""
    if not zones:
        return "zones=0"
    clipped = sum(1 for z in zones if z.get("clipped"))
    refined = sum(1 for z in zones if z.get("refined"))
    return f"zones={len(zones)} clipped={clipped} refined={refined}"
