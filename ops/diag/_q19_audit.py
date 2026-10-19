"""R99q19 — audit every painted line of the 7 charts he sent (data coords)."""
import sys, os, dataclasses, json, math
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")
import psycopg2
import matplotlib
matplotlib.use("Agg")
import matplotlib.axes as _Ax
import matplotlib.pyplot as _plt

REC = []
_p = _Ax.Axes.plot
_axh = _Ax.Axes.axhline
_sp = _plt.subplots


def _plot(self, *a, **kw):
    try:
        if a and hasattr(a[0], "__len__") and len(a) >= 2:
            xs = list(a[0]); ys = list(a[1])
            REC.append({"k": "plot", "n": len(xs), "x0": float(xs[0]), "x1": float(xs[-1]),
                        "y0": float(ys[0]), "y1": float(ys[-1]),
                        "c": str(kw.get("color")), "ls": str(kw.get("linestyle")),
                        "lw": kw.get("linewidth")})
    except Exception:
        pass
    return _p(self, *a, **kw)


def _hline(self, y, *a, **kw):
    try:
        REC.append({"k": "axhline", "n": 2, "x0": 0.0, "x1": 1.0, "y0": float(y), "y1": float(y),
                    "c": str(kw.get("color")), "ls": str(kw.get("linestyle")), "lw": kw.get("linewidth")})
    except Exception:
        pass
    return _axh(self, y, *a, **kw)


def _sub(*a, **kw):
    fig, ax = _sp(*a, **kw)
    REC.append({"k": "AXES", "ax": ax, "fig": fig})
    return fig, ax


_Ax.Axes.plot = _plot
_Ax.Axes.axhline = _hline
_plt.subplots = _sub

DSN = os.environ["VIVA_DB_DSN"]
CODES = sys.argv[1:] or ["K172967", "K749619", "K107736", "K717222",
                         "T700976", "T661070", "T497775"]
cn = psycopg2.connect(DSN, connect_timeout=25); cu = cn.cursor()

from analysis.models import SignalCandidate
from data.fetcher import get_klines
import bot.messages_v7 as B7

for code in CODES:
    cu.execute("""select signal_id, symbol, trigger_tf, setup_code, direction, status,
                         payload::jsonb, created_at
                  from signal_candidates where payload::text like %s
                  order by created_at desc limit 1""", (f"%{code}%",))
    row = cu.fetchone()
    if not row:
        print(f"### {code} NOT FOUND"); continue
    sid, sym, tf, setup, dirn, status, pl, created = row
    md = pl.get("metadata") or {}
    known = {f.name for f in dataclasses.fields(SignalCandidate)}
    cand = SignalCandidate(**{k: v for k, v in pl.items() if k in known})
    cand.metadata = md
    chart_tf = str(md.get("chart_view_tf") or tf)
    df = get_klines(sym, chart_tf, 400)
    del REC[:]
    try:
        png = B7.generate_chart(df, cand, confirmed=True)
    except Exception as e:
        print(f"### {code} render ERR {e}"); continue
    ax = next((r["ax"] for r in REC if r["k"] == "AXES"), None)
    xl = ax.get_xlim() if ax else (0, 0)
    print(f"\n### {code} {sym} {chart_tf} ({setup}, {dirn}, {status}) "
          f"chart_view_tf={chart_tf} bars={len(df)} xlim=({xl[0]:.0f},{xl[1]:.0f}) "
          f"visible={xl[1]-xl[0]:.0f} png={len(png or b'')}")
    n = int(xl[1])
    for r in REC:
        if r["k"] != "plot":
            continue
        if abs(r["x1"] - r["x0"]) < 3 and r["n"] < 3:
            continue
        # value of the line at the live bar and 60 bars back
        try:
            sl = (r["y1"] - r["y0"]) / (r["x1"] - r["x0"]) if r["x1"] != r["x0"] else 0.0
            y_now = r["y0"] + sl * (n - r["x0"])
        except Exception:
            y_now = float("nan")
        print(f"   {r['c']:9s} lw={str(r['lw']):5s} ls={str(r['ls'])[:12]:12s} "
              f"x[{r['x0']:7.1f}..{r['x1']:7.1f}] y[{r['y0']:9.5g}..{r['y1']:9.5g}] "
              f"@live={y_now:9.5g}")
cn.close()
