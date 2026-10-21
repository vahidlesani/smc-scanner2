# Railway Consumption Safeguard — Viva 10-12 law

> «مصرف railway نباید بالا بره؛ تأییدها و بریک‌ها باید آنی و کم‌هزینه برسند»

The bot runs on a metered Railway instance. Every CPU-second spent re-doing
work that was already done is money. The pipeline therefore has FIVE cache
layers between a market event and any expensive work (analysis fit or chart
render). Confirms and breaks travel the cheap path end-to-end.

## Layer 1 — klines fetch cache (`data/fetcher.get_klines`, `use_cache=True`)
Render and scan fetches hit the in-process klines cache; the tape syncs at
most once per candle bucket per symbol. Only the monitor lanes force
`use_cache=False` (they ARE the freshness source). A chart re-render for the
same bucket costs ZERO network and ZERO Binance weight.

## Layer 2 — snapshot-lock + refit suppression (`analysis/snapshot_lock.py`)
Pattern/trendline geometry is detected ONCE per alert chain and frozen
(`render_identity:<signal_id>` in bot_kv). Lifecycle steps (update → confirm
→ break → mirror) reuse the frozen points; no re-fit, no multi-TF re-detect
(R72 law: multi-TF output is text-only, never a second analysis run).

## Layer 3 — chart byte cache (`bot/messages_v7._CHART_CACHE`)
One render per `(signal_id, mode, newest timestamp, tape length, view TF,
live close)`. Retries, mirrors, cross-channel reposts and Telegram
re-deliveries reuse the exact bytes. Viva 10-12: raised 6 → 12 slots
(measured probe PNGs at 240 dpi are 0.3–0.5 MB → ≤ ~6 MB RAM, far below the
OOM guard) so a FULL lifecycle (alert → confirm → break → reposts) now hits
bytes instead of re-rendering, while the live-close component of the key
still forces a fresh picture whenever the market on the chart truly moved.

## Layer 4 — one render per state, states are few
A chain renders only on state transitions (ANALYSIS → READY → CONFIRMED →
broken/invalidated). Price ticks inside the same candle do NOT trigger
renders; the monitor posts text updates (cheap Telegram edit) instead.

## Layer 5 — deploy purge
Railway auto-deploy restarts the worker; caches are in-process by design, so
a deploy always starts clean (no stale-bytes risk) and the kv snapshot-lock
re-hydrates from bot_kv (persisted), never re-fetching history.

## Measured cost per event class (probe evidence, 2026-10-12)
| event            | analysis | render | network |
|------------------|----------|--------|---------|
| price tick       | no       | no     | cached  |
| new candle       | no       | no (text edit) | cached |
| confirm / break  | no (frozen geometry) | 1 (only if state flips) | cached |
| mirror / repost  | no       | no (byte cache) | cached |
| new alert        | yes (once) | yes (once) | 1 sync |

Any future feature that adds a render or a fit per tick/candle VIOLATES this
law and must route through one of the five layers first.
