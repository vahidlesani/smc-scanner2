"""Clean, evidence-driven Telegram messages for Viva Signal Bot v7."""
from __future__ import annotations

import html
import io
import os
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import requests

from analysis.models import SignalCandidate
from analysis.risk import build_money_management
from config import get_settings

SETTINGS = get_settings()
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID_EDUCATION = os.getenv("CHAT_ID_SIGNALS", "")
CHAT_ID_EXECUTION = os.getenv("CHAT_ID_APPROACHING", "")
CHAT_ID_RESULTS = os.getenv("CHAT_ID_RESULTS", "")
CHAT_ID_ADMIN = os.getenv("CHAT_ID", "")


def _e(value) -> str:
    return html.escape(str(value), quote=False)


def _price(value: float) -> str:
    value = float(value)
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def _chunks(text: str, limit: int = 3900) -> List[str]:
    chunks: List[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return chunks


def send_message(text: str, chat_id: Optional[str] = None) -> bool:
    target = chat_id or CHAT_ID_ADMIN
    if not TOKEN or not target:
        print("Telegram message skipped: missing TELEGRAM_TOKEN or target chat id")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    success = True
    for chunk in _chunks(text):
        try:
            response = requests.post(
                url,
                data={
                    "chat_id": target,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if not response.ok:
                print(f"Telegram sendMessage {response.status_code}: {response.text[:240]}")
                success = False
        except Exception as exc:
            print(f"Telegram sendMessage error: {exc}")
            success = False
    return success


def send_photo(image: bytes, caption: str, chat_id: Optional[str] = None) -> bool:
    target = chat_id or CHAT_ID_ADMIN
    if not TOKEN or not target or not image:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            data={"chat_id": target, "caption": caption[:1000], "parse_mode": "HTML"},
            files={"photo": ("viva-chart.png", image, "image/png")},
            timeout=35,
        )
        if not response.ok:
            print(f"Telegram sendPhoto {response.status_code}: {response.text[:240]}")
        return bool(response.ok)
    except Exception as exc:
        print(f"Telegram sendPhoto error: {exc}")
        return False


def generate_chart(df: pd.DataFrame, candidate: SignalCandidate, confirmed: bool = False) -> Optional[bytes]:
    if df is None or df.empty:
        return None
    try:
        frame = df.tail(100).copy().set_index("timestamp")
        frame.index = pd.DatetimeIndex(frame.index)
        market_colors = mpf.make_marketcolors(
            up="#00d084", down="#ff4d5a", edge="inherit", wick="inherit", volume="in"
        )
        style = mpf.make_mpf_style(
            marketcolors=market_colors,
            base_mpf_style="nightclouds",
            gridstyle=":",
            facecolor="#0b1020",
            figcolor="#0b1020",
        )
        fig, axes = mpf.plot(
            frame,
            type="candle",
            volume=True,
            style=style,
            returnfig=True,
            figsize=(13, 8),
            title=f"\n{candidate.symbol} | {candidate.style} | {candidate.setup_code} | {candidate.direction}",
            ylabel="Price (USDT)",
        )
        ax = axes[0]
        ax.axhspan(candidate.entry_zone_bottom, candidate.entry_zone_top, color="#ffd166", alpha=0.18, label="POI")
        ax.axhline(candidate.planned_entry, color="#ffffff", linestyle="--", linewidth=1.1, label="Entry")
        ax.axhline(candidate.sl, color="#ff4d5a", linestyle="--", linewidth=1.2, label="Invalidation / SL")
        if confirmed:
            ax.axhline(candidate.tp1, color="#00d084", linestyle="--", linewidth=1.1, label="TP1")
            ax.axhline(candidate.tp2, color="#00a86b", linestyle="--", linewidth=1.1, label="TP2")
        sweep_level = candidate.metadata.get("sweep_level")
        if sweep_level:
            ax.axhline(float(sweep_level), color="#b388ff", linestyle=":", linewidth=1.0, label="Liquidity sweep")
        structure_level = candidate.metadata.get("structure_level")
        if structure_level:
            ax.axhline(float(structure_level), color="#4cc9f0", linestyle=":", linewidth=1.0, label="MSS / BOS")
        ax.legend(loc="upper left", fontsize=8, framealpha=0.5)
        ax.text(
            0.99,
            0.02,
            f"{SETTINGS.channel_name} • {candidate.signal_id}",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            color="#b7c0d8",
            fontsize=8,
        )
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        buffer.seek(0)
        return buffer.read()
    except Exception as exc:
        print(f"Chart generation error {candidate.signal_id}: {exc}")
        return None


def build_educational_message(candidate: SignalCandidate) -> str:
    direction_fa = "سناریوی احتمالی خرید" if candidate.direction == "LONG" else "سناریوی احتمالی فروش"
    evidence_blocks = []
    for item in candidate.evidence:
        status = "✅" if item.confirmed else "⚠️"
        evidence_blocks.append(f"{status} <b>{_e(item.title)}</b>\n\n{_e(item.detail)}")
    confirmations = "\n".join(f"• {_e(item)}" for item in candidate.confirmations) or "• تأیید کمکی اضافه‌ای ثبت نشده است."
    warnings = "\n".join(f"• {_e(item)}" for item in candidate.warnings)
    return (
        f"📚 <b>تحلیل آموزشی | ستاپ در حال بررسی</b>\n"
        f"⛔ <b>این پیام تأیید ورود نیست</b>\n"
        f"👀 فقط برای رصد بازار و اهداف آموزشی\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>{_e(candidate.symbol)}</b>  •  {_e(candidate.style)}\n"
        f"🧭 {_e(direction_fa)}\n"
        f"🎯 ستاپ: <b>{_e(candidate.strategy_fa)}</b>\n"
        f"⭐ امتیاز فعلی: <b>{candidate.score}/10</b>\n"
        f"🆔 <code>{_e(candidate.signal_id)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(evidence_blocks)
        + f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🔎 <b>ناحیه‌ای که زیر نظر داریم</b>\n\n"
        f"از <b>{_price(candidate.entry_zone_bottom)}</b> تا <b>{_price(candidate.entry_zone_top)}</b>\n"
        f"سطح ابطال سناریو: <b>{_price(candidate.sl)}</b>\n\n"
        f"🧩 <b>تأییدهای کمکی</b>\n{confirmations}\n\n"
        f"⚠️ <b>شرایط و هشدارها</b>\n{warnings}\n\n"
        f"⛔ Entry، اهرم و حجم پوزیشن هنوز پیشنهاد نمی‌شود.\n"
        f"✅ در صورت تکمیل شرایط، ابتدا Approaching و سپس Confirmed ارسال می‌شود.\n"
        f"📢 <b>{_e(SETTINGS.channel_name)}</b>"
    )


def build_approaching_message(candidate: SignalCandidate, current_price: float, distance_atr: float) -> str:
    waiting = "حفظ ناحیه و بسته‌شدن کندل تأییدی همراه با شکست Micro Structure"
    return (
        f"⚡ <b>APPROACHING ENTRY ZONE</b>\n"
        f"⛔ <b>هنوز ورود تأیید نشده است</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>{_e(candidate.symbol)}</b> • {_e(candidate.style)} • {_e(candidate.direction)}\n"
        f"🎯 {_e(candidate.strategy_fa)}\n"
        f"⭐ {candidate.score}/10\n"
        f"🆔 <code>{_e(candidate.signal_id)}</code>\n\n"
        f"📍 ناحیه بررسی: <b>{_price(candidate.entry_zone_bottom)} – {_price(candidate.entry_zone_top)}</b>\n"
        f"💹 قیمت فعلی: <b>{_price(current_price)}</b>\n"
        f"📏 فاصله تا ناحیه: <b>{distance_atr:.2f} ATR</b>\n\n"
        f"🔎 در انتظار: {_e(waiting)}\n\n"
        f"👀 آماده بررسی چارت باشید، اما تا پیام Confirmed وارد نشوید.\n"
        f"📢 <b>{_e(SETTINGS.channel_name)}</b>"
    )


def build_confirmed_message(candidate: SignalCandidate) -> str:
    mm = build_money_management(candidate)
    reasons = []
    for index, item in enumerate([item for item in candidate.evidence if item.confirmed], start=1):
        reasons.append(f"<b>{index}. {_e(item.title)}</b>\n{_e(item.detail)}")
    mm_warning = "\n⚠️ حجم به سقف Margin مجاز محدود شده است." if mm.get("margin_capped") else ""
    return (
        f"✅ <b>ENTRY CONFIRMED</b>\n"
        f"📊 <b>{_e(candidate.style)} • {_e(candidate.symbol)} • {_e(candidate.direction)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 ستاپ: <b>{_e(candidate.strategy_fa)}</b>\n"
        f"⭐ کیفیت نهایی: <b>{candidate.score}/10</b> • Grade {mm.get('grade', '-')}\n"
        f"🆔 <code>{_e(candidate.signal_id)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🧠 <b>دلایل تأیید ورود</b>\n\n"
        + "\n\n".join(reasons)
        + f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>سطوح معامله</b>\n"
        f"├ Entry: <b>{_price(candidate.planned_entry)}</b>\n"
        f"├ Stop Loss: <b>{_price(candidate.sl)}</b>\n"
        f"├ TP1: <b>{_price(candidate.tp1)}</b> • {candidate.rr_tp1:.2f}R • بستن {SETTINGS.partial_tp1_percent:.0f}%\n"
        f"└ TP2: <b>{_price(candidate.tp2)}</b> • {candidate.rr_tp2:.2f}R • بستن {SETTINGS.partial_tp2_percent:.0f}%\n\n"
        f"💼 <b>مدیریت سرمایه بهینه</b>\n"
        f"├ اندازه حساب: <b>${mm.get('account', 0):,.0f}</b>\n"
        f"├ ریسک واقعی: <b>{mm.get('risk_pct', 0):.2f}% = ${mm.get('risk_amount', 0):.2f}</b>\n"
        f"├ اهرم ایمن پیشنهادی: <b>{mm.get('leverage', 1)}x</b>\n"
        f"├ Margin: <b>${mm.get('margin', 0):.2f} ({mm.get('margin_pct', 0):.1f}%)</b>\n"
        f"├ Position Size: <b>${mm.get('position_size', 0):,.0f}</b>\n"
        f"├ سود تقریبی TP1: <b>${mm.get('tp1_profit', 0):.2f}</b>\n"
        f"├ سود تقریبی TP2: <b>${mm.get('tp2_profit', 0):.2f}</b>\n"
        f"└ هزینه تخمینی Fee/Slippage: <b>${mm.get('estimated_roundtrip_cost', 0):.2f}</b>"
        f"{mm_warning}\n\n"
        f"📌 بعد از TP1، حد ضرر باقیمانده به Breakeven منتقل می‌شود.\n"
        f"⚠️ بسته‌شدن معتبر آن‌سوی {_price(candidate.sl)} سناریو را باطل می‌کند.\n"
        f"📢 <b>{_e(SETTINGS.channel_name)}</b>"
    )


def send_educational_setup(candidate: SignalCandidate, chart_df: Optional[pd.DataFrame]) -> bool:
    target = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
    chart = generate_chart(chart_df, candidate, confirmed=False) if chart_df is not None else None
    if chart:
        send_photo(
            chart,
            f"📚 {_e(candidate.symbol)} • {_e(candidate.style)} • {_e(candidate.setup_code)}\n"
            f"⛔ تأیید ورود نیست\n🆔 <code>{_e(candidate.signal_id)}</code>",
            target,
        )
    return send_message(build_educational_message(candidate), target)


def send_approaching(candidate: SignalCandidate, current_price: float, distance_atr: float) -> bool:
    return send_message(
        build_approaching_message(candidate, current_price, distance_atr),
        CHAT_ID_EXECUTION or CHAT_ID_ADMIN,
    )


def send_confirmed(candidate: SignalCandidate, chart_df: Optional[pd.DataFrame]) -> bool:
    """Publish both required components, resuming a partially completed attempt."""
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN

    if not candidate.metadata.get("confirmation_chart_sent"):
        chart = generate_chart(chart_df, candidate, confirmed=True) if chart_df is not None else None
        if not chart:
            print(f"Confirmed publication blocked: chart unavailable for {candidate.signal_id}")
            return False
        if not send_photo(
            chart,
            f"✅ CONFIRMED • {_e(candidate.symbol)} • {_e(candidate.style)} • {_e(candidate.direction)}\n"
            f"⭐ {candidate.score}/10\n🆔 <code>{_e(candidate.signal_id)}</code>",
            target,
        ):
            return False
        candidate.metadata["confirmation_chart_sent"] = True

    if not candidate.metadata.get("confirmation_message_sent"):
        if not send_message(build_confirmed_message(candidate), target):
            return False
        candidate.metadata["confirmation_message_sent"] = True

    return bool(
        candidate.metadata.get("confirmation_chart_sent")
        and candidate.metadata.get("confirmation_message_sent")
    )


def send_candidate_cancelled(candidate: SignalCandidate, reason: str) -> bool:
    return send_message(
        f"ℹ️ <b>سناریوی آموزشی باطل شد</b>\n"
        f"🪙 {_e(candidate.symbol)} • {_e(candidate.style)}\n"
        f"🆔 <code>{_e(candidate.signal_id)}</code>\n\n"
        f"دلیل: {_e(reason)}\n\n"
        f"این Setup تأیید نشده بود و در Win Rate یا نتایج معاملات محاسبه نمی‌شود.",
        CHAT_ID_EDUCATION or CHAT_ID_ADMIN,
    )


def _published_lifecycle_event(event: dict) -> bool:
    """Fail closed: result channels accept only DB-backed current-v7 publications."""
    signal_id = str(event.get("signal_id") or "")
    if (
        not signal_id.startswith("viva-")
        or event.get("strategy_version") != SETTINGS.strategy_version
        or event.get("confirmation_sent") is not True
        or not event.get("confirmed_at")
    ):
        print(f"Lifecycle notification blocked: invalid publication proof for {signal_id or 'unknown'}")
        return False
    try:
        # Late import avoids coupling message construction to DB initialization.
        from database.repository_v7 import is_lifecycle_event_publishable
        allowed = is_lifecycle_event_publishable(
            signal_id,
            str(event.get("event") or ""),
            str(event.get("result") or "") or None,
        )
    except Exception as exc:
        print(f"Lifecycle notification blocked: publication lookup failed for {signal_id}: {exc}")
        return False
    if not allowed:
        print(f"Lifecycle notification blocked: unpublished signal {signal_id}")
    return allowed


def send_tp1_event(signal: dict) -> bool:
    if signal.get("event") != "TP1" or not _published_lifecycle_event(signal):
        return False
    return send_message(
        f"🥇 <b>TP1 HIT</b>\n"
        f"🪙 <b>{_e(signal['symbol'])}</b> • {_e(signal.get('style', ''))}\n"
        f"🆔 <code>{_e(signal['signal_id'])}</code>\n\n"
        f"✅ {SETTINGS.partial_tp1_percent:.0f}% پوزیشن بسته شد.\n"
        f"🔒 حد ضرر {SETTINGS.partial_tp2_percent:.0f}% باقی‌مانده به Breakeven منتقل شد.",
        CHAT_ID_RESULTS or CHAT_ID_ADMIN,
    )


def send_trade_result(event: dict) -> bool:
    result = event.get("result", "")
    if (
        event.get("event") != "CLOSED"
        or result not in {"WIN", "LOSS"}
        or not _published_lifecycle_event(event)
    ):
        return False
    emoji = "✅" if result == "WIN" else "❌"
    return send_message(
        f"{emoji} <b>نتیجه سیگنال Confirmed</b>\n"
        f"🪙 <b>{_e(event.get('symbol'))}</b> • {_e(event.get('style', ''))}\n"
        f"🆔 <code>{_e(event.get('signal_id'))}</code>\n"
        f"📊 نتیجه: <b>{_e(result)}</b>\n"
        f"📈 بازده قیمت: <b>{float(event.get('pnl', 0)):+.2f}%</b>\n"
        f"💰 P&amp;L تقریبی: <b>${float(event.get('profit_usd', 0)):+.2f}</b>\n"
        f"📢 <b>{_e(SETTINGS.channel_name)}</b>",
        CHAT_ID_RESULTS or CHAT_ID_ADMIN,
    )


def send_startup_message(symbol_count: int) -> bool:
    return send_message(
        f"🚀 <b>Viva Signal Bot {SETTINGS.version} Started</b>\n"
        f"📢 {_e(SETTINGS.channel_name)}\n"
        f"📊 Dynamic symbols: {symbol_count}\n"
        f"⏱ Full scan: {SETTINGS.full_scan_minutes}m • Monitor: {SETTINGS.monitor_minutes}m\n"
        f"📚 Educational ≥ {SETTINGS.educational_min_score}/10\n"
        f"✅ Execution ≥ {SETTINGS.execution_min_score}/10 + mandatory gates\n"
        f"🆔 Signal IDs: viva-*",
        CHAT_ID_ADMIN,
    )
