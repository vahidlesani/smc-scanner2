#!/usr/bin/env bash
# R62-ARENA Railway ops — access | usage | backup | deploy
# Runs in GitHub Actions (.github/workflows/railway-ops.yml) or locally:
#   export RAILWAY_TOKEN=<project token>   # never commit it
#   bash ops/railway/ops.sh access
# SECURITY: prints names/status only. Variable VALUES and DB URLs are masked
# (GitHub ::add-mask::) and only ever leave the runner inside an AES-256
# encrypted archive (backup) protected by BACKUP_PASSPHRASE.
set -euo pipefail
ACTION="${1:-access}"
SERVICE="${2:-${RAILWAY_SERVICE:-}}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mask() { [ -n "${GITHUB_ACTIONS:-}" ] && [ -n "$1" ] && echo "::add-mask::$1" || true; }

command -v railway >/dev/null || npm i -g @railway/cli >/dev/null 2>&1
railway --version

services() { python3 "$HERE/rw_api.py" access | sed -n 's/^- \([^ ]*\)  id=.*/\1/p'; }

case "$ACTION" in
  access)
    # R63-ACCESS: authenticate and read metadata only. Do not fetch variable
    # values just to print their names; no credentials or launch commands.
    python3 "$HERE/rw_api.py" access
    ;;
  usage)
    python3 "$HERE/rw_api.py" usage
    ;;
  backup)
    : "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE secret is required for backup}"
    mask "$BACKUP_PASSPHRASE"
    STAMP="$(date -u +%Y%m%d-%H%M%S)"
    WORK="$(mktemp -d)"; OUT="${BACKUP_OUT:-$PWD/backup-out}"; mkdir -p "$OUT"
    echo "== project snapshot"; python3 "$HERE/rw_api.py" access > "$WORK/project.txt" || true
    DBURL=""
    for s in $(services); do
      railway variables --service "$s" --json > "$WORK/vars-$s.json" 2>/dev/null || continue
      # mask every value before anything else can echo it
      python3 - "$WORK/vars-$s.json" <<'PY' | while read -r v; do mask "$v"; done
import json,sys
for v in json.load(open(sys.argv[1])).values():
    v=str(v)
    if len(v)>=6: print(v)
PY
      for k in DATABASE_PUBLIC_URL DATABASE_URL; do
        v="$(python3 -c "import json,sys;print(json.load(open('$WORK/vars-$s.json')).get('$k',''))")"
        if [ -n "$v" ] && [ -z "$DBURL" ] && ! grep -q "railway.internal" <<<"$v"; then DBURL="$v"; echo "db source: $s/$k"; fi
      done
      echo "vars saved (encrypted later): $s ($(python3 -c "import json;print(len(json.load(open('$WORK/vars-$s.json'))))" ) keys)"
    done
    if [ -n "$DBURL" ]; then
      mask "$DBURL"
      if ! command -v pg_dump >/dev/null || [ "$(pg_dump --version | grep -oE '[0-9]+' | head -1)" -lt 17 ]; then
        sudo install -d /usr/share/postgresql-common/pgdg
        sudo curl -fsSo /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc
        echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list >/dev/null
        sudo apt-get -qq update && sudo apt-get -qq install -y postgresql-client-17 >/dev/null
        export PATH="/usr/lib/postgresql/17/bin:$PATH"
      fi
      echo "== pg_dump ($(pg_dump --version))"
      pg_dump "$DBURL" --no-owner --no-privileges -Fc -f "$WORK/db.dump"
      pg_dump "$DBURL" --no-owner --no-privileges --schema-only -f "$WORK/schema.sql"
      ls -la "$WORK/db.dump" | awk '{print "db.dump bytes:",$5}'
    else
      echo "!! no reachable DATABASE_URL — if the app uses SQLite on a volume, run: railway ssh -s <svc> 'sqlite3 \$DB_PATH .dump' > db.sql"
    fi
    git rev-parse HEAD > "$WORK/git_head.txt" 2>/dev/null || true
    tar -C "$WORK" -czf "$WORK/../viva-railway-$STAMP.tgz" .
    gpg --batch --yes --pinentry-mode loopback --passphrase "$BACKUP_PASSPHRASE" \
        --symmetric --cipher-algo AES256 -o "$OUT/viva-railway-$STAMP.tgz.gpg" "$WORK/../viva-railway-$STAMP.tgz"
    (cd "$OUT" && sha256sum "viva-railway-$STAMP.tgz.gpg" | tee "viva-railway-$STAMP.sha256")
    shred -u "$WORK"/* "$WORK/../viva-railway-$STAMP.tgz" 2>/dev/null || rm -rf "$WORK"
    echo "encrypted backup ready: $OUT/viva-railway-$STAMP.tgz.gpg"
    echo "restore: gpg -d FILE.gpg | tar xz ; pg_restore --no-owner -d \"\$NEW_DATABASE_URL\" db.dump"
    ;;
  deploy)
    : "${SERVICE:?service name required (request.json \"service\")}"
    railway up --service "$SERVICE" --detach 2>&1 | grep -v -i "token" || true
    ;;
  *) echo "unknown action $ACTION"; exit 2;;
esac
