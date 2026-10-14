"""R99b-TC-home — TECHCLASSIC discipline-home tests."""
import importlib

from analysis.techclassic import (
    TECHCLASSIC_ENGINES, TC_ENTRY_RULES,
    get_tc_engine, tc_health_check, tc_alarm,
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
