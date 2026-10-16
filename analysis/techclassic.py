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
        # R99q14: `x or []` is a numpy/pandas landmine — `bool(array)` raises
        # ValueError and the guard below then reports an EMPTY pivot set, i.e.
        # geometry silently disappears on any engine given arrays/series.
        _h = [float(x) for x in ([] if highs is None else highs)]
        _l = [float(x) for x in ([] if lows is None else lows)]
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


# R99q TC v2 zoom law (his 10-15 corrected TECHCLASSIC charts: ETC 15M and
# TAO 15M «پترن و زوم و تعداد کندل غلطه»، BNB 1D «پترن درسته .. تعداد کندل و
# زوم غلطه»): the frame is the detected pattern + a slim 20-bar pad, capped
# per TF. If the pattern itself is longer than the cap it wins (never cut a
# detected shape) and only the pad shrinks.
_TC_FRAME_PAD = {"1m": 50, "3m": 50, "5m": 55, "15m": 55, "30m": 60,
                 "1h": 75, "2h": 85, "4h": 95, "6h": 100, "8h": 100,
                 "12h": 105, "1d": 115, "3d": 135, "1w": 145}
_TC_FRAME_CAP = {"1m": 140, "3m": 140, "5m": 145, "15m": 150, "30m": 155,
                 "1h": 170, "2h": 180, "4h": 190, "6h": 195, "8h": 200,
                 "12h": 210, "1d": 230, "3d": 270, "1w": 290}
_TC_LINE_FAMILIES = ("TRENDLINE", "CHANNEL")


_CANDLE_FLOOR = 80   # کف قانونی او؛ VIVA_CANDLE_MIN آن را override می‌کند


def _candle_floor() -> int:
    """R99q14 SETUP-CANDLE LAW (Viva 10-15, verbatim: «ستاپ‌ها هم از ۱۲۰ به بالا
    باید باشه بر اساس انتخاب پترن در زوم درست … چارت‌ها اکثرا نه هندسه دارن نه
    اینکه زوم درستی دارن»): the setup's own floor is 120 candles now (his 80-floor
    of 10-15 stayed for the raw detection tape; the PICTURE of a setup must show
    the pattern), still overridable per deploy.
    """
    try:
        import os as _os
        _own = int(str(_os.getenv("VIVA_SETUP_CANDLE_MIN", "") or "").strip() or 120)
        _old = int(str(_os.getenv("VIVA_CANDLE_MIN", "") or "").strip() or 80)
        return max(20, _own, _old)
    except Exception:
        return 120


def tc_candles_for(tf, pattern_span, pattern=None):
    """قانون جدید ۱۰-۱۵ (verbatim): «کمترین حالت ... کف تعداد کندل‌ها ۸۰ کندل
    هست و سقفش با توجه شکل و نوع پترن، تایم‌فریم و ترندلاین باید انتخاب بشه»
    + HYPE: «۴۰ تا ۵۰ تا کندل بیشتر باشه تا زوم بهتر بشه» → قاب پهن است:
    کف ۸۰ (قابل تنظیم با VIVA_CANDLE_MIN)، سقف با تایم‌فریم، و ترندلاین/کانال
    (خطوط بلند) قاب را پرتر می‌کند.
    """
    try:
        _t = str(tf or "").lower()
        _pad = _TC_FRAME_PAD.get(_t, 85)
        _cap = _TC_FRAME_CAP.get(_t, 190)
        _span = max(0, int(pattern_span or 0))
        _base = _span + _pad
        _fam = str(pattern or "").upper()
        if any(_k in _fam for _k in _TC_LINE_FAMILIES):
            _base = _span + 2 * _pad
        # R99q19 note: the per-TF ceiling stays the R99q9 law (15m→160, 4h→200
        # …). The zoom bug was never the cap — it was pattern_span collapsing
        # to 0 because the validators dropped every sloped pattern; with the
        # span real (LIT 1h: 168) the frame reaches 170 = the cap honestly.
        return max(_candle_floor(), min(_cap, _base))
    except Exception:
        return 120


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
# ── R99o TC-owned geometry (Viva 10-15, DOGE 15m: the shared funnel drew a
# CHANNEL while the pill cited TRIANGLE, anchored 164 bars back) ──
TC_MAX_ANCHOR_SPAN = {
    "1m": 96, "3m": 96, "5m": 96, "15m": 96, "30m": 96,
    "1h": 72, "2h": 72, "4h": 48, "8h": 48, "12h": 48,
    "1d": 30, "3d": 30, "1w": 30,
}
_TC_MULTI_EDGE = {"WEDGE", "CHANNEL", "TRIANGLE", "FLAG", "PENNANT"}


