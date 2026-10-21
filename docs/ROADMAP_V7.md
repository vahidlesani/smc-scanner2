# Viva v7 Quality Roadmap

## Implemented foundation

- [x] 15-minute aligned discovery scan
- [x] 5-minute candidate/trade monitor
- [x] dynamic volume-based watchlist
- [x] one market bundle per symbol
- [x] separate Swing and Scalp engines
- [x] educational candidate vs executable confirmation separation
- [x] confirmed-only Supabase history
- [x] Persian evidence-rich Telegram layouts
- [x] `viva-` IDs with style/setup codes
- [x] portfolio-aware money management
- [x] walk-forward shared-engine backtest
- [x] dashboard confirmed-only filtering

## Controlled rollout

1. Deploy v7 in educational/shadow mode for at least 7 days.
2. Confirm there are no Bybit 403/429 bursts, Telegram duplicates or schema errors.
3. Review at least 100 confirmed historical/out-of-sample trades per Setup before increasing risk.
4. Compare Setup versions using Expectancy, Profit Factor and Max Drawdown—not Win Rate alone.
5. Disable any Setup with negative out-of-sample expectancy until its rules are revised.

## Next research candidates (not promoted automatically)

- Wyckoff Spring/Upthrust with reclaim and MSS
- session VWAP/deviation context for Scalp
- SMT divergence between strongly related markets
- open-interest/funding change as a supporting derivatives filter
- market-regime classifier for trend/range/expansion

Each research detector must first run in shadow/backtest mode. It must not become an executable strategy merely because it increases signal count.
