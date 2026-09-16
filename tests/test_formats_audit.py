"""Format law audit (Viva 09-17): the two reference skeletons saved in
handoff/MESSAGE_REFERENCE.md are asserted here so no future edit can drift
the detailed educational message or the final-warning preview again."""
from test_v7 import make_candidate

import bot.messages_v7 as mv7

DETAIL_MARKERS = [
    "🏷", "🆔", " <b>تحلیل آموزشی | ستاپ در حال بررسی</b>",
    "⛔ <b>این پیام تأیید ورود نیست</b>",
    "👀 فقط برای رصد بازار و اهداف آموزشی",
    "🪙", "🌐", "🧭", "🎯 ستاپ:", "⭐ امتیاز فعلی:",
    "🔎 <b>ناحیه‌ای که زیر نظر داریم</b>",
    "🧭 <b>کانتکست تایم بالاتر</b>",
    "⛔ ورود، اهرم و حجم پوزیشن هنوز پیشنهاد نمی‌شود",
    "📢",
]

FINAL_WARNING_MARKERS = [
    "🏷 <b>VIVA __ TecnoClasic</b>",
    "⚡<b>هشدار نهایی | آماده‌سازی ورود</b>",
    "🪙 <b>{_e(sym)}</b>", "🔎 در آستانه شکست — تکنوکلاسیک (پیش‌نمایش؛ سیگنال نیست)",
    "📐 خط روند اصلی روی تایم",
    "🎯 جهت محتمل پس از شکست معتبر:",
    "📏 فاصله زنده تا خط:",
    "⚖️ تاریخچۀ برخورد روی این خط:",
    "🌀 کامپرشن:",
    "سیگنال واقعی فقط با Close معتبرِ شکست + پولبک اول + BOS تایم پایین",
    "🆔<code>{_e(code)}</code>",
]


def _cand():
    c = make_candidate("EDUCATIONAL", 7)
    c.symbol = "UNIUSDT"
    c.direction = "SHORT"
    c.style = "DAYTRADE"
    c.trigger_timeframe = "15M"
    c.setup_code = "TLBREAK"
    c.metadata.update({"poi_type": "ORDER_BLOCK",
                       "target_ladder": {"targets": [1.0, 0.9], "weights": [50, 50]}})
    return c


def test_detail_skeleton_order():
    txt = mv7.build_educational_message(_cand())
    pos = -1
    for marker in DETAIL_MARKERS:
        at = txt.find(marker)
        assert at > pos, f"marker missing/out of order: {marker}"
        pos = at


def test_final_warning_skeleton_in_source():
    import inspect
    src = inspect.getsource(mv7.send_technoclassic_preview)
    pos = -1
    for marker in FINAL_WARNING_MARKERS:
        at = src.find(marker)
        assert at > pos, f"final-warning marker missing/out of order: {marker}"
        pos = at
