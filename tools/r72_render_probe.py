"""R72 REAL RENDER PROBE (2026-10-12) — production path, real Binance tape.

Renders the restored pipeline end-to-end and pins the user's law visually:

  A  first alert chart (snapshot STAMPED)                 perp, trigger TF
  B  update chart after a rogue fresh re-fit (lock RESTORES the stamp —
     geometry must equal A's, never the refit)             perp, trigger TF
  C  tool-escape exception: candles left the long tool → view ONE TF up,
     geometry still the stamped one, ordered note in text  perp, 1h
  D  spot chart from the restored baseline spot engine     spot, CryptoCove law
  E  zoom-stability: the same locked chain on a shallower window — same lines

KV is shimmed in-memory (identical contract to bot_kv), everything else is
the real production code: generate_chart(), lock_render_geometry(),
_lifecycle_view_plan(), scan_spot_symbol()/build_spot_candidate().
"""
import io
import json
import os
import sys

os.environ.setdefault("MPLBACKEND", "Agg")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

OUT = "/home/user/renders_r72"
os.makedirs(OUT, exist_ok=True)
REPORT = {"parts": {}}

# ── in-memory bot_kv shim (real contract, no DB side effects) ─────────────
import database.bot_kv as _kv  # noqa: E402
_KV = {}


def _gj(key, default=None):
    return _KV.get(key, default)


def _sj(key, value):
    if value is None:
        _KV.pop(key, None)
    else:
        _KV[key] = value


_kv.get_json = _gj
_kv.set_json = _sj

import pandas as pd  # noqa: E402
from data.fetcher import get_klines  # noqa: E402
from analysis.snapshot_lock import lock_render_geometry  # noqa: E402
import bot.messages_v7 as M  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402

M._chart_cache_get = lambda k: None          # never reuse bytes across parts
M._chart_cache_set = lambda k, v: None


def _save(name, png: bytes):
    path = os.path.join(OUT, name)
    with open(path, "wb") as fh:
        fh.write(png)
    return path


def _fail(part, exc):
    import traceback
    REPORT["parts"][part] = {"ok": False, "error": f"{exc}",
                             "tb": traceback.format_exc(limit=3)}
    print(f"[{part}] FAIL: {exc}")


# ══════════════════ PART 1 — perp chain on real BTCUSDT 15m ══════════════
try:
    df15 = get_klines("BTCUSDT", "15m", 300, closed_only=True, use_cache=False)
    df15x = get_klines("BTCUSDT", "15m", 340, closed_only=True, use_cache=False)
    df1h = get_klines("BTCUSDT", "1h", 250, closed_only=True, use_cache=False)
    last = float(df15["close"].iloc[-1])
    rng = float((df15["high"] - df15["low"]).tail(50).mean())
    # deterministic escape: the tool's top target sits BELOW the recent real
    # high, so real candles have already closed outside the band
    band_hi = float(df15["high"].tail(40).max()) * 0.995
    tp2 = min(last + 3.0 * rng, band_hi)
    tp1 = last + (tp2 - last) * 0.55
    tp3 = last + (tp2 - last) * 0.8
    sl = last - 1.6 * rng
    cand = SignalCandidate(
        signal_id="R72-PERP-1", symbol="BTCUSDT", style="DAYTRADE",
        setup_code="TLBREAK", setup_name="شکست خط روند", strategy_fa="TLBREAK",
        direction="LONG", score=8, status="CONFIRMED",
        entry_zone_bottom=last * 0.998, entry_zone_top=last * 1.002,
        planned_entry=last, sl=sl, tp1=tp1, tp2=tp2, rr_tp1=1.3, rr_tp2=2.1,
        bias="BULL", trigger_timeframe="15m", mandatory_gates={"zone": True},
        created_at=str(df15["timestamp"].iloc[-60]),
        confirmed_at=str(df15["timestamp"].iloc[-59]),
        metadata={"atr": rng, "touched": True,
                  "tool_entry_ts": str(df15["timestamp"].iloc[-60]),
                  "target_ladder": {"targets": [tp1, tp2, tp3],
                                    "weights": [40.0, 35.0, 25.0],
                                    "path_pct": 3.1}})
    stamp = lock_render_geometry(cand, kv_get=_gj, kv_set=_sj, frame=df15)
    pngA = M.generate_chart(df15, cand, confirmed=True)
    assert pngA, "chart A empty"
    _save("A_first_alert_15m.png", pngA)
    geoA = json.dumps(cand.metadata.get("render_patterns"), sort_keys=True, default=str)
    nA = len(cand.metadata.get("render_patterns") or [])
    REPORT["parts"]["A"] = {"ok": True, "lock": stamp, "patterns": nA,
                            "kinds": [p.get("type") for p in (cand.metadata.get("render_patterns") or [])]}
    print(f"[A] lock={stamp} patterns={nA}")

    # ── B: rogue refit attempt (fresh enrich on a LONGER real tape) — the
    # lock must restore the stamped geometry exactly
    for k in ("render_patterns", "render_zones", "pattern_band", "render_line_watch"):
        cand.metadata.pop(k, None)
    pngB = M.generate_chart(df15x, cand, confirmed=True)   # enrich refits…
    assert pngB, "chart B empty"
    restored = lock_render_geometry(cand, kv_get=_gj, kv_set=_sj, frame=df15x)
    pngB = M.generate_chart(df15x, cand, confirmed=True)   # …lock restores, re-render
    geoB = json.dumps(cand.metadata.get("render_patterns"), sort_keys=True, default=str)
    _save("B_update_after_rogue_refit_15m.png", pngB)
    REPORT["parts"]["B"] = {"ok": True, "lock": restored,
                            "geometry_identical_to_A": geoA == geoB}
    print(f"[B] lock={restored} geometry==A: {geoA == geoB}")

    # ── C: tool-escape → view ONE TF up, note text, geometry untouched
    view, escaped, note = M._lifecycle_view_plan(
        cand, now=pd.Timestamp(df15x["timestamp"].iloc[-1]) + pd.Timedelta(minutes=15),
        frame=df15x)
    lock_render_geometry(cand, kv_get=_gj, kv_set=_sj, frame=df1h)
    pngC = M.generate_chart(df1h, cand, confirmed=True)
    assert pngC, "chart C empty"
    _save("C_tool_escape_view_1h.png", pngC)
    geoC = json.dumps(cand.metadata.get("render_patterns"), sort_keys=True, default=str)
    REPORT["parts"]["C"] = {"ok": True, "view_tf": view, "escaped_candles": escaped,
                            "trigger_tf": cand.trigger_timeframe, "note_fa": note,
                            "geometry_identical_to_A": geoA == geoC}
    print(f"[C] view={view} escaped={escaped} trigger={cand.trigger_timeframe} geometry==A: {geoA == geoC}")

    # ── E: zoom stability — same locked chain, shallower window
    pngE = M.generate_chart(df15x.tail(170).reset_index(drop=True), cand, confirmed=True)
    assert pngE, "chart E empty"
    _save("E_zoom_170bars_same_geometry.png", pngE)
    geoE = json.dumps(cand.metadata.get("render_patterns"), sort_keys=True, default=str)
    REPORT["parts"]["E"] = {"ok": True, "geometry_identical_to_A": geoA == geoE}
    print(f"[E] geometry==A: {geoA == geoE}")