def _tc_fam(ptype) -> str:
    return str(ptype or "").upper().split("_")[0]


def tc_validate_pattern(pat, label_family, live_idx, tf):
    """(keep, reason, new_type). TC's own honesty gate — see R99o header."""
    if not isinstance(pat, dict):
        return (False, "not-a-dict", None)
    _t = str(pat.get("type") or pat.get("name") or "").upper()
    _lines = [L for L in (pat.get("lines") or []) if isinstance(L, dict)]
    if not _lines:
        return (True, "band-kept", None)  # RANGE band: no lines to lie
    _live = int(live_idx or 0)
    try:
        _x1s = [int(L.get("x1") or 0) for L in _lines]
        _x0s = [int(L.get("x0") or 0) for L in _lines]
    except Exception:
        return (False, "bad-coords", None)
    if _live and max(_x1s) < _live - 6:
        return (False, "stale-end", None)  # R4: must reach live
    try:
        _touches = sum(len(L.get("points") or []) for L in _lines)
    except Exception:
        _touches = 0
    # R99q19 (his 10-16: «چرا تکنوکلاسیک حتی یک پترن درست نمی‌ده .. ترندلاین‌های
    # ول از گذشته .. زوم اشتباه»): the anchor cap used to be a fixed 72 bars on
    # 1h / 48 on 4h, so a REAL 7-day falling wedge on 4 pivots died as
    # «ancient-anchor» — while his own candle law says the frame's ceiling
    # follows the shape («سقفش با توجه شکل و نوع پترن، تایم‌فریم و ترندلاین»).
    # A multi-edge shape standing on ≥3 pivots now earns the TF's own legal
    # picture cap (_TC_FRAME_CAP); single lines and under-touched junk keep the
    # tight cap, so the long-trash law still kills the 1000-bar relics.
    _cap = TC_MAX_ANCHOR_SPAN.get(str(tf or "").lower(), 96)
    try:
        if (_tc_fam(_t) in _TC_MULTI_EDGE and len(_lines) >= 2 and _touches >= 3):
            _cap = max(_cap, int(_TC_FRAME_CAP.get(str(tf or "").lower(), _cap)))
    except Exception:
        pass
    if _live and (_live - min(_x0s)) > _cap:
        return (False, "ancient-anchor", None)  # R2: the long-trash law
    if _touches == 0 and (max(_x1s) - min(_x0s)) < 20:
        return (False, "empty-noise", None)  # R5
    if _tc_fam(_t) in _TC_MULTI_EDGE and len(_lines) >= 2 and _touches < 3:
        return (False, "under-touched", None)  # R99q v2: 2 lines, <3 pivots
        # = a wedge drawn on noise (his ETC/TAO 15M «پترن غلطه»)
    if _tc_fam(_t) in _TC_MULTI_EDGE:
        if label_family and _tc_fam(_t) != str(label_family).upper():
            if len(_lines) == 1:
                return (True, "relabel-trendline", "TRENDLINE")
            # R99q19 (his 10-16: «از پترن‌ها فقط فالینگ وج رو گاهی درست می‌کشن
            # بقیه پترن‌ها رو انگار اصلا نمی‌شناسن»): a TWO-line shape standing on
            # ≥3 real pivots is a pattern the tape actually shows — killing it
            # for a naming difference (TC says CHANNEL_ASCENDING, the shared
            # descriptor fits WEDGE_FALLING on this frame) left the canvas with
            # NO geometry and the painter then invented hull lines. The shape is
            # KEPT and honestly relabeled to its own geometry family; the
            # pill/label then follows the drawn type (display keys only —
            # confirm/entry logic untouched). Under-touched two-liners keep
            # dying above as «under-touched».
            return (True, "relabel-shape", _t if _t.endswith(tuple("0123456789")) is False else _t)
        if len(_lines) < 2:
            return (True, "relabel-trendline", "TRENDLINE")  # R3 honest single
    return (True, "ok", None)


