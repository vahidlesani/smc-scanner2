"""Unit + integration tests for the multi-candle / higher-TF trigger engine."""
import pandas as pd
import pytest

from analysis.trigger_patterns import multi_candle_trigger
from analysis.models import SignalCandidate
from analysis.quality_engine import evaluate_confirmation


def _bars(rows, start="2026-09-01 10:00", step_min=5):
    ts = pd.date_range(start, periods=len(rows), freq=f"{step_min}min")
    return pd.DataFrame(
        {"timestamp": ts,
         "open": [r[0] for r in rows], "high": [r[1] for r in rows],
         "low": [r[2] for r in rows], "close": [r[3] for r in rows],
         "volume": [100.0] * len(rows)}
    )


ZONE = (99.0, 100.05)

# A 7-bar drift-and-sweep base: no single candle is a pin, but candles 5-7
# aggregate into a textbook 30m-style pin bar (wick 99.20 at the zone).
CLUSTER_PIN_ROWS = [
    (100.40, 100.45, 100.30, 100.32),
    (100.32, 100.35, 100.10, 100.15),
    (100.15, 100.20,  99.90,  99.95),
    ( 99.95, 100.00,  99.60,  99.70),
    ( 99.65,  99.70,  99.20,  99.50),   # deep sweep wick
    ( 99.50,  99.75,  99.45,  99.70),   # recovery
    ( 99.70,  99.75,  99.65,  99.66),   # last closed bar (small body, no pin)
]


# ---------------------------------------------------------------- cluster pin
def test_cluster_pin_recognized_but_no_single_candle_pin():
    df = _bars(CLUSTER_PIN_ROWS)
    alt = multi_candle_trigger(df, "LONG", *ZONE, atr_value=1.0, mtf_enabled=False)
    assert alt is not None and alt.kind == "CLUSTER_PIN" and alt.size == 3
    assert alt.extreme == pytest.approx(99.20)


def test_require_zone_mid_blocks_fade_close():
    rows = [list(r) for r in CLUSTER_PIN_ROWS]
    rows[-1] = [99.50, 99.55, 99.45, 99.40]  # close below zone mid
    df = _bars(rows)
    alt = multi_candle_trigger(df, "LONG", *ZONE, atr_value=1.0, mtf_enabled=False)
    assert alt is None


def test_quiet_base_confirms_nothing():
    df = _bars([
        (100.40, 100.42, 100.35, 100.38),
        (100.38, 100.40, 100.30, 100.35),
        (100.15, 100.20, 100.05, 100.10),
        (100.15, 100.20, 100.05, 100.10),
        ( 99.60,  99.62,  99.55,  99.58),
        ( 99.58,  99.65,  99.55,  99.62),
    ])
    assert multi_candle_trigger(df, "LONG", *ZONE, atr_value=1.0, mtf_enabled=False) is None


# -------------------------------------------------------------------- reclaim
def test_reclaim_of_zone_top_is_a_trigger():
    df = _bars([
        (100.35, 100.40, 100.25, 100.30),
        (100.30, 100.32, 100.20, 100.22),
        (100.25, 100.30, 100.00,  99.95),  # dips to the zone top edge
        ( 99.95, 100.50,  99.90, 100.45),  # closes back above it
    ])
    alt = multi_candle_trigger(df, "LONG", 99.0, 100.05, 1.0, mtf_enabled=False)
    assert alt is not None and alt.kind in {"RECLAIM", "CLUSTER_PIN"}


# ----------------------------------------------------------------- doji break
def test_doji_at_zone_then_directional_break():
    df = _bars([
        (99.87, 99.90, 99.82, 99.85),
        (99.84, 99.90, 99.80, 99.82),
        (99.80, 99.82, 99.70, 99.62),
        (99.55, 99.62, 99.50, 99.60),
        (99.55, 99.65, 99.40, 99.53),   # doji inside the zone
        (99.46, 99.80, 99.45, 99.78),   # break above doji high with body
    ])
    alt = multi_candle_trigger(df, "LONG", 99.0, 100.0, 1.0, mtf_enabled=False)
    assert alt is not None and alt.kind in {"DOJI_BREAK", "CLUSTER_PIN", "RECLAIM"}


