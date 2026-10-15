"""ALBROX home — فاز نظم و انضباط (R99i).

The UNION setup (r60): Brooks-style structural entries (breakout legs,
second entries, micro-structure). Structural lane: instant confirm at
break — first close after the break. Own zones may draw (and judge for
ALBROX only); foreign gates alarm + veto refused. Late confirm =
annotation, entry proceeds.
"""
_ALBROX_FRAME_PAD = {"15m": 60, "30m": 65, "1h": 80, "2h": 90, "4h": 100,
                     "6h": 105, "8h": 105, "12h": 110, "1d": 120, "3d": 140,
                     "1w": 150}
_ALBROX_FRAME_CAP = {"15m": 160, "30m": 165, "1h": 180, "2h": 190, "4h": 200,
                     "6h": 205, "8h": 205, "12h": 215, "1d": 240, "3d": 280,
                     "1w": 300}
_ALBROX_LINE_FAMILIES = ("TRENDLINE", "CHANNEL")


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


def albrox_candles_for(tf, pattern_span, pattern=None):
    """قانون جدید ۱۰-۱۵ (verbatim): «کمترین حالت ... کف تعداد کندل‌ها ۸۰ کندل
    هست و سقفش با توجه شکل و نوع پترن، تایم‌فریم و ترندلاین باید انتخاب بشه»
    + HYPE: «۴۰ تا ۵۰ تا کندل بیشتر باشه تا زوم بهتر بشه» → قاب پهن است:
    کف ۸۰ (قابل تنظیم با VIVA_CANDLE_MIN)، سقف با تایم‌فریم، و ترندلاین/کانال
    (خطوط بلند) قاب را پرتر می‌کند.
    """
    try:
        _t = str(tf or "").lower()
        _pad = _ALBROX_FRAME_PAD.get(_t, 90)
        _cap = _ALBROX_FRAME_CAP.get(_t, 200)
        _span = max(0, int(pattern_span or 0))
        _base = _span + _pad
        _fam = str(pattern or "").upper()
        if any(_k in _fam for _k in _ALBROX_LINE_FAMILIES):
            _base = _span + 2 * _pad        # ترندلاین/کانال ⇒ قاب پرتر
        return max(_candle_floor(), min(_cap, _base))
    except Exception:
        return 120

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
        # R99q14: NEVER `x or []` here — the pre-break lane hands numpy
        # arrays in and `bool(array)` raises ValueError ("truth value of an
        # array ... is ambiguous"), which the guard below swallowed as an
        # EMPTY pivot set → the ALBROX pre-break lane was silent on every
        # live frame (0 events / 0 exceptions) while TC/PINVAL/TLBREAK spoke.
        _h = [float(x) for x in ([] if highs is None else highs)]
        _l = [float(x) for x in ([] if lows is None else lows)]
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


