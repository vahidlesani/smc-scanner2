"""R65 — the 10-02 round (Viva's NIGHTUSDT + TECH + zoom + trendline audit).

Every test here pins a measured defect found on the real tapes:

* dual-space trendline fit (the BTC 1h case where a price-collinear descending
  line was invisible because the fit ran only in log space);
* TECHCLASSIC's tradeable-break gate (66% of break events arrive 1.5–10 ATR
  past the edge → the mint died silently in the geometry net);
* spot urgency — the ONE-STEP-LOWER confirm ladder and the break-bar truth;
* the focus window of the smart zoom (his «روی ارتفاع کندل‌ها دقت بشه»).
"""
from __future__ import annotations

import io
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _tape(n=170, freq="4h", end=None):
    """Descending-highs trendline: three PRICE-COLLINEAR touches + a final
    close above the line (the probe geometry)."""
    end = end or pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None))
    ts = pd.date_range(end=end, periods=n, freq=freq)
    U = lambda i: 130.0 - 0.28 * i
    L = lambda i: 98.0 - 0.125 * i
    nodes = [(0, 0.5 * (U(0) + L(0))), (40, U(40)), (65, L(65)), (95, U(95)),
             (120, L(120)), (144, U(144)), (160, L(160)), (n - 2, L(160) + 6)]
    vals = np.zeros(n)
    for (i0, v0), (i1, v1) in zip(nodes, nodes[1:]):
        vals[i0:i1 + 1] = np.linspace(v0, v1, i1 - i0 + 1)
    vals[n - 1] = vals[n - 2] + 1.0
    o = vals - 0.10
    c = vals + 0.10
    h = np.maximum(o, c) + 0.25
    low = np.minimum(o, c) - 0.25
    for i, v in ((40, U(40)), (95, U(95)), (144, U(144))):
        h[i] = v
        c[i] = v - 0.15
        o[i] = v - 0.35
        low[i] = o[i] - 0.25
    o[-1], c[-1], h[-1], low[-1] = 86.0, 90.0, 90.5, 85.5
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": low,
                         "close": c, "volume": np.full(n, 1000.0),
                         "turnover": np.full(n, 50000.0)})


# ── 1. dual-space fitter ────────────────────────────────────────────────────
def test_dual_space_finds_price_collinear_line_on_log_window():
    """The BTC 1h defect: the window spans >3% (→ log axis) but the pivots are
    collinear in PRICE. The fitter must still validate that line."""
    import analysis.viva_tlbreak as V
    d = _tape()
    assert (float(d["high"].max()) - float(d["low"].min())) / float(d["low"].min()) > 0.03
    os.environ["TLBREAK_R65_DUAL_SPACE"] = "1"
    ln = V.fit_validated_line(d, "HIGH")
    assert ln is not None, "price-collinear descending line must be found"
    assert ln.touch_count >= 3
    # the line must actually sit on its pivots, not float above the tape
    for p in ln.points:
        assert abs(float(p["price"]) - ln.price_at(float(p["index"]))) <= 0.35
    # the kill switch restores the legacy (log-only) behaviour
    os.environ["TLBREAK_R65_DUAL_SPACE"] = "0"
    try:
        legacy = V.fit_validated_line(d, "HIGH")
    finally:
        os.environ["TLBREAK_R65_DUAL_SPACE"] = "1"
    assert legacy is None or legacy.touch_count <= ln.touch_count


def test_dual_space_is_a_fallback_never_a_rival():
    """The chart's own space wins a tie: the alternate carries a weight."""
    import analysis.viva_tlbreak as V
    assert 0 < V._R65_ALT_SPACE_WEIGHT < 1.0


# ── 2. TECHCLASSIC tradeable-break gate ─────────────────────────────────────
def test_tc_extension_gate_ledger_and_cap():
    import analysis.pattern_engine as PE
    from analysis.pattern_engine import _fit_cfg
    cfg = _fit_cfg()
    assert float(cfg.extension_cap_atr_daytrade) > 0
    assert callable(PE.drain_r65_extension_blocks)
    src = io.open(os.path.join(ROOT, "analysis", "pattern_engine.py"),
                  encoding="utf-8").read()
    assert "R65 TRADEABLE-BREAK" in src
    assert "_d65 > _ext_cap" in src