except Exception as exc:
    _fail("perp", exc)

# ══════════════ PART 2 — spot via restored baseline engine ══════════════
try:
    from analysis.spot_engine import scan_spot_symbol, build_spot_candidate
    SPOT_TFS = ["4h", "8h", "12h", "1d", "3d", "1w"]
    spot_done = False
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "SUIUSDT", "BNBUSDT"):
        frames = {}
        for tf in SPOT_TFS:
            try:
                d = get_klines(sym, tf, 350, closed_only=True, use_cache=True)
                if d is not None and len(d) > 60:
                    frames[tf] = d
            except Exception:
                pass
        items = scan_spot_symbol(sym, frames) or []
        if items:
            item = items[0]
            cs = build_spot_candidate(item)
            lock_render_geometry(cs, kv_get=_gj, kv_set=_sj)
            tf_s = str(cs.trigger_timeframe or item.get("tf") or "4h")
            pngD = M.generate_chart(frames.get(tf_s, frames.get("4h")), cs, confirmed=True)
            if pngD:
                _save("D_spot_engine_live.png", pngD)
                REPORT["parts"]["D"] = {
                    "ok": True, "source": "scan_spot_symbol LIVE",
                    "symbol": sym, "tf": tf_s,
                    "kind": item.get("kind") or item.get("pattern_type"),
                    "patterns": [p.get("type") for p in (cs.metadata.get("render_patterns") or [])]}
                print(f"[D] live spot item {sym} {tf_s} {item.get('kind')}")
                spot_done = True
                break
    if not spot_done:
        # no live breakout this minute → render the baseline detector's own
        # geometry on the real BTC 4h tape (same engine the chains use)
        from analysis.render_kit import detect_patterns
        d4 = get_klines("BTCUSDT", "4h", 320, closed_only=True, use_cache=False)
        pats = detect_patterns(d4, "LONG", log_axis=True) or []
        two = [p for p in pats if len(p.get("lines") or []) >= 2] or pats
        pick = (two or [None])[0]
        price = float(d4["close"].iloc[-1])
        box_top = price * 1.18
        cs = SignalCandidate(
            signal_id="R72-SPOT-1", symbol="BTCUSDT", style="SWING",
            setup_code="SPOT", setup_name="اسپات", strategy_fa="SPOT",
            direction="LONG", score=8, status="PUBLISH",
            entry_zone_bottom=price * 0.99, entry_zone_top=price, planned_entry=price,
            sl=price * 0.9, tp1=box_top, tp2=box_top * 1.1, rr_tp1=1.5, rr_tp2=2.0,
            bias="BULL", trigger_timeframe="4h", mandatory_gates={"zone": True},
            created_at=str(d4["timestamp"].iloc[-3]), confirmed_at=str(d4["timestamp"].iloc[-2]),
            metadata={"market": "SPOT", "is_spot": True, "spot_box_top": box_top,
                      "atr": float((d4["high"] - d4["low"]).tail(14).mean()),
                      "render_patterns": [pick] if pick else []})
        lock_render_geometry(cs, kv_get=_gj, kv_set=_sj, frame=d4)
        pngD = M.generate_chart(d4, cs, confirmed=True)
        assert pngD, "spot chart empty"
        _save("D_spot_baseline_engine.png", pngD)
        REPORT["parts"]["D"] = {"ok": True, "source": "baseline detector (no live breakout now)",
                                "symbol": "BTCUSDT", "tf": "4h",
                                "kind": (pick or {}).get("type"),
                                "all_detected": [p.get("type") for p in pats]}
        print(f"[D] baseline spot render, picked {(pick or {}).get('type')} of {[p.get('type') for p in pats]}")
except Exception as exc:
    _fail("spot", exc)

with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as fh:
    json.dump(REPORT, fh, ensure_ascii=False, indent=1, default=str)
print("\nREPORT:", json.dumps(REPORT, ensure_ascii=False, default=str)[:1500])
