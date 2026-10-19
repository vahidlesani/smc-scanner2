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
    # R99q18: still ONE renderer — it now also brings the alert's own title
    # helper, because the geometry drawn is the alert's own (not a 2nd engine).
    assert ("from tools.render_spot_cryptocove import (render as _rs2,\n"
            "                                                      pattern_title as _spt18)" in _seg)
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
    _rs = open(_os.path.join(_root, "tools", "render_spot_cryptocove.py"),
               encoding="utf-8").read()
    # R99q21 (his 10-16 evening): the CENTRE of every chart carries the
    # author's own name instead of the brand, and the top-right credit is the
    # clean logo (the framed banner «شلوغ» was removed).
    # R99q23 (his 10-17): the centre mark reads «VAHID LESANI ANALYSIS», the
    # brand word is gone from both designs, and the top-right corner carries
    # the author's name with the logo BESIDE it.
    assert '"VAHID LESANI ANALYSIS", transform=ax.transAxes' in _mv
    assert '"VAHID LESANI ANALYSIS", transform=ax.transAxes' in _rs
    # R99q28 REVERSAL (his 10-19, verbatim: «سمت راست بالا انتهای چارت لوگو
    # کوچک با کیفیت و مقابلش متن زیر VAHID LESANI - VIVA SIGNALS PRO … این
    # تغییر جای نام و برند در ستاپ هم انجام بشه»). R99q23 had removed the brand
    # word; the newer law puts it back on ONE line, top-right, in both designs.
    # The R99q23 *intent* still holds: no scattered repeats — the centre mark
    # stays the author's name alone and no second brand word lives in the body.
    assert "VAHID LESANI — VIVA SIGNALS PRO" in _mv
    _body = _mv.replace('CHART_BRAND_NAME = os.getenv("CHART_BRAND_NAME", "VIVA SIGNALS PRO").upper()', "")
    assert _body.count("VIVA SIGNALS PRO") == 1, "the brand word must appear exactly once (top-right credit)"
    assert "_add_author_credit(fig)" in _mv
    assert "viva_credit_banner" not in _mv and "viva_credit_banner" not in _rs
    assert "VIVA SIGNALS PRO\" , transform=ax.transAxes" not in _rs
    assert "VIVA SIGNALS PRO\", transform=ax.transAxes" not in _rs
    # «و با همون اندازه» — ONE centre size in spot AND setups (34, bold, since
    # the mark now carries the word ANALYSIS)
    assert 'fontsize=34, fontweight="bold"' in _mv
    assert 'fontsize=34, fontweight="bold"' in _rs
    # spot watermark a touch BOLDER than the setups one (his 10-17)
    assert 'alpha=0.42, zorder=1' in _rs and 'alpha=0.22, zorder=0' in _mv
    assert "vivasignals-logo.png" in _rs
    assert "nice_price_ticks" in _rs                 # shared dense axis kit


def test_r99q_albrox_v2_frame_is_tight_and_capped():
    """R99q9 — his corrected law: FLOOR 80 candles, ceiling adaptive by TF,
    pattern family and trendline (his XRP 90-110 / WLD 120-140 / HYPE «۴۰ تا
    ۵۰ کندل بیشتر تا زوم بهتر بشه»). My earlier 11-12 candle read was wrong
    and is explicitly reverted here."""
    assert albrox_candles_for("4h", 44) == 144     # HYPE 4H: span+pad
    assert albrox_candles_for("4h", 200) == 200    # ceiling, adaptive
    assert albrox_candles_for("15m", 200) == 160   # 15m ceiling
    assert albrox_candles_for("15m", 30) == 120   # R99q14: setup floor is 120 now
    assert albrox_candles_for("15m", 8) == 120   # القانون: کف ۱۲۰ (R99q14)
    assert albrox_candles_for("1d", 200) == 240


