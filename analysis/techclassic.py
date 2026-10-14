"""TECHCLASSIC home — فاز نظم و انضباط (R99b-TC-home).

End-state law (VIVA_USER_LAWS.md §10): every setup owns ONE file under
analysis/ holding ALL its engines. This is TECHCLASSIC's file; its handoff
and rules live HERE (§10), separate from every other setup.

Engines (VIVA_USER_LAWS.md §6):
  1. detection     — smart TL/pattern detection
  2. zoom          — smart zoom
  3. pivots        — correct-pivot detection
  4. candle_count  — per-TF candle count from the detected pattern
  5. zones_render  — refined S/D zones per TF (soft blue/red boxes) + render
  6. confirm_entry — confirm + position entry
  7. trailing      — smart stop trailing
  8. tohom         — smart early entry before close
  9. entry_rules   — SEPARATE entry-law checker; NO other gate may sit in
                     front of it (the old bug: zones used to veto TC entries).

Entry law: instant confirm right after break+close (or via own TOHOM).
Zones are DRAWN for TC but must NEVER gate/veto its entries.

DATA ONLY in this slice — nothing imports this module in production yet.
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
    "confirm_entry": {"entry": None, "status": "declared",
                      "notes": "instant confirm at break; confirm-with-tool at 0.2% pre-entry"},
    "trailing": {"entry": None, "status": "declared",
                 "notes": "precise trailing + smart exit on opposite patterns"},
    "tohom": {"entry": None, "status": "declared",
              "notes": "smart early entry before close; never fake"},
    "entry_rules": {"entry": None, "status": "declared", "separate": True,
                    "notes": "SEPARATE checker; forbidden_gates must be empty in TC path"},
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
