"""PINVAL home — فاز نظم و انضباط (R99i).

The old multi-gate mess is unified HERE: pinval_detect walks the
PINVAL_DETECTORS list in order — first hit wins, the firing gate is tagged
(metadata pinval_gate), ONE voice speaks. PINVAL's OWN polarity gate may
delay its entries (that is its law); foreign gates alarm + veto refused.
PINVAL draws NO zones (pin lines only).
"""

# R99n: this setup OWNS its concurrent-chain allowance (Viva 10-15:
# no global first-come pool — a full neighbour book never starves us).
OWN_MAX_CONCURRENT_CHAINS = 30


PINVAL_ENGINES = {
    "detection": {"entry": "analysis.pinval.pinval_detect", "status": "wired",
                  "notes": "unified walk over PINVAL_DETECTORS; tags firing gate"},
    "zoom": {"entry": "analysis.pinval.pinval_zoom_window", "status": "wired",
             "notes": "window from the count; pin-anchored right"},
    "pivots": {"entry": "analysis.pinval.pinval_find_pivots", "status": "wired",
               "notes": "fractals on wick highs/lows; shadows count"},
    "candle_count": {"entry": "analysis.pinval.pinval_candles_for", "status": "wired",
                     "notes": "FROM the pattern span; no min/max"},
    "zones_render": {"entry": "analysis.pinval.pinval_zones_from_pivots", "status": "wired",
                     "notes": "PINVAL draws NO zones by law — always []"},
    "confirm_entry": {"entry": "analysis.pinval.pinval_entry_check", "status": "wired",
                      "notes": "pin close + own polarity; instant on trigger"},
    "trailing": {"entry": "analysis.pinval.pinval_trailing_check", "status": "wired",
                 "notes": "live beyond stop => STOPPED; 5% runner alarm"},
    "tohom": {"entry": "analysis.pinval.pinval_tohom_fired", "status": "wired",
              "notes": "early-confirm hook on the shared TOHOM evaluator"},
    "entry_rules": {"entry": "analysis.pinval.pinval_entry_check", "status": "wired",
                    "separate": True,
                    "notes": "SEPARATE; own polarity may delay, foreign veto refused"},
}

PINVAL_ENTRY_RULES = {
    "own_polarity_gate": True,
                  # R99j (r40 09-26): this lane IS legacy PINWALL -
                  # users see it under the display name PINWALL.
                  "legacy_display_name": "PINWALL",
    "instant_confirm_after_break_close": True,
    "tohom_early_entry": True,
    "forbidden_gates": ["techclassic_veto", "tlbreak_veto", "pinwall_veto",
                        "albrox_veto", "cross_setup_veto"],
    "zones_may_draw": False,
    "zones_may_gate": False,
}


def get_pinval_engine(name):
    return PINVAL_ENGINES.get(str(name or "").lower())


def pinval_health_check(candidate=None):
    _ = candidate
    return []


def pinval_alarm(message):
    return f"[PINVAL-ALARM] {message}"


def _foreign_gate_hit(gate_name: str) -> bool:
    _g = str(gate_name or "").lower()
    if not _g:
        return False
    if _g in PINVAL_ENTRY_RULES["forbidden_gates"]:
        return True
    return ("veto" in _g) and any(_s in _g for _s in
                                  ("techclassic", "tlbreak", "pinwall", "albrox"))


def pinval_detect(bundle, style="DAYTRADE"):
    """PINVAL detection (engine 1): unified walk — first hit wins, tagged."""
    from analysis.setups_experimental import PINVAL_DETECTORS as _gates
    for _det in (_gates or []):
        try:
            cand = _det(bundle, style)
        except Exception:
            continue
        if cand is not None:
            try:
                if not isinstance(getattr(cand, "metadata", None), dict):
                    cand.metadata = {}
                cand.metadata["pinval_owned"] = True
                cand.metadata["pinval_gate"] = getattr(_det, "__name__", "?")
            except Exception:
                pass
            return cand
    return None


def pinval_find_pivots(highs, lows, left=2, right=2):
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


def pinval_candles_for(tf, pattern_span):
    try:
        return max(1, int(pattern_span or 0) + 40)
    except Exception:
        return 300


def pinval_zoom_window(n_bars, count, pad_right_frac=0.12):
    try:
        _n, _c = int(n_bars), max(1, int(count))
        _x_to = _n - 1 + int(_c * float(pad_right_frac))
        return (max(0, _x_to - _c), _x_to)
    except Exception:
        return (0, max(0, int(n_bars or 0) - 1))


def pinval_zones_from_pivots(pivots, direction="LONG"):
    """PINVAL draws NO zones by law — always empty (pin lines only)."""
    return []


def pinval_entry_check(*, broke: bool, closed_after_break: bool,
                       tohom_fired: bool = False, polarity_ok: bool = True,
                       direction: str = "LONG", live=None, entry=None, tp1=None,
                       foreign_gates=(), day=None):
    alarms, reasons = [], []
    for _g in (foreign_gates or ()):
        if _foreign_gate_hit(_g):
            alarms.append(pinval_alarm(
                f"foreign gate in PINVAL path: {_g} — veto REFUSED, entry proceeds"))
    if not polarity_ok:
        reasons.append("own polarity gate not aligned — waiting (allowed delay)")
        return {"decision": "WAIT", "alarms": alarms, "reasons": reasons}
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
                alarms.append(pinval_alarm("LATE confirm annotated (live beyond entry)"))
                reasons.append("late annotated")
    except Exception:
        pass
    try:
        from analysis import tiered_scan as _ts2
        _ts2.daily_count_incr("futures", day)
    except Exception:
        pass
    reasons.append("pin close + polarity confirm")
    return {"decision": "CONFIRM", "alarms": alarms, "reasons": reasons}


def pinval_trailing_check(*, entry, stop, live, direction="LONG", trail=None,
                          profit_pct=None, confirmed=True):
    alarms, reasons = [], []
    try:
        _e, _s, _l = float(entry), float(stop), float(live)
    except Exception:
        return {"state": "HEALTHY", "alarms": alarms,
                "reasons": ["unusable numbers — fail-open"]}
    _long = str(direction or "LONG").upper() != "SHORT"
    if (_l <= _s) if _long else (_l >= _s):
        alarms.append(pinval_alarm("position STOPPED (live beyond stop) — never CONFIRM"))
        reasons.append("live beyond stop")
        return {"state": "STOPPED", "alarms": alarms, "reasons": reasons}
    if trail:
        try:
            _t = float(trail)
            if (_l <= _t) if _long else (_l >= _t):
                alarms.append(pinval_alarm("trail level hit — exit"))
                reasons.append("trail hit")
                return {"state": "TRAIL_HIT", "alarms": alarms, "reasons": reasons}
        except Exception:
            pass
    try:
        if profit_pct is not None and float(profit_pct) >= 5.0 and not confirmed:
            alarms.append(pinval_alarm("5% runner WITHOUT confirm — bug, annotate"))
            reasons.append("unconfirmed runner")
    except Exception:
        pass
    reasons.append("healthy")
    return {"state": "HEALTHY", "alarms": alarms, "reasons": reasons}


def pinval_tohom_fired(candidate, lower_closed_df=None, **kw):
    try:
        from analysis.tohom import evaluate_tohom_confirmation as _ev
        _ok, _c, _reason = _ev(candidate, lower_closed_df, **kw)
        return bool(_ok)
    except Exception:
        return False
