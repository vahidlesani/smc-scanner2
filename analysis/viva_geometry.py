"""viva_geometry — هستهٔ واحد و پایدار هندسهٔ الگوها (اسپات + پرپچوآل).

قانون صفر: هیچ عددی اینجا بدون تأیید ویوا «قانون» نمی‌شود؛ این ماژول فقط
هندسه را نام می‌برد، اندازه می‌گیرد و چرخهٔ شکست را ثبت می‌کند. معامله با
لایه‌های engine_spot / engine_perp است.

اصول سخت این هسته (مرحلهٔ ۱، تأییدشده ۲۰۲۶-۱۰-۱۲):
  * همهٔ هندسه در ln(price) — محور همیشه لگاریتمی.
  * مختصات زمانی پایدار: برش lookback ایندکس صفر نمی‌سازد؛ offset جهانی حفظ می‌شود.
  * پیوت پایانِ بدون تأیید راست، «تأییدنشده» است و هرگز لنگر خط نمی‌شود.
  * ویک اسپایک (≥۲×میانهٔ ویک و ≥۱×ATR) از لنگرها حذف می‌شود (r58 hybrid).
  * خطوط همگرا هرگز پس از برشِ عرض، «مثلث» نام نمی‌گیرند: w1>0 سخت.
  * مثلث متقارن: نسبت شیب دو ضلع در [0.4, 2.5].
  * موازی‌بودن با اختلاف نسبی شیب‌ها سنجیده می‌شود نه فقط نسبت عرض.
  * مستطیل: هر دو ضلع مستقلأ افقی؛ کانالِ افقی فقط وقتی قطب/پایه نباشد.
  * پایهٔ ورود = قوی‌ترین حرکت جهت‌دار معتبرِ پیش از الگو (نه صرفاً آخرین پیوت).
  * چرخهٔ شکست رویدادمحور: اولین عبورِ کلوز، ماندگاری، فیک (برگشت به داخلِ
    هر دو ضلع)، ریتست، ابطال — با ایندکس رویداد، نه «۴ کندل آخر».
  * بایاس هندسه جدا از کیفیت کندل شکست (بروکس: STRONG/OK/WEAK/CLIMAX).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

UP, DOWN, NONE = "UP", "DOWN", "NONE"

# ── آستانه‌های هندسه (همه قابل کالیبراسیون با نمونهٔ برچسب‌خوردهٔ ویوا) ──
FLAT_TOL = 0.15            # |drift| نرمال‌شده ≤ ۱۵٪ ارتفاع = ضلع افقی
CONVERGE_CORE, CONVERGE_EDGE = 0.70, 0.76
PARALLEL_LO, PARALLEL_HI = 0.85, 1.18
DIVERGE_EDGE, DIVERGE_CORE = 1.30, 1.40
PARALLEL_SLOPE_TOL = 0.30  # اختلاف نسبی شیب دو ضلع برای «موازی»
SYM_SLOPE_RATIO = (0.4, 2.5)
CHANNEL_SLOPE_TOL = 0.45   # کانال: اختلاف نسبی شیب تا این حد مجاز
MIN_HEIGHT_ATR = 2.0
MIN_PATTERN_BARS = 14
MIN_TOUCHES = {"converging": 4, "diverging": 4, "parallel": 4, "box": 4,
               "flag": 4, "pivot": 3}
TOUCH_TOL_ATR = 0.45
CLOSE_VIOL_ATR = 0.25
WICK_VIOL_ATR = 0.9
WICK_VIOL_MAX = 3
ZIGZAG_ATR = 2.0
MIN_TOUCH_GAP = 5
LEG_MIN_ATR = 3.0
LEG_LOOKBACK = 80
BREAK_TOL_ATR = 0.10
FALSE_RETURN_BARS = 3

# تعداد کندل قاب به تفکیک TF (قانون r57 + رنج r65 برای اینترادِی)
TF_VIEW_BARS = {"15m": 200, "30m": 200, "1h": 200, "2h": 200,
                "4h": 170, "8h": 170, "12h": 210, "1d": 210, "3d": 300, "1w": 210}
TF_MINUTES = {"15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "8h": 480,
              "12h": 720, "1d": 1440, "3d": 4320, "1w": 10080}
RIGHT_PROJ = 0.22          # فضای داخلی سمت راست برای باکس هدف (مثل رفرنس)
LEFT_PAD_MIN = 0.14
MAX_FILL = 0.85            # کندل‌ها ≤ ۸۵٪ ارتفاع محور (مگر الگوی قطری)


# ═══════════════════════════ ابزار log ═══════════════════════════
def log_ohlc(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    bad = df[["open", "high", "low", "close"]].astype(float)
    if (bad.values <= 0).any() or np.isnan(bad.values).any():
        raise ValueError("OHLC نامعتبر: صفر/منفی/NaN در داده")
    return {k: np.log(bad[k].to_numpy()) for k in ("open", "high", "low", "close")}


def atr_log(L: Dict[str, np.ndarray], k: int = 14) -> float:
    h, l, c = L["high"], L["low"], L["close"]
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    if len(tr) < k:
        return float(np.median(tr)) or 1e-9
    # میانهٔ خام TR (نه میانگین متحرک): به ویک پرت/اسپایک کاملاً مقاوم (r58)
    return float(np.median(tr)) or 1e-9


def spike_mask(L: Dict[str, np.ndarray], atr: float) -> np.ndarray:
    """r58 hybrid: ویک اکسترم (≥۲×میانهٔ ویک‌ها و ≥۱×ATR) اسپایک است؛ از لنگر حذف
    می‌شود ولی در رسم دیده می‌شود."""
    wick_up = L["high"] - np.maximum(L["open"], L["close"])
    wick_dn = np.minimum(L["open"], L["close"]) - L["low"]
    wick = np.maximum(wick_up, wick_dn)
    med = float(np.median(wick)) or 1e-9
    return (wick >= 2.0 * med) & (wick >= 1.0 * atr)


@dataclass(frozen=True)
class Line:
    slope: float
    intercept: float
    side: str = ""
    touches: Tuple[int, ...] = ()
    first_index: int = 0

    def at(self, x: float) -> float:
        return self.slope * x + self.intercept

    def price_at(self, x: float) -> float:
        return math.exp(self.at(x))


@dataclass
class Leg:
    direction: str = NONE
    move: float = 0.0
    bars: int = 0
    start_index: int = -1
    end_price_log: float = 0.0


@dataclass
class PatternResult:
    slug: str
    upper: Line
    lower: Line
    x0: int
    x1: int
    score: float
    leg: Leg
    meta: Dict
    outlook: Dict = field(default_factory=dict)
    kind: str = "two_line"          # two_line | pivot_pattern
    neckline: Optional[Line] = None


# ═══════════════════════════ پیوت‌ها ═══════════════════════════
def zigzag_pivots(L: Dict[str, np.ndarray], atr: float, k: int = 3,
                  confirmed_only: bool = True,
                  spikes: Optional[np.ndarray] = None) -> List[Dict]:
    """پیوت‌های تأییدشده با نوسان ≥ ZIGZAG_ATR؛ پیوت انتهایی بدون k کندل تأییدِ
    راست، confirmed=False و اگر confirmed_only باشد حذف می‌شود. اسپایک‌ها لنگر
    نمی‌شوند (از high/low به بدنهٔ معادل تنزل می‌یابند)."""
    h, l = L["high"].copy(), L["low"].copy()
    n = len(h)
    piv: List[Dict] = []
    for i in range(k, n - k):
        win_h, win_l = h[i - k:i + k + 1], l[i - k:i + k + 1]
        if h[i] >= win_h.max() and (h[i] - win_l.min()) >= ZIGZAG_ATR * atr:
            if piv and piv[-1]["kind"] == "H":
                if h[i] > piv[-1]["price"]:
                    piv[-1] = {"index": i, "price": float(h[i]), "kind": "H", "confirmed": True}
            elif not piv or piv[-1]["index"] < i:
                piv.append({"index": i, "price": float(h[i]), "kind": "H", "confirmed": True})
        elif l[i] <= win_l.min() and (win_h.max() - l[i]) >= ZIGZAG_ATR * atr:
            if piv and piv[-1]["kind"] == "L":
                if l[i] < piv[-1]["price"]:
                    piv[-1] = {"index": i, "price": float(l[i]), "kind": "L", "confirmed": True}
            elif not piv or piv[-1]["index"] < i:
                piv.append({"index": i, "price": float(l[i]), "kind": "L", "confirmed": True})
    # پیوت انتهاییِ در حال شکل‌گیری (بدون k تأیید راست) — فقط مشاهده، نه لنگر
    if piv and n - 1 > piv[-1]["index"]:
        t0 = piv[-1]["index"] + 1
        if piv[-1]["kind"] == "H":
            cand = int(np.argmin(l[t0:n])) + t0
            if n - 1 - cand >= 1 and (h[max(t0, cand - k):min(n, cand + k + 1)].max() - l[cand]) >= ZIGZAG_ATR * atr \
               and l[cand] <= l[t0:n].min():
                piv.append({"index": cand, "price": float(l[cand]), "kind": "L", "confirmed": False})
        else:
            cand = int(np.argmax(h[t0:n])) + t0
            if n - 1 - cand >= 1 and (h[cand] - l[max(t0, cand - k):min(n, cand + k + 1)].min()) >= ZIGZAG_ATR * atr \
               and h[cand] >= h[t0:n].max():
                piv.append({"index": cand, "price": float(h[cand]), "kind": "H", "confirmed": False})
    # r58 hybrid — نسخهٔ پایدار: ویکِ پیوت فقط وقتی اسپایک است که نسبت به ویکِ
    # سایر پیوت‌های همان سمت پرت باشد (≥۳×میانهٔ ویک پیوت‌ها و ≥۱×ATR)؛ در آن صورت
    # لنگر به بدنه تنزل می‌کند. تماس‌های مشروع الگو دست‌نخورده می‌مانند.
    body_hi = np.maximum(L["open"], L["close"])
    body_lo = np.minimum(L["open"], L["close"])
    for kind, body in (("H", body_hi), ("L", body_lo)):
        ps = [p for p in piv if p["kind"] == kind]
        if len(ps) < 3:
            continue
        wicks = np.array([abs(p["price"] - float(body[p["index"]])) for p in ps])
        med = float(np.median(wicks)) or 1e-9
        for p, wk in zip(ps, wicks):
            if wk >= 3.0 * med and wk >= 1.0 * atr:
                p["price"] = float(body[p["index"]])
                p["spike_adj"] = True
    if confirmed_only:
        piv = [p for p in piv if p["confirmed"]]
    return piv


# ═══════════════════════════ اندازه و اعتبار ═══════════════════════════
def measure(upper: Line, lower: Line, x0: int, x1: int) -> Optional[Dict]:
    span = max(1, x1 - x0)
    w0 = upper.at(x0) - lower.at(x0)
    w1 = upper.at(x1) - lower.at(x1)
    wm = upper.at(x0 + span // 2) - lower.at(x0 + span // 2)
    hmax = max(w0, w1, wm)
    if hmax <= 0 or w0 <= 0 or w1 <= 0:      # خطوط متقاطع = الگوی نامعتبر
        return None
    du = upper.slope * span / hmax
    dl = lower.slope * span / hmax
    apex = None
    if lower.slope > upper.slope:
        apex = w1 / (lower.slope - upper.slope)
    return {"span": span, "w0": w0, "w1": w1, "ratio": w1 / w0, "hmax": hmax,
            "du": du, "dl": dl, "su": _sign(du), "sl": _sign(dl),
            "apex_bars": apex, "slope_gap": abs(du - dl)}


def _sign(d: float) -> int:
    return 0 if abs(d) <= FLAT_TOL else (1 if d > 0 else -1)


def classify_geometry(upper: Line, lower: Line, x0: int, x1: int,
                      leg: Optional[Leg] = None, atr: float = 0.0,
                      flag_stats: Optional[Dict] = None) -> Tuple[str, Dict]:
    """اسم فقط از هندسه؛ سمت ورود اسم را عوض نمی‌کند (نقش را تعیین می‌کند)."""
    leg = leg or Leg()
    m = measure(upper, lower, x0, x1)
    if m is None:
        return "NONE", {"reason": "عرض نامعتبر/خطوط متقاطع"}
    meta = dict(m)
    meta["leg"] = leg
    if atr and m["hmax"] < MIN_HEIGHT_ATR * atr:
        return "NONE", dict(meta, reason="ارتفاع کمتر از ۲×ATR")
    if m["span"] < MIN_PATTERN_BARS:
        return "NONE", dict(meta, reason="کوتاه‌تر از حداقل کندل")

    r, su, sl = m["ratio"], m["su"], m["sl"]
    du, dl, gap = m["du"], m["dl"], m["slope_gap"]
    slug, fam, conf = "NONE", "", 1.0

    if r <= CONVERGE_EDGE:
        fam = "converging"
        conf = 1.0 if r <= CONVERGE_CORE else 0.6
        if su == 0 and sl > 0:
            slug = "TRIANGLE_ASCENDING"
        elif sl == 0 and su < 0:
            slug = "TRIANGLE_DESCENDING"
        elif su < 0 < sl:
            lo, hi = SYM_SLOPE_RATIO
            ratio = abs(du) / max(abs(dl), 1e-9)
            if lo <= ratio <= hi:
                slug = "TRIANGLE_SYMMETRICAL"
            else:
                return "NONE", dict(meta, reason="نسبت شیب مثلث متقارن خارج از [0.4,2.5]")
        elif su < 0 and sl < 0:
            slug = "WEDGE_FALLING"
        elif su > 0 and sl > 0:
            slug = "WEDGE_RISING"
    elif r >= DIVERGE_EDGE:
        fam = "diverging"
        conf = 1.0 if r >= DIVERGE_CORE else 0.6
        if su > 0 and sl < 0:
            slug = "BROADENING"
        elif su > 0 and sl == 0:
            slug = "BROADENING_WEDGE_ASC"
        elif su == 0 and sl < 0:
            slug = "BROADENING_WEDGE_DESC"
        elif su > 0 and sl > 0:
            slug = "CHANNEL_ASCENDING_BROAD"
        elif su < 0 and sl < 0:
            slug = "CHANNEL_DESCENDING_BROAD"
    else:
        fam = "parallel"
        truly_parallel = gap <= PARALLEL_SLOPE_TOL
        conf = 1.0 if (PARALLEL_LO <= r <= PARALLEL_HI and truly_parallel) else 0.6
        if not truly_parallel and (r < PARALLEL_LO or r > PARALLEL_HI):
            return "NONE", dict(meta, reason="نیمه‌همگرا/نیمه‌واگرا؛ موازی نیست")
        both_flat = abs(du) <= FLAT_TOL and abs(dl) <= FLAT_TOL
        if both_flat:
            if leg.direction != NONE and flag_stats and flag_stats.get("is_flag"):
                fam, slug = "flag", "FLAG_BULL" if leg.direction == UP else "FLAG_BEAR"
            elif leg.direction != NONE:
                slug = "RECTANGLE_BULL" if leg.direction == UP else "RECTANGLE_BEAR"
            else:
                slug = "CHANNEL_FLAT"
        elif du > 0 and dl > 0 and gap <= CHANNEL_SLOPE_TOL:
            slug = "CHANNEL_ASCENDING"
        elif du < 0 and dl < 0 and gap <= CHANNEL_SLOPE_TOL:
            slug = "CHANNEL_DESCENDING"
        elif abs(du) <= FLAT_TOL or abs(dl) <= FLAT_TOL:
            slug = "TRIANGLE_ASCENDING" if (abs(du) <= FLAT_TOL and dl > 0) else \
                   "TRIANGLE_DESCENDING" if (abs(dl) <= FLAT_TOL and du < 0) else "NONE"
        else:
            return "NONE", dict(meta, reason="شیب‌های ناسازگار با خانوادهٔ موازی")

    if slug == "NONE":
        return "NONE", dict(meta, reason="ترکیب شیب/همگرایی ناسازگار")
    # پرچم/پنتت: قطب الزامی
    if flag_stats and leg.direction != NONE:
        if slug in ("RECTANGLE_BULL", "RECTANGLE_BEAR") and flag_stats.get("is_flag"):
            slug = "FLAG_BULL" if leg.direction == UP else "FLAG_BEAR"
        if slug in ("CHANNEL_ASCENDING", "CHANNEL_DESCENDING") and flag_stats.get("is_pennant"):
            slug = "PENNANT_BULL" if leg.direction == UP else "PENNANT_BEAR"
    meta.update(family=fam, geometry_confidence=conf)
    return slug, meta


# ═══════════════════════════ پایهٔ ورود ═══════════════════════════
def entry_leg(L: Dict[str, np.ndarray], pivots: Sequence[Dict], x0: int,
              atr: float, height: float = 0.0) -> Leg:
    """قوی‌ترین حرکت جهت‌دار معتبر پیش از شروع الگو (نه صرفاً آخرین پیوت)."""
    thr = max(LEG_MIN_ATR * atr, 0.5 * height)
    best: Optional[Leg] = None
    for p in pivots:
        if p["index"] >= x0 or x0 - p["index"] > LEG_LOOKBACK:
            continue
        seg = slice(p["index"], x0 + 1)
        if p["kind"] == "L":
            move, d = float(L["high"][seg].max()) - p["price"], UP
        else:
            move, d = p["price"] - float(L["low"][seg].min()), DOWN
        if move < thr:
            continue
        if best is None or move > best.move:
            best = Leg(d, move, int(x0 - p["index"]), int(p["index"]),
                       float(L["high"][seg].max()) if d == UP else float(L["low"][seg].min()))
    return best or Leg()


def flag_stats_for(L: Dict[str, np.ndarray], leg: Leg, x0: int, x1: int,
                   height: float, atr: float) -> Dict:
    if leg.direction == NONE or height <= 0:
        return {"is_flag": False, "is_pennant": False}
    pole_ok = leg.move >= 2.0 * height and leg.move >= POLE_MIN_ATR * atr
    span = max(1, x1 - x0)
    len_ok = span <= 1.2 * max(leg.bars, 1)
    seg = slice(max(0, leg.start_index), x0 + 1)
    if leg.direction == UP:
        retrace = (leg.end_price_log - float(L["low"][seg].min())) / leg.move
    else:
        retrace = (float(L["high"][seg].max()) - leg.end_price_log) / leg.move
    ok = pole_ok and len_ok and retrace <= 0.50
    return {"is_flag": ok, "is_pennant": ok, "pole": leg.move, "retrace": retrace}


POLE_MIN_ATR = 3.0


# ═══════════════════════════ فیت دوخطی ═══════════════════════════
def _fit_line(xs: np.ndarray, ys: np.ndarray, side: str, touches: Sequence[int],
              first_index: int) -> Line:
    if len(xs) >= 2:
        sl, ic = np.polyfit(xs, ys, 1)
    else:
        sl, ic = 0.0, float(ys[0])
    return Line(float(sl), float(ic), side, tuple(touches), first_index)


def _side_lines(L: Dict[str, np.ndarray], pivots: Sequence[Dict], side: str,
                atr: float, n: int, spikes: Optional[np.ndarray] = None,
                max_cand: int = 10) -> List[Line]:
    want = "H" if side == "upper" else "L"
    vals = L["high"] if side == "upper" else L["low"]
    pts = [p for p in pivots if p["kind"] == want and p["confirmed"]]
    out: List[Line] = []
    if len(pts) < 2:
        return out
    scores = []
    for a in range(len(pts)):
        for b in range(a + 1, len(pts)):
            p, q = pts[a], pts[b]
            if q["index"] - p["index"] < MIN_TOUCH_GAP:
                continue
            sl = (q["price"] - p["price"]) / (q["index"] - p["index"])
            ic = p["price"] - sl * p["index"]
            ln = np.arange(n)
            lv = sl * ln + ic
            dev = vals - lv
            # پنجرهٔ شکست: از نخستین اندیسی که کلوزها تا انتهای چارت یک‌کاسه بیرون
            # خط مانده‌اند به بعد، «شکست زنده» است نه خطای فیت (detect-then-breakout)
            cs = L["close"]
            j = n
            if side == "upper":
                while j > p["index"] + 1 and cs[j - 1] > lv[j - 1] + CLOSE_VIOL_ATR * atr:
                    j -= 1
            else:
                while j > p["index"] + 1 and cs[j - 1] < lv[j - 1] - CLOSE_VIOL_ATR * atr:
                    j -= 1
            tail_cut = j
            if side == "upper":
                close_out = int(np.sum(L["close"][p["index"]:tail_cut] > lv[p["index"]:tail_cut] + CLOSE_VIOL_ATR * atr))
                wick_out = int(np.sum(dev[p["index"]:tail_cut] > WICK_VIOL_ATR * atr))
            else:
                close_out = int(np.sum(L["close"][p["index"]:tail_cut] < lv[p["index"]:tail_cut] - CLOSE_VIOL_ATR * atr))
                wick_out = int(np.sum(dev[p["index"]:tail_cut] < -WICK_VIOL_ATR * atr))
            if close_out > 0 or wick_out > WICK_VIOL_MAX:
                continue
            touch = [t["index"] for t in pts
                     if abs(t["price"] - (sl * t["index"] + ic)) <= TOUCH_TOL_ATR * atr]
            if len(touch) < 2 or p["index"] not in touch or q["index"] not in touch:
                continue
            span = q["index"] - p["index"]
            # پاداش تازگیِ تماس تا انتخابِ خط با برش تاریخچه پایدار بماند
            scores.append((len(touch) ** 2 * span + 4.0 * max(touch), p, q, sl, ic, touch))
    scores.sort(key=lambda t: -t[0])
    for _, p, q, sl, ic, touch in scores[:max_cand]:
        out.append(_fit_line(np.array([t["index"] for t in pts if t["index"] in touch]),
                             np.array([t["price"] for t in pts if t["index"] in touch]),
                             side, touch, p["index"]))
    return out


def _shift(ln: Line, off: int) -> Line:
    return Line(ln.slope, ln.intercept - ln.slope * off, ln.side,
                tuple(t + off for t in ln.touches), ln.first_index + off)


def fit_patterns(df: pd.DataFrame, offset: int = 0, lookback: Optional[int] = None,
                 max_results: int = 6) -> List[PatternResult]:
    """کشف دوخطی پایدار: برش lookback فقط پنجرهٔ تحلیل است؛ offset ایندکس جهانی
    را حفظ می‌کند تا خطوط با تغییر زوم/TF جابه‌جا نشوند."""
    if lookback is not None and lookback < len(df):
        offset += len(df) - lookback
        df = df.tail(lookback).reset_index(drop=True)
    L = log_ohlc(df)
    n = len(df)
    if n < 30:
        return []
    atr = atr_log(L)
    sp = spike_mask(L, atr)
    piv = zigzag_pivots(L, atr, spikes=sp, confirmed_only=True)
    ups = _side_lines(L, piv, "upper", atr, n)
    lows = _side_lines(L, piv, "lower", atr, n)
    results: List[PatternResult] = []
    for u_l in ups:
        for lo_l in lows:
            u, lo = _shift(u_l, offset), _shift(lo_l, offset)
            if u.first_index >= offset + n - 8 or lo.first_index >= offset + n - 8:
                continue
            x0 = max(u.first_index, lo.first_index)
            x1 = offset + n - 1
            if x1 - x0 < MIN_PATTERN_BARS:
                continue
            m = measure(u, lo, x0, x1)
            if m is None:
                continue
            leg = entry_leg(L, piv, x0 - offset, atr, m["hmax"])
            # R99q: flag_stats index into L (the TRIMMED frame) — it must get
            # LOCAL coords; the global conversion below is for the result only.
            # (Latent crash found when engine_spot gained its own lookback.)
            _leg_local = leg
            if leg.direction != NONE:
                leg = Leg(leg.direction, leg.move, leg.bars,
                          leg.start_index + offset, leg.end_price_log)
            fs = flag_stats_for(L, _leg_local, x0 - offset, x1 - offset,
                                m["hmax"], atr)
            slug, meta = classify_geometry(u, lo, x0, x1, leg, atr, fs)
            if slug == "NONE":
                continue
            fam = meta["family"]
            need = MIN_TOUCHES["flag" if slug.startswith(("FLAG", "PENNANT")) else
                             ("box" if slug.startswith("RECT") else fam)]
            if len(u.touches) + len(lo.touches) < need:
                continue
            last_touch = max(list(u.touches) + list(lo.touches))
            if last_touch < offset + n - max(8, int(0.35 * (n - (x0 - offset)))):
                continue
            # کلوزها تا n-1 نباید بیرون باند باشند مگر در پنجرهٔ شکستِ اخیر
            out = _outside_closes(L, _shift(u, -offset), _shift(lo, -offset),
                                  x0 - offset, n, atr, allow_break_tail=True)
            if out > WICK_VIOL_MAX:
                continue
            # پاداشِ تازگی: ساختارِ زندهٔ سمت راست بر الگوهای بایگانی‌شدهٔ چپ اولویت
            # دارد تا با تغییر زوم/تاریخچه، انتخابِ الگو پایدار بماند
            # R99q (Viva 10-15): «بهترین پترن» = الگویی که هر دو ضلعش تا لبهٔ
            # لایو زنده است. پاداش فقط به الگویی که هر دو ضلعش ≥۳ پیوت دارد و
            # ضلع ضعیفش تازه است (الگوهای نیمه‌مرده با یک ضلع ۶۰ کندل عقب و
            # خط‌های دو-تاچِ چسبیده به نوک کندلِ لایو از صدر می‌افتند).
            # (پاداش فقط تابع خودِ الگوست — x0/x1 — نه طول فریم؛ پس با رسیدن
            # کندل زنده یا برش زوم، رتبهٔ برنده جابه‌جا نمی‌شود.)
            _fresh = 0.0
            _span9 = max(1, x1 - x0)
            if len(u.touches) >= 3 and len(lo.touches) >= 3:
                _weak = min(max(list(u.touches) or [0]), max(list(lo.touches) or [0]))
                if _weak >= x0 + 0.75 * _span9:
                    _fresh = 2.5
            score = (2.0 * (len(u.touches) + len(lo.touches))
                     + 0.02 * min(n - x0, 160) + 0.10 * last_touch
                     + _fresh
                     + 3.0 * meta["geometry_confidence"] - 20.0 * out)
            res = PatternResult(slug, u, lo, x0, x1, float(score), leg, meta)
            res.outlook = both_sides(slug, leg.direction)
            results.append(res)
    results.sort(key=lambda r: -r.score)
    dedup: List[PatternResult] = []
    for r in results:
        if any(o.slug == r.slug and abs(o.x0 - r.x0) <= 6 for o in dedup):
            continue
        dedup.append(r)
    return dedup[:max_results]


def _outside_closes(L, u: Line, lo: Line, x0: int, n: int, atr: float,
                    allow_break_tail: bool) -> int:
    xs = np.arange(x0, n)
    cu = L["close"][x0:n]
    up_v = cu > u.at(xs) + CLOSE_VIOL_ATR * atr
    dn_v = cu < lo.at(xs) - CLOSE_VIOL_ATR * atr
    if allow_break_tail and len(xs) > 6:   # پنجرهٔ شکست اخیر، خطا نیست
        up_v[-6:] = False
        dn_v[-6:] = False
    return int(np.sum(up_v | dn_v))


# ═══════════════════════════ الگوهای پیوتی ═══════════════════════════
NECK_ATR = 0.35


def detect_pivot_patterns(df: pd.DataFrame, offset: int = 0,
                          lookback: Optional[int] = None) -> List[PatternResult]:
    """سقف/کف دوقلو، سر‌وشانه (±)، فنجان‌ودسته (±) با خط گردن و هدف اندازه‌گیری‌شده
    (ادواردز‌ومجی: تأیید = کلوز قاطع پشت خط گردن؛ بالکوفسکی: عبور پیش از شکست = ابطال)."""
    if lookback is not None and lookback < len(df):
        offset += len(df) - lookback
        df = df.tail(lookback).reset_index(drop=True)
    L = log_ohlc(df)
    n = len(df)
    if n < 40:
        return []
    atr = atr_log(L)
    sp = spike_mask(L, atr)
    piv = zigzag_pivots(L, atr, spikes=sp, confirmed_only=True)
    H = [p for p in piv if p["kind"] == "H"]
    Lo = [p for p in piv if p["kind"] == "L"]
    out: List[PatternResult] = []

    def neck_line(a: Dict, b: Dict) -> Line:
        sl = (b["price"] - a["price"]) / max(1, b["index"] - a["index"])
        return Line(sl, a["price"] - sl * a["index"], "neck", (a["index"], b["index"]), a["index"])

    # دوقلوها
    for arr, kind, slug in ((H, "H", "DOUBLE_TOP"), (Lo, "L", "DOUBLE_BOTTOM")):
        for a, b in zip(arr, arr[1:]):
            gap = b["index"] - a["index"]
            tol = max(0.35 * atr, 0.02 * abs(a["price"]))
            if gap < 5 or abs(a["price"] - b["price"]) > tol:
                continue
            between = [p for p in (Lo if kind == "H" else H)
                       if a["index"] < p["index"] < b["index"]]
            if not between:
                continue
            mpt = between[0] if kind == "H" else between[-1]
            depth = abs(a["price"] - mpt["price"])
            if depth < MIN_HEIGHT_ATR * atr:
                continue
            if kind == "H":
                lows_between = [p for p in Lo if a["index"] <= p["index"] <= b["index"]]
                neck_p = min(lows_between, key=lambda p: p["price"]) if lows_between else mpt
            else:
                highs_between = [p for p in H if a["index"] <= p["index"] <= b["index"]]
                neck_p = max(highs_between, key=lambda p: p["price"]) if highs_between else mpt
            neck = _shift(Line(0.0, neck_p["price"], "neck", (neck_p["index"],), neck_p["index"]), offset)
            depth = abs(a["price"] - neck_p["price"])
            if depth < MIN_HEIGHT_ATR * atr:
                continue
            top = _shift(Line(0.0, max(a["price"], b["price"]), "upper",
                       (a["index"], b["index"]), a["index"]), offset)
            bot = _shift(Line(0.0, neck_p["price"], "lower", (neck_p["index"],), neck_p["index"]), offset)
            res = PatternResult(slug, top, bot, a["index"] + offset, b["index"] + offset,
                                10.0 + depth / atr, Leg(), {"depth": depth, "kind": kind,
                                                           "hmax": depth})
            res.kind = "pivot_pattern"
            res.neckline = neck
            out.append(res)

    # سر و شانه (و معکوس)
    for arr, kind, slug in ((H, "H", "HEAD_SHOULDERS"), (Lo, "L", "INV_HEAD_SHOULDERS")):
        for a, b, c in zip(arr, arr[1:], arr[2:]):
            if not (a["index"] < b["index"] < c["index"]):
                continue
            if kind == "H":
                if not (b["price"] > a["price"] and b["price"] > c["price"]
                        and abs(a["price"] - c["price"]) <= 0.5 * atr):
                    continue
            else:
                if not (b["price"] < a["price"] and b["price"] < c["price"]
                        and abs(a["price"] - c["price"]) <= 0.5 * atr):
                    continue
            n1 = [p for p in (Lo if kind == "H" else H) if a["index"] < p["index"] < b["index"]]
            n2 = [p for p in (Lo if kind == "H" else H) if b["index"] < p["index"] < c["index"]]
            if not n1 or not n2:
                continue
            p1, p2 = n1[-1] if kind == "H" else n1[0], n2[0] if kind == "H" else n2[-1]
            depth = abs(b["price"] - min(p1["price"], p2["price"])) if kind == "H" \
                else abs(max(p1["price"], p2["price"]) - b["price"])
            if depth < MIN_HEIGHT_ATR * atr:
                continue
            neck_lvl = min(p1["price"], p2["price"]) if kind == "H" else max(p1["price"], p2["price"])
            top = _shift(Line(0.0, max(b["price"], neck_lvl), "upper", (b["index"],), b["index"]), offset)
            bot = _shift(Line(0.0, min(b["price"], neck_lvl), "lower", (p1["index"],), p1["index"]), offset)
            res = PatternResult(slug, top, bot, a["index"] + offset, c["index"] + offset,
                                12.0 + depth / atr, Leg(), {"depth": depth, "hmax": depth})
            res.kind = "pivot_pattern"
            res.neckline = _shift(neck_line(p1, p2), offset)
            out.append(res)

    # فنجان و دسته (و معکوس): قوس عمیق + دستهٔ کوچک
    for slug, hi_src, lo_src in (("CUP_HANDLE", H, Lo), ("INV_CUP_HANDLE", Lo, H)):
        for a, b in zip(hi_src, hi_src[1:]):
            gap = b["index"] - a["index"]
            if gap < 20:
                continue
            tol = max(0.5 * atr, 0.03 * abs(a["price"]))
            if abs(a["price"] - b["price"]) > tol:
                continue
            mid = [p for p in lo_src if a["index"] < p["index"] < b["index"]]
            if not mid:
                continue
            bottom = min(mid, key=lambda p: p["price"]) if slug == "CUP_HANDLE" \
                else max(mid, key=lambda p: p["price"])
            depth = abs(a["price"] - bottom["price"])
            if depth < 3 * atr:
                continue
            if not (0.3 < (bottom["index"] - a["index"]) / gap < 0.8):
                continue
            handle = [p for p in hi_src if bottom["index"] < p["index"] < b["index"]]
            if slug == "CUP_HANDLE" and handle and handle[0]["price"] > a["price"] + 0.3 * depth:
                continue
            top = _shift(Line(0.0, max(a["price"], b["price"]), "upper", (a["index"], b["index"]), a["index"]), offset)
            bot = _shift(Line(0.0, bottom["price"], "lower", (bottom["index"],), bottom["index"]), offset)
            res = PatternResult(slug, top, bot, a["index"] + offset, b["index"] + offset,
                                9.0 + depth / atr, Leg(), {"depth": depth, "hmax": depth})
            res.kind = "pivot_pattern"
            res.neckline = _shift(Line(0.0, max(a["price"], b["price"]), "neck",
                                (a["index"], b["index"]), a["index"]), offset)
            out.append(res)
    out.sort(key=lambda r: -r.score)
    return out[:4]


# ═══════════════════════════ نقش و بایاس ═══════════════════════════
BIAS = {"WEDGE_FALLING": UP, "WEDGE_RISING": DOWN, "TRIANGLE_ASCENDING": UP,
        "TRIANGLE_DESCENDING": DOWN, "TRIANGLE_SYMMETRICAL": NONE,
        "RECTANGLE_BULL": UP, "RECTANGLE_BEAR": DOWN, "RECTANGLE": NONE,
        "FLAG_BULL": UP, "FLAG_BEAR": DOWN, "PENNANT_BULL": UP, "PENNANT_BEAR": DOWN,
        "BROADENING": NONE, "BROADENING_WEDGE_ASC": DOWN, "BROADENING_WEDGE_DESC": UP,
        "CHANNEL_ASCENDING": UP, "CHANNEL_DESCENDING": DOWN, "CHANNEL_FLAT": NONE,
        "CHANNEL_ASCENDING_BROAD": UP, "CHANNEL_DESCENDING_BROAD": DOWN,
        "DOUBLE_TOP": DOWN, "DOUBLE_BOTTOM": UP, "HEAD_SHOULDERS": DOWN,
        "INV_HEAD_SHOULDERS": UP, "CUP_HANDLE": UP, "INV_CUP_HANDLE": DOWN}


def both_sides(slug: str, entry: str) -> Dict:
    """نقش هر دو سمت شکست؛ بایاس هندسه جدا از کیفیت شکست."""
    bias = BIAS.get(slug, NONE)
    cont = (entry == UP and bias == UP) or (entry == DOWN and bias == DOWN)
    return {"bias": bias, "entry_side": entry,
            "break_up_role": "continuation" if bias == UP else "reversal",
            "break_down_role": "continuation" if bias == DOWN else "reversal",
            "likely_edge": "UPPER" if bias == UP else ("LOWER" if bias == DOWN else None)}


def break_quality(L: Dict[str, np.ndarray], i: int, atr: float, edge: str) -> str:
    """درجهٔ کندل شکست (ال‌بروکس): STRONG/OK/WEAK/CLIMAX."""
    o, c, h, l = (L[k][i] for k in ("open", "close", "high", "low"))
    body = abs(c - o)
    rng = max(h - l, 1e-9)
    if edge == "UP":
        strong = c > o and body >= 0.6 * rng and body >= 0.8 * atr
    else:
        strong = c < o and body >= 0.6 * rng and body >= 0.8 * atr
    if not strong:
        return "WEAK"
    look = slice(max(0, i - 9), i + 1)
    run = np.sum(np.abs(np.diff(L["close"][look])) > 0.8 * atr)
    if run >= 4:
        return "CLIMAX"
    return "STRONG" if body >= 1.0 * atr else "OK"


# ═══════════════════════════ چرخهٔ شکست ══════════════════════════
def breakout_lifecycle(df: pd.DataFrame, res: PatternResult, atr: Optional[float] = None,
                       offset: int = 0) -> Dict:
    """رویدادمحور: اولین عبورِ کلوز از هر ضلع = رویداد؛ ماندگاری/فیک/ریتست ثبت
    می‌شود؛ bars_ago از خود رویداد است نه از پنجرهٔ لغزان."""
    L = log_ohlc(df)
    atr = atr or atr_log(L)
    n = len(df)
    tol = BREAK_TOL_ATR * atr
    c = L["close"]
    x0 = max(0, res.x0 - offset)
    first_up = first_dn = None
    false_up = false_dn = None
    retest_up = retest_dn = None
    for i in range(max(1, x0), n):
        u_v, l_v = res.upper.at(i + offset), res.lower.at(i + offset)
        if first_up is None and c[i] > u_v + tol:
            first_up = i
        if first_dn is None and c[i] < l_v - tol:
            first_dn = i
        if first_up is not None and false_up is None and i > first_up:
            inside = c[i] <= res.upper.at(i + offset) and c[i] >= res.lower.at(i + offset)
            if inside and i - first_up <= FALSE_RETURN_BARS:
                false_up = i
        if first_dn is not None and false_dn is None and i > first_dn:
            inside = c[i] <= res.upper.at(i + offset) and c[i] >= res.lower.at(i + offset)
            if inside and i - first_dn <= FALSE_RETURN_BARS:
                false_dn = i
        if first_up is not None and false_up is None and i > first_up + FALSE_RETURN_BARS:
            if retest_up is None and abs(c[i] - res.upper.at(i + offset)) <= tol and c[i - 1] > res.upper.at(i - 1 + offset):
                retest_up = i
        if first_dn is not None and false_dn is None and i > first_dn + FALSE_RETURN_BARS:
            if retest_dn is None and abs(c[i] - res.lower.at(i + offset)) <= tol and c[i - 1] < res.lower.at(i - 1 + offset):
                retest_dn = i
    ev = None
    if first_up is not None and (first_dn is None or first_up <= first_dn):
        edge = "UPPER"
        ev = first_up
        if false_up is not None:
            status = "FALSE_BREAK_UP"
        elif retest_up is not None:
            status = "RETEST_UP"
        else:
            status = "BREAK_UP_CLOSED"
    elif first_dn is not None:
        edge = "LOWER"
        ev = first_dn
        if false_dn is not None:
            status = "FALSE_BREAK_DOWN"
        elif retest_dn is not None:
            status = "RETEST_DOWN"
        else:
            status = "BREAK_DOWN_CLOSED"
    else:
        return {"status": "INSIDE", "edge": None, "event_index": None,
                "bars_since_break": None, "quality": None}
    q = break_quality(L, ev, atr, "UP" if edge == "UPPER" else "DOWN")
    return {"status": status, "edge": edge, "event_index": ev + offset,
            "bars_since_break": n - 1 - ev, "quality": q,
            "false_index": (false_up if edge == "UPPER" else false_dn),
            "retest_index": (retest_up if edge == "UPPER" else retest_dn)}


# ═══════════════════════════ هدف اندازه‌گیری‌شده ═══════════════════════════
def measured_target(slug: str, meta: Dict, level: float, direction: str) -> float:
    h = meta.get("hmax", 0.0) or abs(meta.get("w0", 0.0))
    if slug.startswith(("FLAG", "PENNANT")) and meta.get("leg") is not None \
            and meta["leg"].move > 0:
        h = meta["leg"].move
    if slug.startswith("BROADENING") or slug.endswith("_BROAD"):
        h = min(h, meta.get("w1", h))          # سقف ریسک در واگراها
    if slug in ("DOUBLE_TOP", "HEAD_SHOULDERS"):
        return level * math.exp(-h)
    if slug in ("DOUBLE_BOTTOM", "INV_HEAD_SHOULDERS"):
        return level * math.exp(h)
    return level * math.exp(h if direction == UP else -h)


# ═══════════════════════════ نما (زوم/قاب) ═══════════════════════════
def choose_view(df: pd.DataFrame, res: PatternResult,
                target_price: Optional[float] = None, tf: Optional[str] = None) -> Dict:
    """قابِ خدمتگزارِ الگو: فضای راست برای باکس هدف، سابقهٔ چپ برای پایه، کندل‌ها
    ≤۸۵٪ ارتفاع (مگر قطری)، و تعداد کندل هم‌راستا با جدول r57."""
    L = log_ohlc(df)
    n = len(df)
    # A stale pattern must never force the viewport to pan months/years left.
    # Pattern fitting is performed on a bounded lookback; enforce the same
    # visible-age contract here as a final guard against legacy/global anchors.
    x0 = min(max(0, int(res.x0)), n - 1)
    x1 = min(max(x0, int(res.x1)), n - 1)
    tbar = TF_VIEW_BARS.get(tf or "", 0)
    # Visible data window is intentionally bounded by the timeframe's chart
    # budget. Keep at least 80% of that budget, and never widen it just to show
    # an old pattern start. If the selected pattern is older than the visible
    # budget, its left anchors are clipped by the viewport rather than moving
    # the live candles off-screen.
    target_bars = int(tbar or 200)
    max_data_bars = max(60, target_bars)
    x_from = max(0, n - max_data_bars)
    # A pattern can be framed only if its start is inside the bounded data
    # window. Otherwise the renderer still shows current market data, not stale
    # history. Keep the right projection independent of historical pattern age.
    frame_x0 = max(x0, x_from)
    plen = max(1, x1 - frame_x0 + 1)
    leg_bars = int(min(max(0, res.leg.bars * 1.1), max_data_bars * 0.20)) \
        if res.leg.direction != NONE else 0
    left_need = min(max(leg_bars, int(LEFT_PAD_MIN * plen)), max_data_bars // 4)
    right = max(8, int(round(target_bars * RIGHT_PROJ)))
    x_to = n - 1 + right
    # x_from is based on live candles, not on res.x0; no stale candidate may
    # expand the historical window beyond max_data_bars.
    total = x_to - x_from + 1
    lo_t, hi_t = (int(0.8 * target_bars), int(1.25 * target_bars))
    seg = slice(x_from, n)
    data_lo = float(L["low"][seg].min())
    data_hi = float(L["high"][seg].max())
    # Include only the selected pattern's line values inside the actual viewport.
    # This prevents valid near-price trendlines from being clipped vertically,
    # while avoiding unbounded extrapolation to stale x0/x1 anchors.
    line_values = []
    # A pattern wholly to the left of the visible data is stale for framing:
    # do not extrapolate its equations into today's price scale.
    overlaps_view = x1 >= x_from and x0 <= n - 1
    if overlaps_view:
        line_x0 = max(x_from, x0)
        line_x1 = min(n - 1, x1)
        if line_x1 >= line_x0:
            for line in (res.upper, res.lower):
                for xi in (line_x0, line_x1):
                    try:
                        value = float(line.price_at(xi))
                    except (AttributeError, TypeError, ValueError, OverflowError):
                        continue
                    if math.isfinite(value) and value > 0:
                        # A wildly detached projection is not a useful price-axis
                        # anchor; bound it relative to the visible candle envelope.
                        if data_lo / 1.8 <= value <= data_hi * 1.8:
                            line_values.append(math.log(value))
    lo, hi = data_lo, data_hi
    if line_values:
        lo, hi = min(lo, min(line_values)), max(hi, max(line_values))
    if target_price:
        tl = math.log(max(target_price, 1e-9))
        lo, hi = min(lo, tl), max(hi, tl)
    rng = max(hi - lo, 1e-9)
    diag = abs(res.meta.get("du", 0)) + abs(res.meta.get("dl", 0)) > 1.2
    m_top, m_bot = 0.06, 0.05
    fill = (data_hi - data_lo) / (rng * (1 + m_top + m_bot))
    if fill > MAX_FILL and not diag:
        extra = fill / MAX_FILL - 1.0
        m_top += extra * 0.6
        m_bot += extra * 0.4
        fill = (data_hi - data_lo) / (rng * (1 + m_top + m_bot))
    y_min, y_max = lo - m_bot * rng, hi + m_top * rng
    return {"x_from": x_from, "x_to": x_to, "bars": x_to - x_from + 1,
            "pad_right": right, "y_min": math.exp(y_min), "y_max": math.exp(y_max),
            "fill": float(fill), "diagonal_pattern": bool(diag), "tf": tf}


# ── R99q (Viva 10-15): «محور قیمت‌ها خالیه باید قیمت‌ها دقیق نوشته بشه» ───
# یک قانونِ واحد برای تیک‌های محور قیمت در همهٔ چارت‌ها (اسپات + پرپ):
# گام‌های رُند ۱/۱٫۵/۲/۲٫۵/۵/۷٫۵ ×۱۰^k با ۱۰ تا ۱۶ لیبل، و تعداد اعشار از
# خودِ گام (۰٫۰۱۵ → سه اعشار، ۵۰۰۰ → صفر اعشار). قطعی و نسخه-مستقل.
_TICK_LADDER = (1.0, 1.5, 2.0, 2.5, 5.0, 7.5)


def nice_price_ticks(lo: float, hi: float, target: int = 13):
    """(ticks, decimals) — لیست تیک‌های رُند داخل [lo, hi] و دقت نمایش."""
    try:
        lo_f, hi_f = float(lo), float(hi)
        if not (hi_f > lo_f > 0):
            return [], 4
        raw = (hi_f - lo_f) / max(4, int(target) - 1)
        mag = 10.0 ** math.floor(math.log10(raw))
        best = None
        for mult in (1.0, 2.0, 2.5, 5.0, 10.0):
            step = mult * mag
            n = int((hi_f - lo_f) / step) + 1
            if 8 <= n <= 18:
                best = step
                break
        if best is None:
            # گام ریزتر با نصفِ لدر (۱٫۵/۷٫۵) برای بازه‌های باریک
            for mult in (1.5, 7.5, 0.5, 0.25):
                step = mult * mag
                n = int((hi_f - lo_f) / step) + 1
                if 8 <= n <= 26:
                    best = step
                    break
        if best is None:
            best = (hi_f - lo_f) / max(4, int(target) - 1)
        _ord = int(math.floor(math.log10(best) + 1e-9))
        dec = max(0, -_ord)
        _mult = round(best / (10.0 ** _ord), 3)
        if _mult in (1.5, 2.5, 7.5):
            dec += 1
        start = math.ceil((lo_f * (1 + 1e-9)) / best) * best
        ticks, t = [], start
        while t <= hi_f * (1 + 1e-9) and len(ticks) < 40:
            ticks.append(round(t, 10))
            t += best
        if len(ticks) < 6:               # خیلی باریک: گام را نصف کن
            best2 = best / 2.0
            dec = max(dec, -int(math.floor(math.log10(best2))))
            start = math.ceil((lo_f * (1 + 1e-9)) / best2) * best2
            ticks, t = [], start
            while t <= hi_f * (1 + 1e-9) and len(ticks) < 40:
                ticks.append(round(t, 10))
                t += best2
        return ticks, int(dec)
    except Exception:
        return [], 4
