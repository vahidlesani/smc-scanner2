"""Small deployment diagnostic for Bybit connectivity and response quality."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fetcher import get_instruments, get_klines, get_tickers


def main() -> int:
    instruments = get_instruments(use_cache=False)
    tickers = get_tickers(use_cache=False)
    candles = get_klines("BTCUSDT", "15m", 5, use_cache=False)
    print(f"instruments={len(instruments)}")
    print(f"tickers={len(tickers)}")
    print(f"btc_15m_bars={0 if candles is None else len(candles)}")
    if not instruments or not tickers or candles is None:
        print(
            "FAILED: check deployment region, Bybit service restrictions, cloud-IP policy, "
            "and optional BYBIT_PROXY_URL. This is often a network 403 rather than rate limiting."
        )
        return 1
    print("OK: Bybit public market data is reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
