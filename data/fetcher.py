"""Rate-aware Bybit market-data client with caching and endpoint fallback."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import get_settings

TF_MAP = {"1d": "D", "12h": "720", "8h": "360", "4h": "240", "2h": "120", "1h": "60", "30m": "30", "15m": "15", "5m": "5", "3m": "3", "1m": "1"}

_SETTINGS = get_settings()
_BASE_URLS = [
    item.strip().rstrip("/")
    for item in os.getenv(
        "BYBIT_BASE_URLS", "https://api.bybit.com,https://api.bytick.com"
    ).split(",")
    if item.strip()
]

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "viva-signal-bot/7.0"})
_PROXY_URL = os.getenv("BYBIT_PROXY_URL", "").strip()
if _PROXY_URL:
    # Optional static outbound proxy for cloud IPs explicitly approved for the
    # deployment. Never put proxy credentials in source control.
    _SESSION.proxies.update({"http": _PROXY_URL, "https": _PROXY_URL})
_RETRY = Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY, pool_connections=20, pool_maxsize=20))

_RATE_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
_CACHE_LOCK = threading.Lock()
_CACHE: Dict[Tuple, Tuple[float, object]] = {}
_LAST_ERROR: Dict[str, float] = {}


@dataclass
class MarketBundle:
    symbol: str
    frames: Dict[str, Optional[pd.DataFrame]] = field(default_factory=dict)
    ticker: Dict = field(default_factory=dict)

    def get(self, timeframe: str) -> Optional[pd.DataFrame]:
        return self.frames.get(timeframe)


# ── Round-15 (Viva 09-21): «برای صرفه‌جویی مصرف هم ببین استفاده الکی نداشته
# باشیم» — a CLOSED candle cannot change until its own timeframe closes, yet the
# old cache lived 45 seconds, so every 5-minute discovery pass re-downloaded and
# re-analysed the very same closed candles for all 40–47 symbols. The cache now
# lives exactly as long as the candle itself (capped at 30 minutes for safety).
_TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
               "1h": 3600, "2h": 7200, "4h": 14400, "8h": 28800, "12h": 43200,
               "1d": 86400,
               # ── round 15 (Viva 09-22): the SPOT engine scans 4h/1d/3d/1w and
               # no venue serves 3d/1w, so those two are AGGREGATED locally
               # from the daily tape (see _aggregate_daily).
               "3d": 259200, "1w": 604800}
_AGG_FROM_DAILY = {"3d": 3, "1w": 7}


def _aggregate_daily(frame: pd.DataFrame, k: int) -> Optional[pd.DataFrame]:
    """Fold k closed daily candles into one 3d/1w candle (no partial bucket).

    Only COMPLETE buckets are emitted, so a 3d/1w candle is never a half-formed
    bar pretending to be closed — the confirmation law («کلوز معتبر») stays
    honest on the spot timeframes.
    """
    try:
        if frame is None or frame.empty:
            return None
        d = frame.reset_index(drop=True).copy()
        d["timestamp"] = pd.to_datetime(d["timestamp"])
        d = d.sort_values("timestamp")
        # ── buckets are EPOCH-ALIGNED (every calendar k-th day), never aligned
        # to the fetch window: a window-aligned bucket would shift its open/
        # close every time the lookback changed, which is exactly how a 3d bar
        # can disagree with the daily tape it came from.
        _day_index = (d["timestamp"].astype("int64") // 86_400_000_000_000)
        d["_g"] = (_day_index // k).astype("int64")
        if d.empty or len(d) < k * 2:
            return None
        rows = []
        for _, g in d.groupby("_g"):
            if len(g) < k:
                continue
            rows.append({
                "timestamp": pd.Timestamp(g["timestamp"].iloc[0]),
                "open": float(g["open"].iloc[0]),
                "high": float(g["high"].max()),
                "low": float(g["low"].min()),
                "close": float(g["close"].iloc[-1]),
                "volume": float(g["volume"].sum()) if "volume" in g else 0.0,
            })
        if not rows:
            return None
        return pd.DataFrame(rows)
    except Exception as exc:
        print(f"aggregate warning: {exc}")
        return None

_COST = {"kline_calls": 0, "kline_cache_hits": 0}


def closed_candle_ttl(interval: str, cap: int = 1800) -> int:
    """Seconds until this timeframe's next close (min 20s, max `cap`)."""
    try:
        sec = int(_TF_SECONDS.get(str(interval).lower(), 300))
        remaining = int(sec - (time.time() % sec)) + 2
        return int(max(20, min(remaining, cap)))
    except Exception:
        return 45


