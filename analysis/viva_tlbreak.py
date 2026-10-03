"""Isolated VIVA-TLBREAK personal strategy module.

No existing setup imports this module yet. It is built/tested independently so
PINVAL and all other live strategies remain unchanged until Viva approves the
replay results and explicitly enables it.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import pandas as pd

from analysis.indicators import pivots

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "strategies" / "viva_tlbreak" / "breakout_strategy_config.json"


@dataclass(frozen=True)
class VivaTLBreakConfig:
    pivot_left: int = 5
    pivot_right: int = 5
    min_touches: int = 3
    touch_tolerance_atr: float = 0.15
    # r57 (his shadow law): "outlier" (futures TRADE default, unchanged) or
    # "bodies" (render/drawing — trend anchors never sit on liquidation wicks)
    wick_policy: str = "outlier"
    max_fit_residual_atr: float = 0.25
    require_alive: bool = False
    recency_bars: int = 40
    edge_atr: float = 8.0
    # r31 (Viva 09-26, PYTH): a substantial line whose close-break is inside
    # this many bars of the right edge stays admissible even when it died
    # soon after its last defining pivot — the tradeable recognition window.
    # r33 (Viva 09-26 LAW, verbatim): «بعد از بریک هم باید بمونه … حداقل
    # ۵۰ کندل بعد از بریک، مگر اینکه ترندلاین معتبر دیگری ارجح باشه» — the
    # window is 50 bars, for recognition AND retest, never 10/12.
    fresh_break_bars: int = 50
    min_score: float = 7.0
    retest_window_trigger_bars_daytrade: int = 16
    retest_window_trigger_bars_swing: int = 24
    extension_cap_atr_daytrade: float = 1.5
    extension_cap_atr_swing: float = 2.0
    min_pattern_bars_daytrade: int = 12
    max_pattern_bars_daytrade: int = 80
    min_pattern_bars_swing: int = 15
    # r32 (Viva 09-26, DASH 1D wedge missed while 1H fired): a wedge leg on
    # the daily structure easily spans >90 bars — the old cap discarded it
    # before scoring. 150 keeps the guard against runaway «patterns».
    max_pattern_bars_swing: int = 150
    channel_parallel_tolerance_pct: float = 15.0
    triangle_apex_max_progress: float = 0.90
    # R16 phase 3 — log-space calibration. On a window whose price span is
    # wider than this, the chart is drawn on a LOG axis; a straight line in
    # price space is a CURVE there and visibly leaves the pivots it was fit
    # through («خط قرمز لنگ در هوا»). Above the threshold the fit itself moves
    # into log10 space so the line touches its pivots on the rendered chart.
    log_fit_min_span: float = 0.03


def load_config(path: Path = DEFAULT_CONFIG) -> VivaTLBreakConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    pivot = raw["pivot_detection"]
    score = raw["scoring_system"]
    profiles = raw["timeframe_profiles"]
    return VivaTLBreakConfig(
        pivot_left=int(pivot["left_bars"]),
        pivot_right=int(pivot["right_bars"]),
        min_touches=int(pivot["min_touches_required_per_line"]),
        touch_tolerance_atr=float(pivot["touch_tolerance_atr_fraction"]),
        max_fit_residual_atr=float(pivot["max_line_fit_residual_atr_fraction"]),
        min_score=float(score["entry_score_threshold"]),
        retest_window_trigger_bars_daytrade=int(profiles["daytrade"]["retest_window_bars_on_trigger_tf"]),
        retest_window_trigger_bars_swing=int(profiles["swing"]["retest_window_bars_on_trigger_tf"]),
        extension_cap_atr_daytrade=float(profiles["daytrade"]["max_extension_atr_multiple_without_retest"]),
        extension_cap_atr_swing=float(profiles["swing"]["max_extension_atr_multiple_without_retest"]),
        min_pattern_bars_daytrade=int(profiles["daytrade"]["min_pattern_length_bars_on_structure_tf"]),
        max_pattern_bars_daytrade=int(profiles["daytrade"]["max_pattern_length_bars_on_structure_tf"]),
        min_pattern_bars_swing=int(profiles["swing"]["min_pattern_length_bars_on_structure_tf"]),
        max_pattern_bars_swing=int(profiles["swing"]["max_pattern_length_bars_on_structure_tf"]),
        channel_parallel_tolerance_pct=float(raw["pattern_types"]["channel"]["parallel_tolerance_pct"]),
        triangle_apex_max_progress=0.90,
        log_fit_min_span=float(os.getenv("TLBREAK_LOG_FIT_MIN_SPAN", "0.03") or 0.03),
    )


@dataclass(frozen=True)
class ValidatedLine:
    side: Literal["HIGH", "LOW"]
    slope: float
    intercept: float
    touch_count: int
    fit_residual_atr: float
    first_index: int
    last_index: int
    points: tuple[dict, ...]
    break_index: int | None = None
    # R16 phase 3: set when the fit ran in log10 space (wide-span window).
    # `slope`/`intercept` stay the LOCAL tangent at `last_index` so every
    # legacy consumer (sign tests, ATR-scaled drift, chord projections) keeps
    # its meaning, while `price_at` returns the calibrated curve value.
    log_fit: bool = False
    log_slope: float = 0.0
    log_intercept: float = 0.0

    def price_at(self, index: float) -> float:
        if self.log_fit:
            return float(10.0 ** (self.log_slope * float(index) + self.log_intercept))
        return self.slope * float(index) + self.intercept

    def tangent_at(self, index: float) -> float:
        """Δprice per bar at `index` (log fits: d/dx of 10**(a x + b))."""
        if not self.log_fit:
            return self.slope
        return float(np.log(10.0) * self.log_slope * self.price_at(index))


def _atr(df: pd.DataFrame) -> float:
    value = float((df["high"] - df["low"]).tail(14).mean())
    return value if np.isfinite(value) and value > 0 else 0.0


# ── R64 SMART-GEOMETRY (Viva 10-02: «زوم هوشمند … اسپایک‌ها وج و مثلث رو خراب
# میکنن … پیوت ۲۰ کندل قبل رو به یک سقف محلی وصل میکنه و اسمش رو ترند میذاره»).
# The fitter judged every pivot with ONE ruler: the mean range of the LAST 14
# bars, in LINEAR price — one liquidation spike inflated it (sloppy lines
# accepted), a flat stretch shrank it (real majors rejected), and on a 2×
# window the same ruler meant half the tolerance at the top of the tape.
# R64 measures touches and residuals with a ROBUST, SCALE-HONEST unit: the
# median candle height of the whole fit window (×2.0 — calibrated on the TC
# replay 09-04..09-24 and the 15m line-break event study, see HANDOFF R64),
# in log10 space whenever the fit itself is in log space — the engine «zooms»
# the way his eye zooms a log chart: spikes shrink to noise, flat candles are
# not magnified into fake precision. Score-only weights (never a gate):
# lines resting on MAJOR pivots (prominence) and anchored on the window's
# real leg extreme beat a short local pair. ``TLBREAK_R64_GEOMETRY=0`` restores
# the legacy ruler/score for a one-switch rollback.
_R64_UNIT_FACTOR = 2.0
_R64_WEIGHTS = True      # prominence / leg-extreme / min-span selection weights
_R64_MIN_SPAN_FRAC = 0.10   # defining pair spans ≥ this share of the window
_R64_LEG_HALF = True        # leg-extreme bonus measured on the window's recent half
# R65: the alternate geometry space (price-linear on a log window, or the
# reverse) is a FALLBACK: when both spaces validate the same pair the chart's
# own space must win, so the alternate carries this weight.
_R65_ALT_SPACE_WEIGHT = 0.88


def _r65_dual_space() -> bool:
    return str(os.getenv("TLBREAK_R65_DUAL_SPACE", "1") or "1").strip().lower() \
        not in ("0", "false", "no", "off")


def _r64_enabled() -> bool:
    return str(os.getenv("TLBREAK_R64_GEOMETRY", "1") or "1").strip().lower() \
        not in ("0", "false", "no", "off")


def _robust_unit(df: pd.DataFrame, use_log: bool) -> float:
    """Median candle height of the window (×_R64_UNIT_FACTOR), log10 units when use_log.
    0.0 when undefined (the caller falls back to the legacy ATR)."""
    try:
        h = df["high"].astype(float).to_numpy()
        l = df["low"].astype(float).to_numpy()
        if use_log:
            ok = (h > 0) & (l > 0) & (h >= l)
            r = np.log10(h[ok] / l[ok])
        else:
            r = h - l
        r = r[np.isfinite(r) & (r > 0)]
        if len(r) < 5:
            return 0.0
        u = float(np.median(r)) * _R64_UNIT_FACTOR
        return u if np.isfinite(u) and u > 0 else 0.0
    except Exception:
        return 0.0


def _pivot_prominence(df: pd.DataFrame, pts: list, side: str, use_log: bool = False,
                      unit: float = 0.0, window: int = 15) -> dict:
    """SWING SIZE of each pivot in ruler units: min(excursion into the pivot,
    reaction out of it) over ``window`` bars each side — the classic «major
    vs minor swing». A trendline touch in a trend still scores (pullback in,
    bounce out); a 2-candle wiggle on a flat tape scores ~1-2. SCORE weight
    only, never a gate."""
    out: dict = {}
    try:
        if unit <= 0:
            return {}
        hi = df["high"].astype(float).to_numpy()
        lo = df["low"].astype(float).to_numpy()
        n = len(hi)
        for q in pts:
            i = int(q["index"])
            if i < 0 or i >= n:
                continue
            y = float(q["price"])
            a0, a1 = max(0, i - window), min(n, i + window + 1)
            if side == "HIGH":
                pre = lo[a0:i].min() if i > a0 else y
                post = lo[i + 1:a1].min() if a1 > i + 1 else y
                far = (y, max(pre, 1e-12)), (y, max(post, 1e-12))
            else:
                pre = hi[a0:i].max() if i > a0 else y
                post = hi[i + 1:a1].max() if a1 > i + 1 else y
                far = (max(pre, 1e-12), y), (max(post, 1e-12), y)
            amps = []
            for top, bot in far:
                if use_log and top > 0 and bot > 0:
                    amps.append(max(0.0, math.log10(top / bot)) / unit)
                else:
                    amps.append(max(0.0, top - bot) / unit)
            # the right edge is not evidence against a fresh pivot
            out[i] = float(amps[0] if a1 <= i + 1 else min(amps))
    except Exception:
        return {}
    return out


def fit_validated_line(
    df: pd.DataFrame,
    side: Literal["HIGH", "LOW"],
    cfg: Optional[VivaTLBreakConfig] = None,
) -> Optional[ValidatedLine]:
    """Classic-doctrine trendline (Viva 09-17 pivot ruling, his hand-drawn
    schematics): a line is defined by TWO MAJOR PIVOTS of the active leg and
    NO same-side pivot between them may cross it (a resistance line lives
    ABOVE every high it spans; a support line BELOW every low).  Extra pivots
    within tolerance add touches; validity = touches x span, recency breaks
    ties.  The old «last-N-pivots polyfit» is what drew lines through candles
    and misplaced wedges — retired here for both render AND trade, with the
    trade gate still demanding cfg.min_touches (3) while render accepts 2."""
    cfg = cfg or load_config()
    atr = _atr(df)
    if atr <= 0:
        return None
    # R16 phase 3 — is this window drawn on a log axis? Same 3% guard the
    # chart obeys (spot is always log; futures go log when the span demands).
    # r50 note: on a log axis a 2-point data-space segment renders
    # SCREEN-straight (matplotlib transforms path vertices only), and this
    # log-fit line's endpoints are exactly those vertices — so the drawn
    # trendline is straight on the CryptoCove log chart with no extra work.
    # R16 phase 3: is this window drawn on a log axis?
    # R66: log_fit_min_span defaults to 0.0 (or env) for universal log fitting,
    # while preserving cfg.log_fit_min_span=99.0 kill switch/opt-out.
    use_log = False
    try:
        _lo = float(df["low"].min())
        _hi = float(df["high"].max())
        if _lo > 0 and (_hi - _lo) / _lo >= float(cfg.log_fit_min_span or 0.0):
            use_log = True
    except Exception:
        use_log = False
    highs, lows = pivots(df, cfg.pivot_left, cfg.pivot_right,
                      wick_noise_filter=True,
                      wick_policy=getattr(cfg, "wick_policy", "outlier") or "outlier")
    pts = highs if side == "HIGH" else lows
    n = len(df) - 1
    if len(pts) < 2:
        return None
    tol = max(cfg.touch_tolerance_atr, 0.12) * atr
    # r57 (his «لیمیت نداریم که فقط ۵۰ تا یا هرچی» — the old 16-pivot pool
    # hid the chart's BEST majors; the whole pivot history competes now, the
    # touches×fit×span score still picks the most valid line).
    pool = pts[-200:]
    # ── R64 smart geometry: robust, scale-honest ruler + major-pivot weights
    r64 = _r64_enabled()
    unit = _robust_unit(df, use_log) if r64 else 0.0
    if unit <= 0:
        r64 = False
    tol_frac = max(cfg.touch_tolerance_atr, 0.12)
    tol_u = tol_frac * unit if r64 else tol          # tolerance in RULER units
    _w64 = bool(r64 and _R64_WEIGHTS)
    _prom = _pivot_prominence(df, pool, side, use_log, unit,
                              window=max(10, 3 * int(cfg.pivot_left))) if _w64 else {}
    _min_pair = max(20.0, float(cfg.pivot_left) * 4)
    if _w64:
        # a «trend» must span a real share of the zoomed window — the 20-bar
        # local pair on a 300-bar chart is what his eye refuses to call a line
        _min_pair = max(_min_pair, float(_R64_MIN_SPAN_FRAC) * float(n))
    if _w64 and _R64_LEG_HALF:
        _half = [q for q in pool if float(q["index"]) >= 0.5 * float(n)]
        _leg_pool = _half if len(_half) >= 10 else pool[-10:]
    else:
        _leg_pool = pool[-10:]

    def _res_u(price: float, line_val: float) -> float:
        """Signed residual (price − line) in ruler units."""
        if r64:
            if use_log and price > 0 and line_val > 0:
                return (math.log10(price) - math.log10(line_val)) / unit
            return (price - line_val) / unit
        return (price - line_val) / tol * tol_frac if tol > 0 else 0.0

    best: Optional[ValidatedLine] = None
    best_score = -1.0

    # ── R65 DUAL-SPACE GEOMETRY (Viva 10-02: «انجین تشخیص ترندلاین‌ها و
    # الگوها اصلا خوب عمل نمی‌کنه و خطاها خیلی زیاده» + «بعضی از ترندها از
    # پیوت اشتباه گرفته شده»). Root cause found by probe: the R64 fit ran in
    # ONE space — log10 whenever the window spanned >3%. A line through
    # PRICE-collinear pivots (three clean descending touches, BTC 1h) then
    # carries a curvature residual of ≈1 candle height, misses the touch
    # tolerance, and the engine publishes NO upper line at all — so it either
    # falls back to a local 2-touch pair (the «wrong pivot» chart) or draws
    # nothing. Every anchor pair is now validated in BOTH spaces (log10 and
    # price) and the space that actually validates the pair wins; a tie goes
    # to the chart's own space, and the alternate space carries a weight so it
    # is a fallback, never a rival. Kill switch: TLBREAK_R65_DUAL_SPACE=0.
    _pidx = np.asarray([float(q["index"]) for q in pool], dtype=float)
    _pprc = np.asarray([float(q["price"]) for q in pool], dtype=float)
    _plog = np.log10(np.clip(_pprc, 1e-12, None))
    _closes = df["close"].to_numpy(dtype=float)
    _unit_lin = unit if not use_log else (_robust_unit(df, False) or tol)
    _unit_log = unit if use_log else 0.0

    def _fit_pair(x0: float, y0: float, x1: float, y1: float, log_space: bool):
        """Validate ONE anchor pair in ONE geometry space → payload or None."""
        if log_space and not (y0 > 0 and y1 > 0):
            return None
        if log_space:
            ls = (math.log10(y1) - math.log10(y0)) / (x1 - x0)
            li = math.log10(y0) - ls * x0
        else:
            ls = li = 0.0
        slope = (y1 - y0) / (x1 - x0)
        intercept = y0 - slope * x0
        _u = _unit_log if log_space else _unit_lin

        def _res_pair(a: float, b: float) -> float:
            """Ruler residual between two prices in THIS space."""
            if r64 and _u > 0:
                if log_space and a > 0 and b > 0:
                    return (math.log10(a) - math.log10(b)) / _u
                return (a - b) / _u
            return (a - b) / tol * tol_frac if tol > 0 else 0.0

        if r64 and _u > 0:
            if log_space:
                res = (_plog - (ls * _pidx + li)) / _u
            else:
                res = (_pprc - (slope * _pidx + intercept)) / _u
            near_mask = np.abs(res) <= tol_frac
            over_mask = (res > tol_frac) if side == "HIGH" else (res < -tol_frac)
        else:
            _vals = (10.0 ** (ls * _pidx + li)) if log_space else (slope * _pidx + intercept)
            res = _pprc - _vals
            near_mask = np.abs(res) <= tol
            over_mask = (res > tol) if side == "HIGH" else (res < -tol)
        # touches: every pool pivot the line actually passes through
        touching: list = []
        _tres: list = []
        for _pos in np.nonzero(near_mask)[0]:
            q = pool[int(_pos)]
            _r = float(res[_pos])
            if touching and float(q["index"]) - \
                    float(touching[-1]["index"]) <= max(2.0, float(cfg.pivot_right)):
                if abs(_r) < abs(_tres[-1]):
                    touching[-1] = q
                    _tres[-1] = _r
            else:
                touching.append(q)
                _tres.append(_r)
        if len(touching) < cfg.min_touches:
            return None
        fx = min(float(q["index"]) for q in touching)
        lx = max(float(q["index"]) for q in touching)
        # VALID-UNTIL-BROKEN (classic doctrine, Viva 09-17): to the RIGHT of
        # the defining pair no same-side pivot may cross the extended line — a
        # broken line is history, never a live trendline. This is what killed
        # the steep purple watch-line over candles.
        break_at: Optional[int] = None
        _right = np.nonzero(over_mask & (_pidx > x1))[0]
        if len(_right):
            break_at = int(min(_pidx[int(_k)] for _k in _right))
        _mid = np.nonzero(over_mask & (_pidx > fx) & (_pidx < x1))[0]
        pierces = int(len(_mid))
        if cfg.require_alive:
            # first close that crosses the extended line = the bar where the
            # trend DIED (Viva 09-18: a broken leg-trend is still drawn — but
            # only UP TO its break bar, never past it).
            _kk = np.arange(int(x1) + 1, n + 1, dtype=float)
            if len(_kk):
                _lv = (10.0 ** (ls * _kk + li)) if log_space else (slope * _kk + intercept)
                _cc = _closes[int(x1) + 1: n + 1]
                if side == "HIGH":
                    _hit = np.nonzero(_cc > _lv + 0.35 * atr)[0]
                else:
                    _hit = np.nonzero(_cc < _lv - 0.35 * atr)[0]
                if len(_hit):
                    _cb = int(_kk[_hit[0]])
                    break_at = _cb if break_at is None else min(break_at, _cb)
        if pierces:
            # ONE piercing pivot = the head of a head-&-shoulders — and H&S
            # shoulders are FLAT by definition. On a sloped line even a single
            # pierce means the line cuts candles.
            _flat_far = (abs(_res_pair(y1, y0)) >= 0.5) if r64 \
                else (abs(y1 - y0) >= 0.5 * atr)
            if pierces > 1 or _flat_far:
                return None
        if break_at is not None:
            # BROKEN history line: must be substantial (3+ touches, 30+ bar
            # span) and must have lived at least 10 bars past its last
            # defining pivot — unless the break is FRESH (r31).
            if len(touching) < max(cfg.min_touches, 3):
                return None
            if x1 - fx < 30:
                return None
            _fresh31 = int(getattr(cfg, "fresh_break_bars", 12) or 12)
            if break_at - x1 < 10 and break_at < n - _fresh31:
                return None
        elif cfg.require_alive:
            # ALIVE line: touched price recently AND its projected edge still
            # sits near price (no line floating in the air).
            if lx < n - cfg.recency_bars:
                return None
            _edge_now0 = (10.0 ** (ls * n + li)) if log_space else (slope * n + intercept)
            if abs(_edge_now0 - float(_closes[n])) > cfg.edge_atr * atr:
                return None
        need = max(cfg.min_touches, 3) if pierces else cfg.min_touches
        if len(touching) < need:
            return None
        dev = (max(abs(v) for v in _tres) if r64
               else (max(abs(v) for v in _tres) / atr))
        if dev > cfg.max_fit_residual_atr:
            return None
        span = x1 - x0
        score = len(touching) * (span ** 0.5) + 0.25 * (x1 / max(1.0, float(n)))
        if _w64 and _prom:
            # majors win: mean prominence of the touches vs the pivot strength
            _pm = [min(20.0, float(_prom.get(int(q["index"]), 4.0))) for q in touching]
            score *= min(1.6, max(0.75, (sum(_pm) / max(1, len(_pm)) / 4.0) ** 0.5))
        if pierces:
            score *= 0.55      # a clean classic line always outranks a pierced one
        if break_at is not None:
            score *= 0.80      # a live trend outranks a finished one
            if int(break_at) >= n - int(getattr(cfg, "fresh_break_bars", 12) or 12):
                score *= 1.6   # a FRESH break IS the event (PYTH 09-26)
        _edge_now2 = (10.0 ** (ls * n + li)) if log_space else (slope * n + intercept)
        if abs(_edge_now2 - float(_closes[n])) <= 2.0 * atr:
            score *= 1.15      # context_score §9: the line price sits near now
        # Viva 09-17 schematics: the trendline of a leg STARTS AT THE LEG
        # EXTREME (peak for highs, trough for lows) — reward such lines.
        # R64: the leg is the zoomed window's recent half, not the last 10
        # fractals — a local high must not earn the leg-extreme bonus.
        _leg = _leg_pool
        _ext = max((float(q["price"]) for q in _leg), default=y0) if side == "HIGH" \
            else min((float(q["price"]) for q in _leg), default=y0)
        if (abs(_res_pair(y0, _ext)) <= tol_frac) if r64 else (abs(y0 - _ext) <= tol):
            score *= 2.0
        return {"score": float(score), "touching": touching, "fx": fx, "lx": lx,
                "dev": float(dev), "break_at": break_at, "ls": float(ls),
                "li": float(li), "slope": float(slope),
                "intercept": float(intercept), "log_space": bool(log_space)}

    _dual = bool(use_log and _r65_dual_space())
    _spaces = (True, False) if _dual else (False,)
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            x0, y0 = float(pool[i]["index"]), float(pool[i]["price"])
            x1, y1 = float(pool[j]["index"]), float(pool[j]["price"])
            if x1 - x0 < _min_pair:
                continue
            # ── R64.1 LIVE-RELEVANCE (his 10-03: «این ترند بی ربط به قیمت چی
            # میکه») — a candidate whose value at the LIVE bar has drifted too
            # far from the live price is archived history, not a working trend
            # (NEAR 12h: a May TL against a 4.7 live). A just-broken edge sits
            # near price, so TC/TLBREAK trades are untouched. Env
            # TL_MAX_LIVE_DRAG (default 0.55; 0 disables).
            _drag_max64 = float(os.getenv("TL_MAX_LIVE_DRAG", "0.55") or "0.55")
            if _drag_max64 > 0:
                _xe64 = float(n - 1)
                _dt64 = max(x1 - x0, 1e-9)
                _cand64 = [y0 + (y1 - y0) * (_xe64 - x0) / _dt64]
                if y0 > 0 and y1 > 0:
                    _ls64 = (math.log10(y1) - math.log10(y0)) / _dt64
                    _cand64.append(10.0 ** (_ls64 * (_xe64 - x0)
                                            + math.log10(y0) - _ls64 * x0))
                _lp64 = float(df["close"].iloc[-1]) if "close" in df else 0.0
                if _lp64 > 0 and all(
                        _v > 0 and abs(_v / _lp64 - 1.0) > _drag_max64
                        for _v in _cand64):
                    continue
            for _log_space in _spaces:
                got = _fit_pair(x0, y0, x1, y1, _log_space)
                if got is None:
                    continue
                _sc = float(got["score"])
                if _dual and _log_space != bool(use_log):
                    _sc *= _R65_ALT_SPACE_WEIGHT     # alternate space = fallback
                if _sc <= best_score:
                    continue
                best_score = _sc
                touching = got["touching"]
                fx, lx = got["fx"], got["lx"]
                break_at = got["break_at"]
                _ls, _li = got["ls"], got["li"]
                slope, intercept = got["slope"], got["intercept"]
                if _log_space:
                    # local tangent at the newest touch: keeps `slope`'s
                    # price-per-bar meaning for every legacy consumer while
                    # price_at() walks the calibrated log curve.
                    _y_last = float(10.0 ** (_ls * max(lx, x1) + _li))
                    _tan = math.log(10.0) * _ls * _y_last
                    _int = _y_last - _tan * max(lx, x1)
                else:
                    _tan, _int = float(slope), float(intercept)
                best = ValidatedLine(
                    side=side,
                    slope=float(_tan),
                    intercept=float(_int),
                    log_fit=bool(_log_space),
                    log_slope=float(_ls),
                    log_intercept=float(_li),
                    touch_count=len(touching),
                    fit_residual_atr=float(got["dev"]),
                    first_index=int(fx),
                    last_index=int(lx),
                    points=tuple(touching),
                    break_index=break_at,
                )
    # ── r61.3-R62 EARLIER-PIVOT LAW (his VVV 10-01: «اگر ترندلاین یا ترندهای
    # الگو به پیوت‌های قبل‌تر هم برخورد می‌کنند باید رسم بشن»): the winning
    # pair may anchor late while an EARLIER same-side pivot already sits on
    # the same line. Absorb the earliest run of collinear pivots (no
    # violating pivot between) — more touches, truer anchor, the chart then
    # starts the line where the market actually built it.
    if best is not None:
        _tol_x = max(cfg.touch_tolerance_atr, 0.12) * atr

        def _lv_at(_x):
            if getattr(best, "log_fit", False):
                return 10.0 ** (float(best.log_slope) * _x + float(best.log_intercept))
            return float(best.slope) * _x + float(best.intercept)

        # R65: the absorber measures with the WINNER's own ruler — a linear
        # (price-space) winner on a log window must not be re-measured with
        # the log ruler, or its collinear head pivots are dropped again.
        _win_log = bool(getattr(best, "log_fit", False))

        def _res_win(a: float, b: float) -> float:
            if r64 and _win_log:
                return _res_u(a, b)
            if r64 and _unit_lin > 0:
                return (a - b) / _unit_lin
            return (a - b) / tol * tol_frac if tol > 0 else 0.0

        if r64:
            # same ruler as the fit: |residual| ≤ tol in robust units
            def _absorb_far(_p, _lv):
                return abs(_res_win(_p, _lv)) > tol_frac

            def _absorb_over(_p, _lv):
                ru = _res_win(_p, _lv)
                return (side == "HIGH" and ru > tol_frac) or (side == "LOW" and ru < -tol_frac)
        else:
            def _absorb_far(_p, _lv):
                return abs(_p - _lv) > _tol_x

            def _absorb_over(_p, _lv):
                return (side == "HIGH" and _p > _lv + _tol_x) or (side == "LOW" and _p < _lv - _tol_x)

        _ext = sorted(list(best.points or ()), key=lambda q: float(q["index"]))
        _head = []
        while True:
            if not _ext:
                break
            _cur_min = min(float(q["index"]) for q in _ext)
            _prev = [q for q in pool if float(q["index"]) < _cur_min - 0.5]
            if not _prev:
                break
            _q = max(_prev, key=lambda q: float(q["index"]))
            if _absorb_far(float(_q["price"]), _lv_at(float(_q["index"]))):
                break
            _bad = [pp for pp in pool
                    if _cur_min - 0.5 > float(pp["index"]) > float(_q["index"])
                    and _absorb_over(float(pp["price"]), _lv_at(float(pp["index"])))]
            if _bad:
                break
            _head.insert(0, _q)
            _ext.insert(0, _q)
            if len(_head) >= 12:
                break
        if _head:
            best = ValidatedLine(
                side=best.side, slope=best.slope, intercept=best.intercept,
                touch_count=best.touch_count + len(_head),
                fit_residual_atr=best.fit_residual_atr,
                first_index=int(min(float(q["index"]) for q in _ext)),
                last_index=best.last_index,
                points=tuple(sorted(_ext, key=lambda q: float(q["index"]))),
                break_index=best.break_index,
                log_fit=bool(getattr(best, "log_fit", False)),
                log_slope=float(getattr(best, "log_slope", 0.0) or 0.0),
                log_intercept=float(getattr(best, "log_intercept", 0.0) or 0.0),
            )
    return best


def classify_pattern(upper: Optional[ValidatedLine], lower: Optional[ValidatedLine], index: int) -> str:
    """Classify only validated geometry; no line means no pattern claim."""
    if upper is None and lower is None:
        return "NONE"
    if upper is None or lower is None:
        return "TRENDLINE"
    width_now = upper.price_at(index) - lower.price_at(index)
    width_then = upper.price_at(max(upper.first_index, lower.first_index)) - lower.price_at(max(upper.first_index, lower.first_index))
    converging = width_now > 0 and width_then > 0 and width_now < 0.85 * width_then
    if not converging:
        return "CHANNEL"
    if upper.slope < 0 < lower.slope:
        return "TRIANGLE_SYMMETRICAL"
    if upper.slope >= 0 and lower.slope >= 0:
        return "WEDGE_RISING"
    if upper.slope <= 0 and lower.slope <= 0:
        return "WEDGE_FALLING"
    return "TRIANGLE"


def fit_viva_breakout_line(df: pd.DataFrame, direction: str, cfg: Optional[VivaTLBreakConfig] = None) -> Optional[dict]:
    """Return a Scanner-2 compatible validated line for live paper alerts."""
    cfg = cfg or load_config()
    side: Literal["HIGH", "LOW"] = "HIGH" if str(direction).upper() == "LONG" else "LOW"
    line = fit_validated_line(df, side, cfg)
    if line is None:
        return None
    highs, lows = pivots(df, cfg.pivot_left, cfg.pivot_right,
                      wick_noise_filter=True)
    opposite = lows if side == "HIGH" else highs
    after = [p for p in opposite if p["index"] > line.first_index]
    if not after:
        return None
    anchor = (min if side == "HIGH" else max)(after, key=lambda p: float(p["price"]))
    n = len(df)
    bound_now = float(anchor["price"] + line.slope * (n - 1 - anchor["index"]))
    line_now = line.price_at(n - 1)
    height = line_now - bound_now if side == "HIGH" else bound_now - line_now
    atr = _atr(df)
    if height < 1.5 * atr or height > 25 * atr:
        return None
    return {
        "a": line.points[0], "b": line.points[-1], "anchor": anchor,
        "slope": line.slope, "line_now": line_now, "line_prev": line.price_at(n - 2),
        "bound_now": bound_now, "height": height, "touches": line.touch_count,
        "forward_touches": 0, "fit_error_atr": line.fit_residual_atr, "atr": atr,
    }

@dataclass(frozen=True)
class BreakoutAssessment:
    direction: str
    line_price: float
    close: float
    body_atr: float
    body_range_ratio: float
    outer_close: bool
    beyond_atr: float
    passed: bool
    score: float
    reasons: tuple[str, ...]


def assess_closed_breakout(
    trigger_df: pd.DataFrame,
    line: ValidatedLine,
    direction: str,
) -> Optional[BreakoutAssessment]:
    """Closed-candle breakout score from the Viva config contract.

    This is deliberately independent from entry/retest. A valid break is only
    state S2; it never becomes an executable signal by itself.
    """
    if len(trigger_df) < 20:
        return None
    atr = _atr(trigger_df)
    if atr <= 0:
        return None
    row = trigger_df.iloc[-1]
    close, opn = float(row["close"]), float(row["open"])
    high, low = float(row["high"]), float(row["low"])
    rng = max(high - low, 1e-12)
    body = abs(close - opn)
    line_price = line.price_at(len(trigger_df) - 1)
    is_long = str(direction).upper() == "LONG"
    beyond = (close - line_price) / atr if is_long else (line_price - close) / atr
    directional = close > opn if is_long else close < opn
    outer_close = (close >= high - 0.30 * rng) if is_long else (close <= low + 0.30 * rng)
    body_ratio = body / rng
    reasons = []
    score = 0.0
    if beyond >= 0.25:
        score += 0.8; reasons.append("close beyond line >= 0.25 ATR")
    if body_ratio >= 0.50:
        score += 0.6; reasons.append("body/range >= 0.50")
    if outer_close:
        score += 0.6; reasons.append("close in outer 30%")
    passed = directional and score >= 1.4
    return BreakoutAssessment(
        direction="LONG" if is_long else "SHORT", line_price=line_price,
        close=close, body_atr=body / atr, body_range_ratio=body_ratio,
        outer_close=outer_close, beyond_atr=beyond, passed=passed,
        score=score, reasons=tuple(reasons),
    )


def structure_score(line: ValidatedLine, cfg: Optional[VivaTLBreakConfig] = None) -> float:
    """0..2 structure-quality score: touch count, residual and pattern span."""
    cfg = cfg or load_config()
    score = 0.0
    if line.touch_count >= 4:
        score += 0.7
    elif line.touch_count >= cfg.min_touches:
        score += 0.4
    if line.fit_residual_atr <= cfg.max_fit_residual_atr:
        score += 0.7
    span = line.last_index - line.first_index
    if span >= cfg.pivot_left * 6:
        score += 0.6
    return min(2.0, score)

@dataclass(frozen=True)
class RetestAssessment:
    retest_index: int
    line_price: float
    rejection_kind: str
    reentry_atr: float
    score: float
    passed: bool


def assess_retest_rejection(
    trigger_df: pd.DataFrame,
    line: ValidatedLine,
    direction: str,
    *,
    breakout_index: int,
    pattern_height: float,
    max_window_bars: int,
) -> Optional[RetestAssessment]:
    """Find first retest of broken line/base and a closed rejection candle."""
    atr = _atr(trigger_df)
    if atr <= 0 or pattern_height <= 0:
        return None
    is_long = str(direction).upper() == "LONG"
    end = min(len(trigger_df), breakout_index + max_window_bars + 1)
    for i in range(breakout_index + 1, end):
        row = trigger_df.iloc[i]
        prev = trigger_df.iloc[i - 1]
        line_price = line.price_at(i)
        touches = float(row["low"]) <= line_price + 0.15 * atr and float(row["high"]) >= line_price - 0.15 * atr
        if not touches:
            continue
        # Retest cannot close deeply back inside the old structure.
        reentry = (line_price - float(row["close"])) if is_long else (float(row["close"]) - line_price)
        if reentry > 0.50 * pattern_height:
            return RetestAssessment(i, line_price, "DEEP_REENTRY", reentry / atr, 0.0, False)
        body = abs(float(row["close"]) - float(row["open"]))
        rng = max(float(row["high"]) - float(row["low"]), 1e-12)
        if is_long:
            pin = float(row["close"]) >= float(row["low"]) + .65 * rng and (min(float(row["open"]), float(row["close"])) - float(row["low"])) >= .55 * rng
            engulf = float(prev["close"]) < float(prev["open"]) and float(row["close"]) > float(row["open"]) and float(row["open"]) <= float(prev["close"])
            close_reclaim = float(row["close"]) >= line_price
        else:
            pin = float(row["close"]) <= float(row["high"]) - .65 * rng and (float(row["high"]) - max(float(row["open"]), float(row["close"]))) >= .55 * rng
            engulf = float(prev["close"]) > float(prev["open"]) and float(row["close"]) < float(row["open"]) and float(row["open"]) >= float(prev["close"])
            close_reclaim = float(row["close"]) <= line_price
        if pin:
            return RetestAssessment(i, line_price, "PIN_REJECTION", reentry / atr, 2.0, True)
        if engulf and body >= .40 * atr:
            return RetestAssessment(i, line_price, "ENGULF_REJECTION", reentry / atr, 2.0, True)
        if close_reclaim and body >= .35 * atr:
            return RetestAssessment(i, line_price, "CLOSE_RECLAIM", reentry / atr, 1.3, True)
    return None


@dataclass(frozen=True)
class MicroBOSAssessment:
    index: int
    level: float
    body_atr: float
    passed: bool


def assess_micro_bos(confirm_df: pd.DataFrame, direction: str, *, not_before_index: int) -> Optional[MicroBOSAssessment]:
    """Closed 5M BOS after rejection; no same-candle hindsight."""
    atr = _atr(confirm_df)
    if atr <= 0:
        return None
    is_long = str(direction).upper() == "LONG"
    for i in range(max(3, not_before_index + 1), len(confirm_df)):
        row = confirm_df.iloc[i]
        prev_window = confirm_df.iloc[max(not_before_index, i - 3):i]
        if prev_window.empty:
            continue
        level = float(prev_window["high"].max()) if is_long else float(prev_window["low"].min())
        body = abs(float(row["close"]) - float(row["open"]))
        directional = float(row["close"]) > float(row["open"]) if is_long else float(row["close"]) < float(row["open"])
        broken = float(row["close"]) > level if is_long else float(row["close"]) < level
        if directional and broken and body >= .40 * atr:
            return MicroBOSAssessment(i, level, body / atr, True)
    return None

@dataclass(frozen=True)
class PatternPlan:
    pattern: str
    direction: str
    breakout_price: float
    pattern_height: float
    stop_anchor: float
    measured_target: float
    structural_target: Optional[float]


def build_pattern_plan(
    df: pd.DataFrame,
    upper: Optional[ValidatedLine],
    lower: Optional[ValidatedLine],
    direction: str,
    *,
    structural_target: Optional[float] = None,
) -> Optional[PatternPlan]:
    """Pattern-specific stop anchor and measured final target.

    No order is created here; this returns geometry consumed later by the
    live candidate builder after retest + 5M BOS are complete.
    """
    if upper is None and lower is None:
        return None
    n = len(df) - 1
    direction = str(direction).upper()
    pattern = classify_pattern(upper, lower, n)
    price = float(df["close"].iloc[-1])
    if upper and lower:
        upper_now, lower_now = upper.price_at(n), lower.price_at(n)
        height = abs(upper_now - lower_now)
    else:
        line = upper or lower
        assert line is not None
        atr = _atr(df)
        height = max(2.0 * atr, abs(float(df["high"].tail(30).max()) - float(df["low"].tail(30).min())) * .25)
    if height <= 0:
        return None
    if direction == "LONG":
        if pattern in {"WEDGE_FALLING", "TRIANGLE", "TRIANGLE_SYMMETRICAL", "CHANNEL"} and lower is not None:
            stop_anchor = min(float(p["price"]) for p in lower.points)
        else:
            stop_anchor = float((lower or upper).points[-1]["price"])
        measured = price + height
        valid_structural = structural_target if structural_target and structural_target > price else None
    else:
        if pattern in {"WEDGE_RISING", "TRIANGLE", "TRIANGLE_SYMMETRICAL", "CHANNEL"} and upper is not None:
            stop_anchor = max(float(p["price"]) for p in upper.points)
        else:
            stop_anchor = float((upper or lower).points[-1]["price"])
        measured = price - height
        valid_structural = structural_target if structural_target and structural_target < price else None
    return PatternPlan(
        pattern=pattern, direction=direction, breakout_price=price,
        pattern_height=height, stop_anchor=stop_anchor,
        measured_target=measured, structural_target=valid_structural,
    )

@dataclass(frozen=True)
class ConfluenceScore:
    volume_score: float
    rsi_score: float
    ema_score: float
    htf_score: float
    counter_trend: bool
    total: float
    reasons: tuple[str, ...]


def line_price_at_time(line: ValidatedLine, timestamp) -> float:
    """Project a refine-TF regression line by time for trigger-TF checks."""
    if len(line.points) < 2:
        return line.price_at(line.last_index)
    first, last = line.points[0], line.points[-1]
    t0 = pd.Timestamp(first["timestamp"]).timestamp()
    t1 = pd.Timestamp(last["timestamp"]).timestamp()
    target = pd.Timestamp(timestamp).timestamp()
    if t1 <= t0:
        return line.price_at(line.last_index)
    price_per_second = (float(last["price"]) - float(first["price"])) / (t1 - t0)
    return float(last["price"]) + price_per_second * (target - t1)


def _ema(values: pd.Series, span: int) -> pd.Series:
    return values.astype(float).ewm(span=span, adjust=False).mean()


def score_confluences(
    structure_df: pd.DataFrame,
    refine_df: pd.DataFrame,
    trigger_df: pd.DataFrame,
    direction: str,
    *,
    counter_requires_full_retest: bool = True,
    retest_score: float = 0.0,
    volume_score: float = 0.0,
) -> ConfluenceScore:
    """Independent score components from Viva config; no global setup changes."""
    from analysis.indicators import rsi, structure_bias, volume_ratio
    is_long = str(direction).upper() == "LONG"
    reasons: list[str] = []
    bias = structure_bias(structure_df, 5).get("bias", "NEUTRAL")
    aligned = bias == ("BULLISH" if is_long else "BEARISH")
    counter = bias in {"BULLISH", "BEARISH"} and not aligned
    htf_score = 1.0 if aligned else 0.0
    if aligned:
        reasons.append("HTF structure aligned")
    elif counter:
        reasons.append("counter-trend breakout")
    ema20 = _ema(refine_df["close"], 20)
    ema50 = _ema(refine_df["close"], 50)
    ema_score = 0.0
    if len(ema20) >= 3:
        slope_ok = ema20.iloc[-1] > ema20.iloc[-3] if is_long else ema20.iloc[-1] < ema20.iloc[-3]
        stack_ok = ema20.iloc[-1] >= ema50.iloc[-1] if is_long else ema20.iloc[-1] <= ema50.iloc[-1]
        if slope_ok and stack_ok:
            ema_score = 0.5
            reasons.append("EMA20/50 refinement aligned")
    r = float(rsi(trigger_df, 14).iloc[-1])
    rsi_score = 0.0
    if (is_long and 50 < r < 75) or ((not is_long) and 25 < r < 50):
        rsi_score = 1.0
        reasons.append(f"RSI={r:.0f} directional non-extreme")
    vr = volume_ratio(trigger_df, 20)
    if vr >= 1.5:
        volume_score = max(volume_score, 1.0)
        reasons.append(f"breakout volume={vr:.2f}x")
    if counter and counter_requires_full_retest and retest_score < 2.0:
        reasons.append("counter-trend requires full retest")
        # Keep visible, but disallow entry at adapter stage.
    total = htf_score + ema_score + rsi_score + volume_score
    return ConfluenceScore(volume_score, rsi_score, ema_score, htf_score, counter, total, tuple(reasons))

@dataclass(frozen=True)
class VivaTLBreakEvaluation:
    pattern: str
    direction: str
    structure_score: float
    breakout: BreakoutAssessment
    retest: Optional[RetestAssessment]
    micro_bos: Optional[MicroBOSAssessment]
    confluence: ConfluenceScore
    plan: Optional[PatternPlan]
    disqualified_reason: str = ""

    @property
    def final_score(self) -> float:
        return min(10.0, self.structure_score + self.breakout.score + (self.retest.score if self.retest and self.retest.passed else 0.0) + self.confluence.total)

    @property
    def ready(self) -> bool:
        return bool(self.retest and self.retest.passed and self.micro_bos and self.micro_bos.passed and not self.disqualified_reason)


def assess_projected_breakout(trigger_df: pd.DataFrame, line: ValidatedLine, direction: str) -> Optional[BreakoutAssessment]:
    """Breakout candle against the refine-TF line projected by timestamp."""
    if len(trigger_df) < 20:
        return None
    atr = _atr(trigger_df)
    if atr <= 0:
        return None
    row = trigger_df.iloc[-1]
    close, opn = float(row["close"]), float(row["open"])
    high, low = float(row["high"]), float(row["low"])
    rng, body = max(high-low, 1e-12), abs(close-opn)
    line_price = line_price_at_time(line, row["timestamp"])
    is_long = str(direction).upper() == "LONG"
    beyond = (close-line_price)/atr if is_long else (line_price-close)/atr
    directional = close > opn if is_long else close < opn
    outer = close >= high-.30*rng if is_long else close <= low+.30*rng
    ratio = body/rng
    score = (0.8 if beyond>=.25 else 0)+(0.6 if ratio>=.50 else 0)+(0.6 if outer else 0)
    reasons = tuple(x for x, ok in (("close beyond projected line",beyond>=.25),("body/range",ratio>=.50),("outer close",outer)) if ok)
    return BreakoutAssessment("LONG" if is_long else "SHORT",line_price,close,body/atr,ratio,outer,beyond,directional and score>=1.4,score,reasons)


def evaluate_viva_tlbreak(
    structure_df: pd.DataFrame,
    refine_df: pd.DataFrame,
    trigger_df: pd.DataFrame,
    confirm_df: pd.DataFrame,
    direction: str,
    *,
    cfg: Optional[VivaTLBreakConfig] = None,
) -> Optional[VivaTLBreakEvaluation]:
    """Composite evaluator for the isolated strategy; still caller-controlled.

    It produces a transparent assessment/candidate input and does not mutate
    any existing scanner or global strategy.
    """
    cfg = cfg or load_config()
    upper = fit_validated_line(refine_df, "HIGH", cfg)
    lower = fit_validated_line(refine_df, "LOW", cfg)
    chosen = upper if str(direction).upper()=="LONG" else lower
    if chosen is None:
        return None
    pattern = classify_pattern(upper, lower, len(refine_df)-1)
    breakout = assess_projected_breakout(trigger_df, chosen, direction)
    if breakout is None:
        return None
    structure = structure_score(chosen, cfg)
    # Retest is assessed on trigger data using a timestamp-projected line;
    # use a temporary line whose index coordinate maps to trigger bars only
    # for the local retest state. Price projection remains time-based above.
    retest = None
    if breakout.passed:
        # We only evaluate the newest closed breakout here; subsequent scans
        # advance the stored candidate state in the adapter layer.
        synthetic = ValidatedLine(chosen.side, 0.0, breakout.line_price, chosen.touch_count, chosen.fit_residual_atr, 0, len(trigger_df)-1, chosen.points)
        retest = assess_retest_rejection(trigger_df, synthetic, direction, breakout_index=len(trigger_df)-2, pattern_height=max(_atr(refine_df)*1.5, abs((upper.price_at(len(refine_df)-1) if upper else 0)-(lower.price_at(len(refine_df)-1) if lower else 0))), max_window_bars=cfg.retest_window_bars_daytrade)
    micro = assess_micro_bos(confirm_df, direction, not_before_index=0) if retest and retest.passed else None
    confluence = score_confluences(structure_df, refine_df, trigger_df, direction, retest_score=retest.score if retest else 0.0)
    plan = build_pattern_plan(refine_df, upper, lower, direction) if breakout.passed else None
    disqualify = ""
    if breakout.beyond_atr > cfg.extension_cap_atr_daytrade:
        disqualify = "OVER_EXTENSION_WITHOUT_RETEST"
    if confluence.counter_trend and (not retest or retest.score < 2.0):
        disqualify = "COUNTER_TREND_RETEST_INCOMPLETE"
    return VivaTLBreakEvaluation(pattern, str(direction).upper(), structure, breakout, retest, micro, confluence, plan, disqualify)


def pattern_length_ok(line: ValidatedLine, style: str, cfg: Optional[VivaTLBreakConfig] = None) -> bool:
    cfg = cfg or load_config()
    span = line.last_index - line.first_index
    if str(style).upper() == "SWING":
        return cfg.min_pattern_bars_swing <= span <= cfg.max_pattern_bars_swing
    return cfg.min_pattern_bars_daytrade <= span <= cfg.max_pattern_bars_daytrade

def pattern_geometry_ok(upper: Optional[ValidatedLine], lower: Optional[ValidatedLine], index: int, cfg: Optional[VivaTLBreakConfig] = None) -> tuple[bool, str]:
    cfg = cfg or load_config()
    pattern = classify_pattern(upper, lower, index)
    if upper is None or lower is None:
        return True, pattern
    if pattern == "CHANNEL":
        denom = max(abs(upper.slope), abs(lower.slope), 1e-12)
        slope_gap = abs(upper.slope - lower.slope) / denom * 100
        return slope_gap <= cfg.channel_parallel_tolerance_pct, pattern
    if pattern.startswith("TRIANGLE"):
        den = upper.slope - lower.slope
        if abs(den) < 1e-12:
            return False, pattern
        apex = (lower.intercept - upper.intercept) / den
        start = max(upper.first_index, lower.first_index)
        progress = (index - start) / max(apex - start, 1e-12)
        return progress <= cfg.triangle_apex_max_progress, pattern
    return True, pattern

def recent_failed_breakout_penalty(trigger_df: pd.DataFrame, line: ValidatedLine, direction: str, lookback: int = 10) -> float:
    """Penalty when price recently broke the same line then closed back inside."""
    if len(trigger_df) < 4:
        return 0.0
    is_long = str(direction).upper() == "LONG"
    start = max(1, len(trigger_df) - lookback - 1)
    was_outside = False
    for i in range(start, len(trigger_df)):
        price = line_price_at_time(line, trigger_df["timestamp"].iloc[i])
        close = float(trigger_df["close"].iloc[i])
        outside = close > price if is_long else close < price
        inside = close <= price if is_long else close >= price
        if was_outside and inside:
            return -1.5
        was_outside = outside
    return 0.0

VIVA_STAGES = ("S0_WATCH", "S1_VALID", "S2_BREAKOUT", "S3_RETEST", "S4_REJECTION", "S5_MICRO_BOS", "S6_CONFIRMED", "S7_CONTINUATION")


def advance_live_state(metadata: dict, row: pd.Series, previous: pd.Series, direction: str, *, zone_low: float, zone_high: float, atr_value: float) -> tuple[str, bool]:
    """Durable per-candidate state transition for live paper lifecycle.

    Simplified for reachability (the original required S3 retest -> S4 rejection
    -> S5 micro-BOS to happen on three *separate* closed bars inside a narrow
    window, which almost never aligned on the confirm TF, so VIVA-TLBREAK never
    confirmed). Now: after the retest, the FIRST decisive directional bar that
    both rejects the zone AND breaks the prior micro-structure confirms; a
    rejection bar and a later micro-BOS bar still confirm via S4->S5.
    """
    state = str(metadata.get("viva_state") or "S2_BREAKOUT")
    lo, hi = sorted((float(zone_low), float(zone_high)))
    touched = float(row["low"]) <= hi and float(row["high"]) >= lo
    body = abs(float(row["close"]) - float(row["open"]))
    rng = max(float(row["high"]) - float(row["low"]), 1e-12)
    is_long = str(direction).upper() == "LONG"
    if state == "S2_BREAKOUT" and touched:
        return "S3_RETEST", False
    if state in ("S3_RETEST", "S4_REJECTION"):
        pin = (float(row["close"]) >= float(row["low"]) + .65*rng and (min(float(row["open"]),float(row["close"]))-float(row["low"])) >= .55*rng) if is_long else (float(row["close"]) <= float(row["high"]) - .65*rng and (float(row["high"])-max(float(row["open"]),float(row["close"]))) >= .55*rng)
        engulf = (float(previous["close"]) < float(previous["open"]) and float(row["close"]) > float(row["open"]) and float(row["open"]) <= float(previous["close"])) if is_long else (float(previous["close"]) > float(previous["open"]) and float(row["close"]) < float(row["open"]) and float(row["open"]) >= float(previous["close"]))
        directional = (float(row["close"]) > float(row["open"])) if is_long else (float(row["close"]) < float(row["open"]))
        bos = (float(row["close"]) > float(previous["high"])) if is_long else (float(row["close"]) < float(previous["low"]))
        rejected = pin or (engulf and body >= .35*atr_value) or directional
        body_ok = body >= .35*atr_value
        # Immediate confirm: decisive directional bar breaking micro-structure
        # while at the retest (covers the common case where rejection and
        # continuation happen on the same confirmation bar).
        if rejected and bos and directional and body_ok:
            return "S5_MICRO_BOS", True
        if rejected:
            return "S4_REJECTION", False
        if state == "S4_REJECTION" and bos and directional and body >= .40*atr_value:
            return "S5_MICRO_BOS", True
    return state, False

@dataclass(frozen=True)
class WatchLine:
    side: Literal["HIGH", "LOW"]
    slope: float
    intercept: float
    first: dict
    last: dict

    def price_at(self, index: float) -> float:
        return self.slope * float(index) + self.intercept


def fit_two_pivot_watch(df: pd.DataFrame, side: Literal["HIGH", "LOW"], cfg: Optional[VivaTLBreakConfig] = None) -> Optional[WatchLine]:
    """Visible 2-pivot watch only; never eligible for entry/confirmation."""
    cfg = cfg or load_config()
    highs, lows = pivots(df, cfg.pivot_left, cfg.pivot_right,
                      wick_noise_filter=True)
    pts = highs if side == "HIGH" else lows
    if len(pts) < 2:
        return None
    first, last = pts[-2], pts[-1]
    span = float(last["index"] - first["index"])
    if span < cfg.pivot_left * 2:
        return None
    slope = (float(last["price"]) - float(first["price"])) / span
    if side == "HIGH" and slope >= 0:
        return None
    if side == "LOW" and slope <= 0:
        return None
    return WatchLine(side, slope, float(first["price"]) - slope * float(first["index"]), first, last)


def classify_pattern_detailed(upper: Optional[ValidatedLine], lower: Optional[ValidatedLine], index: int, cfg: Optional[VivaTLBreakConfig] = None) -> str:
    """Extended pattern subtype classifier for chart/result labels."""
    cfg = cfg or load_config()
    base = classify_pattern(upper, lower, index)
    if upper is None and lower is None:
        return "NONE"
    if upper is None or lower is None:
        line = upper or lower
        assert line is not None
        if abs(line.slope) <= 0.01:
            return "HORIZONTAL_SR"
        return "TRENDLINE"
    scale = max(abs(upper.price_at(index) - lower.price_at(index)), 1e-9)
    flat_upper = abs(upper.slope) <= 0.05 * scale
    flat_lower = abs(lower.slope) <= 0.05 * scale
    if flat_upper and lower.slope > 0:
        return "TRIANGLE_ASCENDING"
    if flat_lower and upper.slope < 0:
        return "TRIANGLE_DESCENDING"
    if base == "CHANNEL":
        return "CHANNEL_DESCENDING" if upper.slope < 0 else "CHANNEL_ASCENDING" if upper.slope > 0 else "CHANNEL_FLAT"
    return base
