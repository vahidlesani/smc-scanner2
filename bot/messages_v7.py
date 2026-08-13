"""Clean, evidence-driven Telegram messages for Viva Signal Bot v7."""
from __future__ import annotations

import html
import io
import os
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle
from matplotlib.ticker import FuncFormatter
import matplotlib.image as mpimg
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

# VivaSignals Pro chart identity: TradingView-inspired, but deliberately
# independent and optimized for Telegram readability.
CHART_THEME = {
    "figure": os.getenv("CHART_FIGURE_COLOR", "#0B101A"),
    "panel": os.getenv("CHART_PANEL_COLOR", "#111827"),
    "grid": os.getenv("CHART_GRID_COLOR", "#273449"),
    "text": os.getenv("CHART_TEXT_COLOR", "#E5EDF7"),
    "muted": os.getenv("CHART_MUTED_COLOR", "#94A3B8"),
    "bull": os.getenv("CHART_BULL_COLOR", "#00C2A8"),
    "bear": os.getenv("CHART_BEAR_COLOR", "#FF5C6C"),
    "entry": os.getenv("CHART_ENTRY_COLOR", "#FFC857"),
    "invalidation": os.getenv("CHART_INVALIDATION_COLOR", "#FF4757"),
    "tp1": os.getenv("CHART_TP1_COLOR", "#39D98A"),
    "tp2": os.getenv("CHART_TP2_COLOR", "#00B8D9"),
    "liquidity": os.getenv("CHART_LIQUIDITY_COLOR", "#A78BFA"),
    "structure": os.getenv("CHART_STRUCTURE_COLOR", "#38BDF8"),
}
CHART_BRAND_NAME = os.getenv("CHART_BRAND_NAME", "VIVA SIGNALS PRO").upper()
CHART_BRAND_HANDLE = os.getenv("CHART_BRAND_HANDLE", "")
CHART_LOGO_PATH = os.getenv(
    "CHART_LOGO_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "vivasignals-logo.png"),
)
SIGNAL_SEPARATOR = os.getenv(
    "SIGNAL_SEPARATOR_TEXT",
    "━━━━━━━━━━ 💹 VIVASIGNALS PRO ━━━━━━━━━━",
)


def _e(value) -> str:
    return html.escape(str(value), quote=False)


def _price(value: float) -> str:
    value = float(value)
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def _axis_price(value: float, _position=None) -> str:
    value = float(value)
    absolute = abs(value)
    if absolute >= 1000:
        return f"{value:,.0f}"
    if absolute >= 100:
        return f"{value:,.2f}"
    if absolute >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def _market_label(candidate: SignalCandidate) -> str:
    asset_class = str(candidate.market.get("asset_class") or "CRYPTO").upper()
    venue = str(candidate.market.get("venue") or "BYBIT").upper()
    labels = {
        "FOREX": "فارکس",
        "METAL": "فلزات",
        "COMMODITY": "کالا",
        "EQUITY": "سهام",
        "TRADFI": "TradFi",
        "CRYPTO": "کریپتو",
    }
    return f"{venue} • {labels.get(asset_class, asset_class)}"


def _chart_market_label(candidate: SignalCandidate) -> str:
    """Use ASCII on charts so rendering never depends on RTL shaping fonts."""
    asset_class = str(candidate.market.get("asset_class") or "CRYPTO").upper()
    venue = str(candidate.market.get("venue") or "BYBIT").upper()
    return f"{venue} • {asset_class}"


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


def send_signal_separator(chat_id: Optional[str] = None) -> bool:
    """Separate complete lifecycle packages without splitting chart and text."""
    return send_message(f"<b>{_e(SIGNAL_SEPARATOR)}</b>", chat_id)


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


def _level_tag(ax, x: float, y: float, label: str, color: str) -> None:
    ax.text(
        x,
        y,
        label,
        color="#07111A",
        fontsize=7.5,
        fontweight="bold",
        va="center",
        ha="left",
        zorder=12,
        bbox={"boxstyle": "round,pad=0.28", "facecolor": color, "edgecolor": color, "alpha": 0.96},
    )


def _scenario_arrow(ax, start, end, color: str, alpha: float = 0.9) -> None:
    arrow = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=13,
        linewidth=1.5,
        linestyle=(0, (4, 3)),
        color=color,
        alpha=alpha,
        transform=ax.transData,
        zorder=11,
    )
    ax.add_patch(arrow)


