"""R99q40 — snapshot the ALERT card of a real production chain.

His order (10-21): «حتما اسنپ‌شات از هشدار رو هم بزن و پوش کن». The card must be
rendered from the chain's OWN stored payload (the exact metadata the monitor
judged) against the real tape of its trigger timeframe — never from a probe
fixture — so the picture in the repo is the picture the member receives.

    python tools/alert_snapshot.py viva-ZEC-SW-TLBREAK-10210301-18AF out.png \
        --cut "2026-10-21 03:30" --confirmed

The DB is opened READ-ONLY. Markers are drawn from the candidate's own plan
(after `evaluate_confirmation` when --confirm-first is passed), so a rebased
entry is shown rebased, exactly as the alert would print it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

DSN = ("postgresql://postgres.nmndchflpeigorkmqcwi:Viva2026%21.%21"
       "@aws-0-eu-central-1.pooler.supabase.com:5432/postgres")

_TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240,
           "6h": 360, "8h": 480, "12h": 720, "1d": 1440}


def klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    url = (f"https://data-api.binance.vision/api/v3/klines"
           f"?symbol={symbol}&interval={interval}&limit={limit}")
    raw = json.loads(urllib.request.urlopen(url, timeout=30).read().decode())
    return pd.DataFrame({
        "timestamp": pd.to_datetime([r[0] for r in raw], unit="ms"),
        "open": [float(r[1]) for r in raw], "high": [float(r[2]) for r in raw],
        "low": [float(r[3]) for r in raw], "close": [float(r[4]) for r in raw],
        "volume": [float(r[5]) for r in raw],
    })


def load_candidate(signal_id: str):
    import psycopg2
    from analysis.models import SignalCandidate
    cn = psycopg2.connect(DSN, connect_timeout=20)
    cn.set_session(readonly=True)
    cur = cn.cursor()
    cur.execute("select payload from signal_candidates where signal_id=%s", (signal_id,))
    row = cur.fetchone()
    cn.close()
    if not row:
        raise SystemExit(f"signal not found: {signal_id}")
    return SignalCandidate.from_json(row[0])


def stub_kv() -> None:
    import database.bot_kv as kv
    store: dict = {}
    kv.get_json = lambda k, d=None: store.get(k, d)
    kv.set_json = lambda k, v: store.__setitem__(k, v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("signal_id")
    ap.add_argument("out")
    ap.add_argument("--cut", default="", help="last closed bar time (UTC, 'YYYY-MM-DD HH:MM')")
    ap.add_argument("--confirmed", action="store_true", help="render the CONFIRMED card")
    ap.add_argument("--confirm-first", action="store_true",
                    help="run evaluate_confirmation at the cut and draw its verdict")
    ap.add_argument("--bars", type=int, default=200)
    args = ap.parse_args()

    stub_kv()
    import matplotlib
    matplotlib.use("Agg")
    import bot.messages_v7 as M

    cand = load_candidate(args.signal_id)
    tf = str(cand.trigger_timeframe or "30m").lower()
    if args.confirm_first and args.cut:
        from analysis.quality_engine import evaluate_confirmation
        df_all = klines(cand.symbol, tf)
        cut = pd.Timestamp(args.cut)
        frame = df_all.loc[df_all["timestamp"] <= cut].reset_index(drop=True)
        ok, cand, why = evaluate_confirmation(cand, frame.copy(),
                                             frame_tf_minutes=float(_TF_MIN.get(tf, 0)))
        print(f"confirm-first: ok={ok} why={why[:90]}")
    df = klines(cand.symbol, tf)
    if args.cut:
        df = df.loc[df["timestamp"] <= pd.Timestamp(args.cut)]
    df = df.tail(args.bars).reset_index(drop=True)
    conf = bool(args.confirmed or args.confirm_first)
    png = M.generate_chart(df, cand, confirmed=conf, preconfirm_tool=not conf)
    open(args.out, "wb").write(png or b"")
    md = cand.metadata or {}
    print(f"{args.out} {len(png or b'')} B  {cand.symbol} {cand.setup_code} "
          f"{cand.direction} {tf} entry={cand.planned_entry} sl={cand.sl} "
          f"tp1={cand.tp1} tp2={cand.tp2} ctx={md.get('tl_context_tf')}")


if __name__ == "__main__":
    main()
