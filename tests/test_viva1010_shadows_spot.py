"""Viva 10-10 shadow law + spot ladder key.

Shadows: a shadow under 1.5 ATR is ALWAYS reasonable (anchors at the wick);
only very-very-long liquidation spikes demote to the body.
Spot: the ladder sig survives refits (10-bar centre bucket + side)."""
import pandas as pd


def _df():
    n = 70
    o, h, l, c = [], [], [], []
    for _ in range(n):
        o.append(99.3); h.append(100.0); l.append(99.0); c.append(99.7)
    # reasonable pivot: 1.2-ATR upper shadow (must stay a WICK pivot)
    h[30] = 100.9
    o[30] = 99.3; c[30] = 99.7; l[30] = 99.0
    # liquidation spike: 3.0-ATR shadow (must demote to BODY)
    h[50] = 102.7
    o[50] = 99.3; c[50] = 99.7; l[50] = 99.0
    ts = pd.date_range("2026-09-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": l,
                         "close": c, "volume": 1000.0})


def test_outlier_policy_respects_reasonable_shadow():
    from analysis.indicators import pivots
    highs, _ = pivots(_df(), 5, 5, wick_noise_filter=True,
                      wick_policy="outlier")
    by_idx = {q["index"]: q for q in highs}
    assert by_idx[30]["anchor"] == "wick"
    assert abs(by_idx[30]["price"] - 100.9) < 1e-9


def test_outlier_policy_still_strips_liquidation_spike():
    from analysis.indicators import pivots
    highs, _ = pivots(_df(), 5, 5, wick_noise_filter=True,
                      wick_policy="outlier")
    by_idx = {q["index"]: q for q in highs}
    assert by_idx[50]["anchor"] == "body"
    assert abs(by_idx[50]["price"] - 99.7) < 1e-9


def test_hybrid_policy_respects_reasonable_shadow():
    from analysis.indicators import pivots
    highs, _ = pivots(_df(), 5, 5, wick_policy="hybrid")
    by_idx = {q["index"]: q for q in highs}
    assert by_idx[30]["anchor"] == "wick"
    assert by_idx[50]["anchor"] == "body"


def test_spot_sig_survives_refit():
    from analysis.spot_engine import _spot_sig
    a = _spot_sig("ADAUSDT", "4h", "RISING_WEDGE", "LONG", 120, 200)
    b = _spot_sig("ADAUSDT", "4h", "RISING_WEDGE", "LONG", 122, 203)
    assert a == b


def test_spot_sig_splits_new_location_shape_side():
    from analysis.spot_engine import _spot_sig
    a = _spot_sig("ADAUSDT", "4h", "RISING_WEDGE", "LONG", 120, 200)
    assert _spot_sig("ADAUSDT", "4h", "RISING_WEDGE", "LONG", 40, 90) != a
    assert _spot_sig("ADAUSDT", "4h", "DOUBLE_TOP", "LONG", 120, 200) != a
    assert _spot_sig("ADAUSDT", "4h", "RISING_WEDGE", "SHORT", 120, 200) != a
    assert _spot_sig("BTCUSDT", "4h", "RISING_WEDGE", "LONG", 120, 200) != a