def _add_branding(fig, ax, candidate: SignalCandidate) -> None:
    footer = Rectangle(
        (0, 0),
        1,
        0.052,
        transform=fig.transFigure,
        facecolor=CHART_THEME["figure"],
        edgecolor=CHART_THEME["grid"],
        linewidth=0.8,
        zorder=20,
    )
    fig.add_artist(footer)
    fig.text(
        0.055,
        0.024,
        f"{candidate.signal_id}  •  {_chart_market_label(candidate)}",
        color=CHART_THEME["muted"],
        fontsize=7.5,
        va="center",
        zorder=22,
    )
    brand_x = 0.952
    if os.path.isfile(CHART_LOGO_PATH):
        try:
            logo_ax = fig.add_axes([0.918, 0.004, 0.038, 0.044], zorder=23)
            logo_ax.imshow(mpimg.imread(CHART_LOGO_PATH), alpha=0.52)
            logo_ax.axis("off")
            brand_x = 0.912
        except Exception as exc:
            print(f"Chart logo warning: {exc}")
    brand_line = CHART_BRAND_NAME + (f"  {CHART_BRAND_HANDLE}" if CHART_BRAND_HANDLE else "")
    fig.text(
        brand_x,
        0.024,
        brand_line,
        color=CHART_THEME["text"],
        fontsize=10.5,
        fontweight="bold",
        ha="right",
        va="center",
        alpha=0.82,
        zorder=22,
    )
    ax.text(
        0.985,
        0.025,
        CHART_BRAND_NAME.upper(),
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=10,
        fontweight="bold",
        color=CHART_THEME["text"],
        alpha=0.10,
        zorder=2,
    )


