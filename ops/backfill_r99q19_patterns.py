"""R99q19 back-fill — re-stamp stored chains with real pattern geometry.

Viva 10-16: «زوم اشتباه .. پترن رو نمي‌شناسه .. ترندلاين‌های ول از گذشته».
Root cause (proven on LIT 1h T700976): the shared pattern set is fitted on a
tail window (render_count bars) but the TC/ALBROX validators compared it with
the FULL frame's live index, so every sloped pattern died as «stale-end» and
the stored chain kept only a RANGE band — the chart then invented hull lines.
The live fix stamps `pattern_frame_bars` (render_kit.pattern_frame_live_index)
and judges in the pattern's own space; this script repairs the chains that were
minted BEFORE the fix (last N days, default 3).

Safety: a chain is only rewritten when the fresh detection actually yields at
least one sloped pattern; every other metadata key is preserved untouched.
Run:  python3 ops/backfill_r99q19_patterns.py [days] [--dry]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DSN = os.getenv("VIVA_DB_DSN") or os.environ["VIVA_DB_DSN"]


def main(days: int = 3, dry: bool = False) -> None:
    import psycopg2
    from analysis.candle_counts import render_count
    from analysis.render_kit import detect_patterns, _chart_will_be_log
    from data.fetcher import get_klines
    cn = psycopg2.connect(DSN, connect_timeout=25)
    cu = cn.cursor()
    cu.execute("""select signal_id, symbol, trigger_tf, setup_code, payload::jsonb
                  from signal_candidates
                  where created_at::timestamptz >= now() - (%s || ' day')::interval
                    and setup_code in ('TECHCLASSIC','ALBROX','TLBREAK','PINVAL')
                  order by created_at desc""", (int(days),))
    rows = cu.fetchall()
    fixed = skipped = 0
    for sid, sym, tf, setup, pl in rows:
        md = (pl or {}).get("metadata") or {}
        pats = md.get("render_patterns") or []
        has_sloped = any(L.get("side") for p in pats
                         for L in (p.get("lines") or []) if isinstance(L, dict))
        if has_sloped and md.get("pattern_frame_bars"):
            skipped += 1
            continue
        chart_tf = str(md.get("chart_view_tf") or tf or "1h").lower()
        try:
            df = get_klines(sym, chart_tf, 400)
            if df is None or df.empty:
                skipped += 1
                continue
        except Exception:
            skipped += 1
            continue
        try:
            rw = int(render_count(chart_tf, 300))
            sliced = df.tail(rw).reset_index(drop=True)
            fresh = detect_patterns(sliced, str((pl or {}).get("direction") or "LONG"),
                                    log_axis=True)
        except Exception as exc:
            print(f"  {sid}: detect failed {exc}")
            skipped += 1
            continue
        md["render_patterns"] = fresh
        md["pattern_frame_bars"] = int(len(sliced))
        md["pattern_frame_offset"] = int(max(0, len(df) - rw))
        # the setup's OWN validator chooses (same gate a fresh mint runs)
        try:
            import dataclasses
            from analysis.models import SignalCandidate as _SC
            _known = {f.name for f in dataclasses.fields(_SC)}
            _c = _SC(**{k: v for k, v in (pl or {}).items() if k in _known})
            _c.metadata = md
            _setup = str(setup or "").upper()
            if _setup == "TECHCLASSIC":
                from analysis.techclassic import tc_refine_geometry as _rf
                _rf(_c)
            elif _setup == "ALBROX":
                from analysis.albrox import albrox_refine_geometry as _rf
                _rf(_c)
        except Exception as exc:
            print(f"  {sid}: refine skipped {exc}")
        md = _c.metadata if isinstance(_c.metadata, dict) else md
        sloped = [p for p in (md.get("render_patterns") or [])
                  if any(L.get("side") for L in (p.get("lines") or []))]
        if not sloped:
            skipped += 1
            continue
        md["pattern_backfill_r99q19"] = True
        if not dry:
            cu.execute("""update signal_candidates
                          set payload = jsonb_set(payload::jsonb, '{metadata}', %s::jsonb, true)
                          where signal_id = %s""",
                       (json.dumps(md, ensure_ascii=False, default=str), sid))
        fixed += 1
        print(f"  {sid}: {len(sloped)} sloped pattern(s) restored "
              f"(fit={len(sliced)} bars){' [dry]' if dry else ''}")
    if not dry:
        cn.commit()
    cn.close()
    print(f"R99q19 back-fill: fixed={fixed} skipped={skipped} of {len(rows)}")


if __name__ == "__main__":
    _days = 3
    _dry = "--dry" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit():
            _days = int(a)
    main(_days, _dry)