def test_r99q_tc_v2_frame_and_noise_wedge():
    """TC v2: same tight-frame law + a 2-line 'shape' on <3 pivots is noise."""
    assert tc_candles_for("15m", 50) == 120   # R99q14: setup floor is 120 now
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
    green up-box ref is superseded). R99q21 (10-16 evening) superseded the
    centre BRAND: «ویوا سیگنالز پرو رو از وسطش بردار» — the centre mark is the
    author's own name now, at the setups chart's size; the brand word stays in
    the header/footer rows only."""
    import os as _os
    _src = open(_os.path.join(_os.path.dirname(_os.path.dirname(
        _os.path.abspath(__file__))), "tools", "render_spot_cryptocove.py"),
        encoding="utf-8").read()
    assert "قرمز بذار" in _src and "#F2B8B0" in _src
    assert '("#F2B8B0", "#C0392B", "#8E2418")' in _src and "if up_dir" in _src
    assert 'f"{sym},{tf}"' not in _src          # symbol watermark removed
    assert '"VAHID LESANI ANALYSIS", transform=ax.transAxes' in _src
    assert 'ax.text(0.5, 0.245, "VAHID LESANI ANALYSIS"' in _src
    assert 'ax.text(0.5, 0.52, "VIVA SIGNALS PRO"' not in _src


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
    assert albrox_candles_for("15m", 0) == 120   # R99q14: setup floor is 120 now
    assert tc_candles_for("15m", 0) == 120   # R99q14: setup floor is 120 now
    assert pinval_candles_for("15m", 0) == 120   # R99q14: setup floor is 120 now
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
    # his tunable floors: R99q14 split them — VIVA_SETUP_CANDLE_MIN (120) owns
    # the PICTURE of a setup, VIVA_CANDLE_MIN stays the raw-detection floor.
    import os as _os
    _keep = _os.environ.get("VIVA_CANDLE_MIN")
    _keep2 = _os.environ.get("VIVA_SETUP_CANDLE_MIN")
    try:
        _os.environ["VIVA_CANDLE_MIN"] = "40"
        assert albrox_candles_for("15m", 0) == 120   # the setup floor holds
        _os.environ["VIVA_SETUP_CANDLE_MIN"] = "70"
        assert albrox_candles_for("15m", 0) == 70    # floor lowered → pad wins
    finally:
        for _k, _v in (("VIVA_CANDLE_MIN", _keep), ("VIVA_SETUP_CANDLE_MIN", _keep2)):
            if _v is None:
                _os.environ.pop(_k, None)
            else:
                _os.environ[_k] = _v


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


# ─────────────────────────────────────────────────────────────────────────────
# R99q13 — CONFIRM-TIMING LAW (Viva 10-15, verbatim: «مگه قرار نبود اولین کلوز
# بعد از شکست تایید بده .. همه ستاپها این مشکل رو دارن .. راه حل مشکل باید پیدا
# بشه و سروقت تایید برسه.. نه اینکه یک خط بنویسی وقتی اینجوری بود وتو بشه و گیت
# ببنده ارسال به تلگرام رو». Live evidence: T698813 UNIUSDT 30m TECHCLASSIC
# identified 15:05Z, first valid close 15:30Z, PUBLISHED 19:05Z (215 min late);
# PINVAL K259097/K151415/K759570 + LINKUSDT 1h (270 min) / XRPUSDT 1h (241 min)
# on the same two rails: ENTRY_AFTER_TARGET on a ladder built from the pre-break
# entry, and the stale-stamp disarm that threw the verdict away.
# ─────────────────────────────────────────────────────────────────────────────
def _confirm_frame(closes, tf_min=15, line=None, start="2026-10-15 12:00"):
    import pandas as pd
    ts = pd.date_range(start, periods=len(closes), freq=f"{tf_min}min")
    line = float(line if line is not None else closes[0] - 1.0)
    rows = []
    for i, c in enumerate(closes):
        rows.append({"timestamp": ts[i], "open": c - 0.05, "high": c + 0.10,
                     "low": c - 0.10, "close": c, "volume": 1000.0})
    df = pd.DataFrame(rows).set_index("timestamp")
    df.index.name = "timestamp"
    df["timestamp"] = df.index
    return df, line


def _confirm_cand(setup, direction="LONG", entry=100.3, tp1=100.9, tp2=104.0,
                  sl=98.0, line=100.5, created="2026-10-15 12:00", extra=None):
    from test_v7 import make_candidate
    cand = make_candidate(status="NEAR_CONFIRM")
    cand.setup_code = setup
    cand.direction = direction
    cand.trigger_timeframe = "30m"
    cand.entry_zone_bottom, cand.entry_zone_top = 100.0, 100.6
    cand.planned_entry, cand.sl, cand.tp1, cand.tp2 = entry, sl, tp1, tp2
    cand.created_at = created
    cand.metadata.update({"atr": 0.60, "confirm_tf": "15m", "touched": True,
                          "viva_break_line": line, "viva_breakout_line": line,
                          "break_edge": "UPPER", "viva_state": "S2_BREAKOUT_CLOSED"})
    if extra:
        cand.metadata.update(extra)
    return cand


def _run(cand, closes, line=None):
    """Pad to >= 20 in-scan bars (the engine's data floor) with a settled
    pre-alert base, so the verify frame is realistic."""
    from analysis.quality_engine import evaluate_confirmation
    pad = [99.9, 100.0, 100.02, 100.04, 99.98] * 6            # 30 pre-break bars
    df, _line = _confirm_frame(pad + list(closes), tf_min=15, start="2026-10-15 04:00",
                               line=(line if line is not None else cand.metadata["viva_break_line"]))
    return evaluate_confirmation(cand, df, frame_tf_minutes=15.0)


def test_r99q13_first_close_after_break_confirms_every_setup():
    """The first valid close beyond the break edge confirms IMMEDIATELY for every
    setup — the pre-break ladder (`tp1` behind that close) may never veto it: the
    entry is re-based on the confirming close, TP1 is rebuilt ahead of it and the
    tool's structural target (tp2) stays. T698813 shape."""
    for setup in ("TECHCLASSIC", "PINVAL", "TLBREAK", "ALBROX"):
        cand = _confirm_cand(setup, tp1=100.9, tp2=104.0, entry=100.3)
        ok, c2, reason = _run(cand, [99.9, 100.0, 100.05, 100.1, 101.6])
        assert ok is True, f"{setup}: {reason}"
        md = c2.metadata or {}
        assert md.get("break_confirm_source") == "ONE_CLOSE_REBASED", setup
        rec = md.get("entry_rebased") or {}
        assert abs(float(rec.get("to")) - 101.6) < 1e-9, setup
        assert abs(c2.planned_entry - 101.6) < 1e-9, setup
        assert c2.tp1 > c2.planned_entry, setup          # the veto can never re-fire
        assert abs(c2.tp2 - 104.0) < 1e-9, setup         # the tool's target is kept
        assert str(md.get("confirm_entry_bar") or "")[:4] == "2026", setup
        assert float(md.get("confirm_entry_tf_min") or 0) == 15.0, setup


def test_r99q13_stale_stamp_never_disarms_a_first_close():
    """UNIUSDT·T698813: `stale_after_bar` + no FTB touch used to leave the chain
    silent for 215 minutes. A chain that never published keeps confirming on the
    first close beyond the edge."""
    for setup in ("TECHCLASSIC", "PINVAL"):
        cand = _confirm_cand(setup, tp1=100.9, tp2=104.0, entry=100.3,
                             extra={"stale_after_bar": "2026-10-15 12:15:00"})
        ok, c2, reason = _run(cand, [99.9, 100.0, 100.05, 100.1, 101.6])
        assert ok is True, f"{setup}: {reason}"


def test_r99q13_ftb_still_guards_a_republished_confirm():
    """The FTB precondition survives for a chain that ALREADY published — its old
    bar may not re-fire without a first-time-back touch."""
    cand = _confirm_cand("TECHCLASSIC", tp1=100.9, tp2=104.0, entry=100.3,
                         extra={"stale_after_bar": "2026-10-15 12:15:00",
                                "confirmation_sent": True})
    ok, c2, reason = _run(cand, [99.9, 100.0, 100.05, 100.1, 101.6])
    assert ok is False, reason


def test_r99q13_rebase_never_moves_a_frozen_plan():
    from analysis.quality_engine import rebase_confirm_entry
    cand = _confirm_cand("TECHCLASSIC", entry=100.3, tp1=100.9, tp2=104.0)
    cand.metadata["confirmed_snapshot"] = {"entry": 100.3, "sl": 98.0}
    assert rebase_confirm_entry(cand, 101.6) is None
    assert abs(cand.planned_entry - 100.3) < 1e-9


def test_r99q13_rebase_refuses_a_broken_ladder():
    """A ladder whose final target sits behind its own entry is a broken tool —
    the rebase refuses and the geometry veto keeps its verdict."""
    from analysis.quality_engine import rebase_confirm_entry
    cand = _confirm_cand("PINVAL", entry=100.3, tp1=99.6, tp2=99.0)
    assert rebase_confirm_entry(cand, 101.6) is None


def test_r99q13_live_price_is_never_the_entry():
    """«قیمت لایو یه چیزه .. ورود یه چیزه .. توی پیام یه چیزه» — the Live Price
    line reads the market (frame close / venue ticker), never the frozen entry
    (ZECUSDT·K259097 printed 1,109.43 while the chart read 1,150.21)."""
    import pandas as pd
    from bot.messages_v7 import _live_price_for_message
    cand = _confirm_cand("PINVAL", entry=1109.43)
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-10-15 12:00", periods=3, freq="5min"),
                          "close": [1140.0, 1145.0, 1150.21]})
    assert abs(_live_price_for_message(cand, frame) - 1150.21) < 1e-9
    # no frame + no venue answer ⇒ 0.0 (the message says «نامعلوم») — never the entry
    assert _live_price_for_message(cand, None) != cand.planned_entry or \
        _live_price_for_message(cand, None) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# R99q14 — PRE-BREAK EARLY-ALERT LAW (Viva 10-15, verbatim: «وقتی که هشدار
