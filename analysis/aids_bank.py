"""Viva 2026-09-14 (23:40 law): the «تأییدهای کمکی» must EXPLAIN, not telegram-list.

Three deterministic banks (Fibo 15 / EMA 15 / RSI 15) plus one-line session
notes.  Selection is stable within a candle (seed = symbol+tf+bar ts) so an
update never re-phrases the same fact, but it varies candle-to-candle so the
channel never looks like a broken record.  Everything is Persian; numeric or
Latin fragments are wrapped in directional isolates by callers that need it.
"""
from __future__ import annotations

import hashlib
from typing import Dict, Optional

# ── FIBO — 15 explanations across the useful swing levels ──────────────────
FIBO_BANK: Dict[str, list] = {
    "on_level": [
        "قیمت دقیقاً روی لول {lv}٪ فیبو نشسته؛ این سطح معمولاً محلِ نفس‌کشیدنِ موج است.",
        "لول {lv}٪ فیبو همین حالا لمس شده؛ واکنش کندلِ بعد (شدو یا ریجکت) تکلیف سناریو را روشن می‌کند.",
        "همین‌جا روی {lv}٪، ترازِ عرضه و تقاضای موجِ قبل است؛ شکستنِ آرامِ آن یعنی ضعفِ روند.",
        "بستِ کندل روی لول {lv}٪ یعنی خریداران/فروشندگان این قیمت را پذیرفته‌اند؛ ادامه با پولبک سالم است.",
        "قیمت به فاصلهٔ {dist} با لول {lv}٪ فاصله دارد و در محدودهٔ واکنشِ این فیبو نفس می‌کشد.",
        "لول {lv}٪ به‌عنوان مرزِ اصلاحِ سالم فعال است؛ تا حفظ آن، موج اصلی زنده تلقی می‌شود.",
    ],
    "retest": [
        "پولبک به لول {lv}٪ زده شد و قیمت ریجکت گردید؛ این امضای کلاسیکِ ادامهٔ روند است.",
        "لمسِ {lv}٪ و پس‌زدنِ سریع — سفارجات limit روی این لول کار کرده‌اند.",
        "بعد از شکست، {lv}٪ به حمایت/مقاومتِ معکوس تبدیل شده و تستش سالم بود.",
        "کندلِ فعلی سایه‌اش را از {lv}٪ پس گرفته؛ ضعفِ ادامه در گروِ کلوزِ آن‌طرف‌تر است.",
    ],
    "break": [
        "لول {lv}٪ به سمتِ {dir} شکسته شد؛ اصلاحِ عمیق‌تر از این، ساختارِ موج را عوض می‌کند.",
        "قیمت از {lv}٪ به {dir} رد شد — اگر کلوز بیرون بماند، فیبو دیگر حمایت/مقاومت نیست.",
        "عبورِ معتبر از {lv}٪ یعنی موجِ جدید؛ سطحِ بعدیِ مرجع {next_lv}٪ است.",
        "کلوز پشتِ {lv}٪ افتاد؛ سناریوی ادامه ضعیف و سناریوی بازگشت فعال می‌شود.",
    ],
    "extension": [
        "لول ۱۲۷٪ فیبو به‌عنوان هدفِ اکستنشن فعال است؛ ریجکتِ آن یعنی ادغامِ موج.",
        "قیمت ۱۲۷٪ را رد کرد؛ ۱۶۱٫۸٪ ترمزِ بعدیِ روند است.",
        "اکستنشنِ ۱۶۱٫۸٪ مقاومتِ کلاسیکِ موجِ پنجم است؛ به آن نزدیک شده‌ایم.",
    ],
}

