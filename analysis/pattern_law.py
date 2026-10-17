"""pattern_law — the ONE reference law for chart-pattern identification (R99q21).

Viva 10-16 (verbatim): «اسپات پر از باگ است ... دلیلش این است که شرایط درست
تشخیص پترن‌ها در رندر یا انجین تشخیص پترن‌ها کد نشده ... تنها پترنی که تشخیص
میده فالینگ وج هست ... گاهی کانال یا مثلث و رایزینگ وج هم میده اما با هندسه
افتضاح و غلط .. سریعا کامل کد دقیق پترن‌ها رو بنویس .. دبل تاپ و دبل باتم و سر و
شانه رو از اون ۱۶ پترن کم بکن ... برای هرکدام به انجین رفرنس بده ... حتما یادت
باشه ما پترنی نیاز داریم که نزدیک به شکست باشه یا ابتدای شکست باشه».

Why this module exists
----------------------
Before R99q21 every lane classified a pair of fitted lines with its own ad-hoc
if-chain (render_kit.detect_patterns, pattern_engine.classify_shape,
patterns16.classify16, spot_engine side tables). Small differences between those
chains produced the symptoms he reported: the same structure labelled
FALLING_WEDGE on one chart and CHANNEL/TRIANGLE on the next, wedges with an apex
already behind the live bar, «کانال، وج شد», patterns that were TRUE but
PAST-MARKET, and an alert whose pattern changed at confirmation.

This module is the single source of truth:
  * PATTERN_LAW — 13 live patterns (double top / double bottom / head&shoulders
    are RETIRED per his instruction) each with the explicit international rule
    (Edwards & Magee, Bulkowski, Brooks) AND its numeric conditions.
  * pair_metrics() — every measurement the law needs, computed in the space the
    chart is drawn in (log when the fit is log).
  * classify_pair() — the law as CODE: families are tried in a fixed order and
    every decision is recorded with its reason (`meta["why"]`), so a wrong label
    can be traced instead of guessed.
  * near_break() — «نزدیک به شکست یا ابتدای شکست»: a pattern far past its
    breakout is not shown as a live pattern.

Nothing here places a trade; it names what the geometry IS and whether it is
still tradeable-adjacent.
"""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple

# ────────────────────────────── the law ──────────────────────────────────
# ref = the international source of the rule, kept next to the numbers so the
# code can always be audited against the book instead of against memory.
PATTERN_LAW: Dict[str, Dict] = {
    "WEDGE_FALLING": {
        "fa": "گوه نزولی", "family": "converging", "bias": "BULL", "break": "UPPER",
        "ref": "E&M Ch.7 'Wedges'; Bulkowski §Falling Wedge (breakout up ~68%)",
        "rule": "دو ضلع همگرا، هر دو شیب نزولی (لبهٔ بالا نزولِ تندتر)، ورود قیمت "
                "از بالا؛ شکست معتبر = کلوز بالای لبهٔ بالا.",
        "need": {"rel_u": (-1.0, -0.004), "rel_l": (-1.0, -0.002),
                 "conv": (0.20, 0.85), "apex": (0.0, 1.6)},
    },
    "WEDGE_RISING": {
        "fa": "گوه صعودی", "family": "converging", "bias": "BEAR", "break": "LOWER",
        "ref": "E&M Ch.7; Bulkowski §Rising Wedge (breakout down ~68%)",
        "rule": "دو ضلع همگرا، هر دو شیب صعودی (لبهٔ پایین صعودِ تندتر)، ورود قیمت "
                "از پایین؛ شکست معتبر = کلوز زیر لبهٔ پایین.",
        "need": {"rel_u": (0.002, 1.0), "rel_l": (0.004, 1.0),
                 "conv": (0.20, 0.85), "apex": (0.0, 1.6)},
    },
    "TRIANGLE_SYMMETRICAL": {
        "fa": "مثلث متقارن", "family": "converging", "bias": "NEUTRAL", "break": "ANY",
        "ref": "E&M Ch.7 'Triangles'; Bulkowski §Symmetrical Triangle",
        "rule": "لبهٔ بالا نزولی، لبهٔ پایین صعودی، همگرایی پیش‌رونده؛ جهت با کلوزِ "
                "همان ضلعی که می‌شکند تعیین می‌شود.",
        "need": {"rel_u": (-1.0, -0.003), "rel_l": (0.003, 1.0),
                 "conv": (0.20, 0.92), "apex": (0.0, 1.4)},
    },
    "TRIANGLE_ASCENDING": {
        "fa": "مثلث صعودی", "family": "converging", "bias": "BULL", "break": "UPPER",
        "ref": "Bulkowski §Ascending Triangle (upward break ~63%)",
        "rule": "لبهٔ بالا افقی (≥۲ برخورد)، لبهٔ پایین صعودی؛ شکست = کلوز بالای لبهٔ افقی.",
        "need": {"rel_u": (-0.004, 0.004), "rel_l": (0.003, 1.0),
                 "conv": (0.15, 1.05), "apex": (-0.2, 3.0)},
    },
    "TRIANGLE_DESCENDING": {
        "fa": "مثلث نزولی", "family": "converging", "bias": "BEAR", "break": "LOWER",
        "ref": "Bulkowski §Descending Triangle (downward break ~64%)",
        "rule": "لبهٔ پایین افقی (≥۲ برخورد)، لبهٔ بالا نزولی؛ شکست = کلوز زیر لبهٔ افقی.",
        "need": {"rel_u": (-1.0, -0.003), "rel_l": (-0.004, 0.004),
                 "conv": (0.15, 1.05), "apex": (-0.2, 3.0)},
    },
    "CHANNEL_ASCENDING": {
        "fa": "کانال صعودی", "family": "parallel", "bias": "BULL", "break": "ANY",
        "ref": "E&M Ch.7 'Channels'; Brooks PA Ch.12 (channel line)",
        "rule": "دو ضلع موازی صعودی (اختلاف شیب ≤ ۳۵٪)، فاصلهٔ نسبی تقریباً ثابت؛ "
                "شکست = کلوز بیرون هر لبه.",
        "need": {"rel_u": (0.004, 1.0), "rel_l": (0.004, 1.0),
                 "parallel": 0.35, "flatband": 0.35},
    },
    "CHANNEL_DESCENDING": {
        "fa": "کانال نزولی", "family": "parallel", "bias": "BEAR", "break": "ANY",
        "ref": "E&M Ch.7; Brooks PA Ch.12",
        "rule": "دو ضلع موازی نزولی (اختلاف شیب ≤ ۳۵٪)؛ شکست = کلوز بیرون هر لبه.",
        "need": {"rel_u": (-1.0, -0.004), "rel_l": (-1.0, -0.004),
                 "parallel": 0.35, "flatband": 0.35},
    },
    "RECTANGLE": {
        "fa": "مستطیل / رنج", "family": "box", "bias": "NEUTRAL", "break": "ANY",
        "ref": "E&M Ch.7 'Rectangles'; Brooks PA §Trading Range",
        "rule": "سقف و کف افقیِ چندبرخوردی (هر ضلع ≥۲ برخورد)؛ شکست = کلوز بیرون.",
        "need": {"rel_u": (-0.004, 0.004), "rel_l": (-0.004, 0.004),
                 "parallel": 1.0, "flatband": 0.40},
    },
    "FLAG_BULL": {
        "fa": "پرچم صعودی", "family": "flag", "bias": "BULL", "break": "UPPER",
        "ref": "Bulkowski §Flags (rise then small downward drift)",
        "rule": "پایهٔ صعودیِ تند (pole) و سپس کانال کوچکِ نزولی/افقی؛ شکست = کلوز "
                "بالای پرچم. طول پرچم ≤ ۴۰٪ طول پایه.",
        "need": {"rel_u": (-0.30, 0.02), "rel_l": (-0.30, 0.02),
                 "parallel": 0.6, "pole": 0.03, "pole_dir": 1, "short": 0.45},
    },
    "FLAG_BEAR": {
        "fa": "پرچم نزولی", "family": "flag", "bias": "BEAR", "break": "LOWER",
        "ref": "Bulkowski §Flags (decline then small upward drift)",
        "rule": "پایهٔ نزولیِ تند و سپس کانال کوچکِ صعودی/افقی؛ شکست = کلوز زیر پرچم.",
        "need": {"rel_u": (-0.02, 0.30), "rel_l": (-0.02, 0.30),
                 "parallel": 0.6, "pole": 0.03, "pole_dir": -1, "short": 0.45},
    },
    "PENNANT_BULL": {
        "fa": "پرچم سه‌گوش صعودی", "family": "flag", "bias": "BULL", "break": "UPPER",
        "ref": "Bulkowski §Pennants (flag with converging edges)",
        "rule": "پایهٔ صعودیِ تند + مثلث کوچکِ همگرا؛ شکست = کلوز بالای رأسِ کوچک.",
        "need": {"rel_u": (-0.30, 0.30), "rel_l": (-0.30, 0.30),
                 "conv": (0.20, 0.95), "pole": 0.03, "pole_dir": 1, "short": 0.45},
    },
    "PENNANT_BEAR": {
        "fa": "پرچم سه‌گوش نزولی", "family": "flag", "bias": "BEAR", "break": "LOWER",
        "ref": "Bulkowski §Pennants",
        "rule": "پایهٔ نزولیِ تند + مثلث کوچکِ همگرا؛ شکست = کلوز زیر رأسِ کوچک.",
        "need": {"rel_u": (-0.30, 0.30), "rel_l": (-0.30, 0.30),
                 "conv": (0.20, 0.95), "pole": 0.03, "pole_dir": -1, "short": 0.45},
    },
    "BROADENING": {
        "fa": "مگافون گشونده", "family": "diverging", "bias": "NEUTRAL", "break": "ANY",
        "ref": "E&M Ch.7 (broadening formations); Bulkowski §Broadening",
        "rule": "دو ضلع واگرا با شیب‌های مخالف؛ معامله فقط از لبه‌ها با کلوز بیرون.",
        "need": {"rel_u": (0.003, 1.0), "rel_l": (-1.0, -0.003), "expand": 1.15},
    },
    # ── non-pattern geometry (still drawn, never traded as a shape) ──
    "TRENDLINE": {
        "fa": "خط روند", "family": "single", "bias": "NEUTRAL", "break": "ANY",
        "ref": "E&M Ch.3 (trendline: ≥2 touches, same side)",
        "rule": "یک خط معتبر با ≥۲ برخورد؛ کلوز آن‌طرف = تأیید.",
        "need": {},
    },
    "CHANNEL_FLAT": {
        "fa": "کانال افقی", "family": "parallel", "bias": "NEUTRAL", "break": "ANY",
        "ref": "E&M Ch.7 (horizontal channel / range edges)",
        "rule": "دو لبهٔ افقیِ کم‌برخورد؛ معامله فقط با کلوز بیرون هر لبه.",
        "need": {"rel_u": (-0.004, 0.004), "rel_l": (-0.004, 0.004)},
    },
    "TRIANGLE": {
        "fa": "مثلث (هندسهٔ نامشخص)", "family": "converging", "bias": "NEUTRAL",
        "break": "ANY",
        "ref": "legacy bucket: two edges with no family evidence — never traded as a shape",
        "rule": "دو ضلع با جهت نامشخص؛ فقط پس از کلوز بیرون یک لبه معنا دارد.",
        "need": {},
    },
    "NONE": {"fa": "—", "family": "single", "bias": "NEUTRAL", "break": "ANY",
             "ref": "-", "rule": "هندسهٔ معتبری شناسایی نشد (بی‌ساختار).", "need": {}},
}

