"""TechnoClassic pattern engine — VIVA stage-5, reality build (2026-09-10).

Classical-geometry lifecycle on 1H/4H/1D, in BOTH directions, built on the
documented rules of the classic authors (Viva's request):

  * Edwards & Magee (Technical Analysis of Stock Trends): a trendline needs a
    THIRD touch to be confirmed; importance rises with time elapsed and
    number of successful reactions; a break must pass a percentage filter;
    the channel line is a measuring tool (project its width = Minimum Price
    Objective), the trendline is the trading signal.
  * Al Brooks (Reading Price Charts Bar by Bar / Encyclopedia): fading the
    overshoot of a trend or channel line — the failed breakout / trap — is a
    HIGH-probability reversal setup; "failure of anything" (prior swing,
    channel line overshoot) is a valid counter move.
  * Alfonso's law (Viva): ~75% of first attempts to break a well-tested
    support/resistance FAIL — price rejects and travels to the opposite edge.
    That rejection is the low-risk / small-stop trade; the break is the
    exception that must be PROVEN by displacement + confirmation.

Consequences encoded here (Viva bug-report of 2026-09-10 screenshots):
  * Lines must be ALIVE: last touch recent, span recent, height sane vs ATR,
    no steep garbage diagonals, no crossing through recent price.
  * All distances/states are computed against the LIVE price (ticker), and
    if the chart feed lags the live price the alert is SUPPRESSED (stale) —
    the bot must never talk about an edge that the market already left.
  * A validated touch's REACTION history (reject vs break) decides whether
    the alert says FADE (bounce toward the opposite edge) or BREAK-READY /
    BREAK-CLOSED. Break candidates require real displacement.
  * Higher-timeframe edges outrank lower ones: a 1D tested edge overrides a
    1h pattern signal's target — implemented as `htf_pattern_adjustment`,
    a SCORE-ONLY layer applied to every setup (never a hard reject).
  * This intelligence lives in the TECHCLASSIC setup; TLBREAK / ALBROX /
    PINWALLQ / PINVAL stats stay pristine (no score surgery inside them).
"""
from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import get_settings

STATE_NEAR = "EDGE_NEAR"
STATE_READY = "BREAK_READY"
STATE_BREAK = "BREAK_CLOSED"
# Viva 09-24 (his nature sheets): an opposite-side break of a ONE-NATURE
# pattern is a VIOLATION — it warns and explains, it never becomes a signal.
STATE_VIOLATED = "PATTERN_VIOLATED"
STATE_FADE = "REJECTION_FADE"

# E&M: breaking above a resistance is the LONG event; below support the SHORT.
# Every shape alerts both edges; the pattern label only informs the caption.
# Viva 09-23/24 (حکم ماهیت الگو — verbatim): «رایزینگ وج ماهیت نزولی داره،
# با شکست کف و کلوز زیرش تایید میشه». A wedge trades its NATURE only:
# rising wedge → breakdown-SHORT, falling wedge → breakout-LONG. The
# counter-nature edge carries NO rule, so a LONG at the bottom of a rising
# wedge (the ADA morning bug) or a SHORT at the top of a falling one can
# never be created or confirmed. Internal کف→سقف / سقف→کف candidates stay
# legal ONLY in parallel channels (the is_parallel fade gate below) —
# channels and rectangles, exactly as he defined.
# Viva Law (Universal Breakout Direction): Break determines the trade direction.
# A close above the UPPER edge is ALWAYS a LONG trade.
# A close below the LOWER edge is ALWAYS a SHORT trade.
# No dogmatic one-nature suppression: if price breaks the floor, the trade is SHORT!
_EDGE_RULES = {p: {"upper": "LONG", "lower": "SHORT"} for p in (
    "TRIANGLE_ASCENDING", "TRIANGLE_DESCENDING", "TRIANGLE_SYMMETRICAL",
    "TRIANGLE", "CHANNEL_ASCENDING", "CHANNEL_DESCENDING",
    "CHANNEL_FLAT", "CHANNEL", "TRENDLINE", "HORIZONTAL_SR", "BROADENING",
    "WEDGE_RISING", "WEDGE_FALLING", "FLAG_BULL", "FLAG_BEAR"
)}

_NATURAL_EDGE = {
    "WEDGE_RISING": "lower",
    "WEDGE_FALLING": "upper",
    "FLAG_BULL": "upper",
    "FLAG_BEAR": "lower",
    "TRIANGLE_ASCENDING": "upper",
    "TRIANGLE_DESCENDING": "lower",
}

# r54 (Viva 09-28, LIT falling-wedge short — verbatim: «این الگو ذاتا صعودی
# است و با بریک ضلع بالا تایید میشه … اگر نزولی قراره بده اون هم با بریکِ
# ترند پایین و کلوز یا سیستم توهم باید تایید بشه»): every ONE-NATURE pattern
# carries its DOCTRINE direction; a trade AGAINST it is a counter-doctrine
# trade and exists only through (a) the opposite side's break + valid close,
# (b) TOHOM on that same edge, or (c) explicit supporting judgment — which
# MUST be stated in the confirmation message.
_DOCTRINE_DIRECTION = {
    "WEDGE_RISING": "SHORT",
    "WEDGE_FALLING": "LONG",
    "FLAG_BULL": "LONG",
    "FLAG_BEAR": "SHORT",
    "TRIANGLE_ASCENDING": "LONG",
    "TRIANGLE_DESCENDING": "SHORT",
}


def _counter_support_factors(bundle, direction: str, trigger_df):
    """The (c) path's evidence — multi-TF structure / momentum pressure in the
    trade's own direction. Empty list = NO supporting judgment exists."""
    factors = []
    want = "BULLISH" if str(direction).upper() == "LONG" else "BEARISH"
    fa = "صعودی" if want == "BULLISH" else "نزولی"
    try:
        from analysis.indicators import structure_bias as _sb54
    except Exception:
        _sb54 = None
    try:
        for tf in ("4h", "1d"):
            _f = bundle.get(tf) if bundle is not None else None
            if _f is None or len(_f) < 60:
                continue
            _b = (_sb54 or structure_bias)(_f.reset_index(drop=True)) if False else _sb54(_f.reset_index(drop=True))
            if str(_b.get("bias") or "").upper() == want:
                factors.append(f"ساختار سوئینگِ تایم‌فریم بالاتر ({tf}) {fa} است و جهتِ این معامله را تأیید می‌کند")
                break
    except Exception:
        pass
    try:
        d = trigger_df.tail(5).reset_index(drop=True)
        sign = 1.0 if str(direction).upper() == "LONG" else -1.0
        atr = float((d["high"] - d["low"]).tail(14).mean() or 0.0) or 1e-12
        press = sum(sign * (float(r["close"]) - float(r["open"])) for _, r in d.iterrows())
        if press / atr >= 1.5:
            factors.append("فشارِ بدنه‌ای کندل‌های اخیرِ تایم تریگر هم‌جهتِ این معامله است ( displacement تأییدی)")
    except Exception:
        pass
    return factors


def _counter_doctrine_gate(pattern: str, direction: str, is_break: bool,
                           bundle, trigger_df):
    """Pure r54 gate: returns (allowed, factors, doctrine_direction).

    * counter BREAK (the opposite side closed through its line): allowed by
      the (a)/(b) paths — the one-close law / TOHOM confirm on that edge.
    * counter FADE (rejection-based, no break): allowed ONLY with at least
      one supporting factor — the (c) path — which the confirm message must
      display; otherwise the candidate is never minted."""
    doctrine = _DOCTRINE_DIRECTION.get(str(pattern or "").upper())
    if not doctrine or str(direction).upper() == doctrine:
        return True, [], doctrine
    factors = _counter_support_factors(bundle, direction, trigger_df)
    if is_break:
        return True, factors, doctrine
    return bool(factors), factors, doctrine
# patterns whose ONLY valid break is their nature side; the other side warns
def alert_lineage_key(setup: str, symbol: str, trigger_tf: str, pattern_tf: str,
                      side, direction: str, points, is_break: bool = True) -> str:
    """R31.7 (cherry-pick r29e): stable identity of one edge scenario across
    rescans. Empty when the edge has <2 timestamped pivots or the kill
    switch is on."""
    if _legacy317():
        return ""
    try:
        ts = [str(p.get("timestamp") or p.get("ts") or "")[:16] for p in (points or [])]
        ts = [t for t in ts if t]
        if len(ts) < 2:
            return ""
        return "|".join((str(setup).upper(), str(symbol).upper(), str(trigger_tf).lower(),
                         str(pattern_tf).lower(), str(side or ""), str(direction).upper(),
                         "BRK" if is_break else "EDGE", ts[0], ts[1]))
    except Exception:
        return ""


def _legacy317() -> bool:
    """R31.7 kill switch: R317_LEGACY=1 restores the pre-audit behaviour."""
    return os.getenv("R317_LEGACY", "").strip().lower() in {"1", "true", "on", "yes"}


_ONE_NATURE = frozenset((
    "WEDGE_FALLING", "WEDGE_RISING", "TRIANGLE_ASCENDING", "TRIANGLE_DESCENDING",
    "FLAG_BULL", "FLAG_BEAR", "CHANNEL_ASCENDING", "CHANNEL_DESCENDING",
    "HEAD_SHOULDERS", "INV_HEAD_SHOULDERS", "DOUBLE_TOP", "DOUBLE_BOTTOM",
))

from analysis.patterns16 import PATTERN16_LIBRARY as _P16_LIB

PATTERN_FA = {k: v.get("fa", k) for k, v in _P16_LIB.items()}
PATTERN_FA.update({
    "INVERSE_HEAD_SHOULDERS": "سر و شانه معکوس",
    "TRIPLE_TOP": "سقف سه‌برخوردی",
    "TRIPLE_BOTTOM": "کف سه‌برخوردی",
    "FLAG_BULL": "پرچم صعودی",
    "FLAG_BEAR": "پرچم نزولی",
    "DOUBLE_BOTTOM": "کف دوقلو",
    "CUP_HANDLE": "کاپ و دسته",
})

# fit windows per timeframe — pattern must be RECENT history, not the whole archive
# R63 (audit W8): 30m/2h are structure TFs of the SWING 30m/2h lanes — they
# had no entry and silently fell back to 140.
# R64 CANDLE-COUNT LAW (his 10-02 «۲۵۰ تا ۳۵۰ کندل بسته به تایم‌فریم»): the
# fit window IS the chart window — one map (analysis.candle_counts) for both.
from analysis.candle_counts import CANDLE_COUNTS as _R64_COUNTS
_FIT_WINDOW = {tf: int(_R64_COUNTS[tf]) for tf in ("15m", "30m", "1h", "2h", "4h", "1d")}

_LOCK = threading.Lock()
_LINE_CACHE: Dict[str, dict] = {}


def _s():
    return get_settings()


def _atr(df: pd.DataFrame, k: int = 14) -> float:
    try:
        return float((df["high"] - df["low"]).tail(k).mean())
    except Exception:
        return 0.0


# ── compression (squeeze before a break; feeds READY/BREAK scoring) ───────
def compression_metrics(df: pd.DataFrame) -> Dict:
    out = {"squeeze_ok": False, "doji_count": 0, "small_body_ratio": 0.0,
           "contraction": 1.0, "bars": 0}
    try:
        if df is None or len(df) < 30:
            return out
        d = df.tail(30).reset_index(drop=True)
        o, c = d["open"].astype(float), d["close"].astype(float)
        h, l = d["high"].astype(float), d["low"].astype(float)
        rng = (h - l)
        body = (c - o).abs()
        atr14 = float(rng.tail(14).mean())
        if atr14 <= 0:
            return out
        recent = d.tail(8)
        r_rng = (recent["high"] - recent["low"]).astype(float)
        r_body = (recent["close"] - recent["open"]).abs()
        doji = int(((r_body <= 0.15 * r_rng) & (r_rng > 0)).sum())
        small = float((r_rng <= 0.75 * atr14).mean())
        base_rng = float(d.head(14)["high"].sub(d.head(14)["low"]).mean())
        contraction = float(r_rng.mean() / base_rng) if base_rng > 0 else 1.0
        out.update({"doji_count": doji, "small_body_ratio": round(small, 3),
                    "contraction": round(contraction, 3), "bars": int(len(recent))})
        out["squeeze_ok"] = bool((doji >= 2 and small >= 0.5 and contraction <= 0.60)
                                 or contraction <= 0.45)
        return out
    except Exception:
        return out


def compression_bonus(df: pd.DataFrame) -> Tuple[float, Dict]:
    m = compression_metrics(df)
    return (2.0 if m["squeeze_ok"] else 0.5 if m["small_body_ratio"] >= 0.4 else 0.0), m


def base_side_bonus(df: pd.DataFrame, price: float, direction: str) -> float:
    """Additive bonus when price sits ON or just above a swing-low base (LONG)
    or just below a swing-high base (SHORT). Never blocks (Viva rule)."""
    try:
        from analysis.setups_v7 import pivots
        d = df.tail(120)
        highs, lows = pivots(d, 2, 2)
        atr14 = float((d["high"] - d["low"]).tail(14).mean())
        if atr14 <= 0:
            return 0.0
        pts = lows if direction == "LONG" else highs
        for p in list(pts)[-4:]:
            lvl = float(p["price"])
            near = (0 <= price - lvl <= 1.0 * atr14) if direction == "LONG" \
                else (0 <= lvl - price <= 1.0 * atr14)
            if abs(price - lvl) <= 0.25 * atr14:
                return 2.0
            if near:
                return 1.0
        return 0.0
    except Exception:
        return 0.0