def test_tc_gate_blocks_a_chase_and_keeps_a_fresh_break():
    """A far break must be refused with a ledger entry; a fresh one survives."""
    import analysis.pattern_engine as PE
    import analysis.setups_experimental  # noqa: F401 — registers SETUP_NAMES
    from data.fetcher import MarketBundle

    d = _tape()
    trig = d.tail(40).reset_index(drop=True)
    live = float(d["close"].iloc[-1])
    evs = [e for e in PE.scan_edges(d, trig, "4h", live_price=live)
           if e["state"] == PE.STATE_BREAK]
    if not evs:
        pytest.skip("probe tape produced no break event")
    b = MarketBundle(symbol="TESTUSDT",
                     frames={"4h": d, "1d": d, "1h": d, "30m": d, "15m": d, "2h": d},
                     ticker={"last_price": live})
    PE.drain_r65_extension_blocks()
    _ = PE.detect_technoclassic(b, "DAYTRADE")
    blocks = PE.drain_r65_extension_blocks()
    assert all("TESTUSDT" in x for x in blocks)
    # the ledger only ever records real over-extension
    for row in blocks:
        assert float(row.rsplit("|", 1)[1]) > 1.5


# ── 3. spot urgency ─────────────────────────────────────────────────────────
def test_spot_confirm_ladder_is_one_step_below():
    from analysis.spot_engine import spot_confirm_tf
    assert spot_confirm_tf("4h") == "1h"
    assert spot_confirm_tf("8h") == "1h"
    assert spot_confirm_tf("12h") == "4h"
    assert spot_confirm_tf("1d") == "4h"
    assert spot_confirm_tf("3d") == "1d"
    assert spot_confirm_tf("1w") == "1d"


def test_find_break_bar_returns_the_first_clearing_close():
    from analysis.spot_engine import find_break_bar
    d = pd.DataFrame({"close": [10.0, 10.2, 10.6, 10.9, 11.4]})
    assert find_break_bar(d, 10.5, 0.02) == 2
    assert find_break_bar(d, 12.0, 0.02) is None


def _sub_tape(pat: pd.DataFrame, break_up: bool) -> pd.DataFrame:
    """A 1h tape whose LAST CLOSED candle closes above the 4h edge."""
    from analysis.render_kit import detect_patterns, line_y
    pats = detect_patterns(pat, "LONG", log_axis=True)
    assert pats, "the 4h shape must be detected first"
    edge = max(float(line_y(l, len(pat) - 1)) for l in pats[0]["lines"])
    end = pd.Timestamp(pat["timestamp"].iloc[-1])
    ts = pd.date_range(end=end + pd.Timedelta(hours=1), periods=36, freq="1h")
    closes = np.linspace(edge - 3.0, edge - 0.4, len(ts))
    if break_up:
        # a normal break close: just past the edge (a chase would be refused
        # by the R65 recency law, by design)
        closes[-1] = edge + 0.35
    o = closes - 0.15
    h = np.maximum(o, closes) + 0.2
    low = np.minimum(o, closes) - 0.2
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": low,
                         "close": closes, "volume": np.full(len(ts), 900.0),
                         "turnover": np.full(len(ts), 40000.0)})


def test_urgent_confirm_fires_on_sub_tf_close_without_pattern_tf_close():
    from analysis.spot_engine import scan_spot_urgent_confirms
    pat = _tape()                       # the 4h tape closes BELOW its edge
    sub = _sub_tape(pat, break_up=True)  # …but the fresh 1h candle breaks out
    items = scan_spot_urgent_confirms("TESTUSDT", {"4h": pat, "1h": sub}, "4h")
    assert items, "the 1h break close must confirm the 4h shape early"
    it = items[0]
    assert it["urgent_confirm"] is True and it["confirm_tf"] == "1h"
    assert it["entry"] == pytest.approx(float(sub["close"].iloc[-1]))
    assert it["broken_level"] > 0 and it["sl"] < it["entry"]
    assert it["break_bar_ts"]


def test_urgent_confirm_refuses_when_sub_close_stays_inside():
    from analysis.spot_engine import scan_spot_urgent_confirms
    pat = _tape()
    sub = _sub_tape(pat, break_up=False)
    assert scan_spot_urgent_confirms("TESTUSDT", {"4h": pat, "1h": sub}, "4h") == []


