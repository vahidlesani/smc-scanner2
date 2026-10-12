"""R73 SMART-ZOOM ENGINE (Viva 2026-10-12) — «موتور زوم هوشمند».

His verbatim dictation (abridged): «رندر نباید دیزاین چارت‌های من رو تغییر بده …
بکگراند، رنگ کندلها، رنگ خطوط، اندازه قاب چارت کندلها، لوگوهای من در واترمارک و
پایین صفحه … پرپچوال زومش کاملا غلط بود .. باید بهترین پیوتها رو انتخاب بکنه و
بعدش کندلها رو هم از نظر ارتفاع هم از نظر تعداد در حدی انتخاب بکنه که همه جای
ابزار لانگ شورت باشه هم بهترین شکل پترن یا ترندلاین رسم بشه .. نه اینکه کل ارتفاع
چارت رو از سقف تا کف بیاره .. باید لگاریتمی باشه .. اگر شورت است … جای ابزار بمونه
پایین نه ابزار له بشه نه کندلها له بشن یا نباید از چارت بیرون بزنن .. اگر لانگ هم
هست برعکس .. شاید جایی نیاز باشه ۹۰ تا کندل باشه .. یه جا ۲۰۰ تا .. یه جا ۳۰۰ تا
پس نباید محدودیت بذاریم .. باید موتور بهترین حالت رو انتخاب بکنه که قیمت به
واکنش به اون پترن یا ترندلاین نزدیک باشه» plus: «زوم ترندها و ترندلاین‌های سینگل
نباید روی هوا شروع بشن بلکه باید بشینه روی پیوت .. چه بادی چه شدو».

What lives here (pure functions, no rendering, no design tokens touched):

``snap_points_to_pivots(frame, points)``
    A stored line point is moved OFF mid-air onto the candle it belongs to:
    the bar at the point's own timestamp (±2 bars) and the nearest of that
    bar's high/low (wicks) or open/close (body). Deterministic in the bar's
    timestamp, so a locked chain's picture is identical on every zoom/update
    (R72 law holds) while old floating endpoints heal on the next render.

``solve_zoom(frame, candidate, ...)``
    TradingView-style pan/zoom solved offline. Searches the candle COUNT
    (60…400, NO hard cap — 90/200/300 whichever wins) and the PRICE WINDOW in
    log10 space so that: the whole long/short tool is inside, no candle of the
    window is cut or squashed, the pattern owns a good share of the width,
    live price sits near its reaction to the pattern/trendline, and the
    tool's target side keeps a clean band (LONG → headroom on TOP, SHORT →
    on the BOTTOM). Returns ``{"n", "y_lo", "y_hi"}`` or None (caller falls
    back to the old window law — production-fallback rule).

Design invariants (background, candle/line palette, frame size, brand marks,
the signature mark behind price) are NOT here and must never be touched by
this module.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

# candle-count search ladder — no hard cap of its own: 70…400 (his 90/200/265/
# 290/300 examples); per-market caps apply in solve_zoom (perp intraday ≤320)
COUNT_LADDER = (70, 90, 110, 140, 170, 200, 240, 265, 290, 320, 350, 400)
MIN_N, MAX_N = 60, 400
SNAP_TOL_BARS = 2

# ── his 10-12 numeric laws (verbatim quantities) ──
WIDTH_FILL_MIN = 0.75      # candles own ≥75-80% of the plot WIDTH …
RIGHT_GAP_MAX = 0.20       # … i.e. the gap price-axis→live candle ≤20%
HEIGHT_FILL_MAX = 0.70     # candles own ≤65-70% of the panel HEIGHT …
HEIGHT_FILL_TARGET = 0.64
TOOL_BAND_MIN = 0.25       # … and 25-30% stays the clean tool band
PERP_INTRADAY_CAP = 320    # 15m…4h perp: never 300-350+ candles («لایو بی‌اهمیت»)
PERP_INTRADAY_TFS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h"}


# ────────────────────────── pivot snap ──────────────────────────

def _bar_index_for_ts(idx: pd.DatetimeIndex, ts: pd.Timestamp) -> Optional[int]:
    if len(idx) == 0:
        return None
    pos = int(idx.searchsorted(ts))
    best, best_d = None, None
    for cand in (pos - 1, pos, pos + 1):
        if 0 <= cand < len(idx):
            d = abs((idx[cand] - ts).total_seconds())
            if best_d is None or d < best_d:
                best, best_d = cand, d
    if best is None:
        return None
    # ±2 bars tolerance, but never reach across a different TF's bar step
    step = (idx[-1] - idx[-2]).total_seconds() if len(idx) > 1 else 1.0
    if best_d > SNAP_TOL_BARS * max(step, 1.0):
        return None
    return best


def snap_points_to_pivots(frame: pd.DataFrame, points: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Move floating line endpoints onto real pivots (wick OR body).

    Pure & deterministic: the snap target depends only on the historical bar
    at the point's stored timestamp, never on the window around it.
    """
    out: List[Dict[str, Any]] = []
    if frame is None or getattr(frame, "empty", True) or not points:
        return [dict(p) for p in (points or [])]
    try:
        idx = pd.DatetimeIndex(pd.to_datetime(
            frame["timestamp"] if "timestamp" in frame.columns else frame.index))
    except Exception:
        return [dict(p) for p in points]
    for p in points:
        q = dict(p)
        try:
            # render_patterns points carry "ts", viva_*_points carry
            # "timestamp" — the snap speaks both dialects
            _raw = q.get("timestamp") or q.get("ts")
            ts = pd.Timestamp(str(_raw))
            price = float(q.get("price"))
        except Exception:
            out.append(q)
            continue
        i = _bar_index_for_ts(idx, ts)
        if i is None or not math.isfinite(price):
            out.append(q)
            continue
        row = frame.iloc[i]
        try:
            o, h, l, c = (float(row["open"]), float(row["high"]),
                          float(row["low"]), float(row["close"]))
        except Exception:
            out.append(q)
            continue
        pivots = (h, l, c, o)          # wicks first, then body («چه بادی چه شدو»)
        q["price"] = min(pivots, key=lambda v: abs(v - price))
        q["pivot_snapped"] = True
        out.append(q)
    return out


