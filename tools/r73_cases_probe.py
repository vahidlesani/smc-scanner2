"""R73 CASES PROBE (2026-10-12) — his five named tapes + perp, live Binance.

Measures the numeric laws on the exact cases he judged by eye:
  BTCUSDT 4h / 1d / 3d spot, ETHUSDT 4h spot, SOLUSDT 1d spot, SUIUSDT 1d spot
  BTCUSDT 15m perp (live-market tangibility cap)
and renders each through the production path.
"""
import json
import os
import sys

os.environ.setdefault("MPLBACKEND", "Agg")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

OUT = "/home/user/renders_r73"
os.makedirs(OUT, exist_ok=True)
REP = {}

import database.bot_kv as _kv  # noqa: E402
_KV = {}
_kv.get_json = lambda k, d=None: _KV.get(k, d)
_kv.set_json = lambda k, v: (_KV.pop(k, None) if v is None else _KV.__setitem__(k, v))

import math  # noqa: E402
import pandas as pd  # noqa: E402
from data.fetcher import get_klines  # noqa: E402
from analysis.snapshot_lock import lock_render_geometry  # noqa: E402
from analysis.smart_zoom import solve_zoom  # noqa: E402
from analysis.render_kit import detect_patterns  # noqa: E402
import bot.messages_v7 as M  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402

M._chart_cache_get = lambda k: None
M._chart_cache_set = lambda k, v: None

CASES = [("BTCUSDT", "4h"), ("BTCUSDT", "1d"), ("BTCUSDT", "3d"),
         ("ETHUSDT", "4h"), ("SOLUSDT", "1d"), ("SUIUSDT", "1d")]


def _metrics(plan, df):
    n = int(plan["n"])
    w = df.tail(n)
    lc_lo = math.log10(float(w["low"].min()))
    lc_hi = math.log10(float(w["high"].max()))
    lg_lo = math.log10(plan["y_lo"])
    lg_hi = math.log10(plan["y_hi"])
    return {"n": n,
            "height_fill": round((lc_hi - lc_lo) / (lg_hi - lg_lo), 3),
            "right_gap": round(plan["right_gap"], 3),
            "candles_low_side": round((lc_hi - lg_lo) / (lg_hi - lg_lo), 3)}


for sym, tf in CASES:
    try:
        df = get_klines(sym, tf, 400, closed_only=True, use_cache=False)
        # mirror production: the spot lane detects on the DICTATED tape depth
        from analysis.candle_counts import candle_count as _cc73
        _det73 = df.tail(int(_cc73(tf, 300))).reset_index(drop=True)
        pats = detect_patterns(_det73, "LONG", log_axis=True) or []
        # mirror the production spot lane: the channel upgrade runs on every
        # item's pattern commands inside scan_spot_symbol
        from analysis.spot_engine import channel_upgrade
        pats = channel_upgrade(pats, _det73)
        pick = next((p for p in pats if len(p.get("lines") or []) >= 2),
                    pats[0] if pats else None)
        price = float(df["close"].iloc[-1])
        box_top = price * 1.18
        cs = SignalCandidate(
            signal_id=f"R73C-{sym}-{tf}", symbol=sym, style="SWING",
            setup_code="SPOT", setup_name="اسپات", strategy_fa="SPOT",
            direction="LONG", score=8, status="PUBLISH",
            entry_zone_bottom=price * 0.99, entry_zone_top=price,
            planned_entry=price, sl=price * 0.9, tp1=box_top, tp2=box_top * 1.1,
            rr_tp1=1.5, rr_tp2=2.0, bias="BULL", trigger_timeframe=tf,
            mandatory_gates={"zone": True},
            created_at=str(df["timestamp"].iloc[-3]),
            confirmed_at=str(df["timestamp"].iloc[-2]),
            metadata={"market": "SPOT", "is_spot": True, "spot_box_top": box_top,
                      "atr": float((df["high"] - df["low"]).tail(14).mean()),
                      "render_patterns": [pick] if pick else []})
        lock_render_geometry(cs, frame=df)
        plan = solve_zoom(df, cs, confirmed=True, is_spot=True, chart_tf=tf,
                          det_n=len(_det73))
        png = M.generate_chart(df, cs, confirmed=True)
        name = f"spot_{sym}_{tf}.png"
        if png:
            with open(os.path.join(OUT, name), "wb") as fh:
                fh.write(png)
        REP[f"{sym} {tf}"] = {"ok": bool(png), "kind": (pick or {}).get("type"),
                              **( _metrics(plan, df) if plan else {"plan": None})}
        print(f"[{sym} {tf}] {REP[f'{sym} {tf}']}")
    except Exception as e:
        REP[f"{sym} {tf}"] = {"ok": False, "err": str(e)}
        print(f"[{sym} {tf}] FAIL {e}")

try:  # perp intraday: cap + tangibility
    df = get_klines("BTCUSDT", "15m", 400, closed_only=True, use_cache=False)
    last = float(df["close"].iloc[-1])
    rng = float((df["high"] - df["low"]).tail(60).mean())
    cand = SignalCandidate(
        signal_id="R73C-BTC-15m", symbol="BTCUSDT", style="DAYTRADE",
        setup_code="TLBREAK", setup_name="شکست خط روند", strategy_fa="TLBREAK",
        direction="LONG", score=8, status="CONFIRMED",
        entry_zone_bottom=last * 0.998, entry_zone_top=last * 1.002,
        planned_entry=last, sl=last - 1.7 * rng, tp1=last + 1.6 * rng,
        tp2=last + 2.6 * rng, rr_tp1=1.4, rr_tp2=2.2, bias="BULL",
        trigger_timeframe="15m", mandatory_gates={"zone": True},
        created_at=str(df["timestamp"].iloc[-70]),
        confirmed_at=str(df["timestamp"].iloc[-69]),
        metadata={"atr": rng, "touched": True,
                  "tool_entry_ts": str(df["timestamp"].iloc[-70]),
                  "target_ladder": {"targets": [last + 1.6 * rng, last + 2.6 * rng,
                                                last + 3.4 * rng],
                                    "weights": [40.0, 35.0, 25.0], "path_pct": 3.0}})
    lock_render_geometry(cand, frame=df)
    plan = solve_zoom(df, cand, confirmed=True, is_spot=False, chart_tf="15m")
    png = M.generate_chart(df, cand, confirmed=True)
    if png:
        with open(os.path.join(OUT, "perp_BTCUSDT_15m.png"), "wb") as fh:
            fh.write(png)
    REP["BTC 15m perp"] = {"ok": bool(png),
                           **(_metrics(plan, df) if plan else {"plan": None})}
    print("[BTC 15m perp]", REP["BTC 15m perp"])
except Exception as e:
    REP["BTC 15m perp"] = {"ok": False, "err": str(e)}
    print("[BTC 15m perp] FAIL", e)

with open(os.path.join(OUT, "cases_report.json"), "w", encoding="utf-8") as fh:
    json.dump(REP, fh, ensure_ascii=False, indent=1)
print("DONE")
