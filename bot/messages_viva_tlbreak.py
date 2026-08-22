"""VIVA-TLBREAK specific Persian narrative blocks.

Lifecycle decides *when* a message is published; this module decides what a
Viva-TLBREAK message explains. It does not affect other strategies.
"""
from __future__ import annotations
from typing import Any


def _f(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def detailed_warning_fa(metadata: dict, direction: str) -> str:
    pattern = str(metadata.get("viva_pattern") or metadata.get("tl_pattern_fa") or "ساختار داینامیک")
    touches = metadata.get("tl_touches") or metadata.get("viva_touch_count") or "—"
    fit = _f(metadata.get("tl_fit_error_atr") or metadata.get("viva_fit_error_atr"))
    stage = str(metadata.get("viva_state") or metadata.get("tl_stage") or "WATCH")
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
        action = "چون شکست برگشتی است، بدون Pin/Engulf در ری‌تست و BOS پنج‌دقیقه‌ای هیچ ورود اجرایی نداریم."
    else:
        action = "اگر ری‌تست به بیس برگشت و BOS پنج‌دقیقه‌ای بسته شد، chase نکن و فقط همان ساختار را دنبال کن."
    return (
        "🤖 <b>مشاوره AI | فقط مشورتی</b>\n"
        f"• فاصله فعلی از breakout ≈ {extension} ATR\n"
        f"• {action}\n"
        "• AI اجازه تغییر Stop، Target یا تأیید مستقل را ندارد."
    )


def management_fa(entry: float, first_stop: float, final_target: float, direction: str) -> str:
    return (
        "💼 <b>مدیریت معامله VIVA-TLBREAK</b>\n"
        f"• Entry مرجع: <code>{_f(entry, 6)}</code>\n"
        f"• First Stop ساختاری: <code>{_f(first_stop, 6)}</code>\n"
        f"• Target نهایی الگو: <code>{_f(final_target, 6)}</code>\n"
        "• خروج‌ها در پنج پله مدیریت می‌شوند؛ بعد هر TP، Stop فقط در جهت سود جابه‌جا می‌شود."
    )
