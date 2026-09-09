"""Setup-specific structural-zone policy, observational in the research phase.

The policy records whether a candidate satisfies the proposed location and
confluence model. It does not reject or publish a candidate by itself; this
keeps stage-four comparisons honest and prevents an unvalidated rule from
silently reducing the alert universe.
"""
from __future__ import annotations

from typing import Dict, Iterable, Set


POLICIES = {
    "PINVAL": {
        "required_any": {"DEMAND", "FVG", "FLIP", "ORDER_BLOCK", "FLAG_LIMIT"},
        "preferred": {"DEMAND", "FVG", "FLIP", "ORDER_BLOCK"},
        "min_score": 3,
        "min_score_strict": 5,
    },
    "PINWALLQ": {
        "required_any": {"DEMAND", "FVG", "FLIP", "ORDER_BLOCK", "FLAG_LIMIT"},
        "preferred": {"FVG", "FLIP", "ORDER_BLOCK"},
        "min_score": 4,
        "min_score_strict": 6,
    },
    "ALBROX": {
        "required_any": {"DEMAND", "FVG", "FLIP", "ORDER_BLOCK", "FLAG_LIMIT"},
        "preferred": {"ORDER_BLOCK", "FVG", "FLAG_LIMIT", "FLIP"},
        "min_score": 4,
        "min_score_strict": 6,
    },
    "TLBREAK": {
        "required_any": {"FLIP", "FVG", "ORDER_BLOCK", "BREAKER", "FLAG_LIMIT", "DEMAND", "SUPPLY"},
        "preferred": {"FLIP", "BREAKER", "FVG", "ORDER_BLOCK"},
        "min_score": 3,
        "min_score_strict": 5,
    },
}


def _nearby_origins(candidate) -> Set[str]:
    items = (candidate.metadata or {}).get("zone_candidates") or []
    return {
        str(item.get("origin") or "").upper()
        for item in items
        if float(item.get("distance_atr", 99.0) or 99.0) <= 1.5
    }


def evaluate_zone_policy(candidate) -> Dict:
    """Return a reproducible, JSON-safe policy decision for one candidate."""
    setup = str(candidate.setup_code or "").upper()
    policy = POLICIES.get(setup)
    if not policy:
        return {"version": "zone-policy-1", "setup": setup, "eligible": False, "reason": "UNSUPPORTED_SETUP"}

    md = candidate.metadata or {}
    confluence = md.get("zone_confluence") or {}
    origins = _nearby_origins(candidate)
    direction = str(candidate.direction or "").upper()
    aligned_location = (
        (direction == "LONG" and bool(confluence.get("demand_near")))
        or (direction == "SHORT" and bool(confluence.get("supply_near")))
        or bool(confluence.get("flip_near"))
    )

    score = 0
    reasons = []
    if aligned_location:
        score += 2
        reasons.append("DIRECTION_ALIGNED_LOCATION")
    if origins.intersection(policy["preferred"]):
        score += 2
        reasons.append("PREFERRED_ZONE")
    if confluence.get("fvg_near"):
        score += 1
        reasons.append("FVG")
    if confluence.get("ifvg_near"):
        score += 1
        reasons.append("IFVG")
    if confluence.get("order_block_near"):
        score += 1
        reasons.append("ORDER_BLOCK")
    if confluence.get("breaker_near"):
        score += 1
        reasons.append("BREAKER")
    if confluence.get("flag_limit_near"):
        score += 1
        reasons.append("FLAG_LIMIT")
    if confluence.get("liquidity_sweep_near"):
        score += 1
        reasons.append("LIQUIDITY_SWEEP")
    if bool(md.get("premium_discount_aligned")):
        score += 1
        reasons.append("PREMIUM_DISCOUNT_ALIGNED")

    # TLBREAK geometry remains mandatory in its own detector/state machine;
    # zone policy can only add context, not certify a break by itself.
    geometry_ok = setup != "TLBREAK" or bool(
        md.get("tl_pattern") or md.get("viva_pattern") or md.get("strategy_variant")
    )
    has_zone = bool(origins.intersection(policy["required_any"])) or aligned_location
    eligible = bool(geometry_ok and has_zone and score >= policy["min_score"])
    strict = bool(geometry_ok and has_zone and score >= policy["min_score_strict"])
    return {
        "version": "zone-policy-1",
        "setup": setup,
        "eligible": eligible,
        "strict": strict,
        "score": int(score),
        "minimum": int(policy["min_score"]),
        "strict_minimum": int(policy["min_score_strict"]),
        "nearby_origins": sorted(origins),
        "reasons": reasons,
        "geometry_ok": geometry_ok,
        "has_direction_aligned_location": aligned_location,
        "mode": "OBSERVATIONAL_NOT_A_GATE",
    }


def attach_zone_policy(candidate) -> None:
    try:
        candidate.metadata["zone_policy"] = evaluate_zone_policy(candidate)
    except Exception as exc:
        candidate.metadata["zone_policy"] = {
            "version": "zone-policy-1", "eligible": False,
            "mode": "OBSERVATIONAL_NOT_A_GATE", "error": str(exc)[:160],
        }
