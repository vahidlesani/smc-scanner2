"""R99q21 — THE PATTERN LAW (his 10-16 night, verbatim: «شرایط درست تشخیص
پترن‌ها در رندر یا انجین تشخیص پترن‌ها کد نشده … حدود ۱۳ یا ۱۴ پترن رو کدنویسی
بکنی مثل فالینگ وج و رفرنس بدی به موتورهای هوشمند … دبل تاپ و دبل باتم و سر و
شانه رو از اون ۱۶ پترن کم بکن»).

What is locked here:
  * ONE reference law file, with an engine reference for every live pattern;
  * the retired pivot shapes really are retired (never emitted, never traded);
  * every drawn shape carries the law's verdict (slug · bias · break side ·
    near-break), so spot, setups and the message layer cannot disagree;
  * past-market patterns are gated out of alerts — but the confirmation
    layer's calibrated projections are NOT starved by that gate.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest


# ─────────────────────────── the law itself ───────────────────────────
def test_thirteen_patterns_have_names_refs_and_persian_rules():
    from analysis import pattern_law as L
    live = {k: v for k, v in L.PATTERN_LAW.items() if L.pattern_is_live(k)}
    assert len(live) >= 14, f"his floor is 13-14 coded patterns, got {len(live)}"
    for slug, d in live.items():
        assert d.get("fa"), f"{slug} has no Persian name"
        assert d.get("ref"), f"{slug} carries no ENGINE REFERENCE (his ask)"
        assert d.get("rule"), f"{slug} has no coded rule"
        assert str(d.get("bias")) in ("BULL", "BEAR", "NEUTRAL")
        assert str(d.get("break")) in ("UPPER", "LOWER", "ANY")


def test_the_three_retired_families_are_really_retired():
    from analysis import pattern_law as L
    for dead in ("DOUBLE_TOP", "DOUBLE_BOTTOM", "HEAD_SHOULDERS",
                 "INV_HEAD_SHOULDERS", "CUP_HANDLE", "INV_CUP_HANDLE"):
        assert dead in L.RETIRED_PATTERNS
        assert not L.pattern_is_live(dead)


def test_falling_wedge_is_the_reference_pattern():
    """His yardstick: «تنها پترنی که تشخیص میده فالینگ وج هست» — it must stay."""
    from analysis import pattern_law as L
    assert L.pattern_is_live("WEDGE_FALLING")
    assert L.bias_of("WEDGE_FALLING") == "BULL"
    assert L.break_side_of("WEDGE_FALLING") == "UPPER"


# ───────────────────── the classifier is the only path ─────────────────────
def _frame(ic_u, slope_u, ic_l, slope_l, n=150):
    """A clean converging tape: the zigzag rides the two rails, so both edges
    are testable (the fitter needs pivots on BOTH rails)."""
    import math as _m
    rows = []
    for i in range(n):
        u = ic_u + slope_u * i
        l = ic_l + slope_l * i
        t = 0.5 + 0.45 * _m.sin(i * _m.pi / 5.0)
        c = l + (u - l) * t
        rows.append({"timestamp": pd.Timestamp("2026-09-01") + pd.Timedelta(hours=4 * i),
                     "open": c, "high": max(u, c), "low": min(l, c), "close": c,
                     "volume": 1000.0})
    return pd.DataFrame(rows)


def _pair(df):
    n = len(df)
    up = {"slope": -0.30, "intercept": 160.0, "x0": 0, "x1": n - 1}
    lo = {"slope": -0.10, "intercept": 100.0, "x0": 0, "x1": n - 1}
    return up, lo


def test_law_classifies_a_falling_wedge_with_a_recorded_reason():
    """His own yardstick pattern: a steeper descending upper edge over a gentler
    descending lower edge IS a falling wedge, and the law says why."""
    from analysis.pattern_law import classify_pair, pair_metrics
    df = _frame(160.0, -0.30, 100.0, -0.10)
    up, lo = _pair(df)
    meta = {}
    assert classify_pair(pair_metrics(up, lo, len(df), df=df), meta) == "WEDGE_FALLING"
    assert meta.get("why"), "every verdict must record WHY (his audit trail)"


def test_a_single_edge_is_still_a_trendline():
    from analysis.pattern_law import classify_pair, pair_metrics
    df = _frame(160.0, -0.30, 100.0, -0.10)
    up, _ = _pair(df)
    assert classify_pair(pair_metrics(up, None, len(df), df=df), {}) == "TRENDLINE"


# ───────────────────────── the near-break gate ─────────────────────────
def test_gate_drops_past_market_patterns_and_the_env_switch_works(monkeypatch):
    from analysis.pattern_law import gate_patterns
    pats = [{"type": "WEDGE_FALLING", "near_break": True},
            {"type": "TRIANGLE", "near_break": False, "break_state": "STALE",
             "dist_atr": 6.1}]
    kept = gate_patterns(pats, tag="test")
    assert [p["type"] for p in kept] == ["WEDGE_FALLING"]
    monkeypatch.setenv("VIVA_NEAR_BREAK_GATE", "0")
    assert len(gate_patterns(pats)) == 2


def test_every_render_shape_carries_the_law_stamp():
    """«هشدار ابتدایی … الان در زمان تایید یه چیز دیگه میده» — the stamp is the
    fix: the drawn shape carries the law's own slug and verdict, and the law —
    not the old engine ifs — decides the final name."""
    from analysis.render_kit import _law_stamp
    df = _frame(160.0, -0.30, 100.0, -0.10)
    up, lo = _pair(df)
    cmd = _law_stamp({"type": "TRIANGLE", "lines": [up, lo]}, df, up, lo,
                     replace_type=True)
    assert cmd["type"] == "WEDGE_FALLING", "the law renames the legacy label"
    assert cmd["law_bias"] == "BULL" and cmd["break_side"] == "UPPER"
    assert isinstance(cmd["near_break"], bool) and cmd["break_state"]
    assert cmd["law_why"], "the stamp carries the reason with it"


def test_every_drawing_site_in_the_renderer_is_stamped():
    """Two-line shapes, the flat band and the flag/pennant mini-channel all go
    through the SAME stamp (a shape can never slip out un-judged)."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "analysis", "render_kit.py"), encoding="utf-8").read()
    assert '{"type": str(shape), "lines": [gu, gl]},\n                                      df, _ns(gu), _ns(gl), replace_type=True' in src
    assert 'touches_u' not in src or "for _fp67 in _dfp67" in src
    assert "_fp67 = _law_stamp(_fp67, df" in src          # flag/pennant
    assert '"type": "RANGE"' in src and "df, {\"slope\": 0.0, \"intercept\": float(rhi)}" in src