# his 10-16 instruction: «دبل تاپ و دبل باتم و سر و شانه رو از اون ۱۶ پترن کم بکن»
RETIRED_PATTERNS: Dict[str, str] = {
    "DOUBLE_TOP": "Viva 10-16: pivots-only trio removed from the pattern set (no reliable near-break geometry)",
    "DOUBLE_BOTTOM": "Viva 10-16: pivots-only trio removed from the pattern set",
    "HEAD_SHOULDERS": "Viva 10-16: pivots-only trio removed from the pattern set",
    "INV_HEAD_SHOULDERS": "Viva 10-16: pivots-only trio removed from the pattern set",
    "INVERSE_HEAD_SHOULDERS": "Viva 10-16: alias of the retired inverse head-and-shoulders pattern",
    "CUP_HANDLE": "Viva 10-16: pivots-only shapes removed from the pattern set",
    "INV_CUP_HANDLE": "Viva 10-16: pivots-only shapes removed from the pattern set",
}

# families in the order the law is applied (specific → general)
_FAMILY_ORDER = ("flag", "box", "converging", "parallel", "diverging")


def pattern_is_live(slug: str) -> bool:
    """True when a canonical or explicitly aliased slug may be emitted as a pattern."""
    raw = str(slug or "").strip().upper()
    if raw in RETIRED_PATTERNS:
        return False
    k = canonical_pattern_slug(raw)
    if k in RETIRED_PATTERNS:
        return False
    return k in PATTERN_LAW and PATTERN_LAW[k].get("family") not in ("single",)


# ─────────────────────── measurements (the honest numbers) ───────────────
def _price_at(line, x: float) -> Optional[float]:
    """Price of a line object at x — accepts the render dict and the fitter's
    Line (both expose the same three spellings)."""
    try:
        if line is None:
            return None
        if isinstance(line, dict):
            from analysis.render_kit import line_y
            v = float(line_y(line, x))
        else:
            v = float(line.price_at(x))
        return v if math.isfinite(v) and v > 0 else None
    except Exception:
        return None


def _per_bar(line, n: float, tail: int = 12) -> float:
    """Price change per bar over the last `tail` bars (the eye's segment)."""
    try:
        k = max(2, int(tail))
        a = _price_at(line, max(0.0, float(n) - k))
        b = _price_at(line, float(n))
        if not a or not b:
            return 0.0
        return (b - a) / float(k)
    except Exception:
        return 0.0


def _rel_drift(line, start: float, n: float) -> float:
    """Relative move of the edge across the pattern (log-safe, scale-free).

    Using (p_end/p_start - 1) instead of a raw slope is what makes the SAME
    conditions work on a 0.008-range 15m chart and a 3× range 1d chart, and on
    log-fitted and linear-fitted lines alike — the old per-bar slope thresholds
    needed a separate tuning per timeframe, which is how «کانال، وج شد»."""
    a = _price_at(line, start)
    b = _price_at(line, n)
    if not a or not b:
        return 0.0
    return (b / a) - 1.0


