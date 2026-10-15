"""R99o — TC/ALBROX owned geometry + licence equality (Viva 10-15)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.techclassic import (tc_validate_pattern, tc_refine_geometry,
                                  tc_candles_for, tc_zoom_window)
from analysis.albrox import albrox_select_patterns, albrox_refine_geometry


def _line(x0, x1, npts=2):
    return {"x0": x0, "x1": x1,
            "points": [{"x": x0 + i} for i in range(npts)],
            "slope": 0.001, "intercept": 1.0}


def _pat(ptype, lines):
    return {"type": ptype, "lines": lines}


# ── TC validator: DOGE replay ────────────────────────────────
def test_doge_channel_dropped():
    _ch = _pat("CHANNEL_DESCENDING", [_line(30, 194, 6), _line(45, 194, 4)])
    _keep, _reason, _newt = tc_validate_pattern(_ch, "TRIANGLE", 194, "15m")
    assert _keep is False and _reason in ("ancient-anchor", "label-mismatch")


def test_doge_trendline_kept():
    _tl = _pat("TRENDLINE", [_line(144, 194, 4)])
    _keep, _reason, _newt = tc_validate_pattern(_tl, "TRIANGLE", 194, "15m")
    assert (_keep, _newt) == (True, None), (_keep, _reason)


def test_band_kept_and_noise_dropped():
    assert tc_validate_pattern({"type": "RANGE"}, "TRIANGLE", 194, "15m")[0] is True
    _db = _pat("DOUBLE_BOTTOM", [_line(182, 194, 0)])
    assert tc_validate_pattern(_db, "TRIANGLE", 194, "15m")[0] is False


def test_single_edge_relabelled_not_dropped():
    _one = _pat("WEDGE_FALLING", [_line(150, 194, 3)])
    _keep, _reason, _newt = tc_validate_pattern(_one, "WEDGE", 194, "15m")
    assert (_keep, _newt) == (True, "TRENDLINE")


def test_stale_end_dropped():
    _old = _pat("TRENDLINE", [_line(50, 150, 4)])
    assert tc_validate_pattern(_old, "", 194, "15m")[0] is False


def test_tc_refine_doge_integration():
    _md = {"tl_pattern": "TRIANGLE_DESCENDING", "tl_context_tf": "4h",
           "render_patterns": [
               _pat("CHANNEL_DESCENDING",
                    [_line(30, 194, 6), _line(45, 194, 4)]),
               _pat("TRENDLINE", [_line(144, 194, 4)]),
               {"type": "RANGE"},
               _pat("DOUBLE_BOTTOM", [_line(182, 194, 0)])]}
    _cand = SimpleNamespace(setup_code="TECHCLASSIC", trigger_timeframe="15m",
                            signal_id="t", metadata=_md)
    tc_refine_geometry(_cand, bundle=None)
    _types = [str(p.get("type")) for p in _md["render_patterns"]]
    assert _types == ["TRENDLINE", "RANGE"], _types
    assert _md["tc_pattern_span"] == 50
    assert _md["render_htf_pattern"] == "TRENDLINE"  # pill sync
    assert _md["tl_context_tf"] == "15m" and _md["tc_context_was"] == "4h"
    assert _md["tc_owned"] is True and len(_md["tc_dropped"]) == 2


def test_tc_refine_fail_open():
    _cand = SimpleNamespace(setup_code="TECHCLASSIC", trigger_timeframe="15m",
                            signal_id="t", metadata=None)
    assert tc_refine_geometry(_cand) is _cand
    assert tc_refine_geometry(None) is None


def test_tc_count_zoom_pure():
    assert tc_candles_for("15m", 50) == 90
    _x0, _x1 = tc_zoom_window(194, 90)
    assert (_x0, _x1) == (194 - 1 + 10 - 90, 194 - 1 + 10)  # (113, 203)


# ── ALBROX selection: XLM replay ────────────────────────────
def test_xlm_twins_deduped_best_two_kept():
    _pats = [_pat("WEDGE_FALLING", [_line(104, 199, 1), _line(110, 199, 1)]),
             _pat("TRENDLINE", [_line(97, 199, 6)]),
             _pat("DOUBLE_BOTTOM", [_line(185, 199, 0)]),
             _pat("DOUBLE_BOTTOM", [_line(185, 199, 0)])]
    _kept = albrox_select_patterns(_pats, 199)
    assert [str(p.get("type")) for p in _kept] == ["TRENDLINE", "WEDGE_FALLING"]


def test_albrox_stale_dropped():
    _pats = [_pat("TRENDLINE", [_line(10, 100, 5)]),
             _pat("CHANNEL", [_line(150, 199, 2)])]
    _kept = albrox_select_patterns(_pats, 199)
    assert [str(p.get("type")) for p in _kept] == ["CHANNEL"]


def test_albrox_refine_integration():
    _md = {"render_patterns": [
        _pat("WEDGE_FALLING", [_line(104, 199, 2)]),
        _pat("TRENDLINE", [_line(97, 199, 6)])]}
    _cand = SimpleNamespace(setup_code="ALBROX", trigger_timeframe="30m",
                            signal_id="a", metadata=_md)
    albrox_refine_geometry(_cand, bundle=None)
    assert len(_md["render_patterns"]) == 2
    assert _md["albrox_owned"] is True


# ── law guards ───────────────────────────────────────────────
def test_licence_exemption_removed():
    import main as _main
    assert set(getattr(_main, "_STRUCTURAL_QUALITY_LANES", {"X"})) == set()


def test_consults_present_in_shared():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _qe = open(os.path.join(_root, "analysis", "quality_engine.py"),
               encoding="utf-8").read()
    assert "tc_refine_geometry" in _qe and "albrox_refine_geometry" in _qe
    _mv = open(os.path.join(_root, "bot", "messages_v7.py"),
               encoding="utf-8").read()
    assert "tc_zoom_window" in _mv and "tc_candles_for" in _mv
