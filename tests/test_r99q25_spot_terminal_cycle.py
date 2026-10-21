"""R99q25 — Spot geometry lifecycle and terminal-position release."""
from types import SimpleNamespace


def _kv(monkeypatch, initial=None):
    import database.bot_kv as kv
    memory = dict(initial or {})
    monkeypatch.setattr(kv, "get_json", lambda key, default=None: memory.get(key, default))
    monkeypatch.setattr(kv, "set_json", lambda key, value: memory.__setitem__(key, value))
    return memory


def _pattern(last_ts="2026-10-18 10:00:00", last_price=101.0):
    return {
        "type": "WEDGE_FALLING", "shape": "converging",
        "lines": [
            {"side": "HIGH", "points": [
                {"ts": "2026-10-18 08:00:00", "price": 102.0},
                {"ts": last_ts, "price": last_price}]},
            {"side": "LOW", "points": [
                {"ts": "2026-10-18 08:15:00", "price": 98.0},
                {"ts": "2026-10-18 10:15:00", "price": 99.0}]},
        ],
    }


def test_spot_fingerprint_tracks_geometry_not_window_indices():
    from analysis.spot_engine import spot_pattern_fingerprint
    a = _pattern()
    b = _pattern()
    b["lines"][0]["x0"] = 3
    b["lines"][0]["x1"] = 70
    c = _pattern(last_ts="2026-10-18 10:30:00", last_price=101.2)
    assert spot_pattern_fingerprint(a) == spot_pattern_fingerprint(b)
    assert spot_pattern_fingerprint(a) != spot_pattern_fingerprint(c)


def test_terminal_spot_close_retires_only_the_traded_shape(monkeypatch):
    from analysis.spot_engine import (spot_pattern_fingerprint,
                                      spot_pattern_is_retired,
                                      spot_position_close,
                                      spot_position_open)
    memory = _kv(monkeypatch, {
        "spot_tf_position": {"ETHUSDT|4H": 123.0},
        "spot_chain|ETHUSDT|4H": {"code": "VIVA-SPOT-Y123456", "charts": 5},
        "spot_urgent_watch": {"ETHUSDT|4h": {"symbol": "ETHUSDT"}},
        "line_watch": {"ETHUSDT|4h|HIGH": {"symbol": "ETHUSDT"}},
    })
    old = _pattern()
    fingerprint = spot_pattern_fingerprint(old)
    cand = SimpleNamespace(
        metadata={"public_code": "VIVA-SPOT-Y123456", "pattern_type": "WEDGE_FALLING",
                  "spot_pattern_id": fingerprint, "render_patterns": [old]},
        symbol="ETHUSDT", trigger_timeframe="4h", planned_entry=100.0,
        sl=96.0,
    )
    pos = spot_position_open(cand, [105.0, 110.0, 115.0], 55)
    assert pos["entry"] == 100.0 and pos["stop"] == 96.0
    assert pos["spot_pattern_id"] == fingerprint

    import main
    main._release_terminal_spot_event({
        "event": "CLOSED", "source": "SPOTBREAK", "public_code": "VIVA-SPOT-Y123456",
        "symbol": "ETHUSDT", "trigger_timeframe": "4h", "close_reason": "TP2",
    })
    assert memory["spot_positions"]["VIVA-SPOT-Y123456"]["closed"] == "TP2"
    assert memory["spot_tf_position"] == {}
    assert memory["spot_chain|ETHUSDT|4H"] == {}
    assert memory["spot_urgent_watch"] == {}
    assert memory["line_watch"] == {}
    assert spot_pattern_is_retired("ETHUSDT", "4h", fingerprint)
    assert not spot_pattern_is_retired("ETHUSDT", "4h",
                                       spot_pattern_fingerprint(_pattern(
                                           last_ts="2026-10-18 10:30:00", last_price=101.2)))


def test_spot_candidate_stamp_is_pattern_specific():
    import main
    a = SimpleNamespace(symbol="ETHUSDT", trigger_timeframe="4h", metadata={
        "pattern_type": "WEDGE_FALLING", "spot_pattern_id": "geometry-a"})
    b = SimpleNamespace(symbol="ETHUSDT", trigger_timeframe="4h", metadata={
        "pattern_type": "WEDGE_FALLING", "spot_pattern_id": "geometry-b"})
    assert main._spot_candidate_stamp_key(a) != main._spot_candidate_stamp_key(b)
