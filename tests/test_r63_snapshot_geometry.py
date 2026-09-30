"""R63: per-code snapshot lock + one geometry (chart == trade)."""
from types import SimpleNamespace

from analysis.snapshot_lock import (lock_render_geometry, snapshot_key,
                                    unify_trade_geometry)


def _kv():
    store = {}
    return store, (lambda k, d=None: store.get(k, d)), (lambda k, v: store.__setitem__(k, v))


def _cand(sid, pats, zones, **extra):
    md = {"render_patterns": pats, "render_zones": zones}
    md.update(extra)
    return SimpleNamespace(signal_id=sid, metadata=md)


def test_first_chart_stamps_later_scans_cannot_extend_or_add_zones():
    store, g, s = _kv()
    line_a = {"type": "WEDGE_RISING", "lines": [{"side": "HIGH", "points": [{"ts": "2026-10-01 00:00", "price": 1}]}]}
    c = _cand("SIG1", [line_a], [{"kind": "OB", "bottom": 1, "top": 2}])
    assert lock_render_geometry(c, g, s) == "STAMPED"
    assert snapshot_key("SIG1") in store
    # a later scan re-fitted onto NEW pivots and found a NEW zone
    c.metadata["render_patterns"] = [{"type": "WEDGE_RISING", "lines": [{"side": "HIGH", "points": [{"ts": "2026-10-01 09:00", "price": 3}]}]}]
    c.metadata["render_zones"] = [{"kind": "OB", "bottom": 1, "top": 2}, {"kind": "FVG", "bottom": 5, "top": 6}]
    assert lock_render_geometry(c, g, s) == "RESTORED"
    assert c.metadata["render_patterns"] == [line_a]
    assert len(c.metadata["render_zones"]) == 1
    assert c.metadata["snapshot_locked"] is True


def test_lock_is_per_unique_code_only():
    store, g, s = _kv()
    a = _cand("A", [{"type": "RANGE", "lo": 1, "hi": 2}], [])
    lock_render_geometry(a, g, s)
    b = _cand("B", [{"type": "CHANNEL_UP", "lines": []}], [{"kind": "FVG"}])
    assert lock_render_geometry(b, g, s) == "STAMPED"
    assert b.metadata["render_patterns"][0]["type"] == "CHANNEL_UP"


def test_trade_lines_replace_render_fitter_lines_G1():
    md = {"strategy_variant": "VIVA_TLBREAK",
          "viva_upper_points": [{"timestamp": "t1", "price": 2}, {"timestamp": "t2", "price": 1.9}],
          "render_patterns": [{"type": "WEDGE_FALLING", "lines": [{}]},
                              {"type": "RANGE", "lo": 1, "hi": 2},
                              {"type": "DOUBLE_TOP", "trade_geometry": True, "lines": [{}]}]}
    assert unify_trade_geometry(md) is True
    kinds = [p["type"] for p in md["render_patterns"]]
    assert kinds == ["RANGE", "DOUBLE_TOP"]
    assert md["render_geometry_source"] == "TRADE"


def test_no_trade_lines_keeps_render_patterns():
    md = {"strategy_variant": "PINVAL", "render_patterns": [{"type": "WEDGE_FALLING", "lines": [{}]}]}
    assert unify_trade_geometry(md) is False
    assert len(md["render_patterns"]) == 1


def test_absorb_keep_set_freezes_render_keys():
    src = open("database/candidate_store.py", encoding="utf-8").read()
    assert "SNAPSHOT_KEYS as _snap63" in src


def test_locked_patterns_never_refit_per_tf():
    import pandas as pd
    from bot.messages_v7 import _native_patterns_for_frame
    idx = pd.date_range("2026-10-01", periods=60, freq="15min")
    frame = pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0}, index=idx)
    stored = [{"type": "WEDGE_RISING", "lines": [{"side": "HIGH", "slope": 0.0, "intercept": 1.0,
                                                  "points": [{"ts": "2026-09-20 00:00", "price": 1.0}]}]}]
    out = _native_patterns_for_frame(frame, "LONG", "15m", "LOCKED1", stored, locked=True)
    assert out is stored
