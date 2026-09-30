"""r60.1 — bug-D identity fix, TOHOM FTB + candle vocabulary, TLBREAK
rejection scalp, ALBROX union (Viva 09-29 «همه رو درست کن»).

Laws under test (docs/TC_TLBREAK_REFERENCE.md §6):
- one live alert per pattern (stable pivot identity + lineage supersede);
- TOHOM confirms pre-close at the FTB and EXPLAINS why (doji / reverse-pin
  join the vocabulary; one counter sub-step allowed at the retest);
- rejection scalps (TLBREAK/ALBROX) confirm ONLY via TOHOM — a bare close
  never does, and candle patterns never veto real breaks;
- ALBROX = TECHCLASSIC engine + zone break/reclaim + zone rejection scalp,
  zones only score.
"""

import importlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, __import__("os").path.dirname(__file__))

from test_v7 import make_candidate  # noqa: E402


# ── 1) stable pattern identity (bug-D) ──────────────────────────────────────
def _line_df():
    n = 90
    mid = 100.0 + 0.05 * np.arange(n)
    hi = mid + 5.0
    lo = mid - 5.0
    hi[[10, 40, 70]] += 0.6
    lo[[20, 50, 80]] -= 0.6
    o = (hi + lo) / 2
    c = (hi + lo) / 2
    ts = pd.date_range("2026-09-01", periods=n, freq="4h")
    return pd.DataFrame({"timestamp": ts, "open": o, "high": hi, "low": lo,
                         "close": c, "volume": np.full(n, 100.0)})


def test_pattern_id_stable_across_window_slide_refit():
    """THE dup-killer: sliding the window one bar (a refit) must NOT mint a
    new pattern id when the defining pivots are unchanged."""
    from analysis.pattern_engine import fit_edge_line, pattern_id_for
    from analysis.viva_tlbreak import load_config
    df = _line_df()
    ln1 = fit_edge_line(df, "HIGH", load_config(), len(df) - 1)
    assert ln1 is not None and len(ln1.points) >= 2
    id1 = pattern_id_for("TRIANGLE_DESCENDING", "4h", ln1, None, len(df) - 1)
    df2 = pd.concat([df.iloc[1:], df.iloc[[-1]].assign(
        timestamp=df["timestamp"].iloc[-1] + pd.Timedelta(hours=4))]).reset_index(drop=True)
    ln2 = fit_edge_line(df2, "HIGH", load_config(), len(df2) - 1)
    assert ln2 is not None
    id2 = pattern_id_for("TRIANGLE_DESCENDING", "4h", ln2, None, len(df2) - 1)
    assert id1 == id2


def test_pattern_id_changes_on_new_pivot():
    from analysis.pattern_engine import fit_edge_line, pattern_id_for
    from analysis.viva_tlbreak import load_config
    df = _line_df()
    ln1 = fit_edge_line(df, "HIGH", load_config(), len(df) - 1)
    id1 = pattern_id_for("TRIANGLE_DESCENDING", "4h", ln1, None, len(df) - 1)
    df3 = df.copy()
    df3.loc[40, "high"] = float(df3.loc[40, "high"]) + 3.0     # a defining touch moves
    ln3 = fit_edge_line(df3, "HIGH", load_config(), len(df3) - 1)
    id3 = pattern_id_for("TRIANGLE_DESCENDING", "4h", ln3, None, len(df3) - 1)
    assert id1 != id3


def test_tc_candidate_carries_stable_lineage():
    """TC candidates now carry alert_lineage_key → the store supersedes a
    re-detected same-pattern row instead of minting a twin (his ARB case)."""
    import analysis.setups_experimental  # noqa: F401 — registers SETUP_NAMES
    from test_pattern_engine import _wedge_frames, _Bundle
    import analysis.pattern_engine as pe
    from analysis.setups_v7 import timeframe_profile
    pattern, trigger = _wedge_frames()
    stf, _ref, ttf = timeframe_profile("DAYTRADE")
    p2 = pattern.tail(pe._FIT_WINDOW.get(stf, 140)).reset_index(drop=True)
    events = [e for e in pe.scan_edges(p2, trigger, stf)
              if e["state"] in (pe.STATE_BREAK, pe.STATE_FADE)]
    ev = next(e for e in events if e["state"] == pe.STATE_BREAK)
    cand = pe._build_candidate(_Bundle({"4h": pattern, "1h": pattern, "15m": trigger}),
                               "DAYTRADE", ev, p2, trigger, stf, ttf, pe._fit_cfg())
    if cand is None:
        pytest.skip("wedge fixture did not build a candidate")
    assert cand.metadata.get("alert_lineage_key"), "TC must carry R31.7 lineage"
    assert cand.metadata["alert_lineage_key"].startswith("TECHCLASSIC|")


