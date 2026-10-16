"""R99q20 proof renders — spot samples + setup samples with the new laws.

usage: python3 ops/diag/_q20_render.py [--banner] [--spot-only|--setup-only]
Writes q20_*.png next to the repo root's parent (workspace).
"""
import sys, os, math
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")
os.environ["VIVA_NO_FREEZE_WRITE"] = "1"   # proofs must not mutate prod zoom state
os.environ["VIVA_Q20_DEBUG"] = "1"
if "--banner" in sys.argv:
    os.environ["VIVA_CREDIT_BANNER"] = "1"
    print("[banner] credit banner + name-under-logo ON")
import psycopg2, dataclasses
from PIL import Image, ImageDraw
from analysis.candle_counts import fetch_limits
from data.fetcher import get_market_bundle, get_klines

OUT = "/home/user"
TAG = os.environ.get("VIVA_RENDER_TAG") or ("q20b" if "--banner" in sys.argv else "q20")
mode_spot = "--setup-only" not in sys.argv
mode_setup = "--spot-only" not in sys.argv

if mode_spot:
    from analysis.spot_engine import SPOT_TRIGGERS, scan_spot_alerts, build_spot_alert_candidate
    import bot.messages_v7 as B7
    SPOT = [("DASHUSDT", "12h"), ("INJUSDT", "3d"), ("APTUSDT", "3d"), ("STXUSDT", "12h")]
    for sym, tf in SPOT:
        b = get_market_bundle(sym, tuple(SPOT_TRIGGERS), limits=fetch_limits())
        items = [i for i in scan_spot_alerts(sym, b) if str(i.get("tf")) == tf]
        if not items:
            print(f"spot {sym} {tf}: NO ALERT"); continue
        it = items[0]
        cand = build_spot_alert_candidate(it)
        df = None
        for attr in ("frames", "klines", "data"):
            m = getattr(b, attr, None)
            if isinstance(m, dict) and tf in m:
                df = m[tf]; break
        if df is None:
            df = get_klines(sym, tf, 400)
        png = B7.generate_chart(df, cand, confirmed=False)
        p = f"{OUT}/{TAG}_spot_{sym}_{tf}.png"
        open(p, "wb").write(png or b"")
        print(f"spot {sym:9s} {tf:>3s} stage={it.get('stage'):9s} "
              f"pattern={it.get('pattern'):20s} {len(png or b'')//1024}KB -> {os.path.basename(p)}")

if mode_setup:
    import bot.messages_v7 as B7
    from analysis.models import SignalCandidate
    from analysis.render_kit import enrich_render
    DSN = ("postgresql://postgres.nmndchflpeigorkmqcwi:Viva2026%21.%21@"
           "aws-0-eu-central-1.pooler.supabase.com:5432/postgres")
    cn = psycopg2.connect(DSN, connect_timeout=25); cu = cn.cursor()
    SETUPS = ["T700976", "T661070", "K172967", "K107736", "K717222", "T497775"]
    for code in SETUPS:
        cu.execute("""select signal_id, symbol, trigger_tf, setup_code, payload::jsonb
                      from signal_candidates where payload::text like %s
                      order by created_at desc limit 1""", (f"%{code}%",))
        row = cu.fetchone()
        if not row:
            print(f"{code}: NOT FOUND"); continue
        sid, sym, tf, setup, pl = row
        md = dict(pl.get("metadata") or {})
        known = {f.name for f in dataclasses.fields(SignalCandidate)}
        cand = SignalCandidate(**{k: v for k, v in pl.items() if k in known})
        md.pop("snapshot_locked", None)
        # R99q21: run the real restore path so the law re-stamp is exercised
        # exactly as prod's confirmation turn does.
        try:
            from analysis.snapshot_lock import lock_render_geometry as _lrg21
            cand.metadata = md
            print(f"  [lock] {code}: {_lrg21(cand, frame=None)}")
        except Exception as _e21:
            print(f"  [lock] {code}: skipped ({_e21})")
        cand.metadata = md
        chart_tf = str(md.get("chart_view_tf") or tf).lower()
        bundle = get_market_bundle(sym, ("5m", "15m", "30m", "1h", "2h", "4h", "1d"),
                                   limits=fetch_limits())
        trig = bundle.get(str(tf).lower())
        if trig is None or not len(trig):
            trig = get_klines(sym, tf, 400)
        cand.metadata["render_patterns"] = []
        enrich_render(cand, trig)
        try:
            from analysis.snapshot_lock import lock_render_geometry as _lrg21b
            _lrg21b(cand, frame=trig)
        except Exception as _e21b:
            print(f"  [lock2] {code}: skipped ({_e21b})")
        if str(setup).upper() == "TECHCLASSIC":
            from analysis.techclassic import tc_refine_geometry
            tc_refine_geometry(cand, bundle)
        elif str(setup).upper() == "ALBROX":
            from analysis.albrox import albrox_refine_geometry
            albrox_refine_geometry(cand, bundle)
        df = get_klines(sym, chart_tf, 400)
        png = B7.generate_chart(df, cand, confirmed=True)
        p = f"{OUT}/{TAG}_{code}_{sym}_{chart_tf}.png"
        open(p, "wb").write(png or b"")
        md2 = cand.metadata
        print(f"{code} {sym:9s} {chart_tf:>3s} {str(setup):10s} "
              f"patterns={[(q.get('type'), q.get('law_slug'), q.get('near_break'), q.get('break_state')) for q in (md2.get('render_patterns') or [])]} "
              f"span={md2.get('tc_pattern_span') or md2.get('albrox_pattern_span') or 0} "
              f"{len(png or b'')//1024}KB -> {os.path.basename(p)}")
    cn.close()
