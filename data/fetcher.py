import requests
import pandas as pd
from datetime import datetime

def get_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    """
    دیتا از بایننس فیوچرز میگیره و DataFrame برمیگردونه
    """
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        raw = r.json()
        
        df = pd.DataFrame(raw, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        
        # تبدیل به عدد
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
    HTF: روز برای bias کلی
    MTF: 4h برای ساختار
    LTF: 15m برای entry
    """
    return {
        "1d":  get_klines(symbol, "1d",  100),
        "4h":  get_klines(symbol, "4h",  200),
        "1h":  get_klines(symbol, "1h",  200),
        "15m": get_klines(symbol, "15m", 200),
    }