def pair_metrics(upper, lower, n: int, df=None, pole_bars: int = 24) -> Dict:
    """Everything the law reads, measured once, in one place."""
    m: Dict = {"ok": False}
    # one edge only = a single trendline (the legacy contract every caller
    # relies on: a lone validated line is TRENDLINE, never NONE)
    m["single"] = (upper is None) != (lower is None)
    u0, l0 = _price_at(upper, n), _price_at(lower, n)
    if u0 is None or l0 is None:
        return m
    # role sanity at the LIVE bar: the upper edge must be above (R62-ARENA P3)
    if u0 < l0:
        upper, lower = lower, upper
        u0, l0 = l0, u0
    try:
        start = max(int(getattr(upper, "first_index", 0) or 0),
                    int(getattr(lower, "first_index", 0) or 0))
    except Exception:
        start = 0
    start = max(0, min(int(start), int(n) - 2))
    span = max(1, int(n) - start)
    w_then = (_price_at(upper, start) or 0.0) - (_price_at(lower, start) or 0.0)
    w_mid = (_price_at(upper, start + span / 2) or 0.0) - (_price_at(lower, start + span / 2) or 0.0)
    w_now = float(u0) - float(l0)
    if w_then <= 0 or w_now <= 0:
        return m
    height = max(w_then, w_now)
    mid = (_price_at(upper, start) + _price_at(lower, start)) / 2.0
    m.update({
        "ok": True, "start": start, "span": span, "n": int(n),
        "width_then": w_then, "width_mid": w_mid, "width_now": w_now,
        "height": height,
        "height_rel": (height / mid) if mid else 0.0,
        "rel_u": _rel_drift(upper, start, n),
        "rel_l": _rel_drift(lower, start, n),
        "mid_rel": (mid and (w_mid / mid)) or 0.0,
        "conv_ratio": (w_now / w_then) if w_then else 1.0,
        "expand_ratio": (w_now / w_then) if w_then else 1.0,
        "touches_u": len(getattr(upper, "points", ()) or ()),
        "touches_l": len(getattr(lower, "points", ()) or ()),
        "apex": apex_position(upper, lower, start, n),
        # the TAIL (last 12 bars) is what the eye reads — r61 HYPE law: a stale
        # rally leg inflates the window drift while the edge price actually
        # tests is falling. Price-per-bar, plus the relative version.
        "tail_u": _per_bar(upper, n, 12),
        "tail_l": _per_bar(lower, n, 12),
    })
    # pole (only meaningful for flag/pennant): the run just BEFORE the pattern
    if df is not None:
        try:
            i = max(1, int(start) - 1)
            j = max(0, i - int(pole_bars))
            p0 = float(df["close"].iloc[j])
            p1 = float(df["close"].iloc[i])
            m["pole_rel"] = (p1 / p0) - 1.0 if p0 else 0.0
            hi = float(df["high"].iloc[j:i + 1].max())
            lo = float(df["low"].iloc[j:i + 1].min())
            m["pole_atr"] = (abs(p1 - p0) / max((hi - lo) / max(1, i - j), 1e-12))
        except Exception:
            m["pole_rel"] = 0.0
        # entry side: where price came IN from (close before the pattern, vs band)
        try:
            c = float(df["close"].iloc[max(0, int(start) - 1)])
            m["entry_side"] = "ABOVE" if c >= (float(mid) or c) else "BELOW"
        except Exception:
            m["entry_side"] = "ANY"
    else:
        m["pole_rel"], m["entry_side"] = 0.0, "ANY"
    return m


def apex_position(upper, lower, start: float, n: float) -> Optional[float]:
    """x where the two edges meet (bisection on the painter's own price
    functions — mode-agnostic: log and linear pairs both work)."""
    try:
        def gap(x):
            a, b = _price_at(upper, x), _price_at(lower, x)
            if a is None or b is None:
                return None
            return a - b
        g0 = gap(start)
        g1 = gap(n)
        if g0 is None or g1 is None:
            return None
        if g0 <= 0 or g1 > 0:          # not converging across the pattern
            return None
        lo, hi = float(n), float(n) + max(20.0, (n - start) * 6.0)
        g2 = gap(hi)
        if g2 is None or g2 < 0:       # already crossed before `n`?? treat as now
            return float(n)
        for _ in range(48):
            md = (lo + hi) / 2.0
            gm = gap(md)
            if gm is None:
                return None
            if gm > 0:
                lo = md
            else:
                hi = md
        return (lo + hi) / 2.0
    except Exception:
        return None


# ───────────────────────── the classifier (the law AS code) ──────────────
def _in(v: float, rng: Tuple[float, float]) -> bool:
    return rng[0] <= v <= rng[1]


def _flat(rel: float, m: Dict, tol_rel: float = 0.004) -> bool:
    """«افقی» judged against the pattern's own height (E&M: a drift under ~12%
    of the pattern height over its span IS horizontal), never an absolute slope
    — that is what makes one law work on a 0.008-range 15m chart and a 3× 1d
    chart alike."""
    band = max(float(tol_rel), 0.12 * abs(float(m.get("height_rel") or 0.0)))
    return abs(rel) <= band


def _why(meta: Dict, text: str) -> None:
    meta.setdefault("why", []).append(text)


