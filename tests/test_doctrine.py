"""Doctrine 09-16 night: base/continuation gate + range TP locking.

Viva's rules under test:
  * «سقف دنبال نزولی، کف دنبال صعودی» — inside a PLAIN range the ceiling
    feeds shorts and the floor feeds longs, edge-to-edge only.
  * after a spike/trend, a base (rectangle/wedge/triangle/plain base/IFVG/
    supply...) is a CONTINUATION structure: touching an edge = warning only,
    break + first trigger-TF close (or pullback retest of the broken edge)
    = entry.  No swing high/low may by itself forbid continuation.
  * TPs outside a live range/channel are POST-BREAK only.
"""
import numpy as np
import pandas as pd

from analysis.render_kit import base_gate, detect_base, gate_ladder


def _ohlc(close, seed=5, sigma=0.0, wick=0.05):
    rng = np.random.default_rng(seed)
    close = np.asarray(close, float) + rng.normal(0, sigma, len(close))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(wick * 0.5, wick, len(close))
    low = np.minimum(open_, close) - rng.uniform(wick * 0.5, wick, len(close))
    return pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=len(close), freq="1h"),
                         "open": open_, "high": high, "low": low,
                         "close": close, "volume": 1e6})


def _zig(pre, lo, hi, half, bars):
    out = list(pre)
    up = True
    t = 0
    while len(out) < bars:
        a = lo if up else hi
        b = hi if up else lo
        out.extend(np.linspace(a, b, half)[1 if out else 0:])
        up = not up
        t += 1
    return np.array(out[:bars], float)


class _Cand:
    def __init__(self, direction, targets):
        self.direction = direction
        self.metadata = {"target_ladder": {"targets": targets,
                                            "weights": [30, 30, 20, 20]}}


def test_detect_base_flat_range_then_edges():
    lead = np.full(40, 100.0)
    body = _zig([], 100.0, 101.2, 4, 25)
    df = _ohlc(np.concatenate([lead, body]), sigma=0.04, wick=0.10)
    base = detect_base(df)
    assert base is not None and base["trend"] is None
    assert base["side"] in ("DOWN", "UP")           # last close sits at an edge


def test_detect_base_spike_up_base_above():
    spike = np.linspace(10.0, 11.5, 30)
    base_seg = _zig([], 11.30, 11.62, 4, 24)
    close = np.concatenate([spike, base_seg, [11.95]])
    df = _ohlc(close, sigma=0.04, wick=0.04)
    b = detect_base(df)
    assert b is not None and b["trend"] == "UP" and b["side"] == "ABOVE"


def test_gate_pure_range_mean_reversion():
    b = {"trend": None, "hi": 101.2, "lo": 100.0, "side": "DOWN", "touch_from": "ABOVE"}
    assert base_gate("LONG", b) == "ALLOW"          # کف دنبال صعودی
    assert base_gate("SHORT", b) == "REJECT-EDGE"
    b2 = dict(b, side="UP", touch_from="BELOW")
    assert base_gate("SHORT", b2) == "ALLOW"        # سقف دنبال نزولی
    assert base_gate("LONG", b2) == "REJECT-EDGE"
    assert base_gate("LONG", dict(b, side=None)) == "REJECT-MID"
    assert base_gate("LONG", dict(b, side="ABOVE")) == "ALLOW"
    assert base_gate("SHORT", dict(b, side="BELOW")) == "ALLOW"


def test_gate_trend_up_continuation():
    up = {"trend": "UP", "hi": 11.62, "lo": 11.30}
    # break close above / pullback retest from above = long entries
    assert base_gate("LONG", dict(up, side="ABOVE", touch_from=None)) == "ALLOW"
    assert base_gate("LONG", dict(up, side="UP", touch_from="ABOVE")) == "ALLOW"
    # touch from inside = warning only, no position yet
    assert base_gate("LONG", dict(up, side="UP", touch_from="BELOW")) == "WARN-CONT"
    assert base_gate("SHORT", dict(up, side="UP", touch_from="BELOW")) == "WARN-REV"
    # base failure: break below / retest from below = short
    assert base_gate("SHORT", dict(up, side="BELOW", touch_from=None)) == "ALLOW"
    assert base_gate("SHORT", dict(up, side="DOWN", touch_from="BELOW")) == "ALLOW"
    # longs at the floor of a continuation base are counter-trend
    assert base_gate("LONG", dict(up, side="DOWN", touch_from="ABOVE")) == "REJECT-SIDE"


def test_gate_trend_down_mirror():
    dn = {"trend": "DOWN", "hi": 10.70, "lo": 10.38}
    assert base_gate("SHORT", dict(dn, side="BELOW", touch_from=None)) == "ALLOW"
    assert base_gate("SHORT", dict(dn, side="DOWN", touch_from="BELOW")) == "ALLOW"
    assert base_gate("SHORT", dict(dn, side="DOWN", touch_from="ABOVE")) == "WARN-CONT"
    assert base_gate("LONG", dict(dn, side="DOWN", touch_from="ABOVE")) == "WARN-REV"
    assert base_gate("LONG", dict(dn, side="ABOVE", touch_from=None)) == "ALLOW"
    assert base_gate("SHORT", dict(dn, side="UP", touch_from="BELOW")) == "REJECT-SIDE"


def test_gate_ladder_locks_external_targets():
    base = {"trend": None, "hi": 101.2, "lo": 100.0, "side": "DOWN", "touch_from": "ABOVE"}
    c = _Cand("LONG", [100.8, 101.1, 101.6, 102.0])
    gate_ladder(c, base)
    assert c.metadata["tp_gates"] == {"level": 101.2, "locked": [2, 3]}
    c2 = _Cand("SHORT", [100.6, 100.2, 99.4, 98.8])
    gate_ladder(c2, base)
    assert c2.metadata["tp_gates"] == {"level": 100.0, "locked": [2, 3]}
    # once the edge breaks, the outside targets wake up
    c3 = _Cand("LONG", [100.8, 101.1, 101.6, 102.0])
    gate_ladder(c3, dict(base, side="ABOVE"))
    assert "tp_gates" not in c3.metadata
