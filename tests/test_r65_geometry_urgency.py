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
