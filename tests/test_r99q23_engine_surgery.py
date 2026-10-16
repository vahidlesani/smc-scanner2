"""R99q23 — the PER-ENGINE surgery law (his 10-17: «شروع کن ستاپ‌ها رو از
تکنوکلاسیک تا البروکس و تی‌ال‌بریک و پینوال»).

Every engine stamps its OWN candidate in its OWN file with the law
(`pattern_law.engine_stamp`), and the alert itself must carry those stamps:
the slug the classifier actually drew, the selection state it stands in (the
seven conditions of R99q22) and that pattern's ENGINE REFERENCE.
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analysis.pattern_law import PATTERN_LAW, engine_stamp   # noqa: E402


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _frame(n=120, slope=-0.15, base=100.0):
    closes = [base + slope * x for x in range(n)]
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-09-01", periods=n, freq="1h"),
        "open": closes, "high": [c + 0.4 for c in closes],
        "low": [c - 0.4 for c in closes], "close": closes,
        "volume": [1.0] * n})


# ── 1) every engine calls the stamp in its OWN file ──────────────────────
def test_each_setup_engine_stamps_its_own_candidate():
    assert "engine_stamp" in _src("analysis/techclassic.py")          # TECHCLASSIC
    assert "engine_stamp" in _src("analysis/setups_v7.py")            # the mint choke
    exp = _src("analysis/setups_experimental.py")
    assert exp.count("engine_stamp") >= 3                             # TLBREAK + PINVAL + ALBROX
    for tag in ('"TLBREAK"', '"PINVAL"', '"ALBROX"'):
        assert f"_es23(" in exp and tag in exp, f"{tag} must stamp its own lane"


def test_the_stamp_is_not_inside_the_shared_render_kit():
    """The surgery law says each engine is corrected in its own files — the
    shared plumbing must only make room for the stamp, never run it."""
    assert "engine_stamp" not in _src("analysis/render_kit.py")


# ── 2) what the stamp writes ─────────────────────────────────────────────
def test_stamp_carries_slug_state_and_engine_reference():
    md = {"render_patterns": [
        {"type": "WEDGE_FALLING", "law_slug": "WEDGE_FALLING",
         "lines": [{"slope": -0.3, "intercept": 130.0, "side": "HIGH", "x0": 0, "x1": 119},
                   {"slope": -0.1, "intercept": 100.0, "side": "LOW", "x0": 0, "x1": 119}],
         "select_state": "RETEST_UPPER", "near_break": True, "dist_atr": 0.3}]}
    info = engine_stamp(md, _frame(), "TECHCLASSIC")
    assert info["law_slug"] == "WEDGE_FALLING"
    assert md["law_state"] == "RETEST_UPPER"
    assert md["law_state_fa"] and "ریتست" in md["law_state_fa"]
    assert md["pattern_ref"] == PATTERN_LAW["WEDGE_FALLING"]["ref"]
    assert md["pattern_rule_fa"] == PATTERN_LAW["WEDGE_FALLING"]["rule"]
    assert md["pattern_bias"] == "BULL" and md["pattern_break_side"] == "UPPER"


def test_single_trendline_lane_gets_state_role_and_candle_evidence():
    """His condition 7 inside an engine: a lone line is judged, and the
    trigger-TF candle (pin bar / inverted pin bar / doji) rides along."""
    n = 120
    ln = {"slope": -0.20, "intercept": 120.0, "x0": 0, "x1": n - 1, "side": "HIGH"}
    closes = [-0.20 * x + 120.0 - 0.3 for x in range(n)]
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-09-01", periods=n, freq="1h"),
        "open": closes, "high": [c + 0.25 for c in closes],
        "low": [c - 0.25 for c in closes], "close": closes,
        "volume": [1.0] * n})
    md = {"render_patterns": [{"type": "TRENDLINE", "law_slug": "TRENDLINE",
                               "lines": [ln], "near_break": True}]}
    info = engine_stamp(md, df, "TLBREAK")
    assert info["line_state"] in ("TOUCH", "NEAR", "COMPRESSION", "REJECTED",
                                  "FRESH_BREAK", "RETEST_BE")
    assert md["line_role"] in ("SUPPORT", "RESISTANCE")
    assert "line_state_fa" in md


def test_a_stamp_never_vetoes_a_candidate():
    """The engines keep measuring: the ONE veto lives at the publish boundary."""
    md = {"render_patterns": [{"type": "TRENDLINE", "law_slug": "TRENDLINE",
                               "lines": [{"slope": 0.0, "intercept": 10.0,
                                          "side": "HIGH", "x0": 0, "x1": 119}]}]}
    info = engine_stamp(md, _frame(base=100.0), "PINVAL")
    assert info is not None and "law_state" in md


# ── 3) the alert carries the law ─────────────────────────────────────────
def test_the_alert_prints_the_law_block():
    src = _src("bot/messages_v7.py")
    assert "def _law_note_lines(" in src
    assert "*_law_note_lines(candidate)" in src
    for token in ("🧩 الگو:", "📖 مرجع:", "📐 وضعیت خط:", "🕯 شاهد کندلی"):
        assert token in src, f"the caption must be able to print {token}"


def test_techclassic_declares_when_it_is_still_waiting_for_the_edge():
    src = _src("analysis/techclassic.py")
    assert "tc_awaits_edge" in src
    assert "داخل پترن" in src
