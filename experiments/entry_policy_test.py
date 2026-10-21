"""Entry-policy counterfactual test — answers Viva's observation:

"The educational signals find good positions, but the confirmation layer never
lets us in, and later the targets get hit."

Replays every collected candidate (the full educational pool, incl. dead-gate
ones) under three entry policies on cached 90d data:

  CONFIRMED   -> current engine (reference numbers from phase-1 baseline)
  TOUCH       -> limit fill at planned_entry on first zone touch within expiry
  MARKET      -> market fill at detection-bar close

Trade lifecycle mirrors analysis.backtest._simulate_trade exactly:
stop-first on ambiguous candles, TP1 -> breakeven stop, 60/40 TP1/TP2 partials,
0.18% round-trip cost (fees 2x0.06% + slippage 2x0.03%).
"""
from __future__ import annotations

import argparse
import json
import pickle
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).parent.parent
RESULTS = REPO / "experiments/results"

FEES_RT = 2 * (0.06 + 0.03)  # percent, round trip
PARTIAL_TP1, PARTIAL_TP2 = 60.0, 40.0


def walk_trade(direction: str, entry: float, sl: float, tp1: float, tp2: float,
               trigger: pd.DataFrame, start_i: int, style: str) -> dict:
    """Exact mirror of _simulate_trade; start_i = first bar to EVALUATE (post-fill logic)."""
    max_hold = 7 * 24 * 4 if style == "SWING" else 24 * 12
    tp1_hit = False
    end = min(len(trigger), start_i + max_hold + 1)
    result, gross, reason = "TIMEOUT", 0.0, "Time expiry"
    last_close = None
    for i in range(start_i, end):
        row = trigger.iloc[i]
        high, low, close = float(row["high"]), float(row["low"]), float(row["close"])
        last_close = close
        if direction == "LONG":
            stop_hit = low <= (entry if tp1_hit else sl)
            first_hit, final_hit = high >= tp1, high >= tp2
        else:
            stop_hit = high >= (entry if tp1_hit else sl)
            first_hit, final_hit = low <= tp1, low <= tp2
        if stop_hit:  # conservative: stop wins same-candle ambiguity
            if tp1_hit:
                gross = abs(tp1 - entry) / entry * 100 * PARTIAL_TP1 / 100
                result, reason = "WIN", "TP1 then Breakeven"
            else:
                gross = -abs(sl - entry) / entry * 100
                result, reason = "LOSS", "Stop Loss"
            break
        if final_hit:
            gross = (abs(tp1 - entry) / entry * 100 * PARTIAL_TP1 / 100
                     + abs(tp2 - entry) / entry * 100 * PARTIAL_TP2 / 100)
            result, reason = "WIN", "TP2"
            break
        if first_hit:
            tp1_hit = True
    if result == "TIMEOUT" and last_close is not None:
        gross = ((last_close - entry) / entry * 100 if direction == "LONG"
                 else (entry - last_close) / entry * 100)
        reason = "TIMEOUT with TP1" if tp1_hit else "TIMEOUT flat"
    return {"result": result, "reason": reason, "gross": gross,
            "net": gross - FEES_RT, "tp1_first": tp1_hit or result == "WIN"}


def simulate_policy(cand: dict, trigger: pd.DataFrame, det_i: int, policy: str,
                    expiry_bars: int) -> dict:
    direction = cand["direction"]
    entry, sl = float(cand["planned_entry"]), float(cand["sl"])
    tp1, tp2 = float(cand["tp1"]), float(cand["tp2"])
    zb, zt = float(cand["entry_zone_bottom"]), float(cand["entry_zone_top"])
    end = min(len(trigger), det_i + expiry_bars + 1)

    if policy == "MARKET":
        fill_i = det_i
        px = float(trigger["close"].iloc[det_i])
        return walk_trade(direction, px, sl, tp1, tp2, trigger, fill_i + 1, cand["style"])

    # TOUCH: limit at planned_entry once the bar range overlaps the zone
    for i in range(det_i + 1, end):
        row = trigger.iloc[i]
        high, low, opn = float(row["high"]), float(row["low"]), float(row["open"])
        if low <= zt and high >= zb:  # zone touched
            # honest limit-fill: better price if the bar opens through the level
            px = min(entry, opn) if direction == "LONG" else max(entry, opn)
            # same-bar: if the fill bar itself reaches SL, stop-first (conservative)
            if (direction == "LONG" and low <= sl) or (direction == "SHORT" and high >= sl):
                return {"result": "LOSS", "reason": "SL same bar as touch",
                        "gross": -abs(sl - px) / px * 100, "net": -abs(sl - px) / px * 100 - FEES_RT,
                        "tp1_first": False}
            return walk_trade(direction, px, sl, tp1, tp2, trigger, i + 1, cand["style"])
    return {"result": "NO_TOUCH", "reason": "Zone never touched", "gross": 0.0,
            "net": 0.0, "tp1_first": False}


