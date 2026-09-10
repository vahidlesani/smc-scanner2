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

import threading
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import get_settings

STATE_NEAR = "EDGE_NEAR"
STATE_READY = "BREAK_READY"
STATE_BREAK = "BREAK_CLOSED"
STATE_FADE = "REJECTION_FADE"

# E&M: breaking above a resistance is the LONG event; below support the SHORT.
# Every shape alerts both edges; the pattern label only informs the caption.
_EDGE_RULES = {p: {"upper": "LONG", "lower": "SHORT"} for p in (
    "WEDGE_FALLING", "WEDGE_RISING", "TRIANGLE_ASCENDING", "TRIANGLE_DESCENDING",
    "TRIANGLE_SYMMETRICAL", "TRIANGLE", "CHANNEL_ASCENDING", "CHANNEL_DESCENDING",
    "CHANNEL_FLAT", "CHANNEL", "TRENDLINE", "HORIZONTAL_SR", "BROADENING",
)}

PATTERN_FA = {
    "WEDGE_FALLING": "گوه نزولی (فالینگ‌وج)",
    "WEDGE_RISING": "گوه صعودی (رایزینگ‌وج)",
    "TRIANGLE_ASCENDING": "مثلث صعودی",
    "TRIANGLE_DESCENDING": "مثلث نزولی",
    "TRIANGLE_SYMMETRICAL": "مثلث متقارن",
    "TRIANGLE": "مثلث",
    "CHANNEL_ASCENDING": "کانال صعودی",
    "CHANNEL_DESCENDING": "کانال نزولی",
    "CHANNEL_FLAT": "کانال افقی",
    "CHANNEL": "کانال",
    "TRENDLINE": "خط روند اصلی",
    "HORIZONTAL_SR": "سطح افقی مهم",
    "BROADENING": "مگافون گشونده",
    "HEAD_SHOULDERS": "سر و شانه (H&S)",
    "INVERSE_HEAD_SHOULDERS": "سر و شانه معکوس",
    "TRIPLE_TOP": "سقف سه‌برخوردی",
    "TRIPLE_BOTTOM": "کف سه‌برخوردی",
    "FLAG_BULL": "پرچم/کنج صعودی",
    "FLAG_BEAR": "پرچم/کنج نزولی",
}

# fit windows per timeframe — pattern must be RECENT history, not the whole archive
_FIT_WINDOW = {"1h": 200, "4h": 140, "1d": 110}

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
def classify_shape(upper, lower, n) -> str:
    """Wedge-vs-triangle honest classifier: 'flat' only when TOTAL drift is
    small vs pattern height (per-bar slope comparisons mislabel wedges)."""
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
    flat_u = drift_u <= 0.12 * width_now
    flat_l = drift_l <= 0.12 * width_now
    width_then = upper.price_at(start) - lower.price_at(start)
    converging = width_then > 0 and width_now < 0.85 * width_then
    # slope deadband: a drift under 2% of height over the span IS horizontal
    tol = 0.02 * width_now / span
    if not converging:
        if width_then > 0 and width_now > 1.18 * width_then and upper.slope > tol and lower.slope < -tol:
            return "BROADENING"          # E&M megaphone: both edges fan outward
        sgn = (upper.slope > tol) - (upper.slope < -tol)
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
        return "WEDGE_RISING"
    return "TRIANGLE"


