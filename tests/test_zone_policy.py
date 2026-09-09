from analysis.models import SignalCandidate
from analysis.zone_policy import attach_zone_policy, evaluate_zone_policy


def _candidate(setup, direction, origins, confluence, premium_aligned=False, metadata_extra=None):
    metadata = {
        "zone_candidates": [
            {"origin": origin, "distance_atr": 1.0} for origin in origins
        ],
        "zone_confluence": confluence,
        "premium_discount_aligned": premium_aligned,
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    return SignalCandidate(
        signal_id="policy-test", symbol="BTCUSDT", style="SWING", setup_code=setup,
        setup_name=setup, strategy_fa=setup, direction=direction, score=8,
        status="EDUCATIONAL", entry_zone_bottom=99, entry_zone_top=101,
        planned_entry=100, sl=98, tp1=102, tp2=104, rr_tp1=1, rr_tp2=2,
        bias="BULLISH" if direction == "LONG" else "BEARISH",
        trigger_timeframe="1h", metadata=metadata,
    )


def test_pinwall_long_prefers_demand_fvg_and_discount():
    c = _candidate("PINVAL", "LONG", {"DEMAND", "FVG"}, {
        "demand_near": True, "supply_near": False, "fvg_near": True,
        "flip_near": False, "ifvg_near": False, "order_block_near": False,
        "breaker_near": False, "flag_limit_near": False,
        "liquidity_sweep_near": True,
    }, premium_aligned=True)
    result = evaluate_zone_policy(c)
    assert result["eligible"] is True
    assert "DIRECTION_ALIGNED_LOCATION" in result["reasons"]
    # v2: DEMAND and FVG are both preferred hits — FVG's own +1 is deduped
    assert set(result["preferred_zone_hits"]) == {"DEMAND", "FVG"}
    assert "FVG" not in result["reasons"]
    assert "LIQUIDITY_SWEEP" in result["reasons"] and result["score"] == 6


def test_albrox_without_location_is_not_eligible():
    c = _candidate("ALBROX", "LONG", {"SUPPLY"}, {
        "demand_near": False, "supply_near": True, "fvg_near": False,
        "flip_near": False, "ifvg_near": False, "order_block_near": False,
        "breaker_near": False, "flag_limit_near": False,
        "liquidity_sweep_near": False,
    })
    assert evaluate_zone_policy(c)["eligible"] is False


def test_tlbreak_requires_geometry_context_but_zone_policy_does_not_replace_it():
    c = _candidate("TLBREAK", "LONG", {"FLIP", "BREAKER"}, {
        "demand_near": False, "supply_near": False, "fvg_near": False,
        "flip_near": True, "ifvg_near": False, "order_block_near": False,
        "breaker_near": True, "flag_limit_near": False,
        "liquidity_sweep_near": False,
    })
    assert evaluate_zone_policy(c)["eligible"] is False
    c.metadata["tl_pattern"] = "CHANNEL"
    r = evaluate_zone_policy(c)
    assert r["eligible"] is True
    assert "tl_pattern" in r["geometry_evidence"]


# ------------------------------------------------------------------ v2 fixes
def test_fix1_long_short_symmetry_pinval():
    """A SHORT pin at SUPPLY must score exactly like a LONG pin at DEMAND."""
    long_conf = {"demand_near": True, "supply_near": False, "flip_near": False}
    short_conf = {"demand_near": False, "supply_near": True, "flip_near": False}
    L = evaluate_zone_policy(_candidate("PINVAL", "LONG", {"DEMAND"}, long_conf))
    S = evaluate_zone_policy(_candidate("PINVAL", "SHORT", {"SUPPLY"}, short_conf))
    assert L["score"] == S["score"] == 4
    assert L["eligible"] is True and S["eligible"] is True


def test_fix1_short_supply_counts_for_albrox_too():
    L = evaluate_zone_policy(_candidate("ALBROX", "LONG", {"DEMAND", "ORDER_BLOCK"},
                                        {"demand_near": True}))
    S = evaluate_zone_policy(_candidate("ALBROX", "SHORT", {"SUPPLY", "ORDER_BLOCK"},
                                        {"supply_near": True}))
    assert L["score"] == S["score"] and L["eligible"] == S["eligible"]


def test_fix2_no_double_count_of_preferred_origin():
    """A lone FVG gets the +2 preferred bonus but NOT its own +1 flag."""
    c = _candidate("PINWALLQ", "LONG", {"FVG"}, {"fvg_near": True})
    r = evaluate_zone_policy(c)
    assert r["score"] == 2 and "PREFERRED_ZONE" in r["reasons"] and "FVG" not in r["reasons"]
    # ...but a second, independent confluence still earns its flag
    c2 = _candidate("PINWALLQ", "LONG", {"FVG"}, {"fvg_near": True, "breaker_near": True})
    r2 = evaluate_zone_policy(c2)
    assert r2["score"] == 3 and "BREAKER" in r2["reasons"]


def test_fix3_flip_polarity_respected():
    base = {"flip_near": True, "demand_near": False, "supply_near": False}
    bull_flip = _candidate("PINVAL", "LONG", {"FLIP"}, base,
                           metadata_extra={"zone_polarity": {"zone_kind": "SUPPLY_FLIP", "allowed": True}})
    r_ok = evaluate_zone_policy(bull_flip)
    assert r_ok["score"] == 4  # +2 location (verified bull flip) +2 preferred FLIP
    assert "FLIP_WITH_VERIFIED_POLARITY" in r_ok["reasons"]

    wrong = _candidate("PINVAL", "LONG", {"FLIP"}, base,
                       metadata_extra={"zone_polarity": {"zone_kind": "DEMAND_FLIP", "allowed": False}})
    r_bad = evaluate_zone_policy(wrong)
    # contradiction: no location bonus... but half credit only when kind unknown; here known+wrong
    assert "DIRECTION_ALIGNED_LOCATION" not in r_bad["reasons"]
    assert "FLIP_WITH_VERIFIED_POLARITY" not in r_bad["reasons"]
    assert r_bad["score"] < r_ok["score"]

    unknown = _candidate("PINVAL", "LONG", {"FLIP"}, base)
    r_unk = evaluate_zone_policy(unknown)
    assert "FLIP_POLARITY_UNKNOWN" in r_unk["reasons"] and r_unk["score"] == r_bad["score"] - 0 + 1


def test_fix5_per_policy_origin_distance():
    far = {"zone_candidates": [{"origin": "BREAKER", "distance_atr": 2.0}]}
    c_tl = _candidate("TLBREAK", "LONG", set(), {"demand_near": False})
    c_tl.metadata.update(far)
    c_tl.metadata["tl_pattern"] = "UP"
    assert "BREAKER" in evaluate_zone_policy(c_tl)["nearby_origins"]
    c_pv = _candidate("PINVAL", "LONG", set(), {"demand_near": True})
    c_pv.metadata.update(far)
    assert "BREAKER" not in evaluate_zone_policy(c_pv)["nearby_origins"]


def test_fix4_attach_writes_dict_and_survives_garbage():
    c = _candidate("PINVAL", "LONG", {"DEMAND"}, {"demand_near": True})
    c.metadata["zone_polarity"] = "not-a-dict"  # tolerate malformed enrichment
    attach_zone_policy(c)
    assert isinstance(c.metadata["zone_policy"], dict)
    assert c.metadata["zone_policy"]["version"] == "zone-policy-2"

    class Broken:
        metadata = None
    attach_zone_policy(Broken())  # must never raise into the scan loop


def test_json_safe_output():
    import json
    c = _candidate("PINWALLQ", "SHORT", {"SUPPLY", "FVG"}, {"supply_near": True, "fvg_near": True})
    json.dumps(evaluate_zone_policy(c))
