#!/usr/bin/env bash
# R99q41 — the whole migration in one command, safe to re-run (idempotent).
#
#   RAILWAY_API_TOKEN=<new account token> bash ops/railway/go_r99q41.sh
#
# What it refuses to do: deploy without TELEGRAM_TOKEN (the bot would be silent).
# Add --allow-no-telegram to override, --dry-run to only inspect.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${RAILWAY_API_TOKEN:?set RAILWAY_API_TOKEN to the NEW account token}"
ENV_FILE="${ENV_FILE:-/home/user/.viva_secrets/env_r99q41.json}"
ARGS=(--apply --deploy --env-file "$ENV_FILE")
for a in "$@"; do
  case "$a" in
    --dry-run)   ARGS=(--env-file "$ENV_FILE") ;;
    --allow-no-telegram|--deploy) : ;;
    *)           ARGS+=("$a") ;;
  esac
done
exec python3 ops/railway/migrate_r99q41.py "${ARGS[@]}"
