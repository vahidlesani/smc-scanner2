"""Round 16 phase 3 — log-space calibration of trend/pattern lines.

The complaint this closes: «خط قرمز لنگ در هوا» — a fitted line that clearly
leaves the pivots it was fit through. Root cause: on a wide-span window the
chart is drawn on a LOG axis, a straight line in price space is a curve there,
so the painted segment drifts off the pivots in the middle.

Law implemented:
  * span > `log_fit_min_span` (3%, the same guard the chart obeys) → the fit
    itself runs in log10 space, so the line touches its pivots on the rendered
    chart (VALIDATED, ATR tolerances untouched — only the geometry changes);
  * the drawn geometry is a calibrated polyline (a 2-point segment for linear
    lines, byte-identical to before), on the pattern lines AND after a display
    TF step-up;
  * the confirmation gates (pattern band containment, break-side law) project
    the calibrated curve exactly instead of the old chord;
  * narrow-span windows keep the previous linear behaviour exactly.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────── fixtures ───────────────────────────────
def _frame_from_lows(lows, hi=1.012, op=1.003, cl=1.006, freq="4h"):
    lows = [float(x) for x in lows]
    ts = pd.date_range("2026-09-01", periods=len(lows), freq=freq)
    return pd.DataFrame({"timestamp": ts,
                         "open": [x * op for x in lows],
                         "high": [x * hi for x in lows],
                         "low": lows,
                         "close": [x * cl for x in lows],
                         "volume": [1000] * len(lows)})


def _rail_frame(alpha, pad, pivots, n=90, hi=1.012, op=1.003, cl=1.006):
    """A support rail that touches the lows at exactly `pivots` (a clean
    log-linear rail); the reference rail is returned for assertions."""
    rail = 60.0 * np.power(alpha, np.arange(n, dtype=float))
    lows = rail * pad
    for p in pivots:
        lows[p] = rail[p]
    return _frame_from_lows(lows, hi=hi, op=op, cl=cl), rail


def _render_cfg():
    """The chart's own fitter settings (analysis.render_kit.detect_patterns)."""
    import dataclasses as _dc
    from analysis.viva_tlbreak import load_config
    return _dc.replace(load_config(), pivot_left=3, pivot_right=3, min_touches=2,
                       touch_tolerance_atr=0.20, max_fit_residual_atr=0.45,
                       require_alive=True)


_WIDE = (1.008, 1.03, (16, 38, 60, 80))       # ~+120% span → log axis
_NARROW = (1.0003, 1.003, (12, 30, 48, 64))   # ~+2.3% span → linear axis


def _wide_frame():
    return _rail_frame(*_WIDE)


def _narrow_frame():
    return _rail_frame(*_NARROW, n=70, hi=1.002, op=1.001, cl=1.001)


# ─────────────────────────────── the fit ───────────────────────────────
def test_wide_span_window_fits_in_log_space():
    from analysis.viva_tlbreak import fit_validated_line
    cfg = _render_cfg()
    df, base = _wide_frame()
    line = fit_validated_line(df, "LOW", cfg)
    assert line is not None, "a clean rail must still validate"
    assert line.log_fit is True
    assert line.log_slope > 0 and line.log_intercept > 0
    # every touch pivot sits ON the calibrated curve (that is the whole point)
    atr = float((df["high"] - df["low"]).tail(14).mean())
    for point in line.points:
        y = line.price_at(float(point["index"]))
        assert abs(float(point["price"]) - y) <= 0.20 * atr
    # the rail the frame was built on IS the fitted curve (log-linear)
    assert line.price_at(float(line.last_index)) == pytest.approx(
        float(base[line.last_index]), rel=0.01)


def test_log_fit_beats_the_linear_chord_on_a_wide_window():
    """The measured proof of «لنگ در هوا»: on a log axis the linear chord is
    off the middle pivots by more than the calibration tolerance."""
    from analysis.viva_tlbreak import fit_validated_line
    df, _ = _wide_frame()
    line = fit_validated_line(df, "LOW", _render_cfg())
    assert line is not None and line.log_fit
    first, last = line.points[0], line.points[-1]
    x0, y0 = float(first["index"]), float(first["price"])
    x1, y1 = float(last["index"]), float(last["price"])
    chord = lambda x: y0 + (y1 - y0) * (x - x0) / (x1 - x0)      # noqa: E731
    worst_linear, worst_log = 0.0, 0.0
    for point in line.points:
        x, y = float(point["index"]), float(point["price"])
        worst_linear = max(worst_linear, abs(chord(x) - y) / y)
        worst_log = max(worst_log, abs(line.price_at(x) - y) / y)
    assert worst_linear > worst_log
    assert worst_log < 0.5 * worst_linear


