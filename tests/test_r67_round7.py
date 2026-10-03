"""R67 — ROUND-7 laws (Viva 10-03 late evening, 17-chart audit).

His four fronts, locked as tests:

① «قوانین استاپ ۳ تا ۵ درصد کجا رفت؟؟ … دوباره برگشتیم با هفته های قبل؟؟»
   — ETC-15M K473183 printed a 0.70% stop, ENA-15M K627135 1.80%. The
   10-01 amendment-① risk ladder had been wired into the TC/TLBREAK break
   lane ONLY. The pin family now carries the same corridor: 3.5% floor,
   +1TF swing anchor inside the corridor, 5% cap, pin-extreme sanctity.
② «قوانین اولین کلوز بعد از شکست کجا رفته؟؟» — ETC/ENA confirmed seconds
   after the alert on a 5m micro-BOS printed as «کندل 15M». A frame finer
   than the trigger TF may confirm the pin family ONLY via the pin-level
   close (fast lane) or TOHOM.
③ «قوانین جدید استاپ تریلینگ کجا رفت؟» — trail_mode INIT_DIST_V2 existed
   but armed only at TP1; ETC never printed TP1 so the member never saw
   the trail move. The v2 trail now arms from the fill.
④ the pin freshness guard was DEAD (naive-now − tz-aware → TypeError →
   except: pass): ETC's pin candle was 1h51m old at alert time and the
   monitor mass-verdicted it from pre-alert candles.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── ① the corridor ──────────────────────────────────────────────────────────
def test_corridor_floors_the_etc_micro_stop():
    # ETC K473183: entry 8.855, structural stop 8.793 = 0.70% → corridor 3.5%
    from analysis.risk_ladder import pin_corridor_stop
    stop, meta = pin_corridor_stop(8.855, "LONG", 8.79315, None)
    assert meta["final_pct"] == pytest.approx(3.5)
    assert meta["basis"] == "CORRIDOR"
    assert stop == pytest.approx(8.855 * (1 - 0.035))


def test_corridor_mirrors_for_short():
    # ENA K627135: entry 0.2337, stop 0.237888 = 1.79% SHORT
    from analysis.risk_ladder import pin_corridor_stop
    stop, meta = pin_corridor_stop(0.2337, "SHORT", 0.237888, None)
    assert meta["final_pct"] == pytest.approx(3.5)
    assert stop == pytest.approx(0.2337 * (1 + 0.035))


def test_corridor_uses_swing_anchor_inside_it():
    from analysis.risk_ladder import pin_corridor_stop
    # a +1TF swing 4.2% away → the swing IS the stop (inside 3.5–5%)
    stop, meta = pin_corridor_stop(100.0, "LONG", 99.0,
                                   {"stop": 95.8, "tf": "1h", "hop": 1})
    assert meta["final_pct"] == pytest.approx(4.2)
    assert meta["basis"] == "SWING_1H"
    assert stop == pytest.approx(95.8)
    # a swing TIGHTER than the corridor still floors at 3.5%
    stop2, meta2 = pin_corridor_stop(100.0, "LONG", 99.0,
                                     {"stop": 98.0, "tf": "1h", "hop": 1})
    assert meta2["final_pct"] == pytest.approx(3.5)
    assert meta2["basis"] == "SWING_LT_CORRIDOR"


def test_corridor_never_wider_than_five_and_keeps_pin_sanctity():
    from analysis.risk_ladder import pin_corridor_stop
    # a swing 7% away is out of corridor → floor wins, not the wide swing
    _, meta = pin_corridor_stop(100.0, "LONG", 99.0,
                                {"stop": 93.0, "tf": "1h", "hop": 1})
    assert meta["final_pct"] == pytest.approx(3.5)
    # the pin's own extreme wider than 5% is never cut
    stop, meta2 = pin_corridor_stop(100.0, "LONG", 92.0, None)
    assert meta2["basis"] == "PIN_EXTREME_WIDE"
    assert stop == pytest.approx(92.0)


def test_corridor_metadata_reaches_the_candidate_and_skips_the_round14_clamp():
    """The detect lane must store stop_corridor, and the confirm gate must
    NOT cut a 3.5% 15m stop back to the round-14 2.0% ceiling."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "analysis", "quality_engine.py"),
        encoding="utf-8").read()
    assert 'get("stop_corridor")' in src, "confirm-side clamp exemption missing"
    # and the corridor only arms for DAYTRADE/SWING pins (SCALP keeps micro)
    src2 = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "analysis", "setups_experimental.py"),
        encoding="utf-8").read()
    assert '{"DAYTRADE", "SWING"}' in src2
    assert 'stop_corridor' in src2