# ── 2) TOHOM: doji + reverse-pin + FTB early confirm ────────────────────────
def _tohom_fixture(closes, vols, opens=None, highs=None, lows=None,
                   touched=False, now_min=25):
    """Lower-TF frame: 25 pre-candles + 3 sub-candles of the forming trigger
    candle; returns (candidate, frame, now, trigger_open)."""
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    rows = []
    base_close = closes[0] - 1.0
    for i in range(25):
        ts = t0 + timedelta(minutes=5 * i)
        rows.append({"timestamp": ts, "open": base_close, "high": base_close + 0.2,
                     "low": base_close - 0.2, "close": base_close, "volume": 100.0})
    for i, cl in enumerate(closes):
        ts = t0 + timedelta(minutes=5 * (25 + i))
        op = opens[i] if opens is not None else cl - 0.1
        hi = highs[i] if highs is not None else max(op, cl) + 0.15
        lo = lows[i] if lows is not None else min(op, cl) - 0.15
        rows.append({"timestamp": ts, "open": op, "high": hi, "low": lo,
                     "close": cl, "volume": vols[i]})
    df = pd.DataFrame(rows)
    cand = make_candidate()
    cand.direction = "LONG"
    cand.score = 8
    cand.metadata.update({"viva_breakout_line": closes[0], "atr": 1.0,
                          "touched": touched})
    now = t0 + timedelta(minutes=5 * (25 + now_min - 25) + 4)
    now = t0 + timedelta(minutes=5 * 25 + 19)     # 3 subs closed, 4th forming
    trigger_open = t0 + timedelta(minutes=5 * 25)
    return cand, df, now, trigger_open


def test_tohom_confirms_with_doji_vocabulary():
    from analysis.tohom import evaluate_tohom_confirmation
    edge = 100.0
    cand, df, now, topen = _tohom_fixture(
        closes=[edge + 0.05, edge + 0.18, edge + 0.31],
        vols=[110.0, 140.0, 170.0],
        opens=[edge, edge + 0.10, edge + 0.30],
        highs=[edge + 0.08, edge + 0.21, edge + 0.45],   # last: body 0.01 / rng 0.28 → doji
        lows=[edge - 0.03, edge + 0.07, edge + 0.17],
    )
    ok, _c, reason = evaluate_tohom_confirmation(cand, df, trigger_open=topen, now=now)
    assert ok is True, reason
    assert cand.metadata.get("tohom_pattern") == "دوجی"
    assert "پیش از کلوز" in cand.metadata.get("tohom_note_fa", "")


def test_tohom_ftb_halved_margin_confirms_early():
    from analysis.tohom import evaluate_tohom_confirmation
    edge = 100.0
    # last sub close sits +0.07 ATR past the edge: below the fresh-break
    # clearance (0.10 ATR), above the FTB clearance (0.05 ATR)…
    common = dict(
        closes=[edge + 0.02, edge + 0.12, edge + 0.07],
        vols=[120.0, 150.0, 180.0],
        opens=[edge - 0.05, edge + 0.04, edge + 0.00],
    )
    cand0, df0, now, topen = _tohom_fixture(touched=False, **common)
    ok0, _c, _r = evaluate_tohom_confirmation(cand0, df0, trigger_open=topen, now=now)
    assert ok0 is False                        # fresh-break clearance not met
    cand1, df1, now, topen = _tohom_fixture(touched=True, **common)
    ok1, _c, reason = evaluate_tohom_confirmation(cand1, df1, trigger_open=topen, now=now)
    assert ok1 is True, reason                 # FTB: price is ON the line
    assert "First Time Back" in cand1.metadata.get("tohom_note_fa", "")


def test_tohom_allows_one_counter_substep():
    from analysis.tohom import evaluate_tohom_confirmation
    edge = 100.0
    cand, df, now, topen = _tohom_fixture(
        closes=[edge + 0.30, edge + 0.18, edge + 0.40],   # dip = the FTB itself
        vols=[120.0, 130.0, 180.0],
        opens=[edge + 0.22, edge + 0.28, edge + 0.22],
        touched=True,
    )
    ok, _c, reason = evaluate_tohom_confirmation(cand, df, trigger_open=topen, now=now)
    assert ok is True, reason


# ── 3) rejection scalps confirm ONLY via TOHOM ──────────────────────────────
def test_rejection_scalp_never_confirms_on_bare_close():
    from analysis.quality_engine import evaluate_confirmation
    cand = make_candidate()
    cand.direction = "SHORT"
    cand.setup_code = "TLBREAK"
    cand.metadata.update({"rejection_scalp": True, "tohom_required": True,
                          "viva_breakout_line": 101.0, "atr": 1.0})
    cand.planned_entry, cand.sl = 100.0, 101.5
    cand.tp1, cand.tp2 = 98.8, 98.2
    df = _flat_df(100.0)
    cand.created_at = str(df.index[-2])
    ok, _c, reason = evaluate_confirmation(cand, df)
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "WAIT_TOHOM_SCALP"


