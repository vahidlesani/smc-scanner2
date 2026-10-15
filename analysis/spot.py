"""SPOT home — فاز نظم و انضباط (R99h).

Spot owns ONE file holding ALL its engines (VIVA_USER_LAWS.md §10).
LONG only, bullish shapes only. NO waiting state: the breaking CLOSED
candle confirms immediately. ROUND-16 decoupling: no futures gate may
ever judge a spot chain (and vice versa).

Engines (§6 adapted): detection, zoom, pivots, candle_count, zones_render,
confirm_entry, trailing, tohom, entry_rules (SEPARATE).
"""

# R99n: this setup OWNS its concurrent-chain allowance (Viva 10-15:
# no global first-come pool — a full neighbour book never starves us).
OWN_MAX_CONCURRENT_CHAINS = 30


SPOT_ENGINES = {
    "detection": {"entry": "analysis.spot.spot_detect", "status": "wired",
                  "notes": "own wrapper over spot_signals_for; tags spot_owned"},
    "zoom": {"entry": "analysis.spot.spot_zoom_window", "status": "wired",
             "notes": "window from the count; pattern-anchored right"},
    "pivots": {"entry": "analysis.spot.spot_find_pivots", "status": "wired",
               "notes": "HTF fractals (3/3) on wick highs/lows; shadows count"},
    "candle_count": {"entry": "analysis.spot.spot_candles_for", "status": "wired",
                     "notes": "FROM the detected pattern span; no min/max"},
    "zones_render": {"entry": "analysis.spot.spot_zones_from_pivots", "status": "wired",
                     "notes": "refined S/D boxes; DRAWN only, never gates"},
    "confirm_entry": {"entry": "analysis.spot.spot_entry_check", "status": "wired",
                      "notes": "breaking closed candle confirms instantly"},
    "trailing": {"entry": "analysis.spot.spot_trailing_check", "status": "wired",
                 "notes": "LONG-only; live<=stop => STOPPED, never publish"},
    "tohom": {"entry": "analysis.spot.spot_tohom_fired", "status": "wired",
              "notes": "early-confirm hook on the shared TOHOM evaluator"},
    "entry_rules": {"entry": "analysis.spot.spot_entry_check", "status": "wired",
                    "separate": True,
                    "notes": "SEPARATE; futures gates alarm + veto refused"},
}

SPOT_ENTRY_RULES = {
    "instant_confirm_on_breaking_close": True,
    "tohom_early_entry": True,
    "forbidden_gates": ["techclassic_veto", "tlbreak_veto", "pinval_veto",
                        "pinwall_veto", "albrox_veto", "cross_setup_veto"],
    "zones_may_draw": True,
    "zones_may_gate": False,
    "long_only": True,
}


def get_spot_engine(name):
    return SPOT_ENGINES.get(str(name or "").lower())


def spot_health_check(candidate=None):
    _ = candidate
    return []


def spot_alarm(message):
    return f"[SPOT-ALARM] {message}"


def _foreign_gate_hit(gate_name: str) -> bool:
    _g = str(gate_name or "").lower()
    if not _g:
        return False
    if _g in SPOT_ENTRY_RULES["forbidden_gates"]:
        return True
    return ("veto" in _g) and any(_s in _g for _s in
                                  ("techclassic", "tlbreak", "pinval", "pinwall", "albrox"))


def spot_detect(symbol, bundle):
    """SPOT detection (engine 1): own wrapper; tags spot_owned chains."""
    from analysis.spot_engine import spot_signals_for as _det
    cands = _det(symbol, bundle) or []
    for _c in cands:
        try:
            if not isinstance(getattr(_c, "metadata", None), dict):
                _c.metadata = {}
            _c.metadata["spot_owned"] = True
        except Exception:
            pass
    return cands


def spot_find_pivots(highs, lows, left=3, right=3):
    """SPOT pivots (engine 3): HTF fractals on WICK highs/lows."""
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


