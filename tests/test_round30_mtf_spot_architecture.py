import pandas as pd

from analysis.spot_engine import (
    SPOT_LONG_TFS,
    SPOT_MID_TFS,
    SPOT_SHORT_TFS,
    SPOT_TRIGGERS,
    _SPOT_STYLE_BY_TF,
)
from data.fetcher import _resample_ohlcv, get_market_bundle


def _frame(periods: int, freq: str) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=periods, freq=freq)
    base = pd.Series(range(periods), dtype=float) + 100.0
    return pd.DataFrame({
        "timestamp": ts,
        "open": base,
        "high": base + 2.0,
        "low": base - 1.0,
        "close": base + 1.0,
        "volume": 100.0,
    })


def test_spot_horizons_are_short_mid_long():
    assert SPOT_SHORT_TFS == ("4h", "8h")
    assert SPOT_MID_TFS == ("12h", "1d")
    assert SPOT_LONG_TFS == ("3d", "1w")
    assert SPOT_TRIGGERS == ("4h", "8h", "12h", "1d", "3d", "1w")
    assert _SPOT_STYLE_BY_TF["4h"] == "SWING"
    assert _SPOT_STYLE_BY_TF["8h"] == "SWING"
    assert _SPOT_STYLE_BY_TF["12h"] == "SWING"
    assert _SPOT_STYLE_BY_TF["1d"] == "GRAND"
    assert _SPOT_STYLE_BY_TF["3d"] == "GRAND"
    assert _SPOT_STYLE_BY_TF["1w"] == "GRAND"


def test_resample_ohlcv_requires_complete_buckets():
    src = _frame(10, "15min")
    out = _resample_ohlcv(src, "1h", 4)
    assert out is not None
    assert len(out) == 2
    assert out.loc[0, "open"] == src.loc[0, "open"]
    assert out.loc[0, "close"] == src.loc[3, "close"]
    assert out.loc[0, "high"] == src.loc[:3, "high"].max()
    assert out.loc[0, "low"] == src.loc[:3, "low"].min()


def test_market_bundle_derives_multiples_and_keeps_5m_direct(monkeypatch):
    calls = []

    def fake_get_klines(symbol, interval, limit=200, closed_only=True, use_cache=True, end_ms=None):
        calls.append((interval, int(limit)))
        if interval == "5m":
            return _frame(300, "5min")
        if interval == "15m":
            return _frame(200, "15min")
        if interval == "4h":
            return _frame(170, "4h")
        if interval == "1d":
            return _frame(420, "1D")
        raise AssertionError(f"unexpected direct timeframe: {interval}")

    monkeypatch.setattr("data.fetcher.get_klines", fake_get_klines)
    bundle = get_market_bundle(
        "BTCUSDT",
        ("4h", "8h", "12h", "1d", "3d", "1w", "1h", "15m", "5m"),
        limits={"4h": 170, "1d": 420, "3d": 120, "1w": 60, "5m": 300, "15m": 200},
    )

    assert [tf for tf, _ in calls] == ["5m", "15m", "4h", "1d"]
    assert len(bundle.get("5m")) == 300
    assert len(bundle.get("15m")) == 200
    assert len(bundle.get("4h")) == 170
    assert len(bundle.get("8h")) >= 45
    assert len(bundle.get("12h")) >= 45
    assert len(bundle.get("1h")) >= 45
    assert len(bundle.get("3d")) >= 45
    assert len(bundle.get("1w")) >= 45
