"""Round 15 phase 5 — his 09-22 hand-over: the four real channels + SPOT.

Fixed here:

* his channel NAMES decide the buckets (15m/30m/1h · 2h/4h · 1d/3d/1w · spot),
  with the old SWING_* env names still honoured as fallbacks;
* 3d and 1w exist as epoch-aligned aggregates of the daily tape — never a
  window-aligned bucket whose open/close would shift with the lookback;
* the SPOT engine is LONG-only, bullish-shape-only, TLBREAK + TECHCLASSIC, on
  4h/1d/3d/1w, long the broken shape's upper side, with a structural stop and a
  measured path that can never sit closer than the timeframe's band;
* the stop ceiling of the timeframe is the LAST word before a chart or a
  message leaves the building (his ADA 1h chart: 9% stop against a 1.75% cap);
* spot charts are log-scale, futures charts are not.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ───────────────────────────── channels ─────────────────────────────

def test_his_channel_names_decide_the_buckets():
    """No module reload here on purpose: reloading bot.messages_v7 mid-suite
    resets its render caches and makes an unrelated chart test flaky. The
    mapping is asserted on the module's own source + the live bucket function.
    """
    import bot.messages_v7 as M
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'CHAT_ID_TF_15M_1H' in src and 'CHAT_ID_TF_2H_4H' in src
    assert 'CHAT_ID_TF_1D' in src and 'CHAT_ID_SPOT' in src
    # the old names survive as fallbacks so no deploy can lose a channel
    assert 'os.getenv("CHAT_ID_TF_15M_1H",' in src
    assert 'os.getenv("CHAT_ID_SWING_SHORT", "")' in src
    assert '("15M_1H", {"15m", "30m", "1h"}' in src
    assert '("2H_4H", {"2h", "4h"}' in src
    assert '("1D", {"1d", "3d", "1w"}' in src
    assert M.tf_channel_bucket("15m") == "15M_1H"
    assert M.tf_channel_bucket("1h") == "15M_1H"
    assert M.tf_channel_bucket("30m") == "15M_1H"
    assert M.tf_channel_bucket("2h") == "2H_4H"
    assert M.tf_channel_bucket("4h") == "2H_4H"
    assert M.tf_channel_bucket("1d") == "1D"
    assert M.tf_channel_bucket("3d") == "1D"
    assert M.tf_channel_bucket("1w") == "1D"


# ─────────────────────── 3d / 1w aggregation ───────────────────────

def _daily(n=40, start="2026-07-01"):
    ts = pd.date_range(start, periods=n, freq="1D")
    px = np.linspace(100, 140, n)
    return pd.DataFrame({"timestamp": ts, "open": px, "high": px + 1.5,
                         "low": px - 1.5, "close": px + 0.5,
                         "volume": [10.0] * n})


def test_3d_and_1w_are_epoch_aligned_aggregates():
    from data.fetcher import _aggregate_daily
    d = _daily(40)
    a3 = _aggregate_daily(d, 3)
    a7 = _aggregate_daily(d, 7)
    assert a3 is not None and a7 is not None
    # 3-day buckets start on epoch-aligned days → day-of-epoch divisible by 3
    for ts in a3["timestamp"]:
        day = pd.Timestamp(ts).value // 86_400_000_000_000
        assert day % 3 == 0
    for ts in a7["timestamp"]:
        day = pd.Timestamp(ts).value // 86_400_000_000_000
        assert day % 7 == 0
    # OHLC honesty: every bucket's high/low bracket its own daily members and
    # its close is the LAST close inside the bucket
    for _, bucket in a3.iterrows():
        start = pd.Timestamp(bucket["timestamp"])
        end = start + pd.Timedelta(days=3)
        members = d[(d["timestamp"] >= start) & (d["timestamp"] < end)]
        assert len(members) == 3
        assert bucket["high"] >= members["high"].max() - 1e-9
        assert bucket["low"] <= members["low"].min() + 1e-9
        assert abs(bucket["close"] - members["close"].iloc[-1]) < 1e-9


def test_a_half_formed_bucket_is_never_emitted():
    from data.fetcher import _aggregate_daily
    d = _daily(38)                     # 38 days → the last 3d/1w bucket is partial
    a3 = _aggregate_daily(d, 3)
    assert len(a3) == 12               # 36 closed days folded, the 2 left over dropped
    from data.fetcher import _TF_SECONDS
    assert _TF_SECONDS["3d"] == 259200 and _TF_SECONDS["1w"] == 604800


# ─────────────────────────── the SPOT engine ───────────────────────────

def _spot_frames():
    """A fresh 4h tape (its last closed bar is the newest closed bucket)."""
    n = 90
    now = pd.Timestamp.utcnow().tz_localize(None).floor("4h")
    ts = pd.date_range(end=now, periods=n, freq="4h")
    px = list(np.linspace(100.0, 108.0, n))
    px[-1] = 112.0                     # the break close
    close = pd.Series(px)
    return {"4h": pd.DataFrame({"timestamp": ts, "open": close - 0.2,
                                "high": close + 0.5, "low": close - 0.6,
                                "close": close, "volume": [100.0] * n})}


def _fake_patterns(bias="BULL", label="WEDGE_FALLING", upper=105.0, slope=-0.05):
    def _fake(df, direction=""):
        n = len(df) - 1
        upper_line = {"side": "HIGH", "slope": slope,
                      "intercept": upper - slope * n, "x0": 5, "x1": n,
                      "points": [{"ts": str(df["timestamp"].iloc[5]), "price": upper},
                                 {"ts": str(df["timestamp"].iloc[-6]), "price": upper - 2.5}]}
        lower_line = {"side": "LOW", "slope": slope, "intercept": 0.0,
                      "intercept_real": None, "x0": 3, "x1": n,
                      "points": [{"ts": str(df["timestamp"].iloc[3]), "price": 96.0},
                                 {"ts": str(df["timestamp"].iloc[-8]), "price": 96.5}]}
        lower_line.pop("intercept_real")
        lower_line["intercept"] = 96.0 - slope * 3
        from analysis.patterns import pattern_info
        info = pattern_info(label)
        return [{"type": label, "lines": [upper_line, lower_line],
                 "name": label, "name_fa": info["fa"], "bias": bias,
                 "shape": info["shape"], "rule_fa": info["rule_fa"],
                 "break_direction": "UP" if bias in ("BULL", "NEUTRAL") else "DOWN",
                 "label": label}]
    return _fake


def test_spot_engine_never_returns_a_short_or_a_bearish_shape(monkeypatch):
    from analysis.spot_engine import bullish_pattern_ok, scan_spot_symbol
    assert bullish_pattern_ok({"bias": "BULL"}, 100.0, 95.0) is True
    assert bullish_pattern_ok({"bias": "BEAR"}, 100.0, 95.0) is False
    assert bullish_pattern_ok({"bias": "NEUTRAL"}, 100.0, 95.0) is True
    assert bullish_pattern_ok({"bias": "NEUTRAL"}, 94.0, 95.0) is False
    # a bearish shape (rising wedge) never becomes a spot LONG
    monkeypatch.setattr("analysis.render_kit.detect_patterns",
                        _fake_patterns(bias="BEAR", label="WEDGE_RISING", upper=99.0))
    assert scan_spot_symbol("TESTUSDT", _spot_frames()) == []


def test_a_spot_candidate_is_born_confirmed_long_with_log_chart_and_box(monkeypatch):
    from analysis.spot_engine import scan_spot_symbol, build_spot_candidate
    # a bullish falling wedge whose upper side is 105 and price closed at 112
    monkeypatch.setattr("analysis.render_kit.detect_patterns",
                        _fake_patterns(bias="BULL", label="WEDGE_FALLING", upper=105.0))
    items = scan_spot_symbol("TESTUSDT", _spot_frames())
    assert items, "a bullish break of the shape's upper side must produce a signal"
    it = items[0]
    assert it["sl"] < it["entry"]                 # structurally LONG
    assert it["tf"] in ("4h", "1d", "3d", "1w")
    assert it["path_pct"] >= 5.0 - 1e-9           # his band for 4h/1d
    cand = build_spot_candidate(it)
    assert cand.direction == "LONG" and cand.status == "CONFIRMED"
    assert (cand.metadata or {})["market"] == "SPOT"
    assert (cand.metadata or {})["log_scale"] is True
    assert (cand.metadata or {})["spot_measured_box"] is True
    assert (cand.metadata or {})["target_ladder"]["targets"]
    from analysis.trade_management import stop_ceiling_pct
    dist_pct = (cand.planned_entry - cand.sl) / cand.planned_entry * 100.0
    assert dist_pct <= stop_ceiling_pct(cand.trigger_timeframe) + 1e-9


def test_spot_lane_is_wired_and_budgeted():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "main.py"), encoding="utf-8").read()
    assert "def run_spot_scan()" in src and "next_spot" in src
    assert "chat_override=CHAT_ID_SPOT" in src
    assert "SPOT_MAX_PER_DAY" in src and "SPOT_SCAN_MINUTES" in src
    msg = open(os.path.join(root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "_a9.set_yscale(\"log\")" in msg


# ─────────────────────── stop ceiling, last word ───────────────────────

def test_the_stop_ceiling_is_enforced_just_before_publishing():
    from analysis.models import SignalCandidate
    from bot.messages_v7 import _final_stop_guard
    cand = SignalCandidate(
        signal_id="R15E-1", symbol="ADAUSDT", style="SWING",
        setup_code="PINWALLQ", setup_name="t", strategy_fa="t",
        direction="SHORT", score=8, status="CONFIRMED",
        entry_zone_bottom=0.2196, entry_zone_top=0.2198, planned_entry=0.2197,
        sl=0.2397, tp1=0.2136, tp2=0.2015, rr_tp1=1.0, rr_tp2=2.0,
        bias="BEAR", trigger_timeframe="1h", mandatory_gates={"zone": True},
        created_at="2026-09-21T09:00:00+00:00", metadata={})
    out = _final_stop_guard(cand)
    dist = (out.sl - out.planned_entry) / out.planned_entry * 100.0
    assert abs(dist - 1.75) < 1e-6, dist          # 1h ceiling, round 14 table
    assert out.metadata["stop_clamped"] == "1.75%"
    # an inside-the-ceiling structural stop is never touched
    cand.sl = 0.2225
    _final_stop_guard(cand)
    assert abs(cand.sl - 0.2225) < 1e-12
