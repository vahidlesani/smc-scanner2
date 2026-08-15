"""Two-phase experiment runner.

Phase `collect`: run the v7 scan loop once per symbol/style (slow, ~15-20 min)
and persist every unique candidate + its detection index to a pickle.

Phase `replay`: re-simulate the confirmation/invalidation phase under different
confirmation profiles (fast) so each relaxation lever can be measured alone.

Also supports `sl_scale` to widen invalidation buffers during collection, which
tests the dominant KILLED_SL_AFTER_TOUCH failure mode.
"""
from __future__ import annotations

import argparse
import pickle
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

import sys

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

import analysis.setups_v7 as setups_mod  # noqa: E402
from analysis.backtest import _historical_ticker, _simulate_trade  # noqa: E402
from analysis.indicators import structure_bias  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402
from analysis.setups_v7 import scan_setups  # noqa: E402
from data.fetcher import MarketBundle  # noqa: E402
from experiments.diagnose_funnel import (  # noqa: E402
    ConfirmProfile,
    build_index_map,
    instrumented_wait,
    slice_by_count,
)
from experiments.okx_feed import load_frames  # noqa: E402

RESULTS = Path(__file__).parent / "results"
RESULTS.mkdir(exist_ok=True)


def _candidate_key_local(candidate: SignalCandidate):
    """Semantic dedup key (robust to capped sliding slices): same structure
    level re-detected on later bars collapses to one candidate."""
    level = float(candidate.metadata.get("structure_level", 0) or 0)
    ref = abs(float(candidate.planned_entry)) or 1.0
    return (
        candidate.style,
        candidate.setup_code,
        candidate.direction,
        round(level / ref, 5),
        round(float(candidate.entry_zone_top - candidate.entry_zone_bottom) / ref, 5),
    )


def enable_sl_scale(scale: float) -> None:
    """Multiply the invalidation buffer (and clearance beyond the liquidity anchor)."""
    if abs(scale - 1.0) < 1e-9:
        return
    original = setups_mod._liquidity_protected_invalidation

    def scaled(trigger_df, poi, direction, atr_value, style, spread_pct=0.0):
        result = original(trigger_df, poi, direction, atr_value, style, spread_pct)
        anchor = float(result["liquidity_anchor"])
        buffer_value = float(result["buffer"]) * scale
        price = anchor - buffer_value if direction == "LONG" else anchor + buffer_value
        return {
            "price": float(price),
            "liquidity_anchor": anchor,
            "buffer": float(buffer_value),
            "protected_pivots": result["protected_pivots"],
        }

    setups_mod._liquidity_protected_invalidation = scaled


def collect(symbol: str, style: str, days: int, sl_scale: float, every_n: int = 1) -> Path:
    enable_sl_scale(sl_scale)
    frames, trigger_tf = load_frames(symbol, style, days)
    trigger = frames[trigger_tf]
    warmup = 180 if style == "SWING" else 240
    index_maps = {tf: build_index_map(frame, trigger["timestamp"]) for tf, frame in frames.items()}
    seen = set()
    detections: List[Dict] = []
    funnel = Counter()

    for index in range(warmup, len(trigger) - 5, max(1, every_n)):
        timestamp = trigger["timestamp"].iloc[index]
        funnel["bars"] += 1
        sliced, ok = {}, True
        for tf, frame in frames.items():
            count = int(index_maps[tf][index])
            cap = {"1d": 0, "4h": 280, "1h": 280, "15m": 340, "5m": 460}.get(tf, 0)
            part = slice_by_count(frame, count, 60 if tf != "1d" else 0, cap=cap)
            if part is None and tf != "1d":
                ok = False
                break
            sliced[tf] = part
        if not ok:
            continue
        bundle = MarketBundle(symbol=symbol, frames=sliced, ticker=_historical_ticker(sliced.get("1d"), timestamp))
        for candidate in scan_setups(bundle, style):
            from config import get_settings as _gs

            if _gs().skip_dead_gate_candidates and not candidate.execution_ready:
                continue  # mirrors the patched live/backtest behaviour
            key = _candidate_key_local(candidate)
            if key in seen:
                continue
            seen.add(key)
            candidate.created_at = pd.Timestamp(timestamp).isoformat()
            expiry_hours = 36 if style == "SWING" else 6
            candidate.expires_at = (pd.Timestamp(timestamp) + timedelta(hours=expiry_hours)).isoformat()
            detections.append({"index": index, "candidate": candidate.to_json()})
        funnel["unique"] = len(detections)

    out = RESULTS / f"detections_{symbol}_{style}_{days}d_sl{sl_scale}_n{every_n}.pkl"
    with out.open("wb") as fh:
        pickle.dump(
            {"symbol": symbol, "style": style, "days": days, "sl_scale": sl_scale, "every_n": every_n, "detections": detections},
            fh,
        )
    print(f"[collect] {symbol} {style} sl_scale={sl_scale} n={every_n}: {dict(funnel)} → {out}", flush=True)
    return out