def snap_pattern_commands(patterns: Sequence[Dict[str, Any]], frame: pd.DataFrame) -> List[Dict[str, Any]]:
    out = []
    for pat in patterns or []:
        q = dict(pat)
        lines = q.get("lines")
        if isinstance(lines, list):
            q["lines"] = [dict(ln, points=snap_points_to_pivots(frame, ln.get("points") or []))
                          if isinstance(ln, dict) else ln for ln in lines]
        out.append(q)
    return out


# ────────────────────────── the zoom solver ──────────────────────────

def _tool_levels(candidate) -> List[float]:
    md = getattr(candidate, "metadata", None) or {}
    vals = []
    for attr in ("planned_entry", "entry_zone_bottom", "entry_zone_top", "sl", "tp1", "tp2"):
        try:
            v = float(getattr(candidate, attr, 0) or 0)
            if v > 0 and math.isfinite(v):
                vals.append(v)
        except Exception:
            pass
    for v in (((md.get("target_ladder") or {}).get("targets")) or []):
        try:
            v = float(v or 0)
            if v > 0 and math.isfinite(v):
                vals.append(v)
        except Exception:
            pass
    return vals


def _pattern_anchors(patterns) -> List[pd.Timestamp]:
    ts: List[pd.Timestamp] = []
    for pat in patterns or []:
        for ln in (pat.get("lines") or []):
            for p in (ln.get("points") or []):
                try:
                    ts.append(pd.Timestamp(str(p.get("timestamp") or p.get("ts"))))
                except Exception:
                    pass
    return ts


def _pattern_edge_y(patterns, ts: pd.Timestamp) -> Optional[float]:
    """nearest stored line-point price at/after ts (the reaction edge)."""
    best, best_d = None, None
    for pat in patterns or []:
        for ln in (pat.get("lines") or []):
            for p in (ln.get("points") or []):
                try:
                    pts = pd.Timestamp(str(p.get("timestamp") or p.get("ts")))
                    pr = float(p.get("price"))
                except Exception:
                    continue
                d = abs((pts - ts).total_seconds())
                if best_d is None or d < best_d:
                    best, best_d = pr, d
    return best


