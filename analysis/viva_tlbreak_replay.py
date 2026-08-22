"""Walk-forward replay for isolated VIVA-TLBREAK research.

The evaluator only sees candles available at each step. This prevents
look-ahead in pivot/line/retest validation and produces a reviewable event log.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import pandas as pd


@dataclass(frozen=True)
class ReplayEvent:
    index: int
    timestamp: str
    state: str
    pattern: str
    score: float
    reason: str


def walk_forward(frame: pd.DataFrame, evaluator: Callable[[pd.DataFrame], object], *, warmup: int = 120) -> list[ReplayEvent]:
    """Call evaluator on progressively closed data only."""
    events: list[ReplayEvent] = []
    for i in range(max(warmup, 1), len(frame)):
        window = frame.iloc[: i + 1].copy()
        result = evaluator(window)
        if result is None:
            continue
        state = str(getattr(result, "state", "WATCH"))
        pattern = str(getattr(result, "pattern", "NONE"))
        score = float(getattr(result, "final_score", getattr(result, "score", 0)) or 0)
        reason = str(getattr(result, "disqualified_reason", "") or "")
        events.append(ReplayEvent(i, str(window["timestamp"].iloc[-1]), state, pattern, score, reason))
    return events