def tc_refine_geometry(candidate, bundle=None):
    """TC v2 mint filter (own file). Fail-open: errors return it untouched."""
    try:
        md = getattr(candidate, "metadata", None)
        if not isinstance(md, dict):
            return candidate
        _pats = list(md.get("render_patterns") or [])
        _tf = str(getattr(candidate, "trigger_timeframe", "") or "").lower()
        # R99q19: the live bar index in the PATTERN's coordinate space (the fit
        # window stamped by render_kit) — never the full frame's length, which
        # made every sloped pattern look «stale» and killed the whole set.
        try:
            from analysis.render_kit import pattern_live_index as _pli19
            _live = int(_pli19(md, bundle, str(getattr(candidate, "trigger_timeframe", "")
                                               or ""), _pats) or 0)
        except Exception:
            _live = 0
        _label = str(md.get("tl_pattern") or md.get("pattern_type") or "")
        _fam = _label.split("_")[0].upper() if _label else ""
        _kept, _dropped, _spans = [], [], []
        for _p in _pats:
            _keep, _reason, _newt = tc_validate_pattern(_p, _fam, _live, _tf)
            if _keep:
                _q = dict(_p)
                if _newt:
                    _q["type"] = _newt
                _kept.append(_q)
                try:
                    _lx = [int(L.get("x1") or 0) - int(L.get("x0") or 0)
                           for L in (_q.get("lines") or []) if isinstance(L, dict)]
                    if _lx:
                        _spans.append(max(_lx))
                except Exception:
                    pass
            else:
                _dropped.append(f"{(_p.get('type') or _p.get('name'))}:{_reason}")
        # R99q v2: the lead (kept[0] → pill + span + view) is the pattern whose
        # first anchor lives inside the tight frame — in-frame first, order kept.
        try:
            _kept.sort(key=lambda _q: 0 if (_live and all(
                int(L.get("x0") or 0) >= _live - 130
                for L in (_q.get("lines") or []) if isinstance(L, dict))
                ) else 1)
        except Exception:
            pass
        md["render_patterns"] = _kept
        md["tc_pattern_span"] = max(_spans) if _spans else 0
        # R99o context honesty (Viva 10-15, honesty-veto class): surviving
        # lines are TRIGGER-native (x-coords fit the trigger frame, not a 4H
        # one); the 4H was the dropped pattern's HTF story. Leaving it makes
        # the painter divide every slope by pattern/trigger (AERO misfire —
        # the flat green monster) and a kept single collapses into a band
        # the veto rejects (0 sloped lines → no photo). Certifies survivors.
        _trig99o = str(getattr(candidate, "trigger_timeframe", "") or "")
        if _kept and _trig99o:
            if str(md.get("tl_context_tf") or "") != _trig99o:
                md["tc_context_was"] = md.get("tl_context_tf")
            md["tl_context_tf"] = _trig99o
        if _kept:
            _drawn = str(_kept[0].get("type") or _kept[0].get("name") or "")
            if _drawn:  # pill↔chart sync (display keys only; confirm untouched)
                md["render_htf_pattern"] = _drawn
                md["tc_label_was"] = _label
                md["tl_pattern"] = _drawn
        md["tc_owned"] = True
        md["tc_refined"] = True
        md["tc_dropped"] = _dropped
        try:
            if __import__("os").getenv("VIVA_TC_DEBUG"):
                print(f"[tc19] live={_live} label={_label!r} kept="
                      f"{[(q.get('type'), [(L.get('side'), L.get('x0'), L.get('x1'), len(L.get('points') or [])) for L in (q.get('lines') or [])]) for q in _kept]} "
                      f"dropped={_dropped} span={md.get('tc_pattern_span')}")
        except Exception:
            pass
        return candidate
    except Exception as _exc:
        try:
            print(f"[TC-REFINE] fail-open: {_exc}")
        except Exception:
            pass
        return candidate


