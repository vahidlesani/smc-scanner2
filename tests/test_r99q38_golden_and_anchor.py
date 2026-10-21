"""R99q38i/j — the GOLDEN tier and the live-candle tool anchor (his 10-21).

«اگر بریک یک ترندلاین و ناحیه در هریک از ستاپ ها با هم اتفاق بیافته .. و قیمت
بالای موینگ ۲۱ و ۵۱ باشه یا یک سیگنال طلایی محسوب میشه که باید برچسب بخوره»
«ابزار لانگ و شورت در ابتدای تایید باید به کندل لایو لنگر بشه»
"""
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tape(n=120, start=100.0, step=0.0):
    ts = pd.date_range("2026-09-01", periods=n, freq="15min")
    px = [start + i * step for i in range(n)]
    return pd.DataFrame({"timestamp": ts, "open": px,
                         "high": [p * 1.002 for p in px],
                         "low": [p * 0.998 for p in px], "close": px,
                         "volume": [100.0] * n})


def _cand(**over):
    from analysis.models import SignalCandidate
    base = dict(signal_id="G1", symbol="TESTUSDT", style="SWING", setup_code="PINVAL",
                setup_name="t", strategy_fa="t", direction="LONG", score=8,
                status="NEAR_CONFIRM", entry_zone_bottom=99.0, entry_zone_top=100.5,
                planned_entry=100.2, sl=97.0, tp1=106.0, tp2=110.0,
                rr_tp1=1.2, rr_tp2=2.0, bias="BULL", trigger_timeframe="15m",
                metadata={"atr": 1.0, "touched": True})
    md = over.pop("metadata", {})
    base.update(over)
    base["metadata"].update(md)
    return SignalCandidate(**base)


def test_golden_needs_line_zone_and_both_moving_averages():
    from analysis.quality_engine import _grade_signal_tier
    df = _tape(step=0.05)                       # rising tape → close above MA21/MA51
    cand = _cand(metadata={"viva_break_line": 101.0})
    assert _grade_signal_tier(cand, df) == "GOLDEN"

    # no line → no tier
    assert _grade_signal_tier(_cand(), df) == ""

    # zone not cleared → no tier
    far_zone = _cand(metadata={"viva_break_line": 101.0})
    far_zone.entry_zone_top = 200.0
    assert _grade_signal_tier(far_zone, df) == ""

    # price under the averages → no tier
    falling = _tape(step=-0.05)
    assert _grade_signal_tier(_cand(metadata={"viva_break_line": 101.0}), falling) == ""


def test_the_tier_is_written_on_confirmation_and_stamped_on_the_card():
    src = open(os.path.join(ROOT, "analysis", "quality_engine.py"), encoding="utf-8").read()
    assert 'candidate.metadata["signal_tier"] = _grade_signal_tier(candidate, closed_df)' in src
    msg = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'signal_tier") or "").upper() == "GOLDEN"' in msg
    assert 'notes.insert(0, ("◆ GOLDEN SIGNAL", "#B7791F"))' in msg


def test_the_tool_starts_on_the_live_candle():
    msg = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'tool_start = int(_anchored_x(_entry_ts, max(0, count)))' in msg
    assert 'tool_start = int(_anchored_x(_entry_ts, max(0, count - 20)))' not in msg
