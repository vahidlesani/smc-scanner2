#!/usr/bin/env bash
# Viva Railway recovery ladder — 10-13 («ریلوی رو درست کن»)
#
#   RAILWAY_TOKEN=... bash ops/railway/recover.sh
#       → تشخیص مستقیم GraphQL از سندباکس (پروژه/سرویس/آخرین دیپلوی)
#   GITHUB_PAT=...    bash ops/railway/recover.sh
#       → پوش شاخهٔ تعمیر + دیسپچ ورک‌فلو railway-ops (action=access, nonce=8)
#         + خواندن وضعیت اجرا
#   هر دو با هم = هر دو مرحله.
#
# توکن‌ها فقط در env؛ هرگز در چت/ریپو/لاگ چاپ نمی‌شوند.
set -uo pipefail
DOMAIN="https://smc-scanner2-production.up.railway.app"
REPO="vahidlesani/smc-scanner2"

echo "== 1) health probe =="
curl -sS -m 15 -D /tmp/viva_h.txt -o /tmp/viva_h.json "$DOMAIN/health" || true
grep -Ei "^HTTP/|x-railway-fallback|^server:" /tmp/viva_h.txt || true
cat /tmp/viva_h.json; echo

if [ -n "${RAILWAY_TOKEN:-}" ]; then
  echo "== 2) Railway GraphQL: projects/services/latest deployments =="
  curl -sS -m 40 https://backboard.railway.com/graphql/v2 \
    -H "Authorization: Bearer $RAILWAY_TOKEN" -H 'Content-Type: application/json' \
    -d '{"query":"{ projects { edges { node { id name plan { planId } services { edges { node { id name updatedAt latestDeployment { id status createdAt gitCommitSha } } } } } } } }"}' \
    | head -c 4000; echo
fi

if [ -n "${GITHUB_PAT:-}" ]; then
  echo "== 3) push repair/main-10-13 =="
  git push "https://x-access-token:$GITHUB_PAT@github.com/$REPO" repair/main-10-13 2>&1 | sed 's/x-access-token:[^@]*/x-access-token:***/' || true
  echo "== 4) dispatch railway-ops (request.json: action=access nonce=8) =="
  curl -sS -m 30 -X POST -H "Authorization: token $GITHUB_PAT" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$REPO/actions/workflows/railway-ops.yml/dispatches" \
    -d '{"ref":"repair/main-10-13"}' -o /dev/null -w "dispatch HTTP %{http_code}\n"
  sleep 6
  echo "== 5) latest railway-ops runs =="
  curl -sS -m 30 -H "Authorization: token $GITHUB_PAT" \
    "https://api.github.com/repos/$REPO/actions/workflows/railway-ops.yml/runs?per_page=3" \
    | grep -E '"status"|"conclusion"|"html_url"' | head -9
fi
echo "== done =="
