"""r40 laws (Viva 09-26 evening report) — same-commit proofs.

① CHART-FILL: the smart y-window must keep the WHOLE rendered tape inside
   the panel — early bars of a pumping frame used to render invisible and
   leave the left half of the price panel empty (SEI/POL 09-26).
② PIVOT-AGE: valid lines whose last touch is older than ~50 candles must
   survive (the 0.30·n liveness cap killed exactly the MAJOR edges).
③ CONFIRM-GATE: a fresh opposite break of a watched line vetoes the confirm
   regardless of the 3·ATR relevance filter; inside ranges only ALBROX and
   the pin family take the INTERNAL lane.
④ SETUP-CONSOLIDATION: PINWALLQ is no longer emitted; its quality audit
   rides the classic PINVAL (PINWALL LEGACY).
⑤ LADDER: three pills, exits 40/30/30, TP3 IS the final target.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── ① CHART-FILL ─────────────────────────────────────────────────────────────

def test_smart_window_keeps_whole_tape_inside():
    """SEI/POL 09-26: frame 0.060–0.080, recent-40 at 0.072–0.079 — the old
    base (recent-span/0.6) put ylo ≈ 0.0696 and the early candles rendered
    INVISIBLE below the panel (empty left half)."""
    from bot.messages_v7 import _smart_y_window
    out = _smart_y_window(0.060, 0.080, atr=0.0012,
                          ov_lo=0.0716, ov_hi=0.0767,
                          recent_lo=0.072, recent_hi=0.079)
    assert out is not None
    ylo, yhi = out
    assert ylo <= 0.060, (ylo, yhi)
    assert yhi >= 0.080, (ylo, yhi)


def test_smart_window_far_overlay_still_fights_the_basement():
    """r28 DASH law survives r40: candles hard, far overlays still capped."""
    from bot.messages_v7 import _smart_y_window
    ylo, yhi = _smart_y_window(55.0, 65.0, atr=4.0, ov_lo=13.3, ov_hi=65.0)
    assert ylo > 40.0 and ylo < 55.0 < yhi


def test_info_box_says_3_parts():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "3 PARTS" in src and "5 PARTS" not in src


# ── ② PIVOT-AGE ──────────────────────────────────────────────────────────────

def test_line_alive_keeps_major_edge_touched_80_bars_ago():
    """n=164: the old 0.30·n cap (~49 bars) killed a line last touched 80
    bars ago — a major edge price consolidated under. r40 keeps it."""
    from analysis.pattern_engine import _line_alive
    line = SimpleNamespace(touch_count=3, last_index=164 - 80, first_index=0)
    assert _line_alive(line, 164) is True


def test_line_alive_still_rejects_fossils():
    from analysis.pattern_engine import _line_alive
    line = SimpleNamespace(touch_count=3, last_index=3, first_index=0)
    assert _line_alive(line, 164) is False          # 161/164 untouched
    line2 = SimpleNamespace(touch_count=2, last_index=160, first_index=0)
    assert _line_alive(line2, 164) is False          # too few touches


# ── ③ CONFIRM-GATE ───────────────────────────────────────────────────────────

def test_fresh_break_veto_present_in_engine():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "analysis", "quality_engine.py"), encoding="utf-8").read()
    # the veto scans the last 6 closed bars BEFORE the relevance filter
    assert "len(closed_df) - 6" in src
    assert "ساختارِ شکسته‌شده به پایین تأیید نمی‌شود" in src
    assert "ساختارِ شکسته‌شده به بالا تأیید نمی‌شود" in src
    # internal (range) lane restricted to ALBROX + pin family
    assert '"ALBROX", "PINVAL", "PINWALLQ"' in src


def test_tlbreak_up_long_is_not_vetoed_by_own_high_side_break():
    """A break/retest LONG closing ABOVE its high-side line is the lane
    itself — only LOW-side fresh down-breaks veto LONGs (mirror for shorts)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "analysis", "quality_engine.py"), encoding="utf-8").read()
    assert 'candidate.direction == "LONG" and _bs6 == "LOW"' in src
    assert 'candidate.direction == "SHORT" and _bs6 == "HIGH"' in src


# ── ④ SETUP-CONSOLIDATION ────────────────────────────────────────────────────

def test_pinwallq_no_longer_emitted_and_quality_merged_into_classic():
    from analysis import setups_experimental as exp
    assert exp.PINWALL_QUALITY_DETECTORS == []
    src = open(os.path.abspath(exp.__file__), encoding="utf-8").read()
    # the classic detector folds the Q audit in
    assert "_pinwall_quality_score(_qdf, best.direction, best)" in src
    # the detector function itself stays (legacy rows keep rendering)
    assert "def detect_pinwall_quality" in src


def test_pinwall_quality_score_components():
    import pandas as pd
    from analysis.setups_experimental import _pinwall_quality_score
    rows = []
    px = 100.0
    for i in range(30):
        o = px; c = px + 0.05; h = c + 0.02; l = o - 0.02
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": 10.0})
        px = c
    # the pin candle: long lower wick, tiny body at the top of the range
    rows[-1] = {"open": px, "high": px + 0.05, "low": px - 1.2,
                "close": px + 0.03, "volume": 10.0}
    df = pd.DataFrame(rows)
    score, details = _pinwall_quality_score(df, "LONG", SimpleNamespace(metadata={}))
    assert set(details) == {"anatomy", "location", "context", "bias", "total"}
    assert details["anatomy"] > 0
    assert score == details["total"]


# ── ⑤ LADDER ─────────────────────────────────────────────────────────────────

def test_ladder_three_pills_tp3_is_final():
    from analysis.trade_management import build_ladder
    p = build_ladder(100, 98, "LONG", {"tick_size": 0.01}, 110, trigger_tf="1d")
    assert len(p["targets"]) == 3
    assert p["targets"][-1] == 110.0
    assert p["weights"] == [40.0, 30.0, 30.0]


def test_ladder_source_has_no_five_part_split():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "analysis", "trade_management.py"), encoding="utf-8").read()
    assert "_path / 3.0" in src
    assert "range(3)" in src
    assert "_path / 5.0" not in src and "range(5)" not in src
