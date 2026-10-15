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
        _w = list(range(i - int(left), i + int(right) + 1))
        _w.remove(i)
        if all(_h[i] >= _h[j] for j in _w) and any(_h[i] > _h[j] for j in _w):
            _hi.append((i, _h[i]))
        if all(_l[i] <= _l[j] for j in _w) and any(_l[i] < _l[j] for j in _w):
            _lo.append((i, _l[i]))
    return {"highs": _hi, "lows": _lo}


# R99q v2 frame law (his 10-15 per-setup zoom law) — PINVAL's OWN numbers:
# a pin level is read against its recent taps, so the intraday window keeps
# one bar more than the pattern engines' and the higher frames cap tighter
# than TC's (pin charts are levels, not long shapes).
_PINVAL_FRAME_CAP = {"1h": 75, "2h": 70, "4h": 70, "6h": 75, "8h": 80,
                     "12h": 85, "1d": 110, "3d": 130, "1w": 140}


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


_PINVAL_FRAME_PAD = {"15m": 65, "30m": 70, "1h": 80, "2h": 90, "4h": 100, "6h": 105, "8h": 105, "12h": 110, "1d": 120, "3d": 140, "1w": 150}
_PINVAL_FRAME_CAP = {"15m": 160, "30m": 165, "1h": 175, "2h": 185, "4h": 195, "6h": 200, "8h": 205, "12h": 215, "1d": 235, "3d": 275, "1w": 295}
_PINVAL_LINE_FAMILIES = ("TRENDLINE", "CHANNEL")


def pinval_candles_for(tf, pattern_span, pattern=None):
    """قانون جدید ۱۰-۱۵ (verbatim): «کف تعداد کندل‌ها ۸۰ کندل و سقفش با توجه شکل و نوع پترن، تایم‌فریم و ترندلاین» + «۴۰ تا ۵۰ کندل بیشتر تا زوم بهتر بشه» → قاب پهن: کف ۸۰ (VIVA_CANDLE_MIN قابل تنظیم)؛ PINVAL سطح پین + لمس‌هایش را می‌خواند؛ ترندلاین/کانال قاب را پرتر می‌کند."""
    try:
        _t = str(tf or "").lower()
        _pad = _PINVAL_FRAME_PAD.get(_t, 90)
        _cap = _PINVAL_FRAME_CAP.get(_t, 200)
        _span = max(0, int(pattern_span or 0))
        _base = _span + _pad
        _fam = str(pattern or "").upper()
        if any(_k in _fam for _k in _PINVAL_LINE_FAMILIES):
            _base = _span + 2 * _pad
        return max(_candle_floor(), min(_cap, _base))
    except Exception:
        return 120


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


# ── R99q14 PRE-BREAK EARLY ALERT — PINVAL's OWN pin lines (Viva 10-15: the first
# alert must arrive while price is still on the pattern side, before the break).
# The pin's own anatomy rules are the judge (same thresholds the PINVAL detector
# uses); the edge is the line whose close is the confirmation — the pin's HIGH
# for a LONG trigger and its LOW for a SHORT.
_PINVAL_MIN_GAP_BARS = 2


def _prebreak_atr(df) -> float:
    try:
        from analysis.brooks_pa import atr as _atr_b
        _v = float(_atr_b(df))
        return _v if _v > 0 else 0.0
    except Exception:
        return 0.0


def pinval_prebreak(df, tf: str, symbol: str = "", bundle=None,
                    live_price: float = None) -> list:
    """Pre-break events from PINVAL's own pin-bar anatomy (no foreign detector)."""
    if df is None or len(df) < 45:
        return []
    atr_v = _prebreak_atr(df)
    if atr_v <= 0:
        return []
    try:
        from config import get_settings
        min_range = float(getattr(get_settings(), "pinv_min_range_atr", 0.6) or 0.6)
    except Exception:
        min_range = 0.6
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
    n = len(df)
    out = []
    seen_sides = set()
    for i in range(n - 1, max(0, n - 26), -1):
        if n - 1 - i < _PINVAL_MIN_GAP_BARS:
            continue
        try:
            row = df.iloc[i]
            o, h, l, c = (float(row["open"]), float(row["high"]),
                          float(row["low"]), float(row["close"]))
        except Exception:
            continue
        rng = h - l
        body = abs(c - o)
        if rng < min_range * atr_v or body <= 0:
            continue
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        side = direction = None
        if lower_wick >= 0.60 * rng and body <= 0.35 * rng and c >= o:
            edge, side, direction = h, "upper", "LONG"       # reclaim of the pin high
        elif upper_wick >= 0.60 * rng and body <= 0.35 * rng and c <= o:
            edge, side, direction = l, "lower", "SHORT"
        if side is None or side in seen_sides:
            continue
        # the edge must NOT be broken yet (that is the confirm lane's moment)
        if side == "upper" and live > edge + 0.10 * atr_v:
            continue
        if side == "lower" and live < edge - 0.10 * atr_v:
            continue
        dist = abs(live - edge) / atr_v
        if dist > 2.4:
            continue
        if dist > band:
            # inside/near the pin body is also a valid watch, but only while the
            # pin's own zone still holds price (never a far-away edge)
            if not (l - 0.25 * atr_v <= live <= h + 0.25 * atr_v):
                continue
        seen_sides.add(side)
        out.append({
            "setup": "PINVAL",
            "setup_name": "PINVAL",
            "tf": tf,
            "pattern_tf": tf,
            "side": side,
            "direction": direction,
            "pattern": "PINBAR",
            "pattern_fa": "پین‌بار (خط پین)",
            "edge": edge,
            "distance_atr": round(dist, 3),
            "line_geo": {"price": edge, "a": edge, "b": 0.0, "slope": 0.0,
                         "ts": str(df["timestamp"].iloc[i]) if "timestamp" in df.columns else ""},
            "pattern_geo": {},
            "pin_high": h, "pin_low": l,
            "pin_points": [{"ts": str(df["timestamp"].iloc[i]) if "timestamp" in df.columns else "",
                            "price": edge}],
            "measured": {"from": edge, "to": edge, "pct": 0.0, "height": 0.0},
            "touches": 1,
            "score": 6,
            "atr": atr_v,
            "state": "EDGE_NEAR",
            "note_fa": ("پین‌بار تازه شکل گرفته و قیمت هنوز خط پین را با کلوز "
                        f"({edge:g}) نشکسته — تأیید فقط با کلوزِ معتبر."),
        })
    return out


def pinwall_prebreak(df, tf: str, symbol: str = "", bundle=None,
                     live_price: float = None) -> list:
    """PINWALL QUALITY rides the same own-engine pin law (its zones are pins)."""
    _evs = pinval_prebreak(df, tf, symbol=symbol, bundle=bundle, live_price=live_price)
    for _e in _evs:
        _e["setup"] = "PINWALLQ"
        _e["setup_name"] = "PINWALL QUALITY"
    return _evs
