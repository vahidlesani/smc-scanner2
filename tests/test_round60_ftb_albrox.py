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