def classify_pair(m: Dict, meta: Optional[Dict] = None) -> str:
    """The 13-pattern law. Returns the slug; `meta['why']` records every gate.

    Order matters and is fixed: flags/pennants (pole-gated) → box/rectangle →
    converging (wedges/triangles) → parallel (channels) → broadening → single.
    Every family gate reads the SAME numbers from pair_metrics, so the render,
    the spot engine and the setup engines can no longer disagree about one
    structure.
    """
    meta = meta if meta is not None else {}
    if not m.get("ok"):
        return "TRENDLINE" if m.get("single") else "NONE"
    span = int(m["span"])
    if span < 8:
        _why(meta, f"span {span} < 8")
        return "NONE"
    ru, rl = float(m["rel_u"]), float(m["rel_l"])
    conv = float(m["conv_ratio"])
    exp = float(m["expand_ratio"])
    height_rel = abs(float(m.get("height_rel") or 0.0))
    flat_u, flat_l = _flat(ru, m), _flat(rl, m)
    apx = m.get("apex")
    meta.update({"rel_u": round(ru, 6), "rel_l": round(rl, 6),
                 "conv_ratio": round(conv, 4), "flat_u": flat_u, "flat_l": flat_l,
                 "touches_u": m.get("touches_u"), "touches_l": m.get("touches_l"),
                 "entry_side": m.get("entry_side"), "apex": apx})

    # ① FLAG / PENNANT — needs a pole; the pattern must be a SHORT pause
    pole = float(m.get("pole_rel") or 0.0)
    pole_min = max(0.03, 1.2 * height_rel)
    if abs(pole) >= pole_min and span <= max(20, int(0.45 * 60)):
        short_enough = height_rel <= max(0.02, 0.45 * abs(pole))
        if short_enough:
            if pole > 0 and (flat_u or flat_l or (ru <= 0.02 and rl <= 0.02)):
                _why(meta, f"flag: pole {pole:+.2%} up, pause <=0.02 & short")
                return "PENNANT_BULL" if conv <= 0.95 else "FLAG_BULL"
            if pole < 0 and (flat_u or flat_l or (ru >= -0.02 and rl >= -0.02)):
                _why(meta, f"flag: pole {pole:+.2%} down, pause >=-0.02 & short")
                return "PENNANT_BEAR" if conv <= 0.95 else "FLAG_BEAR"

    # ② BOX / RECTANGLE — both edges horizontal, SAME drift direction (a flat
    # top with a drifting bottom is not a box), and both tested twice
    if flat_u and flat_l and (ru > 0) == (rl > 0):
        if int(m.get("touches_u") or 0) >= 2 and int(m.get("touches_l") or 0) >= 2:
            _why(meta, "rectangle: both horizontal (same drift), >=2 touches each")
            return "RECTANGLE"
        _why(meta, "both flat but a side has <2 touches -> not a box")

    # ③ CONVERGING — the wedge/triangle matrix. Evidence order: the TAILS
    # (what the eye reads on the live end, r61 HYPE law) decide the family;
    # the window drifts are the fallback; the ENTRY SIDE vetoes «rising wedge»
    # on a structure price fell into from above.
    converging = False
    if conv <= 0.92 and (m.get("width_mid", 0) or 0) < 0.97 * (m.get("width_then") or 1e9):
        same_sign = (ru > 0) == (rl > 0)
        delta = abs(abs(ru) - abs(rl)) / max(abs(ru), abs(rl), 1e-12)
        # Opposite drifts always approach. Same-sign pairs must genuinely
        # OUT-RUN each other (Δ≥15%); a hard-looking contraction (conv≤0.60)
        # still needs a real speed difference (Δ≥8%) — a thin band with equal
        # speeds yields any conv ratio from pivot noise alone, which is how a
        # parallel CHANNEL kept flipping to WEDGE («کانال، وج شد» killer).
        converging = bool((not same_sign)
                          or (conv <= 0.92 and delta >= 0.15)
                          or (conv <= 0.60 and delta >= 0.08))
        if not converging:
            _why(meta, f"conv {conv:.2f} but drifts near-parallel (Δ{delta:.2f})")
    if converging:
        if apx is not None and apx < 0.25 * span:
            _why(meta, f"apex {apx:.0f} inside the first quarter — structure spent")
            return "NONE"
        wnow = max(float(m.get("width_now") or 0.0), 1e-12)
        tol_t = 0.025 * wnow / max(1, min(12, span))
        tu = float(m.get("tail_u") or 0.0)
        tl = float(m.get("tail_l") or 0.0)
        su = (tu > tol_t) - (tu < -tol_t)
        sl = (tl > tol_t) - (tl < -tol_t)
        es = str(m.get("entry_side") or "ANY")
        meta.update({"tail_u": round(tu, 8), "tail_l": round(tl, 8),
                     "tail_sign_u": su, "tail_sign_l": sl})
        # a HORIZONTAL edge is a triangle by definition (E&M) — checked before
        # the wedge matrix, judged against the pattern's own height
        if flat_u and (sl > 0 or rl > 0.004):
            _why(meta, "horizontal top + rising bottom -> ascending triangle")
            return "TRIANGLE_ASCENDING"
        if flat_l and (su < 0 or ru < -0.004):
            _why(meta, "horizontal bottom + falling top -> descending triangle")
            return "TRIANGLE_DESCENDING"
        if su < 0 and sl < 0:
            _why(meta, "both tails falling -> falling wedge")
            return "WEDGE_FALLING"
        if su > 0 and sl > 0:
            if es == "ABOVE":
                # HYPE law: a converging structure price entered from ABOVE is a
                # top being carved — never «رایزینگ وج»; name it by the lower tail
                _why(meta, "rising tails but entered from above -> not a rising wedge")
                if tl < 0:
                    return "WEDGE_FALLING"
                if tl > 0:
                    return "TRIANGLE_SYMMETRICAL"
                return "TRIANGLE_DESCENDING"
            _why(meta, "both tails rising, entered from below -> rising wedge")
            return "WEDGE_RISING"
        if su < 0 and sl > 0:
            _why(meta, "upper tail down + lower tail up -> symmetrical")
            return "TRIANGLE_SYMMETRICAL"
        if su == 0 and sl > 0:
            _why(meta, "flat top + rising bottom -> ascending triangle")
            return "TRIANGLE_ASCENDING"
        if sl == 0 and su < 0:
            _why(meta, "flat bottom + falling top -> descending triangle")
            return "TRIANGLE_DESCENDING"
        # flat/noisy tails: fall back to the window drifts
        if ru < 0 <= rl:
            _why(meta, "window: upper down + lower up -> symmetrical")
            return "TRIANGLE_SYMMETRICAL"
        if ru <= -0.004 and rl <= -0.004:
            _why(meta, "window: both falling")
            return "WEDGE_FALLING"
        if ru >= 0.004 and rl >= 0.004:
            _why(meta, "window: both rising")
            if es == "ABOVE":
                return "WEDGE_FALLING"
            return "WEDGE_RISING"
        if flat_u and ru < -0.004:
            return "TRIANGLE_DESCENDING"
        if flat_l and rl > 0.004:
            return "TRIANGLE_ASCENDING"

    # ④ PARALLEL — channels: same sign, similar RELATIVE speed, steady band
    if (ru > 0.004 and rl > 0.004) or (ru < -0.004 and rl < -0.004):
        same_sign = (ru > 0) == (rl > 0)
        if same_sign:
            speed = min(abs(ru), abs(rl)) / max(abs(ru), abs(rl), 1e-12)
            band_ok = True
            try:
                w0, w1 = float(m["width_then"]), float(m["width_now"])
                # a band thinner than ~6% of price cannot carry a reliable
                # width ratio (pivot noise moves it 2×) — there the DRIFT
                # similarity is the parallelism evidence
                if abs(float(m.get("height_rel") or 0.0)) >= 0.06:
                    band_ok = 0.55 <= (w1 / w0) <= 1.45
            except Exception:
                pass
            if speed >= 0.62 and band_ok:
                _why(meta, f"parallel: speed ratio {speed:.2f}, band steady")
                return "CHANNEL_ASCENDING" if ru > 0 else "CHANNEL_DESCENDING"
            meta["speed_ratio"] = round(speed, 3)
            _why(meta, f"same sign but speed ratio {speed:.2f} / band {band_ok}")

    # ⑤ BROADENING — the megaphone (opposite drifts, band widening)
    if exp >= 1.15 and ru > 0.003 and rl < -0.003:
        _why(meta, f"expanding {exp:.2f} with opposite drifts")
        return "BROADENING"

    # ⑥ honest fallback — §29: a one-slope pair is NOT a channel and not a
    # named shape; the legacy generic bucket is TRIANGLE (renderer + messages
    # already treat it as «دو خط روند با هندسهٔ نامشخص»), never a guessed
    # channel direction.
    if flat_u and flat_l and abs(ru) <= 0.004 and abs(rl) <= 0.004 \
            and (ru > 0) == (rl > 0):
        _why(meta, "two truly horizontal edges -> flat band")
        return "CHANNEL_FLAT"
    if ru != 0 or rl != 0:
        _why(meta, "no family matched -> generic TRIANGLE bucket")
        return "TRIANGLE"
    _why(meta, "no family matched -> NONE")
    return "NONE"


# ─────────────────────────── near-break gate ─────────────────────────────
def near_break(upper, lower, n: int, close: float, atr: float,
               break_age: Optional[int] = None,
               fresh_bars: int = 18, max_atr: float = 4.0) -> Tuple[bool, Dict]:
    """«پترنی نیاز داریم که نزدیک به شکست باشه یا ابتدای شکست باشه».

    A pattern qualifies when:
      * price is INSIDE the band and within `max_atr` ATR of an edge
        (about to break), or
      * it broke within `fresh_bars` (the trade's opening move), or
      * `break_age` is unknown and price still hugs an edge.
    Far-past patterns (broken long ago / price many ATR away) are rejected:
    that was the «گذشته مارکت» chart he keeps seeing.
    Returns (ok, info) with the side and the distance so messages can say it.
    """
    info: Dict = {"side": None, "dist_atr": None, "state": "UNKNOWN"}
    try:
        if not atr or atr <= 0 or n is None:
            return True, info
        u = _price_at(upper, n)
        l = _price_at(lower, n)
        if u is None or l is None:
            return True, info
        du = abs(close - u) / atr
        dl = abs(close - l) / atr
        side = "UPPER" if du <= dl else "LOWER"
        info["side"] = side
        info["dist_atr"] = round(min(du, dl), 3)
        if break_age is not None and 0 <= break_age <= fresh_bars:
            info["state"] = "FRESH_BREAK"
            return True, info
        inside = l <= close <= u
        if inside and min(du, dl) <= max_atr:
            info["state"] = "AT_EDGE" if min(du, dl) <= 0.75 else "INSIDE"
            return True, info
        if inside:
            info["state"] = "FAR_INSIDE"
            return False, info
        # outside the band: a fresh break keeps it alive — and so does a
        # RETEST (price back hugging the edge it broke; his «ابتدای شکست»
        # includes the first retest, and a 0.4-ATR retest is not «گذشته
        # مارکت» — only a pattern that price has LEFT far behind is).
        if break_age is not None and 0 <= break_age <= fresh_bars:
            info["state"] = "FRESH_BREAK"
            return True, info
        if min(du, dl) <= 1.0:
            info["state"] = "RETEST"
            return True, info
        info["state"] = "STALE"
        return False, info
    except Exception:
        return True, info


