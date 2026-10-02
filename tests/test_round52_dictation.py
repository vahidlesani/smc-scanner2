"""r52 — HIS dictation round (Viva 09-28 «ببین و بخون و دقیق انجام بده»).

1. CryptoCove candle counts are now HIS numbers (4h/8h→170, 12h/1d→210,
   3d→300, 1w→210) with the window as a HARD CAP (the r37 widen is retired —
   SUI's month-of-needle-candles chart must be impossible).
2. The one-time deep-history store: daily tape fetched deep ONCE, stored in
   bot_kv, later scans only tail-refresh (Railway cost law).
3. Suffocation law: Retest→Rejection→BOS NEVER confirms a VIVA_TLBREAK
   signal and never blocks it — THIS signal confirms on the first valid
   close beyond the edge (or TOHOM); pullback/BOS is the NEXT position's map.
4. LOG axis kit: locator (subs='all') + plain formatter + silent minors at
   every set_yscale site (SUI's lonely 1.0 with naked dashes must not recur).
5. The chart TF stamp reads the TAPE first (SUI's 4h-deep frame stamped
   «15M» must not recur).
"""
import ast
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ── 1. the dictated counts + hard cap ──────────────────────────────────────
def test_dictated_candle_counts_are_law():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    # R64 (his 10-02 dictation «۲۵۰ تا ۳۵۰ کندل بسته به تایم‌فریم … هم اسپات
    # هم پرپچوال، حتی روزانه») supersedes the r52 counts — the map lives in
    # analysis.candle_counts and every TF sits inside 250..350.
    from analysis.candle_counts import CANDLE_COUNTS
    from bot.messages_v7 import _CHART_CANDLE_COUNTS
    # R65 picture density: the chart has its OWN map now — 190–210 on the
    # intraday frames (his «کندل ۱۹۰ تا ۲۱۰ تا کافیه … فقط شلوغ‌تر شد»),
    # while DETECTION keeps the dictated 250–350 bars.
    from analysis.candle_counts import RENDER_COUNTS
    assert _CHART_CANDLE_COUNTS == RENDER_COUNTS
    for _tf in ("5m", "15m", "30m", "1h", "2h"):
        assert 190 <= RENDER_COUNTS[_tf] <= 210
    for tf in ("4h", "8h", "12h", "1d", "3d", "1w", "1h", "2h", "30m", "15m"):
        assert 250 <= CANDLE_COUNTS[tf] <= 350, tf
    # the r37 widen must be gone: no 2.2x window stretch may remain
    assert "int(_lookback * 2.2)" not in src
    assert "_need37" not in src


def test_window_is_a_hard_cap_in_render():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    # r53: the map is the module-level single source of truth; the render
    # window is cut straight from it — no widen may sit in between.
    assert "_CHART_CANDLE_COUNTS = dict(_R65_RENDER_COUNTS)" in src
    assert "RENDER_COUNTS as _R65_RENDER_COUNTS" in src
    seg = src.split("_lookback = _CHART_CANDLE_COUNTS.get")[1].split("frame = _clean_render_frame")[0]
    assert "_need37" not in seg and "2.2" not in seg
    assert "frame = _clean_render_frame(df, window=_lookback)" in src


def test_chart_tf_stamp_prefers_the_tape():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    marker = src.index("def _chart_tf_token")
    body = src[marker:marker + 1400]
    assert body.index("_infer_chart_tf(frame, candidate)") < \
        body.index("md.get(\"chart_view_tf\")")


