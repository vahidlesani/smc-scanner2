import pandas as pd

from analysis.mtf_candles import analyze_mtf_candles


def _df(n=40, start=100.0):
    idx = pd.date_range("2026-09-24", periods=n, freq="1h")
    close = [start + i * 0.05 for i in range(n)]
    close[-2] = close[-3] - 0.1
    close[-1] = close[-2] + 0.8
    return pd.DataFrame({
        "timestamp": idx,
        "open": [x - 0.02 for x in close],
        "high": [x + 0.08 for x in close],
        "low": [x - 0.08 for x in close],
        "close": close,
        "volume": [1000.0] * n,
    })


def test_mtf_candle_engine_is_evidence_only_and_multi_tf():
    bundle = {"1h": _df(), "4h": _df(), "1d": _df()}
    out = analyze_mtf_candles(bundle, "LONG", "1h")
    assert "items" in out and "by_tf" in out
    assert isinstance(out["items"], list)
    assert out["summary"] == "" or "1H:" in out["summary"] or "4H:" in out["summary"] or "1D:" in out["summary"]
