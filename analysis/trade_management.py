"""Deterministic multi-target and trailing-stop lifecycle primitives.

This module has no database or Telegram dependency so every fill rule is unit
 testable before it is wired into the live monitor.
"""
from __future__ import annotations
from typing import Dict, List, Optional

DEFAULT_WEIGHTS = (35.0, 35.0, 20.0, 5.0, 5.0)


def venue_tick(price: float, market: Optional[Dict] = None) -> float:
    market = market or {}
    try:
        tick = float(market.get("tick_size") or market.get("price_tick") or 0)
    except (TypeError, ValueError):
        tick = 0.0
    if tick > 0:
        return tick
    p = abs(float(price))
    return 0.1 if p >= 10_000 else (0.01 if p >= 10 else (0.0001 if p >= 1 else (0.00001 if p >= .1 else .000001)))


def build_ladder(entry: float, sl: float, direction: str, market: Optional[Dict] = None, final_target: Optional[float] = None) -> Dict:
    """Five 1R-spaced profit levels, fixed exits 35/35/20/5/5.

    Stop only trails after a target is actually reached. The five-tick buffer
    always moves in the profitable direction, never loosens the original stop.
    """
    entry, sl = float(entry), float(sl)
    risk = abs(entry - sl)
    if entry <= 0 or risk <= 0:
        raise ValueError("entry/sl must define positive risk")
    sign = 1.0 if str(direction).upper() == "LONG" else -1.0
    tick_gap = 5.0 * venue_tick(entry, market)
    # Exit ladder is independent from the R:R gate. It partitions the actual
    # structural final target into five equal price segments.
    proposed_final = float(final_target or 0)
    valid_final = (proposed_final > entry if sign > 0 else proposed_final < entry)
    final_price = proposed_final if valid_final else entry + sign * risk * 5
    targets = [entry + (final_price - entry) * i / 5.0 for i in range(1, 6)]
    # after TP1 stop moves just beyond entry; afterwards just beyond prior TP
    trail_stops = [entry + sign * tick_gap]
    trail_stops += [targets[n] + sign * tick_gap for n in range(0, 4)]
    return {
        "version": 1,
        "direction": str(direction).upper(),
        "entry": entry,
        "original_sl": sl,
        "current_sl": sl,
        "risk": risk,
        "final_target": final_price,
        "tick_gap": tick_gap,
        "targets": targets,
        "target_r": [abs(t - entry) / risk for t in targets],
        "trail_stops": trail_stops,
        "weights": list(DEFAULT_WEIGHTS),
        "hit_index": 0,
        "realized_r": 0.0,
        "closed": False,
    }


def advance_ladder(state: Dict, high: float, low: float) -> Dict:
    """Advance on one *closed* candle.

    Conservative ordering: when current stop and next target coexist in one
    candle, stop is assumed first. This avoids optimistic backtests.
    """
    out = dict(state)
    out["targets"] = list(state["targets"])
    out["weights"] = list(state["weights"])
    out["trail_stops"] = list(state["trail_stops"])
    out["target_r"] = list(state.get("target_r") or [abs(t - out["entry"]) / out["risk"] for t in out["targets"]])
    events: List[Dict] = []
    if out.get("closed"):
        return {"state": out, "events": events}
    direction = out["direction"]
    stop = float(out["current_sl"])
    stop_hit = low <= stop if direction == "LONG" else high >= stop
    if stop_hit:
        remaining = 100.0 - sum(out["weights"][:int(out["hit_index"])])
        stop_r = ((stop - out["entry"]) / out["risk"]) if direction == "LONG" else ((out["entry"] - stop) / out["risk"])
        out["realized_r"] = float(out["realized_r"]) + stop_r * remaining / 100.0
        out["closed"] = True
        events.append({"event": "TRAIL_STOP" if out["hit_index"] else "STOP", "stop": stop, "realized_r": out["realized_r"]})
        return {"state": out, "events": events}

    idx = int(out["hit_index"])
    while idx < len(out["targets"]):
        target = float(out["targets"][idx])
        hit = high >= target if direction == "LONG" else low <= target
        if not hit:
            break
        weight = float(out["weights"][idx])
        out["realized_r"] = float(out["realized_r"]) + float(out["target_r"][idx]) * weight / 100.0
        out["current_sl"] = float(out["trail_stops"][idx])
        idx += 1
        out["hit_index"] = idx
        events.append({"event": f"TP{idx}", "target": target, "weight": weight, "new_sl": out["current_sl"]})
    if idx >= len(out["targets"]):
        out["closed"] = True
        events.append({"event": "LADDER_COMPLETE", "realized_r": out["realized_r"]})
    return {"state": out, "events": events}
