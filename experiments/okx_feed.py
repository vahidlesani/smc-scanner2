"""OKX public candle feed with the same DataFrame schema as data.fetcher.

Used only for offline diagnosis/backtesting because the sandbox network is
geo-blocked from Bybit. Returns columns:
["timestamp", "open", "high", "low", "close", "volume", "turnover"]
with tz-naive UTC timestamps, oldest-first.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import requests

BASE = "https://www.okx.com"
BAR: Dict[str, str] = {"1d": "1D", "4h": "4H", "1h": "1H", "15m": "15m", "5m": "5m"}
CACHE_DIR = Path(__file__).parent / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)


def to_okx_symbol(symbol: str) -> str:
    s = symbol.upper().replace(".P", "")
    if s.endswith("USDT"):
        s = s[: -len("USDT")]
    return f"{s}-USDT-SWAP"


def _parse(rows) -> pd.DataFrame:
    rows = list(reversed(rows))  # OKX returns newest-first
    df = pd.DataFrame(
        [r[:8] for r in rows],
        columns=["timestamp", "open", "high", "low", "close", "volume", "vol_ccy", "turnover"],
    )
    for col in ["open", "high", "low", "close", "volume", "turnover"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(
        pd.to_numeric(df["timestamp"], errors="coerce"), unit="ms", utc=True
    ).dt.tz_localize(None)
    df = (
        df[["timestamp", "open", "high", "low", "close", "volume", "turnover"]]
        .dropna()
        .drop_duplicates("timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    return df


def fetch_okx_klines(symbol: str, timeframe: str, limit: int, pause: float = 0.12) -> Optional[pd.DataFrame]:
    inst = to_okx_symbol(symbol)
    bar = BAR[timeframe]
    collected, after = [], None
    remaining = int(limit) + 1  # extra row to be able to drop a forming candle
    while remaining > 0:
        batch = min(100, remaining)
        params = {"instId": inst, "bar": bar, "limit": str(batch)}
        if after:
            params["after"] = after  # records earlier than this ts
        resp = requests.get(f"{BASE}/api/v5/market/history-candles", params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != "0":
            raise RuntimeError(f"OKX error for {inst} {bar}: {payload}")
        rows = payload.get("data") or []
        if not rows:
            break
        collected.extend(rows)
        oldest_ts = min(int(x[0]) for x in rows)
        after = str(oldest_ts - 1)
        remaining -= len(rows)
        if len(rows) < batch:
            break
        time.sleep(pause)
    if not collected:
        return None
    df = _parse(collected)
    return df.iloc[-limit:].reset_index(drop=True)


def load_cached(symbol: str, timeframe: str, limit: int, refresh: bool = False) -> pd.DataFrame:
    key = f"{to_okx_symbol(symbol)}_{timeframe}_{limit}.csv"
    path = CACHE_DIR / key
    if path.exists() and not refresh:
        df = pd.read_csv(path, parse_dates=["timestamp"])
        return df
    df = fetch_okx_klines(symbol, timeframe, limit)
    if df is None:
        raise RuntimeError(f"No OKX data for {symbol} {timeframe}")
    df.to_csv(path, index=False)
    return df


def load_frames(symbol: str, style: str, days: int, refresh: bool = False):
    """Mirror analysis.backtest._load_frames counts, sourced from OKX."""
    if style == "SWING":
        counts = {"1d": max(150, days + 120), "4h": days * 6 + 180, "1h": days * 24 + 240, "15m": days * 96 + 300}
        trigger_tf = "15m"
    else:
        counts = {"1d": max(120, days + 90), "1h": days * 24 + 240, "15m": days * 96 + 300, "5m": days * 288 + 400}
        trigger_tf = "5m"
    frames = {tf: load_cached(symbol, tf, count, refresh=refresh) for tf, count in counts.items()}
    return frames, trigger_tf