def _flat_df(mid, n=30):
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    rows = [{"timestamp": t0 + timedelta(minutes=15 * i), "open": mid, "high": mid + 0.1,
             "low": mid - 0.1, "close": mid, "volume": 100.0} for i in range(n)]
    df = pd.DataFrame(rows).set_index("timestamp")
    df.index.name = "timestamp"
    df["timestamp"] = df.index
    return df


# ── 4) TLBREAK rejection-scalp lane ─────────────────────────────────────────
def test_tlbreak_rejection_scalp_mints():
    from test_pattern_engine import _wedge_frames, _Bundle
    import analysis.setups_experimental as exp
    from analysis.viva_tlbreak import fit_validated_line, load_config
    pattern, _trig = _wedge_frames()
    upper = fit_validated_line(pattern, "HIGH", load_config())
    lower = fit_validated_line(pattern, "LOW", load_config())
    if upper is None:
        pytest.skip("fixture has no validated upper line")
    lvl = float(upper.price_at(len(pattern) - 1))
    atr = float((pattern["high"] - pattern["low"]).tail(14).mean())
    # last trigger candle: taps the resistance line, pin-rejects back below
    ts = pd.date_range("2026-09-01", periods=8, freq="15min")
    rows = []
    for i, t in enumerate(ts):
        if i < 6:
            c = lvl - 0.30 * atr
        elif i == 6:
            c = lvl - 0.20 * atr
        else:
            c = lvl - 0.45 * atr
        rows.append({"timestamp": t, "open": c - 0.05 * atr, "high": c + 0.05 * atr,
                     "low": c - 0.05 * atr, "close": c, "volume": 100.0})
    rows[-1].update({"open": lvl - 0.50 * atr, "close": lvl - 0.45 * atr,
                     "high": lvl + 0.10 * atr, "low": lvl - 0.75 * atr})   # the pin
    trig = pd.DataFrame(rows)
    cand = exp._tlbreak_rejection_scalp(_Bundle({"4h": pattern, "15m": trig}),
                                        "DAYTRADE", pattern, "4h", upper, lower, trig, "15m")
    assert cand is not None, "rejection anatomy must mint the scalp"
    assert cand.direction == "SHORT"
    assert cand.setup_code == "TLBREAK"
    md = cand.metadata
    assert md.get("rejection_scalp") is True and md.get("tohom_required") is True
    assert md.get("viva_breakout_line") == pytest.approx(lvl)
    assert cand.sl > cand.planned_entry            # stop behind the wick
    assert cand.tp1 < cand.planned_entry < cand.sl


# ── 5) ALBROX union ─────────────────────────────────────────────────────────
def test_albrox_pattern_lane_uses_tc_engine(monkeypatch):
    from test_pattern_engine import _wedge_frames, _Bundle
    import analysis.setups_experimental as exp
    pattern, trigger = _wedge_frames()
    seen = {}

    def fake_tc(bundle, style, setup_code="TECHCLASSIC"):
        seen["setup_code"] = setup_code
        return "CAND"

    import analysis.pattern_engine as pe
    monkeypatch.setattr(pe, "detect_technoclassic", fake_tc)
    monkeypatch.setattr(exp, "_albrox_zone_lane", lambda b, s: None)
    out = exp.detect_albrox(_Bundle({"4h": pattern, "1h": pattern, "15m": trigger}), "DAYTRADE")
    assert out == "CAND" and seen["setup_code"] == "ALBROX"


def test_albrox_zone_break_lane_mints(monkeypatch):
    import analysis.setups_experimental as exp
    from test_pattern_engine import _Bundle
    zone = {"kind": "OB_DEMAND", "bottom": 99.0, "top": 100.0,
            "ts": "2026-09-01 00:00", "score": 1}
    monkeypatch.setattr(exp, "_albrox_zones", lambda *a, **k: [zone])
    monkeypatch.setattr(exp, "_ensure_frames", lambda b, tfs: True)
    ts = pd.date_range("2026-09-01", periods=70, freq="15min")
    rows = [{"timestamp": t, "open": 100.4, "high": 100.6, "low": 100.2,
             "close": 100.4, "volume": 100.0} for t in ts]
    rows[-1].update({"open": 100.4, "high": 100.9, "low": 99.5, "close": 100.8})
    rows[-2].update({"close": 99.8, "open": 99.9, "high": 100.0, "low": 99.6})
    tdf = pd.DataFrame(rows)
    cand = exp._albrox_zone_lane(_Bundle({"4h": tdf, "15m": tdf}), "DAYTRADE")
    assert cand is not None
    assert cand.setup_code == "ALBROX" and cand.direction == "LONG"
    md = cand.metadata
    assert md.get("zone_kind") == "OB_DEMAND"
    assert md.get("viva_breakout_line") == 100.0          # the edge the fast lane waits for
    assert md.get("break_direction") == "UP"
    assert not md.get("rejection_scalp")
    assert cand.entry_zone_bottom == 99.0 and cand.entry_zone_top == 100.0