# ═══════════════════════════════════════════════════════════════════════════
# R99q22 — PATTERN SELECTION LAW (his 10-17, verbatim)
# «باید پترنی انتخاب بشه که حتما قیمت ۱- داخل پترن باشه ۲- نزدیک به ضلع بالا
#  یا پایین پترن باشه ۳- در حال ریتست روی ضلع بالای پترن باشه ۴- در حال ریتست و
#  برخورد از پایین به سمت زیر ضلع پترن باشه … ۵- ضلع بالا یا پایین رو بریک کرده
#  اما در همون کندل یا چند کندل بعدش دوباره وارد پترن شده …»
#
# The seven conditions he listed are the LIFECYCLE of a live pattern, so the law
# now names the state instead of asking one yes/no question:
#
#   INSIDE            (1) price inside the pattern (still live, not left behind)
#   AT_EDGE           (1+2) inside and within `approach_atr` of an edge — the
#                     classic «نزدیک به شکست» case
#   FRESH_BREAK       the edge closed through within `fresh_bars` — his «اولین
#                     ورود ما» (the impulse entry)
#   RETEST_UPPER      (3) broke UP, price came back DOWN to the broken upper
#                     edge (break-even retest from above)
#   RETEST_LOWER      (4) broke DOWN, price came back UP to the broken lower
#                     edge / approached from below toward the underside of it
#   FAILED_BREAK      (5) the edge was pierced and price RE-ENTERED the pattern
#                     in the same candle or the next few — a trap, still live
#   STALE             price has LEFT the pattern and the break is old: the ONLY
#                     veto (his «پترن گذشته مارکت»)
#
# Single trendlines (his condition 7) are judged by trendline_state() —
# TOUCH / REJECTED / COMPRESSION / FRESH_BREAK / RETEST_BE with the trigger-TF
# candle evidence (pin-bar, doji) attached.
#
# Numeric starting points follow the engine spec he was shown (GPT-5.5 file):
# approach 0.75 ATR, close buffer 0.10 ATR, touch 0.35 ATR, retest 1.0 ATR,
# wick violation 0.65 ATR.
# ═══════════════════════════════════════════════════════════════════════════
SELECTION_STATES = ("INSIDE", "AT_EDGE", "FRESH_BREAK", "RETEST_UPPER",
                    "RETEST_LOWER", "FAILED_BREAK", "STALE")
#: every state except STALE is tradeable-adjacent
ACTIONABLE_STATES = tuple(x for x in SELECTION_STATES if x != "STALE")

APPROACH_ATR = 0.75      # «نزدیک به ضلع»
CLOSE_BUFFER_ATR = 0.10  # a break needs this much close beyond the edge
TOUCH_ATR = 0.35         # a real touch of a line
RETEST_ATR = 1.00        # a retest hugs the broken edge this closely
INSIDE_LIVE_ATR = 6.0    # deeper than this inside a band = the pattern's own
                         # height dwarfs the distance; still INSIDE (cond. 1)


def _frame_cols(df) -> Tuple[list, list, list]:
    """(closes, highs, lows) as plain lists in index space of df."""
    try:
        c = [float(v) for v in df["close"].tolist()]
        h = [float(v) for v in df["high"].tolist()]
        lo = [float(v) for v in df["low"].tolist()]
        return c, h, lo
    except Exception:
        return [], [], []


def select_state(df, upper, lower, atr: float,
                 lookback: int = 90, fresh_bars: int = 18,
                 reenter_bars: int = 3, approach_atr: float = APPROACH_ATR,
                 retest_atr: float = RETEST_ATR) -> Dict:
    """Judge WHERE price stands against a two-edge pattern.

    Returns {state, ok, side, dist_atr, break_age, retest_from, reenter,
             failed_break, why}. `ok=False` ONLY for STALE (پترن گذشته‌مارکت).
    Lenient by design: missing data or an unreadable line returns ok=True.
    """
    info: Dict = {"state": "UNKNOWN", "ok": True, "side": None,
                  "dist_atr": None, "break_age": None, "retest_from": None,
                  "reenter": False, "failed_break": False, "why": ""}
    try:
        if df is None or not atr or atr <= 0:
            return info
        n = int(len(df))
        if n < 5:
            return info
        closes, highs, lows = _frame_cols(df)
        if len(closes) != n:
            return info
        close = closes[-1]
        u = _price_at(upper, n - 1)
        l = _price_at(lower, n - 1)
        if u is None and l is None:
            return info
        if l is None:
            l = u
        if u is None:
            u = l
        if u < l:
            u, l = l, u
        du = abs(close - u) / atr
        dl = abs(close - l) / atr
        side = "UPPER" if du <= dl else "LOWER"
        info["side"] = side
        info["dist_atr"] = round(min(du, dl), 3)
        inside = (l - 1e-12) <= close <= (u + 1e-12)
        # ── walk the tail: when did each edge last close through? did price
        # come back inside right after (his condition 5)?
        i0 = max(0, n - max(10, int(lookback)))
        buf = CLOSE_BUFFER_ATR * atr
        up_age = dn_age = None
        crossings = []          # (age, side) of every edge crossing in the tail
        for x in range(n - 1, max(i0, 1) - 1, -1):
            _u = _price_at(upper, x)
            _l = _price_at(lower, x)
            _u0 = _price_at(upper, x - 1)
            _l0 = _price_at(lower, x - 1)
            if _u is None or _l is None or _u0 is None or _l0 is None:
                continue
            _c, _c0 = closes[x], closes[x - 1]
            # a BREAK is a CROSSING (he means «شکست»): the previous close was
            # not beyond the edge and this one is. Without this test a price
            # that merely STAYS above a falling edge reads as a fresh break on
            # every bar — the root of «پترن شکسته‌شده اشتباه تازه تشخیص داده شد».
            if _c > _u + buf and _c0 <= _u0 + buf:
                crossings.append((n - 1 - x, "UP"))
                if up_age is None:
                    up_age = n - 1 - x
            if _c < _l - buf and _c0 >= _l0 - buf:
                crossings.append((n - 1 - x, "DN"))
                if dn_age is None:
                    dn_age = n - 1 - x
        info["break_age"] = min([a for a in (up_age, dn_age) if a is not None],
                                default=None)
        # Every crossing is kept, not just the newest: his condition 5 asks
        # whether a break was FOLLOWED by a re-entry inside the pattern.
        for _age, _s in crossings[:8]:
            _x = n - 1 - _age
            for y in range(_x + 1, min(n, _x + 1 + reenter_bars + 1)):
                _u2 = _price_at(upper, y)
                _l2 = _price_at(lower, y)
                if _u2 is None or _l2 is None:
                    continue
                if _l2 <= closes[y] <= _u2:
                    info["reenter"] = True
                    info["failed_break"] = True
                    break
            if info["failed_break"]:
                break
        # ── the decision
        if inside:
            inside = True
            info["state"] = "AT_EDGE" if min(du, dl) <= approach_atr else "INSIDE"
            info["why"] = (f"price inside the band, {info['dist_atr']} ATR off the "
                           f"nearest edge ({side})")
            return info
        if up_age is not None and up_age <= fresh_bars:
            info["state"] = "FRESH_BREAK"
            info["retest_from"] = "ABOVE" if close > u else None
            info["why"] = f"upper edge closed through {up_age} bars ago"
            return info
        if dn_age is not None and dn_age <= fresh_bars:
            info["state"] = "FRESH_BREAK"
            info["retest_from"] = "BELOW" if close < l else None
            info["why"] = f"lower edge closed through {dn_age} bars ago"
            return info
        # price left the band — is it coming BACK to the broken edge?
        if du <= retest_atr and close > u:
            info["state"] = "RETEST_UPPER"
            info["retest_from"] = "ABOVE"
            info["why"] = (f"broke up, price back within {round(du, 2)} ATR of the "
                           f"broken upper edge (break-even pullback)")
            return info
        if dl <= retest_atr and close < l:
            info["state"] = "RETEST_LOWER"
            info["retest_from"] = "BELOW"
            info["why"] = (f"broke down, price back within {round(dl, 2)} ATR of the "
                           f"broken lower edge (break-even pullback)")
            return info
        if info["failed_break"] and min(du, dl) <= retest_atr * 2.0:
            info["state"] = "FAILED_BREAK"
            info["why"] = ("edge pierced then price re-entered the pattern within "
                           f"{reenter_bars} bars — trap, still live")
            return info
        info["state"] = "STALE"
        info["ok"] = False
        info["why"] = (f"price left the pattern ({min(du, dl):.2f} ATR off the "
                       f"nearest edge) and the break is {info['break_age']} bars old")
        return info
    except Exception as exc:
        info["why"] = f"selector error: {exc}"
        return info


