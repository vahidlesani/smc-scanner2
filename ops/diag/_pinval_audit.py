"""Audit: do PINVAL charts actually PAINT pattern/trendline geometry? (R99q14)"""
import sys, os, json, dataclasses
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")
import psycopg2
DSN = ("postgresql://postgres.nmndchflpeigorkmqcwi:Viva2026%21.%21@"
       "aws-0-eu-central-1.pooler.supabase.com:5432/postgres")
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 14
con = psycopg2.connect(DSN); cur = con.cursor()
cur.execute("""select symbol, trigger_tf, payload::jsonb from signal_candidates
               where setup_code='PINVAL' order by created_at desc limit %s""", (LIMIT,))
rows = cur.fetchall(); con.close()

from analysis.models import SignalCandidate
from data.fetcher import get_klines
import bot.messages_v7 as B7
import matplotlib; matplotlib.use("Agg")
import matplotlib.axes as _mxa
_plot_calls = {"n": 0, "sloped": 0}
_orig_plot = _mxa.Axes.plot
def _plot_spy(self, *a, **k):
    _plot_calls["n"] += 1
    try:
        ys = list(a[1]) if len(a) > 1 else []
        xs = list(a[0]) if a else []
        if len(xs) > 1 and len(ys) > 1 and abs(float(xs[-1]) - float(xs[0])) > 1e-9 \
                and abs((float(ys[-1]) - float(ys[0])) / (float(xs[-1]) - float(xs[0]))) > 1e-9:
            _plot_calls["sloped"] += 1
    except Exception:
        pass
    return _orig_plot(self, *a, **k)
_mxa.Axes.plot = _plot_spy
known = {f.name for f in dataclasses.fields(SignalCandidate)}

_orig_cnt = B7._count_incanvas_sloped_lines
_state = {"n": -99}
def _wrap(fig):
    n = _orig_cnt(fig)
    _state["n"] = n
    return n
B7._count_incanvas_sloped_lines = _wrap

_o_nat = B7._native_patterns_for_frame
_state_nat = {}
def _nat(*a, **k):
    r = _o_nat(*a, **k)
    _state_nat["in"] = len(a[4] or []) if len(a) > 4 else -1
    _state_nat["out"] = len(r or [])
    return r
B7._native_patterns_for_frame = _nat

print(f"{'sym':10s} {'tf':4s} {'rp':>3s} {'rz':>3s} {'up':>3s} {'lo':>3s} {'nat in/out':>10s} {'sloped':>6s} {'png':>7s}  verdict")
for sym, tf, pl in rows:
    cand = SignalCandidate(**{k: v for k, v in pl.items() if k in known})
    md = pl.get("metadata") or {}
    cand.metadata = md
    df = get_klines(sym, tf, 400)
    if df is None or df.empty:
        print(f"{sym:10s} {tf:4s}  NO FRAME"); continue
    _state["n"] = -99; _state_nat.clear(); _plot_calls["n"] = 0; _plot_calls["sloped"] = 0
    png = B7.generate_chart(df, cand, confirmed=False)
    nat = f"{_state_nat.get('in','?')}/{_state_nat.get('out','?')}"
    _sl = _plot_calls["sloped"]
    v = "GEOMETRY" if _sl > 0 else "NO-GEOMETRY"
    print(f"{sym:10s} {tf:4s} {len(md.get('render_patterns') or []):3d} {len(md.get('render_zones') or []):3d} "
          f"{len(md.get('viva_upper_points') or []):3d} {len(md.get('viva_lower_points') or []):3d} "
          f"{nat:>10s} {_sl:6d} {('yes' if png else 'NONE'):>7s}  {v} (plots={_plot_calls['n']})")
