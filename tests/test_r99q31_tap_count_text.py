"""R99q31g — the tap/grid count is written in the Telegram text too.

His 10-20: «تعداد تپ و گرید در متن تلگرام هم بیاید». The counts existed only
inside the chart legend («WEDGE · 5 PIVOTS · GRADE B · 4/5»), so a text-only
reader never learned how well the rails were tested. Geometry untouched — the
row only reports what the engine already measured.
"""
from analysis.models import SignalCandidate
from bot.messages_v7 import _law_note_lines


def _cand(md):
    return SignalCandidate(
        signal_id="s1", symbol="XRPUSDT", style="perp", setup_code="TLBREAK",
        setup_name="s", strategy_fa="f", direction="SHORT", score=8,
        status="CONFIRMED", entry_zone_bottom=1.0, entry_zone_top=1.0,
        planned_entry=1.0, sl=1.1, tp1=0.85, tp2=0.8, rr_tp1=2.0, rr_tp2=3.0,
        bias="bear", trigger_timeframe="4h", metadata=md)


def _tap_rows(rows):
    return [r for r in rows if "تستِ ضلع" in r]


def test_taps_from_metadata_reach_the_text():
    rows = _law_note_lines(_cand({
        "law_slug": "WEDGE_FALLING", "pattern_taps": {"upper": 4, "lower": 5},
        "pattern_grade": "B"}))
    got = _tap_rows(rows)
    assert len(got) == 1
    assert "4 / 5" in got[0]
    assert "B" in got[0]


def test_taps_fall_back_to_the_stamped_shape():
    rows = _law_note_lines(_cand({
        "law_slug": "TRIANGLE_ASCENDING",
        "pattern_law_all": [{"law_slug": "TRIANGLE_ASCENDING",
                             "upper_taps": 3, "lower_taps": 2}]}))
    assert "3 / 2" in _tap_rows(rows)[0]


def test_no_taps_no_row():
    rows = _law_note_lines(_cand({"law_slug": "WEDGE_FALLING"}))
    assert _tap_rows(rows) == []


def test_the_count_never_invents_a_missing_side():
    rows = _law_note_lines(_cand({
        "law_slug": "TRENDLINE", "pattern_taps": {"upper": 4}}))
    got = _tap_rows(rows)
    assert len(got) == 1
    assert "4" in got[0] and "?" not in got[0]


def test_the_row_is_absent_when_there_is_no_pattern_at_all():
    rows = _law_note_lines(_cand({"pattern_taps": {"upper": 4, "lower": 4}}))
    assert _tap_rows(rows) == []
