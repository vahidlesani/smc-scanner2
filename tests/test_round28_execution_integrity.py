"""R28 execution-integrity laws: initial stops need real room and trailing stops never chase a closed candle."""
from analysis.trade_management import (
    initial_stop_distance_pct,
    initial_stop_is_valid,
    min_initial_stop_pct,
    band_trailing,
)


def test_initial_stop_floor_is_timeframe_aware():
    assert min_initial_stop_pct("15m") < min_initial_stop_pct("1h") < min_initial_stop_pct("1d")
    assert initial_stop_distance_pct(100.0, 99.5) == 0.5
    assert initial_stop_is_valid(100.0, "LONG", 99.5, "15m")
    assert not initial_stop_is_valid(100.0, "LONG", 99.8, "15m")
    assert initial_stop_is_valid(100.0, "SHORT", 100.5, "15m")
    assert not initial_stop_is_valid(100.0, "SHORT", 100.2, "15m")


def test_initial_stop_rejects_wrong_side():
    assert not initial_stop_is_valid(100.0, "LONG", 100.5, "15m")
    assert not initial_stop_is_valid(100.0, "SHORT", 99.5, "15m")


def test_trailing_long_stays_below_closed_price():
    state = {
        "version": 2, "closed": False, "hit_index": 1,
        "entry": 100.0, "direction": "LONG", "current_sl": 101.0,
        "targets": [101.0, 102.0], "trail_stops": [101.0, 101.5],
        "band_floors": [101.9], "band_hit_index": 1,
        "band_extreme": 101.0, "tick_gap": 0.01,
    }
    candles = [{"open": 101.0, "high": 102.2, "low": 100.9, "close": 102.0}] * 21
    out = band_trailing(state, candles)["state"]
    assert out["current_sl"] < candles[-1]["close"]


def test_trailing_short_stays_above_closed_price():
    state = {
        "version": 2, "closed": False, "hit_index": 1,
        "entry": 100.0, "direction": "SHORT", "current_sl": 99.0,
        "targets": [99.0, 98.0], "trail_stops": [99.0, 98.5],
        "band_floors": [98.1], "band_hit_index": 1,
        "band_extreme": 99.0, "tick_gap": 0.01,
    }
    candles = [{"open": 99.0, "high": 99.1, "low": 97.8, "close": 98.0}] * 21
    out = band_trailing(state, candles)["state"]
    assert out["current_sl"] > candles[-1]["close"]
