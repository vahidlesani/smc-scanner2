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
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
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
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
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
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90)
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
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
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
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90)
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
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    st = advance_ladder(p, 102.1, 100.1)["state"]
    st["version"] = 1
    candles = [{"open": 105.0, "high": 105.5, "low": 104.8,
                "close": 105.2, "volume": 10.0} for _ in range(25)]
    step = band_trailing(st, candles)
    assert step["state"]["current_sl"] == st["current_sl"]
    assert not step["events"]


def test_band_floor_ratios_adapt_to_band_width():
    # k = clip(0.30 + 0.10×(width_R − 0.5), 0.30, 0.50)
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)   # 1R bands
    assert [round(k, 3) for k in p["band_ks"]] == [0.35] * 4
    q = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 120)   # 2R bands
    assert [round(k, 3) for k in q["band_ks"]] == [0.45] * 4
    assert abs(q["band_floors"][0] - 101.8) < 1e-9
    assert abs(q["band_floors"][1] - 105.8) < 1e-9


def test_vol_stop_scales_with_atr_n_argument():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
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
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    win = _flat_window()
    win[-1] = {"open": 100.6, "high": 100.7, "low": 98.9,
               "close": 99.0, "volume": 400.0}
    scan = smart_exit_scan("LONG", win, p)
    assert scan["level"] == "" and scan["score"] == 0


def test_smart_exit_red_needs_three_concurrent_signs():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
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


def test_smart_exit_orange_warns_but_never_closes():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    armed = advance_ladder(p, 102.1, 100.1)["state"]
    win = _flat_window()
    win[-2] = {"open": 100.0, "high": 100.6, "low": 99.9,
               "close": 100.5, "volume": 100.0}
    win[-1] = {"open": 100.6, "high": 100.7, "low": 99.3,
               "close": 99.9, "volume": 400.0}
    scan = smart_exit_scan("LONG", win, armed)
    assert scan["level"] == "ORANGE" and scan["score"] == 2


def test_smart_exit_short_mirror_red():
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90)
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
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
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
