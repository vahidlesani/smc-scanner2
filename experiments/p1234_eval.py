"""Standalone evaluation of the experimental P1234 detector across 90 days.

Scans at production cadence (every 15m bar for SWING, every 3rd 5m bar for
SCALP), dedups candidates with the same key logic, then runs the STRICT
confirmation simulation + trade sim. Prints a per-setup summary line usable for
go/no-go decisions (min sample, expectancy, PF).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from analysis.backtest import _historical_ticker, _simulate_trade  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402
from analysis.setups_experimental import detect_pattern_1234, detect_trendline_breakout  # noqa: E402
from data.fetcher import MarketBundle  # noqa: E402

DETECTORS = {"p1234": detect_pattern_1234, "tlbreak": detect_trendline_breakout}


def _dedup_key(candidate) -> tuple:
    md = candidate.metadata
    if candidate.setup_code == "TLBREAK":
        return (candidate.setup_code, candidate.direction,
                int(md.get("tl_b_index", -1)), round(float(md.get("tl_line", 0)), 6))
    return (candidate.setup_code, candidate.direction,
            int(md.get("break_index", md.get("impulse_index", -1))),
            round(float(md.get("p1234_p2", 0)), 6))
from experiments.diagnose_funnel import (  # noqa: E402
    ConfirmProfile,
    build_index_map,
    instrumented_wait,
    slice_by_count,
)
from experiments.okx_feed import load_frames  # noqa: E402


def evaluate(symbol: str, style: str, days: int, detector=None) -> dict:
    detect_fn = detector or detect_pattern_1234
    frames, trigger_tf = load_frames(symbol, style, days)
    trigger = frames[trigger_tf]
    warmup = 180 if style == "SWING" else 240
    every_n = 1 if style == "SWING" else 3
    index_maps = {tf: build_index_map(f, trigger["timestamp"]) for tf, f in frames.items()}
    seen, reports, trades = set(), [], []
    profile = ConfirmProfile(name="STRICT")

    for index in range(warmup, len(trigger) - 5, every_n):
        ts = trigger["timestamp"].iloc[index]
        sliced, ok = {}, True
        for tf, frame in frames.items():
            count = int(index_maps[tf][index])
            cap = {"1d": 0, "4h": 280, "1h": 280, "15m": 340, "5m": 460}.get(tf, 0)
            part = slice_by_count(frame, count, 60 if tf != "1d" else 0, cap=cap)
            if part is None and tf != "1d":
                ok = False
                break
            sliced[tf] = part
        if not ok:
            continue
        bundle = MarketBundle(symbol=symbol, frames=sliced, ticker=_historical_ticker(sliced.get("1d"), ts))
        try:
            candidate = detect_fn(bundle, style)
        except Exception:
            continue
        if not candidate or candidate.score < 6:
            continue
        key = _dedup_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        candidate.created_at = pd.Timestamp(ts).isoformat()
        hours = 36 if style == "SWING" else 6
        candidate.expires_at = (pd.Timestamp(ts) + timedelta(hours=hours)).isoformat()
        report, confirmed_index = instrumented_wait(candidate, trigger, index, profile)
        reports.append(report)
        if confirmed_index is not None:
            trade = _simulate_trade(candidate, trigger, confirmed_index)
            report.trade_result, report.trade_pnl = trade.result, round(trade.pnl_pct, 4)
            trades.append(trade)

    outcomes = Counter(r.outcome for r in reports)
    pnls = np.array([t.pnl_pct for t in trades]) if trades else np.array([0.0])
    wins = int((pnls > 0).sum()) if trades else 0
    gross_p = float(pnls[pnls > 0].sum()) if trades else 0.0
    gross_l = abs(float(pnls[pnls <= 0].sum())) if trades else 0.0
    return {
        "symbol": symbol, "style": style, "days": days,
        "detections": len(reports), "outcomes": dict(outcomes),
        "trades": len(trades), "wins": wins, "losses": len(trades) - wins,
        "winrate": round(100 * wins / len(trades), 1) if trades else 0.0,
        "expectancy": round(float(pnls.mean()), 4) if trades else 0.0,
        "profit_factor": round(gross_p / gross_l, 2) if gross_l > 0 else (999.0 if gross_p > 0 else 0.0),
        "total_pnl": round(float(pnls.sum()), 2) if trades else 0.0,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,XRPUSDT,SOLUSDT")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--detector", default="p1234", choices=sorted(DETECTORS))
    p.add_argument("--tag", default="")
    p.add_argument("--styles", default="SWING,SCALP")
    args = p.parse_args()
    detect_fn = DETECTORS[args.detector]
    out = []
    for symbol in args.symbols.split(","):
        for style in args.styles.split(","):
            try:
                row = evaluate(symbol.strip().upper(), style, args.days, detector=detect_fn)
            except Exception as exc:
                row = {"symbol": symbol, "style": style, "error": str(exc)}
            out.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    fname = f"p1234_eval{args.tag}.json"
    Path(REPO / f"experiments/results/{fname}").write_text(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
