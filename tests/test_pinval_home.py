"""R99i-PINVAL — pinval discipline-home tests."""
import analysis.tiered_scan as _ts
from analysis.pinval import (
    PINVAL_ENGINES, PINVAL_ENTRY_RULES, get_pinval_engine,
    pinval_health_check, pinval_alarm, pinval_detect, pinval_find_pivots,
    pinval_candles_for, pinval_zoom_window, pinval_zones_from_pivots,
    pinval_entry_check, pinval_trailing_check, pinval_tohom_fired,
)


def test_pinval_all_nine_wired():
    assert sorted(PINVAL_ENGINES) == [
        "candle_count", "confirm_entry", "detection", "entry_rules",
        "pivots", "tohom", "trailing", "zones_render", "zoom"]
    for _name, _e in PINVAL_ENGINES.items():
        assert _e["status"] == "wired", _name
        assert _e["entry"], _name


def test_pinval_rules_no_zones():
    assert PINVAL_ENTRY_RULES["own_polarity_gate"] is True
    assert PINVAL_ENTRY_RULES["legacy_display_name"] == "PINWALL"
    assert PINVAL_ENTRY_RULES["zones_may_draw"] is False
    assert pinval_zones_from_pivots({"highs": [(1, 2.0)], "lows": []}) == []
    assert get_pinval_engine("NOPE") is None
    assert pinval_health_check(None) == []
    assert pinval_alarm("x").startswith("[PINVAL-ALARM]")


def test_pinval_detect_unifies_gates(monkeypatch):
    import types as _t
    import analysis.pinval as _pv

    def _gate_a(bundle, style):
        return None

    def _gate_b(bundle, style):
        return _t.SimpleNamespace(metadata={})

    monkeypatch.setattr("analysis.setups_experimental.PINVAL_DETECTORS",
                        [_gate_a, _gate_b], raising=False)
    import analysis.setups_experimental as _se
    monkeypatch.setattr(_se, "PINVAL_DETECTORS", [_gate_a, _gate_b])
    _c = _pv.pinval_detect(object(), "DAYTRADE")
    assert _c.metadata.get("pinval_gate") == "_gate_b"
    assert _c.metadata.get("pinval_owned") is True


def test_pinval_pivots_candles_zoom():
    _p = pinval_find_pivots([1, 2, 3, 2, 1, 2, 5, 2, 1],
                            [1, 2, 3, 2, 0.5, 2, 5, 2, 1])
    assert (6, 5.0) in _p["highs"] and (4, 0.5) in _p["lows"]
    assert pinval_candles_for("30m", 100) == 165  # R99q9 wide law
    assert pinval_zoom_window(300, 160) == (158, 318)


def _fake_kv(monkeypatch, store):
    class _KV:
        @staticmethod
        def get_json(_k, default=None):
            return store.get(_k, default)

        @staticmethod
        def set_json(_k, _v):
            store[_k] = _v
            return True

    monkeypatch.setattr(_ts, "_kv", lambda: _KV)


def test_pinval_entry_polarity_veto_late(monkeypatch):
    _fake_kv(monkeypatch, {})
    _w = pinval_entry_check(broke=True, closed_after_break=True,
                            polarity_ok=False, day="2099-05-01")
    assert _w["decision"] == "WAIT" and "polarity" in _w["reasons"][0]
    _v = pinval_entry_check(broke=True, closed_after_break=True,
                            foreign_gates=["pinwall_veto"], day="2099-05-01")
    assert _v["decision"] == "CONFIRM" and len(_v["alarms"]) == 1
    _l = pinval_entry_check(broke=True, closed_after_break=True,
                            direction="SHORT", live=98.0, entry=100.0,
                            day="2099-05-01")
    assert _l["decision"] == "CONFIRM" and any("LATE" in a for a in _l["alarms"])
    # R99q (his «گیت خشک‌کننده رو بردار»): daily TOTAL budget retired — the
    # old 25/25 counter no longer defers anything.
    _fake_kv(monkeypatch, {"tier_day_count:2099-05-02:spot": 25})
    _d = pinval_entry_check(broke=True, closed_after_break=True, day="2099-05-02")
    assert _d["decision"] == "CONFIRM"


def test_pinval_trailing_stop_runner():
    _s = pinval_trailing_check(entry=100.0, stop=102.0, live=103.0,
                               direction="SHORT")
    assert _s["state"] == "STOPPED"
    _r = pinval_trailing_check(entry=100.0, stop=98.0, live=101.0,
                               profit_pct=5.0, confirmed=False)
    assert _r["state"] == "HEALTHY" and len(_r["alarms"]) == 1


def test_pinval_tohom_no_crash():
    import types as _t
    _c = _t.SimpleNamespace(setup_code="PINVAL", direction="LONG",
                            trigger_timeframe="30m", metadata={})
    assert pinval_tohom_fired(_c, None) is False