def cost_counters() -> dict:
    return dict(_COST)


def _throttle() -> None:
    global _LAST_REQUEST_AT
    with _RATE_LOCK:
        wait = _SETTINGS.bybit_min_request_interval - (time.monotonic() - _LAST_REQUEST_AT)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_AT = time.monotonic()


def _log_error_once(key: str, message: str, cooldown: int = 60) -> None:
    now = time.monotonic()
    if now - _LAST_ERROR.get(key, 0) >= cooldown:
        print(message)
        _LAST_ERROR[key] = now


def _cache_get(key: Tuple):
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if not item or item[0] <= time.monotonic():
            if item:
                _CACHE.pop(key, None)
            return None
        value = item[1]
        return value.copy(deep=True) if isinstance(value, pd.DataFrame) else value


def _cache_set(key: Tuple, value, ttl: int) -> None:
    stored = value.copy(deep=True) if isinstance(value, pd.DataFrame) else value
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic() + ttl, stored)
        if len(_CACHE) > 400:   # Railway RAM guard (Viva 09-16): hard cap
            for _k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:len(_CACHE) - 400]:
                _CACHE.pop(_k, None)


def clear_market_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _request(path: str, params: Dict) -> Optional[Dict]:
    last_error = ""
    for base in _BASE_URLS:
        url = f"{base}{path}"
        try:
            _throttle()
            response = _SESSION.get(url, params=params, timeout=_SETTINGS.bybit_timeout_seconds)
            if response.status_code in (403, 451):
                last_error = f"HTTP {response.status_code} from {base}"
                continue
            response.raise_for_status()
            payload = response.json()
            if payload.get("retCode") != 0:
                last_error = str(payload.get("retMsg") or "unknown Bybit error")
                continue
            return payload
        except Exception as exc:
            last_error = str(exc)
    _log_error_once(
        f"{path}:{params.get('symbol', '')}",
        f"Bybit request failed {path} {params.get('symbol', '')}: {last_error}",
    )
    return None