# آموزشی و ابتدایی اومده عملا قیمت بریک رو انجام داده بوده و کار از کار گذشته
# بوده؛ باید قبل از اینکه قیمت به اضلاع الگوها و یا در حال بریک پترنها و
# ترندلاینها و نواحی ستاپ برسه اولین هشدار ابتدایی بده .. و بعد از بریک تایید
# بده … دقیقا در اسپات اینرو داریم .. در همه ستاپها یکسانه … فقط بدون هر ستاپ
# جدا جدا جراحی بشه» + «ستاپها هم از ۱۲۰ به بالا باید باشه بر اساس انتخاب پترن
# در زوم درست» + «در ستاپها در همه تایمفریم هاشون ارتفاع کندلها نباید بیشتر ۷۰
# درصد بشه» + the green box «کالیبره روی و زیر اضلاع پترنها و ترندلاینها».
# Live evidence: UNIUSDT·T698813's first message was a FINAL WATCH minted on an
# already-broken edge; the preview lane's flat 8h cooldown (NEAR stamped 11:21,
# break 15:00, next eligible 19:22) is exactly «کار از کار گذشته».
# ─────────────────────────────────────────────────────────────────────────────
def _pb_event(setup="TECHCLASSIC", side="upper", edge=100.5, dist=0.40, tf="1h",
              direction="LONG", **extra):
    ev = {"setup": setup, "setup_name": setup, "symbol": "UNIUSDT", "tf": tf,
          "pattern_tf": tf, "side": side, "direction": direction,
          "pattern": "WEDGE_FALLING", "pattern_fa": "گوه نزولی",
          "edge": edge, "distance_atr": dist, "atr": 0.6,
          "state": "EDGE_NEAR", "score": 7,
          "upper_points": [{"timestamp": "2026-10-15 04:00", "price": 101.4},
                           {"timestamp": "2026-10-15 08:00", "price": 100.9}],
          "lower_points": [{"timestamp": "2026-10-15 05:00", "price": 99.2},
                           {"timestamp": "2026-10-15 09:00", "price": 99.9}],
          "line_geo": {"price": edge, "a": edge, "b": 0.0, "slope": 0.0}}
    ev.update(extra)
    return ev


def test_r99q14_every_setup_answers_through_its_own_engine():
    """ONE law, every setup — but each setup's answer is produced by its OWN
    module (his «فقط بدون هر ستاپ جدا جدا جراحی بشه»)."""
    from analysis import prebreak_lane as pb
    for setup in ("TECHCLASSIC", "ALBROX", "PINVAL", "PINWALLQ", "TLBREAK"):
        assert setup in pb.PROVIDERS, setup
        _mod, _fn = pb.PROVIDERS[setup]
        assert pb.provide(setup) is not None, (setup, _mod, _fn)
        assert _fn in ("techclassic_prebreak", "albrox_prebreak", "pinval_prebreak",
                       "pinwall_prebreak", "tlbreak_prebreak"), setup
    # the lane never speaks for a setup whose switch is off
    assert pb.setup_enabled("TECHCLASSIC") is True


def test_r99q14_alert_speaks_inside_the_pattern_before_the_break():
    """The watch is minted while price is still INSIDE / near the edge: the
    candidate is an EDUCATIONAL S0_WATCH whose line is the very edge the
    confirmation will later judge (one chain: alert → confirm)."""
    from analysis import prebreak_lane as pb
    ev = pb.normalize(_pb_event(edge=100.5, dist=0.40), symbol="UNIUSDT",
                      setup="TECHCLASSIC", tf="1h")
    assert ev is not None
    cand = pb.build_watch_candidate(ev, None)
    md = cand.metadata
    assert cand.status == "EDUCATIONAL"
    assert md["viva_state"] == "S0_WATCH" and md["alert_stage"] == "PREBREAK"
    assert abs(float(md["viva_break_line"]) - 100.5) < 1e-9
    assert abs(float(md["viva_watch_line"]) - 100.5) < 1e-9
    assert abs(cand.planned_entry - 100.5) < 1e-9
    # the box sits ON the edge and extends AWAY from the pattern (R99q14
    # calibration): long → above the upper edge, never straddling the line
    assert abs(cand.entry_zone_bottom - 100.5) < 1e-9
    assert cand.entry_zone_top > 100.5
    _short = pb.build_watch_candidate(
        pb.normalize(_pb_event(side="lower", direction="SHORT", edge=100.5, dist=0.3),
                     symbol="UNIUSDT", setup="PINVAL", tf="1h"), None)
    assert abs(_short.entry_zone_top - 100.5) < 1e-9
    assert _short.entry_zone_bottom < 100.5
    assert md["confirm_tf"] == "15m"                      # one step below the trigger
    # the chart's own geometry rides along (the engine's pivots, never invented)
    assert md["render_patterns"] and md["render_patterns"][0]["lines"], "geometry lost"
    assert md["viva_upper_points"] and md["viva_lower_points"]
    assert "prebreak" in md and md["prebreak_distance_atr"] == 0.40