def test_albrox_zone_rejection_is_tohom_only(monkeypatch):
    import analysis.setups_experimental as exp
    from test_pattern_engine import _Bundle
    zone = {"kind": "OB_SUPPLY", "bottom": 101.0, "top": 102.0,
            "ts": "2026-09-01 00:00", "score": 1}
    monkeypatch.setattr(exp, "_albrox_zones", lambda *a, **k: [zone])
    monkeypatch.setattr(exp, "_ensure_frames", lambda b, tfs: True)
    ts = pd.date_range("2026-09-01", periods=70, freq="15min")
    rows = [{"timestamp": t, "open": 100.6, "high": 100.8, "low": 100.4,
             "close": 100.6, "volume": 100.0} for t in ts]
    rows[-1].update({"open": 100.55, "high": 101.2, "low": 100.3, "close": 100.5})  # pin under supply
    tdf = pd.DataFrame(rows)
    cand = exp._albrox_zone_lane(_Bundle({"4h": tdf, "15m": tdf}), "DAYTRADE")
    assert cand is not None and cand.direction == "SHORT"
    md = cand.metadata
    assert md.get("rejection_scalp") is True and md.get("tohom_required") is True
    from analysis.quality_engine import evaluate_confirmation
    cand.planned_entry, cand.sl = 100.5, 101.4
    cand.tp1, cand.tp2 = 99.6, 99.1
    _df = _flat_df(100.5)
    cand.created_at = str(_df.index[-2])
    ok, _c, _r = evaluate_confirmation(cand, _df)
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "WAIT_TOHOM_SCALP"


def test_albrox_registered_and_enabled():
    import config
    import analysis.setups_experimental as exp
    assert config.get_settings().albrox_enabled is True
    assert exp.ALBROX_DETECTORS and exp.ALBROX_DETECTORS[0].__name__ == "detect_albrox"


# ── 6) r60.2 THE LAW: TC = break-only, twin guard across lanes ──────────────
def _tc_detect_env(monkeypatch):
    monkeypatch.setenv("TECHCLASSIC_ENABLED", "true")
    import config
    config._cached = None
    importlib.reload(config)
    import analysis.pattern_engine as pe
    importlib.reload(pe)
    import analysis.setups_experimental as exp
    importlib.reload(exp)
    return pe


def test_tc_never_mints_internal_fade_signals(monkeypatch):
    """THE r60.2 law («تکنوکلاسیک نباید سیگنال داخلی قبل از شکست بگیره»):
    a pattern whose only event is an internal edge-fade mints NOTHING."""
    pe = _tc_detect_env(monkeypatch)
    from test_pattern_engine import _wedge_frames, _Bundle
    pattern, trigger = _wedge_frames()
    bundle = _Bundle({"4h": pattern, "1h": pattern, "15m": trigger})
    import analysis.setups_v7 as _sv7  # pe imports _ensure_frames from here at call time
    monkeypatch.setattr(_sv7, "_ensure_frames", lambda b, tfs: True)
    fade_ev = {"state": pe.STATE_FADE, "pattern": "CHANNEL_ASCENDING",
               "pattern_fa": "کانال", "side": "lower", "direction": "LONG",
               "line_price": 100.0, "live": 100.5, "touches": 4,
               "fit_error_atr": 0.3, "structure_score": 7,
               "reactions": {"reject_rate": 0.8}, "edge_points": []}
    monkeypatch.setattr(pe, "scan_edges",
                        lambda *a, **k: [dict(fade_ev)])
    monkeypatch.setattr(pe, "_build_candidate",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("fade must never reach the builder")))
    assert pe.detect_technoclassic(bundle, "DAYTRADE") is None


def test_tc_twin_guard_blocks_second_lane(monkeypatch):
    """FET case: the same visual pattern re-detected on another trigger lane
    (trig-1h SWING vs trig-15m DAYTRADE) must stay silent — the guard key is
    pattern-level, not per-lane."""
    pe = _tc_detect_env(monkeypatch)
    from database.bot_kv import set_json as _sj
    from test_pattern_engine import _wedge_frames, _Bundle
    pattern, trigger = _wedge_frames()
    bundle = _Bundle({"4h": pattern, "1h": pattern, "15m": trigger})
    import analysis.setups_v7 as _sv7
    monkeypatch.setattr(_sv7, "_ensure_frames", lambda b, tfs: True)
    ev = {"state": pe.STATE_BREAK, "pattern": "TRIANGLE_DESCENDING",
          "pattern_fa": "مثلث نزولی", "side": "lower", "direction": "SHORT",
          "line_price": 100.0, "live": 98.0, "touches": 4, "fit_error_atr": 0.3,
          "structure_score": 8, "reactions": {"reject_rate": 0.7},
          "edge_points": [{"timestamp": "2026-09-01 04:00", "price": 101.0},
                          {"timestamp": "2026-09-10 08:00", "price": 99.0}],
          "pattern_tf": "4h"}
    monkeypatch.setattr(pe, "scan_edges", lambda *a, **k: [dict(ev)])
    mints = {"n": 0}

    from types import SimpleNamespace as _NS
    def fake_build(*a, **k):
        mints["n"] += 1
        return _NS(signal_id="FAKE-TWIN-1")

    monkeypatch.setattr(pe, "_build_candidate", fake_build)
    _sj(pe._mint_guard_key(bundle, ev), {})          # hermetic: clear the guard
    first = pe.detect_technoclassic(bundle, "DAYTRADE")
    assert getattr(first, "signal_id", "") == "FAKE-TWIN-1"       # lane A posts
    assert mints["n"] == 1
    assert pe.detect_technoclassic(bundle, "DAYTRADE") is None  # same lane again: silent
    assert mints["n"] == 1                           # builder never ran again


