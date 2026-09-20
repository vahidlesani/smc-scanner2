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


# ── Viva 09-19/20 ladder v3: original 5-pill shape, exits 40/30/30 ────────


def test_ladder_v3_five_pills_forty_thirty_thirty():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    # five equal segments entry→final — the approved tool shape; TP1 keeps
    # its original distance (no 1R floor); TP4/TP5 are INFO (zero weight).
    assert p["targets"] == [102.0, 104.0, 106.0, 108.0, 110.0]
    assert p["weights"] == [40.0, 30.0, 30.0, 0.0, 0.0]
    assert p["version"] == 2
    assert p["trail_stops"][0] == 100.05          # net BE, fee 0 → 5 ticks
    result = advance_ladder(p, 102.1, 100.2)
    assert result["events"][0]["event"] == "TP1"
    assert result["state"]["current_sl"] == 100.05
    assert result["state"]["hit_index"] == 1
    assert abs(result["state"]["realized_r"] - 0.4) < 1e-9   # 1R × 40%


def test_ladder_closes_when_weight_exhausted_at_tp3():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    out = advance_ladder(p, 106.5, 100.2)["state"]   # TP1+TP2+TP3 same candle
    assert out["closed"]
    assert out["hit_index"] == 3
    assert abs(out["realized_r"] - (0.4 * 1.0 + 0.3 * 2.0 + 0.3 * 3.0)) < 1e-9


def test_ladder_stop_is_conservative_when_same_candle_hits_tp():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01})
    result = advance_ladder(p, 102.2, 97.9)          # original stop first
    assert result["events"][0]["event"] == "STOP"
    assert result["state"]["closed"]


def test_ladder_short_five_segments_and_trail():
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90, trigger_tf="1d")
    assert p["targets"] == [98.0, 96.0, 94.0, 92.0, 90.0]
    assert p["weights"] == [40.0, 30.0, 30.0, 0.0, 0.0]
    result = advance_ladder(p, 99.9, 97.9)
    assert result["events"][0]["event"] == "TP1"
    assert result["state"]["current_sl"] == 99.95


def test_net_breakeven_includes_roundtrip_cost():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, fee_pct=0.0018)
    assert abs(p["be_gap"] - 0.18) < 1e-9
    assert abs(p["trail_stops"][0] - 100.18) < 1e-9


# ── Formula-based protection floors (adaptive, spec §4/§5) ────────────────


def test_band_trailing_ratchets_to_profit_floor_long():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    st = advance_ladder(p, 102.1, 100.1)["state"]
    assert st["hit_index"] == 1
    assert abs(st["band_floors"][0] - 100.7) < 1e-9   # 1R band → k=0.35
    candles = [{"open": 104.0, "high": 104.2, "low": 103.6,
                "close": 104.0, "volume": 10.0} for _ in range(25)]
    candles[-1] = {"open": 105.0, "high": 105.5, "low": 104.8,
                   "close": 105.2, "volume": 10.0}
    step = band_trailing(st, candles)
    new_sl = step["state"]["current_sl"]
    assert new_sl > st["current_sl"]
    assert new_sl >= st["band_floors"][0] - 1e-9
    assert step["events"] and step["events"][0]["event"] == "PROFIT_FLOOR"
    candles2 = candles[:-1] + [{"open": 104.0, "high": 104.1, "low": 100.2,
                                "close": 100.3, "volume": 10.0}]
    step2 = band_trailing(step["state"], candles2)
    assert step2["state"]["current_sl"] >= new_sl - 1e-12   # ratchet only
    assert not step2["events"]


def test_band_trailing_short_mirrors():
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90, trigger_tf="1d")
    st = advance_ladder(p, 99.9, 97.9)["state"]
    assert abs(st["band_floors"][0] - 99.3) < 1e-9
    candles = [{"open": 95.8, "high": 96.2, "low": 95.6,
                "close": 95.8, "volume": 10.0} for _ in range(25)]
    candles[-1] = {"open": 95.0, "high": 95.2, "low": 94.5,
                   "close": 94.8, "volume": 10.0}
    step = band_trailing(st, candles)
    assert step["state"]["current_sl"] < st["current_sl"]
    assert step["state"]["current_sl"] <= st["band_floors"][0] + 1e-9
    candles2 = candles[:-1] + [{"open": 96.0, "high": 99.8, "low": 95.9,
                                "close": 99.5, "volume": 10.0}]
    step2 = band_trailing(step["state"], candles2)
    assert step2["state"]["current_sl"] <= step["state"]["current_sl"] + 1e-12


