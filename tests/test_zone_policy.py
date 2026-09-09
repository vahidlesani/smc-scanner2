from analysis.models import SignalCandidate
from analysis.zone_policy import evaluate_zone_policy


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
    assert "FVG" in result["reasons"]


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
    assert evaluate_zone_policy(c)["eligible"] is True
