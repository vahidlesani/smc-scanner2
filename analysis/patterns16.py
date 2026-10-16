"""patterns16 — the 16 canonical chart patterns as CODE LAW (r61).

Viva 09-30 (verbatim): «اگر ۱۶ الگوی اصلی در انجین به درستی درک نشن در اسپات
و مخصوصاً در ستاپ‌ها دائماً مشکل ادامه دار خواهد بود» + «باید قوانین این عکس
رفرنس رو از سورس بین‌المللی بگیری و کد بکنی» + «حتی مهمه که ببینیم قیمت از
کدام سمت وارد شده».

International source of the rules encoded here: Edwards & Magee "Technical
Analysis of Stock Trends" + Bulkowski "Encyclopedia of Chart Patterns" —
the two references every international chart-pattern table (including his
poster) descends from.

This module owns:
  1. PATTERN16_LIBRARY — the canonical 16 (+ flat variants) with Persian names
     matching his poster, bias, entry-side expectation and the one-line rule.
  2. tail_slopes / classify16 — the honest two-edge classifier: edge roles are
     sanity-checked against price, slopes are measured on the TAIL (the last
     segment the eye sees), not the whole-window OLS compromise, and a WEDGE
     label must match the side price ENTERED from (HYPE 09-30 law: a narrowing
     structure entered from ABOVE after a vertical rally is NOT a rising wedge).
  3. detect_pivot_patterns — the pivot-sequence family the two-line fitter can
     never see: double top/bottom, head & shoulders (+inverse), cup & handle
     (+inverted), with neckline, measured move and entry side.

Nothing here decides a trade; it names and measures what the geometry is.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# ───────────────────────── canonical vocabulary ──────────────────────────
# bias = the pattern's MAJORITY breakout direction (E&M/Bulkowski stats);
# the actual break always decides (his doctrine: the close decides).
PATTERN16_LIBRARY: Dict[str, Dict] = {
    # — دو مدل وج (poster: کوه صعودی / کوه نزولی) —
    "WEDGE_RISING": {
        "fa": "گوه صعودی (رایزینگ‌وج)", "bias": "BEAR", "shape": "converging",
        "entry": "BELOW",
        "rule_fa": "دو ضلع همگرا که هر دو شیب صعودی دارند و قیمت از پایین وارد الگو شده؛ کلوز زیر ضلع پایین = برگشت نزولی، کلوز بالای ضلع بالا = ادامهٔ صعودی.",
    },
    "WEDGE_FALLING": {
        "fa": "گوه نزولی (فالینگ‌وج)", "bias": "BULL", "shape": "converging",
        "entry": "ABOVE",
        "rule_fa": "دو ضلع همگرا که هر دو شیب نزولی دارند و قیمت از بالا وارد الگو شده؛ کلوز بالای ضلع بالا = برگشت صعودی، کلوز زیر ضلع پایین = ادامهٔ نزولی.",
    },
    # — سه مدل مثلث —
    "TRIANGLE_ASCENDING": {
        "fa": "مثلث صعودی", "bias": "BULL", "shape": "converging",
        "entry": "BELOW",
        "rule_fa": "ضلع بالا افقی (مقاومت) و ضلع پایین صعودی؛ کلوز بالای ضلع افقی = تأیید صعودی.",
    },
    "TRIANGLE_DESCENDING": {
        "fa": "مثلث نزولی", "bias": "BEAR", "shape": "converging",
        "entry": "ABOVE",
        "rule_fa": "ضلع پایین افقی (حمایت) و ضلع بالا نزولی؛ کلوز زیر ضلع افقی = تأیید نزولی.",
    },
    "TRIANGLE_SYMMETRICAL": {
        "fa": "مثلث متقارن", "bias": "NEUTRAL", "shape": "converging",
        "entry": "ANY",
        "rule_fa": "ضلع بالا نزولی و ضلع پایین صعودی؛ جهت با کلوزِ همان ضلعی که می‌شکند تعیین می‌شود — ورود قیمت معمولاً جهتِ شکست را پیش‌بینی می‌کند.",
    },
    # — دو مدل کانال —
    "CHANNEL_ASCENDING": {
        "fa": "کانال صعودی", "bias": "BULL", "shape": "parallel",
        "entry": "ANY",
        "rule_fa": "دو ضلع موازی صعودی؛ کلوز بالای سقف کانال = ادامهٔ صعودی، کلوز زیر کف = شکست کانال.",
    },
    "CHANNEL_DESCENDING": {
        "fa": "کانال نزولی", "bias": "BEAR", "shape": "parallel",
        "entry": "ANY",
        "rule_fa": "دو ضلع موازی نزولی؛ کلوز زیر کف کانال = ادامهٔ نزولی، کلوز بالای سقف = شکست کانال.",
    },
    # — دو مدل مستطیل —
    "RECTANGLE_BULL": {
        "fa": "مستطیل صعودی", "bias": "BULL", "shape": "box",
        "entry": "BELOW",
        "rule_fa": "پرچمِ افقی پس از موج صعودی (استراحتِ روند)؛ کلوز بالای سقف مستطیل = ادامهٔ صعودی.",
    },
    "RECTANGLE_BEAR": {
        "fa": "مستطیل نزولی", "bias": "BEAR", "shape": "box",
        "entry": "ABOVE",
        "rule_fa": "پرچمِ افقی پس از موج نزولی؛ کلوز زیر کف مستطیل = ادامهٔ نزولی.",
    },
    # — دو مدل پرچم (+ پرچم سه‌گوش پوستر) —
    "FLAG_BULL": {
        "fa": "پرچم صعودی", "bias": "BULL", "shape": "parallel",
        "entry": "BELOW",
        "rule_fa": "پرچمِ کوچکِ نزولیِ موازی پس از پایهٔ صعودی تند؛ کلوز بالای پرچم = ادامهٔ صعودی.",
    },
    "FLAG_BEAR": {
        "fa": "پرچم نزولی", "bias": "BEAR", "shape": "parallel",
        "entry": "ABOVE",
        "rule_fa": "پرچمِ کوچکِ صعودیِ موازی پس از پایهٔ نزولی تند؛ کلوز زیر پرچم = ادامهٔ نزولی.",
    },
    "PENNANT_BULL": {
        "fa": "پرچم سه‌گوش صعودی", "bias": "BULL", "shape": "converging",
        "entry": "BELOW",
        "rule_fa": "مثلث کوچکِ همگرا بلافاصله پس از پایهٔ صعودی تند (پرچم سه‌گوش)؛ کلوز بالای رأسِ کوچک = ادامهٔ صعودی.",
    },
    "PENNANT_BEAR": {
        "fa": "پرچم سه‌گوش نزولی", "bias": "BEAR", "shape": "converging",
        "entry": "ABOVE",
        "rule_fa": "مثلث کوچکِ همگرا بلافاصله پس از پایهٔ نزولی تند؛ کلوز زیر رأسِ کوچک = ادامهٔ نزولی.",
    },
    # — سقف/کف دوقلو و سر و شانه و کاپ —
    "DOUBLE_TOP": {
        "fa": "سقف دوقلو", "bias": "BEAR", "shape": "pivots",
        "entry": "ABOVE",
        "rule_fa": "دو سقفِ هم‌سطح با درهٔ میانی (خط گردن)؛ کلوز زیر خط گردن = تأیید نزولی، هدف = ارتفاع الگو از خط گردن.",
    },
    "DOUBLE_BOTTOM": {
        "fa": "کف دوبل", "bias": "BULL", "shape": "pivots",
        "entry": "BELOW",
        "rule_fa": "دو کفِ هم‌سطح با قلهٔ میانی (خط گردن)؛ کلوز بالای خط گردن = تأیید صعودی، هدف = ارتفاع الگو از خط گردن.",
    },
    "HEAD_SHOULDERS": {
        "fa": "سر و شانه", "bias": "BEAR", "shape": "pivots",
        "entry": "ABOVE",
        "rule_fa": "سه سقف با سرِ میانیِ بلندتر و شانه‌های هم‌سطح؛ کلوز زیر خط گردن = تأیید نزولی.",
    },
    "INV_HEAD_SHOULDERS": {
        "fa": "سر و شانه معکوس", "bias": "BULL", "shape": "pivots",
        "entry": "BELOW",
        "rule_fa": "سه کف با سرِ میانیِ عمیق‌تر؛ کلوز بالای خط گردن = تأیید صعودی.",
    },
    "CUP_HANDLE": {
        "fa": "کاپ و دسته", "bias": "BULL", "shape": "pivots",
        "entry": "BELOW",
        "rule_fa": "کفِ گردِ U شکل با دستهٔ کم‌عمق در سمت راست؛ کلوز بالای سقفِ دسته = تأیید صعودی.",
    },
    "INV_CUP_HANDLE": {
        "fa": "کاپ و دستهٔ معکوس", "bias": "BEAR", "shape": "pivots",
        "entry": "ABOVE",
        "rule_fa": "سقفِ گردِ وارونه با دستهٔ کوچک؛ کلوز زیر کفِ دسته = تأیید نزولی.",
    },
    # — legacy slugs kept so old keys keep rendering —
    "TRIANGLE": {"fa": "مثلث", "bias": "NEUTRAL", "shape": "converging", "entry": "ANY",
                 "rule_fa": "هندسهٔ همگرا؛ جهت = جهتِ ضلعِ شکسته‌شده با کلوز."},
    "BROADENING": {"fa": "مگافون گشونده", "bias": "NEUTRAL", "shape": "converging", "entry": "ANY",
                   "rule_fa": "دو ضلع واگرا؛ هر سمت با کلوز بیرونِ همان ضلع معتبر است."},
    "CHANNEL_FLAT": {"fa": "کانال افقی", "bias": "NEUTRAL", "shape": "parallel", "entry": "ANY",
                     "rule_fa": "کانال افقی: معامله فقط از لبه‌ها با کلوز بیرونِ لبه."},
    "CHANNEL": {"fa": "کانال", "bias": "NEUTRAL", "shape": "parallel", "entry": "ANY",
                "rule_fa": "دو ضلع موازی؛ جهت = جهت ضلع شکسته‌شده با کلوز."},
    "RECTANGLE": {"fa": "مستطیل / رنج", "bias": "NEUTRAL", "shape": "box", "entry": "ANY",
                  "rule_fa": "سقف و کف افقیِ چندبرخوردی؛ کلوز بیرون هر کدام = تأیید همان سمت."},
    "TRENDLINE": {"fa": "خط روند اصلی", "bias": "NEUTRAL", "shape": "single", "entry": "ANY",
                  "rule_fa": "یک خط روند معتبر (≥۲ برخورد)؛ کلوز آن‌طرفِ خط = تأیید."},
    "HORIZONTAL_SR": {"fa": "سطح افقی مهم", "bias": "NEUTRAL", "shape": "single", "entry": "ANY",
                      "rule_fa": "سطح افقیِ چندبرخوردی؛ کلوز بیرون سطح = تأیید."},
    "NONE": {"fa": "—", "bias": "NEUTRAL", "shape": "single", "entry": "ANY",
             "rule_fa": "هندسهٔ معتبری شناسایی نشد."},
}


def info16(kind: str) -> Dict:
    k = str(kind or "").upper()
    lib = PATTERN16_LIBRARY.get(k)
    if lib is None:
        return dict(PATTERN16_LIBRARY["NONE"], key="NONE")
    return dict(lib, key=k)


# ───────────────────── honest two-edge classification ────────────────────
def tail_slope(price_at, n: int, start: int, tail: int = 12) -> float:
    """Per-bar slope of the line's LAST `tail` bars — the segment the eye
    actually reads. Whole-window OLS hides it (the HYPE 09-30 bug: a stale
    rally trendline made a topping structure read «دو ضلع با شیب صعودی»)."""
    try:
        k = max(2, min(int(tail), int(n) - int(start)))
        a = float(price_at(int(n) - k))
        b = float(price_at(int(n)))
        return (b - a) / float(k)
    except Exception:
        return 0.0


def entry_side(df, start: int, upper_at_n: float, lower_at_n: float) -> str:
    """«قیمت از کدام سمت وارد شده» — the side price entered the pattern from.

    E&M: a consolidation entered from BELOW on a rising leg is continuation
    territory; entered from ABOVE after a vertical blow-off it is a TOP being
    carved. Measured at the bar just before the pattern start: a close in the
    upper half of the band (or above it) = entered from ABOVE, else BELOW.
    """
    try:
        i = max(0, int(start) - 1)
        c = float(df["close"].iloc[i])
        mid = (float(upper_at_n) + float(lower_at_n)) / 2.0
        return "ABOVE" if c >= mid else "BELOW"
    except Exception:
        return "ANY"


def classify16(upper, lower, n: int, df=None, tail: int = 12) -> Tuple[str, Dict]:
    """R99q21 — DELEGATES to the single reference law (analysis.pattern_law).

    Returns (slug, meta) exactly as before, but the verdict now comes from
    PATTERN_LAW — the same code the renderer, the spot engine and the setup
    engines call — so one structure can no longer be named three different
    things in three lanes. `meta` carries the measured numbers and the `why`
    trail.

    The pivots-only trio (DOUBLE_TOP / DOUBLE_BOTTOM / HEAD_SHOULDERS and their
    inverses) is RETIRED per Viva 10-16 and is never returned from here.
    """
    try:
        from analysis.pattern_law import pair_metrics, classify_pair
        m = pair_metrics(upper, lower, int(n), df=df)
        meta: Dict = {"entry_side": m.get("entry_side", "ANY")}
        slug = classify_pair(m, meta)
        meta.update({k: m.get(k) for k in ("rel_u", "rel_l", "conv_ratio",
                                           "width_then", "width_now", "span")})
        return slug, meta
    except Exception as exc:            # never silent, never a wrong label
        return "NONE", {"error": str(exc)}

def detect_flag_pennant(df, atr_v: float, pole_bars: int = 12,
                        flag_bars: int = 22) -> list:
    """Pole → counter-drift consolidation, coded for the RENDER vocabulary
    (Viva 10-03: «۱۶ تا الگو داریم چرا فقط چند مورد وج پیدا میکنه فقط؟؟»).

    • POLE: a displacement of ≥ 2.5×ATR within ≤ ``pole_bars`` bars, ending
      within the last ~``flag_bars`` bars (a fossil pole is not a setup).
    • FLAG: the consolidation drifts AGAINST the pole (both mini-edges fall
      after a bull pole / rise after a bear) and stays inside ~2×ATR width.
    • PENNANT: the mini pair CONVERGES (width shrinks ≥ 30%).
    Returns render commands of the same shape as ``detect_pivot_patterns``
    (type + lines + neckline) so the painter needs no new branch. Alert
    detection is deliberately untouched this round — render vocabulary only.
    """
    out: list = []
    try:
        import numpy as np
        close = df["close"].astype(float).to_numpy()
        high = df["high"].astype(float).to_numpy()
        low = df["low"].astype(float).to_numpy()
        n = len(close)
        if n < pole_bars + flag_bars + 10 or atr_v <= 0:
            return out
        best = None
        # the consolidation may run long (a 38-bar flag is still a flag);
        # only the ANCHOR must be fresh enough to matter on the chart
        for end in range(n - 6, max(pole_bars + 2, n - 3 * flag_bars) - 1, -1):
            if end - pole_bars - 1 < 1:
                break
            # the pole may end slightly BEFORE the consolidation anchor — take
            # the strongest pole window that closes within 10 bars of `end`
            move, pole_end = 0.0, 0
            for j in range(max(pole_bars + 1, end - 10), end):
                _m = float(close[j] - close[j - pole_bars])
                if abs(_m) > abs(move):
                    move, pole_end = _m, j
            if abs(move) < 1.8 * atr_v:
                continue
            span = n - end
            if span < 4:
                continue
            width = float(high[end:].max() - low[end:].min())
            if width > max(4.5 * atr_v, 0.58 * abs(move)):
                continue
            mid = float(close[end:min(n, end + span)].mean())
            first_half = float(close[end:max(end + span // 2, end + 1)].mean())
            last_half = float(close[end + span // 2:].mean())
            drift = last_half - first_half
            # honest pennant: the consolidation's second half is measurably
            # TIGHTER than its first (convergence, not a guess)
            _h1, _l1 = float(high[end:max(end + span // 2, end + 1)].max()), float(low[end:max(end + span // 2, end + 1)].min())
            _h2, _l2 = float(high[end + span // 2:].max()), float(low[end + span // 2:].min())
            _w1 = max(_h1 - _l1, 1e-12)
            _w2 = max(_h2 - _l2, 0.0)
            kind = ""
            # R67: pennants are decided by CONVERGENCE first; flags need a
            # meaningful counter-drift (≥0.25×ATR) — a sideways oscillation
            # after a pole is a pennant, not a flag.
            if _w2 <= 0.60 * _w1:
                kind = "PENNANT_BULL" if move > 0 else "PENNANT_BEAR"
            elif move > 0 and drift <= -0.25 * atr_v:
                kind = "FLAG_BULL"
            elif move < 0 and drift >= 0.25 * atr_v:
                kind = "FLAG_BEAR"
            if kind:
                best = (kind, end, mid, width)
                break
            _ = pole_end
        if not best:
            return out
        kind, end, mid, width = best
        neckline = float(mid)
        flag_xs = np.arange(end, n)
        flag_h = high[end:]
        flag_l = low[end:]
        if len(flag_xs) >= 3:
            s_up, ic_up = np.polyfit(flag_xs, flag_h, 1)
            s_lo, ic_lo = np.polyfit(flag_xs, flag_l, 1)
            if "FLAG_BULL" in kind:
                # Bull flag tilts down against the upward impulse
                avg_slope = min(s_up, s_lo, -0.02 * atr_v)
                s_up = avg_slope
                s_lo = avg_slope
            elif "FLAG_BEAR" in kind:
                avg_slope = max(s_up, s_lo, 0.02 * atr_v)
                s_up = avg_slope
                s_lo = avg_slope
            # Anchor upper line on top of flag highs
            up_vals = s_up * flag_xs + ic_up
            ic_up += float(np.max(flag_h - up_vals))
            # Anchor lower line to bottom of flag lows
            lo_vals = s_lo * flag_xs + ic_lo
            ic_lo += float(np.min(flag_l - lo_vals))
        else:
            s_up, ic_up = 0.0, float(mid + width / 2.0)
            s_lo, ic_lo = 0.0, float(mid - width / 2.0)

        lines = [{"side": "HIGH", "slope": float(s_up), "intercept": float(ic_up),
                  "x0": int(end), "x1": int(n - 1)},
                 {"side": "LOW", "slope": float(s_lo), "intercept": float(ic_lo),
                  "x0": int(end), "x1": int(n - 1)}]
        fa_map = {"FLAG_BULL": "پرچم صعودی", "FLAG_BEAR": "پرچم نزولی",
                  "PENNANT_BULL": "پرچم سه‌گوش صعودی", "PENNANT_BEAR": "پرچم سه‌گوش نزولی"}
        out.append({"type": kind, "name_fa": fa_map.get(kind, kind), "lines": lines, "neckline": neckline,
                    "pole_atr": round(abs(close[end - 1] - close[end - 1 - pole_bars]) / atr_v, 2)})
    except Exception:
        return []
    return out


# ─────────────────── pivot-structure pattern detectors ───────────────────
def _swings(df, left: int = 3, right: int = 3, max_pts: int = 8) -> Tuple[List[Dict], List[Dict]]:
    """Fractal swing highs/lows (robust zigzag): a pivot dominates its `left`
    neighbours on both sides. Returns (highs, lows) newest-last."""
    try:
        h = df["high"].astype(float).to_numpy()
        l = df["low"].astype(float).to_numpy()
        n = len(h)
        highs, lows = [], []
        for i in range(left, n - right):
            # R63: STRICT on the right side — a flat top/bottom of equal
            # highs (tick-size plateaus) is ONE pivot (its first bar), never
            # two adjacent «tops» that hide the real double top.
            if h[i] >= h[i - left:i].max() and h[i] > h[i + 1:i + 1 + right].max():
                highs.append({"index": i, "price": float(h[i])})
            if l[i] <= l[i - left:i].min() and l[i] < l[i + 1:i + 1 + right].min():
                lows.append({"index": i, "price": float(l[i])})
        return highs[-max_pts:], lows[-max_pts:]
    except Exception:
        return [], []


def _neckline(lows: List[Dict], i0: int, i1: int) -> float:
    seg = [p["price"] for p in lows if i0 <= int(p["index"]) <= i1]
    return float(sum(seg) / len(seg)) if seg else 0.0


def detect_pivot_patterns(df, atr: float) -> List[Dict]:
    """RETIRED (Viva 10-16, verbatim: «دبل تاپ و دبل باتم و سر و شانه رو از اون ۱۶
    پترن کم بکن»). The pivots-only family is removed from the pattern set: those
    shapes have no reliable near-break geometry on a live scanner, and their
    necklines kept being published long after the move. The set the engines now
    speak is the 13 live patterns in analysis.pattern_law (wedges, triangles,
    channels, flags/pennants, rectangle, broadening) — each an edge-pair with
    an auditable breakout side.

    Kept (old payloads and call sites reference it) and returns an empty list,
    so nothing can resurrect the trio.
    """
    return []


def _detect_pivot_patterns_retired(df, atr: float) -> List[Dict]:
    out: List[Dict] = []
    try:
        if df is None or len(df) < 40 or atr <= 0:
            return out
        n = len(df) - 1
        highs, lows = _swings(df)
        tol = 0.60 * atr          # «هم‌سطح» = within 0.6 ATR (Bulkowski ~tight)
        min_gap = 4               # bars between the two tops/bottoms

        def _line(idx0: int, idx1: int, price: float, side: str = "HIGH") -> Dict:
            # side is the STAGING role (spot lane): a bear-pattern neckline is
            # SUPPORT (LOW — the break DOWN confirms); a bull-pattern neckline
            # is RESISTANCE (HIGH — the close ABOVE confirms).
            return {"side": side, "slope": 0.0, "intercept": float(price),
                    "x0": int(idx0), "x1": int(n), "points": []}

        # double TOP / head & shoulders (3 tops)
        if len(highs) >= 2:
            a, b = highs[-2], highs[-1]
            gap = int(b["index"]) - int(a["index"])
            if gap >= min_gap and abs(a["price"] - b["price"]) <= tol:
                mids = [p for p in lows if int(a["index"]) < int(p["index"]) < int(b["index"])]
                if mids:
                    neck = min(mids, key=lambda p: p["price"])
                    height = float(a["price"]) - float(neck["price"])
                    if height > 0.8 * atr:
                        # R62-ARENA (audit P5): a double TOP's neckline is the
                        # SUPPORT under it (break DOWN confirms) → LOW side.
                        neck_line = _line(int(neck["index"]), n, float(neck["price"]), "LOW")
                        neck_line["points"] = []
                        item = {"type": "DOUBLE_TOP", "shape": "single",
                                "lines": [neck_line],
                                "pivots": [a, neck, b],
                                "entry_side": "ABOVE",
                                "measured": round(height, 8),
                                "neckline": float(neck["price"])}
                        # upgrade to H&S when a MIDDLE top is the head
                        if len(highs) >= 3:
                            x, y, z = highs[-3], highs[-2], highs[-1]
                            shoulder = min(x["price"], z["price"])
                            if (int(z["index"]) - int(x["index"]) >= 2 * min_gap
                                    and y["price"] > shoulder + 0.6 * atr
                                    and abs(x["price"] - z["price"]) <= tol):
                                trs = [p for p in lows
                                       if int(x["index"]) < int(p["index"]) < int(z["index"])]
                                if len(trs) >= 2:
                                    nkl = sum(p["price"] for p in trs) / len(trs)
                                    if y["price"] - nkl > 1.2 * atr:
                                        item = {"type": "HEAD_SHOULDERS", "shape": "single",
                                                "lines": [_line(int(trs[0]["index"]), n, nkl, "LOW")],
                                                "pivots": [x, trs[0], y, trs[-1], z],
                                                "entry_side": "ABOVE",
                                                "measured": round(y["price"] - nkl, 8),
                                                "neckline": float(nkl)}
                        out.append(item)
        # double BOTTOM / inverse H&S (3 lows)
        if len(lows) >= 2:
            a, b = lows[-2], lows[-1]
            gap = int(b["index"]) - int(a["index"])
            if gap >= min_gap and abs(a["price"] - b["price"]) <= tol:
                mids = [p for p in highs if int(a["index"]) < int(p["index"]) < int(b["index"])]
                if mids:
                    neck = max(mids, key=lambda p: p["price"])
                    height = float(neck["price"]) - float(a["price"])
                    if height > 0.8 * atr:
                        item = {"type": "DOUBLE_BOTTOM", "shape": "single",
                                "lines": [_line(int(neck["index"]), n, float(neck["price"]), "HIGH")],
                                "pivots": [a, neck, b],
                                "entry_side": "BELOW",
                                "measured": round(height, 8),
                                "neckline": float(neck["price"])}
                        if len(lows) >= 3:
                            x, y, z = lows[-3], lows[-2], lows[-1]
                            shoulder = max(x["price"], z["price"])
                            if (int(z["index"]) - int(x["index"]) >= 2 * min_gap
                                    and y["price"] < shoulder - 0.6 * atr
                                    and abs(x["price"] - z["price"]) <= tol):
                                trs = [p for p in highs
                                       if int(x["index"]) < int(p["index"]) < int(z["index"])]
                                if len(trs) >= 2:
                                    nkl = sum(p["price"] for p in trs) / len(trs)
                                    if nkl - y["price"] > 1.2 * atr:
                                        item = {"type": "INV_HEAD_SHOULDERS", "shape": "single",
                                                "lines": [_line(int(trs[0]["index"]), n, nkl, "HIGH")],
                                                "pivots": [x, trs[0], y, trs[-1], z],
                                                "entry_side": "BELOW",
                                                "measured": round(nkl - y["price"], 8),
                                                "neckline": float(nkl)}
                        out.append(item)
        # CUP & HANDLE (+inverted): rounded base = far-apart equal extremes with
        # a shallow middle, then a small pullback (handle) near the rim.
        if len(highs) >= 2 and len(df) >= 60:
            a, b = highs[0], highs[-1]
            if int(b["index"]) - int(a["index"]) >= 30 \
                    and abs(a["price"] - b["price"]) <= 1.2 * tol:
                seg_l = [p for p in lows if int(a["index"]) < int(p["index"]) < int(b["index"])]
                if seg_l:
                    base = min(p["price"] for p in seg_l)
                    depth = float(a["price"]) - base
                    rim = min(a["price"], b["price"])
                    if depth > 1.5 * atr:
                        handle = [p for p in lows if int(p["index"]) > int(b["index"])
                                  and p is not b]
                        handle_depth = (float(df["high"].iloc[int(b["index"]):n + 1].max())
                                        - float(df["low"].iloc[int(b["index"]):n + 1].min()))
                        if handle_depth <= 0.5 * depth:   # shallow handle (O'Neil ≤⅓–½)
                            item = {"type": "CUP_HANDLE", "shape": "single",
                                    "lines": [_line(int(b["index"]), n, rim, "HIGH")],
                                    "pivots": [a, {"index": int(seg_l[len(seg_l) // 2]["index"]),
                                                   "price": base}, b],
                                    "entry_side": "BELOW",
                                    "measured": round(depth, 8),
                                    "neckline": float(rim)}
                            out.append(item)
    except Exception:
        return out
    return out
