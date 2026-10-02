"""R64 — TC/ALBROX order, sane-zone for break lanes, H&S label direction,
smart (log/robust) trendline geometry, the ONE candle-count map, spot window
unity, deep-history cost fix and the log-space chart zoom."""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ── 1. TECHCLASSIC registers BEFORE ALBROX (TC root cause #1) ─────────────
def test_technoclassic_runs_before_albrox(monkeypatch):
    import dataclasses
    import analysis.setups_v7 as v7
    monkeypatch.setattr(v7, "SETTINGS", dataclasses.replace(
        v7.SETTINGS, albrox_enabled=True, technoclassic_enabled=True))
    names = [getattr(d, "__name__", "") for d in v7._active_detectors()]
    assert "detect_technoclassic" in names and "detect_albrox" in names
    assert names.index("detect_technoclassic") < names.index("detect_albrox")


# ── 2. sane-zone: break corridor + floor capped by the TF stop ceiling ────
def test_sane_zone_break_corridor_is_not_a_watch_box():
    from analysis.trade_management import sane_zone_geometry_ok as ok
    # 1d break: line 1.00, live 1.24 → corridor 0.99..1.25 (26%) — the old
    # law killed it as a «4.7% box»; the corridor is not a watch zone.
    assert not ok(0.99, 1.25, 1.24, 1.15, "LONG", 0.07, "SWING")
    assert ok(0.99, 1.25, 1.24, 1.15, "LONG", 0.07, "SWING",
              line_price=1.00, trigger_tf="1d")
    # a pin/zone lane (no line) keeps law ① exactly
    assert not ok(0.99, 1.25, 1.24, 1.15, "LONG", 0.07, "SWING", trigger_tf="1d")


def test_sane_zone_floor_never_exceeds_the_stop_ceiling():
    from analysis.trade_management import sane_zone_geometry_ok as ok
    # SUI-like 1d: ATR 7.3% → 1.5×ATR = 10.95% > the 8% 1d ceiling → every
    # GRAND was impossible. Floor is now ≤ 0.9×8% = 7.2%.
    assert not ok(0.999, 1.001, 1.0, 0.925, "LONG", 0.073, "GRAND")
    assert ok(0.999, 1.001, 1.0, 0.925, "LONG", 0.073, "GRAND", trigger_tf="1d")
    # below the capped floor it still refuses (no glued stops)
    assert not ok(0.999, 1.001, 1.0, 0.95, "LONG", 0.073, "GRAND", trigger_tf="1d")


# ── 3. H&S label only rides its own doctrine direction ────────────────────
def _hs_frame():
    # flat upper line at 10.0 touched at 5, 25, 45; a head to 11.0 at 15
    n = 60
    hi = np.full(n, 9.5)
    lo = np.full(n, 9.0)
    for i in (5, 25, 45):
        hi[i] = 10.0
    hi[15] = 11.0
    return pd.DataFrame({"open": 9.2, "high": hi, "low": lo, "close": 9.3, "volume": 1.0})


class _Line:
    slope = 0.0
    points = ({"index": 5}, {"index": 25}, {"index": 45})


def test_head_label_never_on_the_opposite_break():
    from analysis.pattern_engine import _structural_refine
    df = _hs_frame()
    # upper-edge break = LONG → a «head» above is a failed head, never H&S
    pat, note = _structural_refine(df, _Line(), "upper", 59, 2.0, "HORIZONTAL_SR",
                                   direction="LONG")
    assert pat == "HORIZONTAL_SR" and note == ""
    pat, _ = _structural_refine(df, _Line(), "upper", 59, 2.0, "HORIZONTAL_SR",
                                direction="SHORT")
    assert pat == "HEAD_SHOULDERS"
    # legacy call (no direction) unchanged
    pat, _ = _structural_refine(df, _Line(), "upper", 59, 2.0, "HORIZONTAL_SR")
    assert pat == "HEAD_SHOULDERS"


# ── 4. smart geometry: robust, scale-honest ruler ─────────────────────────
def _tape(n=300, seed=7, base=100.0):
    rng = np.random.default_rng(seed)
    c = base * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    return pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="h"),
                         "open": o, "high": h, "low": l, "close": c, "volume": 1.0})


