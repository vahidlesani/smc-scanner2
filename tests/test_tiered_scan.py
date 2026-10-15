"""R99c — tiered-scan tests: aggregation truth, cadence, budget, guard."""
import pandas as pd

import analysis.tiered_scan as ts


def _bars_15m(n=10, start=1_699_999_200):  # 1800-aligned: pairs fold exactly
    rows = []
    for i in range(n):
        o = 100.0 + i
        rows.append({"timestamp": pd.Timestamp(start + i * 900, unit="s"),
                     "open": o, "high": o + 1.0, "low": o - 1.0,
                     "close": o + 0.5, "volume": 10.0})
    return pd.DataFrame(rows)


def test_agg_map_covers_all_derived_and_minimal_bases():
    assert set(ts.AGG_MAP) == {"30m", "2h", "8h", "12h", "3d", "1w"}
    assert ts.BASE_TFS == ("5m", "15m", "1h", "4h", "1d")
    for _derived, (_base, _k) in ts.AGG_MAP.items():
        assert _base in ts.BASE_TFS and _k >= 2


def test_aggregate_ohlc_exact_and_partial_dropped():
    out = ts.aggregate_frame(_bars_15m(10), 2, 900)
    assert out is not None and len(out) == 5
    _r0 = out.iloc[0]
    assert _r0["open"] == 100.0 and _r0["close"] == 101.5
    assert _r0["high"] == 102.0 and _r0["low"] == 99.0
    assert _r0["volume"] == 20.0
    # 9 bars -> 4 complete buckets, the forming 9th bar is dropped
    out9 = ts.aggregate_frame(_bars_15m(9), 2, 900)
    assert out9 is not None and len(out9) == 4


def test_aggregate_monday_week_and_too_short():
    assert ts.aggregate_frame(_bars_15m(3), 2, 900) is None
    assert ts.aggregate_frame(None, 2) is None
    assert ts.aggregate_frame(_bars_15m(10), 1) is None
    _d = pd.DataFrame([{"timestamp": pd.Timestamp("2026-01-05") + pd.Timedelta(days=i),
                        "open": 1.0, "high": 2.0, "low": 0.5,
                        "close": 1.5, "volume": 1.0} for i in range(14)])
    _w = ts.aggregate_frame(_d, 7, monday_shift=True)
    assert _w is not None and len(_w) == 2
    assert pd.Timestamp(_w.iloc[0]["timestamp"]).weekday() == 0  # Monday


def test_cadence_env_parsing(monkeypatch):
    monkeypatch.delenv("TIER_DEEP_MINUTES", raising=False)
    monkeypatch.setenv("FULL_SCAN_MINUTES", "5")
    assert ts.deep_minutes() == 5
    monkeypatch.setenv("TIER_DEEP_MINUTES", "10")
    assert ts.deep_minutes() == 10
    monkeypatch.delenv("TIER_SPOT_DEEP_MINUTES", raising=False)
    monkeypatch.delenv("SPOT_SCAN_MINUTES", raising=False)
    assert ts.spot_deep_minutes() == 60
    monkeypatch.setenv("TIER_GUARD_SECONDS", "45")
    assert ts.guard_seconds() == 45
    monkeypatch.setenv("TIER_GUARD_ENABLED", "0")
    assert ts.guard_enabled() is False


def test_budget_and_caps(monkeypatch):
    monkeypatch.setenv("VIVA_MAX_SIGNALS_PER_DAY", "25")
    monkeypatch.setenv("VIVA_MAX_CONCURRENT_POSITIONS", "3")
    assert ts.daily_cap() == 25 and ts.concurrent_cap() == 3
    assert ts.concurrent_ok(2) is True and ts.concurrent_ok(3) is False
    _store = {}

    class _KV:
        @staticmethod
        def get_json(_k, default=None):
            return _store.get(_k, default)

        @staticmethod
        def set_json(_k, _v):
            _store[_k] = _v
            return True

    monkeypatch.setattr(ts, "_kv", lambda: _KV)
    assert ts.daily_budget_ok("2099-01-01") is True
    assert ts.daily_count_incr("futures", "2099-01-01") == 1
    assert ts.daily_count("2099-01-01") == 1
    assert ts.daily_count_incr("spot", "2099-01-01") == 1
    assert ts.daily_count("2099-01-01") == 2  # TOTAL across lanes
    # R99q (Viva 10-15): the daily TOTAL cap is RETIRED — the counter still
    # tracks publishes for telemetry, but it never gates a setup again.
    _store["tier_day_count:2099-01-01:futures"] = 20
    _store["tier_day_count:2099-01-01:spot"] = 5
    assert ts.daily_budget_ok("2099-01-01") is True  # retired: never caps
    assert ts.daily_count_incr("nope", "2099-01-01") == -1


def test_spot_unchanged_skip(monkeypatch):
    _store = {}

    class _KV:
        @staticmethod
        def get_json(_k, default=None):
            return _store.get(_k, default)

        @staticmethod
        def set_json(_k, _v):
            _store[_k] = _v
            return True

    monkeypatch.setattr(ts, "_kv", lambda: _KV)

    class _B:
        def __init__(self, tag):
            self._df = pd.DataFrame(
                [{"timestamp": pd.Timestamp(tag)}])

        def get(self, _tf):
            return self._df

    assert ts.spot_unchanged_skip("BTCUSDT", _B("2026-10-14 00:00")) is False
    assert ts.spot_unchanged_skip("BTCUSDT", _B("2026-10-14 00:00")) is True
    assert ts.spot_unchanged_skip("BTCUSDT", _B("2026-10-14 04:00")) is False


def test_guard_band_logic(monkeypatch):
    monkeypatch.setenv("TIER_GUARD_BAND_PCT", "1.0")
    assert ts.dist_to_entry_pct("LONG", 100.0, 100.5) == 0.5
    assert ts.dist_to_entry_pct("LONG", 0, 100.0) is None
    assert ts.guard_should_fire("LONG", 100.0, 100.5) is True
    assert ts.guard_should_fire("SHORT", 100.0, 102.0) is False
