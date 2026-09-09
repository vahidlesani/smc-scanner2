"""Setup-specific structural-zone policy, observational in the research phase.

The policy records whether a candidate satisfies the proposed location and
confluence model. It does not reject or publish a candidate by itself; this
keeps stage-four comparisons honest and prevents an unvalidated rule from
silently reducing the alert universe.

v2 refinements (review follow-ups):
  1. Direction-symmetric zone sets — a SHORT pin at SUPPLY scores exactly the
     same as a LONG pin at DEMAND (the v1 preferred/required sets quietly
     disadvantaged shorts).
  2. No double-counting — an origin that earned the +2 PREFERRED_ZONE bonus
     does not also collect its +1 confluence flag.
  3. Flip polarity is honored via the live `zone_polarity` metadata
     (SUPPLY_FLIP is bull-aligned, DEMAND_FLIP bear-aligned); an unverifiable
     flip keeps only half credit and says so in the reasons.
  4. TLBREAK geometry evidence is reported (which field satisfied it) instead
     of pretending the guard is protective.
  5. Origin distance threshold is per-policy instead of a hardcoded 1.5 ATR.
"""
from __future__ import annotations

from typing import Dict, Set, Tuple


# Direction-symmetric sets. `both` applies to any direction; `long`/`short`
# mirror each other exactly.
POLICIES: Dict[str, Dict] = {
    "PINVAL": {
        "required_both": {"FVG", "FLIP", "ORDER_BLOCK", "FLAG_LIMIT"},
        "required_long": {"DEMAND"},
        "required_short": {"SUPPLY"},
        "preferred_both": {"FVG", "FLIP", "ORDER_BLOCK"},
        "preferred_long": {"DEMAND"},
        "preferred_short": {"SUPPLY"},
        "min_score": 3,
        "min_score_strict": 5,
        "max_origin_atr": 1.5,
    },
    "PINWALLQ": {
        "required_both": {"FVG", "FLIP", "ORDER_BLOCK", "FLAG_LIMIT"},
        "required_long": {"DEMAND"},
        "required_short": {"SUPPLY"},
        "preferred_both": {"FVG", "FLIP", "ORDER_BLOCK"},
        "preferred_long": set(),
        "preferred_short": set(),
        "min_score": 4,
        "min_score_strict": 6,
        "max_origin_atr": 1.5,
    },
    "ALBROX": {
        "required_both": {"FVG", "FLIP", "ORDER_BLOCK", "FLAG_LIMIT"},
        "required_long": {"DEMAND"},
        "required_short": {"SUPPLY"},
        "preferred_both": {"ORDER_BLOCK", "FVG", "FLAG_LIMIT", "FLIP"},
        "preferred_long": set(),
        "preferred_short": set(),
        "min_score": 4,
        "min_score_strict": 6,
        "max_origin_atr": 1.5,
    },
    "TLBREAK": {
        "required_both": {"FVG", "FLIP", "ORDER_BLOCK", "BREAKER", "FLAG_LIMIT"},
        "required_long": {"DEMAND"},
        "required_short": {"SUPPLY"},
        "preferred_both": {"FLIP", "BREAKER", "FVG", "ORDER_BLOCK"},
        "preferred_long": set(),
        "preferred_short": set(),
        "min_score": 3,
        "min_score_strict": 5,
        # a valid retest can sit a little further from the origin than a pin
        "max_origin_atr": 2.25,
    },
}

# zone_kind values produced by analysis.zone_polarity.evaluate_polarity
_FLIP_ALIGNED_LONG = {"SUPPLY_FLIP", "AT_DEMAND"}
_FLIP_ALIGNED_SHORT = {"DEMAND_FLIP", "AT_SUPPLY"}

# +1 confluence flags and the origin family they must not double-count with
_FLAGS: Tuple[Tuple[str, str], ...] = (
    ("fvg_near", "FVG"),
    ("ifvg_near", "IFVG"),
    ("order_block_near", "ORDER_BLOCK"),
    ("breaker_near", "BREAKER"),
    ("flag_limit_near", "FLAG_LIMIT"),
    ("liquidity_sweep_near", "LIQUIDITY_SWEEP"),
)


def _polarity_zone_kind(md: Dict) -> str:
    """Best-effort read of the live polarity verdict's zone_kind."""
    pol = md.get("zone_polarity") or {}
    if isinstance(pol, dict):
        return str(pol.get("zone_kind") or "").upper()
    return str(getattr(pol, "zone_kind", "") or "").upper()


def _nearby_origins(candidate, max_atr: float) -> Set[str]:
    items = (candidate.metadata or {}).get("zone_candidates") or []
    out: Set[str] = set()
    for item in items:
        if isinstance(item, str):
            out.add(item.upper())
            continue
        try:
            dist = float(item.get("distance_atr", 99.0) or 99.0)
        except (TypeError, ValueError):
            dist = 99.0
        if dist <= max_atr:
            origin = str(item.get("origin") or "").upper()
            if origin:
                out.add(origin)
    return out


