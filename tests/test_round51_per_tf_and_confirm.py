"""r51 — MULTI-TF-TREND LAW + CONFIRM-TIMING + UPDATE-EVENT + PRICE-AXIS.

Viva 09-27 batch:
1. Every visited TF must draw ITS OWN precise trendlines/patterns; foreign
   anchors (pivot timestamps outside the render window) collapsed onto x=0
   and fanned «tangled red lines» with the channel's lower line missing
   (WLD 1D/2H/30m, RAY 1H, ADA/FIL 1D). The renderer now RE-FITS foreign
   patterns and viva edges on the render frame's own tape.
2. Structural lanes (TLBREAK/TECHCLASSIC/ALBROX) confirm at the FIRST close
   beyond the edge even when the duty-cycle window is closed (DASH T242271:
   63→74 swept +17% with zero confirms in 1670 minutes).
3. Updates only on confirm / invalidation / final-readiness — the per-candle
   «زنجیره زنده و زیر نظر است» heartbeat is retired.
4. LOG charts print plain decimal prices — the r48 spot/wide-span log switch
   must re-arm the plain formatter (FIL/ADA/WLD axes showed 10⁰, 2.8×10⁻¹).
"""
import ast
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _synthetic_frame(n: int = 80, start="2026-09-01", freq="1h") -> pd.DataFrame:
    rng = np.random.default_rng(51)
    base = 1.0 + np.cumsum(rng.normal(0.0008, 0.006, n))
    highs = base * (1 + np.abs(rng.normal(0.004, 0.002, n)))
    lows = base * (1 - np.abs(rng.normal(0.004, 0.002, n)))
    opens = np.concatenate([[base[0]], base[:-1]])
    closes = base
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({
        "timestamp": idx, "open": opens, "high": np.maximum(highs, np.maximum(opens, closes)),
        "low": np.minimum(lows, np.minimum(opens, closes)), "close": closes,
        "volume": rng.uniform(800, 2000, n),
    }).set_index("timestamp")


def _foreign_pattern() -> dict:
    """A channel whose anchors predate any plausible render window (what the
    detector stored on its deep tape before the frame was re-cut)."""
    return {
        "type": "CHANNEL_ASCENDING",
        "lines": [
            {"slope": 0.001, "intercept": 1.0, "x0": 0, "log_fit": False,
             "points": [{"ts": "2026-06-01T00:00:00", "price": 1.0},
                        {"ts": "2026-06-10T00:00:00", "price": 1.05}]},
            {"slope": 0.0009, "intercept": 0.95, "x0": 0, "log_fit": False,
             "points": [{"ts": "2026-06-02T00:00:00", "price": 0.97},
                        {"ts": "2026-06-12T00:00:00", "price": 1.02}]},
        ],
    }


# ── 1. anchor-nativity gate ────────────────────────────────────────────────
def test_native_pattern_passes_through():
    from bot.messages_v7 import _pattern_anchors_in_frame
    frame = _synthetic_frame()
    pat = {"type": "WEDGE", "lines": [{"points": [
        {"ts": str(frame.index[5]), "price": 1.1},
        {"ts": str(frame.index[40]), "price": 1.2}]}]}
    assert _pattern_anchors_in_frame(pat, frame.index[0], frame.index[-1])


def test_foreign_anchor_is_caught():
    from bot.messages_v7 import _pattern_anchors_in_frame
    frame = _synthetic_frame()
    assert not _pattern_anchors_in_frame(_foreign_pattern(), frame.index[0], frame.index[-1])


def test_range_boxes_are_always_native():
    from bot.messages_v7 import _pattern_anchors_in_frame
    frame = _synthetic_frame()
    pat = {"type": "RANGE", "lo": 0.9, "hi": 1.1, "ts0": "2019-01-01T00:00:00"}
    assert _pattern_anchors_in_frame(pat, frame.index[0], frame.index[-1])


def test_foreign_pattern_refit_returns_frame_native_geometry():
    from bot.messages_v7 import _native_patterns_for_frame
    from bot.messages_v7 import _TF_PATTERN_CACHE
    _TF_PATTERN_CACHE.clear()
    frame = _synthetic_frame()
    out = _native_patterns_for_frame(frame, "LONG", "1h", "sig-r51",
                                     [_foreign_pattern()], log_axis=False)
    # the stored foreign pattern is never drawn as-is…
    assert out != [_foreign_pattern()]
    # …and whatever the TF's own fitter returns carries anchors INSIDE the frame
    for pat in out:
        t0, t1 = frame.index[0], frame.index[-1]
        for ln in (pat.get("lines") or []):
            for pt in (ln.get("points") or []):
                ts = pd.Timestamp(str(pt.get("ts")))
                if ts.tzinfo is not None:
                    ts = ts.tz_localize(None)
                assert t0.tz_localize(None) <= ts <= t1.tz_localize(None)


