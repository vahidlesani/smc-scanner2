# Viva Scanner — Railway Migration Runbook (۲۰۲۶-۱۰-۱۳)

## What is backed up (workspace `/home/user/backup/`)
| item | path | size | content |
|---|---|---|---|
| DB dump | `backup/viva_db_dump/` | 165 MB | schema.sql + COPY-CSV of ALL 13 tables (bot_kv 71k rows incl. snapshot-locks/render-identity, signals 4.7k, candidates 643, telegram events 9.9k, public-code registry 107k) + `restore.py` |
| Git bundle | `backup/viva-repo.bundle` | 65 MB | EVERY commit/branch incl. unpushed R72/R73/R74 chain |

**Key fact: the database is NOT on Railway.** It lives on Supabase
(`DATABASE_URL`). A Railway migration therefore moves ONLY the compute
service; the DB, all locks and all history stay where they are. The dump is
pure insurance — restore with `VIVA_DB_URL=<target> python restore.py`.

## New Railway project — exact steps
1. New project → **connect GitHub repo** `vahidlesani/smc-scanner2`, branch
   `main`, root `/`, **auto-deploy ON** (Railway builds via Nixpacks; the
   Procfile `web: python combined_service.py` is the start command — one
   container runs scanner thread + dashboard waitress together).
2. Set variables (names the code actually reads; copy VALUES from the old
   project's Variables tab — none of them live in the repo):
   - **Must-have:** `TELEGRAM_TOKEN`, `DATABASE_URL` (the Supabase string),
     `CHAT_ID`, `CHAT_ID_SIGNALS`, `CHAT_ID_RESULTS`, `CHAT_ID_SPOT`,
     `CHAT_ID_VIVA_SIGNALS`, `CHAT_ID_TF_15M_1H`, `CHAT_ID_TF_2H_4H`,
     `CHAT_ID_TF_1D`, `CHAT_ID_SWING_LONG/MID/SHORT`, `CHAT_ID_APPROACHING`,
     `ADMIN_USERNAMES`, `PORT` (Railway gives it), `WEB_THREADS` (set `2`),
     `RAILWAY_CONTROL_TOKEN/PROJECT_ID/ENVIRONMENT_ID/SERVICE_ID` (only for
     the in-bot setup switcher; optional).
   - **Tunables (defaults are safe):** `FULL_SCAN_MINUTES=15`,
     `REALTIME_EXECUTION_SECONDS=5`, `CANDIDATE_MONITOR_SECONDS=10`,
     `CANDIDATE_MONITOR_IDLE_SECONDS=20`, `SPOT_SCAN_MINUTES`,
     `SPOT_ENGINE_ENABLED=1`, `CHART_DPI=240`, `CHART_STYLE=light`.
   - Symbol lists (`ALBROX_SYMBOLS`, `PINVAL_SYMBOLS`, `TECHCLASSIC_SYMBOLS`,
     `EXPERIMENTAL_*`) — copy verbatim from old project or defaults apply.
3. First deploy: `combined_service.py` runs
   `scripts/purge_render_locks.purge_once()` automatically (stale render
   locks from the old instance cleared), scanner thread starts, dashboard
   serves on `$PORT`.
4. **Kill the OLD service BEFORE the new one takes Telegram polling** — two
   live pollers fight over updates (and double the bill). Old project →
   service → Settings → Delete/Stop.
5. Verify: dashboard `/` up, one line in logs
   `🌐 Viva combined service listening on 0.0.0.0:$PORT`, then a forced
   scan posts to the test channel.

## Where the Railway balance actually goes (audit 10-13, code-level)
Railway metered = CPU-seconds + RAM-seconds of UPTIME. The bot is 24/7 by
design (alerts must be instant), so uptime IS the base cost. On top of it:
1. **Duplicate instances (prime suspect after migrations):** any leftover
   service/sandbox environment running the same repo doubles uptime AND
   makes two Telegram pollers race. The `railway sandbox create -p …` line
   Viva pasted is exactly such an ephemeral environment — if it was ever
   run, a sandbox service may still be alive. Needs a valid API token to
   list & kill (see below).
2. Full discovery scan every 15 min over the whole universe (CPU spike,
   unavoidable — it is the alert engine).
3. Chart renders at 240 dpi on state changes (CPU spike; byte-cached since
   09-17, cache raised 6→12 on 10-12 so lifecycle reposts cost zero).
4. Everything else is already gated: realtime lane skips ticker fetch when
   zero filled positions (R67.2), monitor loop idles at 20 s with zero
   chains, line-watch batches ONE ticker snapshot per market per 30 s,
   klines fetch-cache serves repeated reads.

## Tokens status (10-13)
  the 7 local commits (R72/R73/R74) is BLOCKED until a fresh PAT arrives.
- The three UUIDs pasted as "Railway API token" are **project/environment
  IDs, not tokens** (Bearer auth rejects all three). A real Railway API
  token is created at Railway → Account → API Tokens (long string, not a
  UUID). With it I can list every project/service/sandbox, find the duplicate
  burner and stop it, and read usage.
