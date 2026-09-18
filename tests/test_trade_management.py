from analysis.trade_management import (
    build_ladder,
    advance_ladder,
    entry_touched,
    band_trailing,
    smart_exit_scan,
)


def test_entry_fill_requires_a_real_ohlc_touch():
    assert entry_touched(100.0, 101.0, 99.9)
    assert not entry_touched(100.0, 101.0, 100.01)
    assert not entry_touched(100.0, 99.99, 98.0)


# ── Viva 09-19 aligned ladder: exits sit ON the drawn levels ──────────────


def test_ladder_long_three_aligned_exits():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    # risk=2, dist=10 (5R): TP1 pinned at exactly 1R per the ruling;
    # TP2 = midpoint(102,110); TP3 = structural final target.
    assert p["targets"] == [102.0, 106.0, 110.0]
    assert p["weights"] == [50.0, 30.0, 20.0]
    assert p["version"] == 2
    assert p["trail_stops"][0] == 100.05          # net BE, fee 0 → 5 ticks
    result = advance_ladder(p, 104.1, 100.2)
    assert result["events"][0]["event"] == "TP1"
    assert result["state"]["current_sl"] == 100.05
    assert result["state"]["hit_index"] == 1


def test_tp1_floor_never_below_one_r():
    # final = 1.8R → structural 40% point (0.72R) is floored to exactly 1R
    # and the ladder drops to the 2-exit 60/40 plan.
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 103.6)
    assert p["targets"][0] == 102.0
    assert p["targets"][-1] == 103.6
    assert p["weights"] == [60.0, 40.0]


def test_single_exit_when_final_inside_one_r():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 101.5)
    assert p["targets"] == [101.5]
    assert p["weights"] == [100.0]


def test_net_breakeven_includes_roundtrip_cost():
    # professional point 5: BE = entry + fee/slippage allowance, not raw entry.
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, fee_pct=0.0018)
    assert abs(p["be_gap"] - 0.18) < 1e-9
    assert abs(p["trail_stops"][0] - 100.18) < 1e-9


def test_ladder_stop_is_conservative_when_same_candle_hits_tp():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01})
    # fallback final = 3R → targets [102, 104, 106]; low crosses the
    # original stop in the same candle → STOP is assumed first.
    result = advance_ladder(p, 102.2, 97.9)
    assert result["events"][0]["event"] == "STOP"
    assert result["state"]["closed"]


def test_ladder_short_three_exits_and_trail():
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90)
    assert p["targets"] == [98.0, 94.0, 90.0]
    assert p["weights"] == [50.0, 30.0, 20.0]
    result = advance_ladder(p, 99.9, 95.9)
    assert result["events"][0]["event"] == "TP1"
    assert result["state"]["current_sl"] == 99.95


def test_worst_win_after_tp1_is_half_r():
    # The whole point of the 09-19 ruling: a TP1-then-BE trade banks +0.5R
    # worst case (the old 5-segment ladder banked only +0.14R).
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 104)  # dist = 2R
    assert p["targets"] == [102.0, 103.0, 104.0]                 # TP1 floored
    st = advance_ladder(p, 102.2, 101.0)["state"]
    assert st["hit_index"] == 1
    assert abs(st["realized_r"] - 0.5) < 1e-9                    # 1R × 50%
    out = advance_ladder(st, 101.0, 99.0)["state"]               # BE stop
    assert out["closed"]
    assert out["realized_r"] >= 0.5


# ── Formula-based protection floors between targets (spec §4/§5) ──────────


def test_band_trailing_ratchets_to_profit_floor_long():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    st = advance_ladder(p, 104.5, 103.9)["state"]                # TP1 printed
    assert st["hit_index"] == 1
    assert abs(st["band_floors"][0] - 100.8) < 1e-9              # α = 0.40 of entry→TP1
    candles = [{"open": 104.0, "high": 104.2, "low": 103.6,
                "close": 104.0, "volume": 10.0} for _ in range(25)]
    candles[-1] = {"open": 105.0, "high": 105.5, "low": 104.8,
                   "close": 105.2, "volume": 10.0}
    step = band_trailing(st, candles)
    new_sl = step["state"]["current_sl"]
    assert new_sl > st["current_sl"]                             # trailed up
    assert new_sl >= st["band_floors"][0] - 1e-9                 # ≥ floor
    assert step["events"] and step["events"][0]["event"] == "PROFIT_FLOOR"
    # ratchet: a weak candle never lowers the stop (غیرقابل‌برگشت)
    candles2 = candles[:-1] + [{"open": 104.0, "high": 104.1, "low": 100.2,
                                "close": 100.3, "volume": 10.0}]
    step2 = band_trailing(step["state"], candles2)
    assert step2["state"]["current_sl"] >= new_sl - 1e-12
    assert not step2["events"]                                   # announced once


