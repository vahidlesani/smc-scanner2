"""Viva 10-09 SMART-WINDOW locks: live-focus y (both renderers), no count
floor/ceiling, touch-validated superiority, 240-DPI unify, sendDocument path.
"""
import math
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _frame(n=200, last_now=True):
    end = pd.Timestamp.utcnow().tz_localize(None).floor("4h")
    ts = pd.date_range(end=end, periods=n, freq="4h")
    rng = np.random.default_rng(11)
    close = 100 + np.cumsum(rng.normal(0, 0.4, n))
    o = close - 0.1
    h = np.maximum(o, close) + 0.3
    lo = np.minimum(o, close) - 0.3
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": lo,
                         "close": close, "volume": np.full(n, 1000.0)})


def _break_pat(edge, touch_ts, side="HIGH"):
    return {"shape": "single", "type": "TRENDLINE", "child": False,
            "lines": [{"side": side, "slope": 0.0, "intercept": float(edge),
                       "x0": 0, "x1": 199,
                       "points": [{"ts": "2026-01-01", "x": 0},
                                  {"ts": str(touch_ts), "x": 199}]}]}


# ── 1. the shared ruler: need + live + margin, no floor, no ceiling ──
def test_ruler_need_is_ref_plus_live_plus_margin():
    from analysis.chart_window import need_start, need_count, NEED_MARGIN
    n, live = 400, 60
    refs = [100]                       # first-needed anchor at bar 100
    assert need_start(n, refs, live) == 100 - NEED_MARGIN
    assert need_count(n, refs, live) == n - (100 - NEED_MARGIN)
    assert need_start(n, [], live) == n - live   # anchorless → live only


def test_ruler_has_no_floor_and_no_ceiling():
    from analysis.chart_window import need_count
    import analysis.chart_window as cw
    assert not hasattr(cw, "NEED_MIN_BARS")          # the 45-floor is DEAD
    assert need_count(400, [390], 40) == 40          # thin needs stay thin
    assert need_count(2000, [10], 60) > 1500         # deep needs stay deep


def test_ruler_live_block_is_a_floor_per_tf():
    from analysis.chart_window import live_block_for_tf
    for tf in ("5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h",
               "1d", "3d", "1w"):
        assert live_block_for_tf(tf) >= 30, tf
    assert live_block_for_tf("nonsense") >= 30       # fail-open


# ── 2. live-focus y: the live block owns the panel, fossils clip ──
def test_smart_y_live_block_owns_panel_and_fossil_clips():
    from bot.messages_v7 import _smart_y_window
    # a BTC-4h-like tape: live block 100±2, one fossil spike at 40
    ylo, yhi = _smart_y_window(40.0, 102.0, 0.5, None, None,
                               recent_lo=98.0, recent_hi=102.0)
    live_share = (102.0 - 98.0) / (yhi - ylo)
    assert live_share >= 0.35, (ylo, yhi)   # live fills the panel, no squash
    assert ylo > 40.0                        # the fossil spike clips


def test_smart_y_overlays_and_live_never_clip():
    from bot.messages_v7 import _smart_y_window
    # the tool ON/NEAR the tape stays IN FULL (a level adrift beyond 2× the
    # soft reach is off-canvas context — the DASH law, locked by r28/r37/r40).
    ylo, yhi = _smart_y_window(90.0, 110.0, 0.5, 85.0, 115.0,
                               recent_lo=98.0, recent_hi=102.0)
    assert ylo <= 85.0 and yhi >= 115.0      # the tool stays IN FULL
    assert ylo <= 98.0 and yhi >= 102.0      # the live block is never cut


def test_smart_y_clean_frame_has_no_forced_scroll():
    from bot.messages_v7 import _smart_y_window
    # tape ≈ live: the window hugs the frame, never a gate-driven crop
    ylo, yhi = _smart_y_window(98.0, 102.0, 0.5, None, None,
                               recent_lo=98.5, recent_hi=101.5)
    assert ylo < 98.5 and yhi > 101.5
    assert (yhi - ylo) < 3.0 * (102.0 - 98.0)


