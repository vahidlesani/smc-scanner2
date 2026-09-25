"""Historical OHLCV loader for the walk-forward replay (R31.5).

Primary source: Binance USDT-M futures public archive (data.binance.vision),
monthly zips for complete months + daily zips for the current month. Fallback:
OKX history-candles (same schema). Output schema == data.fetcher.get_klines:
["timestamp","open","high","low","close","volume","turnover"], tz-naive UTC
candle-OPEN timestamps, oldest first.

The sandbox that develops this code is geo-blocked from every exchange; the
loader is exercised inside GitHub Actions (.github/workflows/replay.yml). A
parquet/csv cache keeps re-runs cheap; the cache dir is git-ignored.
"""
from __future__ import annotations

import io
import os
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

VISION = "https://data.binance.vision/data/futures/um"
CACHE = Path(os.getenv("REPLAY_CACHE_DIR", Path(__file__).parent / "data_cache" / "replay"))
COLS = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]
_SESSION = requests.Session()


def _get(url: str, tries: int = 3) -> Optional[bytes]:
    for i in range(tries):
        try:
            r = _SESSION.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.5 * (i + 1))
    return None


def _parse_zip(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = zf.namelist()[0]
        raw = zf.read(name).decode("utf-8", "replace")
    first = raw.split("\n", 1)[0]
    header = 0 if first and not first[0].isdigit() else None
    df = pd.read_csv(io.StringIO(raw), header=header)
    df = df.iloc[:, :8]
    df.columns = ["open_time", "open", "high", "low", "close", "volume", "close_time", "turnover"]
    ot = pd.to_numeric(df["open_time"], errors="coerce")
    unit = "us" if ot.max() > 10**14 else "ms"
    out = pd.DataFrame({
        "timestamp": pd.to_datetime(ot, unit=unit, utc=True).dt.tz_localize(None),
        "open": pd.to_numeric(df["open"], errors="coerce"),
        "high": pd.to_numeric(df["high"], errors="coerce"),
        "low": pd.to_numeric(df["low"], errors="coerce"),
        "close": pd.to_numeric(df["close"], errors="coerce"),
        "volume": pd.to_numeric(df["volume"], errors="coerce"),
        "turnover": pd.to_numeric(df["turnover"], errors="coerce"),
    })
    return out.dropna()


def _months(start: date, end: date) -> List[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month // 12), d.month % 12 + 1, 1)
    return out


def load_vision(symbol: str, tf: str, start: date, end: date) -> Optional[pd.DataFrame]:
    """Monthly archives where the month is complete, daily archives after."""
    parts: List[pd.DataFrame] = []
    today = datetime.utcnow().date()
    for m in _months(start, end):
        nxt = date(m.year + (m.month // 12), m.month % 12 + 1, 1)
        if nxt <= today - timedelta(days=1):
            url = f"{VISION}/monthly/klines/{symbol}/{tf}/{symbol}-{tf}-{m:%Y-%m}.zip"
            blob = _get(url)
            if blob is not None:
                parts.append(_parse_zip(blob))
                continue
        d = max(m, start)
        while d < nxt and d <= end:
            url = f"{VISION}/daily/klines/{symbol}/{tf}/{symbol}-{tf}-{d:%Y-%m-%d}.zip"
            blob = _get(url)
            if blob is not None:
                parts.append(_parse_zip(blob))
            d += timedelta(days=1)
    if not parts:
        return None
    df = pd.concat(parts, ignore_index=True)
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    lo, hi = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
    return df[(df["timestamp"] >= lo) & (df["timestamp"] < hi)].reset_index(drop=True)


def load_okx(symbol: str, tf: str, start: date, end: date) -> Optional[pd.DataFrame]:
    bar = {"1d": "1Dutc", "4h": "4Hutc", "1h": "1H", "30m": "30m", "15m": "15m", "5m": "5m"}[tf]
    inst = symbol.upper().replace("USDT", "") + "-USDT-SWAP"
    rows, after = [], str(int((pd.Timestamp(end) + pd.Timedelta(days=1)).timestamp() * 1000))
    stop = int(pd.Timestamp(start).timestamp() * 1000)
    for _ in range(3000):
        try:
            r = _SESSION.get("https://www.okx.com/api/v5/market/history-candles",
                             params={"instId": inst, "bar": bar, "limit": "100", "after": after},
                             timeout=30)
            data = r.json().get("data") or []
        except Exception:
            return None
        if not data:
            break
        rows.extend(data)
        oldest = min(int(x[0]) for x in data)
        if oldest <= stop:
            break
        after = str(oldest)
        time.sleep(0.11)
    if not rows:
        return None
    df = pd.DataFrame([x[:8] for x in rows],
                      columns=["ts", "open", "high", "low", "close", "volume", "vc", "turnover"])
    out = pd.DataFrame({"timestamp": pd.to_datetime(pd.to_numeric(df["ts"]), unit="ms")})
    for c in ("open", "high", "low", "close", "volume", "turnover"):
        out[c] = pd.to_numeric(df[c], errors="coerce")
    out = out.dropna().drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return out[out["timestamp"] >= pd.Timestamp(start)].reset_index(drop=True)


def load(symbol: str, tf: str, start: date, end: date) -> Optional[pd.DataFrame]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{symbol}_{tf}_{start:%Y%m%d}_{end:%Y%m%d}.csv.gz"
    if path.exists():
        df = pd.read_csv(path, parse_dates=["timestamp"])
        return df[COLS]
    df = load_vision(symbol, tf, start, end)
    src = "binance-vision"
    if df is None or df.empty:
        df = load_okx(symbol, tf, start, end)
        src = "okx"
    if df is None or df.empty:
        print(f"[data] {symbol} {tf}: NO DATA")
        return None
    df = df[COLS]
    df.to_csv(path, index=False, compression="gzip")
    print(f"[data] {symbol} {tf}: {len(df)} bars from {src} "
          f"{df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")
    return df