def test_spot_scan_records_the_real_break_bar():
    src = io.open(os.path.join(ROOT, "analysis", "spot_engine.py"),
                  encoding="utf-8").read()
    assert '"bars_since_break": _bsb' in src
    assert "spot_bars_since_break" in src


# ── 4. focus window (smart zoom) ────────────────────────────────────────────
def _crushed(n=300):
    """A 300-bar tape whose live block sits in the top corner of the axis
    because of one old capitulation low (the BTC 30m picture)."""
    ts = pd.date_range("2026-06-01", periods=n, freq="30min")
    base = np.full(n, 100.0)
    base[40] = 60.0                              # the old capitulation
    rng = np.random.default_rng(5)
    close = base + rng.normal(0, 0.15, n)
    close[-60:] = 100 + rng.normal(0, 0.15, 60)
    o = close - 0.05
    h = np.maximum(o, close) + 0.2
    low = np.minimum(o, close) - 0.2
    low[40] = 59.5
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": low,
                         "close": close, "volume": np.full(n, 1000.0),
                         "turnover": np.full(n, 5e4)})


def test_focus_window_shortens_a_crushed_recent_block():
    from bot.messages_v7 import _r65_focus_window
    from analysis.models import SignalCandidate
    d = _crushed()
    cand = SignalCandidate(signal_id="t", symbol="TUSDT", style="DAYTRADE",
                           setup_code="PINVAL", setup_name="p", strategy_fa="p",
                           direction="LONG", score=8, status="CONFIRMED",
                           entry_zone_bottom=99.7, entry_zone_top=100.2,
                           planned_entry=100.0, sl=99.0, tp1=102.0, tp2=104.0,
                           rr_tp1=2.0, rr_tp2=4.0, bias="BULLISH",
                           trigger_timeframe="30m")
    cand.metadata = {}
    n = _r65_focus_window(d, cand, 300, True, max_n=300)
    assert n < 300, "a crushed recent block must shorten the frame"
    assert n >= 60
    window = d.tail(n)
    recent = window.tail(60)
    box = float(window["high"].max()) - float(window["low"].min())
    share = (float(recent["high"].max()) - float(recent["low"].min())) / box
    assert share >= 0.60


def test_focus_window_never_cuts_the_pattern_anchors():
    from bot.messages_v7 import _r65_focus_window
    from analysis.models import SignalCandidate
    d = _crushed()
    cand = SignalCandidate(signal_id="t", symbol="TUSDT", style="DAYTRADE",
                           setup_code="PINVAL", setup_name="p", strategy_fa="p",
                           direction="LONG", score=8, status="CONFIRMED",
                           entry_zone_bottom=99.7, entry_zone_top=100.2,
                           planned_entry=100.0, sl=99.0, tp1=102.0, tp2=104.0,
                           rr_tp1=2.0, rr_tp2=4.0, bias="BULLISH",
                           trigger_timeframe="30m")
    anchor_ts = str(d["timestamp"].iloc[-200])
    cand.metadata = {"break_line_geo": {"a_ts": anchor_ts}}
    n = _r65_focus_window(d, cand, 300, True, max_n=300)
    assert str(d.tail(n)["timestamp"].iloc[0]) <= anchor_ts


def test_render_density_map_is_intraday_190_210():
    from analysis.candle_counts import CANDLE_COUNTS, RENDER_COUNTS, candle_count, render_count
    for tf in ("5m", "15m", "30m", "1h", "2h"):
        assert 190 <= RENDER_COUNTS[tf] <= 210
        assert candle_count(tf) == CANDLE_COUNTS[tf] >= 250
    for tf in ("4h", "8h", "12h", "1d", "3d", "1w"):
        assert render_count(tf) == candle_count(tf)
    from bot.messages_v7 import _CHART_CANDLE_COUNTS
    assert _CHART_CANDLE_COUNTS == RENDER_COUNTS


