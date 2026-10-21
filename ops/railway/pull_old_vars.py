#!/usr/bin/env python3
"""R99q41 — pull EVERY variable of the OLD Railway service, with values.

    OLD_RAILWAY_TOKEN=... python ops/railway/pull_old_vars.py \
        --out /home/user/.viva_secrets/old_vars.json

Reads the old service through the Railway GraphQL API (the same call that
returned the 83-name list at 15:xx on 10-21) and writes a JSON of
NAME → VALUE. Then it diffs against the new service's env file and prints what
is still missing, so the migration carries the REAL values — not code defaults.

Sealed variables are returned without a value by design; they are listed under
"sealed" so they can be re-entered by hand from the dashboard.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

API = "https://backboard.railway.com/graphql/v2"
P = "dfa19d15-6e78-41b5-8a0c-8ccfc3807add"   # old project
E = "a787e251-94d1-4665-8ab4-dc9b92a10a2a"   # old environment
S = "84f5a4ef-117f-4c2d-a460-83bd290ce58a"   # old service


def gql(token: str, q: str, v: dict | None = None) -> dict:
    req = urllib.request.Request(
        API, data=json.dumps({"query": q, "variables": v or {}}).encode(), method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "User-Agent": "viva-ops/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http": e.code, "body": e.read().decode(errors="replace")[:400]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/home/user/.viva_secrets/old_vars.json")
    ap.add_argument("--compare", default="/home/user/.viva_secrets/env_r99q41.json")
    args = ap.parse_args()
    token = os.environ.get("OLD_RAILWAY_TOKEN", "").strip()
    if not token:
        raise SystemExit("OLD_RAILWAY_TOKEN is required (token of the OLD account)")

    r = gql(token, 'query($p:String!,$e:String!,$s:String!)'
                   '{variables(projectId:$p,environmentId:$e,serviceId:$s)}',
            {"p": P, "e": E, "s": S})
    if r.get("errors") or r.get("http"):
        msg = json.dumps(r, ensure_ascii=False)[:300]
        hint = ""
        if "Not Authorized" in msg:
            hint = ("\n  → the API key is refused. Either the token was revoked, or Railway is "
                    "in an incident (check https://status.railway.com). "
                    "A fresh token: old account → Account Settings → Tokens.")
        raise SystemExit("could not read the old service: " + msg + hint)

    variables = (r.get("data") or {}).get("variables") or {}
    masked = {k: v for k, v in variables.items() if v in ("", None)}
    json.dump(variables, open(args.out, "w"), indent=1, ensure_ascii=False)
    os.chmod(args.out, 0o600)
    print(f"read {len(variables)} variables → {args.out}")
    if masked:
        print("sealed / empty (re-enter by hand):", ", ".join(sorted(masked)))

    if os.path.exists(args.compare):
        have = json.load(open(args.compare))
        missing = sorted(set(variables) - set(have))
        extra = sorted(set(have) - set(variables))
        print(f"\nmissing from the NEW service ({len(missing)}):")
        for k in missing:
            print("   ", k)
        if extra:
            print(f"\nonly on the new service ({len(extra)}):", ", ".join(extra))
        merged = dict(have)
        merged.update({k: v for k, v in variables.items() if v not in ("", None)})
        out2 = args.compare.replace(".json", ".merged.json")
        json.dump(merged, open(out2, "w"), indent=1, ensure_ascii=False)
        os.chmod(out2, 0o600)
        print(f"\nmerged file written: {out2}  ({len(merged)} variables) — "
              "upload THIS as the VIVA_ENV_JSON secret / pass it to migrate_r99q41.py")


if __name__ == "__main__":
    main()
