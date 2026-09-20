"""Round 13 (Viva 09-21) — the live candle is a NORMAL candle, and every
timeframe stays alive between its candle closes.

His report, verbatim:

* «این رو درست کن با خط چین نمی‌خوام» · «خط چین کندل لایو اصلا نه دیده میشه برای
  تصمیم گیری خوب نیست همون شکل کندل باید عادی باشه» → the forming candle is
  appended to the tape and painted like every other candle; no dashed ghost.
* «آیا در تایم اسکن یا مانیتور کردن ۳ دقیقه … ۱: در چارت یک ساعته تغییرات روی کندل
  لایو تایم‌فریم‌های بالاتر اعمال میشه یا ۲: کندل یک‌ساعته و ۴ ساعته و روزانه هر
  یک‌ساعته و ۴ ساعت و یک روز یکبار بروز میشه؟؟ اگر جواب گزینه ۲ هست .. کاملا اشتباهه»
  → the charted live candle moves with the market (the render cache carries the
  live price), and the chain's liveness no longer waits for a 4-minute kline
  window once per candle.
* «من هنوز سیگنال روزانه ندیدم که تایید بشه … ۴ ساعته هم زیاد ندیدم» → a daily
  chain used to be looked at ~1% of the day; windows now span several monitor
  cycles.
"""

import datetime as _dt
import io
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot.messages_v7 as M
import main as MAIN
from test_v7 import make_candidate


# ── 1. the forming candle rides as one more NORMAL candle ───────────────────

def _frame(periods=60):
    ts = pd.date_range("2026-09-21", periods=periods, freq="15min")
    closes = [100 + i * 0.1 for i in range(periods)]
    return pd.DataFrame({
        "timestamp": ts, "open": [c - 0.05 for c in closes],
        "high": [c + 0.2 for c in closes], "low": [c - 0.2 for c in closes],
        "close": closes, "volume": [100] * periods,
    })


def test_the_live_bucket_is_appended_as_a_plain_row(monkeypatch):
    cand = make_candidate()
    cand.trigger_timeframe = "15m"
    base = _frame()
    live_ts = pd.Timestamp(base["timestamp"].iloc[-1]) + pd.Timedelta(minutes=15)
    monkeypatch.setattr(M, "_live_candle", lambda c, df: {
        "timestamp": live_ts, "open": 106.0, "high": 107.5, "low": 105.5,
        "close": 107.0, "volume": 42.0})
    frame, row = M._frame_with_live_candle(base, cand)
    assert len(frame) == len(base) + 1
    assert pd.Timestamp(frame["timestamp"].iloc[-1]) == live_ts
    assert float(frame["close"].iloc[-1]) == 107.0
    assert row and row["volume"] == 42.0
    # the tape below is untouched — the analysis candle is still the closed one
    assert float(frame["close"].iloc[-2]) == float(base["close"].iloc[-1])


def test_no_dashed_ghost_and_no_forming_label_any_more():
    src = io.open("bot/messages_v7.py", encoding="utf-8").read()
    assert "FORMING" not in src.split("def generate_chart")[1].split("def ")[0]
    assert "_ghost" not in src
    assert "_frame_with_live_candle" in src


