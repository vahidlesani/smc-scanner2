"""R99p — the morning-after repair (Viva 10-15, #18 fallout)."""
import math
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.albrox import (albrox_select_patterns, albrox_pattern_distance_atr,
                             albrox_candles_for, albrox_zoom_window)
from analysis.techclassic import tc_candles_for, tc_validate_pattern
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
    # v2 floor: real wedges stand on >=3 pivots (R99q walk)
    _pats = [_pat("WEDGE_FALLING", [_line(104, 199, 2, 0.01, 1.0),
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
    assert albrox_candles_for("4h", 44) == 144
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
    # R99q update (his 10-15 order): red box on SPOT breakdowns too
    assert "قرمز بذار" in _rs and '("#F2B8B0", "#C0392B", "#8E2418")' in _rs
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


def test_r99q_albrox_v2_frame_is_tight_and_capped():
    """R99q9 — his corrected law: FLOOR 80 candles, ceiling adaptive by TF,
    pattern family and trendline (his XRP 90-110 / WLD 120-140 / HYPE «۴۰ تا
    ۵۰ کندل بیشتر تا زوم بهتر بشه»). My earlier 11-12 candle read was wrong
    and is explicitly reverted here."""
    assert albrox_candles_for("4h", 44) == 144     # HYPE 4H: span+pad
    assert albrox_candles_for("4h", 200) == 200    # ceiling, adaptive
    assert albrox_candles_for("15m", 200) == 160   # 15m ceiling
    assert albrox_candles_for("15m", 30) == 90
    assert albrox_candles_for("15m", 8) == 80    # القانون: کف ۸۰
    assert albrox_candles_for("1d", 200) == 240


def test_r99q_tc_v2_frame_and_noise_wedge():
    """TC v2: same tight-frame law + a 2-line 'shape' on <3 pivots is noise."""
    assert tc_candles_for("15m", 50) == 105
    assert tc_candles_for("15m", 200) == 150
    assert tc_candles_for("1d", 28) == 143
    _noise = {"type": "WEDGE_FALLING", "lines": [
        {"x0": 150, "x1": 194, "points": [{"x": 150}], "slope": .001, "intercept": 1.},
        {"x0": 152, "x1": 194, "points": [{"x": 152}], "slope": .001, "intercept": 1.}]}
    assert tc_validate_pattern(_noise, "WEDGE", 194, "15m")[1] == "under-touched"
    _real = {"type": "WEDGE_FALLING", "lines": [
        {"x0": 150, "x1": 194, "points": [{"x": 150}, {"x": 170}],
         "slope": .001, "intercept": 1.},
        {"x0": 152, "x1": 194, "points": [{"x": 152}, {"x": 176}],
         "slope": .001, "intercept": 1.}]}
    assert tc_validate_pattern(_real, "WEDGE", 194, "15m")[0] is True


def test_r99q_spot_red_breakdown_box_and_brand_center():
    """His 10-15 update: break boxes on SPOT are RED on breakdowns (the older
    green up-box ref is superseded), and the centre watermark is the BRAND
    «VIVA SIGNALS PRO» — never the symbol name."""
    import os as _os
    _src = open(_os.path.join(_os.path.dirname(_os.path.dirname(
        _os.path.abspath(__file__))), "tools", "render_spot_cryptocove.py"),
        encoding="utf-8").read()
    assert "قرمز بذار" in _src and "#F2B8B0" in _src
    assert '("#F2B8B0", "#C0392B", "#8E2418")' in _src and "if up_dir" in _src
    assert 'f"{sym},{tf}"' not in _src          # symbol watermark removed
    assert '"VIVA SIGNALS PRO"' in _src and "0.52" in _src


def test_r99q_albrox_under_touched_noise_wedge_dropped():
    """ALBROX's own honesty floor (his ETC/TAO 15m «پترن غلطه»): a two-line
    shape standing on fewer than three pivots is noise; a real wedge survives."""
    _noise = {"type": "WEDGE_FALLING", "lines": [
        {"x0": 150, "x1": 199, "points": [{"x": 150}], "slope": .001, "intercept": 1.},
        {"x0": 152, "x1": 199, "points": [{"x": 152}], "slope": .002, "intercept": 1.}]}
    _real = {"type": "WEDGE_FALLING", "lines": [
        {"x0": 150, "x1": 199, "points": [{"x": 150}, {"x": 170}],
         "slope": .001, "intercept": 1.},
        {"x0": 152, "x1": 199, "points": [{"x": 152}], "slope": .002, "intercept": 1.}]}
    _kept = albrox_select_patterns([_noise], 199)
    assert _kept == []
    _kept2 = albrox_select_patterns([_real], 199)
    assert [str(p.get("type")) for p in _kept2] == ["WEDGE_FALLING"]


# ── R99q7: weekly setup licence (his 10-15 «قانون موقت جدید») ──────────
def test_r99q7_trigger_grid_and_bias_rule():
    """Five trigger frames everywhere; the daily is bias-only in futures and
    a legal trigger in spot (his «روزانه هم در اسپات داریم ... فقط بایاس»)."""
    from analysis import tiered_scan as _ts
    assert _ts.trigger_tfs("futures") == ("15m", "30m", "1h", "2h", "4h")
    assert _ts.trigger_tfs("spot") == ("15m", "30m", "1h", "2h", "4h", "1d")
    assert "1d" not in _ts.trigger_tfs("futures")
    assert _ts.LICENCE_TF_COUNT == 5


def test_r99q7_weekly_cap_env_and_symbols():
    """His tunable: env wins; default = 5 × scanned symbols (40 → 200)."""
    import os as _os
    from analysis import tiered_scan as _ts
    _keep = {k: _os.environ.get(k) for k in
             ("VIVA_SETUP_WEEKLY_LICENCE", "VIVA_WEEKLY_LICENCE_PINVAL",
              "VIVA_LICENCE_SYMBOLS")}
    try:
        for _k in _keep:
            _os.environ.pop(_k, None)
        _os.environ["VIVA_LICENCE_SYMBOLS"] = "40"
        assert _ts.weekly_licence_cap("PINVAL") == 200     # his worked example
        _os.environ["VIVA_LICENCE_SYMBOLS"] = "54"
        assert _ts.weekly_licence_cap("PINVAL") == 270
        _os.environ["VIVA_SETUP_WEEKLY_LICENCE"] = "120"
        assert _ts.weekly_licence_cap("PINVAL") == 120     # global env wins
        _os.environ["VIVA_WEEKLY_LICENCE_PINVAL"] = "45"
        assert _ts.weekly_licence_cap("PINVAL") == 45      # per-setup env wins
        assert _ts.weekly_licence_cap("ALBROX") == 120
    finally:
        for _k, _v in _keep.items():
            if _v is None:
                _os.environ.pop(_k, None)
            else:
                _os.environ[_k] = _v


def test_r99q7_week_wallet_spends_and_resets():
    """One wallet per setup per ISO week: spend, block at the cap, and the
    NEXT week starts full again (his «ابتدای هر هفته آپدیت بشه»)."""
    from analysis import tiered_scan as _ts
    _wk = "1999-W07"          # an old week so the real wallet is untouched
    _wk2 = "1999-W08"
    _roll = uuid.uuid4().hex[:6]          # idempotent across reruns
    _setup = f"PROBE{_roll}"
    assert _ts.weekly_count(_wk, _setup) == 0
    assert _ts.weekly_licence_ok(_setup, _wk) is True
    for _ in range(3):
        assert _ts.weekly_licence_incr(_setup, _wk) == _ + 1
    assert _ts.weekly_count(_wk, _setup) == 3
    _cap = _ts.weekly_licence_cap(_setup)
    _ts.weekly_licence_incr(_setup, _wk, n=_cap)
    assert _ts.weekly_count(_wk, _setup) == 3 + _cap
    assert _ts.weekly_licence_ok(_setup, _wk) is False           # wallet empty
    assert _ts.weekly_licence_ok(_setup, _wk2) is True           # new week full
    _snap = _ts.weekly_licence_snapshot([_setup], _wk)
    assert _snap[_setup]["used"] == 3 + _cap and _snap[_setup]["left"] == 0


def test_r99q7_gates_are_wired_in_main():
    """Both publish lanes consult the wallet, and the futures lane refuses a
    1d trigger (bias-only law)."""
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mn = open(os.path.join(_root, "main.py"), encoding="utf-8").read()
    assert _mn.count("weekly_licence_ok(") == 2          # futures + spot
    assert _mn.count("weekly_licence_incr(") == 2
    assert "not in _tier99j.SETUP_TRIGGER_TFS" in _mn   # bias-only refusal
    assert '"licence": _lic99' in _mn                   # DB-readable wallet


def test_r99q7_all_four_engines_own_their_frame():
    """TLBREAK and PINVAL keep their OWN zoom numbers (his per-engine law),
    and the chart-window selector consults all four setups."""
    from analysis.tlbreak import tlbreak_candles_for
    from analysis.pinval import pinval_candles_for
    assert tlbreak_candles_for("15m", 200) == 170     # ceiling, wide frame
    assert tlbreak_candles_for("4h", 40) == 205
    assert tlbreak_candles_for("4h", 400) == 205      # own cap
    assert tlbreak_candles_for("1d", 150) == 245      # own 1d cap
    assert pinval_candles_for("15m", 200) == 160      # pin level + taps
    assert pinval_candles_for("2h", 40) == 130
    assert pinval_candles_for("2h", 400) == 185       # own cap
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mv = open(os.path.join(_root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert '"TECHCLASSIC", "ALBROX", "TLBREAK", "PINVAL"' in _mv
    assert "tlbreak_candles_for" in _mv and "pinval_candles_for" in _mv


# ── R99q9: candle-count law v2 (his correction) + PINVAL-only ──────────
def test_r99q9_candle_law_floor_and_adaptive_ceiling():
    """His verbatim correction: «کف تعداد کندل‌ها ۸۰ کندل هست و سقفش با توجه
    شکل و نوع پترن، تایم‌فریم و ترندلاین» + «۴۰ تا ۵۰ کندل بیشتر تا زوم بهتر
    بشه». My earlier 11-12 candle reading was a misread of his zeros."""
    from analysis.techclassic import tc_candles_for
    from analysis.tlbreak import tlbreak_candles_for
    from analysis.pinval import pinval_candles_for
    # floor everywhere
    assert albrox_candles_for("15m", 0) == 80
    assert tc_candles_for("15m", 0) == 80
    assert pinval_candles_for("15m", 0) == 80
    # adaptive ceiling per TF
    assert albrox_candles_for("15m", 400) == 160
    assert albrox_candles_for("4h", 400) == 200
    assert albrox_candles_for("1d", 400) == 240
    assert tc_candles_for("1d", 400) == 230
    # a trendline/channel earns a fuller frame (his ceiling factor)
    assert albrox_candles_for("4h", 44) == 144
    assert albrox_candles_for("4h", 44, "CHANNEL_DESCENDING") == 200
    assert pinval_candles_for("2h", 40) == 130
    assert pinval_candles_for("2h", 40, "TRENDLINE") == 185
    # TLBREAK shows the line AND the break leg → its own wider pad
    assert tlbreak_candles_for("15m", 40) == 170
    # his tunable floor
    import os as _os
    _keep = _os.environ.get("VIVA_CANDLE_MIN")
    try:
        _os.environ["VIVA_CANDLE_MIN"] = "40"
        assert albrox_candles_for("15m", 0) == 60   # floor lowered → pad wins
    finally:
        if _keep is None:
            _os.environ.pop("VIVA_CANDLE_MIN", None)
        else:
            _os.environ["VIVA_CANDLE_MIN"] = _keep


def test_r99q9_pinval_only_switch():
    """His correction: of the TWO pins only the LEGACY one is on
    (PINVAL = PINWALL LEGACY lane); the OTHER setups stay ON — I never had
    permission to switch ALBROX/TECHCLASSIC/TLBREAK off."""
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _p = os.path.join(os.path.dirname(_root), "RAILWAY_VALUES_PASTE.txt")
    if not os.path.exists(_p):
        return                      # file lives outside the repo copy
    _txt = open(_p, encoding="utf-8").read()
    assert "PINVAL_ENABLED=true" in _txt                 # legacy pin ON
    assert "PINWALL_QUALITY_ENABLED=false" in _txt       # the other pin OFF
    for _on in ("ALBROX_ENABLED=true", "TECHCLASSIC_ENABLED=true",
                "VIVA_TLBREAK_ENABLED=true"):
        assert _on in _txt, _on
    assert "WEBAPP_ENABLED" not in _txt                  # not my call to set
    # and the Q lane really is inert in code (nothing to publish)
    from analysis import setups_experimental as _se
    assert _se.PINWALL_QUALITY_DETECTORS == []
    assert "detect_pinbar_zone" in [
        getattr(_d, "__name__", "") for _d in _se.PINVAL_DETECTORS]


def test_r99q9_pivots_survive_the_indexed_render_frame():
    """Real bug found on the live BNB pin chart: the render contract indexes
    frames BY timestamp (the column is dropped), and the both-edges guarantee
    called pivots() on that frame → KeyError 'timestamp' → every missing edge
    silently failed (PINVAL BNB drew one line, the rejection tag hung in
    space). Pivots must work on a column-less, DatetimeIndexed frame."""
    import pandas as _pd
    import numpy as _np
    from analysis.indicators import pivots
    _n = 60
    _ts = _pd.date_range("2026-10-01", periods=_n, freq="15min")
    _base = 700 + 20 * _np.sin(_np.linspace(0, 6, _n))
    _df = _pd.DataFrame({"open": _base, "high": _base + 1.5, "low": _base - 1.5,
                         "close": _base + 0.2})
    _idx = _df.copy()
    _idx.index = _pd.DatetimeIndex(_ts)
    _h1, _l1 = pivots(_df.assign(timestamp=_ts), 2, 2)
    _h2, _l2 = pivots(_idx, 2, 2)          # the render frame shape
    assert len(_h1) == len(_h2) and len(_h1) > 0
    assert _h2[0]["timestamp"] is not None
    assert str(_h2[0]["timestamp"]) == str(_ts[_h2[0]["index"]])


def test_r99q9_spot_is_its_own_lane():
    """His answer «اسپات جداست»: the spot lane is independent of the setup
    switches — the switch block touches futures setups only."""
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _p = os.path.join(os.path.dirname(_root), "RAILWAY_VALUES_PASTE.txt")
    if not os.path.exists(_p):
        return
    _txt = open(_p, encoding="utf-8").read()
    assert "SPOT_ENGINE_ENABLED" not in _txt and "SPOT_ENABLED" not in _txt
    assert "TIER_SPOT_DEEP_MINUTES" in _txt          # spot keeps its own cadence


def test_r99q9_both_edges_lines_speak_the_render_contract():
    """The both-edges guarantee must hand the painter {"ts","price"} points
    (a raw pivot dict has no "ts" → the painter raised DateParseError 'None'
    and the whole chart died — the webapp demo's 404)."""
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mv = open(os.path.join(_root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "_as_render_line" in _mv
    assert '_d["points"] = _pts' in _mv
    # the painter itself must never trust a stamp blindly
    assert 'q.get("ts") or q.get("timestamp")' in _mv
    _ind = open(os.path.join(_root, "analysis", "indicators.py"), encoding="utf-8").read()
    assert "def _ts_at(" in _ind and "_ts_at(df, i)" in _ind


def test_r99q12_spot_zoom_floor_125():
    """His 10-15 ruling on the FIL 8h spot chart: «تعداد کندل ۵۰ تا است ..
    کمه .. باید از ۱۲۵ باشه به بالا بر اساس پترن .. زیر ۱۰۰ خیلی»."""
    from tools.render_spot_cryptocove import spot_window_count, SPOT_WINDOW_CAP
    # a small pattern must still get the 125-candle floor
    assert spot_window_count("8h", 240, 300) == 125
    assert spot_window_count("4h", 200, 300) == 125
    assert spot_window_count("1d", 295, 300) == 125
    # a bigger pattern earns a wider frame, up to its own cap
    assert spot_window_count("8h", 150, 300) == 171
    assert spot_window_count("8h", 60, 300) == SPOT_WINDOW_CAP["8h"]
    # the hard floor can never be configured below 100
    import os as _os
    _keep = _os.environ.get("VIVA_SPOT_CANDLE_MIN")
    try:
        _os.environ["VIVA_SPOT_CANDLE_MIN"] = "40"
        assert spot_window_count("8h", 295, 300) == 100   # the absolute hard floor
    finally:
        if _keep is None:
            _os.environ.pop("VIVA_SPOT_CANDLE_MIN", None)
        else:
            _os.environ["VIVA_SPOT_CANDLE_MIN"] = _keep
    # the spot renderer really uses it (no more 120-bar narrow frame)
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _rs = open(os.path.join(_root, "tools", "render_spot_cryptocove.py"),
               encoding="utf-8").read()
    assert "spot_window_count" in _rs and "VIVA_SPOT_CANDLE_MIN" in _rs
    assert "MAX_BARS = 240" in _rs