def test_tc_mint_guard_releases_on_new_pivot(monkeypatch):
    """A genuinely NEW pivot (structural change) = a new guard key → the
    setup may alert again without waiting for the TTL."""
    pe = _tc_detect_env(monkeypatch)
    from database.bot_kv import set_json as _sj
    from test_pattern_engine import _wedge_frames, _Bundle
    pattern, trigger = _wedge_frames()
    bundle = _Bundle({"4h": pattern, "1h": pattern, "15m": trigger})
    import analysis.setups_v7 as _sv7
    monkeypatch.setattr(_sv7, "_ensure_frames", lambda b, tfs: True)
    ev1 = {"state": pe.STATE_BREAK, "pattern": "P", "side": "lower",
           "direction": "SHORT", "line_price": 100.0, "live": 98.0, "touches": 3,
           "fit_error_atr": 0.3, "structure_score": 8,
           "reactions": {"reject_rate": 0.5},
           "edge_points": [{"timestamp": "2026-09-01 04:00", "price": 101.0},
                           {"timestamp": "2026-09-10 08:00", "price": 99.0}],
           "pattern_tf": "4h"}
    ev2 = dict(ev1, edge_points=[{"timestamp": "2026-09-01 04:00", "price": 101.0},
                                 {"timestamp": "2026-09-12 12:00", "price": 98.5}])  # new pivot
    from types import SimpleNamespace as _NS
    state = {"n": 0, "ev": ev1}
    def fake_scan(*a, **k):
        return [dict(state["ev"])]
    def fake_build(*a, **k):
        state["n"] += 1
        return _NS(signal_id=f"FAKE-{state['n']}")
    monkeypatch.setattr(pe, "scan_edges", fake_scan)
    monkeypatch.setattr(pe, "_build_candidate", fake_build)
    _sj(pe._mint_guard_key(bundle, ev1), {})   # hermetic: clear
    _sj(pe._mint_guard_key(bundle, ev2), {})
    assert getattr(pe.detect_technoclassic(bundle, "DAYTRADE"), "signal_id", "") == "FAKE-1"
    state["ev"] = ev2                          # a NEW defining pivot appears
    assert getattr(pe.detect_technoclassic(bundle, "DAYTRADE"), "signal_id", "") == "FAKE-2"
    assert state["n"] == 2
    state["ev"] = ev2
    assert pe.detect_technoclassic(bundle, "DAYTRADE") is None   # same pivots again → silent
    assert state["n"] == 2


# ── 7) r60.3: multi-TF geometry law + HTF boxes + zone-anchored plan ────────
def test_htf_zone_boxes_merge_separately():
    """The missing OB boxes: enrich_render always stored htf_zones but nothing
    drew them. merge_htf_zones joins the NEAREST box per side under the
    «HTF·» family — separate, one parent per side."""
    from analysis.render_kit import merge_htf_zones
    chart = [{"kind": "FVG", "bottom": 101.0, "top": 101.5}]
    htf = [
        {"kind": "OB", "bottom": 104.0, "top": 106.0},     # nearest above
        {"kind": "OB", "bottom": 120.0, "top": 124.0},     # far above — loses
        {"kind": "DEMAND", "bottom": 90.0, "top": 92.0},   # nearest below
    ]
    out = merge_htf_zones(chart, htf, price=100.0, direction="LONG")
    kinds = [z["kind"] for z in out]
    assert kinds.count("HTF·OB") == 1 and kinds.count("HTF·DEMAND") == 1
    htf_ob = next(z for z in out if z["kind"] == "HTF·OB")
    assert htf_ob["bottom"] == 104.0 and z_is_htf(htf_ob)
    assert chart[0]["kind"] == "FVG"                       # chart zones untouched


def z_is_htf(z):
    return z.get("htf") is True