def _parse_klines(raw: List[List]) -> Optional[pd.DataFrame]:
    if not raw:
        return None
    rows = list(reversed(raw))
    df = pd.DataFrame(
        rows,
        columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"],
    )
    for col in ["open", "high", "low", "close", "volume", "turnover"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(
        pd.to_numeric(df["timestamp"], errors="coerce"), unit="ms", utc=True
    ).dt.tz_localize(None)
    return df.dropna().drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def get_klines(
    symbol: str,
    interval: str,
    limit: int = 200,
    closed_only: bool = True,
    use_cache: bool = True,
    end_ms: Optional[int] = None,
) -> Optional[pd.DataFrame]:
    global _COST
    # ── 3d / 1w exist only as AGGREGATES of the daily tape (round 15 spot)
    _iv = str(interval).lower()
    if _iv in _AGG_FROM_DAILY:
        _k = int(_AGG_FROM_DAILY[_iv])
        _base = get_klines(symbol, "1d", min(1000, int(limit) * _k + _k + 2),
                           closed_only=closed_only, use_cache=use_cache)
        _agg = _aggregate_daily(_base, _k)
        if _agg is not None and int(limit) > 0:
            _agg = _agg.tail(int(limit)).reset_index(drop=True)
        return _agg
    _route_key = ("route", str(symbol).upper(), str(interval).lower(),
                  int(limit), bool(closed_only))
    if use_cache and end_ms is None:
        cached = _cache_get(_route_key)
        if cached is not None and not cached.empty:
            _COST["kline_cache_hits"] += 1
            return cached
    _COST["kline_calls"] += 1
    """Fetch candles for `symbol` — Ourbit first (Viva's execution venue),
    Bybit as fallback for symbols Ourbit doesn't list.

    Data provider precedence is env-driven:
    DATA_PROVIDER=ourbit  -> ourbit-then-bybit (default)
    DATA_PROVIDER=bybit   -> bybit only
    """
    provider = os.getenv("DATA_PROVIDER", "ourbit").strip().lower()
    if provider != "bybit":
        try:
            from data.ourbit import get_ourbit_klines, ourbit_listed

            if ourbit_listed(symbol):
                frame = get_ourbit_klines(
                    symbol,
                    interval,
                    limit=limit,
                    closed_only=closed_only,
                    end_s=int(end_ms / 1000) if end_ms else None,
                )
                if frame is not None and not frame.empty:
                    if use_cache and end_ms is None:
                        _cache_set(_route_key, frame,
                                   closed_candle_ttl(interval) if closed_only
                                   else _SETTINGS.bybit_cache_seconds)
                    return frame
        except Exception as exc:  # never let a venue hiccup kill a scan
            _log_error_once(f"ourbit-route:{symbol}:{interval}", f"Ourbit route failed {symbol} {interval}: {exc}")
    frame = _get_klines_bybit(symbol, interval, limit, closed_only, use_cache, end_ms)
    if frame is not None and not frame.empty and use_cache and end_ms is None:
        _cache_set(_route_key, frame,
                   closed_candle_ttl(interval) if closed_only
                   else _SETTINGS.bybit_cache_seconds)
    return frame


def _get_klines_bybit(
    symbol: str,
    interval: str,
    limit: int = 200,
    closed_only: bool = True,
    use_cache: bool = True,
    end_ms: Optional[int] = None,
) -> Optional[pd.DataFrame]:
    """Fetch up to 1000 bars. Use get_klines_paginated for longer history."""
    if interval not in TF_MAP:
        _log_error_once(f"interval:{interval}", f"Unknown interval: {interval}")
        return None
    requested = min(max(int(limit), 1), 1000)
    key = ("kline", symbol.upper(), interval, requested, closed_only, end_ms)
    if use_cache and end_ms is None:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    fetch_limit = min(requested + (1 if closed_only and end_ms is None else 0), 1000)
    params = {
        "category": "linear",
        "symbol": symbol.upper(),
        "interval": TF_MAP[interval],
        "limit": fetch_limit,
    }
    if end_ms is not None:
        params["end"] = int(end_ms)
    payload = _request("/v5/market/kline", params)
    raw = ((payload or {}).get("result") or {}).get("list") or []
    df = _parse_klines(raw)
    if df is None or df.empty:
        return None

    # With no historical end, the newest row is the currently forming candle.
    if closed_only and end_ms is None and len(df) > 1:
        df = df.iloc[:-1].reset_index(drop=True)
    if len(df) > requested:
        df = df.iloc[-requested:].reset_index(drop=True)
    if use_cache and end_ms is None:
        _cache_set(key, df, _SETTINGS.bybit_cache_seconds)
    return df


def get_klines_paginated(
    symbol: str, interval: str, limit: int, closed_only: bool = True
) -> Optional[pd.DataFrame]:
    """Fetch historical bars backwards without silently truncating at 1000."""
    remaining = max(1, int(limit))
    frames: List[pd.DataFrame] = []
    end_ms: Optional[int] = None
    first = True
    while remaining > 0:
        batch_size = min(remaining + (1 if first and closed_only else 0), 1000)
        frame = get_klines(
            symbol,
            interval,
            batch_size,
            closed_only=closed_only if first else False,
            use_cache=first,
            end_ms=end_ms,
        )
        if frame is None or frame.empty:
            break
        frames.append(frame)
        remaining -= len(frame)
        oldest = pd.Timestamp(frame["timestamp"].iloc[0])
        end_ms = int(oldest.timestamp() * 1000) - 1
        first = False
        if len(frame) < min(batch_size, 1000):
            break
    if not frames:
        return None
    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return result.iloc[-limit:].reset_index(drop=True)


def get_tickers(use_cache: bool = True) -> List[Dict]:
    key = ("tickers", "linear")
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return [dict(item) for item in cached]
    payload = _request("/v5/market/tickers", {"category": "linear"})
    items = ((payload or {}).get("result") or {}).get("list") or []
    result = [dict(item) for item in items]
    if result:
        _cache_set(key, result, 60)
    return result


def get_instruments(use_cache: bool = True) -> List[Dict]:
    key = ("instruments", "linear")
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return [dict(item) for item in cached]
    cursor = ""
    result: List[Dict] = []
    while True:
        params = {"category": "linear", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        payload = _request("/v5/market/instruments-info", params)
        block = (payload or {}).get("result") or {}
        result.extend(dict(item) for item in (block.get("list") or []))
        cursor = block.get("nextPageCursor") or ""
        if not cursor:
            break
    if result:
        _cache_set(key, result, 6 * 3600)
    return result


def _resample_ohlcv(frame: Optional[pd.DataFrame], rule: str, min_bars: int) -> Optional[pd.DataFrame]:
    """Build a higher closed candle locally from a lower structural tape.

    The input timestamps are candle-open timestamps. Buckets are therefore
    left-labeled/left-closed, and incomplete first/last buckets are discarded.
    This is used only where the source timeframe has enough history; long
    history (1D) remains a direct tape so 3D/1W patterns do not silently lose
    context.
    """
    try:
        if frame is None or frame.empty:
            return None
        d = frame.copy()
        d["timestamp"] = pd.to_datetime(d["timestamp"])
        d = d.sort_values("timestamp").drop_duplicates("timestamp")
        d = d.set_index("timestamp")
        agg = d.resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}
        )
        counts = d["close"].resample(rule, label="left", closed="left").count()
        expected = max(1, int(min_bars))
        agg = agg[counts >= expected].dropna(subset=["open", "high", "low", "close"])
        if agg.empty:
            return None
        return agg.reset_index().reset_index(drop=True)
    except Exception as exc:
        _log_error_once(f"resample:{rule}", f"local resample failed {rule}: {exc}")
        return None