def evaluate_zone_policy(candidate) -> Dict:
    """Return a reproducible, JSON-safe policy decision for one candidate."""
    setup = str(candidate.setup_code or "").upper()
    policy = POLICIES.get(setup)
    if not policy:
        return {"version": "zone-policy-2", "setup": setup,
                "eligible": False, "reason": "UNSUPPORTED_SETUP"}

    md = candidate.metadata or {}
    confluence = md.get("zone_confluence") or {}
    if not isinstance(confluence, dict):
        confluence = {}
    is_long = str(candidate.direction or "").upper() == "LONG"
    max_atr = float(policy.get("max_origin_atr", 1.5))
    origins = _nearby_origins(candidate, max_atr)

    required = set(policy["required_both"]) | (policy["required_long"] if is_long else policy["required_short"])
    preferred = set(policy["preferred_both"]) | (policy["preferred_long"] if is_long else policy["preferred_short"])

    flip_near = bool(confluence.get("flip_near"))
    flip_kind = _polarity_zone_kind(md)
    aligned_families = {"SUPPLY_FLIP", "DEMAND_FLIP"}
    if is_long:
        hard_location = bool(confluence.get("demand_near"))
        flip_aligned = flip_near and flip_kind in _FLIP_ALIGNED_LONG
        flip_unknown = flip_near and flip_kind not in _FLIP_ALIGNED_LONG | _FLIP_ALIGNED_SHORT
    else:
        hard_location = bool(confluence.get("supply_near"))
        flip_aligned = flip_near and flip_kind in _FLIP_ALIGNED_SHORT
        flip_unknown = flip_near and flip_kind not in _FLIP_ALIGNED_LONG | _FLIP_ALIGNED_SHORT
    aligned_location = hard_location or flip_aligned

    score = 0
    reasons = []
    if hard_location:
        score += 2
        reasons.append("DIRECTION_ALIGNED_LOCATION")
    elif flip_aligned:
        score += 2
        reasons.append("FLIP_WITH_VERIFIED_POLARITY")
    elif flip_unknown:
        score += 1
        reasons.append("FLIP_POLARITY_UNKNOWN")

    preferred_hit = origins & preferred
    if preferred_hit:
        score += 2
        reasons.append("PREFERRED_ZONE")
    for flag_key, family in _FLAGS:
        if not confluence.get(flag_key):
            continue
        if family in preferred_hit and family != "LIQUIDITY_SWEEP":
            continue  # already counted inside the +2 preferred bonus
        score += 1
        reasons.append(family)
    if bool(md.get("premium_discount_aligned")):
        score += 1
        reasons.append("PREMIUM_DISCOUNT_ALIGNED")

    # TLBREAK geometry: report WHICH evidence made it look validated; the
    # policy never certifies a break by itself.
    geometry_ok = True
    geometry_evidence = []
    if setup == "TLBREAK":
        for key in ("viva_pattern", "tl_pattern", "viva_state", "strategy_variant"):
            if md.get(key):
                geometry_evidence.append(str(key))
        geometry_ok = bool(geometry_evidence)

    has_zone = bool(origins & (required | aligned_families)) or aligned_location or flip_unknown
    eligible = bool(geometry_ok and has_zone and score >= policy["min_score"])
    strict = bool(geometry_ok and has_zone and score >= policy["min_score_strict"])
    return {
        "version": "zone-policy-2",
        "setup": setup,
        "eligible": eligible,
        "strict": strict,
        "score": int(score),
        "minimum": int(policy["min_score"]),
        "strict_minimum": int(policy["min_score_strict"]),
        "nearby_origins": sorted(origins),
        "preferred_zone_hits": sorted(preferred_hit),
        "reasons": reasons,
        "geometry_ok": geometry_ok,
        "geometry_evidence": geometry_evidence,
        "has_direction_aligned_location": aligned_location,
        "flip_polarity_kind": flip_kind or "NONE",
        "max_origin_atr": max_atr,
        "mode": "OBSERVATIONAL_NOT_A_GATE",
    }


def attach_zone_policy(candidate) -> None:
    """Never raise: a broken candidate must not kill the scan loop."""
    verdict: Dict = {}
    try:
        verdict = evaluate_zone_policy(candidate)
    except Exception as exc:
        verdict = {
            "version": "zone-policy-2", "eligible": False,
            "mode": "OBSERVATIONAL_NOT_A_GATE", "error": str(exc)[:160],
        }
    try:
        if isinstance(getattr(candidate, "metadata", None), dict):
            candidate.metadata["zone_policy"] = verdict
    except Exception:
        pass