def _line_alive(line, n) -> bool:
    """A line matters only if it was TESTED RECENTLY and spans real time
    (E&M: importance rises with time + number of reactions)."""
    try:
        if line is None or int(getattr(line, "touch_count", 0)) < 3:
            return False
        age = n - int(line.last_index)
        if age > max(6, int(0.30 * n)):          # dead edge nobody touched lately
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
        if int(recent[-1]["index"]) > n or n - int(recent[-1]["index"]) > max(6, int(0.30 * n)):
            return None  # newest pivot must be recent — no archaeology
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
                       height: float, pattern: str):
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
    _n0 = len(pattern_df) - 1
    upper = fit_edge_line(pattern_df, "HIGH", cfg, _n0)
    lower = fit_edge_line(pattern_df, "LOW", cfg, _n0)
    if upper is None and lower is None:
        return events
    n = len(pattern_df) - 1
    pattern = classify_shape(upper, lower, n)
    # Viva 2026-09-10 (doctrine): edge BOUNCE trades only inside PARALLEL
    # channels (dynamic or static). Wedges/triangles get warnings + breaks.
    is_parallel = str(pattern).upper().startswith("CHANNEL")
    rules = _EDGE_RULES.get(str(pattern).upper())
    if not rules:
        return events
    atr_p = _atr(pattern_df)
    atr_t = _atr(trigger_df) or atr_p
    if atr_p <= 0 or atr_t <= 0:
        return events
    # sanity: measured width must be a real pattern (E&M "well-formed"), not a
    # sliver nor a chart-wide absurdity
    width_now = None
    if upper is not None and lower is not None:
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
    for side, line in (("upper", upper), ("lower", lower)):
        if not _line_alive(line, n):
            continue
        direction = rules.get(side)
        if not direction:
            continue
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
        if crossed and displacement:
            state = STATE_BREAK
        elif crossed:
            state = STATE_READY
        elif dist <= 0.15:
            state = STATE_READY
        elif dist <= 1.2:
            state = STATE_NEAR
        else:
            continue
        # E&M Minimum Price Objective: pattern width projected from the edge
        if width_now is not None:
            height = width_now
        elif direction == "LONG":
            height = max(line_now - float(pattern_df["low"].iloc[max(0, n - 40):n + 1].min()), 1.5 * atr_p)
        else:
            height = max(float(pattern_df["high"].iloc[max(0, n - 40):n + 1].max()) - line_now, 1.5 * atr_p)
        height = min(height, 45.0 * atr_p)
        # ── E&M special formations & flag-pennant overlay (labels only) ─────
        pattern, struct_note = _structural_refine(pattern_df, line, side, n, height, pattern)
        _fp = _flagpole_strength(pattern_df, line, side, n, atr_p, height)
        if _fp is not None:
            pattern = "FLAG_BULL" if _fp > 0 else "FLAG_BEAR"
            struct_note = (f"میله‌ی پرچم: حرکتِ {abs(_fp)}×ATRِ بلافاصله قبل از "
                           "فشردگی — شکست در جهتِ میله ادامه‌دهنده است (ادواردز/مجی)")
        target = line_now + height if direction == "LONG" else line_now - height
        pct = (target - live) / live * 100.0 if live else 0.0
        ev = {
            "pattern": pattern, "pattern_fa": PATTERN_FA.get(pattern, pattern),
            "side": side, "direction": direction, "state": state,
            "line_price": line_now, "live": live, "distance_atr": round(abs(dist), 3),
            "touches": int(line.touch_count), "fit_error_atr": round(float(line.fit_residual_atr), 3),
            "structure_score": structure_score(line, cfg), "reactions": react,
            "measured": {"from": line_now, "to": target, "pct": round(pct, 1),
                         "height": height, "last_close": live},
            "compression": comp, "pattern_tf": pattern_tf,
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
        if fade_enabled and is_parallel and react["touches"] >= 3 \
                and abs(dist) <= 0.35 and (not crossed or rejected_now):
            fdir = "SHORT" if side == "upper" else "LONG"
            opp = lower if side == "upper" else upper
            if opp is not None and _line_alive(opp, n):
                ftgt = float(opp.price_at(n))
            else:
                ftgt = live - 1.8 * atr_p if fdir == "SHORT" else live + 1.8 * atr_p
            if fdir == "SHORT":
                stop = max(line_now, float(trigger_df["high"].iloc[-1])) + 0.35 * atr_p
                risk, rew = stop - live, live - ftgt
            else:
                stop = min(line_now, float(trigger_df["low"].iloc[-1])) - 0.35 * atr_p
                risk, rew = live - stop, ftgt - live
            if 0.15 * atr_p <= risk <= 3.0 * atr_p and rew >= 1.3 * max(risk, 1e-9):
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
    return events


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


def detect_technoclassic(bundle, style: str):
    """TECHCLASSIC live detector: only this setup issues pattern signals
    (breakouts AND confirmed edge-fades). Other setups untouched."""
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
    events = [e for e in scan_edges(pat, trig, structure_tf,
                                    live_price=(live if live > 0 else None))
              if e["state"] in (STATE_BREAK, STATE_FADE)]
    if not events:
        return None
    events.sort(key=lambda e: (e["state"] == STATE_BREAK, e["structure_score"]), reverse=True)
    fade_enabled = bool(getattr(settings, "technoclassic_fade_signals", True))
    for ev in events:
        if ev["state"] == STATE_FADE and not fade_enabled:
            continue
        candidate = _build_candidate(bundle, style, ev, pat, trig, structure_tf, trigger_tf, cfg)
        if candidate is not None:
            return candidate
    return None


def _build_candidate(bundle, style: str, ev: Dict, pat, trig, structure_tf: str,
                     trigger_tf: str, cfg):
    from analysis.indicators import structure_bias
    from analysis.models import EvidenceItem, generate_viva_public_code
    from analysis.setups_v7 import _base_candidate
    from analysis.viva_tlbreak import fit_validated_line, structure_score
    from analysis.viva_tlbreak_state import VivaTLState

    is_break = ev["state"] == STATE_BREAK
    fade = ev.get("fade") or {}
    direction = (ev["direction"] if is_break else str(fade.get("direction") or ev["direction"])).upper()
    atr_p = _atr(pat)
    atr_t = _atr(trig) or atr_p
    if atr_p <= 0 or atr_t <= 0:
        return None
    n = len(pat) - 1
    live = float(ev.get("live") or float(trig["close"].iloc[-1]))
    line_now = float(ev["line_price"])
    upper = fit_validated_line(pat, "HIGH", cfg)
    lower = fit_validated_line(pat, "LOW", cfg)
    opp = lower if direction == "LONG" else upper
    # stop = NEAREST recent opposite validated touch (never the global min/max
    # that produced Viva's absurd 74%-away shorts)
    buffer = 0.35 * atr_p
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
        final_target = float(ev["measured"]["to"])
        if stop is None:
            stop = (line_now - 1.5 * atr_p) if direction == "LONG" else (line_now + 1.5 * atr_p)
    else:
        entry = float(fade.get("entry") or live)
        final_target = float(fade.get("target") or line_now)
        stop = float(fade.get("stop") or stop or 0.0)
        if stop <= 0:
            return None
    risk = (entry - stop) if direction == "LONG" else (stop - entry)
    reward = (final_target - entry) if direction == "LONG" else (entry - final_target)
    if risk <= 0.2 * atr_p or reward <= 0:
        return None
    if risk > (2.2 * max(atr_p, abs(final_target - entry)) if is_break else 3.0 * atr_p):
        return None
    min_rr = 1.5 if is_break else 1.3
    if reward / risk < min_rr:
        return None
    poi = {"bottom": line_now - 0.15 * atr_t, "top": line_now + 0.15 * atr_t,
           "touches": int(ev.get("touches") or 0),
           "type": f"TECHNOCLASSIC {ev['pattern']} {'BREAK' if is_break else 'FADE'}"}
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
    gate = "technoclassic_break_closed" if is_break else "technoclassic_rejection_confirmed"
    candidate = _base_candidate(bundle, style, "TECHCLASSIC", direction, structure_tf,
                               trigger_tf, context, poi, impulse,
                               special, gate, True)
    if candidate is None:
        return None
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
    candidate.sl = float(stop)
    tp2 = float(final_target)
    tp1 = entry + (tp2 - entry) * 0.40 if direction == "LONG" else entry - (entry - tp2) * 0.40
    candidate.tp1 = float(tp1)
    candidate.tp2 = tp2
    rr1 = abs(tp1 - entry) / max(risk, 1e-12)
    candidate.rr_tp1 = float(rr1)
    candidate.rr_tp2 = float(reward / risk)
    squeeze = bool((ev.get("compression") or {}).get("squeeze_ok"))
    raw = float(ev.get("structure_score") or 0.0) + (2.0 if is_break else 1.0) \
        + (2.0 if squeeze else 0.0) + min(2.0, 2.0 * float(ev["reactions"]["reject_rate"])) \
        + min(2.0, 0.5 * int(ev.get("touches") or 3))
    candidate.score = min(10, max(6, int(round(raw))))
    comp_bonus, _comp = (0.0, {})
    try:
        comp_bonus, _comp = compression_bonus(pat)
    except Exception:
        pass
    candidate.mandatory_gates["htf_alignment"] = True
    candidate.strategy_fa = (f"تکنوکلاسیک | " +
                             (f"شکست {fa_pattern} در {structure_tf} — پولبک اول + BOS تأیید"
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
    return candidate


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