def test_band_trailing_ignores_legacy_v1_ladders():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    st = advance_ladder(p, 102.1, 100.1)["state"]
    st["version"] = 1
    candles = [{"open": 105.0, "high": 105.5, "low": 104.8,
                "close": 105.2, "volume": 10.0} for _ in range(25)]
    step = band_trailing(st, candles)
    assert step["state"]["current_sl"] == st["current_sl"]
    assert not step["events"]


def test_band_floor_ratios_adapt_to_band_width():
    # k = clip(0.30 + 0.10×(width_R − 0.5), 0.30, 0.50)
    # entry 100 · risk 2 (SL 98) · 1d ceiling 10% → target 110 is legal and
    # the five segments are 2.0 wide = 1R bands … (2R bands → k = 0.45)
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    assert [round(k, 3) for k in p["band_ks"]] == [0.35] * 4   # 1R bands
    assert abs(p["band_floors"][0] - 100.7) < 1e-9
    assert abs(p["band_floors"][1] - 102.7) < 1e-9
    # 0.5R bands (five segments of 1.0 against a risk of 2) → k clamps at 0.30
    r = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1h")
    assert r["target_capped"] is True and abs(r["final_target"] - 105) < 1e-9
    assert [round(k, 3) for k in r["band_ks"]] == [0.30] * 4


def test_tf_target_ceiling_clamps_far_structural_targets():
    """«مدیریت ویوا» §4: 1d 10% · 4h 7% · 1h/15m 5% hard distance ceiling."""
    from analysis.trade_management import cap_final_target, target_distance_cap_pct
    assert target_distance_cap_pct("1d") == 10.0
    assert target_distance_cap_pct("4h") == 7.0
    assert target_distance_cap_pct("1h") == 5.0
    assert target_distance_cap_pct("15m") == 5.0
    # his XRP chart: entry 1.381, raw structural target 1.119 = 19% away
    _px, capped, pct = cap_final_target(1.381, 1.119, "SHORT", "15m")
    assert capped and pct == 5.0
    assert abs(_px - 1.31195) < 1e-6
    ladder = build_ladder(1.381, 1.462, "SHORT", {"tick_size": 0.0001}, 1.119,
                          trigger_tf="15m")
    assert ladder["target_capped"] is True
    assert ladder["raw_final_target"] == 1.119
    assert abs(ladder["targets"][0] - 1.3672) < 1e-4   # TP1 ≈ 1%
    assert abs(ladder["targets"][4] - 1.3119) < 1e-4   # TP5 = 5% ceiling
    # a target already inside the ceiling is untouched
    _px2, capped2, _ = cap_final_target(1.381, 1.34, "SHORT", "15m")
    assert not capped2 and _px2 == 1.34


def test_zero_weight_info_pills_never_emit_receipts():
    """Exits end at TP3 (40/30/30); a candle that also prints TP4/TP5 INFO
    closes the ladder at TP3 and produces no receipts for zero-weight pills."""
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="15m")
    assert p["weights"] == [40.0, 30.0, 30.0, 0.0, 0.0]
    step = advance_ladder(p, 200.0, 99.0)   # one candle sweeps every pill
    assert [e["event"] for e in step["events"]] == ["TP1", "TP2", "TP3", "LADDER_COMPLETE"]
    assert step["state"]["closed"] is True


def test_vol_stop_scales_with_atr_n_argument():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    st = advance_ladder(p, 102.1, 100.1)["state"]
    candles = [{"open": 104.0, "high": 104.2, "low": 103.6,
                "close": 104.0, "volume": 10.0} for _ in range(25)]
    candles[-1] = {"open": 105.0, "high": 105.5, "low": 104.8,
                   "close": 105.2, "volume": 10.0}
    tight = band_trailing(st, candles)["state"]["current_sl"]
    loose = band_trailing(st, candles, atr_n=50.0)["state"]["current_sl"]
    assert tight > loose > st["current_sl"]
    assert abs(loose - 100.7) < 1e-6        # pure progress interpolation