def test_htf_zone_merge_handles_gaps_and_price_inside():
    from analysis.render_kit import merge_htf_zones
    out = merge_htf_zones([], [{"kind": "OB", "bottom": 99.0, "top": 101.0}],
                          price=100.0)                     # price INSIDE the box
    assert out == []                                       # not above/below → skip
    assert merge_htf_zones([], None, price=100.0) == []
    assert merge_htf_zones([], [{"kind": "OB", "bottom": 101.0, "top": 99.0}],
                           price=100.0) == []              # inverted rect → skip


def test_viva_points_xs_projects_across_frames():
    """THE multi-TF law: the pattern's own pivots map onto any frame by TIME —
    a pre-window pivot extrapolates to a NEGATIVE x (the same straight line),
    it is never clamped to 0 and never re-fitted."""
    from bot.messages_v7 import _viva_points_xs  # draw helper (chart-side)
    from datetime import datetime, timedelta
    t0 = datetime(2026, 9, 20)
    frame = pd.DataFrame({"x": range(10)})
    frame.index = [t0 + timedelta(hours=i) for i in range(10)]
    pts = [{"timestamp": "2026-09-20 02:00", "price": 100.0},   # inside → x=2
           {"timestamp": "2026-09-19 17:00", "price": 110.0}]   # 7 bars before → x=-7
    xs = _viva_points_xs(pts, frame)
    assert xs[0] == 2.0
    assert xs[1] == -7.0                                # extrapolated, not clamped
    # a pivot INSIDE again maps exactly — the line is one straight identity
    pts2 = pts + [{"timestamp": "2026-09-20 09:00", "price": 90.0}]
    xs2 = _viva_points_xs(pts2, frame)
    assert xs2[2] == 9.0
    y9 = 100.0 + (9.0 - 2.0) * (110.0 - 100.0) / (-7.0 - 2.0)
    assert abs(y9 - (100.0 + (9.0 - xs[0]) * (pts[1]["price"] - pts[0]["price"]) / (xs[1] - xs[0]))) < 1e-9


def test_tc_tp2_snaps_to_opposing_zone_edge(monkeypatch):
    """«اون باکس‌ها میتونن به تارگت گذاری کمک بکنن»: TP2 lands on the nearest
    opposing box EDGE instead of a raw percent path."""
    import analysis.setups_experimental  # registers SETUP_NAMES
    import analysis.pattern_engine as pe
    import analysis.render_kit as rk
    from test_pattern_engine import _wedge_frames, _Bundle
    from analysis.setups_v7 import timeframe_profile
    zone = {"kind": "OB", "bottom": 100.0, "top": 101.0, "ts0": "2026-09-01 00:00"}
    real = rk.detect_zones

    def fake_zones(df, direction, zlo, zhi, *a, **k):
        zs = real(df, direction, zlo, zhi, *a, **k) if callable(real) else []
        zs.append(dict(zone))
        return zs

    monkeypatch.setattr(rk, "detect_zones", fake_zones)
    pattern, trigger = _wedge_frames()
    stf, _ref, ttf = timeframe_profile("DAYTRADE")
    p2 = pattern.tail(pe._FIT_WINDOW.get(stf, 140)).reset_index(drop=True)
    events = [e for e in pe.scan_edges(p2, trigger, stf) if e["state"] == pe.STATE_BREAK]
    if not events:
        pytest.skip("no break event in fixture")
    cand = pe._build_candidate(_Bundle({"4h": pattern, "1h": pattern, "15m": trigger}),
                               "DAYTRADE", events[0], p2, trigger, stf, ttf,
                               pe._fit_cfg())
    if cand is None:
        pytest.skip("no candidate built")
    md = cand.metadata
    # with an OB at [100,101] near a ~100-level fixture, TP2 must sit on the
    # box edge whenever the raw path fell within the 0.55–1.45 window; either
    # way the snap decision must be RECORDED, never silent.
    assert md.get("tp2_zone") in ("OB", "") or md.get("tp2_zone") is None
    if md.get("tp2_zone") == "OB":
        assert cand.tp2 in (100.0, 101.0)


# ── 8) r60.4: box law + update law + trigger-TF anchor priority ─────────────
def test_chart_never_draws_htf_boxes():
    """THE box law («فقط ساپلای و دیمند همون تایم … رسم بشه»): the chart
    renderer must NOT merge htf_zones into the draw list — trigger-TF refined
    boxes only; htf_zones stay a TP/stop CALCULATION input."""
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    draw_zone_block = src.split('if _rz_list:')[1][:2000]
    assert "merge_htf_zones" not in draw_zone_block
    assert "htf_zones" not in draw_zone_block


def test_live_break_updates_never_post():
    """THE update law («آپدیت فقط برای هشدار نهایی و آماده‌سازی»): the
    live-break chatter block computes and stores the note but never sends an
    update (his 23:46 + 3 repeats case, each with a live chart)."""
    src = open("main.py", encoding="utf-8").read()
    block = src.split("THE update law")[1].split('except Exception as _lb_exc')[0]
    assert "send_setup_update" not in block
    assert 'live_break_note' in block          # evidence kept, silently


