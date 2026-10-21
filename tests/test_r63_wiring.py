"""R63 wiring: W3 budget share, W4 thread-local profile, W5 fetch diet, W8 2h, weekly buckets."""
import threading

import pandas as pd


def test_profile_override_is_thread_local_W4():
    from analysis import setups_v7
    setups_v7.PROFILE_OVERRIDE["SWING"] = ("2h", "1h", "30m")
    seen = {}

    def other():
        seen["p"] = setups_v7.timeframe_profile("SWING")

    t = threading.Thread(target=other)
    t.start(); t.join()
    try:
        assert setups_v7.timeframe_profile("SWING") == ("2h", "1h", "30m")
        assert seen["p"] == setups_v7.TIMEFRAME_PROFILES["SWING"]
    finally:
        setups_v7.PROFILE_OVERRIDE.pop("SWING", None)
    assert "SWING" not in setups_v7.PROFILE_OVERRIDE


def test_2h_alone_fetches_the_15m_base_W8(monkeypatch):
    # R64: 2h rides the DIRECT 1h tape now (250 two-hour candles cannot come
    # from ≤1000 15m bars); the W8 guarantee — 2h alone is never None — stays.
    import data.fetcher as f
    calls = []

    def fake(symbol, interval, limit, closed_only=True, **kw):
        calls.append((interval, limit))
        freq = {"15m": "15min", "1h": "1h"}.get(interval, "15min")
        ts = pd.date_range("2026-09-01", periods=limit, freq=freq)
        return pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 1.0, "low": 1.0,
                             "close": 1.0, "volume": 1.0})
    monkeypatch.setattr(f, "get_klines", fake)
    b = f.get_market_bundle("XUSDT", ("2h",))
    assert b.get("2h") is not None and len(b.get("2h")) >= 250
    assert calls and calls[0][0] == "1h" and calls[0][1] <= 1000


def test_2h_falls_back_to_15m_when_no_1h_route_R64(monkeypatch):
    import data.fetcher as f
    calls = []

    def fake(symbol, interval, limit, closed_only=True, **kw):
        calls.append((interval, limit))
        if interval == "1h":
            return None
        ts = pd.date_range("2026-09-01", periods=limit, freq="15min")
        return pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 1.0, "low": 1.0,
                             "close": 1.0, "volume": 1.0})
    monkeypatch.setattr(f, "get_klines", fake)
    b = f.get_market_bundle("XUSDT", ("2h",))
    assert b.get("2h") is not None and len(b.get("2h")) >= 100
    assert [c[0] for c in calls] == ["1h", "15m"]


def test_fit_window_has_2h_30m_W8():
    from analysis.pattern_engine import _FIT_WINDOW
    assert "2h" in _FIT_WINDOW and "30m" in _FIT_WINDOW


def test_htf_fetch_windows_not_always_W5(monkeypatch):
    import main
    from datetime import datetime, timezone

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 1, 5, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(main, "datetime", _DT)
    assert main._tf_fetch_window("8h") is False
    assert main._tf_fetch_window("12h") is False
    assert main._tf_fetch_window("1w") is False


def test_expected_closed_bar_W5():
    import main
    k = main._expected_closed_bar("1h")
    assert len(k) == 16 and k.endswith(":00")
    assert main._expected_closed_bar("weird") == ""


def test_weekly_bucket_is_monday():
    from data.fetcher import _aggregate_daily
    ts = pd.date_range("2026-08-01", periods=60, freq="1D")
    d = pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0})
    w = _aggregate_daily(d, 7)
    assert set(w["timestamp"].dt.day_name()) == {"Monday"}


def test_budget_share_source_W3():
    src = open("main.py", encoding="utf-8").read()
    assert "_per_setup_cap" in src and "_break_reserve" in src and "_budget_ok(candidate)" in src
