"""Round 16 — the spot ALERT LADDER (Viva 09-22):

* «هشدار برخورد اولیه به هر سمتی از ترندهای بالا و پایین هر الگویی»  → TOUCH
* «هشدار نزدیک شدن به شکست یا بریک شدن»                              → NEAR_BREAK
* «هشدار شکست هر دو جهت ... فقط کلوز بعد از بریک در جهت لانگ تایید»   → BREAK_DOWN
* the CryptoCove box law: from the FIRST warning the box rides to the next
  structural high (+1%)
* the ladder never walks backward; a published signal closes it (CONFIRM)
* markers are committed only AFTER a successful send (handoff law)
"""
from __future__ import annotations

import uuid

import pandas as pd
import pytest


def _df(closes, highs=None, lows=None, opens=None, tf_hours=24):
    n = len(closes)
    idx = pd.date_range("2026-09-01", periods=n, freq=f"{tf_hours}h")
    highs = highs if highs is not None else [c * 1.01 for c in closes]
    lows = lows if lows is not None else [c * 0.99 for c in closes]
    opens = opens if opens is not None else list(closes)
    return pd.DataFrame({"timestamp": idx, "open": opens, "high": highs,
                         "low": lows, "close": list(closes),
                         "volume": [1.0] * n})


# a falling wedge: upper side at bar n → -0.5·n + 120, lower → -0.9·n + 110
WEDGE = {"type": "WEDGE_FALLING", "shape": "converging", "bias": "BULL",
         "lines": [{"slope": -0.5, "intercept": 120.0, "side": "HIGH", "x0": 10},
                   {"slope": -0.9, "intercept": 110.0, "side": "LOW", "x0": 20}]}
N = 50            # upper = 95.0 · lower = 65.0
ATR = 1.0


def _stage(candle, pat=WEDGE, atr=ATR, n=N):
    from analysis.spot_engine import _stage_for_pattern
    closes = [100.0] * (n + 1)
    closes[-1] = candle["close"]
    highs = [101.0] * (n + 1)
    highs[-1] = candle.get("high", candle["close"] * 1.01)
    lows = [99.0] * (n + 1)
    lows[-1] = candle.get("low", candle["close"] * 0.99)
    opens = [100.0] * (n + 1)
    opens[-1] = candle.get("open", candle["close"])
    return _stage_for_pattern(pat, _df(closes, highs, lows, opens), atr, n)


# ── TOUCH: wick kisses a side, the close stays >0.30·ATR inside ─────────────
def test_touch_upper_side():
    s = _stage({"close": 94.0, "high": 95.2, "open": 94.6})
    assert s and s["stage"] == "TOUCH" and s["side"] == "HIGH"


def test_touch_lower_side():
    s = _stage({"close": 66.5, "low": 64.9, "open": 67.2})
    assert s and s["stage"] == "TOUCH" and s["side"] == "LOW"


# ── NEAR_BREAK: close hugging an edge (≤0.30·ATR) ───────────────────────────
def test_near_break_upper():
    s = _stage({"close": 94.8, "open": 94.2})
    assert s and s["stage"] == "NEAR_BREAK" and s["side"] == "HIGH"


def test_near_break_lower():
    s = _stage({"close": 65.25, "open": 65.9})
    assert s and s["stage"] == "NEAR_BREAK" and s["side"] == "LOW"


# ── BREAK_DOWN: valid bearish close beyond the lower side = WARNING ONLY ────
def test_break_down():
    s = _stage({"close": 64.0, "open": 65.6})
    assert s and s["stage"] == "BREAK_DOWN" and s["side"] == "LOW"


def test_break_down_needs_directional_body():
    # a doji close beyond the edge is NOT a valid break (one-close law)
    s = _stage({"close": 64.85, "open": 64.9})
    assert s is None or s["stage"] != "BREAK_DOWN"


def test_quiet_candle_is_silent():
    assert _stage({"close": 80.0}) is None


# ── structural high → the CryptoCove box target (+1%) ───────────────────────
def test_structural_high_above():
    closes = [100.0] * 60
    highs = [100.5] * 60
    highs[30] = 118.0                       # a clear pivot above the price
    d = _df(closes, highs=highs, lows=[99.5] * 60)
    from analysis.spot_engine import _structural_high_above
    top = _structural_high_above(d, 100.0)
    assert top == pytest.approx(118.0)
    assert _structural_high_above(d, 130.0) is None   # nothing above anymore