def trendline_state(df, line, atr: float, lookback: int = 40,
                    fresh_bars: int = 18, touch_atr: float = TOUCH_ATR,
                    retest_atr: float = 0.60) -> Dict:
    """Condition 7 — the SINGLE-trendline lane.

    States: FRESH_BREAK · RETEST_BE (magnet back to the break-even after a
    closed breakthrough) · REJECTED (touched and closed away) · TOUCH (hugging
    the line now) · COMPRESSION (candles squeezing under/over it) · STALE.
    Also returns `role` (SUPPORT when price is above the line, RESISTANCE when
    below) and `candle` — the trigger-TF evidence (PINBAR / INV_PINBAR / DOJI).
    """
    info: Dict = {"state": "UNKNOWN", "ok": True, "role": None,
                  "dist_atr": None, "side": None, "candle": None,
                  "touches": 0, "why": ""}
    try:
        if df is None or not atr or atr <= 0 or line is None:
            return info
        n = int(len(df))
        if n < 5:
            return info
        closes, highs, lows = _frame_cols(df)
        if len(closes) != n:
            return info
        close = closes[-1]
        v = _price_at(line, n - 1)
        if v is None:
            return info
        d = (close - v) / atr
        info["dist_atr"] = round(abs(d), 3)
        info["role"] = "SUPPORT" if d >= 0 else "RESISTANCE"
        info["side"] = "LOW" if d >= 0 else "HIGH"
        # last closed candle's evidence (his pin-bar / doji clause)
        try:
            o, h, lo, c = (float(df["open"].iloc[-1]), highs[-1], lows[-1], closes[-1])
            rng = max(h - lo, 1e-12)
            body = abs(c - o)
            up_wick = h - max(o, c)
            dn_wick = min(o, c) - lo
            if body <= 0.10 * rng:
                info["candle"] = "DOJI"
            elif dn_wick >= 2.0 * max(body, 1e-12) and dn_wick >= 0.35 * rng:
                info["candle"] = "PINBAR"
            elif up_wick >= 2.0 * max(body, 1e-12) and up_wick >= 0.35 * rng:
                info["candle"] = "INV_PINBAR"
        except Exception:
            pass
        # interaction history on the line
        i0 = max(1, n - max(6, int(lookback)))
        touched = rejected = 0
        break_age = None
        for x in range(i0, n):
            vx = _price_at(line, x)
            if vx is None:
                continue
            if abs(closes[x] - vx) <= touch_atr * atr:
                touched += 1
            if x > 0:
                vp = _price_at(line, x - 1)
                if vp is not None:
                    if closes[x - 1] < vp and closes[x] > vx + CLOSE_BUFFER_ATR * atr:
                        break_age = n - 1 - x
                    if closes[x - 1] > vp and closes[x] < vx - CLOSE_BUFFER_ATR * atr:
                        break_age = n - 1 - x
        info["touches"] = touched
        for x in range(max(1, n - 6), n):
            vx = _price_at(line, x)
            if vx is None:
                continue
            wick = (highs[x] - vx) if d >= 0 else (vx - lows[x])
            if 0 <= wick <= touch_atr * 1.5 * atr and abs(closes[x] - vx) > touch_atr * atr:
                rejected += 1
        if break_age is not None and break_age <= fresh_bars:
            info["state"] = "FRESH_BREAK"
            info["why"] = f"line closed through {break_age} bars ago"
            return info
        if break_age is not None and abs(d) <= retest_atr:
            info["state"] = "RETEST_BE"
            info["why"] = ("price magnetised back to the break-even of the broken "
                           f"line ({round(abs(d), 2)} ATR) after {break_age} bars")
            return info
        if rejected >= 1 and abs(d) <= retest_atr * 2.0:
            info["state"] = "REJECTED"
            info["why"] = f"{rejected} touch-and-reject(s) on the line in the last bars"
            return info
        if abs(d) <= approach_atr_default():
            info["state"] = "TOUCH"
            info["why"] = (f"price at the line ({round(abs(d), 2)} ATR) — "
                           f"{'approaching from below' if d < 0 else 'holding above'}")
            return info
        # compression: three shrinking candles hugging the line
        if abs(d) <= 1.2:
            try:
                rs = [highs[x] - lows[x] for x in range(n - 3, n)]
                rs0 = [highs[x] - lows[x] for x in range(max(0, n - 6), n - 3)]
                if rs0 and (sum(rs) / 3.0) < 0.65 * (sum(rs0) / max(len(rs0), 1)):
                    info["state"] = "COMPRESSION"
                    info["why"] = "candles compressing against the line"
                    return info
            except Exception:
                pass
        if abs(d) <= 2.5:
            info["state"] = "NEAR"
            info["why"] = f"price {round(abs(d), 2)} ATR from the line"
            return info
        info["state"] = "STALE"
        info["ok"] = False
        info["why"] = f"price {round(abs(d), 2)} ATR from the line, no recent touch"
        return info
    except Exception as exc:
        info["why"] = f"trendline selector error: {exc}"
        return info


STATE_FA = {
    "INSIDE": "داخل پترن",
    "AT_EDGE": "نزدیک ضلع (آمادهٔ شکست)",
    "FRESH_BREAK": "شکستِ تازه",
    "RETEST_UPPER": "ریتست ضلع بالا (پولبک به بریک‌ایون)",
    "RETEST_LOWER": "ریتست ضلع پایین (پولبک به بریک‌ایون)",
    "FAILED_BREAK": "شکستِ ناموفق — قیمت داخل پترن برگشت",
    "STALE": "گذشته مارکت",
    "TOUCH": "برخورد به خط",
    "RETEST_BE": "ریتست بریک‌ایون خط",
    "REJECTED": "برخورد و رد شدن از خط",
    "COMPRESSION": "فشردگی زیر/روی خط",
    "NEAR": "نزدیک خط",
    "UNKNOWN": "نامشخص",
}
CANDLE_FA = {"PINBAR": "پین‌بار", "INV_PINBAR": "پین‌بار معکوس", "DOJI": "دوجی"}


# Detector labels are not perfectly canonical yet. Keep aliases explicit so
# a detector can retain its geometry label while still citing the correct law.
PATTERN_ALIASES: Dict[str, str] = {
    "RANGE": "RECTANGLE",
    "CHANNEL": "CHANNEL_FLAT",
}


def canonical_pattern_slug(slug: str) -> str:
    key = str(slug or "").strip().upper()
    if key in RETIRED_PATTERNS:
        return key
    return PATTERN_ALIASES.get(key, key)


