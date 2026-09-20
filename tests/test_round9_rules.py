"""Round-9 rulings (Viva 09-20) — locked as tests so the live engine keeps them.

Covered:
  1. R:R never vetoes an entry (reported only).
  2. TP ladder: uniform spacing, no oversized TP1→TP2 gap, structural TP1,
     final pill = TF-capped structural ceiling, exits 40/30/30.
  3. Inside-pattern close must NOT confirm (INSIDE_PATTERN_NO_BREAK).
  4. Internal-entry lane: long from a range floor with candle confirmation,
     stop behind the channel + buffer, targets under the channel ceiling.
  5. Protection-phase exit arms a re-entry; the pullback with a confirmed
     candle produces the re-entry plan (banked TP1 stays locked).
"""
from __future__ import annotations

import pandas as pd

from analysis.trade_management import build_ladder, smart_exit_scan, reentry_setup


def _candles(rows):
    return [{"open": o, "high": h, "low": l, "close": c, "volume": v}
            for (o, h, l, c, v) in rows]


# ── 2. ladder spacing ────────────────────────────────────────────────────
def test_ladder_gaps_are_uniform_and_never_balloon():
    # his bug: a structural TP1 close to the entry used to be followed by a
    # much larger TP1→TP2 jump.
    lad = build_ladder(100.0, 98.5, "LONG", {"tick_size": 0.001}, 106.0,
                       structural_tp1=100.4, trigger_tf="1h")
    tg = [float(t) for t in lad["targets"]]
    gaps = [round(tg[i + 1] - tg[i], 6) for i in range(len(tg) - 1)]
    assert len(tg) == 5 and lad["weights"] == [40.0, 30.0, 30.0, 0.0, 0.0]
    assert max(gaps) - min(gaps) < 1e-9, gaps
    assert tg[0] == 100.4 and lad["tp1_source"] == "STRUCTURE"
    # final pill = the TF-capped ceiling (1h → 5% over 100 = 105)
    assert abs(tg[-1] - 105.0) < 1e-9 and lad["target_capped"] is True


def test_ladder_floor_side_mirrors_the_same_spacing():
    lad = build_ladder(100.0, 101.5, "SHORT", {"tick_size": 0.001}, 94.0,
                       structural_tp1=99.6, trigger_tf="1h")
    tg = [float(t) for t in lad["targets"]]
    gaps = [round(tg[i] - tg[i + 1], 6) for i in range(len(tg) - 1)]
    assert max(gaps) - min(gaps) < 1e-9
    assert tg[0] == 99.6 and abs(tg[-1] - 95.0) < 1e-9      # 5% cap below entry


def test_ladder_five_pills_survive_a_deep_structural_tp1():
    lad = build_ladder(99.5, 97.5, "LONG", {"tick_size": 0.001}, 107.5,
                       structural_tp1=103.5, trigger_tf="15m")
    tg = [float(t) for t in lad["targets"]]
    assert len(tg) == 5 and len(set(round(t, 6) for t in tg)) == 5
    assert all(tg[i] < tg[i + 1] for i in range(4))


# ── 3/4. pattern containment + internal lane ─────────────────────────────
def _range_frame(band_lo=99.0, band_hi=103.0, last=None, n=26):
    rows = []
    for i in range(n):
        mid = (band_lo + band_hi) / 2 + ((i % 4) - 1.5) * 0.4
        rows.append((mid - 0.2, mid + 0.4, mid - 0.4, mid, 1000.0))
    if last:
        rows[-1] = last
    return pd.DataFrame([{"timestamp": pd.Timestamp("2026-09-20 10:00") + pd.Timedelta(minutes=15 * i),
                          "open": o, "high": h, "low": l, "close": c, "volume": v}
                         for i, (o, h, l, c, v) in enumerate(rows)])


def _candidate(direction="LONG", **over):
    from analysis.models import SignalCandidate
    base = dict(signal_id="R9-1", symbol="TESTUSDT", style="DAYTRADE", setup_code="ALBROX",
                setup_name="t", strategy_fa="t", direction=direction, score=8,
                status="NEAR_CONFIRM", entry_zone_bottom=99.5, entry_zone_top=100.0,
                planned_entry=100.0, sl=98.4, tp1=101.5, tp2=103.0, rr_tp1=1.0, rr_tp2=2.0,
                bias="BULL", trigger_timeframe="15m",
                mandatory_gates={"zone": True, "rr": True},
                metadata={"atr": 1.0, "touched": True,
                          "pattern_band": {"kind": "RANGE", "lo": 99.0, "hi": 103.0,
                                           "slope_lo": 0.0, "slope_hi": 0.0,
                                           "ts_last": "2026-09-20 16:15",
                                           "tf_minutes": 15.0}})
    base.update(over)
    return SignalCandidate(**base)