# ── EMA — 15 explanations on 21/51/100/200 ─────────────────────────────────
EMA_BANK = [
    "قیمت بالای EMA{lv} است و خودِ {lv} هم صعودی؛ روند کوتاه‌مدت در کنترل خریداران.",
    "قیمت زیر EMA{lv} گیر کرده تا زمانی که کلوزِ بالاتر از {lv} نیاید؛ بالا زدنِ بدون کلوز تله است.",
    "EMA{lv} در ۳ کندلِ اخیر به سمت بالا شکسته شد — تغییرِ فازِ کوتاه‌مدت.",
    "EMA{lv} در ۳ کندلِ اخیر به سمت پایین شکسته شد؛ مومنتوم از دست رفته است.",
    "فاصلهٔ قیمت تا EMA{lv} فقط {dist}٪ است؛ هر کلوزی دو طرفِ این عدد می‌تواند سوئیچِ روند باشد.",
    "قیمت به EMA{lv} چسبیده؛ بازار بینِ دو قدرت متعادل شده و جهت از کندلِ بعد بیرون می‌آید.",
    "EMA{lv} نقشِ داینامیکِ حمایت را بازی می‌کند و هر بار لمسش با شدو پس زده شده.",
    "EMA{lv} نقشِ داینامیکِ مقاومت را دارد؛ نزدیک‌شدن به آن بدون حجم، شکست نیست.",
    "ترکیبِ فعلی (زیرِ ۲۱، بالای ۵۱) یعنی اصلاح در دلِ روندِ صعودی؛ نه تأییدِ بازگشت، نه نقض.",
    "ترکیبِ فعلی (بالای ۲۱، زیرِ ۵۱) یعنی تلاشِ بازگشت روی میانگینِ میانی؛ تا کلوز بالای ۵۱ جدی نیست.",
    "هر چهار مووینگ زیرِ قیمت هستند؛ روندِ بلندمدت کاملاً صعودی و پولبک‌ها فرصت محسوب می‌شوند.",
    "هر چهار مووینگ بالای قیمت‌اند؛ روندِ بلندمدت نزولی و جهش‌ها تلهٔ نقدینگی‌اند.",
    "قیمت فقط بینِ EMA21 و EMA51 نوسان می‌کند؛ بازار رِنج است و سیگنالِ جهت از شکستِ یکی از این دو می‌آید.",
    "EMA200 به‌عنوان مرزِ نهایی زیرِ قیمت حفظ شده؛ تا بالای آن، سناریوهای نزولی اعتبارِ کامل ندارند.",
    "EMA200 بالای قیمت مقاومتِ ساختاری است؛ عبورِ آن با حجم، یعنی ورودِ پولِ جدید به بازی.",
]

# ── RSI — 15 explanations (divergence / OB-OS / 50-line / behavior) ────────
RSI_BANK = [
    "RSI روی {v} در منطقۀ بی‌طرف است؛ نه هیجان خرید هست نه فروش.",
    "RSI از ۵۰ به بالا شکست؛ میانگین قدرت در دست خریداران.",
    "RSI از ۵۰ به پایین شکست؛ فروشندگان فرمان را گرفته‌اند.",
    "RSI در قلمرو بیش‌خرید ({v}) — ادامه با سوختِ کمتر؛ اصلاح محتمل است.",
    "RSI در قلمرو اشباعِ فروش ({v})؛ این عدد به‌خودی‌خود کف نیست، نشانهٔ بازگشت لازم است.",
    "واگرایی منفی: قیمت سقفِ جدید زد اما RSI نه — نشانهٔ خستگیِ روندِ صعودی.",
        "واگرایی مثبت: قیمت کفِ جدید ساخت ولی RSI کفِ قبلیِ خود را نشکست — خریداران در کمین‌اند.",
        "RSI سقفِ قبلی‌اش را با مومنتوم قوی‌تر زد؛ تأییدِ هم‌جهتِ روند.",
        "تقاطعِ RSI با خطِ ۳۰ از پایین به بالا = تریگرِ کلاسیکِ خروج از اشباعِ فروش؛ با کلوزِ دومِ متوالی اعتبار می‌گیرد.",
    "تقاطعِ RSI با خطِ ۷۰ از بالا = تریگرِ اشباع؛ مراقبِ دو کلوزِ متوالی باشید.",
    "RSI روی قفلِ {v} می‌لغزد؛ بازار بینِ دو موج نفس می‌کشد.",
    "میانگینِ RSI ده کندل اخیر {avg} است؛ جهتِ خنثیِ فعلی با شکستِ همین میانگین می‌شکند.",
    "واگرایی پنهان: اصلاحِ قیمت عمیق‌تر از اصلاحِ RSI بود — نشانهٔ سلامتِ روندِ اصلی.",
    "RSI هنوز از قلهٔ قبلی پایین‌تر دویده؛ حتی ریجکت‌ها هم بی‌قدرت‌اند.",
    "پرشِ RSI از ۴۰ به ۶۰ در دو کندل — تشنجِ خریدِ تازه؛ پولبکش طبیعی است.",
]

# ── Sessions — Viva law: one-two useful lines per session ──────────────────
SESSION_NOTE = {
    "SYDNEY": "سشن استرالیا — نقدینگیِ سبک؛ حرکت‌های این ساعات معمولاً فیک‌اوت‌سازند.",
    "ASIA": "سشن آسیا — رِنج‌سازیِ کلاسیک؛ شکست‌های این بازه اغلب در لندن فیلتر می‌شوند.",
    "TOKYO": "سشن توکیو — شروعِ جریانِ پولِ آسیا؛ حجمِ متوسط، نوسانِ جهت‌دارِ کم.",
    "LONDON": "سشن لندن — اصلی‌ترین موج‌سازِ روز؛ شکست‌های معتبر در همین بازه کلوز می‌خورند.",
    "NY": "سشن نیویورک — اخبارِ آمریکا و اوجِ نقدینگی؛ اسپیکی‌ترین کندل‌ها اینجا کلوز می‌خورند.",
    "LONDON_NY_OVERLAP": "هم‌پوشانی لندن/نیویورک — بیشترین حجمِ روز؛ حرکتِ اینجا جدی‌ترین سیگنالِ سشنی است.",
    "LATE_NY": "غروبِ نیویورک — خروجِ پولِ خبری؛ بازار به رِنجِ آسیای فردا لیز می‌خورد.",
    "OFF_HOURS": "خارج از سشن‌های اصلی — نقدینگیِ کم؛ فاصله‌های اسلیپیج را در مدیریت لحاظ کنید.",
}