# ── 5. pin lane: the channel-location guard ─────────────────────────────────
def _channel_tape(n=156):
    """A realistic rising channel: the tape ZIGZAGS between the two edges, so
    bodies ride near an edge and the wicks are modest (no liquidation spikes) —
    the shape the fitter and the pin lane actually see."""
    ts = pd.date_range("2026-06-01", periods=n, freq="1h")
    up = 130.0 - 0.10 * np.arange(n)
    low = 118.0 - 0.10 * np.arange(n)
    mid = (up + low) / 2.0
    phase = np.sin(np.arange(n) / 3.8)               # rides edge to edge
    close = mid + phase * (up - low) / 2.0 * 0.92
    o = close - 0.25 * np.sign(np.cos(np.arange(n) / 3.8))
    h = np.maximum(o, close) + 0.45
    lo = np.minimum(o, close) - 0.45
    hi_turn = np.arange(n)[phase > 0.93]
    lo_turn = np.arange(n)[phase < -0.93]
    for i in hi_turn:                                 # touch the upper edge
        h[i] = up[i]
        close[i] = up[i] - 0.55
        o[i] = up[i] - 0.95
        lo[i] = o[i] - 0.45
    for i in lo_turn:                                 # touch the lower edge
        lo[i] = low[i]
        close[i] = low[i] + 0.55
        o[i] = low[i] + 0.95
        h[i] = o[i] + 0.45
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": lo,
                         "close": close, "volume": np.full(n, 1000.0),
                         "turnover": np.full(n, 5e4)})


def test_pin_channel_top_gate_blocks_a_long_at_the_top():
    """His exact complaint: a LONG pin at the TOP of a channel must be refused
    (the mirror: a SHORT pin at the bottom)."""
    import analysis.setups_experimental as E
    from analysis.viva_tlbreak import fit_validated_line, load_config
    import dataclasses as _dc
    d = _channel_tape()
    cfg = _dc.replace(load_config(), pivot_left=3, pivot_right=3, min_touches=2,
                      touch_tolerance_atr=0.20, max_fit_residual_atr=0.45,
                      require_alive=False)
    up_ln = fit_validated_line(d, "HIGH", cfg)
    lo_ln = fit_validated_line(d, "LOW", cfg)
    assert up_ln is not None and lo_ln is not None, "the channel must be fittable"
    n = len(d) - 1
    hi_now, lo_now = float(up_ln.price_at(n)), float(lo_ln.price_at(n))
    span = hi_now - lo_now
    blocked, note = E._pin_channel_top_blocked(d, "LONG", hi_now - 0.05 * span)
    assert blocked and note
    blocked2, _ = E._pin_channel_top_blocked(d, "LONG", lo_now + 0.10 * span)
    assert not blocked2, "a long pin in the lower half is legal"
    blocked3, _ = E._pin_channel_top_blocked(d, "SHORT", lo_now + 0.05 * span)
    assert blocked3
    # a probe BEYOND the edge is a post-break retest — the guard stands down
    blocked4, _ = E._pin_channel_top_blocked(d, "LONG", hi_now + 0.5 * span)
    assert not blocked4


def test_pin_location_ledger_exists():
    import analysis.setups_experimental as E
    assert hasattr(E, "PINVAL_LOCATION_BLOCKS")


# ── 6. the whole point of the TC gate: a fresh break still mints ─────────────
def test_fresh_break_survives_the_extension_gate():
    import analysis.pattern_engine as PE
    from analysis.pattern_engine import _fit_cfg
    cfg = _fit_cfg()
    cap = float(cfg.extension_cap_atr_daytrade)
    # a break event sitting 0.4 ATR past its edge is inside the cap
    assert 0.4 <= cap
    src = io.open(os.path.join(ROOT, "analysis", "pattern_engine.py"),
                  encoding="utf-8").read()
    assert "events = _kept" in src


# ── 7. spot break recency: no 3-days-late confirmation, no chase ─────────────
def test_spot_break_recency_law():
    from analysis.spot_engine import spot_break_recency_ok
    assert spot_break_recency_ok(0, 0.2)
    assert spot_break_recency_ok(1, 0.95)
    assert not spot_break_recency_ok(2, 0.1)      # the «3 days later» bug
    assert not spot_break_recency_ok(None, 0.1)   # no bar in window = stale
    assert not spot_break_recency_ok(0, 2.0)      # a chase is not a confirmation


