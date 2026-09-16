"""CHART-8 (Viva 09-16): the unified DETECT → ORDER-TO-RENDER kit.

Viva's ruling (verbatim): «اول باید تابعی باشه که تشخیص بده و دستور رسم اون
الگو رو بده» and «همه ستاپها باید نواحی مشخص روشون رسم بشه». Every setup
calls enrich_render(); the chart renderer only obeys the render commands
stored in metadata — detection and painting are separate, testable layers.

Zone kinds (his vocabulary, English abbreviations on charts per 09-16 night):
FVG, IFVG, OB (order block), FLIP (flip zone), BOS (break level), SUPPLY and
DEMAND swing clusters; DIAMOND / FLAG-LIMIT reserved for future detectors.
Patterns reuse the validated Edwards-&-Magee/Brooks edge fitter and the
honest wedge/triangle/channel/flag classifier in analysis.pattern_engine.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ZONE_KINDS = ("FVG", "IFVG", "OB", "FLIP", "BOS", "SUPPLY", "DEMAND",
              "DIAMOND", "FLAG-LIMIT")


def _atr(df: pd.DataFrame, k: int = 14) -> float:
    try:
        return float((df["high"] - df["low"]).tail(k).mean()) or 0.0
    except Exception:
        return 0.0


def detect_zones(df: pd.DataFrame, direction: str,
                 entry_bottom: float = 0.0, entry_top: float = 0.0,
                 cap: int = 6) -> List[Dict]:
    """Every zone the doctrine can name inside the visible window, newest
    first, de-duplicated, entry zone excluded (the renderer paints that one
    itself with the POI label)."""
    zones: List[Dict] = []
    n = len(df)
    atr = _atr(df)
    if n < 30 or atr <= 0:
        return zones
    hi = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    cl = df["close"].to_numpy(float)

    def _overlaps_entry(b: float, t: float) -> bool:
        return not (t < entry_bottom - 0.3 * atr or b > entry_top + 0.3 * atr)

    def _add(kind: str, bottom: float, top: float, x0: int, bias: str) -> None:
        if top - bottom <= 0 or _overlaps_entry(bottom, top):
            return
        # Viva 09-17: «نواحی فقط با کیفیت» — a zone 8+ ATR away is history,
        # not a level price can act on inside this alert's life.
        if abs((bottom + top) / 2 - float(cl[-1])) > 8 * atr:
            return
        if any(abs(bottom - z["bottom"]) < 0.5 * atr and z["kind"] == kind
               for z in zones):
            return
        zones.append({"kind": kind, "bottom": float(bottom),
                      "top": float(top), "x0": int(x0), "bias": bias})

    # ── FVG / IFVG: three-candle imbalances, fresh first ─────────────────
    start = max(2, n - 90)
    for i in range(start, n):
        h0, l0 = float(hi[i - 2]), float(lo[i - 2])
        if lo[i] > h0:                      # bullish imbalance
            b, t, bias = h0, float(lo[i]), "DEMAND"
        elif hi[i] < l0:                    # bearish imbalance
            b, t, bias = float(hi[i]), l0, "SUPPLY"
        else:
            continue
        later_l = lo[i + 1:]
        later_h = hi[i + 1:]
        traversed = bool((later_l <= b).any()) if bias == "DEMAND" \
            else bool((later_h >= t).any())
        if not traversed:
            _add("FVG", b, t, i - 2, bias)
        elif bias == "DEMAND" and cl[-1] < b:
            _add("IFVG", b, t, i - 2, "SUPPLY")   # failed demand → inverse
        elif bias == "SUPPLY" and cl[-1] > t:
            _add("IFVG", b, t, i - 2, "DEMAND")  # failed supply → inverse

    # ── OB: last opposite candle before a displacement move ─────────────
    for i in range(max(3, n - 70), n - 2):
        move = cl[i + 2] - cl[i]
        body = cl[i] - cl[i - 1]
        if move > 1.6 * atr and body < 0:     # bull impulse out of a red candle
            _add("OB", min(cl[i], float(hi[i - 1]) * 0 + float(min(cl[i], cl[i - 1]))),
                 max(cl[i], cl[i - 1]), i - 1, "DEMAND")
        elif move < -1.6 * atr and body > 0:  # bear impulse out of a green one
            _add("OB", min(cl[i], cl[i - 1]), max(cl[i], cl[i - 1]),
                 i - 1, "SUPPLY")

    # ── BOS / FLIP: last broken swing level; retest after break = flip ───
    try:
        from analysis.indicators import pivots as _piv
        ph, pl = _piv(df.reset_index(drop=True).assign(timestamp=df.index
                      if "timestamp" not in df.columns else df["timestamp"]),
                      3, 3)
    except Exception:
        ph, pl = [], []
    last_close = float(cl[-1])
    for pts, bias in ((ph, "SUPPLY"), (pl, "DEMAND")):
        for pt in list(pts)[-10:]:
            lvl = float(pt["price"])
            x0 = int(pt.get("index", n - 20))
            after = cl[x0 + 1:]
            if len(after) < 3:
                continue
            broke = bool((after > lvl + 0.15 * atr).any()) if bias == "SUPPLY" \
                else bool((after < lvl - 0.15 * atr).any())
            if not broke:
                continue
            retest = bool(((after > lvl - 0.25 * atr) &
                           (after < lvl + 0.25 * atr)).sum() >= 1)
            _add("FLIP" if retest else "BOS", lvl - 0.12 * atr,
                 lvl + 0.12 * atr, x0,
                 "DEMAND" if bias == "SUPPLY" else "SUPPLY")

    # ── swing-cluster SUPPLY / DEMAND (his «کف و سقف و میانه») ───────────
    for pts, kind in ((ph, "SUPPLY"), (pl, "DEMAND")):
        for pt in list(pts)[-12:]:
            y = float(pt["price"])
            if abs(y - last_close) > 6 * atr:
                continue
            x0 = int(pt.get("index", n - 30))
            _add(kind, y - 0.26 * atr, y + 0.26 * atr, x0, kind)

    # per-kind quota: a FVG staircase must never crowd out the S/D map
    quota = {"FVG": 2, "IFVG": 1, "OB": 2, "FLIP": 2, "BOS": 2,
             "SUPPLY": 2, "DEMAND": 2, "DIAMOND": 1, "FLAG-LIMIT": 1}
    taken: Dict[str, int] = {}
    picked: List[Dict] = []
    for z in sorted(zones, key=lambda z: -z["x0"]):   # newest first
        k = z["kind"]
        if taken.get(k, 0) >= quota.get(k, 1):
            continue
        taken[k] = taken.get(k, 0) + 1
        picked.append(z)
    order = {k: i for i, k in enumerate(("FLIP", "OB", "FVG", "IFVG", "BOS",
                                         "SUPPLY", "DEMAND", "DIAMOND",
                                         "FLAG-LIMIT"))}
    picked.sort(key=lambda z: (order.get(z["kind"], 9), -z["x0"]))
    return picked[:cap]


def detect_patterns(df: pd.DataFrame) -> List[Dict]:
    """Validated edge geometry + honest shape classification (doctrine:
    Edwards & Magee / Brooks / E&M) as render commands; plus a trading-range
    box when the window is flat between two tested horizontals."""
    out: List[Dict] = []
    if df is None or len(df) < 45:
        return out
    try:

        import dataclasses as _dc
        from analysis.viva_tlbreak import fit_validated_line, load_config
        from analysis.pattern_engine import classify_shape
        # RENDER-ONLY clone (Viva 09-17): painting tolerates 2-touch lines and
        # a wider residual than TRADE detection ever may — doctrine lines are
        # drawn for the eye here; entries keep the strict fitter.
        cfg = _dc.replace(load_config(), pivot_left=3, pivot_right=3,
                          min_touches=2, touch_tolerance_atr=0.20,
                          max_fit_residual_atr=0.45)
        n = len(df) - 1

        def _score(ln) -> float:
            """Viva 09-17 (his option 1): validity = touches x fit x span —
            the MOST valid line wins, never merely the nearest one."""
            span = max(1, int(getattr(ln, "last_index", n)) - int(ln.first_index))
            touch = max(1, int(getattr(ln, "touch_count", len(ln.points or ())) or 1))
            fit = 1.0 / (1.0 + float(getattr(ln, "fit_residual_atr", 0.0) or 0.0))
            return touch * fit * (span ** 0.5)

        def _best(side: str):
            """Best-fitting validated line across three lookback windows —
            returns (line, x-offset) WITHOUT mutating the frozen dataclass."""
            cands = []
            for w in (90, 130, len(df)):
                if w < 45:
                    continue
                off = max(0, len(df) - w)
                ln = fit_validated_line(df.tail(w).reset_index(drop=True), side, cfg)
                if ln is not None:
                    cands.append((ln, off))
            return max(cands, key=lambda t: _score(t[0]), default=(None, 0))

        upper, u_off = _best("HIGH")
        lower, l_off = _best("LOW")

        def _ser(ln, off=0):
            return {
                "slope": float(ln.slope),
                "intercept": float(ln.intercept) - float(ln.slope) * off,
                "x0": int(off + ln.first_index), "x1": int(n),
                "points": [{"ts": str(pp.get("timestamp")),
                            "price": float(pp.get("price"))}
                           for pp in (ln.points or ())],
            }

        if upper is not None and lower is not None:
            shape = classify_shape(upper, lower, n)
            if shape in ("NONE", ""):
                # converging pair = wedge even when the classifier stays shy
                g0 = (upper.price_at(max(upper.first_index, lower.first_index))
                      - lower.price_at(max(upper.first_index, lower.first_index)))
                g1 = upper.price_at(n) - lower.price_at(n)
                same_dir = (upper.slope < 0) == (lower.slope < 0) and abs(upper.slope) > 0
                if same_dir and 0 < g1 < g0:
                    shape = "WEDGE_FALLING" if upper.slope < 0 else "WEDGE_RISING"
            if shape not in ("NONE", ""):
                out.append({"type": str(shape),
                            "lines": [_ser(upper, u_off), _ser(lower, l_off)]})
            else:
                # No classified shape: BOTH lines still paint, each as its
                # own TRENDLINE (CRV ruling 09-17: his two hand-drawn blue
                # lines; FIL: the ascending support from the lows).
                out.append({"type": "TRENDLINE", "lines": [_ser(upper, u_off)]})
                out.append({"type": "TRENDLINE", "lines": [_ser(lower, l_off)]})
        elif upper is not None or lower is not None:
            out.append({"type": "TRENDLINE",
                        "lines": [_ser(upper, u_off) if upper is not None
                                  else _ser(lower, l_off)]})
    except Exception as exc:
        print(f"render-kit pattern warning: {exc}")
    # trading range: two tested horizontals wide enough to matter
    try:
        from analysis.indicators import pivots as _piv
        ph, pl = _piv(df.reset_index(drop=True), 2, 2)
        atr = _atr(df)
        if ph and pl and atr > 0:
            last = float(df["close"].iloc[-1])
            rhi = min((float(p["price"]) for p in ph[-8:]), default=None)
            rlo = max((float(p["price"]) for p in pl[-8:]), default=None)
            if rhi and rlo and rhi - rlo >= 2.2 * atr and rlo <= last <= rhi:
                out.append({"type": "RANGE", "hi": rhi, "lo": rlo})
    except Exception:
        pass
    return out[:3]


def enrich_render(candidate, trigger_df: pd.DataFrame,
                  htf_df: Optional[pd.DataFrame] = None):
    """THE order-to-render call every setup makes: zones + patterns of the
    trigger TF, plus higher-TF zones so a 15m setup knows it stands under a
    4h supply («اینجوری ستاپ اشتباه نمیکنه»)."""
    md = candidate.metadata
    md["render_zones"] = detect_zones(
        trigger_df, getattr(candidate, "direction", ""),
        float(getattr(candidate, "entry_zone_bottom", 0) or 0),
        float(getattr(candidate, "entry_zone_top", 0) or 0))
    pats = detect_patterns(trigger_df.tail(170))
    md["render_patterns"] = pats
    # FLAG / FLAG-LIMIT: the flag's far edge IS a limit-entry zone
    for _p in pats:
        if _p.get("type") in ("FLAG_BULL", "FLAG_BEAR") and _p.get("lines"):
            _ln = _p["lines"][0]
            _xe = float(_ln.get("x1", 0))
            _ye = float(_ln["slope"]) * _xe + float(_ln["intercept"])
            _atr = _atr(trigger_df)
            _band = max(0.15 * _atr, 1e-9)
            md["render_zones"] = [{
                "kind": "FLAG-LIMIT",
                "bottom": _ye - _band, "top": _ye + _band,
                "x0": max(0, int(_xe) - 6),
                "bias": "DEMAND" if _p["type"] == "FLAG_BULL" else "SUPPLY",
            }] + list(md["render_zones"])
    base = detect_base(trigger_df)
    if base:
        md["base_watch"] = base
        md["base_gate"] = base_gate(getattr(candidate, "direction", ""), base)
        gate_ladder(candidate, base)
    if htf_df is not None and len(htf_df) > 45:
        md["htf_zones"] = detect_zones(htf_df, getattr(candidate, "direction", ""),
                                       cap=3)
    return candidate

# ── base / continuation doctrine (Viva 09-16 night) ──────────────────────
def detect_base(df, box_n: int = 24, atr_mult: float = 3.5,
                pre_n: int = 20, drift_mult: float = 1.5,
                tol_frac: float = 0.12):
    """Spike/trend into a consolidation base (rectangle / wedge / triangle /
    plain base / IFVG / supply cluster ...).  Returns None when price is not
    coiling.  Dict: trend UP|DOWN|None, hi, lo, x0, side UP|DOWN|ABOVE|BELOW|
    None(mid-box), touch_from ABOVE|BELOW|None."""
    if df is None or len(df) < box_n + pre_n + 5:
        return None
    try:
        hi_all = df["high"].to_numpy(float)
        lo_all = df["low"].to_numpy(float)
        cl = df["close"].to_numpy(float)
    except Exception:
        return None
    n = len(df)
    # the LAST candle is the actor, not part of the base: a break candle must
    # be able to close outside the box it breaks
    b_hi = float(hi_all[n - box_n - 1:n - 1].max())
    b_lo = float(lo_all[n - box_n - 1:n - 1].min())
    box_h = b_hi - b_lo
    if box_h <= 0:
        return None
    tr = pd.DataFrame({"high": hi_all, "low": lo_all, "close": cl,
                       "open": np.r_[cl[0], cl[:-1]]})
    atr = _atr(tr)
    if not np.isfinite(atr) or atr <= 0 or box_h > atr_mult * atr:
        return None                                  # still trending, no base
    drift = cl[n - box_n] - cl[n - box_n - pre_n]
    if drift > drift_mult * atr:
        trend = "UP"
    elif drift < -drift_mult * atr:
        trend = "DOWN"
    else:
        trend = None                                 # pure trading range
    c = float(cl[-1])
    tol = max(tol_frac * box_h, 0.35 * atr)
    if c > b_hi + tol:
        side, touch = "ABOVE", None
    elif c < b_lo - tol:
        side, touch = "BELOW", None
    elif c >= b_hi - tol:
        side, touch = "UP", ("ABOVE" if c >= b_hi else "BELOW")
    elif c <= b_lo + tol:
        side, touch = "DOWN", ("BELOW" if c <= b_lo else "ABOVE")
    else:
        side, touch = None, None
    return {"trend": trend, "hi": b_hi, "lo": b_lo,
            "x0": n - box_n, "side": side, "touch_from": touch}


def base_gate(direction: str, base) -> str:
    """Doctrine gate.  'سقف دنبال نزولی، کف دنبال صعودی' = inside a plain
    range the CEILING feeds shorts and the FLOOR feeds longs (mean reversion
    edge-to-edge only).  After a spike/trend the base edges are continuation
    triggers: touch = warning only, break + first trigger-TF close (or the
    pullback retest of the broken edge) = entry.  No swing high/low may by
    itself forbid trend continuation."""
    if not base:
        return "ALLOW"
    s, tr, tf = base.get("side"), base.get("trend"), base.get("touch_from")
    if s is None:
        return "REJECT-MID"                          # mid-box: no new entry
    if tr is None:                                   # pure range / channel
        if s in ("ABOVE", "BELOW"):
            return "ALLOW"                           # breakout: setup rules
        if s == "DOWN" and direction == "LONG":
            return "ALLOW"                           # floor -> long
        if s == "UP" and direction == "SHORT":
            return "ALLOW"                           # ceiling -> short
        return "REJECT-EDGE"                         # no cross-range trade
    if tr == "UP":
        if direction == "LONG":
            if s == "ABOVE" or (s == "UP" and tf == "ABOVE"):
                return "ALLOW"                       # break close / pullback
            if s == "UP":
                return "WARN-CONT"                   # touch: alert only
            return "REJECT-SIDE"
        if s == "BELOW" or (s == "DOWN" and tf == "BELOW"):
            return "ALLOW"                           # base failed -> short
        if s == "UP":
            return "WARN-REV"
        return "REJECT-SIDE"
    if direction == "SHORT":
        if s == "BELOW" or (s == "DOWN" and tf == "BELOW"):
            return "ALLOW"
        if s == "DOWN":
            return "WARN-CONT"
        return "REJECT-SIDE"
    if s == "ABOVE" or (s == "UP" and tf == "ABOVE"):
        return "ALLOW"                               # base failed -> long
    if s == "DOWN":
        return "WARN-REV"
    return "REJECT-SIDE"


def gate_ladder(candidate, base) -> None:
    """TPs outside a live range/channel are POST-BREAK only: long ladders may
    not reach past the ceiling, short ladders not past the floor, until the
    opposite edge breaks (lifecycle re-activates them)."""
    if not base or base.get("side") in ("ABOVE", "BELOW"):
        return
    lad = (candidate.metadata or {}).get("target_ladder") or {}
    targets = lad.get("targets") or []
    if not targets:
        return
    if candidate.direction == "LONG":
        locked = [i for i, t in enumerate(targets) if t > base["hi"] + 1e-9]
        level = base["hi"]
    else:
        locked = [i for i, t in enumerate(targets) if t < base["lo"] - 1e-9]
        level = base["lo"]
    if locked:
        candidate.metadata["tp_gates"] = {"level": float(level),
                                          "locked": locked}
