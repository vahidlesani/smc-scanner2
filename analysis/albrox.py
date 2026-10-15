"""ALBROX home — فاز نظم و انضباط (R99i).

The UNION setup (r60): Brooks-style structural entries (breakout legs,
second entries, micro-structure). Structural lane: instant confirm at
break — first close after the break. Own zones may draw (and judge for
ALBROX only); foreign gates alarm + veto refused. Late confirm =
annotation, entry proceeds.
"""

# R99n: this setup OWNS its concurrent-chain allowance (Viva 10-15:
# no global first-come pool — a full neighbour book never starves us).
OWN_MAX_CONCURRENT_CHAINS = 30


ALBROX_ENGINES = {
    "detection": {"entry": "analysis.albrox.albrox_detect", "status": "wired",
                  "notes": "own wrapper over detect_albrox; tags albrox_owned"},
    "zoom": {"entry": "analysis.albrox.albrox_zoom_window", "status": "wired",
             "notes": "window from the count; leg-anchored right"},
    "pivots": {"entry": "analysis.albrox.albrox_find_pivots", "status": "wired",
               "notes": "fractals on wick highs/lows; shadows count"},
    "candle_count": {"entry": "analysis.albrox.albrox_candles_for", "status": "wired",
                     "notes": "FROM the pattern span; no min/max"},
    "zones_render": {"entry": "analysis.albrox.albrox_zones_from_pivots", "status": "wired",
                     "notes": "own refined boxes; only OWN zones judge"},
    "confirm_entry": {"entry": "analysis.albrox.albrox_entry_check", "status": "wired",
                      "notes": "structural instant confirm at break+close"},
    "trailing": {"entry": "analysis.albrox.albrox_trailing_check", "status": "wired",
                 "notes": "live beyond stop => STOPPED; 5% runner alarm"},
    "tohom": {"entry": "analysis.albrox.albrox_tohom_fired", "status": "wired",
              "notes": "early-confirm hook on the shared TOHOM evaluator"},
    "entry_rules": {"entry": "analysis.albrox.albrox_entry_check", "status": "wired",
                    "separate": True,
                    "notes": "SEPARATE; foreign gates alarm + veto refused"},
}

ALBROX_ENTRY_RULES = {
    "union_setup": True,
    "instant_confirm_after_break_close": True,
    "tohom_early_entry": True,
    "forbidden_gates": ["techclassic_veto", "tlbreak_veto", "pinval_veto",
                        "pinwall_veto", "cross_setup_veto"],
    "zones_may_draw": True,
    "zones_may_gate": "own-only",
}


def get_albrox_engine(name):
    return ALBROX_ENGINES.get(str(name or "").lower())


def albrox_health_check(candidate=None):
    _ = candidate
    return []


def albrox_alarm(message):
    return f"[ALBROX-ALARM] {message}"


def _foreign_gate_hit(gate_name: str) -> bool:
    _g = str(gate_name or "").lower()
    if not _g:
        return False
    if _g in ALBROX_ENTRY_RULES["forbidden_gates"]:
        return True
    return ("veto" in _g) and any(_s in _g for _s in
                                  ("techclassic", "tlbreak", "pinval", "pinwall"))


def albrox_detect(bundle, style="DAYTRADE"):
    from analysis.setups_experimental import detect_albrox as _det
    cand = _det(bundle, style)
    if cand is not None:
        try:
            if not isinstance(getattr(cand, "metadata", None), dict):
                cand.metadata = {}
            cand.metadata["albrox_owned"] = True
        except Exception:
            pass
    return cand


def albrox_find_pivots(highs, lows, left=2, right=2):
    try:
        _h = [float(x) for x in (highs or [])]
        _l = [float(x) for x in (lows or [])]
    except Exception:
        return {"highs": [], "lows": []}
    _n = min(len(_h), len(_l))
    _hi, _lo = [], []
    for i in range(int(left), _n - int(right)):
        _w = list(range(i - int(left), i + int(right) + 1))
        _w.remove(i)
        if all(_h[i] >= _h[j] for j in _w) and any(_h[i] > _h[j] for j in _w):
            _hi.append((i, _h[i]))
        if all(_l[i] <= _l[j] for j in _w) and any(_l[i] < _l[j] for j in _w):
            _lo.append((i, _l[i]))
    return {"highs": _hi, "lows": _lo}


