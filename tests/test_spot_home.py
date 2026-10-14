"""R99h-SPOT — spot discipline-home tests (mirrors TC contract)."""
import analysis.tiered_scan as _ts
from analysis.spot import (
    SPOT_ENGINES, SPOT_ENTRY_RULES, get_spot_engine,
    spot_health_check, spot_alarm, spot_detect, spot_find_pivots,
    spot_candles_for, spot_zoom_window, spot_zones_from_pivots,
    spot_entry_check, spot_trailing_check, spot_tohom_fired,
)


def test_spot_all_nine_wired():
    assert sorted(SPOT_ENGINES) == [
        "candle_count", "confirm_entry", "detection", "entry_rules",
        "pivots", "tohom", "trailing", "zones_render", "zoom"]
    for _name, _e in SPOT_ENGINES.items():
        assert _e["status"] == "wired", _name
        assert _e["entry"], _name


def test_spot_rules_long_only_and_decoupled():
    assert SPOT_ENTRY_RULES["long_only"] is True
    assert SPOT_ENTRY_RULES["zones_may_gate"] is False
    for g in ("techclassic_veto", "pinwall_veto", "cross_setup_veto"):
        assert g in SPOT_ENTRY_RULES["forbidden_gates"]
    assert get_spot_engine("NOPE") is None
    assert spot_health_check(None) == []
    assert spot_alarm("x").startswith("[SPOT-ALARM]")


def test_spot_detect_delegates_and_tags(monkeypatch):
    import types as _t

    def _fake(symbol, bundle):
        assert symbol == "ATOMUSDT"
        return [_t.SimpleNamespace(metadata={})]

    monkeypatch.setattr("analysis.spot_engine.spot_signals_for", _fake)
    _c = spot_detect("ATOMUSDT", object())[0]
    assert _c.metadata.get("spot_owned") is True


def test_spot_pivots_htf():
    _h = [1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3]
    _l = [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3]
    _p = spot_find_pivots(_h, _l)
    assert (4, 5.0) in _p["highs"]
    assert (4, 1.0) in _p["lows"]


def test_spot_candles_zoom_zones():
    assert spot_candles_for("8h", 120) == 160
    assert spot_zoom_window(300, 160) == (158, 318)
    _z = spot_zones_from_pivots(
        {"highs": [(1, 2.0), (2, 2.1)], "lows": [(1, 1.5), (2, 1.6)]})
    assert [z["side"] for z in _z] == ["supply", "demand"]


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


def test_spot_entry_instant_and_veto_refused(monkeypatch):
    _fake_kv(monkeypatch, {})
    _w = spot_entry_check(broke_closed=False, day="2099-03-01")
    assert _w["decision"] == "WAIT"
    _r = spot_entry_check(broke_closed=True,
                          foreign_gates=["techclassic_veto"],
                          day="2099-03-01")
    assert _r["decision"] == "CONFIRM"
    assert len(_r["alarms"]) == 1
    _fake_kv(monkeypatch, {"tier_day_count:2099-03-02:futures": 25})
    _d = spot_entry_check(broke_closed=True, day="2099-03-02")
    assert _d["decision"] == "DEFERRED_BUDGET"


def test_spot_trailing_atom_case():
    _r = spot_trailing_check(entry=1.896, stop=1.70, live=1.65)
    assert _r["state"] == "STOPPED" and len(_r["alarms"]) == 1
    _h = spot_trailing_check(entry=1.896, stop=1.70, live=1.95)
    assert _h["state"] == "HEALTHY"


def test_spot_tohom_no_crash():
    import types as _t
    _c = _t.SimpleNamespace(setup_code="SPOTBREAK", direction="LONG",
                            trigger_timeframe="8h", metadata={})
    assert spot_tohom_fired(_c, None) is False
