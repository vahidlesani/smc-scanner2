"""Dynamic Bybit watchlist based on tradability, turnover, spread and relative volume."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from config import get_settings
from data.fetcher import get_instruments, get_klines, get_tickers

SETTINGS = get_settings()

FALLBACK_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    "LTCUSDT", "BCHUSDT", "TRXUSDT", "TONUSDT", "SUIUSDT",
    "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "NEARUSDT",
    "ATOMUSDT", "AAVEUSDT", "UNIUSDT", "RENDERUSDT", "FETUSDT",
]


def _float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class DynamicUniverse:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._symbols: List[str] = []
        self._metrics: Dict[str, Dict] = {}
        self._updated_monotonic = 0.0

    def _is_fresh(self) -> bool:
        return bool(self._symbols) and (
            time.monotonic() - self._updated_monotonic
            < SETTINGS.watchlist_refresh_minutes * 60
        )

    def get(self, force: bool = False) -> Tuple[List[str], Dict[str, Dict]]:
        with self._lock:
            if not force and self._is_fresh():
                return list(self._symbols), {k: dict(v) for k, v in self._metrics.items()}
            symbols, metrics = self._build()
            self._symbols = symbols or list(FALLBACK_SYMBOLS)
            self._metrics = metrics
            self._updated_monotonic = time.monotonic()
            return list(self._symbols), {k: dict(v) for k, v in self._metrics.items()}

    def _build(self) -> Tuple[List[str], Dict[str, Dict]]:
        instruments = get_instruments()
        tickers = get_tickers(use_cache=False)
        if not instruments or not tickers:
            print("⚠️ Dynamic watchlist unavailable; using liquid fallback symbols")
            return list(FALLBACK_SYMBOLS), {}

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        minimum_age_ms = SETTINGS.watchlist_min_listing_days * 86_400_000
        tradable = set()
        for item in instruments:
            symbol = str(item.get("symbol", ""))
            launch_time = int(_float(item.get("launchTime"), 0))
            old_enough = not launch_time or now_ms - launch_time >= minimum_age_ms
            if (
                symbol.endswith("USDT")
                and item.get("quoteCoin") == "USDT"
                and item.get("status") == "Trading"
                and "Perpetual" in str(item.get("contractType", ""))
                and old_enough
            ):
                tradable.add(symbol)

        rows: List[Dict] = []
        for ticker in tickers:
            symbol = str(ticker.get("symbol", ""))
            if symbol not in tradable:
                continue
            bid = _float(ticker.get("bid1Price"))
            ask = _float(ticker.get("ask1Price"))
            last = _float(ticker.get("lastPrice"))
            turnover = _float(ticker.get("turnover24h"))
            volume = _float(ticker.get("volume24h"))
            spread_pct = ((ask - bid) / ((ask + bid) / 2) * 100) if bid > 0 and ask > bid else 999
            if (
                last <= 0
                or turnover < SETTINGS.watchlist_min_turnover_usd
                or spread_pct > SETTINGS.watchlist_max_spread_percent
            ):
                continue
            rows.append({
                "symbol": symbol,
                "turnover24h": turnover,
                "volume24h": volume,
                "spread_pct": spread_pct,
                "last_price": last,
                "price_change_24h": _float(ticker.get("price24hPcnt")) * 100,
                "funding_rate": _float(ticker.get("fundingRate")),
                "open_interest": _float(ticker.get("openInterestValue")),
                "relative_volume": 1.0,
            })

        rows.sort(key=lambda row: row["turnover24h"], reverse=True)
        prefiltered = rows[: SETTINGS.watchlist_prefilter_symbols]

        # Compare current rolling 24h turnover with recent closed daily turnover.
        # This admits temporarily active symbols even when they are not permanent majors.
        for row in prefiltered:
            daily = get_klines(row["symbol"], "1d", 10, closed_only=True)
            if daily is None or len(daily) < 4 or "turnover" not in daily:
                continue
            baseline = float(daily["turnover"].tail(7).median())
            if baseline > 0:
                row["relative_volume"] = row["turnover24h"] / baseline

        top_turnover = prefiltered[: SETTINGS.watchlist_top_turnover]
        top_relative = sorted(
            prefiltered,
            key=lambda row: (row["relative_volume"], row["turnover24h"]),
            reverse=True,
        )[: SETTINGS.watchlist_top_relative_volume]

        selected: List[Dict] = []
        seen = set()
        for row in top_turnover + top_relative:
            if row["symbol"] in seen:
                continue
            selected.append(row)
            seen.add(row["symbol"])
            if len(selected) >= SETTINGS.watchlist_max_symbols:
                break

        metrics = {row["symbol"]: dict(row) for row in selected}
        symbols = [row["symbol"] for row in selected]
        if symbols:
            rv_count = sum(1 for row in selected if row["relative_volume"] >= 1.5)
            print(
                f"📈 Dynamic watchlist: {len(symbols)} symbols "
                f"({rv_count} with relative volume ≥ 1.5x)"
            )
        return symbols, metrics


UNIVERSE = DynamicUniverse()
