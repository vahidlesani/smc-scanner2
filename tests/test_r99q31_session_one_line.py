"""R99q31f — the session announcement is ONE line, analysis included.

His 10-20: «بلوکِ تأییدِ سشن در یک خط اعلام شود همراه با تحلیلش». Before this,
`_tech_aids_lines` printed «• 🕐 سشن آخرین کندل: لندن» and then, on the next
row, the session's own analysis starting with another «🕐» — two lines for one
fact, and the second one occupied an EMA/Fibo/RSI slot.
"""
from analysis.models import SignalCandidate
from bot.messages_v7 import _tech_aids_lines


def _cand(md):
    return SignalCandidate(
        signal_id="s1", symbol="BTCUSDT", style="perp", setup_code="TLBREAK",
        setup_name="s", strategy_fa="f", direction="LONG", score=8,
        status="CONFIRMED", entry_zone_bottom=1.0, entry_zone_top=1.0,
        planned_entry=1.0, sl=0.9, tp1=1.2, tp2=1.3, rr_tp1=2.0, rr_tp2=3.0,
        bias="bull", trigger_timeframe="1h", metadata=md)


def test_session_name_and_analysis_share_one_row():
    rows = _tech_aids_lines(_cand({"session": "LONDON"}))
    sess_rows = [r for r in rows if "🕐" in r]
    assert len(sess_rows) == 1
    assert "لندن" in sess_rows[0]
    assert "—" in sess_rows[0]              # the analysis rides the same line
    assert len(sess_rows[0]) > len("• 🕐 سشن آخرین کندل: ")


def test_a_stored_session_aid_never_prints_a_second_time():
    rows = _tech_aids_lines(_cand({
        "session": "NY",
        "tech_aids": ["🕐 سشن نیویورک — اخبارِ آمریکا و اوجِ نقدینگی",
                      "📊 EMA21 بالای قیمت"]}))
    assert len([r for r in rows if "🕐" in r]) == 1
    assert any("EMA21" in r for r in rows)


def test_the_freed_slot_carries_a_real_aid():
    md = {"session": "ASIA",
          "tech_aids": ["🕐 سشن آسیا — رِنج‌سازی",
                        "📊 EMA21", "🌀 فیبو 0.618", "📈 RSI 55"]}
    rows = _tech_aids_lines(_cand(md))
    assert any("EMA21" in r for r in rows)
    assert any("فیبو" in r for r in rows)
    assert any("RSI" in r for r in rows)


def test_a_candidate_without_a_session_is_unchanged():
    rows = _tech_aids_lines(_cand({"tech_aids": ["📊 EMA21 بالای قیمت"]}))
    assert len(rows) == 1
    assert "EMA21" in rows[0]
    assert "🕐" not in rows[0]
