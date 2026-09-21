"""Canonical pattern library — every shape carries its OWN name, bias, rule and
drawing geometry (Viva 09-21/22: «هر الگویی اسم داره، قوانین خودش رو داره و
باید دقیقاً شکل خودش در چارت رسم بشه … دقیقا مثل چارتهای کریپتوکاو»).

One place defines the vocabulary so the detector, the confirmation engine, the
message text and the chart renderer can never disagree about what a shape is
called or which way it leans:

    pattern_type            canonical slug (WEDGE_FALLING …)
    pattern_fa              Persian name
    pattern_bias            BULL / BEAR / NEUTRAL (Edwards & Magee / Brooks)
    pattern_shape           how the geometry must be DRAWN:
                              "converging" — two sides meeting (wedge/triangle)
                              "parallel"   — channel/flag, constant width
                              "box"        — rectangle / range
                              "single"     — one trendline only
    pattern_rule_fa         the rule in one Persian line (what breaks it)
    break_edge / confirm    which edge confirms which direction
    measured_target()       the measured move of the shape (CryptoCove style)

Nothing here decides a trade; it only names and draws what the validated
geometry actually is.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

PATTERN_LIBRARY: Dict[str, Dict] = {
    "WEDGE_FALLING": {
        "fa": "گوه نزولی (فالینگ‌وج)", "bias": "BULL", "shape": "converging",
        "rule_fa": "دو ضلع همگرا با شیب نزولی؛ شکست و کلوز بالای ضلع بالا = برگشت صعودی، شکست زیر ضلع پایین = ادامهٔ نزولی (BREAKDOWN).",
    },
    "WEDGE_RISING": {
        "fa": "گوه صعودی (رایزینگ‌وج)", "bias": "BEAR", "shape": "converging",
        "rule_fa": "دو ضلع همگرا با شیب صعودی؛ شکست و کلوز زیر ضلع پایین = برگشت نزولی، شکست بالای ضلع بالا = ادامهٔ صعودی (BREAKOUT_UP).",
    },
    "TRIANGLE_ASCENDING": {
        "fa": "مثلث صعودی", "bias": "BULL", "shape": "converging",
        "rule_fa": "ضلع بالا افقی (مقاومت) و ضلع پایین صعودی؛ کلوز بالای ضلع افقی = تأیید صعودی.",
    },
    "TRIANGLE_DESCENDING": {
        "fa": "مثلث نزولی", "bias": "BEAR", "shape": "converging",
        "rule_fa": "ضلع پایین افقی (حمایت) و ضلع بالا نزولی؛ کلوز زیر ضلع افقی = تأیید نزولی.",
    },
    "TRIANGLE_SYMMETRICAL": {
        "fa": "مثلث متقارن", "bias": "NEUTRAL", "shape": "converging",
        "rule_fa": "دو ضلع همگرای متقارن؛ جهت با همان ضلعی که اول شکسته و کلوز می‌شود تعیین می‌شود — نه با پیش‌بینی.",
    },
    "TRIANGLE": {
        "fa": "مثلث", "bias": "NEUTRAL", "shape": "converging",
        "rule_fa": "هندسهٔ همگرا بدون تقارن کامل؛ جهت = جهت ضلع شکسته‌شده با کلوز.",
    },
    "BROADENING": {
        "fa": "مگافون گشونده", "bias": "NEUTRAL", "shape": "converging",
        "rule_fa": "دو ضلع واگرا؛ هر سمت با کلوز بیرونِ همان ضلع معتبر است (نوسان‌های بزرگ‌تر).",
    },
    "CHANNEL_ASCENDING": {
        "fa": "کانال صعودی", "bias": "BULL", "shape": "parallel",
        "rule_fa": "دو ضلع موازی صعودی؛ کلوز بالای سقف کانال = ادامهٔ صعودی، کلوز زیر کف = شکست کانال.",
    },
    "CHANNEL_DESCENDING": {
        "fa": "کانال نزولی", "bias": "BEAR", "shape": "parallel",
        "rule_fa": "دو ضلع موازی نزولی؛ کلوز زیر کف کانال = ادامهٔ نزولی، کلوز بالای سقف = شکست کانال.",
    },
    "CHANNEL_FLAT": {
        "fa": "کانال افقی", "bias": "NEUTRAL", "shape": "parallel",
        "rule_fa": "کانال افقی: معامله فقط از لبه‌ها با کلوز بیرونِ لبه.",
    },
    "CHANNEL": {
        "fa": "کانال", "bias": "NEUTRAL", "shape": "parallel",
        "rule_fa": "دو ضلع موازی؛ جهت = جهت ضلع شکسته‌شده با کلوز.",
    },
    "FLAG_BULL": {
        "fa": "پرچم صعودی", "bias": "BULL", "shape": "parallel",
        "rule_fa": "پرچم کوچک نزولیِ موازی پس از یک پایهٔ صعودی؛ کلوز بالای پرچم = ادامهٔ صعودی.",
    },
    "FLAG_BEAR": {
        "fa": "پرچم نزولی", "bias": "BEAR", "shape": "parallel",
        "rule_fa": "پرچم کوچک صعودیِ موازی پس از یک پایهٔ نزولی؛ کلوز زیر پرچم = ادامهٔ نزولی.",
    },
    "RECTANGLE": {
        "fa": "مستطیل / رنج", "bias": "NEUTRAL", "shape": "box",
        "rule_fa": "سقف و کف افقیِ چند‌برخوردی؛ کلوز بیرون هر کدام = تأیید همان سمت.",
    },
    "RANGE": {
        "fa": "رنج", "bias": "NEUTRAL", "shape": "box",
        "rule_fa": "بازهٔ افقی؛ معامله از لبه‌ها با کلوز.",
    },
    "TRENDLINE": {
        "fa": "خط روند اصلی", "bias": "NEUTRAL", "shape": "single",
        "rule_fa": "یک خط روند معتبر (≥۲ برخورد)؛ کلوز آن‌طرفِ خط = تأیید.",
    },
    "HORIZONTAL_SR": {
        "fa": "سطح افقی مهم", "bias": "NEUTRAL", "shape": "single",
        "rule_fa": "سطح افقیِ چند‌برخوردی؛ کلوز بیرون سطح = تأیید.",
    },
    "NONE": {
        "fa": "—", "bias": "NEUTRAL", "shape": "single", "rule_fa": "هندسهٔ معتبری شناسایی نشد.",
    },
}


def pattern_info(kind: str) -> Dict:
    """Name / bias / shape / rule for a slug — unknown slugs degrade to NONE."""
    k = str(kind or "").upper()
    info = PATTERN_LIBRARY.get(k)
    if info is None:
        return dict(PATTERN_LIBRARY["NONE"], key="NONE")
    return dict(info, key=k)


def pattern_fa(kind: str) -> str:
    return pattern_info(kind)["fa"]


def pattern_bias(kind: str) -> str:
    return pattern_info(kind)["bias"]


def pattern_shape(kind: str) -> str:
    return pattern_info(kind)["shape"]


def classify(upper, lower, n: int, atr: float = 0.0,
             width_history: Optional[Tuple[float, float]] = None) -> str:
    """Name the validated two-line geometry (fallback: the older classifier).

    `width_history` is (width_now, width_then) when the caller already measured
    it; otherwise the widths are computed from the lines themselves.
    """
    try:
        if upper is None and lower is None:
            return "NONE"
        if upper is None or lower is None:
            return "TRENDLINE"
        if width_history and len(width_history) == 2:
            width_now, width_then = float(width_history[0]), float(width_history[1])
        else:
            start = max(int(upper.first_index), int(lower.first_index))
            width_now = float(upper.price_at(n) - lower.price_at(n))
            width_then = float(upper.price_at(start) - lower.price_at(start))
        if width_now <= 0:
            return "NONE"
        span = max(1, int(n) - max(int(upper.first_index), int(lower.first_index)))
        # slope deadband: a drift under 2% of the height over the span is flat
        tol = 0.02 * width_now / span
        if width_then > 0 and width_now > 1.18 * width_then \
                and upper.slope > tol and lower.slope < -tol:
            return "BROADENING"
        # flags: a SHORT parallel channel that retraces a pole (Brooks)
        if atr > 0 and span <= 60 and width_then > 0:
            _w_ratio = width_now / width_then
            if 0.75 <= _w_ratio <= 1.25:
                _su, _sl = float(upper.slope), float(lower.slope)
                if _su < -tol and _sl < -tol and abs(upper.slope - lower.slope) <= tol:
                    return "FLAG_BULL"      # a downward parallel channel = bull flag
                if _su > tol and _sl > tol and abs(upper.slope - lower.slope) <= tol:
                    return "FLAG_BEAR"
        converging = width_then > 0 and width_now < 0.85 * width_then
        if not converging:
            sgn = (upper.slope > tol) - (upper.slope < -tol)
            return ("CHANNEL_ASCENDING" if sgn > 0
                    else "CHANNEL_DESCENDING" if sgn < 0 else "CHANNEL_FLAT")
        drift_u = abs(float(upper.slope)) * span
        drift_l = abs(float(lower.slope)) * span
        flat_u = drift_u <= 0.12 * width_now
        flat_l = drift_l <= 0.12 * width_now
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
    except Exception:
        return "NONE"


def measured_target(kind: str, price: float, upper=None, lower=None,
                    n: int = 0, direction: str = "LONG") -> float:
    """The shape's own measured move (height projected from the live price)."""
    try:
        height = 0.0
        if upper is not None and lower is not None:
            height = abs(float(upper.price_at(n)) - float(lower.price_at(n)))
        if height <= 0:
            return float(price)
        return float(price) + height if str(direction).upper() == "LONG" else float(price) - height
    except Exception:
        return float(price)


def state_label(kind: str, break_direction: str = "") -> str:
    """«الگوی صعودی که به پایین شکسته» is not a bullish reversal — it is a
    BREAKDOWN of that pattern and must say so (Viva 09-21 rule)."""
    k = str(kind or "").upper() or "NONE"
    b = str(break_direction or "").upper()
    if not b:
        return k
    bias = pattern_bias(k)
    if b == "DOWN" and bias == "BULL":
        return f"{k} · BREAKDOWN"
    if b == "UP" and bias == "BEAR":
        return f"{k} · BREAKOUT_UP"
    return k


def describe_fa(kind: str, break_direction: str = "") -> str:
    """One message-ready Persian line: name + the rule it obeys."""
    info = pattern_info(kind)
    _state = state_label(kind, break_direction)
    if _state != info["key"]:
        return f"{info['fa']} — {info['rule_fa']} (وضعیت فعلی: {_state})"
    return f"{info['fa']} — {info['rule_fa']}"
