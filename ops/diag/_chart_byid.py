"""Re-render ANY real prod chain by signal_id (R99q15 diagnostic harness).

usage: python3 /home/user/_chart_byid.py <SIGNAL_ID> [confirmed=0|1] [tag]
"""
import sys, os, dataclasses
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")
import psycopg2

DSN = os.environ["VIVA_DB_DSN"]
SID = sys.argv[1]
CONF = (len(sys.argv) > 2 and str(sys.argv[2]) not in ("0", "false", "False"))
TAG = sys.argv[3] if len(sys.argv) > 3 else "q15"

con = psycopg2.connect(DSN, connect_timeout=20); cur = con.cursor()
cur.execute("""select payload::jsonb, symbol, trigger_tf, setup_code from signal_candidates
               where signal_id=%s limit 1""", (SID,))
row = cur.fetchone(); con.close()
if not row:
    print("no chain", SID); sys.exit(1)
pl, SYM, TF, SETUP = row[0], row[1], row[2], row[3]

from analysis.models import SignalCandidate
from data.fetcher import get_klines
import bot.messages_v7 as B7

known = {f.name for f in dataclasses.fields(SignalCandidate)}
cand = SignalCandidate(**{k: v for k, v in pl.items() if k in known})
md = pl.get("metadata") or {}
cand.metadata = md
try:
    df = get_klines(SYM, TF, 400)
except Exception:
    df = None
if df is None or df.empty:
    df = get_klines(SYM, "30m", 400)
print(f"{SID} {SYM} {TF} {SETUP}: bars={len(df)} "
      f"rp={len(md.get('render_patterns') or [])} rz={len(md.get('render_zones') or [])} "
      f"up={len(md.get('viva_upper_points') or [])} lo={len(md.get('viva_lower_points') or [])}")
png = B7.generate_chart(df, cand, confirmed=CONF)
out = f"/home/user/proof_q15_{SYM}_{TF}_{SETUP}_{TAG}.png"
if png:
    open(out, "wb").write(png); print("chart ->", out, len(png))
else:
    print("chart: None")
