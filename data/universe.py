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

FIAT_CODES = {
    "USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD",
    "SEK", "NOK", "SGD", "HKD", "MXN", "ZAR", "TRY", "CNH",
}
STABLECOINS = {"USDT", "USDC", "USDE", "DAI", "FDUSD", "TUSD", "USD1"}
METAL_CODES = {"XAU", "XAG", "GOLD", "SILVER"}
COMMODITY_MARKERS = {"OIL", "WTI", "BRENT", "XBR", "XTI", "NATGAS", "COPPER"}
FOREX_PAIR_CODES = {
    "EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "NZDUSD",
    "USDCHF", "EURJPY", "EURGBP", "GBPJPY", "AUDJPY", "EURCHF",
}
MAJOR_EQUITY_CODES = {
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "GOOG",
    "AMD", "NFLX", "COIN", "MSTR", "PLTR", "AVGO", "JPM", "V", "MA",
    "SPY", "QQQ", "DIA", "IWM",
}


def _asset_class(instrument: Dict) -> str:
    symbol = str(instrument.get("symbol", "")).upper().replace("+", "")
    base = str(instrument.get("baseCoin", "")).upper()
    quote = str(instrument.get("quoteCoin", "")).upper()
    descriptor = " ".join(
        str(instrument.get(key, ""))
        for key in ("symbolType", "displayName", "contractType")
    ).upper()
    if (
        (base in FIAT_CODES and quote in FIAT_CODES and base not in STABLECOINS)
        or any(symbol.startswith(pair) for pair in FOREX_PAIR_CODES)
    ):
        return "FOREX"
    if base in METAL_CODES or any(marker in symbol for marker in METAL_CODES):
        return "METAL"
    if any(marker in symbol or marker in descriptor for marker in COMMODITY_MARKERS):
        return "COMMODITY"
    if (
        "STOCK" in descriptor
        or "EQUITY" in descriptor
        or "XSTOCK" in descriptor
        or base in MAJOR_EQUITY_CODES
        or any(symbol.startswith(code + "USDT") for code in MAJOR_EQUITY_CODES)
    ):
        return "EQUITY"
    if "TRADFI" in descriptor or "RWA" in descriptor:
        return "TRADFI"
    return "CRYPTO"


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
        tradable: Dict[str, Dict] = {}
        for item in instruments:
            symbol = str(item.get("symbol", "")).upper()
            launch_time = int(_float(item.get("launchTime"), 0))
            old_enough = not launch_time or now_ms - launch_time >= minimum_age_ms
            usdt_settled = (
                str(item.get("settleCoin", "")).upper() == "USDT"
                or str(item.get("quoteCoin", "")).upper() == "USDT"
            )
            if (
                symbol
                and usdt_settled
                and item.get("status") == "Trading"
                and "Perpetual" in str(item.get("contractType", ""))
                and old_enough
            ):
                normalized = dict(item)
                normalized["asset_class"] = _asset_class(item)
                tradable[symbol] = normalized

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
                or turnover < SETTINGS.watchlist_min_turnover_usd * 0.5
                or spread_pct > SETTINGS.watchlist_max_spread_percent
            ):
                continue
            instrument = tradable[symbol]
            leverage_filter = instrument.get("leverageFilter") or {}
            rows.append({
                "symbol": symbol,
                "venue": "BYBIT",
                "asset_class": instrument.get("asset_class", "CRYPTO"),
                "display_name": instrument.get("displayName") or symbol,
                "turnover24h": turnover,
                "trading_day_turnover": 0.0,
                "projected_day_turnover": 0.0,
                "volume24h": volume,
                "spread_pct": spread_pct,
                "last_price": last,
                "price_change_24h": _float(ticker.get("price24hPcnt")) * 100,
                "funding_rate": _float(ticker.get("fundingRate")),
                "open_interest": _float(ticker.get("openInterestValue")),
                "max_leverage": _float(leverage_filter.get("maxLeverage"), 20.0),
                "relative_volume": 1.0,
            })

        rows.sort(key=lambda row: row["turnover24h"], reverse=True)
        # Overall turnover prefilter plus reserved TradFi candidates prevents
        # liquid FX/metals/stocks from being crowded out by crypto majors.
        prefilter_pool = rows[: SETTINGS.watchlist_prefilter_symbols]
        forex_pool = [row for row in rows if row["asset_class"] == "FOREX"][:12]
        tradfi_pool = [row for row in rows if row["asset_class"] != "CRYPTO"][:40]
        prefiltered: List[Dict] = []
        prefilter_seen = set()
        for row in prefilter_pool + forex_pool + tradfi_pool:
            if row["symbol"] not in prefilter_seen:
                prefiltered.append(row)
                prefilter_seen.add(row["symbol"])

        # Rank on the current UTC trading day's actual turnover. Projecting the
        # day's pace avoids excluding every market shortly after 00:00 UTC.
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed_fraction = max((now - day_start).total_seconds() / 86_400, 0.10)
        liquid_today: List[Dict] = []
        for row in prefiltered:
            daily = get_klines(row["symbol"], "1d", 10, closed_only=False)
            if daily is None or len(daily) < 4 or "turnover" not in daily:
                continue
            timestamps = daily["timestamp"]
            current_mask = timestamps >= day_start.replace(tzinfo=None)
            if not bool(current_mask.any()):
                continue
            current_turnover = float(daily.loc[current_mask, "turnover"].iloc[-1])
            projected = current_turnover / elapsed_fraction
            completed = daily.loc[~current_mask, "turnover"].tail(7)
            baseline = float(completed.median()) if not completed.empty else 0.0
            row["trading_day_turnover"] = current_turnover
            row["projected_day_turnover"] = projected
            row["relative_volume"] = projected / baseline if baseline > 0 else 1.0
            if projected >= SETTINGS.watchlist_min_turnover_usd:
                liquid_today.append(row)

        liquid_today.sort(key=lambda row: row["trading_day_turnover"], reverse=True)
        top_turnover = liquid_today[: SETTINGS.watchlist_top_turnover]
        top_relative = sorted(
            liquid_today,
            key=lambda row: (row["relative_volume"], row["trading_day_turnover"]),
            reverse=True,
        )[: SETTINGS.watchlist_top_relative_volume]
        top_forex = [row for row in liquid_today if row["asset_class"] == "FOREX"][
            : SETTINGS.watchlist_max_forex_symbols
        ]
        top_tradfi = [
            row for row in liquid_today
            if row["asset_class"] not in {"CRYPTO", "FOREX"}
        ][: SETTINGS.watchlist_max_tradfi_symbols]

        selected: List[Dict] = []
        seen = set()
        forex_selected = 0
        for row in top_forex + top_tradfi + top_turnover + top_relative:
            if row["symbol"] in seen:
                continue
            if (
                row["asset_class"] == "FOREX"
                and forex_selected >= SETTINGS.watchlist_max_forex_symbols
            ):
                continue
            selected.append(row)
            seen.add(row["symbol"])
            if row["asset_class"] == "FOREX":
                forex_selected += 1
            if len(selected) >= SETTINGS.watchlist_max_symbols:
                break

        metrics = {row["symbol"]: dict(row) for row in selected}
        symbols = [row["symbol"] for row in selected]
        if symbols:
            rv_count = sum(1 for row in selected if row["relative_volume"] >= 1.5)
            forex_count = sum(1 for row in selected if row["asset_class"] == "FOREX")
            tradfi_count = sum(1 for row in selected if row["asset_class"] != "CRYPTO")
            print(
                f"📈 Dynamic watchlist: {len(symbols)} symbols by current-day liquidity "
                f"({rv_count} relative-volume ≥ 1.5x • {forex_count} FX • {tradfi_count} TradFi)"
            )
        return symbols, metrics


UNIVERSE = DynamicUniverse()
