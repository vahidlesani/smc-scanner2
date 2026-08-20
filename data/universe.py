"""Dynamic Bybit watchlist based on tradability, turnover, spread and relative volume."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

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
METAL_CODES = {"XAU", "XAG", "GOLD", "SILVER", "PAXG", "XAUT"}
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

# Tokenized stocks/ETFs and synthetic RWA contracts must never enter the
# crypto scanner even if a venue reports them with a USDT suffix.
TOKENIZED_NONCRYPTO_BASES = {
    "AAPL", "AMZN", "AMD", "AVGO", "BA", "COIN", "GOOG", "GOOGL", "HOOD", "INTC", "KORU", "META", "MSFT", "MSTR", "MU", "NFLX", "NVDA", "NVDAX", "PLTR", "QQQ", "SAMSUNG", "SKHYNIX", "SNDK", "SNXX", "SPCX", "SPY", "TSLA",
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
        """Multi-source universe:
        - global ranking from an INDEPENDENT venue (data.ranking, OKX first)
        - execution-venue metrics from Ourbit (preferred; Viva trades there)
          or Bybit for symbols Ourbit does not list
        - metals (PAXG/XAUT …) injected from Ourbit/Bybit even if missing
          from crypto-only rankings.
        """
        from data.ourbit import get_ourbit_tickers, ourbit_listed
        from data.ranking import get_global_ranking, get_ranked_symbols

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        minimum_age_ms = SETTINGS.watchlist_min_listing_days * 86_400_000

        ranking = get_global_ranking()
        ranked = get_ranked_symbols()
        instruments = {str(i.get("symbol", "")).upper(): i for i in get_instruments() or [] if i.get("symbol")}
        bybit_tickers = {str(t.get("symbol", "")): t for t in (get_tickers(use_cache=False) or [])}
        ourbit_rows = {}
        try:
            ourbit_rows = {row["symbol"]: row for row in (get_ourbit_tickers() or [])}
        except Exception as exc:
            print(f"⚠️ Ourbit tickers unavailable: {exc}")

        def _bybit_row(symbol: str) -> Optional[Dict]:
            instrument = instruments.get(symbol)
            ticker = bybit_tickers.get(symbol)
            if not instrument or not ticker:
                return None
            launch_time = int(_float(instrument.get("launchTime"), 0))
            old_enough = not launch_time or now_ms - launch_time >= minimum_age_ms
            usdt_settled = (
                str(instrument.get("settleCoin", "")).upper() == "USDT"
                or str(instrument.get("quoteCoin", "")).upper() == "USDT"
            )
            if not (
                usdt_settled
                and instrument.get("status") == "Trading"
                and "Perpetual" in str(instrument.get("contractType", ""))
                and old_enough
            ):
                return None
            bid = _float(ticker.get("bid1Price"))
            ask = _float(ticker.get("ask1Price"))
            last = _float(ticker.get("lastPrice"))
            if last <= 0:
                return None
            spread_pct = ((ask - bid) / ((ask + bid) / 2) * 100) if bid > 0 and ask > bid else 999
            leverage_filter = instrument.get("leverageFilter") or {}
            return {
                "venue": "BYBIT",
                "last_price": last,
                "spread_pct": spread_pct,
                "venue_turnover": _float(ticker.get("turnover24h")),
                "funding_rate": _float(ticker.get("fundingRate")),
                "open_interest": _float(ticker.get("openInterestValue")),
                "max_leverage": _float(leverage_filter.get("maxLeverage"), 20.0),
                "asset_class": _asset_class(instrument),
            }

        rows: List[Dict] = []
        seen = set()

        def _append(symbol: str, global_turnover: float, venue_row: Dict, rank_source: str) -> None:
            if symbol in seen:
                return
            base = symbol.upper().removesuffix("USDT").removesuffix("USDC")
            if base in TOKENIZED_NONCRYPTO_BASES:
                return
            spread = venue_row.get("spread_pct")
            last = float(venue_row.get("last_price") or 0)
            if last <= 0 or spread is None or spread > SETTINGS.watchlist_max_spread_percent:
                return
            rows.append({
                "symbol": symbol,
                "venue": venue_row["venue"],
                "asset_class": venue_row.get("asset_class", "CRYPTO"),
                "display_name": symbol,
                "turnover24h": float(global_turnover),
                "trading_day_turnover": 0.0,
                "projected_day_turnover": 0.0,
                "volume24h": 0.0,
                "spread_pct": float(spread),
                "last_price": last,
                "price_change_24h": 0.0,
                "funding_rate": float(venue_row.get("funding_rate") or 0),
                "open_interest": float(venue_row.get("open_interest") or 0),
                "max_leverage": float(venue_row.get("max_leverage", 20.0)),
                "relative_volume": 1.0,
                "rank_source": rank_source,
            })
            seen.add(symbol)

        # 1) Global ranking order (independent venue): top candidates only.
        for index, symbol in enumerate(ranked):
            if len(rows) >= SETTINGS.watchlist_prefilter_symbols:
                break
            if index >= SETTINGS.watchlist_prefilter_symbols * 2:
                break
            rank_row = ranking.get(symbol) or {}
            global_turnover = float(rank_row.get("global_turnover24h", 0))
            if global_turnover < SETTINGS.watchlist_min_turnover_usd * 0.5:
                continue
            venue_row = None
            ob = ourbit_rows.get(symbol)
            if ob and ob.get("last_price"):
                venue_row = {
                    "venue": "OURBIT",
                    "last_price": float(ob["last_price"]),
                    "spread_pct": ob.get("spread_pct"),
                    "venue_turnover": float(ob.get("turnover24h") or 0),
                    "funding_rate": float(ob.get("funding_rate") or 0),
                    "open_interest": float(ob.get("open_interest") or 0),
                    "max_leverage": 20.0,
                    "asset_class": _asset_class({"symbol": symbol, "baseCoin": symbol[:-4], "quoteCoin": "USDT"}),
                }
            if venue_row is None:
                venue_row = _bybit_row(symbol)
            if venue_row is None:
                continue
            _append(symbol, global_turnover, venue_row, str(rank_row.get("source", "")))

        # 2) Bybit-venue fallback pool: any tradable instrument the global
        # ranking did not cover (offline mode, FX pairs, or ranking outage)
        # still joins in venue-turnover order.
        bybit_sorted = sorted(
            bybit_tickers.items(),
            key=lambda kv: _float(kv[1].get("turnover24h")),
            reverse=True,
        )
        for symbol, ticker in bybit_sorted:
            if len(rows) >= SETTINGS.watchlist_prefilter_symbols:
                break
            if symbol in seen or not symbol.endswith("USDT") and not any(
                symbol.startswith(pair) for pair in FOREX_PAIR_CODES
            ):
                continue
            turnover = _float(ticker.get("turnover24h"))
            if turnover < SETTINGS.watchlist_min_turnover_usd * 0.5:
                continue
            venue_row = _bybit_row(symbol)
            if venue_row is None:
                continue
            _append(symbol, turnover, venue_row, "BYBIT")

        # 3) Metals injection — gold/silver tokens are not on crypto rankings.
        for symbol, ob in ourbit_rows.items():
            asset = _asset_class({"symbol": symbol, "baseCoin": symbol[:-4], "quoteCoin": "USDT"})
            if asset not in {"METAL", "COMMODITY"} or symbol in seen:
                continue
            if float(ob.get("turnover24h") or 0) < SETTINGS.watchlist_min_turnover_usd * 0.3:
                continue
            venue_row = {
                "venue": "OURBIT",
                "last_price": float(ob.get("last_price") or 0),
                "spread_pct": ob.get("spread_pct"),
                "venue_turnover": float(ob.get("turnover24h") or 0),
                "funding_rate": float(ob.get("funding_rate") or 0),
                "open_interest": float(ob.get("open_interest") or 0),
                "max_leverage": 20.0,
                "asset_class": asset,
            }
            _append(symbol, float(ob.get("turnover24h") or 0), venue_row, "OURBIT")
        # Same for Bybit-only metals (e.g. if Ourbit drops one).
        for symbol, _ticker in bybit_tickers.items():
            if not symbol.endswith("USDT") or symbol in seen:
                continue
            asset = _asset_class({"symbol": symbol, "baseCoin": symbol[:-4], "quoteCoin": "USDT"})
            if asset not in {"METAL", "COMMODITY"}:
                continue
            venue_row = _bybit_row(symbol)
            if venue_row and _float(_ticker.get("turnover24h")) >= SETTINGS.watchlist_min_turnover_usd * 0.3:
                _append(symbol, _float(_ticker.get("turnover24h")), venue_row, "BYBIT")

        # 4) Rank on the current UTC trading day's actual turnover. Projecting the
        # day's pace avoids excluding every market shortly after 00:00 UTC.
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed_fraction = max((now - day_start).total_seconds() / 86_400, 0.10)
        liquid_today: List[Dict] = []
        allowed_assets = {x.strip().upper() for x in str(SETTINGS.watchlist_allowed_asset_classes).split(",") if x.strip()}
        for row in rows:
            if allowed_assets and str(row.get("asset_class", "CRYPTO")).upper() not in allowed_assets:
                continue
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
            # Metals/commodities run structurally thinner books on crypto
            # venues; gold token spreads are tight, so a lower floor is fair.
            asset_class = row.get("asset_class", "CRYPTO")
            floor = (
                SETTINGS.watchlist_min_turnover_usd * 0.25
                if asset_class in {"METAL", "COMMODITY"}
                else SETTINGS.watchlist_min_turnover_usd
            )
            if projected >= floor:
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
        chosen = set()
        forex_selected = 0
        for row in top_forex + top_tradfi + top_turnover + top_relative:
            if row["symbol"] in chosen:
                continue
            if (
                row["asset_class"] == "FOREX"
                and forex_selected >= SETTINGS.watchlist_max_forex_symbols
            ):
                continue
            selected.append(row)
            chosen.add(row["symbol"])
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
            ourbit_count = sum(1 for row in selected if row["venue"] == "OURBIT")
            print(
                f"📈 Dynamic watchlist: {len(symbols)} symbols by current-day liquidity "
                f"({rv_count} relative-volume ≥ 1.5x • {forex_count} FX • {tradfi_count} TradFi • {ourbit_count} Ourbit)"
            )
        return symbols, metrics


UNIVERSE = DynamicUniverse()
