"""R99q29 — GEOMETRY CALIBRATION TO HIS REFERENCES (Viva 10-19, option B).

His references are the bar, not an opinion:

  docs/references_good_10_09/
    spot_ADA_12H-ascending-channel-CONFIRMED.jpg ...
        «both edges multi-pivot (upper 4, lower 5+), CONFIRMED on the
         upper-edge break. The channel-drawing standard.»
    spot_DOT_4H-major-TL-breakup.jpg ...
        «single descending Major Trendline through 6+ highs, break-up +
         first close, +25% box. Clean pivots, honest slope, no refit drift.»
  docs/references_good_10_12/
    BADREF_geo_8H-skybox-TOUCH.png ...
        «+65.8% sky box (ancient ceiling) ... Box must end at the same-TF
         structural ceiling (~1.02) ...»
    spot_JUP / spot_ZEC ...
        «the UPPER trend must extend to the new base (price crossed it)»

So this module answers three questions the engines never asked out loud:

  1. HOW MANY PIVOTS does this edge actually rest on?   -> touch_census()
  2. How good is this edge, on a scale his eye agrees with? -> grade()
  3. Where does an honest target box END?               -> structural_ceiling()

Nothing here vetoes. It grades, records, and clamps — the publish gate stays
the single judge.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

try:  # pandas is optional at import time for pure unit tests
    import pandas as pd  # noqa: F401
except Exception:  # pragma: no cover
    pd = None  # type: ignore


# ── touch census ────────────────────────────────────────────────────────────
def _price_at(line: Dict, x: float):
    from analysis.render_kit import line_y
    try:
        v = float(line_y(line, x))
        return v if v > 0 else None
    except Exception:
        return None


def _atr(df, k: int = 14) -> float:
    try:
        h = df["high"].astype(float).tail(k)
        l = df["low"].astype(float).tail(k)
        return float((h - l).mean())
    except Exception:
        return 0.0


def touch_census(df, line: Dict, side: str = "HIGH",
                 tol_atr: float = 0.28) -> Dict:
    """Count the bars whose wick reaches `line`, grouped into distinct taps.

    An "edge resting on N pivots" (his ADA wording) means N SEPARATE taps, not
    N touching bars — a choppy week along one trendline is ONE pivot. So taps
    are clustered: two touches closer than `cluster_bars` belong to the same
    pivot.

    `tol_atr` is how far a wick may miss the line and still count. 0.28 ATR
    reproduces the 09-17 hybrid-wick doctrine: reasonable wicks touch, a
    liquidation spike does not drag the line.
    """
    out = {"touches": 0, "first": None, "last": None, "idx": [], "tol_atr": tol_atr}
    try:
        n = len(df)
        if n < 10 or not line:
            return out
        atr = _atr(df) or 0.0
        if atr <= 0:
            return out
        tol = float(tol_atr) * atr
        hi = df["high"].astype(float).tolist()
        lo = df["low"].astype(float).tolist()
        side = str(side or "HIGH").upper()
        taps: List[int] = []
        for i in range(n):
            y = _price_at(line, i)
            if y is None:
                continue
            if side == "HIGH":
                if abs(hi[i] - y) <= tol:
                    taps.append(i)
            else:
                if abs(lo[i] - y) <= tol:
                    taps.append(i)
        if not taps:
            return out
        # cluster: a tap within 3 bars of the previous one is the same pivot
        clusters: List[int] = [taps[0]]
        for t in taps[1:]:
            if t - clusters[-1] > 3:
                clusters.append(t)
        out["touches"] = len(clusters)
        out["first"] = int(clusters[0])
        out["last"] = int(clusters[-1])
        out["idx"] = [int(c) for c in clusters]
        return out
    except Exception:
        return out


# ── grade ───────────────────────────────────────────────────────────────────
# His ADA reference is upper 4 / lower 5+; his DOT reference is 6+ on one
# line. So 4+ taps is the A bar, 3 is B, 2 is the minimum the renderer may
# draw at all.
GRADE_A_TOUCHES = 4
GRADE_B_TOUCHES = 3


def grade(touches: int, fit_atr: float = 0.0, span: int = 0) -> Tuple[str, str]:
    """(letter, why) for ONE edge. Pure; no data needed."""
    t = max(0, int(touches or 0))
    f = max(0.0, float(fit_atr or 0.0))
    if t >= GRADE_A_TOUCHES and f <= 0.30 and span >= 20:
        return "A", f"{t} taps, fit {f:.2f} ATR"
    if t >= GRADE_B_TOUCHES and f <= 0.45:
        return "B", f"{t} taps, fit {f:.2f} ATR"
    if t >= 2:
        return "C", f"{t} taps, fit {f:.2f} ATR"
    return "D", f"{t} taps"


def pair_grade(upper_taps: int, lower_taps: int,
               upper_fit: float = 0.0, lower_fit: float = 0.0,
               span: int = 0) -> Tuple[str, str]:
    """The pair's grade = the WEAKER edge (a channel is only as good as its
    worse side). Mirrors how he reads a chart."""
    gu, wu = grade(upper_taps, upper_fit, span)
    gl, wl = grade(lower_taps, lower_fit, span)
    order = {"A": 3, "B": 2, "C": 1, "D": 0}
    worst = gu if order[gu] <= order[gl] else gl
    why = f"upper {wu} | lower {wl}"
    return worst, why


# ── honest box end ──────────────────────────────────────────────────────────
def structural_ceiling(df, close: float, floor_idx: int = 0,
                       lookback: int = 120, min_gap: float = 0.012) -> Optional[float]:
    """The next same-TF structural high above price, or None.

    This is the BADREF_geo cure: the box may never run to a months-old ceiling
    from a dead regime (`+65.8% sky box`). The search is bounded to the
    pattern's own window plus `lookback` bars, and a candidate must sit at
    least `min_gap` (1.2%) above price to be worth drawing.
    """
    try:
        highs = df["high"].astype(float).to_numpy()
        n = len(highs)
        start = max(3, n - int(lookback), int(floor_idx or 0))
        for i in range(n - 3, start - 1, -1):
            if (highs[i] >= highs[i - 1] and highs[i] >= highs[i + 1]
                    and highs[i] >= highs[i - 2] and highs[i] >= highs[i + 2]
                    and float(highs[i]) > float(close) * (1.0 + float(min_gap))):
                return float(highs[i])
        return None
    except Exception:
        return None


def structural_floor(df, close: float, floor_idx: int = 0,
                     lookback: int = 120, min_gap: float = 0.012) -> Optional[float]:
    """Mirror of structural_ceiling for the short box."""
    try:
        lows = df["low"].astype(float).to_numpy()
        n = len(lows)
        start = max(3, n - int(lookback), int(floor_idx or 0))
        for i in range(n - 3, start - 1, -1):
            if (lows[i] <= lows[i - 1] and lows[i] <= lows[i + 1]
                    and lows[i] <= lows[i - 2] and lows[i] <= lows[i + 2]
                    and float(lows[i]) < float(close) * (1.0 - float(min_gap))):
                return float(lows[i])
        return None
    except Exception:
        return None


def clamp_box_end(target: float, ceiling: Optional[float], direction: str = "LONG",
                  overshoot: float = 0.012) -> Tuple[float, str]:
    """Pull a target box back to the same-TF structure.

    Returns (final_target, source) where source is one of:
      CEILING       the box ends just past the structural ceiling (honest)
      MEASURED      no ceiling found — the measured move stands
      SAME          the measured move already ended before the ceiling
    """
    try:
        t = float(target or 0.0)
        d = str(direction or "LONG").upper()
        if t <= 0 or ceiling is None or float(ceiling) <= 0:
            return t, "MEASURED"
        c = float(ceiling)
        if d == "LONG":
            if t > c * (1.0 + float(overshoot)):
                return c * (1.0 + float(overshoot) * 0.5), "CEILING"
            return t, "SAME"
        if t < c * (1.0 - float(overshoot)):
            return c * (1.0 - float(overshoot) * 0.5), "CEILING"
        return t, "SAME"
    except Exception:
        return float(target or 0.0), "MEASURED"
