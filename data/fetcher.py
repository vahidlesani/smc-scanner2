import requests
import pandas as pd

TF_MAP = {
    "1d": "1D",
    "4h": "4H",
    "1h": "1H",
    "15m": "15m",
}

SYMBOL_MAP = {
    "BTCUSDT": "BTC-USDT-SWAP",
    "ETHUSDT": "ETH-USDT-SWAP",
    "SOLUSDT": "SOL-USDT-SWAP",
    "BNBUSDT": "BNB-USDT-SWAP",
    "XRPUSDT": "XRP-USDT-SWAP",
    "ADAUSDT": "ADA-USDT-SWAP",
    "AVAXUSDT": "AVAX-USDT-SWAP",
    "LINKUSDT": "LINK-USDT-SWAP",
    "DOTUSDT": "DOT-USDT-SWAP",
    "NEARUSDT": "NEAR-USDT-SWAP",
    "APTUSDT": "APT-USDT-SWAP",
    "ARBUSDT": "ARB-USDT-SWAP",
    "OPUSDT": "OP-USDT-SWAP",
    "SUIUSDT": "SUI-USDT-SWAP",
    "TONUSDT": "TON-USDT-SWAP",
    "DOGEUSDT": "DOGE-USDT-SWAP",
    "MATICUSDT": "MATIC-USDT-SWAP",
    "LTCUSDT": "LTC-USDT-SWAP",
    "ATOMUSDT": "ATOM-USDT-SWAP",
    "INJUSDT": "INJ-USDT-SWAP",
}


def get_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    okx_symbol = SYMBOL_MAP.get(symbol, symbol)
    okx_interval = TF_MAP.get(interval, interval)

    url = "https://www.okx.com/api/v5/market/candles"
    params = {
        "instId": okx_symbol,
        "bar": okx_interval,
        "limit": min(limit, 300)
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        if data.get("code") != "0":
            print(f"OKX error {symbol}: {data.get('msg')}")
            return None

        raw = data.get("data", [])
        if not raw:
            return None

        raw = list(reversed(raw))

        df = pd.DataFrame(raw, columns=[
            "timestamp", "open", "high", "low", "close",
            "volume", "volCcy", "volCcyQuote", "confirm"
        ])

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])

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