def test_a_render_includes_the_live_candle(monkeypatch):
    cand = make_candidate("CONFIRMED", 8)
    cand.trigger_timeframe = "15m"
    base = _frame(120)
    live_ts = pd.Timestamp(base["timestamp"].iloc[-1]) + pd.Timedelta(minutes=15)
    monkeypatch.setattr(M, "_live_candle", lambda c, df: {
        "timestamp": live_ts, "open": 113.0, "high": 114.0, "low": 112.5,
        "close": 113.5, "volume": 10.0})
    image = M.generate_chart(base, cand, confirmed=False)
    assert image is not None and image[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_render_cache_follows_the_live_price(monkeypatch):
    cand = make_candidate("EDUCATIONAL", 6)
    cand.trigger_timeframe = "15m"
    base = _frame()
    live_ts = pd.Timestamp(base["timestamp"].iloc[-1]) + pd.Timedelta(minutes=15)
    monkeypatch.setattr(M, "_live_candle", lambda c, df: {
        "timestamp": live_ts, "open": 106.0, "high": 107.5, "low": 105.5,
        "close": 107.0, "volume": 1.0})
    frame_a, _ = M._frame_with_live_candle(base, cand)
    key_a = M._chart_cache_key(frame_a, cand, False)
    monkeypatch.setattr(M, "_live_candle", lambda c, df: {
        "timestamp": live_ts, "open": 106.0, "high": 108.9, "low": 105.5,
        "close": 108.4, "volume": 9.0})
    frame_b, _ = M._frame_with_live_candle(base, cand)
    key_b = M._chart_cache_key(frame_b, cand, False)
    # same bucket, moved price → a NEW render; without the price in the key the
    # old image (up to a whole candle old) would have been re-posted for hours
    assert key_a != key_b
    assert key_a[:5] == key_b[:5]


# ── 2. every timeframe is looked at long enough to catch its candle ─────────

class _Clock:
    def __init__(self, when):
        self._when = when

    def now(self, tz=None):
        return self._when if tz else self._when.replace(tzinfo=None)


def _window_at(monkeypatch, when, tf):
    monkeypatch.setattr(MAIN, "datetime", _Clock(when))
    return MAIN._tf_fetch_window(tf)


def test_a_daily_candle_close_is_never_missed_again(monkeypatch):
    day = _dt.date(2026, 9, 21)
    assert _window_at(monkeypatch, _dt.datetime(day.year, day.month, day.day, 0, 5, tzinfo=_dt.timezone.utc), "1d")
    assert _window_at(monkeypatch, _dt.datetime(day.year, day.month, day.day, 0, 40, tzinfo=_dt.timezone.utc), "1d")
    assert not _window_at(monkeypatch, _dt.datetime(day.year, day.month, day.day, 3, 0, tzinfo=_dt.timezone.utc), "1d")


def test_four_hour_and_hourly_windows_span_several_cycles(monkeypatch):
    day = _dt.date(2026, 9, 21)
    four = _dt.datetime(day.year, day.month, day.day, 4, 15, tzinfo=_dt.timezone.utc)
    assert _window_at(monkeypatch, four, "4h")          # was False: 4-minute window
    assert not _window_at(monkeypatch, _dt.datetime(day.year, day.month, day.day, 5, 0, tzinfo=_dt.timezone.utc), "4h")
    one = _dt.datetime(day.year, day.month, day.day, 9, 9, tzinfo=_dt.timezone.utc)
    assert _window_at(monkeypatch, one, "1h")           # was False before round 13
    assert not _window_at(monkeypatch, _dt.datetime(day.year, day.month, day.day, 9, 30, tzinfo=_dt.timezone.utc), "1h")
    quarter = _dt.datetime(day.year, day.month, day.day, 9, 17, tzinfo=_dt.timezone.utc)
    assert _window_at(monkeypatch, quarter, "15m")
    assert not _window_at(monkeypatch, _dt.datetime(day.year, day.month, day.day, 9, 21, tzinfo=_dt.timezone.utc), "15m")


# ── 3. a chain without a frame is still alive ──────────────────────────────

def test_the_monitor_no_longer_drops_chains_between_windows():
    src = io.open("main.py", encoding="utf-8").read()
    assert "if not market_data and not publication_in_progress" not in src
    assert "prices = _live_price_map()" in src
    assert 'prices.get(str(candidate.symbol or "").upper())' in src
    assert "have_frames = market_data is not None" in src


def test_the_live_price_map_is_fail_soft(monkeypatch):
    MAIN._PRICE_MAP = {}
    MAIN._PRICE_MAP_AT = 0.0

    def _boom(*_a, **_k):
        raise RuntimeError("venue down")

    import data.ourbit as OB
    monkeypatch.setattr(OB, "get_ourbit_tickers", _boom)
    import data.fetcher as F
    monkeypatch.setattr(F, "get_tickers", _boom)
    assert MAIN._live_price_map() == {}


def test_a_confirmation_on_an_old_candle_is_not_tradeable():
    cand = make_candidate()
    cand.trigger_timeframe = "1d"
    cand.metadata["confirm_tf"] = "4h"
    now = _dt.datetime.now(_dt.timezone.utc)
    fresh = pd.DataFrame({"timestamp": [pd.Timestamp(now - _dt.timedelta(minutes=5))]})
    old = pd.DataFrame({"timestamp": [pd.Timestamp(now - _dt.timedelta(hours=9))]})
    assert MAIN._confirmation_stale_minutes(cand, fresh) is None
    assert MAIN._confirmation_stale_minutes(cand, old) >= 500
    # the confirming bar named by the pattern lane wins over "newest closed bar"
    cand.metadata["fast_break_bar"] = str(now - _dt.timedelta(hours=10))
    assert MAIN._confirmation_stale_minutes(cand, fresh) >= 590


# ── 4. the analysis candle set still speaks only closed candles ────────────

def test_analysis_still_uses_closed_candles_only():
    src = io.open("data/fetcher.py", encoding="utf-8").read()
    assert "def get_klines(" in src and "closed_only: bool = True" in src
    setup_src = io.open("analysis/setups_v7.py", encoding="utf-8").read()
    assert "closed_only=False" not in setup_src