def test_monitor_tf_hierarchy_and_sqrt_scaling():
    from database.repository_v7 import monitor_tf_for, vol_atr_n_for
    assert monitor_tf_for("1d") == "1h"
    assert monitor_tf_for("4h") == "15m"
    assert monitor_tf_for("1h") == "15m"
    assert monitor_tf_for("15m") == "5m"     # Viva 09-19/20: signs live on 5m
    assert monitor_tf_for("3m") == "1m"
    assert monitor_tf_for("5m") == "1m"
    assert monitor_tf_for("7m") == "7m"
    assert abs(vol_atr_n_for("15m", "5m") - 1.7320508) < 1e-6
    assert abs(vol_atr_n_for("1d", "1h") - 4.8989795) < 1e-6


# ── Smart exit: reversal pressure on the monitor TF (spec §7/§9) ──────────


def _flat_window(n=25, o=100.0, spread=0.4, vol=100.0):
    return [{"open": o, "high": o + spread / 2, "low": o - spread / 2,
             "close": o, "volume": vol} for _ in range(n)]


def test_smart_exit_disarmed_before_tp1():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    win = _flat_window()
    win[-1] = {"open": 100.6, "high": 100.7, "low": 98.9,
               "close": 99.0, "volume": 400.0}
    scan = smart_exit_scan("LONG", win, p)
    assert scan["level"] == "" and scan["score"] == 0


def test_smart_exit_red_closes_on_two_or_more_signs():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    armed = advance_ladder(p, 102.1, 100.1)["state"]
    win = _flat_window()
    assert smart_exit_scan("LONG", win, armed)["level"] == ""
    win[-2] = {"open": 100.0, "high": 100.6, "low": 99.9,
               "close": 100.5, "volume": 100.0}
    win[-1] = {"open": 100.6, "high": 100.7, "low": 98.9,
               "close": 99.0, "volume": 400.0}
    scan = smart_exit_scan("LONG", win, armed)
    assert scan["level"] == "RED" and scan["score"] >= 3
    assert len(scan["reasons"]) >= 3


def test_smart_exit_two_signs_close_not_warn():
    """Viva 09-19/20 (verbatim): in the protection phase two concurrent
    reversal signs must CLOSE the remainder — never «فقط هشدار»."""
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    armed = advance_ladder(p, 102.1, 100.1)["state"]
    win = _flat_window()
    win[-2] = {"open": 100.0, "high": 100.6, "low": 99.9,
               "close": 100.5, "volume": 100.0}
    win[-1] = {"open": 100.6, "high": 100.7, "low": 99.3,
               "close": 99.9, "volume": 400.0}
    scan = smart_exit_scan("LONG", win, armed)
    assert scan["score"] == 2
    assert scan["level"] == "RED"


def test_smart_exit_single_sign_only_warns():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    armed = advance_ladder(p, 102.1, 100.1)["state"]
    win = _flat_window()
    win[-1] = {"open": 100.1, "high": 100.15, "low": 99.9,
               "close": 99.95, "volume": 400.0}
    scan = smart_exit_scan("LONG", win, armed)
    assert scan["level"] == "ORANGE" and scan["score"] == 1


def test_smart_exit_single_sign_short_mirror():
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90, trigger_tf="1d")
    armed = advance_ladder(p, 98.1, 97.5)["state"]
    win = _flat_window()
    win[-1] = {"open": 99.9, "high": 100.1, "low": 99.85,
               "close": 100.05, "volume": 400.0}
    scan = smart_exit_scan("SHORT", win, armed)
    assert scan["level"] == "ORANGE" and scan["score"] == 1


def test_smart_exit_short_mirror_red():
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90, trigger_tf="1d")
    armed = advance_ladder(p, 98.1, 97.5)["state"]
    win = _flat_window()
    win[-2] = {"open": 100.0, "high": 100.1, "low": 99.4,
               "close": 99.5, "volume": 100.0}
    win[-1] = {"open": 99.4, "high": 101.1, "low": 99.3,
               "close": 101.0, "volume": 400.0}
    scan = smart_exit_scan("SHORT", win, armed)
    assert scan["level"] == "RED" and scan["score"] >= 3


