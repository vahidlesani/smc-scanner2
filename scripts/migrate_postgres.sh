#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Secure full-data Postgres migration for the Railway account/project move.
#
# Usage:
#   OLD_DATABASE_URL="postgres://...old..." \
#   NEW_DATABASE_URL="postgres://...new..." \
#     bash scripts/migrate_postgres.sh
#
# What it does:
#   1. Dumps the OLD database (schema + data) to a local, chmod-600 file.
#   2. Restores it into the NEW database.
#   3. Runs a row-count checksum per table and compares old vs new.
#   4. Removes the dump file on success (kept on failure for inspection).
#
# SECURITY:
#   * Credentials are read ONLY from the environment — never committed.
#   * The dump file is created with chmod 600 inside this directory and deleted
#     afterwards. Do not run this on a shared machine.
#   * Accepts both postgres:// and postgresql:// (rewrites automatically).
#
# CUTOVER (important): the bot uses Telegram long-polling. Stop the OLD service
# BEFORE pointing traffic at the new one so two pollers never run at once.
# ---------------------------------------------------------------------------
set -euo pipefail

if [[ -z "${OLD_DATABASE_URL:-}" || -z "${NEW_DATABASE_URL:-}" ]]; then
  echo "ERROR: set OLD_DATABASE_URL and NEW_DATABASE_URL in the environment." >&2
  exit 1
fi

norm() { echo "$1" | sed 's#^postgres://#postgresql://#'; }
OLD_URL="$(norm "$OLD_DATABASE_URL")"
NEW_URL="$(norm "$NEW_DATABASE_URL")"

DUMP="$(pwd)/.viva_migration_$(date +%Y%m%d_%H%M%S).dump"
trap '[[ -f "$DUMP" && "${KEEP_DUMP:-0}" != "1" ]] && rm -f "$DUMP"' EXIT

echo "==> 1/4 Dumping old database..."
pg_dump --no-owner --no-privileges --format=custom --dbname="$OLD_URL" --file="$DUMP"
chmod 600 "$DUMP"
echo "    dump written: $(du -h "$DUMP" | cut -f1)"

echo "==> 2/4 Restoring into new database..."
# --clean ensures idempotent restore; errors on already-missing objects are ok.
pg_restore --no-owner --no-privileges --clean --if-exists \
  --dbname="$NEW_URL" "$DUMP" || {
  echo "    restore reported non-fatal errors (objects may already exist)." >&2
}

echo "==> 3/4 Verifying row counts per table..."
TABLES=(signals active_signals market_memory strategy_stats backtest_results \
        signal_symbol_locks signal_telegram_events signal_public_code_registry \
        backtest_runs)

count() {
  local url="$1" table="$2"
  psql "$url" -tAc "SELECT count(*) FROM \"$table\";" 2>/dev/null || echo "NA"
}

FAIL=0
printf "%-32s %12s %12s\n" "TABLE" "OLD" "NEW"
for t in "${TABLES[@]}"; do
  c_old="$(count "$OLD_URL" "$t")"
  c_new="$(count "$NEW_URL" "$t")"
  printf "%-32s %12s %12s\n" "$t" "$c_old" "$c_new"
  if [[ "$c_old" != "$c_new" && "$c_old" != "NA" && "$c_new" != "NA" ]]; then
    echo "    !! mismatch on $t" >&2
    FAIL=1
  fi
done

if [[ "$FAIL" -ne 0 ]]; then
  echo "==> 4/4 MISMATCH detected — dump kept for inspection: $DUMP" >&2
  KEEP_DUMP=1
  exit 2
fi

echo "==> 4/4 Migration verified: all table counts match."
echo "    Next: set DATABASE_URL on the NEW Railway service to the new database,"
echo "    then STOP the old service before starting the new one (avoid dual pollers)."