def _detections_path(symbol: str, style: str, days: int, sl_scale: float, every_n: int = 1) -> Path:
    p = RESULTS / f"detections_{symbol}_{style}_{days}d_sl{sl_scale}_n{every_n}.pkl"
    if not p.exists():
        p = RESULTS / f"detections_{symbol}_{style}_{days}d_sl{sl_scale}.pkl"
    return p


def location_blocker_ids(symbol: str, style: str, days: int, sl_scale: float, every_n: int = 1) -> set:
    """Detection indices whose ONLY htf_alignment blocker is premium/discount.

    i.e. bias aligned + 15m/1h aligned, but price location wrong. Such
    candidates stand for the 'location as info, not gate' experiment.
    """
    from analysis.indicators import premium_discount, structure_bias

    frames, trigger_tf = load_frames(symbol, style, days)
    trigger = frames[trigger_tf]
    context_tf = "4h" if style == "SWING" else "1h"
    lower_tf = "1h" if style == "SWING" else "15m"
    index_maps = {tf: build_index_map(frame, trigger["timestamp"]) for tf, frame in frames.items()}
    pickle_path = _detections_path(symbol, style, days, sl_scale, every_n)
    with pickle_path.open("rb") as fh:
        detections = pickle.load(fh)["detections"]
    result = set()
    for position, det in enumerate(detections):
        candidate = SignalCandidate.from_json(det["candidate"])
        bad = [g for g, ok in candidate.mandatory_gates.items() if not ok]
        if not bad or set(bad) - {"htf_alignment"}:
            continue  # needs other relaxation too; keep for gate-purity
        index = int(det["index"])
        ctx = slice_by_count(frames[context_tf], int(index_maps[context_tf][index]), 30)
        low = slice_by_count(frames[lower_tf], int(index_maps[lower_tf][index]), 30)
        if ctx is None or low is None:
            continue
        expected = "BULLISH" if candidate.direction == "LONG" else "BEARISH"
        if structure_bias(low, 3)["bias"] not in (expected, "NEUTRAL"):
            continue
        location = premium_discount(ctx)["location"]
        location_ok = (
            location in ("DISCOUNT", "EQUILIBRIUM")
            if candidate.direction == "LONG"
            else location in ("PREMIUM", "EQUILIBRIUM")
        )
        if not location_ok:
            result.add(position)
    return result