def test_money_management_refine_cost_inside_risk_and_wide_stop_penalty():
    # Viva 09-19/20 refine: fees+slippage live inside effective risk, wide
    # stops shrink the risk budget, degraded RR trims leverage.
    from analysis.risk import calculate_position
    acc = 10_000.0
    tight = calculate_position(100.0, 98.0, "LONG", 8, acc, "SWING", 20, 102.0, 106.0)
    assert tight is not None
    # effective risk (stop + round-trip cost) must exceed the bare stop risk
    assert tight["eff_risk_pct"] > tight["risk_pct"]
    assert abs(tight["cost_pct"] - 0.18) < 1e-9
    wide = calculate_position(100.0, 78.0, "LONG", 8, acc, "SWING", 20, 104.0, 110.0)
    assert wide is not None
    assert wide["position_size"] < tight["position_size"] / 3.0   # 22% stop → ×0.35
    absurd = calculate_position(100.0, 55.0, "LONG", 8, acc, "SWING", 20, 104.0, 110.0)
    assert absurd is None                                          # >30% = unsizeable
    degraded = calculate_position(100.0, 98.0, "LONG", 8, acc, "SWING", 20, 100.5, 106.0)
    assert degraded is not None
    assert degraded["leverage"] <= 2                               # rr1 < 1 trim


def test_protection_phase_two_signs_close_semantics():
    # Viva 09-19/20: in the protection phase TWO concurrent signs close the
    # remainder at the monitor candle close (score>=2), ONE sign warns only.
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    armed = advance_ladder(p, 102.1, 100.1)["state"]
    win = _flat_window()
    win[-2] = {"open": 100.0, "high": 100.6, "low": 99.9,
               "close": 100.5, "volume": 100.0}
    win[-1] = {"open": 100.6, "high": 100.7, "low": 99.3,
               "close": 99.9, "volume": 400.0}                    # engulf + volume
    scan = smart_exit_scan("LONG", win, armed)
    assert scan["score"] == 2                                      # monitor closes NOW
    win1 = _flat_window()
    win1[-1] = {"open": 100.6, "high": 100.7, "low": 99.3,
                "close": 99.9, "volume": 400.0}                    # volume surge only
    scan1 = smart_exit_scan("LONG", win1, armed)
    assert scan1["score"] == 1                                     # warning only


# ── «مدیریت ویوا» (09-20) — separated management profile + §6.1 sequence ──

def test_viva_management_profile_is_separate_and_matches_the_table():
    from analysis.risk import viva_position, calculate_position
    # exact table boundaries: <5 → 30$ · 5 to <50 → 40$ · ≥50 → 50$ (all 20×)
    assert viva_position(1.381, "SHORT", 1.462)["margin"] == 30.0
    assert viva_position(4.99, "SHORT")["margin"] == 30.0
    assert viva_position(5.0, "SHORT")["margin"] == 40.0
    assert viva_position(49.99, "SHORT")["margin"] == 40.0
    assert viva_position(50.0, "LONG")["margin"] == 50.0
    assert viva_position(2500.0, "LONG")["margin"] == 50.0
    assert {viva_position(p, "LONG")["leverage"] for p in (1.0, 20.0, 500.0)} == {20}
    # the standard engine is untouched while the profile flag is off
    std = calculate_position(1.381, 1.462, "SHORT", 8, 1000, "DAYTRADE", 20, 1.34, 1.31)
    assert std and std.get("profile") != "VIVA"
    # and the hazard of a 20× table against a wide stop is REPORTED
    v = viva_position(1.381, "SHORT", 1.462)
    assert v["liq_distance_pct"] == 5.0 and "لیکوئید" in v["liq_warning_fa"]


def test_fast_watch_tf_is_one_step_finer_than_the_monitor():
    from database.repository_v7 import fast_watch_tf_for, monitor_tf_for
    assert monitor_tf_for("15m") == "5m"
    assert fast_watch_tf_for("15m") == "3m"      # his §7 example: 15m trade
    assert fast_watch_tf_for("1h") == "5m"
    assert fast_watch_tf_for("1d") == "15m"


def test_single_confirmed_reverse_pin_close_is_a_red_close():
    """«مدیریت ویوا» §6.1: a closed reverse pin bar on the monitor frame exits
    the remainder even when it is the only sign on that frame."""
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    armed = advance_ladder(p, 102.1, 100.1)["state"]
    win = _flat_window()
    win[-1] = {"open": 100.0, "high": 101.0, "low": 99.95,
               "close": 99.98, "volume": 90.0}   # reversed pin, no volume spike
    scan = smart_exit_scan("LONG", win, armed)
    assert scan["score"] == 1
    assert any("پین‌بار" in r for r in scan["reasons"])
