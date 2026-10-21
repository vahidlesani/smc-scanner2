"""10-10 regression: the Live Price Alignment Law inside detect_technoclassic
used out-of-scope names (upper/lower/n) and raised NameError on EVERY
non-empty detection since Oct 6 — killing the TC lane and the ALBROX
pattern lane with it. Per-event edges now; these tests pin the law."""

import importlib
from types import SimpleNamespace as _NS


def _env(monkeypatch):
    monkeypatch.setenv("TECHCLASSIC_ENABLED", "true")
    import config
    config._cached = None
    importlib.reload(config)
    import analysis.pattern_engine as pe
    importlib.reload(pe)
    import analysis.setups_experimental as exp
    importlib.reload(exp)
    return pe


def _bundle(pe, live_price):
    from test_pattern_engine import _wedge_frames, _Bundle
    pattern, trigger = _wedge_frames()
    b = _Bundle({"4h": pattern, "1h": pattern, "15m": trigger})
    if live_price is not None:
        b.ticker["last_price"] = live_price
    return b


def _ev(pe, direction, line_price=100.0, tag="A"):
    d = {"state": pe.STATE_BREAK, "pattern": "P", "side": "lower",
         "direction": direction, "live": 100.0, "touches": 3,
         "fit_error_atr": 0.3, "structure_score": 8,
         "reactions": {"reject_rate": 0.5},
         "edge_points": [{"timestamp": f"2026-09-01 04:00-{tag}", "price": 101.0},
                         {"timestamp": f"2026-09-10 08:00-{tag}", "price": 99.0}],
         "pattern_tf": "4h"}
    if line_price is not None:
        d["line_price"] = line_price
    return d


def _run(pe, monkeypatch, bundle, ev):
    import analysis.setups_v7 as _sv7
    from database.bot_kv import set_json as _sj
    monkeypatch.setattr(_sv7, "_ensure_frames", lambda b, tfs: True)
    monkeypatch.setattr(pe, "scan_edges", lambda *a, **k: [dict(ev)])
    monkeypatch.setattr(pe, "_brooks_edge_ok", lambda *a, **k: True)
    monkeypatch.setattr(pe, "pivot_pattern_events", lambda *a, **k: [])
    state = {"n": 0}
    def fake_build(*a, **k):
        state["n"] += 1
        return _NS(signal_id=f"FAKE-{state['n']}")
    monkeypatch.setattr(pe, "_build_candidate", fake_build)
    _sj(pe._mint_guard_key(bundle, ev), {})  # hermetic
    return pe.detect_technoclassic(bundle, "DAYTRADE"), state["n"]


def test_long_kept_when_live_above_edge(monkeypatch):
    pe = _env(monkeypatch)
    cand, n = _run(pe, monkeypatch, _bundle(pe, 100.5), _ev(pe, "LONG", tag="L1"))
    assert n == 1 and getattr(cand, "signal_id", "") == "FAKE-1"


def test_long_dropped_when_live_below_edge(monkeypatch):
    pe = _env(monkeypatch)
    cand, n = _run(pe, monkeypatch, _bundle(pe, 99.5), _ev(pe, "LONG", tag="L2"))
    assert cand is None and n == 0


def test_short_kept_when_live_below_edge(monkeypatch):
    pe = _env(monkeypatch)
    cand, n = _run(pe, monkeypatch, _bundle(pe, 99.5), _ev(pe, "SHORT", tag="S1"))
    assert n == 1 and getattr(cand, "signal_id", "") == "FAKE-1"


def test_short_dropped_when_live_above_edge(monkeypatch):
    pe = _env(monkeypatch)
    cand, n = _run(pe, monkeypatch, _bundle(pe, 100.5), _ev(pe, "SHORT", tag="S2"))
    assert cand is None and n == 0


def test_equality_with_edge_passes(monkeypatch):
    pe = _env(monkeypatch)
    cand, n = _run(pe, monkeypatch, _bundle(pe, 100.0), _ev(pe, "LONG", tag="E1"))
    assert n == 1


def test_missing_ticker_fails_open(monkeypatch):
    pe = _env(monkeypatch)
    cand, n = _run(pe, monkeypatch, _bundle(pe, None), _ev(pe, "LONG", tag="F1"))
    assert n == 1  # live unknown → no filtering, never a crash


def test_event_without_edge_fails_open(monkeypatch):
    pe = _env(monkeypatch)
    cand, n = _run(pe, monkeypatch, _bundle(pe, 90.0), _ev(pe, "LONG", line_price=None, tag="F2"))
    assert n == 1  # no edge on the event → kept, never a crash
