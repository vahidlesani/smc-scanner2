"""Viva 10-08 CryptoCove/spot/zoom/cost laws — lock tests.

His 16-mehr complaint + the 17 CryptoCove refs, operationalised:
TP 40/50/60 + 10% runner, spike-only deep scroll, full-frame ladder,
anchor-timestamp sig identity, flag-no-confirm, DT/DB rules, TOHOM
doctrine gates (touch/slope/shock/displacement), spot linewidth restore.
"""
import numpy as np
import pandas as pd


def _frame(n, start=100.0, step=0.1, end_ts=None):
    ts = pd.date_range(end=end_ts or pd.Timestamp.utcnow().tz_localize(None),
                       periods=n, freq="4h")
    px = start + np.arange(n) * step
    return pd.DataFrame({"timestamp": ts, "open": px - 0.1, "high": px + 0.2,
                         "low": px - 0.2, "close": px,
                         "volume": np.full(n, 1000.0),
                         "turnover": np.full(n, 5e4)})


# ── 1. TP law: 40/50/60 of box path + runner at path end ────────────────
def test_spot_tp_law_40_50_60_plus_runner():
    from analysis.spot_engine import spot_risk_levels, SPOT_WEIGHTS
    r = spot_risk_levels(100.0, 101.0, [99.0], 1.0, 10.0, 98.0,
                         df_highs=[103.0, 107.0, 109.5])
    assert r["targets"] == [104.0, 105.0, 106.0]
    assert r["runner"] == 110.0
    assert tuple(SPOT_WEIGHTS) == (30.0, 30.0, 30.0, 10.0)


# ── 2. spot linewidth restore (Oct-7 2.8 fattening is gone) ──────────────
def test_spot_linewidth_restore_lock():
    src = open("analysis/spot_pattern_engine.py").read()
    assert "linewidth=2.8" not in src
    assert "linewidth=2.0" in src
    assert "s=48" not in src


# ── 3. ladder fits the FULL deep frame (no 180 cap on majors) ───────────
def test_render_ladder_full_frame_lock():
    src = open("analysis/render_kit.py").read()
    assert "if len(df) > 180:" in src and "append(len(df))" in src


# ── 4. sig = frozen anchor timestamps (stable across a window shift) ─────
def test_spot_sig_anchor_timestamp_identity(monkeypatch):
    from analysis.spot_engine import scan_spot_alerts
    now = pd.Timestamp.utcnow().tz_localize(None)
    d1 = _frame(300, end_ts=now.floor("4h"))
    d2 = _frame(300, end_ts=now.floor("4h") - pd.Timedelta(hours=4))

    def _fake(df, direction="", log_axis=None):
        n = len(df) - 1
        return [{"type": "TRENDLINE", "shape": "single",
                 "bias": "NEUTRAL", "break_direction": "UP",
                 "lines": [{"side": "HIGH", "slope": 0.0,
                            "intercept": float(df["close"].iloc[-1]) + 0.05,
                            "x0": 30, "x1": n,
                            "points": [{"ts": "2026-10-01 00:00", "price": 1.0},
                                       {"ts": "2026-10-02 00:00", "price": 1.0}]}]}]
    monkeypatch.setattr("analysis.render_kit.detect_patterns", _fake)
    a = scan_spot_alerts("TESTUSDT", {"4h": d1})
    b = scan_spot_alerts("TESTUSDT", {"4h": d2})
    assert a and b
    # timestamp identity (not bare window ints) …
    assert "-" in a[0]["sig"] and ":" in a[0]["sig"]
    # … frozen across the one-candle window shift
    assert a[0]["sig"].split("|")[3:] == b[0]["sig"].split("|")[3:]


# ── 5. deep scroll ONLY when a spike drags the axis ──────────────────────
def test_deep_scroll_is_spike_only():
    from bot.messages_v7 import _smart_y_window
    atr = 1.0
    clean = _smart_y_window(45.0, 55.0, atr, recent_lo=48.0, recent_hi=52.0,
                            bars=300)          # deep but CLEAN
    spiky = _smart_y_window(0.0, 100.0, atr, recent_lo=48.0, recent_hi=52.0,
                            bars=300)          # deep + spike
    assert clean is not None and spiky is not None
    # Viva 10-09 LIVE-FOCUS (SUPERSEDES r40's absolute hard fill — his
    # «y-span too tall», fossils clip): the clean frame keeps the live block
    # plus tape within reach (wick-tips may shave; the 16-mehr spirit — never
    # butcher a clean chart — survives); the spike frame scrolls hard onto
    # the live block, which is never cut.
    assert clean[0] < 48.0 and clean[1] > 52.0
    assert (clean[1] - clean[0]) < 2.0 * (55.0 - 45.0)
    assert spiky[0] > 0.0 or spiky[1] < 100.0        # spike frame scrolls
    assert spiky[0] <= 48.0 and spiky[1] >= 52.0     # live never cut


# ── 6. flags/pennants never confirm ──────────────────────────────────────
def test_flag_pennant_never_confirm():
    from analysis.spot_engine import _spot_bull_shapes
    for kind in ("FLAG_BULL", "FLAG_BEAR", "PENNANT_BULL", "PENNANT_BEAR"):
        pat = {"type": kind, "shape": "single",
               "lines": [{"side": "HIGH", "slope": 0.0, "intercept": 100.0,
                          "x0": 10, "x1": 60}]}
        assert list(_spot_bull_shapes([pat], 101.0, 60.0)) == [], kind


