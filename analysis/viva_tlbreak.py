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
