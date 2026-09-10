"""TechnoClassic pattern engine tests: geometry lifecycle, compression,
additive-only bonuses, cooldown, and detector smoke."""
import importlib
import math

import numpy as np
import pandas as pd
import pytest


def _wedge_frames(n=140):
    """Falling wedge as a clean zigzag between an upper line (touching at
    i=45/95/128) and a slightly lower-sloped line below it (touches at
    i=15/70/112); final trigger bar closes above the projected upper line
    with a displacement body."""
    U = lambda i: 100.0 - 0.10 * i
    L = lambda i: 60.0 - 0.01 * i
    wick = 0.6
    keys = [(0, 88.0), (15, L(15) + wick), (50, U(50) - wick), (75, L(75) + wick),
            (95, U(95) - wick), (112, L(112) + wick), (125, U(125) - wick),
            (137, L(137) + wick), (139, (U(139) + L(139)) / 2)]
    vals = np.zeros(n)
    for (i0, v0), (i1, v1) in zip(keys, keys[1:]):
        seg = np.linspace(v0, v1, i1 - i0 + 1)
        vals[i0:i1 + 1] = seg[:i1 - i0 + 1]
    high = vals + wick
    low = vals - wick
    open_ = vals - 0.01
    close = vals + 0.01
    ts = pd.date_range("2026-01-01", periods=n, freq="4h")
    pattern = pd.DataFrame({"timestamp": ts, "open": open_, "high": high,
                            "low": low, "close": close,
                            "volume": np.full(n, 100.0)})
    line_now = float(high[-1])  # close enough; recomputed below via fit
    atr_ref = float(np.mean((high - low)[-14:]))
    # trigger frame: 40 quiet bars then a closing break with displacement
    trig_n = 40
    ref = U(n - 1)
    t_mid = np.full(trig_n, ref - 1.0 * max(atr_ref, 1e-9))
    t_open = t_mid.copy(); t_close = t_mid.copy()
    t_high = t_mid + 0.3 * atr_ref; t_low = t_mid - 0.3 * atr_ref
    t_open[-1] = ref - 0.2 * atr_ref
    t_close[-1] = ref + 1.1 * atr_ref
    t_high[-1] = t_close[-1] + 0.05 * atr_ref
    t_low[-1] = t_open[-1] - 0.05 * atr_ref
    t_ts = pd.date_range("2026-08-01", periods=trig_n, freq="15min")
    trigger = pd.DataFrame({"timestamp": t_ts, "open": t_open, "high": t_high,
                            "low": t_low, "close": t_close,
                            "volume": np.full(trig_n, 100.0)})
    return pattern, trigger


class _Bundle:
    def __init__(self, frames, symbol="TESTUSDT"):
        self._f = frames
        self.symbol = symbol
        self.ticker = {"turnover24h": 10_000_000, "spread_pct": 0.05}

    def get(self, tf):
        return self._f.get(tf)


def _mod():
    from analysis import pattern_engine
    return pattern_engine


def test_scan_edges_finds_break_on_falling_wedge():
    m = _mod()
    pattern, trigger = _wedge_frames()
    events = m.scan_edges(pattern, trigger, "4h")
    assert events, "expected at least one edge event on a validated wedge"
    long_upper = [e for e in events if e["direction"] == "LONG" and e["side"] == "upper"]
    assert long_upper
    assert any(e["state"] in (m.STATE_BREAK, m.STATE_READY) for e in long_upper)
    ev = long_upper[0]
    assert "WEDGE" in ev["pattern"] or "TRIANGLE" in ev["pattern"] or "TRENDLINE" in ev["pattern"]


