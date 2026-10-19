"""R99q17: list every line the ETH 15M PINVAL chart actually paints (data coords)."""
import sys, os, dataclasses, json
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")
import psycopg2
import matplotlib
matplotlib.use("Agg")
import matplotlib.axes as _Ax

REC = []
_orig = _Ax.Axes.plot


def _p(self, *a, **kw):
    try:
        if a and hasattr(a[0], "__len__") and len(a) >= 2:
            xs = list(a[0]); ys = list(a[1])
            REC.append({"n": len(xs), "x0": float(xs[0]), "x1": float(xs[-1]),
                        "y0": float(ys[0]), "y1": float(ys[-1]),
                        "color": str(kw.get("color")), "ls": str(kw.get("linestyle")),
                        "lw": kw.get("linewidth"), "alpha": kw.get("alpha")})
    except Exception:
        pass
    return _orig(self, *a, **kw)


_Ax.Axes.plot = _p

DSN = os.environ["VIVA_DB_DSN"]
cn = psycopg2.connect(DSN, connect_timeout=20); cu = cn.cursor()
cu.execute("""select payload::jsonb, symbol, trigger_tf from signal_candidates
              where payload::jsonb->'metadata'->>'public_code'=%s limit 1""",
           ("VIVA-PINWALL-K108944",))
pl, SYM, TF = cu.fetchone(); cn.close()

from analysis.models import SignalCandidate
from data.fetcher import get_klines
import bot.messages_v7 as B7
known = {f.name for f in dataclasses.fields(SignalCandidate)}
cand = SignalCandidate(**{k: v for k, v in pl.items() if k in known})
cand.metadata = pl.get("metadata") or {}
df = get_klines(SYM, TF, 400)
png = B7.generate_chart(df, cand, confirmed=True)
print(f"{SYM} {TF} bars={len(df)} png={len(png or b'')}")
print(f"{'color':10s} {'lw':>5s} {'alpha':>6s}  x0→x1        y0→y1         ls")
for r in REC:
    if float(r["x1"]) - float(r["x0"]) < 3:
        continue
    print(f"{r['color']:10s} {str(r['lw']):>5s} {str(r['alpha']):>6s}  "
          f"{r['x0']:7.1f}→{r['x1']:7.1f}  {r['y0']:9.2f}→{r['y1']:9.2f}  {r['ls']}")
