"""Ourbit public futures market-data client (MEXC-style contract API).

Viva trades on Ourbit, so candle data must come from the same venue whose
prices he actually executes. Everything here is public market data — no API
key required. If a symbol is not listed on Ourbit the caller falls back to
the Bybit client, so coverage never regresses.

Base URL: https://futures.ourbit.com
- GET /api/v1/contract/detail                 -> instrument list
- GET /api/v1/contract/kline/{SYMBOL_X_USDT}  -> klines (parallel arrays)
- GET /api/v1/contract/ticker                 -> 24h tickers
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = os.getenv("OURBIT_BASE_URL", "https://futures.ourbit.com").rstrip("/")

TF_MAP = {
    "1m": "Min1",
    "5m": "Min5",
    "15m": "Min15",
    "1h": "Min60",
    "4h": "Hour4",
    "1d": "Day1",
}
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "viva-signal-bot/7.6"})
_RETRY = Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=0.4,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY, pool_connections=12, pool_maxsize=12))

_RATE_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
_MIN_INTERVAL = float(os.getenv("OURBIT_MIN_REQUEST_INTERVAL", "0.06"))
_TIMEOUT = float(os.getenv("OURBIT_TIMEOUT_SECONDS", "10"))

_CACHE_LOCK = threading.Lock()
_CACHE: Dict[Tuple, Tuple[float, object]] = {}
_CONTRACT_LOCK = threading.Lock()
_CONTRACT_SYMBOLS: Optional[set] = None
_CONTRACT_FETCHED_AT = 0.0


def _throttle() -> None:
    global _LAST_REQUEST_AT
    with _RATE_LOCK:
        wait = _MIN_INTERVAL - (time.monotonic() - _LAST_REQUEST_AT)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_AT = time.monotonic()


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


def _get(path: str, params: Optional[Dict] = None) -> Optional[Dict]:
    try:
        _throttle()
        response = _SESSION.get(f"{BASE_URL}{path}", params=params or {}, timeout=_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, dict) or not payload.get("success"):
        return None
    return payload.get("data")


def to_ourbit_symbol(symbol: str) -> Optional[str]:
    """SOLUSDT -> SOL_USDT (USDT-quoted instruments only)."""
    symbol = (symbol or "").upper().strip()
    if symbol.endswith("USDT") and len(symbol) > 4:
        return f"{symbol[:-4]}_USDT"
    return None


def from_ourbit_symbol(symbol: str) -> str:
    return (symbol or "").replace("_", "").upper()


def get_contract_symbols(force: bool = False) -> set:
    """Cached set of tradeable perpetual symbols (e.g. {'BTC_USDT', ...})."""
    global _CONTRACT_SYMBOLS, _CONTRACT_FETCHED_AT
    with _CONTRACT_LOCK:
        fresh = (
            _CONTRACT_SYMBOLS is not None
            and time.monotonic() - _CONTRACT_FETCHED_AT < 6 * 3600
        )
        if fresh and not force:
            return set(_CONTRACT_SYMBOLS)
        data = _get("/api/v1/contract/detail")
        symbols = set()
        for item in data or []:
            raw = str(item.get("symbol", "")).upper()
            if not raw.endswith("_USDT"):
                continue
            # state 0 = enabled on MEXC-style engines; apiAllowed when present.
            state = item.get("state")
            api_allowed = item.get("apiAllowed", True)
            if state not in (None, 0) or not api_allowed:
                continue
            symbols.add(raw)
        if symbols:
            _CONTRACT_SYMBOLS = symbols
            _CONTRACT_FETCHED_AT = time.monotonic()
        return set(_CONTRACT_SYMBOLS or set())


def ourbit_listed(symbol: str) -> bool:
    ob = to_ourbit_symbol(symbol)
    return bool(ob) and ob in get_contract_symbols()


def _parse_klines(data: Dict) -> Optional[pd.DataFrame]:
    if not data or not data.get("time"):
        return None
    try:
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(pd.to_numeric(data["time"]), unit="s", utc=True),
                "open": pd.to_numeric(data["open"], errors="coerce"),
                "high": pd.to_numeric(data["high"], errors="coerce"),
                "low": pd.to_numeric(data["low"], errors="coerce"),
                "close": pd.to_numeric(data["close"], errors="coerce"),
                "volume": pd.to_numeric(data.get("vol") or data.get("volume"), errors="coerce"),
                "turnover": pd.to_numeric(data.get("amount"), errors="coerce"),
            }
        )
    except Exception:
        return None
    df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    if df["turnover"].isna().all():
        df["turnover"] = df["volume"] * df["close"]
    return df.dropna(subset=["open", "high", "low", "close"]).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def get_ourbit_klines(
    symbol: str,
    interval: str,
    limit: int = 200,
    closed_only: bool = True,
    end_s: Optional[int] = None,
) -> Optional[pd.DataFrame]:
    ob_symbol = to_ourbit_symbol(symbol)
    if not ob_symbol or interval not in TF_MAP:
        return None
    requested = min(max(int(limit), 1), 2000)
    fetch = min(requested + (1 if closed_only and end_s is None else 0), 2000)
    params: Dict[str, object] = {"interval": TF_MAP[interval], "limit": fetch}
    if end_s is not None:
        params["end"] = int(end_s)
        params["start"] = int(end_s) - fetch * TF_SECONDS[interval]
    key = ("ob_kline", ob_symbol, interval, requested, closed_only, end_s)
    if end_s is None:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    data = _get(f"/api/v1/contract/kline/{ob_symbol}", params)
    df = _parse_klines(data or {})
    if df is None or df.empty:
        return None
    if closed_only and end_s is None and len(df) > 1:
        df = df.iloc[:-1].reset_index(drop=True)
    if len(df) > requested:
        df = df.iloc[-requested:].reset_index(drop=True)
    if end_s is None:
        _cache_set(key, df, 45)
    return df


def get_ourbit_tickers() -> List[Dict]:
    key = ("ob_tickers",)
    cached = _cache_get(key)
    if cached is not None:
        return [dict(item) for item in cached]
    data = _get("/api/v1/contract/ticker")
    rows: List[Dict] = []
    for item in data or []:
        last = _f(item.get("lastPrice"))
        bid = _f(item.get("bid1"))
        ask = _f(item.get("ask1"))
        spread_pct = ((ask - bid) / ((ask + bid) / 2) * 100) if bid > 0 and ask > bid else None
        rows.append(
            {
                "symbol": from_ourbit_symbol(str(item.get("symbol", ""))),
                "ourbit_symbol": str(item.get("symbol", "")).upper(),
                "last_price": last,
                "turnover24h": _f(item.get("amount24")),
                "volume24h": _f(item.get("volume24")),
                "spread_pct": spread_pct,
                "funding_rate": _f(item.get("fundingRate")),
                "open_interest": _f(item.get("holdVol")) * last if last else 0.0,
                "price_change_24h": _f(item.get("riseFallRate")) * 100,
            }
        )
    if rows:
        _cache_set(key, rows, 60)
    return rows


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