# ── geometry validity (the "reality" gate; fixes the screenshot bugs) ──────
def classify_shape(upper, lower, n, df=None) -> str:
    """Wedge-vs-triangle honest classifier: 'flat' only when TOTAL drift is
    small vs pattern height (per-bar slope comparisons mislabel wedges).

    r61 HYPE law (Viva 09-30: «این الان کجاش رایزینگ وج هست؟؟ … اگر ضلع بالا
    رسم بشه فالینگ وج هست»): a WEDGE_RISING claim must survive the TAIL test —
    the upper edge's LAST segment (the one the eye reads) may not contradict
    the window-OLS slope — and, when the frame is given, the ENTRY-SIDE test:
    a converging both-slopes-up structure that price entered from ABOVE after
    a vertical rally is a top being carved, never a rising wedge."""
    from analysis.patterns16 import tail_slope as _ts61, entry_side as _es61
    if upper is None and lower is None:
        return "NONE"
    if upper is None or lower is None:
        return "TRENDLINE"
    width_now = upper.price_at(n) - lower.price_at(n)
    if width_now <= 0:
        return "NONE"
    start = max(upper.first_index, lower.first_index)
    span = max(1, n - start)
    drift_u = abs(upper.slope) * span
    drift_l = abs(lower.slope) * span
    width_then = upper.price_at(start) - lower.price_at(start)
    # R62-ARENA (audit P1): «flat» is judged against the pattern HEIGHT (its
    # widest point, E&M), not the width at the apex. Near the apex a converging
    # pattern is thin, so the old width_now yardstick called every flat top a
    # slope → ascending triangles were published as RISING WEDGES (bearish!).
    height = max(float(width_now), float(width_then or 0.0))
    flat_u = drift_u <= 0.12 * height
    flat_l = drift_l <= 0.12 * height
    # V3 §5/§29: contraction must be PROGRESSIVE, not an endpoint-noise
    # artifact — the mid-span width has to sit clearly below the start width
    # before any wedge/triangle claim. A true channel keeps width_mid ≈ width_then
    # and can never flip to a wedge under small noise (his «کانال، وج شده» bug).
    width_mid = upper.price_at(start + span // 2) - lower.price_at(start + span // 2)
    converging = (width_then > 0 and width_now < 0.85 * width_then
                  and width_mid < 0.97 * width_then)
    # V3 §5 slope-delta evidence: a WEDGE claim needs the two fitted lines to
    # genuinely APPROACH (Δdrift > 15% of the dominant drift). Noise-parallel
    # fits (measured: channels Δ/max ≤ 0.09, real wedges ≥ 0.24) stay channels
    # no matter what the noisy endpoint width suggests — this is the
    # «کانال، وج شد» flip killer (same symbol, two charts, two labels).
    if abs(drift_u - drift_l) <= 0.15 * max(drift_u, drift_l, 1e-12):
        converging = False
    # slope deadband: a drift under 2% of height over the span IS horizontal
    tol = 0.02 * height / span
    if not converging:
        if width_then > 0 and width_now > 1.18 * width_then and upper.slope > tol and lower.slope < -tol:
            return "BROADENING"          # E&M megaphone: both edges fan outward
        # V3 §31: flat-top/flat-bottom triangles are judged BEFORE the channel
        # branch (a slowly-descending triangle is NOT a descending channel)
        flat_u25 = drift_u <= 0.25 * width_now
        flat_l25 = drift_l <= 0.25 * width_now
        if flat_u25 and not flat_l25 and lower.slope > tol:
            return "TRIANGLE_ASCENDING"
        if flat_l25 and not flat_u25 and upper.slope < -tol:
            return "TRIANGLE_DESCENDING"
        # V3 §29: a channel needs parallelism evidence — BOTH edges moving the
        # same way. Opposing drifts that never converged are an honest triangle.
        sgn_u = (upper.slope > tol) - (upper.slope < -tol)
        sgn_l = (lower.slope > tol) - (lower.slope < -tol)
        if sgn_u and sgn_l and sgn_u != sgn_l:
            return "TRIANGLE"
        # V3 §29: a channel needs BOTH edges meaningful — a one-slope shape is
        # «نه کانال» (his sheets); it renders as two honest trendlines.
        if (sgn_u == 0) != (sgn_l == 0):
            return "TRIANGLE"
        # V3 §29: a channel needs SIMILAR slopes («both lines rise with
        # similar slope»). When one edge DOMINATES (drift > 2.2× the other)
        # the pair is a triangle hugging a dominant line, not a parallel
        # channel — measured live: SHIB 1H rising-bottom + mildly-rising top
        # was labelled CHANNEL_ASCENDING and read wrong to the eye.
        _span_c = max(1, int(n) - max(int(getattr(upper, "first_index", 0)),
                                      int(getattr(lower, "first_index", 0))))
        _du = abs(float(upper.slope)) * _span_c
        _dl = abs(float(lower.slope)) * _span_c
        if max(_du, _dl) > 2.2 * max(min(_du, _dl), 1e-12):
            return "TRIANGLE"
        sgn = sgn_u or sgn_l
        return "CHANNEL_ASCENDING" if sgn > 0 else "CHANNEL_DESCENDING" if sgn < 0 else "CHANNEL_FLAT"
    if flat_u and not flat_l and lower.slope > tol:
        return "TRIANGLE_ASCENDING"
    if flat_l and not flat_u and upper.slope < -tol:
        return "TRIANGLE_DESCENDING"
    if upper.slope < -tol < lower.slope:
        return "TRIANGLE_SYMMETRICAL"
    if upper.slope <= 0 and lower.slope <= 0:
        return "WEDGE_FALLING"
    if upper.slope >= 0 and lower.slope >= 0:
        # r61 honest-tail + entry-side audit (docstring)
        start = max(int(upper.first_index), int(lower.first_index))
        tol_t = 0.025 * width_now / max(1, min(12, span))
        tu = _ts61(upper.price_at, n, start)
        tl = _ts61(lower.price_at, n, start)
        # R62-ARENA (audit P2): the entry side is read against the band AT
        # the pattern start (where price entered), not at the live bar.
        es = _es61(df, start, float(upper.price_at(start)), float(lower.price_at(start))) \
            if df is not None else "ANY"
        if tu < -tol_t or es == "ABOVE":
            # the upper edge price actually tests LATE is FALLING (or price
            # came in from above) — «فالینگ وج» by the eye's honest edges
            if tl < -tol_t:
                return "WEDGE_FALLING"
            if tl > tol_t:
                return "TRIANGLE_SYMMETRICAL"
            return "TRIANGLE_DESCENDING"
        return "WEDGE_RISING"
    return "TRIANGLE"


def _line_alive(line, n) -> bool:
    """A line matters only if it was TESTED RECENTLY and spans real time
    (E&M: importance rises with time + number of reactions)."""
    try:
        if line is None or int(getattr(line, "touch_count", 0)) < 3:
            return False
        age = n - int(line.last_index)
        # r40 (Viva 09-26, «پیوتها و سوئینگهای معتبر قدیمیتر از ۵۰ کندل نباید
        # کشته بشن»): the old 0.30·n gate murdered exactly the MAJOR edges —
        # a line last touched ~50 bars ago (price consolidating under it)
        # is the trend, not archaeology. Liveness now only rejects a true
        # fossil (≥85% of the window untouched, min 90 bars); floating is
        # already handled by the fitters' edge-proximity checks.
        if age > max(90, int(0.85 * n)):          # dead edge nobody touched lately
            return False
        if int(line.last_index) - int(line.first_index) < max(4, int(0.15 * n)):
            return False                          # too young/crowded to matter
        return True
    except Exception:
        return False


def touch_reactions(df: pd.DataFrame, line, side: str, n: int, atr: float) -> Dict:
    """What actually happened at each historical touch — the part the old
    engine ignored (Viva: '99%只看 pivots'): did price REJECT off the line or
    BREAK through it? reject_rate drives FADE vs BREAK alerts."""
    res = {"touches": int(len(getattr(line, "points", ()) or ())),
           "rejects": 0, "breaks": 0, "reject_rate": 0.0}
    try:
        if atr <= 0:
            return res
        closes = df["close"].astype(float).to_numpy()
        highs = df["high"].astype(float).to_numpy()
        lows = df["low"].astype(float).to_numpy()
        for p in (line.points or ()):
            ip = int(p.get("index", -1))
            if ip < 1 or ip >= n - 1:
                continue
            lvl = float(line.price_at(ip))
            j1 = min(n + 1, ip + 9)
            seg_c, seg_h, seg_l = closes[ip + 1:j1], highs[ip + 1:j1], lows[ip + 1:j1]
            if len(seg_c) == 0:
                continue
            if side == "upper":
                broke = float(seg_h.max()) >= lvl + 0.30 * atr and float(seg_c.max()) >= lvl + 0.30 * atr
                rejected = float(seg_l.min()) <= lvl - 0.8 * atr
            else:
                broke = float(seg_l.min()) <= lvl - 0.30 * atr and float(seg_c.min()) <= lvl - 0.30 * atr
                rejected = float(seg_h.max()) >= lvl + 0.8 * atr
            if broke:
                res["breaks"] += 1
            elif rejected:
                res["rejects"] += 1
        tot = res["rejects"] + res["breaks"]
        if tot:
            res["reject_rate"] = round(res["rejects"] / tot, 2)
        return res
    except Exception:
        return res


def fit_edge_line(df: pd.DataFrame, side: str, cfg, n: int):
    """Validated edge line with ONE-outlier tolerance (Edwards & Magee / Brooks):
    a spike that pierced the line and came back (failed break, H&S head, wick
    noise) must NOT invalidate an otherwise 3-touch line — it is REACTION data.
    Strict guard: the dropped pivot must lie at least 0.5 ATR OUTSIDE the fitted
    line, and the newest pivot must remain a touch (recency). Falls back to the
    plain validator; never loosens it for the other setups."""
    side = "HIGH" if str(side).upper() in ("HIGH", "UPPER") else "LOW"
    from analysis.viva_tlbreak import fit_validated_line
    line = fit_validated_line(df, side, cfg)
    if line is not None:
        return line
    try:
        import numpy as _np
        from analysis.viva_tlbreak import pivots as _piv, ValidatedLine
        highs, lows = _piv(df, cfg.pivot_left, cfg.pivot_right)
        pts = highs if side == "HIGH" else lows
        if len(pts) < cfg.min_touches + 1:
            return None
        atr = float((df["high"] - df["low"]).tail(14).mean())
        if atr <= 0:
            return None
        recent = pts[-6:]
        if int(recent[-1]["index"]) > n or n - int(recent[-1]["index"]) > max(40, int(0.75 * n)):
            return None  # newest pivot must be recent — no archaeology
        # r40: the «recent» bound above is 0.75·n (min 40) now — the old
        # 0.30·n (~50 candles on a 164-bar window) killed valid ranges whose
        # newest test was older than 50 bars (Viva 09-26 law ②).
        best = None
        for drop in range(len(recent) - 1):
            chosen = tuple(p for i, p in enumerate(recent) if i != drop)
            if len(chosen) < cfg.min_touches:
                continue
            xs = _np.asarray([float(p["index"]) for p in chosen])
            ys = _np.asarray([float(p["price"]) for p in chosen])
            if xs[-1] - xs[0] < cfg.pivot_left * 3:
                continue
            slope, intercept = _np.polyfit(xs, ys, 1)
            resid = float(_np.max(_np.abs(ys - (slope * xs + intercept))) / atr)
            if resid > cfg.max_fit_residual_atr:
                continue
            out = recent[drop]
            lvl = slope * float(out["index"]) + intercept
            pierced = (float(out["price"]) > lvl + 0.5 * atr) if side == "HIGH" \
                else (float(out["price"]) < lvl - 0.5 * atr)
            if not pierced:
                continue
            cand = ValidatedLine(side=side, slope=float(slope), intercept=float(intercept),
                                 touch_count=len(chosen), fit_residual_atr=resid,
                                 first_index=int(xs[0]), last_index=int(xs[-1]), points=chosen)
            if best is None or cand.touch_count > best.touch_count:
                best = cand
        return best
    except Exception:
        return None


def _structural_refine(df: pd.DataFrame, line, side: str, n: int,
                       height: float, pattern: str, direction: str = ""):
    """Edwards & Magee special formations layered on a validated FLAT line:
    a swing that protrudes beyond the line between its first two touches is a
    HEAD (H&S); a flat 3+ touch edge with no head is a multiple top/bottom.
    Labels are informational — geometry and edge rules are untouched."""
    try:
        pts = [int(p.get("index", -1)) for p in (line.points or ())
               if int(p.get("index", -1)) >= 0]
        if len(pts) < 3 or height <= 0 or pts[-1] - pts[0] < 6:
            return pattern, ""
        if abs(float(line.slope)) * (pts[-1] - pts[0]) > 0.20 * height:
            return pattern, ""           # not flat: wedge/triangle/channel stands
        i0, i1 = pts[0], pts[1]
        if side == "upper":
            seg = df["high"].iloc[i0:i1 + 1].astype(float)
            shoulder = max(float(df["high"].iloc[i0]), float(df["high"].iloc[i1]))
            ext = float(seg.max()) if len(seg) else shoulder
            protrude = ext - shoulder
        else:
            seg = df["low"].iloc[i0:i1 + 1].astype(float)
            shoulder = min(float(df["low"].iloc[i0]), float(df["low"].iloc[i1]))
            ext = float(seg.min()) if len(seg) else shoulder
            protrude = shoulder - ext
        if len(seg) >= 3 and protrude >= 0.25 * height:
            # R64 (label bug, SOL 09-14 «SHORT INVERSE_HEAD_SHOULDERS»): the
            # head label is bearish for H&S and bullish for its inverse — it
            # may only ride an event whose direction IS that doctrine. The
            # edge's own break goes the other way (an upper-edge break is a
            # LONG, a lower-edge break a SHORT): that is a failed head /
            # spring, never an H&S — the geometric name stands.
            _d64 = str(direction or "").upper()
            if _d64 and ((side == "upper" and _d64 != "SHORT")
                         or (side != "upper" and _d64 != "LONG")):
                return pattern, ""
            if side == "upper":
                return ("HEAD_SHOULDERS",
                        "سر و شانه: سر ≥۲۵٪ِ ارتفاع بالاتر از خطِ شانه‌ها — "
                        "تأییدِ کلاسیک با شکستِ خطِ گردن (ضلعِ مقابل) است")
            return ("INVERSE_HEAD_SHOULDERS",
                    "سر و شانه معکوس: سرِ عمیق‌تر از خطِ کف‌ها — "
                    "تأییدِ کلاسیک با شکستِ خطِ گردن (ضلعِ مقابل) است")
        if pattern in ("CHANNEL_FLAT", "HORIZONTAL_SR", "TRENDLINE"):
            return ("TRIPLE_TOP" if side == "upper" else "TRIPLE_BOTTOM",
                    "خطِ افقیِ ۳برخوردی — ادواردز/مجی: هر برخوردِ بیشتر، اعتبارِ بیشتر")
        return pattern, ""
    except Exception:
        return pattern, ""


def _flagpole_strength(df: pd.DataFrame, line, side: str, n: int,
                       atr_p: float, height: float):
    """E&M/Brooks flag-pennant: a big directional move immediately BEFORE the
    first edge touch, then a small sideways/counter channel. Returns signed
    pole strength in ATRs when the geometry qualifies (continuation only —
    counter-trend poles are exhaustion, not flags), else None."""
    try:
        if atr_p <= 0 or height <= 0:
            return None
        pts = [int(p.get("index", -1)) for p in (line.points or ())
               if int(p.get("index", -1)) >= 0]
        if not pts or pts[0] < 10:
            return None
        c = df["close"].astype(float).to_numpy()
        i0 = pts[0]
        pole = float((c[i0] - c[max(0, i0 - 8)]) / atr_p)
        if abs(pole) < 2.2 or height > 0.9 * abs(pole) * atr_p:
            return None
        if (pole > 0) != (side == "upper"):
            return None
        return round(pole, 1)
    except Exception:
        return None


# ── edge scan ──────────────────────────────────────────────────────────────
# ── V3 §27/§28: stable pattern identity + lifecycle registry ──────────────
# §28: every pattern has a stable pattern_id and an explicit lifecycle;
# terminal states are NEVER deleted — they stay queryable with their reason.
_LIFECYCLE: Dict[str, Dict] = {}
_LIFECYCLE_LOCK = threading.Lock()
_LIFECYCLE_SCAN_SEQ = {"n": 0}
_LIFECYCLE_STATE_OF_EVENT = {
    "EDGE_NEAR": "EDGE_NEAR", "BREAK_READY": "BREAK_READY",
    "BREAK_CLOSED": "BREAK_CLOSED", "REJECTION_FADE": "RETEST",
}
_LIFECYCLE_MAX_SPAN = 400        # expiration reason: excessive age (bars)
_LIFECYCLE_QUIET_SCANS = 60      # expiration reason: no recent touch/scans


def pattern_id_for(pattern, pattern_tf: str, upper, lower, n: int) -> str:
    """§28 stable id: deterministic hash of kind + both fitted lines + span.
    Same geometry → same id across rescans; a materially refitted line is a
    DIFFERENT pattern (structural replacement), never a silent mutation."""
    # r60 bug-D: identity now lives in the DEFINING PIVOTS, not the fit.
    # The old slope/intercept hash re-minted the same visual pattern on every
    # refit — each new candle slid the polyfit slightly, the id changed, and
    # the engine «discovered» the identical pattern again (his ARB 09-29 case:
    # T138451 FINAL WATCH → T490695 CONFIRMED ten minutes apart). Pivot prices
    # (3 significant digits) + relative pivot spacings are invariant to window
    # slide and micro-refits; a genuinely new/lost pivot is still a different
    # pattern (structural replacement), never a silent mutation.
    parts = [str(pattern), str(pattern_tf)]
    for line in (upper, lower):
        if line is None:
            parts.append("none")
            continue
        pts = tuple(line.points or ())
        if len(pts) < 2:
            parts.append("%.8g|%.8g|%d" % (float(line.slope), float(line.intercept),
                                           int(line.first_index)))
            continue
        sig, prev_idx = [], None
        for p in pts:
            idx = int(float(p.get("index", 0)))
            gap = 0 if prev_idx is None else idx - prev_idx
            prev_idx = idx
            sig.append("%.3g~%d" % (float(p.get("price", 0.0)), gap))
        parts.append("+".join(sig))
    parts.append(str(int(n)))
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return "%s-%s" % (str(pattern).lower(), digest)


def lifecycle_observe(pattern_id: str, state: str, reason: Optional[str] = None,
                      meta: Optional[Dict] = None) -> Dict:
    """Record a lifecycle transition (§28). Terminal records persist."""
    with _LIFECYCLE_LOCK:
        rec = dict(_LIFECYCLE.get(pattern_id) or {})
        if not rec:
            rec = {"pattern_id": pattern_id, "state": "DETECTED",
                   "created_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        rec.update({"state": state,
                    "last_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "last_scan": _LIFECYCLE_SCAN_SEQ["n"]})
        if reason:
            rec["reason"] = reason
        if meta:
            m = dict(rec.get("meta") or {})
            m.update(meta)
            rec["meta"] = m
        _LIFECYCLE[pattern_id] = rec
        return dict(rec)


def lifecycle_get(pattern_id: str) -> Optional[Dict]:
    with _LIFECYCLE_LOCK:
        rec = _LIFECYCLE.get(pattern_id)
        return dict(rec) if rec else None


def lifecycle_reset() -> None:
    with _LIFECYCLE_LOCK:
        _LIFECYCLE.clear()
        _LIFECYCLE_SCAN_SEQ["n"] = 0


def _lifecycle_scan_tick() -> None:
    """§28 expiration sweep — excessive age / no recent touch. Expiration is
    EMITTED (state EXPIRED + reason); the record is never deleted."""
    with _LIFECYCLE_LOCK:
        _LIFECYCLE_SCAN_SEQ["n"] += 1
        seq = _LIFECYCLE_SCAN_SEQ["n"]
        for _pid, rec in list(_LIFECYCLE.items()):
            if rec.get("state") in ("EXPIRED", "INVALIDATED", "FAILED"):
                continue
            meta = rec.get("meta") or {}
            reason = None
            if int(meta.get("span") or 0) > _LIFECYCLE_MAX_SPAN:
                reason = "excessive_age"
            elif seq - int(rec.get("last_scan") or seq) > _LIFECYCLE_QUIET_SCANS:
                reason = "no_recent_touch"
            if reason:
                rec.update({"state": "EXPIRED", "reason": reason, "last_scan": seq})


def dedupe_events(events: List[Dict]) -> List[Dict]:
    """§27 PRIMARY EVENT DEDUPLICATION: drop EXACT duplicates only (same
    event_id). Upper-vs-lower edge, approach-vs-break, warning-vs-later
    confirmation, and different timeframes are distinct evidence — never
    merged."""
    out: List[Dict] = []
    seen = set()
    for ev in events or []:
        eid = ev.get("event_id")
        if eid is not None:
            if eid in seen:
                continue
            seen.add(eid)
        out.append(ev)
    return out


def scan_edges(pattern_df: pd.DataFrame, trigger_df: pd.DataFrame,
               pattern_tf: str, live_price: Optional[float] = None) -> List[Dict]:
    """Per-edge lifecycle events on a fitted pattern frame. All distances use
    the LIVE price; stale feeds are suppressed, never 'predicted'."""
    from analysis.viva_tlbreak import fit_validated_line, load_config, structure_score
    settings = _s()
    events: List[Dict] = []
    if pattern_df is None or len(pattern_df) < 40 or trigger_df is None or len(trigger_df) < 6:
        return events
    cfg = load_config()
    # R64.3: PATTERN edges are structure — the far side of a live range or a
    # triple top is the pattern itself; his «ترند بی‌ربط» law targets single
    # floating trendlines, never a pattern's own second edge. ATR gate OFF
    # here, ON everywhere trade-side.
    import dataclasses as _dc718
    cfg = _dc718.replace(cfg, atr_relevance_gate=False)
    _n0 = len(pattern_df) - 1
    upper = fit_edge_line(pattern_df, "HIGH", cfg, _n0)
    lower = fit_edge_line(pattern_df, "LOW", cfg, _n0)
    if upper is None and lower is None:
        return events
    n = len(pattern_df) - 1
    pattern = classify_shape(upper, lower, n, df=pattern_df)   # R62 (P2): entry-side audit live
    # R62-ARENA (audit P7): a scissored pair (the two independently fitted
    # edges cross before the live bar) used to classify NONE → no rules →
    # total silence on that TF. Two honest trendlines remain: each edge is
    # judged on its own (break UP → LONG, break DOWN → SHORT; the one-break
    # law picks the freshest when both fired).
    _scissored62 = False
    if pattern == "NONE" and upper is not None and lower is not None:
        pattern = "TRENDLINE"
        _scissored62 = True
    # Viva 2026-09-10 (doctrine): edge BOUNCE trades only inside PARALLEL
    # channels (dynamic or static). Wedges/triangles get warnings + breaks.
    is_parallel = str(pattern).upper().startswith("CHANNEL")
    rules = _EDGE_RULES.get(str(pattern).upper())
    if not rules:
        return events
    # V3 §27/§28: stable identity for this pattern + expiration sweep tick
    pid = pattern_id_for(pattern, pattern_tf, upper, lower, n)
    _lifecycle_scan_tick()
    atr_p = _atr(pattern_df)
    atr_t = _atr(trigger_df) or atr_p
    if atr_p <= 0 or atr_t <= 0:
        return events
    # sanity: measured width must be a real pattern (E&M "well-formed"), not a
    # sliver nor a chart-wide absurdity
    width_now = None
    if upper is not None and lower is not None and not _scissored62:
        width_now = float(upper.price_at(n) - lower.price_at(n))
        if not (1.5 * atr_p <= width_now <= 45.0 * atr_p):
            return events
    last_close = float(trigger_df["close"].iloc[-1])
    live = float(live_price) if (live_price and float(live_price) > 0) else last_close
    stale_tol = float(getattr(settings, "technoclassic_stale_atr", 1.5) or 1.5)
    if abs(live - last_close) > stale_tol * atr_t:
        return events  # chart feed left behind by the market → silence, not fiction
    thr = float(getattr(settings, "technoclassic_reject_rate", 0.6) or 0.6)
    fade_enabled = bool(getattr(settings, "technoclassic_fade_signals", True))
    comp = compression_metrics(pattern_df)
    # V3 §6 APPROACH DIRECTION: net displacement of the PRE-PATTERN path
    # into the pattern — evidence only, geometry is never overwritten.
    _start_idx = max(upper.first_index, lower.first_index) if (upper and lower) else \
        (upper.first_index if upper else lower.first_index)
    _lookback = min(40, max(6, int(_start_idx)))
    _seg = pattern_df["close"].iloc[max(0, int(_start_idx) - _lookback):int(_start_idx) + 1]
    if len(_seg) >= 6:
        _net = float(_seg.iloc[-1]) - float(_seg.iloc[0])
        _thr6 = 0.25 * atr_p * max(1.0, _lookback ** 0.5)
        approach_direction = ("FROM_ABOVE" if _net < -_thr6
                              else "FROM_BELOW" if _net > _thr6 else "INSIDE")
    else:
        approach_direction = "UNKNOWN"
    # V3 §7 PATTERN ROLE: contextual evidence, never a trade instruction.
    _ROLE9 = {
        "WEDGE_FALLING": ("REVERSAL", 70), "WEDGE_RISING": ("REVERSAL", 70),
        "TRIANGLE_ASCENDING": ("CONTINUATION", 60), "TRIANGLE_DESCENDING": ("CONTINUATION", 60),
        "TRIANGLE_SYMMETRICAL": ("CONTINUATION", 60), "TRIANGLE": ("CONTINUATION", 50),
        "CHANNEL_ASCENDING": ("CONTINUATION", 55), "CHANNEL_DESCENDING": ("CONTINUATION", 55),
        "CHANNEL_FLAT": ("CONSOLIDATION", 60), "CHANNEL": ("CONTINUATION", 55),
        "FLAG_BULL": ("CONTINUATION", 80), "FLAG_BEAR": ("CONTINUATION", 80),
        "BROADENING": ("UNKNOWN", 25), "TRENDLINE": ("UNKNOWN", 30),
        "HEAD_SHOULDERS": ("REVERSAL", 70), "DOUBLE_TOP": ("REVERSAL", 70),
        "INV_HEAD_SHOULDERS": ("REVERSAL", 70), "DOUBLE_BOTTOM": ("REVERSAL", 70),
    }
    _role9, _rolec9 = _ROLE9.get(str(pattern).upper(), ("UNKNOWN", 30))
    ev_ref9 = str(trigger_df["timestamp"].iloc[-1])
    for side, line in (("upper", upper), ("lower", lower)):
        if not _line_alive(line, n):
            continue
        direction = rules.get(side)
        _nat = _NATURAL_EDGE.get(pattern)
        _counter54 = bool(_nat and _nat != side)
        if not direction:
            # Viva 09-24: the wrong-side break of a ONE-NATURE pattern was
            # warn-only. r54 (his 09-28 law, superseding): a wrong-side CLOSE
            # break IS the counter-doctrine confirmation («اگر نزولی قراره
            # بده اون هم با بریکِ ترند پایین و کلوز یا توهم باید تایید بشه»)
            # — it now runs the NORMAL break machinery as a counter candidate;
            # a live-only cross (wick, no close) stays a WARN-ONLY event.
            if str(pattern).upper() not in _ONE_NATURE:
                continue
            _ln9 = float(line.price_at(n))
            _cross9 = (live > _ln9) if side == "upper" else (live < _ln9)
            if not _cross9:
                continue
            _cc54 = (last_close > _ln9) if side == "upper" else (last_close < _ln9)
            if not _cc54:
                events.append({
                    "pattern": pattern, "pattern_fa": PATTERN_FA.get(pattern, pattern),
                    "side": side, "direction": None, "state": STATE_VIOLATED,
                    "warn_only": True, "distance_atr": round(abs(live - _ln9) / max(atr_p, 1e-12), 3),
                    "break_edge": "UPPER" if side == "upper" else "LOWER",
                    "break_direction": "UP" if side == "upper" else "DOWN",
                    "line_price": _ln9, "live": live, "pattern_tf": pattern_tf,
                    "ref_ts": str(trigger_df["timestamp"].iloc[-1]),
                    "approach_direction": approach_direction,
                    "pattern_role": _role9, "role_confidence": _rolec9,
                    "legality": "WARNING_ONLY",
                    "event_id": f"{side}|{pattern}|{STATE_VIOLATED}|{ev_ref9}",
                    "violation_fa": (
                        f"الگوی {PATTERN_FA.get(pattern, pattern)} در تایم‌فریم {pattern_tf} "
                        f"نقض شد — بریک و کلوز از ضلعِ {'بالا' if side == 'upper' else 'پایین'} "
                        "در خلافِ ماهیت الگو است. هیچ سیگنالی تأیید نمی‌شود؛ فقط هشدار."),
                })
                continue
            # r54: a wrong-side CLOSE-cross falls through to the normal break
            # machinery below with the counter direction (SHORT via the lower
            # line of a falling wedge / LONG via the upper line of a
            # descending triangle).
        if direction is None:
            # close-cross confirmed above — promote to the counter direction
            _counter54 = True
            direction = "LONG" if side == "upper" else "SHORT"
        line_now = float(line.price_at(n))
        if side == "upper":
            dist = (line_now - live) / atr_p
            crossed = live > line_now
            wick_beyond = float(trigger_df["high"].iloc[-1]) > line_now
        else:
            dist = (live - line_now) / atr_p
            crossed = live < line_now
            wick_beyond = float(trigger_df["low"].iloc[-1]) < line_now
        body = abs(float(trigger_df["close"].iloc[-1]) - float(trigger_df["open"].iloc[-1]))
        rng = float(trigger_df["high"].iloc[-1]) - float(trigger_df["low"].iloc[-1])
        displacement = body >= 0.5 * atr_t and (rng <= 0 or body / max(rng, 1e-12) >= 0.55)
        react = touch_reactions(pattern_df, line, side, n, atr_p)
        # overshoot + close back inside = Brooks' failed-breakout/rejection bar
        rejected_now = bool(wick_beyond and ((last_close <= line_now) if side == "upper"
                                             else (last_close >= line_now))) \
            or (dist <= 0.15 and not crossed)
        # r31 calibration (Viva 09-26, PYTH): when the fitted line is a
        # substantial line whose close-break already happened within the
        # fresh window, the break IS the event — recognise it now without
        # demanding a fresh displacement bar (the break candle closed bars
        # ago; waiting re-arms the engine on a weaker local line forever).
        _bk31 = getattr(line, "break_index", None)
        # Freshness of breakout must match timeframe scale (Viva Fresh Break Law):
        # 12 bars on 1D is 12 days ago (stale history, not a fresh setup!).
        _tf_str = str(pattern_tf or "").lower()
        _max_fw = 2 if _tf_str in ("1d", "3d", "1w") else (3 if _tf_str in ("4h", "8h", "12h") else 4)
        _fw31 = min(int(getattr(cfg, "fresh_break_bars", 12) or 12), _max_fw)
        _fresh_bk31 = _bk31 is not None and 0 <= n - int(_bk31) <= _fw31
        # Viva Failed-Break Doctrine: A historical break candle is VOID if price has reclaimed
        # back inside or across to the opposite edge!
        _break_held = (last_close > line_now - 0.05 * atr_p and live > line_now - 0.05 * atr_p) if side == 'upper'             else (last_close < line_now + 0.05 * atr_p and live < line_now + 0.05 * atr_p)
        if _fresh_bk31 and _break_held:
            state = STATE_BREAK
        elif crossed and displacement and _break_held:
            state = STATE_BREAK
        elif crossed and _break_held:
            state = STATE_READY
        elif dist <= 0.15 and not _break_held:
            # Price is inside approaching the edge
            state = STATE_READY
        elif dist <= 1.2 and not _break_held:
            state = STATE_NEAR
        else:
            continue
        # ── r61.2 FAILED-BREAK RECLAIM (Viva 09-30, BNB T336567: «الگو به بالا
        # شکسته اما باز این سیگنال برعکس بریک صادر کرده»): a validated close-
        # break that the LAST CLOSE has already pulled back through (beyond a
        # 0.10·ATR wick tolerance) is a FAILED break — dead at the source.
        # FTB stays safe: a wick-touch of the line is a pullback, only the
        # close back on the pre-break side kills the event.
        # ── r61.3-R62 RECLAIM REBALANCE (his 10-01 law: «نفوذ به پشتِ بریک
        # ایون در صورتی که کلوز دوباره خارج از آن باشد اشکالی ندارد» + the
        # retest-re-entry doctrine): a break whose newest close has pulled
        # back through the line is NO LONGER killed at the source. The r61.2
        # source-kill silently starved TECHCLASSIC/TLBREAK (last TC alert
        # 09-30 12:04, then ZERO — the first retest of a freshly broken edge
        # is normal lifecycle, not failure). Direction stays governed by the
        # ONE-BREAK law; the reclaim itself is vetoed at CONFIRM time
        # (BREAK_RECLAIMED gate + break_established + fresh-close law).
        _still61 = (last_close > line_now - 0.10 * atr_p) if side == "upper" \
            else (last_close < line_now + 0.10 * atr_p)
        _reclaim61 = bool(state == STATE_BREAK and not _still61)
        # E&M Minimum Price Objective: pattern width projected from the edge
        if width_now is not None:
            height = width_now
        elif direction == "LONG":
            height = max(line_now - float(pattern_df["low"].iloc[max(0, n - 40):n + 1].min()), 1.5 * atr_p)
        else:
            height = max(float(pattern_df["high"].iloc[max(0, n - 40):n + 1].max()) - line_now, 1.5 * atr_p)
        height = min(height, 45.0 * atr_p)
        # ── E&M special formations & flag-pennant overlay (labels only) ─────
        pattern, struct_note = _structural_refine(pattern_df, line, side, n, height, pattern,
                                                  direction=str(direction or ""))
        _fp = _flagpole_strength(pattern_df, line, side, n, atr_p, height)
        if _fp is not None:
            pattern = "FLAG_BULL" if _fp > 0 else "FLAG_BEAR"
            struct_note = (f"میله‌ی پرچم: حرکتِ {abs(_fp)}×ATRِ بلافاصله قبل از "
                           "فشردگی — شکست در جهتِ میله ادامه‌دهنده است (ادواردز/مجی)")
        # A relabelled shape owns its own edge rule; never retain direction
        # calculated before the structural/flag overlay.
        _canonical_direction = _EDGE_RULES.get(pattern, {}).get(side)
        if pattern in {"FLAG_BULL", "FLAG_BEAR"} and not _canonical_direction:
            continue
        direction = (_canonical_direction or direction).upper()
        target = line_now + height if direction == "LONG" else line_now - height
        # r32 (Viva 09-26; r28 leftover LTC-15m TC TARGET 70.824 < LIVE
        # 71.15): a LONG target at/below the live price is not a target —
        # the projection keeps a 1.5·ATR minimum beyond the market.
        if direction == "LONG":
            target = max(target, live + 1.5 * atr_p)
        else:
            target = min(target, live - 1.5 * atr_p)
        # r32 (Viva 09-26, AERO 15m: entry/stop/TP inside ONE doji candle):
        # the projection floor is 2× the last trigger candle's range — a
        # «setup» whose whole geometry fits one candle is noise.
        _lr32 = float(trigger_df["high"].iloc[-1]) - float(trigger_df["low"].iloc[-1])
        if math.isfinite(_lr32) and _lr32 > 0:
            height = max(height, 2.0 * _lr32)
            target = line_now + height if direction == "LONG" else line_now - height
            if direction == "LONG":
                target = max(target, live + 1.5 * atr_p)
            else:
                target = min(target, live - 1.5 * atr_p)
        # r32 (Viva 09-26, CHANNEL-TRADE law — APT 15m mid-channel): a
        # channel BREAK must carry volume expansion; without it the engine
        # is trading the middle of a range on a whisper.
        if str(pattern).upper().startswith("CHANNEL") and state == STATE_BREAK:
            try:
                _v32 = trigger_df["volume"].astype(float)
                _vm32 = float(_v32.tail(21).head(20).mean())
                _vr32 = (float(_v32.iloc[-1]) / _vm32) if _vm32 > 0 else 0.0
            except Exception:
                _vr32 = 0.0
            if _vr32 < 1.3 and not _counter54:
                continue   # volume gate for LEGAL breaks; r54 counter close-law is its own authority
        pct = (target - live) / live * 100.0 if live else 0.0
        ev = {
            "pattern": pattern, "pattern_fa": PATTERN_FA.get(pattern, pattern),
            "side": side, "direction": direction, "state": state,
            "break_edge": "UPPER" if side == "upper" else "LOWER",
            "break_direction": "UP" if side == "upper" else "DOWN",
            "direction_reason": (f"{pattern}: "
                                 f"{'شکست ضلع بالا' if side == 'upper' else 'شکست ضلع پایین'}"),
            "line_price": line_now, "live": live, "distance_atr": round(abs(dist), 3),
            "touches": int(line.touch_count), "fit_error_atr": round(float(line.fit_residual_atr), 3),
            "edge_points": [dict(p) for p in (line.points or ())],
            # R62-ARENA: the broken edge's own geometry (value + slope in
            # time) so every confirmation lane projects the SAME sloped line
            # onto later candles instead of a frozen alert-time level.
            "line_geo": _r62_line_geo(line, pattern_df, n, pattern_tf),
            "pattern_geo": {"upper": (_r62_line_geo(upper, pattern_df, n, pattern_tf) if upper else {}),
                            "lower": (_r62_line_geo(lower, pattern_df, n, pattern_tf) if lower else {})},
            "structure_score": structure_score(line, cfg), "reactions": react,
            "measured": {"from": line_now, "to": target, "pct": round(pct, 1),
                         "height": height, "last_close": live},
            "compression": comp, "pattern_tf": pattern_tf,
            "approach_direction": approach_direction,
            "pattern_role": _role9, "role_confidence": _rolec9,
            "counter_doctrine": bool(_counter54),
            "doctrine_direction": (_DOCTRINE_DIRECTION.get(str(pattern).upper())
                                   if _counter54 else None),
            "legality": "LEGAL",
            "reclaimed_seen": _reclaim61,
            "fresh_break_recognition": bool(_fresh_bk31),
            "bars_since_break": (n - int(_bk31)) if _bk31 is not None else None,
            "event_id": f"{side}|{pattern}|{state}|{ev_ref9}",
            "upper_points": [dict(p) for p in (upper.points if upper else ())],
            "lower_points": [dict(p) for p in (lower.points if lower else ())],
            "ref_ts": str(trigger_df["timestamp"].iloc[-1]),
            "base_box": [float(trigger_df["low"].tail(8).min()),
                         float(trigger_df["high"].tail(8).max())],
        }
        if struct_note:
            ev["struct_note"] = struct_note
        # ── Alfonso/Brooks edge fade — SUPPORTING evidence, not the strategy ─
        # Viva 2026-09-10: (1) fade only in parallel channels; (2) never fade a
        # line price has ALREADY crossed; (3) reject-rate is a bonus, not a veto.
        if react["reject_rate"] >= thr:
            ev["structure_score"] = min(10, int(ev.get("structure_score") or 0) + 1)
            ev["support_note_fa"] = (f"نرخ دفع تاریخِ این خط {int(float(react['reject_rate']) * 100)}٪ "
                                     "— کمک‌تأییدِ مثبت (نه شرط قطعی)")
        if fade_enabled and not _counter54 and is_parallel and react["touches"] >= 3 \
                and abs(dist) <= 0.35 and (not crossed or rejected_now):
            fdir = "SHORT" if side == "upper" else "LONG"
            opp = lower if side == "upper" else upper
            if opp is not None and _line_alive(opp, n):
                ftgt = float(opp.price_at(n))
            else:
                # round 14: the fallback target is the doctrine path of this
                # timeframe (percent of price) — never an ATR multiple, and
                # never anything read off the stop.
                try:
                    from analysis.trade_management import doctrine_path as _dp14
                    _p14, _s14 = _dp14(live, str(pattern_tf or "15m"))
                    ftgt = live - _p14 if fdir == "SHORT" else live + _p14
                except Exception:
                    ftgt = live - 0.03 * live if fdir == "SHORT" else live + 0.03 * live
            # round 11: the fade stop sits behind the line and the last bar's
            # extreme with the STANDARD buffer (no ATR term).
            from analysis.trade_management import structural_buffer as _sbuf
            _bf = _sbuf(live)
            if fdir == "SHORT":
                stop = max(line_now, float(trigger_df["high"].iloc[-1])) + _bf
                risk, rew = stop - live, live - ftgt
            else:
                stop = min(line_now, float(trigger_df["low"].iloc[-1])) - _bf
                risk, rew = live - stop, ftgt - live
            # round 14 (verbatim): «لطفا ارتباطی بین تی پی و استاپ نذار» — the old
            # `rew >= 1.3 x risk` gate tied the target to the stop; only geometry
            # (positive risk, positive reward) speaks now.
            if risk > 0 and rew > 0:
                ev["fade"] = {"direction": fdir, "entry": live, "stop": stop, "target": ftgt,
                              "tp_mid": round((live + ftgt) / 2.0, 6),
                              "rr": round(rew / max(risk, 1e-12), 2),
                              "reject_rate": react["reject_rate"],
                              "rule": "Alfonso/Brooks edge fade in parallel channel"}
                if rejected_now or abs(dist) <= 0.15:
                    ev["state"] = STATE_FADE
                else:
                    ev["fade_pending_note"] = "پلنِ بازگشت فقط با کندلِ دفع (شدو/کلوزِ برگشتی) فعال می‌شود"
        # ── both scenarios, probabilities only — no 100% before confirmation ─
        edge_fa = "سقف" if side == "upper" else "کف"
        opp_fa = "کف" if side == "upper" else "سقف"
        ev["scenarios"] = {
            "hold": (f"پایداریِ کانال: بازگشت به سمتِ {opp_fa} — خرید از {edge_fa} / فروشِ تأییدشده؛ "
                     "ورود فقط با کندلِ دفع + تایم‌پایین" if is_parallel
                     else f"الگو موازی نیست: ادواردز/مجی — برگشتِ روی ضلع بازی نمی‌شود؛ فقط شکستِ معتبر"),
            "break": (f"شکستِ {edge_fa}: کلوز معتبر فراتر از خط + پولبکِ اول + BOS تایم پایین "
                      f"→ سیگنالِ {('صعودی' if direction == 'LONG' else 'نزولی')} با هدفِ اندازه‌گیری‌شده"),
            "prob": "هیچ‌کدام ۱۰۰٪ نیست؛ همه احتمالی‌ست مگر تأییدِ کاملِ زنجیره",
        }
        events.append(ev)
    # V3 §27/§28: identity + lifecycle bookkeeping on every emitted event,
    # then exact-duplicate dedupe (same event_id only).
    _meta9 = {"pattern": str(pattern), "pattern_tf": str(pattern_tf),
              "span": int(n - _start_idx)}
    for ev in events:
        ev.setdefault("pattern_id", pid)
        if ev.get("warn_only"):
            ev["lifecycle"] = "INVALIDATED"
            lifecycle_observe(pid, "INVALIDATED",
                              reason="opposite_side_break_close", meta=_meta9)
        else:
            ev["lifecycle"] = _LIFECYCLE_STATE_OF_EVENT.get(
                str(ev.get("state") or ""), "ACTIVE")
            lifecycle_observe(pid, ev["lifecycle"], meta=_meta9)
    return dedupe_events(events)


# ── alert cooldown (durable: survives Railway redeploys via bot_kv) ───────
_ALERT_SEEN: Optional[Dict[str, float]] = None
_KV_KEY = "tc_alert_seen"
_KV_TTL = 96 * 3600.0  # stamps older than this are pruned on the next write


def _seen() -> Dict[str, float]:
    global _ALERT_SEEN
    if _ALERT_SEEN is None:
        try:
            from database.bot_kv import get_json
            raw = get_json(_KV_KEY, {}) or {}
            now = time.time()
            _ALERT_SEEN = {str(k): float(v) for k, v in raw.items()
                           if float(v) > now - _KV_TTL}
        except Exception:
            _ALERT_SEEN = {}
    return _ALERT_SEEN


def _seen_store() -> None:
    try:
        from database.bot_kv import set_json
        now = time.time()
        set_json(_KV_KEY, {k: v for k, v in _seen().items() if v > now - _KV_TTL})
    except Exception:
        pass


def _cooldown_ok(key: str, state: str) -> bool:
    hours = float(getattr(_s(), "technoclassic_cooldown_hours", 8.0) or 8.0)
    now = time.time()
    seen = _seen()
    stamp = seen.get(key)
    window = hours * 3600.0 if state == STATE_NEAR else (hours / 2) * 3600.0
    if stamp and now - stamp < window:
        return False
    seen[key] = now
    _seen_store()
    return True


def choose_primary(events: List[Dict]) -> List[Dict]:
    """One alert per (symbol, pattern_tf): the edge price is CLOSEST to.
    Announcing LONG and SHORT on the same symbol/TF at the same minute is
    noise, not analysis — the far edge gets re-announced when it matters."""
    best: Dict = {}
    for ev in events:
        key = (str(ev.get("symbol")), str(ev.get("pattern_tf")))
        d = float(ev.get("distance_atr") if ev.get("distance_atr") is not None else 9e9)
        if key not in best or d < float(best[key].get("distance_atr") or 9e9):
            best[key] = ev
    return list(best.values())


def _r62_line_geo(line, frame, n, tf):
    try:
        from analysis.confirm_r62 import line_geo_from
        return line_geo_from(line, frame, n, str(tf or ""))
    except Exception:
        return {}


def evaluate_prebreak(symbol: str, pattern_df: pd.DataFrame, trigger_df: pd.DataFrame,
                      pattern_tf: str, live_price: Optional[float] = None) -> List[Dict]:
    out: List[Dict] = []
    for ev in choose_primary(scan_edges(pattern_df, trigger_df, pattern_tf, live_price=live_price)):
        if ev["state"] == STATE_BREAK:
            continue  # real breaks become candidates via the detector, not previews
        key = f"{symbol}|{pattern_tf}|{ev['pattern']}|{ev['state']}|{ev['side']}"
        if _cooldown_ok(key, ev["state"]):
            ev2 = dict(ev)
            ev2["symbol"] = symbol
            out.append(ev2)
    return out


# ── live candidate for the TECHCLASSIC setup ───────────────────────────────
def _fit_cfg():
    from analysis.viva_tlbreak import load_config
    return load_config()


# ── R63 P4 — TRADEABLE PIVOT PATTERNS (Viva 10-01, verbatim: «همه الگوهایی
# که فقط در چارت رسم میشن باید قابل ترید باشن — سقف و کف دوقلو، سر و شانه،
# فنجان و دسته … شناسایی، رسم و در صورت تایید پوزیشن صادر بشه، طبق قوانین
# اساتید بزرگ»). Doctrine: Edwards & Magee (prior trend + decisive neckline
# close), Bulkowski (tops within tolerance, pattern invalid if price exceeds
# the tops before the break, target = height from the neckline), Al Brooks
# (strong breakout bar, follow-through, no climactic chase, a reversal needs a
# trend to reverse). The event carries the SAME fields as a scan_edges break,
# so the one TC builder/confirm ladder/snapshot lock serve it unchanged.
def pivot_pattern_events(pattern_df: pd.DataFrame, trigger_df: pd.DataFrame,
                         pattern_tf: str, live_price: Optional[float] = None) -> List[Dict]:
    from analysis.brooks_pa import (PIVOT_DOCTRINE, atr as _atr_b, breakout_bar_quality,
                                    entry_side, first_cross_index, follow_through)
    from analysis.patterns16 import detect_pivot_patterns
    out: List[Dict] = []
    try:
        if pattern_df is None or trigger_df is None or len(pattern_df) < 40 or len(trigger_df) < 12:
            return out
        pdf = pattern_df.reset_index(drop=True)
        tdf = trigger_df.reset_index(drop=True)
        atr_p = _atr_b(pdf)
        atr_t = _atr_b(tdf) or atr_p
        if atr_p <= 0 or atr_t <= 0 or "timestamp" not in pdf.columns:
            return out
        n = len(pdf) - 1
        last_close = float(tdf["close"].iloc[-1])
        live = float(live_price) if (live_price and float(live_price) > 0) else last_close

        def _pt(i, price):
            return {"timestamp": str(pdf["timestamp"].iloc[int(i)]), "price": float(price)}

        for item in detect_pivot_patterns(pdf, atr_p):
            kind = str(item.get("type") or "")
            if kind not in PIVOT_DOCTRINE:
                continue
            direction, role, want_from = PIVOT_DOCTRINE[kind]
            piv = list(item.get("pivots") or [])
            neck = float(item.get("neckline") or 0.0)
            height = float(item.get("measured") or 0.0)
            if len(piv) < 3 or neck <= 0 or height <= 0:
                continue
            first_i, last_i = int(piv[0]["index"]), int(piv[-1]["index"])
            # freshness: the last pivot is recent history, and confirmed (≥2 bars old)
            if n - last_i > 60 or n - last_i < 2:
                continue
            short = direction == "SHORT"
            if kind == "CUP_HANDLE":
                extremes = [float(piv[0]["price"]), float(piv[-1]["price"])]
            else:
                extremes = [float(p["price"]) for p in piv[0::2]]   # tops (or bottoms)
            # Bulkowski: price beyond the tops (bottoms) before the break = void
            after = pdf.iloc[last_i + 1:]
            if len(after):
                if short and float(after["high"].max()) > max(extremes) + 0.25 * atr_p:
                    continue
                if not short and kind != "CUP_HANDLE" and \
                        float(after["low"].min()) < min(extremes) - 0.25 * atr_p:
                    continue
            # Edwards & Magee / Brooks: entry side — a reversal needs a trend
            # to reverse; a continuation must be entered WITH its trend.
            es = entry_side(pdf, first_i, neck, height)
            if es.get("from") != want_from or float(es.get("prior_move") or 0) < 0.8:
                continue
            # decisive trigger-TF close through the neckline (penetration filter)
            pen = 0.10 * atr_t
            lvl = neck - pen if short else neck + pen
            if (short and last_close >= lvl) or (not short and last_close <= lvl):
                continue
            bi = first_cross_index(tdf, neck, direction, lookback=4)
            if bi is None:
                continue                                   # stale break — no chase
            bq = breakout_bar_quality(tdf, bi, direction, neck)
            if not bq.get("ok"):
                continue                                   # WEAK / CLIMAX (Brooks)
            ft = follow_through(tdf, bi, direction, neck, tol=0.05 * atr_t)
            if not ft.get("ok"):
                continue                                   # failed breakout
            # don't chase: price already ran ≥60% of the measured move
            if abs(live - neck) > 0.60 * height:
                continue
            target = neck - height if short else neck + height
            buf = 0.15 * atr_p
            if kind == "CUP_HANDLE":
                hl = float(pdf["low"].iloc[last_i:].min())
                stop_hint = hl - buf
            elif kind in ("HEAD_SHOULDERS", "INV_HEAD_SHOULDERS"):
                rs = float(piv[-1]["price"])                # right shoulder
                stop_hint = rs + buf if short else rs - buf
            else:
                stop_hint = (max(extremes) + buf) if short else (min(extremes) - buf)
            if kind == "CUP_HANDLE":
                # the rim IS the neckline (left lip → right lip)
                neck_pts = [_pt(first_i, neck), _pt(last_i, neck)]
            else:
                neck_pts = [_pt(p["index"], neck) for p in piv[1:-1:2]] or [_pt(piv[1]["index"], neck)]
                if len(neck_pts) < 2:
                    neck_pts = [neck_pts[0], _pt(last_i, neck)]
            if kind == "CUP_HANDLE":
                ext_pts = []
            elif kind in ("HEAD_SHOULDERS", "INV_HEAD_SHOULDERS"):
                ext_pts = [_pt(piv[0]["index"], piv[0]["price"]), _pt(piv[-1]["index"], piv[-1]["price"])]
            else:
                ext_pts = [_pt(p["index"], p["price"]) for p in piv[0::2]]
            geo = {"ts": str(pdf["timestamp"].iloc[n]), "price": neck, "price_back": neck,
                   "back_bars": 20, "tf_min": tf_minutes_safe(pattern_tf), "log": False,
                   "a_ts": neck_pts[0]["timestamp"]}
            side = "lower" if short else "upper"
            score = 6 + (1 if bq.get("grade") == "STRONG" else 0) \
                + (1 if ft.get("status") == "CONFIRMED" else 0) \
                + (1 if float(es.get("prior_move") or 0) >= 1.5 else 0) \
                + (1 if kind in ("HEAD_SHOULDERS", "INV_HEAD_SHOULDERS") else 0)
            pct = (target - live) / live * 100.0 if live else 0.0
            ev = {
                "pattern": kind, "pattern_fa": PATTERN_FA.get(kind, kind),
                "side": side, "direction": direction, "state": STATE_BREAK,
                "break_edge": "LOWER" if short else "UPPER",
                "break_direction": "DOWN" if short else "UP",
                "direction_reason": f"{kind}: شکست خط گردن ({'پایین' if short else 'بالا'})",
                "line_price": neck, "live": live,
                "distance_atr": round(abs(live - neck) / atr_p, 3),
                "touches": len(piv), "fit_error_atr": 0.0,
                "edge_points": neck_pts,
                "line_geo": geo,
                "pattern_geo": {"upper": ({} if short else geo), "lower": (geo if short else {})},
                "structure_score": min(10, score),
                "reactions": {"reject_rate": 0.0, "touches": len(piv)},
                "measured": {"from": neck, "to": target, "pct": round(pct, 1),
                             "height": height, "last_close": live},
                "compression": {}, "pattern_tf": pattern_tf,
                "approach_direction": es.get("from"),
                "pattern_role": role, "role_confidence": 80,
                "counter_doctrine": False, "doctrine_direction": None,
                "legality": "LEGAL", "fresh_break_recognition": True,
                "bars_since_break": int(len(tdf) - 1 - bi),
                "event_id": f"{side}|{kind}|{STATE_BREAK}|{neck_pts[0]['timestamp']}",
                "upper_points": (ext_pts if short else neck_pts),
                "lower_points": (neck_pts if short else ext_pts),
                "ref_ts": str(tdf["timestamp"].iloc[-1]) if "timestamp" in tdf.columns else "",
                "base_box": [float(tdf["low"].tail(8).min()), float(tdf["high"].tail(8).max())],
                "stop_hint": float(stop_hint),
                "pivot_pattern": {
                    "type": kind, "role": role, "neckline": neck, "height": height,
                    "pivots_ts": [_pt(p["index"], p["price"]) for p in piv],
                    "entry_side": es, "breakout_bar": bq, "follow_through": ft,
                },
            }
            out.append(ev)
    except Exception as exc:
        print(f"R63 pivot-pattern scan skipped: {exc}")
    return out


def tf_minutes_safe(tf: str) -> float:
    try:
        from analysis.confirm_r62 import tf_minutes
        return float(tf_minutes(str(tf or ""), 60.0))
    except Exception:
        return 60.0


_MINT_GUARD_TTL_S = 12 * 3600  # r60.2: one live alert per visual pattern across lanes


def _mint_guard_key(bundle, ev) -> str:
    """Pattern-level identity for the twin guard: symbol + pattern TF + kind +
    edge + the edge's FIRST and LAST pivot timestamps. A new pivot (a genuine
    structural change) yields a new key and may alert again; a mere refit
    yields the SAME key and stays silent. No trigger TF in the key — that is
    the whole point (FET trig-1h vs trig-15m twins)."""
    pts = [str(p.get("timestamp") or p.get("ts") or "")[:16]
           for p in (ev.get("edge_points") or ())]
    if not pts:
        pts = [str(getattr(bundle, "symbol", ""))]
    # r60.6: DIRECTION is NOT in the key — «جهت شکست رو تایید بکنن»: once a
    # break of this pattern owns a live chain, the OPPOSITE-direction break of
    # the same pattern may not mint a rival scenario (his ONDO complaint: the
    # engine kept hunting SHORTS after the downtrend had already broken UP).
    # A new pivot still changes the key and frees the pattern.
    return "|".join(("TCMINT", str(getattr(bundle, "symbol", "")).upper(),
                     str(ev.get("pattern_tf") or ev.get("pattern") or ""),
                     str(ev.get("pattern") or ""), str(ev.get("side") or ""),
                     pts[0], pts[-1]))


# R65: BREAK events refused because the price had already run past the
# broken edge by more than the config's extension cap (see the gate in
# detect_technoclassic). Kept as a visible ledger — a blocked break is a
# decision, never a silent drop.
R65_EXTENSION_BLOCKS: List[str] = []


def drain_r65_extension_blocks() -> List[str]:
    """Test/ops helper: notes collected since the last drain."""
    out = list(R65_EXTENSION_BLOCKS)
    R65_EXTENSION_BLOCKS.clear()
    return out


def _brooks_edge_ok(trig: pd.DataFrame, ev: Dict) -> bool:
    """R63: grade the trigger-TF bar that crossed a TC edge (Al Brooks).
    Only a FRESH cross (last 4 bars) is graded; an older recognised break is
    left to the existing stale/reclaim laws. WEAK/CLIMAX bars and failed
    follow-through reject the event; the grade is stored on the event."""
    from analysis.brooks_pa import breakout_bar_quality, first_cross_index, follow_through
    if ev.get("pivot_pattern"):
        return True
    d = str(ev.get("direction") or "").upper()
    lvl = float(ev.get("line_price") or 0.0)
    if d not in ("LONG", "SHORT") or lvl <= 0 or trig is None or len(trig) < 12:
        return True
    t = trig.reset_index(drop=True)
    bi = first_cross_index(t, lvl, d, lookback=4)
    if bi is None:
        return True
    bq = breakout_bar_quality(t, bi, d, lvl)
    ft = follow_through(t, bi, d, lvl)
    ev["brooks"] = {"breakout_bar": bq, "follow_through": ft}
    if bq.get("grade") == "STRONG":
        ev["structure_score"] = min(10, int(ev.get("structure_score") or 0) + 1)
    return bool(bq.get("ok")) and bool(ft.get("ok"))


def detect_technoclassic(bundle, style: str, setup_code: str = "TECHCLASSIC"):
    """TECHCLASSIC live detector: only this setup issues pattern signals
    (breakouts AND confirmed edge-fades). Other setups untouched.
    r60: setup_code is injectable — ALBROX's pattern lane is THIS engine
    under the ALBROX name (his union law: ALBROX = TLBREAK + TECHCLASSIC +
    zones; the zone lanes live in setups_experimental)."""
    settings = _s()
    if not getattr(settings, "technoclassic_enabled", False):
        return None
    from analysis.indicators import structure_bias
    from analysis.models import EvidenceItem, generate_viva_public_code
    from analysis.setups_v7 import _base_candidate, _ensure_frames, timeframe_profile
    from analysis.viva_tlbreak import fit_validated_line, structure_score

    cfg = _fit_cfg()
    structure_tf, _refine_tf, trigger_tf = timeframe_profile(style)
    if not _ensure_frames(bundle, (structure_tf, trigger_tf)):
        return None
    pat = bundle.get(structure_tf)
    trig = bundle.get(trigger_tf)
    if pat is None or len(pat) < 60 or trig is None or len(trig) < 6:
        return None
    pat = pat.tail(_FIT_WINDOW.get(structure_tf, 140)).reset_index(drop=True)
    live = 0.0
    try:
        live = float((getattr(bundle, "ticker", None) or {}).get("last_price") or 0.0)
    except Exception:
        live = 0.0
    # ── r60.2 THE LAW (Viva 09-30, verbatim): «تکنوکلاسیک نباید سیگنال
    # داخلی قبل از شکست ترند یا الگو بگیره» — ONLY a validated CLOSE through
    # an edge may mint a signal (break UP → LONG, break DOWN → SHORT). The
    # edge-fade lane (internal rejection inside the still-unbroken pattern —
    # his AAVE/FET/ETC 09-29 complaint) is DEAD here: rejections belong to
    # TLBREAK's scalp lane and ALBROX's zone-rejection lane, where the TOHOM
    # illusion engine governs them.
    events = [e for e in scan_edges(pat, trig, structure_tf,
                                    live_price=(live if live > 0 else None))
              if e["state"] == STATE_BREAK]
    # ── R65 TRADEABLE-BREAK (no-chase) GATE — the TECHCLASSIC «nothing ever
    # happens» root cause, measured on 121 real break events (2026-10-02):
    # 66% arrive with price already 1.5–10 ATR PAST the broken edge (the 4h
    # lane's median was 7.9 ATR — the probe case: broken edge 74,180 vs live
    # 84,370). The mint then built a 12%-wide zone and a 3.5% stop on a 15m
    # trigger, and the round-12 geometry net dropped it silently, so the setup
    # looked dead while it was really emitting un-tradeable chases.
    # Viva's own config names the law (max_extension_atr_multiple_without_
    # retest): past it the break is HISTORY — a retest belongs to the retest
    # lanes; TC waits for a new/fresh edge. Blocked events are recorded (never
    # silently swallowed) and the gate never invents a level.
    try:
        _ext_cap = float(getattr(cfg, "extension_cap_atr_swing"
                                 if str(style).upper() in ("SWING", "GRAND")
                                 else "extension_cap_atr_daytrade", 1.5) or 1.5)
    except Exception:
        _ext_cap = 1.5
    _kept = []
    for _e65 in events:
        try:
            _d65 = abs(float(_e65.get("distance_atr") or 0.0))
        except Exception:
            _d65 = 0.0
        if _d65 > _ext_cap:
            _note65 = (f"{getattr(bundle, 'symbol', '?')}|{structure_tf}|"
                       f"{_e65.get('pattern')}|{_e65.get('direction')}|{_d65:.1f}")
            if len(R65_EXTENSION_BLOCKS) < 200:
                R65_EXTENSION_BLOCKS.append(_note65)
            continue
        _kept.append(_e65)
    events = _kept
    # ── R63 Brooks breakout law on the EDGE lane too: a weak (doji / tail
    # against) or climactic breakout bar, or a breakout that already failed
    # (close back inside), never mints — «بریک‌اوت فالوترو میخواد».
    try:
        events = [e for e in events if _brooks_edge_ok(trig, e)]
    except Exception:
        pass
    # ── R63 P4: the pivot family (double top/bottom, H&S ±, cup & handle)
    if getattr(settings, "technoclassic_pivot_patterns_enabled", True):
        try:
            events += pivot_pattern_events(pat, trig, structure_tf,
                                           live_price=(live if live > 0 else None))
        except Exception as _p63:
            print(f"R63 pivot lane skipped {getattr(bundle, 'symbol', '?')}: {_p63}")
    if not events:
        return None
    events.sort(key=lambda e: e["structure_score"], reverse=True)
    # ── r61.2 THE ONE-BREAK LAW (Viva 09-30, verbatim: «الگو به بالا شکسته
    # اما باز این سیگنال برعکس بریک صادر کرده» + «این قوانین برای همه ستاپها
    # بودا»): when BOTH edges of the SAME pattern carry a validated close-
    # break, the pattern HAS ONE direction — the MOST RECENT break's (tie →
    # the stronger structure). The opposite-edge event dies here; it can
    # never outscore the pattern's own break (the BNB bug: a 3-pivot lower
    # edge outscored the 2-pivot upper edge that had just broken UP).
    _dir61 = {}
    for _e61 in events:
        _age61 = 0 if _e61.get("bars_since_break") is None else int(_e61["bars_since_break"])
        _d61 = str(_e61.get("direction") or "")
        _rk61 = (_age61, -int(_e61.get("structure_score") or 0))
        if _d61 not in _dir61 or _rk61 < _dir61[_d61]:
            _dir61[_d61] = _rk61
    if len(_dir61) > 1:
        _win61 = min(_dir61.items(), key=lambda kv: kv[1])[0]
        events = [_e61 for _e61 in events if str(_e61.get("direction") or "") == _win61]
    # Viva Live Price Alignment Law: A pattern break direction MUST strictly match live price position!
    # If live price is ABOVE the pattern's upper edge, direction CANNOT be SHORT.
    # If live price is BELOW the pattern's lower edge, direction CANNOT be LONG.
    if upper is not None and live > float(upper.price_at(n)):
        events = [e for e in events if str(e.get("direction")).upper() == "LONG"]
    elif lower is not None and live < float(lower.price_at(n)):
        events = [e for e in events if str(e.get("direction")).upper() == "SHORT"]
    for ev in events:
        # ── r60.2 twin guard: the same visual pattern re-detected on ANOTHER
        # trigger/style lane (his FET case: T446848 trig-1h → T894237
        # trig-15m two hours later) must not post twice. The guard key lives
        # at PATTERN level (no trigger TF), so any lane meeting the same
        # pivots within the freshness window stays silent.
        _guard = _mint_guard_key(bundle, ev)
        try:
            from database.bot_kv import get_json as _gj
            _seen = _gj(_guard, {}) or {}
            if float(_seen.get("ts") or 0) > __import__("time").time() - _MINT_GUARD_TTL_S:
                # ── r60.5 (his «یعنی چی هر الگو در هر ۱۲ ساعت یکبار؟؟»): the
                # 12h window is only a BACKSTOP. The real rule is one LIVE
                # chain per pattern: while the previous alert for this exact
                # pattern still lives (alert/trade running), stay silent; the
                # moment it RESOLVES (cancelled / expired / closed), a fresh
                # break of the same pattern may alert again immediately.
                _sid60 = str(_seen.get("signal_id") or "")
                _st60 = ""
                if _sid60:
                    try:
                        from database.candidate_store import candidate_status as _cs60
                        _st60 = _cs60(_sid60)
                    except Exception:
                        _st60 = ""
                # R62-ARENA (audit P10): the guard is stamped when the
                # candidate is BUILT, before it is stored/posted. A candidate
                # that never reached the store (budget-deferred, dedup, license
                # gate) left status "" and silenced its pattern for 12h. An
                # unknown id older than one discovery cycle (20 min) is a
                # never-persisted mint → allowed again.
                _age62 = __import__("time").time() - float(_seen.get("ts") or 0)
                if _st60 in ("CANCELLED", "EXPIRED", "CLOSED", "DEAD_GATE", "SUPERSEDED",
                             "UNPOSTED"):
                    pass                                   # resolved → allow re-mint
                elif _st60 == "" and _sid60 and _age62 > 20 * 60:
                    pass                                   # never persisted → allow
                elif not _sid60 or _st60 in ("", "EDUCATIONAL", "APPROACHING",
                                             "CONFIRMED", "NEAR_CONFIRM"):
                    continue                               # live or unknown → silent
                else:
                    pass                                   # any other terminal state → allow
        except Exception:
            _seen = {}
        candidate = _build_candidate(bundle, style, ev, pat, trig, structure_tf, trigger_tf, cfg,
                                     setup_code=setup_code)
        if candidate is not None:
            try:
                from database.bot_kv import set_json as _sj
                import time as _t60
                _sj(_guard, {"ts": _t60.time(),
                             "signal_id": str(getattr(candidate, "signal_id", "") or "")})
            except Exception:
                pass
            return candidate
    return None



def measured_target(entry: float, direction: str, trigger_tf: str,
                    measured_to: float) -> tuple:
    """(target_price, path_source) for a broken pattern's projection.

    Viva 09-21 (round 12): the measured-move projection is clamped into the
    timeframe band before the ladder is split, so a broken pattern can never
    publish a 34% target on a 15m trigger (the DASH case). Side-correct by
    construction: the target always lands on the scenario's own side.
    """
    from analysis.trade_management import clamp_path_to_band
    try:
        entry = float(entry or 0.0)
        d = abs(float(measured_to) - entry) if measured_to else 0.0
    except Exception:
        d = 0.0
    path, source = clamp_path_to_band(entry, trigger_tf, d)
    if path <= 0:
        return 0.0, "NONE"
    target = entry + path if str(direction).upper() == "LONG" else entry - path
    return float(target), source

def _build_candidate(bundle, style: str, ev: Dict, pat, trig, structure_tf: str,
                     trigger_tf: str, cfg, setup_code: str = "TECHCLASSIC"):
    from analysis.indicators import structure_bias
    from analysis.models import EvidenceItem, generate_viva_public_code
    from analysis.patterns import pattern_info
    from analysis.setups_v7 import _base_candidate
    from analysis.viva_tlbreak import fit_validated_line, structure_score
    from analysis.viva_tlbreak_state import VivaTLState

    is_break = ev["state"] == STATE_BREAK
    fade = ev.get("fade") or {}
    direction = (ev["direction"] if is_break else str(fade.get("direction") or ev["direction"])).upper()
    # ── r54 DOCTRINE GATE (Viva 09-28, LIT falling-wedge short): a trade
    # against the pattern's own nature exists only via the opposite-side
    # close-break / TOHOM, or with stated supporting judgment; a counter
    # FADE with zero support is never minted.
    try:
        _ok54, _factors54, _doc54 = _counter_doctrine_gate(
            str(ev.get("pattern") or ""), direction, bool(is_break), bundle, trig)
    except Exception as _g54_exc:
        print(f"counter-gate skipped {getattr(bundle, 'symbol', '?')}: {_g54_exc}")
        _ok54, _factors54, _doc54 = True, [], None
    if not _ok54:
        return None
    _counter54 = bool(_doc54 and str(direction).upper() != str(_doc54).upper())
    atr_p = _atr(pat)
    atr_t = _atr(trig) or atr_p
    if atr_p <= 0 or atr_t <= 0:
        return None
    n = len(pat) - 1
    live = float(ev.get("live") or float(trig["close"].iloc[-1]))
    line_now = float(ev["line_price"])
    # R64.3: these two re-fits are PATTERN CONTEXT (CHoCH slope, opposite
    # edge) — the pattern's own far side is structure, never «ترند بی‌ربط».
    # The ATR-distance gate stays on for trade-edge fits only.
    import dataclasses as _dc1560
    _ctx_cfg = _dc1560.replace(cfg, atr_relevance_gate=False)
    upper = fit_validated_line(pat, "HIGH", _ctx_cfg)
    lower = fit_validated_line(pat, "LOW", _ctx_cfg)
    opp = lower if direction == "LONG" else upper
    # ── r60.6 CHANGE OF CHARACTER (Viva 09-30, verbatim): «وقتی ترند نزولی
    # میشکنه به بالا دیگه اسمش خلاف روند نیست ... احتمال چنج آف کارکتر هست
    # که باید امتیاز بالاتری بده به پوزیشن نه اینکه خفه کنه». A VALIDATED
    # falling line closed ABOVE = CHoCH UP (a broken rising line closed below
    # = CHoCH DOWN): the trade takes the BREAK's side, the counter-doctrine
    # label is lifted and the setup is REWARDED, never suppressed.
    _choch60 = ""
    try:
        if is_break:
            _broken60 = upper if str(ev.get("side") or "").lower() == "upper" else lower
            _sl60 = float(getattr(_broken60, "slope", 0.0) or 0.0)
            if direction == "LONG" and _sl60 < 0:
                _choch60 = "UP"
            elif direction == "SHORT" and _sl60 > 0:
                _choch60 = "DOWN"
    except Exception:
        _choch60 = ""
    if ev.get("pivot_pattern"):
        _choch60 = ""               # R63: the pivot family has its own doctrine
    if _choch60:
        _counter54 = False          # a CHoCH break is never «خلاف ماهیت»
    # stop = NEAREST recent opposite validated touch (never the global min/max
    # that produced Viva's absurd 74%-away shorts).
    # Viva 09-20 round 11: «بدون atr … پشت آخرین سویینگ با بافر» → the buffer
    # is the standard price allowance, never an ATR multiple.
    from analysis.trade_management import (structural_buffer, clamp_path_to_band,
                                           clamp_stop_price, target_distance_cap_pct)
    buffer = structural_buffer(live)
    stop = None
    if opp is not None:
        cands = []
        for p in (opp.points or ()):
            pr = float(p["price"])
            if direction == "LONG" and pr < live - 0.1 * atr_p:
                cands.append(pr)
            elif direction == "SHORT" and pr > live + 0.1 * atr_p:
                cands.append(pr)
        if cands:
            stop = (max(cands) if direction == "LONG" else min(cands)) + (-buffer if direction == "LONG" else buffer)
    if is_break:
        entry = live
        # ── Viva 09-21 (round 12): the measured-move projection is NOT a live
        # level — DASH 15m went out with a 34% target off it. The path now goes
        # through the same doctrine funnel as every other setup: the measured
        # distance is treated as a level and capped by the TF ceiling
        # (15m/1h 5% · 4h 7% · 1d 10%) before the five-part split.
        _measured_to = float((ev.get("measured") or {}).get("to") or 0.0)
        final_target, cand_path_source = measured_target(entry, direction,
                                                          trigger_tf, _measured_to)
        if final_target <= 0:
            return None
        # ── his 09-21 ruling: a far structural swing never deletes the scenario;
        # the stop is CUT at 1.25% of price (the VVV 1h case carried a 19%-away
        # swing for two days because the old code refused to publish it at all).
        # R63 P4: the pivot family's stop is its structural doctrine stop
        # (right shoulder / the tops / the handle low) — Bulkowski, E&M.
        try:
            _sh63 = float(ev.get("stop_hint") or 0.0)
            if _sh63 > 0 and ((direction == "LONG" and _sh63 < entry)
                              or (direction == "SHORT" and _sh63 > entry)):
                stop = _sh63
        except Exception:
            pass
        if stop is None:
            stop = (line_now - buffer) if direction == "LONG" else (line_now + buffer)
    else:
        entry = float(fade.get("entry") or live)
        _wall = float(fade.get("target") or 0.0)
        # ── round 12: a fade aims at the OPPOSITE side of the pattern (his law
        # «هدف در شورت کف الگو و در صعودی زیر سقف الگو»), so the wall distance is
        # the path — only the TF ceiling may shorten it. The wall must sit on the
        # scenario's own side; a mirrored value is a collector bug, not a target.
        _cap_pct = float(target_distance_cap_pct(trigger_tf)) or 5.0
        _cap_abs = entry * _cap_pct / 100.0
        _wall_ok = (_wall > entry) if direction == "LONG" else (0 < _wall < entry)
        if _wall_ok and abs(_wall - entry) >= entry * 0.006:
            _d = abs(_wall - entry)
            _path = float(min(_d, _cap_abs))
            cand_path_source = "WALL_FADE" if _d <= _cap_abs else "WALL_FADE_CAPPED"
        else:
            _path, cand_path_source = clamp_path_to_band(
                entry, trigger_tf, abs(_wall - entry) if _wall > 0 else 0.0)
        final_target = entry + _path if direction == "LONG" else entry - _path
        stop = float(fade.get("stop") or stop or 0.0)
        if stop <= 0:
            return None
    stop, _stop_was_clamped = clamp_stop_price(entry, direction, stop,
                                               str(trigger_tf or ""))
    risk = (entry - stop) if direction == "LONG" else (stop - entry)
    reward = (final_target - entry) if direction == "LONG" else (entry - final_target)
    # Viva 09-20 round 11: no ATR limits and NO R:R gate on the stop/targets
    # («بدون atr», «فرمول ریسک به ریوارد … اصلا اهمیت نداره») — only the
    # geometry must make sense.
    if risk <= 0 or reward <= 0:
        return None
    poi = {"bottom": line_now - 0.15 * atr_t, "top": line_now + 0.15 * atr_t,
           "touches": int(ev.get("touches") or 0),
           "type": f"{setup_code} {ev['pattern']} {'BREAK' if is_break else 'FADE'}"}
    bias = structure_bias(pat, 5)
    context = {"bias": bias.get("bias", "NEUTRAL")}
    impulse = {"index": len(trig) - 1, "level": line_now, "valid": True,
               "direction": "BULLISH" if direction == "LONG" else "BEARISH",
               "body_atr": 0.5, "volume_ratio": 1.0}
    fa_pattern = ev.get("pattern_fa") or ev["pattern"]
    special = EvidenceItem(
        "technoclassic", "تکنوکلاسیک | هندسهٔ اعتبارسنجی‌شده",
        (f"{fa_pattern} روی {structure_tf} با {ev['touches']} پیوت معتبر (خطای فیت "
         f"{ev['fit_error_atr']} ATR)؛ " +
         ("کلوز شکست با جابه‌جایی ثبت شد." if is_break else
          f"برخوردِ دفع‌شده در ضلع؛ نرخ دفع تاریخی {int(float(ev['reactions']['reject_rate'])*100)}٪ (قانون آلفونسو).")),
        True, 2, level=line_now, timeframe=structure_tf)
    gate = f"{setup_code.lower()}_break_closed" if is_break else f"{setup_code.lower()}_rejection_confirmed"
    candidate = _base_candidate(bundle, style, setup_code, direction, structure_tf,
                               trigger_tf, context, poi, impulse,
                               special, gate, True)
    if candidate is None:
        return None
    # ── r60 bug-D: TC/ALBROX candidates now carry the same stable alert
    # lineage TLBREAK has had since R31.7 (pivot-timestamp identity), so a
    # refit re-detection of the SAME pattern supersedes the older row at the
    # store instead of minting a twin alert.
    try:
        _lk = alert_lineage_key(setup_code, str(bundle.symbol), str(trigger_tf),
                                str(structure_tf), str(ev.get("side") or ""),
                                direction, [dict(p) for p in (ev.get("edge_points") or ())],
                                bool(is_break))
        if _lk:
            candidate.metadata["alert_lineage_key"] = _lk
    except Exception:
        pass
    # chain-link (same contract as the legacy setups): the confirmation message
    # must quote the edge-alert that announced this level — persisted in KV so
    # it survives the 5-minute gap and any restart.
    try:
        import time as _t
        from database.bot_kv import get_json
        link = get_json(f"tc_link|{str(bundle.symbol).upper()}|{structure_tf}", {}) or {}
        if link.get("mid") and float(link.get("ts") or 0) > _t.time() - 40 * 3600:
            candidate.metadata["approaching_message_id"] = int(link["mid"])
    except Exception:
        pass
    if _choch60:
        candidate.evidence.append(EvidenceItem(
            "choch", "تغییر کاراکتر (CHoCH)",
            (f"ترند {'نزولی' if _choch60 == 'UP' else 'صعودی'} اعتبارسنجی‌شده در جهت مخالف با کلوزِ معتبر "
             f"شکسته شد — {'صعودی' if _choch60 == 'UP' else 'نزولی'} شدنِ ساختار؛ امتیاز +2 "
             "(تغییر کاراکتر تقویت است، نه خلاف‌روند)."),
            True, 1, level=line_now, timeframe=str(structure_tf)))
    candidate.sl = float(stop)
    # ── Viva 09-23 (his chart ruling, verbatim): «استاپ باید از کف بیس ۴
    # ساعته در بیاد … اگر استاپ و تی‌پی‌ها رو از نواحی تایم پایین‌تر از تایم
    # تریگر در بیاریم خیلی بهتر بشه» — the LTF base hosts the stop and the
    # NEAREST LTF swing hosts TP1 (the high-probability touch that arms the
    # trailing). Fail-open: any fetch/compute problem keeps today's values.
    _ltf_note = ""
    try:
        from analysis.trade_management import (ltf_for_trigger, ltf_structural_stop,
                                               ltf_tp1)
        from data.fetcher import get_klines
        _ltf = ltf_for_trigger(trigger_tf)
        _ltf_df = get_klines(str(bundle.symbol), _ltf, 60, closed_only=False, use_cache=True)
        _lstop = ltf_structural_stop(entry, direction, _ltf_df)
        if _lstop > 0:
            _lstop2, _clamp2 = clamp_stop_price(entry, direction, _lstop, str(trigger_tf or ""))
            if abs(entry - _lstop2) > abs(entry - stop) * 0.8:   # materially behind
                stop = float(_lstop2)
                candidate.sl = stop
                _ltf_note = f"LTF{_ltf}"
    except Exception as _exc:
        print(f"TECHCLASSIC LTF stop skipped {getattr(bundle, 'symbol', '?')}: {_exc}")
    tp2 = float(final_target)
    # ── r60.3 zone-anchored plan (Viva 09-30: «اون باکس‌ها میتونن به تارگت
    # گذاری و استاپ کمک بکنن»): the PATTERN-TF zone inventory (FVG/flip/OB/
    # supply-demand — the same boxes the chart draws) snaps TP2 onto the
    # nearest opposing box EDGE (front-running the box beats stopping inside
    # it) and a protective box between entry and the structural stop hosts
    # the stop behind its far edge. Bounded so the tool stays honest.
    _tp2_zone60 = ""
    try:
        # ── r60.4 THE zone-anchor priority (Viva 09-30, verbatim): «من در تایم
        # تریگر ساپلای و دیمند منطقی میخوام که ریفاین شده باشه» و «تی پی و
        # استاپ اگر در تایم تریگر دیده نمیشه با توجه به تایم بالاتر محاسبه
        # بشه». The anchor reads the TRIGGER-TF refined inventory FIRST (the
        # same boxes his chart shows), then the pattern-TF for context; the
        # higher-TF metadata inventory joins ONLY when neither showed an
        # opposing/protective box — for CALCULATION, never for drawing.
        from analysis.render_kit import detect_zones as _dz60
        _zinv60 = list(_dz60(trig, direction, float(poi["bottom"]), float(poi["top"])) or [])
        try:
            _zinv60 += list(_dz60(pat, direction, float(poi["bottom"]), float(poi["top"])) or [])
        except Exception:
            pass
        _buf60 = structural_buffer(entry)
        if direction == "LONG":
            _opp60 = sorted((z for z in _zinv60 if float(z.get("bottom", 0) or 0) > entry),
                            key=lambda z: float(z["bottom"]))
        else:
            _opp60 = sorted((z for z in _zinv60
                             if 0 < float(z.get("top", 0) or 0) < entry),
                            key=lambda z: -float(z["top"]))
        if not _opp60:
            # fallback: the higher-TF inventory (calculation only, never drawn)
            _htf60 = list((candidate.metadata or {}).get("htf_zones") or [])
            if _htf60:
                _zinv60 = _zinv60 + _htf60
                if direction == "LONG":
                    _opp60 = sorted((z for z in _htf60 if float(z.get("bottom", 0) or 0) > entry),
                                    key=lambda z: float(z["bottom"]))
                else:
                    _opp60 = sorted((z for z in _htf60
                                     if 0 < float(z.get("top", 0) or 0) < entry),
                                    key=lambda z: -float(z["top"]))
        if _opp60:
            _edge60 = (float(_opp60[0].get("bottom", 0) or 0) if direction == "LONG"
                       else float(_opp60[0].get("top", 0) or 0))
            _d60 = abs(_edge60 - entry)
            _p60 = abs(tp2 - entry)
            if _p60 > 0 and 0.55 * _p60 <= _d60 <= 1.45 * _p60:
                tp2 = float(_edge60)
                _tp2_zone60 = str(_opp60[0].get("kind") or "ZONE")
        _risk60 = abs(entry - stop)
        if _risk60 > 0:
            if direction == "LONG":
                _prot60 = sorted((z for z in _zinv60 if entry > float(z.get("top", 0) or 0) > 0),
                                 key=lambda z: -float(z["top"]))
                _pedge60 = (float(_prot60[0].get("bottom", 0) or 0) - _buf60) if _prot60 else 0.0
                _between = _prot60 and entry > _pedge60 > stop
            else:
                _prot60 = sorted((z for z in _zinv60
                                  if float(z.get("bottom", float("inf")) or float("inf")) > entry),
                                 key=lambda z: float(z["bottom"]))
                _pedge60 = (float(_prot60[0].get("top", 0) or 0) + _buf60) if _prot60 else 0.0
                _between = _prot60 and entry < _pedge60 < stop
            if _between:
                _sl60 = clamp_stop_price(entry, direction, float(_pedge60),
                                         str(trigger_tf or ""))[0]
                if 0.45 * _risk60 <= abs(entry - _sl60) <= 1.10 * _risk60:
                    stop = float(_sl60)
    except Exception:
        pass
    _path_full = abs(tp2 - entry)
    tp1 = entry + (tp2 - entry) / 5.0 if direction == "LONG" else entry - (entry - tp2) / 5.0
    try:
        from analysis.trade_management import ltf_for_trigger as _lf, ltf_tp1 as _ltp1
        _TP1_CAP = {"1d": 6.0, "4h": 3.5, "2h": 2.5, "1h": 2.0, "30m": 1.5,
                    "15m": 1.2, "5m": 1.0, "3m": 1.0, "1m": 1.0}
        _ltf2 = _lf(trigger_tf)
        _ltp = _ltp1(entry, direction,
                     get_klines(str(bundle.symbol), _ltf2, 60, closed_only=False, use_cache=True),
                     path=_path_full, cap_pct=float(_TP1_CAP.get(str(trigger_tf or "15m"), 2.0)))
        if _ltp > 0 and ((direction == "LONG" and entry < _ltp < tp2)
                         or (direction == "SHORT" and tp2 < _ltp < entry)):
            tp1 = float(_ltp)
    except Exception:
        pass
    candidate.tp1 = float(tp1)
    candidate.tp2 = tp2
    if _ltf_note:
        try:
            candidate.metadata["stop_source"] = _ltf_note + "_BASE"
        except Exception:
            pass
    # ── Viva 09-21 (round 12): the entry the geometry actually traded from must
    # be the entry the message shows. DASH 15m LONG carried its stop ABOVE the
    # POI-mid entry because only the stop had been rebuilt on the live price.
    candidate.planned_entry = float(entry)
    candidate.entry_zone_bottom = float(min(entry, line_now) - 0.15 * atr_t)
    candidate.entry_zone_top = float(max(entry, line_now) + 0.15 * atr_t)
    try:
        candidate.metadata["path_source"] = cand_path_source
        if _tp2_zone60:
            candidate.metadata["tp2_zone"] = _tp2_zone60
        candidate.metadata["stop_source"] = ("STRUCTURE" if abs(entry - stop) > buffer * 1.5
                                            else "BROKEN_LINE")
        candidate.metadata["stop_clamped"] = bool(_stop_was_clamped)
    except Exception:
        pass
    rr1 = abs(tp1 - entry) / max(risk, 1e-12)
    candidate.rr_tp1 = float(rr1)
    candidate.rr_tp2 = float(reward / risk)
    squeeze = bool((ev.get("compression") or {}).get("squeeze_ok"))
    raw = float(ev.get("structure_score") or 0.0) + (2.0 if is_break else 1.0) \
        + (2.0 if squeeze else 0.0) + min(2.0, 2.0 * float(ev["reactions"]["reject_rate"])) \
        + min(2.0, 0.5 * int(ev.get("touches") or 3)) \
        + (2.0 if _choch60 else 0.0)   # r60.6: CHoCH is a REWARD, not a veto
    candidate.score = min(10, max(6, int(round(raw))))
    comp_bonus, _comp = (0.0, {})
    try:
        comp_bonus, _comp = compression_bonus(pat)
    except Exception:
        pass
    # ── r60 TC calibration (Viva 09-29, dictated law): TECHCLASSIC is the
    # WITH-TREND BREAK lane — the validated break itself is the signal. The
    # multi-TF alignment reading stays as evidence/score, but it may never be
    # a MANDATORY gate for a break (his prime suspect: the multi-TF snapshot
    # vetoing the trigger-TF confirm). BREAK events drop the gate entirely;
    # FADEs keep the forced-pass (a fade must still declare trend harmony).
    if is_break:
        candidate.mandatory_gates.pop("htf_alignment", None)
    else:
        candidate.mandatory_gates["htf_alignment"] = True
    candidate.strategy_fa = (f"تکنوکلاسیک | " +
                             (f"شکست {fa_pattern} در {structure_tf} — تأیید با اولین کلوز (توهم هوشمند)"
                              if is_break else
                              f"دفع از ضلعِ کانالِ موازی در {structure_tf} — کمک‌تأییدِ قانون آلفونسو؛ "
                              f"ورودِ بازگشتی فقط با کندلِ دفع/تأییدِ تایم‌پایین"))
    stage = "S2_BREAKOUT" if is_break else "S3_RETEST"
    candidate.metadata.update({
        "strategy_variant": "VIVA_TLBREAK",
        "tc_clean": True,
        "technoclassic": {"kind": "break" if is_break else "fade", "pattern": ev["pattern"],
                          "pattern_tf": structure_tf, "side": ev["side"],
                          "reactions": ev["reactions"], "compression_bonus": comp_bonus,
                          "live_at_signal": live, "distance_atr": ev.get("distance_atr")},
        "viva_state_machine": VivaTLState(stage=stage).payload(),
        "viva_retest_window_bars": 40 if str(style).upper() == "SWING" else 32,
        "viva_pattern": ev["pattern"], "tl_pattern": ev["pattern"],
        "tl_pattern_fa": fa_pattern,
        "viva_touch_count": int(ev.get("touches") or 0),
        "viva_fit_error_atr": float(ev.get("fit_error_atr") or 0.0),
        "viva_break_line": line_now, "viva_breakout_line": line_now,
        "break_line_geo": ev.get("line_geo") or {},
        "pattern_geo": ev.get("pattern_geo") or {},
        "pattern_type": ev["pattern"],
        "pattern_bias": pattern_info(ev["pattern"]).get("bias", "NEUTRAL"),
        "break_edge": ev.get("break_edge"),
        "break_direction": ev.get("break_direction"),
        "trade_direction": direction,
        "direction_reason": ev.get("direction_reason", ""),
        "approach_direction": ev.get("approach_direction"),
        "pattern_role": ev.get("pattern_role"),
        "role_confidence": ev.get("role_confidence"),
        "pattern_id": ev.get("pattern_id"),
        "lifecycle": ev.get("lifecycle"),
        "counter_doctrine": _counter54,
        "choch": _choch60 or None,
        "doctrine_direction": (_doc54 if _counter54 else None),
        "direction_why_fa": (_factors54 if _counter54 else []),
        "viva_structure_score": float(ev.get("structure_score") or 0.0),
        "viva_final_score": raw, "viva_state": stage + "_CLOSED",
        "tl_context_tf": structure_tf, "tl_line": line_now,
        "tl_touches": int(ev.get("touches") or 0),
        "viva_upper_points": ev.get("upper_points") or [],
        "viva_lower_points": ev.get("lower_points") or [],
        "viva_retest_zone": [poi["bottom"], poi["top"]],
        "tc_projection": dict(ev["measured"], direction=direction),
        "tc_base": ev.get("base_box") or [],
        "public_code": generate_viva_public_code("TLBREAK", style),
    })
    # R31.7 (why TECHCLASSIC was silent, cause #2): every scan minted a NEW
    # random signal_id for the SAME broken edge; the zone (a sloped line)
    # drifts every 15 minutes, so the lineage test (0.08 ATR) failed and the
    # alert was re-created / superseded before any confirm-TF close. The
    # lineage is the broken EDGE itself - identified by its defining pivots
    # timestamps, which do not move as the fit window slides.
    _lk = alert_lineage_key("TECHCLASSIC", bundle.symbol, trigger_tf, ev.get("pattern_tf") or structure_tf,
                            ev.get("side"), direction,
                            ev.get("upper_points") if ev.get("side") == "upper" else ev.get("lower_points"),
                            is_break)
    if _lk:
        candidate.metadata["alert_lineage_key"] = _lk
    # r30 (Viva 09-26): «ابطال نمی‌تونه بین ناحیه باشه» — the pre-confirm
    # invalidation line must sit BEYOND the entry zone (protective side),
    # never inside it; otherwise approaching the zone (the whole point)
    # invalidates the scenario (LTC 69.404 inside 63.6-70.9).
    try:
        _zb30 = float(candidate.entry_zone_bottom)
        _zt30 = float(candidate.entry_zone_top)
        _sl30 = float(candidate.sl or 0)
        if _sl30 > 0 and direction == "LONG" and _sl30 >= _zb30:
            candidate.sl = round(_zb30 - buffer, 8)
        elif _sl30 > 0 and direction == "SHORT" and 0 < _sl30 <= _zt30:
            candidate.sl = round(_zt30 + buffer, 8)
    except Exception:
        pass
    # ── r61.1 SANE-ZONE LAW (Viva 09-30: «ناحیه های بررسی و ابطال عقلانی و
    # اصولی باشه»): a watch zone must be a zone and its invalidation must sit
    # a real distance beyond it — a setup glued to its door is skipped.
    try:
        from analysis.trade_management import sane_zone_geometry_ok as _szg61
        if not _szg61(float(candidate.entry_zone_bottom),
                      float(candidate.entry_zone_top),
                      float(candidate.planned_entry or (candidate.entry_zone_bottom + candidate.entry_zone_top) / 2.0),
                      float(candidate.sl or 0), direction, float(atr_t or 0.0),
                      str(getattr(candidate, "style", "") or ""),
                      # R64: a break lane — the zone is the line→live
                      # corridor; floors capped by the trigger-TF ceiling
                      line_price=float(line_now), trigger_tf=str(trigger_tf or "")):
            return None
    except Exception:
        pass
    # ── r63 RISK-LADDER STOP (his 10-01 amendment, law ①, verbatim: «استاپ
    # اولیه پشتِ آخرین سوینگِ یک تایم‌فریم بالاتر از تایم‌فریم تریگر؛ نبود →
    # دو TF بالاتر؛ نبود → ۳٫۵ تا ۵٪، سقف ۵٪») — replaces the structural stop
    # for the break/structure lanes (newest law wins over the 09-23 LTF-base
    # stop; the LTF law keeps hosting TP1). Pin/reject lanes are exempt
    # (law ④ keeps them exactly behind the same-TF extreme + last swing).
    # The r30 sane-zone guard is re-applied after the ladder so the stop
    # never lands inside the entry zone. Fail-open everywhere.
    try:
        # R64 (found by the TC probe): ``config`` exposes get_settings(), not
        # SETTINGS — the old import raised on EVERY build and the fail-open
        # silently skipped his law-① risk ladder for every TC/ALBROX trade.
        from config import get_settings as _gs63
        _S63 = _gs63()
        if bool(getattr(_S63, "risk_ladder_enabled", True)) \
                and not bool((candidate.metadata or {}).get("rejection_scalp")):
            from analysis.risk_ladder import ladder_stop as _ls63
            from data.fetcher import get_klines as _gk63
            _entry63 = float(candidate.planned_entry or (candidate.entry_zone_bottom
                                                         + candidate.entry_zone_top) / 2.0)
            _sl063 = float(candidate.sl or 0.0)
            _struct_pct63 = (abs(_entry63 - _sl063) / _entry63 * 100.0) \
                if (_entry63 > 0 and _sl063 > 0) else 0.0
            _lad63 = _ls63(str(bundle.symbol), direction, _entry63,
                           str(trigger_tf or ""), _struct_pct63, _gk63)
            if _lad63 and _lad63.get("stop") and _sl063 > 0:
                _new63 = float(_lad63["stop"])
                # r30 sane-zone guard: invalidation stays BEYOND the zone
                _zb63 = float(candidate.entry_zone_bottom)
                _zt63 = float(candidate.entry_zone_top)
                if direction == "LONG" and _new63 >= _zb63:
                    _new63 = round(_zb63 - float(buffer), 8)
                elif direction == "SHORT" and 0 < _new63 <= _zt63:
                    _new63 = round(_zt63 + float(buffer), 8)
                if ((direction == "LONG" and _new63 < _sl063)
                        or (direction == "SHORT" and _new63 > _sl063)
                        or _lad63.get("basis") == "PCT"):
                    # take the ladder when it is materially behind the old
                    # stop, or when it IS the approved pct fallback
                    if abs(_entry63 - _new63) / max(_entry63, 1e-12) > 0.001:
                        candidate.sl = _new63
                candidate.metadata["stop_ladder"] = {
                    "tf": _lad63.get("tf"), "hop": _lad63.get("hop"),
                    "basis": _lad63.get("basis")}
    except Exception as _lad63_exc:
        print(f"risk-ladder stop skipped {getattr(bundle, 'symbol', '?')}: {_lad63_exc}")
    # ── Viva 09-23 (round 20 ENTRY LAW): remember the MAJOR-pivot trendline
    # opposing this break (highest-TF validated 1d/4h/1h line on the break's
    # side) — confirmation must be a CLOSE beyond it, not just the tool line.
    try:
        _maj_cands = [l for l in _htf_lines(str(bundle.symbol))
                      if (str(l.get("side")) == "upper") == (direction == "LONG")]
        if _maj_cands:
            _rank = {"1d": 3, "4h": 2, "1h": 1}
            _maj_cands.sort(key=lambda l: _rank.get(str(l.get("tf")), 0), reverse=True)
            candidate.metadata["viva_major_break_line"] = float(_maj_cands[0]["price"])
            candidate.metadata["viva_major_break_line_tf"] = str(_maj_cands[0]["tf"])
    except Exception:
        pass
    _attach_r63_geometry(candidate, ev, structure_tf)
    return candidate


def _attach_r63_geometry(candidate, ev: Dict, structure_tf: str) -> None:
    """R63: the trade lane hands the chart its OWN geometry (G1) — a pivot
    pattern's M/W/H&S polyline + neckline is drawn from the very pivots the
    trade was built on, and the Brooks reading is stated as evidence."""
    try:
        from analysis.models import EvidenceItem
        md = candidate.metadata
        pp = ev.get("pivot_pattern")
        if pp:
            md["pivot_pattern"] = pp
            md["render_patterns_trade"] = [{
                "type": pp.get("type"), "trade_geometry": True, "lines": [],
                "pivots_ts": list(pp.get("pivots_ts") or []),
                "neckline": float(pp.get("neckline") or 0.0),
                "role": pp.get("role"), "tf": str(structure_tf),
            }]
            es = pp.get("entry_side") or {}
            bq = pp.get("breakout_bar") or {}
            ft = pp.get("follow_through") or {}
            candidate.evidence.append(EvidenceItem(
                "pivot_pattern", "الگوی پیوتی کلاسیک (ادواردز/مجی · بالکوفسکی)",
                (f"{ev.get('pattern_fa') or pp.get('type')} روی {structure_tf}: "
                 f"{'برگشتی' if pp.get('role') == 'REVERSAL' else 'ادامه‌دهنده'} — "
                 f"قیمت از {'پایین' if es.get('from') == 'BELOW' else 'بالا'} وارد الگو شد "
                 f"(حرکت قبلی {es.get('prior_move')}× ارتفاع)؛ کلوز قاطع زیرِ/بالای خط گردن "
                 f"{float(pp.get('neckline') or 0):.6g}؛ هدف = ارتفاع الگو از خط گردن."),
                True, 2, level=float(pp.get("neckline") or 0.0), timeframe=str(structure_tf)))
        else:
            b = ev.get("brooks") or {}
            bq = b.get("breakout_bar") or {}
            ft = b.get("follow_through") or {}
        if bq:
            md["brooks_breakout"] = {"grade": bq.get("grade"), "follow_through": ft.get("status")}
            _g = {"STRONG": "قوی", "OK": "قابل‌قبول"}.get(str(bq.get("grade")), str(bq.get("grade")))
            _f = {"CONFIRMED": "تأیید شد", "HOLDING": "بیرون الگو پایدار", "PENDING": "در انتظار کندل بعد"}.get(
                str(ft.get("status")), str(ft.get("status")))
            candidate.evidence.append(EvidenceItem(
                "brooks_breakout", "پرایس‌اکشن ال بروکس | کندل شکست",
                f"کندل شکست {_g} (بدنه {bq.get('body_ratio')} از رنج، کلوز در {bq.get('close_pos')} رنج)؛ فالوترو: {_f}.",
                True, 1, level=float(ev.get("line_price") or 0.0), timeframe=str(structure_tf)))
    except Exception as exc:
        print(f"R63 geometry attach warning: {exc}")


# ── HTF edge intelligence for ALL setups (score-only layer) ────────────────
def _htf_lines(symbol: str) -> List[Dict]:
    """Cached 1D/4H/1H validated edges with their reaction history.
    TTL: technoclassic_htf_cache_hours (default 4)."""
    ttl = float(getattr(_s(), "technoclassic_htf_cache_hours", 4.0) or 4.0) * 3600.0
    with _LOCK:
        cached = _LINE_CACHE.get(symbol)
        if cached and time.time() - cached["at"] < ttl:
            return cached["lines"]
    from data.fetcher import get_klines
    from analysis.viva_tlbreak import fit_validated_line
    lines: List[Dict] = []
    for tf in ("1d", "4h", "1h"):
        try:
            df = get_klines(symbol, tf, _FIT_WINDOW.get(tf, 140) + 40)
            if df is None or len(df) < 60:
                continue
            df = df.tail(_FIT_WINDOW.get(tf, 140)).reset_index(drop=True)
            n = len(df) - 1
            atr = _atr(df)
            if atr <= 0:
                continue
            for side, scan in (("upper", "HIGH"), ("lower", "LOW")):
                line = fit_validated_line(df, scan)
                if not _line_alive(line, n):
                    continue
                react = touch_reactions(df, line, side, n, atr)
                lines.append({"tf": tf, "side": side,
                              "price": float(line.price_at(n)),
                              "touches": int(line.touch_count),
                              "reject_rate": float(react["reject_rate"]),
                              "atr": atr})
        except Exception:
            continue
    with _LOCK:
        _LINE_CACHE[symbol] = {"at": time.time(), "lines": lines}
    return lines


def htf_pattern_adjustment(bundle, candidate) -> Tuple[int, str]:
    """Score-only cross-timeframe awareness (Viva: a 1h setup whose TP stands
    ON a daily tested edge is likely to fail; an entry AT such an edge is a
    gift). Never rejects, never touches gates — just score + a caption note.
    1D edges weigh 2, 4H 1, 1H half."""
    settings = _s()
    if not getattr(settings, "technoclassic_htf_scoring", True):
        return 0, ""
    try:
        entry = float(candidate.planned_entry or 0.0)
        tp1 = float(candidate.tp1 or 0.0)
        tp2 = float(getattr(candidate, "tp2", 0.0) or tp1)
        if entry <= 0:
            return 0, ""
        direction = str(candidate.direction).upper()
        lines = _htf_lines(str(bundle.symbol))
        if not lines:
            return 0, ""
        weight = {"1d": 2.0, "4h": 1.0, "1h": 0.5}
        conflict = 0.0
        bonus = 0.0
        notes: List[str] = []
        for L in lines:
            if int(L["touches"]) < 3 or float(L["reject_rate"]) < 0.5:
                continue
            w = weight.get(L["tf"], 0.5)
            price_ref = max(entry, 1e-9)
            if direction == "LONG":
                if L["side"] == "upper":
                    for tgt, k in ((tp1, 1.0), (tp2, 0.5)):
                        if tgt <= entry:
                            continue
                        d = (L["price"] - tgt) / price_ref
                        if -0.02 <= d <= 0.01:  # TP1 straddles a tested daily/4h edge
                            conflict += w * k
                            notes.append(f"هدف روی/پشت ضلعِ تست‌شدهٔ {L['tf']}")
                            break
                elif bonus == 0.0 and abs(entry - L["price"]) <= 0.006 * price_ref:
                    bonus += w * 0.75
                    notes.append(f"ورود روی ضلعِ حمایتیِ معتبر {L['tf']}")
            else:
                if L["side"] == "lower":
                    for tgt, k in ((tp1, 1.0), (tp2, 0.5)):
                        if tgt >= entry:
                            continue
                        d = (tgt - L["price"]) / price_ref
                        if -0.02 <= d <= 0.01:
                            conflict += w * k
                            notes.append(f"هدف روی/پشت ضلعِ تست‌شدهٔ {L['tf']}")
                            break
                elif bonus == 0.0 and abs(entry - L["price"]) <= 0.006 * price_ref:
                    bonus += w * 0.75
                    notes.append(f"ورود روی ضلعِ مقاومتیِ معتبر {L['tf']}")
        delta = int(round(max(-2.0, min(2.0, bonus - conflict))))
        return (delta, " • ".join(notes[:2]))
    except Exception:
        return 0, ""


# ── prebreak previews for the scan loop ────────────────────────────────────
def send_prebreak_alerts(bundle) -> Dict[str, int]:
    settings = _s()
    counts = {"near": 0, "ready": 0, "sent": 0}
    if not getattr(settings, "technoclassic_enabled", False):
        return counts
    if not getattr(settings, "technoclassic_preview_alerts", True):
        return counts
    from data.fetcher import get_klines
    live = 0.0
    try:
        live = float((getattr(bundle, "ticker", None) or {}).get("last_price") or 0.0)
    except Exception:
        live = 0.0
    tfs = [x.strip() for x in str(getattr(settings, "technoclassic_pattern_tfs", "1h,4h,1d")).split(",")
           if x.strip() in _FIT_WINDOW]
    trig = None
    for tf in ("15m", "1h"):
        trig = bundle.get(tf)
        if trig is not None and len(trig) > 6:
            break
    if trig is None:
        try:
            trig = get_klines(str(bundle.symbol), "15m", 120)
        except Exception:
            return counts
    for pattern_tf in tfs:
        pdf = None
        try:
            pdf = get_klines(str(bundle.symbol), pattern_tf, _FIT_WINDOW.get(pattern_tf, 140) + 60,
                             closed_only=False, use_cache=False)
        except Exception:
            continue
        if pdf is None or len(pdf) < 60:
            continue
        pdf = pdf.tail(_FIT_WINDOW.get(pattern_tf, 140)).reset_index(drop=True)
        for ev in evaluate_prebreak(str(bundle.symbol), pdf, trig, pattern_tf,
                                    live_price=(live if live > 0 else None)):
            if ev.get("warn_only"):
                # Viva 09-24: violation = light warn message, no preview chain
                counts["violated"] = counts.get("violated", 0) + 1
                try:
                    from bot.messages_v7 import send_pattern_violation
                    send_pattern_violation(ev)
                except Exception as exc:
                    print(f"pattern-violation send skipped: {exc}")
                continue
            counts["near" if ev["state"] == STATE_NEAR else "ready"] += 1
            counts["sent"] += 1
            try:
                from bot.messages_v7 import send_technoclassic_preview
                send_technoclassic_preview(ev)
            except Exception as exc:
                print(f"TECHCLASSIC preview send skipped: {exc}")
    if counts["sent"]:
        print(f"📐 TECHCLASSIC previews • {bundle.symbol} near={counts['near']} ready={counts['ready']}")
    return counts
