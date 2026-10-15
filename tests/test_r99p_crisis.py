"""R99p — the morning-after repair (Viva 10-15, #18 fallout)."""
import math
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
def test_direction_lane_intact():
    """R99q keeps the R99p direction lane where it now matters: the live-chain
    seats of the absorb/concurrency gate are per direction (a stale LONG chain
    can never block fresh SHORTs), and the 24h counter keeps its lane SQL."""
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _cs = open(os.path.join(_root, "database", "candidate_store.py"),
               encoding="utf-8").read()
    assert "OR direction=?" in _cs
    _mp = open(os.path.join(_root, "main.py"), encoding="utf-8").read()
    assert 'str(c.direction).upper() == str(candidate.direction).upper()' in _mp
    assert "len(live_chains) >= _concmax" in _mp


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


# ── R99q: no perp violation alerts at all ──────────────────────────────
def test_r99q_perp_violation_alerts_retired():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _pe = open(os.path.join(_root, "analysis", "pattern_engine.py"),
               encoding="utf-8").read()
    assert '"warn_only": True' not in _pe          # never emitted on the perp path
    assert "send_pattern_violation" not in _pe      # and never sent from it


def test_r99q_licence_is_concurrency_not_quota():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mp = open(os.path.join(_root, "main.py"), encoding="utf-8").read()
    assert "len(live_chains) >= _concmax" in _mp    # seats, not a 24h quota
    assert "used >= max(1, int(getattr(SETTINGS" not in _mp


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


# ── R99q: spot single render path (his «این نشد اون… نداریم») ──────────
def test_r99q_spot_single_render_path():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mv = open(os.path.join(_root, "bot", "messages_v7.py"),
               encoding="utf-8").read()
    _seg = _mv[_mv.find("if _is_spot:"):]
    _seg = _seg[:_seg.find("# Always initialize chart-only price-axis tags")]
    assert "tools.render_spot_cryptocove import render" in _seg
    assert "render_cryptocove_spot_chart" not in _seg   # old renderer off-path
    assert "return b\"\"" in _seg                       # no chart → text-only


def test_r99q_spot_renderer_design_guards():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _rs = open(os.path.join(_root, "tools", "render_spot_cryptocove.py"),
               encoding="utf-8").read()
    assert 'ax.scatter(_tix' in _rs          # data-space Circle bug never returns
    assert "Circle((ti" not in _rs
    assert "1.5 * d_span" in _rs            # GEO: a far box never squashes candles
    assert "PAD_RIGHT_BARS" in _rs and "MAX_BARS" in _rs  # tight refs zoom
    assert "and up_dir" in _rs              # box only for upward break (refs law)
    assert "SPOTBREAK" in _rs and "BINANCE SPOT" in _rs


def test_r99q_spot_major_pivot_window():
    """His «به پیوت ماژور داخل اون تایم‌فریم احترام بذار» — the spot analyzer
    window is bounded per TF, and the best-pattern score rewards the pattern
    whose BOTH edges live to the live end (the 6-week half-dead road dies)."""
    from analysis import engine_spot as es
    assert es.SPOT_LOOKBACK["4h"] == 150
    assert max(es.SPOT_LOOKBACK.values()) < 300
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _vg = open(os.path.join(_root, "analysis", "viva_geometry.py"),
               encoding="utf-8").read()
    assert "_weak >= x0 + 0.75 * _span9" in _vg      # both-edges liveness rank
    assert "_fresh = 2.5" in _vg
    assert "_leg_local" in _vg                      # latent flag_stats crash fixed


def test_r99q_drying_gate_removed():
    """His order verbatim: «گفتم گیت خشک‌کننده سیگنال‌های ستاپ‌ها رو بردارررر»."""
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mp = open(os.path.join(_root, "main.py"), encoding="utf-8").read()
    assert "not _tier99j.daily_budget_ok()" not in _mp
    assert "not _tier99.daily_budget_ok()" not in _mp
    _ts = open(os.path.join(_root, "analysis", "tiered_scan.py"),
               encoding="utf-8").read()
    assert "RETIRED (R99q" in _ts


# ── R99q: spot shape naming + channel priority (his «پترن غلط») ─────────
def test_r99q_spot_shape_name_from_geometry():
    from analysis.engine_spot import _shape_name

    class _L:
        def __init__(self, s, i):
            self.slope, self.intercept = s, i

        def price_at(self, x):
            return math.exp(self.slope * x + self.intercept)

    class _R:
        def __init__(self, u, lo, x0, x1):
            self.upper, self.lower, self.x0, self.x1, self.slug = u, lo, x0, x1, "CHANNEL_DESCENDING_BROAD"

    # converging downward (the ENA hand-drawn shape) → wedge, not «broad»
    conv = _shape_name(_R(_L(-0.0021, -0.60), _L(-0.0012, -1.15), 321, 419))
    assert conv == "WEDGE_FALLING"
    # parallel downward → plain channel
    par = _shape_name(_R(_L(-0.0021, -0.60), _L(-0.0021, -1.00), 321, 419))
    assert par == "CHANNEL_DESCENDING"
    # diverging downward → the broad label is honest
    div = _shape_name(_R(_L(-0.0005, -0.70), _L(-0.0021, -0.60), 321, 419))
    assert div == "CHANNEL_DESCENDING_BROAD"


def test_r99q_spot_prefers_real_channel():
    import inspect
    from analysis import engine_spot as es
    src = inspect.getsource(es.best_pattern)
    assert "_up * _lo > 0" in src and ">= top.score - 4.0" in src
    assert "name_slug" in inspect.getsource(es.analyze)
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _rs = open(os.path.join(_root, "tools", "render_spot_cryptocove.py"),
               encoding="utf-8").read()
    assert 'a.get("name_slug") or a.get("slug")' in _rs


# ── R99q: axis density law + signature (his 10-15 dictation) ────────────
def test_r99q_price_axis_is_dense_and_precise():
    from analysis.viva_geometry import nice_price_ticks
    _t, _d = nice_price_ticks(96.5, 126.0)
    assert len(_t) >= 10 and _d == 0                 # SOL: whole dollars
    _t, _d = nice_price_ticks(0.123, 0.300)
    assert len(_t) >= 12 and _d == 2                 # ENA: cents
    _t, _d = nice_price_ticks(55_638, 104_137)
    assert len(_t) >= 8 and _d == 0                  # BTC: no decimals
    _t, _d = nice_price_ticks(0.064, 0.098)
    assert len(_t) >= 10 and _d == 3                 # DOGE: 3 decimals


def test_r99q_signature_and_watermark_wired():
    import os as _os
    _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _mv = open(_os.path.join(_root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert '"by: Vahid Lesani"' in _mv               # his «بنوس by :»
    assert "alpha=0.17" in _mv                       # logo watermark stronger
    _rs = open(_os.path.join(_root, "tools", "render_spot_cryptocove.py"),
               encoding="utf-8").read()
    assert '"by: Vahid Lesani"' in _rs
    assert "VIVA SIGNALS PRO\" , transform=ax.transAxes" not in _rs
    assert "nice_price_ticks" in _rs                 # shared dense axis kit
