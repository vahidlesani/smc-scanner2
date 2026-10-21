"""What does TC's own detector produce BEFORE the refine filter? (live replay)"""
import sys, os, json, dataclasses
sys.path.insert(0, "/home/user/.fresh"); os.chdir("/home/user/.fresh")
import psycopg2
DSN = os.environ["VIVA_DB_DSN"]
SYM = sys.argv[1] if len(sys.argv) > 1 else "LITUSDT"
TF = sys.argv[2] if len(sys.argv) > 2 else "1h"

import analysis.techclassic as TC
# 1) neuter the refiner so we can see the raw geometry
_orig = TC.tc_refine_geometry
def _noop(candidate, bundle=None):
    return candidate
TC.tc_refine_geometry = _noop
import analysis.quality_engine as QE
QE.__dict__["__tc_patched__"] = True

from data.fetcher import get_market_bundle
from analysis.candle_counts import render_count, fetch_limits
from analysis.render_kit import detect_patterns, _chart_will_be_log
from analysis.models import SignalCandidate

b = get_market_bundle(SYM, ("15m", "1h", "4h", "1d"), limits=fetch_limits())
df = b.get(TF)
print(f"{SYM} {TF}: frame bars = {len(df)}")
rw = render_count(TF, 300)
print("render_count(tf,300) =", rw)
tail = df.tail(rw).reset_index(drop=True)
print("tail bars =", len(tail), "| offset =", max(0, len(df) - rw))
pats = detect_patterns(tail, "SHORT", log_axis=True)
print("detector patterns:", len(pats))
for p in pats:
    print(f"  type={p.get('type')} name={p.get('name')}")
    for L in (p.get("lines") or []):
        pts = L.get("points") or []
        print(f"     side={L.get('side')} x0={L.get('x0')} x1={L.get('x1')} "
              f"npts={len(pts)} slope={L.get('slope')} log={L.get('log_fit')} "
              f"break_x={L.get('break_x')}")
        for q in pts[:5]:
            print(f"        • {q.get('ts')} @ {q.get('price')}")
print("--- validator verdicts (live = len(frame)-1 =", len(df)-1, ") with label family from md")
md = {"tl_pattern": None}
for p in pats:
    print("   ", p.get("type"), "->",
          TC.tc_validate_pattern(p, "WEDGE", len(df) - 1, TF),
          "|| live=tail-1 ->", TC.tc_validate_pattern(p, "WEDGE", len(tail) - 1, TF))