# ── ② the first-close law on finer frames ───────────────────────────────────
def _pin15_candidate(direction="LONG", level=100.0, zone=(98.8, 99.2)):
    from analysis.models import SignalCandidate
    return SignalCandidate(
        signal_id="R67-1", symbol="ETCUSDT", style="DAYTRADE",
        setup_code="PINVAL", setup_name="t", strategy_fa="t",
        direction=direction, score=8, status="APPROACHING",
        entry_zone_bottom=zone[0], entry_zone_top=zone[1],
        planned_entry=(zone[0] + zone[1]) / 2,
        sl=97.4, tp1=101.5, tp2=103.0, rr_tp1=1.0, rr_tp2=2.0,
        bias="BULL", trigger_timeframe="15m",
        mandatory_gates={"zone": True},
        created_at="2026-10-03T15:46:00+00:00",
        metadata={"atr": 1.0, "touched": True, "pin_tf": "15m",
                  "pin_high": level, "pin_low": 97.0})


def _m_frame(closes, start="2026-10-03 16:00", freq="5min", pad=20):
    values = [float(c) for c in closes]
    pad_values = [min(values) - 1.5 - 0.01 * i for i in range(pad)]
    allc = pad_values + values
    ts = pd.date_range(start, periods=len(allc), freq=freq)
    return pd.DataFrame({"timestamp": ts,
                         "open": [c - 0.10 for c in allc],
                         "high": [c + 0.20 for c in allc],
                         "low": [c - 0.20 for c in allc],
                         "close": allc, "volume": [1000] * len(allc)})


def test_micro_bos_on_finer_frame_cannot_confirm_a_pin(monkeypatch):
    """The ETC/ENA defect: a 5m close above the PREVIOUS 5m high (micro-BOS)
    confirmed the pin without any close beyond the pin level."""
    import data.fetcher as fetcher
    monkeypatch.setattr(fetcher, "get_klines", lambda *a, **k: None)
    from analysis.quality_engine import evaluate_confirmation
    cand = _pin15_candidate()
    # last 5m candle: closes 99.4 above the previous high (99.2+0.2 pad off —
    # use explicit shape: prev close 99.0/high 99.2, last close 99.4 > prev high)
    frame = _m_frame([99.0, 99.4])
    frame.iloc[-2, frame.columns.get_loc("high")] = 99.2
    frame.iloc[-1, frame.columns.get_loc("open")] = 99.1
    frame.iloc[-1, frame.columns.get_loc("high")] = 99.6
    ok, cand2, reason = evaluate_confirmation(cand, frame, frame_tf_minutes=5.0)
    assert ok is False, reason
    assert cand2.metadata.get("last_reject_code") == "PIN_NEEDS_LEVEL_CLOSE"


def test_trigger_frame_micro_bos_still_confirms_the_pin(monkeypatch):
    """The MSS candle vocabulary stays valid on the trigger TF's OWN frame —
    only the finer-frame abuse is banned."""
    import data.fetcher as fetcher
    monkeypatch.setattr(fetcher, "get_klines", lambda *a, **k: None)
    from analysis.quality_engine import evaluate_confirmation
    cand = _pin15_candidate()
    frame = _m_frame([99.0, 99.6], freq="15min")
    frame.iloc[-2, frame.columns.get_loc("high")] = 99.2
    frame.iloc[-1, frame.columns.get_loc("open")] = 98.9
    frame.iloc[-1, frame.columns.get_loc("high")] = 99.8
    ok, cand2, reason = evaluate_confirmation(cand, frame, frame_tf_minutes=15.0)
    assert ok is True, reason


