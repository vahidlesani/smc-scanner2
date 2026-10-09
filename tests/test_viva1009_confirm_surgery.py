"""Viva 10-09 — surgical confirmation laws (his verbatim dictate).

1. TECHCLASSIC / TLBREAK confirm ONLY on the FIRST CLOSE after the break of a
   single trendline / pattern upper-lower trend, in the break direction.
   Zone edges may NEVER confirm them («تایید نواحی فقط در آلبروکس و پینوال»).
2. INNER ceiling↔floor trades (range/channel edge → opposite wall) confirm in
   TLBREAK (they died at INSIDE_PATTERN_NO_BREAK before).
3. PINWALL-ONLY counter-trend permission: with the pin premise resolved
   (first close beyond the pin extreme) + rising counter-trend orders
   (volume spike, the engine's own TOHOM definition), the counter-break
   vetoes lift. Every other setup keeps its exact veto behavior.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))


def _frame(rows, start="2026-10-09 08:00", freq="15min"):
    ts = pd.date_range(start, periods=len(rows), freq=freq)
    return pd.DataFrame({"timestamp": ts,
                         "open": [r[0] for r in rows],
                         "high": [r[1] for r in rows],
                         "low": [r[2] for r in rows],
                         "close": [r[3] for r in rows],
                         "volume": [float(r[4]) for r in rows]})


def _pad(n, price, rng=0.12, vol=1000.0):
    return [(price - 0.02, price + rng / 2.0, price - rng / 2.0, price, vol)] * n


def _band(kind="RANGE", lo=99.0, hi=103.0):
    return {"kind": kind, "lo": lo, "hi": hi, "slope_lo": 0.0, "slope_hi": 0.0,
            "ts_last": "2026-10-09 16:00", "tf_minutes": 15.0}


def _cand(**over):
    from analysis.models import SignalCandidate
    base = dict(signal_id="S9-1", symbol="TESTUSDT", style="DAYTRADE", setup_code="TLBREAK",
                setup_name="t", strategy_fa="t", direction="LONG", score=8,
                status="NEAR_CONFIRM", entry_zone_bottom=99.5, entry_zone_top=100.0,
                planned_entry=100.0, sl=98.4, tp1=101.5, tp2=103.0, rr_tp1=1.0, rr_tp2=2.0,
                bias="BULL", trigger_timeframe="15m",
                created_at="2026-10-09T07:30:00+00:00",
                mandatory_gates={"zone": True, "rr": True},
                metadata={"atr": 1.0, "touched": True})
    mdo = over.pop("metadata", {})
    base.update(over)
    base["metadata"].update(mdo)
    return SignalCandidate(**base)


def _watch(side, p0, p1):
    return {"side": side, "p0": {"ts": p0[0], "price": p0[1]},
            "p1": {"ts": p1[0], "price": p1[1]}, "log_fit": False}


# ── 1-2. TLBREAK inner lane ──────────────────────────────────────────────
def test_tlbreak_internal_long_from_range_floor_confirms():
    """Floor → ceiling LONG with the production VIVA_TLBREAK variant: the
    internal plan's own edge candle is the trigger (no break close exists
    by definition)."""
    from analysis.quality_engine import evaluate_confirmation
    rows = _pad(24, 99.75) + [(99.10, 99.35, 98.62, 99.30, 1500.0)]
    cand = _cand(setup_code="TLBREAK",
                 metadata={"atr": 1.0, "touched": True,
                           "strategy_variant": "VIVA_TLBREAK",
                           "pattern_band": _band()})
    ok, c2, reason = evaluate_confirmation(cand, _frame(rows))
    assert ok is True, reason
    assert c2.metadata.get("viva_entry_type") == "INTERNAL"
    assert c2.metadata["internal_entry"]["direction"] == "LONG"
    assert c2.metadata["internal_entry"]["entry"] == 99.30
    assert "داخلی" in str(c2.metadata.get("trigger_note"))


def test_tlbreak_internal_short_from_range_ceiling_confirms():
    """Ceiling → floor SHORT (variant-less legacy shape): same lane."""
    from analysis.quality_engine import evaluate_confirmation
    rows = _pad(24, 103.10) + [(103.15, 103.30, 102.90, 103.05, 1200.0)]
    cand = _cand(setup_code="TLBREAK", direction="SHORT", bias="BEAR",
                 entry_zone_bottom=102.75, entry_zone_top=103.15,
                 planned_entry=103.10, sl=104.50, tp1=101.50, tp2=100.00,
                 metadata={"atr": 1.0, "touched": True,
                           "pattern_band": _band(lo=98.0, hi=104.0)})
    ok, c2, reason = evaluate_confirmation(cand, _frame(rows))
    assert ok is True, reason
    assert c2.metadata.get("viva_entry_type") == "INTERNAL"
    assert c2.metadata["internal_entry"]["direction"] == "SHORT"
    assert c2.metadata["internal_entry"]["entry"] == 103.05
    assert "داخلی" in str(c2.metadata.get("trigger_note"))


# ── 3-4. pure-break law: no line, no confirm ─────────────────────────────
def test_techclassic_without_line_break_never_confirms():
    """A bullish pinbar closing above the ZONE top confirmed TC through the
    old zone fallback — now it must wait for a real line break."""
    from analysis.quality_engine import evaluate_confirmation
    rows = _pad(24, 99.80, rng=0.10) + [(99.95, 100.25, 99.90, 100.15, 1100.0)]
    cand = _cand(setup_code="TECHCLASSIC",
                 metadata={"atr": 1.0, "touched": True})   # NO variant/lines/band
    ok, c2, _reason = evaluate_confirmation(cand, _frame(rows))
    assert ok is False
    assert c2.metadata.get("last_reject_code") == "WAIT_FIRST_CLOSE_BREAK"


def test_legacy_tlbreak_zone_close_never_confirms():
    """Legacy TLBREAK (tl anchors, no viva line) closing above the zone top:
    the zone fallback is gone for pure-break setups."""
    from analysis.quality_engine import evaluate_confirmation
    rows = _pad(24, 99.80, rng=0.10) + [(99.95, 100.25, 99.90, 100.15, 1100.0)]
    cand = _cand(setup_code="TLBREAK",
                 metadata={"atr": 1.0, "touched": True,
                           "strategy_variant": "LEGACY_TLBREAK",
                           "tl_a_ts": "2026-10-09 06:00", "tl_a_price": 99.0,
                           "tl_b_ts": "2026-10-09 07:00", "tl_b_price": 99.5})
    ok, c2, _reason = evaluate_confirmation(cand, _frame(rows))
    assert ok is False
    assert c2.metadata.get("last_reject_code") == "WAIT_FIRST_CLOSE_BREAK"


# ── 5. pure-break guard: a real line break still confirms ────────────────
def test_techclassic_first_close_beyond_line_still_confirms():
    """Production TC shape (VIVA_TLBREAK variant + viva line): the first
    close beyond the broken line confirms via S6, as always."""
    from analysis.quality_engine import evaluate_confirmation
    from analysis.viva_tlbreak_state import VivaTLState
    rows = (_pad(24, 99.55)
            + [(99.60, 99.90, 99.50, 99.80, 1000.0),
               (99.90, 100.45, 99.80, 100.30, 1400.0)])
    cand = _cand(setup_code="TECHCLASSIC", sl=98.5, tp1=104.0, tp2=107.0,
                 metadata={"atr": 1.0, "touched": True,
                           "strategy_variant": "VIVA_TLBREAK",
                           "viva_state_machine": VivaTLState(stage="S2_BREAKOUT").payload(),
                           "viva_break_line": 100.0, "viva_breakout_line": 100.0,
                           "break_direction": "UP"})
    ok, c2, reason = evaluate_confirmation(cand, _frame(rows))
    assert ok is True, reason
    assert c2.metadata.get("viva_state") == "S6_CONFIRMED"


# ── 6-7. pinwall-only counter-trend permission ───────────────────────────
def _countertrend_pin_rows(last_vol):
    rows = _pad(19, 99.70)
    rows += [(99.68, 99.74, 99.60, 99.62, 1000.0),
             (99.62, 99.66, 99.55, 99.58, 1000.0),
             (99.58, 99.60, 99.30, 99.38, 1100.0),    # dip THROUGH support
             (99.38, 99.70, 99.35, 99.65, 1200.0),
             (99.65, 99.95, 99.60, 99.90, 1300.0),
             (99.90, 100.35, 99.85, 100.20, last_vol)]  # close over pin_high
    return rows


def _countertrend_pin_cand():
    return _cand(setup_code="PINVAL", sl=98.5, tp1=103.5, tp2=106.0,
                 metadata={"atr": 0.5, "touched": True, "pin_tf": "15m",
                           "pin_high": 100.0, "pin_low": 99.0,
                           "render_line_watch": [
                               _watch("LOW", ("2026-10-09 07:00", 99.50),
                                      ("2026-10-09 09:00", 99.50))]})


def test_pinwall_countertrend_long_lifts_veto_with_rising_volume(monkeypatch):
    """Support broke down, then the pin resolved up with a 3× volume spike:
    PINWALL may take the counter-trend LONG (10-09 permission)."""
    import data.fetcher as fetcher
    monkeypatch.setattr(fetcher, "get_klines", lambda *a, **k: None)
    from analysis.quality_engine import evaluate_confirmation
    ok, c2, reason = evaluate_confirmation(
        _countertrend_pin_cand(), _frame(_countertrend_pin_rows(3200.0)))
    assert ok is True, reason
    assert "vol" in str(c2.metadata.get("countertrend_pin_lift"))


def test_pinwall_countertrend_without_volume_still_vetoed(monkeypatch):
    """Same tape with flat volume: no rising-orders evidence → the 09-21
    break-side veto stands (fail-closed)."""
    import data.fetcher as fetcher
    monkeypatch.setattr(fetcher, "get_klines", lambda *a, **k: None)
    from analysis.quality_engine import evaluate_confirmation
    ok, c2, _reason = evaluate_confirmation(
        _countertrend_pin_cand(), _frame(_countertrend_pin_rows(1000.0)))
    assert ok is False
    assert c2.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH"


# ── 8-9. TOHOM obeys the pure-break law ──────────────────────────────────
def _tohom_subs():
    rows = _pad(26, 99.60, rng=0.08, vol=100.0)
    rows += [(99.62, 99.75, 99.58, 99.72, 110.0),
             (99.72, 99.90, 99.70, 99.88, 120.0),
             (99.88, 100.05, 99.85, 100.02, 150.0),
             (100.00, 100.40, 99.95, 100.32, 520.0)]   # power candle, 5× vol
    df = _frame(rows, freq="5min")
    created = str(df["timestamp"].iloc[26])[:19]
    return df, created


def _tohom_cand(**mdo):
    md = {"atr": 0.5, "touched": False}
    md.update(mdo)
    return _cand(setup_code="TECHCLASSIC", trigger_timeframe="15m", sl=98.5,
                 tp1=104.0, tp2=107.0, metadata=md)


def test_tohom_refuses_zone_edge_for_pure_break_setups():
    """Perfect TOHOM evidence (directional closes + 5× volume + power
    candle) — but the edge is a ZONE: TC must refuse (TOHOM's own charter:
    never loosen the close law)."""
    from analysis.tohom import evaluate_tohom_confirmation
    df, created = _tohom_subs()
    cand = _tohom_cand()
    cand.created_at = created
    _now = df["timestamp"].iloc[-1] + pd.Timedelta(minutes=1)
    ok, c2, _reason = evaluate_tohom_confirmation(cand, df, sub_tf="5m", now=_now)
    assert ok is False
    assert c2.metadata.get("tohom_last_reject") == "TOHOM_ZONE_EDGE"


def test_tohom_with_line_edge_still_confirms_early():
    """Same evidence with a real viva line: the early confirm stands."""
    from analysis.tohom import evaluate_tohom_confirmation
    df, created = _tohom_subs()
    cand = _tohom_cand(viva_breakout_line=99.90, viva_break_line=99.90)
    cand.created_at = created
    _now = df["timestamp"].iloc[-1] + pd.Timedelta(minutes=1)
    ok, c2, reason = evaluate_tohom_confirmation(cand, df, sub_tf="5m", now=_now)
    assert ok is True, reason
    assert c2.metadata.get("tohom") == 1