def replay(symbol: str, style: str, days: int, sl_scale: float, profiles: List[ConfirmProfile], every_n: int = 1) -> None:
    frames, trigger_tf = load_frames(symbol, style, days)
    trigger = frames[trigger_tf]
    pickle_path = _detections_path(symbol, style, days, sl_scale, every_n)
    with pickle_path.open("rb") as fh:
        payload = pickle.load(fh)
    detections = payload["detections"]

    loc_free_ids = None
    if any("LOC" in p.gate_exceptions for p in profiles):
        loc_free_ids = location_blocker_ids(symbol, style, days, sl_scale, every_n)

    for profile in profiles:
        reports, trades = [], []
        for position, det in enumerate(detections):
            candidate = SignalCandidate.from_json(det["candidate"])
            effective = profile
            if "LOC" in profile.gate_exceptions:
                # Per-candidate surgical exception: only records whose sole
                # htf blocker is premium/discount count as execution-ready.
                exc = ("htf_alignment",) if position in (loc_free_ids or set()) else ()
                effective = ConfirmProfile(**{**profile.__dict__, "gate_exceptions": exc})
            report, confirmed_index = instrumented_wait(candidate, trigger, int(det["index"]), effective)
            reports.append(report)
            if confirmed_index is not None:
                trade = _simulate_trade(candidate, trigger, confirmed_index)
                report.trade_result = trade.result
                report.trade_pnl = round(trade.pnl_pct, 4)
                trades.append(trade)

        outcomes = Counter(r.outcome for r in reports)
        pnls = [t.pnl_pct for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        rr1_fails = [v for r in reports for v in r.rr_fail_rr1]
        line = {
            "symbol": symbol, "style": style, "days": days, "sl_scale": sl_scale,
            "profile": profile.name,
            "candidates": len(reports),
            "outcomes": dict(outcomes),
            "trades": len(trades), "wins": wins, "losses": len(trades) - wins,
            "expectancy": round(float(np.mean(pnls)), 4) if pnls else 0.0,
            "total_pnl": round(float(np.sum(pnls)), 4) if pnls else 0.0,
            "avg_bars": round(float(np.mean([t.bars_held for t in trades])), 1) if trades else 0.0,
            "rr1_fail_median": round(float(np.median(rr1_fails)), 3) if rr1_fails else None,
        }
        name = f"replay_{symbol}_{style}_{days}d_sl{sl_scale}_n{every_n}_{profile.name}"
        (RESULTS / f"{name}.json").write_text(__import__("json").dumps(line, indent=2, ensure_ascii=False))
        pd.DataFrame([r.to_dict() for r in reports]).to_csv(RESULTS / f"{name}.csv", index=False)
        print(__import__("json").dumps(line, ensure_ascii=False))


PROFILES_GRID: List[ConfirmProfile] = [
    ConfirmProfile(name="STRICT"),
    ConfirmProfile(name="EXPIRY8", expiry_hours_scalp=8),
    ConfirmProfile(name="GATE_HTF_FREE", gate_exceptions=("htf_alignment",)),
    ConfirmProfile(name="GATE_LOC_FREE", gate_exceptions=("LOC",)),
    ConfirmProfile(name="RR_LIGHT", rr1_floor=1.0, rr2_floor=1.5),
    ConfirmProfile(name="RR_MID", rr1_floor=1.15, rr2_floor=1.8),
    ConfirmProfile(name="BODY_LIGHT", body_min_atr=0.25, require_close_beyond_zone_mid=False),
    ConfirmProfile(
        name="LOC_RR_COMBO",
        rr1_floor=1.15,
        rr2_floor=1.8,
        gate_exceptions=("LOC",),
    ),
    ConfirmProfile(
        name="COMBO_RELAX",
        body_min_atr=0.25,
        require_close_beyond_zone_mid=False,
        rr1_floor=1.0,
        rr2_floor=1.5,
        gate_exceptions=("htf_alignment",),
        expiry_hours_scalp=10,
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["collect", "replay"])
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--style", default="BOTH")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--sl-scale", type=float, default=1.0)
    parser.add_argument("--every-n", type=int, default=0, help="scan every Nth trigger bar; 0 = auto (15m cadence for scalp)")
    args = parser.parse_args()

    styles = ["SWING", "SCALP"] if args.style.upper() == "BOTH" else [args.style.upper()]
    for style in styles:
        every_n = args.every_n or (3 if style == "SCALP" else 1)
        if args.mode == "collect":
            collect(args.symbol.upper(), style, args.days, args.sl_scale, every_n)
        else:
            replay(args.symbol.upper(), style, args.days, args.sl_scale, PROFILES_GRID, every_n)


if __name__ == "__main__":
    main()
