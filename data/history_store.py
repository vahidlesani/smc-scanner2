"""r52 — the ONE-TIME deep-history store (Viva 09-28, verbatim directive):

«برای گرفتن این تعداد تاریخچه فقط یکبار اسکن بلند مدت روزانه بکنه و دیتا رو
دقیق ذخیره بکنه برای نمادهای مورد نظرمون که اسکن‌های بعدی روی قیمت لایو در
اسکن‌های فعلی دیگه دیده میشه و مصرف ریلوی کنترل بشه».

The spot CryptoCove lanes now render 12h/1d×210, 3d×300 and 1w×210 candles.
1w×210 needs ~1480 DAILY bars and 3d×300 needs ~910 — far beyond a single
venue call, and re-downloading them every scan would burn Railway credits.
So the DAILY tape is fetched ONCE per symbol (paginated), stored durably in
bot_kv (Supabase Postgres in prod / SQLite in dev), and every later scan only
pulls the small closed tail since the last save and merges it. 8h/12h stay
resamples of the direct 4h tape (630 bars = one call, no store needed).

Fail-open everywhere: any store error degrades to a plain direct fetch —
the scan must never die because history persistence hiccuped.
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

_KV_PREFIX = "deephist:daily:"
_MEMORY: Dict[str, tuple] = {}      # symbol -> (monotonic_at, frame)
_MEMORY_TTL = 600.0                 # seconds; the kv read is the expensive part
_MAX_ROWS = 2200                    # ~6 years of dailies — plenty for 1w×210


def _row_to_list(frame: pd.DataFrame) -> list:
    ts = pd.to_datetime(frame["timestamp"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    return [[int(t.timestamp() * 1000), float(o), float(h), float(l),
             float(c), float(v)]
            for t, o, h, l, c, v in zip(ts, frame["open"], frame["high"],
                                        frame["low"], frame["close"],
                                        frame.get("volume",
                                                  pd.Series([0.0] * len(frame))))]


def _list_to_frame(rows: list) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low",
                                        "close", "volume"])
    frame["timestamp"] = pd.to_datetime(frame["ts_ms"], unit="ms", utc=True)
    frame["timestamp"] = frame["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
    return frame[["timestamp", "open", "high", "low", "close", "volume"]]


def _load(symbol: str) -> Optional[pd.DataFrame]:
    try:
        from database.bot_kv import get_json
        payload = get_json(_KV_PREFIX + symbol.upper())
        if not payload or not payload.get("rows"):
            return None
        return _list_to_frame(payload["rows"])
    except Exception:
        return None


def _save(symbol: str, frame: pd.DataFrame) -> None:
    try:
        from database.bot_kv import set_json
        frame = frame.tail(_MAX_ROWS)
        set_json(_KV_PREFIX + symbol.upper(), {
            "saved_at": pd.Timestamp.utcnow().tz_localize(None).isoformat(),
            "rows": _row_to_list(frame),
        })
    except Exception:
        pass


def get_deep_daily(symbol: str, need: int) -> Optional[pd.DataFrame]:
    """The daily tape with ≥`need` bars: fetched deep ONCE, tail-refreshed
    after that. Returns None only when even the direct fetch fails — the
    caller then falls back to its own plain get_klines path."""
    symbol = str(symbol or "").upper()
    need = max(200, int(need or 200))
    import time as _t
    hit = _MEMORY.get(symbol)
    if hit and _t.monotonic() - hit[0] < _MEMORY_TTL and len(hit[1]) >= need:
        return hit[1].tail(need).reset_index(drop=True)

    frame = _load(symbol)
    fetched_full = False
    if frame is None or len(frame) < need:
        # ONE-TIME deep scan (paginated), plus headroom for future 1w growth.
        try:
            from data.fetcher import get_klines_paginated
            frame = get_klines_paginated(symbol, "1d",
                                         max(need + 220, 1500),
                                         closed_only=True)
            fetched_full = frame is not None and len(frame) > 0
        except Exception:
            frame = frame  # keep whatever the kv had
    else:
        # cheap tail refresh: only the closed bars since the last saved bar
        try:
            from data.fetcher import get_klines
            last = pd.Timestamp(frame["timestamp"].iloc[-1])
            gap_bars = max(1, int((pd.Timestamp.utcnow().tz_localize(None)
                                   - last).total_seconds() // 86400))
            tail = get_klines(symbol, "1d", min(30, gap_bars + 4),
                              closed_only=True, use_cache=False)
            if tail is not None and len(tail):
                merged = pd.concat([frame, tail], ignore_index=True)
                merged = merged.drop_duplicates("timestamp").sort_values(
                    "timestamp").reset_index(drop=True)
                if len(merged) > len(frame):
                    frame = merged
                    _save(symbol, frame)
        except Exception:
            pass
    if frame is None or frame.empty:
        return None
    if fetched_full:
        _save(symbol, frame)
    out = frame.tail(need).reset_index(drop=True)
    try:
        _MEMORY[symbol] = (_t.monotonic(), frame)
    except Exception:
        pass
    return out