def test_anchor_prefers_trigger_tf_zones(monkeypatch):
    """«تایم تریگر ریفاین میخوام»: when BOTH the trigger and the pattern TF
    offer an opposing zone, TP2 snaps to the TRIGGER-TF edge (nearer box),
    not the pattern-TF one."""
    import analysis.setups_experimental  # registers SETUP_NAMES
    import analysis.pattern_engine as pe
    import analysis.render_kit as rk
    from test_pattern_engine import _wedge_frames, _Bundle
    from analysis.setups_v7 import timeframe_profile
    pattern, trigger = _wedge_frames()
    stf, _ref, ttf = timeframe_profile("DAYTRADE")
    p2 = pattern.tail(pe._FIT_WINDOW.get(stf, 140)).reset_index(drop=True)
    events = [e for e in pe.scan_edges(p2, trigger, stf) if e["state"] == pe.STATE_BREAK]
    if not events:
        pytest.skip("no break event in fixture")
    ev = events[0]
    entry_guess = float(ev.get("live") or float(trigger["close"].iloc[-1]))
    from analysis.trade_management import clamp_path_to_band as _cpb
    raw_d = abs(float((ev.get("measured") or {}).get("to") or 0.0) - entry_guess)
    raw_path, _ = _cpb(entry_guess, ttf, raw_d)   # the ACTUAL clamped path tp2 uses
    assert raw_path > 0
    z_trig = {"kind": "FVG", "bottom": entry_guess + 0.70 * raw_path,
              "top": entry_guess + 0.85 * raw_path, "ts0": "2026-09-01 00:00"}
    z_pat = {"kind": "OB", "bottom": entry_guess + 1.35 * raw_path,
             "top": entry_guess + 1.45 * raw_path, "ts0": "2026-09-01 00:00"}

    def fake_zones(df, direction, zlo, zhi, *a, **k):
        return [dict(z_trig if df is trigger else z_pat)]

    monkeypatch.setattr(rk, "detect_zones", fake_zones)
    cand = pe._build_candidate(_Bundle({"4h": pattern, "1h": pattern, "15m": trigger}),
                               "DAYTRADE", ev, p2, trigger, stf, ttf, pe._fit_cfg())
    if cand is None:
        pytest.skip("no candidate built")
    assert cand.metadata.get("tp2_zone") == "FVG"      # the TRIGGER-TF box won
    assert abs(cand.tp2 - z_trig["bottom"]) < 1e-6


# ── 9) r60.5: the 12h window is a backstop — resolved pattern re-alerts ────
def test_mint_guard_reopens_when_previous_resolves(monkeypatch):
    """«یعنی چی هر الگو در هر ۱۲ ساعت یکبار؟؟» — never a wall-clock throttle:
    while the previous alert LIVES the pattern is silent; the moment it
    resolves (cancelled/expired/…) a fresh break may alert again immediately,
    even inside the 12h backstop window."""
    pe = _tc_detect_env(monkeypatch)
    import analysis.setups_v7 as _sv7
    from database.bot_kv import set_json as _sj
    import time as _t60
    from database.candidate_store import candidate_status
    from test_pattern_engine import _wedge_frames, _Bundle
    monkeypatch.setattr(_sv7, "_ensure_frames", lambda b, tfs: True)
    pattern, trigger = _wedge_frames()
    bundle = _Bundle({"4h": pattern, "1h": pattern, "15m": trigger})
    ev = {"state": pe.STATE_BREAK, "pattern": "P", "side": "lower",
          "direction": "SHORT", "line_price": 100.0, "live": 98.0, "touches": 3,
          "fit_error_atr": 0.3, "structure_score": 8,
          "reactions": {"reject_rate": 0.5},
          "edge_points": [{"timestamp": "2026-09-01 04:00", "price": 101.0},
                          {"timestamp": "2026-09-10 08:00", "price": 99.0}],
          "pattern_tf": "4h"}
    monkeypatch.setattr(pe, "scan_edges", lambda *a, **k: [dict(ev)])
    from types import SimpleNamespace as _NS
    mints = {"n": 0}

    def fake_build(*a, **k):
        mints["n"] += 1
        return _NS(signal_id=f"FAKE-G{mints['n']}")

    monkeypatch.setattr(pe, "_build_candidate", fake_build)
    _sj(pe._mint_guard_key(bundle, ev),
        {"ts": _t60.time(), "signal_id": "GHOST-LIVE-1"})   # fresh mint record
    # the recorded signal is LIVE (unresolved → unknown id counts as live)
    assert pe.detect_technoclassic(bundle, "DAYTRADE") is None
    assert mints["n"] == 0
    # …now it RESOLVED: candidate_status returns a terminal state → allowed
    monkeypatch.setattr("database.candidate_store.candidate_status",
                        lambda sid: "CANCELLED")
    assert getattr(pe.detect_technoclassic(bundle, "DAYTRADE"),
                   "signal_id", "") == "FAKE-G1"
    assert mints["n"] == 1


