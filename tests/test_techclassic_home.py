"""R99b-TC-home + R99d entry engine — TECHCLASSIC discipline tests."""
import importlib

import analysis.tiered_scan as _ts
from analysis.techclassic import (
    TECHCLASSIC_ENGINES, TC_ENTRY_RULES,
    get_tc_engine, tc_health_check, tc_alarm, tc_entry_check,
    tc_trailing_check,
)


def test_tc_has_nine_engines():
    assert sorted(TECHCLASSIC_ENGINES) == [
        "candle_count", "confirm_entry", "detection", "entry_rules",
        "pivots", "tohom", "trailing", "zones_render", "zoom"]


def test_tc_detection_entry_resolves():
    dotted = TECHCLASSIC_ENGINES["detection"]["entry"]
    mod_name, attr = dotted.rsplit(".", 1)
    assert callable(getattr(importlib.import_module(mod_name), attr))


def test_tc_entry_rules_separate_and_instant():
    assert TECHCLASSIC_ENGINES["entry_rules"].get("separate") is True
    assert TECHCLASSIC_ENGINES["entry_rules"]["status"] == "wired"
    assert TC_ENTRY_RULES["instant_confirm_after_break_close"] is True
    assert TC_ENTRY_RULES["tohom_early_entry"] is True
    assert TC_ENTRY_RULES["final_chartless_pct"] == 0.4
    assert TC_ENTRY_RULES["confirm_with_tool_pct"] == 0.2


def test_tc_zones_draw_but_never_gate():
    assert TC_ENTRY_RULES["zones_may_draw"] is True
    assert TC_ENTRY_RULES["zones_may_gate"] is False
    for g in ("pinwall_zone_veto", "albrox_zone_veto", "cross_setup_veto"):
        assert g in TC_ENTRY_RULES["forbidden_gates"]


def test_tc_debugger_and_alarm_stubs():
    assert tc_health_check(None) == []
    msg = tc_alarm("geometry drift on 4h")
    assert "geometry drift on 4h" in msg
    assert msg.startswith("[TC-ALARM]")


def test_tc_get_engine_unknown_safe():
    assert get_tc_engine("nope") is None
    assert get_tc_engine("") is None
    assert get_tc_engine("ZOOM") == TECHCLASSIC_ENGINES["zoom"]


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


def test_tc_entry_instant_confirm_and_wait(monkeypatch):
    _fake_kv(monkeypatch, {})
    assert tc_entry_check(broke=False, closed_after_break=False,
                          day="2099-02-01")["decision"] == "WAIT"
    assert tc_entry_check(broke=True, closed_after_break=False,
                          day="2099-02-01")["decision"] == "WAIT"
    _r = tc_entry_check(broke=True, closed_after_break=True, day="2099-02-01")
    assert _r["decision"] == "CONFIRM" and _r["alarms"] == []


def test_tc_entry_tohom_early(monkeypatch):
    _fake_kv(monkeypatch, {})
    _r = tc_entry_check(broke=True, closed_after_break=False, tohom_fired=True,
                        day="2099-02-02")
    assert _r["decision"] == "CONFIRM"
    assert any("tohom" in x for x in _r["reasons"])


def test_tc_entry_foreign_veto_refused_with_alarm(monkeypatch):
    _fake_kv(monkeypatch, {})
    _r = tc_entry_check(broke=True, closed_after_break=True,
                        foreign_gates=["pinwall_zone_veto", "ok_gate"],
                        day="2099-02-03")
    assert _r["decision"] == "CONFIRM"  # veto REFUSED, entry proceeds
    assert len(_r["alarms"]) == 1 and "pinwall_zone_veto" in _r["alarms"][0]


def test_tc_trailing_btc_case_stopped():
    # BTC-1D sample: entry 86,794 / stop 85,603 / live 81,814 LONG.
    _r = tc_trailing_check(entry=86794, stop=85603, live=81814,
                           direction="LONG")
    assert _r["state"] == "STOPPED"
    assert len(_r["alarms"]) == 1 and "never CONFIRM" in _r["alarms"][0]


def test_tc_trailing_healthy_and_short_mirror():
    _h = tc_trailing_check(entry=86794, stop=85603, live=87000,
                           direction="LONG")
    assert _h["state"] == "HEALTHY" and _h["alarms"] == []
    _s = tc_trailing_check(entry=86794, stop=87800, live=88000,
                           direction="SHORT")
    assert _s["state"] == "STOPPED"
    _t = tc_trailing_check(entry=86794, stop=84000, live=84500, trail=84838,
                           direction="LONG")
    assert _t["state"] == "TRAIL_HIT"


def test_tc_entry_budget_deferred_never_dropped(monkeypatch):
    _fake_kv(monkeypatch, {"tier_day_count:2099-02-04:futures": 20,
                           "tier_day_count:2099-02-04:spot": 5})
    _r = tc_entry_check(broke=True, closed_after_break=True, day="2099-02-04")
    assert _r["decision"] == "DEFERRED_BUDGET"
    assert any("never dropped" in x for x in _r["reasons"])
