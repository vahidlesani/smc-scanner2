"""Clean, evidence-driven Telegram messages for Viva Signal Bot v7."""
from __future__ import annotations

import html
import io
import os
import threading
import time
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle
from matplotlib.ticker import FuncFormatter
import matplotlib.image as mpimg
import mplfinance as mpf
import numpy as np
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

# Chart identity: Viva's own TradingView look (light, monochrome candles,
# borderless pastel supply/demand boxes). CHART_STYLE=dark restores the old
# night theme; all colors remain overridable via the CHART_*_COLOR envs.
_CHART_PRESETS = {
    "light": {
        "figure": "#FFFFFF",
        "panel": "#FFFFFF",
        "grid": "#E6EAF1",
        "text": "#131722",
        "muted": "#6A7587",
        "bull": "#F2F4F7",
        "bear": "#131722",
        "entry": "#2962FF",
        "supply": "#F23645",
        "demand": "#089981",
        "supply_text": "#B81B29",
        "demand_text": "#06705E",
        "invalidation": "#F23645",
        "tp1": "#089981",
        "tp2": "#2962FF",
        "liquidity": "#7B3FF2",
        "structure": "#2962FF",
        "trend": "#131722",
    },
    "dark": {
        "figure": "#0B101A",
        "panel": "#111827",
        "grid": "#273449",
        "text": "#E5EDF7",
        "muted": "#94A3B8",
        "bull": "#00C2A8",
        "bear": "#FF5C6C",
        "entry": "#FFC857",
        "supply": "#FF5C6C",
        "demand": "#00C2A8",
        "supply_text": "#FF8B97",
        "demand_text": "#4AE3CE",
        "invalidation": "#FF4757",
        "tp1": "#39D98A",
        "tp2": "#00B8D9",
        "liquidity": "#A78BFA",
        "structure": "#38BDF8",
        "trend": "#E5EDF7",
    },
}
_STYLE_NAME = (os.getenv("CHART_STYLE", "light") or "light").lower()
_BASE = _CHART_PRESETS["dark" if _STYLE_NAME == "dark" else "light"]
CHART_THEME = {
    key: os.getenv(f"CHART_{key.upper()}_COLOR", default)
    for key, default in _BASE.items()
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
# v7.6 chart overlays (Viva's chart-design references)
_CHART_SCENARIO_ZIGZAG = os.getenv("CHART_SCENARIO_ZIGZAG", "on").strip().lower() in {"1", "on", "true", "yes"}
_CHART_RANGE_OVERLAY = os.getenv("CHART_RANGE_OVERLAY", "on").strip().lower() in {"1", "on", "true", "yes"}
_CHART_STRUCTURE_LINES = os.getenv("CHART_STRUCTURE_LINES", "on").strip().lower() in {"1", "on", "true", "yes"}


def _e(value) -> str:
    return html.escape(str(value), quote=False)


_TF_FA = {"1d": "روزانه", "4h": "۴ ساعته", "1h": "۱ ساعته", "15m": "۱۵ دقیقه", "5m": "۵ دقیقه"}


def _htf_context_fa(candidate: SignalCandidate) -> str:
    """Higher-timeframe context block for every alert message — where we are
    relative to important zones and what just broke (Viva's context rule)."""
    md = candidate.metadata or {}
    bits: List[str] = []
    ctx_tf = (md.get("tl_context_tf") or md.get("pin_ctx_tf") or md.get("context_tf") or "").strip()
    if ctx_tf:
        tf_fa = _TF_FA.get(ctx_tf, ctx_tf.upper())
        if candidate.setup_code == "TLBREAK" and md.get("tl_pattern_fa"):
            st = "شکسته شده" if md.get("tl_stage") == "JUST_BROKE" else "در آستانهٔ شکست است"
            bits.append(f"{md['tl_pattern_fa']} در تایم {tf_fa} {st}")
        elif candidate.setup_code == "PINVAL":
            bits.append(f"کانتکست معتبرسنج: تایم {tf_fa}")
        else:
            bits.append(f"کانتکست تحلیل: تایم {tf_fa}")
    if md.get("sweep_level"):
        bits.append("نقدینگی پشت سقف/کف قبلی جمع شده (Liquidity Sweep)")
    if md.get("structure_level"):
        bits.append("یک سطح ساختار مهم در تایم بالاتر شکسته شده (BOS/MSS)")
    if candidate.setup_code == "PINVAL":
        doji = "؛ دو‌جی کناری هم دیده می‌شود" if md.get("pin_has_doji") else ""
        bits.append(f"کندل داخل {md.get('pin_zone_fa', 'ناحیهٔ مهم')} شکل گرفته{doji}")
    if candidate.bias in ("BULLISH", "BEARISH"):
        bits.append("بایاس ساختاری: " + ("صعودی" if candidate.bias == "BULLISH" else "نزولی"))
    # v7.6 multi-timeframe read (computed at scan time by enrich_candidate_context)
    mtf = md.get("mtf_fa") or []
    zones = md.get("zones_fa") or []
    out = "🧭 <b>کانتکست مولتی‌تایم‌فریم</b>\n" + "\n".join(f"• {_e(b)}" for b in bits)
    if mtf:
        out += "\n\n⏱ <b>نمای تایم‌به‌تایم بازار</b>\n" + "\n".join(_e(line) for line in mtf)
    if zones:
        out += "\n\n🗺 <b>زون‌های مهم نزدیک قیمت</b>\n" + "\n".join(_e(line) for line in zones)
    return out


def _why_fa(candidate: SignalCandidate, limit: int = 6) -> str:
    """🔍 «چرا این هشدار صادر شد؟» — the plain-language confluence list every
    alert/signal must carry per Viva's v7.6 spec."""
    items: List[str] = []
    md = candidate.metadata or {}
    if candidate.strategy_fa:
        items.append(f"ستاپ: {candidate.strategy_fa}")
    for item in candidate.evidence:
        if item.confirmed:
            first_line = str(item.title or "").strip()
            if first_line:
                items.append(first_line)
    for conf in (candidate.confirmations or [])[:2]:
        first_line = str(conf).split(".")[0].split("؛")[0].strip()
        if first_line:
            items.append(first_line)
    if md.get("tl_pattern_fa"):
        items.append(str(md["tl_pattern_fa"]))
    if md.get("div_fa"):
        items.append(str(md["div_fa"]))
    deduped: List[str] = []
    seen = set()
    for item in items:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    body = "\n".join(f"• {_e(x)}" for x in deduped[:limit]) or "• شواهد ساختاری کامل شد."
    return f"🔍 <b>چرا این {'سیگنال' if candidate.status == 'CONFIRMED' else 'هشدار'} صادر شد؟</b>\n{body}"


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


_TG_LOCK = threading.Lock()
_TG_LAST_SENT = 0.0
_TG_MIN_GAP = float(os.getenv("TELEGRAM_MIN_SEND_GAP", "0.9"))


def _tg_pace(min_gap: Optional[float] = None) -> None:
    """Telegram hard rate limits: ~1 msg/s per chat, ~20 msg/min per group.
    A discovery burst can emit many alerts at once, so serialize all sends."""
    global _TG_LAST_SENT
    with _TG_LOCK:
        gap = _TG_MIN_GAP if min_gap is None else min_gap
        wait = gap - (time.monotonic() - _TG_LAST_SENT)
        if wait > 0:
            time.sleep(wait)
        _TG_LAST_SENT = time.monotonic()


def _tg_post(url: str, *, data: dict, files: Optional[dict] = None, timeout: int = 15) -> Optional[dict]:
    """POST with 429-retry honoring retry_after (max 3 attempts)."""
    for attempt in range(3):
        try:
            _tg_pace()
            response = requests.post(url, data=data, files=files, timeout=timeout)
        except Exception as exc:
            print(f"Telegram API error: {exc}")
            return None
        if response.ok:
            return response.json()
        if response.status_code == 429 and attempt < 2:
            retry_after = 5
            try:
                retry_after = int(response.json().get("parameters", {}).get("retry_after", 5))
            except Exception:
                pass
            print(f"Telegram 429 — retry in {retry_after + 1}s ({url.rsplit('/', 1)[-1]})")
            time.sleep(retry_after + 1)
            continue
        print(f"Telegram API {response.status_code}: {response.text[:240]}")
        return None
    return None


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


def send_message(
    text: str,
    chat_id: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
) -> Optional[int]:
    """Send text; returns the first chunk's message_id (truthy) or None."""
    target = chat_id or CHAT_ID_ADMIN
    if not TOKEN or not target:
        print("Telegram message skipped: missing TELEGRAM_TOKEN or target chat id")
        return None
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    first_id: Optional[int] = None
    for chunk in _chunks(text):
        payload = {
            "chat_id": target,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = int(reply_to_message_id)
            payload["allow_sending_without_reply"] = True
        result = _tg_post(url, data=payload, timeout=15)
        if result and first_id is None:
            first_id = int(result.get("result", {}).get("message_id") or 0) or None
    return first_id


def send_signal_separator(chat_id: Optional[str] = None) -> bool:
    """Separate complete lifecycle packages without splitting chart and text."""
    return bool(send_message(f"<b>{_e(SIGNAL_SEPARATOR)}</b>", chat_id))


def send_verdict_reply(candidate: SignalCandidate, ok: Optional[bool], note_fa: str) -> bool:
    """Reply ✅/❌/⚪ to the original alert message so the loop visibly closes
    within a few candles of every alert (Viva's confirmation-feedback rule)."""
    md = candidate.metadata or {}
    mid = md.get("education_message_id") or md.get("approaching_message_id")
    target = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
    if not mid:
        mid = md.get("approaching_message_id")
        target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    dir_fa = "صعودی 🟢" if candidate.direction == "LONG" else "نزولی 🔴"
    head = {True: "✅ <b>تأیید شد</b>", False: "❌ <b>تأیید نشد</b>", None: "⚪ <b>بدون تأیید</b>"}[ok]
    text = (
        f"{head}\n"
        f"🪙 {_e(candidate.symbol)} • {_e(candidate.strategy_fa)}\n"
        f"🧭 سناریوی {dir_fa}\n"
        f"{_e(note_fa)}\n"
        f"🆔 <code>{_e(candidate.signal_id)}</code>"
    )
    return bool(send_message(text, target, reply_to_message_id=mid))


def send_photo(
    image: bytes,
    caption: str,
    chat_id: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
) -> Optional[int]:
    target = chat_id or CHAT_ID_ADMIN
    if not TOKEN or not target or not image:
        return None
    payload = {"chat_id": target, "caption": caption[:1000], "parse_mode": "HTML"}
    if reply_to_message_id:
        payload["reply_to_message_id"] = int(reply_to_message_id)
        payload["allow_sending_without_reply"] = True
    result = _tg_post(
        f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
        data=payload,
        files={"photo": ("viva-chart.png", image, "image/png")},
        timeout=35,
    )
    if not result:
        return None
    return int(result.get("result", {}).get("message_id") or 0) or None


def _level_tag(ax, x: float, y: float, label: str, color: str) -> None:
    # readable text color based on the chip background luminance
    try:
        rgb = matplotlib.colors.to_rgb(color)
        lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        text_color = "#131722" if lum > 0.62 else "#FFFFFF"
    except Exception:
        text_color = "#FFFFFF"
    ax.text(
        x,
        y,
        label,
        color=text_color,
        fontsize=7.5,
        fontweight="bold",
        va="center",
        ha="left",
        zorder=12,
        bbox={"boxstyle": "round,pad=0.28", "facecolor": color, "edgecolor": "none", "alpha": 0.92},
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


def _scenario_path(ax, start, end, color: str, alpha: float = 0.85) -> None:
    """Viva's hand-drawn schematic path: a light zig-zag polyline confined to
    the candle-free right margin, ending in an arrowhead. It sketches the
    *shape* of the expected move (pullbacks inside the trend), not a laser
    line — matches the reference sketches he sent."""
    x0, y0 = start
    x1, y1 = end
    span_x = max(x1 - x0, 1e-9)
    delta_y = y1 - y0
    # alternating counter-bends sized as a fraction of total displacement
    fracs = (0.0, 0.2, 0.34, 0.5, 0.66, 0.8, 1.0)
    bends = (0.0, -0.11, 0.13, -0.12, 0.10, -0.08, 0.0)
    xs = [x0 + f * span_x for f in fracs]
    ys = [y0 + f * delta_y + b * abs(delta_y) for f, b in zip(fracs, bends)]
    ax.plot(xs, ys, color=color, linewidth=1.15, alpha=alpha, zorder=11, solid_capstyle="round")
    head = FancyArrowPatch(
        (xs[-2], ys[-2]),
        (xs[-1], ys[-1]),
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=0,
        color=color,
        alpha=alpha,
        transform=ax.transData,
        zorder=12,
    )
    ax.add_patch(head)


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


def _render_corner_notes(ax, notes: list, confirmed: bool = False) -> None:
    """All chart annotations live in ONE clean stack inside the candle-free
    right margin (Viva's rule: never print over candles). Each note is a small
    borderless chip; color encodes meaning."""
    y = 0.965
    for text, color in notes:
        ax.text(
            0.899, y, text,
            transform=ax.transAxes,
            ha="left", va="top",
            color=color,
            fontsize=6.4,
            fontweight="bold",
            zorder=15,
            bbox={"boxstyle": "round,pad=0.22", "facecolor": CHART_THEME["panel"],
                  "edgecolor": "none", "alpha": 0.88},
        )
        y -= 0.055


def generate_chart(df: pd.DataFrame, candidate: SignalCandidate, confirmed: bool = False) -> Optional[bytes]:
    """Render a branded TradingView-inspired 1440×900 chart."""
    if df is None or df.empty:
        return None
    try:
        frame = df.tail(100).copy().set_index("timestamp")
        frame.index = pd.DatetimeIndex(frame.index)
        if _STYLE_NAME == "dark":
            market_colors = mpf.make_marketcolors(
                up=CHART_THEME["bull"], down=CHART_THEME["bear"],
                edge="inherit", wick="inherit", volume="in",
            )
        else:  # light: Viva monochrome candles (hollow bull / solid bear)
            market_colors = mpf.make_marketcolors(
                up=CHART_THEME["bull"], down=CHART_THEME["bear"],
                edge={"up": "#131722", "down": "#131722"},
                wick={"up": "#131722", "down": "#131722"},
                volume={"up": "#D9DEE8", "down": "#AEB6C4"},
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
        future = 14 if confirmed else 10
        for chart_ax in axes:
            chart_ax.set_xlim(-1, count + future)

        # higher-context charts (TLBREAK 4h/1h or any 1d frame) render on a
        # log price axis so long-term trendline touches/breaks stay visible.
        notes = []
        md0 = candidate.metadata or {}
        ctx_for_log = md0.get("tl_context_tf")
        use_log = (
            getattr(SETTINGS, "chart_log_htf", True)
            and _STYLE_NAME != "dark"
            and (
                (candidate.setup_code == "TLBREAK" and ctx_for_log in ("4h", "1d"))
                or (candidate.trigger_timeframe == "1h" and float(frame["high"].max()) / max(float(frame["low"].min()), 1e-12) > 1.35)
            )
        )
        if use_log:
            try:
                ax.set_yscale("log")
            except Exception:
                use_log = False

        zone_start = max(0, count - 55)
        zone_end = count + future - 0.5  # box extends into the candle-free margin
        zone_color = CHART_THEME["demand"] if candidate.direction == "LONG" else CHART_THEME["supply"]
        zone_text_color = CHART_THEME["demand_text"] if candidate.direction == "LONG" else CHART_THEME["supply_text"]
        zone_name = "DEMAND ZONE  ·  POI / ENTRY" if candidate.direction == "LONG" else "SUPPLY ZONE  ·  POI / ENTRY"
        ax.fill_between(
            [zone_start, zone_end],
            candidate.entry_zone_bottom,
            candidate.entry_zone_top,
            color=zone_color,
            alpha=0.32,
            zorder=1,
            linewidth=0,
        )
        ax.text(
            count + 1.6,  # in the right margin, never over the candles
            (candidate.entry_zone_bottom + candidate.entry_zone_top) / 2,
            zone_name,
            color=zone_text_color,
            fontsize=7,
            va="center",
            ha="left",
            fontweight="bold",
            zorder=12,
            bbox={"boxstyle": "round,pad=0.26", "facecolor": CHART_THEME["panel"],
                  "edgecolor": "none", "alpha": 0.82},
        )

        # TLBREAK: draw the dynamic channel/trendline + parallel bound with
        # thin solid lines (Viva's chart style) using pivot timestamps.
        md = candidate.metadata or {}
        if md.get("tl_a_ts") and md.get("tl_b_ts"):
            try:
                idx = frame.index
                xa = float(np.searchsorted(idx, pd.Timestamp(str(md["tl_a_ts"]))))
                xb = float(np.searchsorted(idx, pd.Timestamp(str(md["tl_b_ts"]))))
                xanc = float(np.searchsorted(idx, pd.Timestamp(str(md.get("tl_anchor_ts") or md["tl_b_ts"]))))
                pa, pb = float(md["tl_a_price"]), float(md["tl_b_price"])
                if xb > xa:
                    slope = (pb - pa) / (xb - xa)
                    x_end = count + future - 0.5
                    ax.plot([xa, x_end], [pa, pa + slope * (x_end - xa)],
                            color=CHART_THEME["trend"], linewidth=1.2, alpha=0.9, zorder=8)
                    p_anc = float(md["tl_anchor_price"])
                    ax.plot([xanc, x_end], [p_anc, p_anc + slope * (x_end - xanc)],
                            color=CHART_THEME["trend"], linewidth=1.2, alpha=0.75, zorder=8)
                    stage = md.get("tl_stage", "")
                    pattern_en = (md.get("tl_pattern") or "CHANNEL").upper()
                    lbl = {"JUST_BROKE": f"{pattern_en} BREAK • {md.get('tl_context_tf','').upper()}",
                           "PRE_BREAK": f"{pattern_en} WATCH • {md.get('tl_context_tf','').upper()}"}.get(stage, pattern_en)
                    notes.append((lbl, CHART_THEME["trend"]))
            except Exception as exc:
                print(f"TLB chart line warning: {exc}")

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
        notes.append((f"INVALIDATION  {_price(candidate.sl)}", CHART_THEME["invalidation"]))

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
            notes.append((f"LIQUIDITY SWEEP  {_price(float(sweep_level))}", CHART_THEME["liquidity"]))
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
            notes.append((f"MSS / BOS  {_price(float(structure_level))}", CHART_THEME["structure"]))

        # The expected direction as one clean schematic path from the entry
        # zone towards TP1, fully inside the candle-free right margin
        # (Viva's sketch style: zig-zag polyline with an arrowhead).
        if not confirmed:
            try:
                _path_kwargs = dict(
                    ax=ax,
                    start=(count + 1.0, candidate.planned_entry),
                    end=(count + future - 2.5, candidate.tp1),
                    color=CHART_THEME["tp1"] if candidate.direction == "LONG" else CHART_THEME["invalidation"],
                    alpha=0.7,
                )
                if _CHART_SCENARIO_ZIGZAG:
                    _scenario_path(**_path_kwargs)
                else:
                    _scenario_arrow(**_path_kwargs)
                notes.append((f"EXPECTED MOVE → TP1  {_price(candidate.tp1)}",
                              CHART_THEME["tp1"]))
            except Exception:
                pass

        if confirmed:
            tool_start = max(0, count - 20)
            tool_end = count + 4.5
            # TradingView-style Long/Short position marker at the last candle.
            marker_price = candidate.planned_entry
            marker_x = count - 1
            if candidate.direction == "LONG":
                ax.scatter([marker_x], [marker_price], marker="^", s=130,
                           color=CHART_THEME["tp1"], zorder=16,
                           edgecolors=CHART_THEME["figure"], linewidths=0.8)
                pos_note = "▲ LONG POSITION"
                pos_color = CHART_THEME["tp1"]
            else:
                ax.scatter([marker_x], [marker_price], marker="v", s=130,
                           color=CHART_THEME["invalidation"], zorder=16,
                           edgecolors=CHART_THEME["figure"], linewidths=0.8)
                pos_note = "▼ SHORT POSITION"
                pos_color = CHART_THEME["invalidation"]
            notes.append((pos_note, pos_color))
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
            if _CHART_SCENARIO_ZIGZAG:
                _scenario_path(ax, (scenario_x[0], candidate.planned_entry),
                               (scenario_x[1], candidate.tp1), CHART_THEME["text"])
                _scenario_path(ax, (scenario_x[1], candidate.tp1),
                               (scenario_x[2], candidate.tp2), CHART_THEME["tp2"])
            else:
                _scenario_arrow(ax, (scenario_x[0], candidate.planned_entry),
                                (scenario_x[1], candidate.tp1), CHART_THEME["text"])
                _scenario_arrow(ax, (scenario_x[1], candidate.tp1),
                                (scenario_x[2], candidate.tp2), CHART_THEME["tp2"])
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

        # Swing highs/lows of the visible window — «سقف و کف» printed as clean
        # dotted guides (no text over candles, label goes to the corner stack).
        try:
            from analysis.indicators import pivots as _piv
            ph, pl = _piv(frame.reset_index(), 2, 2)
            if ph:
                hi = max(p["price"] for p in ph[-6:])
                ax.hlines(float(hi), max(0, count - 50), count + future - 0.5,
                          color=CHART_THEME["invalidation"], linestyle=(0, (1, 3)),
                          linewidth=0.8, alpha=0.5, zorder=4)
                notes.append((f"SWING HIGH  {_price(float(hi))}", CHART_THEME["invalidation"]))
            if pl:
                lo = min(p["price"] for p in pl[-6:])
                ax.hlines(float(lo), max(0, count - 50), count + future - 0.5,
                          color=CHART_THEME["demand"], linestyle=(0, (1, 3)),
                          linewidth=0.8, alpha=0.5, zorder=4)
                notes.append((f"SWING LOW  {_price(float(lo))}", CHART_THEME["demand"]))
        except Exception:
            pass

        # ── Viva v7.6 · valid trading range overlay ──────────────────────
        # If the frame contains a real range (top & bottom validated by >=2
        # pivot touches each), draw both boundaries across the chart and say
        # plainly whether price is INSIDE it (entry blocked until a break).
        if _CHART_RANGE_OVERLAY:
            try:
                from analysis.indicators import pivots as _rng_piv

                _reset = frame.reset_index()
                _rph, _rpl = _rng_piv(_reset, 3, 3)
                _tr = (frame["high"] - frame["low"]).tail(14)
                _atr_now = float(_tr.mean()) if len(_tr) else 0.0
                last_close = float(frame["close"].iloc[-1])
                if _atr_now > 0 and len(_rph) >= 2 and len(_rpl) >= 2:
                    def _validated(piv_list):
                        levels = []
                        for piv in piv_list:
                            price = float(piv["price"])
                            if any(abs(price - lv) <= 0.45 * _atr_now for lv in levels):
                                continue
                            touches = sum(
                                1 for p2 in piv_list
                                if abs(float(p2["price"]) - price) <= 0.55 * _atr_now
                            )
                            if touches >= 2:
                                levels.append(price)
                        return levels

                    his = _validated(_rph)
                    los = _validated(_rpl)
                    if his and los:
                        rhi = min(his, key=lambda v: abs(v - last_close))
                        rlo = min(los, key=lambda v: abs(v - last_close))
                        if rlo < rhi and (rhi - rlo) >= 2.2 * _atr_now:
                            ax.hlines(rhi, 0, count + future - 0.5,
                                      color=CHART_THEME["invalidation"],
                                      linestyle=(0, (8, 5)), linewidth=1.0, alpha=0.55, zorder=3)
                            ax.hlines(rlo, 0, count + future - 0.5,
                                      color=CHART_THEME["demand"],
                                      linestyle=(0, (8, 5)), linewidth=1.0, alpha=0.55, zorder=3)
                            notes.append((f"RANGE HIGH  {_price(rhi)}", CHART_THEME["invalidation"]))
                            notes.append((f"RANGE LOW  {_price(rlo)}", CHART_THEME["demand"]))
                            if rlo <= last_close <= rhi:
                                notes.append(("INSIDE RANGE · شکست معتبر تا ورود لازم است", CHART_THEME["muted"]))
                            else:
                                notes.append(("RANGE BROKEN · بیرون از رنج", CHART_THEME["muted"]))
            except Exception as exc:
                print(f"Range overlay warning: {exc}")

        # ── Viva v7.6 · dynamic trendline/channel on every chart ─────────
        # The same fitter that powers TLBREAK, projected onto whatever frame
        # is being drawn — dashed so it never fights a TLBREAK alert's own
        # solid lines. At most one structural pair per chart: no clutter.
        if _CHART_STRUCTURE_LINES and candidate.setup_code != "TLBREAK":
            try:
                from analysis.setups_experimental import _fit_channel_line

                _reset = frame.reset_index()
                _fdf = _reset[["timestamp", "open", "high", "low", "close", *([c for c in ("volume", "turnover") if c in _reset.columns])]]
                fit = _fit_channel_line(_fdf, candidate.direction)
                if fit:
                    x_a = float(fit["a"]["index"])
                    x_end = count + future - 0.5
                    p_a = float(fit["a"]["price"])
                    slope = float(fit["slope"])
                    ax.plot([x_a, x_end], [p_a, p_a + slope * (x_end - x_a)],
                            color=CHART_THEME["trend"], linestyle=(0, (7, 5)),
                            linewidth=0.95, alpha=0.7, zorder=3)
                    a_x = float(fit["anchor"]["index"])
                    a_p = float(fit["anchor"]["price"])
                    ax.plot([a_x, x_end], [a_p, a_p + slope * (x_end - a_x)],
                            color=CHART_THEME["trend"], linestyle=(0, (7, 5)),
                            linewidth=0.85, alpha=0.5, zorder=3)
                    line_label = "DYNAMIC RESISTANCE" if candidate.direction == "LONG" else "DYNAMIC SUPPORT"
                    notes.append((f"{line_label} · touch/break = هشدار", CHART_THEME["trend"]))
            except Exception as exc:
                print(f"Trendline overlay warning: {exc}")

        _render_corner_notes(ax, notes, confirmed=confirmed)

        # keep candle scale: long context lines may not stretch the y-axis
        _ylo = float(frame["low"].min())
        _yhi = float(frame["high"].max())
        _ylo = min(_ylo, float(candidate.entry_zone_bottom), float(candidate.sl))
        _yhi = max(_yhi, float(candidate.entry_zone_top), float(candidate.sl))
        if confirmed:
            _yhi = max(_yhi, float(candidate.tp2))
            _ylo = min(_ylo, float(candidate.tp1))
        _yr = max(_yhi - _ylo, 1e-9)
        ax.set_ylim(_ylo - 0.06 * _yr, _yhi + 0.06 * _yr)

        _tf_disp = (md.get("tl_context_tf") if candidate.setup_code == "TLBREAK" else None) \
            or md.get("pin_tf") or candidate.trigger_timeframe or ""
        fig.text(
            0.055,
            0.952,
            f"{candidate.symbol}  •  {str(_tf_disp).upper()}  •  {candidate.style}  •  {candidate.direction}",
            color=CHART_THEME["text"],
            fontsize=14,
            fontweight="bold",
            va="center",
        )
        fig.text(
            0.055,
            0.922,
            f"{candidate.setup_code}  ·  {_chart_market_label(candidate)}  ·  TRIG {candidate.trigger_timeframe.upper()}  ·  {'VIVA SETUP ✦ CONFIRMED' if confirmed else 'VIVA SETUP ✦ ANALYSIS'}",
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
        f"{_why_fa(candidate)}\n\n"
        + "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(evidence_blocks)
        + f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🔎 <b>ناحیه‌ای که زیر نظر داریم</b>\n\n"
        f"از <b>{_price(candidate.entry_zone_bottom)}</b> تا <b>{_price(candidate.entry_zone_top)}</b>\n"
        f"سطح ابطال سناریو: <b>{_price(candidate.sl)}</b>\n\n"
        f"{_htf_context_fa(candidate)}\n\n"
        f"🧩 <b>تأییدهای کمکی</b>\n{confirmations}\n\n"
        f"⚠️ <b>شرایط و هشدارها</b>\n{warnings}\n\n"
        f"⛔ Entry، اهرم و حجم پوزیشن هنوز پیشنهاد نمی‌شود.\n"
        f"✅ در صورت تکمیل شرایط، ابتدا Approaching و سپس Confirmed ارسال می‌شود.\n"
        f"📢 <b>{_e(SETTINGS.channel_name)}</b>"
    )


def _ai_note(candidate: SignalCandidate) -> str:
    """🤖 AI Suggestion block — deterministic multi-TF read produced by the
    engine (not an external LLM): regime, risk points, and the one thing that
    would improve or kill the setup."""
    md = candidate.metadata or {}
    lines: List[str] = []
    direction_fa = "صعودی 🟢" if candidate.direction == "LONG" else "نزولی 🔴"
    lines.append(f"بازار در این نماد فعلاً ساختار {direction_fa} می‌سازد.")
    if candidate.setup_code == "TLBREAK":
        stage = md.get("tl_stage")
        if stage == "PRE_BREAK":
            lines.append("قیمت هنوز پشت خط داینامیک است؛ ورود زودتر از Close معتبر یعنی شکار فیک‌اوت. صبر برای شکست.")
        else:
            lines.append("شکست با Close انجام شده؛ ورود فقط روی اولین بازگشت به بیس داخل کندل شکست — نه تعقیب قیمت.")
        if md.get("tl_touches", 0) >= 1:
            lines.append(f"خط فعال {int(md.get('tl_touches', 0))}+ برخورد قبلی دارد؛ اعتبار ساختاری بالاتر است.")
    elif candidate.setup_code == "P1234":
        lines.append("الگوی ۱-۲-۳-۴ فقط زمانی می‌ارزد که بازار پرانرژی باشد؛ در رنجِ خشک بهترین ترید «ننشستن» است.")
    if candidate.rr_tp1 < 1.3:
        lines.append(f"R:R فعلی ({candidate.rr_tp1:.2f}) زیر کف مهندسی است؛ اگر گیر کرد، بهتر است ناحیه تازه‌تر شود.")
    if not candidate.execution_ready:
        lines.append("یکی از گیت‌های اجباری هنوز سبز نیست؛ این تحلیل آموزشی است و وارد فاز اجرایی نمی‌شود.")
    adx_ctx = float(md.get("adx", 0) or 0)
    if adx_ctx >= 25:
        lines.append(f"روند پرانرژی است (ADX≈{adx_ctx:.0f})؛ پولبک‌های کوتاه‌مدت‌تر از انتظار معمول‌اند.")
    lines.append(f"ابطال سناریو: عبور معتبر از {_price(candidate.sl)} — قبل از آن هیچ تصمیمی نگیر.")
    return "🤖 <b>پیشنهاد هوش مصنوعی</b>\n" + "\n".join(f"• {_e(x)}" for x in lines)


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
        f"{_why_fa(candidate)}\n\n"
        f"🔎 در انتظار: {_e(waiting)}\n\n"
        f"{_htf_context_fa(candidate)}\n\n"
        f"{_ai_note(candidate)}\n\n"
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
        f"{_htf_context_fa(candidate)}\n\n"
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
        f"{_ai_note(candidate)}\n\n"
        f"📌 پیشنهاد سیستم: بعد از TP1، حد ضرر باقیمانده به Breakeven منتقل شود.\n"
        f"⚠️ لمس/عبور معتبر از {_price(candidate.sl)} سناریوی تحلیلی را باطل می‌کند.\n"
        f"🧭 {_e(management_note)}\n"
        f"📢 <b>{_e(SETTINGS.channel_name)}</b>"
    )


def _store_alert_message_id(candidate: SignalCandidate, key: str, mid: Optional[int]) -> None:
    if not mid:
        return
    candidate.metadata[key] = int(mid)
    try:
        from database.candidate_store import update_candidate as _persist
        _persist(candidate)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Alert message id persist warning {candidate.signal_id}: {exc}")


def send_educational_setup(candidate: SignalCandidate, chart_df: Optional[pd.DataFrame]) -> bool:
    target = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
    if not candidate.metadata.get("education_separator_attempted"):
        send_signal_separator(target)
        candidate.metadata["education_separator_attempted"] = True
    chart = generate_chart(chart_df, candidate, confirmed=False) if chart_df is not None else None
    if candidate.setup_code == "PINVAL":
        md = candidate.metadata or {}
        zone_fa = str(md.get("pin_zone_fa") or "ناحیه مهم")
        ctx_fa = _TF_FA.get(str(md.get("pin_ctx_tf") or ""), str(md.get("pin_ctx_tf") or "").upper())
        caption = (
            f"🚨 {_e(candidate.symbol)} • {_e(candidate.trigger_timeframe)} • پین‌بار "
            f"{'🟢 صعودی' if candidate.direction == 'LONG' else '🔴 نزولی'}\n"
            f"📍 داخل { _e(zone_fa) }" + (f" (کانتکست {_e(ctx_fa)})" if ctx_fa else "") + "\n"
            f"🆔 <code>{_e(candidate.signal_id)}</code>"
        )
    else:
        caption = (
            f"📚 {_e(candidate.symbol)} • {_e(candidate.style)} • {_e(candidate.setup_code)}\n"
            f"⛔ تأیید ورود نیست\n🆔 <code>{_e(candidate.signal_id)}</code>"
        )
    if chart:
        _store_alert_message_id(candidate, "education_chart_message_id",
                                send_photo(chart, caption, target))
    mid = send_message(build_educational_message(candidate), target)
    _store_alert_message_id(candidate, "education_message_id", mid)
    return bool(mid)


def send_approaching(candidate: SignalCandidate, current_price: float, distance_atr: float) -> bool:
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    if not candidate.metadata.get("approaching_separator_attempted"):
        send_signal_separator(target)
        candidate.metadata["approaching_separator_attempted"] = True
    mid = send_message(build_approaching_message(candidate, current_price, distance_atr), target)
    _store_alert_message_id(candidate, "approaching_message_id", mid)
    return bool(mid)


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
