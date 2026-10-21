"""AERO-class repro on REAL Kraken data: does the confirmed chart lose the
justifying 4H pattern while the PAT label still cites it?

Stage 1 (ALERT):  VIVA_TLBREAK chain, render_patterns=[REAL 4H triangle from
  Kraken ETH 4H via the real detect_patterns], NO trade lines yet ->
  lock_render_geometry (expect STAMP, triangle kept) -> generate_chart(False).
Stage 2 (CONFIRM): trade lines (viva_upper/lower_points, derived from the
  triangle's OWN lines) now exist -> lock_render_geometry (expect RESTORE +
  unify strip) -> generate_chart(confirmed=True).
"""
import sys
sys.path.insert(0, "/home/user/smc-scanner2")
import json
import pandas as pd

from analysis.render_kit import detect_patterns
from analysis.models import SignalCandidate
from analysis.snapshot_lock import lock_render_geometry
from bot.messages_v7 import generate_chart


def load(sym, iv):
    rows = json.load(open(f"/home/user/kraken_{sym}_{iv}.json"))
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
    df["timestamp"] = pd.to_datetime(df["time"], unit="s")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


KV = {}
kv_get = lambda k: KV.get(k)
def kv_set(k, v):
    KV[k] = v


def main():
    h4 = load("ETH", 240)
    h1 = load("ETH", 60)
    print("4H bars:", len(h4), "span:", h4.timestamp.iloc[0], "->", h4.timestamp.iloc[-1])
    print("1H bars:", len(h1), "span:", h1.timestamp.iloc[0], "->", h1.timestamp.iloc[-1])

    d4 = h4.iloc[350:650].reset_index(drop=True)
    T0 = h4["timestamp"].iloc[649]
    h1x = h1.reset_index(drop=True)
    _end0 = int(h1x[h1x["timestamp"] <= T0].index.max())
    h1_alert = h1x.iloc[max(0, _end0 - 239):_end0 + 1].reset_index(drop=True)
    h1_conf = h1x.tail(240).reset_index(drop=True)   # live edge: 4H pivots (Sept) far outside
    print("T0:", T0, "| alert 1H:", h1_alert.timestamp.iloc[0], "->", h1_alert.timestamp.iloc[-1],
          "| confirm 1H:", h1_conf.timestamp.iloc[0], "->", h1_conf.timestamp.iloc[-1])
    pats = detect_patterns(d4, "LONG", log_axis=True)
    print(f"4H detected {len(pats)} patterns:",
          [(p.get("type"), len(p.get("lines") or [])) for p in pats[:6]])
    pat = None
    for p in pats:
        if (p.get("lines") and len(p["lines"]) >= 2
                and str(p.get("type") or "").upper() in (
                    "TRIANGLE", "TRIANGLE_ASCENDING", "TRIANGLE_DESCENDING",
                    "WEDGE", "WEDGE_FALLING", "WEDGE_RISING",
                    "CHANNEL", "CHANNEL_ASCENDING", "CHANNEL_DESCENDING")):
            pat = p
            break
    if pat is None:
        print("NO 2-line trend-family pattern on real 4H — probe cannot proceed")
        return
    print("USING:", pat.get("type"))
    for i, ln in enumerate(pat["lines"][:2]):
        print(f"  line{i} keys:", sorted(ln.keys()))
        print(f"  line{i}:", {k: ln.get(k) for k in (
            "x0", "x1", "y0", "y1", "slope", "intercept", "side", "kind") if k in ln})

    # trade edges = the triangle's OWN lines (timestamps from the detect frame)
    import math

    def pt(line, which):
        x = int(line["x1"] if which == 1 else line["x0"])
        ts = d4["timestamp"].iloc[x]
        if line.get("log_fit") and line.get("log_slope") is not None:
            px = float(10.0 ** (line["log_slope"] * x + line["log_intercept"]))  # base-10!
        else:
            px = float(line["slope"] * x + line["intercept"])
        return {"timestamp": str(ts), "price": px, "y": px}
    up = [pt(pat["lines"][0], 0), pt(pat["lines"][0], 1)]
    lo = [pt(pat["lines"][1], 0), pt(pat["lines"][1], 1)]

    last = float(h1_alert["close"].iloc[-1])
    c = SignalCandidate(
        signal_id="PROBE-AERO-1", symbol="ETHUSDT", style="SWING",
        setup_code="TLBREAK", setup_name="TLBREAK", strategy_fa="VIVA + TLBREAK",
        direction="LONG", score=8, status="TOUCH",
        entry_zone_bottom=last * 0.995, entry_zone_top=last * 1.005,
        planned_entry=last, sl=last * 0.985, tp1=last * 1.02, tp2=last * 1.04,
        rr_tp1=1.3, rr_tp2=2.6, bias="BULLISH", trigger_timeframe="1h")
    c.metadata = {
        "market": "FUTURES", "strategy_variant": "VIVA_TLBREAK",
        "tl_pattern": pat.get("type"), "tl_context_tf": "4H",
        "pattern_type": pat.get("type"),
        "render_patterns": [pat],
        "atr": float((h1["high"] - h1["low"]).tail(14).mean()),
    }

    # ── stage 1: ALERT (no trade lines) ──
    r1 = lock_render_geometry(c, kv_get=kv_get, kv_set=kv_set)
    print(f"ALERT lock={r1} render_patterns={len(c.metadata.get('render_patterns') or [])} "
          f"src={c.metadata.get('render_geometry_source')}")
    png1 = generate_chart(h1_alert, c, confirmed=False)
    open("/home/user/probe_AERO_alert.png", "wb").write(png1 or b"")
    print("alert png bytes:", len(png1 or b""))

    # ── stage 2: CONFIRM (trade lines exist) ──
    c.metadata["viva_upper_points"] = up
    c.metadata["viva_lower_points"] = lo
    c.status = "CONFIRMED"
    r2 = lock_render_geometry(c, kv_get=kv_get, kv_set=kv_set, frame=None)
    print(f"CONFIRM lock={r2} render_patterns={len(c.metadata.get('render_patterns') or [])} "
          f"src={c.metadata.get('render_geometry_source')}")
    from analysis.snapshot_lock import snapshot_key
    _snap = KV.get(snapshot_key("PROBE-AERO-1")) or {}
    print("CONFIRM stored snapshot patterns:", len(_snap.get("render_patterns") or []),
          "src=", _snap.get("render_geometry_source"))
    for _p in (c.metadata.get("render_patterns") or []):
        print("  md pattern:", _p.get("type"), "lines:",
              [(_ln.get("side"), (_ln.get("x0"), _ln.get("x1"))) for _ln in (_p.get("lines") or [])])
    png2 = generate_chart(h1_conf, c, confirmed=True)
    open("/home/user/probe_AERO_confirmed.png", "wb").write(png2 or b"")
    print("confirmed png bytes:", len(png2 or b""))


if __name__ == "__main__":
    main()