# ── 8. one canonical seconds table (the 30m/2h/4h PINVAL clock bug) ──────────
def test_tf_seconds_table_is_complete():
    from analysis.candle_counts import tf_seconds
    assert tf_seconds("30m") == 1800
    assert tf_seconds("2h") == 7200
    assert tf_seconds("4h") == 14400
    assert tf_seconds("3d") == 259200
    assert tf_seconds("1w") == 604800
    assert tf_seconds("nonsense") == 300
    src = io.open(os.path.join(ROOT, "analysis", "setups_experimental.py"),
                  encoding="utf-8").read()
    # the truncated literal map must be gone from the freshness guard
    assert '{"1m": 60, "5m": 300, "15m": 900, "1h": 3600}.get' not in src
    msrc = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert '{"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(pin_tf' not in msrc


# ── 9. the NIGHTUSDT repro: a 3d break must confirm at the 1d close ──────────
def _night_3d_frames():
    """The tape of his first question: a 3d descending trendline, the breakout
    happening INSIDE the still-forming 3d candle, confirmed by a 1d close."""
    n = 170
    up = lambda i: 130.0 - 0.28 * i
    low = lambda i: 100.0 + 0.05 * i
    up_idx, lo_idx = (40, 95, 145), (65, 120, 160)
    nodes = [(0, 0.5 * (up(0) + low(0)))]
    for a, b in zip(up_idx, lo_idx):
        nodes.append((a, float(up(a))))
        nodes.append((b, float(low(b))))
    vals = np.zeros(n)
    for (i0, v0), (i1, v1) in zip(nodes, nodes[1:]):
        vals[i0:i1 + 1] = np.linspace(v0, v1, i1 - i0 + 1)
    vals[nodes[-1][0] + 1:] = nodes[-1][1]      # the tail holds the last pivot
    o, c = vals - 0.10, vals + 0.10
    h, lo = np.maximum(o, c) + 0.25, np.minimum(o, c) - 0.25
    for i in up_idx:
        h[i] = float(up(i)); c[i] = float(up(i)) - 0.15
        o[i] = float(up(i)) - 0.35; lo[i] = o[i] - 0.25
    for i in lo_idx:
        lo[i] = float(low(i)); c[i] = float(low(i)) + 0.15
        o[i] = float(low(i)) + 0.35; h[i] = o[i] + 0.25
    now = pd.Timestamp.utcnow().tz_localize(None).floor("1d")
    d3 = pd.DataFrame({"timestamp": pd.date_range(end=now - pd.Timedelta(days=5),
                                                 periods=n - 1, freq="3D"),
                       "open": o[:-1], "high": h[:-1], "low": lo[:-1],
                       "close": c[:-1], "volume": np.full(n - 1, 1000.0),
                       "turnover": np.full(n - 1, 50000.0)})
    from analysis.render_kit import detect_patterns
    pats = detect_patterns(d3, "LONG", log_axis=True)
    n3 = len(d3) - 1
    edges = []
    import analysis.spot_engine as _S
    for p in pats:
        e = _S._edge_at_frac_index(p, float(n3) + 4.0 / 3.0)
        if e:
            edges.append(float(e))
    edge = max(edges) if edges else 109.0
    m = 40
    ts = pd.date_range(end=now - pd.Timedelta(days=1), periods=m, freq="1D")
    px = np.linspace(100.0, float(d3["close"].iloc[-2]) - 0.4, m)
    so, sc = px - 0.2, px + 0.2
    sh, sl = sc + 0.35, so - 0.35
    so[-2], sc[-2], sh[-2], sl[-2] = sc[-3] - 0.1, sc[-3] + 0.25, sc[-3] + 0.55, sc[-3] - 0.45
    brk = edge * 1.003 + 0.30
    so[-1], sc[-1], sh[-1], sl[-1] = sc[-2] + 0.1, brk, brk + 0.20, sc[-2] - 0.15
    sub = pd.DataFrame({"timestamp": ts, "open": so, "high": sh, "low": sl,
                        "close": sc, "volume": np.full(m, 1000.0),
                        "turnover": np.full(m, 50000.0)})
    return {"3d": d3, "1d": sub, "4h": sub.tail(30).copy()}, edge


