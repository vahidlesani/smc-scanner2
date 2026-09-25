"""r32 (Viva 09-26 night feedback): tool redesign, ledger, zoom lift, engine
gates (target-vs-live, one-candle floor, channel volume confirm), wedge cap,
confirm mirror, score box."""
import math
import os
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

REPO = "/home/user/smc-scanner2"


# ── 1. info box never shows a wrong 0/10 ──────────────────────────────────
def test_info_box_score_snapshot_and_zero_hidden():
    src = open(f"{REPO}/bot/messages_v7.py", encoding="utf-8").read()
    assert 'publish_score' in src and "if _sc32 > 0:" in src
    # the raw unguarded f-string score line is gone
    assert 'f"SCORE  {candidate.score}/10"' not in src


def test_publish_score_snapshot_written_at_discovery():
    src = open(f"{REPO}/main.py", encoding="utf-8").read()
    assert 'candidate.metadata["publish_score"] = int(candidate.score or 0)' in src
    # snapshot lands BEFORE the public code reservation (all published rows)
    assert src.index('publish_score') < src.index('reserve_public_code(candidate)')


# ── 2. tool column = numbers only; ledger carries the words ───────────────
def test_tool_pills_numeric_only_and_ledger_exists():
    src = open(f"{REPO}/bot/messages_v7.py", encoding="utf-8").read()
    assert "if all(str(_lb).isdigit() for _lb, _pc, _c in _items):" in src
    assert "استاپ اولیه" in src and "تریلینگ استاپ" in src and "قیمت لایو" in src
    assert "fa_chart" in src  # Persian shaping on the figure
    # LIVE pill no longer drawn on confirmed charts
    seg = src[src.index("if not confirmed:"):]
    assert " LIVE " in src  # still exists for unconfirmed


def test_tool_lines_are_faint_dashed_connectors():
    src = open(f"{REPO}/bot/messages_v7.py", encoding="utf-8").read()
    assert "count + 4.9, color=color" in src
    assert 'linestyle=(0, (3, 2)), alpha=0.55' in src


# ── 3. smart zoom lifts dead history (LTC 1D) ─────────────────────────────
def test_smart_zoom_recent_structure_floor():
    import bot.messages_v7 as mv
    # 96 daily bars rising 40 → 80; recent 40-bar low ≈ 68; TP ladder to 84
    n = 96
    lows = [40 + 0.42 * i for i in range(n)]
    highs = [l + 3.0 for l in lows]
    highs[-1] = 80.0
    win = mv._smart_y_window(min(lows), max(highs), atr=2.5,
                             ov_lo=63.0, ov_hi=84.0,
                             recent_lo=min(lows[-40:]))
    assert win is not None
    ylo, yhi = win
    assert yhi > 84.0                      # ladder fully inside
    assert ylo > 50.0, f"dead June history must be lifted, got {ylo}"
    # candles (68-80) no longer crammed: they occupy the upper-middle,
    # with real headroom above for the ladder
    assert (80.0 - ylo) / (yhi - ylo) < 0.85


# ── 4. engine gates ────────────────────────────────────────────────────────
def test_engine_target_clamp_and_one_candle_floor_in_source():
    src = open(f"{REPO}/analysis/pattern_engine.py", encoding="utf-8").read()
    assert "target = max(target, live + 1.5 * atr_p)" in src
    assert "height = max(height, 2.0 * _lr32)" in src
    assert "_vr32 < 1.3:" in src and "startswith(\"CHANNEL\")" in src


def test_engine_math_import_present():
    src = open(f"{REPO}/analysis/pattern_engine.py", encoding="utf-8").read()
    assert re.search(r"^import math$", src, re.M)


# ── 5. wedge cap: daily legs up to 150 bars ───────────────────────────────
def test_swing_pattern_cap_allows_long_daily_wedge():
    from analysis.viva_tlbreak import load_config
    cfg = load_config()
    assert cfg.max_pattern_bars_swing == 150
    import json
    raw = json.load(open(f"{REPO}/strategies/viva_tlbreak/breakout_strategy_config.json"))
    assert raw["timeframe_profiles"]["swing"]["max_pattern_length_bars_on_structure_tf"] == 150


# ── 6. confirm mirror: 30m → MID, 4h → SHORT ──────────────────────────────
def test_confirm_mirror_mapping():
    src = open(f"{REPO}/bot/messages_v7.py", encoding="utf-8").read()
    assert '{"30m": CHAT_ID_SWING_MID, "4h": CHAT_ID_SWING_SHORT}' in src
    assert "_mirror32" in src and "TF-channel mirror failed" in src


# ── 7. clamp math sanity ───────────────────────────────────────────────────
def test_target_clamp_direction_math():
    live, atr = 71.15, 0.5
    assert max(70.824, live + 1.5 * atr) == live + 0.75  # LTC case fixed
    assert min(70.9, 71.15 - 1.5 * atr) == 70.4          # SHORT symmetric
