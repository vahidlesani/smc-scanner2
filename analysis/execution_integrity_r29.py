"""R29 final execution integration.

This layer sits beside the five existing setup cores. It never creates a CORE
from context alone and never rewrites Telegram/public identity fields.
All geometry is causal: pivots used for decisions are confirmed pivots and
event timestamps never point into the future.

R29 keeps three answers separate:
  CORE       -> does a setup already exist?
  CONTEXT    -> what is the market doing?
  EXECUTION  -> can the existing setup execute now?
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from analysis.indicators import atr, pivots


TF_STOP_FLOOR_PCT = {
    "1m": 0.20, "3m": 0.25, "5m": 0.30, "15m": 0.45,
    "30m": 0.55, "1h": 0.75, "2h": 0.90, "4h": 1.20, "1d": 2.00,
}

MTF_MAP = {"15m": "5m", "1h": "15m", "4h": "1h", "1d": "4h"}
KNOWN_CORES = {"ALBROX", "PINVAL", "PINWALLQ", "TLBREAK", "TECHCLASSIC",
               "LSR", "BOS1", "TLR", "SDR", "IFVG", "P1234"}

EDGE_EVENTS = {
    "EDGE_NEAR", "EDGE_TOUCH", "BREAK_INTRABAR", "BREAK_CLOSED",
    "RETEST", "REJECTION", "INVALIDATION", "TARGET_REACHED",
}


@dataclass(frozen=True)
class CausalPivot:
    index: int
    timestamp: str
    price: float
    kind: str
    confirmation_timestamp: str
    strength: int
    source_tf: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _ts(v: Any) -> str:
    try:
        return pd.Timestamp(v).isoformat()
    except Exception:
        return str(v)


def causal_pivots(df: pd.DataFrame, source_tf: str, left: int = 3,
                  right: int = 3) -> Tuple[CausalPivot, ...]:
    """Return only pivots whose right-side confirmation bars are already closed."""
    if df is None or len(df) < left + right + 1:
        return ()
    highs, lows = pivots(df, left, right)
    out = []
    for kind, points in (("HIGH", highs), ("LOW", lows)):
        for p in points:
            idx = int(p["index"])
            confirm_idx = idx + right
            if confirm_idx >= len(df):
                continue
            out.append(CausalPivot(
                index=idx,
                timestamp=_ts(df["timestamp"].iloc[idx]),
                price=float(p["price"]),
                kind=kind,
                confirmation_timestamp=_ts(df["timestamp"].iloc[confirm_idx]),
                strength=left + right,
                source_tf=str(source_tf),
            ))
    return tuple(sorted(out, key=lambda p: p.index))


def _slope_quality(df: pd.DataFrame, direction: str, lookback: int = 32) -> Tuple[float, str]:
    if df is None or len(df) < 8:
        return 0.0, "INSUFFICIENT_DATA"
    x = np.arange(min(lookback, len(df)), dtype=float)
    close = pd.to_numeric(df["close"].tail(len(x)), errors="coerce").to_numpy()
    if len(close) < 8 or not np.all(np.isfinite(close)):
        return 0.0, "INSUFFICIENT_DATA"
    norm = (close[-1] - close[0]) / max(abs(close[0]), 1e-12) * 100.0
    expected = 1 if str(direction).upper() == "LONG" else -1
    sign = 1 if norm > 0.05 else -1 if norm < -0.05 else 0
    quality = min(100.0, abs(norm) * 25.0)
    if sign == expected:
        quality += 20.0
    elif sign and sign != expected:
        quality *= 0.35
    return max(0.0, min(100.0, quality)), (
        "UPTREND" if sign > 0 else "DOWNTREND" if sign < 0 else "RANGING"
    )


def trend_quality(frames: Mapping[str, Any], trigger_tf: str,
                  direction: str) -> Dict[str, Any]:
    tf = str(trigger_tf or "").lower()
    local_score, structure = _slope_quality(frames.get(tf), direction)
    htf = MTF_MAP.get(tf)
    htf_score, _ = _slope_quality(frames.get(htf), direction) if htf else (0.0, "")
    broader = {"15m": "1h", "1h": "4h", "4h": "1d"}.get(tf)
    broader_score, _ = _slope_quality(frames.get(broader), direction) if broader else (0.0, "")
    aligned = sum(x >= 50 for x in (local_score, htf_score, broader_score))
    conflict = sum(x < 25 for x in (local_score, htf_score, broader_score)) >= 2
    score = int(max(0, min(100, local_score * 0.55 + htf_score * 0.30 + broader_score * 0.15)))
    if aligned >= 2:
        score = min(100, score + 10)
    return {
        "direction": str(direction).upper(),
        "strength": int(local_score),
        "structure": structure,
        "momentum": "BULLISH" if local_score >= 50 and str(direction).upper() == "LONG"
                    else "BEARISH" if local_score >= 50 and str(direction).upper() == "SHORT"
                    else "NEUTRAL",
        "HTF_alignment": "ALIGNED" if htf_score >= 50 else "CONFLICT" if htf_score else "UNKNOWN",
        "MTF_alignment": "ALIGNED" if aligned >= 2 else "CONFLICT" if conflict else "MIXED",
        "trend_quality": score,
        "conflict": bool(conflict),
        "evidence": {
            "local": round(local_score, 2),
            "mtf": round(htf_score, 2),
            "htf": round(broader_score, 2),
        },
    }


def _local_base(df: pd.DataFrame, direction: str, bars: int = 10) -> Dict[str, Any]:
    """Find a compact causal base immediately before the latest impulse."""
    if df is None or len(df) < 24:
        return {"valid": False, "reason": "INSUFFICIENT_DATA"}
    a = atr(df)
    if pd.isna(a.iloc[-1]) or float(a.iloc[-1]) <= 0:
        return {"valid": False, "reason": "ATR_UNAVAILABLE"}
    av = float(a.iloc[-1])
    recent = df.tail(min(28, len(df))).reset_index(drop=True)
    ranges = (recent["high"] - recent["low"]).astype(float)
    candidates = []
    for width in range(3, min(bars, len(recent) - 3) + 1):
        base = recent.iloc[-width-1:-1]
        if base.empty:
            continue
        lo, hi = float(base["low"].min()), float(base["high"].max())
        span = hi - lo
        if 0 < span <= 1.75 * av:
            impulse = recent.iloc[-1]
            signed = float(impulse["close"]) - float(impulse["open"])
            expected = signed > 0 if direction == "LONG" else signed < 0
            if expected:
                compression = float(base["high"].sub(base["low"]).mean()) / av
                candidates.append((span, -compression, lo, hi, width))
    if not candidates:
        return {"valid": False, "reason": "NO_COMPACT_BASE"}
    span, neg_comp, lo, hi, width = sorted(candidates)[0]
    return {
        "valid": True, "bottom": lo, "top": hi, "span": span,
        "bars": int(width), "compression_atr": round(-neg_comp, 3),
        "impulse_direction": direction,
        "source": "LOCAL_TRIGGER_TF",
    }


def pattern_edges(candidate: Any, frame: Optional[pd.DataFrame]) -> Dict[str, Any]:
    md = getattr(candidate, "metadata", {}) or {}
    pattern_id = str(md.get("pattern_id") or md.get("viva_pattern") or
                       md.get("tl_pattern") or md.get("pattern_type") or "NONE")
    events = []
    edge = md.get("viva_break_line", md.get("viva_breakout_line",
                         md.get("viva_watch_line", md.get("structure_level", 0))))
    try:
        edge = float(edge or 0)
        price = float(getattr(candidate, "planned_entry", 0) or 0)
        av = float(atr(frame).iloc[-1]) if frame is not None and len(frame) >= 20 else 0.0
        if edge > 0 and price > 0 and av > 0:
            distance = abs(price - edge) / av
            events.append("EDGE_TOUCH" if distance <= 0.20 else
                          "EDGE_NEAR" if distance <= 0.75 else "EDGE_NEAR")
        if md.get("viva_state") == "S2_BREAKOUT_CLOSED" or md.get("viva_state") == "S2_BREAKOUT":
            events.append("BREAK_CLOSED")
        if md.get("viva_state") == "S0_WATCH":
            events.append("EDGE_NEAR")
        if md.get("touched") is True:
            events.append("RETEST")
    except Exception:
        pass
    return {
        "pattern_id": pattern_id,
        "events": list(dict.fromkeys(e for e in events if e in EDGE_EVENTS)),
        "edge": edge,
        "role": str(md.get("pattern_role") or "UNKNOWN"),
        "approach": str(md.get("approach_direction") or "UNKNOWN"),
    }


def _target_check(candidate: Any, frame: Optional[pd.DataFrame], direction: str) -> Dict[str, Any]:
    entry = float(getattr(candidate, "planned_entry", 0) or 0)
    t1 = float(getattr(candidate, "tp1", 0) or 0)
    t2 = float(getattr(candidate, "tp2", 0) or 0)
    if entry <= 0 or t1 <= 0 or t2 <= 0:
        return {"valid": False, "reason": "TARGET_INVALID", "target_type": "TP_EXECUTION"}
    risk = abs(entry - float(getattr(candidate, "sl", 0) or 0))
    if risk <= 0:
        return {"valid": False, "reason": "RISK_INVALID", "target_type": "TP_EXECUTION"}
    good_side = (t1 > entry and t2 > entry) if direction == "LONG" else (t1 < entry and t2 < entry)
    if not good_side:
        return {"valid": False, "reason": "TARGET_WRONG_SIDE", "target_type": "TP_EXECUTION"}
    if abs(t2 - entry) / max(entry, 1e-12) < 0.0025:
        return {"valid": False, "reason": "TARGET_TOO_CLOSE", "target_type": "TP_EXECUTION"}
    # Nearby opposite pivots are an obstruction, not a silent rewrite.
    obstruction = ""
    if frame is not None and len(frame) >= 20:
        ph, pl = causal_pivots(frame, str(getattr(candidate, "trigger_timeframe", "")))
        levels = [p.price for p in (ph if direction == "LONG" else pl)
                  if (p.price > entry if direction == "LONG" else p.price < entry)]
        nearer = min(levels, key=lambda x: abs(x-entry), default=0.0)
        if nearer:
            # If a structural level sits materially before TP2, flag it.
            if abs(nearer-entry) + 1e-12 < abs(t2-entry) * 0.75:
                obstruction = f"OPPOSITE_STRUCTURE@{nearer:g}"
    return {
        "valid": not obstruction,
        "reason": "TARGET_OBSTRUCTED" if obstruction else "OK",
        "target_type": "TP_EXECUTION",
        "target_price": t2,
        "target_distance_pct": abs(t2-entry) / entry * 100.0,
        "target_R": abs(t2-entry) / risk,
        "obstruction": obstruction,
    }


def execution_gate(candidate: Any, frames: Mapping[str, Any]) -> Dict[str, Any]:
    direction = str(getattr(candidate, "direction", "") or "").upper()
    tf = str(getattr(candidate, "trigger_timeframe", "") or "").lower()
    entry = float(getattr(candidate, "planned_entry", 0) or 0)
    sl = float(getattr(candidate, "sl", 0) or 0)
    if entry <= 0 or sl <= 0:
        return {"state": "BLOCKED", "score": 0, "reasons": ["GEOMETRY_MISSING"]}
    side_ok = (direction == "LONG" and sl < entry) or (direction == "SHORT" and sl > entry)
    if not side_ok:
        return {"state": "BLOCKED", "score": 0, "reasons": ["STOP_WRONG_SIDE"]}
    stop_pct = abs(entry - sl) / entry * 100.0
    floor = TF_STOP_FLOOR_PCT.get(tf, 0.45)
    reasons = []
    if stop_pct + 1e-9 < floor:
        reasons.append("STOP_TOO_TIGHT")
    target = _target_check(candidate, frames.get(tf), direction)
    if not target["valid"]:
        reasons.append(target["reason"])
    market = str((getattr(candidate, "metadata", {}) or {}).get("market") or
                 getattr(candidate, "market", {}).get("market") or "").upper()
    if market == "SPOT" and direction != "LONG":
        reasons.append("SPOT_SHORT_ILLEGAL")
    if stop_pct > 12.0:
        reasons.append("STOP_TOO_WIDE")
    score = 100
    score -= 35 if "STOP_TOO_TIGHT" in reasons else 0
    score -= 45 if "STOP_TOO_WIDE" in reasons else 0
    score -= 30 if any(x.startswith("TARGET_") for x in reasons) else 0
    blocked = bool(reasons)
    return {
        "state": "BLOCKED" if blocked else "READY",
        "score": max(0, score),
        "reasons": reasons,
        "stop_distance_pct": stop_pct,
        "stop_floor_pct": floor,
        "target": target,
    }


@dataclass
class ProfessionalTrailingEngine:
    entry: float
    initial_stop: float
    current_stop: float
    risk_R: float
    tp1: float
    tp2: float
    tp1_hit: bool = False
    tp2_hit: bool = False
    highest_since_entry: float = 0.0
    lowest_since_entry: float = 0.0
    atr_value: float = 0.0
    atr_multiplier: float = 1.5
    structure_stop: float = 0.0
    chandelier_stop: float = 0.0
    profit_floor: float = 0.0
    regime: str = "PRE_TP1"

    def update(self, direction: str, price: float, fee_buffer: float = 0.0,
               slippage_buffer: float = 0.0) -> Dict[str, Any]:
        d = str(direction or "").upper()
        px = float(price or 0)
        old = float(self.current_stop)
        if px <= 0 or old <= 0:
            return {"new_stop": old, "reason": "GEOMETRY_MISSING", "regime": self.regime}
        if d == "LONG":
            self.highest_since_entry = max(float(self.highest_since_entry or px), px)
            if self.tp1_hit:
                be = self.entry + float(fee_buffer) + float(slippage_buffer)
                self.profit_floor = max(self.profit_floor, be)
                self.regime = "NET_BREAKEVEN" if not self.tp2_hit else "RUNNER_TRAIL"
                candidates = [self.profit_floor]
                if self.structure_stop > 0:
                    candidates.append(self.structure_stop)
                if self.atr_value > 0:
                    self.chandelier_stop = self.highest_since_entry - self.atr_multiplier * self.atr_value
                    candidates.append(self.chandelier_stop)
                new = max([old] + candidates)
            else:
                self.regime = "PRE_TP1"
                # Never move to BE before TP1. Structure/chandelier may tighten
                # only if they remain safely below current market price.
                candidates = [old]
                if self.structure_stop > 0:
                    candidates.append(self.structure_stop)
                new = max(candidates)
            if new >= px:
                new = old
            self.current_stop = max(old, min(new, px - max(self.atr_value * 0.05, px * 0.0005)))
        elif d == "SHORT":
            self.lowest_since_entry = min(float(self.lowest_since_entry or px), px)
            if self.tp1_hit:
                be = self.entry - float(fee_buffer) - float(slippage_buffer)
                self.profit_floor = min(self.profit_floor or be, be)
                self.regime = "NET_BREAKEVEN" if not self.tp2_hit else "RUNNER_TRAIL"
                candidates = [self.profit_floor]
                if self.structure_stop > 0:
                    candidates.append(self.structure_stop)
                if self.atr_value > 0:
                    self.chandelier_stop = self.lowest_since_entry + self.atr_multiplier * self.atr_value
                    candidates.append(self.chandelier_stop)
                new = min([old] + candidates)
            else:
                self.regime = "PRE_TP1"
                candidates = [old]
                if self.structure_stop > 0:
                    candidates.append(self.structure_stop)
                new = min(candidates)
            if new <= px:
                new = old
            self.current_stop = min(old, max(new, px + max(self.atr_value * 0.05, px * 0.0005)))
        else:
            return {"new_stop": old, "reason": "DIRECTION_INVALID", "regime": self.regime}
        reason = "TP1_NET_BE" if self.tp1_hit and self.current_stop != old else "TRAIL_UPDATE" if self.current_stop != old else "KEEP_PREVIOUS_STOP"
        return {"new_stop": float(self.current_stop), "reason": reason, "regime": self.regime}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def trailing_from_ladder(ladder: Dict[str, Any], candles: Sequence[Mapping[str, Any]],
                         direction: str) -> Dict[str, Any]:
    """Live-path adapter: ratchet an existing v2 ladder without changing its IDs."""
    if not ladder or not candles:
        return {"state": ladder, "events": []}
    if float(ladder.get("entry") or 0) <= 0:
        return {"state": ladder, "events": []}
    frame = pd.DataFrame(candles)
    if frame.empty or not {"high", "low", "close"}.issubset(frame.columns):
        return {"state": ladder, "events": []}
    atr_series = atr(frame)
    atr_value = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0.0
    targets = [float(x) for x in (ladder.get("targets") or [])]
    idx = int(ladder.get("hit_index") or 0)
    tp1 = targets[0] if targets else float(ladder.get("tp1") or 0)
    tp2 = targets[1] if len(targets) > 1 else float(ladder.get("tp2") or 0)
    eng = ProfessionalTrailingEngine(
        entry=float(ladder.get("entry") or 0),
        initial_stop=float(ladder.get("initial_sl") or ladder.get("current_sl") or 0),
        current_stop=float(ladder.get("current_sl") or ladder.get("initial_sl") or 0),
        risk_R=float(ladder.get("risk") or 0),
        tp1=tp1, tp2=tp2, tp1_hit=idx >= 1, tp2_hit=idx >= 2,
        highest_since_entry=float(ladder.get("highest_since_entry") or 0),
        lowest_since_entry=float(ladder.get("lowest_since_entry") or 0),
        atr_value=atr_value,
        structure_stop=float(ladder.get("structure_stop") or 0),
        chandelier_stop=float(ladder.get("chandelier_stop") or 0),
        profit_floor=float(ladder.get("profit_floor") or 0),
        regime=str(ladder.get("r29_regime") or "PRE_TP1"),
    )
    price = float(frame["close"].iloc[-1])
    result = eng.update(direction, price,
                        fee_buffer=float(ladder.get("fee_buffer") or 0),
                        slippage_buffer=float(ladder.get("slippage_buffer") or 0))
    old_stop = float(ladder.get("current_sl") or 0)
    changed = abs(float(result["new_stop"]) - old_stop) > 1e-12
    if changed:
        ladder["current_sl"] = result["new_stop"]
        ladder["r29_trailing_used"] = True
        ladder["r29_reason"] = result["reason"]
    ladder.update({
        "r29_regime": eng.regime,
        "highest_since_entry": eng.highest_since_entry,
        "lowest_since_entry": eng.lowest_since_entry,
        "r29_atr": eng.atr_value,
        "r29_chandelier_stop": eng.chandelier_stop,
        "r29_profit_floor": eng.profit_floor,
    })
    return {"state": ladder, "events": ([{"event": "PROFIT_FLOOR", "reason": result["reason"],
                    "stop": result["new_stop"]}] if changed else [])}


def apply_r29(candidate: Any, frames: Mapping[str, Any]) -> Dict[str, Any]:
    """Attach CORE/CONTEXT/EXECUTION without touching transport identity."""
    setup = str(getattr(candidate, "setup_code", "") or "").upper()
    direction = str(getattr(candidate, "direction", "") or "").upper()
    tf = str(getattr(candidate, "trigger_timeframe", "") or "").lower()
    frame = frames.get(tf)
    core_valid = setup in KNOWN_CORES and any(
        bool(getattr(e, "confirmed", False)) for e in (getattr(candidate, "evidence", []) or [])
    )
    ctx = trend_quality(frames, tf, direction)
    base = _local_base(frame, direction)
    edges = pattern_edges(candidate, frame)
    gate = execution_gate(candidate, frames)
    return {
        "CORE_STATE": "VALID" if core_valid else "OBSERVATION",
        "CORE_SCORE": int(getattr(candidate, "score", 0) or 0),
        "CONTEXT_STATE": "AVAILABLE" if frame is not None else "UNKNOWN",
        "CONTEXT_SCORE": int(ctx["trend_quality"]),
        "EXECUTION_STATE": gate["state"],
        "EXECUTION_SCORE": int(gate["score"]),
        "TrendQuality": ctx,
        "LocalBase": base,
        "PatternEdges": edges,
        "ExecutionGate": gate,
        "causal": True,
    }


__all__ = [
    "CausalPivot", "causal_pivots", "trend_quality", "pattern_edges",
    "execution_gate", "ProfessionalTrailingEngine", "trailing_from_ladder",
    "apply_r29", "TF_STOP_FLOOR_PCT", "KNOWN_CORES",
]