def _seed_index(*parts, mod: int) -> int:
    raw = "|".join(str(p) for p in parts).encode("utf-8", "ignore")
    return int(hashlib.md5(raw).hexdigest(), 16) % max(1, mod)


def _disambiguate(txt: str, direction: str) -> str:
    """Viva 2026-09-15 («توضیحاتی که کمک بکنه»): an aid line must speak with
    the scenario's own voice — slash-pairs like «خریداران/فروشندگان» or
    «حمایت/مقاومت» resolve to the side the candidate direction cares about,
    so the helper text reads as an explanation, not a template."""
    d = str(direction or "").upper()
    if d in ("LONG", "BULLISH", "BUY", "بالا"):
        return (txt.replace("خریداران/فروشندگان", "خریداران")
                   .replace("حمایت/مقاومت", "حمایت"))
    if d in ("SHORT", "BEARISH", "SELL", "پایین"):
        return (txt.replace("خریداران/فروشندگان", "فروشندگان")
                   .replace("حمایت/مقاومت", "مقاومت"))
    return txt


def fibo_note(level_pct: float, distance_pct: float, mode: str,
              direction: str, next_lv: float, symbol: str, tf: str, bar_key: str) -> str:
    key = {"ON": "on_level", "RETEST": "retest", "BREAK": "break", "EXT": "extension"}.get(
        str(mode).upper(), "on_level")
    bank = FIBO_BANK[key]
    lv = f"{level_pct:g}"
    txt = bank[_seed_index(symbol, tf, bar_key, key, mod=len(bank))]
    return _disambiguate(txt.format(lv=lv, dist=f"{abs(float(distance_pct)):.3f}", dir=direction,
                                    next_lv=f"{next_lv:g}"), direction)


_EMA_MODES = {
    "ABOVE": [0, 6, 10], "BELOW": [1, 7, 11], "NEAR": [4, 5],
    "CROSS_UP": [2], "CROSS_DOWN": [3], "STORY": [8, 9, 12, 13],
}
_RSI_MODES = {
    "NEUTRAL": [0, 10, 11], "CROSS_UP": [1, 7, 14], "CROSS_DOWN": [2, 13],
    "OB": [3, 9], "OS": [4, 8], "DIV_NEG": [5], "DIV_POS": [6], "HIDDEN": [12],
}


def ema_note(level: int, dist_pct: float, mode: str, symbol: str, tf: str,
             bar_key: str, raw_idx: Optional[int] = None,
             direction: str = "") -> str:
    """One self-descriptive EMA sentence.  The mode selects which bank lines
    may speak (state-aware), the seed rotates phrasing inside that subset."""
    if raw_idx is not None:
        txt = EMA_BANK[int(raw_idx) % len(EMA_BANK)]
    else:
        subset = _EMA_MODES.get(str(mode).upper(), [4, 5])
        txt = EMA_BANK[subset[_seed_index(symbol, tf, bar_key, level, mode,
                                          mod=len(subset))]]
    return _disambiguate(txt.format(lv=level, dist=f"{abs(dist_pct):.2f}"),
                         direction)


def rsi_note(value: float, avg10: float, mode: str, symbol: str, tf: str,
             bar_key: str, raw_idx: Optional[int] = None,
             direction: str = "") -> str:
    if raw_idx is not None:
        txt = RSI_BANK[int(raw_idx) % len(RSI_BANK)]
    else:
        subset = _RSI_MODES.get(str(mode).upper(), _RSI_MODES["NEUTRAL"])
        txt = RSI_BANK[subset[_seed_index(symbol, tf, bar_key, "rsi", mode,
                                          mod=len(subset))]]
    return _disambiguate(txt.format(v=f"{value:.0f}", avg=f"{avg10:.0f}"),
                         direction)


def session_note(name: str) -> str:
    return SESSION_NOTE.get(str(name or "").upper(), "")


def bank_sizes() -> Optional[Dict[str, int]]:
    return {"fibo": sum(len(v) for v in FIBO_BANK.values()),
            "ema": len(EMA_BANK), "rsi": len(RSI_BANK), "session": len(SESSION_NOTE)}