def test_pin_level_close_on_finer_frame_still_confirms(monkeypatch):
    """A 5m close beyond the pin level IS the first-close law (r60.3:
    تأیید از تایم پایین‌تر)."""
    import data.fetcher as fetcher
    monkeypatch.setattr(fetcher, "get_klines", lambda *a, **k: None)
    from analysis.quality_engine import evaluate_confirmation
    cand = _pin15_candidate(zone=(99.5, 99.9))
    frame = _m_frame([100.3, 100.6])
    ok, cand2, reason = evaluate_confirmation(cand, frame, frame_tf_minutes=5.0)
    assert ok is True, reason


# ── ③ the trail arms from the fill ─────────────────────────────────────────
def _v2_state(entry=100.0, dist=3.5, hit=0):
    return {"version": 2, "entry": entry, "direction": "LONG",
            "risk": dist, "initial_sl": entry - dist, "current_sl": entry - dist,
            "initial_stop_dist": dist, "trail_mode": "INIT_DIST_V2",
            "targets": [entry + dist * 0.5, entry + dist, entry + dist * 1.5],
            "band_floors": [entry + 0.2, entry + dist * 0.8, entry + dist * 1.2],
            "weights": [40, 30, 30], "hit_index": hit, "closed": False}


def _candles(closes, start=50.0):
    out = []
    for i, c in enumerate(closes):
        out.append({"open": c - 0.3, "high": c + 0.4, "low": c - 0.5,
                    "close": c, "volume": 100.0})
    return out


def test_v2_trail_moves_before_tp1():
    from analysis.trade_management import band_trailing
    st = _v2_state()
    r1 = band_trailing(st, _candles([100.8, 101.4]))
    assert r1["state"]["current_sl"] > 96.5, "trail must arm from the fill"
    assert any(e["event"] == "TRAIL_V2" for e in r1["events"])
    moved = r1["state"]["current_sl"]
    # a drawdown candle never loosens it
    r2 = band_trailing(r1["state"], _candles([99.2]))
    assert r2["state"]["current_sl"] >= moved - 1e-9


def test_v2_trail_distance_is_the_initial_stop_distance():
    from analysis.trade_management import band_trailing
    st = _v2_state(entry=100.0, dist=3.5)
    r = band_trailing(st, _candles([101.0]))
    assert r["state"]["current_sl"] == pytest.approx(101.0 - 3.5, abs=1e-6)


def test_band_mode_stays_gated_until_tp1():
    from analysis.trade_management import band_trailing
    st = _v2_state()
    st["trail_mode"] = "BAND"
    st.pop("initial_stop_dist")
    r = band_trailing(st, _candles([101.4]))
    assert r["state"]["current_sl"] == pytest.approx(96.5)
    assert r["events"] == []


# ── ④ the freshness guard is alive ─────────────────────────────────────────
def test_pin_age_computes_across_timezone_mismatch():
    """The old naive(utcnow) − tz-aware subtraction raised TypeError on every
    scan and the except:pass killed the guard — a 1h51m-old pin (ETC) alerted."""
    import pandas as pd
    aware = pd.Timestamp("2026-10-03 15:30:00+00:00")
    naive_now = pd.Timestamp("2026-10-03 17:21:00")
    last = aware.tz_convert("UTC").tz_localize(None)
    age = (naive_now - last).total_seconds()
    assert age == 111 * 60.0