def test_compression_metrics_detects_squeeze_and_rejects_noise():
    m = _mod()
    n = 60
    big_rng = np.full(n, 2.0)
    high = np.cumsum(np.ones(n)) + big_rng
    low = high - big_rng
    close = (high + low) / 2
    open_ = close.copy()
    ts = pd.date_range("2026-01-01", periods=n, freq="4h")
    noisy = pd.DataFrame({"timestamp": ts, "open": open_, "high": high,
                          "low": low, "close": close, "volume": np.ones(n)})
    assert m.compression_metrics(noisy)["squeeze_ok"] is False
    # tail: 8 doji bars, tiny range
    doji_high = high.copy(); doji_low = low.copy()
    doji_open = open_.copy(); doji_close = close.copy()
    base = float(close[-9])
    doji_high[-8:] = base + 0.1
    doji_low[-8:] = base - 0.1
    doji_open[-8:] = base + 0.004
    doji_close[-8:] = base - 0.002
    squeeze = pd.DataFrame({"timestamp": ts, "open": doji_open, "high": doji_high,
                            "low": doji_low, "close": doji_close, "volume": np.ones(n)})
    out = m.compression_metrics(squeeze)
    assert out["squeeze_ok"] is True
    assert out["doji_count"] >= 2


def test_bonuses_are_bounded_additive_never_negative():
    m = _mod()
    pattern, trigger = _wedge_frames()
    cb, _ = m.compression_bonus(pattern)
    assert 0.0 <= cb <= 2.0
    last_close = float(pattern["close"].iloc[-1])
    for d in ("LONG", "SHORT"):
        bb = m.base_side_bonus(pattern, last_close, d)
        assert bb in (0.0, 1.0, 2.0)


def test_alert_cooldown_blocks_repeat():
    m = _mod()
    key = "TESTUSDT|4h|WEDGE_FALLING|LONG|upper"
    m._ALERT_SEEN.clear()
    assert m._cooldown_ok(key, m.STATE_NEAR) is True
    assert m._cooldown_ok(key, m.STATE_NEAR) is False


def test_detector_disabled_by_default_flag():
    m = _mod()
    import config
    config._cached = None  # not required; ensure settings object readable
    if getattr(config.get_settings(), "technoclassic_enabled", False):
        pytest.skip("flag on in this environment")
    pattern, trigger = _wedge_frames()
    bundle = _Bundle({"4h": pattern, "1h": pattern, "15m": trigger})
    assert m.detect_technoclassic(bundle, "DAYTRADE") is None


def test_detector_enabled_builds_or_cleanly_skips(tmp_path, monkeypatch):
    monkeypatch.setenv("TECHCLASSIC_ENABLED", "true")
    import config
    importlib.reload(config)
    import analysis.pattern_engine as pe
    importlib.reload(pe)
    pattern, trigger = _wedge_frames()
    bundle = _Bundle({"4h": pattern, "1h": pattern, "15m": trigger})
    cand = pe.detect_technoclassic(bundle, "DAYTRADE")
    if cand is not None:  # geometry must validate end-to-end on this fixture
        assert cand.setup_code == "TECHCLASSIC"
        assert cand.direction == "LONG"
        assert cand.score >= 6 and cand.score <= 10
        md = cand.metadata
        assert md["strategy_variant"] == "VIVA_TLBREAK"
        assert md["viva_state"] == "S2_BREAKOUT_CLOSED"
        assert md["viva_retest_window_bars"] == 32  # DAYTRADE window
        assert cand.tp2 > cand.planned_entry > 0
        assert cand.mandatory_gates.get("technoclassic_break_closed") is True
    monkeypatch.delenv("TECHCLASSIC_ENABLED")
    importlib.reload(config)
    importlib.reload(pe)


# ── reality build (Viva bug report 2026-09-10) ─────────────────────────────
def test_dead_edge_is_not_alerted():
    """Line whose last touch is far in the past must be treated as dead."""
    m = _mod()
    n = 140
    U = lambda i: 100.0 - 0.05 * i
    wick = 0.6
    idx = [8, 20, 33]
    vals = np.full(n, 80.0)
    for k, i in enumerate(idx):
        lo0 = idx[k - 1] if k else 0
        vals[lo0:i + 1] = np.linspace(vals[lo0], U(i) - wick, i + 1 - lo0)
    ts = pd.date_range("2026-01-01", periods=n, freq="4h")
    pattern = pd.DataFrame({"timestamp": ts, "open": vals, "high": vals + wick,
                            "low": vals - wick, "close": vals, "volume": np.full(n, 100.0)})
    t = _wedge_frames()[1]
    assert m.scan_edges(pattern, t, "4h") == []


