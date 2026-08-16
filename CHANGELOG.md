# Changelog

## v7.4.0 — 2026-08-15

### Added
- **Public bot UX** (`bot/commands.py` rewrite): the bot is no longer admin-only.
  - Main menu with emoji layout: ⚡ تحلیل فوری | 🔔 ستاپ‌های فعال | 📊 آمار کانال | 💎 عضویت | 🖥 وضعیت ربات | ❓ راهنما (admin-only row: backtest/strategies).
  - **تحلیل فوری (instant analysis)**: 4 asset classes (🪙 20 crypto / 💱 6 forex majors / 🥇 4 commodities / 📈 12 stocks). Crypto runs a live `scan_bundle` on a fresh market bundle and replies with a chart + compact entry/exit card (zone, entry, SL %, TP1/TP2 with partial-exit guidance, AI engine note). Non-crypto classes show the full symbol grids but answer honestly "feed not connected yet" — no fake data.
  - **🔔 ستاپ‌های فعال**: last 10 active candidates as one-tap buttons; pressing one posts a fresh chart + emoji'd entry/exit explanation.
  - **💎 عضویت** (`bot/membership.py`, new Postgres table `bot_users`): free tier = 3 instant-analysis uses (env `FREE_ANALYSIS_LIMIT`), referral tier = min-$50 deposit via exchange links (env `REF_OURBIT_URL` / `REF_XT_URL` / `REF_BITUNIX_URL` / `REF_TABDEAL_URL`) → UID capture → admin approve (`/approve <uid>` or ✅ button) → one-time channel invite (env `CHANNEL_INVITE_URL`); paid tier = wallet address/QR (env `WALLET_ADDRESS`, `WALLET_QR_PATH`) with plans $15/1m, $30/3m, $50/6m → TXID capture → `/activate <uid> <months>`. Whitelist `ADMIN_USERNAMES` (default vahidlesani,Sogandddkia,vivamonlabs) bypasses all limits. Works without DB via in-memory fallback.
  - New commands: `/analysis`, `/setups`, `/membership` (public); `/approve`, `/activate`, `/users` (admin).

## v7.3.1-exp — 2026-08-15

### Changed
- **TLBREAK v2 — Viva's intra-candle base entry.** After an explosive dynamic-level break the model no longer expects a full pullback to the broken line: the entry zone is the lower-TF base formed inside the break candle (`_intrabar_base`), targets are the engine's first opposing structural zones (first 4h/1h supply/demand) instead of channel-height fractions. Effect on the 90d/4-symbol eval: total PnL **−6.3 → +16.5**; ETHUSDT SCALP became the second validated config (n=27, WR 48%, PF 1.76; IS +3.81 / OOS +2.34 both positive, July-strong, long-driven).

### Added
- **Range-fraction target policy for core v7 setups** behind `RANGE_FRACTION_TARGETS` (default false) + `RANGE_FRACTION_SYMBOLS` scope. 90d A/B (same detections, same confirmations): SWING total **−29.99 → +25.24**, driven by ETHUSDT (n=27, PF 3.5, IS ✔ / OOS ✔ marginal, spread across BOS1/IFVG/LSR — not a single-setup artifact); SOL swing fails OOS; SCALP total slightly worse. Evidence-grade: promising, ETH-scoped forward candidate.

## v7.3.0-exp — 2026-08-14

### Added
- **Experimental TLBREAK setup**: channel/trendline breakout detector (two latest context-TF pivots define the active dynamic line; parallel bound through the extreme opposing pivot gives channel height). Pre-break (PRE_BREAK watch near the line) and just-broken stages both map onto the standard lifecycle: the approaching alert = "نزدیک شکست", the trigger-candle close past the zone = "شکست معتبر با Close". Targets are measured-move fractions of channel height (`TLBREAK_TP1_HEIGHT_FRAC=0.45`, `TLBREAK_TP2_HEIGHT_FRAC=0.70`).
- Knobs: `EXPERIMENTAL_TLBREAK_ENABLED` (false), `EXPERIMENTAL_TLBREAK_SYMBOLS` (empty = all), `TLBREAK_MIN_ADX` (0 = off), `TLBREAK_CONTEXT_TF` (empty = style default 4h/1h; set `1d` for the macro long-term tier).

### R&D results (90d, 4 symbols, OKX, fees included)
- 4h/1h context: only SOLUSDT SCALP positive (+7.11, n=36, WR 50%, PF 1.66) but **OOS 40% = −0.97 (PF 0.78) → rejected**.
- 1d context (macro tier): 0-4 trades/symbol — statistically untestable on a 4-symbol universe; needs forward logging on the full watchlist.

## v7.2.0-exp — 2026-08-14

### Added
- **Experimental P1234 setup** (`analysis/setups_experimental.py`): Ross-style 1-2-3-4 reversal — point-2 close-break on the trigger TF → candidate POI = broken point-2 flip zone → standard v7 lifecycle (first retest + closed-candle trigger).
- **Wilder ADX(14)** in `analysis/indicators.py` and a regime gate for P1234: `P1234_MIN_ADX` (default 0 = off).
- **Opt-in live wiring**: `EXPERIMENTAL_P1234_ENABLED` (default false) merges experimental detectors into `scan_setups`; `EXPERIMENTAL_P1234_SYMBOLS` (default `SOLUSDT`, empty = unrestricted) scopes them per symbol.
- `experiments/p1234_eval.py`, `p1234_trades.py`, `p1234_is_oos.py` — 90/180-day evaluator with trade-level dumps and IS/OOS attribution.

