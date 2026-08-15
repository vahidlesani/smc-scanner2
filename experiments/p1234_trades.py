"""Dump trade-level records for the P1234 detector (for IS/OOS + attribution).

Same scan/simulation as p1234_eval.py but persists every simulated trade with
timestamps so we can do an honest in-sample / out-of-sample split and regime
attribution on the positive cells.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pandas as pd

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from analysis.backtest import _historical_ticker, _simulate_trade  # noqa: E402
from analysis.setups_experimental import detect_pattern_1234, detect_trendline_breakout  # noqa: E402
from experiments.p1234_eval import DETECTORS, _dedup_key  # noqa: E402
from data.fetcher import MarketBundle  # noqa: E402
from experiments.diagnose_funnel import (  # noqa: E402
    ConfirmProfile,
    build_index_map,
    instrumented_wait,
    slice_by_count,
)
from experiments.okx_feed import load_frames  # noqa: E402


def evaluate(symbol: str, style: str, days: int, detector=None) -> tuple[list[dict], Counter]:
    detect_fn = detector or detect_pattern_1234
    frames, trigger_tf = load_frames(symbol, style, days)
    trigger = frames[trigger_tf]
    warmup = 180 if style == "SWING" else 240
    every_n = 1 if style == "SWING" else 3
    index_maps = {tf: build_index_map(f, trigger["timestamp"]) for tf, f in frames.items()}
    seen, outcomes, rows = set(), Counter(), []
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
        outcomes[report.outcome] += 1
        if confirmed_index is not None:
            trade = _simulate_trade(candidate, trigger, confirmed_index)
            rows.append({
                "symbol": symbol,
                "style": style,
                "direction": candidate.direction,
                "created_at": candidate.created_at,
                "confirm_ts": str(trigger["timestamp"].iloc[confirmed_index]),
                "score": candidate.score,
                "entry": round(candidate.planned_entry, 6),
                "stop": round(candidate.sl, 6),
                "tp1": round(candidate.tp1, 6),
                "tp2": round(candidate.tp2, 6),
                "rr1": round(float(candidate.rr_tp1), 3),
                "rr2": round(float(candidate.rr_tp2), 3),
                "p1234_ratio": candidate.metadata.get("p1234_ratio"),
                "session": candidate.metadata.get("session", ""),
                "result": trade.result,
                "pnl_pct": round(trade.pnl_pct, 4),
            })
    return rows, outcomes


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cells", default="SOLUSDT:SWING,SOLUSDT:SCALP,ETHUSDT:SCALP")
    p.add_argument("--days", type=int, default=90)
    args = p.parse_args()
    for cell in args.cells.split(","):
        symbol, style = cell.split(":")
        rows, outcomes = evaluate(symbol.strip().upper(), style.strip().upper(), args.days)
        out = Path(REPO / f"experiments/results/p1234_trades_{symbol.strip().upper()}_{style.strip().upper()}.csv")
        pd.DataFrame(rows).to_csv(out, index=False)
        print(f"{symbol} {style}: trades={len(rows)} outcomes={dict(outcomes)} -> {out}", flush=True)


if __name__ == "__main__":
    main()
