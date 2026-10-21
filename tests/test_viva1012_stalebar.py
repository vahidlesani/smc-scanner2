"""10-12 STALE-BAR PACK — VVV·T124937 replay + the 7-fix laws.

The incident: VVV/USDT 30m chain confirmed at 22:00 Tehran with entry
23.551 while live printed 24.819 (+5.38%). Entry IS the newest close of the
frame passed to evaluate_confirmation (row = closed_df.iloc[-1] -> close ->
executable_entry -> planned_entry), so the confirming bar (~19:30-19:35,
its 5.38% run proven by the CoinGecko tape) reached the ladder through one
of two branches — BOTH now closed:
  (i)  a STALE confirm frame (F2 drops it) with a mixed-TF guard threshold
       2*max(confirm=15, break=240)=480min that scored 150min as «fresh»
       (F1 measures in confirm-TF candles only: 2*15=30min);
  (ii) a legacy 4H confirm frame whose newest CLOSED bar is honestly 150min
       old at 22:00 but whose TRADE already ran away (F3 vetoes at evaluate,
       F4 vetoes at send).
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest


# ── T1: the frame-freshness law (F2 core) ────────────────────────────────
def test_stale_frame_is_dropped_vvv_replay():
    from analysis.confirm_r62 import frame_is_fresh
    # VVV 22:00 Tehran = 18:30Z; confirming bar closed ~19:30 Tehran = 16:00Z.
    now = datetime(2026, 10, 11, 18, 30, tzinfo=timezone.utc)
    assert frame_is_fresh("2026-10-11 16:00:00", 30, 2.0, now=now) is False
    # ...while a genuinely fresh 30m frame (newest bar 10min old) passes.
    assert frame_is_fresh("2026-10-11 18:20:00", 30, 2.0, now=now) is True
    # Fail-closed: an unreadable newest bar is also stale.
    assert frame_is_fresh("garbage!!!", 30, 2.0, now=now) is False
    assert frame_is_fresh(None, 30, 2.0, now=now) is False


# ── T2: the guard now speaks confirm-TF only (F1) ────────────────────────
def test_stale_guard_rejects_mixed_tf_threshold_vvv_replay():
    import main as _main
    from types import SimpleNamespace
    now = datetime.now(timezone.utc)
    # The production shape: confirm ran on the 15m ladder (30m trigger) but
    # the stamp carries the 4H break-detection TF — old law 2*max(15,240).
    stamp = (now - timedelta(minutes=390)).strftime("%Y-%m-%d %H:%M:%S")
    cand = SimpleNamespace(trigger_timeframe="30m", metadata={
        "confirm_tf": "15m", "fast_break_bar": stamp,
        "fast_break_tf_min": 240.0})
    age = _main._confirmation_stale_minutes(cand, None)
    assert age is not None and age >= 140, \
        f"150min-old bar on the 15m ladder must be STALE, got {age}"
    # ...while a 10min-old bar on the same ladder stays fresh.
    fresh = SimpleNamespace(trigger_timeframe="30m", metadata={
        "confirm_tf": "15m",
        "fast_break_bar": (now - timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M:%S"),
        "fast_break_tf_min": 15.0})
    assert _main._confirmation_stale_minutes(fresh, None) is None


# ── T3: a present-but-unreadable stamp fails CLOSED (F5) ─────────────────
def test_broken_stamp_fails_closed():
    import main as _main
    from types import SimpleNamespace
    cand = SimpleNamespace(trigger_timeframe="30m", metadata={
        "confirm_tf": "15m", "fast_break_bar": "not-a-timestamp!!!",
        "fast_break_tf_min": 240.0})
    age = _main._confirmation_stale_minutes(cand, None)
    assert age == 10 ** 9
    assert cand.metadata.get("stale_stamp_broken") is True


# ── T4: the live-vs-entry sanity law (F3/F4 wiring logic) ────────────────
def test_live_entry_divergence_vetoes_vvv_numbers():
    from analysis.confirm_r62 import live_entry_diverged_pct
    from config import Settings
    pct = live_entry_diverged_pct(24.819, 23.551)
    assert pct == pytest.approx(5.38, abs=0.05)
    assert pct > Settings.liveclose_max_pct      # F3 evaluate veto (3.0%)
    assert pct > Settings.confirm_live_tol_pct   # F4 send veto (0.2%)
    # ENA's shape (entry == live) sails through both wires.
    assert live_entry_diverged_pct(0.4521, 0.4521) == pytest.approx(0.0)
    # Missing sides never veto (fail-open: nothing to judge).
    assert live_entry_diverged_pct(0.0, 23.5) is None
    assert live_entry_diverged_pct(24.8, 0.0) is None


def test_stale_pack_knobs_have_defaults():
    from config import Settings
    assert Settings.stale_confirm_bars == 2.0
    assert Settings.frame_max_age_mult == 2.0
    assert Settings.liveclose_max_pct == 3.0
    assert Settings.confirm_live_tol_pct == 0.2


# ── T5: a vetoed chain never wears CONFIRMED (F6 status-stuck) ───────────
def test_vetoed_chain_never_stamped_confirmed(monkeypatch):
    import data.fetcher as _fetcher
    from analysis.models import SignalCandidate
    from analysis.quality_engine import evaluate_confirmation
    import tests.test_trigger_patterns as _tp

    # A 200-bar parent-TF DOWNTREND for a LONG: counter-trend with no swing
    # break (close 99.66 never tops the prior highs) -> the 09-19 veto.
    n = 200
    closes = [102.0 - 0.012 * i for i in range(n)]
    parent = pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01", periods=n, freq="1h"),
        "open": closes, "high": [c + 0.30 for c in closes],
        "low": [c - 0.30 for c in closes], "close": closes,
        "volume": [100.0] * n})
    monkeypatch.setattr(_fetcher, "get_klines", lambda *a, **k: parent)

    cand = _tp._candidate()
    ok, cand, reason = evaluate_confirmation(cand, _tp._df20())
    assert not ok, "the 09-19 counter-trend veto must fire on a parent downtrend"
    assert "COUNTER_TREND" in str(cand.metadata.get("last_reject_code", ""))
    assert cand.status != "CONFIRMED"
    assert not cand.metadata.get("technical_confirmation_complete")


# ── T6: the HTF pill cites the real TF (F7) ──────────────────────────────
def test_htf_pill_stamp_follows_frame_tf():
    from analysis.models import SignalCandidate
    from analysis.render_kit import enrich_render

    def _cand():
        return SignalCandidate(
            signal_id="T-HTF", symbol="TESTUSDT", style="DAYTRADE",
            setup_code="TLBREAK", setup_name="t", strategy_fa="t",
            direction="LONG", score=8, status="APPROACHING",
            entry_zone_bottom=99.0, entry_zone_top=100.0, planned_entry=99.5,
            sl=98.0, tp1=101.5, tp2=103.0, rr_tp1=1.0, rr_tp2=2.0,
            bias="BULL", trigger_timeframe="15m",
            mandatory_gates={"zone": True}, metadata={},
            created_at="2026-10-01 09:45:00+00:00")

    def _frame(step_min, bars=70):
        import numpy as _np
        ts = pd.date_range("2026-10-01", periods=bars, freq=f"{step_min}min")
        walk = 100.0 + _np.cumsum(_np.random.RandomState(7).randn(bars) * 0.1)
        return pd.DataFrame({"timestamp": ts, "open": walk,
                             "high": walk + 0.15, "low": walk - 0.15,
                             "close": walk + 0.02,
                             "volume": [100.0] * bars})

    c1, trig = _cand(), _frame(15)
    enrich_render(c1, trig, htf_df=_frame(60))
    assert c1.metadata.get("render_htf_tf") == "1H", c1.metadata.get("render_htf_tf")
    c4 = _cand()
    enrich_render(c4, trig, htf_df=_frame(240))
    assert c4.metadata.get("render_htf_tf") == "4H", c4.metadata.get("render_htf_tf")
