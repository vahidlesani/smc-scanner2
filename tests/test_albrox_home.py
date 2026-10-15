"""R99i-ALBROX — albrox discipline-home tests."""
import analysis.tiered_scan as _ts
from analysis.albrox import (
    ALBROX_ENGINES, ALBROX_ENTRY_RULES, get_albrox_engine,
    albrox_health_check, albrox_alarm, albrox_detect, albrox_find_pivots,
    albrox_candles_for, albrox_zoom_window, albrox_zones_from_pivots,
    albrox_entry_check, albrox_trailing_check, albrox_tohom_fired,
)


def test_albrox_all_nine_wired():
    assert sorted(ALBROX_ENGINES) == [
        "candle_count", "confirm_entry", "detection", "entry_rules",
        "pivots", "tohom", "trailing", "zones_render", "zoom"]
    for _name, _e in ALBROX_ENGINES.items():
        assert _e["status"] == "wired", _name
        assert _e["entry"], _name


def test_albrox_rules_union_zones():
    assert ALBROX_ENTRY_RULES["union_setup"] is True
    assert ALBROX_ENTRY_RULES["zones_may_gate"] == "own-only"
    assert get_albrox_engine("NOPE") is None
    assert albrox_health_check(None) == []
    assert albrox_alarm("x").startswith("[ALBROX-ALARM]")


def test_albrox_detect_delegates_and_tags(monkeypatch):
    import types as _t

    def _fake(bundle, style):
        return _t.SimpleNamespace(metadata={})

    monkeypatch.setattr("analysis.setups_experimental.detect_albrox", _fake)
    assert albrox_detect(object(), "DAYTRADE").metadata.get("albrox_owned") is True


def test_albrox_pivots_candles_zoom_zones():
    _p = albrox_find_pivots([1, 2, 3, 2, 1, 2, 5, 2, 1],
                            [1, 2, 3, 2, 0.5, 2, 5, 2, 1])
    assert (6, 5.0) in _p["highs"] and (4, 0.5) in _p["lows"]
    assert albrox_candles_for("4h", 200) == 240
    assert albrox_zoom_window(300, 160) == (158, 318)
    _z = albrox_zones_from_pivots(
        {"highs": [(1, 2.0), (2, 2.1)], "lows": [(1, 1.5), (2, 1.6)]})
    assert (_z[0]["top"], _z[1]["bottom"]) == (2.1, 1.5)


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


def test_albrox_entry_structural_late_budget(monkeypatch):
    _fake_kv(monkeypatch, {})
    _r = albrox_entry_check(broke=True, closed_after_break=True, day="2099-06-01")
    assert _r["decision"] == "CONFIRM" and _r["alarms"] == []
    _v = albrox_entry_check(broke=True, closed_after_break=True,
                            foreign_gates=["tlbreak_veto"], day="2099-06-01")
    assert _v["decision"] == "CONFIRM" and len(_v["alarms"]) == 1
    _l = albrox_entry_check(broke=True, closed_after_break=True,
                            live=105.0, entry=100.0, day="2099-06-01")
    assert any("LATE" in a for a in _l["alarms"])
    # R99q (his «گیت خشک‌کننده رو بردار»): the daily TOTAL budget is retired —
    # even with the old counter at 25/25 the entry CONFIRMS, never defers.
    _fake_kv(monkeypatch, {"tier_day_count:2099-06-02:futures": 25})
    assert albrox_entry_check(broke=True, closed_after_break=True,
                              day="2099-06-02")["decision"] == "CONFIRM"


def test_albrox_trailing_stop_runner():
    assert albrox_trailing_check(entry=100.0, stop=98.0, live=97.5)["state"] == "STOPPED"
    _r = albrox_trailing_check(entry=100.0, stop=98.0, live=104.0,
                               profit_pct=7.0, confirmed=False)
    assert _r["state"] == "HEALTHY" and len(_r["alarms"]) == 1


def test_albrox_tohom_no_crash():
    import types as _t
    _c = _t.SimpleNamespace(setup_code="ALBROX", direction="LONG",
                            trigger_timeframe="4h", metadata={})
    assert albrox_tohom_fired(_c, None) is False