def generate_chart(df: pd.DataFrame, candidate: SignalCandidate, confirmed: bool = False) -> Optional[bytes]:
    """Render a branded TradingView-inspired 1440×900 chart."""
    if df is None or df.empty:
        return None
    try:
        frame = df.tail(100).copy().set_index("timestamp")
        frame.index = pd.DatetimeIndex(frame.index)
        market_colors = mpf.make_marketcolors(
            up=CHART_THEME["bull"],
            down=CHART_THEME["bear"],
            edge="inherit",
            wick="inherit",
            volume="in",
        )
        style = mpf.make_mpf_style(
            marketcolors=market_colors,
            base_mpf_style="nightclouds",
            gridstyle=":",
            gridcolor=CHART_THEME["grid"],
            facecolor=CHART_THEME["panel"],
            figcolor=CHART_THEME["figure"],
            edgecolor=CHART_THEME["grid"],
            rc={
                "axes.labelcolor": CHART_THEME["muted"],
                "xtick.color": CHART_THEME["muted"],
                "ytick.color": CHART_THEME["muted"],
                "font.size": 8,
            },
        )
        fig, axes = mpf.plot(
            frame,
            type="candle",
            volume=True,
            style=style,
            returnfig=True,
            figsize=(12, 7.5),
            panel_ratios=(5, 1.15),
            datetime_format="%m-%d  %H:%M",
            xrotation=0,
            ylabel="",
            ylabel_lower="VOLUME",
            warn_too_much_data=500,
        )
        # mplfinance creates manually positioned axes, so set the panel geometry
        # directly: wide price area, compact volume, and a small branded footer.
        price_position = [0.055, 0.245, 0.845, 0.650]
        volume_position = [0.055, 0.090, 0.845, 0.135]
        for index, chart_ax in enumerate(axes):
            chart_ax.set_position(price_position if index < 2 else volume_position)
            chart_ax.set_facecolor(CHART_THEME["panel"])
            chart_ax.grid(True, color=CHART_THEME["grid"], alpha=0.34, linewidth=0.65, linestyle=":")
            chart_ax.yaxis.tick_right()
            chart_ax.yaxis.set_label_position("right")
            chart_ax.tick_params(colors=CHART_THEME["muted"], labelsize=7.5)
            for spine in chart_ax.spines.values():
                spine.set_color(CHART_THEME["grid"])
                spine.set_alpha(0.55)

        ax = axes[0]
        ax.yaxis.set_major_formatter(FuncFormatter(_axis_price))
        ax.tick_params(
            axis="y",
            colors=CHART_THEME["text"],
            labelsize=9.5,
            labelright=True,
            right=True,
            pad=18,
        )
        ax.set_ylabel("")
        for label in ax.get_yticklabels():
            label.set_fontweight("bold")
        # mplfinance creates twin axes; keep only the primary price labels to
        # prevent dim duplicates on the right edge.
        if len(axes) > 1:
            axes[1].tick_params(axis="y", labelleft=False, labelright=False)
        if len(axes) > 3:
            axes[3].tick_params(axis="y", labelleft=False, labelright=False)

        count = len(frame)
        future = 14 if confirmed else 4
        for chart_ax in axes:
            chart_ax.set_xlim(-1, count + future)

        zone_start = max(0, count - 55)
        zone_end = count + (4 if confirmed else 1)
        ax.fill_between(
            [zone_start, zone_end],
            candidate.entry_zone_bottom,
            candidate.entry_zone_top,
            color=CHART_THEME["entry"],
            alpha=0.12,
            zorder=1,
        )
        ax.hlines(
            [candidate.entry_zone_bottom, candidate.entry_zone_top],
            zone_start,
            zone_end,
            colors=CHART_THEME["entry"],
            linewidth=0.75,
            linestyles=(0, (3, 3)),
            alpha=0.65,
            zorder=4,
        )
        ax.text(
            zone_start + 0.6,
            candidate.entry_zone_top,
            "POI / ENTRY ZONE",
            color=CHART_THEME["entry"],
            fontsize=7,
            va="bottom",
            fontweight="bold",
            alpha=0.92,
        )

        line_start = max(0, count - 34)
        line_end = count + (5 if confirmed else 1)
        ax.hlines(
            candidate.sl,
            line_start,
            line_end,
            color=CHART_THEME["invalidation"],
            linewidth=1.15,
            linestyles=(0, (6, 3)),
            zorder=7,
        )
        _level_tag(
            ax,
            line_end + 0.35,
            candidate.sl,
            f"INVALIDATION  {_price(candidate.sl)}",
            CHART_THEME["invalidation"],
        )

        sweep_level = candidate.metadata.get("sweep_level")
        if sweep_level:
            ax.hlines(
                float(sweep_level),
                max(0, count - 65),
                count,
                color=CHART_THEME["liquidity"],
                linestyle=(0, (2, 3)),
                linewidth=1.0,
                alpha=0.80,
            )
            ax.text(
                max(0, count - 64),
                float(sweep_level),
                "LIQUIDITY SWEEP",
                color=CHART_THEME["liquidity"],
                fontsize=6.8,
                va="bottom",
            )
        structure_level = candidate.metadata.get("structure_level")
        if structure_level:
            ax.hlines(
                float(structure_level),
                max(0, count - 55),
                count,
                color=CHART_THEME["structure"],
                linestyle=(0, (4, 3)),
                linewidth=0.95,
                alpha=0.78,
            )
            ax.text(
                max(0, count - 54),
                float(structure_level),
                "MSS / BOS",
                color=CHART_THEME["structure"],
                fontsize=6.8,
                va="bottom",
            )

        if confirmed:
            tool_start = max(0, count - 20)
            tool_end = count + 4.5
            ax.fill_between(
                [tool_start, tool_end],
                candidate.planned_entry,
                candidate.tp2,
                color=CHART_THEME["tp1"],
                alpha=0.085,
                zorder=1,
            )
            ax.fill_between(
                [tool_start, tool_end],
                candidate.planned_entry,
                candidate.sl,
                color=CHART_THEME["invalidation"],
                alpha=0.095,
                zorder=1,
            )
            ax.vlines(
                [tool_start, tool_end],
                min(candidate.sl, candidate.tp2),
                max(candidate.sl, candidate.tp2),
                color=CHART_THEME["muted"],
                linewidth=0.65,
                alpha=0.45,
            )
            levels = [
                (candidate.planned_entry, "ENTRY", CHART_THEME["entry"]),
                (candidate.tp1, "TP1", CHART_THEME["tp1"]),
                (candidate.tp2, "TP2", CHART_THEME["tp2"]),
            ]
            for level, label, color in levels:
                ax.hlines(
                    level,
                    tool_start,
                    tool_end,
                    color=color,
                    linewidth=1.15,
                    linestyles="-" if label == "ENTRY" else (0, (5, 3)),
                    zorder=8,
                )
                _level_tag(ax, tool_end + 0.35, level, f"{label}  {_price(level)}", color)

            scenario_x = [count + 0.6, count + 5.2, count + 9.8]
            _scenario_arrow(
                ax,
                (scenario_x[0], candidate.planned_entry),
                (scenario_x[1], candidate.tp1),
                CHART_THEME["text"],
            )
            _scenario_arrow(
                ax,
                (scenario_x[1], candidate.tp1),
                (scenario_x[2], candidate.tp2),
                CHART_THEME["tp2"],
            )
            _scenario_arrow(
                ax,
                (scenario_x[0], candidate.planned_entry),
                (count + 4.0, candidate.sl),
                CHART_THEME["invalidation"],
                alpha=0.58,
            )
            scenario_label_y = candidate.planned_entry + 0.45 * (
                candidate.tp1 - candidate.planned_entry
            )
            ax.text(
                count + 0.7,
                scenario_label_y,
                "PROJECTED SCENARIO",
                color=CHART_THEME["muted"],
                fontsize=6.8,
                va="bottom" if candidate.direction == "LONG" else "top",
                alpha=0.90,
            )

            info = (
                f"{candidate.direction}  •  {candidate.style}\n"
                f"SETUP  {candidate.setup_code}\n"
                f"SCORE  {candidate.score}/10\n"
                f"R:R  {candidate.rr_tp1:.2f} / {candidate.rr_tp2:.2f}"
            )
            ax.text(
                0.015,
                0.965,
                info,
                transform=ax.transAxes,
                ha="left",
                va="top",
                color=CHART_THEME["text"],
                fontsize=7.8,
                linespacing=1.45,
                zorder=15,
                bbox={
                    "boxstyle": "round,pad=0.55",
                    "facecolor": CHART_THEME["figure"],
                    "edgecolor": CHART_THEME["grid"],
                    "alpha": 0.88,
                },
            )

        fig.text(
            0.055,
            0.952,
            f"{candidate.symbol}  •  {candidate.style}  •  {candidate.direction}",
            color=CHART_THEME["text"],
            fontsize=14,
            fontweight="bold",
            va="center",
        )
        fig.text(
            0.055,
            0.922,
            f"{candidate.setup_code}  ·  {_chart_market_label(candidate)}  ·  {'CONFIRMED' if confirmed else 'EDUCATIONAL ANALYSIS'}",
            color=CHART_THEME["muted"],
            fontsize=8,
            va="center",
        )
        _add_branding(fig, ax, candidate)

        buffer = io.BytesIO()
        fig.savefig(
            buffer,
            format="png",
            dpi=120,
            facecolor=CHART_THEME["figure"],
            edgecolor="none",
        )
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
        f"🌐 {_e(_market_label(candidate))}\n"
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
        f"🌐 {_e(_market_label(candidate))}\n"
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
    invalidation_label = (
        "قیمت ابطال تحلیل (مرجع محاسبه، نه دستور اجباری Stop)"
        if candidate.style.upper() == "SWING"
        else "قیمت ابطال تحلیل / Stop پیشنهادی"
    )
    management_note = (
        "در Swing این سطح مرز ابطال تحلیل است؛ محل سفارش Stop و نحوه خروج باید با مدیریت شخصی معامله‌گر تنظیم شود."
        if candidate.style.upper() == "SWING"
        else "Stop و اندازه پوزیشن صرفاً پیشنهاد سیستم‌اند و باید با مدیریت شخصی معامله‌گر تطبیق داده شوند."
    )
    return (
        f"✅ <b>ENTRY CONFIRMED</b>\n"
        f"📊 <b>{_e(candidate.style)} • {_e(candidate.symbol)} • {_e(candidate.direction)}</b>\n"
        f"🌐 {_e(_market_label(candidate))}\n"
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
        f"├ {_e(invalidation_label)}: <b>{_price(candidate.sl)}</b>\n"
        f"├ TP1: <b>{_price(candidate.tp1)}</b> • {candidate.rr_tp1:.2f}R • بستن {SETTINGS.partial_tp1_percent:.0f}%\n"
        f"└ TP2: <b>{_price(candidate.tp2)}</b> • {candidate.rr_tp2:.2f}R • بستن {SETTINGS.partial_tp2_percent:.0f}%\n\n"
        f"💼 <b>مدیریت سرمایه بهینه</b>\n"
        f"├ اندازه حساب: <b>${mm.get('account', 0):,.0f}</b>\n"
        f"├ ریسک محاسباتی تا ابطال: <b>{mm.get('risk_pct', 0):.2f}% = ${mm.get('risk_amount', 0):.2f}</b>\n"
        f"├ اهرم کیفیت‌محور و ایمن: <b>{mm.get('leverage', 1)}x</b> (سقف کیفیت {mm.get('quality_leverage_cap', 1)}x)\n"
        f"├ Margin پیشنهادی: <b>${mm.get('margin', 0):.2f} ({mm.get('margin_pct', 0):.1f}%)</b>\n"
        f"├ سقف Margin این کیفیت: <b>{mm.get('margin_limit_pct', 0):.1f}% حساب</b>\n"
        f"├ Position Size: <b>${mm.get('position_size', 0):,.0f}</b>\n"
        f"├ سود تقریبی TP1: <b>${mm.get('tp1_profit', 0):.2f}</b>\n"
        f"├ سود تقریبی TP2: <b>${mm.get('tp2_profit', 0):.2f}</b>\n"
        f"└ هزینه تخمینی Fee/Slippage: <b>${mm.get('estimated_roundtrip_cost', 0):.2f}</b>"
        f"{mm_warning}\n\n"
        f"📌 پیشنهاد سیستم: بعد از TP1، حد ضرر باقیمانده به Breakeven منتقل شود.\n"
        f"⚠️ لمس/عبور معتبر از {_price(candidate.sl)} سناریوی تحلیلی را باطل می‌کند.\n"
        f"🧭 {_e(management_note)}\n"
        f"📢 <b>{_e(SETTINGS.channel_name)}</b>"
    )


