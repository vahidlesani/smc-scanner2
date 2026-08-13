# Changelog

## v7.0.1 — 2026-08-13

### Fixed
- PostgreSQL migrations are serialized with an advisory transaction lock and use `ADD COLUMN IF NOT EXISTS`, preventing concurrent dashboard workers from racing on the same column.
- Railway now starts `combined_service.py`, so one container runs both the Scanner and Dashboard instead of silently running Dashboard only.
- Combined health response reports scanner-thread liveness; an unexpected scanner crash terminates the container for automatic restart.
- Render Dashboard uses Gunicorn preload to avoid duplicate import-time migrations.

## v7.0-quality — 2026-08-13

### Fixed
- Removed stale Telegram imports that crashed `main.py` at startup.
- Confirmed-trade lifecycle now processes candles chronologically instead of historical `.any()` checks.
- Unconfirmed educational setups no longer enter Supabase performance statistics.
- Strategy statistics use the real Setup code rather than `N/A`.
- SQLite strategy-stat updates no longer depend on PostgreSQL-only `GREATEST/LEAST`.
- Dashboard channel spelling corrected to `vivasignalyst-Chanel`.

### Added
- Central environment configuration.
- Dynamic high-volume Bybit universe with spread/listing filters and relative-volume ranking.
- Cached, retried and throttled Bybit client with endpoint fallback and historical pagination.
- Independent Swing and Scalp engines.
- Quality setups: LSR, BOS first pullback, trendline first retest, supply/demand first retest and IFVG/breaker.
- Pivot-aligned regular/hidden RSI divergence as confirmation only.
- Mandatory execution gates in addition to the numerical score.
- Local transient candidate store outside Supabase.
- Educational, Approaching, Confirmed, TP1 and Result message templates.
- Full Persian evidence explanations generated from measured setup fields.
- `viva-` signal IDs with SW/SC style and Setup code.
- Confirmation-close entry and late-entry R/R rejection.
- Margin, exposure, correlation and daily-loss guards.
- Walk-forward backtest using the live setup engine, fee/slippage and conservative candle ambiguity.
- Render Blueprint for worker and dashboard.
- v7 unit tests.

### Changed
- Discovery scan interval from 5 to 15 minutes, aligned one minute after 15M closes.
- Candidate monitor separated at 5-minute intervals.
- Educational threshold defaults to 6; executable confirmation defaults to 7 plus all mandatory gates.
- Pin Bar, Engulfing, basic FVG and RSI no longer issue standalone executable trades.
- TP targets prioritise market structure/liquidity and are checked again at the executable confirmation price.
- Dashboard and performance APIs show confirmed signals only.
