import pandas as pd

from analysis.execution_integrity_r28 import (
    TF_STOP_FLOOR_PCT,
    TrailingState,
    apply_execution_integrity,
    build_trailing_state,
    build_trend_context,
    confirm_closed_candle,
    edge_event,
    structural_stop,
    target_engine,
)
from analysis.models import SignalCandidate


def _candidate(**kw):
    base = dict(
        signal_id="test-id", symbol="ETHUSDT", style="DAYTRADE",
        setup_code="TLR", setup_name="TLR", strategy_fa="TLR",
        direction="LONG", score=8, status="EDUCATIONAL",
        entry_zone_bottom=99.0, entry_zone_top=101.0, planned_entry=100.0,
        sl=98.0, tp1=102.0, tp2=104.0, rr_tp1=2.0, rr_tp2=4.0,
        bias="BULL", trigger_timeframe="15m", metadata={},
    )
    base.update(kw)
    return SignalCandidate(**base)


def test_r28_stop_floors_and_arb_regression():
    for tf, floor in TF_STOP_FLOOR_PCT.items():
        d = structural_stop(100.0, "LONG", 100.0 * (1.0 - floor / 100.0), tf)
        assert d.valid, tf
    arb = structural_stop(0.2200, "LONG", 0.2198, "15m")
    assert not arb.valid
    assert arb.stop_quality == "TOO_TIGHT"


def test_wrong_side_stop_and_target_separation():
    assert not structural_stop(100.0, "LONG", 101.0, "1h").valid
    assert not structural_stop(100.0, "SHORT", 99.0, "1h").valid
    good = target_engine(100.0, "LONG", 98.0, 102.0, 104.0)
    assert good.valid and good.projected_R == 2.0
    blocked = target_engine(100.0, "LONG", 98.0, 100.2, 100.4)
    assert not blocked.valid
    assert blocked.target_quality == "TARGET_TOO_CLOSE"


def test_confirmation_is_closed_candle_evidence():
    row = {"open": 100.0, "high": 103.0, "low": 99.5, "close": 102.5}
    ev = confirm_closed_candle(row, "LONG", "CLOSE_CONFIRMATION", edge=101.0, normal_range=2.0)
    assert ev.confirmed
    assert ev.body_ratio > 0


def test_edges_remain_independent_and_intrabar_is_not_executable():
    upper = edge_event("BREAK_INTRABAR", "UPPER", closed=False)
    lower = edge_event("BREAK_CLOSED", "LOWER", closed=True)
    assert upper["side"] == "UPPER" and not upper["executable"]
    assert lower["side"] == "LOWER" and lower["executable"]


def test_trailing_ratchets_and_never_chases_price():
    s = build_trailing_state(100.0, 98.0, "LONG", atr=2.0)
    s.structure_stop = 99.0
    first = s.update("LONG", 104.0)
    assert first["new_stop"] >= 98.0
    old = first["new_stop"]
    s.current_stop = old
    s.tp1_hit = True
    s.structure_stop = 102.0
    second = s.update("LONG", 105.0, fee_buffer=0.10, slippage_buffer=0.10)
    assert second["new_stop"] >= old
    assert second["new_stop"] < 105.0
    s.current_stop = second["new_stop"]
    chase = s.update("LONG", s.current_stop + 0.001)
    assert chase["new_stop"] == s.current_stop


def test_short_trailing_is_symmetric():
    s = build_trailing_state(100.0, 102.0, "SHORT", atr=2.0)
    s.structure_stop = 101.0
    out = s.update("SHORT", 96.0)
    assert out["new_stop"] <= 102.0
    assert out["new_stop"] > 96.0


def test_trend_context_is_neutral_when_local_slope_is_flat():
    df = pd.DataFrame({
        "open": [100.0] * 30, "high": [101.0] * 30,
        "low": [99.0] * 30, "close": [100.0] * 30,
    })
    ctx = build_trend_context({"15m": df, "1h": df}, "15m")
    assert ctx.direction == "NEUTRAL"
    assert ctx.structure == "RANGING"
    assert 0 <= ctx.trend_quality <= 100


def test_core_context_execution_are_separate_and_spot_is_long_only():
    c = _candidate()
    data = apply_execution_integrity(c, {})
    assert data["CORE_STATE"] == "VALID"
    assert data["EXECUTION_STATE"] == "READY"
    c2 = _candidate(direction="SHORT", metadata={"market": "SPOT"})
    data2 = apply_execution_integrity(c2, {})
    assert not data2["spot_long_only"]
    assert data2["EXECUTION_STATE"] == "INVALID"
