"""Phase-1 honest-baseline report.

Replays the collected 90d detections under STRICT confirmation and builds the
audit table: per symbol x style x setup — trades, winrate, expectancy, PF —
split into In-Sample (first 60%) and Out-of-Sample (last 40%) by detection time.

Usage: python3 experiments/phase1_report.py [--days 90]
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from analysis.backtest import _simulate_trade  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402
from experiments.collect_replay import RESULTS  # noqa: E402
from experiments.diagnose_funnel import ConfirmProfile, instrumented_wait  # noqa: E402
from experiments.okx_feed import load_frames  # noqa: E402

PROFILE = ConfirmProfile(name="STRICT")


def metrics_of(trades) -> str:
    if not trades:
        return "n=0"
    pnl = np.array([t.pnl_pct for t in trades])
    wins = int((pnl > 0).sum())
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)
    return f"n={len(trades)} WR={100 * wins / len(trades):.0f}% exp={pnl.mean():+.3f}% PF={pf:.2f} sum={pnl.sum():+.2f}%"


def run(symbol: str, style: str, days: int, every_n: int) -> list:
    pkl_n = RESULTS / f"detections_{symbol}_{style}_{days}d_sl1.0_n{every_n}.pkl"
    if not pkl_n.exists():
        return []
    payload = pickle.load(open(pkl_n, "rb"))
    frames, trigger_tf = load_frames(symbol, style, days)
    trigger = frames[trigger_tf]
    detections = payload["detections"]
    rows = []
    for det in detections:
        candidate = SignalCandidate.from_json(det["candidate"])
        report, confirmed_index = instrumented_wait(candidate, trigger, int(det["index"]), PROFILE)
        if confirmed_index is None:
            continue
        trade = _simulate_trade(candidate, trigger, confirmed_index)
        rows.append({"setup": candidate.setup_code, "detected_at": pd.Timestamp(candidate.created_at), "trade": trade})
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,XRPUSDT,SOLUSDT")
    args = p.parse_args()
    table = defaultdict(list)
    for symbol in args.symbols.split(","):
        symbol = symbol.strip().upper()
        for style in ("SWING", "SCALP"):
            every_n = 1 if style == "SWING" else 3
            rows = run(symbol, style, args.days, every_n)
            if not rows:
                print(f"{symbol} {style}: no confirmed trades or missing pickle", flush=True)
                continue
            cutoff = sorted(r["detected_at"] for r in rows)[int(len(rows) * 0.6)]
            for r in rows:
                r["oos"] = r["detected_at"] > cutoff
            setups = sorted({r["setup"] for r in rows})
            for setup in setups:
                sub_is = [r["trade"] for r in rows if r["setup"] == setup and not r["oos"]]
                sub_os = [r["trade"] for r in rows if r["setup"] == setup and r["oos"]]
                line = {
                    "symbol": symbol, "style": style, "setup": setup,
                    "IS": metrics_of(sub_is), "OOS": metrics_of(sub_os),
                }
                table[f"{symbol}-{style}"].append(line)
                print(f"{symbol:<8} {style:<6} {setup:<6} IS {line['IS']:<52} OOS {line['OOS']}", flush=True)
    Path(RESULTS / "phase1_report.json").write_text(json.dumps(table, indent=2, ensure_ascii=False))
    print("\nSaved → experiments/results/phase1_report.json")


if __name__ == "__main__":
    main()
