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

# candle-count search ladder — no hard cap: 60…400 (his 90/200/300 examples)
COUNT_LADDER = (70, 90, 110, 140, 170, 200, 240, 280, 320, 360, 400)
MIN_N, MAX_N = 60, 400
SNAP_TOL_BARS = 2


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
               confirmed: bool = False) -> Optional[Dict[str, float]]:
    """Pick candle count + log-space price window. None = caller falls back."""
    if frame is None or getattr(frame, "empty", True) or len(frame) < MIN_N:
        return None
    md = getattr(candidate, "metadata", None) or {}
    pats = patterns if patterns is not None else (md.get("render_patterns") or [])
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
    if n_max < MIN_N:
        return None
    anchors = _pattern_anchors(pats)
    live = float(close_all[-1])
    atr = float((frame["high"].astype(float) - frame["low"].astype(float)).tail(14).mean() or 0.0)
    med_range = float((frame["high"].astype(float) - frame["low"].astype(float)).median() or 0.0)
    tool_lo = min(tool) if tool else None
    tool_hi = max(tool) if tool else None
    best: Optional[Dict[str, float]] = None
    best_score = -1e18
    for n in COUNT_LADDER:
        if n < MIN_N or n > n_max:
            continue
        w_hi = float(hi_all[-n:].max())
        w_lo = float(lo_all[-n:].min())
        lo = w_lo if tool_lo is None else min(w_lo, tool_lo)
        hi = w_hi if tool_hi is None else max(w_hi, tool_hi)
        if lo <= 0 or hi <= lo:
            continue
        # ── log-space window with the directional clean band ──
        lg_lo, lg_hi = math.log10(lo), math.log10(hi)
        span = lg_hi - lg_lo
        base = 0.045 * span
        band = 0.14 * span + (0.05 * span if tool else 0.0)
        if is_long:                      # tool targets live ABOVE → headroom top
            y_lo = 10 ** (lg_lo - base)
            y_hi = 10 ** (lg_hi + base + band)
        else:                            # short → clean band at the BOTTOM
            y_lo = 10 ** (lg_lo - base - band)
            y_hi = 10 ** (lg_hi + base)
        yspan = y_hi - y_lo
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
        else:
            width = 0.5
        width_score = math.exp(-((width - 0.45) ** 2) / (2 * 0.25 ** 2))
        edge = _pattern_edge_y(pats, idx[-1])
        if edge and atr > 0:
            reaction = math.exp(-abs(live - edge) / (3.0 * atr))
        else:
            reaction = 0.6
        fill = (w_hi - w_lo) / yspan                     # candles vs panel
        # margins must breathe: a window whose candles+tool touch both edges
        # is the squashed «له شده» picture he rejects
        fill_score = 1.0 if fill <= 0.93 else max(0.0, 1.0 - (fill - 0.93) * 6)
        # needle guard: the MEDIAN candle must own a visible share of the
        # panel height (سوزنی نشه); a deep old wick drags yspan and needles
        # every candle — that window loses here
        needle = med_range / yspan if yspan > 0 else 0.0
        candle_score = 0.0 if needle < 0.008 else (
            1.0 if needle >= 0.015 else (needle - 0.008) / 0.007)
        tool_score = 1.0
        if tool and yspan > 0:
            tshare = (tool_hi - tool_lo) / yspan
            tool_score = 1.0 if tshare <= 0.80 else max(0.0, 1.0 - (tshare - 0.80) * 4)
        score = (2.0 * in_frac + 1.5 * width_score + 1.5 * reaction
                 + fill_score + candle_score + tool_score)
        if score > best_score:
            best_score = score
            best = {"n": float(n), "y_lo": y_lo, "y_hi": y_hi,
                    "score": score, "long": 1.0 if is_long else 0.0}
    return best
