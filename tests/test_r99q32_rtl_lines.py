"""R99q32c — every line of the confirm card opens with a Persian word.

His 10-20: «آخر پیام اول جمله‌ها کلمات یا حروف انگلیسی یا اعداد و نمادها میاد
که باعث میشه به هم بریزه … اگر اول همه خط‌ها کلمه فارسی باشه درست میشه».

Telegram lays a line out by its FIRST strong character. A line that opens with
«WLDUSDT», «+25.8٪» or «TP1» gets an LTR paragraph inside an RTL message and
the tail flips — exactly the sandwich he photographed.
"""
import re

import bot.messages_v7 as M
from analysis.models import SignalCandidate

_FA = re.compile(r"[\u0621-\u064A\u0660-\u0669\u067E\u0686\u0698\u06A9\u06AF]")
_LEAD_JUNK = re.compile(r"^[\s•\-—━|]+")
_EMOJI = re.compile("^[^\u0621-\u064A\u0660-\u0669A-Za-z0-9]+")
_BRAND = {"📌"}


def _cand():
    return SignalCandidate(
        signal_id="rtl", symbol="WLDUSDT", style="SWING", setup_code="SPOTBREAK",
        setup_name="s", strategy_fa="f", direction="LONG", score=8,
        status="CONFIRMED", entry_zone_bottom=107.0, entry_zone_top=108.0,
        planned_entry=107.5, sl=96.75, tp1=110.0, tp2=111.5, rr_tp1=2.0,
        rr_tp2=3.0, bias="bull", trigger_timeframe="4h",
        metadata={"market": "SPOT", "is_spot": True,
                  "target_ladder": {"targets": [110.0, 111.5, 120.0],
                                    "weights": [40, 30, 30]}})


def _text():
    return M._tf_channel_text(_cand(), "🔗 آخرین نتیجه: <i>در انتظار نتیجه</i>")


def test_every_content_line_opens_with_a_persian_letter():
    bad = []
    for line in _text().splitlines():
        raw = _LEAD_JUNK.sub("", line).strip()
        if not raw or raw.startswith("━━"):
            continue
        if raw[:2] in _BRAND or raw.startswith("📌"):
            continue                    # the house signature
        body = re.sub(r"<[^>]+>", "", raw)          # drop the HTML tags first
        body = _EMOJI.sub("", body).lstrip(" •")
        if not body or not _FA.match(body[0]):
            bad.append(line)
    assert not bad, f"lines that do not open in Persian: {bad}"


def test_numbers_are_persian_digits():
    txt = _text()
    assert "۱۰۷.۵" in txt                  # entry, Persian digits
    assert "107.5" not in txt
    assert "۲.۳۳٪" in txt                  # TP distance


def test_no_line_ends_on_a_latin_word_or_a_bare_sign():
    for line in _text().splitlines():
        s = line.strip()
        if not s or s.startswith("━━") or "VIVAMON" in s:
            continue
        assert not re.search(r"[A-Za-z+]\s*$", s), f"latin/sign tail: {line!r}"


def test_the_tp_rows_are_persian_and_still_carry_their_numbers():
    txt = _text()
    for i in ("۱", "۲", "۳"):
        assert f"• هدف {i}:" in txt
    assert "TP1" not in txt


def test_the_header_speaks_persian_timeframe_and_direction():
    txt = _text()
    assert "تایم ۴ ساعته" in txt
    assert "صعودی" in txt
    assert "LONG" not in txt
