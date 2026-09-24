"""Round-26 — V3 spec phase 1+2 acceptance (his integration spec §45-A/D, §52).

Locked definitions of FIXED:
 1. A channel is never mislabeled as a wedge from endpoint noise — contraction
    must be PROGRESSIVE (mid-span width below start width).
 2. A wedge/converging pair is not swallowed by the channel branch.
 3. Flat-top / flat-bottom shapes classify as TRIANGLES before the channel
    branch, even when convergence has not materialized yet.
 4. Channel needs both edges to agree; opposing drifts that never converged
    are an honest TRIANGLE.
 5. Approach direction (§6) and pattern role (§7) ride every edge event and
    the candidate metadata as EVIDENCE (never gates), with a stable event_id.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.pattern_engine import classify_shape, scan_edges

TS = pd.date_range(end="2026-09-24 12:00", periods=150, freq="15min", tz="UTC")


class _L:
    """Minimal line double for classify_shape (price_at / slope / first_index)."""

    def __init__(self, slope, intercept, first_index=0):
        self.slope, self.intercept, self.first_index = slope, intercept, first_index

    def price_at(self, x):
        return self.slope * float(x) + self.intercept


def test_parallel_channel_stays_channel_under_endpoint_noise():
    """§52-1: a true parallel channel must not flip to a wedge — even when a
    noisy endpoint makes width_now dip below 0.85·width_then."""
    # both edges rise 0.05/bar, width constant 10 → parallel channel
    upper, lower = _L(0.05, 110.0), _L(0.05, 100.0)
    labels = set()
    for bias in (0.0, -0.4, 0.4):     # endpoint noise on the lower edge
        lo = _L(0.05, 100.0 + bias)
        labels.add(classify_shape(upper, lo, 140))
    assert labels == {"CHANNEL_ASCENDING"}, labels


def test_noise_parallel_process_never_flips_channel_to_wedge():
    """The live repro of «یک نماد دوچارت، دو لیبل»: a truly PARALLEL channel
    re-detected under 6 noise seeds must never label WEDGE — fitted-line noise
    cannot manufacture convergence (Δdrift ≤ 15% of dominant = parallel)."""
    from analysis.render_kit import detect_patterns
    n = 150
    xi = np.arange(n, dtype=float)
    up = 0.26 - 0.00035 * xi
    lo = 0.235 - 0.00035 * xi                     # constant width 0.025
    for seed in range(6):
        r = np.random.default_rng(seed)
        m2 = (up + lo) / 2 + r.normal(0, 0.0012, n)
        m2 = np.clip(m2, lo + 0.0008, up - 0.0008)
        df = pd.DataFrame({
            "timestamp": pd.date_range(end="2026-09-24 12:00", periods=n, freq="1h", tz="UTC"),
            "open": m2 * 0.999, "high": m2 * 1.004, "low": m2 * 0.996,
            "close": m2, "volume": np.full(n, 1e6)})
        pats = detect_patterns(df.tail(170).reset_index(drop=True), "SHORT")
        kinds = [p["type"] for p in pats]
        assert not any("WEDGE" in k for k in kinds), (seed, kinds)


def test_progressive_convergence_is_a_wedge_not_channel():
    """§52-2: same-sign falling edges that genuinely converge → WEDGE_FALLING."""
    upper, lower = _L(-0.09, 100.0), _L(-0.03, 90.0)   # width 10 → 10-0.06*140≈1.6
    assert classify_shape(upper, lower, 140) == "WEDGE_FALLING"
    upper, lower = _L(0.03, 90.0), _L(0.09, 80.0)      # rising converging pair
    assert classify_shape(upper, lower, 140) == "WEDGE_RISING"


def test_flat_top_slow_descend_is_never_a_channel():
    """Spec §29: if only ONE line has meaningful slope, do not call it a
    channel — a flat top with a falling bottom is a one-slope shape."""
    upper, lower = _L(0.0, 110.0), _L(-0.06, 100.0)    # widening: top flat
    assert classify_shape(upper, lower, 140) == "TRIANGLE"
    upper, lower = _L(0.0, 110.0), _L(-0.01, 100.0)    # gentle variant
    assert classify_shape(upper, lower, 140) == "TRIANGLE"


def test_opposing_drifts_never_converged_is_triangle():
    """§52-4: channel needs parallelism — one edge rising, one falling with a
    gentle opposing drift = an honest TRIANGLE, never a one-sided channel."""
    upper, lower = _L(0.005, 108.0), _L(-0.005, 98.0)  # width 10 → 11.4, no fan
    assert classify_shape(upper, lower, 140) == "TRIANGLE"


def test_edge_events_carry_approach_role_and_event_id():
    """§6/§7/§27: every edge event is independent, evidence-labelled and
    stably identifiable; the metadata contract reaches _build_candidate."""
    rng = np.random.default_rng(17)
    n = 150
    # price FALLS into a falling wedge (approach = FROM_ABOVE)
    low_touches = [(50, 0.205), (80, 0.198), (110, 0.191), (140, 0.1845)]
    high_touches = [(40, 0.226), (75, 0.212), (110, 0.200), (140, 0.1915)]
    anchors = sorted(low_touches + high_touches)
    xs = np.array([a[0] for a in anchors], float)
    ys = np.array([a[1] for a in anchors], float)
    # pre-pattern path: slide DOWN from 0.26 into the pattern start
    pre = np.linspace(0.26, 0.215, 30)
    mid = np.interp(np.arange(n, dtype=float), xs, ys)
    mid[:30] = pre
    mid[141:] = np.linspace(0.1910, 0.1868, 9)   # close between the two edges
    mid += rng.normal(0, 0.0002, n)
    df = pd.DataFrame({
        "timestamp": TS, "open": mid * 0.999,
        "high": mid * (1 + 0.008), "low": mid * (1 - 0.008),
        "close": mid, "volume": np.full(n, 1e6)})
    events = scan_edges(df, df.tail(6).reset_index(drop=True), "15m")
    assert events, "expected edge observations"
    for ev in events:
        assert ev.get("event_id"), ev
        assert ev.get("legality") in ("LEGAL", "WARNING_ONLY")
        assert ev.get("approach_direction") in (
            "FROM_ABOVE", "FROM_BELOW", "INSIDE", "UNKNOWN")
        assert ev.get("pattern_role") in (
            "REVERSAL", "CONTINUATION", "CONSOLIDATION", "BREAKOUT", "UNKNOWN")
    assert events[0]["approach_direction"] == "FROM_ABOVE", events[0]
    wedges = [e for e in events if "WEDGE" in str(e.get("pattern"))]
    assert wedges and all(e["pattern_role"] == "REVERSAL" for e in wedges)
    # §8/§27: events stay independent (no single-event collapse); the far
    # edge stays SILENT by the no-noise law (distance gate) — that is honest.
    ids = {e["event_id"] for e in events}
    assert len(ids) == len(events)
