import psycopg2-binary
import requests
import pandas as pd

TF_MAP = {
    "1d": "D",
    "4h": "240",
    "1h": "60",
    "15m": "15",
}

SYMBOLS_LIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "NEARUSDT",
    "APTUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT", "TONUSDT",
    "DOGEUSDT", "MATICUSDT", "LTCUSDT", "ATOMUSDT", "INJUSDT",
]


def get_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    bybit_interval = TF_MAP.get(interval, interval)

    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": bybit_interval,
        "limit": min(limit, 200)
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        if data.get("retCode") != 0:
            print(f"Bybit error {symbol}: {data.get('retMsg')}")
            return None

        raw = data["result"]["list"]
        if not raw:
            return None

        # Bybit جدیدترین رو اول میده، برعکس میکنیم
        raw = list(reversed(raw))

        df = pd.DataFrame(raw, columns=[
            "timestamp", "open", "high", "low", "close", "volume", "turnover"
        ])

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])

        # رفع FutureWarning - اول به عدد تبدیل میکنیم
        df["timestamp"] = pd.to_numeric(df["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df = df.reset_index(drop=True)

        return df

    except Exception as e:
        print(f"Error fetching {symbol} {interval}: {e}")
        return None


def get_multi_tf(symbol: str) -> dict:
    return {
        "1d":  get_klines(symbol, "1d",  100),
        "4h":  get_klines(symbol, "4h",  200),
        "1h":  get_klines(symbol, "1h",  200),
        "15m": get_klines(symbol, "15m", 200),
    }
