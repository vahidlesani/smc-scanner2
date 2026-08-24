from analysis.trade_management import build_ladder, advance_ladder, entry_touched


def test_entry_fill_requires_a_real_ohlc_touch():
    assert entry_touched(100.0, 101.0, 99.9)
    assert not entry_touched(100.0, 101.0, 100.01)
    assert not entry_touched(100.0, 99.99, 98.0)


def test_ladder_long_targets_and_trail():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    assert p["targets"] == [102, 104, 106, 108, 110]
    assert p["trail_stops"][0] == 100.05
    result = advance_ladder(p, 102.1, 100.2)
    assert result["events"][0]["event"] == "TP1"
    assert result["state"]["current_sl"] == 100.05
    assert result["state"]["hit_index"] == 1


def test_ladder_stop_is_conservative_when_same_candle_hits_tp():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01})
    # high crosses TP1 but low also crosses original stop: stop is first.
    result = advance_ladder(p, 102.2, 97.9)
    assert result["events"][0]["event"] == "STOP"
    assert result["state"]["closed"]


def test_ladder_short_trails_down_after_tp1():
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01}, 90)
    assert p["targets"] == [98, 96, 94, 92, 90]
    result = advance_ladder(p, 99.9, 97.9)
    assert result["events"][0]["event"] == "TP1"
    assert result["state"]["current_sl"] == 99.95

def test_tp1_then_trailing_above_entry_is_a_positive_exit():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    first = advance_ladder(p, 102.1, 100.1)  # TP1 (35%)
    state = first["state"]
    assert state["hit_index"] == 1
    # Stop is entry + 5 ticks; remaining 65% exits above entry.
    exited = advance_ladder(state, 101.0, 100.04)
    assert exited["state"]["closed"]
    assert exited["state"]["realized_r"] > 0
    assert exited["events"][0]["event"] == "TRAIL_STOP"


def test_tp2_then_trailing_at_tp1_keeps_all_realized_profit():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110)
    state = advance_ladder(p, 104.1, 100.1)["state"]  # TP1 + TP2
    assert state["hit_index"] == 2
    # 30% remainder exits slightly above TP1, not as an original stop loss.
    exited = advance_ladder(state, 103.0, 102.04)
    assert exited["state"]["closed"]
    assert exited["state"]["realized_r"] > 1.0
