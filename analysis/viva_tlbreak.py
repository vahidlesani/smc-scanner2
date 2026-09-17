"""Isolated VIVA-TLBREAK personal strategy module.

No existing setup imports this module yet. It is built/tested independently so
PINVAL and all other live strategies remain unchanged until Viva approves the
replay results and explicitly enables it.
"""
from __future__ import annotations

import json
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
    max_fit_residual_atr: float = 0.25
    require_alive: bool = False
    min_score: float = 7.0
    retest_window_trigger_bars_daytrade: int = 16
    retest_window_trigger_bars_swing: int = 24
    extension_cap_atr_daytrade: float = 1.5
    extension_cap_atr_swing: float = 2.0
    min_pattern_bars_daytrade: int = 12
    max_pattern_bars_daytrade: int = 80
    min_pattern_bars_swing: int = 15
    max_pattern_bars_swing: int = 90
    channel_parallel_tolerance_pct: float = 15.0
    triangle_apex_max_progress: float = 0.90


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

    def price_at(self, index: float) -> float:
        return self.slope * float(index) + self.intercept


def _atr(df: pd.DataFrame) -> float:
    value = float((df["high"] - df["low"]).tail(14).mean())
    return value if np.isfinite(value) and value > 0 else 0.0


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
    highs, lows = pivots(df, cfg.pivot_left, cfg.pivot_right)
    pts = highs if side == "HIGH" else lows
    n = len(df) - 1
    if len(pts) < 2:
        return None
    tol = max(cfg.touch_tolerance_atr, 0.12) * atr
    pool = pts[-16:]
    best: Optional[ValidatedLine] = None
    best_score = -1.0
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            x0, y0 = float(pool[i]["index"]), float(pool[i]["price"])
            x1, y1 = float(pool[j]["index"]), float(pool[j]["price"])
            if x1 - x0 < max(20.0, float(cfg.pivot_left) * 4):
                continue
            slope = (y1 - y0) / (x1 - x0)
            intercept = y0 - slope * x0

            def _val(p):
                return slope * float(p["index"]) + intercept

            def _over(p):
                yk = float(p["price"])
                return (side == "HIGH" and yk > _val(p) + tol) or \
                       (side == "LOW" and yk < _val(p) - tol)

            # touches: every pool pivot the line actually passes through
            touching = [q for q in pool if abs(float(q["price"]) - _val(q)) <= tol]
            if len(touching) < cfg.min_touches:
                continue
            fx = min(float(q["index"]) for q in touching)
            lx = max(float(q["index"]) for q in touching)
            # VALID-UNTIL-BROKEN (classic doctrine, Viva 09-17): to the RIGHT
            # of the defining pair no same-side pivot may cross the extended
            # line — a broken line is history, never a live trendline. This
            # is what killed the steep purple watch-line over candles.
            hard = False
            pierces = 0
            break_at: Optional[int] = None
            closes = df["close"].to_numpy()
            if cfg.require_alive:
                # first close that crosses the extended line = the bar where
                # the trend DIED (Viva 09-18: a broken leg-trend is still
                # drawn — but only UP TO its break bar, never past it).
                for kk in range(int(x1) + 1, n + 1):
                    _lv = slope * kk + intercept
                    if side == "HIGH" and float(closes[kk]) > _lv + 0.35 * atr:
                        break_at = kk
                        break
                    if side == "LOW" and float(closes[kk]) < _lv - 0.35 * atr:
                        break_at = kk
                        break
            for q in pool:
                xk = float(q["index"])
                if xk > x1 and _over(q):
                    cand = int(xk)
                    break_at = cand if break_at is None else min(break_at, cand)
                    continue
                if fx < xk < x1 and _over(q):
                    # ONE piercing pivot = the head of a head-&-shoulders —
                    # and H&S shoulders are FLAT by definition. On a sloped
                    # line even a single pierce means the line cuts candles.
                    pierces += 1
                    if pierces > 1 or abs(y1 - y0) >= 0.5 * atr:
                        hard = True
                        break
            if hard:
                continue
            if break_at is not None:
                # BROKEN history line (Viva 09-18, his AAVE blue & LINK red
                # rulings): drawn as the leg's record — must be substantial
                # (3+ touches, 30+ bar span) and must have lived at least 10
                # bars past its last defining pivot before dying.
                if len(touching) < max(cfg.min_touches, 3):
                    continue
                if x1 - fx < 30:
                    continue
                if break_at - x1 < 10:
                    continue
            elif cfg.require_alive:
                # ALIVE line: touched price within the last 40 bars AND its
                # projected edge value still sits near price (no line
                # floating in the air above/below a market that moved on).
                if lx < n - 40:
                    continue
                if abs(slope * n + intercept - float(closes[n])) > 8.0 * atr:
                    continue
            need = max(cfg.min_touches, 3) if pierces else cfg.min_touches
            if len(touching) < need:
                continue
            dev = max(abs(float(q["price"]) - _val(q)) for q in touching) / atr
            if dev > cfg.max_fit_residual_atr:
                continue
            span = x1 - x0
            score = len(touching) * (span ** 0.5) + 0.25 * (x1 / max(1.0, float(n)))
            # a CLEAN classic line (nothing pierces it) always outranks a
            # pierced one — the head exception exists for real H&S only.
            if pierces:
                score *= 0.55
            if break_at is not None:
                score *= 0.80  # a live trend outranks a finished one
            # Viva 09-17 schematics: the trendline of a leg STARTS AT THE LEG
            # EXTREME (peak for highs, trough for lows) — reward such lines.
            _leg = pool[-10:]
            _ext = max((float(q["price"]) for q in _leg), default=y0) if side == "HIGH" \
                else min((float(q["price"]) for q in _leg), default=y0)
            if abs(y0 - _ext) <= tol:
                score *= 2.0
            if score > best_score:
                best_score = score
                best = ValidatedLine(
                    side=side,
                    slope=float(slope),
                    intercept=float(intercept),
                    touch_count=len(touching),
                    fit_residual_atr=float(dev),
                    first_index=int(fx),
                    last_index=int(lx),
                    points=tuple(touching),
                    break_index=break_at,
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
    highs, lows = pivots(df, cfg.pivot_left, cfg.pivot_right)
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
    highs, lows = pivots(df, cfg.pivot_left, cfg.pivot_right)
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
