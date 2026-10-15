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
    # R99q (Viva 10-15, verbatim «گفتم گیت خشک‌کننده سیگنال‌های ستاپ‌ها رو
    # بردارررر»): the daily TOTAL budget is RETIRED — a shared cap that
    # dried EVERY setup at once (today 21/25 by 04:40 Tehran → silence).
    # Capacity lives in the licence seats (3 concurrent per symbol/setup/
    # trigger-TF) and the setup's own concurrent slots. Never deferred.
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


def albrox_select_patterns(patterns, live_idx, live_price=None, atr=None):
    """R99p v2 (Viva 10-15, LTC 4H: a 6-week far line led while the clear
    near wedge lost): dedupe → drop stale/noise/far-single → rank NEAREST
    first (his «nearest (most important)»), touches second → top 2.
    Far SHAPES survive (far-major context, painted faint); far SINGLE
    lines die (the nowhere-line class). live/atr unknown → touches rank."""
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
        if len(_lines) == 1 and not _p.get("pivots_ts"):
            _d99p = albrox_pattern_distance_atr(_p, _live, live_price, atr)
            if _d99p != float("inf") and _d99p > 2.5:
                continue  # far nowhere-single (r59's own 2.5 ATR)
        _filt.append(_p)

    def _key(_p):
        _lines = [L for L in (_p.get("lines") or []) if isinstance(L, dict)]
        try:
            _t = sum(len(L.get("points") or []) for L in _lines) if _lines else 1
            _x = max(int(L.get("x1") or 0) for L in _lines) if _lines else _live
        except Exception:
            _t, _x = 0, 0
        _fam = str(_p.get("type") or _p.get("name") or "").upper().split("_")[0]
        return (albrox_pattern_distance_atr(_p, _live, live_price, atr),
                -_t, -_x, _ALBROX_TYPE_ORDER.get(_fam, 5))

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
        _live_px99p, _atr99p = None, None
        try:
            if bundle is not None:
                _fr99p = bundle.get(getattr(candidate, "trigger_timeframe", ""))
                if _fr99p is not None and len(_fr99p) >= 15:
                    _live_px99p = float(_fr99p["close"].iloc[-1])
                    _atr99p = float((_fr99p["high"] - _fr99p["low"]).tail(14).mean())
        except Exception:
            _live_px99p, _atr99p = None, None
        _kept = albrox_select_patterns(_pats, _live, _live_px99p, _atr99p)
        _kept_ids = set(map(id, _kept))
        md["render_patterns"] = _kept
        try:
            # R99p: the span follows the LEAD (kept[0], nearest) — a far-major
            # context line must not hold the view at 6 weeks.
            _spans = [max(int(L.get("x1") or 0) - int(L.get("x0") or 0), 0)
                      for _p in _kept[:1] for L in (_p.get("lines") or [])
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
def _albrox_line_y_at(ln, x):
    try:
        return float(ln.get("intercept") or 0) + float(ln.get("slope") or 0) * float(x)
    except Exception:
        return None


def albrox_pattern_distance_atr(pat, live_idx, live_price, atr):
    """Nearest distance (ATR) of the pattern to the live price. +inf unknown."""
    try:
        if not atr or float(atr) <= 0 or live_price is None:
            return float("inf")
        _lp, _at = float(live_price), float(atr)
        _lines = [L for L in (pat.get("lines") or []) if isinstance(L, dict)]
        if _lines:
            _ds = []
            for L in _lines:
                _y = _albrox_line_y_at(L, live_idx)
                if _y is not None:
                    _ds.append(abs(_y - _lp) / _at)
            return min(_ds) if _ds else float("inf")
        for _k in ("pivots_ts", "pivots"):
            _pvs = pat.get(_k) or []
            if _pvs:
                try:
                    return min(abs(float(p.get("price") or 0) - _lp) / _at
                               for p in _pvs if isinstance(p, dict))
                except Exception:
                    pass
        _hi = pat.get("hi", pat.get("top", pat.get("high")))
        _lo = pat.get("lo", pat.get("bottom", pat.get("low")))
        if _hi is not None and _lo is not None:
            return abs((float(_hi) + float(_lo)) / 2 - _lp) / _at
        return float("inf")
    except Exception:
        return float("inf")


def albrox_candles_for(tf, pattern_span):
    """ALBROX candle count (own engine, R99p): detected span + 40 context bars
    (same shape as TC's — duplicated per his per-setup law, not imported)."""
    try:
        return max(1, int(pattern_span or 0) + 40)
    except Exception:
        return 300


def albrox_zoom_window(n_bars, count, pad_right_frac=0.12):
    """ALBROX zoom (own engine, R99p): (x_from, x_to), pattern-anchored right."""
    try:
        _n, _c = int(n_bars), max(1, int(count))
        _x_to = _n - 1 + int(_c * float(pad_right_frac))
        return (max(0, _x_to - _c), _x_to)
    except Exception:
        return (0, max(0, int(n_bars or 0) - 1))