def _derive_from_base(
    base_15m: Optional[pd.DataFrame],
    base_4h: Optional[pd.DataFrame],
    daily: Optional[pd.DataFrame],
    requested: tuple,
    limits: Dict[str, int],
) -> Dict[str, Optional[pd.DataFrame]]:
    """Derive exact multiples locally where this saves a venue request.

    5m is always a real venue tape (never reconstructed from 15m).
    1h/30m come from 15m; 8h/12h come from 4h; 3d/1w come from 1d.
    4h and 1d themselves remain direct because they carry the long structural
    history required by the pattern engine.
    """
    out: Dict[str, Optional[pd.DataFrame]] = {}
    for tf in requested:
        if tf == "5m":
            out[tf] = base_5m if False else None
        elif tf == "15m":
            out[tf] = base_15m
        elif tf == "4h":
            out[tf] = base_4h
        elif tf == "1d":
            out[tf] = daily
        elif tf == "1h":
            out[tf] = _resample_ohlcv(base_15m, "1h", 4)
        elif tf == "30m":
            out[tf] = _resample_ohlcv(base_15m, "30min", 2)
        elif tf == "8h":
            out[tf] = _resample_ohlcv(base_4h, "8h", 2)
        elif tf == "12h":
            out[tf] = _resample_ohlcv(base_4h, "12h", 3)
        elif tf == "3d":
            out[tf] = _aggregate_daily(daily, 3)
        elif tf == "1w":
            out[tf] = _aggregate_daily(daily, 7)
    return out


