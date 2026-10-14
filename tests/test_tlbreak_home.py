"""R99i-TLBREAK — tlbreak discipline-home tests."""
import analysis.tiered_scan as _ts
from analysis.tlbreak import (
    TLBREAK_ENGINES, TLBREAK_ENTRY_RULES, get_tlbreak_engine,
    tlbreak_health_check, tlbreak_alarm, tlbreak_detect, tlbreak_find_pivots,
    tlbreak_candles_for, tlbreak_zoom_window, tlbreak_zones_from_pivots,
    tlbreak_entry_check, tlbreak_trailing_check, tlbreak_tohom_fired,
)


def test_tlbreak_all_nine_wired():
    assert sorted(TLBREAK_ENGINES) == [
        "candle_count", "confirm_entry", "detection", "entry_rules",
        "pivots", "tohom", "trailing", "zones_render", "zoom"]
    for _name, _e in TLBREAK_ENGINES.items():
        assert _e["status"] == "wired", _name
        assert _e["entry"], _name


def test_tlbreak_rules_inner_rails_no_zones():
    assert TLBREAK_ENTRY_RULES["inner_ceiling_floor"] is True
    assert TLBREAK_ENTRY_RULES["single_tl_breaks_confirm"] is True
    assert TLBREAK_ENTRY_RULES["steep_lines_never_vetoed"] is True
    assert tlbreak_zones_from_pivots({"highs": [(1, 2.0)], "lows": []}) == []
    assert get_tlbreak_engine("NOPE") is None
    assert tlbreak_health_check(None) == []
    assert tlbreak_alarm("x").startswith("[TLBREAK-ALARM]")


def test_tlbreak_detect_delegates_and_tags(monkeypatch):
    import types as _t

    def _fake(bundle, style):
        return _t.SimpleNamespace(metadata={})

    monkeypatch.setattr("analysis.setups_experimental.detect_viva_tlbreak", _fake)
    assert tlbreak_detect(object(), "SWING").metadata.get("tlbreak_owned") is True


def test_tlbreak_pivots_candles_zoom():
    _p = tlbreak_find_pivots([1, 2, 3, 2, 1, 2, 5, 2, 1],
                             [1, 2, 3, 2, 0.5, 2, 5, 2, 1])
    assert (6, 5.0) in _p["highs"] and (4, 0.5) in _p["lows"]
    assert tlbreak_candles_for("1d", 150) == 190
    assert tlbreak_zoom_window(300, 160) == (158, 318)


def _fake_kv(monkeypatch, store):
    class _KV:
        @staticmethod
        def get_json(_k, default=None):
            return store.get(_k, default)

        @staticmethod
        def set_json(_k, _v):
            return store.get(_k, default)

        @staticmethod
        def set_json(_k, _v):
            store[_k] = _v
            return True

    monkeypatch.setattr(_ts, "_kv", lambda: _KV)


def test_tlbreak_entry_side_late_budget(monkeypatch):
    _fake_kv(monkeypatch, {})
    _r = tlbreak_entry_check(broke=True, closed_after_break=True, side="ceiling",
                             day="2099-07-01")
    assert _r["decision"] == "CONFIRM" and any("ceiling" in x for x in _r["reasons"])
    _v = tlbreak_entry_check(broke=True, closed_after_break=True,
                             foreign_gates=["pinval_veto"], day="2099-07-01")
    assert _v["decision"] == "CONFIRM" and len(_v["alarms"]) == 1
    _l = tlbreak_entry_check(broke=True, closed_after_break=True,
                             direction="SHORT", live=95.0, entry=100.0,
                             day="2099-07-01")
    assert any("LATE" in a for a in _l["alarms"])
    _fake_kv(monkeypatch, {"tier_day_count:2099-07-02:futures": 24,
                           "tier_day_count:2099-07-02:spot": 1})
    assert tlbreak_entry_check(broke=True, closed_after_break=True,
                               day="2099-07-02")["decision"] == "DEFERRED_BUDGET"


def test_tlbreak_trailing_stop_runner():
    assert tlbreak_trailing_check(entry=100.0, stop=98.0, live=97.0)["state"] == "STOPPED"
    _r = tlbreak_trailing_check(entry=100.0, stop=98.0, live=102.0,
                                profit_pct=5.5, confirmed=False)
    assert _r["state"] == "HEALTHY" and len(_r["alarms"]) == 1


def test_tlbreak_tohom_no_crash():
    import types as _t
    _c = _t.SimpleNamespace(setup_code="TLBREAK", direction="SHORT",
                            trigger_timeframe="1d", metadata={})
    assert tlbreak_tohom_fired(_c, None) is False
