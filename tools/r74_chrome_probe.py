"""R74 probe (Viva 10-12 chrome batch + «همه با رندر جدید»): renders spot AND
perp SETUP samples across timeframes through the ONE unified production path
(bot.messages_v7.generate_chart) with real Binance tape, so the new chrome
(dense price ladder, slim right band, OHLC top line, pink live cell, center
watermark, gold footer logo, candle edges) can be judged on real pixels.
"""
import json
import math
import os
import sys

OUT = "/home/user/renders_r74"
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database.bot_kv as _kv  # noqa: E402
_KV = {}
_kv.get_json = lambda k, d=None: _KV.get(k, d)
_kv.set_json = lambda k, v: (_KV.pop(k, None) if v is None else _KV.__setitem__(k, v))

from data.fetcher import get_klines  # noqa: E402
from analysis.snapshot_lock import lock_render_geometry  # noqa: E402
from analysis.smart_zoom import solve_zoom  # noqa: E402
from analysis.render_kit import detect_patterns  # noqa: E402
from analysis.spot_engine import channel_upgrade  # noqa: E402
import bot.messages_v7 as M  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402

M._chart_cache_get = lambda k: None
M._chart_cache_set = lambda k, v: None

REP: dict = {}


def _metrics(plan, df):
    if not plan:
        return {"plan": None}
    n = int(plan["n"])
    w = df.tail(n)
    lc_lo = math.log10(float(w["low"].min()))
    lc_hi = math.log10(float(w["high"].max()))
    lg_lo = math.log10(plan["y_lo"])
    lg_hi = math.log10(plan["y_hi"])
    return {"n": n,
            "height_fill": round((lc_hi - lc_lo) / (lg_hi - lg_lo), 3),
            "right_gap": round(plan["right_gap"], 3)}


def _binance_df(sym, tf, limit=140):
    """Direct Binance spot REST fallback (Ourbit/Bybit 403 on some spots)."""
    import requests, pandas as pd
    r = requests.get("https://data-api.binance.vision/api/v3/klines",
                     params={"symbol": sym, "interval": tf, "limit": limit}, timeout=20)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame([{"timestamp": pd.to_datetime(int(k[0]), unit="ms"),
                        "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4]),
                        "volume": float(k[5])} for k in rows])
    return df