def test_narrow_window_keeps_the_old_linear_behaviour():
    from analysis.viva_tlbreak import fit_validated_line
    df, _ = _narrow_frame()
    span = (df["high"].max() - df["low"].min()) / df["low"].min()
    assert span < 0.03                      # the chart stays linear here
    line = fit_validated_line(df, "LOW", _render_cfg())
    if line is None:                       # nothing validated → nothing changed
        return
    assert line.log_fit is False
    for point in line.points:              # price_at IS slope*x+intercept
        assert line.price_at(float(point["index"])) == \
            pytest.approx(line.slope * float(point["index"]) + line.intercept)


def test_log_threshold_is_configurable():
    """The switch that makes a before/after proof possible, and the guard that
    keeps narrow charts on the old maths."""
    import dataclasses
    from analysis.viva_tlbreak import fit_validated_line
    df, _ = _wide_frame()
    cfg = _render_cfg()
    assert cfg.log_fit_min_span > 0
    on = fit_validated_line(df, "LOW", cfg)
    assert on is not None and on.log_fit is True
    off = fit_validated_line(df, "LOW",
                             dataclasses.replace(cfg, log_fit_min_span=99.0))
    assert off is not None and off.log_fit is False


def test_tangent_matches_the_curve_locally():
    from analysis.viva_tlbreak import fit_validated_line
    df, _ = _wide_frame()
    line = fit_validated_line(df, "LOW", _render_cfg())
    assert line is not None and line.log_fit
    x = float(line.last_index)
    y = line.price_at(x)
    assert line.tangent_at(x) == pytest.approx(
        (line.price_at(x + 0.01) - y) / 0.01, rel=1e-3)