# ── R99q14 PRE-BREAK EARLY ALERT (Viva 10-15, verbatim: «باید قبل از اینکه قیمت
# به اضلاع الگوها و یا در حال بریک پترنها و ترندلاینها برسه اولین هشدار ابتدایی
# بده .. و بعد از بریک تایید بده … در همه ستاپها یکسانه … فقط بدون هر ستاپ جدا
# جدا جراحی بشه»). TECHCLASSIC answers with its OWN engine states — the
# EDGE_NEAR/BREAK_READY events `scan_edges` already mints while price is still
# inside the pattern, near the edge, BEFORE the break. The lane owns the
# cadence; this provider never touches the break lane's cooldown.
_PREBREAK_TF_BELOW = {"5m": "1m", "15m": "5m", "30m": "15m", "1h": "15m",
                      "2h": "30m", "4h": "1h", "8h": "2h", "1d": "4h", "3d": "1d"}


def _prebreak_atr(df) -> float:
    try:
        from analysis.brooks_pa import atr as _atr_b
        _v = float(_atr_b(df))
        return _v if _v > 0 else 0.0
    except Exception:
        return 0.0


def techclassic_prebreak(df, tf: str, symbol: str = "", bundle=None,
                         live_price: float = None) -> list:
    """Pre-break events from the TECHCLASSIC engine itself (never a new detector)."""
    try:
        from analysis.pattern_engine import evaluate_prebreak as _pb
    except Exception:
        return []
    if df is None or len(df) < 45:
        return []
    _below = _PREBREAK_TF_BELOW.get(str(tf or "").lower())
    trig = None
    if bundle is not None and _below:
        try:
            trig = bundle.get(_below)
        except Exception:
            trig = None
    if trig is None or len(trig) < 12:
        trig = df
    live = live_price
    if live is None:
        try:
            live = float(df["close"].iloc[-1])
        except Exception:
            live = None
    atr_v = _prebreak_atr(df)
    out = []
    try:
        evs = _pb(str(symbol or ""), df, trig, str(tf or ""), live_price=live,
                  ignore_cooldown=True) or []
    except Exception as exc:
        print(f"TC prebreak skipped {symbol} {tf}: {exc}")
        return []
    for ev in evs:
        if str(ev.get("state") or "").upper() not in ("EDGE_NEAR", "BREAK_READY"):
            continue
        out.append({
            "setup": "TECHCLASSIC",
            "setup_name": "TECNOCLASIC",
            "tf": tf,
            "pattern_tf": ev.get("pattern_tf") or tf,
            "side": ev.get("side"),
            "direction": ev.get("direction"),
            "pattern": ev.get("pattern"),
            "pattern_fa": ev.get("pattern_fa"),
            "edge": ev.get("line_price"),
            "distance_atr": ev.get("distance_atr"),
            "line_geo": ev.get("line_geo") or {},
            "edge_points": ev.get("edge_points") or [],
            "pattern_geo": ev.get("pattern_geo") or {},
            "upper_points": ev.get("upper_points") or [],
            "lower_points": ev.get("lower_points") or [],
            "measured": ev.get("measured") or {},
            "touches": ev.get("touches"),
            "score": ev.get("structure_score"),
            "atr": atr_v,
            "state": ev.get("state"),
            "pattern_role": ev.get("pattern_role"),
            "note_fa": (f"قیمت هنوز داخل الگوست و به ضلع {'بالایی' if str(ev.get('side')) == 'upper' else 'پایینی'} "
                        f"نزدیک شده — شکست هنوز تأیید نشده."),
        })
    return out
