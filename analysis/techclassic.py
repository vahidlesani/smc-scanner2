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

# R99n: this setup OWNS its concurrent-chain allowance (Viva 10-15:
# no global first-come pool — a full neighbour book never starves us).
OWN_MAX_CONCURRENT_CHAINS = 30


TECHCLASSIC_ENGINES = {
    "detection": {
        "entry": "analysis.techclassic.tc_detect",
        "status": "wired",
        "notes": "existing detector; dedicated-geometry slice next",
    },
    "zoom": {"entry": "analysis.techclassic.tc_zoom_window", "status": "wired",
             "notes": "own smart-zoom (hand-pan spec); not the shared funnel"},
    "pivots": {"entry": "analysis.techclassic.tc_find_pivots", "status": "wired",
               "notes": "standard shadows count as pivots; body-drawn TLs rejected"},
    "candle_count": {"entry": "analysis.techclassic.tc_candles_for", "status": "wired",
                     "notes": "per-TF count from detected pattern; no min/max"},
    "zones_render": {"entry": "analysis.techclassic.tc_zones_from_pivots", "status": "wired",
                     "notes": "refined S/D boxes (soft blue/red) per TF + own render; DRAWN only"},
    "confirm_entry": {"entry": "analysis.techclassic.tc_entry_check",
                      "status": "wired",
                      "notes": "decision logic live; publish-path wiring next"},
    "trailing": {"entry": "analysis.techclassic.tc_trailing_check",
                 "status": "wired",
                 "notes": "live<=stop => STOPPED (confirm forbidden); trail-hit; precise exit"},
    "tohom": {"entry": "analysis.techclassic.tc_tohom_fired",
              "status": "wired",
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
                   direction: str = "LONG", live=None, entry=None, tp1=None,
                   day=None):
    """SEPARATE TC entry-law checker (§6.9). Pure + tested.

    Returns {"decision": "CONFIRM"|"WAIT"|"DEFERRED_BUDGET",
             "alarms": [...], "reasons": [...]}.
    A foreign gate NEVER vetoes: it raises an alarm and the entry proceeds.
    A late confirm (live beyond entry) is ANNOTATED, entry proceeds.
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
        _long = str(direction or "LONG").upper() != "SHORT"
        if live is not None and entry is not None:
            _late = (float(live) > float(entry)) if _long else (float(live) < float(entry))
            if _late:
                alarms.append(tc_alarm("LATE confirm annotated (live beyond entry)"))
                reasons.append("late annotated")
    except Exception:
        pass
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


def tc_detect(bundle, style="DAYTRADE"):
    """TC detection (engine 1): own wrapper over detect_technoclassic.

    Tags every minted candidate as TC-owned so the TC path (and only it)
    judges the chain afterwards.
    """
    from analysis.pattern_engine import detect_technoclassic as _det
    cand = _det(bundle, style)
    if cand is not None:
        try:
            if not isinstance(getattr(cand, "metadata", None), dict):
                cand.metadata = {}
            cand.metadata["tc_owned"] = True
        except Exception:
            pass
    return cand


def tc_find_pivots(highs, lows, left=2, right=2):
    """TC pivots (engine 3): fractal swings on WICK highs/lows.

    Standard shadows COUNT as pivots (user law) — highs/lows include wicks.
    Returns {"highs": [(i, price)], "lows": [(i, price)]}.
    """
    try:
        _h = [float(x) for x in (highs or [])]
        _l = [float(x) for x in (lows or [])]
    except Exception:
        return {"highs": [], "lows": []}
    _n = min(len(_h), len(_l))
    _hi, _lo = [], []
    for i in range(int(left), _n - int(right)):
        _ph = _h[i]
        if all(_ph >= _h[j] for j in range(i - int(left), i + int(right) + 1) if j != i) and \
                any(_ph > _h[j] for j in range(i - int(left), i + int(right) + 1) if j != i):
            _hi.append((i, _ph))
        _pl = _l[i]
        if all(_pl <= _l[j] for j in range(i - int(left), i + int(right) + 1) if j != i) and \
                any(_pl < _l[j] for j in range(i - int(left), i + int(right) + 1) if j != i):
            _lo.append((i, _pl))
    return {"highs": _hi, "lows": _lo}


def tc_candles_for(tf, pattern_span):
    """TC candle count (engine 4): FROM the detected pattern (no min/max).

    Detected span + 40 context bars (the R64 warm-up pad, kept).
    """
    try:
        return max(1, int(pattern_span or 0) + 40)
    except Exception:
        return 300


def tc_zoom_window(n_bars, count, pad_right_frac=0.12):
    """TC zoom (engine 2): window from the count — pattern-anchored right.

    Returns (x_from, x_to); the right pad keeps the live edge breathing.
    """
    try:
        _n, _c = int(n_bars), max(1, int(count))
        _x_to = _n - 1 + int(_c * float(pad_right_frac))
        return (max(0, _x_to - _c), _x_to)
    except Exception:
        return (0, max(0, int(n_bars or 0) - 1))


def tc_zones_from_pivots(pivots, direction="LONG"):
    """TC zones (engine 5): refined S/D boxes from the two latest swings.

    DRAWN on TC charts only — never gates entries (§6.9).
    Returns [{"side": "supply"|"demand", "top": f, "bottom": f}].
    """
    try:
        _p = pivots or {}
        _out = []
        _his = [float(p[1]) for p in (_p.get("highs") or [])[-2:]]
        _los = [float(p[1]) for p in (_p.get("lows") or [])[-2:]]
        if len(_his) == 2:
            _out.append({"side": "supply", "top": max(_his), "bottom": min(_his)})
        if len(_los) == 2:
            _out.append({"side": "demand", "top": max(_los), "bottom": min(_los)})
        return _out
    except Exception:
        return []


def tc_tohom_fired(candidate, lower_closed_df=None, **kw):
    """TC TOHOM hook (engine 8): True when the smart engine confirms early."""
    try:
        from analysis.tohom import evaluate_tohom_confirmation as _ev
        _ok, _c, _reason = _ev(candidate, lower_closed_df, **kw)
        return bool(_ok)
    except Exception:
        return False
