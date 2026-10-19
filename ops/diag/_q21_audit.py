"""R99q21 — the unique-id DRIFT audit (his 10-16: «در برخی شناسه‌های یکتا دقت کن
هشدار ابتدایی بصورت صحیح پترن رسم شده بوده الان در زمان تایید یه چیز دیگه میده
یا اصلا پترنی وجود نداره»).

For the newest signals it prints, per unique id, every label the pipeline keeps
for the SAME chart:

    setup engine  `pattern_type`   (minted at candidate creation)
    renderer      `tl_pattern` / `render_htf_pattern`   (the pill)
    the drawn set `render_patterns[].type` + the LAW's verdict per shape
                  (`law_slug` · `near_break` · `break_state` · `dist_atr`)

DRIFT  = the three disagree (this is the bug he caught).
PAST   = every drawn shape is far/stale (a past-market pattern — gated now).

usage:  python3 ops/diag/_q21_audit.py [--days 4] [--limit 40] [--json out.json]
"""
from __future__ import annotations
import os

import argparse
import json
import sys

DSN = os.environ["VIVA_DB_DSN"]

_LEGACY = {"", "NONE", "RANGE", "TRENDLINE", "TRIANGLE", "CHANNEL"}


def _slug_set(md: dict) -> set:
    out = set()
    for p in (md.get("render_patterns") or []):
        if isinstance(p, dict):
            s = str(p.get("law_slug") or p.get("type") or "").upper()
            if s:
                out.add(s)
    return out


def audit(days: int = 4, limit: int = 40) -> list:
    import psycopg2
    cn = psycopg2.connect(DSN, connect_timeout=25)
    cu = cn.cursor()
    cu.execute("""
        select signal_id, symbol, trigger_tf, setup_code, status, created_at,
               payload::jsonb
          from signal_candidates
         where created_at::timestamptz > now() - (%s || ' days')::interval
         order by created_at::timestamptz desc
         limit %s""", (str(int(days)), int(limit)))
    rows = []
    for sid, sym, tf, setup, status, ts, pl in cu.fetchall():
        md = dict((pl or {}).get("metadata") or {})
        pat_type = str(md.get("pattern_type") or "").upper()
        tl = str(md.get("tl_pattern") or "").upper()
        htf = str(md.get("render_htf_pattern") or "").upper()
        drawn = _slug_set(md)
        shapes = [{"type": p.get("type"), "law_slug": p.get("law_slug"),
                   "near_break": p.get("near_break"),
                   "break_state": p.get("break_state"),
                   "dist_atr": p.get("dist_atr")}
                  for p in (md.get("render_patterns") or []) if isinstance(p, dict)]
        name_y = {pat_type} - _LEGACY
        name_t = {tl} - _LEGACY
        verdict = "OK"
        if not shapes:
            verdict = "NO-PATTERN"
        elif all(s.get("near_break") is False for s in shapes):
            verdict = "PAST"
        if name_y and name_t and name_y != name_t:
            verdict = "DRIFT"
        elif name_y and drawn and not (name_y & drawn):
            verdict = "DRIFT"
        rows.append({"signal_id": sid, "symbol": sym, "tf": tf, "setup": setup,
                     "status": status, "created_at": str(ts),
                     "pattern_type": pat_type, "tl_pattern": tl,
                     "render_htf_pattern": htf, "drawn": sorted(drawn),
                     "shapes": shapes, "verdict": verdict})
    cn.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = audit(a.days, a.limit)
    counts: dict = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        print(f"[{r['verdict']:10s}] {r['signal_id'][:38]:38s} {r['setup']:11s} "
              f"engine={r['pattern_type'] or '-':20s} pill={r['tl_pattern'] or '-':20s} "
              f"drawn={','.join(s.get('law_slug') or s.get('type') or '?' for s in r['shapes']) or '-'}")
    print("\nsummary:", counts)
    if a.json:
        json.dump(rows, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("json ->", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