def send_educational_setup(candidate: SignalCandidate, chart_df: Optional[pd.DataFrame]) -> bool:
    target = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
    if not candidate.metadata.get("education_separator_attempted"):
        send_signal_separator(target)
        candidate.metadata["education_separator_attempted"] = True
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
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    if not candidate.metadata.get("approaching_separator_attempted"):
        send_signal_separator(target)
        candidate.metadata["approaching_separator_attempted"] = True
    return send_message(build_approaching_message(candidate, current_price, distance_atr), target)


def send_confirmed(candidate: SignalCandidate, chart_df: Optional[pd.DataFrame]) -> bool:
    """Publish both required components, resuming a partially completed attempt."""
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    if not candidate.metadata.get("confirmation_separator_attempted"):
        send_signal_separator(target)
        candidate.metadata["confirmation_separator_attempted"] = True

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
    target = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
    if not candidate.metadata.get("cancellation_separator_attempted"):
        send_signal_separator(target)
        candidate.metadata["cancellation_separator_attempted"] = True
    return send_message(
        f"ℹ️ <b>سناریوی آموزشی باطل شد</b>\n"
        f"🪙 {_e(candidate.symbol)} • {_e(candidate.style)}\n"
        f"🆔 <code>{_e(candidate.signal_id)}</code>\n\n"
        f"دلیل: {_e(reason)}\n\n"
        f"این Setup تأیید نشده بود و در Win Rate یا نتایج معاملات محاسبه نمی‌شود.",
        target,
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
    target = CHAT_ID_RESULTS or CHAT_ID_ADMIN
    send_signal_separator(target)
    return send_message(
        f"🥇 <b>TP1 HIT</b>\n"
        f"🪙 <b>{_e(signal['symbol'])}</b> • {_e(signal.get('style', ''))}\n"
        f"🆔 <code>{_e(signal['signal_id'])}</code>\n\n"
        f"✅ {SETTINGS.partial_tp1_percent:.0f}% پوزیشن بسته شد.\n"
        f"🔒 حد ضرر {SETTINGS.partial_tp2_percent:.0f}% باقی‌مانده به Breakeven منتقل شد.",
        target,
    )


def send_trade_result(event: dict) -> bool:
    result = event.get("result", "")
    if (
        event.get("event") != "CLOSED"
        or result not in {"WIN", "LOSS"}
        or not _published_lifecycle_event(event)
    ):
        return False
    target = CHAT_ID_RESULTS or CHAT_ID_ADMIN
    send_signal_separator(target)
    emoji = "✅" if result == "WIN" else "❌"
    return send_message(
        f"{emoji} <b>نتیجه سیگنال Confirmed</b>\n"
        f"🪙 <b>{_e(event.get('symbol'))}</b> • {_e(event.get('style', ''))}\n"
        f"🆔 <code>{_e(event.get('signal_id'))}</code>\n"
        f"📊 نتیجه: <b>{_e(result)}</b>\n"
        f"📈 بازده قیمت: <b>{float(event.get('pnl', 0)):+.2f}%</b>\n"
        f"💰 P&amp;L تقریبی: <b>${float(event.get('profit_usd', 0)):+.2f}</b>\n"
        f"📢 <b>{_e(SETTINGS.channel_name)}</b>",
        target,
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
