"""R31.5 — 30m discovery bundle fix + replay-harness look-ahead guards."""
import inspect

import pandas as pd


def test_discovery_bundle_requests_30m():
    import main
    assert "30m" in main._DISCOVERY_TFS
    src = inspect.getsource(main.run_discovery_scan)
    assert "get_market_bundle(symbol, _DISCOVERY_TFS" in src


def test_market_bundle_derives_30m_from_15m(monkeypatch):
    import data.fetcher as f
    ts = pd.date_range("2026-01-01", periods=900, freq="15min")
    base = pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 2.0, "low": 0.5,
                         "close": 1.5, "volume": 1.0, "turnover": 1.0})
    monkeypatch.setattr(f, "get_klines", lambda s, tf, n=200, closed_only=True, **k: base.tail(n).reset_index(drop=True))
    b = f.get_market_bundle("XUSDT", ("1d", "4h", "1h", "30m", "15m", "5m"))
    assert b.get("30m") is not None and len(b.get("30m")) >= 300
    step = pd.to_datetime(b.get("30m")["timestamp"]).diff().dropna().unique()
    assert list(step) == [pd.Timedelta(minutes=30)]


def test_pinval_freshness_knows_30m():
    from analysis import setups_experimental as exp
    src = inspect.getsource(exp.detect_pinbar_zone)
    assert '"30m": 1800' in src


def test_replay_tape_never_leaks_future_candles():
    from experiments.replay_live_setups import Tape, synthetic_base, Sim, _fake_get_klines, TF_MIN
    tape = Tape("SYNTHUSDT", synthetic_base(6))
    t = pd.Timestamp("2026-01-04 13:25:00")
    for tf in ("5m", "15m", "30m", "1h", "4h", "1d"):
        d = tape.closed(tf, t, 50)
        if d is None:
            continue
        last_close = pd.Timestamp(d["timestamp"].iloc[-1]) + pd.Timedelta(minutes=TF_MIN[tf])
        assert last_close <= t, tf
    Sim.tape, Sim.t = tape, t
    live = _fake_get_klines("SYNTHUSDT", "1h", 30, closed_only=False)
    closed = _fake_get_klines("SYNTHUSDT", "1h", 30, closed_only=True)
    assert pd.Timestamp(live["timestamp"].iloc[-1]) == t.floor("1h")
    assert pd.Timestamp(closed["timestamp"].iloc[-1]) + pd.Timedelta(hours=1) <= t
    # the forming bar only uses 5m bars already closed at t
    assert float(live["high"].iloc[-1]) <= float(tape.closed("5m", t, 12)["high"].max()) + 1e-12


def test_htf_frame_helper_no_dataframe_truthiness():
    from analysis.setups_experimental import _htf_frame
    df4 = pd.DataFrame({"close": [1.0, 2.0]})
    df1 = pd.DataFrame({"close": [3.0]})

    class B:
        def __init__(self, f):
            self.f = f

        def get(self, k):
            return self.f.get(k)
    assert _htf_frame(B({"4h": df4, "1h": df1})) is df4
    assert _htf_frame(B({"1h": df1})) is df1


def test_pinval_30m_stream_is_opt_in(monkeypatch):
    from config import Settings
    monkeypatch.delenv("PINVAL_30M_ENABLED", raising=False)
    assert Settings.pinval_30m_enabled is False
    from analysis import setups_experimental as exp
    assert 'pinval_30m_enabled' in inspect.getsource(exp.detect_pinbar_zone)
