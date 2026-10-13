"""R78 (Viva 10-14) — perp engine matrix: EVERY setup × EVERY trigger TF.

His ruling: «r74 فقط تی‌ال‌بریک بود .. سه ستاپ دیگه نبود .. روی همه ستاپها در
همه تایمفریمهاشون باید عالی جواب بده». One shared detection/drawing core
(render_kit.detect_patterns) feeds the perp V2 renderer for TLBREAK, ALBROX,
TECHCLASSIC and PINVAL across 15m/1h/4h/1d, with the retest-entry law
(entry on the broken line, not the chase price).

Usage: python tools/r78_perp_matrix.py [outdir]
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

import database.bot_kv as _kv  # noqa: E402

_KV = {}
_kv.get_json = lambda k, d=None: _KV.get(k, d)
_kv.set_json = lambda k, v: (_KV.pop(k, None) if v is None else _KV.__setitem__(k, v))

from data.fetcher import get_klines  # noqa: E402
from analysis.render_kit import detect_patterns  # noqa: E402
from analysis.perp_pattern_engine import render_viva_perp_chart  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402

SETUPS = ["TLBREAK", "ALBROX", "TECHCLASSIC", "PINVAL"]
TFS = ["15m", "1h", "4h", "1d"]
SYMBOLS = {"15m": ["BTCUSDT"], "1h": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
           "4h": ["SOLUSDT"], "1d": ["BTCUSDT"]}


def _line_now(pat, last_ts):
    """The broken line projected AT the live bar (same law as production's
    line.price_at(n)) — never a chord midpoint."""
    for ln in (pat.get("lines") or []):
        pts = ln.get("points") or []
        if len(pts) >= 2:
            ta = pd.Timestamp(str(pts[0]["ts"]))
            tb = pd.Timestamp(str(pts[-1]["ts"]))
            pa, pb = float(pts[0]["price"]), float(pts[-1]["price"])
            dt = (tb - ta).total_seconds()
            if dt > 0:
                return pb + (pb - pa) / dt * (last_ts - tb).total_seconds()
            return pb
    return 0.0


def build_case(sym, tf, setup):
    df = get_klines(sym, tf, 400, closed_only=True, use_cache=False)
    det = df.tail(300).reset_index(drop=True)
    best, best_dir = None, "LONG"
    for d in ("LONG", "SHORT"):
        pats = detect_patterns(det, d, log_axis=True) or []
        pick = next((p for p in pats if len(p.get("lines") or []) >= 2), None)
        if pick and (best is None or len(pick["lines"]) > len(best["lines"])):
            best, best_dir = pick, d
    if best is None:
        return None, None
    n = len(det)
    atr = float((det.high - det.low).tail(14).mean())
    live = float(det.close.iloc[-1])
    entry = _line_now(best, det.timestamp.iloc[-1]) or live
    sgn = 1.0 if best_dir == "LONG" else -1.0
    md = {
        "atr": atr, "touched": True,
        "tool_entry_ts": str(det.timestamp.iloc[-40]),
        "render_patterns": [best],
        "leverage": {"15m": 5, "1h": 5, "4h": 3, "1d": 2}.get(tf, 3),
        "trailing_stop": entry - sgn * 1.1 * atr,
        "target_ladder": {
            "targets": [entry + sgn * 1.6 * atr, entry + sgn * 2.6 * atr,
                        entry + sgn * 3.4 * atr],
            "weights": [40.0, 35.0, 25.0], "path_pct": 3.0},
    }
    cs = SignalCandidate(
        signal_id=f"M{setup}{tf}", symbol=sym, style="SWING", setup_code=setup,
        setup_name=setup, strategy_fa=setup, direction=best_dir, score=8,
        status="ANALYSIS",
        entry_zone_bottom=min(entry, entry) - 0.15 * atr,
        entry_zone_top=entry + 0.15 * atr, planned_entry=entry,
        sl=entry - sgn * 1.7 * atr, tp1=entry + sgn * 1.6 * atr,
        tp2=entry + sgn * 2.6 * atr, rr_tp1=1.4, rr_tp2=2.2,
        bias="BULL" if best_dir == "LONG" else "BEAR",
        trigger_timeframe=tf, mandatory_gates={"zone": True},
        created_at=str(det.timestamp.iloc[-70]),
        confirmed_at=str(det.timestamp.iloc[-69]), metadata=md)
    return det, cs


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/home/user/renders_r78"
    import os
    os.makedirs(out, exist_ok=True)
    report = {}
    for setup in SETUPS:
        for tf in TFS:
            df = cs = None
            for sym in SYMBOLS[tf]:
                df, cs = build_case(sym, tf, setup)
                if df is not None:
                    break
            try:
                if df is None:
                    report[f"{setup}/{tf}"] = "no-pattern"
                    continue
                png = render_viva_perp_chart(df, cs, confirmed=True)
                path = f"{out}/perp_{setup}_{tf}.png"
                open(path, "wb").write(png)
                report[f"{setup}/{tf}"] = f"ok {len(png)//1024}kb {cs.direction}"
            except Exception as exc:
                report[f"{setup}/{tf}"] = f"ERR {type(exc).__name__}: {exc}"[:120]
    for k, v in report.items():
        print(k, "->", v)


if __name__ == "__main__":
    main()
