"""R99q20 — inventory every long line a stored chain paints (with y at live/60-back)."""
import sys, os, dataclasses, json
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")
import psycopg2
import matplotlib; matplotlib.use("Agg")
import matplotlib.axes as _Ax
REC = []
_p = _Ax.Axes.plot
def _plot(self, *a, **kw):
    try:
        if a and hasattr(a[0], "__len__") and len(a) >= 2:
            xs = list(a[0]); ys = list(a[1])
            REC.append({"x0": float(xs[0]), "x1": float(xs[-1]), "y0": float(ys[0]),
                        "y1": float(ys[-1]), "c": str(kw.get("color")),
                        "ls": str(kw.get("linestyle"))[:12], "lw": kw.get("linewidth")})
    except Exception:
        pass
    return _p(self, *a, **kw)
_Ax.Axes.plot = _plot

from analysis.models import SignalCandidate
from data.fetcher import get_klines, get_market_bundle
from analysis.candle_counts import fetch_limits
from analysis.render_kit import enrich_render
import bot.messages_v7 as B7

DSN = os.environ["VIVA_DB_DSN"]
code = sys.argv[1] if len(sys.argv) > 1 else "T700976"
cn = psycopg2.connect(DSN, connect_timeout=25); cu = cn.cursor()
cu.execute("""select signal_id, symbol, trigger_tf, setup_code, payload::jsonb,
                     (payload::jsonb->'metadata') from signal_candidates
              where payload::text like %s order by created_at desc limit 1""", (f"%{code}%",))
sid, sym, tf, setup, pl, md0 = cu.fetchone(); cn.close()
md = dict(md0 or {})
print(f"{code} {sym} {tf} {setup} stored={[p.get('type') for p in (md.get('render_patterns') or [])]}"
      f" fit_bars={md.get('pattern_frame_bars')} off={md.get('pattern_frame_offset')}")
known = {f.name for f in dataclasses.fields(SignalCandidate)}
cand = SignalCandidate(**{k: v for k, v in pl.items() if k in known})
cand.metadata = md
chart_tf = str(md.get("chart_view_tf") or tf).lower()
bundle = get_market_bundle(sym, ("5m","15m","30m","1h","2h","4h","1d"), limits=fetch_limits())
trig = bundle.get(str(tf).lower())
if trig is None or not len(trig):
    trig = get_klines(sym, tf, 400)
cand.metadata["render_patterns"] = []
enrich_render(cand, trig)
if str(setup).upper() == "TECHCLASSIC":
    from analysis.techclassic import tc_refine_geometry; tc_refine_geometry(cand, bundle)
elif str(setup).upper() == "ALBROX":
    from analysis.albrox import albrox_refine_geometry; albrox_refine_geometry(cand, bundle)
md = cand.metadata
print("after refine:", [(p.get('type'), [(L.get('side'), L.get('x0'), L.get('x1'),
      len(L.get('points') or []), L.get('log_fit')) for L in (p.get('lines') or [])])
      for p in (md.get('render_patterns') or [])], "dropped=", md.get('tc_dropped') or md.get('albron_dropped'))
print("viva_upper_points:", len(md.get('viva_upper_points') or []),
      "| viva_lower_points:", len(md.get('viva_lower_points') or []))
df = get_klines(sym, chart_tf, 400)
del REC[:]
png = B7.generate_chart(df, cand, confirmed=True)
ax = None
open(f"/home/user/q20paint_{code}.png", "wb").write(png or b"")
print(f"png={len(png or b'')//1024}KB  frame={len(df)}")
for r in REC:
    if abs(r["x1"] - r["x0"]) < 8:
        continue
    sl = (r["y1"] - r["y0"]) / (r["x1"] - r["x0"]) if r["x1"] != r["x0"] else 0
    y_at_n = r["y0"] + sl * (len(df) - 1 - r["x0"])
    print(f"   {r['c']:9s} lw={str(r['lw'])[:5]:5s} ls={r['ls']:12s} "
          f"x[{r['x0']:6.1f}..{r['x1']:6.1f}] y[{r['y0']:8.4f}..{r['y1']:8.4f}] @live={y_at_n:8.4f}")