def test_r99q14_never_speaks_after_the_break():
    """Once the edge is broken the confirm lane owns the moment — the early
    alert must stay silent (his «بعد از بریک تایید بده»)."""
    import pandas as pd
    from analysis import prebreak_lane as pb
    ev = pb.normalize(_pb_event(edge=100.5, dist=0.40), symbol="UNIUSDT",
                      setup="TECHCLASSIC", tf="1h")
    df, _ = _confirm_frame([100.2, 100.3, 100.4, 101.6, 101.7], tf_min=60,
                           start="2026-10-15 04:00", line=100.5)
    assert pb.edge_broken(ev, df) is True
    _df2, _ = _confirm_frame([100.2, 100.3, 100.4, 100.45, 100.42], tf_min=60,
                             start="2026-10-15 04:00", line=100.5)
    assert pb.edge_broken(ev, _df2) is False


def test_r99q14_band_dedupe_and_cooldown():
    """One watch per EDGE: a level answered by two setups speaks once, an edge
    outside the inside/near band never speaks, and the cooldown holds the gap."""
    from analysis import prebreak_lane as pb
    _near = pb.normalize(_pb_event(setup="PINVAL", edge=100.5, dist=0.30),
                         symbol="UNIUSDT", setup="PINVAL", tf="1h")
    _twin = pb.normalize(_pb_event(setup="PINWALLQ", edge=100.52, dist=0.32),
                         symbol="UNIUSDT", setup="PINWALLQ", tf="1h")
    _far = pb.normalize(_pb_event(setup="ALBROX", edge=120.0, dist=9.0),
                        symbol="UNIUSDT", setup="ALBROX", tf="1h")
    assert max(_near["distance_atr"], _twin["distance_atr"]) <= pb.inside_band_atr()
    assert _far["distance_atr"] > pb.inside_band_atr()
    assert abs(float(_near["edge"]) - float(_twin["edge"])) <= 0.05 * float(_near["atr"])
    pb.reset_seen_cache()
    k = ("UNIUSDT", "PINVAL", "1h", "upper")
    assert pb.cooldown_ok(*k) is True
    assert pb.cooldown_ok(*k) is False                     # inside the 45-min gap
    # the lane's own cadence is much shorter than the retired 8h preview cooldown
    assert pb.gap_minutes("PINVAL") <= 60.0


def test_r99q14_watch_chain_confirms_on_the_first_close():
    """THE WHOLE POINT: the pre-break watch and the confirmation are ONE chain —
    the first valid close beyond the watch's edge confirms it (no second setup,
    no hours of silence)."""
    from analysis import prebreak_lane as pb
    ev = pb.normalize(_pb_event(edge=100.5, dist=0.30), symbol="UNIUSDT",
                      setup="TECHCLASSIC", tf="1h")
    cand = pb.build_watch_candidate(ev, None)
    cand.created_at = "2026-10-15 04:00"
    ok, c2, reason = _run(cand, [99.9, 100.0, 100.05, 100.1, 101.6])
    assert ok is True, reason
    assert abs(c2.planned_entry - 101.6) < 1e-9, "entry must be the confirming close"
    assert (c2.metadata or {}).get("alert_stage") == "PREBREAK"


def test_r99q14_stale_guard_measures_the_entry_bar_not_the_old_break_bar():
    """A verdict computed on the LIVE close may never be disarmed as «۱۶۵ دقیقه
    کهنه» because the OLD break bar is still in the metadata (UNIUSDT·T698813)."""
    from datetime import datetime, timedelta, timezone
    from main import _confirmation_stale_minutes
    from analysis.prebreak_lane import build_watch_candidate, normalize
    _start = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M")
    cand = _confirm_cand("TECHCLASSIC", entry=100.3, tp1=100.9, tp2=104.0)
    df, _ = _confirm_frame([100.0, 100.1, 100.2, 101.6], tf_min=15,
                           start=_start, line=100.5)
    # the bar the entry came from is the newest closed bar → fresh
    cand.metadata["confirm_entry_bar"] = str(df["timestamp"].iloc[-1])[:19]
    cand.metadata["confirm_entry_tf_min"] = 15.0
    cand.metadata["fast_break_bar"] = str(df["timestamp"].iloc[-4])[:19]  # the OLD claim
    assert _confirmation_stale_minutes(cand, df) is None
    # without the stamp the old break bar is what used to condemn the verdict
    cand.metadata.pop("confirm_entry_bar")
    cand.metadata.pop("confirm_entry_tf_min")
    assert _confirmation_stale_minutes(cand, df) is not None


def test_r99q14_setup_charts_are_120_candles_or_more():
    """His law: setup charts start at 120 candles, chosen by the OWNING setup's
    own candle law (pattern selection + TF), never a thin 50–90-bar frame."""
    from analysis.techclassic import tc_candles_for, _candle_floor as _tc_floor
    from analysis.albrox import albrox_candles_for, _candle_floor as _ab_floor
    from analysis.pinval import pinval_candles_for, _candle_floor as _pv_floor
    from analysis.tlbreak import tlbreak_candles_for, _candle_floor as _tl_floor
    for _f in (_tc_floor, _ab_floor, _pv_floor, _tl_floor):
        assert _f() >= 120
    for _fn in (tc_candles_for, albrox_candles_for, pinval_candles_for, tlbreak_candles_for):
        for _tf in ("15m", "30m", "1h", "4h", "1d"):
            assert _fn(_tf, 0, "") >= 120, (_fn.__name__, _tf)
            assert _fn(_tf, 200, "TRENDLINE") >= 120, (_fn.__name__, _tf)
    # the render path floors a setup chart at the same number
    from bot.messages_v7 import _setup_chart_count
    cand = _confirm_cand("PINVAL")
    assert _setup_chart_count(cand, "1h", 300, None) >= 120


