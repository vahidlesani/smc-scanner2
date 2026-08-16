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

TF_MAP = {"1d": "D", "4h": "240", "1h": "60", "15m": "15", "5m": "5", "1m": "1"}

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
                    return frame
        except Exception as exc:  # never let a venue hiccup kill a scan
            _log_error_once(f"ourbit-route:{symbol}:{interval}", f"Ourbit route failed {symbol} {interval}: {exc}")
    return _get_klines_bybit(symbol, interval, limit, closed_only, use_cache, end_ms)


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


def get_market_bundle(
    symbol: str,
    timeframes=("1d", "4h", "1h", "15m", "5m"),
    limits: Optional[Dict[str, int]] = None,
    ticker: Optional[Dict] = None,
) -> MarketBundle:
    limits = limits or {"1d": 120, "4h": 240, "1h": 240, "15m": 240, "5m": 240}
    frames = {
        tf: get_klines(symbol, tf, limits.get(tf, 200), closed_only=True)
        for tf in timeframes
    }
    return MarketBundle(symbol=symbol.upper(), frames=frames, ticker=ticker or {})


def get_multi_tf(symbol: str) -> Dict[str, Optional[pd.DataFrame]]:
    """Backward-compatible helper. New code should fetch one MarketBundle."""
    return get_market_bundle(symbol, ("1d", "4h", "1h", "15m")).frames
