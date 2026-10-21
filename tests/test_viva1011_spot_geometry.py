"""10-11 spot geometry pass (render-side ONLY — the confirm lane is untouched).

  G1  _spot_engine_line_frame — the engine's calibrated line re-expressed in
      frame coords (global x = frame x + start_idx).
  G2  _spot_map_pivots — out-of-frame pivots are skipped, never edge-snapped.
  G3  _spot_future_bars — the projection tail scales with the visible frame.
  G4  render smoke — a harness-like candidate still renders a full PNG.
"""
import math

import pandas as pd


def test_engine_log_line_frame_offset():
    from analysis.spot_pattern_engine import _spot_engine_line_frame as F
    # engine: y = 10**(0.001*x + 2.0) in global x; frame starts at 40.
    got = F({"log_fit": True, "log_slope": 0.001, "log_intercept": 2.0,
             "x0": 100}, 40)
    assert got is not None
    s, c, x0f = got
    assert abs(s - 0.001) < 1e-12
    assert abs(c - 2.04) < 1e-12      # c + s*start_idx
    assert x0f == 60
    # frame-x 0 must equal engine-x 40:
    assert abs((s * 0 + c) - (0.001 * 40 + 2.0)) < 1e-12


def test_engine_linear_line_log_linearized():
    from analysis.spot_pattern_engine import _spot_engine_line_frame as F
    got = F({"slope": 0.0, "intercept": 50.0, "x0": 10}, 4)
    assert got is not None
    s, c, x0f = got
    assert abs(s) < 1e-12 and abs(c - math.log10(50.0)) < 1e-12
    assert x0f == 6
    assert F({"side": "HIGH"}, 0) is None     # no fit keys → None
    assert F({}, 0) is None


def test_future_bars_scale():
    from analysis.spot_pattern_engine import _spot_future_bars as B
    assert B(45) == 8 and B(20) == 8 and B(0) == 8
    assert B(144) == 24 and B(200) == 24
    assert B(120) == 20                        # proportional middle


def test_pivot_map_skips_out_of_frame():
    from analysis.spot_pattern_engine import _spot_map_pivots as M
    ts = list(pd.date_range("2026-09-01", periods=10, freq="8h"))
    pts = [{"ts": ts[3], "price": 1.0},
           {"ts": "2020-01-01", "price": 2.0},   # far outside → skipped
           {"ts": "not-a-date", "price": 3.0}]   # unparsable → skipped
    x, y = M(pts, ts)
    assert x == [3] and y == [1.0]


def test_earliest_inframe_ignores_stale():
    import datetime
    from analysis.spot_pattern_engine import _spot_earliest_inframe as E
    t0 = datetime.datetime(2026, 7, 1)
    t1 = datetime.datetime(2026, 9, 1)
    pts = [{"ts": "2026-04-01"},                    # stale → ignored
           {"ts": "not-a-date"},                    # garbage → ignored
           {"ts": "2026-08-10"}, {"ts": "2026-07-20"}]
    got = E(pts, t0, t1, 8 * 3600.0)
    assert got == pd.to_datetime("2026-07-20")
    assert E([{"ts": "2020-01-01"}], t0, t1, 3600.0) is None
    assert E([], t0, t1, 3600.0) is None


def test_render_smoke_full_png():
    import numpy as np
    from analysis.spot_pattern_engine import render_cryptocove_spot_chart
    n = 120
    rng = np.random.default_rng(3)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, n)))
    opn = np.concatenate([[100.0], close[:-1]])
    df = pd.DataFrame({"timestamp": pd.date_range("2026-08-01", periods=n,
                                                  freq="8h"),
                       "open": opn, "high": np.maximum(opn, close) * 1.004,
                       "low": np.minimum(opn, close) * 0.996,
                       "close": close, "volume": 500.0})

    class C:
        symbol = "SMK"
        trigger_timeframe = "8h"
        direction = "LONG"
        status = "TOUCH"
        metadata = {
            "render_patterns": [{"name_fa": "کانال", "type": "CHANNEL_ASC",
                                 "lines": [
                                     {"points": [
                                         {"ts": df["timestamp"].iloc[20],
                                          "price": float(df["high"].iloc[20])},
                                         {"ts": df["timestamp"].iloc[90],
                                          "price": float(df["high"].iloc[90])}],
                                      "side": "HIGH", "x0": 20, "x1": 90,
                                      "log_fit": True, "log_slope": 0.0002,
                                      "log_intercept": 1.99},
                                     {"points": [
                                         {"ts": df["timestamp"].iloc[25],
                                          "price": float(df["low"].iloc[25])},
                                         {"ts": df["timestamp"].iloc[95],
                                          "price": float(df["low"].iloc[95])}],
                                      "side": "LOW", "x0": 25, "x1": 95,
                                      "log_fit": True, "log_slope": 0.0002,
                                      "log_intercept": 1.98}]}] ,
            "pattern_type": "CHANNEL_ASC", "spot_alert_stage": "TOUCH",
            "spot_alert_side": "LONG", "chart_view_tf": "8h"}

    png = render_cryptocove_spot_chart(df, C(), confirmed=False)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 50000   # a full chart, not a blank/error frame
