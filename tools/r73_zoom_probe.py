"""R73 REAL ZOOM PROBE (2026-10-12) — smart-zoom engine on live Binance tape.

1  perp LONG  BTCUSDT 15m  — tool band clean on TOP, candles un-squashed
2  perp SHORT BTCUSDT 1h   — tool band clean at the BOTTOM
3  spot      BTCUSDT 4h    — baseline CryptoCove look, engine y-window

Design (background / candle+line palette / frame / logos) is untouched by
construction: only the window + y-limits + pivot snap run through R73.
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

import pandas as pd  # noqa: E402
from data.fetcher import get_klines  # noqa: E402
from analysis.snapshot_lock import lock_render_geometry  # noqa: E402
import bot.messages_v7 as M  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402

M._chart_cache_get = lambda k: None
M._chart_cache_set = lambda k, v: None


def _save(n, b):
    with open(os.path.join(OUT, n), "wb") as fh:
        fh.write(b)


def _perp(sym, tf, n, direction):
    df = get_klines(sym, tf, n, closed_only=True, use_cache=False)
    last = float(df["close"].iloc[-1])
    rng = float((df["high"] - df["low"]).tail(60).mean())
    if direction == "LONG":
        entry, sl = last, last - 1.7 * rng
        tp1, tp2, tp3 = last + 1.6 * rng, last + 2.6 * rng, last + 3.4 * rng
    else:
        entry, sl = last, last + 1.7 * rng
        tp1, tp2, tp3 = last - 1.6 * rng, last - 2.6 * rng, last - 3.4 * rng
    cand = SignalCandidate(
        signal_id=f"R73-{direction}-{tf}", symbol=sym, style="DAYTRADE",
        setup_code="TLBREAK", setup_name="شکست خط روند", strategy_fa="TLBREAK",
        direction=direction, score=8, status="CONFIRMED",
        entry_zone_bottom=entry * 0.998, entry_zone_top=entry * 1.002,
        planned_entry=entry, sl=sl, tp1=tp1, tp2=tp2, rr_tp1=1.4, rr_tp2=2.2,
        bias="BULL" if direction == "LONG" else "BEAR",
        trigger_timeframe=tf, mandatory_gates={"zone": True},
        created_at=str(df["timestamp"].iloc[-70]),
        confirmed_at=str(df["timestamp"].iloc[-69]),
        metadata={"atr": rng, "touched": True,
                  "tool_entry_ts": str(df["timestamp"].iloc[-70]),
                  "target_ladder": {"targets": [tp1, tp2, tp3],
                                    "weights": [40.0, 35.0, 25.0],
                                    "path_pct": 3.0}})
    lock_render_geometry(cand, frame=df)
    png = M.generate_chart(df, cand, confirmed=True)
    return df, cand, png


try:
    df1, c1, png1 = _perp("BTCUSDT", "15m", 320, "LONG")
    assert png1
    _save("1_perp_LONG_15m.png", png1)
    REP["long"] = {"n_window": len(df1), "ok": True}
    print("[1] LONG ok")
except Exception as e:
    REP["long"] = {"ok": False, "err": str(e)}
    print("[1] FAIL", e)

try:
    df2, c2, png2 = _perp("BTCUSDT", "1h", 320, "SHORT")
    assert png2
    _save("2_perp_SHORT_1h.png", png2)
    REP["short"] = {"ok": True}
    print("[2] SHORT ok")
except Exception as e:
    REP["short"] = {"ok": False, "err": str(e)}
    print("[2] FAIL", e)

try:
    from analysis.render_kit import detect_patterns
    d4 = get_klines("BTCUSDT", "4h", 320, closed_only=True, use_cache=False)
    pats = detect_patterns(d4, "LONG", log_axis=True) or []
    pick = next((p for p in pats if len(p.get("lines") or []) >= 2), pats[0] if pats else None)
    price = float(d4["close"].iloc[-1])
    box_top = price * 1.18
    cs = SignalCandidate(
        signal_id="R73-SPOT", symbol="BTCUSDT", style="SWING",
        setup_code="SPOT", setup_name="اسپات", strategy_fa="SPOT",
        direction="LONG", score=8, status="PUBLISH",
        entry_zone_bottom=price * 0.99, entry_zone_top=price, planned_entry=price,
        sl=price * 0.9, tp1=box_top, tp2=box_top * 1.1, rr_tp1=1.5, rr_tp2=2.0,
        bias="BULL", trigger_timeframe="4h", mandatory_gates={"zone": True},
        created_at=str(d4["timestamp"].iloc[-3]), confirmed_at=str(d4["timestamp"].iloc[-2]),
        metadata={"market": "SPOT", "is_spot": True, "spot_box_top": box_top,
                  "atr": float((d4["high"] - d4["low"]).tail(14).mean()),
                  "render_patterns": [pick] if pick else []})
    lock_render_geometry(cs, frame=d4)
    png3 = M.generate_chart(d4, cs, confirmed=True)
    assert png3
    _save("3_spot_4h.png", png3)
    REP["spot"] = {"ok": True, "kind": (pick or {}).get("type")}
    print("[3] SPOT ok", (pick or {}).get("type"))
except Exception as e:
    REP["spot"] = {"ok": False, "err": str(e)}
    print("[3] FAIL", e)

with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as fh:
    json.dump(REP, fh, ensure_ascii=False, indent=1)
print("REP:", REP)