def get_market_bundle(
    symbol: str,
    timeframes=("1d", "4h", "1h", "15m", "5m"),
    limits: Optional[Dict[str, int]] = None,
    ticker: Optional[Dict] = None,
) -> MarketBundle:
    """Fetch the smallest honest base set, then derive safe higher multiples.

    Cost/accuracy law:
      * 5m is fetched directly — it cannot be reconstructed from 15m.
      * 15m is fetched directly and is the operational LTF source.
      * 1h/30m are resampled from 15m.
      * 8h/12h are resampled from the direct 4h structural tape.
      * 3d/1w are resampled from the direct 1d macro tape.
      * 4h/1d stay direct because reconstructing enough long history from 5m/15m
        would require pagination and more API calls, not fewer.

    The returned API remains the same MarketBundle, so Telegram formats,
    lineage links and unique IDs are untouched.
    """
    requested = tuple(dict.fromkeys(str(tf).lower() for tf in (timeframes or ())))
    limits = limits or {}
    need_5m = "5m" in requested or bool(requested)
    need_15m = any(tf in requested for tf in ("15m", "30m", "1h"))
    need_4h = any(tf in requested for tf in ("4h", "8h", "12h"))
    need_1d = any(tf in requested for tf in ("1d", "3d", "1w"))

    base_5m = get_klines(
        symbol, "5m", max(300, int(limits.get("5m", 300))), closed_only=True
    ) if need_5m else None
    base_15m = get_klines(
        symbol, "15m", max(200, int(limits.get("15m", 200))), closed_only=True
    ) if need_15m or need_5m else None
    base_4h = get_klines(
        symbol, "4h", max(60, int(limits.get("4h", 170))), closed_only=True
    ) if need_4h else None

    # 1D is the economical long-history anchor. For 3D/1W, request enough
    # daily bars to produce the requested number of complete higher bars.
    daily_need = int(limits.get("1d", 120))
    daily_need = max(daily_need, int(limits.get("3d", 45)) * 3 + 6)
    daily_need = max(daily_need, int(limits.get("1w", 45)) * 7 + 7)
    daily = get_klines(symbol, "1d", daily_need, closed_only=True) if need_1d else None

    # Direct fallbacks for unusual requested frames not covered by the local
    # resampler. They preserve backward compatibility without changing callers.
    frames = _derive_from_base(base_15m, base_4h, daily, requested, limits)
    for tf in requested:
        if frames.get(tf) is None and tf not in ("5m", "15m", "4h", "1d", "1h", "30m", "8h", "12h", "3d", "1w"):
            frames[tf] = get_klines(symbol, tf, int(limits.get(tf, 200)), closed_only=True)
    # 5m is direct; keep it separate from _derive_from_base to make the
    # impossible 15m→5m reconstruction explicit.
    if "5m" in requested:
        frames["5m"] = base_5m
    return MarketBundle(symbol=symbol.upper(), frames=frames, ticker=ticker or {})


def get_multi_tf(symbol: str) -> Dict[str, Optional[pd.DataFrame]]:
    """Backward-compatible helper. New code should fetch one MarketBundle."""
    return get_market_bundle(symbol, ("1d", "4h", "1h", "15m", "5m")).frames


def get_multi_tf(symbol: str) -> Dict[str, Optional[pd.DataFrame]]:
    """Backward-compatible helper. New code should fetch one MarketBundle."""
    return get_market_bundle(symbol, ("1d", "4h", "1h", "15m")).frames
