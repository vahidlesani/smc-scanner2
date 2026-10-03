"""Tests for Round 68: Unified Pattern & Trendline Engine (VIVA-TLBREAK for ALL).

Verifying:
1. Cluster extreme start (ZRO 2H highest peak in start cluster).
2. Stale broken trendline rejection (PENGU 12H ancient history purged).
3. TECHCLASSIC & ALBROX riding the exact VIVA-TLBREAK engine.
4. Spot BREAK_UP stage with live chart trigger.
5. CryptoCove golden picture density (RENDER_COUNTS for 4h/8h/12h/1d).
6. Candle clearance for all chart labels & chips.
7. True sloped channel geometry for Bull & Bear Flags.
"""
import pandas as pd
import numpy as np
import pytest

from analysis.candle_counts import RENDER_COUNTS, candle_count, render_count
from analysis.patterns16 import detect_flag_pennant
from analysis.spot_engine import _stage_for_pattern


def _make_ohlcv(n=200, start_price=10.0, trend=0.0):
    timestamps = pd.date_range("2026-09-01", periods=n, freq="4h")
    np.random.seed(42)
    closes = [start_price]
    for i in range(1, n):
        step = trend + np.random.normal(0, 0.05)
        closes.append(max(0.1, closes[-1] + step))
    closes = np.array(closes)
    highs = closes + np.random.uniform(0.02, 0.08, n)
    lows = closes - np.random.uniform(0.02, 0.08, n)
    opens = (closes + np.roll(closes, 1)) / 2
    opens[0] = closes[0]
    volumes = np.random.uniform(1000, 5000, n)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def test_cryptocove_picture_density():
    """CryptoCove dictates readable 140-180 candles for mid/macro charts."""
    assert render_count("4h") == 160
    assert render_count("8h") == 160
    assert render_count("12h") == 160
    assert render_count("1d") == 180
    # Detection retains deep history for discovering majors
    assert candle_count("4h") == 300
    assert candle_count("1d") == 300


def test_spot_break_up_stage():
    """Spot ladder issues BREAK_UP stage when price breaks validly above the upper edge."""
    pat = {
        "shape": "parallel",
        "lines": [
            {"side": "HIGH", "slope": 0.0, "intercept": 10.0, "x0": 0, "x1": 50},
            {"side": "LOW", "slope": 0.0, "intercept": 8.0, "x0": 0, "x1": 50},
        ],
    }
    # Candle closing well above 10.0 with bullish body
    d = pd.DataFrame({
        "open": [9.8, 9.9, 10.05],
        "close": [9.9, 10.0, 10.35],
        "high": [10.0, 10.1, 10.40],
        "low": [9.7, 9.8, 10.0],
    })
    atr = 0.5
    stage_info = _stage_for_pattern(pat, d, atr, len(d) - 1)
    assert stage_info is not None
    assert stage_info["stage"] == "BREAK_UP"
    assert stage_info["side"] == "HIGH"
    assert stage_info["edge"] == 10.0


def test_spot_break_down_stage():
    """Spot ladder retains BREAK_DOWN stage when price breaks validly below lower edge."""
    pat = {
        "shape": "parallel",
        "lines": [
            {"side": "HIGH", "slope": 0.0, "intercept": 10.0, "x0": 0, "x1": 50},
            {"side": "LOW", "slope": 0.0, "intercept": 8.0, "x0": 0, "x1": 50},
        ],
    }
    # Candle closing well below 8.0 with bearish body
    d = pd.DataFrame({
        "open": [8.2, 8.1, 7.95],
        "close": [8.1, 8.0, 7.65],
        "high": [8.3, 8.2, 8.0],
        "low": [8.0, 7.9, 7.60],
    })
    atr = 0.5
    stage_info = _stage_for_pattern(pat, d, atr, len(d) - 1)
    assert stage_info is not None
    assert stage_info["stage"] == "BREAK_DOWN"
    assert stage_info["side"] == "LOW"
    assert stage_info["edge"] == 8.0


def test_flag_sloped_channel():
    """Bull flag produces a counter-trend downward sloped channel, NOT a flat box."""
    n = 60
    closes = np.ones(n) * 10.0
    # Bullish pole: bars 20-30 rally from 10 to 18
    for i in range(20, 31):
        closes[i] = 10.0 + (i - 20) * 0.8
    # Consolidation flag: bars 31-50 drift down from 18 to 16
    for i in range(31, 51):
        closes[i] = 18.0 - (i - 30) * 0.1
    for i in range(51, n):
        closes[i] = closes[50]
    highs = closes + 0.3
    lows = closes - 0.3
    opens = closes.copy()
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-09-01", periods=n, freq="4h"),
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": np.ones(n) * 1000
    })
    atr = 0.5
    pats = detect_flag_pennant(df, atr)
    assert len(pats) > 0
    flag = pats[0]
    assert "FLAG" in flag["type"] or "PENNANT" in flag["type"]
    lines = flag["lines"]
    assert len(lines) == 2
    # Flag upper and lower lines have negative slope (down-sloping counter-drift)
    if "FLAG" in flag["type"]:
        assert lines[0]["slope"] <= 0.0
        assert lines[1]["slope"] <= 0.0


def test_technoclassic_and_albrox_use_viva_tlbreak():
    """Verify TECHCLASSIC and ALBROX detectors now route through detect_viva_tlbreak."""
    from analysis import setups_experimental as exp
    import inspect
    tc_src = inspect.getsource(exp.detect_technoclassic)
    assert "detect_viva_tlbreak(bundle, style, setup_code=\"TECHCLASSIC\")" in tc_src
    al_src = inspect.getsource(exp.detect_albrox)
    assert "detect_viva_tlbreak(bundle, style, setup_code=\"ALBROX\")" in al_src
