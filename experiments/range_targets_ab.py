"""A/B replay of Viva's range-fraction target rule on the 90d v7 detections.

Rule (his spec): only taken when direction matches the range EDGE —
LONG in DISCOUNT, SHORT in PREMIUM. Targets are then fractions of the TRADING
RANGE height H measured from the boundary: TP1 = 0.40xH, TP2 = 0.70xH
(longs: up from range low; shorts: down from range high) — "smaller, more
probable targets, not the far edge of the path".

The collected candidates are replayed twice with identical confirmations:
  BASE  -> original structural targets baked into the pickle
  RANGE -> recomputed range-fraction targets (only when edge-aligned)
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from analysis.backtest import _simulate_trade  # noqa: E402
from analysis.indicators import premium_discount  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402
from experiments.diagnose_funnel import ConfirmProfile, build_index_map, instrumented_wait, slice_by_count  # noqa: E402
from experiments.okx_feed import load_frames  # noqa: E402

CAPS = {"1d": 0, "4h": 280, "1h": 280, "15m": 340, "5m": 460}
RESULTS = REPO / "experiments" / "results"


def replay_cell(symbol: str, style: str, days: int, profile: ConfirmProfile) -> dict:
    frames, trigger_tf = load_frames(symbol, style, days)
    trigger = frames[trigger_tf]
    context_tf = "4h" if style == "SWING" else "1h"
    index_maps = {tf: build_index_map(f, trigger["timestamp"]) for tf, f in frames.items()}
    pkl = RESULTS / f"detections_{symbol}_{style}_{days}d_sl1.0_n{1 if style == 'SWING' else 3}.pkl"
    detections = pickle.load(open(pkl, "rb"))["detections"]

    out = {"symbol": symbol, "style": style, "profile": profile.name,
           "variants": {}, "range_applied": 0, "range_skipped_side": 0}
    for variant in ("BASE", "RANGE"):
        trades, reports = [], []
        for det in detections:
            candidate = SignalCandidate.from_json(det["candidate"])
            if variant == "RANGE":
                idx = int(det["index"])
                sliced = {}
                for tf, frame in frames.items():
                    count = int(index_maps[tf][idx])
                    sliced[tf] = slice_by_count(frame, count, 60 if tf != "1d" else 0, cap=CAPS.get(tf, 0))
                ctx = sliced.get(context_tf)
                if ctx is None or len(ctx) < 30:
                    pass
                else:
                    pd_loc = premium_discount(ctx)
                    high, low = float(pd_loc["high"]), float(pd_loc["low"])
                    H = high - low
                    loc = pd_loc["location"]
                    entry, sl = candidate.planned_entry, candidate.sl
                    edge_ok = ((candidate.direction == "LONG" and loc == "DISCOUNT")
                               or (candidate.direction == "SHORT" and loc == "PREMIUM"))
                    if edge_ok and H > 0:
                        if candidate.direction == "LONG":
                            tp1, tp2 = low + 0.40 * H, low + 0.70 * H
                        else:
                            tp1, tp2 = high - 0.40 * H, high - 0.70 * H
                        # keep targets on the profitable side of entry
                        if (candidate.direction == "LONG" and tp1 > entry) or (candidate.direction == "SHORT" and tp1 < entry):
                            candidate.tp1, candidate.tp2 = tp1, tp2
                            risk = abs(entry - sl)
                            candidate.rr_tp1 = abs(candidate.tp1 - entry) / risk if risk > 0 else 0.0
                            candidate.rr_tp2 = abs(candidate.tp2 - entry) / risk if risk > 0 else 0.0
                            if variant == "RANGE":
                                out["range_applied"] += 1
                        else:
                            out["range_skipped_side"] += 1
                    else:
                        out["range_skipped_side"] += 1
            report, confirmed_index = instrumented_wait(candidate, trigger, int(det["index"]), profile)
            reports.append(report)
            if confirmed_index is not None:
                trade = _simulate_trade(candidate, trigger, confirmed_index)
                trades.append(trade.pnl_pct)
        pnls = np.array(trades) if trades else np.array([0.0])
        wins = int((pnls > 0).sum())
        gp = float(pnls[pnls > 0].sum())
        gl = abs(float(pnls[pnls <= 0].sum()))
        out["variants"][variant] = {
            "trades": len(trades), "wins": wins,
            "winrate": round(100 * wins / len(trades), 1) if trades else 0.0,
            "expectancy": round(float(pnls.mean()), 4) if trades else 0.0,
            "pf": round(gp / gl, 2) if gl > 0 else (999.0 if gp > 0 else 0.0),
            "total_pnl": round(float(pnls.sum()), 2) if trades else 0.0,
            "confirmed": sum(1 for r in reports if r.outcome == "CONFIRMED"),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,XRPUSDT,SOLUSDT")
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    rows = []
    for symbol in args.symbols.split(","):
        for style in ("SWING", "SCALP"):
            row = replay_cell(symbol.strip().upper(), style, args.days, ConfirmProfile(name="STRICT"))
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    (RESULTS / "range_targets_ab.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    for stl in ("SWING", "SCALP"):
        print("=" * 16, stl)
        for v in ("BASE", "RANGE"):
            n = sum(r["variants"][v]["trades"] for r in rows if r["style"] == stl)
            pnl = round(sum(r["variants"][v]["total_pnl"] for r in rows if r["style"] == stl), 2)
            print(f"  {v}: n={n} total={pnl}")


if __name__ == "__main__":
    main()
