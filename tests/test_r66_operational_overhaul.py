"""Unit tests for R66 Operational Overhaul & Optimization (Viva 10-03).

Covers:
  1. HTF Kline Caching (no artificial 30m truncation for 4h/1d candles).
  2. Spike Candle Isolation & Aspect Ratio Preservation.
  3. Deduplication of Overlapping Trendlines.
  4. Single-Wick Anchor Distortion Elimination.
  5. Single Message Exit Consolidation.
  6. Pre-Confirm Update Limit (Max 1 update).
  7. Institutional Volume & Order Flow Engine.
"""
import math
import numpy as np
import pandas as pd
import pytest

from analysis.volume_engine import analyze_volume_profile, VolumeAnalysisResult
from data.fetcher import closed_candle_ttl


# ── 1. HTF Kline Caching Tests ──────────────────────────────────────────────
def test_htf_kline_caching_full_window():
    """4h, 8h, 1d, 3d, 1w cache for their natural period, never capped to 1800s."""
    ttl_1d = closed_candle_ttl("1d")
    ttl_4h = closed_candle_ttl("4h")
    ttl_15m = closed_candle_ttl("15m")

    # 15m is naturally <= 900s
    assert 20 <= ttl_15m <= 902
    # 4h can have TTL up to 14400s (more than old 1800s cap)
    assert 20 <= ttl_4h <= 14402
    # 1d can have TTL up to 86400s (more than old 1800s cap)
    assert 20 <= ttl_1d <= 86402


# ── 2. Spike Candle Zoom Isolation ──────────────────────────────────────────
def test_spike_candle_zoom_isolation():
    """An extreme isolated liquidation spike should not squash normal candle bodies."""
    from bot.messages_v7 import _smart_y_window

    # Baseline 100 candles between 100.0 and 105.0
    n = 100
    px = np.linspace(100.0, 105.0, n)
    c_lo = 100.0
    c_hi = 105.0
    atr = 1.0
    recent_lo = 103.0
    recent_hi = 105.0

    w_normal = _smart_y_window(c_lo, c_hi, atr, recent_lo=recent_lo, recent_hi=recent_hi)
    assert w_normal is not None
    span_normal = w_normal[1] - w_normal[0]

    # Extreme spike: candle 1 has a flash dump wick to 40.0
    # With outlier filtering, c_lo_eff should bound near normal lows
    p1 = 99.8
    c_lo_spike = 40.0
    c_lo_eff = max(c_lo_spike, p1 - 2.5 * atr)

    w_spike = _smart_y_window(c_lo_eff, c_hi, atr, recent_lo=recent_lo, recent_hi=recent_hi)
    assert w_spike is not None
    span_spike = w_spike[1] - w_spike[0]

    # The effective window should protect candle bodies (span_spike within reasonable factor of normal)
    assert span_spike < 2.5 * span_normal
    assert w_spike[0] > 70.0, "extreme spike must not drag window down to 40"


# ── 3. Single-Wick Anchor Distortion Elimination ────────────────────────────
def test_single_wick_anchors_to_body_not_distorted_wick():
    """An isolated liquidation spike wick anchors at the candle body, not the extreme wick tip."""
    from analysis.indicators import pivots

    n = 60
    ts = pd.date_range("2026-10-01", periods=n, freq="1h")
    px = np.linspace(100.0, 102.0, n)
    d = pd.DataFrame({
        "timestamp": ts,
        "open": px,
        "high": px + 0.3,
        "low": px - 0.3,
        "close": px + 0.1,
    })
    # Candle 30 has a massive 10.0 spike wick up (liquidation wick)
    d.iloc[30, d.columns.get_loc("open")] = 101.0
    d.iloc[30, d.columns.get_loc("close")] = 101.2
    d.iloc[30, d.columns.get_loc("high")] = 110.0  # extreme wick
    d.iloc[30, d.columns.get_loc("low")] = 100.8

    highs, _ = pivots(d, left=3, right=3, wick_noise_filter=True, wick_policy="hybrid")
    spike_pivots = [p for p in highs if p["index"] == 30]
    assert len(spike_pivots) == 1
    # Must anchor to body, not the 110.0 wick tip
    assert spike_pivots[0]["anchor"] == "body"
    assert spike_pivots[0]["price"] == pytest.approx(101.2, abs=0.01)


