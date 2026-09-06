import pandas as pd
from analysis.viva_tlbreak import advance_live_state


def _r(o, h, l, c):
    return pd.Series({"open": o, "high": h, "low": l, "close": c})


def test_tlbreak_confirms_after_retest_then_micro_bos():
    zl, zh, direction, atr = 99.9, 100.2, "LONG", 1.0
    md = {"viva_state": "S2_BREAKOUT"}
    # retest bar pulls back into the zone
    s, ready = advance_live_state(
        md, _r(100.15, 100.3, 99.95, 100.05),
        _r(100.4, 100.5, 100.3, 100.4), direction,
        zone_low=zl, zone_high=zh, atr_value=atr,
    )
    assert s == "S3_RETEST" and ready is False
    md["viva_state"] = s
    # decisive directional bar breaks prior high at the retest
    s, ready = advance_live_state(
        md, _r(100.1, 101.2, 100.05, 101.1),
        _r(100.05, 100.3, 99.95, 100.1), direction,
        zone_low=zl, zone_high=zh, atr_value=atr,
    )
    assert s == "S5_MICRO_BOS" and ready is True


def test_tlbreak_confirms_on_same_bar_reject_plus_bos():
    zl, zh, direction, atr = 99.9, 100.2, "LONG", 1.0
    md = {"viva_state": "S3_RETEST"}
    # one decisive bar both rejects (strong close near high) and breaks prior high
    s, ready = advance_live_state(
        md, _r(100.0, 101.3, 99.95, 101.25),
        _r(100.1, 100.6, 99.9, 100.05), direction,
        zone_low=zl, zone_high=zh, atr_value=atr,
    )
    assert ready is True and s == "S5_MICRO_BOS"
