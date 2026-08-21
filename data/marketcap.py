"""Independent crypto market-cap eligibility whitelist.

A volume ranking alone can surface tokenized stocks/RWA wrappers. This module
keeps the scanner universe to native crypto assets that are currently within a
broad market-cap ranking, with a deterministic fallback when the public source
is unavailable.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Set

import requests

_STABLE = {"USDT","USDC","USDE","DAI","FDUSD","TUSD","PYUSD","USD1","USDS","BUSD"}
_FALLBACK = (
    "BTC ETH XRP BNB SOL DOGE TRX ADA HYPE BCH SUI LINK AVAX XMR TON LTC DOT AAVE UNI NEAR APT ATOM INJ OP ARB SEI TIA ENA ONDO RENDER FET ICP ETC FIL CRV MKR LDO RUNE JUP PENDLE DYDX WLD PEPE SHIB BONK FLOKI GALA SAND MANA WIF TAO KAS ALGO VET XLM HBAR QNT FTM IMX GRT STX EOS THETA AXS KAVA COMP SNX ZEC DASH 1INCH".split()
)
_CACHE: Set[str] = set()
_AT = 0.0
_LOCK = threading.Lock()
_TTL = int(os.getenv("MARKETCAP_CACHE_SECONDS", "21600"))


def top_crypto_bases(limit: int = 80) -> Set[str]:
    global _CACHE, _AT
    with _LOCK:
        if _CACHE and time.monotonic() - _AT < _TTL:
            return set(_CACHE)
        bases: Set[str] = set()
        try:
            response = requests.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency":"usd","order":"market_cap_desc","per_page":min(250, max(80, limit + 20)),"page":1,"sparkline":"false"},
                timeout=12,
                headers={"User-Agent":"viva-signal-bot/9"},
            )
            response.raise_for_status()
            for row in response.json():
                symbol = str(row.get("symbol") or "").upper()
                if symbol and symbol not in _STABLE:
                    bases.add(symbol)
                if len(bases) >= limit:
                    break
        except Exception:
            bases = set(_FALLBACK[:limit])
        _CACHE, _AT = bases, time.monotonic()
        return set(bases)
