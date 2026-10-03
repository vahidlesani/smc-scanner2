"""R64.1/R64.2 — his 10-03 bug gallery.

* TC snapshot immutability: the trade-line keys are snapshotted now.
* Deep-frame zoom: the 300-candle map frames the LIVE region (soft far clip),
  overlays stay full; shallow frames keep the r40 hard fill.
* TL live-relevance: a line that ends miles away from the live price is not
  a trend (NEAR 12h class) — skipped; env 0 restores legacy.
* Spot chains get durable codes VIVA-SPOT-Y######.
"""
import os
import sys
import re
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_snapshot_keys_carry_tc_trade_lines():
    from analysis.snapshot_lock import SNAPSHOT_KEYS
    for k in ("viva_upper_points", "viva_lower_points", "tc_projection"):
        assert k in SNAPSHOT_KEYS


def test_deep_frame_zoom_frames_the_live_region():
    from bot.messages_v7 import _smart_y_window
    # 300-bar tape: dead history 0..100, recent 40 bars 48..52
    deep = _smart_y_window(0.0, 100.0, 0.8, None, None,
                           recent_lo=48.0, recent_hi=52.0, bars=300)
    assert deep is not None
    assert deep[0] > 20.0, deep          # far history no longer drags the axis
    shallow = _smart_y_window(0.0, 100.0, 0.8, None, None,
                              recent_lo=48.0, recent_hi=52.0, bars=0)
    assert shallow[0] <= 0.0 + 1e-9      # r40 hard fill intact for shallow frames
    # overlays are NEVER cut, even deep
    withtool = _smart_y_window(0.0, 100.0, 0.8, None, 95.0,
                               recent_lo=48.0, recent_hi=52.0, bars=300)
    assert withtool[1] >= 95.0 - 1e-9


def test_tl_live_relevance_gate_skips_stale_lines(monkeypatch):
    from analysis.viva_tlbreak import fit_validated_line, load_config
    import dataclasses as dc
    # flat base, an old LOWER pair far below the final rally (stale line),
    # then a strong rally: the stale pair's live-bar value is < 45% of live.
    n = 120
    ts = pd.date_range("2026-08-01", periods=n, freq="1h")
    closes = [100.0] * 40 + [100.0 - 30.0 + 0.5 * i for i in range(30)] \
        + [115.0 + 2.0 * i for i in range(50)]
    lows = [c - 0.5 for c in closes]
    lows[10] = 70.0; lows[11] = 69.0; lows[12] = 70.0     # stale pivot trio
    highs = [c + 0.5 for c in closes]
    f = pd.DataFrame({"timestamp": ts, "open": closes, "high": highs,
                      "low": lows, "close": closes, "volume": [1.0] * n})
    cfg = dc.replace(load_config(), pivot_left=2, pivot_right=2, min_touches=2,
                     touch_tolerance_atr=0.30, max_fit_residual_atr=2.0,
                     require_alive=False, wick_policy="hybrid")
    monkeypatch.setenv("TL_MAX_LIVE_DRAG", "0.55")
    got = fit_validated_line(f, "LOW", cfg)
    # the surviving line (if any) must END near the live price
    if got is not None:
        live = float(f["close"].iloc[-1])
        assert abs(float(got.slope) * (n - 1) + float(got.intercept) / live - 1.0) < 0.60
    monkeypatch.setenv("TL_MAX_LIVE_DRAG", "0")
    got_off = fit_validated_line(f, "LOW", cfg)
    assert got_off is not None               # legacy behavior reachable


def test_spot_chain_code_format():
    from analysis.models import generate_viva_public_code
    code = generate_viva_public_code("SPOT")
    assert re.fullmatch(r"VIVA-SPOT-Y\d{6}", code), code