def test_spot_lane_reads_the_same_gate():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "analysis", "spot_engine.py"), encoding="utf-8").read()
    assert "near_break_gate_on" in src
    assert 'pat.get("near_break") is False' in src


def test_alert_time_and_confirmation_time_cannot_diverge():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "analysis", "pattern_engine.py"), encoding="utf-8").read()
    assert 'return pattern, ""' in src, \
        "_structural_refine must be a no-op stub (no second opinion)"


def test_the_gate_never_starves_the_confirmation_watch():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "analysis", "render_kit.py"), encoding="utf-8").read()
    assert "_pats_ungated21" in src and "render_line_watch" in src
    assert "for pp in _pats_ungated21" in src


# ─────────── ONE NAME (the 10-16 audit on his own unique ids) ───────────
def test_the_three_label_sources_collapse_into_one():
    """On his own ids the same chart was announced as CHANNEL_ASCENDING (setup
    engine), drawn as RANGE (renderer pill) and confirmed as a third name.
    After the law, every label key carries the LAW's dominant drawn slug."""
    from analysis.pattern_law import sync_labels
    md = {"pattern_type": "CHANNEL_ASCENDING", "tl_pattern": "RANGE",
          "render_htf_pattern": "RANGE", "viva_pattern": "RANGE",
          "render_patterns": [{"type": "RANGE", "law_slug": "CHANNEL_FLAT",
                               "near_break": True},
                              {"type": "WEDGE_FALLING", "near_break": True}]}
    assert sync_labels(md, md["render_patterns"]) == "WEDGE_FALLING"
    for k in ("pattern_type", "tl_pattern", "render_htf_pattern", "viva_pattern"):
        assert md[k] == "WEDGE_FALLING", f"{k} still disagrees"
    assert md["pattern_label_fa"] == "گوه نزولی"


