"""Instrumented walk-forward diagnosis for smc-core-7.0.

Mirrors analysis/backtest.run_style_backtest but records, for every candidate,
exactly where and why it died. Also supports a tunable confirmation profile so
we can test which relaxation actually unlocks trades.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from analysis.indicators import atr, candle_displacement, structure_bias  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402
from analysis.setups_v7 import DETECTORS, scan_setups  # noqa: E402
from analysis.quality_engine import evaluate_confirmation  # noqa: E402
from analysis.backtest import _candidate_key, _simulate_trade, _historical_ticker  # noqa: E402
from data.fetcher import MarketBundle  # noqa: E402
from experiments.okx_feed import load_frames  # noqa: E402


# ---------------------------------------------------------------- config ----


@dataclass
class ConfirmProfile:
    """Tunable confirmation rules. STRICT matches the live engine."""

    name: str = "STRICT"
    body_min_atr: float = 0.35          # trigger candle body / ATR floor
    require_close_beyond_zone_mid: bool = True
    rr1_floor: float = 1.30
    rr2_floor: float = 2.0
    gate_exceptions: tuple = ()         # gated names exempted from execution_ready
    min_score: int = 7
    expiry_hours_swing: int = 36
    expiry_hours_scalp: int = 6
    sl_buffer_atr_swing: float = 0.35   # (informational; SL comes from candidate)
    sl_buffer_atr_scalp: float = 0.25


STRICT = ConfirmProfile(name="STRICT")

PROFILES: Dict[str, ConfirmProfile] = {
    "STRICT": STRICT,
    "BALANCED": ConfirmProfile(
        name="BALANCED",
        body_min_atr=0.25,
        require_close_beyond_zone_mid=False,
        rr1_floor=1.0,
        rr2_floor=1.5,
        expiry_hours_scalp=8,
    ),
    "LOOSE": ConfirmProfile(
        name="LOOSE",
        body_min_atr=0.15,
        require_close_beyond_zone_mid=False,
        rr1_floor=0.8,
        rr2_floor=1.2,
        expiry_hours_scalp=10,
    ),
}


# ------------------------------------------------------- slicing helpers ----


def build_index_map(frame: pd.DataFrame, trigger_ts: pd.Series) -> np.ndarray:
    """For each trigger timestamp, how many rows of frame are <= that ts."""
    ts = pd.to_datetime(frame["timestamp"]).to_numpy()
    tgt = pd.to_datetime(trigger_ts).to_numpy()
    return np.searchsorted(ts, tgt, side="right")


def slice_by_count(frame: pd.DataFrame, count: int, minimum: int = 0, cap: int = 0) -> Optional[pd.DataFrame]:
    if count <= 0:
        return None
    result = frame.iloc[:count]
    if cap and len(result) > cap:
        result = result.iloc[-cap:]
    return result if len(result) >= minimum else None


# ------------------------------------------------ instrumented evaluation ----


@dataclass
class CandidateReport:
    key: Tuple
    style: str
    setup: str
    direction: str
    score: int
    gates_bad_at_creation: List[str]
    detected_at: str
    outcome: str = "?"
    detail: str = ""
    touch_index: Optional[int] = None
    touch_after_expiry_hours: Optional[float] = None
    candles_after_touch: int = 0
    fail_not_directional: int = 0
    fail_no_pattern: int = 0
    fail_weak_body: int = 0
    rr_fail_events: int = 0
    rr_fail_rr1: List[float] = field(default_factory=list)
    rr1_best: float = 0.0
    rr2_best: float = 0.0
    gates_block_events: int = 0
    score_block_events: int = 0
    parity_confirmed: Optional[bool] = None
    trade_result: Optional[str] = None
    trade_pnl: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "style": self.style,
            "setup": self.setup_code if hasattr(self, "setup_code") else self.setup,
            "direction": self.direction,
            "score": self.score,
            "gates_bad_at_creation": ";".join(self.gates_bad_at_creation),
            "detected_at": self.detected_at,
            "outcome": self.outcome,
            "detail": self.detail,
            "candles_after_touch": self.candles_after_touch,
            "fail_not_directional": self.fail_not_directional,
            "fail_no_pattern": self.fail_no_pattern,
            "fail_weak_body": self.fail_weak_body,
            "rr_fail_events": self.rr_fail_events,
            "rr1_best": round(self.rr1_best, 2),
            "rr2_best": round(self.rr2_best, 2),
            "gates_block_events": self.gates_block_events,
            "score_block_events": self.score_block_events,
            "touch_after_expiry_hours": self.touch_after_expiry_hours,
            "parity_confirmed": self.parity_confirmed,
            "trade_result": self.trade_result,
            "trade_pnl": self.trade_pnl,
        }


def _candle_flags(candidate: SignalCandidate, window: pd.DataFrame, profile: ConfirmProfile):
    if len(window) > 90:
        window = window.iloc[-90:]  # ATR warm-up suffices; huge speedup on long frames
    row = window.iloc[-1]
    prev = window.iloc[-2]
    close, open_price = float(row["close"]), float(row["open"])
    prev_high, prev_low = float(prev["high"]), float(prev["low"])
    candle_range = max(float(row["high"]) - float(row["low"]), 1e-12)
    body_top, body_bottom = max(open_price, close), min(open_price, close)
    upper_wick = float(row["high"]) - body_top
    lower_wick = body_bottom - float(row["low"])
    disp = candle_displacement(window, -1)
    body_atr = float(disp["body_atr"])
    zone_mid = candidate.zone_mid

    if candidate.direction == "LONG":
        directional = close > open_price and (close > zone_mid if profile.require_close_beyond_zone_mid else True)
        structure = close > prev_high
        engulfing = open_price <= float(prev["close"]) and close >= float(prev["open"])
        pinbar = lower_wick >= 0.55 * candle_range and upper_wick <= 0.20 * candle_range
    else:
        directional = close < open_price and (close < zone_mid if profile.require_close_beyond_zone_mid else True)
        structure = close < prev_low
        engulfing = open_price >= float(prev["close"]) and close <= float(prev["open"])
        pinbar = upper_wick >= 0.55 * candle_range and lower_wick <= 0.20 * candle_range

    pattern = structure or engulfing or pinbar
    strong_body = body_atr >= profile.body_min_atr
    return directional, pattern, strong_body, close, body_atr


def _rr_at_entry(candidate: SignalCandidate, entry: float) -> Tuple[float, float]:
    risk = abs(entry - candidate.sl)
    if risk <= 0:
        return 0.0, 0.0
    if candidate.direction == "LONG":
        return (candidate.tp1 - entry) / risk, (candidate.tp2 - entry) / risk
    return (entry - candidate.tp1) / risk, (entry - candidate.tp2) / risk


def instrumented_wait(
    candidate: SignalCandidate,
    trigger: pd.DataFrame,
    detection_index: int,
    profile: ConfirmProfile,
    check_parity: bool = False,
) -> Tuple[CandidateReport, Optional[int]]:
    report = CandidateReport(
        key=_candidate_key(candidate),
        style=candidate.style,
        setup=candidate.setup_code,
        direction=candidate.direction,
        score=candidate.score,
        gates_bad_at_creation=[g for g, ok in candidate.mandatory_gates.items() if not ok],
        detected_at=candidate.created_at,
    )
    expiry_hours = profile.expiry_hours_swing if candidate.style == "SWING" else profile.expiry_hours_scalp
    bars_per_hour = 4 if candidate.style == "SWING" else 12
    max_bars = expiry_hours * bars_per_hour
    # watch beyond expiry only to learn "how late did the touch arrive"
    extended_end = min(len(trigger), detection_index + max_bars + 24 * bars_per_hour)
    end = min(len(trigger), detection_index + max_bars + 1)

    touched = bool(candidate.metadata.get("touched", False))
    if touched:
        report.touch_index = detection_index

    for index in range(detection_index + 1, extended_end):
        candle = trigger.iloc[index]
        low, high = float(candle["low"]), float(candle["high"])
        in_expiry = index < end

        if candidate.direction == "LONG" and low <= candidate.sl:
            report.outcome = "KILLED_SL_AFTER_TOUCH" if touched else "KILLED_SL_BEFORE_TOUCH"
            return report, None
        if candidate.direction == "SHORT" and high >= candidate.sl:
            report.outcome = "KILLED_SL_AFTER_TOUCH" if touched else "KILLED_SL_BEFORE_TOUCH"
            return report, None

        if not touched and low <= candidate.entry_zone_top and high >= candidate.entry_zone_bottom:
            touched = True
            report.touch_index = index
            if not in_expiry:
                ts_det = pd.Timestamp(candidate.created_at)
                ts_touch = pd.Timestamp(candle["timestamp"])
                report.touch_after_expiry_hours = round((ts_touch - ts_det).total_seconds() / 3600, 1)
                report.outcome = "TOUCH_AFTER_EXPIRY"
                return report, None

        if not (touched and in_expiry):
            continue

        report.candles_after_touch += 1
        window = trigger.iloc[: index + 1]
        directional, pattern, strong_body, close, body_atr = _candle_flags(candidate, window, profile)
        if not (directional and pattern and strong_body):
            if not directional:
                report.fail_not_directional += 1
            if not pattern:
                report.fail_no_pattern += 1
            if not strong_body:
                report.fail_weak_body += 1
            continue

        rr1, rr2 = _rr_at_entry(candidate, close)
        report.rr1_best = max(report.rr1_best, rr1)
        report.rr2_best = max(report.rr2_best, rr2)
        if rr1 < profile.rr1_floor or rr2 < profile.rr2_floor:
            report.rr_fail_events += 1
            if len(report.rr_fail_rr1) < 200:
                report.rr_fail_rr1.append(round(rr1, 3))
            continue
        gates_ok = all(
            ok for gate, ok in candidate.mandatory_gates.items() if gate not in profile.gate_exceptions
        )
        if not gates_ok:
            report.gates_block_events += 1
            continue
        if candidate.score + 1 < profile.min_score:
            report.score_block_events += 1
            continue

        report.outcome = "CONFIRMED"
        if check_parity:
            twin = SignalCandidate.from_json(candidate.to_json())
            ok, _, _ = evaluate_confirmation(twin, trigger.iloc[: index + 1].copy())
            report.parity_confirmed = bool(ok)
        return report, index

    if report.candles_after_touch > 0:
        report.outcome = "EXPIRED_TOUCHED_NO_TRIGGER"
    elif report.touch_index is None:
        report.outcome = "EXPIRED_NO_TOUCH"
    else:
        report.outcome = "EXPIRED_TOUCHED_NO_TRIGGER"
    return report, None


# ---------------------------------------------------------------- runner ----


def run_diagnosis(symbol: str, style: str, days: int, profile: ConfirmProfile, check_parity: bool) -> Dict:
    frames, trigger_tf = load_frames(symbol, style, days)
    trigger = frames[trigger_tf]
    warmup = 180 if style == "SWING" else 240
    index_maps = {tf: build_index_map(frame, trigger["timestamp"]) for tf, frame in frames.items()}

    seen = set()
    reports: List[CandidateReport] = []
    trades: List[Dict] = []
    funnel = Counter()
    gate_counter = Counter()
    score_hist = Counter()
    bias_counter = Counter()
    context_tf = "4h" if style == "SWING" else "1h"
    pivot_size = 5

    for index in range(warmup, len(trigger) - 5):
        timestamp = trigger["timestamp"].iloc[index]
        funnel["bars_scanned"] += 1
        sliced = {}
        ok = True
        for tf, frame in frames.items():
            count = int(index_maps[tf][index])
            minimum = 60 if tf in ("4h", "1h", "15m", "5m") else 0
            part = slice_by_count(frame, count, minimum)
            if part is None and tf != "1d":
                ok = False
                break
            sliced[tf] = part
        if not ok:
            continue

        bias_here = structure_bias(sliced[context_tf], pivot_size)["bias"]
        bias_counter[bias_here] += 1

        bundle = MarketBundle(symbol=symbol, frames=sliced, ticker=_historical_ticker(sliced.get("1d"), timestamp))
        candidates = scan_setups(bundle, style)
        funnel["bars_with_candidates"] += 1 if candidates else 0
        for candidate in candidates:
            for gate, valid in candidate.mandatory_gates.items():
                if not valid:
                    gate_counter[gate] += 1
            score_hist[candidate.score] += 1
            key = _candidate_key(candidate)
            if key in seen:
                funnel["candidates_deduped"] += 1
                continue
            seen.add(key)
            candidate.created_at = pd.Timestamp(timestamp).isoformat()
            expiry = pd.Timestamp(timestamp) + timedelta(
                hours=profile.expiry_hours_swing if style == "SWING" else profile.expiry_hours_scalp
            )
            candidate.expires_at = expiry.isoformat()
            report, confirmed_index = instrumented_wait(candidate, trigger, index, profile, check_parity)
            reports.append(report)
            if confirmed_index is not None:
                trade = _simulate_trade(candidate, trigger, confirmed_index)
                report.trade_result = trade.result
                report.trade_pnl = round(trade.pnl_pct, 4)
                trades.append(trade)

    outcome_counter = Counter(r.outcome for r in reports)
    sim = {
        "total": len(trades),
        "wins": sum(1 for t in trades if t.pnl_pct > 0),
        "losses": sum(1 for t in trades if t.pnl_pct <= 0),
        "expectancy": round(float(np.mean([t.pnl_pct for t in trades])), 4) if trades else 0.0,
        "total_pnl": round(float(np.sum([t.pnl_pct for t in trades])), 4) if trades else 0.0,
        "avg_bars": round(float(np.mean([t.bars_held for t in trades])), 1) if trades else 0.0,
    }
    return {
        "symbol": symbol,
        "style": style,
        "days": days,
        "profile": profile.name,
        "funnel": dict(funnel),
        "bias_distribution": dict(bias_counter),
        "gates_false_at_creation": dict(gate_counter),
        "score_hist": dict(sorted(score_hist.items())),
        "outcomes": dict(outcome_counter),
        "trades": sim,
        "trigger_fail_stats": {
            "candidates_with_touch": sum(1 for r in reports if r.candles_after_touch > 0),
            "total_candles_after_touch": sum(r.candles_after_touch for r in reports),
            "fail_not_directional": sum(r.fail_not_directional for r in reports),
            "fail_no_pattern": sum(r.fail_no_pattern for r in reports),
            "fail_weak_body": sum(r.fail_weak_body for r in reports),
            "rr_fail_events": sum(r.rr_fail_events for r in reports),
            "gates_block_events": sum(r.gates_block_events for r in reports),
            "score_block_events": sum(r.score_block_events for r in reports),
            "rr1_best_max": max((r.rr1_best for r in reports), default=0),
            "touches_after_expiry": sum(1 for r in reports if r.touch_after_expiry_hours),
        },
        "parity_mismatch": sum(
            1 for r in reports if r.parity_confirmed is not None and not r.parity_confirmed
        ),
        "reports": [r.to_dict() for r in reports],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--style", default="BOTH")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--profile", default="STRICT")
    parser.add_argument("--parity", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    styles = ["SWING", "SCALP"] if args.style.upper() == "BOTH" else [args.style.upper()]
    profile = PROFILES[args.profile.upper()]
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)

    for style in styles:
        if args.refresh:
            load_frames(args.symbol, style, args.days, refresh=True)
        result = run_diagnosis(args.symbol, style, args.days, profile, args.parity)
        out = out_dir / f"diag_{result['symbol']}_{style}_{profile.name}_{args.days}d.json"
        reports = result.pop("reports")
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        pd.DataFrame(reports).to_csv(out_dir / f"diag_{result['symbol']}_{style}_{profile.name}_{args.days}d.csv", index=False)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"\nSaved → {out}")


if __name__ == "__main__":
    main()