### R&D results (OKX perp OHLCV, production cadence, fees+slippage included)
- P1234 SCALP on SOLUSDT with `P1234_MIN_ADX=20`: **180d n=29, WR 69%, exp +0.78%/trade, PF 5.84, maxDD 3.1; IS(60%) +17.72 / OOS(40%) +4.89 (PF 2.77, WR 58%)** — first config passing the pre-registered bar and promoted to forward paper-trading.
- P1234 SWING fails OOS on every symbol (SOL swing OOS 19 trades → −9.45, 12 consecutive losses). BTC/XRP P1234 negative in both styles, with or without the ADX filter.

## v7.1.0 — 2026-08-13

### Fixed
- **Dead-gate candidates no longer reach the execution track.** A candidate born with a failing mandatory gate (≈57-78% of detections, mostly `htf_alignment`) could never confirm, yet previously it still sent Approaching messages and locked its symbol for up to 36 hours. With `SKIP_DEAD_GATE_CANDIDATES=true` (default) such setups are educational-only: untracked, no execution alerts, no symbol lock, with in-memory dedup to avoid repeated educational spam.
- **Backtest now mirrors live exactly** for dead-gate candidates, so a setup re-detected after its gates heal is no longer swallowed by dedup of a previously dead candidate.
- Candidate expiry in the backtest now follows `CANDIDATE_EXPIRY_HOURS_*` instead of hardcoded 36h/6h.

### Added
- **Machine-readable rejection codes** in `evaluate_confirmation` (`NO_TOUCH`, `NO_TRIGGER`, `RR_DEGRADED`, `GATES_INCOMPLETE`, `CLOSE_THROUGH_INVALIDATION`, ...) persisted in `candidate.metadata["last_reject_code"]`; `/backtest` output now prints a per-style funnel line with the top rejection reasons.
- **Confirmation engine knobs** (defaults reproduce strict v7):
  `CONFIRM_RR1_FLOOR` (1.30), `CONFIRM_RR2_FLOOR` (2.0), `CONFIRM_BODY_MIN_ATR` (0.35), `CONFIRM_REQUIRE_ZONE_MID` (true), `SL_BUFFER_ATR_SWING` (0.35), `SL_BUFFER_ATR_SCALP` (0.25), `SKIP_DEAD_GATE_CANDIDATES` (true).
- `experiments/` toolkit: instrumented walk-forward funnel (`diagnose_funnel.py`), cached collect + fast confirmation replay (`collect_replay.py`), and an OKX OHLCV shim (`okx_feed.py`) for environments geo-blocked from Bybit.

### Analysis (14d walk-forward on BTCUSDT/XRPUSDT, OKX data)
- 59-64% of candidates die via SL-after-zone-touch before any trigger candle; ~78% of scalp candidates were dead at creation (mandatory gate). Trigger-candle strictness and expiry length had negligible effect on confirmed-trade counts; relaxing all HTF gates degraded PnL on BTC.

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

## v7.5.0 — 2026-08-16 — **VIVA SETUP consolidation**

### Changed (defaults!)
- **Setup pruning:** the five legacy core detectors (LSR/BOS1/TLR/SDR/IFVG) are
  OFF by default (`CORE_V7_SETUPS_ENABLED=false`). Live default setups are now
  the three validated/alert paths only: **TLBREAK** (trendline/channel/triangle/
  wedge break&touch), **P1234+ADX** (SOL-scoped), **PINVAL** (pinbar-in-zone
  alert). This is the merged strategy Viva asked for: one «VIVA SETUP» family.
- Chart identity update: timeframe printed in the header; light background
  `CHART_STYLE=light` default unchanged; bull candles switched to very light
  gray (#F2F4F7) so hollow bodies stay visible; all annotation text moved to a
  single candle-free corner stack (INVALIDATION / SWING HIGH / SWING LOW /
  EXPECTED MOVE / pattern state); confirmed charts draw a TradingView-style
  ▲ LONG / ▼ SHORT position marker + dashed scenario arrows; educational
  charts draw an EXPECTED MOVE → TP1 schematic arrow; optional log-scale axis
  for higher-context (TLB 4h/1d) charts (`CHART_LOG_HTF`).
- Every alert/confirmation message now includes a «🧭 کانتکست تایم بالاتر»
  block (pattern state, sweep/structure breaks, zone kind: flip / FVG-flag-limit
  / fresh S-D, bias).

### Added
- **PINVAL detector** (`analysis/setups_experimental.py::detect_pinbar_zone`):
  valid pinbar (wick ≥ 2× body, body ≤ 35% range, range ≥ 0.6 ATR) inside an
  important area — context-TF pivot zone (with flip-zone detection) and/or the
  edge of an un-mitigated FVG («فلگ‌لیمیت») — on trigger TFs 5m/15m/1h
  (scalp: 15m/5m, swing: 1h). Optional adjacent-doji confluence bump.
  Knobs: `PINVAL_ENABLED` (true), `PINVAL_MIN_WICK_BODY` (2.0),
  `PINVAL_MAX_BODY_FRAC` (0.35), `PINVAL_MIN_RANGE_ATR` (0.6),
  `PINVAL_SYMBOLS` (empty = all).
- **Verdict replies:** each alert stores its Telegram `message_id`; the monitor
  replies ✅ تأیید شد / ❌ تأیید نشد / ⚪ بدون تأیید under the alert message.
  For PINVAL the verdict is decided within `ALERT_VERDICT_CANDLES` (3) candles:
  close beyond pin extreme = confirm, close beyond wick = invalidate.
- TLBREAK pattern classifier: separate detection of converging structures →
  «مثلث» (triangle, opposite slopes) vs «وج» (wedge, same-sign narrowing) vs
  channel; strategy_fa now says «شکست الگوی مثلث/وج/کانال» etc.

### Fixed
- Pinbar/alert candidates no longer block or get blocked by the one-lifecycle-
  per-symbol dedupe (they skip symbol locks; `find_similar` ignores PINVAL).
