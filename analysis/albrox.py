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
# ── R99o ALBROX-owned selection (Viva 10-15: keep BEST+NEAREST 2, XLM drew 4
# incl. identical twins) ──
_ALBROX_TYPE_ORDER = {"WEDGE": 0, "CHANNEL": 0, "TRIANGLE": 0, "FLAG": 1,
                      "PENNANT": 1, "TRENDLINE": 2, "DOUBLE": 3, "RANGE": 4}


def albrox_select_patterns(patterns, live_idx):
    """Dedupe → drop stale/noise → keep top 2 (touches, recency, type)."""
    _seen, _uniq = set(), []
    for _p in (patterns or []):
        if not isinstance(_p, dict):
            continue
        try:
            _sig = (str(_p.get("type") or _p.get("name") or "").upper(),
                    tuple(sorted(
                        (float(L.get("x0") or 0), float(L.get("x1") or 0),
                         round(float(L.get("slope") or 0), 10))
                        for L in (_p.get("lines") or []) if isinstance(L, dict))))
        except Exception:
            _sig = (str(_p.get("type") or _p.get("name") or ""), ())
        if _sig in _seen:
            continue
        _seen.add(_sig)
        _uniq.append(_p)
    _live = int(live_idx or 0)
    _filt = []
    for _p in _uniq:
        _lines = [L for L in (_p.get("lines") or []) if isinstance(L, dict)]
        if not _lines:
            _filt.append(_p)  # band
            continue
        try:
            _x1 = max(int(L.get("x1") or 0) for L in _lines)
            _x0 = min(int(L.get("x0") or 0) for L in _lines)
            _touches = sum(len(L.get("points") or []) for L in _lines)
        except Exception:
            continue
        if _live and _x1 < _live - 48:
            continue  # stale
        if _touches == 0 and (_x1 - _x0) < 20:
            continue  # empty noise
        _filt.append(_p)

    def _key(_p):
        _lines = [L for L in (_p.get("lines") or []) if isinstance(L, dict)]
        try:
            _t = sum(len(L.get("points") or []) for L in _lines) if _lines else 1
            _x = max(int(L.get("x1") or 0) for L in _lines) if _lines else _live
        except Exception:
            _t, _x = 0, 0
        _fam = str(_p.get("type") or _p.get("name") or "").upper().split("_")[0]
        return (-_t, -_x, _ALBROX_TYPE_ORDER.get(_fam, 5))

    _filt.sort(key=_key)
    return _filt[:2]


def albrox_refine_geometry(candidate, bundle=None):
    """ALBROX v2 mint filter (own file). Fail-open: errors return untouched."""
    try:
        md = getattr(candidate, "metadata", None)
        if not isinstance(md, dict):
            return candidate
        _pats = list(md.get("render_patterns") or [])
        _live = 0
        try:
            if bundle is not None:
                _fr = bundle.get(getattr(candidate, "trigger_timeframe", ""))
                if _fr is not None and len(_fr):
                    _live = len(_fr) - 1
        except Exception:
            _live = 0
        if not _live:
            try:
                _live = max(int(L.get("x1") or 0)
                            for _p in _pats if isinstance(_p, dict)
                            for L in (_p.get("lines") or [])
                            if isinstance(L, dict))
            except Exception:
                _live = 0
        _kept = albrox_select_patterns(_pats, _live)
        _kept_ids = set(map(id, _kept))
        md["render_patterns"] = _kept
        try:
            _spans = [max(int(L.get("x1") or 0) - int(L.get("x0") or 0), 0)
                      for _p in _kept for L in (_p.get("lines") or [])
                      if isinstance(L, dict)]
            md["albrox_pattern_span"] = max(_spans) if _spans else 0
        except Exception:
            md["albrox_pattern_span"] = 0
        # R99o context honesty (same law as TC): survivors are trigger-native.
        _trig99o = str(getattr(candidate, "trigger_timeframe", "") or "")
        if _kept and _trig99o:
            if str(md.get("tl_context_tf") or "") != _trig99o:
                md["albrox_context_was"] = md.get("tl_context_tf")
            md["tl_context_tf"] = _trig99o
        if _kept:
            _drawn = str(_kept[0].get("type") or _kept[0].get("name") or "")
            if _drawn:
                md["render_htf_pattern"] = _drawn
        md["albrox_owned"] = True
        md["albrox_refined"] = True
        md["albrox_dropped"] = [
            str(_p.get("type") or _p.get("name")) for _p in _pats
            if id(_p) not in _kept_ids]
        return candidate
    except Exception as _exc:
        try:
            print(f"[ALBROX-REFINE] fail-open: {_exc}")
        except Exception:
            pass
        return candidate
