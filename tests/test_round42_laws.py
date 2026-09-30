"""r42 — the message-hygiene round (Viva 09-26, evening screenshots).

His findings, verbatim:
  «راستی اهداف ۴ و ۵ رو از همه پیامهای تی پی و تایید سیگنال و هیت شدنها و
   استاپ و ... حذف بکن … و درصدهای خروج هم اشتباه زده»
     → the TP-hit status table showed the DEAD 35/35/20/5/5 five-row layout;
       it now shows the r40 three-pill ladder with its REAL 40/30/30 exits.
  «گاهی در کانال اصلی چند تا پیام تکراری میاد»
     → the protection-floor ratchet fired a lookalike note every monitor
       cycle; Telegram now gets the first activation per TP level and only
       meaningful jumps (≥0.20% of price), micro-ratchets stay app-only.
  «جارت ثابت بکسگتال» (mojibake on his device)
     → Arabic presentation-form codepoints are banned from outgoing labels;
       _fa_guard NFKC-folds any shaped run back to base letters.
  «فقط اسپات هم طبق قالب و فرمت پیامهای مختصر فیوچرز بیاد»
     → the spot alert's two paragraphs merged into ONE analysis line; the
       volume witness stays a one-liner.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()


# ── 1. TP table: three pills, real weights ──────────────────────────────────

def test_tp_status_table_is_three_rows_forty_thirty_thirty():
    from bot.messages_v7 import _tp_status_lines
    out = _tp_status_lines({"hit_index": 2})
    rows = out.split("\n")
    assert len(rows) == 3, rows
    assert "TP1" in rows[0] and "40%" in rows[0] and "✅" in rows[0]
    assert "TP2" in rows[1] and "30%" in rows[1] and "✅" in rows[1]
    assert "TP3" in rows[2] and "30%" in rows[2] and "💰" in rows[2]
    assert "TP4" not in out and "TP5" not in out


def test_tp_status_table_uses_event_weights_when_sent():
    from bot.messages_v7 import _tp_status_lines
    out = _tp_status_lines({"hit_index": 1, "weights": [50, 25, 25]})
    assert "50%" in out.split("\n")[0]


def test_dead_five_row_layout_is_gone_from_source():
    src = _src()
    assert "[35, 35, 20, 5, 5]" not in src
    assert "min(3, int(event.get(\"hit_index\") or 0))" in src


# ── 2. floor-note ratchet throttle ──────────────────────────────────────────

def test_profit_floor_throttle_present_and_fail_open():
    src = _src()
    part = src.split("def send_trailing_note")[1].split("def ")[0]
    assert "floor_note|" in part            # KV bookkeeping per signal+TP
    assert "0.002 * _new42" in part          # ≥0.20% of price = meaningful jump
    assert "except Exception" in part        # fail-open


# ── 3. caption mojibake guard ───────────────────────────────────────────────

def test_fa_guard_folds_presentation_forms_and_keeps_clean_text():
    import arabic_reshaper
    from bidi.algorithm import get_display
    from bot.messages_v7 import _fa_guard
    clean = "📊 چارت • SEIUSDT • تأیید سیگنال"
    assert _fa_guard(clean) == clean                      # no-op on clean text
    shaped = get_display(arabic_reshaper.reshape("تأیید سیگنال"))
    out = _fa_guard("x " + shaped)
    assert not any(0xFB50 <= ord(ch) <= 0xFEFF for ch in out), out


def test_chart_label_passes_through_guard():
    from bot.messages_v7 import _chart_label
    lab = _chart_label(symbol="CCUSDT", code="K1", title_fa="تأیید سیگنال")
    assert "چارت" in lab and "تأیید سیگنال" in lab


# ── 4. spot alert = futures-brief compactness ──────────────────────────────

def test_spot_alert_merges_geometry_and_meaning_into_one_line():
    src = _src()
    part = src.split("def send_spot_alert")[1].split("def tf_channel_publish_confirmed")[0]
    assert "analysis_line" in part                     # the merged line
    assert part.count('"""\n') >= 0
    # the two old paragraphs are gone
    assert "هشدار تماس؛ روند قیمت را از همین‌جا رصد کنید" not in part
    assert "این الگو نشان‌دهندهٔ احتمال حرکت صعودی است و ممکن است بزودی بشکند" not in part
    # volume witness one-liner kept (he approved it)
    assert "میانگین ۲۰کندله" in part