def solve_zoom(frame: pd.DataFrame, candidate, patterns=None,
               confirmed: bool = False, is_spot: bool = False,
               chart_tf: str = "", det_n: int = 0) -> Optional[Dict[str, float]]:
    """Pick candle count + log-space price window. None = caller falls back.

    Laws (his 10-12 numbers): candles own >=75% of the WIDTH (right gap to the
    live candle <=20%), <=65-70% of the HEIGHT with a 25-30% clean tool band
    on the direction's target side (LONG candles sit LOW, SHORT candles sit
    HIGH), the whole tool inside, no candle cut, and perp intraday frames
    never exceed 320 candles so the live market stays tangible.
    """
    if frame is None or getattr(frame, "empty", True) or len(frame) < MIN_N:
        return None
    md = getattr(candidate, "metadata", None) or {}
    pats = patterns if patterns is not None else (md.get("render_patterns") or [])
    if is_spot:
        # r37: «اسپات ابزار لانگ و شورت نداره» — the spot picture's only
        # tool is the green box: its top must stay inside the window with a
        # small margin (his GoChart: box on the upper edge, candles below)
        _bx73 = float(md.get("spot_box_top") or 0)
        tool = [_bx73] if _bx73 > 0 else []
    else:
        tool = _tool_levels(candidate)
    direction = str(getattr(candidate, "direction", "") or md.get("direction") or "").upper()
    is_long = direction != "SHORT"
    try:
        idx = pd.DatetimeIndex(pd.to_datetime(
            frame["timestamp"] if "timestamp" in frame.columns else frame.index))
        hi_all = frame["high"].astype(float).to_numpy()
        lo_all = frame["low"].astype(float).to_numpy()
        close_all = frame["close"].astype(float).to_numpy()
    except Exception:
        return None
    n_max = min(MAX_N, len(frame))
    if not is_spot and str(chart_tf).lower() in PERP_INTRADAY_TFS:
        n_max = min(n_max, PERP_INTRADAY_CAP)
    if n_max < MIN_N:
        return None
    # ── WIDTH law: the right margin (future bars after the live candle) may
    # never eat more than 20% of the plot width → count ≥ 4×future
    future = 45 if is_spot else (28 if confirmed else 26)
    n_min = max(MIN_N, int(math.ceil(4.0 * future)))
    if is_spot and str(chart_tf).lower() in ("3d", "1w"):
        n_min = max(n_min, 240)          # his «در ۳ روزه کمی بیشتر باشه»
    anchors = _pattern_anchors(pats)
    live = float(close_all[-1])
    atr = float((frame["high"].astype(float) - frame["low"].astype(float)).tail(14).mean() or 0.0)
    med_range = float((frame["high"].astype(float) - frame["low"].astype(float)).median() or 0.0)
    tool_lo = min(tool) if tool else None
    tool_hi = max(tool) if tool else None
    best: Optional[Dict[str, float]] = None
    best_score = -1e18
    for n in COUNT_LADDER:
        if n < n_min or n > n_max:
            continue
        w_hi = float(hi_all[-n:].max())
        w_lo = float(lo_all[-n:].min())
        if w_lo <= 0 or w_hi <= w_lo:
            continue
        lc_lo, lc_hi = math.log10(w_lo), math.log10(w_hi)
        cr = lc_hi - lc_lo
        if cr <= 0:
            continue
        # ── HEIGHT law: candles ≈66% of the panel, tool band on the side ──
        S = cr / HEIGHT_FILL_TARGET
        if is_long:                     # candles LOW, clean band ABOVE
            lg_lo = lc_lo - 0.06 * S
            lg_hi = lg_lo + S
        else:                           # candles HIGH, clean band BELOW
            lg_hi = lc_hi + 0.06 * S
            lg_lo = lg_hi - S
        if tool_hi is not None and math.log10(tool_hi) > lg_hi:
            lg_hi = math.log10(tool_hi) + 0.02 * S
        if tool_lo is not None and math.log10(tool_lo) < lg_lo:
            lg_lo = math.log10(tool_lo) - 0.02 * S
        y_lo, y_hi = 10 ** lg_lo, 10 ** lg_hi
        yspan = y_hi - y_lo
        fill_h = cr / (lg_hi - lg_lo)    # candle share of the panel HEIGHT
        if fill_h > HEIGHT_FILL_MAX + 0.02:
            continue
        # ── scoring ──
        t0 = idx[-n]
        in_frac = (sum(1 for x in anchors if x >= t0) / len(anchors)) if anchors else 1.0
        if anchors:
            _inw = [x for x in anchors if x >= t0]
            a0 = min(_inw) if _inw else min(anchors)
            a1 = max(anchors)
            bars = max(1.0, (min(a1, idx[-1]) - a0).total_seconds() /
                       max(1.0, (idx[-1] - idx[-n]).total_seconds() / n))
            width = bars / n
        elif det_n:
            # anchor-less families (flags/pennants): the picture is best when
            # the window ≈ the tape the shape was DETECTED on (his 265-290 for
            # BTC 4h = the detection depth, chart ≡ trade window law)
            width = min(1.2, float(det_n) / n)
        else:
            width = 0.5
        width_score = math.exp(-((width - 0.95) ** 2) / (2 * 0.15 ** 2))
        edge = _pattern_edge_y(pats, idx[-1])
        if edge and atr > 0:
            reaction = math.exp(-abs(live - edge) / (3.0 * atr))
        else:
            reaction = 0.6
        # needle guard: the MEDIAN candle must stay visible (سوزنی نشه)
        needle = med_range / yspan if yspan > 0 else 0.0
        candle_score = 0.0 if needle < 0.006 else (
            1.0 if needle >= 0.012 else (needle - 0.006) / 0.006)
        tool_score = 1.0
        if tool and yspan > 0:
            tshare = (tool_hi - tool_lo) / yspan
            tool_score = 1.0 if tshare <= 0.85 else max(0.0, 1.0 - (tshare - 0.85) * 4)
        score = (2.0 * in_frac + 1.5 * width_score + 1.5 * reaction
                 + candle_score + tool_score)
        if score > best_score:
            best_score = score
            best = {"n": float(n), "y_lo": y_lo, "y_hi": y_hi,
                    "score": score, "long": 1.0 if is_long else 0.0,
                    "height_fill": fill_h,
                    "right_gap": future / (n + future)}
    return best