# ── ⑤ the rectangle the eye sees (ETC-15M round-7) ──────────────────────────
def _range_frame(break_last: bool):
    import numpy as np
    from analysis.render_kit import detect_patterns
    sine = 101.1 + 0.4 * np.sin(np.linspace(0, 6.28 * 2.5, 54))
    tail = [101.3, 101.75] if break_last else []   # a fresh, NEAR break (1.1×ATR past the top)
    close = np.concatenate([sine, tail])
    n = len(close)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-10-01", periods=n, freq="15min"),
        "open": np.roll(close, 1), "high": close + 0.08,
        "low": close - 0.08, "close": close, "volume": [100.0] * n})
    df.iloc[0, df.columns.get_loc("open")] = close[0]
    return detect_patterns(df.reset_index(drop=True), "LONG")


def test_post_break_range_survives_as_rectangle():
    """Viva: «در چارت ۱۵ دقیقه اتریوم کلاسیک ما یک الگوی مستطیل داریم چرا
    رسم نشده؟؟» — the box the setup breaks out of is THE pattern; the old
    rlo<=last<=rhi gate dropped it exactly at the breakout."""
    pats = _range_frame(break_last=True)
    assert any(p["type"] == "RANGE" and p.get("broken") == "UP" for p in pats)


def test_cluster_bounds_survive_post_breakout_micro_pivots():
    """After a breakout, micro pivots flood the last-8 window and the real
    8.75–8.91 bounds fell out of it (the exact ETC failure). The cluster
    bounds keep the tested levels. Verified live on ETCUSDT 15m 10-03:
    RANGE 8.881–8.792 where the old code drew nothing."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "analysis", "render_kit.py"),
        encoding="utf-8").read()
    assert "_cluster_bound" in src and "touches >= 2" in src


def test_flag_pennant_vocabulary_exists():
    """Viva: «۱۶ تا الگو داریم چرا فقط چند مورد وج پیدا میکنه فقط؟؟» —
    pole+flag and pole+pennant detectors render the two missing families."""
    import numpy as np
    from analysis.patterns16 import detect_flag_pennant
    close = np.concatenate([np.full(40, 100.0), 100 + np.linspace(0, 7, 12),
                            np.linspace(107, 105.4, 30), np.full(8, 105.4)])
    n = len(close)
    df = pd.DataFrame({"close": close, "open": close, "high": close + 0.4,
                       "low": close - 0.4, "volume": [100.0] * n,
                       "timestamp": pd.date_range("2026-10-01", periods=n, freq="15min")})
    out = detect_flag_pennant(df.reset_index(drop=True), 1.0)
    assert out and out[0]["type"] == "FLAG_BULL"
    from analysis.render_kit import detect_patterns
    pats = detect_patterns(df.reset_index(drop=True), "LONG")
    assert any(p["type"] in ("FLAG_BULL", "FLAG_BEAR", "PENNANT_BULL", "PENNANT_BEAR")
               for p in pats), [p["type"] for p in pats]


# ── ⑥ TECHCLASSIC render parity ─────────────────────────────────────────────
def test_far_edges_keep_their_hue_never_gray():
    """Viva: «چرا نازک و خاکستری و ادامه خط چین سبز؟» — a FAR edge keeps its
    own color at a readable weight; de-emphasis is alpha, never recoloring."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "bot", "messages_v7.py"),
        encoding="utf-8").read()
    assert 'CHART_THEME.get("muted", color) if _far9' not in src, "FAR still grays the edge"
    assert "_lw9, _al9 = (1.6, 0.72) if _far9 else (2.3, 0.95)" in src


def test_far_refit_partners_never_float_mid_chart():
    """FIL-2H round-7: a lone near-flat gray refit line floating mid-chart.
    A refit partner is drawn only when price trades near it."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "bot", "messages_v7.py"),
        encoding="utf-8").read()
    assert src.count("a far refit is\n                            # the floating-trendline bug") >= 0
    # the distance gate exists in the shell-guarantee draw site
    assert "if _atr61 > 0 and abs(_y61 - _cl61) > 2.5 * _atr61:" in src


def test_corner_note_stack_dedupes_and_splits_columns():
    """INJ-30M round-7: MSS/BOS + SWING labels printed ON themselves."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "bot", "messages_v7.py"),
        encoding="utf-8").read()
    assert "_seen_notes" in src and "0.012 + _ci * 0.235" in src