_ALBROX_MULTI_EDGE = {"WEDGE", "CHANNEL", "TRIANGLE", "FLAG", "PENNANT"}


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
        # R99q v2 (his 10-15 ALBROX 15m verdicts «پترن غلطه»): a two-line
        # "wedge/channel" standing on <3 pivots is noise drawn on the tape —
        # ALBROX's own honesty floor (TC keeps its own copy).
        if (len(_lines) >= 2 and _touches < 3
                and str(_p.get("type") or _p.get("name") or "").upper().split("_")[0]
                in _ALBROX_MULTI_EDGE):
            continue
        _filt.append(_p)

    def _key(_p):
        _lines = [L for L in (_p.get("lines") or []) if isinstance(L, dict)]
        try:
            _t = sum(len(L.get("points") or []) for L in _lines) if _lines else 1
            _x = max(int(L.get("x1") or 0) for L in _lines) if _lines else _live
        except Exception:
            _t, _x = 0, 0
        _fam = str(_p.get("type") or _p.get("name") or "").upper().split("_")[0]
        # R99q پنجرهٔ تنگ خودش: الگویی که پیوت اولش ۱۲۰ کندل عقب‌تر است، قاب را
        # به «جادهٔ بی‌سر» تبدیل می‌کند (حکم ۱۰-۱۵: تعداد کندل غلط). داخلِ قاب
        # رتبهٔ بهتری می‌گیرد، ولی حذف نمی‌شود (خطِ بلند ماژور معتبر است).
        _in99 = 0 if (_x0 >= max(0, _live - 100)) else 1
        return (_in99,
                albrox_pattern_distance_atr(_p, _live, live_price, atr),
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


def albrox_zoom_window(n_bars, count, pad_right_frac=0.12):
    """ALBROX zoom (own engine, R99p): (x_from, x_to), pattern-anchored right."""
    try:
        _n, _c = int(n_bars), max(1, int(count))
        _x_to = _n - 1 + int(_c * float(pad_right_frac))
        return (max(0, _x_to - _c), _x_to)
    except Exception:
        return (0, max(0, int(n_bars or 0) - 1))


# ── R99q14 PRE-BREAK EARLY ALERT — ALBROX's OWN zone lane (Viva 10-15: the first
# alert must arrive while price is still inside / near the setup's own edges).
# Lane B judge: the freshest un-mitigated pivot supply/demand zone. The edge that
# matters is the zone's PROXIMAL line (demand top / supply bottom) — the level
# whose break is the trade. No foreign detector speaks for ALBROX.
def _prebreak_atr(df) -> float:
    try:
        from analysis.brooks_pa import atr as _atr_b
        _v = float(_atr_b(df))
        return _v if _v > 0 else 0.0
    except Exception:
        return 0.0


def albrox_prebreak(df, tf: str, symbol: str = "", bundle=None,
                    live_price: float = None) -> list:
    """Pre-break events from ALBROX's own zone inventory."""
    if df is None or len(df) < 45:
        return []
    atr_v = _prebreak_atr(df)
    if atr_v <= 0:
        return []
    # R99q14: ALBROX's pre-break view reads ALBROX'S OWN inventory — the r60
    # zone builders in `setups_experimental` (un-mitigated FVGs, pivot SD/flip
    # levels, freshest order blocks) — exactly the set the zone lane trades.
    # (The provider used to synthesise a "zone" from the last two pivot highs /
    # last two pivot lows, which on a live frame is a 4-ATR-wide smear, not a
    # zone — and it was silent anyway, see albrox_find_pivots.) The own-pivot
    # SD zones stay as the fallback when the inventory comes back empty.
    zones = []
    try:
        from analysis.setups_experimental import _albrox_zones as _inventory
        _atr_s = float((df["high"] - df["low"]).tail(14).mean() or 0.0) or atr_v
        zones = list(_inventory(df, bundle, tf, _atr_s) or [])
    except Exception:
        zones = []
    if not zones:
        try:
            highs = df["high"].astype(float).to_numpy()
            lows = df["low"].astype(float).to_numpy()
            zones = albrox_zones_from_pivots(albrox_find_pivots(highs, lows))
        except Exception:
            zones = []
    if not zones:
        return []
    live = live_price
    if live is None:
        try:
            live = float(df["close"].iloc[-1])
        except Exception:
            return []
    band = 0.85
    try:
        from analysis.prebreak_lane import band_atr as _band
        band = float(_band())
    except Exception:
        pass
    try:
        from analysis.prebreak_lane import inside_band_atr as _inb
        inside = float(_inb())
    except Exception:
        inside = 2.4
    closes = df["close"].astype(float).to_numpy()
    out = []
    for z in zones:
        try:
            _zlo, _zhi = sorted((float(z["bottom"]), float(z["top"])))
            # r61.1 SANE-ZONE LAW («این چه ناحیه ای است که دنبال سیگناله؟؟»):
            # a zone taller than 3 ATR is not a zone — never speak, never draw.
            if (_zhi - _zlo) > 3.0 * atr_v or _zhi <= _zlo:
                continue
            _kind = str(z.get("kind") or "").upper()
            _side = str(z.get("side") or "").lower()
            if _side not in ("demand", "supply"):
                if _kind.endswith("DEMAND") or _kind == "DEMAND":
                    _side = "demand"
                elif _kind.endswith("SUPPLY") or _kind == "SUPPLY":
                    _side = "supply"
                else:
                    # FVG / FLIP / SD carry no side: demand below the tape,
                    # supply above it (the only reading the zone lane trades)
                    _side = "demand" if _zhi <= live else "supply"
            if _side == "demand":
                edge, edge_side, direction = _zhi, "upper", "LONG"
                # price must still be at/below the zone's proximal line
                if live > edge + band * atr_v:
                    continue
                if (closes[-1] > edge + 0.10 * atr_v and closes[-2] > edge):
                    continue                       # already broken → confirm lane
            else:
                edge, edge_side, direction = _zlo, "lower", "SHORT"
                if live < edge - band * atr_v:
                    continue
                if (closes[-1] < edge - 0.10 * atr_v and closes[-2] < edge):
                    continue
        except Exception:
            continue
        dist = abs(live - edge) / atr_v
        if dist > inside:
            continue
        out.append({
            "setup": "ALBROX",
            "setup_name": "ALBROX",
            "tf": tf,
            "pattern_tf": tf,
            "side": edge_side,
            "direction": direction,
            "pattern": str(z.get("kind") or "ZONE_SD"),
            "pattern_fa": ("ناحیه عرضه/تقاضا" if str(z.get("kind") or "").upper().startswith(("SD", "FLIP"))
                           else ("ناحیه تقاضا" if direction == "LONG" else "ناحیه عرضه")),
            "edge": edge,
            "distance_atr": round(dist, 3),
            "line_geo": {"price": edge, "a": edge, "b": 0.0, "slope": 0.0,
                         "ts": str(df["timestamp"].iloc[-1]) if "timestamp" in df.columns else ""},
            "pattern_geo": {},
            "zones": [{"kind": str(z.get("kind") or "SD"), "bottom": _zlo, "top": _zhi,
                       "bias": "DEMAND" if _side == "demand" else "SUPPLY"}],
            "measured": {"from": edge, "to": edge, "pct": 0.0, "height": 0.0},
            "touches": 2,
            "score": 6,
            "atr": atr_v,
            "state": "EDGE_NEAR",
            "note_fa": ("قیمت درون/نزدیکِ ناحیهٔ خودِ آبروکس است و لبهٔ نزدیک ناحیه "
                        f"({edge:g}) هنوز شکسته نشده."),
        })
    return out
