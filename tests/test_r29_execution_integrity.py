import pandas as pd

from analysis.execution_integrity_r29 import (
    ProfessionalTrailingEngine,
    apply_r29,
    causal_pivots,
    execution_gate,
)
from analysis.models import EvidenceItem, SignalCandidate


def _frame(n=80):
    ts = pd.date_range("2026-09-23", periods=n, freq="15min", tz="UTC")
    close = [100.0 + i * 0.08 for i in range(n)]
    return pd.DataFrame({
        "timestamp": ts,
        "open": [x - 0.02 for x in close],
        "high": [x + 0.12 for x in close],
        "low": [x - 0.12 for x in close],
        "close": close,
        "volume": [1000.0] * n,
    })


def _candidate(**kw):
    base = dict(
        signal_id="viva-test-r29-001", symbol="TESTUSDT", style="DAYTRADE",
        setup_code="TLBREAK", setup_name="TLBREAK", strategy_fa="TLBREAK",
        direction="LONG", score=8, status="EDUCATIONAL", entry_zone_bottom=100.0,
        entry_zone_top=100.4, planned_entry=100.2, sl=99.2, tp1=101.2, tp2=103.0,
        rr_tp1=1.2, rr_tp2=2.8, bias="BULLISH", trigger_timeframe="15m",
        evidence=[EvidenceItem("core", "core", "existing setup", True, 2)],
        mandatory_gates={"existing": True}, market={}, metadata={"viva_state":"S2_BREAKOUT_CLOSED"},
    )
    base.update(kw)
    return SignalCandidate(**base)


def test_causal_pivot_never_uses_unconfirmed_tail():
    df = _frame(40)
    pts = causal_pivots(df, "15m", left=2, right=2)
    assert all(p.index + 2 < len(df) for p in pts)
    assert all(p.confirmation_timestamp for p in pts)


def test_execution_gate_rejects_too_tight_stop_and_preserves_reason():
    c = _candidate(sl=100.05)
    gate = execution_gate(c, {"15m": _frame()})
    assert gate["state"] == "BLOCKED"
    assert "STOP_TOO_TIGHT" in gate["reasons"]


def test_target_obstruction_is_reported_not_rewritten():
    df = _frame()
    c = _candidate(tp2=103.0)
    gate = execution_gate(c, {"15m": df})
    assert "target" in gate
    assert c.tp2 == 103.0


def test_core_context_execution_are_separate():
    c = _candidate()
    original = (c.signal_id, c.setup_code, c.planned_entry, c.sl, c.tp1, c.tp2, c.metadata.copy())
    out = apply_r29(c, {"15m": _frame(), "1h": _frame(), "4h": _frame()})
    assert out["CORE_STATE"] == "VALID"
    assert "CONTEXT_SCORE" in out and "EXECUTION_SCORE" in out
    assert (c.signal_id, c.setup_code, c.planned_entry, c.sl, c.tp1, c.tp2) == original[:6]


def test_context_cannot_manufacture_core():
    c = _candidate(setup_code="UNKNOWN", evidence=[])
    out = apply_r29(c, {"15m": _frame(), "1h": _frame(), "4h": _frame()})
    assert out["CORE_STATE"] == "OBSERVATION"


def test_professional_trailing_no_early_breakeven_then_net_be():
    eng = ProfessionalTrailingEngine(entry=100.0, initial_stop=98.5, current_stop=98.5,
                                     risk_R=1.5, tp1=101.0, tp2=102.5, atr_value=0.4)
    pre = eng.update("LONG", 100.8, fee_buffer=0.2, slippage_buffer=0.1)
    assert pre["new_stop"] < 100.0
    eng.tp1_hit = True
    post = eng.update("LONG", 101.4, fee_buffer=0.2, slippage_buffer=0.1)
    assert post["new_stop"] >= 100.3
    assert eng.regime == "NET_BREAKEVEN"


def test_trailing_is_ratchet_only():
    eng = ProfessionalTrailingEngine(entry=100.0, initial_stop=98.5, current_stop=99.0,
                                     risk_R=1.5, tp1=101.0, tp2=102.5, atr_value=0.4,
                                     tp1_hit=True)
    first = eng.update("LONG", 102.0)
    second = eng.update("LONG", 101.0)
    assert second["new_stop"] >= first["new_stop"]