def albrox_candles_for(tf, pattern_span):
    try:
        return max(1, int(pattern_span or 0) + 40)
    except Exception:
        return 300


def albrox_zoom_window(n_bars, count, pad_right_frac=0.12):
    try:
        _n, _c = int(n_bars), max(1, int(count))
        _x_to = _n - 1 + int(_c * float(pad_right_frac))
        return (max(0, _x_to - _c), _x_to)
    except Exception:
        return (0, max(0, int(n_bars or 0) - 1))


def albrox_zones_from_pivots(pivots, direction="LONG"):
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


def albrox_entry_check(*, broke: bool, closed_after_break: bool,
                       tohom_fired: bool = False, direction: str = "LONG",
                       live=None, entry=None, tp1=None,
                       foreign_gates=(), day=None):
    alarms, reasons = [], []
    for _g in (foreign_gates or ()):
        if _foreign_gate_hit(_g):
            alarms.append(albrox_alarm(
                f"foreign gate in ALBROX path: {_g} — veto REFUSED, entry proceeds"))
    if not broke:
        reasons.append("no break yet")
        return {"decision": "WAIT", "alarms": alarms, "reasons": reasons}
    if not (closed_after_break or tohom_fired):
        reasons.append("break without close/TOHOM")
        return {"decision": "WAIT", "alarms": alarms, "reasons": reasons}
    try:
        from analysis import tiered_scan as _ts
        _budget_ok = bool(_ts.daily_budget_ok(day))
    except Exception:
        _budget_ok = True
    if not _budget_ok:
        reasons.append("daily TOTAL cap reached — deferred, never dropped")
        return {"decision": "DEFERRED_BUDGET", "alarms": alarms, "reasons": reasons}
    try:
        _long = str(direction or "LONG").upper() != "SHORT"
        if live is not None and entry is not None:
            _late = (float(live) > float(entry)) if _long else (float(live) < float(entry))
            if _late:
                alarms.append(albrox_alarm("LATE confirm annotated (live beyond entry)"))
                reasons.append("late annotated")
    except Exception:
        pass
    try:
        from analysis import tiered_scan as _ts2
        _ts2.daily_count_incr("futures", day)
    except Exception:
        pass
    reasons.append("structural instant confirm at break+close")
    return {"decision": "CONFIRM", "alarms": alarms, "reasons": reasons}


def albrox_trailing_check(*, entry, stop, live, direction="LONG", trail=None,
                          profit_pct=None, confirmed=True):
    alarms, reasons = [], []
    try:
        _e, _s, _l = float(entry), float(stop), float(live)
    except Exception:
        return {"state": "HEALTHY", "alarms": alarms,
                "reasons": ["unusable numbers — fail-open"]}
    _long = str(direction or "LONG").upper() != "SHORT"
    if (_l <= _s) if _long else (_l >= _s):
        alarms.append(albrox_alarm("position STOPPED (live beyond stop) — never CONFIRM"))
        reasons.append("live beyond stop")
        return {"state": "STOPPED", "alarms": alarms, "reasons": reasons}
    if trail:
        try:
            _t = float(trail)
            if (_l <= _t) if _long else (_l >= _t):
                alarms.append(albrox_alarm("trail level hit — exit"))
                reasons.append("trail hit")
                return {"state": "TRAIL_HIT", "alarms": alarms, "reasons": reasons}
        except Exception:
            pass
    try:
        if profit_pct is not None and float(profit_pct) >= 5.0 and not confirmed:
            alarms.append(albrox_alarm("5% runner WITHOUT confirm — bug, annotate"))
            reasons.append("unconfirmed runner")
    except Exception:
        pass
    reasons.append("healthy")
    return {"state": "HEALTHY", "alarms": alarms, "reasons": reasons}


def albrox_tohom_fired(candidate, lower_closed_df=None, **kw):
    try:
        from analysis.tohom import evaluate_tohom_confirmation as _ev
        _ok, _c, _reason = _ev(candidate, lower_closed_df, **kw)
        return bool(_ok)
    except Exception:
        return False