def test_native_pattern_is_not_refitted():
    from bot.messages_v7 import _native_patterns_for_frame
    from bot.messages_v7 import _TF_PATTERN_CACHE
    _TF_PATTERN_CACHE.clear()
    frame = _synthetic_frame()
    native = {"type": "TRENDLINE", "lines": [{"slope": 0.002, "intercept": 0.9,
             "x0": 0, "log_fit": False, "points": [
                 {"ts": str(frame.index[2]), "price": 0.95},
                 {"ts": str(frame.index[60]), "price": 1.05}]}]}
    out = _native_patterns_for_frame(frame, "LONG", "1h", "sig-native",
                                     [native], log_axis=False)
    assert out == [native]


# ── 2. viva edge points ────────────────────────────────────────────────────
def test_viva_points_nativity_and_refit():
    from bot.messages_v7 import _viva_points_native, _refit_viva_points
    frame = _synthetic_frame(120, freq="1h")
    foreign = [{"timestamp": "2026-05-01T00:00:00", "price": 1.2},
               {"timestamp": "2026-05-20T00:00:00", "price": 1.3}]
    assert not _viva_points_native(foreign, frame)
    native = [{"timestamp": str(frame.index[10]), "price": 1.1},
              {"timestamp": str(frame.index[90]), "price": 1.2}]
    assert _viva_points_native(native, frame)
    refit = _refit_viva_points(frame, "HIGH")
    if refit:  # the synthetic tape often yields a valid 2-touch edge
        assert len(refit) >= 2
        for p in refit:
            ts = pd.Timestamp(p["timestamp"])
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
            assert frame.index[0].tz_localize(None) <= ts <= frame.index[-1].tz_localize(None)


# ── 3. price axis: plain decimals only ─────────────────────────────────────
def test_axis_price_never_scientific():
    from bot.messages_v7 import _axis_price
    assert _axis_price(0.2338) == "0.2338"
    assert _axis_price(0.28) == "0.28"
    assert _axis_price(0.2352) != _axis_price(0.2338)
    assert _axis_price(10.5) == "10.5000"
    assert _axis_price(60_000) == "60,000"
    assert _axis_price(123.456) == "123.46"
    assert _axis_price(0) == "0"
    for v in (7.1, 0.6, 2.8e-1, 0.09, 1234.5):
        out = _axis_price(v)
        assert "e" not in out.lower() and "×" not in out, out


def test_log_switch_restores_plain_formatter():
    """The r48 spot/wide-span set_yscale('log') site must re-arm the plain
    formatter (FIL/ADA/WLD 1D printed 10⁰ / 9×10⁻¹ after it)."""
    src = open(os.path.join(ROOT, "bot", "messages_v7.py")).read()
    marker = src.index("if _is_spot or _span48 >= 1.30:")
    window = src[marker:marker + 900]
    assert 'ax.set_yscale("log")' in window
    assert "set_major_formatter(FuncFormatter(_axis_price))" in window
    assert "NullFormatter" in window


# ── 4. confirm-timing breaker (DASH law) ───────────────────────────────────
def test_structural_break_edge_resolution():
    from main import _structural_break_edge

    class _C:
        direction = "LONG"
        entry_zone_top = 67.251
        entry_zone_bottom = 65.114
        metadata = {"tl_line": 66.0}

    assert _structural_break_edge(_C()) == 66.0

    class _C2(_C):
        metadata = {}

    assert _structural_break_edge(_C2()) == 67.251

    class _C3(_C):
        direction = "SHORT"
        metadata = {}

    assert _structural_break_edge(_C3()) == 65.114


def test_break_bypass_and_no_heartbeat_in_monitor_source():
    src = open(os.path.join(ROOT, "main.py")).read()
    # the DASH law: live price beyond the edge → forced frame fetch
    assert "_structural_break_edge" in src
    assert "break_bypass_at" in src
    assert "break_bypass" in src
    # the update-event law: the candle heartbeat is retired
    assert '"hb_bar"' not in src
    assert '"hb_count"' not in src
    assert "گزارشِ پایانِ کندل" not in src
    assert "heartbeat watch" not in src
    # structural lanes set membership is what the breaker keys on
    assert '_STRUCTURAL_QUALITY_LANES' in src


def test_messages_module_still_importable():
    import bot.messages_v7 as m
    assert hasattr(m, "_native_patterns_for_frame")
    assert hasattr(m, "_refit_viva_points")
    assert hasattr(m, "_TF_PATTERN_CACHE")