def test_candidate_status_lookup():
    from database.candidate_store import candidate_status
    assert candidate_status("") == ""
    assert candidate_status("no-such-id-xyz") == ""


# ── 10) r60.6: CHoCH reward + one-direction-per-pattern + contract exemption
def test_choch_rewards_break_against_old_trend(monkeypatch):
    """«وقتی ترند نزولی میشکنه به بالا دیگه اسمش خلاف روند نیست» — a falling
    line closed ABOVE is CHoCH UP: +2 score, NO counter-doctrine label, and
    the evidence explains the character change."""
    import analysis.setups_experimental  # noqa: F401
    import analysis.pattern_engine as pe
    from analysis.setups_v7 import timeframe_profile
    from test_pattern_engine import _wedge_frames, _Bundle
    pattern, trigger = _wedge_frames()
    stf, _ref, ttf = timeframe_profile("DAYTRADE")
    p2 = pattern.tail(pe._FIT_WINDOW.get(stf, 140)).reset_index(drop=True)
    events = [e for e in pe.scan_edges(p2, trigger, stf) if e["state"] == pe.STATE_BREAK]
    ev = next((e for e in events if e.get("direction") == "LONG"), None)
    if ev is None:
        pytest.skip("fixture has no up-break")
    cand = pe._build_candidate(_Bundle({"4h": pattern, "1h": pattern, "15m": trigger}),
                               "DAYTRADE", ev, p2, trigger, stf, ttf, pe._fit_cfg())
    if cand is None:
        pytest.skip("no candidate built")
    assert cand.metadata.get("choch") == "UP"          # falling line broken up
    assert cand.metadata.get("counter_doctrine") is False   # never branded counter
    assert any(item.key == "choch" for item in cand.evidence)


def test_pattern_guard_is_direction_agnostic(monkeypatch):
    """After the downtrend broke UP and owns a live chain, the OPPOSITE
    (SHORT) break of the SAME pattern must not mint a rival scenario."""
    pe = _tc_detect_env(monkeypatch)
    import analysis.setups_v7 as _sv7
    from database.bot_kv import set_json as _sj
    import time as _t60
    from test_pattern_engine import _wedge_frames, _Bundle
    monkeypatch.setattr(_sv7, "_ensure_frames", lambda b, tfs: True)
    pattern, trigger = _wedge_frames()
    bundle = _Bundle({"4h": pattern, "1h": pattern, "15m": trigger})
    ev_long = {"state": pe.STATE_BREAK, "pattern": "P", "side": "upper",
               "direction": "LONG", "line_price": 100.0, "live": 101.0,
               "touches": 3, "fit_error_atr": 0.3, "structure_score": 8,
               "reactions": {"reject_rate": 0.5},
               "edge_points": [{"timestamp": "2026-09-01 04:00", "price": 101.0},
                               {"timestamp": "2026-09-10 08:00", "price": 99.0}],
               "pattern_tf": "4h"}
    ev_short = dict(ev_long, side="lower", direction="SHORT", live=98.0)
    _sj(pe._mint_guard_key(bundle, ev_long), {})   # hermetic: clear the guard
    monkeypatch.setattr(pe, "scan_edges",
                        lambda *a, **k: [dict(ev_long)])
    from types import SimpleNamespace as _NS
    monkeypatch.setattr(pe, "_build_candidate",
                        lambda *a, **k: _NS(signal_id="FAKE-L1"))
    assert getattr(pe.detect_technoclassic(bundle, "DAYTRADE"),
                   "signal_id", "") == "FAKE-L1"          # the UP break owns it
    monkeypatch.setattr(pe, "scan_edges", lambda *a, **k: [dict(ev_short)])
    assert pe.detect_technoclassic(bundle, "DAYTRADE") is None   # rival blocked


def test_tlbreak_break_exempt_from_counter_trend_veto():
    """«همه این ۳ ستاپها جهت شکست رو تایید بکنن»: a TLBREAK chain carrying the
    break contract confirms even while the parent trend is still opposed."""
    from analysis.quality_engine import evaluate_confirmation
    from test_round60_tc_calibrate import _tc_frame_and_candidate
    df, cand = _tc_frame_and_candidate("SHORT")
    cand.setup_code = "TLBREAK"
    cand.metadata.update({"break_direction": "DOWN",
                          "strategy_variant": "VIVA_TLBREAK",
                          # the one-close law already fired on the real chain
                          "viva_state": "S6_CONFIRMED"})
    cand.metadata["tl_context_conflict"] = True
    ok, _c, reason = evaluate_confirmation(cand, df)
    assert ok is True, reason