# ---------------------------------------------------------------- SHORT mirror
def test_short_mirrors_are_supported():
    # price' = 200 - price maps the LONG pin-base onto a SHORT one.
    rows = [(200 - o, 200 - l, 200 - h, 200 - c)
            for (o, h, l, c) in CLUSTER_PIN_ROWS]
    df = _bars(rows)
    alt = multi_candle_trigger(df, "SHORT", 200 - ZONE[1], 200 - ZONE[0],
                               atr_value=1.0, mtf_enabled=False)
    assert alt is not None and alt.kind == "CLUSTER_PIN" and alt.size == 3
    assert alt.extreme == pytest.approx(200 - 99.20)


# ---------------------------------------------------------------------- MTF
def test_mtf_native_pin_rebuilt_from_five_minute_bars():
    rows = [
        (100.40, 100.45, 100.30, 100.35),
        (100.35, 100.40, 100.25, 100.30),
        (100.30, 100.35, 100.20, 100.25),
        (100.25, 100.30, 100.15, 100.20),
        (100.20, 100.25, 100.10, 100.15),
        (100.15, 100.20, 100.05, 100.10),
        (100.10, 100.15, 100.00, 100.05),
        (100.05, 100.10,  99.95, 100.00),
        (100.00, 100.05,  99.90,  99.95),
        ( 99.95, 100.00,  99.90,  99.92),
        ( 99.92,  99.95,  99.88,  99.90),
        ( 99.90,  99.95,  99.85,  99.90),
        # 11:00..11:25 -> one native 30m candle: o 99.50, low 99.15, c 99.75
        ( 99.50,  99.55,  99.25,  99.30),
        ( 99.30,  99.35,  99.20,  99.30),
        ( 99.30,  99.32,  99.20,  99.28),
        ( 99.28,  99.55,  99.15,  99.50),
        ( 99.50,  99.65,  99.45,  99.62),
        ( 99.62,  99.78,  99.58,  99.75),
    ]
    df = _bars(rows, start="2026-09-01 10:00")
    alt = multi_candle_trigger(df, "LONG", 99.0, 100.0, 1.0, max_base=1,
                               require_zone_mid=True)
    assert alt is not None and alt.kind == "MTF_PIN" and alt.higher_tf_min == 30


# ------------------------------------------------------------- integration
def _candidate(**over):
    base = dict(
        signal_id="T1", symbol="TESTUSDT", style="DAYTRADE", setup_code="ALBROX",
        setup_name="t", strategy_fa="t", direction="LONG", score=8, status="APPROACHING",
        entry_zone_bottom=ZONE[0], entry_zone_top=ZONE[1], planned_entry=99.5, sl=98.6,
        tp1=101.5, tp2=103.0, rr_tp1=1.0, rr_tp2=2.0, bias="BULL", trigger_timeframe="5m",
        mandatory_gates={"zone": True, "risk_reward": True},
        metadata={"atr": 1.0, "touched": True},
    )
    base.update(over)
    return SignalCandidate(**base)


def _df20(rows=CLUSTER_PIN_ROWS):
    prefix = [(100.40, 100.45, 100.30, 100.35)] * 14
    return _bars(prefix + [tuple(r) for r in rows]).tail(20).reset_index(drop=True)


def test_confirmation_accepts_cluster_trigger_when_single_candle_fails():
    cand = _candidate()
    ok, cand, reason = evaluate_confirmation(cand, _df20())
    assert ok, reason
    assert cand.status == "CONFIRMED"
    assert cand.metadata.get("alt_trigger_kind") == "CLUSTER_PIN"


def test_viva_tlbreak_fast_lane_through_alt_trigger():
    cand = _candidate(setup_code="TLBREAK",
                      metadata={"atr": 1.0, "touched": True,
                                "strategy_variant": "VIVA_TLBREAK",
                                "viva_state": "S3_RETEST"})
    ok, cand, reason = evaluate_confirmation(cand, _df20())
    assert ok, reason
    assert cand.metadata.get("viva_fast_alt") == "CLUSTER_PIN"


def test_alt_engine_can_be_disabled():
    import analysis.quality_engine as qe
    real = qe.SETTINGS

    class _Off:
        def __getattr__(self, name):
            return getattr(real, name) if name != "alt_triggers_enabled" else False

    qe.SETTINGS = _Off()
    try:
        ok, cand, reason = evaluate_confirmation(_candidate(), _df20())
    finally:
        qe.SETTINGS = real
    assert not ok
    assert cand.metadata.get("last_reject_code") == "NO_TRIGGER"