def test_band_trailing_short_mirrors():
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90)
    st = advance_ladder(p, 96.1, 95.5)["state"]                  # TP1 printed
    assert abs(st["band_floors"][0] - 99.2) < 1e-9
    candles = [{"open": 95.8, "high": 96.2, "low": 95.6,
                "close": 95.8, "volume": 10.0} for _ in range(25)]
    candles[-1] = {"open": 95.0, "high": 95.2, "low": 94.5,
                   "close": 94.8, "volume": 10.0}
    step = band_trailing(st, candles)
    assert step["state"]["current_sl"] < st["current_sl"]        # trailed down
    assert step["state"]["current_sl"] <= st["band_floors"][0] + 1e-9
    candles2 = candles[:-1] + [{"open": 96.0, "high": 99.8, "low": 95.9,
                                "close": 99.5, "volume": 10.0}]
    step2 = band_trailing(step["state"], candles2)
    assert step2["state"]["current_sl"] <= step["state"]["current_sl"] + 1e-12


def test_band_trailing_ignores_legacy_v1_ladders():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    st = advance_ladder(p, 104.5, 103.9)["state"]
    st["version"] = 1                                            # live old row
    candles = [{"open": 105.0, "high": 105.5, "low": 104.8,
                "close": 105.2, "volume": 10.0} for _ in range(25)]
    step = band_trailing(st, candles)
    assert step["state"]["current_sl"] == st["current_sl"]
    assert not step["events"]


# ── Smart exit: reversal pressure on the monitor TF (spec §7/§9) ──────────


def _flat_window(n=25, o=100.0, spread=0.4, vol=100.0):
    return [{"open": o, "high": o + spread / 2, "low": o - spread / 2,
             "close": o, "volume": vol} for _ in range(n)]


def test_smart_exit_disarmed_before_tp1():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    win = _flat_window()
    win[-1] = {"open": 100.6, "high": 100.7, "low": 98.9,
               "close": 99.0, "volume": 400.0}
    scan = smart_exit_scan("LONG", win, p)
    assert scan["level"] == "" and scan["score"] == 0


def test_smart_exit_red_needs_three_concurrent_signs():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    armed = advance_ladder(p, 104.5, 103.9)["state"]
    win = _flat_window()
    scan = smart_exit_scan("LONG", win, armed)
    assert scan["level"] == ""
    win[-2] = {"open": 100.0, "high": 100.6, "low": 99.9,
               "close": 100.5, "volume": 100.0}                  # bull candle
    win[-1] = {"open": 100.6, "high": 100.7, "low": 98.9,
               "close": 99.0, "volume": 400.0}                    # engulf+vol+break
    scan = smart_exit_scan("LONG", win, armed)
    assert scan["level"] == "RED" and scan["score"] >= 3
    assert len(scan["reasons"]) >= 3                              # explainable


def test_smart_exit_orange_warns_but_never_closes():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    armed = advance_ladder(p, 104.5, 103.9)["state"]
    win = _flat_window()
    win[-2] = {"open": 100.0, "high": 100.6, "low": 99.9,
               "close": 100.5, "volume": 100.0}
    win[-1] = {"open": 100.6, "high": 100.7, "low": 99.3,
               "close": 99.9, "volume": 400.0}                    # no low break
    scan = smart_exit_scan("LONG", win, armed)
    assert scan["level"] == "ORANGE" and scan["score"] == 2


def test_smart_exit_short_mirror_red():
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90)
    armed = advance_ladder(p, 96.1, 95.5)["state"]
    win = _flat_window()
    win[-2] = {"open": 100.0, "high": 100.1, "low": 99.4,
               "close": 99.5, "volume": 100.0}                    # bear candle
    win[-1] = {"open": 99.4, "high": 101.1, "low": 99.3,
               "close": 101.0, "volume": 400.0}                   # engulf+vol+break
    scan = smart_exit_scan("SHORT", win, armed)
    assert scan["level"] == "RED" and scan["score"] >= 3