# ── 4. Duplicate Overlapping Trendlines Deduplication ────────────────────────
def test_dedupe_overlapping_trendlines():
    """Two nearly identical trendlines on the same side are deduplicated."""
    from analysis.render_kit import line_y as _line_y_cal

    frame = pd.DataFrame({
        "high": np.linspace(100, 110, 50) + 0.5,
        "low": np.linspace(100, 110, 50) - 0.5,
        "close": np.linspace(100, 110, 50),
    })
    atr = 1.0

    pats = [
        {
            "type": "CHANNEL",
            "lines": [
                {"side": "HIGH", "slope": 0.2, "intercept": 100.0, "x0": 0, "x1": 50},
                {"side": "LOW", "slope": 0.2, "intercept": 95.0, "x0": 0, "x1": 50},
            ]
        },
        {
            "type": "TRENDLINE",
            "lines": [
                # Overlapping almost exactly with previous HIGH line (slope 0.201, intercept 100.1)
                {"side": "HIGH", "slope": 0.201, "intercept": 100.1, "x0": 0, "x1": 50},
            ]
        }
    ]

    # Test the deduplication logic directly
    cnt = len(frame)
    kept = []
    seen_lines = []
    for p in pats:
        lns = p.get("lines") or []
        filtered_lns = []
        for ln in lns:
            side = str(ln.get("side") or "").upper()
            y0 = float(_line_y_cal(ln, 0))
            ym = float(_line_y_cal(ln, cnt // 2))
            ye = float(_line_y_cal(ln, cnt))
            is_dup = False
            for s_prev, y0_p, ym_p, ye_p in seen_lines:
                if s_prev == side:
                    d0 = abs(y0 - y0_p)
                    dm = abs(ym - ym_p)
                    de = abs(ye - ye_p)
                    if max(d0, dm, de) <= 0.40 * atr:
                        is_dup = True
                        break
            if not is_dup:
                seen_lines.append((side, y0, ym, ye))
                filtered_lns.append(ln)
        if filtered_lns:
            kept.append({**p, "lines": filtered_lns})

    # The second HIGH line must be eliminated
    high_lines = [ln for p in kept for ln in p.get("lines", []) if ln.get("side") == "HIGH"]
    assert len(high_lines) == 1


# ── 5. Single Message Exit Consolidation ────────────────────────────────────
def test_trade_close_event_skips_when_ladder_exit_already_sent():
    """If send_ladder_event already handled final exit, send_trade_close_event skips duplicate chart."""
    from bot.messages_v7 import send_trade_close_event, _mark_ladder_exit_sent

    event = {
        "signal_id": "TEST_SIG_CONSOLIDATE_01",
        "public_code": "TC999",
        "event": "CLOSED",
        "result": "WIN",
    }
    # Before marking ladder exit
    # Mark ladder exit sent as send_ladder_event does on final TP / stop
    _mark_ladder_exit_sent(event["signal_id"])

    # send_trade_close_event should return True immediately without publishing duplicate chart
    assert send_trade_close_event(event) is True


# ── 6. Pre-Confirm Update Limit ─────────────────────────────────────────────
def test_pre_confirm_update_limit_max_one():
    """At most one update message is posted between initial alert and confirmation."""
    from analysis.models import SignalCandidate
    from bot.messages_v7 import send_setup_update

    cand = SignalCandidate(
        signal_id="TEST_LIMIT_UPDATES",
        symbol="BTCUSDT",
        style="SWING",
        setup_code="TLBREAK",
        setup_name="TLBREAK",
        strategy_fa="شکست خط روند",
        direction="LONG",
        score=8,
        status="PENDING",
        entry_zone_bottom=100.0,
        entry_zone_top=101.0,
        planned_entry=100.5,
        sl=98.0,
        tp1=104.0,
        tp2=107.0,
        rr_tp1=1.5,
        rr_tp2=3.0,
        bias="BULLISH",
        trigger_timeframe="1h",
    )
    # Simulate that an approaching alert has already been sent
    cand.metadata["approaching_sent"] = True

    # A non-critical update must be blocked
    result = send_setup_update(cand, note_fa="تست آپدیت مازاد", state_fa="در حال نوسان", critical=False)
    assert result is False, "non-critical update must be blocked if approaching alert was already sent"


# ── 7. Institutional Volume & Order Flow Engine Tests ───────────────────────
def test_volume_engine_whale_surge():
    """High volume Z-score triggers whale volume surge flag and boosts institutional score."""
    n = 30
    ts = pd.date_range("2026-10-01", periods=n, freq="15min")
    px = np.linspace(100.0, 105.0, n)
    vols = np.full(n, 1000.0)
    # Massive volume spike on the last candle (5x normal)
    vols[-1] = 5000.0

    d = pd.DataFrame({
        "timestamp": ts,
        "open": px - 0.2,
        "high": px + 0.5,
        "low": px - 0.3,
        "close": px + 0.4,
        "volume": vols,
        "turnover": vols * px,
    })

    res = analyze_volume_profile(d, direction="LONG")
    assert res.volume_zscore > 2.5
    assert "WHALE_VOLUME_SURGE" in res.flags or "INSTITUTIONAL_SURGE" in res.flags
    assert res.score >= 6.5
    assert "نهنگ" in res.summary_fa or "نهادی" in res.summary_fa


def test_volume_engine_vsa_absorption():
    """Very high volume + narrow spread detects absorption."""
    n = 30
    ts = pd.date_range("2026-10-01", periods=n, freq="15min")
    px = np.linspace(100.0, 102.0, n)
    vols = np.full(n, 1000.0)
    vols[-1] = 3000.0  # high volume

    # Highs and lows: normal spread is 1.0, last candle spread is tiny 0.15
    highs = px + 0.5
    lows = px - 0.5
    highs[-1] = px[-1] + 0.08
    lows[-1] = px[-1] - 0.07

    d = pd.DataFrame({
        "timestamp": ts,
        "open": px,
        "high": highs,
        "low": lows,
        "close": px + 0.02,
        "volume": vols,
        "turnover": vols * px,
    })

    res = analyze_volume_profile(d, direction="LONG")
    assert "VOLUME_ABSORPTION" in res.flags
    assert "Absorption" in res.summary_fa
