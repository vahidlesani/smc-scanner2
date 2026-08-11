import requests
import pandas as pd

# نگاشت نام نمادها از بایننس به بایبیت
SYMBOL_MAP = {
    "BTCUSDT": "BTCUSDT",
    "ETHUSDT": "ETHUSDT",
    "SOLUSDT": "SOLUSDT",
    "BNBUSDT": "BNBUSDT",
    "XRPUSDT": "XRPUSDT",
    "ADAUSDT": "ADAUSDT",
    "AVAXUSDT": "AVAXUSDT",
    "LINKUSDT": "LINKUSDT",
    "DOTUSDT": "DOTUSDT",
    "NEARUSDT": "NEARUSDT",
    "APTUSDT": "APTUSDT",
    "ARBUSDT": "ARBUSDT",
    "OPUSDT": "OPUSDT",
    "SUIUSDT": "SUIUSDT",
}

# نگاشت تایم‌فریم از بایننس به بایبیت
TF_MAP = {
    "1d": "D",
    "4h": "240",
    "1h": "60",
    "15m": "15",
}


def get_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    """
    دیتا از Bybit میگیره
    Bybit هیچ محدودیت جغرافیایی نداره
    """
    bybit_symbol = SYMBOL_MAP.get(symbol, symbol)
    bybit_interval = TF_MAP.get(interval, interval)
    
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": bybit_symbol,
        "interval": bybit_interval,
        "limit": limit
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        if data.get("retCode") != 0:
            print(f"Bybit error for {symbol}: {data.get('retMsg')}")
            return None
        
        raw = data["result"]["list"]
        
        if not raw:
            return None
        
        # Bybit داده رو برعکس میده (جدیدترین اول)
        raw = list(reversed(raw))
        
        df = pd.DataFrame(raw, columns=[
            "timestamp", "open", "high", "low", "close", "volume", "turnover"
        ])
        
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])
        
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df = df.reset_index(drop=True)
        
        return df
        
    except Exception as e:
        print(f"Error fetching {symbol} {interval}: {e}")
        return None


def get_multi_tf(symbol: str) -> dict:
    """
    چند تایم‌فریم همزمان میگیره
    """
    return {
        "1d":  get_klines(symbol, "1d",  100),
        "4h":  get_klines(symbol, "4h",  200),
        "1h":  get_klines(symbol, "1h",  200),
        "15m": get_klines(symbol, "15m", 200),
    }
