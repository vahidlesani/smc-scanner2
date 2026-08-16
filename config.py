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
    channel_name: str = "VivaSignals Pro"

    full_scan_minutes: int = 15
    monitor_minutes: int = 5
    # Minute offset inside each monitor interval — aligns cycles to just
    # after candle closes (e.g. 1 => 5m cycles run at :01/:06/:11 UTC).
    monitor_offset_minute: int = 1
    scan_offset_minute: int = 1

    # ── viva setup era: prune low-evidence core detectors by default ──
    # R&D finding (90d/4-symbol): the five core v7 setups had no standalone
    # edge, so only the validated paths run unless explicitly re-enabled.
    core_v7_setups_enabled: bool = False
    # Pinbar-in-zone alerts (5m/15m/1h) — bullish 🔴/🟢 alert + verdict reply
    pinv_enabled: bool = True
    pinv_min_wick_body: float = 2.0      # dominant wick / body
    pinv_max_body_frac: float = 0.35     # body / range
    pinv_min_range_atr: float = 0.6      # candle range / ATR floor
    pinv_symbols: str = ""               # empty = all symbols
    # How many trigger candles an alert gets before a verdict reply (❌/✅)
    alert_verdict_candles: int = 3
    # Log-scale rendering for higher-context trendline charts
    chart_log_htf: bool = True
    educational_min_score: int = 6
    execution_min_score: int = 7
    candidate_expiry_hours_swing: int = 36
    candidate_expiry_hours_scalp: int = 6

    # Confirmation engine knobs (defaults reproduce the original strict v7).
    confirm_rr1_floor: float = 1.30
    confirm_rr2_floor: float = 2.0
    confirm_body_min_atr: float = 0.35
    confirm_require_zone_mid: bool = True
    # Invalidation buffer widths beyond the liquidity anchor, in ATR units.
    sl_buffer_atr_swing: float = 0.35
    sl_buffer_atr_scalp: float = 0.25
    # Candidates born with a failing mandatory gate can never confirm. When
    # enabled, they are educational-only: they are not tracked for monitoring
    # and therefore never send Approaching messages or lock their symbol.
    skip_dead_gate_candidates: bool = True
    # Experimental P1234 detector: minimum Wilder ADX(14) on the trigger
    # timeframe at detection time. 0.0 disables the regime filter.
    p1234_min_adx: float = 0.0
    # Wire the experimental detectors (P1234) into live scanning. Off by
    # default; enable only behind a paper-trading phase.
    experimental_p1234_enabled: bool = False
    # Comma-separated symbol allowlist for the experimental detectors
    # (e.g. "SOLUSDT,ETHUSDT"); empty string = no symbol restriction.
    experimental_p1234_symbols: str = "SOLUSDT"
    # Experimental TLBREAK (trendline/channel breakout) detector.
    experimental_tlbreak_enabled: bool = False
    experimental_tlbreak_symbols: str = ""  # empty = no symbol restriction
    tlbreak_min_adx: float = 0.0            # ADX(14) gate on context TF; 0 = off
    # Override the context timeframe for the channel lines (e.g. "1d" for the
    # macro long-term swing tier Viva specified); empty = style default (4h/1h).
    tlbreak_context_tf: str = ""
    tlbreak_tp1_height_frac: float = 0.45   # TP1 = 45% of channel height
    tlbreak_tp2_height_frac: float = 0.70   # TP2 = 70% ("not the top of the path")
    # Viva's range-fraction target policy for the core v7 setups (default off):
    # LONG in DISCOUNT / SHORT in PREMIUM target 40%/70% of the dealing range.
    range_fraction_targets: bool = False
    range_fraction_symbols: str = ""        # empty = all symbols

    account_size: float = 1000.0
    base_risk_percent: float = 1.0
    max_risk_percent: float = 1.25
    # Maximum account equity posted as margin for one position. Quality tiers
    # use 3%-5%; this is margin allocation, not acceptable account loss.
    max_margin_percent: float = 5.0
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
    watchlist_max_forex_symbols: int = 3
    watchlist_max_tradfi_symbols: int = 15
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
            monitor_offset_minute=_int("MONITOR_OFFSET_MINUTE", cls.monitor_offset_minute),
            core_v7_setups_enabled=_bool("CORE_V7_SETUPS_ENABLED", cls.core_v7_setups_enabled),
            pinv_enabled=_bool("PINVAL_ENABLED", cls.pinv_enabled),
            pinv_min_wick_body=_float("PINVAL_MIN_WICK_BODY", cls.pinv_min_wick_body),
            pinv_max_body_frac=_float("PINVAL_MAX_BODY_FRAC", cls.pinv_max_body_frac),
            pinv_min_range_atr=_float("PINVAL_MIN_RANGE_ATR", cls.pinv_min_range_atr),
            pinv_symbols=os.getenv("PINVAL_SYMBOLS", cls.pinv_symbols),
            alert_verdict_candles=_int("ALERT_VERDICT_CANDLES", cls.alert_verdict_candles),
            chart_log_htf=_bool("CHART_LOG_HTF", cls.chart_log_htf),
            scan_offset_minute=_int("SCAN_OFFSET_MINUTE", cls.scan_offset_minute),
            educational_min_score=_int("EDUCATIONAL_MIN_SCORE", cls.educational_min_score),
            execution_min_score=_int("EXECUTION_MIN_SCORE", cls.execution_min_score),
            candidate_expiry_hours_swing=_int("CANDIDATE_EXPIRY_HOURS_SWING", cls.candidate_expiry_hours_swing),
            candidate_expiry_hours_scalp=_int("CANDIDATE_EXPIRY_HOURS_SCALP", cls.candidate_expiry_hours_scalp),
            confirm_rr1_floor=_float("CONFIRM_RR1_FLOOR", cls.confirm_rr1_floor),
            confirm_rr2_floor=_float("CONFIRM_RR2_FLOOR", cls.confirm_rr2_floor),
            confirm_body_min_atr=_float("CONFIRM_BODY_MIN_ATR", cls.confirm_body_min_atr),
            confirm_require_zone_mid=_bool("CONFIRM_REQUIRE_ZONE_MID", cls.confirm_require_zone_mid),
            sl_buffer_atr_swing=_float("SL_BUFFER_ATR_SWING", cls.sl_buffer_atr_swing),
            sl_buffer_atr_scalp=_float("SL_BUFFER_ATR_SCALP", cls.sl_buffer_atr_scalp),
            skip_dead_gate_candidates=_bool("SKIP_DEAD_GATE_CANDIDATES", cls.skip_dead_gate_candidates),
            p1234_min_adx=_float("P1234_MIN_ADX", cls.p1234_min_adx),
            experimental_p1234_enabled=_bool("EXPERIMENTAL_P1234_ENABLED", cls.experimental_p1234_enabled),
            experimental_p1234_symbols=os.getenv("EXPERIMENTAL_P1234_SYMBOLS", cls.experimental_p1234_symbols),
            experimental_tlbreak_enabled=_bool("EXPERIMENTAL_TLBREAK_ENABLED", cls.experimental_tlbreak_enabled),
            experimental_tlbreak_symbols=os.getenv("EXPERIMENTAL_TLBREAK_SYMBOLS", cls.experimental_tlbreak_symbols),
            tlbreak_min_adx=_float("TLBREAK_MIN_ADX", cls.tlbreak_min_adx),
            tlbreak_tp1_height_frac=_float("TLBREAK_TP1_HEIGHT_FRAC", cls.tlbreak_tp1_height_frac),
            tlbreak_tp2_height_frac=_float("TLBREAK_TP2_HEIGHT_FRAC", cls.tlbreak_tp2_height_frac),
            tlbreak_context_tf=os.getenv("TLBREAK_CONTEXT_TF", cls.tlbreak_context_tf),
            range_fraction_targets=_bool("RANGE_FRACTION_TARGETS", cls.range_fraction_targets),
            range_fraction_symbols=os.getenv("RANGE_FRACTION_SYMBOLS", cls.range_fraction_symbols),
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
            watchlist_max_forex_symbols=_int("WATCHLIST_MAX_FOREX_SYMBOLS", cls.watchlist_max_forex_symbols),
            watchlist_max_tradfi_symbols=_int("WATCHLIST_MAX_TRADFI_SYMBOLS", cls.watchlist_max_tradfi_symbols),
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
