"""R99q19 diag — why do TC/ALBROX charts look wrong? (his 10-16 16:5x batch)"""
import sys, os, json, math
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")
import psycopg2
DSN = ("postgresql://postgres.nmndchflpeigorkmqcwi:Viva2026%21.%21@"
       "aws-0-eu-central-1.pooler.supabase.com:5432/postgres")
CODES = sys.argv[1:] or ["K172967", "K749619", "K107736", "K717222",
                         "T700976", "T661070", "T497775"]
cn = psycopg2.connect(DSN, connect_timeout=25); cu = cn.cursor()
for code in CODES:
    cu.execute("""select signal_id, symbol, trigger_tf, setup_code, direction, status,
                         payload::jsonb, created_at
                  from signal_candidates
                  where payload::text like %s
                  order by created_at desc limit 1""", (f"%{code}%",))
    row = cu.fetchone()
    if not row:
        print(f"### {code}: NOT FOUND in signal_candidates"); continue
    sid, sym, tf, setup, dirn, status, pl, created = row
    md = (pl.get("metadata") or {}) if isinstance(pl, dict) else {}
    print(f"\n### {code} {sym} {tf} {setup} {dirn} status={status} created={created}")
    print(f"    signal_id={sid}")
    keys = ["pattern_type", "pattern_state_label", "chart_view_tf", "pattern_tf",
            "strategy_variant", "viva_state", "tc_state", "htf_tf",
            "tc_candles", "candles", "zoom", "render_tf", "snapshot_locked",
            "pattern_major", "pattern_far", "distance_atr", "touches"]
    for k in keys:
        if k in md:
            print(f"    {k} = {md.get(k)!r}")
    rps = md.get("render_patterns") or []
    print(f"    render_patterns: {len(rps)}")
    for i, p in enumerate(rps):
        print(f"      [{i}] type={p.get('type')} name={p.get('name')} shape={p.get('shape')} "
              f"ts0={p.get('ts0')} hi={p.get('hi')} lo={p.get('lo')}")
        for L in (p.get("lines") or []):
            pts = L.get("points") or []
            print(f"          side={L.get('side')} log={L.get('log_fit')} "
                  f"slope={L.get('slope')} int={L.get('intercept')} "
                  f"x0={L.get('x0')} x1={L.get('x1')} break_x={L.get('break_x')} npts={len(pts)}")
            for q in pts[:6]:
                print(f"              • {q.get('ts')} @ {q.get('price')}")
    for k in ("viva_upper_points", "viva_lower_points"):
        pts = md.get(k) or []
        if pts:
            print(f"    {k}: {len(pts)} pts " + " | ".join(f"{p.get('timestamp')}@{p.get('price')}" for p in pts[:6]))
    # all keys present, for completeness on the first pass
    if os.getenv("VIVA_DIAG_ALL"):
        print("    md keys:", sorted(md.keys()))
cn.close()