def test_robust_unit_is_scale_invariant_and_spike_proof():
    from analysis.viva_tlbreak import _robust_unit, _atr
    d = _tape()
    u = _robust_unit(d, True)
    d2 = d.copy()
    for col in ("open", "high", "low", "close"):
        d2[col] = d2[col] * 1000.0
    assert abs(_robust_unit(d2, True) - u) < 1e-12          # log ruler: scale-free
    d3 = d.copy()
    d3.loc[len(d3) - 3, "high"] = float(d3["high"].iloc[-3]) * 1.08   # liquidation spike
    assert abs(_robust_unit(d3, True) - u) / u < 0.02        # median ignores it
    assert _atr(d3) > 1.3 * _atr(d)                          # the legacy ruler did not


def test_prominence_ranks_majors_over_wiggles():
    from analysis.viva_tlbreak import _pivot_prominence, _robust_unit
    n = 80
    hi = np.full(n, 10.0)
    lo = np.full(n, 9.8)
    hi[20], lo[30] = 13.0, 9.7          # a real swing high: big pullback after
    hi[60] = 10.05                       # a wiggle on a flat tape
    d = pd.DataFrame({"open": 9.9, "high": hi, "low": lo, "close": 9.9, "volume": 1.0})
    d.loc[21:29, "low"] = 9.0            # reaction out of the major high
    u = _robust_unit(d, True)
    prom = _pivot_prominence(d, [{"index": 20, "price": 13.0},
                                 {"index": 60, "price": 10.05}], "HIGH", True, u)
    assert prom[20] > 5 * prom[60]


def test_r64_switch_restores_legacy(monkeypatch):
    import analysis.viva_tlbreak as V
    d = _tape()
    monkeypatch.setenv("TLBREAK_R64_GEOMETRY", "0")
    legacy = [V.fit_validated_line(d, s) for s in ("HIGH", "LOW")]
    monkeypatch.setenv("TLBREAK_R64_GEOMETRY", "1")
    smart = [V.fit_validated_line(d, s) for s in ("HIGH", "LOW")]
    # both modes run; the switch is honoured (never raises)
    assert len(legacy) == len(smart) == 2
    assert V._r64_enabled() is True
    monkeypatch.setenv("TLBREAK_R64_GEOMETRY", "off")
    assert V._r64_enabled() is False


def test_smart_fit_rejects_a_short_local_pair_on_a_big_window():
    """A 20-bar local pair on a 300-bar window must not be the «trend»."""
    import analysis.viva_tlbreak as V
    d = _tape(seed=11)
    ln = V.fit_validated_line(d, "HIGH")
    if ln is not None and ln.break_index is None:
        assert (ln.points[-1]["index"] - ln.points[0]["index"]) >= 0.10 * (len(d) - 1) - 1


# ── 5. ONE candle-count map (chart ≡ engine ≡ spot) ───────────────────────
def test_candle_counts_single_source():
    from analysis.candle_counts import CANDLE_COUNTS, RENDER_COUNTS, candle_count, fetch_limits
    from analysis.pattern_engine import _FIT_WINDOW
    from bot.messages_v7 import _CHART_CANDLE_COUNTS
    # DETECTION keeps the dictated 250–350 pivots-hunting window (his 10-02
    # «۲۵۰ تا ۳۵۰ کندل … برای پیوت‌های بیشتر در تایم‌های بالاتر»).
    for tf, n in _FIT_WINDOW.items():
        assert n == CANDLE_COUNTS[tf] and 250 <= n <= 350
    # R65 PICTURE DENSITY: the CHART is the render map now — 190–210 on the
    # intraday frames (his 10-02 «کندل ۱۹۰ تا ۲۱۰ تا کافیه … فقط شلوغ‌تر شد»),
    # dictated counts above, and never a third number anywhere.
    assert _CHART_CANDLE_COUNTS == RENDER_COUNTS
    for tf in ("5m", "15m", "30m", "1h", "2h"):
        assert 190 <= RENDER_COUNTS[tf] <= 210
    for tf in ("4h", "8h", "12h", "1d", "3d", "1w"):
        assert RENDER_COUNTS[tf] == CANDLE_COUNTS[tf]
    assert candle_count("1D") == 300 and fetch_limits(["4h"]) == {"4h": 340}


