"""R76 (Viva 10-13) — the instant-confirm law, locked.

His report, verbatim: «مدتی است که قیمت به تیپی۳ رسیده تازه تایید پوزیشن در
کانال میاد .. پیام رو نگاه میکنی کمتر از ۳ ثانیه دیلی داشته قیمتها رو متوجه
اشتباه مهلکی میشی». The audit found three latencies; these tests lock the
fixes:

1. TOHOM decisive-break fast path: ONE sub-close ≥0.5·ATR beyond the shared
   edge with volume ≥1.5× confirms NOW (need=3 used to wait price to TP3).
2. A weak single sub-close still waits (the law is instant, not careless).
3. confirm_edge_at rebuilds the SLOPED edge from the chart's own primary
   line when no geometry/tl anchor exists — a frozen alert-time level on a
   falling resistance confirmed only near TP3.
4. The realtime exit lane's cost gate returns the -1 idle sentinel so the
   loop's 5s cadence (and its DB count query) idles at 30s with zero
   positions — consumption without alert latency.
"""
import os
import sys
import types

import pandas as pd

# sandbox lacks mplfinance (production has it); messages_v7 imports it only
# for legacy render helpers these tests never call.
for _m in ("mplfinance",):
    try:
        __import__(_m)
    except Exception:
        sys.modules[_m] = types.ModuleType(_m)

import pytest

from analysis.models import SignalCandidate  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_kv():
    """Session-safe kv stub: applied per test, RESTORED after (a module-level
    stub at collection time broke test_durable_state's sqlite roundtrip)."""
    import database.bot_kv as kv
    orig = (kv.get_json, kv.set_json)
    store = {}
    kv.get_json = lambda k, d=None: store.get(k, d)
    kv.set_json = lambda k, v: (store.pop(k, None) if v is None
                                else store.__setitem__(k, v))
    yield
    kv.get_json, kv.set_json = orig


@pytest.fixture(autouse=True)
def _tohom_on():
    """The instant-confirm law needs the smart engine ON regardless of what
    an earlier suite test left in the shared settings singleton."""
    import config
    orig = config.get_settings
    cfg = orig()
    try:
        object.__setattr__(cfg, "tohom_enabled", True)
    except Exception:
        pass
    yield
    config.get_settings = orig


from analysis.confirm_r62 import confirm_edge_at  # noqa: E402
from analysis.tohom import evaluate_tohom_confirmation  # noqa: E402


def _now5():
    return pd.Timestamp.utcnow().tz_localize(None).floor("5min")


def _cand(direction="LONG", md=None, setup="TLBREAK", created_min=None,
          created_at=None):
    return SignalCandidate(
        signal_id="R76", symbol="BTCUSDT", style="SWING", setup_code=setup,
        setup_name="x", strategy_fa="x", direction=direction, score=8,
        status="ANALYSIS", entry_zone_bottom=95.0, entry_zone_top=99.0,
        planned_entry=99.0, sl=94.0, tp1=104.0, tp2=108.0, rr_tp1=1.5,
        rr_tp2=2.0, bias="BULL", trigger_timeframe="1h",
        mandatory_gates={"zone": True},
        created_at=str(created_at or (pd.Timestamp.utcnow()
                                      - pd.Timedelta(minutes=created_min or 8))),
        confirmed_at=str(pd.Timestamp.utcnow() - pd.Timedelta(minutes=2)),
        metadata=dict(md or {}))


def _sub_frame(close_last, vol_last=300.0, n_hist=26):
    """20 flat history bars + ONE closed 5m sub-candle."""
    now = pd.Timestamp.utcnow().tz_localize(None).floor("5min")
    ts = [now - pd.Timedelta(minutes=5 * (n_hist - i)) for i in range(n_hist)]
    ts.append(now - pd.Timedelta(minutes=5))       # the closed sub-candle
    o = [99.0] * n_hist + [99.6]
    c = [99.0] * n_hist + [close_last]
    v = [100.0] * n_hist + [vol_last]
    return pd.DataFrame({
        "timestamp": ts,
        "open": o, "close": c,
        "high": [max(a, b) + 0.2 for a, b in zip(o, c)],
        "low": [min(a, b) - 0.2 for a, b in zip(o, c)],
        "volume": v,
    })


def test_tohom_decisive_single_sub_confirms():
    cand = _cand(md={"atr": 2.0, "viva_breakout_line": 100.0},
                 created_at=_now5() - pd.Timedelta(minutes=5))
    ok, _, why = evaluate_tohom_confirmation(
        cand, _sub_frame(101.2), sub_tf="5m")     # +1.2 = 0.6·ATR beyond edge
    assert ok, why
    assert cand.metadata.get("tohom") == 1


def test_tohom_weak_single_sub_still_waits():
    cand = _cand(md={"atr": 2.0, "viva_breakout_line": 100.0},
                 created_at=_now5() - pd.Timedelta(minutes=5))
    ok, _, why = evaluate_tohom_confirmation(
        cand, _sub_frame(100.4), sub_tf="5m")     # 0.4 < 0.5·ATR → not decisive
    assert not ok
    assert cand.metadata.get("last_reject_code") == "TOHOM_WAIT"


def test_edge_rebuilt_from_chart_line():
    t0 = pd.Timestamp("2026-10-12 00:00:00")
    t1 = pd.Timestamp("2026-10-12 04:00:00")
    md = {
        "viva_breakout_line": 100.0,
        "render_patterns": [{"type": "TRENDLINE", "lines": [
            {"side": "HIGH", "points": [
                {"ts": str(t0), "price": 100.0},
                {"ts": str(t1), "price": 98.0}]}]}],
    }
    cand = _cand(md=md)
    when = t1 + pd.Timedelta(hours=1)
    edge = confirm_edge_at(cand, when)
    # chord: 100 → 98 over 4h, one more hour → 97.5 (NOT the frozen 100)
    assert abs(edge - 97.5) < 1e-6, edge
    # without `when` the static level is still the answer (PIN/static law)
    assert confirm_edge_at(cand) == 100.0


def test_realtime_gate_returns_idle_sentinel(monkeypatch):
    import database.realtime_monitor as rm
    monkeypatch.setattr(rm, "pending_filled_count", lambda: 0)
    import main
    assert main.run_realtime_execution_cycle() == -1


# ── Viva 10-14 second batch: retest-entry law + chart-timing law ──────────
def test_breakout_entry_is_retest_of_broken_line():
    import re
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "analysis", "pattern_engine.py")).read()
    m = re.search(r"if is_break:.{0,700}?entry = float\(line_now\)", src, re.S)
    assert m, "breakout entry must be the broken line (retest), not the chase"
    block = m.group(0)
    assert "entry = live\n" not in block


def test_chart_timing_law_four_moments():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "analysis", "line_watch.py")).read()
    # touch (s1) and break (s2) carry charts; the helper is fail-soft
    assert "_tchart73 = _lw_render_chart(entry, _titem73, \"s1\")" in src
    assert "_bchart73 = _lw_render_chart(entry, _bitem73, \"s2\")" in src
    assert "_ssa73b(_bitem73, _bchart73)" in src
    mn = open(os.path.join(os.path.dirname(__file__), "..", "main.py")).read()
    # generic r57 update events stay OFF by default (text-only economy)
    assert "_spot_update_events_enabled()" in mn
