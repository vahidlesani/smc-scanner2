"""Paint-path tracer: log native-verdicts, refits, fits, guard-skips."""
import sys
TREE = sys.argv[1] if len(sys.argv) > 1 else "/home/user/smc-scanner2"
sys.path.insert(0, TREE)
print("TREE:", TREE)
import math
import pandas as pd
import bot.messages_v7 as M
import analysis.render_kit  # noqa  (pin TREE in sys.modules before aero exec)
import analysis.models  # noqa
import analysis.snapshot_lock  # noqa

_orig_native = M._viva_points_native
def logged_native(points, frame):
    r = _orig_native(points, frame)
    ts = [str((p or {}).get("timestamp"))[:16] for p in (points or [])]
    print(f"NATIVE verdict={r} npts={len(points or [])} pts={ts} "
          f"frame={str(frame.index[0])[:16]}..{str(frame.index[-1])[:16]} n={len(frame)}")
    return r
M._viva_points_native = logged_native

_orig_refit = M._refit_viva_points
def logged_refit(frame, side):
    r = _orig_refit(frame, side)
    print(f"REFIT side={side} -> {len(r or [])} pts "
          f"{[(str((p or {}).get('timestamp'))[:16], round(float((p or {}).get('price') or 0), 1)) for p in (r or [])]}")
    return r
M._refit_viva_points = logged_refit

_orig_fit = M._pivot_line_fit
def logged_fit(ax, frame, xs, ys):
    out = _orig_fit(ax, frame, xs, ys)
    print(f"FIT xs={[round(float(v), 1) for v in xs]} "
          f"ys={[round(float(v), 1) for v in ys]} -> mode={out[0]} slope={out[1]:.4f}")
    return out
M._pivot_line_fit = logged_fit

# reuse the AERO probe's chain/frames (confirm stage only)
sys.path.insert(0, "/home/user")
import importlib.util
spec = importlib.util.spec_from_file_location("aero", "/home/user/probe_setups_AERO.py")
aero = importlib.util.module_from_spec(spec)
# neutralize aero's own sys.path insert (already have TREE first)
importlib.util.LazyLoader  # noqa
spec.loader.exec_module(aero)
aero.main()
