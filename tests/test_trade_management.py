from analysis.trade_management import build_ladder, advance_ladder


def test_ladder_long_targets_and_trail():
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01})
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
    p = build_ladder(100, 102, "SHORT", {"tick_size": 0.01})
    assert p["targets"] == [98, 96, 94, 92, 90]
    result = advance_ladder(p, 99.9, 97.9)
    assert result["events"][0]["event"] == "TP1"
    assert result["state"]["current_sl"] == 99.95