def _spot_case(sym, tf):
    # PRODUCTION DOMAIN (main.py:_candidate_market_frames): the monitor
    # fetches 140 rows, detects on the CLOSED reset frame and renders THAT
    # same live frame. Mixing a 400-bar render df with fits computed on a
    # tail window shifts every engine line by the offset (the «له شده»
    # steep-leg artefact) — so the probe mirrors production 1:1.
    df = get_klines(sym, tf, 140, closed_only=False, use_cache=False)
    if df is None or df.empty:
        df = _binance_df(sym, tf, 140)
    _det = df.iloc[:-1].reset_index(drop=True)
    pats = detect_patterns(_det, "LONG", log_axis=True) or []
    pats = channel_upgrade(pats, _det)
    pick = next((p for p in pats if len(p.get("lines") or []) >= 2),
                pats[0] if pats else None)
    price = float(df["close"].iloc[-1])
    # production-like ceiling: the alert builder's md value wins (10-10 law);
    # mirror it with the next structural high above live, floored at +18%.
    try:
        from analysis.spot_engine import _structural_high_above as _sha73p
        _sha73v = float(_sha73p(_det, price) or 0.0)
    except Exception:
        _sha73v = 0.0
    box_top = max(price * 1.18, _sha73v * 1.01)
    cs = SignalCandidate(
        signal_id=f"R74-{sym}-{tf}", symbol=sym, style="SWING",
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
    return df, cs, pick


def _perp_case(sym, tf, setup="TLBREAK", direction="LONG"):
    df = get_klines(sym, tf, 400, closed_only=True, use_cache=False)
    _det = df.tail(300).reset_index(drop=True)
    # render the SAME frame detection ran on (production domain law): the
    # engine's fit keys live in detection coords; an offset shifts lines.
    pats = detect_patterns(_det, direction, log_axis=True) or []
    pick = next((p for p in pats if len(p.get("lines") or []) >= 2),
                pats[0] if pats else None)
    last = float(df["close"].iloc[-1])
    rng = float((df["high"] - df["low"]).tail(60).mean())
    sgn = 1.0 if direction == "LONG" else -1.0
    cs = SignalCandidate(
        signal_id=f"R74-{sym}-{tf}-{direction}", symbol=sym, style="DAYTRADE",
        setup_code=setup, setup_name="شکست خط روند", strategy_fa=setup,
        direction=direction, score=8, status="CONFIRMED",
        entry_zone_bottom=last * 0.998, entry_zone_top=last * 1.002,
        planned_entry=last, sl=last - sgn * 1.7 * rng, tp1=last + sgn * 1.6 * rng,
        tp2=last + sgn * 2.6 * rng, rr_tp1=1.4, rr_tp2=2.2,
        bias="BULL" if sgn > 0 else "BEAR",
        trigger_timeframe=tf, mandatory_gates={"zone": True},
        created_at=str(df["timestamp"].iloc[-70]),
        confirmed_at=str(df["timestamp"].iloc[-69]),
        metadata={"atr": rng, "touched": True,
                  "tool_entry_ts": str(df["timestamp"].iloc[-70]),
                  "render_patterns": [pick] if pick else [],
                  "target_ladder": {"targets": [last + sgn * 1.6 * rng,
                                                last + sgn * 2.6 * rng,
                                                last + sgn * 3.4 * rng],
                                    "weights": [40.0, 35.0, 25.0],
                                    "path_pct": 3.0}})
    return _det, cs, pick


SPOT_CASES = [("BTCUSDT", "4h"), ("STRKUSDT", "4h"), ("SUIUSDT", "1d"),
              ("ENAUSDT", "4h"), ("BTCUSDT", "3d"), ("ETHUSDT", "4h"), ("ATOMUSDT", "8h")]
PERP_CASES = [("BTCUSDT", "15m", "LONG"), ("BTCUSDT", "1h", "SHORT"),
              ("SOLUSDT", "4h", "LONG"), ("BTCUSDT", "1d", "LONG")]

for sym, tf in SPOT_CASES:
    key = f"spot {sym} {tf}"
    try:
        df, cs, pick = _spot_case(sym, tf)
        lock_render_geometry(cs, frame=df)
        plan = solve_zoom(df, cs, confirmed=True, is_spot=True, chart_tf=tf)
        png = M.generate_chart(df, cs, confirmed=True)
        if png:
            with open(os.path.join(OUT, f"spot_{sym}_{tf}.png"), "wb") as fh:
                fh.write(png)
        REP[key] = {"ok": bool(png), "kind": (pick or {}).get("type"),
                    **_metrics(plan, df)}
        print(f"[{key}] {REP[key]}")
    except Exception as e:
        REP[key] = {"ok": False, "err": str(e)}
        print(f"[{key}] FAIL {e}")

for sym, tf, d in PERP_CASES:
    key = f"perp {sym} {tf} {d}"
    try:
        df, cs, pick = _perp_case(sym, tf, direction=d)
        lock_render_geometry(cs, frame=df)
        plan = solve_zoom(df, cs, confirmed=True, is_spot=False, chart_tf=tf)
        png = M.generate_chart(df, cs, confirmed=True)
        if png:
            with open(os.path.join(OUT, f"perp_{sym}_{tf}_{d}.png"), "wb") as fh:
                fh.write(png)
        REP[key] = {"ok": bool(png), "kind": (pick or {}).get("type"),
                    **_metrics(plan, df)}
        print(f"[{key}] {REP[key]}")
    except Exception as e:
        REP[key] = {"ok": False, "err": str(e)}
        print(f"[{key}] FAIL {e}")

with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as fh:
    json.dump(REP, fh, ensure_ascii=False, indent=1)
print("DONE", {k: v.get("ok") for k, v in REP.items()})
