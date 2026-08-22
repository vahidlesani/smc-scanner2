"""Durable state machine for VIVA-TLBREAK candidates.

State is JSON-safe and stored in candidate metadata so monitor cycles can resume
without recomputing/hindsight. A later DB adapter may persist the same payload.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

STAGES = ("S0_WATCH", "S1_VALID", "S2_BREAKOUT", "S3_RETEST", "S4_REJECTION", "S5_MICRO_BOS", "S6_CONFIRMED", "S7_CONTINUATION", "CANCELLED")

@dataclass
class VivaTLState:
    stage: str = "S0_WATCH"
    trigger_bars: int = 0
    retest_bars: int = 0
    continuation_count: int = 0
    breakout_at: str = ""
    retest_at: str = ""
    rejection_at: str = ""
    confirmed_at: str = ""
    cancel_reason: str = ""

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, value: dict[str, Any] | None) -> "VivaTLState":
        raw = value or {}
        return cls(**{k: raw[k] for k in cls.__dataclass_fields__ if k in raw})


def advance(state: VivaTLState, event: str, *, max_retest_bars: int, now: datetime | None = None) -> VivaTLState:
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    if state.stage in {"S6_CONFIRMED", "CANCELLED"}:
        return state
    if event == "VALID_PATTERN" and state.stage == "S0_WATCH":
        state.stage = "S1_VALID"
    elif event == "BREAKOUT" and state.stage in {"S0_WATCH", "S1_VALID"}:
        state.stage, state.breakout_at, state.retest_bars = "S2_BREAKOUT", stamp, 0
    elif event == "BAR" and state.stage == "S2_BREAKOUT":
        state.retest_bars += 1
        if state.retest_bars > max_retest_bars:
            state.stage, state.cancel_reason = "CANCELLED", "RETEST_WINDOW_EXPIRED"
    elif event == "RETEST" and state.stage == "S2_BREAKOUT":
        state.stage, state.retest_at = "S3_RETEST", stamp
    elif event == "REJECTION" and state.stage == "S3_RETEST":
        state.stage, state.rejection_at = "S4_REJECTION", stamp
    elif event == "MICRO_BOS" and state.stage == "S4_REJECTION":
        state.stage, state.confirmed_at = "S5_MICRO_BOS", stamp
    elif event == "CONFIRM" and state.stage == "S5_MICRO_BOS":
        state.stage = "S6_CONFIRMED"
    elif event == "CONTINUATION" and state.stage == "S6_CONFIRMED":
        state.stage, state.continuation_count = "S7_CONTINUATION", state.continuation_count + 1
    elif event == "INVALIDATE":
        state.stage, state.cancel_reason = "CANCELLED", "STRUCTURAL_INVALIDATION"
    return state
