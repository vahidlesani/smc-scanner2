"""V3 §27/§28 (r27): stable pattern_id, lifecycle registry with explicit
expiration reasons (never silent deletes), and exact-duplicate event
dedupe — same event_id only; everything else is distinct evidence."""
import numpy as np
import pandas as pd


def _mod():
    from analysis import pattern_engine
    return pattern_engine


def _wedge_frames(n=140):
    """Same geometry as test_pattern_engine._wedge_frames: descending
    triangle (falling upper + near-flat lower) with a closing upper break in
    the trigger frame → warn-only STATE_VIOLATED on the upper edge."""
    U = lambda i: 100.0 - 0.10 * i
    L = lambda i: 60.0 - 0.01 * i
    wick = 0.6
    keys = [(0, 88.0), (15, L(15) + wick), (50, U(50) - wick), (75, L(75) + wick),
            (95, U(95) - wick), (112, L(112) + wick), (125, U(125) - wick),
            (137, L(137) + wick), (139, (U(139) + L(139)) / 2)]
    vals = np.zeros(n)
    for (i0, v0), (i1, v1) in zip(keys, keys[1:]):
        seg = np.linspace(v0, v1, i1 - i0 + 1)
        vals[i0:i1 + 1] = seg[:i1 - i0 + 1]
    high = vals + wick
    low = vals - wick
    ts = pd.date_range("2026-01-01", periods=n, freq="4h")
    pattern = pd.DataFrame({"timestamp": ts, "open": vals - 0.01, "high": high,
                            "low": low, "close": vals + 0.01,
                            "volume": np.full(n, 100.0)})
    atr_ref = float(np.mean((high - low)[-14:]))
    trig_n = 40
    ref = U(n - 1)
    t_mid = np.full(trig_n, ref - 1.0 * max(atr_ref, 1e-9))
    t_open = t_mid.copy(); t_close = t_mid.copy()
    t_high = t_mid + 0.3 * atr_ref; t_low = t_mid - 0.3 * atr_ref
    t_open[-1] = ref - 0.2 * atr_ref
    t_close[-1] = ref + 1.1 * atr_ref
    t_high[-1] = t_close[-1] + 0.05 * atr_ref
    t_low[-1] = t_open[-1] - 0.05 * atr_ref
    trigger = pd.DataFrame({"timestamp": pd.date_range("2026-08-01", periods=trig_n,
                                                       freq="15min"),
                            "open": t_open, "high": t_high, "low": t_low,
                            "close": t_close, "volume": np.full(trig_n, 100.0)})
    return pattern, trigger


def test_pattern_id_stable_across_rescans_and_on_every_event():
    m = _mod(); m.lifecycle_reset()
    pattern, trigger = _wedge_frames()
    e1 = m.scan_edges(pattern, trigger, "4h")
    assert e1, "fixture must emit events"
    pids1 = {e["pattern_id"] for e in e1}
    assert len(pids1) == 1, "all events of one scan share the pattern identity"
    e2 = m.scan_edges(pattern, trigger, "4h")
    assert {e["pattern_id"] for e in e2} == pids1, "same geometry → same id"
    pid = pids1.pop()
    assert pid.startswith("wedge") or pid.startswith("triangle") or pid.startswith("channel")
    rec = m.lifecycle_get(pid)
    assert rec and rec["state"] in ("EDGE_NEAR", "BREAK_READY", "BREAK_CLOSED",
                                    "RETEST", "ACTIVE", "INVALIDATED")
    assert rec["meta"]["pattern_tf"] == "4h"


def test_pattern_id_is_deterministic_geometry_hash():
    m = _mod(); m.lifecycle_reset()
    from analysis.pattern_engine import fit_edge_line, pattern_id_for
    from analysis.viva_tlbreak import load_config
    pattern, _ = _wedge_frames()
    cfg = load_config(); n = len(pattern) - 1
    u = fit_edge_line(pattern, "HIGH", cfg, n)
    lo = fit_edge_line(pattern, "LOW", cfg, n)
    a = pattern_id_for("WEDGE_FALLING", "4h", u, lo, n)
    b = pattern_id_for("WEDGE_FALLING", "4h", u, lo, n)
    assert a == b and len(a) < 40
    assert pattern_id_for("WEDGE_FALLING", "4h", u, lo, n + 1) != a, \
        "different span = different pattern (structural replacement)"


def test_dedupe_drops_exact_duplicates_only():
    m = _mod()
    base = {"event_id": "upper|WEDGE_FALLING|EDGE_NEAR|t1", "side": "upper"}
    other_edge = {"event_id": "lower|WEDGE_FALLING|EDGE_NEAR|t1", "side": "lower"}
    later_state = {"event_id": "upper|WEDGE_FALLING|BREAK_CLOSED|t2", "side": "upper"}
    no_id = {"side": "upper"}
    out = m.dedupe_events([base, dict(base), other_edge, later_state, no_id])
    assert len(out) == 4, "exact dup dropped; edges/states/no-id all kept"
    assert m.dedupe_events([]) == [] and m.dedupe_events(None) == []


def test_violation_marks_invalidated_with_reason_and_persists():
    m = _mod(); m.lifecycle_reset()
    pattern, trigger = _wedge_frames()
    events = m.scan_edges(pattern, trigger, "4h")
    violated = [e for e in events if e.get("warn_only")]
    assert violated, "fixture upper break must warn-only violate"
    v = violated[0]
    assert v["lifecycle"] == "INVALIDATED" and v["pattern_id"]
    rec = m.lifecycle_get(v["pattern_id"])
    assert rec, "§28: terminal records are never deleted silently"
    assert rec["state"] == "INVALIDATED"
    assert rec.get("reason") == "opposite_side_break_close"


def test_expiration_emits_reason_record_survives():
    m = _mod(); m.lifecycle_reset()
    # excessive age
    m.lifecycle_observe("p-age", "EDGE_NEAR", meta={"span": 500})
    m._lifecycle_scan_tick()
    rec = m.lifecycle_get("p-age")
    assert rec["state"] == "EXPIRED" and rec["reason"] == "excessive_age"
    assert m.lifecycle_get("p-age") is not None, "never deleted"
    # no recent touch: quiet for more than the sweep window
    r = m.lifecycle_observe("p-quiet", "EDGE_NEAR", meta={"span": 10})
    m._LIFECYCLE["p-quiet"]["last_scan"] = r["last_scan"] - 61
    m._lifecycle_scan_tick()
    rec = m.lifecycle_get("p-quiet")
    assert rec["state"] == "EXPIRED" and rec["reason"] == "no_recent_touch"