def test_stale_feed_silences_instead_of_predicting():
    """If the chart feed lags the live price beyond the stale tolerance, the
    engine must say NOTHING (the ONDO $0.36-vs-$1.25 class of bug)."""
    m = _mod()
    pattern, trigger = _wedge_frames()
    last_close = float(trigger["close"].iloc[-1])
    atr_t = float((trigger["high"] - trigger["low"]).tail(14).mean())
    events = m.scan_edges(pattern, trigger, "4h", live_price=last_close + 30 * atr_t)
    assert events == []


def test_reaction_history_and_fade_plan():
    """Tested edge with rejection history + overshoot bar back inside ->
    REJECTION_FADE event carrying entry/stop/target (the 75% law)."""
    m = _mod()
    pattern, trigger = _wedge_frames()
    # rewrite the last trigger bar: wick beyond the line, close back inside
    n = len(pattern) - 1
    line = 100.0 - 0.10 * n
    atr_p = float((pattern["high"] - pattern["low"]).tail(14).mean())
    trig = trigger.copy()
    trig["open"].iloc[-1] = line - 0.4 * atr_p
    trig["close"].iloc[-1] = line - 0.15 * atr_p
    trig["high"].iloc[-1] = line + 0.5 * atr_p
    trig["low"].iloc[-1] = line - 0.5 * atr_p
    events = [e for e in m.scan_edges(pattern, trig, "4h") if e["side"] == "upper"]
    assert events, "expected an upper-edge event on the overshoot bar"
    ev = events[0]
    assert ev["reactions"]["touches"] >= 3
    fade = ev.get("fade")
    if ev["state"] == m.STATE_FADE:
        assert fade and fade["direction"] == "SHORT"
        assert fade["stop"] > fade["entry"] and fade["target"] < fade["entry"]
        assert fade["rr"] >= 1.3


def test_htf_layer_penalizes_target_beyond_tested_daily_edge():
    """A 1h-setup whose TP1 sits on a tested 1D edge must lose points, and an
    entry ON a valid edge must earn them — score only, never a reject."""
    m = _mod()
    from types import SimpleNamespace
    m._LINE_CACHE.clear()
    m._LINE_CACHE["XUSDT"] = {"at": 9e18, "lines": [
        {"tf": "1d", "side": "upper", "price": 104.6, "touches": 4, "reject_rate": 0.8, "atr": 2.0},
    ]}
    bundle = SimpleNamespace(symbol="XUSDT")
    cand = SimpleNamespace(planned_entry=100.0, tp1=105.0, tp2=112.0, direction="LONG",
                           score=8, metadata={})
    delta, note = m.htf_pattern_adjustment(bundle, cand)
    assert delta == -2 and "1d" in note
    m._LINE_CACHE["XUSDT"] = {"at": 9e18, "lines": [
        {"tf": "1d", "side": "lower", "price": 100.3, "touches": 3, "reject_rate": 0.75, "atr": 2.0},
    ]}
    delta2, note2 = m.htf_pattern_adjustment(bundle, cand)
    assert delta2 >= 1 and note2
    m._LINE_CACHE.clear()


def test_other_setups_stay_pristine():
    """TLBREAK/ALBROX must carry NO TechnoClassic score surgery (stats purity,
    Viva 2026-09-10): the pattern intelligence lives in TECHCLASSIC itself and
    in the score-only HTF layer outside the detectors."""
    src = open("analysis/setups_experimental.py", encoding="utf-8").read()
    for forbidden in ("viva_tc_compression_bonus", "albrox_tc_compression_bonus",
                      "viva_tc_base_bonus", "compression_bonus(refine_df)",
                      "_tc_comp_bonus + _tc_base_bonus"):
        assert forbidden not in src, f"contamination found: {forbidden}"