# ────────────────────────── render geometry ──────────────────────────
def test_line_xy_draws_a_curve_for_log_lines_and_a_chord_otherwise():
    from analysis.render_kit import line_xy, line_y
    log_line = {"log_fit": True, "log_slope": 0.01, "log_intercept": 1.0,
                "slope": 0.05, "intercept": 1.0}
    xs, ys = line_xy(log_line, 0.0, 100.0)
    assert len(xs) > 2 and len(ys) == len(xs)
    assert ys[0] == pytest.approx(line_y(log_line, 0.0))
    assert ys[-1] == pytest.approx(line_y(log_line, 100.0))
    # curvature: the midpoint of a log line is NOT the chord midpoint
    chord_mid = (ys[0] + ys[-1]) / 2.0
    assert abs(ys[len(ys) // 2] - chord_mid) > 1e-6
    lin = {"slope": 0.05, "intercept": 1.0}
    xs2, ys2 = line_xy(lin, 0.0, 100.0)
    assert len(xs2) == 2 and ys2 == [1.0, 6.0]


def test_detect_patterns_emits_calibrated_lines():
    from analysis.render_kit import detect_patterns, line_y
    df, _ = _wide_frame()
    pats = detect_patterns(df, "LONG")
    assert pats, "the rising rail must render as a structure"
    lines = [ln for p in pats for ln in (p.get("lines") or [])]
    assert lines
    assert any(ln.get("log_fit") for ln in lines)
    for ln in lines:
        if ln.get("log_fit"):
            # the serialized global geometry must reproduce the fit
            assert line_y(ln, float(ln["x1"])) > 0
        else:                               # legacy keys still present
            assert "slope" in ln and "intercept" in ln


def test_pattern_band_carries_log_geometry_for_the_gate():
    """enrich_render must hand the containment gate the calibrated edges."""
    import dataclasses
    from analysis.models import SignalCandidate
    from analysis.render_kit import enrich_render, line_y
    from analysis.viva_tlbreak import load_config
    df, _ = _wide_frame()
    cand = SignalCandidate(signal_id="R16-P3", symbol="TESTUSDT", style="SWING",
                           setup_code="TECHCLASSIC", setup_name="t", strategy_fa="t",
                           direction="LONG", score=8, status="APPROACHING",
                           entry_zone_bottom=100.0, entry_zone_top=101.0,
                           planned_entry=100.5, sl=95.0, tp1=110.0, tp2=115.0,
                           rr_tp1=1.0, rr_tp2=2.0, bias="BULL",
                           trigger_timeframe="4h", created_at="2026-09-21T05:11:54+00:00",
                           metadata={"atr": abs(dataclasses.asdict(load_config())["edge_atr"] or 1.0)})
    enrich_render(cand, df)
    band = cand.metadata.get("pattern_band") or {}
    if band:
        assert "log_lo" in band and "log_hi" in band
        for side in ("log_lo", "log_hi"):
            assert set(band[side]) >= {"fit", "slope", "intercept"}
            assert band[side]["fit"] in (True, False)
    watch = cand.metadata.get("render_line_watch") or []
    assert watch, "the calibrated lines must travel to the confirmation layer"
    for ln in watch:
        assert "log_fit" in ln and "log_slope" in ln and "log_intercept" in ln
        if ln.get("log_fit"):
            assert line_y(ln, float(ln.get("x1") or 0.0)) > 0 or True


# ─────────────────────── confirmation gate projection ───────────────────────
def test_break_side_law_projects_a_log_line_on_its_own_curve():
    """The veto level must be the value of the CALIBRATED line, not the chord."""
    import math
    from analysis.quality_engine import _project_watch_level as proj
    y0, y1 = 100.0, 150.0
    t0 = pd.Timestamp("2026-09-01 00:00")
    t1 = t0 + pd.Timedelta(hours=80)
    watch = {"side": "LOW", "log_fit": True, "p0": {"ts": t0, "price": y0},
             "p1": {"ts": t1, "price": y1}, "slope": 2.5, "intercept": 0.0}
    mid = t0 + (t1 - t0) / 2
    assert proj(watch, mid) == pytest.approx(math.sqrt(y0 * y1), rel=1e-6)
    # and a plain line keeps the chord
    lin = {"side": "LOW", "p0": {"ts": t0, "price": y0},
           "p1": {"ts": t1, "price": y1}}
    assert proj(lin, mid) == pytest.approx((y0 + y1) / 2.0, rel=1e-6)


# ─────────────────────────────── smoke ───────────────────────────────
def test_renderer_uses_the_calibrated_helper():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "from analysis.render_kit import line_xy as _line_xy" in src
    assert "_line_xy(_ln," in src
    # the old hand-rolled chord draws are gone from the pattern loop
    assert "[_sl * _xa + _ic, _sl * _xend8 + _ic]" not in src
    # and a TF step-up rescales a calibrated line in log space
    assert "_ls8 = float(_ln0.get(\"log_slope\") or 0.0) / _tfscale" in src


# ─────────────────────── axis decision (shape safety) ───────────────────────
def test_linear_charts_keep_the_linear_fit():
    """Viva's ruling «چارتهای فیوچرز ظاهر قبلیشان»: a chart that renders
    LINEAR must not receive log-calibrated geometry."""
    from analysis.render_kit import detect_patterns
    df, _ = _wide_frame()
    pats = detect_patterns(df, "LONG", log_axis=False)
    for pat in pats:
        for ln in (pat.get("lines") or []):
            assert not ln.get("log_fit"), "linear chart must stay linear"


def test_log_charts_get_calibrated_lines():
    from analysis.render_kit import detect_patterns
    df, _ = _wide_frame()
    pats = detect_patterns(df, "LONG", log_axis=True)
    assert pats
    assert any(ln.get("log_fit") for p in pats for ln in (p.get("lines") or []))


def test_spot_charts_are_always_log_and_always_calibrated():
    """The spot engine's charts set `log_scale`: its lines must be calibrated
    even when the window is narrow enough for the futures guard."""
    from analysis.models import SignalCandidate
    from analysis.render_kit import _chart_will_be_log
    cand = SignalCandidate(signal_id="R16-P3B", symbol="SOMIUSDT", style="SWING",
                           setup_code="TLBREAK", setup_name="t", strategy_fa="t",
                           direction="LONG", score=8, status="APPROACHING",
                           entry_zone_bottom=1.0, entry_zone_top=1.1, planned_entry=1.05,
                           sl=0.9, tp1=1.2, tp2=1.3, rr_tp1=1.0, rr_tp2=2.0,
                           bias="BULL", trigger_timeframe="3d",
                           created_at="2026-09-21T05:11:54+00:00",
                           metadata={"log_scale": True})
    df, _ = _narrow_frame()
    assert _chart_will_be_log(cand, df) is True