# ── the render-only alert candidate: SPOT language from the first warning ──
def test_alert_candidate_metadata():
    from analysis.spot_engine import build_spot_alert_candidate
    item = {"stage": "NEAR_BREAK", "side": "HIGH", "symbol": "SOMI", "tf": "3d",
            "pattern": "WEDGE_FALLING", "pattern_fa": "گوه نزولی (فالینگ‌وج)",
            "rule_fa": "دو ضلع همگرا…", "close": 94.8, "edge": 95.0,
            "distance_pct": 0.21, "atr": 1.0, "box_top": 119.18,
            "pattern_commands": [WEDGE], "sig": "S|3d|WEDGE_FALLING|10|20",
            "bar_ts": "2026-09-22 00:00:00",
            "detected_at": "2026-09-22T01:00:00+00:00"}
    cand = build_spot_alert_candidate(item)
    md = cand.metadata
    assert md["market"] == "SPOT" and md["log_scale"] is True
    assert md["spot_measured_box"] is True
    assert md["spot_box_top"] == pytest.approx(119.18)
    assert cand.status == "WATCH" and cand.direction == "LONG"
    assert md["render_patterns"] == [WEDGE]


# ── the gate: stage-advance speaks, same stage waits, CONFIRM closes ───────
def _item(stage, sig=None, bar="2026-09-22 00:00:00"):
    return {"stage": stage, "side": "HIGH", "symbol": "TEST", "tf": "1d",
            "pattern": "WEDGE_FALLING", "pattern_fa": "گوه نزولی",
            "rule_fa": "…", "close": 94.8, "edge": 95.0, "distance_pct": 0.21,
            "atr": 1.0, "box_top": 0.0, "pattern_commands": [WEDGE],
            "sig": sig or f"TESTSIG-{uuid.uuid4().hex[:8]}", "bar_ts": bar,
            "detected_at": "2026-09-22T01:00:00+00:00"}


def test_gate_stage_advance_and_confirm_close():
    from analysis.spot_engine import (spot_alert_check, spot_alert_commit,
                                      spot_alert_mark_confirmed)
    it = _item("TOUCH")
    assert spot_alert_check(it) is True          # fresh shape speaks
    spot_alert_commit(it)
    assert spot_alert_check(dict(it)) is False   # same stage, same bar: silent
    up = dict(it, stage="NEAR_BREAK")
    assert spot_alert_check(up) is True          # advance → speaks
    spot_alert_commit(up)
    spot_alert_mark_confirmed(str(it["sig"]))    # a published signal closes it
    assert spot_alert_check(_item("TOUCH", sig=it["sig"],
                                  bar="2026-09-23 00:00:00")) is False


def test_gate_commit_only_after_send():
    from analysis.spot_engine import spot_alert_check, spot_alert_commit
    it = _item("TOUCH")
    assert spot_alert_check(it) is True
    # NO commit (send failed) → the next pass may try again
    assert spot_alert_check(dict(it)) is True
    spot_alert_commit(it)
    assert spot_alert_check(dict(it)) is False   # committed → silent


# ── scan integration: the ladder picks the strongest stage per shape ───────
def test_scan_spot_alerts_monkeypatched(monkeypatch):
    import analysis.render_kit as rk

    def fake_detect(df, direction=""):
        # the wedge's sides at THIS frame's last bar (n = len-1 = 50)
        return [dict(WEDGE, label="WEDGE_FALLING")]

    monkeypatch.setattr(rk, "detect_patterns", fake_detect)
    from analysis.spot_engine import scan_spot_alerts
    closes = [100.0] * 51
    closes[-1] = 94.8
    highs = [101.0] * 51
    highs[-1] = 94.9
    lows = [99.0] * 51
    lows[-1] = 94.0
    opens = [100.0] * 51
    opens[-1] = 94.4
    frame = _df(closes, highs, lows, opens)
    # freshness needs a CURRENT last candle → re-stamp the timestamps to now
    frame["timestamp"] = pd.date_range(
        end=pd.Timestamp.utcnow().tz_localize(None).floor("h"),
        periods=len(frame), freq="24h")
    items = scan_spot_alerts("SOMI", {"3d": frame})
    assert len(items) == 1
    it = items[0]
    assert it["stage"] == "NEAR_BREAK" and it["side"] == "HIGH"
    assert it["pattern"] == "WEDGE_FALLING" and it["tf"] == "3d"
    assert it["sig"].startswith("SOMI|3d|WEDGE_FALLING|")
