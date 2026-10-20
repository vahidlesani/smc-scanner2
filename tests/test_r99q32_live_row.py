"""R99q32d — updates and alerts carry the symbol's LIVE price.

His 10-20: «یا هشدارها چه با چارت‌ها چه بدون چارت‌ها یه مقدار روی دیزاین
پیام‌ها کار بکن .. خط‌کشی بین قسمت‌های پیام .. قیمت لایو اون نماد اضافه بشن
.. شبیه پیام‌های ستاپ‌ها».

A card that names a zone and an invalidation but never the current price makes
the reader hunt the ticker himself.
"""
import bot.messages_v7 as M
from analysis.models import SignalCandidate


def _cand():
    return SignalCandidate(
        signal_id="u1", symbol="ZECUSDT", style="SWING", setup_code="PINVAL",
        setup_name="s", strategy_fa="ف|پین‌وال", direction="LONG", score=9,
        status="WATCH", entry_zone_bottom=1150.0, entry_zone_top=1160.0,
        planned_entry=1155.0, sl=1129.0, tp1=1170.0, tp2=1185.0,
        rr_tp1=2.0, rr_tp2=3.0, bias="bull", trigger_timeframe="30m",
        metadata={})


def test_the_update_caption_carries_a_live_row(monkeypatch):
    monkeypatch.setattr(M, "_live_price_for_message", lambda c: 1152.5)
    cap = M._setup_update_caption(_cand(), "تست", "🔄 تست", 1, has_chart=False)
    assert "📈 قیمت لحظه‌ای:" in cap
    assert "1,152.50" in cap or "۱,۱۵۲.۵۰" in cap


def test_the_compact_alert_carries_the_same_row(monkeypatch):
    monkeypatch.setattr(M, "_live_price_for_message", lambda c: 1152.5)
    cap = M._compact_alert_caption(_cand())
    assert "📈 قیمت لحظه‌ای:" in cap


def test_a_dead_ticker_says_so_instead_of_lying(monkeypatch):
    monkeypatch.setattr(M, "_live_price_for_message", lambda c: 0.0)
    assert "در دسترس نیست" in M._live_row32(_cand())


def test_the_row_is_one_line_and_persian_led(monkeypatch):
    monkeypatch.setattr(M, "_live_price_for_message", lambda c: 42.0)
    row = M._live_row32(_cand())
    assert "\n" not in row
    assert row.lstrip("📈 ").startswith("قیمت")


def test_both_message_families_call_the_same_helper():
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    assert src.count("_live_row32(candidate)") >= 2   # update caption + compact
