"""Round-12 second report — «حدود ۴۰ دقیقه اختلاف … من دارم گذشته مارکت رو می‌بینم».

Two defects were real:

1. The entry alert never carried a clock. Detection time, publication time and the
   close of the source candle were invisible, so a delayed alert looked identical
   to a fresh one (his words: «تاخیر در زمان شناسایی و زمان انتشار و ارسال به
   تلگرام رو در هشدار مفصل نداشتیم»).
2. Alert charts are rendered from CLOSED candles only (no repaint by design), so on
   a 1h trigger the newest bar could be an hour old next to the venue's own chart
   that already shows the forming candle.

The fixes frozen here: the clock block (`_timing_lines`), the past-market guard
(`_stale_alert_verdict` → an alert older than two trigger candles is an analysis
note, never an entry), and the FORMING candle drawn by `_live_candle`.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot.messages_v7 as M  # noqa: E402


def _ts(dt):
    ts = pd.Timestamp(dt)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _candidate(tf="1h", close_ago_min=5, detected_ago_min=None, created=True):
    """A candidate whose source candle closed `close_ago_min` minutes ago."""
    from test_v7 import make_candidate

    cand = make_candidate()
    cand.trigger_timeframe = tf
    now = datetime.now(timezone.utc)
    close = now - timedelta(minutes=close_ago_min)
    cand.metadata["source_candle_close_utc"] = close.isoformat()
    cand.metadata["alert_stamped_at_utc"] = now.isoformat(timespec="seconds")
    if created:
        det = close + timedelta(minutes=(detected_ago_min or 1))
        cand.created_at = det.isoformat()
    return cand


def _frame(tf_minutes=60, bars=5, last_open_ago_min=None):
    now = datetime.now(timezone.utc)
    last_open = now - timedelta(minutes=(last_open_ago_min if last_open_ago_min is not None else tf_minutes))
    stamps = [last_open - timedelta(minutes=tf_minutes * (bars - 1 - i)) for i in range(bars)]
    return pd.DataFrame({
        "timestamp": [_ts(s) for s in stamps],
        "open": [1.0 + i * 0.01 for i in range(bars)],
        "high": [1.05 + i * 0.01 for i in range(bars)],
        "low": [0.95 + i * 0.01 for i in range(bars)],
        "close": [1.02 + i * 0.01 for i in range(bars)],
        "volume": [100.0] * bars,
    })


# ── the clock block ─────────────────────────────────────────────────────────

def test_stamp_source_candle_records_the_close_from_the_frame():
    cand = _candidate(tf="1h", close_ago_min=0)
    cand.metadata.pop("source_candle_close_utc", None)
    M._stamp_source_candle(cand, _frame(tf_minutes=60, last_open_ago_min=60))
    close = pd.Timestamp(cand.metadata["source_candle_close_utc"])
    assert close.tzinfo is not None
    # 1h candle that opened 60 minutes ago closes ~now
    assert abs((datetime.now(timezone.utc) - close.to_pydatetime()).total_seconds()) < 180


def test_timing_lines_state_candle_clock_detection_and_send():
    cand = _candidate(tf="1h", close_ago_min=39, detected_ago_min=39)
    text = "\n".join(M._timing_lines(cand))
    assert "کندل مبدا 1H" in text
    assert "شناسایی" in text and "ارسال به تلگرام" in text
    assert "فاصلهٔ بسته‌شدن کندل تا شناسایی" in text
    # 39 minutes late on a 1h trigger → the past-market warning must speak
    # r30 (Viva 09-26): update timing says NOW + elapsed-since-origin,
    # never «this message arrived late».
    assert "از کندلِ هشدارِ اولیه" in text and "این پیام همین حالا ارسال شده" in text
    assert "دقیقه بعد از بسته‌شدن کندل منتشر شد" not in text


def test_a_fresh_alert_carries_no_late_warning():
    cand = _candidate(tf="15m", close_ago_min=2, detected_ago_min=2)
    text = "\n".join(M._timing_lines(cand))
    assert "بعد از بسته‌شدن کندل منتشر شد" not in text


# ── the past-market guard ───────────────────────────────────────────────────

@pytest.mark.parametrize("tf,minutes,expected", [
    ("15m", 10, True),    # inside one candle → normal entry alert
    ("15m", 40, False),   # > 2×15m → analysis note only
    ("1h", 39, True),     # the GRAM case: late, warned, still an entry alert
    ("1h", 130, False),   # > 2h late → not a trade any more
])
def test_stale_alert_verdict(tf, minutes, expected):
    cand = _candidate(tf=tf, close_ago_min=minutes, detected_ago_min=minutes)
    as_entry, late = M._stale_alert_verdict(cand)
    assert as_entry is expected, (tf, minutes, as_entry)
    assert late == pytest.approx(minutes, abs=1)


def test_past_market_alert_is_never_published_as_an_entry(monkeypatch):
    """send_educational_setup must downgrade a 2-candle-old alert."""
    posted = {"edu": 0, "compact": 0}
    monkeypatch.setattr(M, "send_message", lambda *a, **k: 1)
    monkeypatch.setattr(M, "send_photo", lambda *a, **k: 2)
    monkeypatch.setattr(M, "_pro_slot_post", lambda *a, **k: (posted.__setitem__("compact", posted["compact"] + 1) or 3))
    monkeypatch.setattr(M, "build_educational_message", lambda c: "detail")
    cand = _candidate(tf="15m", close_ago_min=90, detected_ago_min=90)
    M.send_educational_setup(cand, _frame(tf_minutes=15, last_open_ago_min=90))
    assert cand.metadata.get("stale_detection"), "the downgrade was not recorded"


# ── the forming candle ──────────────────────────────────────────────────────

def test_live_candle_helper_returns_the_forming_bar(monkeypatch):
    cand = _candidate(tf="1h", close_ago_min=1)
    cand.symbol = "GRAMUSDT"
    now = datetime.now(timezone.utc)
    live = pd.DataFrame({
        "timestamp": [_ts(now - timedelta(minutes=30))],
        "open": [1.38], "high": [1.39], "low": [1.37], "close": [1.385], "volume": [10.0],
    })
    import data.fetcher as F
    monkeypatch.setattr(F, "get_klines", lambda *a, **k: live)
    # last CLOSED 1h candle opened 90 minutes ago (closed 30 min ago); the live
    # bar is the bucket that opened 30 minutes ago
    frame = _frame(tf_minutes=60, last_open_ago_min=90)
    got = M._live_candle(cand, frame)
    assert got is not None and got["close"] == 1.385


def test_live_candle_helper_is_silent_when_the_tape_has_closed(monkeypatch):
    cand = _candidate(tf="1h", close_ago_min=0)
    now = datetime.now(timezone.utc)
    live = pd.DataFrame({
        "timestamp": [_ts(now - timedelta(minutes=90))],
        "open": [1.38], "high": [1.39], "low": [1.37], "close": [1.385], "volume": [10.0],
    })
    import data.fetcher as F
    monkeypatch.setattr(F, "get_klines", lambda *a, **k: live)
    frame = _frame(tf_minutes=60, last_open_ago_min=30)
    assert M._live_candle(cand, frame) is None


def test_chart_source_marks_the_forming_candle():
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    assert "FORMING" in src and "_live_candle(candidate, df)" in src
    # Viva 09-23: live price is a TV-style tag ON the price ladder (never a
    # floating mid-chart pill) + a live date/time stamp under the youngest candle
    assert '" LIVE {_price(_live_px)} "' in src
    assert "_live_stamp" in src
    # Viva 09-23/24 (13-chart audit): the LIVE tag sits in the IN-PANEL label
    # column — the old axes-fraction x=1.0 anchor printed it OVER the price
    # axis numbers, so that anchor is banned from the source.
    assert "get_yaxis_transform" not in src
    assert "annotation_clip=False" not in src
    # no floating mid-chart live pill any more
    assert '_level_tag(ax, count + 1.8, live_price' not in src