# ── 3. superiority: fossil BREAK dies, live BREAK speaks ──
def test_superiority_fossil_break_is_suppressed(monkeypatch):
    import analysis.render_kit as rk
    from analysis.spot_engine import scan_spot_alerts
    d = _frame(200)
    atr = float((d["high"] - d["low"]).tail(14).mean())
    edge = float(d["close"].iloc[-1]) - 1.0
    d.loc[d.index[-1], "close"] = edge + 0.5 * atr + 1.0
    d.loc[d.index[-1], "open"] = edge
    fossil = _break_pat(edge, d["timestamp"].iloc[5])  # touched 194 bars ago
    monkeypatch.setattr(rk, "detect_patterns", lambda *a, **k: [fossil])
    items = scan_spot_alerts("ADAUSDT", {"4h": d})
    assert [i for i in items if i["stage"] in ("BREAK_UP", "BREAK_DOWN")] == []


def test_superiority_live_break_speaks_with_touch_age(monkeypatch):
    import analysis.render_kit as rk
    from analysis.spot_engine import scan_spot_alerts
    d = _frame(200)
    atr = float((d["high"] - d["low"]).tail(14).mean())
    edge = float(d["close"].iloc[-1]) - 1.0
    d.loc[d.index[-1], "close"] = edge + 0.5 * atr + 1.0
    d.loc[d.index[-1], "open"] = edge
    n = len(d) - 1
    live = _break_pat(edge, d["timestamp"].iloc[n - 3])  # touched 3 bars ago
    monkeypatch.setattr(rk, "detect_patterns", lambda *a, **k: [live])
    items = scan_spot_alerts("ADAUSDT", {"4h": d})
    breaks = [i for i in items if i["stage"] == "BREAK_UP"]
    assert len(breaks) == 1
    assert breaks[0]["touch_age_bars"] == 3


# ── 4. quality: 240 DPI everywhere + the document send path ──
def test_quality_dpi_240_unified_and_document_path_exists():
    spot = open(os.path.join(ROOT, "analysis", "spot_pattern_engine.py"),
                encoding="utf-8").read()
    main = open(os.path.join(ROOT, "bot", "messages_v7.py"),
                encoding="utf-8").read()
    assert 'CHART_DPI", "240"' in spot        # spot left 180 behind
    assert 'CHART_DPI", "240"' in main        # spike renderer already 240
    assert "dpi=180" not in spot
    from bot.messages_v7 import send_chart_file
    assert callable(send_chart_file)
    assert "sendDocument" in main and "CHART_SEND_AS_FILE" in main


# ── 5. superiority is ONE explanation line, not a veto ──
def test_superiority_one_liner_in_alert_text(monkeypatch):
    import bot.messages_v7 as m7
    monkeypatch.setattr(m7, "CHAT_ID_SPOT", "test-chat")
    monkeypatch.setattr("database.bot_kv.get_json", lambda k, d=None: {})
    monkeypatch.setattr("database.bot_kv.set_json", lambda *a, **k: None)
    sent = {}
    monkeypatch.setattr(
        m7, "send_message",
        lambda text, chat, **k: sent.update(text=text) or 111)
    item = {"stage": "BREAK_UP", "side": "HIGH", "symbol": "ADAUSDT",
            "tf": "3d", "pattern": "TRIANGLE_SYMMETRICAL",
            "pattern_fa": "مثلث متقارن", "rule_fa": "",
            "distance_pct": 0.5, "vol_ratio": 1.0, "touch_age_bars": 6,
            "_leads109": True,
            "_rivals109": [{"tf": "12h", "fa": "گوه صعودی",
                            "stage": "BREAK_DOWN", "age": 25}]}
    assert m7.send_spot_alert(item, chart=None) == 111
    assert "⚔️" in sent["text"]
    assert "الگوی برتر این نماد همین است" in sent["text"]
    assert "6 کندل" in sent["text"] and "12h" in sent["text"]