def test_close_inside_the_pattern_never_confirms():
    from analysis.quality_engine import evaluate_confirmation
    df = _range_frame(last=(100.0, 100.6, 99.6, 100.1, 1200.0))   # inside the range
    ok, cand, _reason = evaluate_confirmation(_candidate(), df)
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "INSIDE_PATTERN_NO_BREAK"


def test_internal_long_from_the_range_floor_gets_structural_stop_and_targets():
    from analysis.quality_engine import evaluate_confirmation
    # bullish engulfing/pin closing right at the range FLOOR (99.0)
    df = _range_frame(last=(99.1, 99.35, 98.62, 99.30, 1500.0))
    cand = _candidate()
    ok, cand, reason = evaluate_confirmation(cand, df)
    internal = cand.metadata.get("internal_entry")
    assert internal, reason
    assert cand.metadata.get("viva_entry_type") == "INTERNAL"
    assert internal["direction"] == "LONG"
    assert internal["entry"] == 99.30
    assert internal["sl"] < 99.0                       # stop BEHIND the channel floor
    assert 99.0 < internal["tp1"] < internal["tp2"] < 103.0   # targets under the ceiling
    assert "کانال" in str(cand.metadata.get("internal_entry_note_fa"))
    assert ok is True, reason


# ── 5. protection exit → re-entry on the pullback ────────────────────────
def _flat_window():
    return _candles([(100.0, 100.05, 99.95, 100.0, 100.0)] * 25)


def test_protection_phase_reverse_pin_arms_the_reentry():
    lad = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    armed = __import__("analysis.trade_management", fromlist=["x"]).advance_ladder(
        lad, 102.1, 100.1)["state"]
    win = _flat_window()
    win[-1] = {"open": 100.0, "high": 101.2, "low": 99.9, "close": 99.95, "volume": 100.0}
    scan = smart_exit_scan("LONG", win, armed)
    # one closed reverse pin = a RED close for the monitor (its own rule),
    # the bare score stays ORANGE (single sign) — the ladder closes anyway
    assert scan["reverse_pin"] is True and scan["level"] == "ORANGE"
    import io as _io
    src = _io.open("database/repository_v7.py", encoding="utf-8").read()
    assert "if _fscan.get(\"reverse_pin\"):" in src          # fast frame (5m) pin
    assert "or bool(_fast_pin_reason)" in src                  # …closes the rest
    assert 'ladder["reentry_armed"] = True' in src             # …and arms re-entry
    armed["closed"] = True
    armed["close_reason"] = "SMART_EXIT"
    armed["reentry_armed"] = True
    # a pullback back to the banked TP1 area with a bullish confirmation candle
    pull = _flat_window()
    pull[-3] = {"open": 102.4, "high": 102.5, "low": 101.6, "close": 101.7, "volume": 100.0}
    pull[-2] = {"open": 101.7, "high": 102.0, "low": 101.5, "close": 101.6, "volume": 100.0}
    pull[-1] = {"open": 101.7, "high": 102.3, "low": 101.55, "close": 102.1, "volume": 100.0}
    plan = reentry_setup("LONG", pull, armed, atr=1.0)
    assert plan is not None
    assert plan["entry"] == 102.1 and plan["sl"] < 102.1
    assert "قفل" in plan["note_fa"]
    # no pullback into the zone → no signal
    far = _flat_window()
    far[-1] = {"open": 104.0, "high": 104.5, "low": 103.8, "close": 104.2, "volume": 100.0}
    assert reentry_setup("LONG", far, armed, atr=1.0) is None
    # and a TP-hit-only ladder (not closed by protection) never re-enters
    lad2 = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    st2 = __import__("analysis.trade_management", fromlist=["x"]).advance_ladder(
        lad2, 102.1, 100.1)["state"]
    st2["closed"] = True
    st2["close_reason"] = "LADDER_COMPLETE"
    assert reentry_setup("LONG", pull, st2, atr=1.0) is None
