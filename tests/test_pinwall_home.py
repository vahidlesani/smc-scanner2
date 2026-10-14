"""R99i-PINWALL — pinwall discipline-home tests."""
import analysis.tiered_scan as _ts
from analysis.pinwall import (
    PINWALL_ENGINES, PINWALL_ENTRY_RULES, get_pinwall_engine,
    pinwall_health_check, pinwall_alarm, pinwall_detect, pinwall_find_pivots,
    pinwall_candles_for, pinwall_zoom_window, pinwall_zones_from_pivots,
    pinwall_entry_check, pinwall_trailing_check, pinwall_tohom_fired,
)


def test_pinwall_all_nine_wired():
    assert sorted(PINWALL_ENGINES) == [
        "candle_count", "confirm_entry", "detection", "entry_rules",
        "pivots", "tohom", "trailing", "zones_render", "zoom"]
    for _name, _e in PINWALL_ENGINES.items():
        assert _e["status"] == "wired", _name
        assert _e["entry"], _name


def test_pinwall_rules_counter_trend_union():
    assert PINWALL_ENTRY_RULES["counter_trend_only"] is True
    assert PINWALL_ENTRY_RULES["union_carriers"] == [
        "TECHCLASSIC", "TLBREAK", "ALBROX", "PINWALL"]
    assert get_pinwall_engine("NOPE") is None
    assert pinwall_health_check(None) == []
    assert pinwall_alarm("x").startswith("[PINWALL-ALARM]")


def test_pinwall_detect_delegates_and_tags(monkeypatch):
    import types as _t

    def _fake(bundle, style):
        return _t.SimpleNamespace(metadata={})

    monkeypatch.setattr("analysis.setups_experimental.detect_pinwall_quality", _fake)
    assert pinwall_detect(object(), "SWING").metadata.get("pinwall_owned") is True


def test_pinwall_pivots_candles_zoom_zones():
    _p = pinwall_find_pivots([1, 2, 3, 2, 1, 2, 5, 2, 1],
                             [1, 2, 3, 2, 0.5, 2, 5, 2, 1])
    assert (6, 5.0) in _p["highs"] and (4, 0.5) in _p["lows"]
    assert pinwall_candles_for("1h", 120) == 160
    assert pinwall_zoom_window(300, 160) == (158, 318)
    _z = pinwall_zones_from_pivots(
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


def test_pinwall_entry_union_and_refuse(monkeypatch):
    _fake_kv(monkeypatch, {})
    _r = pinwall_entry_check(broke=True, closed_after_break=True,
                             carried_by="TLBREAK", day="2099-04-01")
    assert _r["decision"] == "CONFIRM"
    assert any("TLBREAK" in x for x in _r["reasons"])
    _w = pinwall_entry_check(broke=True, closed_after_break=True,
                             carried_by="NOPE", day="2099-04-01")
    assert _w["decision"] == "WAIT"
    _f = pinwall_entry_check(broke=True, closed_after_break=True,
                             with_trend=True, day="2099-04-01")
    assert _f["decision"] == "REFUSED" and len(_f["alarms"]) == 1


def test_pinwall_entry_veto_late_budget(monkeypatch):
    _fake_kv(monkeypatch, {})
    _v = pinwall_entry_check(broke=True, closed_after_break=True,
                             foreign_gates=["albrox_veto"], day="2099-04-02")
    assert _v["decision"] == "CONFIRM" and len(_v["alarms"]) == 1
    _l = pinwall_entry_check(broke=True, closed_after_break=True,
                             live=102.0, entry=100.0, day="2099-04-02")
    assert _l["decision"] == "CONFIRM" and any("LATE" in a for a in _l["alarms"])
    _fake_kv(monkeypatch, {"tier_day_count:2099-04-03:futures": 25})
    _d = pinwall_entry_check(broke=True, closed_after_break=True, day="2099-04-03")
    assert _d["decision"] == "DEFERRED_BUDGET"


def test_pinwall_trailing_stop_runner():
    _s = pinwall_trailing_check(entry=100.0, stop=98.0, live=97.0)
    assert _s["state"] == "STOPPED"
    _r = pinwall_trailing_check(entry=100.0, stop=98.0, live=101.0,
                                profit_pct=6.0, confirmed=False)
    assert _r["state"] == "HEALTHY" and len(_r["alarms"]) == 1
    assert pinwall_trailing_check(entry=100.0, stop=98.0, live=101.0)["alarms"] == []


def test_pinwall_tohom_no_crash():
    import types as _t
    _c = _t.SimpleNamespace(setup_code="PINWALL", direction="SHORT",
                            trigger_timeframe="1h", metadata={})
    assert pinwall_tohom_fired(_c, None) is False
