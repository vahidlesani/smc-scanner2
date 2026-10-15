"""R99p — the morning-after repair (Viva 10-15, #18 fallout)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.albrox import (albrox_select_patterns, albrox_pattern_distance_atr,
                             albrox_candles_for, albrox_zoom_window)
from database.candidate_store import _cluster_dupe_rows


def _line(x0, x1, npts, slope, icept):
    return {"x0": x0, "x1": x1, "slope": slope, "intercept": icept,
            "points": [{"x": x0 + i} for i in range(npts)]}


def _pat(ptype, lines):
    return {"type": ptype, "lines": lines}


# ── LTC 4H replay: far ancient vs near young ───────────────────────────
def _ltc_set():
    _live, _px, _atr = 269, 57.68, 1.5
    _ancient = _pat("WEDGE_FALLING", [  # 6 touches, ~2.1 ATR away
        _line(5, 269, 3, 0.001, 54.5 - 0.001 * 269),
        _line(12, 269, 3, 0.0008, 53.0 - 0.0008 * 269)])
    _young = _pat("WEDGE_FALLING", [  # 4 touches, ~0.5 ATR away
        _line(225, 269, 2, -0.02, 58.5 + 0.02 * 269),
        _line(230, 269, 2, -0.015, 57.9 + 0.015 * 269)])
    _far_single = _pat("TRENDLINE", [_line(200, 269, 2, 0.0, 50.0)])
    return _live, _px, _atr, [_ancient, _young, dict(_young), _far_single]


def test_ltc_young_leads_ancient_faint_second():
    _live, _px, _atr, _pats = _ltc_set()
    _kept = albrox_select_patterns(_pats, _live, _px, _atr)
    assert len(_kept) == 2
    assert _kept[0]["lines"][0]["x0"] == 225  # young leads (nearest)
    assert _kept[1]["lines"][0]["x0"] == 5  # ancient survives faint #2


def test_far_single_dropped():
    _live, _px, _atr, _pats = _ltc_set()
    _kept = albrox_select_patterns(_pats, _live, _px, _atr)
    assert all(str(p.get("type")) != "TRENDLINE" for p in _kept)


def test_distance_pure():
    _band = {"type": "RANGE", "hi": 60.0, "lo": 58.0}
    assert abs(albrox_pattern_distance_atr(_band, 269, 57.68, 1.5)
               - abs(59.0 - 57.68) / 1.5) < 1e-9
    assert albrox_pattern_distance_atr(_band, 269, None, 1.5) == float("inf")


def test_legacy_touches_rank_without_live():
    _pats = [_pat("WEDGE_FALLING", [_line(104, 199, 1, 0.01, 1.0),
                                   _line(110, 199, 1, 0.01, 1.0)]),
             _pat("TRENDLINE", [_line(97, 199, 6, 0.01, 1.0)])]
    _kept = albrox_select_patterns(_pats, 199)
    assert [str(p.get("type")) for p in _kept] == ["TRENDLINE", "WEDGE_FALLING"]


# ── licence direction lane + dupe hygiene ──────────────────────────────
def test_quota_sql_has_direction():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _cs = open(os.path.join(_root, "database", "candidate_store.py"),
               encoding="utf-8").read()
    assert "OR direction=?" in _cs
    _mp = open(os.path.join(_root, "main.py"), encoding="utf-8").read()
    _i = _mp.find("chains_last_24h(candidate.symbol")
    assert _i > 0 and "direction" in _mp[_i:_i + 300]


def test_cluster_dupe_rows_pure():
    _rows = [
        {"sid": "A", "sym": "X", "setup": "ALBROX", "tf": "4h",
         "direction": "SHORT", "mid": 100.0, "atr": 10.0, "created": "2026-10-15T10:00:00"},
        {"sid": "B", "sym": "X", "setup": "ALBROX", "tf": "4h",
         "direction": "SHORT", "mid": 100.5, "atr": 10.0, "created": "2026-10-15T09:00:00"},
        {"sid": "C", "sym": "X", "setup": "ALBROX", "tf": "4h",
         "direction": "SHORT", "mid": 130.0, "atr": 10.0, "created": "2026-10-15T08:00:00"},
        {"sid": "D", "sym": "X", "setup": "ALBROX", "tf": "4h",
         "direction": "LONG", "mid": 100.2, "atr": 10.0, "created": "2026-10-15T07:00:00"},
        {"sid": "E", "sym": "X", "setup": "ALBROX", "tf": "4h",
         "direction": "SHORT", "mid": "junk", "atr": 10.0, "created": "2026-10-15T06:00:00"},
    ]
    assert _cluster_dupe_rows(_rows) == {"B"}


def test_boot_hygiene_wired():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mp = open(os.path.join(_root, "main.py"), encoding="utf-8").read()
    assert "retire_open_duplicate_chains" in _mp


# ── violation honesty + anchor ─────────────────────────────────────────
def test_violation_text_honest():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _pe = open(os.path.join(_root, "analysis", "pattern_engine.py"),
               encoding="utf-8").read()
    assert "بدون کلوز" in _pe
    assert "بریک و کلوز از ضلع" not in _pe


def test_preview_anchor_gate():
    import time as _t
    import analysis.pattern_engine as _pe
    _saved = _pe._ALERT_SEEN
    try:
        _pe._ALERT_SEEN = {"S|1h|WEDGE_FALLING|EDGE_NEAR|lower": _t.time()}
        assert _pe._preview_anchor_seen("S", "1h", "WEDGE_FALLING", "lower") is True
        assert _pe._preview_anchor_seen("S", "1h", "WEDGE_FALLING", "upper") is False
        assert _pe._preview_anchor_seen("ZZZ", "1h", "WEDGE_FALLING", "lower") is False
    finally:
        _pe._ALERT_SEEN = _saved


# ── pulse + zoom ───────────────────────────────────────────────────────
def test_pulse_shows_hidden():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mp = open(os.path.join(_root, "main.py"), encoding="utf-8").read()
    for _k in ("liccap_by", "tier=", "dead=", "budget=", "addfail=", "edufail="):
        assert _k in _mp, _k


def test_far_faint_paint_key():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mv = open(os.path.join(_root, "bot", "messages_v7.py"),
               encoding="utf-8").read()
    assert _mv.count("far_faint99p") >= 3  # setter + width + alpha


def test_albrox_zoom_pure():
    assert albrox_candles_for("4h", 44) == 84
    assert albrox_zoom_window(270, 84) == (195, 279)


def test_span_follows_lead():
    import copy as _copy
    from types import SimpleNamespace as _NS
    import pandas as _pd
    from analysis.albrox import albrox_refine_geometry as _ref
    _live, _px, _atr, _pats = _ltc_set()
    _df = _pd.DataFrame({"close": [50.0] * 269 + [_px],
                         "high": [50.0] * 269 + [_px + _atr],
                         "low": [50.0] * 269 + [_px - _atr]})
    _md = {"render_patterns": _copy.deepcopy(_pats)}
    _ref(_NS(setup_code="ALBROX", trigger_timeframe="4h", metadata=_md),
         bundle={"4h": _df})
    assert _md["albrox_pattern_span"] == 44  # young lead, not ancient 264