def test_a_past_market_shape_never_gets_to_name_the_chart():
    from analysis.pattern_law import sync_labels
    md = {"pattern_type": "", "tl_pattern": "",
          "render_patterns": [{"type": "WEDGE_FALLING", "near_break": False,
                               "break_state": "STALE"},
                              {"type": "RANGE", "law_slug": "CHANNEL_FLAT",
                               "near_break": True}]}
    assert sync_labels(md, md["render_patterns"]) == "CHANNEL_FLAT"


def test_the_database_audit_tool_exists_and_reports_drift():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "ops", "diag", "_q21_audit.py")
    assert os.path.isfile(path), "the unique-id drift audit must be re-runnable"
    src = open(path, encoding="utf-8").read()
    assert "pattern_type" in src and "tl_pattern" in src and "DRIFT" in src


# ───────────── per-engine gate (enforced at the publish boundary) ─────────────
def test_setup_gate_blocks_a_cited_pattern_that_is_not_drawn():
    from analysis.pattern_law import setup_gate
    md = {"pattern_type": "WEDGE_FALLING", "render_patterns": [
        {"type": "TRENDLINE"}, {"type": "RANGE", "law_slug": "CHANNEL_FLAT"}]}
    ok, why = setup_gate(md, "TECHCLASSIC")
    assert not ok and why.startswith("CITED-NOT-DRAWN")


def test_setup_gate_blocks_a_past_market_story():
    from analysis.pattern_law import setup_gate
    md = {"pattern_type": "WEDGE_FALLING", "render_patterns": [
        {"type": "WEDGE_FALLING", "near_break": False, "break_state": "STALE",
         "dist_atr": 5.2}]}
    ok, why = setup_gate(md, "TECHCLASSIC")
    assert not ok and why.startswith("PAST-MARKET")


def test_zone_engines_may_trade_without_a_pattern_but_not_on_a_stale_one():
    from analysis.pattern_law import setup_gate
    empty = {"render_patterns": [{"type": "RANGE", "law_slug": "CHANNEL_FLAT",
                                  "near_break": True}]}
    assert setup_gate(empty, "PINVAL")[0] is True       # zone lane: no pattern OK
    assert setup_gate(empty, "ALBROX")[0] is True
    stale = {"render_patterns": [{"type": "CHANNEL_DESCENDING", "near_break": False,
                                  "break_state": "STALE"}]}
    assert setup_gate(stale, "ALBROX")[0] is False


def test_the_gate_is_enforced_when_a_setup_is_published():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "bot", "messages_v7.py"), encoding="utf-8").read()
    i = src.index("def send_setup_update(")
    j = src.index("def ", i + 10)
    assert "setup_gate" in src[i:j], "the publish boundary must run the law"
    assert "NOT published" in src[i:j]


def test_the_engines_themselves_are_not_silenced():
    """The gate lives at the boundary — the detectors must still build and
    measure candidates (silencing them inside the engines killed five
    calibration tests)."""
    for rel in ("analysis/setups_experimental.py", "analysis/setups_v7.py"):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                rel), encoding="utf-8").read()
        assert "setup_gate" not in src, f"{rel} must not run the publish gate"
