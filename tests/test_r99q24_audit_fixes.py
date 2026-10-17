"""R99q24 — the audit-driven fixes (Claude Sonnet 5.5 package, verified items).

His 10-17: «همه اونهایی که فکر میکنی درسته و نیاز ما هستن تست رگرسیون بکن تا
چیزی از قبل خراب نشه» — so every behavioural change below is pinned here:

  A. the publish gate's ONLY veto is PAST-MARKET  (the drying fix)
  B. RANGE is a canonical alias of RECTANGLE       (the audit's PAT-001)
  C. a shape carries a STABLE id and an engine can name the exact one it
     traded (REF-001), so a multi-pattern chart can never relabel the alert
  D. the retired pivot family cannot come back through the TECHCLASSIC lane
     (PAT-002/SET-003)
  E. both TLBREAK paths and the SPOT alerts carry the law stamp (REF-002/003)
  F. a weekly licence wallet must LAST the week — the pace rule (the measured
     cause of «هشدارها خشک شد»: PINVAL 200/200 at 17:48, ALBROX 200/200 at 16:05)
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analysis.pattern_law import (   # noqa: E402
    PATTERN_LAW, RETIRED_PATTERNS, engine_stamp, pattern_pid, select_shape,
    setup_gate)


# ── A. the gate ──────────────────────────────────────────────────────────
def test_only_past_market_vetoes_a_candidate():
    stale = {"pattern_type": "WEDGE_FALLING", "render_patterns": [
        {"type": "WEDGE_FALLING", "law_slug": "WEDGE_FALLING",
         "near_break": False, "break_state": "STALE", "dist_atr": 6.0}]}
    assert setup_gate(stale, "TECHCLASSIC")[0] is False

    naming = {"pattern_type": "FLAG_BULL", "render_patterns": [
        {"type": "RANGE", "law_slug": "CHANNEL_FLAT", "near_break": True,
         "break_state": "INSIDE"}]}
    ok, why = setup_gate(naming, "TECHCLASSIC")
    assert ok is True, "a naming disagreement is not a reason to silence a setup"

    empty = {"render_patterns": []}
    assert setup_gate(empty, "TECHCLASSIC")[0] is True
    assert setup_gate(empty, "TLBREAK")[0] is True


def test_the_gate_still_blocks_a_zone_engine_standing_on_a_stale_shape():
    md = {"render_patterns": [{"type": "CHANNEL_DESCENDING", "near_break": False,
                               "break_state": "STALE", "dist_atr": 5.0}]}
    assert setup_gate(md, "ALBROX")[0] is False
    assert setup_gate(md, "PINVAL")[0] is False


# ── B. RANGE ─────────────────────────────────────────────────────────────
def test_range_has_a_canonical_reference():
    d = PATTERN_LAW["RANGE"]
    assert d["canonical_slug"] == "RECTANGLE"
    assert d["ref"] and "Rectangles" in d["ref"]
    assert PATTERN_LAW["RECTANGLE"]["ref"] == d["ref"]


# ── C. lineage ───────────────────────────────────────────────────────────
def _shape(slug, slope, icpt, nb=True):
    return {"type": slug, "law_slug": slug, "near_break": nb,
            "lines": [{"slope": slope, "intercept": icpt, "x0": 0, "x1": 119,
                       "side": "HIGH"},
                      {"slope": slope / 2, "intercept": icpt - 20, "x0": 0,
                       "x1": 119, "side": "LOW"}]}


def test_a_shape_has_a_stable_id_across_re_renders():
    a = _shape("WEDGE_FALLING", -0.30, 130.0)
    b = dict(a)
    assert pattern_pid(a) == pattern_pid(b)
    c = _shape("WEDGE_FALLING", -0.42, 130.0)
    assert pattern_pid(a) != pattern_pid(c)
    assert pattern_pid(a).startswith("x|WEDGE_FALLING|")


def test_the_engine_names_the_exact_shape_it_traded():
    first = _shape("TRIANGLE_SYMMETRICAL", -0.10, 120.0)
    second = _shape("WEDGE_FALLING", -0.40, 150.0)
    first["pid"] = pattern_pid(first)
    second["pid"] = pattern_pid(second)
    md = {"render_patterns": [first, second],
          "pattern_type": "WEDGE_FALLING",
          "selected_pattern_pid": second["pid"]}
    chosen = select_shape(md)
    assert chosen is second and md["pattern_selection"] == "lineage"
    info = engine_stamp(md, None, "TECHCLASSIC")
    assert info["law_slug"] == "WEDGE_FALLING"
    assert md["selected_pattern_pid"] == second["pid"]

    # without the lineage the CITED slug still wins over «first on the chart»
    md2 = {"render_patterns": [first, second], "pattern_type": "WEDGE_FALLING"}
    assert select_shape(md2) is second
    assert md2["pattern_selection"].startswith("cited:")


# ── D. retired pivots ────────────────────────────────────────────────────
def test_the_retired_pivot_family_cannot_return_through_technoclassic():
    src = open(os.path.join(ROOT, "analysis", "pattern_engine.py"),
               encoding="utf-8").read()
    assert "RETIRED_PATTERNS" in src, \
        "the pivot lane must be filtered through the ONE registry"
    from analysis.patterns16 import detect_pivot_patterns
    n = 120
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-09-01", periods=n, freq="1h"),
        "open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
        "close": [100.0] * n, "volume": [1.0] * n})
    assert detect_pivot_patterns(df, 1.0) == []
    assert not ({s for s in RETIRED_PATTERNS} & {"WEDGE_FALLING", "TRIANGLE"})


# ── E. the stamp reaches every lane ──────────────────────────────────────
def test_tlbreak_main_path_and_spot_alerts_carry_the_law():
    exp = open(os.path.join(ROOT, "analysis", "setups_experimental.py"),
               encoding="utf-8").read()
    i = exp.index("def detect_viva_tlbreak(")
    j = exp.index("_PARENT_TF_1009", i)
    main_path = exp[i:j]
    assert main_path.count("engine_stamp") >= 2, \
        "BOTH the WATCH branch and the validated-break return must stamp"
    assert "_es24(candidate.metadata, trigger_df, \"TLBREAK\")" in main_path

    spot = open(os.path.join(ROOT, "analysis", "spot_engine.py"),
                encoding="utf-8").read()
    assert "engine_stamp" in spot
    assert "pattern_ref" in spot and "law_state" in spot


# ── F. the pace rule ─────────────────────────────────────────────────────
def test_a_weekly_wallet_must_last_the_week(monkeypatch):
    from analysis import tiered_scan as ts
    from datetime import datetime, timezone

    # Saturday of an ISO week: 2 days left (today + Sunday)
    sat = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    assert ts.days_left_in_week(sat) == 2
    assert ts.days_left_in_week(datetime(2026, 10, 12, tzinfo=timezone.utc)) == 7

    used, cap, today = {"u": 100}, {"c": 200}, {"d": 0}
    monkeypatch.setattr(ts, "weekly_count", lambda *a, **k: used["u"])
    monkeypatch.setattr(ts, "weekly_licence_cap", lambda *a, **k: cap["c"])
    monkeypatch.setattr(ts, "daily_setup_count", lambda *a, **k: today["d"])
    monkeypatch.delenv("VIVA_WEEKLY_PACE", raising=False)

    # 100 left over 2 days → pace 50/day
    assert ts.weekly_pace_ok("PINVAL", now=sat) is True
    today["d"] = 50
    assert ts.weekly_pace_ok("PINVAL", now=sat) is False   # burst stopped
    today["d"] = 10
    used["u"] = cap["c"]
    assert ts.weekly_pace_ok("PINVAL", now=sat) is False   # wallet empty
    # the switch really switches it off
    monkeypatch.setenv("VIVA_WEEKLY_PACE", "0")
    assert ts.weekly_pace_ok("PINVAL", now=sat) is True


def test_the_pace_rule_is_wired_into_both_lanes():
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert src.count("weekly_pace_ok(") >= 2          # futures + spot
    assert src.count("daily_setup_incr(") >= 2
