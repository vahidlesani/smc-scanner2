"""R28 execution-integrity layer.

This module is deliberately independent from Telegram, public identifiers and
the five setup cores.  It provides causal context/evidence plus the execution
price/risk layer described by R28.  Callers may consume its metadata without
changing publication templates or lineage IDs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import math


TF_STOP_FLOOR_PCT = {
    "1m": 0.20, "3m": 0.25, "5m": 0.30, "15m": 0.45,
    "30m": 0.55, "1h": 0.75, "2h": 0.90, "4h": 1.20, "1d": 2.00,
}

SETUP_ENTRY_MODES = {
    "LSR": "RETEST",
    "BOS1": "RETEST",
    "TLR": "RETEST",
    "SDR": "RETEST",
    "IFVG": "RETEST",
    "PINVAL": "REJECTION",
    "PINWALLQ": "REJECTION",
    "ALBROX": "CLOSE_BREAK",
    "TLBREAK": "CLOSE_BREAK",
    "TECHCLASSIC": "CLOSE_BREAK",
    "SPOTBREAK": "CLOSE_BREAK",
}

ONE_NATURE_DIRECTION = {
    "WEDGE_RISING": "SHORT",
    "WEDGE_FALLING": "LONG",
    "TRIANGLE_ASCENDING": "LONG",
    "TRIANGLE_DESCENDING": "SHORT",
    "CHANNEL_ASCENDING": "LONG",
    "CHANNEL_DESCENDING": "SHORT",
    "FLAG_BULL": "LONG",
    "FLAG_BEAR": "SHORT",
    "BULL_FLAG": "LONG",
    "BEAR_FLAG": "SHORT",
}

@dataclass(frozen=True)
class TrendContext:
    direction: str = "NEUTRAL"
    strength: int = 0
    structure: str = "RANGING"
    momentum: str = "NEUTRAL"
    volatility_regime: str = "NORMAL"
    HTF_alignment: str = "UNKNOWN"
    MTF_alignment: str = "UNKNOWN"
    trend_quality: int = 0
    conflict: bool = False
    evidence: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction, "strength": int(self.strength),
            "structure": self.structure, "momentum": self.momentum,
            "volatility_regime": self.volatility_regime,
            "HTF_alignment": self.HTF_alignment,
            "MTF_alignment": self.MTF_alignment,
            "trend_quality": int(self.trend_quality),
            "conflict": bool(self.conflict), "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class ConfirmationEvidence:
    confirmed: bool
    mode: str
    direction: str
    body_ratio: float = 0.0
    close_location: float = 0.5
    wick_ratio: float = 0.0
    range_vs_normal: float = 0.0
    follow_through: bool = False
    volume_confirmation: Optional[bool] = None
    displacement_quality: float = 0.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confirmed": self.confirmed, "mode": self.mode,
            "direction": self.direction, "body_ratio": self.body_ratio,
            "close_location": self.close_location, "wick_ratio": self.wick_ratio,
            "range_vs_normal": self.range_vs_normal,
            "follow_through": self.follow_through,
            "volume_confirmation": self.volume_confirmation,
            "displacement_quality": self.displacement_quality,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class EntryDecision:
    valid: bool
    mode: str
    entry: float
    quality: int
    reason: str = ""


@dataclass(frozen=True)
class StopDecision:
    valid: bool
    initial_stop: float
    structural_invalidation: float
    structure_reference: float
    buffer: float
    stop_distance_abs: float
    stop_distance_pct: float
    risk_R: float
    stop_quality: str
    stop_reason: str
    stop_regime: str
    risk_valid: bool


@dataclass(frozen=True)
class TargetDecision:
    valid: bool
    tp1: float
    tp2: float
    runner_target: float
    target_type: str
    target_quality: str
    obstruction: str
    projected_R: float
    target_reason: str


@dataclass
class TrailingState:
    initial_stop: float
    current_stop: float
    risk_R: float
    tp1_hit: bool = False
    tp2_hit: bool = False
    highest_since_entry: float = 0.0
    lowest_since_entry: float = 0.0
    atr: float = 0.0
    atr_multiplier: float = 1.5
    structure_stop: float = 0.0
    chandelier_stop: float = 0.0
    profit_floor: float = 0.0
    regime: str = "PRE_TP1"

    def update(self, direction: str, current_price: float, fee_buffer: float = 0.0,
               slippage_buffer: float = 0.0, min_gap_pct: float = 0.0010) -> Dict[str, Any]:
        d = str(direction or "").upper()
        px = float(current_price or 0.0)
        if px <= 0:
            return {"new_stop": self.current_stop, "reason": "KEEP_PREVIOUS_STOP",
                    "regime": self.regime}
        gap = max(px * float(min_gap_pct), abs(self.atr) * 0.05)
        old = float(self.current_stop)
        candidates = []
        if d == "LONG":
            self.highest_since_entry = max(float(self.highest_since_entry or px), px)
            if self.structure_stop > 0:
                candidates.append(self.structure_stop)
            if self.atr > 0:
                self.chandelier_stop = self.highest_since_entry - self.atr_multiplier * self.atr
                candidates.append(self.chandelier_stop)
            if self.tp1_hit:
                net_be = self.initial_stop + max(self.risk_R, 0.0) * 0.0
                net_be = max(net_be, self.initial_stop + float(fee_buffer) + float(slippage_buffer))
                self.profit_floor = max(self.profit_floor, net_be)
                candidates.append(self.profit_floor)
                self.regime = "NET_BREAKEVEN" if not self.tp2_hit else "RUNNER_TRAIL"
            else:
                self.regime = "PRE_TP1"
            candidate = max([old] + candidates)
            if candidate >= px - gap:
                return {"new_stop": old, "reason": "KEEP_PREVIOUS_STOP",
                        "regime": self.regime}
            self.current_stop = max(old, candidate)
        elif d == "SHORT":
            self.lowest_since_entry = min(float(self.lowest_since_entry or px), px)
            if self.structure_stop > 0:
                candidates.append(self.structure_stop)
            if self.atr > 0:
                self.chandelier_stop = self.lowest_since_entry + self.atr_multiplier * self.atr
                candidates.append(self.chandelier_stop)
            if self.tp1_hit:
                net_be = min(self.initial_stop, self.initial_stop - float(fee_buffer) - float(slippage_buffer))
                self.profit_floor = min(self.profit_floor or net_be, net_be)
                candidates.append(self.profit_floor)
                self.regime = "NET_BREAKEVEN" if not self.tp2_hit else "RUNNER_TRAIL"
            else:
                self.regime = "PRE_TP1"
            candidate = min([old] + candidates)
            if candidate <= px + gap:
                return {"new_stop": old, "reason": "KEEP_PREVIOUS_STOP",
                        "regime": self.regime}
            self.current_stop = min(old, candidate)
        else:
            return {"new_stop": old, "reason": "KEEP_PREVIOUS_STOP",
                    "regime": self.regime}
        return {"new_stop": float(self.current_stop), "reason": "RATCHET",
                "regime": self.regime}


def _last_closed(df) -> Optional[Mapping[str, Any]]:
    try:
        if df is None or len(df) == 0:
            return None
        row = df.iloc[-1]
        return {str(k): row[k] for k in row.index}
    except Exception:
        return None


def _atr_like(df, period: int = 14) -> float:
    try:
        if df is None or len(df) < 2:
            return 0.0
        h = [float(x) for x in df["high"].tail(period)]
        l = [float(x) for x in df["low"].tail(period)]
        return sum(max(a - b, 0.0) for a, b in zip(h, l)) / max(len(h), 1)
    except Exception:
        return 0.0


def _causal_slope(df, lookback: int = 20) -> float:
    try:
        closes = [float(x) for x in df["close"].tail(lookback)]
        if len(closes) < 4 or closes[0] <= 0:
            return 0.0
        return (closes[-1] - closes[0]) / closes[0] * 100.0
    except Exception:
        return 0.0


def build_trend_context(frames: Mapping[str, Any], trigger_tf: str) -> TrendContext:
    """Causal context: only the last closed bar of each supplied frame is used."""
    tf = str(trigger_tf or "").lower()
    ordered = [k for k in ("1d", "4h", "1h", "15m", "5m", "3m", "1m") if k in frames]
    slopes = {k: _causal_slope(frames[k]) for k in ordered}
    local = slopes.get(tf, 0.0)
    htf_keys = [k for k in ordered if _tf_rank(k) > _tf_rank(tf)]
    mtf_keys = [k for k in ordered if _tf_rank(k) < _tf_rank(tf)]
    hvals = [slopes[k] for k in htf_keys if abs(slopes[k]) > 1e-9]
    mvals = [slopes[k] for k in mtf_keys if abs(slopes[k]) > 1e-9]
    direction = "LONG" if local > 0.15 else "SHORT" if local < -0.15 else "NEUTRAL"
    signs = [1 if x > 0 else -1 for x in slopes.values() if abs(x) > 0.15]
    conflict = bool(signs and max(signs) != min(signs))
    structure = "RANGING" if abs(local) < 0.15 else ("UPTREND" if local > 0 else "DOWNTREND")
    strength = min(100, int(abs(local) * 20.0))
    momentum = "BULLISH" if local > 0.30 else "BEARISH" if local < -0.30 else "NEUTRAL"
    vol = _atr_like(frames.get(tf))
    try:
        price = float(frames[tf]["close"].iloc[-1])
        vol_pct = vol / price * 100.0 if price > 0 else 0.0
    except Exception:
        vol_pct = 0.0
    volatility = "HIGH" if vol_pct >= 2.0 else "LOW" if vol_pct <= 0.4 else "NORMAL"
    h_align = "ALIGNED" if hvals and all((x > 0) == (local > 0) for x in hvals) else "CONFLICT" if hvals else "UNKNOWN"
    m_align = "ALIGNED" if mvals and all((x > 0) == (local > 0) for x in mvals) else "CONFLICT" if mvals else "UNKNOWN"
    quality = max(0, min(100, int(strength * 0.45 + (25 if h_align == "ALIGNED" else 0) +
                                  (20 if m_align == "ALIGNED" else 0) +
                                  (10 if not conflict else 0))))
    evidence = tuple(
        [f"{k}:slope={slopes[k]:+.3f}%" for k in ordered]
        + [f"volatility={volatility}", f"conflict={conflict}"]
    )
    return TrendContext(direction, strength, structure, momentum, volatility,
                        h_align, m_align, quality, conflict, evidence)


def _tf_rank(tf: str) -> int:
    return {"1m": 1, "3m": 2, "5m": 3, "15m": 4, "30m": 5, "1h": 6,
            "2h": 7, "4h": 8, "1d": 9}.get(str(tf).lower(), 0)


def pattern_context(candidate: Any) -> Dict[str, Any]:
    md = getattr(candidate, "metadata", {}) or {}
    kind = str(md.get("pattern_type") or md.get("viva_pattern") or "NONE").upper()
    direction = str(getattr(candidate, "direction", "") or "").upper()
    break_direction = str(md.get("break_direction") or "").upper()
    role = str(md.get("pattern_role") or "UNKNOWN").upper()
    approach = str(md.get("approach_direction") or "UNKNOWN").upper()
    legal = True
    natural = ONE_NATURE_DIRECTION.get(kind)
    if natural and break_direction in {"UP", "DOWN"}:
        legal = (natural == ("LONG" if break_direction == "UP" else "SHORT"))
    return {
        "pattern_type": kind,
        "pattern_id": md.get("pattern_id", ""),
        "pattern_role": role,
        "approach_direction": approach,
        "upper_edge": md.get("pattern_upper_edge", md.get("viva_break_line", 0.0)),
        "lower_edge": md.get("pattern_lower_edge", 0.0),
        "upper_touch_count": md.get("upper_touch_count", md.get("tl_touches", 0)),
        "lower_touch_count": md.get("lower_touch_count", md.get("tl_touches", 0)),
        "convergence": md.get("convergence", md.get("viva_structure_score", 0.0)),
        "parallelism": md.get("parallelism", 0.0),
        "age": md.get("pattern_age", 0),
        "quality": md.get("pattern_quality", md.get("viva_final_score", 0.0)),
        "break_quality": md.get("break_quality", {}),
        "retest_quality": md.get("retest_quality", {}),
        "break_direction": break_direction,
        "legal_direction": legal,
        "direction": direction,
        "evidence": md.get("pattern_evidence", []),
    }


def edge_event(event: str, side: str, *, closed: bool = False, valid: bool = True) -> Dict[str, Any]:
    """Independent upper/lower edge observation; no edge is collapsed."""
    return {
        "event": str(event).upper(), "side": str(side).upper(),
        "closed": bool(closed), "valid": bool(valid),
        "executable": bool(closed and valid and event in {"BREAK_CLOSED", "RETEST", "REJECTION"}),
    }


def _candle_metrics(row: Mapping[str, Any]) -> Tuple[float, float, float, float, float]:
    o, h, l, c = map(float, (row["open"], row["high"], row["low"], row["close"]))
    rng = max(h - l, 1e-12)
    body = abs(c - o)
    close_loc = (c - l) / rng
    wick = max(h - max(o, c), min(o, c) - l) / rng
    return rng, body / rng, close_loc, wick, c - o


def confirm_closed_candle(row: Mapping[str, Any], direction: str, mode: str,
                          edge: Optional[float] = None, normal_range: float = 0.0) -> ConfirmationEvidence:
    rng, body_ratio, close_loc, wick_ratio, signed_body = _candle_metrics(row)
    d = str(direction or "").upper()
    side_ok = signed_body > 0 if d == "LONG" else signed_body < 0
    edge_ok = True if edge is None else (float(row["close"]) > float(edge) if d == "LONG"
                                         else float(row["close"]) < float(edge))
    range_vs = rng / normal_range if normal_range > 0 else 1.0
    displacement = min(1.0, max(0.0, (body_ratio - 0.25) / 0.50))
    rejection = wick_ratio >= 0.45 and body_ratio <= 0.55
    if mode == "REJECTION_CONFIRMATION":
        confirmed = side_ok and rejection
    elif mode == "DISPLACEMENT_CONFIRMATION":
        confirmed = side_ok and edge_ok and body_ratio >= 0.45
    elif mode == "STRUCTURE_RECLAIM":
        confirmed = edge_ok and side_ok
    else:
        confirmed = edge_ok and side_ok
    return ConfirmationEvidence(
        confirmed=bool(confirmed), mode=str(mode), direction=d,
        body_ratio=body_ratio, close_location=close_loc, wick_ratio=wick_ratio,
        range_vs_normal=range_vs, follow_through=False,
        displacement_quality=displacement,
        reason="closed-candle confirmation" if confirmed else "closed-candle evidence insufficient",
    )


def resolve_entry(candidate: Any) -> EntryDecision:
    md = getattr(candidate, "metadata", {}) or {}
    setup = str(getattr(candidate, "setup_code", "") or "").upper()
    mode = str(md.get("entry_mode") or SETUP_ENTRY_MODES.get(setup, "SETUP_DEFINED")).upper()
    entry = float(getattr(candidate, "planned_entry", 0.0) or 0.0)
    if entry <= 0:
        return EntryDecision(False, mode, entry, 0, "entry is missing")
    if mode == "CURRENT_PRICE" and md.get("structural_entry_required", False):
        return EntryDecision(False, mode, entry, 0, "CURRENT_PRICE is not legal for structural entry")
    quality = 100
    if md.get("entry_distance_to_invalidation") is not None:
        try:
            if float(md["entry_distance_to_invalidation"]) <= 0:
                return EntryDecision(False, mode, entry, 0, "entry is at invalidation")
        except Exception:
            return EntryDecision(False, mode, entry, 0, "invalid entry geometry")
    return EntryDecision(True, mode, entry, quality, "setup-defined entry mode")


def structural_stop(entry: float, direction: str, stop: float,
                    trigger_tf: str, *, invalidation: float = 0.0,
                    structure_reference: float = 0.0, buffer: float = 0.0,
                    risk_limit_pct: Optional[float] = None) -> StopDecision:
    e, s = float(entry or 0), float(stop or 0)
    d = str(direction or "").upper()
    dist = abs(e - s) if e > 0 and s > 0 else 0.0
    pct = dist / e * 100.0 if e > 0 else 0.0
    side_ok = (d == "LONG" and 0 < s < e) or (d == "SHORT" and s > e > 0)
    floor = float(TF_STOP_FLOOR_PCT.get(str(trigger_tf or "").lower(), 0.45))
    floor_ok = pct >= floor
    invalid_ok = True
    if invalidation > 0:
        invalid_ok = (s < invalidation) if d == "LONG" else (s > invalidation)
    quality = "STRUCTURAL_GOOD" if side_ok and floor_ok and invalid_ok else "INVALID"
    if side_ok and not floor_ok:
        quality = "TOO_TIGHT"
    elif side_ok and floor_ok and risk_limit_pct is not None and pct > float(risk_limit_pct):
        quality = "RISK_INVALID"
    regime = "STRUCTURAL" if structure_reference > 0 or invalidation > 0 else "FALLBACK"
    risk_r = 1.0
    return StopDecision(side_ok and floor_ok and invalid_ok and quality != "RISK_INVALID",
                        s, invalidation, structure_reference, float(buffer), dist, pct,
                        risk_r, quality,
                        "structural invalidation / timeframe floor" if side_ok else "wrong-side or missing stop",
                        regime, quality not in {"INVALID", "TOO_TIGHT", "RISK_INVALID"})


def target_engine(entry: float, direction: str, stop: float,
                   tp1: float, tp2: float, runner_target: float = 0.0,
                   target_type: str = "TP_EXECUTION", obstruction: str = "") -> TargetDecision:
    e, s, t1, t2 = map(float, (entry or 0, stop or 0, tp1 or 0, tp2 or 0))
    d = str(direction or "").upper()
    risk = abs(e - s)
    valid1 = (t1 > e and d == "LONG") or (t1 < e and d == "SHORT")
    valid2 = (t2 > e and d == "LONG") or (t2 < e and d == "SHORT")
    if not (e > 0 and risk > 0 and valid1 and valid2):
        return TargetDecision(False, t1, t2, float(runner_target or 0), target_type,
                              "INVALID", obstruction, 0.0, "target direction/risk invalid")
    projected = abs(t2 - e) / risk
    if projected <= 0.25:
        return TargetDecision(False, t1, t2, float(runner_target or t2), target_type,
                              "TARGET_TOO_CLOSE", obstruction, projected, "target is too close to entry")
    if obstruction:
        return TargetDecision(False, t1, t2, float(runner_target or t2), target_type,
                              "TARGET_OBSTRUCTED", obstruction, projected, "obstruction is unresolved")
    return TargetDecision(True, t1, t2, float(runner_target or t2), target_type,
                          "STRUCTURAL_GOOD", "", projected, "target uses actual structural stop")


def build_trailing_state(entry: float, stop: float, direction: str, atr: float = 0.0,
                         risk_R: Optional[float] = None) -> TrailingState:
    risk = float(risk_R if risk_R is not None else abs(float(entry) - float(stop)))
    return TrailingState(initial_stop=float(stop), current_stop=float(stop),
                         risk_R=risk, atr=float(atr or 0.0))


def apply_execution_integrity(candidate: Any, frames: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Attach CORE/CONTEXT/EXECUTION state without changing publication fields."""
    frames = frames or {}
    tf = str(getattr(candidate, "trigger_timeframe", "") or "").lower()
    context = build_trend_context(frames, tf) if frames else TrendContext()
    pattern = pattern_context(candidate)
    entry = resolve_entry(candidate)
    stop = structural_stop(float(getattr(candidate, "planned_entry", 0) or 0),
                           str(getattr(candidate, "direction", "") or ""),
                           float(getattr(candidate, "sl", 0) or 0), tf,
                           invalidation=float(pattern.get("lower_edge") or 0)
                           if str(getattr(candidate, "direction", "")).upper() == "LONG"
                           else float(pattern.get("upper_edge") or 0),
                           structure_reference=float(pattern.get("upper_edge") or 0),
                           buffer=0.0)
    target = target_engine(float(getattr(candidate, "planned_entry", 0) or 0),
                           str(getattr(candidate, "direction", "") or ""),
                           float(getattr(candidate, "sl", 0) or 0),
                           float(getattr(candidate, "tp1", 0) or 0),
                           float(getattr(candidate, "tp2", 0) or 0))
    execution_score = 0
    execution_score += 25 if entry.valid else 0
    execution_score += 35 if stop.valid else 0
    execution_score += 30 if target.valid else 0
    execution_score += 10 if context.volatility_regime != "HIGH" else 0
    execution_state = "READY" if entry.valid and stop.valid and target.valid else "INVALID"
    market = str((getattr(candidate, "metadata", {}) or {}).get("market") or "").upper()
    if market == "SPOT" and str(getattr(candidate, "direction", "")).upper() != "LONG":
        execution_state = "INVALID"
    return {
        "CORE_STATE": "VALID",
        "CORE_SCORE": int(getattr(candidate, "score", 0) or 0),
        "CONTEXT_STATE": "AVAILABLE" if frames else "UNKNOWN",
        "CONTEXT_SCORE": int(context.trend_quality),
        "EXECUTION_STATE": execution_state,
        "EXECUTION_SCORE": execution_score,
        "trend_context": context.to_dict(),
        "pattern_context": pattern,
        "entry": {"valid": entry.valid, "mode": entry.mode, "quality": entry.quality, "reason": entry.reason},
        "stop": stop.__dict__,
        "target": target.__dict__,
        "spot_long_only": market != "SPOT" or str(getattr(candidate, "direction", "")).upper() == "LONG",
    }


__all__ = [
    "TrendContext", "ConfirmationEvidence", "EntryDecision", "StopDecision",
    "TargetDecision", "TrailingState", "TF_STOP_FLOOR_PCT", "build_trend_context",
    "pattern_context", "edge_event", "confirm_closed_candle", "resolve_entry",
    "structural_stop", "target_engine", "build_trailing_state",
    "apply_execution_integrity",
]
