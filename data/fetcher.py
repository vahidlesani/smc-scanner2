from typing import Optional

import time
import requests
import pandas as pd

TF_MAP = {
    "1d": "D",
    "4h": "240",
    "1h": "60",
    "15m": "15",
}

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "smc-scanner/4"})


def get_klines(
    symbol: str,
    interval: str,
    limit: int = 200,
    closed_only: bool = True,
) -> Optional[pd.DataFrame]:
    if interval not in TF_MAP:
        print(f"Unknown interval: {interval}")
        return None

    bybit_interval = TF_MAP[interval]
    fetch_limit = min(max(limit + (1 if closed_only else 0), 1), 1000)

    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": bybit_interval,
        "limit": fetch_limit,
    }

    try:
        r = _SESSION.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        if data.get("retCode") != 0:
            print(f"Bybit error {symbol}: {data.get('retMsg')}")
            return None

        raw = (data.get("result") or {}).get("list") or []
        if not raw:
            return None

        # Bybit جدیدترین را اول می‌دهد
        raw = list(reversed(raw))

        df = pd.DataFrame(raw, columns=[
            "timestamp", "open", "high", "low", "close", "volume", "turnover"
        ])

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["timestamp"] = pd.to_datetime(
            pd.to_numeric(df["timestamp"], errors="coerce"),
            unit="ms",
        )

        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df = df.dropna().reset_index(drop=True)

        # آخرین ردیف کندلِ در حال تشکیل است
        if closed_only and len(df) > 1:
            df = df.iloc[:-1].reset_index(drop=True)

        if limit and len(df) > limit:
            df = df.iloc[-limit:].reset_index(drop=True)

        return df if not df.empty else None

    except Exception as e:
        print(f"Error fetching {symbol} {interval}: {e}")
        return None


def get_multi_tf(symbol: str) -> dict:
    data = {
        "1d": get_klines(symbol, "1d", 100),
        "4h": get_klines(symbol, "4h", 200),
        "1h": get_klines(symbol, "1h", 200),
        "15m": get_klines(symbol, "15m", 200),
    }
    time.sleep(0.05)
    return data