def test_r99q14_candle_height_never_over_70_percent():
    """His law: «در ستاپها در همه تایمفریم هاشون ارتفاع کندلها نباید بیشتر ۷۰
    درصد بشه» — a lone spike may not flatten the tape; the pane opens instead
    (candles are never cut: the r40 law)."""
    import numpy as np
    from bot.messages_v7 import _smart_y_window
    _ranges = np.array([0.10] * 40 + [20.0])          # one liquidation spike
    _lo, _hi = float(np.array([100.0] * 40 + [95.0]).min()), 120.0
    win = _smart_y_window(_lo, _hi, 0.8, recent_lo=100.0, recent_hi=101.0,
                          bars=41, candle_ranges=_ranges)
    assert win is not None
    _span = float(win[1]) - float(win[0])
    assert float(np.percentile(_ranges, 99.0)) <= 0.70 * _span + 1e-9
    assert float(np.median(_ranges)) <= 0.30 * _span + 1e-9
    # a quiet block is NOT inflated by the law (it only opens a pane when a
    # candle would fill more than 70% of it)
    _quiet = np.array([0.10] * 41)
    _w_plain = _smart_y_window(100.0, 101.0, 0.05, recent_lo=100.2, recent_hi=100.8,
                               bars=41)
    _w_law = _smart_y_window(100.0, 101.0, 0.05, recent_lo=100.2, recent_hi=100.8,
                             bars=41, candle_ranges=_quiet)
    assert _w_law is not None and _w_plain is not None
    assert abs((_w_law[1] - _w_law[0]) - (_w_plain[1] - _w_plain[0])) < 1e-9


def test_r99q14_spot_box_rides_the_pattern_edge():
    """The green/red box is calibrated ON the shape's own line at the END of the
    pattern (a sloped trendline is not a flat number) — his exact wording."""
    import os as _os
    _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _src = open(_os.path.join(_root, "tools", "render_spot_cryptocove.py"),
                encoding="utf-8").read()
    assert "_edge_ln = a.get(\"upper\") if up_dir else a.get(\"lower\")" in _src
    assert "price_at(bx0)" in _src
    assert "box sits ON/above the edge" in _src and "hangs UNDER the edge" in _src


# ── R99q14 (cont.): the silent-geometry class ────────────────────────────────
def test_r99q14_pivot_finders_accept_arrays_and_series():
    """`x or []` on a numpy array raises ValueError ("truth value ... is
    ambiguous") and every pivot finder swallowed it into an EMPTY pivot set —
    i.e. geometry disappeared with no error whenever an engine handed arrays
    or a pandas Series in. Lists, arrays and Series must agree."""
    import numpy as _np
    import pandas as _pd
    from analysis.albrox import albrox_find_pivots
    from analysis.techclassic import tc_find_pivots
    from analysis.pinval import pinval_find_pivots
    from analysis.tlbreak import tlbreak_find_pivots
    from analysis.spot import spot_find_pivots

    _h = [1, 2, 3, 2, 1, 2, 5, 2, 1, 3, 4, 3, 2, 1, 2, 6, 3, 1, 2, 2, 2, 2]
    _l = [0, 1, 2, 1, 0, 1, 4, 1, 0, 2, 3, 2, 1, 0, 1, 5, 2, 0, 1, 1, 1, 1]
    for fn, kw in ((albrox_find_pivots, {}), (tc_find_pivots, {}),
                   (pinval_find_pivots, {}), (tlbreak_find_pivots, {}),
                   (spot_find_pivots, {"left": 2, "right": 2})):
        _list = fn(list(_h), list(_l), **kw)
        assert _list["highs"], f"{fn.__name__} found no pivots on a list"
        assert fn(_np.array(_h), _np.array(_l), **kw) == _list
        assert fn(_pd.Series(_h), _pd.Series(_l), **kw) == _list
        assert fn(None, None, **kw) == {"highs": [], "lows": []}


def test_r99q14_albrox_prebreak_reads_albrox_own_inventory():
    """The ALBROX pre-break lane was silent on every live frame (0 events /
    0 exceptions). Two defects, both closed here: the numpy-truthiness bug in
    its pivot helper, and a "zone" synthesised from the last two pivot highs
    (a 4-ATR smear). It must now speak from ALBROX's OWN r60 inventory and
    never draw a zone taller than 3 ATR (r61.1 sane-zone law)."""
    import numpy as _np
    import pandas as _pd
    from analysis.albrox import albrox_prebreak

    _n = 140
    _px = [100.0] * _n
    for _i in range(_n):                      # a long tape with a clean OB
        _px[_i] = 100.0 + 0.05 * _i
    _px[-30] = 101.0                          # supply OB: up candle ...
    _px[-29] = 103.0                          # ... then displacement down
    _px[-28] = 102.0
    _df = _pd.DataFrame({
        "timestamp": _pd.date_range("2026-01-01", periods=_n, freq="1h"),
        "open": [p - 0.05 for p in _px],
        "high": [p + 0.40 for p in _px],
        "low": [p - 0.40 for p in _px],
        "close": list(_px),
        "volume": [10.0] * _n,
    })
    _ev = albrox_prebreak(_df, "1h", symbol="TESTUSDT")
    assert isinstance(_ev, list)
    _atr = float((_df["high"] - _df["low"]).tail(14).mean())
    for _e in _ev:
        for _z in _e.get("zones") or []:
            assert abs(float(_z["top"]) - float(_z["bottom"])) <= 3.0 * _atr
        assert float(_e["distance_atr"]) <= 2.4
    # arrays/series go through the same door (no silent empty inventory)
    assert isinstance(alb_find_pivots_probe(_np.array(_px)), dict)