def pattern_law_entry(slug: str) -> Dict:
    """Return the law for one exact selected slug, resolving only explicit aliases."""
    key = str(slug or "").strip().upper()
    if not key or key in RETIRED_PATTERNS:
        return {}
    return PATTERN_LAW.get(canonical_pattern_slug(key)) or {}


def pattern_ref_fa(slug: str) -> str:
    """Persian one-liner for an alert caption: the pattern's engine reference."""
    return str(pattern_law_entry(slug).get("ref") or "")


def engine_stamp(md: dict, df=None, setup_code: str = "") -> dict:
    """R99q23 PER-ENGINE SURGERY — every setup's own alert carries the law.

    Each engine (TECHCLASSIC / TLBREAK / ALBROX / PINVAL) calls this in its OWN
    file right after its geometry is built, so the published alert knows:
      * which slug the law sees (`law_slug`) and in which selection state it
        stands (`law_state` — the seven conditions of R99q22);
      * the pattern's ENGINE REFERENCE (`pattern_ref`, `pattern_rule_fa`) so the
        alert itself answers «برای هرکدام به انجین رفرنس بده»;
      * for a single-trendline lane: the line's own state (`line_state`) and the
        trigger-TF candle evidence (`candle_evidence` — pin bar / inverted pin
        bar / doji, his condition 7).
    Never vetoes: the publish gate is the one place that drops a candidate.
    """
    out: Dict = {"law_slug": "", "law_state": "", "pattern_ref": "",
                 "candle_evidence": "", "line_state": ""}
    try:
        if not isinstance(md, dict):
            return out
        pats = [p for p in (md.get("pattern_law_all") or md.get("render_patterns") or [])
                if isinstance(p, dict)]
        if not pats:
            md["law_state"] = md.get("law_state") or ""
            return out
        # Prefer the exact shape selected by the detector that owns this
        # candidate. A different near-break shape earlier in render_patterns
        # must never lend its reference to this setup/spot signal.
        wanted = str(md.get("selected_pattern_slug") or md.get("pattern_type")
                     or md.get("tl_pattern") or "").strip().upper()
        dom = None
        if wanted:
            wanted_canonical = canonical_pattern_slug(wanted)
            dom = next((p for p in pats
                        if str(p.get("law_slug") or p.get("type") or "").strip().upper()
                        in (wanted, wanted_canonical)), None)
            # Explicit candidate label with no matching drawn geometry is a
            # provenance mismatch. Do not silently borrow another pattern's
            # reference; leave the stamp empty for diagnosis instead.
            if dom is None:
                return out
        else:
            # Legacy candidates may omit a selected slug. Only infer a shape
            # when the renderer supplied exactly one plausible near-break
            # geometry; never choose "the first" from an ambiguous list.
            plausible = [p for p in pats
                         if p.get("near_break") is not False and p.get("lines")]
            if len(plausible) == 1:
                dom = plausible[0]
            elif len(pats) == 1:
                dom = pats[0]
            else:
                return out
        slug = str(dom.get("law_slug") or dom.get("type") or wanted or "").upper()
        out["law_slug"] = canonical_pattern_slug(slug)
        d = pattern_law_entry(slug)
        # state: take the stamped one, otherwise judge now
        st = str(dom.get("select_state") or dom.get("break_state") or "").upper()
        if st in ("", "UNKNOWN") and df is not None:
            try:
                st = str(selection_for_shape(dom, df, _atr_of(df)).get("state") or "")
            except Exception:
                st = st or ""
        out["law_state"] = st
        md["law_slug"] = canonical_pattern_slug(slug)
        md["law_state"] = st
        md["law_state_fa"] = STATE_FA.get(st, st)
        md["pattern_ref"] = d.get("ref") or ""
        md["pattern_rule_fa"] = d.get("rule") or ""
        md["pattern_bias"] = d.get("bias") or "NEUTRAL"
        md["pattern_break_side"] = d.get("break") or "ANY"
        md["pattern_type"] = slug or md.get("pattern_type")
        md["tl_pattern"] = slug or md.get("tl_pattern")
        lns = [l for l in (dom.get("lines") or []) if isinstance(l, dict)]
        if len(lns) == 1 and df is not None:
            try:
                ti = trendline_state(df, lns[0], _atr_of(df))
                md["line_state"] = str(ti.get("state") or "")
                md["line_state_fa"] = STATE_FA.get(str(ti.get("state") or ""), "")
                md["line_role"] = ti.get("role") or ""
                out["line_state"] = md["line_state"]
                if ti.get("candle"):
                    md["candle_evidence"] = ti["candle"]
                    out["candle_evidence"] = ti["candle"]
            except Exception:
                pass
        md["engine_stamp"] = {k: v for k, v in out.items()}
        md["setup_code"] = md.get("setup_code") or setup_code
        return out
    except Exception as exc:
        print(f"engine stamp warning: {exc}")
        return out


def _atr_of(df) -> float:
    """14-bar ATR of a frame (True Range mean) — local, no imports."""
    try:
        h = [float(v) for v in df["high"].tolist()][-14:]
        l = [float(v) for v in df["low"].tolist()][-14:]
        c = [float(v) for v in df["close"].tolist()]
        trs = []
        for i in range(len(h)):
            j = len(c) - len(h) + i
            pc = c[j - 1] if j > 0 else c[j]
            trs.append(max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc)))
        return sum(trs) / max(len(trs), 1)
    except Exception:
        return 0.0


def approach_atr_default() -> float:
    """The «نزدیک به ضلع» distance, overridable per deploy."""
    try:
        return float(os.getenv("VIVA_PATTERN_APPROACH_ATR", "") or APPROACH_ATR)
    except Exception:
        return APPROACH_ATR


def selection_for_shape(shape: dict, df, atr: float) -> Dict:
    """Stamp ONE render command with the R99q22 selection verdict.

    Two-edge commands (wedges / triangles / channels / flags) go through
    select_state(); a single-trendline command goes through trendline_state().
    Because his law has no veto except «پترن گذشته‌مارکت», the band's STALE is
    the only state that returns ok=False — and a single trendline is NEVER
    dropped here (the renderer keeps context lines; only its label changes).
    """
    info: Dict = {"state": "UNKNOWN", "ok": True, "dist_atr": None,
                  "side": None, "why": ""}
    try:
        if not isinstance(shape, dict):
            return info
        lns = [l for l in (shape.get("lines") or []) if isinstance(l, dict)]
        if len(lns) >= 2:
            up, lo = lns[0], lns[1]
            if str(up.get("side") or "").upper() == "LOW" and \
                    str(lo.get("side") or "").upper() == "HIGH":
                up, lo = lo, up
            info = select_state(df, up, lo, atr)
        elif len(lns) == 1:
            info = trendline_state(df, lns[0], atr)
        elif shape.get("hi") is not None and shape.get("lo") is not None:
            info = select_state(df,
                                {"slope": 0.0, "intercept": float(shape["hi"])},
                                {"slope": 0.0, "intercept": float(shape["lo"])},
                                atr)
        info["one_line"] = len(lns) == 1
        if info["one_line"]:
            # A single trendline is the chart's CONTEXT line: his condition 7
            # asks the law to NAME what price is doing with it (TOUCH /
            # REJECTED / COMPRESSION / FRESH_BREAK / RETEST_BE), never to
            # delete it — only a two-edge pattern price has LEFT is stale.
            info["ok"] = True
        return info
    except Exception as exc:
        info["why"] = f"selection error: {exc}"
        return info


def label_fa(slug: str) -> str:
    k = str(slug or "").upper()
    d = PATTERN_LAW.get(k)
    return str(d.get("fa")) if d else k.replace("_", " ")


LABEL_KEYS = ("pattern_type", "tl_pattern", "render_htf_pattern", "viva_pattern")

