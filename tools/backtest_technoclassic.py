"""Walk-forward backtest of the REAL TechnoClassic engine — no reimplementation.

It imports the same `scan_edges` that ships alerts, replays it bar-by-bar on
exchange history (Ourbit, the execution venue), and simulates the plan each
event announces today:
  • BREAK_CLOSED  → enter next open, stop = edge line (retest-fail invalidation),
                    target = E&M measured objective (channel width from break pt)
  • REJECTION_FADE→ enter next open, fade plan's stop/target from the event
                    (Alfonso 75% law: bounce toward the opposite edge)

Conservative fills: if stop and target are BOTH touched inside one candle the
stop wins (worst case). Fees+slippage 0.12% per side. One open trade per
(symbol, tf, side) — mirrors production dedup instead of stacking entries.

Usage:
  python3 tools/backtest_technoclassic.py --symbols SOLUSDT,DOGEUSDT --tfs 4h,1d --bars 900
Outputs: /home/user/tc_backtest/report.md + summary.json

The point is calibration evidence for Viva (reject-rate threshold, fade-vs-break
expectancy, per-TF quality) — never a gate change on its own.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

FEE = 0.0012  # per side, taker + slippage allowance (Ourbit linear perp)


def _walk(df, tf, sim_from):
    """Yield (i, events) scanning ONLY data visible at bar i."""
    from analysis.pattern_engine import scan_edges, _FIT_WINDOW
    w = _FIT_WINDOW.get(tf, 140)
    n = len(df)
    for i in range(max(w, sim_from), n - 1):
        win = df.iloc[max(0, i - w + 1): i + 1].reset_index(drop=True)
        trig = df.iloc[max(0, i - 33): i + 1].reset_index(drop=True)
        if len(trig) < 8:
            continue
        live = float(df["close"].iloc[i])
        try:
            evs = scan_edges(win, trig, tf, live_price=live)
        except Exception:
            evs = []
        if evs:
            yield i, evs


def _simulate(df, i, ev):
    """Return (r_multiple, bars_held, kind) or None when the plan is unusable."""
    fade = ev.get("fade") or {}
    kind = "FADE" if ev.get("state") == "REJECTION_FADE" and fade else "BREAK"
    if kind == "FADE":
        direction = fade["direction"]
        stop = float(fade["stop"])
        target = float(fade["target"])
    else:
        if ev.get("state") != "BREAK_CLOSED":
            return None
        direction = ev["direction"]
        stop = float(ev["line_price"])
        target = float(ev["measured"]["to"])
    entry = float(df["open"].iloc[i + 1])
    atr_i = float((df["high"] - df["low"]).iloc[max(0, i - 14):i + 1].mean()) or 1e-9
    # production sanity: risk is NEVER allowed to shrink to the line itself —
    # floor at 0.35 ATR (same spirit as _build_candidate's stop anchoring)
    if direction == "LONG":
        stop = min(stop, entry - 0.35 * atr_i)
    else:
        stop = max(stop, entry + 0.35 * atr_i)
    risk = entry - stop if direction == "LONG" else stop - entry
    reward = target - entry if direction == "LONG" else entry - target
    if risk <= 0 or reward <= 0:
        return None
    if reward / risk < 1.2:      # the ladder won't take it either — skip
        return None
    o, h, l = (df["open"], df["high"], df["low"])
    exit_px, bars = None, 0
    for j in range(i + 1, min(len(df), i + 1 + 160)):
        if j == i + 1:
            entry = float(o.iloc[j])      # fill at the open of bar i+1
            if direction == "LONG":
                stop = min(stop, entry - 0.35 * atr_i)
            else:
                stop = max(stop, entry + 0.35 * atr_i)
            risk = entry - stop if direction == "LONG" else stop - entry
            reward = target - entry if direction == "LONG" else entry - target
            if risk <= 0 or reward / risk < 1.2:
                return None
        lo, hi = float(l.iloc[j]), float(h.iloc[j])
        hit_stop = lo <= stop if direction == "LONG" else hi >= stop
        hit_tp = hi >= target if direction == "LONG" else lo <= target
        if hit_stop:                      # stop-first: conservative on ties
            exit_px = stop
        elif hit_tp:
            exit_px = target
        if exit_px is not None:
            bars = j - i
            break
    if exit_px is None:                   # timeout: exit last open, mark flat
        exit_px = float(df["close"].iloc[min(len(df) - 1, i + 160)])
        bars = 160
    gross = (exit_px - entry) / entry if direction == "LONG" else (entry - exit_px) / entry
    net_pct = gross - 2 * FEE
    r = (net_pct * entry) / risk
    return r, bars, kind


def run(symbols, tfs, bars):
    from data.fetcher import get_klines_paginated
    trades = []
    for symbol in symbols:
        for tf in tfs:
            try:
                df = get_klines_paginated(symbol, tf, bars)
            except Exception as exc:
                print(f"fetch failed {symbol} {tf}: {exc}")
                continue
            if df is None or len(df) < 220:
                print(f"skip {symbol} {tf}: only {0 if df is None else len(df)} bars")
                continue
            df = df.reset_index(drop=True)
            busy_until = {}
            for i, evs in _walk(df, tf, 160):
                for ev in evs:
                    key = (symbol, tf, ev.get("side"))
                    if i < busy_until.get(key, -1):
                        continue
                    out = _simulate(df, i, ev)
                    if out is None:
                        continue
                    r, held, kind = out
                    busy_until[key] = i + max(10, held)
                    trades.append({
                        "symbol": symbol, "tf": tf, "bar": i, "kind": kind,
                        "pattern": ev.get("pattern"), "side": ev.get("side"),
                        "r": round(r, 3), "bars": int(held),
                        "touches": int(ev.get("touches") or 0),
                        "reject_rate": float((ev.get("reactions") or {}).get("reject_rate", 0.0)),
                    })
            print(f"{symbol} {tf}: {len([t for t in trades if t['symbol']==symbol and t['tf']==tf])} trades")
    return trades


def summarize(trades):
    def agg(rows):
        if not rows:
            return None
        rs = [t["r"] for t in rows]
        wins = [r for r in rs if r > 0]
        return {
            "n": len(rs),
            "win_rate_pct": round(100.0 * len(wins) / len(rs), 1),
            "expectancy_r": round(sum(rs) / len(rs), 2),
            "median_r": round(sorted(rs)[len(rs) // 2], 2),
            "sum_r": round(sum(rs), 1),
            "avg_bars": round(sum(t["bars"] for t in rows) / len(rows), 1),
        }
    out = {
        "ALL": agg(trades),
        "BREAK": agg([t for t in trades if t["kind"] == "BREAK"]),
        "FADE": agg([t for t in trades if t["kind"] == "FADE"]),
    }
    for tf in sorted({t["tf"] for t in trades}):
        out[f"tf:{tf}"] = agg([t for t in trades if t["tf"] == tf])
    out["FADE rr>=0.6"] = agg([t for t in trades if t["kind"] == "FADE" and t["reject_rate"] >= 0.6])
    out["BREAK rr<0.6"] = agg([t for t in trades if t["kind"] == "BREAK" and t["reject_rate"] < 0.6])
    for pat in sorted({str(t.get("pattern")) for t in trades}):
        out[f"pat:{pat}"] = agg([t for t in trades if str(t.get("pattern")) == pat])
    return {k: v for k, v in out.items() if v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="SOLUSDT,DOGEUSDT,AVAXUSDT")
    ap.add_argument("--tfs", default="4h,1d")
    ap.add_argument("--bars", type=int, default=900)
    ap.add_argument("--out", default="/home/user/tc_backtest")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    trades = run([s.strip().upper() for s in args.symbols.split(",") if s.strip()],
                 [t.strip() for t in args.tfs.split(",") if t.strip()], args.bars)
    summ = summarize(trades)
    json.dump({"trades": trades, "summary": summ}, open(f"{args.out}/summary.json", "w"),
              ensure_ascii=False, indent=1)
    lines = ["# TechnoClassic walk-forward backtest (REAL engine, conservative fills)\n",
             f"symbols={args.symbols} tfs={args.tfs} bars={args.bars} fee/side={FEE*100:.2f}%\n",
             "| bucket | n | win% | expectancy R | median R | ΣR | avg bars |", "|---|---|---|---|---|---|---|"]
    for k, v in summ.items():
        lines.append(f"| {k} | {v['n']} | {v['win_rate_pct']} | {v['expectancy_r']} | "
                     f"{v['median_r']} | {v['sum_r']} | {v['avg_bars']} |")
    open(f"{args.out}/report.md", "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
