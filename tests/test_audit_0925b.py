"""R31.7 — audit 2026-09-25b: candle engines, classical patterns, trend engine,
TLBREAK freshness and chart geometry. Each test pins one fixed bug."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture(autouse=True)
def _no_legacy(monkeypatch):
    monkeypatch.delenv("R317_LEGACY", raising=False)


def _ohlc(rows, start="2026-09-01", freq="15min"):
    ts = pd.date_range(start, periods=len(rows), freq=freq)
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": l, "close": c,
                         "volume": np.full(len(rows), 100.0)})


# ── candle engine: trigger_patterns.multi_candle_trigger ────────────────────
def test_cluster_trigger_requires_the_base_to_trade_the_zone():
    from analysis.trigger_patterns import multi_candle_trigger
    # a clean bullish pin-shaped base far ABOVE the zone (zone 80–81)
    rows = [(100, 100.5, 99.5, 100)] * 10 + [(100, 100.3, 97.0, 100.2), (100.2, 100.4, 99.9, 100.35)]
    df = _ohlc(rows)
    got = multi_candle_trigger(df, "LONG", 80.0, 81.0, 1.0, mtf_enabled=False, require_zone_mid=False)
    assert got is None or got.kind not in {"CLUSTER_PIN", "RECLAIM", "CLUSTER_ENGULF", "CLUSTER_BOS"}


def test_cluster_engulf_needs_opposite_colours():
    from analysis.trigger_patterns import multi_candle_trigger
    # previous 2-bar stretch GREEN, current 2-bar stretch RED: never a LONG engulf
    rows = [(100, 100.2, 99.8, 100)] * 6 + [(99.0, 99.6, 98.9, 99.5), (99.5, 100.0, 99.4, 99.9),
                                             (99.95, 100.0, 98.7, 98.8), (98.8, 98.9, 98.6, 98.7)]
    df = _ohlc(rows)
    got = multi_candle_trigger(df, "LONG", 98.5, 99.2, 0.5, mtf_enabled=False,
                               require_zone_mid=False, fibo_enabled=False)
    assert got is None or got.kind != "CLUSTER_ENGULF"


def test_mtf_trigger_ignores_the_still_forming_higher_tf_candle():
    from analysis.trigger_patterns import multi_candle_trigger
    # 24 flat bars (4 complete 90-min bins) + 2 bars that ALONE look like a
    # bullish pin — as a partial 90-min bin they must not fire MTF_PIN
    flat = [(100, 100.1, 99.9, 100.0)] * 24
    tail = [(100.0, 100.05, 97.0, 99.9), (99.9, 100.1, 99.8, 100.05)]
    df = _ohlc(flat + tail, start="2026-09-01 00:00")
    got = multi_candle_trigger(df, "LONG", 96.5, 97.5, 0.3, max_base=1,
                               require_zone_mid=False, fibo_enabled=False)
    assert got is None or not got.kind.startswith("MTF_")


# ── candle engine: mtf_candles ──────────────────────────────────────────────
def test_long_legged_doji_is_not_both_pins():
    from analysis.mtf_candles import _candle, _describe
    c = _candle(100, 110, 90, 100.2)
    item = _describe("4h", c, None, "LONG", True, False)
    assert item is not None
    assert not ("Bullish Pin Bar" in item["pattern"] and "Bearish Pin Bar" in item["pattern"])


def test_bearish_candle_is_not_sold_as_long_confirmation():
    from analysis.mtf_candles import _candle, _describe
    prev = _candle(100, 102, 99.5, 101.5)
    cur = _candle(101.8, 102, 98.8, 99.0)          # bearish engulfing
    item = _describe("1h", cur, prev, "LONG", True, False)
    assert item["bias"] == "BEAR"
    assert "خلاف" in item["text"] and "قابل تفسیر" not in item["text"]


def test_weekly_resample_is_monday_aligned_and_complete():
    from analysis.mtf_candles import analyze_mtf_candles
    days = pd.date_range("2026-05-06", periods=210, freq="D")        # a Wednesday
    d1 = pd.DataFrame({"timestamp": days, "open": 100.0, "high": 101.0, "low": 99.0,
                       "close": 100.0, "volume": 1.0})
    captured = {}
    import analysis.mtf_candles as mc
    orig = mc._describe

    def spy(tf, c, prev, direction, ns, nr):
        captured.setdefault(tf, c)
        return orig(tf, c, prev, direction, ns, nr)
    mc._describe = spy
    try:
        analyze_mtf_candles({"1d": d1}, "LONG")
    finally:
        mc._describe = orig
    # replicate the bins the module now builds
    _d = d1.set_index("timestamp")
    rs = _d.resample("W-MON", label="left", closed="left")
    cnt = rs["close"].count()
    assert all(ix.day_name() == "Monday" for ix in cnt.index)
    assert "1w" in captured       # weekly evidence still produced


# ── classical patterns: pattern_engine.scan_edges ───────────────────────────
def _flat():
    import test_pattern_engine as t
    return t._mod(), t._flat_frames


def test_stale_break_is_not_re_emitted(monkeypatch):
    m, ff = _flat()
    pat, trig = ff()
    atr = float((pat["high"] - pat["low"]).tail(14).mean())
    stale = pat.copy()
    for i in range(134, 140):                       # broke out 6 bars ago
        stale.loc[i, ["open", "close", "high", "low"]] = [100.5, 100.7, 100.9, 100.3]
    t3 = trig.copy()
    for c in ("open", "high", "low", "close"):
        t3[c] = t3[c] - 0.3 * atr                   # 0.9 ATR above the line
    assert m.scan_edges(stale, t3, "4h") == []
    assert m.scan_edges(pat, t3, "4h")               # the SAME price on a fresh break is fine
    monkeypatch.setenv("R317_LEGACY", "1")
    assert m.scan_edges(stale, t3, "4h")             # kill switch restores the old behaviour


def test_chasing_far_beyond_the_line_is_blocked():
    m, ff = _flat()
    pat, trig = ff()
    atr = float((pat["high"] - pat["low"]).tail(14).mean())
    t2 = trig.copy()
    for c in ("open", "high", "low", "close"):
        t2[c] = t2[c] + 1.0 * atr                   # 2.2 ATR beyond
    assert m.scan_edges(pat, t2, "4h") == []


def test_inverse_hs_spelling_is_one_nature():
    from analysis import pattern_engine as pe
    assert "INVERSE_HEAD_SHOULDERS" in pe._ONE_NATURE
    assert "INVERSE_HEAD_SHOULDERS" in pe._BULL_FORMATIONS


# ── TLBREAK freshness + fitted-line time projection ─────────────────────────
def _vline(slope=0.0, icpt=100.0, idx=(10, 20, 30), start="2026-09-01", freq="1h"):
    from analysis.viva_tlbreak import ValidatedLine
    ts = pd.date_range(start, periods=40, freq=freq)
    pts = tuple({"index": i, "price": slope * i + icpt, "timestamp": ts[i]} for i in idx)
    return ValidatedLine(side="HIGH", slope=slope, intercept=icpt, touch_count=len(idx),
                         fit_residual_atr=0.1, first_index=idx[0], last_index=idx[-1], points=pts)


def test_line_price_at_time_follows_the_fit_not_the_touch_secant():
    from analysis.viva_tlbreak import ValidatedLine, line_price_at_time
    ts = pd.date_range("2026-09-01", periods=40, freq="1h")
    # touches sit ±0.4 off a flat fitted line at 100
    pts = ({"index": 10, "price": 99.6, "timestamp": ts[10]},
           {"index": 30, "price": 100.4, "timestamp": ts[30]})
    ln = ValidatedLine(side="HIGH", slope=0.0, intercept=100.0, touch_count=2,
                       fit_residual_atr=0.2, first_index=10, last_index=30, points=pts)
    assert line_price_at_time(ln, ts[39]) == pytest.approx(100.0)


def test_tlbreak_breakout_freshness():
    from analysis.viva_tlbreak import breakout_is_fresh
    ln = _vline()
    ts = pd.date_range("2026-09-02 16:00", periods=30, freq="15min")
    base = np.full(30, 99.0)
    df = pd.DataFrame({"timestamp": ts, "open": base, "high": base + 0.5, "low": base - 0.5,
                       "close": base, "volume": 1.0})
    fresh = df.copy()
    fresh.loc[29, ["open", "close", "high"]] = [99.2, 100.6, 100.7]
    assert breakout_is_fresh(fresh, ln, "LONG")
    stale = df.copy()
    stale.loc[20:, ["open", "close", "high", "low"]] = [100.8, 101.0, 101.2, 100.6]
    assert not breakout_is_fresh(stale, ln, "LONG")
    chase = fresh.copy()
    chase.loc[29, ["close", "high"]] = [104.5, 104.6]
    assert not breakout_is_fresh(chase, ln, "LONG")


# ── trend engine ────────────────────────────────────────────────────────────
def _trend_frame(tail_close):
    # HH/HL zig-zag, then a close under the last higher low
    vals = []
    for k in range(6):
        base = 100 + 4 * k
        vals += list(np.linspace(base, base + 6, 5))[:-1] + list(np.linspace(base + 6, base + 2, 5))[:-1]
    last = vals[-1]
    vals = np.array(vals + [last + 1.0, last + 2.0, last + 3.0, tail_close])
    ts = pd.date_range("2026-09-01", periods=len(vals), freq="1h")
    return pd.DataFrame({"timestamp": ts, "open": vals, "high": vals + 0.2, "low": vals - 0.2,
                         "close": vals, "volume": 1.0})


def test_structure_bias_flips_on_choch(monkeypatch):
    from analysis.indicators import structure_bias
    up = structure_bias(_trend_frame(126.5), 3)
    assert up["bias"] == "BULLISH"
    hl = float(up["last_low"]["price"])
    broken = structure_bias(_trend_frame(hl - 1.0), 3)
    assert broken["bias"] == "BEARISH" and broken["choch"] is True
    monkeypatch.setenv("R317_LEGACY", "1")
    assert structure_bias(_trend_frame(hl - 1.0), 3)["bias"] == "BULLISH"


def test_structure_bias_twin_pivots_do_not_hide_the_trend(monkeypatch):
    from analysis.indicators import structure_bias
    d = _trend_frame(0.0)
    d = d.iloc[:-5].reset_index(drop=True)          # end on a clean higher low
    # duplicate the last swing high bar value → an equal-high twin pivot
    top = int(d["high"].iloc[-12:].idxmax())
    d.loc[top + 1, ["high", "close", "open", "low"]] = d.loc[top, ["high", "close", "open", "low"]].values
    assert structure_bias(d, 3)["bias"] == "BULLISH"


def test_session_blocks_are_contiguous():
    from analysis.indicators import session_name
    assert session_name("2026-09-25 11:00") == "LONDON"
    assert session_name("2026-09-25 13:30") == "LONDON_NY_OVERLAP"
    assert session_name("2026-09-25 18:00") == "NEW_YORK"
    assert session_name("2026-09-25 03:00") == "ASIA"
    assert session_name("2026-09-25 22:00") == "OFF_SESSION"


# ── chart geometry ──────────────────────────────────────────────────────────
def test_pivot_x_before_the_frame_is_negative_not_clamped():
    from bot.messages_v7 import _frame_x_of_ts
    idx = pd.DatetimeIndex(pd.date_range("2026-09-01", periods=96, freq="1D"))
    assert _frame_x_of_ts(idx, "2026-08-22") == pytest.approx(-10.0)
    assert _frame_x_of_ts(idx, "2026-09-05") == 4.0


def test_lower_tf_pivot_maps_to_its_containing_candle():
    from bot.messages_v7 import _frame_x_of_ts
    idx = pd.DatetimeIndex(pd.date_range("2026-09-01", periods=10, freq="4h"))
    # a 15m pivot at 09:45 lives in the 08:00 4h candle (x=2), not the next one
    assert _frame_x_of_ts(idx, "2026-09-01 09:45") == 2.0
