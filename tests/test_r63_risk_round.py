"""r63 risk pack — his 10-01 amendment laws ① and ⑥.

* Law ① stop ladder: initial stop behind the last swing of trigger-TF+1,
  else +2 TFs, else the nearest-of-3.5/5%-to-structural fallback (cap 5%).
* Law ⑥ trailing v2: the trail sits at the INITIAL stop distance behind the
  closed-candle price (ratchet-only); TP1 already banks 40%; the immediate
  exit flag = reverse pin OR engulfing WITH a close beyond the last swing
  of the fast frame, armed only between TP1 and TP2.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── law ① · risk ladder ─────────────────────────────────────────────────────

def _swing_df(prices, side="low", start="2026-09-25", freq="1h",
              pad_at=101.0, pad=32):
    """A ≥30-bar flat pad (pivot-free) followed by points that are clean 2/2
    pivots at `prices`, so the LAST one is trivially the most recent swing."""
    ts = pd.date_range(start, periods=pad + len(prices), freq=freq)
    all_p = [pad_at] * pad + list(prices)
    lows = [p - 0.6 for p in all_p]
    highs = [p + 0.6 for p in all_p]
    closes = list(all_p)
    return pd.DataFrame({"timestamp": ts, "open": closes, "high": highs,
                         "low": lows, "close": closes,
                         "volume": [100.0] * len(all_p)})


def test_ladder_uses_plus_one_tf_swing():
    from analysis.risk_ladder import ladder_stop
    # 1h swings with the last confirmed swing low at 98.0
    frames = {"1h": _swing_df([100.0, 102.0, 98.0, 101.0, 99.0, 103.0])}
    calls = []
    def fetch(sym, tf, n, **kw):
        calls.append(tf)
        return frames.get(tf)
    out = ladder_stop("XUSDT", "LONG", 105.0, "15m", 2.0, fetch)
    assert out and out["hop"] == 1 and out["tf"] == "1h" and out["basis"] == "SWING"
    assert out["stop"] < 98.0                       # behind the swing + buffer
    assert 96.0 < out["stop"] < 98.0


def test_ladder_falls_to_second_tf_then_pct():
    from analysis.risk_ladder import ladder_stop
    # hop1 (4h): the transition pivot sits ~15% below entry → the 12% sanity
    # guard skips it; hop2 (1d): frame missing → pct fallback
    bad = _swing_df([90.0, 92.0, 91.0, 93.0, 92.5, 94.0])
    frames = {"4h": bad}
    def fetch(sym, tf, n, **kw):
        return frames.get(tf)
    out = ladder_stop("XUSDT", "LONG", 105.0, "1h", 2.0, fetch)
    assert out["basis"] == "PCT"
    # structural 2.0% → nearest of (3.5, 5) is 3.5 → stop = entry·0.965
    assert abs(out["stop"] - 105.0 * 0.965) < 1e-6


def test_pct_tiebreak_nearest_to_structural_and_cap5():
    from analysis.risk_ladder import _pct_fallback
    # structural 4.6% → 5% is nearer; structural 9% → capped 5%
    assert abs(_pct_fallback(100.0, "LONG", 4.6) - 95.0) < 1e-9
    assert abs(_pct_fallback(100.0, "LONG", 9.0) - 95.0) < 1e-9
    assert abs(_pct_fallback(100.0, "SHORT", 1.0) - 103.5) < 1e-9


# ── law ⑥ · trailing v2 ─────────────────────────────────────────────────────

def _ladder(entry=100.0, sl=98.0, direction="LONG"):
    from analysis.trade_management import build_ladder
    return build_ladder(entry=entry, sl=sl, direction=direction,
                        final_target=107.0, trigger_tf="15m")


def _win(opens, highs, lows, closes, vols=None):
    n = len(closes)
    return [{"open": o, "high": h, "low": l, "close": c,
             "volume": (vols or [100.0] * n)[i]}
            for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes))]


def test_build_ladder_carries_initial_distance_and_v2_mode():
    st = _ladder()
    assert st["trail_mode"] == "INIT_DIST_V2"
    assert abs(st["initial_stop_dist"] - 2.0) < 1e-9


def test_trail_v2_chandelier_at_initial_distance():
    from analysis.trade_management import band_trailing
    st = _ladder()
    st["hit_index"] = 1
    st["current_sl"] = 100.0                       # net-BE after TP1
    # closes 103 → stop = 101; then close 104.5 → 102.5; then 102.8 → ratchet keeps 102.5
    w1 = _win([101, 102], [103.4, 103.2], [100.5, 102.4], [103.0, 103.0])
    r1 = band_trailing(dict(st), w1)
    assert abs(r1["state"]["current_sl"] - 101.0) < 1e-6
    w2 = _win([102, 103], [104.9, 104.7], [101.5, 104.2], [104.5, 104.5])
    r2 = band_trailing(r1["state"], w2)
    assert abs(r2["state"]["current_sl"] - 102.5) < 1e-6
    w3 = _win([103, 103.5], [105.0, 103.6], [102.6, 102.4], [103.4, 102.8])
    r3 = band_trailing(r2["state"], w3)
    assert abs(r3["state"]["current_sl"] - 102.5) < 1e-6   # never loosens


def test_reverse_flag_needs_swing_break_and_engulf_counts():
    from analysis.trade_management import smart_exit_scan
    # build a rising 5m feed then a bearish engulfing that closes BELOW the
    # last confirmed swing low → immediate-exit flag must fire for a LONG
    n = 26
    closes = [100.0 + 0.2 * i for i in range(n)]
    # plant a clear swing low at i=20 (dip)
    closes[20] = closes[19] - 1.2
    closes[21] = closes[20] + 0.9
    closes[22] = closes[21] + 0.9
    closes[23] = closes[22] + 0.9
    opens = [c - 0.05 for c in closes]
    highs = [c + 0.15 for c in closes]
    lows = [c - 0.15 for c in closes]
    # last candle: bearish engulfing closing below the swing low (101.8+)
    swing_low = closes[20]
    opens[-1] = closes[-2] + 0.10                  # opens above prev close
    closes[-1] = swing_low - 0.5                   # closes below the swing
    highs[-1] = opens[-1] + 0.12
    lows[-1] = closes[-1] - 0.10
    cands = [{"open": o, "high": h, "low": l, "close": c, "volume": 100.0}
             for o, h, l, c in zip(opens, highs, lows, closes)]
    st = {"hit_index": 1, "closed": False}
    scan = smart_exit_scan("LONG", cands, st)
    assert scan.get("reverse_pin") is True
    assert "engulf" in (scan.get("reverse_kinds") or [])

    # same pattern but the close STAYS ABOVE the last swing → no flag
    closes2 = list(closes[:-1]) + [swing_low + 0.8]
    highs2 = list(highs[:-1]) + [closes2[-1] + 0.05]
    lows2 = list(lows[:-1]) + [closes2[-1] - 0.60]
    opens2 = list(opens[:-1]) + [closes[-2] + 0.10]
    cands2 = [{"open": o, "high": h, "low": l, "close": c, "volume": 100.0}
              for o, h, l, c in zip(opens2, highs2, lows2, closes2)]
    scan2 = smart_exit_scan("LONG", cands2, {"hit_index": 1, "closed": False})
    assert scan2.get("reverse_pin") is False

    # before TP1 (hit_index=0) the scanner is not even armed
    scan3 = smart_exit_scan("LONG", cands, {"hit_index": 0, "closed": False})
    assert not scan3.get("reverse_pin")


def test_tp1_weight_is_40_percent():
    from analysis.trade_management import DEFAULT_WEIGHTS
    assert abs(DEFAULT_WEIGHTS[0] - 40.0) < 1e-9
