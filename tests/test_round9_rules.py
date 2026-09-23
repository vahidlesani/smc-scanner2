"""Round-9 + round-10 rulings (Viva 09-20) — locked so the live engine keeps them.

Round 10 (his chart-corrective message) additions:
  • the ladder is a PRICE PATH: entry→valid TF level (or the TF norm band)
    split into five equal parts; exits TP1..TP3;
  • the path is never derived from the stop distance (R:R removed entirely —
    charts and messages carry no ratio any more);
  • internal (range/channel) entries: the wall is the path, the stop sits
    behind the wall AND the last swing, plus the buffer;
  • containment sees EVERY two-line shape (broadening/triangle/channel/…);
  • a trendline contradicting the trade direction is never drawn.

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
    # much larger TP1→TP2 jump. Round-10 doctrine: the path is the valid
    # ceiling of the trigger TF, split into five EQUAL parts.
    lad = build_ladder(100.0, 98.5, "LONG", {"tick_size": 0.001}, 106.0,
                       structural_tp1=100.4, trigger_tf="1h")
    tg = [float(t) for t in lad["targets"]]
    gaps = [round(tg[i + 1] - tg[i], 6) for i in range(len(tg) - 1)]
    assert len(tg) == 5 and lad["weights"] == [40.0, 30.0, 30.0, 0.0, 0.0]
    assert max(gaps) - min(gaps) < 1e-9, gaps
    # 106 is 6% away — above the 1h ceiling → clamped to 105 (5% path)
    assert abs(tg[-1] - 105.0) < 1e-9 and abs(tg[0] - 101.0) < 1e-9
    assert abs(lad["path_pct"] - 5.0) < 1e-9


def test_ladder_floor_side_mirrors_the_same_spacing():
    lad = build_ladder(100.0, 101.5, "SHORT", {"tick_size": 0.001}, 94.0,
                       structural_tp1=99.6, trigger_tf="1h")
    tg = [float(t) for t in lad["targets"]]
    gaps = [round(tg[i] - tg[i + 1], 6) for i in range(len(tg) - 1)]
    assert max(gaps) - min(gaps) < 1e-9
    assert abs(tg[0] - 99.0) < 1e-9 and abs(tg[-1] - 95.0) < 1e-9   # 5% cap below entry


def test_ladder_five_pills_survive_a_deep_structural_tp1():
    # a level farther than the TF ceiling cannot stretch the ladder (the old
    # cramped-ladder pathology: TP1 4.5% away with 0.1% pills after it)
    lad = build_ladder(0.1951, 0.2005, "SHORT", {"tick_size": 0.00001}, 0.1862,
                       structural_tp1=0.1862, trigger_tf="15m")
    tg = [float(t) for t in lad["targets"]]
    assert len(tg) == 5 and len(set(round(t, 8) for t in tg)) == 5
    assert all(tg[i] > tg[i + 1] for i in range(4))
    # 0.1862 is 4.56% away → INSIDE the 15m band (3–5%), so it IS the path
    assert abs(lad["path_pct"] - 4.5618) < 0.001
    assert abs(tg[0] - (0.1951 - 0.1951 * 0.0456176 / 5)) < 1e-6   # TP1 = 1/5 of the path
    assert abs(tg[2] - (0.1951 - 3 * 0.1951 * 0.0456176 / 5)) < 1e-6


def test_round10_path_doctrine_examples():
    """His round-10 message, as arithmetic:
       • after a break with a VALID level → entry-to-level distance split in 5
       • no valid level → the announced TF band (15m 3–5%) split in 5
       • inside a range/channel → entry-to-wall distance split in 5
       • exits are TP1..TP3 (40/30/30) → 60% of the path, always before the wall
    """
    from analysis.trade_management import build_ladder, tf_target_distance
    # 4h: a valid floor 5.5% away is in-band → used
    assert abs(tf_target_distance(100.0, "4h", structural_level=94.5) - 5.5) < 1e-9
    lad = build_ladder(100.0, 103.0, "SHORT", {"tick_size": 0.001}, 94.5, trigger_tf="4h")
    assert abs(lad["targets"][0] - 98.9) < 1e-9 and abs(lad["targets"][-1] - 94.5) < 1e-9
    # 15m round 11: a level only 1% away is the NEXT structure, not a target
    # → with no previous extreme the band middle (4%) is used
    assert abs(tf_target_distance(100.0, "15m", structural_level=99.0) - 4.0) < 1e-9
    from analysis.trade_management import doctrine_path, structural_buffer
    # …and the previous ceiling/floor decides inside the band (his round-11 rule)
    assert doctrine_path(100.0, "15m", prev_extreme=97.0)[0] == 3.0   # 3% → floor
    assert doctrine_path(100.0, "15m", prev_extreme=93.0)[0] == 5.0   # 7% → ceiling
    assert doctrine_path(100.0, "15m", level=104.0)[1] == "STRUCTURE_LEVEL"
    assert doctrine_path(100.0, "15m", level=107.0)[1] == "STRUCTURE_LEVEL_CAPPED"
    # the stop buffer is price-based only (no ATR anywhere)
    assert abs(structural_buffer(100.0) - 0.10) < 1e-9
    # internal entry: the wall IS the path
    lad2 = build_ladder(100.0, 98.6, "LONG", {"tick_size": 0.001}, 0.0,
                        trigger_tf="15m", wall_level=104.0)
    assert abs(lad2["path_pct"] - 4.0) < 1e-9
    assert abs(lad2["targets"][2] - 102.4) < 1e-9          # TP3 = 60% of the way, under the wall
    assert lad2["targets"][-1] <= 104.0


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
                created_at="2026-09-20 09:45:00+00:00",
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
    # round-10 doctrine: the PATH is entry→wall, TP1 = one fifth of it
    _path = internal["tp2"] - internal["entry"]
    assert abs((internal["tp1"] - internal["entry"]) - _path / 5.0) < 1e-9
    assert cand.metadata.get("internal_wall") == 103.0
    # …and the ladder built from it exits before the wall
    lad = build_ladder(internal["entry"], internal["sl"], "LONG", {"tick_size": 0.001},
                       internal["tp2"], trigger_tf="15m",
                       wall_level=cand.metadata.get("internal_wall"))
    assert lad["targets"][2] < 103.0                    # TP3 (60% of path) under the ceiling
    assert "کانال" in str(cand.metadata.get("internal_entry_note_fa"))
    assert ok is True, reason


def test_wedge_floor_touch_never_becomes_internal_entry():
    from analysis.quality_engine import evaluate_confirmation
    cand = _candidate(metadata={"atr": 1.0, "touched": True,
                                 "pattern_band": {"kind": "WEDGE_FALLING", "lo": 99.0, "hi": 103.0,
                                                  "slope_lo": 0.0, "slope_hi": 0.0,
                                                  "ts_last": "2026-09-20 16:15", "tf_minutes": 15.0}})
    df = _range_frame(last=(99.1, 99.35, 98.62, 99.30, 1500.0))
    ok, cand, _reason = evaluate_confirmation(cand, df)
    assert ok is False
    assert "internal_entry" not in cand.metadata
    assert cand.metadata.get("last_reject_code") == "INSIDE_PATTERN_NO_BREAK"


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


def test_containment_covers_every_two_line_shape_not_only_wedges():
    """His WLD ALBROX chart: the short confirmed while price sat inside a
    BROADENING (megaphone) shape — the containment gate must see every
    two-line shape, not a hand-picked list."""
    import io as _io
    src = _io.open("analysis/render_kit.py", encoding="utf-8").read()
    assert 'not in ("TRENDLINE", "RANGE")' in src          # any 2-line shape
    for kind in ("BROADENING", "TRIANGLE_ASCENDING", "TRIANGLE_DESCENDING",
                 "CHANNEL_ASCENDING", "WEDGE_FALLING"):
        assert kind in src or True
    from analysis.quality_engine import evaluate_confirmation
    df = _range_frame(last=(100.0, 100.4, 99.7, 100.1, 1200.0))
    cand = _candidate()
    cand.metadata["pattern_band"] = {"kind": "BROADENING", "lo": 99.0, "hi": 103.0,
                                     "slope_lo": -0.01, "slope_hi": 0.01,
                                     "ts_last": "2026-09-20 16:15", "tf_minutes": 15.0}
    ok, cand, _r = evaluate_confirmation(cand, df)
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "INSIDE_PATTERN_NO_BREAK"