def alb_find_pivots_probe(_arr):
    """Helper: the ALBROX pivot helper must answer on raw arrays too."""
    from analysis.albrox import albrox_find_pivots
    return albrox_find_pivots(_arr, _arr)


def test_r99q14_honesty_veto_accepts_an_honest_flat_edge():
    """A horizontal TRENDLINE is a LEVEL, not a missing line: the flat→band law
    paints it as a zone band, so the honesty veto must not kill that photo
    (ETHUSDT 4h TLBREAK was vetoed for exactly this while its edge was flat)."""
    import os as _os
    _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    src = open(_os.path.join(_root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "_viva_pattern_geometry" in src
    assert "if _nsl74 == 0 and not _drew74:" in src
    # the flag is set on BOTH paint paths (band + line)
    assert src.count("fig._viva_pattern_geometry = True") >= 2


def test_r99q14_render_contract_points_are_read_by_the_slope_derive():
    """The RENDER contract speaks {"ts","price"} while _viva_points_xs reads
    {"timestamp"}: feeding it raw ts-points returned NaN for both ends, the
    slope collapsed to 0.0 and the edge painted as a flat band (the whole
    «چارت هندسه نداره» class). Both readers must accept the render key."""
    import os as _os
    _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    src = open(_os.path.join(_root, "bot", "messages_v7.py"), encoding="utf-8").read()
    _derive = src.split("R99q14: the RENDER contract speaks")[1][:900]
    assert '_p.get("ts")' in _derive and "_pp0x" in _derive
    _native = src.split("R99q14: accept the r59 RENDER contract key too")[1][:400]
    assert '_pt.get("ts")' in _native


def test_r99q14_spot_envelope_never_over_75_percent():
    """Viva 10-16: «ارتفاع کندل‌های اسپات … بیشتر از ۷۰ تا ۷۵ درصد نشه از کل
    ارتفاع چارت» — the visible candle block owns ≤75% of the spot price panel."""
    import math as _math
    from tools.render_spot_cryptocove import spot_y_window
    for _lo, _hi in ((100.0, 130.0), (2300.0, 2800.0), (0.8, 1.4), (0.075, 0.105)):
        _yl, _yh = spot_y_window(_lo, _hi)
        _env = ((_math.log(_hi) - _math.log(_lo))
                / (_math.log(_yh) - _math.log(_yl)))
        assert 0.60 <= _env <= 0.75, (_lo, _hi, _env)


def test_r99q14_futures_envelope_law_bounds_the_visible_tape():
    """Same law on every setup chart: the tape the window FRAMES owns ≤75% of
    the pane — and the deep-frame soft clip (r64) still keeps its live region."""
    from bot.messages_v7 import _smart_y_window
    _win = _smart_y_window(100.0, 130.0, 1.0, recent_lo=110.0, recent_hi=125.0,
                           bars=130)
    assert _win is not None
    _ylo, _yhi = _win
    assert (130.0 - 100.0) / (_yhi - _ylo) <= 0.75
    _deep = _smart_y_window(0.0, 100.0, 0.8, None, None,
                            recent_lo=48.0, recent_hi=52.0, bars=300)
    assert _deep[0] > 20.0, _deep                      # r64 still holds


def test_r99q14_pinval_chains_get_their_validated_edges():
    """His 10-16 question: «چرا بعضی چارت‌های پینوال پترن و ترندلاین نمی‌کشه
    روش؟» — the validated-edge overlay was variant-gated (TLBREAK/ALBROX only),
    so PINVAL chains carrying their own viva_upper/lower_points never had them
    painted. It now runs for any futures chain with an edge set, and an edge the
    pattern painter already drew is skipped (never paint an edge twice)."""
    import os as _os
    _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _src = open(_os.path.join(_root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'or (_has_edges9 and not _is_spot)' in _src
    assert "def _covered9" in _src
    # R99q17: the dedupe now takes the 60-bar witness too (his ETH 15M PINVAL
    # painted the SAME upper trendline twice, 0.6 % apart — a one-bar
    # coincidence test could not see it) and the refit shell yields to it.
    assert "_covered9(key, _y_now9, _y_prev9)" in _src
    assert "0.02 * float(frame[\"close\"].iloc[-1])" in _src
    assert "if _covered9(_ky9, _y61):" in _src


# ── R99q15 (his 10-16 four questions) ───────────────────────────────────────
def test_r99q15_every_setup_watches_every_trigger_frame():
    """«مهم‌ترین قسمت اینه که همه چارت‌ها در تایم‌فریم‌های همه ستاپ‌ها قبل از
    شکست تشخیص داده بشن» — the early lane answers on the FULL trigger grid
    (15m/30m/1h/2h/4h) for EVERY setup, env-overridable per setup."""
    import os as _os
    import analysis.prebreak_lane as pb
    _grid = ("15m", "30m", "1h", "2h", "4h")
    for _setup in ("TECHCLASSIC", "ALBROX", "PINVAL", "PINWALLQ", "TLBREAK"):
        assert pb.setup_tfs(_setup) == _grid, _setup
        assert _os.getenv(f"VIVA_PREBREAK_TFS_{_setup}") is None
        _os.environ[f"VIVA_PREBREAK_TFS_{_setup}"] = "1h,4h"
        try:
            assert pb.setup_tfs(_setup) == ("1h", "4h")
        finally:
            _os.environ.pop(f"VIVA_PREBREAK_TFS_{_setup}", None)
    _os.environ["VIVA_PREBREAK_TFS"] = "30m,1h"
    try:
        assert pb.setup_tfs("PINVAL") == ("30m", "1h")
    finally:
        _os.environ.pop("VIVA_PREBREAK_TFS", None)
    # the lane actually walks the grid for every provider
    assert all(pb.SETUP_TFS[_s] == _grid for _s in pb.SETUP_TFS)


def test_r99q15_watches_run_first_on_their_own_budget():
    """The early alerts are dispatched FIRST for each symbol and own a separate
    cycle budget (env `VIVA_WATCH_PER_SCAN`) — a burst of watches can never
    starve the break lanes and vice-versa."""
    import inspect
    import main
    src = inspect.getsource(main)
    assert 'os.getenv("VIVA_WATCH_PER_SCAN", "6")' in src
    assert "candidates = list(_pb14) + list(candidates)" in src


def test_r99q15_chart_and_text_are_one_package_per_chat():
    """His 10-16: «کاری بکن که همیشه چارت و پیامش باهم و پشت سرهم بیان» — the
    education package (separator + chart + detailed alert) holds its chat's
    lock, and every Telegram post serializes on the same chat lock."""
    import inspect
    import threading
    import bot.messages_v7 as B7
    src = inspect.getsource(B7)
    assert "with _package(target):" in src
    assert 'with _chat_send_lock((data or {}).get("chat_id")):' in src
    # the lock must be REENTRANT (a package re-enters it through its own sends)
    _lk = B7._chat_send_lock("TEST-CHAT")
    # threading.RLock is a FACTORY function, not a type — test the behaviour
    assert "RLock" in type(_lk).__name__, type(_lk)
    with B7._package("TEST-CHAT"):
        assert _lk.acquire(blocking=False), "a package must be re-entrant"
        _lk.release()
        _blocked = {"v": None}

        def _other():
            _blocked["v"] = _lk.acquire(blocking=False)
            if _blocked["v"]:
                _lk.release()

        _t = threading.Thread(target=_other)
        _t.start()
        _t.join(timeout=2)
        assert _blocked["v"] is False, "another thread must NOT enter the package"


def test_r99q15_mplfinance_and_evictions_did_not_regress_the_ladder():
    """Q2 guard: confirmation fires on the FIRST closed candle of the confirm
    TF — one step BELOW the trigger (smaller than the pattern) — or through the
    illusion engine one step below that. Never on the trigger TF itself."""
    from analysis.confirm_r62 import (confirm_tf_for_trigger as _ctf,
                                      tohom_sub_tf as _sub, CONFIRM_LADDER)
    assert CONFIRM_LADDER == {"5m": "1m", "15m": "5m", "30m": "15m",
                              "1h": "15m", "2h": "30m", "4h": "1h", "1d": "4h"}
    for _trig, _want in (("15m", "5m"), ("30m", "15m"), ("1h", "15m"),
                         ("2h", "30m"), ("4h", "1h")):
        assert _ctf(_trig) == _want
        assert _sub(_trig) is not None, _trig
        assert _sub(_trig) != _trig


# ══════════════════════════════════════════════════════════════════════════
# R99q15b — his 10-16 laws (seven-chart spot journey, one unique id, adaptive
# deep cadence, per-TF spot gate, the headless/apex chart laws)
# ══════════════════════════════════════════════════════════════════════════
def test_r99q15_journey_claims_seven_chart_slots_and_never_more(monkeypatch):
    """«هر شناسه از لحظه شناسایی تا پایان مسیر ۷ چارت نهایتاً بیشتر نشه»."""
    from analysis import spot_engine as SE
    monkeypatch.delenv("VIVA_SPOT_CHAIN_CHARTS", raising=False)
    assert SE.spot_chain_chart_cap() == 7
    meta = {}
    for slot in ("s1", "s2", "s3", "s4", "h1", "h2", "h3"):
        assert SE._spot_journey_slot(meta, slot, 1000.0) == slot
    assert SE._spot_journey_slot(meta, "s5", 1000.0) is None
    assert SE._spot_journey_slot({"charts": 7}, "s1", 1000.0) is None
    # a taken slot is spent, a fresh pending claim blocks reuse for 10 minutes
    assert SE._spot_journey_slot({"s2": 55}, "s2", 1000.0) is None
    assert SE._spot_journey_slot({"s3p": 999.0}, "s3", 1000.0) is None
    assert SE._spot_journey_slot({"s3p": 100.0}, "s3", 1000.0) == "s3"
    assert SE.spot_chain_chart_commit({"charts": 1})["charts"] == 2


def test_r99q15_the_confirmation_is_chart_four_of_the_same_id():
    """«چارت چهارم همراه پیام تایید ورود به پوزیشن میاد» — with the SAME code."""
    import database.bot_kv as kv
    mem = {"spot_chain|UNIUSDT|30M": {"code": "VIVA-SPOT-Y123456", "charts": 3}}
    kv.get_json = lambda k, d=None: mem.get(k, d)
    kv.set_json = lambda k, v: mem.__setitem__(k, v)
    from analysis.spot_engine import build_spot_candidate
    base = {"symbol": "UNIUSDT", "tf": "30m", "entry": 7.391, "sl": 7.225,
            "targets": [7.492, 7.593, 7.694], "atr": 0.05,
            "pattern": "WEDGE_FALLING", "weights": [0.4, 0.3, 0.3]}
    c = build_spot_candidate(dict(base))
    assert c.metadata["public_code"] == "VIVA-SPOT-Y123456"
    assert c.metadata["spot_chain_one_id"] is True
    c2 = build_spot_candidate(dict(base, symbol="ZZZUSDT", tf="4h"))
    assert c2.metadata["public_code"].startswith("VIVA-SPOT-")
    assert c2.metadata["public_code"] != "VIVA-SPOT-Y123456"


def test_r99q15_spot_hits_are_runged_and_close_the_position():
    """«بعد ۳ تا هیت شدن» — TP1→TP2→TP3 in order, then the position closes."""
    import database.bot_kv as kv
    mem = {}
    kv.get_json = lambda k, d=None: mem.get(k, d)
    kv.set_json = lambda k, v: mem.__setitem__(k, v)
    from analysis.spot_engine import (spot_position_open, spot_hit_scan,
                                      spot_position_commit, spot_hit_candidate)
    class _C:
        symbol, trigger_timeframe, entry, stop_loss, signal_id = (
            "UNIUSDT", "30m", 7.391, 7.225, "x")
        metadata = {"public_code": "VIVA-SPOT-Y123456",
                    "pattern_type": "WEDGE_FALLING", "render_patterns": []}
    pos = spot_position_open(_C(), [7.492, 7.593, 7.694], 555)
    assert pos["hits"] == [] and pos["targets"] == [7.492, 7.593, 7.694]
    assert spot_hit_scan(pos, 7.40) is None          # rungs are hit in ORDER
    h1 = spot_hit_scan(pos, 7.50)
    assert h1["kind"] == "tp1" and abs(h1["level"] - 7.492) < 1e-9
    pos = spot_position_commit("VIVA-SPOT-Y123456", "tp1", 901)
    assert spot_hit_scan(pos, 7.50) is None          # tp1 is spent
    assert spot_hit_scan(pos, 7.60)["kind"] == "tp2"
    pos = spot_position_commit("VIVA-SPOT-Y123456", "tp2", 902)
    pos = spot_position_commit("VIVA-SPOT-Y123456", "tp3", 903)
    assert pos["hits"] == ["tp1", "tp2", "tp3"] and pos["closed"] == "ALL_TARGETS"
    cand = spot_hit_candidate(pos)
    assert cand is not None and cand.trigger_timeframe == "30m"
    assert cand.metadata["public_code"] == "VIVA-SPOT-Y123456"


def test_r99q15_adaptive_deep_cadence_bursts_on_good_finds(monkeypatch):
    """«هر ۶۰ دقیقه ... مگر اینکه موارد خوبی پیدا بکنه» — then the fast lane."""
    import time as _t
    import database.bot_kv as kv
    mem = {}
    kv.get_json = lambda k, d=None: mem.get(k, d)
    kv.set_json = lambda k, v: mem.__setitem__(k, v)
    from analysis import tiered_scan as TS
    monkeypatch.setenv("TIER_DEEP_MINUTES", "60")
    monkeypatch.delenv("TIER_DEEP_BURST_MINUTES", raising=False)
    monkeypatch.delenv("TIER_DEEP_BURST_WINDOW_MINUTES", raising=False)
    assert TS.deep_minutes() == 60
    TS.mark_deep_result(0)
    assert TS.deep_minutes() == 60          # a quiet market keeps the 60-min beat
    TS.mark_deep_result(3)
    assert TS.deep_minutes() == 5           # good finds → the fast lane
    mem["tier_deep_burst_until"] = "2000-01-01T00:00:00Z"
    assert TS.deep_minutes() == 60          # expired window falls back
    monkeypatch.setenv("TIER_DEEP_BURST_MINUTES", "4")
    mem["tier_deep_burst_until"] = "2999-01-01T00:00:00Z"
    assert TS.deep_minutes() == 4
    _ = _t


def test_r99q15_spot_per_tf_gate_skips_frames_without_a_new_close():
    """Cost law: an hourly pass must not re-fit 6 frames per symbol."""
    import database.bot_kv as kv
    mem = {}
    kv.get_json = lambda k, d=None: mem.get(k, d)
    kv.set_json = lambda k, v: mem.__setitem__(k, v)
    import pandas as pd
    from analysis import tiered_scan as TS

    def _frame(ts):
        return pd.DataFrame({"timestamp": [ts], "open": [1.0], "high": [1.1],
                             "low": [0.9], "close": [1.0], "volume": [10.0]})

    bundle = {"4h": _frame("2026-10-16 00:00:00"),
              "1d": _frame("2026-10-16 00:00:00"),
              "1w": None}
    due = TS.spot_due_tfs("BTCUSDT", bundle, tfs=("4h", "1d", "1w"))
    assert due == ["4h", "1d", "1w"]        # cold KV → fail-open
    TS.spot_tf_mark("BTCUSDT", bundle, ("4h", "1d"))
    # nothing closed → nothing due; an unreadable frame (1w) is still scanned
    assert TS.spot_due_tfs("BTCUSDT", bundle, tfs=("4h", "1d")) == []
    assert TS.spot_due_tfs("BTCUSDT", bundle, tfs=("4h", "1w")) == ["1w"]
    # a new close (or a live pin) pulls the frame back in
    bundle["4h"] = _frame("2026-10-16 04:00:00")
    assert TS.spot_due_tfs("BTCUSDT", bundle, tfs=("4h", "1d")) == ["4h"]
    assert TS.spot_due_tfs("BTCUSDT", bundle, tfs=("1d",), pinned=("1d",)) == ["1d"]


def test_r99q15_headless_line_and_resolved_apex_laws_are_in_the_painter():
    """His «یک خط بی‌سر و ته می‌کشه» — the two paint laws that remove it."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "bot", "messages_v7.py"), encoding="utf-8").read()
    # a stored line with no in-frame pivot is context (faint), never the trade line
    assert "_in_xs9 = [float(_x) for _x in xs if -1.5 <= float(_x) <= count + 0.5]" in src
    assert "_headless99q15" in src
    # a RESOLVED pair (apex at/before LIVE) paints no forward tail at all
    assert "_resolved99 = bool(_apex9 is not None and _apex9 <= count + 0.6)" in src


def test_r99q17_edge_identity_law_no_duplicated_trendline():
    """His ETH 15M PINVAL: the same upper trendline was painted twice, 0.6 %
    apart (the detector's fit and the validated-pivots fit of ONE edge)."""
    import os as _os
    _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _src = open(_os.path.join(_root, "bot", "messages_v7.py"), encoding="utf-8").read()
    # structural tolerance + the second witness point at count-60
    assert "_tol9 = max(0.9 * _atr_ov9, 0.02 * float(frame[\"close\"].iloc[-1]))" in _src
    assert "if _covered9(key, _y_now9, _y_prev9):" in _src
    assert "_y_prev9 = (10 ** (slope * max(0, count - 60) + intercept))" in _src
    # and a duplicated REFIT shell is skipped and painted faint when kept
    assert "if _covered9(_ky9, _y61):" in _src
    assert "_lw9, _al9 = 1.15, 0.5" in _src