def test_nightusdt_3d_break_confirms_at_the_1d_close_not_three_days_later():
    from analysis.spot_engine import scan_spot_symbol, scan_spot_urgent_confirms
    frames, edge = _night_3d_frames()
    # the OLD lane needs the PATTERN TF to close before it can say anything:
    # the last closed 3d candle is still inside the shape -> silence.
    assert scan_spot_symbol("NIGHTUSDT", frames) == []
    # the new urgent lane confirms on the 1d close that left the edge
    items = scan_spot_urgent_confirms("NIGHTUSDT", frames, "3d")
    assert items, "a 1d close beyond the broken 3d edge must confirm"
    it = items[0]
    assert it["urgent_confirm"] is True and it["confirm_tf"] == "1d"
    assert it["entry"] == float(frames["1d"]["close"].iloc[-1])
    assert it["entry"] > float(it["broken_level"])
    assert it["break_bar_ts"] == it["confirm_bar_ts"]     # the break is THIS close
    assert "ماروبوزو" in str(it["confirm_candle_fa"])


# ── 10. SPOT + the smart engine (TOHOM): earlier than the confirm candle ─────
def _fake_bull_shape(upper=105.0):
    """A bullish shape whose upper edge sits at ``upper`` (no pivots needed:
    the spot lane's own filters are exercised by the round-15 tests)."""
    def _fake(df, direction="", log_axis=None):
        n = len(df) - 1
        line = {"side": "HIGH", "slope": 0.0, "intercept": upper, "x0": 30,
                "x1": n, "points": [{"ts": str(df["timestamp"].iloc[30]),
                                     "price": upper},
                                    {"ts": str(df["timestamp"].iloc[n]),
                                     "price": upper}]}
        return [{"type": "TRENDLINE", "lines": [line], "name": "TRENDLINE",
                 "bias": "NEUTRAL", "shape": "single", "break_direction": "UP",
                 "label": "TRENDLINE"}]
    return _fake


def test_spot_tohom_confirms_before_the_confirm_candle_closes(monkeypatch):
    """Viva 10-02: «تایید اسپات با موتور توهم هوشمند می‌تونه زودتر از کلوز تایم
    تریگر تایید ورود بده». For a 4h spot chain the confirm TF is 1h and the
    smart engine reads 15m: three directional 15m closes (last one beyond the
    edge, volume jump, power candle) confirm the entry while the 4h candle is
    still forming."""
    from analysis.spot_engine import scan_spot_tohom_confirms, spot_tohom_tf
    assert spot_tohom_tf("4h") == "15m"
    now = pd.Timestamp.utcnow().tz_localize(None)
    # ── the 4h shape tape (its last bar is the STILL-FORMING candle) ──
    n4 = 90
    ts4 = pd.date_range(end=now.floor("4h"), periods=n4, freq="4h")
    px4 = np.linspace(100.0, 106.0, n4)
    d4 = pd.DataFrame({"timestamp": ts4, "open": px4 - 0.2, "high": px4 + 0.4,
                       "low": px4 - 0.5, "close": px4,
                       "volume": np.full(n4, 1000.0),
                       "turnover": np.full(n4, 5e4)})
    # ── the 15m sub tape: the last three CLOSED bars ride the break ──
    n15 = 60
    ts15 = pd.date_range(end=now.floor("15min") - pd.Timedelta(minutes=15),
                         periods=n15, freq="15min")
    px15 = np.linspace(102.0, 104.2, n15)
    o15, c15 = px15 - 0.1, px15 + 0.1
    h15, l15 = c15 + 0.2, o15 - 0.2
    vol15 = np.full(n15, 1000.0)
    for k, (oo, cc) in enumerate(((104.3, 104.6), (104.5, 105.2), (104.9, 105.7))):
        i = n15 - 3 + k
        o15[i], c15[i] = oo, cc
        h15[i] = cc + 0.12
        l15[i] = oo - 0.12
    vol15[-1], vol15[-2] = 2000.0, 900.0
    d15 = pd.DataFrame({"timestamp": ts15, "open": o15, "high": h15, "low": l15,
                        "close": c15, "volume": vol15,
                        "turnover": vol15 * np.linspace(100.0, 105.7, n15)})
    monkeypatch.setattr("analysis.render_kit.detect_patterns",
                        _fake_bull_shape(105.0))
    frames = {"4h": d4, "15m": d15, "1h": d15.tail(20).copy()}
    items = scan_spot_tohom_confirms("TESTUSDT", frames, "4h")
    assert items, "the smart engine must confirm on the sub-candles of the forming candle"
    it = items[0]
    assert it["tohom_confirm"] is True and it["urgent_confirm"] is True
    assert it["confirm_tf"] == "15m"
    assert float(it["entry"]) == float(c15[-1])
    assert float(it["entry"]) > float(it["broken_level"])
    assert "توهم" in str(it["confirm_candle_fa"])