def spot_candles_for(tf, pattern_span):
    """SPOT candle count (engine 4): FROM the pattern (no min/max)."""
    try:
        return max(1, int(pattern_span or 0) + 40)
    except Exception:
        return 300


def spot_zoom_window(n_bars, count, pad_right_frac=0.12):
    """SPOT zoom (engine 2): pattern-anchored window from the count."""
    try:
        _n, _c = int(n_bars), max(1, int(count))
        _x_to = _n - 1 + int(_c * float(pad_right_frac))
        return (max(0, _x_to - _c), _x_to)
    except Exception:
        return (0, max(0, int(n_bars or 0) - 1))


def spot_zones_from_pivots(pivots, direction="LONG"):
    """SPOT zones (engine 5): refined S/D boxes; DRAWN only, never gates."""
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


def spot_entry_check(*, broke_closed: bool, foreign_gates=(), day=None):
    """SPOT entry-law checker (engines 6+9). Pure + tested.

    No waiting state: the breaking CLOSED candle confirms instantly.
    Futures gates NEVER veto: alarm + veto refused, entry proceeds.
    """
    alarms, reasons = [], []
    for _g in (foreign_gates or ()):
        if _foreign_gate_hit(_g):
            alarms.append(spot_alarm(
                f"futures gate in SPOT path: {_g} — veto REFUSED, entry proceeds"))
    if not broke_closed:
        reasons.append("no breaking closed candle yet")
        return {"decision": "WAIT", "alarms": alarms, "reasons": reasons}
    # R99q (Viva 10-15, verbatim «گفتم گیت خشک‌کننده سیگنال‌های ستاپ‌ها رو
    # بردارررر»): the daily TOTAL budget is RETIRED — a shared cap that
    # dried EVERY setup at once (today 21/25 by 04:40 Tehran → silence).
    # Capacity lives in the licence seats (3 concurrent per symbol/setup/
    # trigger-TF) and the setup's own concurrent slots. Never deferred.
    try:
        from analysis import tiered_scan as _ts2
        _ts2.daily_count_incr("spot", day)
    except Exception:
        pass
    reasons.append("instant confirm on breaking closed candle")
    return {"decision": "CONFIRM", "alarms": alarms, "reasons": reasons}


def spot_trailing_check(*, entry, stop, live, trail=None):
    """SPOT trailing (engine 7): LONG-only; live<=stop => STOPPED."""
    alarms, reasons = [], []
    try:
        _e, _s, _l = float(entry), float(stop), float(live)
    except Exception:
        return {"state": "HEALTHY", "alarms": alarms,
                "reasons": ["unusable numbers — fail-open"]}
    if _l <= _s:
        alarms.append(spot_alarm(
            f"position STOPPED (live {_l:,.4g} beyond stop {_s:,.4g}) — "
            "never publish"))
        reasons.append("live beyond stop")
        return {"state": "STOPPED", "alarms": alarms, "reasons": reasons}
    if trail:
        try:
            if _l <= float(trail):
                alarms.append(spot_alarm("trail level hit — exit"))
                reasons.append("trail hit")
                return {"state": "TRAIL_HIT", "alarms": alarms,
                        "reasons": reasons}
        except Exception:
            pass
    _dist = abs(_l - _s) / _s * 100 if _s else 0.0
    reasons.append(f"healthy ({_dist:.2f}% from stop)")
    return {"state": "HEALTHY", "alarms": alarms, "reasons": reasons}


def spot_tohom_fired(candidate, lower_closed_df=None, **kw):
    """SPOT TOHOM hook (engine 8): early-confirm on the shared evaluator."""
    try:
        from analysis.tohom import evaluate_tohom_confirmation as _ev
        _ok, _c, _reason = _ev(candidate, lower_closed_df, **kw)
        return bool(_ok)
    except Exception:
        return False