# ── 7. double top/bottom rules: apart + level + deep ─────────────────────
def test_double_top_rules_reject_ripples():
    from analysis.patterns16 import detect_pivot_patterns
    n = 90
    ts = pd.date_range(end=pd.Timestamp.utcnow().tz_localize(None),
                       periods=n, freq="1d")
    # adjacent ripples 3 bars apart, shallow trough → NOT a double top
    px = np.full(n, 100.0)
    px[40], px[43] = 101.0, 101.0
    px[41:43] = 100.6
    df = pd.DataFrame({"timestamp": ts, "open": px, "high": px + 0.1,
                       "low": px - 0.1, "close": px,
                       "volume": np.full(n, 1000.0)})
    assert "DOUBLE_TOP" not in [p["type"] for p in detect_pivot_patterns(df, 1.0)]


def test_double_top_rules_accept_real_twin_tops():
    from analysis.patterns16 import detect_pivot_patterns
    n = 120
    ts = pd.date_range(end=pd.Timestamp.utcnow().tz_localize(None),
                       periods=n, freq="1d")
    px = np.full(n, 100.0)
    px[50], px[70] = 105.0, 105.0          # 20 bars apart, level
    px[51:58] = np.linspace(104.0, 101.0, 7)
    px[58:63] = 101.0                       # deep trough between
    px[63:70] = np.linspace(101.0, 104.0, 7)
    df = pd.DataFrame({"timestamp": ts, "open": px, "high": px + 0.1,
                       "low": px - 0.1, "close": px,
                       "volume": np.full(n, 1000.0)})
    assert "DOUBLE_TOP" in [p["type"] for p in detect_pivot_patterns(df, 1.0)]


# ── 8. TOHOM doctrine: shock + displacement gates ────────────────────────
def test_spot_tohom_blocks_without_shock(monkeypatch):
    import datetime as _dt
    from analysis.spot_engine import scan_spot_tohom_confirms
    _FROZEN = _dt.datetime(2026, 10, 3, 3, 30, tzinfo=_dt.timezone.utc)

    class _FrozenDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _FROZEN if tz is not None else _FROZEN.replace(tzinfo=None)
    monkeypatch.setattr("analysis.spot_engine.datetime", _FrozenDT)
    now = pd.Timestamp(_FROZEN.replace(tzinfo=None))
    n4 = 90
    ts4 = pd.date_range(end=now.floor("4h"), periods=n4, freq="4h")
    px4 = np.linspace(100.0, 106.0, n4)
    d4 = pd.DataFrame({"timestamp": ts4, "open": px4 - 0.2, "high": px4 + 0.4,
                       "low": px4 - 0.5, "close": px4,
                       "volume": np.full(n4, 1000.0),
                       "turnover": np.full(n4, 5e4)})
    n15 = 60
    ts15 = pd.date_range(end=now.floor("15min") - pd.Timedelta(minutes=15),
                         periods=n15, freq="15min")
    px15 = np.linspace(102.0, 104.2, n15)
    o15, c15 = px15 - 0.1, px15 + 0.1
    for k, (oo, cc) in enumerate(((104.3, 104.6), (104.5, 105.2), (104.9, 105.7))):
        i = n15 - 3 + k
        o15[i], c15[i] = oo, cc
    # directional streak but NO volume shock (flat 1000) → blocked
    d15 = pd.DataFrame({"timestamp": ts15, "open": o15,
                        "high": c15 + 0.12, "low": o15 - 0.12, "close": c15,
                        "volume": np.full(n15, 1000.0),
                        "turnover": np.full(n15, 5e4)})

    def _fake(df, direction="", log_axis=None):
        nn = len(df) - 1
        return [{"type": "TRENDLINE", "shape": "single", "bias": "NEUTRAL",
                 "break_direction": "UP",
                 "lines": [{"side": "HIGH", "slope": 0.0, "intercept": 105.0,
                            "x0": 30, "x1": nn,
                            "points": [{"ts": "t0", "price": 105.0},
                                       {"ts": "t1", "price": 105.0}]}]}]
    monkeypatch.setattr("analysis.render_kit.detect_patterns", _fake)
    frames = {"4h": d4, "15m": d15, "1h": d15.tail(20).copy()}
    assert scan_spot_tohom_confirms("TESTUSDT", frames, "4h") == []


# ── 9. spot card carries the 10% runner ──────────────────────────────────
def test_spot_card_runner_row():
    from analysis.models import SignalCandidate
    from bot.messages_v7 import _tf_channel_text
    cand = SignalCandidate(
        signal_id="viva-spot-TEST-4h-x", symbol="TESTUSDT", style="SWING",
        setup_code="SPOTBREAK", setup_name="Spot test", strategy_fa="تست",
        direction="LONG", score=8, status="CONFIRMED",
        entry_zone_bottom=99.0, entry_zone_top=100.0, planned_entry=100.0,
        sl=95.0, tp1=104.0, tp2=106.0, rr_tp1=0.0, rr_tp2=0.0, bias="BULL",
        trigger_timeframe="4h",
        metadata={"market": "SPOT",
                  "target_ladder": {"targets": [104.0, 105.0, 106.0],
                                    "weights": [30.0, 30.0, 30.0, 10.0],
                                    "runner": 110.0, "path_pct": 10.0}})
    text = _tf_channel_text(cand, "")
    assert "هولد" in text and "10%" in text and "110" in text


# ── 10. ladder-refresh lane exists ───────────────────────────────────────
def test_ladder_refresh_lane_exists():
    import main
    assert callable(getattr(main, "_spot_mint_pins", None))
    assert callable(getattr(main, "_spot_ladder_refresh", None))
    src = open("main.py").read()
    assert "SPOT_LADDER_MINUTES" in src
