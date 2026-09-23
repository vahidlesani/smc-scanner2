"""Round-15 phase 2 — the shared «جهت الگو = جهت شکست = جهت معامله» law.

Viva's audit of his own chart set (09-21) found three live defects:

* a FALLING WEDGE — a bullish compression — published as SHORT while price had
  already closed ABOVE that wedge (XRP / AAVE / RENDER 15m);
* a RISING WEDGE published as LONG (AVAX / SEI 15m);
* a chart whose ladder read «PATH 0.00%» / «R:R -0.07» and still confirmed.

His law: pattern_type · pattern_bias · break_edge · break_direction ·
trade_direction must agree; if the side that actually broke is opposite to the
trade direction the setup is VOID — never silently flipped. When the pattern's
own bias disagrees with the broken side, the state is a BREAK of that pattern
and must carry a different state name, not the pattern's reversal.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cand(direction, setup="TLBREAK", **over):
    from analysis.models import SignalCandidate
    base = dict(signal_id="R15B-1", symbol="SUIUSDT", style="DAYTRADE",
                setup_code=setup, setup_name="t", strategy_fa="t",
                direction=direction, score=8, status="APPROACHING",
                entry_zone_bottom=99.0, entry_zone_top=100.0,
                planned_entry=99.5, sl=98.4, tp1=101.5, tp2=103.0,
                rr_tp1=1.0, rr_tp2=2.0, bias="BULL", trigger_timeframe="15m",
                mandatory_gates={"zone": True},
                created_at="2026-09-21T05:00:00+00:00",
                metadata={"atr": 1.0, "touched": True})
    base.update(over)
    return SignalCandidate(**base)


def _frame(closes, start="2026-09-21 05:00", freq="15min", pad=20):
    values = [float(c) for c in closes]
    pad_values = [min(values) - 1.5 - 0.01 * i for i in range(pad)]
    allc = pad_values + values
    ts = pd.date_range(start, periods=len(allc), freq=freq)
    return pd.DataFrame({"timestamp": ts,
                         "open": [c - 0.10 for c in allc],
                         "high": [c + 0.20 for c in allc],
                         "low": [c - 0.20 for c in allc],
                         "close": allc, "volume": [1000] * len(allc)})


def _band(kind="WEDGE_FALLING", lo=98.0, hi=102.0):
    return {"kind": kind, "lo": lo, "hi": hi, "slope_lo": 0.0, "slope_hi": 0.0,
            "ts_last": "2026-09-21 05:00", "tf_minutes": 15.0}


def test_pattern_bias_table_speaks_his_language():
    from analysis.quality_engine import pattern_bias_of
    assert pattern_bias_of("WEDGE_FALLING") == "BULL"      # گوه نزولی = صعودی
    assert pattern_bias_of("WEDGE_RISING") == "BEAR"       # گوه صعودی = نزولی
    assert pattern_bias_of("TRIANGLE_ASCENDING") == "BULL"
    assert pattern_bias_of("TRIANGLE_DESCENDING") == "BEAR"
    assert pattern_bias_of("TRIANGLE_SYMMETRICAL") == "NEUTRAL"
    assert pattern_bias_of("CHANNEL_ASCENDING") == "BULL"
    assert pattern_bias_of("CHANNEL_DESCENDING") == "BEAR"
    assert pattern_bias_of("") == "NEUTRAL"


def test_falling_wedge_broken_up_confirms_as_long_with_full_metadata():
    from analysis.quality_engine import evaluate_confirmation
    cand = _cand("LONG", entry_zone_bottom=101.4, entry_zone_top=102.0,
                 sl=100.0, tp1=103.5, tp2=105.0,
                 metadata={"atr": 1.0, "touched": True,
                           "pattern_band": _band("WEDGE_FALLING")})
    ok, c2, reason = evaluate_confirmation(cand, _frame([101.9, 102.4]))
    assert ok is True, reason
    md = c2.metadata
    assert md["pattern_type"] == "WEDGE_FALLING"
    assert md["pattern_bias"] == "BULL"
    assert md["break_edge"] == "UPPER"
    assert md["break_direction"] == "UP"
    assert md["trade_direction"] == "LONG"
    assert md["direction_reason"]


def test_short_on_a_falling_wedge_that_broke_up_is_void():
    """The exact defect he photographed: bullish pattern, close above it, SHORT
    still approved. The confirmation must be refused."""
    from analysis.quality_engine import evaluate_confirmation
    cand = _cand("SHORT", sl=103.0, tp1=98.0, tp2=96.5,
                 entry_zone_bottom=100.0, entry_zone_top=100.5,
                 metadata={"atr": 1.0, "touched": True,
                           # an inside-band level that used to let the fast lane
                           # skip the containment gate entirely — the leak
                           "tl_fast_break": "stale", "confirm_level_used": 101.5,
                           "pattern_band": _band("WEDGE_FALLING")})
    ok, c2, reason = evaluate_confirmation(cand, _frame([101.8, 102.4]))
    assert ok is False
    assert c2.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH", reason


def test_long_on_a_rising_wedge_that_broke_down_is_void():
    from analysis.quality_engine import evaluate_confirmation
    cand = _cand("LONG", metadata={"atr": 1.0, "touched": True,
                                   "pattern_band": _band("WEDGE_RISING")})
    ok, c2, reason = evaluate_confirmation(cand, _frame([98.2, 97.5]))
    assert ok is False
    assert c2.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH", reason


def test_detector_contract_rejects_opposite_trade_direction():
    """A detector-created UP break cannot later become a SHORT via a generic lane."""
    from analysis.quality_engine import evaluate_confirmation
    cand = _cand("SHORT", sl=103.0, tp1=98.0, tp2=96.5,
                 metadata={"atr": 1.0, "touched": True,
                           "strategy_variant": "VIVA_TLBREAK",
                           "break_direction": "UP",
                           "pattern_type": "CHANNEL_ASCENDING"})
    ok, c2, reason = evaluate_confirmation(cand, _frame([101.8, 102.4]))
    assert ok is False
    assert c2.metadata.get("last_reject_code") == "BREAK_SIDE_MISMATCH", reason


def test_break_against_the_bias_keeps_its_own_state_name():
    """His rule: a falling wedge broken DOWN is not a bullish reversal — it is a
    BREAKDOWN and must be published under that state name."""
    from analysis.quality_engine import evaluate_confirmation
    cand = _cand("SHORT", sl=98.6, tp1=96.8, tp2=95.5, bias="BEAR",
                 entry_zone_bottom=97.5, entry_zone_top=98.2,
                 metadata={"atr": 1.0, "touched": True, "tl_fast_break": "stale",
                           "confirm_level_used": 99.0,
                           "pattern_band": _band("WEDGE_FALLING"),
                           "render_patterns": [{"type": "WEDGE_FALLING",
                                                "lo": 98.0, "hi": 102.0}]})
    # a frame whose recent bars are the LOWEST of the window (a genuine
    # down-side break, so the counter-trend touch gate has nothing to say)
    vals = [102.6 - 0.05 * i for i in range(20)] + [98.4, 97.4]
    ts = pd.date_range("2026-09-21 05:00", periods=len(vals), freq="15min")
    frame = pd.DataFrame({"timestamp": ts,
                          "open": [c + 0.10 for c in vals],
                          "high": [c + 0.20 for c in vals],
                          "low": [c - 0.20 for c in vals],
                          "close": vals, "volume": [1000] * len(vals)})
    ok, c2, reason = evaluate_confirmation(cand, frame)
    assert ok is True, reason
    md = c2.metadata
    assert md["break_direction"] == "DOWN"
    assert md["pattern_state_label"] == "WEDGE_FALLING · BREAKDOWN"
    assert "شکست نزولی" in md["direction_reason"]
    assert md["render_patterns"][0]["label"] == "WEDGE_FALLING · BREAKDOWN"


def test_zero_path_ladder_never_confirms():
    from analysis.quality_engine import evaluate_confirmation
    cand = _cand("LONG", setup="PINVAL",
                 metadata={"atr": 1.0, "touched": True, "pin_high": 100.0,
                           "pin_low": 97.6, "pin_tf": "15m",
                           "target_ladder": {"path_pct": 0.2}})
    ok, c2, reason = evaluate_confirmation(cand, _frame([100.2, 100.4]))
    assert ok is False
    assert c2.metadata.get("last_reject_code") == "ZERO_TARGET_PATH", reason


def test_ladder_on_the_wrong_side_of_entry_never_confirms():
    from analysis.quality_engine import evaluate_confirmation
    cand = _cand("LONG", setup="PINVAL", tp1=99.0, tp2=98.0,
                 metadata={"atr": 1.0, "touched": True, "pin_high": 100.0,
                           "pin_low": 97.6, "pin_tf": "15m",
                           "target_ladder": {"path_pct": 2.0}})
    ok, c2, reason = evaluate_confirmation(cand, _frame([100.2, 100.4]))
    assert ok is False
    assert c2.metadata.get("last_reject_code") == "ENTRY_AFTER_TARGET", reason


def test_chart_prints_no_rr_and_no_zero_path():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "bot", "messages_v7.py"), encoding="utf-8").read()
    # no R:R read-out is ever COMPOSED for the chart panel (comments may still
    # explain why it is gone)
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    _f = "f"          # built by concatenation so this test never trips the
    _cq = '"'         # PEP-701 lint on itself
    assert _f + _cq + "R:R" not in code and _f + _cq + "R/R" not in code
    assert _f + _cq + "PATH  " not in code
    # the PATH read-out is guarded (nothing printed under 0.5%)
    assert 'if _pathp8 >= 0.5:' in src
