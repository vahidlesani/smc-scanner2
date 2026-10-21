"""VIVA-TLBREAK specific Persian narrative blocks.

Lifecycle decides *when* a message is published; this module decides what a
Viva-TLBREAK message explains. It does not affect other strategies.
"""
from __future__ import annotations
from typing import Any


def _f(value: Any, digits: int = 2) -> str:
    """Viva 09-17 decimal ladder (his verbatim ruling): ≥1000 → comma+2 dec;
    100-999 → 2 dec; 1-99 → 3 dec; sub-$1 → 4 significant digits. The digits
    argument is retired."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "—"
    a = abs(x)
    if a >= 1000:
        return f"{x:,.2f}"
    if a >= 100:
        s = f"{x:.2f}"
    elif a >= 1:
        s = f"{x:.3f}"
    elif x == 0:
        return "0"
    else:
        import math as _math
        s = f"{x:.{max(1, 3 - _math.floor(_math.log10(a)))}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def detailed_warning_fa(metadata: dict, direction: str) -> str:
    pattern = str(metadata.get("viva_pattern") or metadata.get("tl_pattern_fa") or "ساختار داینامیک")
    touches = metadata.get("tl_touches") or metadata.get("viva_touch_count") or "—"
    fit = _f(metadata.get("tl_fit_error_atr") or metadata.get("viva_fit_error_atr"))
    stage = str(metadata.get("viva_state") or metadata.get("tl_stage") or "WATCH")
    # Viva 2026-09-16: «هیچ کلمه انگلیسی نیاد» — stage codes speak Persian.
    stage = {
        "WATCH": "رصد", "PRE_BREAK": "پیش از شکست",
        "S1_APPROACH": "نزدیک‌شدن به خط", "S2_BREAKOUT_CLOSED": "شکست با کلوز ثبت شد",
        "BREAKOUT_CLOSED": "شکست با کلوز ثبت شد", "S3_RETEST": "ری‌تست",
        "RETEST": "ری‌تست", "BASE": "بیس ساخته شد", "CONFIRMED": "تأیید شد",
    }.get(stage, stage)
    line = _f(metadata.get("tl_line") or metadata.get("viva_break_line"), 6)
    base = str(metadata.get("tl_base_kind") or metadata.get("viva_base_kind") or "در انتظار بیس/ری‌تست")
    counter = bool(metadata.get("viva_counter_trend") or metadata.get("tl_context_conflict"))
    side = "صعودی" if direction == "LONG" else "نزولی"
    counter_text = "این شکست خلاف بایاس تایم بالاتر است؛ ری‌تست و تأیید ۵دقیقه‌ای باید کامل باشند." if counter else "جهت شکست با کانتکست ساختاری هم‌راستاست."
    return (
        "📐 <b>VIVA-TLBREAK | تحلیل ساختار داینامیک</b>\n"
        f"• الگو: <b>{pattern}</b> • سناریو: <b>{side}</b>\n"
        f"• اعتبار خط: {touches} پیوت تأییدشده • خطای فیت ≈ {fit} ATR\n"
        f"• سطح شکست/ری‌تست: <code>{line}</code>\n"
        f"• مرحله فعلی: <b>{stage}</b> • بیس: {base}\n"
        f"• {counter_text}\n"
        "• ورود فقط بعد از ری‌تست معتبر و BOS/MSS پنج‌دقیقه‌ای بررسی می‌شود."
    )


def ai_advisory_fa(metadata: dict, direction: str) -> str:
    counter = bool(metadata.get("viva_counter_trend") or metadata.get("tl_context_conflict"))
    extension = _f(metadata.get("viva_extension_atr"))
    if counter:
        action = "چون شکست برگشتی است، بدون پین/انگالف در ری‌تست و BOS پنج‌دقیقه‌ای هیچ ورود اجرایی نداریم."
    else:
        action = "اگر ری‌تست به بیس برگشت و BOS پنج‌دقیقه‌ای بسته شد، قیمت را تعقیب نکن و فقط همان ساختار را دنبال کن."
    return (
        "🤖 <b>مشاوره AI | فقط مشورتی</b>\n"
        f"• فاصله فعلی از نقطهٔ شکست ≈ {extension} ATR\n"
        f"• {action}\n"
        "• هوش مصنوعی اجازه تغییر استاپ، هدف یا تأیید مستقل را ندارد."
    )


def management_fa(entry: float, first_stop: float, final_target: float, direction: str,
                  title: str = "VIVA-TLBREAK") -> str:
    # Viva 2026-09-16 (his corrected paste, verbatim labels): Entry→ورود،
    # First Stop→استاپ ابتدایی، Target→هدف؛ no Latin words in messages.
    return (
        f"💼 <b>مدیریت معامله {title}</b>\n"
        f"• ورود مرجع: <code>{_f(entry, 6)}</code>\n"
        f"• استاپ ابتدایی ساختاری: <code>{_f(first_stop, 6)}</code>\n"
        f"• هدف نهایی الگو: <code>{_f(final_target, 6)}</code>\n"
        "• خروج‌ها در پنج پله مدیریت می‌شوند؛ بعد هر تارگت، استاپ‌ها فقط در جهت سود جابه‌جا می‌شود."
    )
