"""R99q19 proof — re-mint geometry for his 7 charts and audit the canvas.

For each stored alert: fetch a fresh trigger frame, re-run the render kit
(patterns + the R99q19 fit-frame stamp) and the setup's OWN refine, then render
and trace every long line that reaches the picture.
"""
import sys, os, dataclasses, json, math
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")
import psycopg2
import matplotlib
matplotlib.use("Agg")
import matplotlib.axes as _Ax

REC = []
_p = _Ax.Axes.plot


def _plot(self, *a, **kw):
    try:
        if a and hasattr(a[0], "__len__") and len(a) >= 2:
            xs = list(a[0]); ys = list(a[1])
            REC.append({"n": len(xs), "x0": float(xs[0]), "x1": float(xs[-1]),
                        "y0": float(ys[0]), "y1": float(ys[-1]),
                        "c": str(kw.get("color")), "ls": str(kw.get("linestyle"))[:12],
                        "lw": kw.get("linewidth")})
    except Exception:
        pass
    return _p(self, *a, **kw)


_Ax.Axes.plot = _plot

DSN = os.environ["VIVA_DB_DSN"]
CODES = sys.argv[1:] or ["K172967", "K749619", "K107736", "K717222",
                         "T700976", "T661070", "T497775"]

from analysis.models import SignalCandidate
from data.fetcher import get_klines, get_market_bundle
from analysis.candle_counts import fetch_limits
from analysis.render_kit import enrich_render
import bot.messages_v7 as B7

cn = psycopg2.connect(DSN, connect_timeout=25); cu = cn.cursor()
for code in CODES:
    cu.execute("""select signal_id, symbol, trigger_tf, setup_code, direction, status,
                         payload::jsonb, created_at
                  from signal_candidates where payload::text like %s
                  order by created_at desc limit 1""", (f"%{code}%",))
    row = cu.fetchone()
    if not row:
        print(f"### {code} NOT FOUND"); continue
    sid, sym, tf, setup, dirn, status, pl, created = row
    md = dict(pl.get("metadata") or {})
    known = {f.name for f in dataclasses.fields(SignalCandidate)}
    cand = SignalCandidate(**{k: v for k, v in pl.items() if k in known})
    md.pop("snapshot_locked", None)          # a FRESH mint (what a new alert sees)
    md.pop("confirmed_snapshot", None)
    cand.metadata = md
    chart_tf = str(md.get("chart_view_tf") or tf).lower()
    bundle = get_market_bundle(sym, ("5m", "15m", "30m", "1h", "2h", "4h", "1d"),
                               limits=fetch_limits())
    trig = bundle.get(str(tf).lower())
    if trig is None or not len(trig):
        trig = get_klines(sym, tf, 400)
    # fresh geometry through the REAL kit + the setup's own refine
    cand.metadata["render_patterns"] = []
    enrich_render(cand, trig)
    if setup.upper() == "TECHCLASSIC":
        from analysis.techclassic import tc_refine_geometry
        tc_refine_geometry(cand, bundle)
    elif setup.upper() == "ALBROX":
        from analysis.albrox import albrox_refine_geometry
        albrox_refine_geometry(cand, bundle)
    md = cand.metadata
    rps = md.get("render_patterns") or []
    types = [p.get("type") or p.get("name") for p in rps]
    nlines = sum(len(p.get("lines") or []) for p in rps)
    npiv = sum(len(L.get("points") or []) for p in rps for L in (p.get("lines") or []))
    span = md.get("tc_pattern_span") or md.get("albrox_pattern_span") or 0
    df = get_klines(sym, chart_tf, 400)
    del REC[:]
    try:
        png = B7.generate_chart(df, cand, confirmed=True)
    except Exception as e:
        print(f"### {code} render ERR {e}"); continue
    open(f"/home/user/q19_{code}.png", "wb").write(png or b"")
    long_lines = [r for r in REC if abs(r["x1"] - r["x0"]) >= 8]
    print(f"\n### {code} {sym} {chart_tf} {setup} {dirn} — patterns={types} "
          f"lines={nlines} pivots={npiv} span={span} dropped={md.get('tc_dropped') or md.get('albrox_dropped')}")
    print(f"    fit_bars={md.get('pattern_frame_bars')} frame={len(df)} visible={md.get('chart_zoom_frozen')} "
          f"png={len(png or b'')//1024}KB")
    for r in long_lines:
        print(f"      {r['c']:9s} lw={str(r['lw']):5s} ls={r['ls']:12s} "
              f"x[{r['x0']:6.1f}..{r['x1']:6.1f}] y[{r['y0']:9.5g}..{r['y1']:9.5g}]")
cn.close()
