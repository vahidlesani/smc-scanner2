"""R99b-TC-home + R99d entry engine — TECHCLASSIC discipline tests."""
import importlib

import analysis.tiered_scan as _ts
from analysis.techclassic import (
    TECHCLASSIC_ENGINES, TC_ENTRY_RULES,
    get_tc_engine, tc_health_check, tc_alarm, tc_entry_check,
    tc_trailing_check, tc_detect, tc_find_pivots, tc_candles_for,
    tc_zoom_window, tc_zones_from_pivots, tc_tohom_fired,
)


def test_tc_all_nine_wired():
    for _name, _e in TECHCLASSIC_ENGINES.items():
        assert _e["status"] == "wired", _name
        assert _e["entry"], _name


def test_tc_detect_delegates_and_tags(monkeypatch):
    import types as _t
    import analysis.techclassic as _tc

    _seen = {}

    def _fake(bundle, style):
        _seen["style"] = style
        return _t.SimpleNamespace(setup_code="TECHCLASSIC", metadata={})

    monkeypatch.setattr("analysis.pattern_engine.detect_technoclassic", _fake)
    _c = _tc.tc_detect(object(), "SWING")
    assert _seen["style"] == "SWING"
    assert _c.metadata.get("tc_owned") is True


def test_tc_pivots_fractal_on_wicks():
    _h = [1, 2, 3, 2, 1, 2, 5, 2, 1]
    _l = [1, 2, 3, 2, 0.5, 2, 5, 2, 1]
    _p = tc_find_pivots(_h, _l, left=2, right=2)
    assert (6, 5.0) in _p["highs"]
    assert (4, 0.5) in _p["lows"]
    assert tc_find_pivots([], []) == {"highs": [], "lows": []}


def test_tc_candles_zoom_math():
    assert tc_candles_for("1d", 120) == 160
    assert tc_zoom_window(300, 160) == (158, 318)
    assert tc_zoom_window(50, 160)[0] == 0


def test_tc_zones_boxes():
    _p = {"highs": [(5, 100.0), (9, 102.0)], "lows": [(3, 90.0), (7, 91.0)]}
    _z = tc_zones_from_pivots(_p)
    _s = [z for z in _z if z["side"] == "supply"][0]
    _d = [z for z in _z if z["side"] == "demand"][0]
    assert (_s["top"], _s["bottom"]) == (102.0, 100.0)
    assert (_d["top"], _d["bottom"]) == (91.0, 90.0)
    assert tc_zones_from_pivots({"highs": [], "lows": []}) == []


def test_tc_tohom_wrapper_no_crash():
    import types as _t
    _c = _t.SimpleNamespace(setup_code="TECHCLASSIC", direction="LONG",
                            trigger_timeframe="1h", metadata={})
    assert tc_tohom_fired(_c, None) is False


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


def test_tc_entry_late_annotated(monkeypatch):
    _fake_kv(monkeypatch, {})
    _r = tc_entry_check(broke=True, closed_after_break=True,
                        live=102.0, entry=100.0, day="2099-02-05")
    assert _r["decision"] == "CONFIRM"
    assert any("LATE" in a for a in _r["alarms"])


def test_tc_entry_budget_gate_retired(monkeypatch):
    """R99q (his «گیت خشک‌کننده سیگنال‌های ستاپ‌ها رو بردارررر»): the shared
    25/day budget used to dry every setup at once; now the old counters mean
    nothing — the entry CONFIRMS."""
    _fake_kv(monkeypatch, {"tier_day_count:2099-02-04:futures": 20,
                           "tier_day_count:2099-02-04:spot": 5})
    _r = tc_entry_check(broke=True, closed_after_break=True, day="2099-02-04")
    assert _r["decision"] == "CONFIRM"
