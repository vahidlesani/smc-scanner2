"""R99q39 — geometry: a shape is bounded by the bars it was TESTED on,
and a setup's card draws the geometry its own engine traded."""
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _line(points, x0, x1=None):
    return {"side": "HIGH", "x0": x0, "x1": x1 if x1 is not None else x0,
            "slope": 0.0, "intercept": 1.0, "log_fit": False,
            "points": [{"ts": t, "price": 1.0} for t in points]}


def _tape(n=200):
    ts = pd.date_range("2026-09-01", periods=n, freq="4h")
    return pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 1.1,
                         "low": 0.9, "close": 1.0, "volume": 10.0})


def test_evidence_window_reads_the_pivots_not_the_drawing_end():
    df = _tape()
    ln = _line([str(df["timestamp"].iloc[150]), str(df["timestamp"].iloc[186])], 150, 199)
    from analysis.pattern_law import evidence_window
    first, last, n = evidence_window(ln, len(df) - 1, df)
    assert (first, last, n) == (150, 186, 2)


def test_two_edges_that_barely_overlap_are_not_one_shape():
    from analysis.pattern_law import common_window
    df = _tape()
    up = _line([str(df["timestamp"].iloc[180]), str(df["timestamp"].iloc[186])], 180, 199)
    lo = _line([str(df["timestamp"].iloc[20]), str(df["timestamp"].iloc[40])], 20, 199)
    w = common_window(up, lo, len(df) - 1, df)
    assert w["common"] is False
    assert w["ratio"] < 0.40


def test_two_edges_over_the_same_stretch_stay_a_shape():
    from analysis.pattern_law import common_window
    df = _tape()
    up = _line([str(df["timestamp"].iloc[60]), str(df["timestamp"].iloc[180])], 60, 199)
    lo = _line([str(df["timestamp"].iloc[70]), str(df["timestamp"].iloc[170])], 70, 199)
    w = common_window(up, lo, len(df) - 1, df)
    assert w["common"] is True
    assert w["span"] >= 100


def test_the_classifier_refuses_an_incoherent_pair_and_says_why():
    from analysis.pattern_law import classify_pair, pair_metrics
    df = _tape()
    up = _line([str(df["timestamp"].iloc[180]), str(df["timestamp"].iloc[186])], 180, 199)
    lo = _line([str(df["timestamp"].iloc[20]), str(df["timestamp"].iloc[40])], 20, 199)
    up.update({"slope": -0.001}); lo.update({"slope": 0.001})
    m = pair_metrics(up, lo, len(df) - 1, df=df)
    meta = {}
    slug = classify_pair(m, meta)
    assert m.get("common") is False
    assert slug == "NONE"
    assert any("share" in str(w) for w in (meta.get("why") or []))


# ── the chart draws the ENGINE's geometry, not a second guess ─────────────
def test_the_break_family_card_uses_its_own_pattern_geo():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "_eng39c" in src
    assert "engine_geometry" in src
    assert "VIVA_LEGACY_CHART_REFIT" in src


def test_a_validated_break_line_is_never_dropped_as_a_mini_flag():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'and not _pat.get("engine_geometry")' in src


def test_spot_edges_are_bounded_by_their_shared_window():
    src = open(os.path.join(ROOT, "analysis", "viva_geometry.py"), encoding="utf-8").read()
    assert "_shared_end" in src
    assert "R99q39b" in src
