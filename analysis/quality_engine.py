"""Orchestrates separate Swing/Scalp engines and candidate confirmation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

import pandas as pd

from analysis.indicators import atr, candle_displacement
from analysis.models import EvidenceItem, SignalCandidate, iso_now
from analysis.setups_v7 import scan_setups
from config import get_settings
from data.fetcher import MarketBundle

SETTINGS = get_settings()


class SwingEngine:
    name = "SWING"
    required_frames = ("1d", "4h", "1h")

    def scan(self, bundle: MarketBundle) -> List[SignalCandidate]:
        # mid-term swing = TWO trigger streams: 1h and 4h (Viva 09-16)
        from analysis import setups_v7
        out: List[SignalCandidate] = []
        for trig in ("1h", "4h"):
            setups_v7.PROFILE_OVERRIDE["SWING"] = ("1d", "4h", trig)
            try:
                out.extend(scan_setups(bundle, self.name))
            finally:
                setups_v7.PROFILE_OVERRIDE.pop("SWING", None)
        return out


class DayTradeEngine:
    """Viva 09-16: short swing — 4h context, 1h structure, 15m trigger/confirm."""
    name = "DAYTRADE"
    required_frames = ("4h", "1h", "15m")

    def scan(self, bundle: MarketBundle) -> List[SignalCandidate]:
        return scan_setups(bundle, self.name)


class ScalpEngine:
    name = "SCALP"
    required_frames = ("1h", "15m", "5m", "1m")

    def scan(self, bundle: MarketBundle) -> List[SignalCandidate]:
        turnover = float((bundle.ticker or {}).get("turnover24h", 0) or 0)
        spread = float((bundle.ticker or {}).get("spread_pct", 999) or 999)
        if turnover < SETTINGS.scalp_min_turnover_usd or spread > SETTINGS.scalp_max_spread_percent:
            return []
        return scan_setups(bundle, self.name)


class GrandEngine:
    """Viva 2026-09-13: 1D long-term swing stream — pattern on the daily
    chart, context 4H, one closed 4H candle confirms."""
    name = "GRAND"
    required_frames = ("1d", "4h", "1h")

    def scan(self, bundle: MarketBundle) -> List[SignalCandidate]:
        return scan_setups(bundle, self.name)


ENGINES = {"GRAND": GrandEngine(), "SWING": SwingEngine(),
           "DAYTRADE": DayTradeEngine(), "SCALP": ScalpEngine()}


def _live_styles() -> List[str]:
    raw = str(getattr(SETTINGS, "live_styles", "DAYTRADE,SWING") or "")
    styles = [x.strip().upper() for x in raw.split(",") if x.strip() in ENGINES]
    return styles or ["DAYTRADE", "SWING", "GRAND", "SCALP"]


def scan_bundle(bundle: MarketBundle) -> List[SignalCandidate]:
    """Run only the explicitly enabled tiers. Lower TF may still confirm a
    DAYTRADE/SWING entry even while standalone SCALP discovery is paused."""
    candidates: List[SignalCandidate] = []
    for style in _live_styles():
        candidates.extend(ENGINES[style].scan(bundle))
    from analysis.setups_v7 import enrich_candidate_context
    for candidate in candidates:
        try:
            enrich_candidate_context(bundle, candidate)
        except Exception:
            pass
    # R28 execution layer: attach CORE/CONTEXT/EXECUTION evidence only.\n    # This does not alter Telegram templates, link-chain IDs, public codes, or\n    # the five setup cores; it is a separate price/risk layer.\n    try:\n        from analysis.execution_integrity_r28 import apply_execution_integrity\n        for candidate in candidates:\n            try:\n                frames = {}\n                for _tf in (\"1d\", \"4h\", \"2h\", \"1h\", \"30m\", \"15m\", \"5m\", \"3m\", \"1m\"):\n                    try:\n                        _frame = bundle.get(_tf)\n                    except Exception:\n                        _frame = None\n                    if _frame is not None and len(_frame) > 0:\n                        frames[_tf] = _frame\n                candidate.metadata[\"r28_execution\"] = apply_execution_integrity(candidate, frames)\n            except Exception as _r28_exc:\n                # Context is advisory; a tooling failure must never manufacture\n                # a trade or silently rewrite an existing setup decision.\n                candidate.metadata[\"r28_execution_error\"] = str(_r28_exc)[:240]\n\n    # TechnoClassic HTF-edge intelligence — SCORE-ONLY for all setups
    # (Viva 2026-09-10): a tested 1D/4H edge ahead of TP1 costs points, an
    # entry sitting ON such an edge earns them. Never a gate, never a reject.
    try:
        from analysis.pattern_engine import htf_pattern_adjustment
        for candidate in candidates:
            if str(candidate.setup_code) == "TECHCLASSIC":
                continue  # its own geometry is already priced by its detector
            try:
                delta, note = htf_pattern_adjustment(bundle, candidate)
                if delta or note:
                    candidate.score = int(max(0, min(10, candidate.score + delta)))
                    candidate.metadata["htf_edge_delta"] = int(delta)
                    candidate.metadata["htf_edge_note"] = str(note)
            except Exception:
                pass
    except Exception:
        pass