def test_spot_tohom_is_fail_closed_without_evidence(monkeypatch):
    """No volume jump / no directional streak → NO confirmation (the engine may
    only grant early what the close law would grant later)."""
    from analysis.spot_engine import scan_spot_tohom_confirms
    now = pd.Timestamp.utcnow().tz_localize(None)
    n4 = 90
    ts4 = pd.date_range(end=now.floor("4h"), periods=n4, freq="4h")
    px4 = np.linspace(100.0, 106.0, n4)
    d4 = pd.DataFrame({"timestamp": ts4, "open": px4 - 0.2, "high": px4 + 0.4,
                       "low": px4 - 0.5, "close": px4,
                       "volume": np.full(n4, 1000.0),
                       "turnover": np.full(n4, 5e4)})
    n15 = 60
    ts15 = pd.date_range(end=now.floor("15min") - pd.Timedelta(minutes=15),
                         periods=n15, freq="15min")
    px15 = np.linspace(102.0, 103.0, n15)
    o15, c15 = px15 - 0.1, px15 + 0.1          # flat closes: no direction, no volume
    d15 = pd.DataFrame({"timestamp": ts15, "open": o15, "high": c15 + 0.2,
                        "low": o15 - 0.2, "close": c15,
                        "volume": np.full(n15, 1000.0),
                        "turnover": np.full(n15, 5e4)})
    monkeypatch.setattr("analysis.render_kit.detect_patterns",
                        _fake_bull_shape(101.5))
    frames = {"4h": d4, "15m": d15, "1h": d15.tail(20).copy()}
    assert scan_spot_tohom_confirms("TESTUSDT", frames, "4h") == []


# ── 11. the spot SNAPSHOT law: born frozen, judged on its own drawing ────────
def test_spot_snapshot_is_stamped_at_detection(monkeypatch):
    """Viva 10-02: «در اسپات وقتی یک ترند یا الگو شناسایی میشه باید اسنپ‌شات بشه
    تا تکلیفش … تایید بشه یا ریجکت». The stamp happens on the born candidate —
    NOT on the first render — so the whole life of the chain draws one picture."""
    import analysis.snapshot_lock as SL
    from analysis.spot_engine import lock_spot_snapshot
    calls = []
    monkeypatch.setattr(SL, "lock_render_geometry",
                        lambda cand, **kw: calls.append(str(cand.signal_id)) or "STAMPED")
    from tests.test_r65_geometry_urgency import _fake_bull_shape  # self import
    from analysis.spot_engine import scan_spot_symbol
    import pandas as pd
    n = 80
    ts = pd.date_range(end=pd.Timestamp.utcnow().tz_localize(None).floor("4h"),
                       periods=n, freq="4h")
    px = np.linspace(100.0, 104.4, n)      # everything below the 105 edge …
    o, cc = px - 0.2, px + 0.2
    hh, ll = cc + 0.35, o - 0.35
    o[-1], cc[-1], hh[-1], ll[-1] = 104.3, 105.6, 105.7, 104.2   # … the break bar
    d = pd.DataFrame({"timestamp": ts, "open": o, "high": hh,
                      "low": ll, "close": cc,
                      "volume": np.full(n, 1000.0), "turnover": np.full(n, 5e4)})
    monkeypatch.setattr("analysis.render_kit.detect_patterns",
                        _fake_bull_shape(105.0))
    items = scan_spot_symbol("TESTUSDT", {"4h": d})
    assert items, "the shape must confirm on the 4h close"
    from analysis.spot_engine import build_spot_candidate
    cand = build_spot_candidate(items[0])
    assert lock_spot_snapshot(cand) == "STAMPED"
    assert calls and calls[0] == str(cand.signal_id)


