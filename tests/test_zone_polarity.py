"""Unit tests for the PINVAL Zone Polarity Gate (analysis.zone_polarity).

Each fixture builds a context frame with ONE unambiguous structural wall so the
nearest-wall decision is deterministic:
  * demand  : clear swing LOW shelf that price is sitting on
  * supply  : clear swing HIGH shelf that price is pressed under
  * flip    : that supply decisively broken with a closed candle, then retest
"""
from __future__ import annotations

import pandas as pd

from analysis.zone_polarity import evaluate_polarity


def _frame(rows):
    ts = pd.Timestamp("2026-01-01")
    out = []
    for i, (o, h, l, c, v) in enumerate(rows):
        out.append(dict(
            timestamp=ts + pd.Timedelta(hours=i),
            open=o, high=h, low=l, close=c, volume=v,
        ))
    return pd.DataFrame(out)


def _range(n=140, lo=100.0, hi=104.0):
    """Sideways range: repeated swing-high pivots near ``hi`` and swing-low
    pivots near ``lo`` so both walls are unambiguous."""
    rows = []
    ts = pd.Timestamp("2026-01-01")
    price = (lo + hi) / 2
    i = 0
    while len(rows) < n:
        # drop to the floor: 3 red bars tagging ~lo
        for _ in range(3):
            o = price; c = max(lo + 0.3, o - 0.9)
            h = o + 0.3
            l = min(o, c) - 0.5
            if len(rows) % 12 == 0:
                l = lo - 0.1  # clean demand sweep wick
            rows.append((o, max(h, max(o, c) + 0.2), l, c, 1000))
            price = c
        # rally to the ceiling: 3 green bars tagging ~hi
        for _ in range(3):
            o = price; c = min(hi - 0.3, o + 0.9)
            l = o - 0.3
            h = max(o, c) + 0.5
            if len(rows) % 12 == 6:
                h = hi + 0.1  # clean supply sweep wick
            rows.append((o, h, min(l, min(o, c) - 0.2), c, 1200))
            price = c
    return _frame(rows[:n])


DEMAND = 100.0
SUPPLY = 104.0


def test_bullish_pin_at_demand_is_allowed():
    df = _range()
    v = evaluate_polarity(df, None, "LONG", DEMAND + 0.1, 1.0)
    assert v.allowed is True
    assert v.reason == "AT_DEMAND"


def _ending_near(df, level, top=True):
    """Re-anchor the latest closed candles near ``level`` so the probe/price is at
    that wall (the real detector evaluates the just-closed pin candle)."""
    rows = df.to_dict("records")
    ts = df["timestamp"].iloc[-1]
    if top:
        # price rallied into supply; last bar high tags ~level, close under it.
        extra = [
            (101.5, level + 0.1, 101.3, 103.0, 2600),
            (103.0, level + 0.05, 102.9, 103.6, 3000),
        ]
    else:
        # price dropped into demand; last bar low tags ~level, close above it.
        extra = [
            (102.5, 102.7, level - 0.1, 101.0, 2600),
            (101.0, 101.1, level - 0.05, 100.4, 3000),
        ]
    for k, (o, h, l, c, vv) in enumerate(extra, 1):
        rows.append(dict(timestamp=ts + pd.Timedelta(hours=k),
                         open=o, high=h, low=l, close=c, volume=vv))
    return _frame([(r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows])


def test_bullish_pin_under_supply_is_rejected():
    df = _ending_near(_range(), SUPPLY + 0.3, top=True)
    # bullish pin's rejection low sits right under the supply ceiling
    v = evaluate_polarity(df, None, "LONG", SUPPLY - 0.1, 1.0)
    assert v.allowed is False
    assert v.reason == "UNDER_SUPPLY"


def test_bearish_pin_at_supply_is_allowed():
    df = _ending_near(_range(), SUPPLY + 0.3, top=True)
    # bearish pin's rejection high tags the supply ceiling
    v = evaluate_polarity(df, None, "SHORT", SUPPLY + 0.2, 1.0)
    assert v.allowed is True
    assert v.reason == "AT_SUPPLY"


def test_bearish_pin_above_demand_is_rejected():
    df = _range()
    v = evaluate_polarity(df, None, "SHORT", DEMAND + 0.1, 1.0)
    assert v.allowed is False
    assert v.reason == "ABOVE_DEMAND"


def test_bullish_pin_after_valid_supply_breakout_flip_is_allowed():
    df = _range()
    ts = df["timestamp"].iloc[-1]
    extra = [
        (SUPPLY - 0.4, SUPPLY + 1.5, SUPPLY - 0.6, SUPPLY + 1.2, 5000),
        (SUPPLY + 1.2, SUPPLY + 2.8, SUPPLY + 1.0, SUPPLY + 2.5, 6000),
        (SUPPLY + 2.5, SUPPLY + 2.6, SUPPLY - 0.1, SUPPLY + 0.3, 2000),
    ]
    rows = df.to_dict("records")
    for k, (o, h, l, c, vv) in enumerate(extra, 1):
        rows.append(dict(timestamp=ts + pd.Timedelta(hours=k),
                         open=o, high=h, low=l, close=c, volume=vv))
    brk = _frame([(r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows])
    # pin low retests the broken supply shelf (~SUPPLY), now support/flip.
    v = evaluate_polarity(brk, None, "LONG", SUPPLY + 0.1, 1.0, breakout_body_atr=0.5)
    assert v.allowed is True
    assert v.reason == "SUPPLY_FLIP"