# the label the message layer should cite: the TRADEABLE shape first, the
# context band last (a chart with a wedge AND a range box is a WEDGE chart).
_LABEL_RANK = ("WEDGE_FALLING", "WEDGE_RISING", "TRIANGLE_ASCENDING",
               "TRIANGLE_DESCENDING", "TRIANGLE_SYMMETRICAL", "CHANNEL_ASCENDING",
               "CHANNEL_DESCENDING", "FLAG_BULL", "FLAG_BEAR", "PENNANT_BULL",
               "PENNANT_BEAR", "BROADENING", "RECTANGLE", "CHANNEL_FLAT",
               "TRIANGLE", "TRENDLINE", "RANGE")


def label_sync_on() -> bool:
    return str(os.getenv("VIVA_LAW_LABEL_SYNC", "1") or "1").strip().lower() \
        not in ("0", "false", "off", "no")


def dominant_slug(pats) -> str:
    """The one pattern a chart is ABOUT (tradeable shapes beat context bands)."""
    best, best_rank = "", len(_LABEL_RANK) + 5
    for p in (pats or []):
        if not isinstance(p, dict):
            continue
        slug = str(p.get("law_slug") or p.get("type") or "").upper()
        if not slug:
            continue
        if slug in RETIRED_PATTERNS:
            continue
        rank = _LABEL_RANK.index(slug) if slug in _LABEL_RANK else len(_LABEL_RANK)
        if p.get("near_break") is False:
            rank += len(_LABEL_RANK)          # a past-market shape never leads
        if rank < best_rank:
            best, best_rank = slug, rank
    return best


def sync_labels(md: dict, pats=None) -> str:
    """ONE chart, ONE pattern name (his 10-16 audit finding: on his own unique
    ids the first alert named one pattern, «tl_pattern» named another and the
    confirmation a third — «در زمان تایید یه چیز دیگه میده»).

    Every label key the pipeline reads (setup engine's `pattern_type`, the
    renderer's `tl_pattern` / `render_htf_pattern`, the legacy `viva_pattern`)
    is set from the LAW's dominant slug of what is actually drawn.
    """
    if not isinstance(md, dict) or not label_sync_on():
        return ""
    try:
        slug = dominant_slug(pats if pats is not None
                             else (md.get("render_patterns") or []))
    except Exception:
        slug = ""
    if not slug:
        return ""
    _keys = LABEL_KEYS
    _env = str(os.getenv("VIVA_LAW_LABEL_KEYS") or "").strip()
    if _env:
        _keys = tuple(x.strip().upper() for x in _env.split(",") if x.strip())
    for k in _keys:
        if k in md or k in ("pattern_type", "tl_pattern"):
            md[k] = slug
    try:
        md["pattern_label_fa"] = label_fa(slug)
    except Exception:
        pass
    return slug


def setup_gate_on() -> bool:
    """Per-engine law gate (his 10-16: «انجین‌های ستاپ‌ها هم جدا جدا تصحیح بکن»).
    `VIVA_SETUP_LAW_GATE=0` switches it off."""
    return str(os.getenv("VIVA_SETUP_LAW_GATE", "1") or "1").strip().lower() \
        not in ("0", "false", "off", "no")


_CONTEXT_ONLY = ("RANGE", "TRENDLINE", "NONE", "")


def real_shapes(pats) -> list:
    """The patterns a chart can be ABOUT — the context band and a lone
    trendline are geometry, not a pattern."""
    out = []
    for p in (pats or []):
        if not isinstance(p, dict):
            continue
        slug = str(p.get("law_slug") or p.get("type") or "").upper()
        if slug and slug not in _CONTEXT_ONLY:
            out.append(p)
    return out


def setup_gate(md: dict, setup_code: str = "") -> tuple:
    """R99q21 ENGINE-BY-ENGINE GATE (phase 1: the presence + freshness law).

      TECHCLASSIC : a pattern is REQUIRED — a bare band/trendline is not a TC
                    setup (his «حتی یک پترن درست نمی‌ده» + the XRP/JUP rows that
                    announced a pattern and drew none).
      TLBREAK     : the traded edge must be near its break (or freshly broken);
                    a broken-long-ago edge is history, not a trade.
      PINVAL / ALBROX / others: a pattern is optional (zone / candle-window
                    engines) — but CITING a pattern that is not drawn, or that is
                    past-market, vetoes the candidate.

    Returns (ok, reason). Env: VIVA_SETUP_LAW_GATE (default 1).
    """
    if not isinstance(md, dict) or not setup_gate_on():
        return True, "OFF"
    code = str(setup_code or md.get("setup_code") or "").upper()
    # judge on EVERY shape the law saw (drawn or gated out) — the engine must
    # not be silenced by the display gate that removed the pattern it cites.
    _all = md.get("pattern_law_all") or md.get("render_patterns")
    pats = real_shapes(_all)
    drawn = real_shapes(md.get("render_patterns"))
    cited = str(md.get("pattern_type") or md.get("viva_pattern") or "").upper()
    cited_real = bool(cited) and cited not in _CONTEXT_ONLY and cited not in RETIRED_PATTERNS
    if not pats:
        if cited_real:
            # it announced a pattern the law cannot draw for it
            return False, f"CITED-NOT-DRAWN:{cited}"
        if code == "TECHCLASSIC" and not drawn and not cited:
            return False, "TC-NO-PATTERN"
        return True, "NO-SHAPE-OK"
    fresh = [p for p in pats if p.get("near_break") is not False]
    if not fresh:
        return False, "PAST-MARKET:" + ",".join(
            f"{p.get('law_slug') or p.get('type')}/{p.get('break_state')}" for p in pats[:3])
    if cited_real and all(
            str(p.get("law_slug") or p.get("type") or "").upper() != cited for p in pats):
        # the cited engine name is nowhere on the canvas: TECHCLASSIC's whole
        # premise is that named pattern (his «حتی یک پترن درست نمی‌ده») → block;
        # a zone/candle engine is only CITING it → allow, renamed by the law.
        if code == "TECHCLASSIC":
            return False, f"CITED-NOT-DRAWN:{cited}"
        return True, f"RENAMED:{cited}->{dominant_slug(pats)}"
    return True, "OK"


def near_break_gate_on() -> bool:
    """The gate is ON by default (his 10-16: «پترن‌ها در ستاپ‌ها و اسپات هنوز هم
    گاهی گذشته مارکت هستند») — `VIVA_NEAR_BREAK_GATE=0` switches it off."""
    return str(os.getenv("VIVA_NEAR_BREAK_GATE", "1") or "1").strip().lower() \
        not in ("0", "false", "off", "no")


def gate_patterns(pats, tag: str = "") -> list:
    """Keep only patterns the law still calls actionable (near the break / at
    the start of it). A pattern far inside or long-broken is PAST-MARKET: it is
    dropped here, once, for every lane that draws or cites it."""
    out = [p for p in (pats or []) if isinstance(p, dict)]
    if not near_break_gate_on():
        return out
    kept, dropped = [], []
    for p in out:
        (dropped if p.get("near_break") is False else kept).append(p)
    if dropped:
        _why = ", ".join(f"{p.get('type')}/{p.get('break_state')}"
                         f"@{p.get('dist_atr')}" for p in dropped[:4])
        print(f"R99q21 near-break gate{(' ' + tag) if tag else ''}: "
              f"dropped {len(dropped)} past-market pattern(s) [{_why}]")
    return kept


def bias_of(slug: str) -> str:
    d = PATTERN_LAW.get(str(slug or "").upper()) or {}
    return str(d.get("bias") or "NEUTRAL")


def break_side_of(slug: str) -> str:
    d = PATTERN_LAW.get(str(slug or "").upper()) or {}
    return str(d.get("break") or "ANY")