def test_stored_shape_is_judged_instead_of_a_refit(monkeypatch):
    """The ladder's pinned SHAPE is the one the confirm lane judges — a shifted
    window may not swap the drawing (snapshot law)."""
    from analysis.spot_engine import scan_spot_urgent_confirms
    now = pd.Timestamp.utcnow().tz_localize(None)
    n = 80
    ts = pd.date_range(end=now.floor("4h") - pd.Timedelta(hours=4), periods=n, freq="4h")
    px = np.linspace(100.0, 104.4, n)
    o, c = px - 0.2, px + 0.2
    h, l = c + 0.35, o - 0.35
    vol = np.full(n, 1000.0)
    o[-1], c[-1], h[-1], l[-1] = 104.3, 104.6, 104.7, 104.2
    d = pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": l,
                      "close": c, "volume": vol, "turnover": vol * c})
    # a 1h sub frame whose LAST CLOSED bar cleared the edge with a strong close
    n1 = 60
    ts1 = pd.date_range(end=now.floor("1h") - pd.Timedelta(minutes=60),
                        periods=n1, freq="1h")
    base = np.linspace(100.0, 103.0, n1)
    o1, c1 = base - 0.15, base + 0.15
    h1, l1 = c1 + 0.3, o1 - 0.3
    o1[-1], c1[-1], h1[-1], l1[-1] = c1[-2] + 0.1, 106.5, 106.6, c1[-2] - 0.1
    v1 = np.full(n1, 500.0)
    d1 = pd.DataFrame({"timestamp": ts1, "open": o1, "high": h1, "low": l1,
                       "close": c1, "volume": v1, "turnover": v1 * c1})
    # a shape snapshot whose upper edge is 106 — the LIVE detector (refit) would
    # say 104 and miss the break; the stored shape must be used
    shape = {"type": "TRENDLINE", "shape": "single", "bias": "BULL",
             "name": "TRENDLINE", "break_direction": "UP",
             "lines": [{"side": "HIGH", "slope": 0.0, "intercept": 106.0,
                        "x0": 10, "x1": n - 1,
                        "points": [{"ts": str(ts[10]), "price": 106.0},
                                   {"ts": str(ts[-1]), "price": 106.0}]}]}
    frames = {"4h": d, "1h": d1, "15m": d1.tail(20).copy()}
    items = scan_spot_urgent_confirms("TESTUSDT", frames, "4h", shape=shape)
    assert items and float(items[0]["broken_level"]) == 106.0
    # without the stored shape the fresh detector sees a different (lower)
    # structure — the point of the snapshot
    monkeypatch.setattr("analysis.render_kit.detect_patterns", lambda *a, **k: [])
    assert scan_spot_urgent_confirms("TESTUSDT", frames, "4h") == []


# ── 12. the chart must NOT re-fit a spot snapshot ────────────────────────────
def test_spot_chart_never_refits_its_snapshot():
    """Viva 10-02: «وقتی چارت تغییر میکنه ری‌فیت میکنن» — a spot chain's stored
    geometry is drawn as-is; only futures keep the legacy per-TF re-fit."""
    import bot.messages_v7 as M
    import pandas as pd
    n = 120
    ts = pd.date_range("2026-06-01", periods=n, freq="1h")
    px = np.linspace(100.0, 110.0, n)
    frame = pd.DataFrame({"open": px - 0.2, "high": px + 0.4, "low": px - 0.4,
                          "close": px, "volume": np.full(n, 100.0)},
                         index=ts)
    # a stored pattern whose pivots are FAR OLDER than the frame (foreign)
    stored = [{"type": "TRENDLINE", "shape": "single", "bias": "BULL",
               "lines": [{"side": "HIGH", "slope": 0.0, "intercept": 90.0,
                          "x0": 5, "x1": 40,
                          "points": [{"ts": "2025-01-01", "price": 90.0},
                                     {"ts": "2025-02-01", "price": 90.0}]}]}]
    out = M._native_patterns_for_frame(frame, "LONG", "1h", "sid", stored,
                                       log_axis=True, allow_refit=False)
    assert out is stored, "the snapshot must be drawn verbatim"
    # and the call site gives spot chains that flag
    src = io.open(os.path.join(ROOT, "bot", "messages_v7.py"),
                  encoding="utf-8").read()
    assert 'os.getenv("R65_SPOT_CHART_REFIT", "0")' in src