def summarize(rows: list[dict]) -> dict:
    entered = [r for r in rows if r["result"] != "NO_TOUCH"]
    out = {"signals": len(rows), "entered": len(entered)}
    if not entered:
        return out
    nets = np.array([r["net"] for r in entered])
    wins = int((nets > 0).sum())
    tp1_first = sum(1 for r in entered if r["tp1_first"])
    gp = float(nets[nets > 0].sum())
    gl = abs(float(nets[nets <= 0].sum()))
    out.update({
        "fill_rate": round(100 * len(entered) / len(rows), 1),
        "tp1_first_rate": round(100 * tp1_first / len(entered), 1),  # «تارگت اول زده شد قبل از استاپ»
        "winrate_net": round(100 * wins / len(entered), 1),
        "expectancy": round(float(nets.mean()), 4),
        "pf": round(gp / gl, 2) if gl > 0 else (999.0 if gp > 0 else 0.0),
        "total_net": round(float(nets.sum()), 2),
        "by_direction": {d: summarize_dir([r for r in entered if r["direction"] == d])
                         for d in ("LONG", "SHORT")},
    })
    return out


def summarize_dir(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    nets = np.array([r["net"] for r in rows])
    tp1_first = sum(1 for r in rows if r["tp1_first"])
    return {"n": len(rows), "tp1_first": round(100 * tp1_first / len(rows), 1),
            "wr": round(100 * float((nets > 0).mean()), 1),
            "net": round(float(nets.sum()), 2)}


def run_cell(symbol: str, style: str, trigger: pd.DataFrame) -> dict:
    pkl = RESULTS / f"detections_{symbol}_{style}_90d_sl1.0_n{1 if style=='SWING' else 3}.pkl"
    blob = pickle.load(open(pkl, "rb"))
    ts = trigger["timestamp"].to_numpy()
    expiry_bars = (36 * 4) if style == "SWING" else (6 * 12)
    pools = {"ALL": defaultdict(list), "GATES_OK": defaultdict(list), "GATES_DEAD": defaultdict(list)}
    for det in blob["detections"]:
        cand = json.loads(det["candidate"])
        det_ts = pd.Timestamp(cand["created_at"])
        det_i = int(np.searchsorted(ts, np.datetime64(det_ts.tz_convert(None) if det_ts.tzinfo else det_ts)))
        if det_i >= len(trigger) - 2:
            continue
        gates_ok = bool(cand.get("mandatory_gates")) and all(cand["mandatory_gates"].values())
        pool = "GATES_OK" if gates_ok else "GATES_DEAD"
        for policy in ("TOUCH", "MARKET"):
            r = simulate_policy(cand, trigger, det_i, policy, expiry_bars)
            r.update({"direction": cand["direction"], "setup": cand["setup_code"],
                      "created_at": str(det_ts)})
            pools["ALL"][policy].append(r)
            pools[pool][policy].append(r)
    return {pool: {pol: summarize(rows) for pol, rows in per_pol.items()}
            for pool, per_pol in pools.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,XRPUSDT,SOLUSDT")
    args = ap.parse_args()
    import sys
    sys.path.insert(0, str(REPO))
    from experiments.okx_feed import load_frames
    report = {}
    for symbol in args.symbols.split(","):
        for style in ("SWING", "SCALP"):
            frames, trigger_tf = load_frames(symbol.strip().upper(), style, 90)
            report[f"{symbol}_{style}"] = run_cell(symbol.strip().upper(), style, frames[trigger_tf])
            allp = report[f"{symbol}_{style}"]["ALL"]
            okp = report[f"{symbol}_{style}"]["GATES_OK"]
            print(f"{symbol} {style}: ALL touch={allp.get('TOUCH',{})} ", flush=True)
            print(f"   GATES_OK touch={okp.get('TOUCH',{})} market={okp.get('MARKET',{})}", flush=True)
    out = RESULTS / "entry_policy_report.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"saved -> {out}")


if __name__ == "__main__":
    main()
