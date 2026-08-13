"""Central configuration for Viva Signal Bot v7.

All production behaviour can be changed through environment variables without
editing source code. Defaults intentionally favour quality over signal count.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    version: str = "v7.0-quality"
    strategy_version: str = "smc-core-7.0"
    channel_name: str = "vivasignalyst-Chanel"

    full_scan_minutes: int = 15
    monitor_minutes: int = 5
    scan_offset_minute: int = 1
    educational_min_score: int = 6
    execution_min_score: int = 7
    candidate_expiry_hours_swing: int = 36
    candidate_expiry_hours_scalp: int = 6

    account_size: float = 1000.0
    base_risk_percent: float = 1.0
    max_risk_percent: float = 1.25
    max_margin_percent: float = 25.0
    max_open_trades: int = 5
    max_correlated_trades: int = 2
    daily_loss_limit_percent: float = 3.0
    partial_tp1_percent: float = 60.0
    partial_tp2_percent: float = 40.0
    fee_rate_percent: float = 0.06
    slippage_percent: float = 0.03

    watchlist_top_turnover: int = 50
    watchlist_top_relative_volume: int = 20
    watchlist_max_symbols: int = 70
    watchlist_prefilter_symbols: int = 90
    watchlist_refresh_minutes: int = 60
    watchlist_min_turnover_usd: float = 5_000_000.0
    watchlist_max_spread_percent: float = 0.25
    watchlist_min_listing_days: int = 14
    scalp_min_turnover_usd: float = 20_000_000.0
    scalp_max_spread_percent: float = 0.12

    bybit_timeout_seconds: int = 12
    bybit_min_request_interval: float = 0.08
    bybit_cache_seconds: int = 45
    run_scan_on_start: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            version=os.getenv("APP_VERSION", cls.version),
            strategy_version=os.getenv("STRATEGY_VERSION", cls.strategy_version),
            channel_name=os.getenv("CHANNEL_NAME", cls.channel_name),
            full_scan_minutes=_int("FULL_SCAN_MINUTES", cls.full_scan_minutes),
            monitor_minutes=_int("MONITOR_MINUTES", cls.monitor_minutes),
            scan_offset_minute=_int("SCAN_OFFSET_MINUTE", cls.scan_offset_minute),
            educational_min_score=_int("EDUCATIONAL_MIN_SCORE", cls.educational_min_score),
            execution_min_score=_int("EXECUTION_MIN_SCORE", cls.execution_min_score),
            candidate_expiry_hours_swing=_int("CANDIDATE_EXPIRY_HOURS_SWING", cls.candidate_expiry_hours_swing),
            candidate_expiry_hours_scalp=_int("CANDIDATE_EXPIRY_HOURS_SCALP", cls.candidate_expiry_hours_scalp),
            account_size=_float("ACCOUNT_SIZE", cls.account_size),
            base_risk_percent=_float("RISK_PERCENT", cls.base_risk_percent),
            max_risk_percent=_float("MAX_RISK_PERCENT", cls.max_risk_percent),
            max_margin_percent=_float("MAX_MARGIN_PERCENT", cls.max_margin_percent),
            max_open_trades=_int("MAX_OPEN_TRADES", cls.max_open_trades),
            max_correlated_trades=_int("MAX_CORRELATED_TRADES", cls.max_correlated_trades),
            daily_loss_limit_percent=_float("DAILY_LOSS_LIMIT_PERCENT", cls.daily_loss_limit_percent),
            partial_tp1_percent=_float("PARTIAL_TP1_PERCENT", cls.partial_tp1_percent),
            partial_tp2_percent=_float("PARTIAL_TP2_PERCENT", cls.partial_tp2_percent),
            fee_rate_percent=_float("FEE_RATE_PERCENT", cls.fee_rate_percent),
            slippage_percent=_float("SLIPPAGE_PERCENT", cls.slippage_percent),
            watchlist_top_turnover=_int("WATCHLIST_TOP_TURNOVER", cls.watchlist_top_turnover),
            watchlist_top_relative_volume=_int("WATCHLIST_TOP_RELATIVE_VOLUME", cls.watchlist_top_relative_volume),
            watchlist_max_symbols=_int("WATCHLIST_MAX_SYMBOLS", cls.watchlist_max_symbols),
            watchlist_prefilter_symbols=_int("WATCHLIST_PREFILTER_SYMBOLS", cls.watchlist_prefilter_symbols),
            watchlist_refresh_minutes=_int("WATCHLIST_REFRESH_MINUTES", cls.watchlist_refresh_minutes),
            watchlist_min_turnover_usd=_float("WATCHLIST_MIN_TURNOVER_USD", cls.watchlist_min_turnover_usd),
            watchlist_max_spread_percent=_float("WATCHLIST_MAX_SPREAD_PERCENT", cls.watchlist_max_spread_percent),
            watchlist_min_listing_days=_int("WATCHLIST_MIN_LISTING_DAYS", cls.watchlist_min_listing_days),
            scalp_min_turnover_usd=_float("SCALP_MIN_TURNOVER_USD", cls.scalp_min_turnover_usd),
            scalp_max_spread_percent=_float("SCALP_MAX_SPREAD_PERCENT", cls.scalp_max_spread_percent),
            bybit_timeout_seconds=_int("BYBIT_TIMEOUT_SECONDS", cls.bybit_timeout_seconds),
            bybit_min_request_interval=_float("BYBIT_MIN_REQUEST_INTERVAL", cls.bybit_min_request_interval),
            bybit_cache_seconds=_int("BYBIT_CACHE_SECONDS", cls.bybit_cache_seconds),
            run_scan_on_start=_bool("RUN_SCAN_ON_START", cls.run_scan_on_start),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
