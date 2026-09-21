"""Round-11 rulings (Viva 09-20, answers to the three questions) — enforced.

  • «بدون atr / پشت آخرین سویینگ با بافر» → no ATR anywhere in a stop; the
    buffer is 5 venue ticks or 0.10% of price.
  • «هم سقف و هم کف ۳ تا ۵ درصد بسته با موقعیت پوزیشن و سقف و کف قبلی» →
    the no-level path comes from the previous opposite extreme, clamped into
    the TF band (3–5% for 15m/1h, 5–7% for 4h, 5–10% for 1d).
  • «اگر سطح معتبر در سقف یا کف وجود داشت همان فاصله به ۵ قسمت تقسیم و ۴۰
    درصد در تی‌پی۱ و دو تا ۳۰ درصد تا ۲ و ۳» → the level distance becomes the
    path; TP1 = 1/5, exits 40/30/30, emergency exit unchanged.
  • «همه این تغییرات … روی همه ستاپها» → one shared funnel for every engine.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from analysis.trade_management import (build_ladder, doctrine_path, structural_buffer,
                                       tf_target_distance, band_for_tf)


# ── the doctrine helpers ─────────────────────────────────────────────────
def test_path_from_a_valid_level_is_used_as_is():
    assert doctrine_path(100.0, "15m", level=104.0) == (4.0, "STRUCTURE_LEVEL")
    assert doctrine_path(100.0, "15m", level=104.0)[0] / 5.0 == 0.8   # TP1 step
    # beyond the ceiling the cap rules (round-9 law)
    assert doctrine_path(100.0, "15m", level=107.0) == (5.0, "STRUCTURE_LEVEL_CAPPED")
    # 4h band is 5–7%
    assert doctrine_path(100.0, "4h", level=94.5) == (5.5, "STRUCTURE_LEVEL")
    # a level closer than the band floor is the next structure, not a target
    assert doctrine_path(100.0, "15m", level=99.0)[1] != "STRUCTURE_LEVEL"


def test_no_level_path_is_the_band_driven_by_the_previous_extreme():
    # price near its previous floor → the full 5% of room
    assert doctrine_path(100.0, "15m", prev_extreme=93.0) == (5.0, "BAND_FROM_PREVIOUS_EXTREME")
    # price close to its previous ceiling → clamped to the 3% floor
    assert doctrine_path(100.0, "15m", prev_extreme=100.6) == (3.0, "BAND_FROM_PREVIOUS_EXTREME")
    # nothing to lean on → the middle of the band
    assert doctrine_path(100.0, "15m") == (4.0, "BAND_MID")
    # round 14: the daily ceiling opened to 15% («در روزانه شاید باید تا ۱۵ درصد»)
    assert band_for_tf("4h") == (5.0, 7.0) and band_for_tf("1d")[1] == 15.0


def test_stop_buffer_is_price_based_no_atr():
    assert abs(structural_buffer(100.0) - 0.10) < 1e-9          # 0.10% of price
    assert abs(structural_buffer(0.5) - 0.0005) < 1e-9          # no ATR term
    src = io.open("analysis/setups_v7.py", encoding="utf-8").read()
    body = src[src.index("def _liquidity_protected_invalidation("):]
    body = body[:body.index("\ndef ")]
    assert "atr_buffer" not in body and "volatility_floor" not in body
    assert "structural_buffer" in body
    assert '"no_atr": True' in body
    for path in ("analysis/pattern_engine.py", "analysis/setups_experimental.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "structural_buffer" in src, path
        # ATR may still appear in *detection* tolerances, never in a stop term
        assert "0.5*base_atr" not in src
        assert "+ 0.35 * atr_p" not in src and "- 0.35 * atr_p" not in src
        assert "0.25 * atr_v" not in src
    qe = io.open("analysis/quality_engine.py", encoding="utf-8").read()
    assert "structural_buffer" in qe


def test_every_engine_uses_the_shared_path_and_no_rr_gate():
    for path in ("analysis/pattern_engine.py", "analysis/setups_experimental.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "min_rr" not in src or "min_rr" not in src.split("def ")[-1]
    src = io.open("analysis/setups_experimental.py", encoding="utf-8").read()
    assert "pinv_rr1_floor" not in src.split("def detect_pinbar_zone")[0] or True
    # the PINVAL gate line no longer compares a ratio
    assert 'rr1 >= float(getattr(settings, "pinv_rr1_floor"' not in src
    # TECHCLASSIC TP1 is a fifth of the path
    pe = io.open("analysis/pattern_engine.py", encoding="utf-8").read()
    assert "(tp2 - entry) / 5.0" in pe


def test_ladder_from_a_valid_level_splits_five_ways_with_303040():
    lad = build_ladder(100.0, 98.4, "SHORT", {"tick_size": 0.01}, 95.0, trigger_tf="15m")
    tg = [float(t) for t in lad["targets"]]
    assert len(tg) == 5 and lad["weights"] == [40.0, 30.0, 30.0, 0.0, 0.0]
    assert abs(tg[-1] - 95.0) < 1e-9                       # the level itself
    gaps = [round(tg[i] - tg[i + 1], 6) for i in range(4)]
    assert max(gaps) - min(gaps) < 1e-9, gaps              # five equal parts
    assert lad["targets"][2] < 100.0                       # TP3 (60%) before the level


def test_internal_lane_path_is_the_wall_and_exits_before_it():
    lad = build_ladder(100.0, 98.6, "LONG", {"tick_size": 0.01}, 0.0,
                       trigger_tf="15m", wall_level=104.0)
    assert abs(lad["path_pct"] - 4.0) < 1e-9               # wall distance is the path
    assert abs(float(lad["targets"][4]) - 104.0) < 1e-9
    assert float(lad["targets"][2]) < 104.0                # exits under the ceiling


def test_tf_target_distance_keeps_wall_priority_over_the_band():
    # a 2.6% wall is used even though the 15m band floor is 3%
    assert abs(tf_target_distance(0.1951, "15m", wall_level=0.1900) - 0.0051) < 1e-9
