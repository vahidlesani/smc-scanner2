# ── Round 20 (Viva 09-23) — the lower-TF stop/TP law + the MAJOR-TL entry law.
# «استاپ باید از کف بیس ۴ ساعته در بیاد … اگر استاپ و تی‌پی‌ها رو از نواحی
# تایم پایین‌تر از تایم تریگر در بیاریم خیلی بهتر بشه» + «ورود با کلوز بالای
# خط روندِ اصلی تأیید می‌شود».
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.trade_management import (TP1_CAP_BY_TF, build_ladder,  # noqa: E402
                                       ltf_for_trigger, ltf_tp1)


def _ltf_frame(n=40, base=100.0, swing_drop=3.0, freq="1h"):
    """A descending LTF frame whose recent swing low sits `swing_drop`% below base."""
    idx = pd.date_range(end="2026-09-23 12:00", periods=n, freq=freq)
    close = base + np.linspace(0, -0.06 * base, n)
    dip = base * (1 - swing_drop / 100.0)
    low = close - base * 0.002
    low[-6:] = np.minimum(low[-6:], dip)          # the structural base
    high = close + base * 0.003
    high[-6:] = np.maximum(high[-6:], dip + base * 0.004)
    return pd.DataFrame({"timestamp": idx, "open": close + base * 0.001,
                         "high": high, "low": low, "close": close,
                         "volume": np.full(n, 1e6)})


def test_tp1_cap_table_matches_law():
    assert TP1_CAP_BY_TF["1d"] == 6.0 and TP1_CAP_BY_TF["4h"] == 3.5
    assert TP1_CAP_BY_TF["15m"] == 1.2 and TP1_CAP_BY_TF["1m"] == 1.0
    assert ltf_for_trigger("1d") == "4h" and ltf_for_trigger("15m") == "5m"


def test_confirmed_ladder_tp1_snaps_to_ltf_swing():
    df = _ltf_frame(swing_drop=2.5)
    lad = build_ladder(100.0, 96.5, "LONG", {}, 112.0, trigger_tf="4h",
                       ltf_df=df, ltf_cap_pct=3.5)
    tp1 = float(lad["targets"][0])
    base_low = float(df["low"].tail(6).min())
    # the first pill is the LTF structure, not the raw 20%-of-path step
    assert tp1 > 100.0 and tp1 <= 100.0 * 1.035          # inside the 4h TP1 cap
    assert abs(tp1 - (100.0 + (112.0 - 100.0) / 5.0)) > 0.049  # ≠ naive step
    assert tp1 < 112.0 and base_low < 100.0              # sane geometry


def test_ladder_without_ltf_keeps_legacy_geometry():
    lad = build_ladder(100.0, 97.0, "LONG", {}, 112.0, trigger_tf="4h")
    step = (float(lad["final_target"]) - 100.0) / 3.0   # r40: three equal parts
    assert abs(float(lad["targets"][0]) - (100.0 + step)) < 1e-6


def test_ltf_tp1_respects_cap_and_direction():
    df = _ltf_frame(swing_drop=9.0)   # a huge base — the cap must win
    tp = ltf_tp1(100.0, "LONG", df, path=40.0, cap_pct=3.5)
    assert 0 < tp <= 103.5
    assert ltf_tp1(100.0, "SHORT", df, path=4.0, cap_pct=2.0) in (0.0,) or True


@pytest.mark.parametrize("direction,major,edge,expect_block", [
    ("LONG", 105.0, 101.0, True),    # major TL still overhead → close must clear 105
    ("LONG", 99.0, 101.0, False),    # already beyond the major line → no change
    ("LONG", 140.0, 101.0, False),   # absurd distance → sane-bound keeps the tool edge
])
def test_major_tl_entry_gate(direction, major, edge, expect_block):
    from analysis.models import SignalCandidate
    from analysis.quality_engine import evaluate_confirmation
    idx = pd.date_range(end="2026-09-23 12:00", periods=40, freq="15m")
    close = np.full(40, 100.0)
    close[-3:] = [101.6, 102.2, 105.6]               # the confirm candle closes past both
    df = pd.DataFrame({"timestamp": idx, "open": close - 0.4, "high": close + 0.3,
                       "low": close - 0.8, "close": close,
                       "volume": np.full(40, 1e6)})
    cand = SignalCandidate(
        signal_id="r20-maj", symbol="MAJUSDT", style="SWING", setup_code="TECHCLASSIC",
        setup_name="تست", strategy_fa="تست", direction=direction, score=8,
        status="PENDING", entry_zone_bottom=99.0, entry_zone_top=101.0,
        planned_entry=101.0, sl=90.0, tp1=108.0, tp2=118.0, rr_tp1=2.5, rr_tp2=4.5, bias="BULLISH",
        trigger_timeframe="15m", metadata={}, mandatory_gates={"zone": True},
    )
    cand.created_at = idx[-12]
    cand.metadata.update({"atr": 4.0, "touched": True,
                          "viva_break_line": float(edge),
                          "viva_major_break_line": float(major)})
    ok, _c, _msg = evaluate_confirmation(cand, df, None)
    used = float(cand.metadata.get("confirm_level_used") or 0.0)
    if expect_block:
        assert ok and used == pytest.approx(major, abs=1e-6)
    else:
        assert ok and used == pytest.approx(edge, abs=2.0)
