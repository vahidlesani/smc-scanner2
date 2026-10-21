"""Visual probe: render real Binance-vision tapes through generate_chart.

Persisted on purpose — the sandbox loses /tmp between sessions, and every visual
check in R99q3x has needed exactly this harness.

    python tools/render_probe.py SUIUSDT 30m TLBREAK out.png --side SHORT
    python tools/render_probe.py WLDUSDT 30m TECHCLASSIC out.png --paths a,r,c

The KV store is stubbed (in-memory), so the snapshot/zoom-freeze laws run on a
clean slate exactly like the first card of a fresh chain.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])

import pandas as pd  # noqa: E402


def klines(symbol: str, interval: str, limit: int = 400) -> pd.DataFrame:
    url = (f"https://data-api.binance.vision/api/v3/klines"
           f"?symbol={symbol}&interval={interval}&limit={limit}")
    raw = json.loads(urllib.request.urlopen(url, timeout=30).read().decode())
    return pd.DataFrame({
        "timestamp": pd.to_datetime([r[0] for r in raw], unit="ms"),
        "open": [float(r[1]) for r in raw], "high": [float(r[2]) for r in raw],
        "low": [float(r[3]) for r in raw], "close": [float(r[4]) for r in raw],
        "volume": [float(r[5]) for r in raw],
    })


def stub_kv() -> None:
    import database.bot_kv as kv
    store: dict = {}
    kv.get_json = lambda k, d=None: store.get(k, d)
    kv.set_json = lambda k, v: store.__setitem__(k, v)


def candidate(symbol: str, tf: str, code: str, side: str, df: pd.DataFrame, bars: int):
    from analysis.models import SignalCandidate
    last = float(df["close"].iloc[-1])
    hi = float(df["high"].tail(60).max())
    lo = float(df["low"].tail(60).min())
    if side.upper() == "SHORT":
        entry, sl = hi, hi * 1.012
        tps = [last * 0.985, last * 0.965, last * 0.945]
    else:
        entry, sl = last, lo * 0.988
        tps = [last * 1.015, last * 1.035, last * 1.055]
    return SignalCandidate(
        signal_id=f"probe-{symbol}-{tf}", symbol=symbol, style="SWING",
        setup_code=code, setup_name=code, strategy_fa="probe", direction=side.upper(),
        score=9, status="READY", entry_zone_bottom=entry * 0.999,
        entry_zone_top=entry * 1.001, planned_entry=entry, sl=sl,
        tp1=tps[0], tp2=tps[1], rr_tp1=1.2, rr_tp2=2.0, bias=side.upper(),
        trigger_timeframe=tf, market={"asset_class": "CRYPTO", "venue": "BINANCE"},
        metadata={"market": "FUTURES", "engine": "SWING",
                  "public_code": f"{symbol}-PROBE", "target_ladder": {"targets": tps}})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("tf")
    ap.add_argument("setup", nargs="?", default="TECHCLASSIC")
    ap.add_argument("out", nargs="?", default="/tmp/probe.png")
    ap.add_argument("--side", default="SHORT")
    ap.add_argument("--bars", type=int, default=200)
    ap.add_argument("--paths", default="c",
                    help="a=analysis r=ready c=confirmed (csv)")
    args = ap.parse_args()
    stub_kv()
    import matplotlib
    matplotlib.use("Agg")
    import bot.messages_v7 as M

    df = klines(args.symbol, args.tf).tail(args.bars).reset_index(drop=True)
    for tag in [t.strip() for t in args.paths.split(",") if t.strip()]:
        conf, pre = (tag == "c"), (tag == "r")
        png = M.generate_chart(df, candidate(args.symbol, args.tf, args.setup,
                                             args.side, df, args.bars),
                               confirmed=conf, preconfirm_tool=pre)
        out = args.out if len(args.paths) == 1 else args.out.replace(".png", f"_{tag}.png")
        open(out, "wb").write(png or b"")
        print(out, len(png or b""))


if __name__ == "__main__":
    main()
