"""R99q29 — geometry must be judged in RELATIVE (price-normalised) space.

Three real defects are pinned here, each one seen in production charts:

1. `pair_metrics` measured band convergence as `width_now / width_then` on
   ABSOLUTE price. On a falling chart every band shrinks in absolute terms
   even when the two edges are exactly parallel, so a 160-bar parallel
   channel measured conv=0.51 and `classify_pair` filed it as TRIANGLE.
2. `pair_metrics` read the measurement start with `getattr(ln, "first_index")`,
   which is always empty for the render dicts (they store `x0`), so every
   dict-fed pair was measured from bar 0 — a window the pattern never covered.
3. `pattern_naming` returned an empty `why` when the law refused a pair.

The naming layer is additive: it may describe a candidate, never kill it.
"""
import numpy as np
import pandas as pd
import pytest

from analysis.pattern_law import classify_pair, pair_metrics
from analysis.pattern_naming import _pts_to_line, name_candidate


def _channel(n=170, slope=-0.0042, top=2.0, gap=0.14, seed=11):
    """A chart built to sit inside a channel, so both edges carry real taps."""
    x = np.arange(n, dtype=float)
    up = top * np.exp(slope * x)
    lo = (top - gap) * np.exp(slope * x)
    mid = (up + lo) / 2.0
    rng = np.random.default_rng(seed)
    close = mid * (1 + rng.normal(0, 0.004 * 4, n))
    open_ = mid * (1 + rng.normal(0, 0.004 * 4, n))
    high = np.maximum(open_, close) * (1 + abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - abs(rng.normal(0, 0.004, n)))
    ts = pd.date_range("2026-03-01", periods=n, freq="4h")
    df = pd.DataFrame({"timestamp": ts, "open": open_, "high": high,
                       "low": low, "close": close,
                       "volume": np.full(n, 5e5)})
    return df, up, lo


UP_IDX = [10, 40, 70, 100, 130]
LO_IDX = [15, 45, 78, 108, 135, 150]


def _lines():
    df, up, lo = _channel()
    ts = df["timestamp"]
    pts_u = [{"ts": str(ts[i]), "price": float(up[i])} for i in UP_IDX]
    pts_l = [{"ts": str(ts[i]), "price": float(lo[i])} for i in LO_IDX]
    return df, _pts_to_line(pts_u, df), _pts_to_line(pts_l, df)


def test_parallel_edges_on_a_falling_chart_are_a_channel_not_a_triangle():
    df, upper, lower = _lines()
    assert upper is not None and lower is not None
    m = pair_metrics(upper, lower, len(df) - 1, df=df)
    assert m["ok"] is True
    # the absolute ratio still contracts (that is the bug's fingerprint) ...
    assert m["conv_ratio"] < 0.9
    # ... but relative to price the band is steady
    assert 0.85 <= float(m["conv_rel"]) <= 1.15
    meta = {}
    assert classify_pair(m, meta) == "CHANNEL_DESCENDING"


def test_measurement_starts_where_the_edges_start_not_at_bar_zero():
    df, upper, lower = _lines()
    m = pair_metrics(upper, lower, len(df) - 1, df=df)
    # both edges are render dicts -> start comes from x0
    assert m["start"] == max(UP_IDX[0], LO_IDX[0])
    assert m["span"] == (len(df) - 1) - m["start"]


def test_naming_layer_writes_type_grade_and_taps():
    df, _upper, _lower = _lines()
    ts = df["timestamp"]
    _, up_curve, lo_curve = _channel()
    md = {
        "viva_upper_points": [{"ts": str(ts[i]), "price": float(up_curve[i])}
                              for i in UP_IDX],
        "viva_lower_points": [{"ts": str(ts[i]), "price": float(lo_curve[i])}
                              for i in LO_IDX],
    }
    cand = _mk_candidate(md)
    res = name_candidate(cand, df)
    assert res["written"] is True, res
    assert cand.metadata["pattern_type"] == "CHANNEL_DESCENDING"
    assert cand.metadata["pattern_label_fa"] == "کانال نزولی"
    assert cand.metadata["pattern_grade"] in ("A", "B")
    assert cand.metadata["pattern_taps"]["upper"] >= 4
    assert "render_patterns" in cand.metadata


def test_naming_never_vetoes_and_always_explains_itself():
    df = _channel()[0]
    cand = _mk_candidate({})            # no geometry at all
    res = name_candidate(cand, df)
    assert res["written"] is False
    assert res["reason"]              # never an empty explanation
    # the caller's candidate is untouched beyond metadata
    assert cand.status == "EDUCATIONAL"


def _mk_candidate(md):
    from analysis.models import SignalCandidate
    return SignalCandidate(
        signal_id="r99q29", symbol="XUSDT", style="perp", setup_code="TLBREAK",
        setup_name="TL", strategy_fa="", direction="SHORT", score=8,
        status="EDUCATIONAL", entry_zone_bottom=1.0, entry_zone_top=1.01,
        planned_entry=1.0, sl=1.05, tp1=0.9, tp2=0.85, rr_tp1=2, rr_tp2=3,
        bias="bear", trigger_timeframe="4h", metadata=md)


# ── honest box end (BADREF_geo_8H-skybox) ──────────────────────────────────
def test_clamp_box_end_pulls_a_sky_box_back_to_structure():
    from analysis.geometry_v2 import clamp_box_end
    close, ceiling = 100.0, 104.0
    # +65.8% measured move must NOT survive a 4% ceiling
    final, src = clamp_box_end(close * 1.658, ceiling, "LONG")
    assert src == "CEILING"
    assert final < close * 1.06
    # a target that already ends before the ceiling is left alone
    same, src2 = clamp_box_end(102.0, ceiling, "LONG")
    assert (same, src2) == (102.0, "SAME")
    # no structure found -> the measured move stands
    keep, src3 = clamp_box_end(close * 1.658, None, "LONG")
    assert src3 == "MEASURED" and abs(keep - close * 1.658) < 1e-9


def test_structural_ceiling_ignores_the_ancient_regime():
    from analysis.geometry_v2 import structural_ceiling
    n = 260
    close = np.full(n, 100.0)
    high = close + 0.5
    high[8] = 165.8                    # the ancient sky high, far outside lookback
    high[250] = 104.0                  # the honest same-TF level
    high[251] = 103.0
    df = pd.DataFrame({"close": close, "high": high, "low": close - 0.5})
    got = structural_ceiling(df, float(close[-1]), lookback=120, min_gap=0.012)
    assert got is not None and abs(got - 104.0) < 1e-9


def test_chart_clamps_the_projection_before_it_is_drawn():
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "bot", "messages_v7.py"), encoding="utf-8").read()
    region = src.split("def generate_chart(")[1]
    assert "HONEST BOX END" in region
    assert "clamp_box_end" in region
    # the clamp must run BEFORE the projection is painted
    assert region.index("clamp_box_end") < region.index("MEASURED TARGET")


def test_grade_and_taps_reach_the_chart_notes():
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'pattern_grade' in src and 'pattern_taps' in src
