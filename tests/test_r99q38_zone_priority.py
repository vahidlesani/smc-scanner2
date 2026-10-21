"""R99q38m — ALBROX is LINE-first, the pin family is ZONE-first.

His 10-21, verbatim: «آلبروکس میتونه روی نواحی تایید بشه اما شکست ترندها
اولویت داره .. پین وال برعکسش .. ممکنه روی شکست ترند یا پترن تایید بشه اما
نواحی اولویت دارن»
"""
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _watch(side, p0, p1):
    return {"side": side, "p0": {"ts": p0[0], "price": p0[1]},
            "p1": {"ts": p1[0], "price": p1[1]}, "log_fit": False}


def _pin(direction="LONG", pin_high=100.6, pin_low=98.2, zone=(98.9, 99.3)):
    from analysis.models import SignalCandidate
    return SignalCandidate(
        signal_id="R99Q38M-1", symbol="ENAUSDT", style="SWING",
        setup_code="PINVAL", setup_name="t", strategy_fa="t",
        direction=direction, score=8, status="APPROACHING",
        entry_zone_bottom=zone[0], entry_zone_top=zone[1],
        planned_entry=(zone[0] + zone[1]) / 2,
        sl=97.9, tp1=101.2, tp2=102.4, rr_tp1=1.0, rr_tp2=2.0,
        bias="BULL", trigger_timeframe="15m",
        mandatory_gates={"zone": True},
        created_at="2026-10-03T16:05:00+00:00",
        metadata={"atr": 0.8, "touched": True, "pin_tf": "15m",
                  "pin_high": pin_high, "pin_low": pin_low})


def _frame(closes, start="2026-10-03 16:00", freq="15min", pad=20):
    vals = [float(c) for c in closes]
    pad_vals = [min(vals) - 1.2 - 0.01 * i for i in range(pad)]
    allc = pad_vals + vals
    ts = pd.date_range(start, periods=len(allc), freq=freq)
    return pd.DataFrame({"timestamp": ts,
                         "open": [c - 0.05 for c in allc],
                         "high": [c + 0.12 for c in allc],
                         "low": [c - 0.12 for c in allc],
                         "close": allc, "volume": [1000] * len(allc)})


def test_a_line_on_the_near_side_of_the_zone_cannot_preempt_the_zone():
    """A PINVAL LONG whose drawn TL lies BELOW the zone top may not set the
    trigger — the zone is the priority, the line is not a shortcut."""
    from analysis.confirm_r62 import line_respects_zone
    assert line_respects_zone(97.95, 99.30, True) is False      # below the zone top
    assert line_respects_zone(99.30, 99.30, True) is True       # exactly at it
    assert line_respects_zone(99.75, 99.30, True) is True       # beyond it (ENA)
    # mirrored for a SHORT: the line must be at or below the zone bottom
    assert line_respects_zone(101.20, 100.80, False) is False
    assert line_respects_zone(100.40, 100.80, False) is True
    # no zone on the chain → the line keeps its old right
    assert line_respects_zone(97.95, 0.0, True) is True


def test_the_engine_gates_the_pin_line_through_that_law():
    src = open(os.path.join(ROOT, "analysis", "quality_engine.py"), encoding="utf-8").read()
    assert "line_respects_zone as _lrz67" in src
    assert "_line_ok67 = _lrz67(" in src
    assert 'candidate.metadata["pin_line_blocked_by_zone"]' in src


def test_a_line_beyond_the_zone_still_confirms_a_pin_long(monkeypatch):
    """The ENA K142040 geometry he praised: the TL broke ABOVE the zone."""
    import data.fetcher as fetcher
    monkeypatch.setattr(fetcher, "get_klines", lambda *a, **k: None)
    from analysis.quality_engine import evaluate_confirmation
    cand = _pin("LONG")
    cand.metadata["render_line_watch"] = [
        _watch("HIGH", ("2026-10-03 15:00", 100.35), ("2026-10-03 17:00", 99.75))]
    frame = _frame([99.55, 99.72])
    ok, cand2, reason = evaluate_confirmation(cand, frame, frame_tf_minutes=15.0)
    assert ok is True, reason
    assert cand2.metadata.get("confirm_edge_source") == "PIN_LINE_WATCH"


def test_albrox_takes_the_first_edge_the_market_gives():
    """q39a: ALBROX may confirm at its ZONE and at its LINE — whichever price
    reaches first (his 10-21 evening: making it line-only «کند»د it)."""
    from analysis.confirm_r62 import confirm_edge_at
    from analysis.models import SignalCandidate
    def _cand(lower_zone_top):
        return SignalCandidate(
            signal_id="R99Q39A-1", symbol="SUIUSDT", style="SWING",
            setup_code="ALBROX", setup_name="t", strategy_fa="t",
            direction="LONG", score=8, status="APPROACHING",
            entry_zone_bottom=lower_zone_top - 0.004, entry_zone_top=lower_zone_top,
            planned_entry=lower_zone_top - 0.002, sl=1.0100, tp1=1.0500, tp2=1.0600,
            rr_tp1=1.0, rr_tp2=2.0, bias="BULL", trigger_timeframe="30m",
            mandatory_gates={"zone": True}, created_at="2026-10-03T16:00:00+00:00",
            metadata={"atr": 0.01,
                      "break_line_geo": {"ts": "2026-10-03 10:00", "price": 1.0600,
                                         "price_back": 1.0500, "back_bars": 8,
                                         "tf_min": 30.0, "log": False}})
    when = pd.Timestamp("2026-10-03 18:00")
    # zone (1.024) nearer than the line (~1.060) -> the ZONE confirms first
    assert abs(confirm_edge_at(_cand(1.0240), when) - 1.024) < 1e-9
    # a zone above the line (1.100) -> the LINE (1.08 here) is the first edge
    e = confirm_edge_at(_cand(1.1000), when)
    assert abs(e - 1.08) < 1e-6, e


def test_albrox_confirms_on_its_line_not_on_a_zone_behind_it():
    from analysis.confirm_r62 import confirm_edge_at
    from analysis.models import SignalCandidate
    cand = SignalCandidate(
        signal_id="R99Q38M-2", symbol="SUIUSDT", style="SWING",
        setup_code="ALBROX", setup_name="t", strategy_fa="t",
        direction="LONG", score=8, status="APPROACHING",
        entry_zone_bottom=1.0200, entry_zone_top=1.0240,
        planned_entry=1.0220, sl=1.0100, tp1=1.0500, tp2=1.0600,
        rr_tp1=1.0, rr_tp2=2.0, bias="BULL", trigger_timeframe="30m",
        mandatory_gates={"zone": True}, created_at="2026-10-03T16:00:00+00:00",
        metadata={"atr": 0.01,
                  "break_line_geo": {"ts": "2026-10-03 10:00", "price": 1.0300,
                                     "price_back": 1.0200, "back_bars": 8,
                                     "tf_min": 30.0, "log": False}})
    when = pd.Timestamp("2026-10-03 20:00")
    edge = confirm_edge_at(cand, when)
    # q39a: the zone (1.024) is nearer than the projected line, so the zone is
    # the FIRST edge ALBROX gets — the line stays the preferred reference but
    # never blocks a zone the market has already cleared.
    assert abs(edge - 1.0240) < 1e-9, edge
