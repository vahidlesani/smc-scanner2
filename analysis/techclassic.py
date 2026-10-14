"""TECHCLASSIC home — فاز نظم و انضباط (R99b + R99d entry engine).

End-state law (VIVA_USER_LAWS.md §10): every setup owns ONE file under
analysis/ holding ALL its engines. This is TECHCLASSIC's file; its handoff
and rules live HERE (§10), separate from every other setup.

Engines (VIVA_USER_LAWS.md §6): detection, zoom, pivots, candle_count,
zones_render, confirm_entry, trailing, tohom, entry_rules (SEPARATE).

Entry law (§6.9 + §8): instant CONFIRM right after break+close (or via own
TOHOM). Zones are DRAWN for TC but must NEVER gate/veto its entries — any
foreign gate found in the TC path raises an ALARM and the entry proceeds
(the veto is REFUSED, never silent). Confirms of alerted chains are never
budget-gated; NEW mints respect the daily TOTAL cap (fail-open).
"""

TECHCLASSIC_ENGINES = {
    "detection": {
        "entry": "analysis.pattern_engine.detect_technoclassic",
        "status": "declared",
        "notes": "existing detector; dedicated-geometry slice next",
    },
    "zoom": {"entry": None, "status": "declared",
             "notes": "own smart-zoom (hand-pan spec); not the shared funnel"},
    "pivots": {"entry": None, "status": "declared",
               "notes": "standard shadows count as pivots; body-drawn TLs rejected"},
    "candle_count": {"entry": None, "status": "declared",
                     "notes": "per-TF count from detected pattern; no min/max"},
    "zones_render": {"entry": None, "status": "declared",
                     "notes": "refined S/D boxes (soft blue/red) per TF + own render; DRAWN only"},
    "confirm_entry": {"entry": "analysis.techclassic.tc_entry_check",
                      "status": "wired",
                      "notes": "decision logic live; publish-path wiring next"},
    "trailing": {"entry": "analysis.techclassic.tc_trailing_check",
                 "status": "wired",
                 "notes": "live<=stop => STOPPED (confirm forbidden); trail-hit; precise exit"},
    "tohom": {"entry": "analysis.tohom",
              "status": "declared",
              "notes": "module exists; TC hook takes tohom_fired as input (wiring next)"},
    "entry_rules": {"entry": "analysis.techclassic.tc_entry_check",
                    "status": "wired", "separate": True,
                    "notes": "SEPARATE checker; foreign gates alarm + veto refused"},
}

TC_ENTRY_RULES = {
    "instant_confirm_after_break_close": True,
    "tohom_early_entry": True,
    "final_chartless_pct": 0.4,
    "confirm_with_tool_pct": 0.2,
    "forbidden_gates": ["pinwall_zone_veto", "albrox_zone_veto", "cross_setup_veto"],
    "zones_may_draw": True,   # §6.5 — TC paints zones on its charts
    "zones_may_gate": False,  # §6.9 — zones must NEVER veto TC entries
}


def get_tc_engine(name):
    """Return one TECHCLASSIC engine entry, or None if unknown."""
    return TECHCLASSIC_ENGINES.get(str(name or "").lower())


def tc_health_check(candidate=None):
    """Debugger stub (§11): return a list of issue strings (empty = healthy).

    Wired checks land here engine by engine; any non-empty result must raise
    an alarm via tc_alarm so a human sees it.
    """
    _ = candidate
    return []


def tc_alarm(message):
    """Alarm stub (§11): format an alarm payload (routing wired later)."""
    return f"[TC-ALARM] {message}"


def _foreign_gate_hit(gate_name: str) -> bool:
    _g = str(gate_name or "").lower()
    if not _g:
        return False
    if _g in TC_ENTRY_RULES["forbidden_gates"]:
        return True
    return ("veto" in _g) or ("zone" in _g and "pinwall" in _g) or ("zone" in _g and "albrox" in _g)


def tc_entry_check(*, broke: bool, closed_after_break: bool,
                   tohom_fired: bool = False, foreign_gates=(),
                   day=None):
    """SEPARATE TC entry-law checker (§6.9). Pure + tested.

    Returns {"decision": "CONFIRM"|"WAIT"|"DEFERRED_BUDGET",
             "alarms": [...], "reasons": [...]}.
    A foreign gate NEVER vetoes: it raises an alarm and the entry proceeds.
    """
    alarms, reasons = [], []
    for _g in (foreign_gates or ()):
        if _foreign_gate_hit(_g):
            alarms.append(tc_alarm(
                f"foreign gate in TC path: {_g} — veto REFUSED, entry proceeds"))
    if not broke:
        reasons.append("no break yet")
        return {"decision": "WAIT", "alarms": alarms, "reasons": reasons}
    if not (closed_after_break or tohom_fired):
        reasons.append("break without close/TOHOM — waiting for the trigger")
        return {"decision": "WAIT", "alarms": alarms, "reasons": reasons}
    try:
        from analysis import tiered_scan as _ts
        _budget_ok = bool(_ts.daily_budget_ok(day))
    except Exception:
        _budget_ok = True
    if not _budget_ok:
        reasons.append("daily TOTAL cap reached — deferred, never dropped")
        return {"decision": "DEFERRED_BUDGET", "alarms": alarms,
                "reasons": reasons}
    try:
        from analysis import tiered_scan as _ts2
        _ts2.daily_count_incr("futures", day)
    except Exception:
        pass
    reasons.append("tohom early entry" if tohom_fired and not closed_after_break
                   else "instant confirm after break+close")
    return {"decision": "CONFIRM", "alarms": alarms, "reasons": reasons}


def tc_trailing_check(*, entry, stop, live, direction="LONG", trail=None):
    """TC trailing/exit engine (R99e). Pure + tested.

    LONG:  live <= stop  => STOPPED (a CONFIRM must never publish; EXIT).
    SHORT: live >= stop  => STOPPED. A breached `trail` level => TRAIL_HIT.
    Returns {"state": "STOPPED"|"TRAIL_HIT"|"HEALTHY", "alarms": [...],
             "reasons": [...]}.
    """
    alarms, reasons = [], []
    try:
        _e, _s, _l = float(entry), float(stop), float(live)
    except Exception:
        return {"state": "HEALTHY", "alarms": alarms,
                "reasons": ["unusable numbers — fail-open"]}
    _long = str(direction or "LONG").upper() != "SHORT"
    _dead = (_l <= _s) if _long else (_l >= _s)
    if _dead:
        alarms.append(tc_alarm(
            f"position STOPPED (live {_l:,.0f} beyond stop {_s:,.0f}) — "
            "EXIT, never CONFIRM"))
        reasons.append("live beyond stop")
        return {"state": "STOPPED", "alarms": alarms, "reasons": reasons}
    if trail:
        try:
            _t = float(trail)
            _hit = (_l <= _t) if _long else (_l >= _t)
            if _hit:
                alarms.append(tc_alarm(f"trail level {_t:,.0f} hit — exit"))
                reasons.append("trail hit")
                return {"state": "TRAIL_HIT", "alarms": alarms,
                        "reasons": reasons}
        except Exception:
            pass
    _dist = abs(_l - _s) / _s * 100 if _s else 0.0
    reasons.append(f"healthy ({_dist:.2f}% from stop)")
    return {"state": "HEALTHY", "alarms": alarms, "reasons": reasons}
