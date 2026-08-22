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
    min_score: float = 7.0
    retest_window_trigger_bars_daytrade: int = 16
    retest_window_trigger_bars_swing: int = 24
    extension_cap_atr_daytrade: float = 1.5
    extension_cap_atr_swing: float = 2.0


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
    """Fit a line to >=3 confirmed fractal pivots with ATR residual control."""
    cfg = cfg or load_config()
    atr = _atr(df)
    if atr <= 0:
        return None
    highs, lows = pivots(df, cfg.pivot_left, cfg.pivot_right)
    pts = highs if side == "HIGH" else lows
    if len(pts) < cfg.min_touches:
        return None
    # Find the newest 3+ pivot set that genuinely lies on one line.
    for take in range(min(len(pts), 6), cfg.min_touches - 1, -1):
        chosen = tuple(pts[-take:])
        xs = np.asarray([float(p["index"]) for p in chosen])
        ys = np.asarray([float(p["price"]) for p in chosen])
        if xs[-1] - xs[0] < cfg.pivot_left * 3:
            continue
        slope, intercept = np.polyfit(xs, ys, 1)
        residual = float(np.max(np.abs(ys - (slope * xs + intercept))) / atr)
        if residual > cfg.max_fit_residual_atr:
            continue
        touches = sum(
            1 for p in chosen
            if abs(float(p["price"]) - (slope * float(p["index"]) + intercept)) <= cfg.touch_tolerance_atr * atr
        )
        if touches < cfg.min_touches:
            continue
        return ValidatedLine(
            side=side,
            slope=float(slope),
            intercept=float(intercept),
            touch_count=touches,
            fit_residual_atr=residual,
            first_index=int(chosen[0]["index"]),
            last_index=int(chosen[-1]["index"]),
            points=chosen,
        )
    return None


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