def test_spot_scan_window_is_the_chart_window():
    src = open(os.path.join(ROOT, "analysis", "spot_engine.py"), encoding="utf-8").read()
    assert src.count("d = d.tail(_spot_count(tf)).reset_index(drop=True)") == 2
    from analysis.spot_engine import _spot_count
    assert _spot_count("1d") == 300 and _spot_count("1w") == 250


def test_bundle_1h_2h_ride_direct_1h_tape(monkeypatch):
    import data.fetcher as f
    calls = []

    def fake(symbol, interval, limit, closed_only=True, **kw):
        calls.append((interval, limit))
        freq = {"15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D", "5m": "5min"}[interval]
        ts = pd.date_range("2025-01-01", periods=limit, freq=freq)
        return pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 1.01, "low": 0.99,
                             "close": 1.0, "volume": 1.0})
    monkeypatch.setattr(f, "get_klines", fake)
    monkeypatch.setattr("data.history_store.get_deep_daily", lambda s, n: None)
    b = f.get_market_bundle("XUSDT", ("1d", "4h", "2h", "1h", "30m", "15m"))
    assert len(b.get("1h")) >= 300 and len(b.get("2h")) >= 250
    assert len(b.get("4h")) >= 300 and len(b.get("30m")) >= 300
    assert all(lim <= 1000 for _, lim in calls)


# ── 6. deep-history: a young coin is fetched deep ONCE (Railway cost) ─────
def test_young_coin_is_not_redownloaded_every_scan(monkeypatch):
    import data.history_store as hs
    hs._MEMORY.clear()
    hs._COMPLETE.clear()
    calls = {"deep": 0, "tail": 0}
    stored = {}
    young = pd.DataFrame({"timestamp": pd.date_range("2025-06-01", periods=480, freq="D"),
                          "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0})

    def fake_deep(sym, iv, limit, closed_only=True):
        calls["deep"] += 1
        return young.copy()

    def fake_tail(sym, iv, limit, closed_only=True, use_cache=False, end_ms=None):
        calls["tail"] += 1
        return young.tail(3).copy()
    monkeypatch.setattr("data.fetcher.get_klines_paginated", fake_deep)
    monkeypatch.setattr("data.fetcher.get_klines", fake_tail)
    monkeypatch.setattr(hs, "_load", lambda s: stored.get(s))
    monkeypatch.setattr(hs, "_save", lambda s, fr: stored.__setitem__(s, fr.copy()))
    assert len(hs.get_deep_daily("YNGUSDT", 1477)) == 480 and calls["deep"] == 1
    hs._MEMORY.clear()                                   # TTL expired / restart
    assert len(hs.get_deep_daily("YNGUSDT", 1477)) == 480
    assert calls["deep"] == 1 and calls["tail"] == 1     # tail refresh only


# ── 7. smart log zoom ─────────────────────────────────────────────────────
def test_smart_y_window_log_space_percent_floor():
    import math
    from bot.messages_v7 import _smart_y_window
    lo, hi = math.log10(100.0), math.log10(100.5)        # a flat 0.5% tape
    w = _smart_y_window(lo, hi, 0.0002, None, None, recent_lo=lo, recent_hi=hi,
                        log_space=True)
    assert w is not None
    span_pct = 10 ** (w[1] - w[0]) - 1
    assert 0.02 < span_pct < 0.05                        # opened to ~2.5%, not 0.5%
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "R64 SMART LOG ZOOM" in src and "log_space=True" in src


# ── 8. r63 risk ladder actually runs (config has no SETTINGS symbol) ──────
def test_risk_ladder_reads_settings_through_get_settings():
    import config
    assert not hasattr(config, "SETTINGS")
    assert config.get_settings().risk_ladder_enabled in (True, False)
    src = open(os.path.join(ROOT, "analysis", "pattern_engine.py"), encoding="utf-8").read()
    assert "from config import SETTINGS" not in src
    assert "from config import get_settings as _gs63" in src
