"""Render one setup's production chart at a historical moment (R31.7).

Rebuilds the MarketBundle from the local sample tape (``REPLAY_CACHE_DIR``),
runs a single detector, and writes ``<out>/<name>.png`` plus a JSON sidecar
with the render metadata (lines, pivots, patterns) so chart geometry can be
debugged on REAL candles without exchange access.

    REPLAY_CACHE_DIR=experiments/sample_klines PYTHONPATH=. \
      python experiments/chart_debug.py --symbol BTCUSDT --at 2026-09-08T13:45 \
      --setup TLBREAK --tf 15m --out /tmp/cd
"""
from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import pandas as pd


def _json_safe(o):
    try:
        json.dumps(o)
        return o
    except Exception:
        if isinstance(o, dict):
            return {str(k): _json_safe(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_json_safe(v) for v in o]
        return str(o)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--at", required=True, help="UTC wall time, e.g. 2026-09-08T13:45")
    ap.add_argument("--setup", default="TLBREAK")
    ap.add_argument("--tf", default="", help="trigger TF filter, e.g. 4h")
    ap.add_argument("--out", default="/tmp/chart_debug")
    ap.add_argument("--confirmed", action="store_true")
    # the tape window must match the cached sample file names
    ap.add_argument("--tape-start", default="2026-09-04")
    ap.add_argument("--tape-end", default="2026-09-24")
    a = ap.parse_args()

    import time_machine
    from datetime import date
    from experiments.replay_live_setups import Tape, real_base, install_patches, Sim
    install_patches()
    t = pd.Timestamp(a.at)
    tape = Tape(a.symbol.upper(), real_base(a.symbol.upper(), date.fromisoformat(a.tape_start),
                                            date.fromisoformat(a.tape_end)))
    Sim.tape, Sim.t = tape, t
    traveller = time_machine.travel(t.to_pydatetime().replace(tzinfo=None) + timedelta(seconds=30), tick=False)
    traveller.start()
    try:
        from analysis import quality_engine as qe
        cands = [x for x in qe.scan_bundle(tape.bundle(t))
                 if x.setup_code == a.setup
                 and (not a.tf or str(x.trigger_timeframe).lower() == a.tf)]
        c = cands[0] if cands else None
        if c is None:
            print("no candidate")
            return
        from bot.messages_v7 import generate_chart
        tf = str(c.trigger_timeframe).lower()
        df = tape.closed(tf, t, 180)
        if a.confirmed:
            c.metadata["tool_entry_ts"] = str(df["timestamp"].iloc[-1])
        png = generate_chart(df, c, confirmed=a.confirmed)
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        name = f"{a.symbol}_{a.setup}_{c.trigger_timeframe}_{t:%m%d_%H%M}"
        if png:
            (out / f"{name}.png").write_bytes(png)
        md = c.metadata or {}
        keep = {k: md.get(k) for k in md if k.startswith(("render_", "viva_", "tc_", "tl_", "chart_"))}
        keep.update(direction=c.direction, entry=c.planned_entry, sl=c.sl, tp1=c.tp1, tp2=c.tp2,
                    trigger_tf=tf, signal_id=c.signal_id)
        (out / f"{name}.json").write_text(json.dumps(_json_safe(keep), indent=1, ensure_ascii=False))
        print(out / f"{name}.png")
    finally:
        traveller.stop()


if __name__ == "__main__":
    main()
