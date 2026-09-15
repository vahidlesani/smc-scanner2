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
        from analysis.viva_tlbreak import fit_validated_line, load_config
        from analysis.pattern_engine import classify_shape
        cfg = load_config()
        n = len(df) - 1
        upper = fit_validated_line(df, "HIGH", cfg)
        lower = fit_validated_line(df, "LOW", cfg)
        shape = classify_shape(upper, lower, n)
        lines = []
        for ln in (upper, lower):
            if ln is None:
                continue
            lines.append({
                "slope": float(ln.slope), "intercept": float(ln.intercept),
                "x0": int(ln.first_index), "x1": int(n),
                "points": [{"ts": str(p.get("timestamp")),
                            "price": float(p.get("price"))}
                           for p in (ln.points or ())],
            })
        if shape not in ("NONE", "") and lines:
            out.append({"type": str(shape), "lines": lines})
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
    return out[:2]


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
    md["render_patterns"] = detect_patterns(trigger_df.tail(170))
    if htf_df is not None and len(htf_df) > 45:
        md["htf_zones"] = detect_zones(htf_df, getattr(candidate, "direction", ""),
                                       cap=3)
    return candidate