# ── 2. deep-history store ──────────────────────────────────────────────────
def test_history_store_fetches_once_then_tail_refreshes(monkeypatch):
    import time as _t
    import data.history_store as hs
    hs._MEMORY.clear()
    calls = {"deep": 0, "tail": 0}
    stored = {}

    deep_frame = pd.DataFrame({
        "timestamp": pd.date_range("2022-01-01", periods=1600, freq="D"),
        "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0,
        "volume": 100.0,
    })

    def fake_deep(sym, iv, limit, closed_only=True):
        calls["deep"] += 1
        return deep_frame.copy()

    def fake_tail(sym, iv, limit, closed_only=True, use_cache=False, end_ms=None):
        calls["tail"] += 1
        return deep_frame.tail(3).copy()

    monkeypatch.setattr("data.fetcher.get_klines_paginated", fake_deep)
    monkeypatch.setattr("data.fetcher.get_klines", fake_tail)
    monkeypatch.setattr(hs, "_load", lambda s: stored.get(s))
    monkeypatch.setattr(hs, "_save", lambda s, f: stored.__setitem__(s, f.copy()))

    out1 = hs.get_deep_daily("TESTUSDT", 1477)
    assert len(out1) == 1477 and calls["deep"] == 1 and calls["tail"] == 0
    assert "TESTUSDT" in stored  # the one-time deep scan persisted

    # second call inside the TTL: zero venue calls
    out2 = hs.get_deep_daily("TESTUSDT", 1477)
    assert len(out2) == 1477 and calls["deep"] == 1 and calls["tail"] == 0

    # TTL expired: only a small tail refresh, never a second deep scan
    at, frame = hs._MEMORY["TESTUSDT"]
    hs._MEMORY["TESTUSDT"] = (at - hs._MEMORY_TTL - 1, frame)
    out3 = hs.get_deep_daily("TESTUSDT", 1477)
    assert calls["deep"] == 1 and calls["tail"] == 1
    assert len(out3) == 1477


def test_history_store_fail_open(monkeypatch):
    import data.history_store as hs
    hs._MEMORY.clear()
    monkeypatch.setattr(hs, "_load", lambda s: None)
    def _boom(*a, **k):
        raise RuntimeError("venue down")
    monkeypatch.setattr("data.fetcher.get_klines_paginated", _boom)
    assert hs.get_deep_daily("BOOMUSDT", 300) is None  # never raises


# ── 3. suffocation law: pullback/BOS never confirm ─────────────────────────
def test_no_ready_without_fast_lane_in_tobreak_confirm():
    """The r52 block must strip machine-`ready` (retest/rejection/BOS) and the
    S3/S4 alt fast lane as confirmation paths, and keep the fast_lane one."""
    src = open(os.path.join(ROOT, "analysis", "quality_engine.py"),
               encoding="utf-8").read()
    marker = src.index("r52 SUFFOCATION LAW")
    window = src[marker:marker + 2400]
    assert 'candidate.metadata["pullback_entry_ready"] = True' in window
    assert "ready = False" in window
    # the alt rejection cluster must NOT set ready=True any more
    assert "ready = True\n            state = \"S5_MICRO_BOS\"" not in window
    # the wait message names the FIRST CLOSE, not the retest ladder
    assert "WAIT_FIRST_CLOSE_" in src
    assert "در انتظار Retest → Rejection → BOS" not in src


def test_strategy_titles_no_longer_demand_pullback_bos():
    src = open(os.path.join(ROOT, "analysis", "pattern_engine.py"),
               encoding="utf-8").read()
    assert "پولبک اول + BOS تأیید" not in src
    assert "تأیید با اولین کلوز (توهم هوشمند)" in src
    for path in ("bot/messages_v7.py",):
        src2 = open(os.path.join(ROOT, path), encoding="utf-8").read()
        assert "پولبک اول + BOS تایم پایین" not in src2
        assert "نقشهٔ ورود پوزیشن بعدی" in src2


# ── 4. LOG axis kit at every site ──────────────────────────────────────────
def test_log_axis_decorate_helper_and_sites():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "def _log_axis_decorate" in src
    assert "LogLocator(base=10.0, subs=\"all\"" in src
    # every set_yscale("log") site inside generate_chart paths is followed by
    # the decorate call (the three known sites)
    assert src.count('_log_axis_decorate(') >= 3


def test_axis_price_plain_decimals():
    from bot.messages_v7 import _axis_price
    assert _axis_price(0.8) == "0.8"
    assert _axis_price(0.2352) == "0.2352"
    assert _axis_price(1.0) == "1.0000"
    assert "e" not in _axis_price(0.09).lower()
