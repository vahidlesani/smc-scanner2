"""Clean, evidence-driven Telegram messages for Viva Signal Bot v7."""
from __future__ import annotations

import html
import io
import os
import threading
import time
from typing import List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator, AutoMinorLocator
import matplotlib.image as mpimg
import mplfinance as mpf
import numpy as np
import pandas as pd
import requests

from analysis.models import SignalCandidate
from analysis.risk import build_money_management
from analysis.trade_management import build_ladder
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
        "figure": "#F8F1E7",
        "panel": "#FFF9F0",
        "grid": "#E6DDD0",
        "text": "#25272B",
        "muted": "#74716C",
        "bull": "#F3E7DA",
        "bear": "#3D4046",
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
        "trend": "#3D4046",
        "volume_up": "#C7A58A",
        "volume_down": "#96745F",
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
SETUP_STICKER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "stickers")
SIGNAL_SEPARATOR = os.getenv(
    "SIGNAL_SEPARATOR_TEXT",
    "━━━━━━━━━━ 💹 VIVASIGNALS PRO ━━━━━━━━━━",
)
        # v7.6 chart overlays (Viva's chart-design references)
_CHART_SCENARIO_ZIGZAG = os.getenv("CHART_SCENARIO_ZIGZAG", "off").strip().lower() in {"1", "on", "true", "yes"}
_CHART_RANGE_OVERLAY = os.getenv("CHART_RANGE_OVERLAY", "on").strip().lower() in {"1", "on", "true", "yes"}
_CHART_STRUCTURE_LINES = os.getenv("CHART_STRUCTURE_LINES", "on").strip().lower() in {"1", "on", "true", "yes"}


def _e(value) -> str:
    return html.escape(str(value), quote=False)

def _public_code(candidate: SignalCandidate) -> str:
    return str((candidate.metadata or {}).get("public_code") or candidate.signal_id)

def _iran_time(candidate: SignalCandidate) -> str:
    try:
        value = str(getattr(candidate, "confirmed_at", "") or candidate.created_at).replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def _candidate_send_latency(candidate: SignalCandidate) -> str:
    try:
        value = str(getattr(candidate, "confirmed_at", "") or candidate.created_at).replace("Z", "+00:00")
        then = datetime.fromisoformat(value)
        if then.tzinfo is None:
            then = then.replace(tzinfo=ZoneInfo("UTC"))
        seconds = max(0, int((datetime.now(ZoneInfo("UTC")) - then.astimezone(ZoneInfo("UTC"))).total_seconds()))
        return f"{seconds // 60}m {seconds % 60}s"
    except Exception:
        return "—"


_TF_FA = {"1d": "روزانه", "4h": "۴ ساعته", "1h": "۱ ساعته", "15m": "۱۵ دقیقه", "5m": "۵ دقیقه", "1m": "۱ دقیقه"}


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

    # v7.6.3 compact multi-TF read (Viva's rule: SHORT narrative — structure
    # bias of the higher TFs plus a natural-language note only when price is
    # near an important level).
    mtf = md.get("mtf_struct") or {}
    near = md.get("nearest_zones") or []
    style = candidate.style.upper()
    show_tfs = ("1d", "4h") if style == "SWING" else ("4h", "1h")
    if style == "SCALP":
        show_tfs = ("4h", "1h")
    seg = []
    for tf in show_tfs:
        row = mtf.get(tf)
        if not row:
            continue
        bias = row.get("bias", "NEUTRAL")
        bias_fa = {"BULLISH": "صعودی 🟢", "BEARISH": "نزولی 🔴", "NEUTRAL": "خنثی ⚪"}.get(bias, "خنثی ⚪")
        rsi_val = row.get("rsi")
        tag = ""
        if isinstance(rsi_val, (int, float)):
            if rsi_val >= 70:
                tag = " (RSI افراطی⚠️)"
            elif rsi_val <= 30:
                tag = " (RSI اشباع فروش⚠️)"
        seg.append(f"{_TF_FA.get(tf, tf.upper())}: {bias_fa}{tag}")
    if seg:
        bits.append("ساختار تایم‌های بالاتر → " + " | ".join(seg))
    allowed = {"1d", "4h"} if style == "SWING" else {"4h", "1h"}
    z_above = [z for z in near if z.get("side") == "above" and z.get("tf") in allowed]
    z_below = [z for z in near if z.get("side") == "below" and z.get("tf") in allowed]
    if z_above:
        z = z_above[0]
        if z["dist_atr"] <= 5:
            note = f"نزدیک‌ترین سطح بالای قیمت: سقف {_TF_FA.get(z['tf'], z['tf'])} {_price(z['level'])} (≈{z['dist_atr']} واحد نوسان)"
            if z["dist_atr"] <= 1.5:
                note += " — ⚠️ در همسایگی مقاومت مهم هستیم"
            bits.append(note)
    if z_below:
        z = z_below[0]
        if z["dist_atr"] <= 5:
            note = f"نزدیک‌ترین سطح زیر قیمت: کف {_TF_FA.get(z['tf'], z['tf'])} {_price(z['level'])} (≈{z['dist_atr']} واحد نوسان)"
            if z["dist_atr"] <= 1.5:
                note += " — ⚠️ در همسایگی حمایت مهم هستیم"
            bits.append(note)
    return "🧭 <b>کانتکست تایم بالاتر</b>\n" + "\n".join(f"• {_e(b)}" for b in bits)


def _confirm_rule_fa(candidate: SignalCandidate) -> str:
    """Viva's requirement: every alert states the confirmation condition AND
    the invalidation condition up front, in one glanceable line."""
    md = candidate.metadata or {}
    if candidate.setup_code == "PINVAL":
        tf_fa = _TF_FA.get(str(md.get("pin_tf") or ""), candidate.trigger_timeframe)
        n = int(md.get("pin_verdict_candles") or 3)
        hi, lo = float(md.get("pin_high") or 0), float(md.get("pin_low") or 0)
        if candidate.direction == "LONG":
            cond = f"کلوز {tf_fa} بالای {_price(hi)}"
            kill = f"کلوز {tf_fa} زیر {_price(lo)}"
        else:
            cond = f"کلوز {tf_fa} زیر {_price(lo)}"
            kill = f"کلوز {tf_fa} بالای {_price(hi)}"
        return f"⚖️ <b>شرط تأیید (تا {n} کندل {tf_fa} بعد):</b> {cond} • <b>ابطال:</b> {kill}"
    ctf = str(md.get("confirm_tf") or "").upper()
    ctf_fa = _TF_FA.get(str(md.get("confirm_tf") or "").lower(), ctf)
    return (
        f"⚖️ <b>شرط تأیید:</b> بازگشت به ناحیه + کلوز معتبر {ctf_fa} در جهت سناریو"
        f" • <b>ابطال:</b> عبور معتبر از {_price(candidate.sl)}"
    )


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


def delete_message(chat_id: str, message_id: int) -> bool:
    if not TOKEN or not chat_id or not message_id:
        return False
    result = _tg_post(
        f"https://api.telegram.org/bot{TOKEN}/deleteMessage",
        data={"chat_id": str(chat_id), "message_id": int(message_id)}, timeout=12,
    )
    return bool(result and result.get("ok"))


def purge_candidate_alert_posts(candidate: SignalCandidate) -> int:
    """Delete only this candidate's alert-channel package, never Pro/results."""
    target = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
    deleted = 0
    for key in ("education_chart_message_id", "education_message_id"):
        mid = candidate.metadata.get(key)
        if mid and delete_message(target, int(mid)):
            deleted += 1
    candidate.metadata["alert_posts_purged"] = True
    try:
        from database.candidate_store import update_candidate
        update_candidate(candidate)
    except Exception:
        pass
    return deleted


def purge_pro_watch_post(candidate: SignalCandidate) -> bool:
    """Remove only the compact final-watch post from VivaMon Labs Pro.
    Confirmed chart and all TP/trailing replies are never touched."""
    mid = candidate.metadata.get("approaching_message_id")
    sep = candidate.metadata.get("pro_separator_message_id")
    if not mid and not sep:
        return False
    ok = False
    if mid:
        ok = delete_message(CHAT_ID_EXECUTION or CHAT_ID_ADMIN, int(mid)) or ok
    if sep:
        ok = delete_message(CHAT_ID_EXECUTION or CHAT_ID_ADMIN, int(sep)) or ok
    if ok:
        candidate.metadata["pro_watch_post_purged"] = True
        try:
            from database.candidate_store import update_candidate
            update_candidate(candidate)
        except Exception:
            pass
    return ok


def purge_resolved_alert_posts(limit: int = 400) -> int:
    """Remove only resolved/duplicate educational posts from the alert channel.
    Confirmed execution and result channels are never touched."""
    from database.candidate_store import get_resolved_candidates, update_candidate
    target = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
    deleted = 0
    for candidate in get_resolved_candidates(limit):
        if candidate.metadata.get("alert_posts_purged"):
            continue
        deleted += purge_candidate_alert_posts(candidate)
    return deleted


def send_signal_separator(chat_id: Optional[str] = None) -> bool:
    """Separate complete lifecycle packages without splitting chart and text."""
    return bool(send_message(f"<b>{_e(SIGNAL_SEPARATOR)}</b>", chat_id))


def send_verdict_reply(candidate: SignalCandidate, ok: Optional[bool], note_fa: str) -> bool:
    """Reply ✅/❌/⚪ to the original alert message so the loop visibly closes
    within a few candles of every alert (Viva's confirmation-feedback rule)."""
    if candidate.status in {"CANCELLED", "EXPIRED", "SUPERSEDED", "VERDICT_NO", "VERDICT_TIMEOUT"}:
        return False
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
        f"🆔 <code>{_e(_public_code(candidate))}</code>"
    )
    return bool(send_message(text, target, reply_to_message_id=mid))


def send_photo(
    image: bytes,
    caption: str,
    chat_id: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    reply_markup: Optional[dict] = None,
) -> Optional[int]:
    target = chat_id or CHAT_ID_ADMIN
    if not TOKEN or not target or not image:
        return None
    payload = {"chat_id": target, "caption": caption[:1000], "parse_mode": "HTML"}
    if reply_to_message_id:
        payload["reply_to_message_id"] = int(reply_to_message_id)
        payload["allow_sending_without_reply"] = True
    if reply_markup:
        import json
        payload["reply_markup"] = json.dumps(reply_markup)
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


def _scenario_path(ax, start, end, color: str, alpha: float = 0.88) -> None:
    """A restrained candle-like projected path: two natural pullbacks, smooth
    segments and one precise arrowhead — not a cartoon zigzag."""
    x0, y0 = start
    x1, y1 = end
    dx, dy = max(x1 - x0, 1e-9), y1 - y0
    # small counter-swings preserve the direction of the scenario.
    fractions = (0.0, 0.26, 0.48, 0.72, 1.0)
    pullbacks = (0.0, -0.075, 0.045, -0.030, 0.0)
    xs = [x0 + dx * f for f in fractions]
    ys = [y0 + dy * f + abs(dy) * p for f, p in zip(fractions, pullbacks)]
    ax.plot(xs, ys, color=color, linewidth=1.35, linestyle=(0, (5, 3)),
            alpha=alpha, zorder=11, solid_capstyle="round", solid_joinstyle="round",
            antialiased=True)
    ax.add_patch(FancyArrowPatch(
        (xs[-2], ys[-2]), (xs[-1], ys[-1]), arrowstyle="-|>",
        mutation_scale=14, linewidth=0.0, color=color, alpha=alpha,
        transform=ax.transData, zorder=12,
    ))


def _add_setup_sticker(fig, candidate: SignalCandidate) -> None:
    path = os.path.join(SETUP_STICKER_DIR, f"{str(candidate.setup_code).lower()}.png")
    if not os.path.isfile(path):
        return
    try:
        # Header band keeps the branded setup sticker out of the candle area.
        # Separate high-resolution badge, kept in the empty upper-right margin.
        sticker_ax = fig.add_axes([0.685, 0.900, 0.070, 0.070], zorder=30)
        sticker_ax.imshow(mpimg.imread(path))
        sticker_ax.axis("off")
    except Exception as exc:
        print(f"Setup sticker warning: {exc}")


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
        f"{_public_code(candidate)}  •  {_chart_market_label(candidate)}",
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
    # Signature watermark lives behind price, deliberately subtle like a
    # TradingView publication watermark: actual logo + text, never above candles.
    if os.path.isfile(CHART_LOGO_PATH):
        try:
            mark_ax = ax.inset_axes([0.395, 0.315, 0.21, 0.37], transform=ax.transAxes, zorder=0)
            mark_ax.imshow(mpimg.imread(CHART_LOGO_PATH), alpha=0.050)
            mark_ax.set_axis_off()
            mark_ax.patch.set_alpha(0)
        except Exception as exc:
            print(f"Chart watermark warning: {exc}")
    ax.text(
        0.50, 0.50, CHART_BRAND_NAME.upper(), transform=ax.transAxes,
        ha="center", va="center", fontsize=31, fontweight="bold",
        color=CHART_THEME["text"], alpha=0.040, zorder=0,
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


def _setup_badge(candidate: SignalCandidate) -> tuple[str, str]:
    """Branded, setup-specific sticker used consistently on chart and caption."""
    code = str(candidate.setup_code or "SETUP").upper()
    labels = {
        "PINVAL": "VIVA ✦ PINWALL LEGACY",
        "PINWALLQ": "VIVA ✦ PINWALL QUALITY",
        "TLBREAK": "VIVA ✦ TLBREAK",
        "P1234": "VIVA ✦ 1-2-3-4",
        "ALBROX": "VIVA ✦ ALBROX",
        "LSR": "VIVA ✦ LIQUIDITY",
        "SDR": "VIVA ✦ SUPPLY/DEMAND",
        "BOS1": "VIVA ✦ BOS RETEST",
        "IFVG": "VIVA ✦ FVG FLIP",
        "TLR": "VIVA ✦ TREND RETEST",
    }
    color = CHART_THEME["structure"] if code in {"P1234", "BOS1", "IFVG"} else (CHART_THEME["trend"] if code == "TLBREAK" else CHART_THEME["demand"])
    return labels.get(code, f"VIVA ✦ {code}"), color


def _setup_stickers(candidate: SignalCandidate, confirmed: bool) -> list:
    """Small semantic chips. They label lifecycle/structure without covering price."""
    md = candidate.metadata or {}
    badge, badge_color = _setup_badge(candidate)
    chips = [(badge, badge_color), ("CONFIRMED" if confirmed else "FINAL WATCH", CHART_THEME["tp1"] if confirmed else CHART_THEME["entry"])]
    poi = str(md.get("poi_type") or "").upper()
    if "BASE" in poi or "ORDER_BLOCK" in poi:
        chips.append(("RBR / DBD BASE", CHART_THEME["demand"] if candidate.direction == "LONG" else CHART_THEME["supply"]))
    if md.get("pinv") or candidate.setup_code == "PINVAL":
        chips.append(("PIN REJECTION", CHART_THEME["structure"]))
    if md.get("structure_level"):
        chips.append(("MICRO BOS / MSS", CHART_THEME["structure"]))
    if md.get("target_event"):
        chips.append((str(md["target_event"]), CHART_THEME["tp1"]))
    visit = int(md.get("visit_index") or 1)
    if md.get("touched"):
        chips.append(("FIRST RETEST" if visit <= 1 else f"RETEST #{visit}", CHART_THEME["trend"]))
    return chips


def _render_corner_notes(ax, notes: list, frame: pd.DataFrame, confirmed: bool = False) -> None:
    """Compact annotation stack in the emptier LEFT chart corner.
    It keeps structural labels away from both live candles and the price ladder."""
    if not notes or frame is None or frame.empty:
        return
    lo, hi = ax.get_ylim()
    span = max(hi - lo, 1e-12)
    # Measure the oldest visible third: choose the larger of top/bottom empty
    # spaces, exactly where discretionary charting normally parks annotations.
    sample = frame.iloc[:max(12, len(frame) // 3)]
    top_empty = max(0.0, (hi - float(sample["high"].max())) / span)
    bottom_empty = max(0.0, (float(sample["low"].min()) - lo) / span)
    # Confirmed charts reserve upper-left for the Long/Short trade box.
    # Their structural notes therefore always use the lower-left empty corner.
    use_top = (top_empty >= bottom_empty) and not confirmed
    y = 0.968 if use_top else 0.055
    step = -0.043 if use_top else 0.043
    shown = notes[:9]
    for text, color in shown:
        ax.text(
            0.014, y, text,
            transform=ax.transAxes,
            ha="left", va="top" if use_top else "bottom",
            color=color, fontsize=5.8, fontweight="bold", zorder=15,
            bbox={"boxstyle": "round,pad=0.16", "facecolor": CHART_THEME["panel"],
                  "edgecolor": "none", "alpha": 0.82},
        )
        y += step


def _draw_visible_fvgs(ax, frame: pd.DataFrame, count: int) -> list:
    """Draw at most two fresh visible FVGs as subtle TradingView-like boxes."""
    found = []
    start = max(2, len(frame) - 90)
    for i in range(start, len(frame)):
        h0, l0 = float(frame["high"].iloc[i - 2]), float(frame["low"].iloc[i - 2])
        hi, lo = float(frame["high"].iloc[i]), float(frame["low"].iloc[i])
        if lo > h0:  # bullish imbalance
            bottom, top, color, tag = h0, lo, CHART_THEME["demand"], "BULL FVG"
        elif hi < l0:  # bearish imbalance
            bottom, top, color, tag = hi, l0, CHART_THEME["supply"], "BEAR FVG"
        else:
            continue
        later = frame.iloc[i + 1:]
        # Fresh: price has not fully traversed the gap afterwards.
        mitigated = bool((later["low"] <= bottom).any()) if tag == "BULL FVG" else bool((later["high"] >= top).any())
        if mitigated:
            continue
        found.append((i, bottom, top, color, tag))
    # closest/latest only — never turn the chart into a colored wallpaper.
    result = []
    for i, bottom, top, color, tag in found[-2:]:
        ax.add_patch(Rectangle((max(0, i - 2), bottom), count - max(0, i - 2), top - bottom,
                               facecolor=color, edgecolor=color, linewidth=0.7,
                               linestyle=(0, (3, 2)), alpha=0.09, zorder=0))
        result.append((tag, color))
    return result


def generate_chart(df: pd.DataFrame, candidate: SignalCandidate, confirmed: bool = False) -> Optional[bytes]:
    """Render a branded TradingView-inspired 1440×900 chart."""
    if df is None or df.empty:
        return None
    try:
        # Preserve enough history for real channel / wedge / range geometry;
        # the blank future panel is added separately, never by sacrificing bars.
        frame = df.tail(150).copy().set_index("timestamp")
        frame.index = pd.DatetimeIndex(frame.index)
        if _STYLE_NAME == "dark":
            market_colors = mpf.make_marketcolors(
                up=CHART_THEME["bull"], down=CHART_THEME["bear"],
                edge="inherit", wick="inherit", volume="in",
            )
        else:  # light: Viva monochrome candles (hollow bull / solid bear)
            market_colors = mpf.make_marketcolors(
                up=CHART_THEME["bull"], down=CHART_THEME["bear"],
                edge={"up": "#6C625C", "down": "#3D4046"},
                wick={"up": "#6C625C", "down": "#3D4046"},
                volume={"up": CHART_THEME["volume_up"], "down": CHART_THEME["volume_down"]},
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
            figsize=(15, 8.5),
            panel_ratios=(5.2, 1.05),
            update_width_config={"candle_linewidth": 0.72, "candle_width": 0.62, "volume_width": 0.62},
            datetime_format="%m-%d  %H:%M",
            xrotation=0,
            ylabel="",
            ylabel_lower="VOLUME",
            warn_too_much_data=500,
        )
        # mplfinance creates manually positioned axes, so set the panel geometry
        # directly: wide price area, compact volume, and a small branded footer.
        # Wide candle-free future area: at 120dpi this is ~7cm from the last
        # candle to the price ladder, leaving every chart label readable.
        price_position = [0.050, 0.235, 0.820, 0.665]
        volume_position = [0.050, 0.085, 0.820, 0.125]
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
        # mplfinance otherwise applies its default blue histogram edge. Keep
        # volume borders in the same muted nude family as their fill.
        if len(axes) > 2:
            for bar in getattr(axes[2], "patches", []):
                face = bar.get_facecolor()
                bar.set_edgecolor(face)
                bar.set_linewidth(0.35)
        for _price_ax in axes[:2]:
            _price_ax.yaxis.set_major_formatter(FuncFormatter(_axis_price))
        ax.tick_params(
            axis="y",
            colors=CHART_THEME["text"],
            labelsize=9.0,
            labelright=True,
            right=True,
            pad=12,
            length=4,
            width=0.8,
        )
        # TradingView-like readable price ladder: measured major intervals,
        # light minor guides, precise plain-number formatting on the right.
        ax.yaxis.set_major_locator(MaxNLocator(nbins=8, min_n_ticks=6))
        ax.yaxis.set_minor_locator(AutoMinorLocator(2))
        ax.grid(which="minor", axis="y", color=CHART_THEME["grid"], alpha=0.16, linewidth=0.45)
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
        # 30–34 bars of blank future space keeps the last candle roughly seven
        # centimetres from the price ladder / labels on the 12-inch render.
        future = 42 if confirmed else 40
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
                # set_yscale replaces the price formatter with matplotlib's
                # scientific log labels (4.38 × 10³); restore plain prices.
                ax.yaxis.set_major_formatter(FuncFormatter(_axis_price))
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
            count + 2.0,  # in the wide right margin, never over the candles
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
                            color=CHART_THEME["trend"], linewidth=1.65, alpha=0.92, zorder=8,
                            solid_capstyle="round", antialiased=True)
                    p_anc = float(md["tl_anchor_price"])
                    ax.plot([xanc, x_end], [p_anc, p_anc + slope * (x_end - xanc)],
                            color=CHART_THEME["trend"], linewidth=1.35, alpha=0.75, zorder=8,
                            solid_capstyle="round", antialiased=True)
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
        notes.append((f"FIRST STOP  {_price(candidate.sl)}", CHART_THEME["invalidation"]))
        live_price = float(frame["close"].iloc[-1])
        ax.hlines(live_price, max(0, count - 24), count + future - 0.5,
                  color=CHART_THEME["muted"], linewidth=0.9, linestyles=(0, (1, 3)), alpha=0.75, zorder=6)
        _level_tag(ax, count + 1.0, live_price, f"LIVE  {_price(live_price)}", CHART_THEME["muted"])

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
            ladder = (candidate.metadata or {}).get("target_ladder") or {}
            ladder_targets = list(ladder.get("targets") or [candidate.tp1, candidate.tp2])
            ladder_weights = list(ladder.get("weights") or [35, 35])
            levels = [
                (candidate.planned_entry, "ENTRY", CHART_THEME["entry"]),
                (candidate.sl, "FIRST STOP", CHART_THEME["invalidation"]),
            ]
            for i, level in enumerate(ladder_targets):
                label = f"TP{i+1} {float(ladder_weights[i]) if i < len(ladder_weights) else 0:.0f}%"
                levels.append((float(level), label, CHART_THEME["tp1"] if i < 3 else CHART_THEME["tp2"]))
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

            hit_index = int(ladder.get("hit_index") or (candidate.metadata or {}).get("hit_index") or 0)
            trailing_sl = float((candidate.metadata or {}).get("current_trailing_sl") or 0)
            if hit_index > 0 and trailing_sl > 0:
                ax.hlines(trailing_sl, tool_start, tool_end, color=CHART_THEME["liquidity"],
                          linewidth=1.25, linestyles=(0, (2, 2)), zorder=9)
                _level_tag(ax, tool_end + 0.35, trailing_sl,
                           f"TRAILING SL • TP{hit_index}  {_price(trailing_sl)}", CHART_THEME["liquidity"])

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
                                notes.append(("INSIDE RANGE · wait for a valid break", CHART_THEME["muted"]))
                            else:
                                notes.append(("RANGE BROKEN · outside the range", CHART_THEME["muted"]))
            except Exception as exc:
                print(f"Range overlay warning: {exc}")

        # ── VIVA-TLBREAK validated geometry overlay ─────────────────────
        if md.get("strategy_variant") == "VIVA_TLBREAK":
            try:
                for key, color, label in (("viva_upper_points", CHART_THEME["supply"], "VALID UPPER LINE"), ("viva_lower_points", CHART_THEME["demand"], "VALID LOWER LINE")):
                    points = md.get(key) or []
                    if len(points) < 2:
                        continue
                    xs, ys = [], []
                    for point in points:
                        ts = pd.Timestamp(str(point.get("timestamp")))
                        x = float(np.searchsorted(frame.index, ts))
                        xs.append(x); ys.append(float(point["price"]))
                    if len(xs) < 2:
                        continue
                    slope, intercept = np.polyfit(np.asarray(xs), np.asarray(ys), 1)
                    x0, x1 = min(xs), count + future - .5
                    ax.plot([x0, x1], [slope*x0+intercept, slope*x1+intercept], color=color, linewidth=1.65, alpha=.90, zorder=7, solid_capstyle="round")
                    ax.scatter(xs, ys, s=24, color=CHART_THEME["panel"], edgecolors=color, linewidths=1.1, zorder=9)
                    notes.append((f"{label} · {len(xs)} PIVOTS", color))
                line = md.get("viva_breakout_line") or md.get("viva_break_line")
                if line:
                    ax.hlines(float(line), max(0, count-45), count+future-.5, color=CHART_THEME["structure"], linewidth=1.15, linestyles=(0,(5,3)), zorder=6)
                    notes.append((f"BREAK LINE  {_price(float(line))}", CHART_THEME["structure"]))
                zone = md.get("viva_retest_zone")
                if zone and len(zone) == 2:
                    lo, hi = sorted(map(float, zone))
                    ax.fill_between([max(0,count-35), count+future-.5], lo, hi, color=CHART_THEME["liquidity"], alpha=.08, zorder=1)
                    notes.append(("RETEST ZONE", CHART_THEME["liquidity"]))
                watch_points = md.get("viva_watch_points") or []
                if len(watch_points) == 2:
                    xs, ys = [], []
                    for point in watch_points:
                        xs.append(float(np.searchsorted(frame.index, pd.Timestamp(str(point.get("timestamp"))))))
                        ys.append(float(point["price"]))
                    slope, intercept = np.polyfit(np.asarray(xs), np.asarray(ys), 1)
                    ax.plot([xs[0], count + future - .5], [slope*xs[0]+intercept, slope*(count+future-.5)+intercept], color=CHART_THEME["liquidity"], linewidth=1.25, linestyle=(0,(3,3)), alpha=.85, zorder=6)
                    ax.scatter(xs, ys, s=22, color=CHART_THEME["panel"], edgecolors=CHART_THEME["liquidity"], linewidths=1.0, zorder=9)
                    notes.append(("2-PIVOT WATCH · NO ENTRY", CHART_THEME["liquidity"]))
                score = md.get("viva_final_score")
                if score is not None:
                    notes.append((f"VIVA SCORE  {float(score):.1f}/10", CHART_THEME["text"]))
            except Exception as exc:
                print(f"Viva TLBREAK overlay warning: {exc}")

        # ── Viva v7.6 · dynamic trendline/channel on every chart ─────────
        # The same fitter that powers TLBREAK, projected onto whatever frame
        # is being drawn — dashed so it never fights a TLBREAK alert's own
        # solid lines. At most one structural pair per chart: no clutter.
        # A generic fitted trendline is never decoration. PINVAL/PINWALL/ALBROX
        # charts must not acquire unrelated black lines; non-TLBREAK setups opt
        # in only when their detector explicitly validated that overlay.
        if _CHART_STRUCTURE_LINES and candidate.setup_code != "TLBREAK" and bool(md.get("chart_validated_trendline")):
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
                            color=CHART_THEME["trend"], linestyle="-",
                            linewidth=1.45, alpha=0.84, zorder=3,
                            solid_capstyle="round", antialiased=True)
                    a_x = float(fit["anchor"]["index"])
                    a_p = float(fit["anchor"]["price"])
                    ax.plot([a_x, x_end], [a_p, a_p + slope * (x_end - a_x)],
                            color=CHART_THEME["trend"], linestyle="-",
                            linewidth=1.20, alpha=0.65, zorder=3,
                            solid_capstyle="round", antialiased=True)
                    ax.scatter([x_a, a_x], [p_a, a_p], s=18, color=CHART_THEME["panel"],
                               edgecolors=CHART_THEME["trend"], linewidths=0.9, zorder=8)
                    line_label = "DYNAMIC RESISTANCE" if candidate.direction == "LONG" else "DYNAMIC SUPPORT"
                    notes.append((f"{line_label} · touch/break alerts", CHART_THEME["trend"]))
            except Exception as exc:
                print(f"Trendline overlay warning: {exc}")

        # Semantic setup chips and fresh imbalances are visual context, not extra signals.
        notes = _setup_stickers(candidate, confirmed) + notes
        notes.extend(_draw_visible_fvgs(ax, frame, count))

        # keep candle scale: long context lines may not stretch the y-axis
        _ylo = float(frame["low"].min())
        _yhi = float(frame["high"].max())
        _ylo = min(_ylo, float(candidate.entry_zone_bottom), float(candidate.sl))
        _yhi = max(_yhi, float(candidate.entry_zone_top), float(candidate.sl))
        if confirmed:
            ladder_targets = list(((candidate.metadata or {}).get("target_ladder") or {}).get("targets") or [candidate.tp1, candidate.tp2])
            _yhi = max(_yhi, *[float(v) for v in ladder_targets])
            _ylo = min(_ylo, *[float(v) for v in ladder_targets])
        _yr = max(_yhi - _ylo, 1e-9)
        ax.set_ylim(_ylo - 0.06 * _yr, _yhi + 0.06 * _yr)

        _render_corner_notes(ax, notes, frame, confirmed=confirmed)

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
            f"{candidate.setup_code}  ·  {_chart_market_label(candidate)}  ·  TRIG {candidate.trigger_timeframe.upper()}"
            f"{' • VIEW ' + str(md.get('chart_view_tf')).upper() if md.get('chart_view_tf') else ''}  ·  {'VIVA SETUP ✦ CONFIRMED' if confirmed else 'VIVA SETUP ✦ ANALYSIS'}",
            color=CHART_THEME["muted"],
            fontsize=8,
            va="center",
        )
        _add_setup_sticker(fig, candidate)
        fig.text(0.762, 0.931, "VIVA SETUP ✳️", color=CHART_THEME["text"], fontsize=9.5, fontweight="bold", va="center")
        _add_branding(fig, ax, candidate)

        buffer = io.BytesIO()
        fig.savefig(
            buffer,
            format="png",
            dpi=180,
            facecolor=CHART_THEME["figure"],
            edgecolor="none",
        )
        plt.close(fig)
        buffer.seek(0)
        return buffer.read()
    except Exception as exc:
        print(f"Chart generation error {candidate.signal_id}: {exc}")
        return None


def _viva_tlbreak_sections(candidate: SignalCandidate) -> str:
    if (candidate.metadata or {}).get("strategy_variant") != "VIVA_TLBREAK":
        return ""
    from bot.messages_viva_tlbreak import detailed_warning_fa, ai_advisory_fa, management_fa
    md = candidate.metadata or {}
    final_target = float(md.get("viva_final_target") or candidate.tp2)
    return (
        detailed_warning_fa(md, candidate.direction)
        + "\n\n" + ai_advisory_fa(md, candidate.direction)
        + "\n\n" + management_fa(candidate.planned_entry, candidate.sl, final_target, candidate.direction)
    )


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
        f"🆔 <code>{_e(_public_code(candidate))}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(evidence_blocks)
        + f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🔎 <b>ناحیه‌ای که زیر نظر داریم</b>\n\n"
        f"از <b>{_price(candidate.entry_zone_bottom)}</b> تا <b>{_price(candidate.entry_zone_top)}</b>\n"
        f"سطح ابطال سناریو: <b>{_price(candidate.sl)}</b>\n\n"
        f"{_confirm_rule_fa(candidate)}\n\n"
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
        f"🆔 <code>{_e(_public_code(candidate))}</code>\n\n"
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
        f"🆔 <code>{_e(_public_code(candidate))}</code>\n"
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
        hi, lo = float(md.get("pin_high") or 0), float(md.get("pin_low") or 0)
        if candidate.direction == "LONG":
            rule = f"✅ کلوز بالای {_price(hi)} • ❌ کلوز زیر {_price(lo)}"
        else:
            rule = f"✅ کلوز زیر {_price(lo)} • ❌ کلوز بالای {_price(hi)}"
        caption = (
            f"🚨 {_e(candidate.symbol)} • {_e(candidate.trigger_timeframe)} • پین‌بار "
            f"{'🟢 صعودی' if candidate.direction == 'LONG' else '🔴 نزولی'}\n"
            f"📍 داخل {_e(zone_fa)}" + (f" (کانتکست {_e(ctx_fa)})" if ctx_fa else "") + "\n"
            f"{_e(rule)}\n"
            f"🕓 ایران: {_iran_time(candidate)}\n"
            f"🆔 <code>{_e(_public_code(candidate))}</code>"
        )
    else:
        caption = (
            f"📚 {_e(candidate.symbol)} • {_e(candidate.style)} • {_e(candidate.setup_code)}\n"
            f"⛔ تأیید ورود نیست\n🕓 ایران: {_iran_time(candidate)}\n🆔 <code>{_e(_public_code(candidate))}</code>"
        )
    if chart:
        _store_alert_message_id(candidate, "education_chart_message_id",
                                send_photo(chart, caption, target))
    mid = send_message(build_educational_message(candidate), target)
    _store_alert_message_id(candidate, "education_message_id", mid)
    return bool(mid)


def _approaching_ai_hint(candidate: SignalCandidate) -> str:
    md = candidate.metadata or {}
    if candidate.setup_code == "TLBREAK":
        return "فقط بعد از Close معتبر پشت خط و حفظ بیس وارد شو؛ تعقیب قیمت ممنوع."
    if candidate.setup_code == "PINVAL":
        return "پین‌بار فقط location است؛ تأیید با شکست micro-structure تایم پایین معتبر می‌شود."
    if md.get("nearest_zones"):
        return "زون نزدیک را ببین؛ تأیید تایم پایین را به‌خاطر هیجان حرکت جا ننداز."
    return "تا کلوز تأییدی و حفظ ابطال، این فقط سناریوی تحت‌نظر است."


def _ai_watch_hint(candidate: SignalCandidate) -> str:
    """One concise, deterministic assistant note; never an entry command."""
    md = candidate.metadata or {}
    if candidate.setup_code == "TLBREAK":
        return "فقط بعد از Close معتبر پشت خط و حفظ base؛ chase ممنوع."
    if candidate.setup_code == "PINVAL":
        return "پین‌بار فقط rejection است؛ ورود بعد از MSS/BOS تایم پایین."
    if md.get("structure_level"):
        return "تأیید فقط با شکست ساختار خرد پس از retest ناحیه معتبر است."
    return "سناریو زیر نظر است؛ تا کلوز تأییدی هیچ ورود اجرایی نداریم."


def _approaching_caption(candidate: SignalCandidate, current_price: float, distance_atr: float) -> str:
    why = candidate.strategy_fa
    badge, _ = _setup_badge(candidate)
    advisory = str((candidate.metadata or {}).get("gemini_advisory") or "").strip()
    ai_line = f"🤖 <b>نظر AI:</b> {_e(advisory)}\n" if advisory else ""
    return (
        f"🏷 <b>{_e(badge)}</b>\n"
        f"⚡ <b>هشدار نهایی | آماده‌سازی ورود</b> • {_e(candidate.setup_code)}\n"
        f"🪙 <b>{_e(candidate.symbol)}</b> • {_e(candidate.style)} • {_e(candidate.direction)}\n"
        f"🕓 زمان رصد — ایران: {_iran_time(candidate)}\n"
        f"📨 زمان ارسال — ایران: {_iran_now()}\n"
        f"🎯 {_e(why)} • ⭐ {candidate.score}/10\n"
        + ai_line +
        f"📍 زون: {_price(candidate.entry_zone_bottom)} – {_price(candidate.entry_zone_top)} • قیمت: {_price(current_price)}\n"
        f"⚖️ در انتظار کلوز تأییدی تایم پایین / MSS • فاصله {distance_atr:.2f} ATR\n"
        f"🛑 ابطال: {_price(candidate.sl)} • 🆔 <code>{_e(_public_code(candidate))}</code>"
    )


def send_approaching(candidate: SignalCandidate, current_price: float, distance_atr: float) -> bool:
    """Final watch alert belongs in Pro too, but compact and chart-backed.
    It is still NOT a confirmed entry."""
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    try:
        from data.fetcher import get_klines
        frame = get_klines(candidate.symbol, candidate.trigger_timeframe, 180, closed_only=False, use_cache=False)
        chart = generate_chart(frame, candidate, confirmed=False) if frame is not None else None
    except Exception:
        chart = None
    if not candidate.metadata.get("pro_separator_message_id"):
        candidate.metadata["pro_separator_message_id"] = send_message("<b>━━━━━━━━ VIVA-MON-LABS ━━━━━━━━</b>", target)
    caption = _approaching_caption(candidate, current_price, distance_atr)
    source_mid = candidate.metadata.get("education_chart_message_id") or candidate.metadata.get("education_message_id")
    source_link = _telegram_message_link(CHAT_ID_EDUCATION or CHAT_ID_ADMIN, int(source_mid)) if source_mid else ""
    markup = {"inline_keyboard": [[{"text": "📚 تحلیل و چارت هشدار اولیه", "url": source_link}]]} if source_link else None
    mid = send_photo(chart, caption, target, reply_markup=markup) if chart else send_message(caption, target, reply_markup=markup)
    _store_alert_message_id(candidate, "approaching_message_id", mid)
    return bool(mid)


def _exact_event_message_id(signal_id: str, event_key: str, fallback: int = 0) -> int:
    """Resolve one immutable Telegram receipt, never by symbol/timeframe/code."""
    try:
        from database.repository_v7 import get_telegram_event_message_id
        message_id = get_telegram_event_message_id(str(signal_id), str(event_key))
        if message_id:
            return int(message_id)
    except Exception as exc:
        print(f"Telegram receipt lookup warning {signal_id}/{event_key}: {exc}")
    return int(fallback or 0)


def _telegram_message_link(chat_id: str, message_id: int) -> str:
    """Member-visible direct channel/supergroup permalink."""
    raw = str(chat_id or "")
    if raw.startswith("-100"):
        return f"https://t.me/c/{raw[4:]}/{int(message_id)}"
    return ""


def _confirmed_chart_caption(candidate: SignalCandidate) -> str:
    mm = build_money_management(candidate)
    style_fa = {"DAYTRADE": "DAYTRADE", "SWING": "SWING", "SCALP": "SCALP"}.get(candidate.style.upper(), candidate.style)
    badge, _ = _setup_badge(candidate)
    advisory = str((candidate.metadata or {}).get("gemini_advisory") or "").strip()
    rows = [
        f"🏷 <b>{_e(badge)}</b>",
        f"✅ <b>سیگنال تأییدشده</b> • {_e(candidate.setup_code)}",
        f"🪙 <b>{_e(candidate.symbol)}</b> • {_e(candidate.trigger_timeframe)} • {_e(style_fa)} • {_e(candidate.direction)}",
        f"🕓 زمان تأیید — ایران: {_iran_time(candidate)}",
        f"📨 زمان ارسال — ایران: {_iran_now()}",
        f"📡 تأخیر ارسال: {_candidate_send_latency(candidate)}",
        "━━━━━━━━━━━━━━━━━━",
        f"🎯 Entry: <b>{_price(candidate.planned_entry)}</b>",
        f"🛑 First Stop: <b>{_price(candidate.sl)}</b>",
        f"📈 Live Price: <b>{_price(float((candidate.metadata or {}).get('live_price') or candidate.planned_entry))}</b>",
        *[f"🏁 TP{i+1}: {_price(level)} • {weight:.0f}%" for i, (level, weight) in enumerate(zip((candidate.metadata.get('target_ladder') or {}).get('targets', [candidate.tp1, candidate.tp2]), (candidate.metadata.get('target_ladder') or {}).get('weights', [35, 35])))],
        f"⚖️ R:R {candidate.rr_tp1:.2f} / {candidate.rr_tp2:.2f} • ⭐ {candidate.score}/10",
    ]
    if advisory:
        rows.append(f"🤖 <b>نظر AI:</b> {_e(advisory)}")
    if mm:
        rows.extend([
            "━━━━━━━━━━━━━━━━━━",
            f"💼 حجم پوزیشن: <b>${mm['position_size']:,.0f}</b>",
            f"🧱 مارجین: <b>${mm['margin']:,.2f}</b>",
            f"⚙️ اهرم: <b>{mm['leverage']}x</b>",
            f"🛡 ریسک: <b>{mm['risk_pct']:.2f}%</b>",
        ])
    rows.append(f"🆔 <code>{_e(candidate.metadata.get('public_code') or candidate.signal_id)}</code>")
    return "\n".join(rows)


def send_confirmed(candidate: SignalCandidate, chart_df: Optional[pd.DataFrame]) -> bool:
    """Execution channel is intentionally chart-first: confirmed trade numbers
    plus a one-click link back to its educational alert/chart."""
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    candidate.metadata["target_ladder"] = build_ladder(candidate.planned_entry, candidate.sl, candidate.direction, candidate.market, candidate.tp2)
    if chart_df is not None and not chart_df.empty and "close" in chart_df.columns:
        candidate.metadata["live_price"] = float(chart_df["close"].iloc[-1])
    if not candidate.metadata.get("confirmation_chart_sent"):
        chart = generate_chart(chart_df, candidate, confirmed=True) if chart_df is not None else None
        if not chart:
            print(f"Confirmed publication blocked: chart unavailable for {candidate.signal_id}")
            return False
        source_chat = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
        source_mid = candidate.metadata.get("education_chart_message_id") or candidate.metadata.get("education_message_id")
        link = _telegram_message_link(source_chat, int(source_mid)) if source_mid else ""
        keyboard = {"inline_keyboard": [[{"text": "📚 چارت و توضیحات هشدار اولیه", "url": link}]]} if link else None
        watch_mid = candidate.metadata.get("approaching_message_id")
        mid = send_photo(chart, _confirmed_chart_caption(candidate), target,
                         reply_to_message_id=int(watch_mid) if watch_mid else None,
                         reply_markup=keyboard)
        if not mid:
            return False
        candidate.metadata["confirmation_chart_message_id"] = int(mid)
        candidate.metadata["confirmation_chart_sent"] = True
    # Deliberately no second verbose message in VivaMon Labs Pro.
    candidate.metadata["confirmation_message_sent"] = True
    return True


def send_candidate_cancelled(candidate: SignalCandidate, reason: str) -> bool:
    """A cancelled educational scenario disappears from the alert feed instead
    of becoming another noisy cancellation post. Confirmed/result channels are untouched."""
    removed = purge_candidate_alert_posts(candidate)
    pro_removed = purge_pro_watch_post(candidate)
    print(f"Alert removed {candidate.signal_id}: {reason} • alert_posts={removed} pro_watch={pro_removed}")
    return True


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


def _event_clock(event: dict) -> tuple[str, str, str]:
    def parse(value):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            return dt
        except Exception: return None
    opened, happened = parse(event.get("confirmed_at")), parse(event.get("event_at"))
    iran = happened.astimezone(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M:%S") if happened else "—"
    if opened and happened:
        delta = happened - opened
        mins = max(0, int(delta.total_seconds() // 60))
        duration = f"{mins//1440:02d}D {mins%1440//60:02d}H {mins%60:02d}M"
    else: duration = "—"
    # This is message-publication latency from the closed market event, not
    # trade duration. Keep it explicit so channel timing is auditable.
    if happened:
        lag_seconds = max(0, int((datetime.now(ZoneInfo("UTC")) - happened.astimezone(ZoneInfo("UTC"))).total_seconds()))
        latency = f"{lag_seconds // 60}m {lag_seconds % 60}s"
    else:
        latency = "—"
    return iran, duration, latency


def _setup_display(value: str) -> str:
    code = str(value or "").upper()
    return {
        "PINVAL": "PINWALL LEGACY", "PINWALLQ": "PINWALL QUALITY",
        "PINWALL_QUALITY": "PINWALL QUALITY", "ALBROX": "ALBROX ORIGINAL",
        "TLBREAK": "VIVA-TLBREAK",
    }.get(code, code or "SETUP")


def _event_timing_lines(event: dict) -> str:
    """One consistent, audit-friendly timing block for every lifecycle post."""
    def iran(value):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            return dt.astimezone(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "—"
    event_iran, duration, latency = _event_clock(event)
    return (
        f"🕓 Confirmed — ایران: <b>{iran(event.get('confirmed_at'))}</b>\n"
        f"🕑 رویداد بازار — ایران: <b>{event_iran}</b>\n"
        f"📨 ارسال ربات — ایران: <b>{_iran_now()}</b>\n"
        f"📡 تأخیر ارسال: <b>{latency}</b>  •  ⏱ مدت پوزیشن: <b>{duration}</b>"
    )


def _tp_status_lines(event: dict) -> str:
    hit = max(0, min(5, int(event.get("hit_index") or 0)))
    weights = [35, 35, 20, 5, 5]
    rows = []
    for i, weight in enumerate(weights, start=1):
        state = "✓ بسته شد" if i <= hit else "○ در انتظار"
        rows.append(f"TP{i}  |  {weight}%  |  {state}")
    return "\n".join(rows)


def send_tp1_event(signal: dict) -> bool:
    if not str(signal.get("event") or "").startswith("TP") or not _published_lifecycle_event(signal):
        return False
    target = CHAT_ID_RESULTS or CHAT_ID_ADMIN
    send_signal_separator(target)
    event_key = str(signal.get("event") or "TP1")
    link_id = _exact_event_message_id(
        str(signal.get("signal_id") or ""), event_key,
        int(signal.get("pro_event_message_id") or signal.get("first_tp_message_id") or signal.get("pro_message_id") or 0),
    )
    link = _telegram_message_link(CHAT_ID_EXECUTION or CHAT_ID_ADMIN, link_id)
    code = _e(signal.get("public_code") or signal.get("signal_id"))
    code_line = f'<a href="{link}">🆔 <code>{code}</code></a>' if link else f"🆔 <code>{code}</code>"
    setup = _setup_display(signal.get("source") or signal.get("strategy_fa"))
    return send_message(
        f"🎯 <b>{_e(signal.get('event') or 'TP')} HIT</b>\n"
        f"🏷 <b>{_e(setup)}</b>\n{code_line}\n\n"
        f"🪙 <b>{_e(signal['symbol'])}</b> • {_e(signal.get('trigger_timeframe') or signal.get('style', ''))} • {_e(signal.get('style',''))} • {_e(signal.get('direction',''))}\n"
        f"{_event_timing_lines(signal)}\n\n"
        f"🎯 Entry: <b>{_price(float(signal.get('entry') or 0))}</b>\n"
        f"🛑 First Stop: <b>{_price(float(signal.get('original_sl') or 0))}</b>\n"
        f"📈 Live Price: <b>{_price(float(signal.get('live_price') or 0))}</b>\n\n"
        f"📊 <b>خروج این پله</b>\n"
        f"• حجم بسته‌شده: <b>{float(signal.get('weight', 0)):.0f}%</b>\n"
        f"• حرکت قیمت: <b>{float(signal.get('leg_price_move_pct', 0)):+.2f}%</b>\n"
        f"• سود پله: <b>${float(signal.get('leg_profit_usd', 0)):+.2f}</b>\n"
        f"• بازده پله با اهرم: <b>{float(signal.get('leg_full_roi_pct', 0)):+.2f}%</b>\n"
        f"• اثر بر کل مارجین: <b>{float(signal.get('leg_margin_roi_pct', 0)):+.2f}%</b>\n\n"
        f"🔒 Trailing SL: <b>{_price(float(signal.get('new_sl') or signal.get('sl') or 0))}</b>",
        target,
    )


def _final_lifecycle_anchor(event: dict) -> int:
    """Choose the only valid parent for a final result of this exact position.

    Initial-stop LOSS belongs below its own Confirmed chart.  A WIN belongs
    below the last reached TP (TP1..TP5), including a protected remainder that
    exits at Entry+5 ticks / prior-TP+5 ticks.
    """
    signal_id = str(event.get("signal_id") or "")
    result = str(event.get("result") or "").upper()
    hit_index = max(0, min(5, int(event.get("hit_index") or 0)))
    if result == "WIN" and hit_index:
        return _exact_event_message_id(signal_id, f"TP{hit_index}")
    return _exact_event_message_id(signal_id, "CONFIRMED", int(event.get("pro_message_id") or 0))


def send_no_fill_event(event: dict) -> bool:
    """Close an untouched confirmed scenario without creating a trade result."""
    if str(event.get("event") or "") != "NO_FILL":
        return False
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    reply_id = _exact_event_message_id(
        str(event.get("signal_id") or ""), "CONFIRMED", int(event.get("pro_message_id") or 0)
    ) or None
    code = _e(event.get("public_code") or event.get("signal_id"))
    reason = "کندل ورود و استاپ هم‌زمان بود؛ ترتیب اجرا از OHLC قابل اثبات نیست." if event.get("reason") == "AMBIGUOUS_ENTRY_STOP_SAME_CANDLE" else "قیمت در مهلت تعیین‌شده به Entry نرسید."
    return bool(send_message(
        f"⚪ <b>NO FILL • NO TRADE</b> • <code>{code}</code>\n\n"
        f"🪙 {_e(event.get('symbol'))} • {_e(event.get('trigger_timeframe') or event.get('style'))}\n"
        f"🎯 Entry: <b>{_price(float(event.get('entry') or 0))}</b>\n"
        f"📌 {reason}\n"
        f"این سناریو Cancelled شد؛ <b>نه Win است، نه Loss و در Win Rate حساب نمی‌شود.</b>",
        target, reply_to_message_id=reply_id
    ))


def _lifecycle_chart_frame(candidate: SignalCandidate, levels: list[float]) -> Optional[pd.DataFrame]:
    """Keep the full fixed trade tool visible without stretching the chart.

    Render the trigger TF first. Escalate only when Entry/First Stop/TP ladder
    would leave the visible price range: 15m→30m→1h and 1h→2h→4h.
    """
    from data.fetcher import get_klines
    trigger = str(candidate.trigger_timeframe or "15m").lower()
    chains = {
        "5m": ["5m", "15m", "30m", "1h"],
        "15m": ["15m", "30m", "1h"],
        "1h": ["1h", "2h", "4h"],
    }
    choices = chains.get(trigger, [trigger])
    usable = [float(v) for v in levels if float(v or 0) > 0]
    fallback = None
    for tf in choices:
        frame = get_klines(candidate.symbol, tf, 180, closed_only=False, use_cache=False)
        if frame is None or frame.empty:
            continue
        fallback = frame
        low, high = float(frame["low"].min()), float(frame["high"].max())
        pad = max(high - low, 1e-12) * 0.04
        if not usable or (min(usable) >= low - pad and max(usable) <= high + pad):
            candidate.metadata["chart_view_tf"] = tf
            return frame
    if fallback is not None:
        candidate.metadata["chart_view_tf"] = choices[-1]
    return fallback


def send_trade_close_event(event: dict) -> bool:
    """Final result with a live chart under its exact lifecycle parent."""
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    reply_id = _final_lifecycle_anchor(event) or None
    result = str(event.get("result") or "")
    emoji = "✅" if result == "WIN" else "❌" if result == "LOSS" else "⚪"
    code = _e(event.get("public_code") or event.get("signal_id"))
    setup = _setup_display(event.get("source") or event.get("strategy_fa"))
    hit = int(event.get("hit_index") or 0)
    exit_kind = "FULL TP5" if hit >= 5 else (f"TP{hit} + PROTECTED EXIT" if result == "WIN" and hit else "INITIAL STOP LOSS")
    text = (
        f"{emoji} <b>نتیجه نهایی پوزیشن</b>\n"
        f"🏷 <b>{_e(setup)}</b>\n"
        f"🆔 <code>{code}</code>\n\n"
        f"🪙 {_e(event.get('symbol'))} • {_e(event.get('trigger_timeframe') or event.get('style'))} • {_e(event.get('style'))} • {_e(event.get('direction'))}\n"
        f"{_event_timing_lines(event)}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n🎯 Entry: <b>{_price(float(event.get('entry') or 0))}</b>\n"
        f"🛑 First Stop: <b>{_price(float(event.get('original_sl') or 0))}</b>\n"
        f"📈 Live / Exit Price: <b>{_price(float(event.get('live_price') or 0))}</b>\n"
        f"🏁 TPهای زده‌شده: <b>{hit}/5</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n📌 نوع خروج: <b>{exit_kind}</b>\n"
        f"💰 سود/ضرر نهایی: <b>${float(event.get('profit_usd') or 0):+.2f}</b>\n"
        f"📈 بازده قیمت: <b>{float(event.get('pnl') or 0):+.2f}%</b>\n"
        f"🚀 اثر نهایی بر کل مارجین: <b>{float(event.get('margin_roi_pct') or 0):+.2f}%</b>\n"
        f"📍 نتیجه: <b>{_e(result)}</b>"
    )
    try:
        candidate = _event_chart_candidate(event)
        ladder = (candidate.metadata or {}).get("target_ladder") or {}
        frame = _lifecycle_chart_frame(candidate, [candidate.planned_entry, candidate.sl, *(ladder.get("targets") or []), (candidate.metadata or {}).get("current_trailing_sl", 0)])
        chart = generate_chart(frame, candidate, confirmed=True) if frame is not None else None
    except Exception:
        chart = None
    if chart:
        return bool(send_photo(chart, text, target, reply_to_message_id=reply_id))
    return bool(send_message(text, target, reply_to_message_id=reply_id))


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
    anchor_mid = _final_lifecycle_anchor(event)
    link = _telegram_message_link(CHAT_ID_EXECUTION or CHAT_ID_ADMIN, anchor_mid)
    code = _e(event.get("public_code") or event.get("signal_id"))
    link_line = f'<a href="{link}">🆔 <code>{code}</code></a>\n' if link else f"🆔 <code>{code}</code>\n"
    setup = _setup_display(event.get("source") or event.get("strategy_fa"))
    return send_message(
        f"{emoji} <b>نتیجه نهایی Confirmed</b>\n"
        f"🏷 <b>{_e(setup)}</b>\n{link_line}\n"
        f"🪙 <b>{_e(event.get('symbol'))}</b> • {_e(event.get('trigger_timeframe') or event.get('style', ''))} • {_e(event.get('style', ''))} • {_e(event.get('direction',''))}\n"
        f"{_event_timing_lines(event)}\n\n"
        f"🎯 Entry: <b>{_price(float(event.get('entry') or 0))}</b>\n"
        f"🛑 First Stop: <b>{_price(float(event.get('original_sl') or 0))}</b>\n"
        f"📈 Live / Exit Price: <b>{_price(float(event.get('live_price') or 0))}</b>\n"
        f"🏁 TPهای زده‌شده: <b>{int(event.get('hit_index') or 0)}/5</b>\n\n"
        f"💰 سود/ضرر نهایی: <b>${float(event.get('profit_usd', 0)):+.2f}</b>\n"
        f"📈 بازده قیمت: <b>{float(event.get('pnl', 0)):+.2f}%</b>\n"
        f"🚀 اثر نهایی بر کل مارجین: <b>{float(event.get('margin_roi_pct') or 0):+.2f}%</b>\n"
        f"📌 نتیجه: <b>{_e(result)}</b>\n"
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


def _iran_now() -> str:
    return datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M")


def _event_chart_candidate(event: dict) -> SignalCandidate:
    targets = list(event.get("targets") or [])
    entry = float(event.get("entry") or 0)
    sl = float(event.get("original_sl") or event.get("sl") or 0)
    tp1 = float(targets[0]) if targets else entry
    tp2 = float(targets[1]) if len(targets) > 1 else tp1
    direction = str(event.get("direction") or "LONG").upper()
    risk = max(abs(entry - sl), 1e-12)
    rr1, rr2 = abs(tp1-entry)/risk, abs(tp2-entry)/risk
    return SignalCandidate(
        signal_id=str(event.get("signal_id") or ""), symbol=str(event.get("symbol") or ""),
        style=str(event.get("style") or "DAYTRADE"), setup_code=str(event.get("source") or "SETUP"),
        setup_name=str(event.get("source") or "SETUP"), strategy_fa=str(event.get("strategy_fa") or event.get("source") or "SETUP"),
        direction=direction, score=0, status="CONFIRMED", entry_zone_bottom=entry,
        entry_zone_top=entry, planned_entry=entry, sl=sl, tp1=tp1, tp2=tp2,
        rr_tp1=rr1, rr_tp2=rr2, bias="BULLISH" if direction == "LONG" else "BEARISH",
        # Final live chart must stay on the position's own trigger timeframe.
        trigger_timeframe=str(event.get("trigger_timeframe") or ("5m" if str(event.get("style")) == "SCALP" else "15m")),
        metadata={
            "target_event": str(event.get("event") or ""),
            "public_code": event.get("public_code") or event.get("signal_id"),
            # Static Entry / First Stop / five TP geometry is carried into
            # every lifecycle chart. Only live price and the trailing line move.
            "target_ladder": {
                "targets": targets or build_ladder(entry, sl, direction, {}, tp2).get("targets", []),
                "weights": [35, 35, 20, 5, 5],
                "hit_index": int(event.get("hit_index") or 0),
            },
            "current_trailing_sl": float(event.get("sl") or event.get("new_sl") or 0),
        },
    )


def send_ladder_event(event: dict) -> bool:
    """Detailed live TP/trailing reply in VivaMon."""
    kind = str(event.get("event") or "")
    if kind not in {"TP1", "TP2", "TP3", "TP4", "TP5", "TRAIL_STOP", "STOP"}:
        return False
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    reply_id = (int(event.get("last_tp_message_id") or 0) or int(event.get("pro_message_id") or 0) or None) if kind.startswith("TP") else (int(event.get("pro_message_id") or 0) or None)
    code = _e(event.get("public_code") or event.get("signal_id"))
    setup = _setup_display(event.get("source") or event.get("strategy_fa"))
    common = (
        f"🏷 <b>{_e(setup)}</b>\n"
        f"🆔 <code>{code}</code>\n\n"
        f"🪙 <b>{_e(event.get('symbol'))}</b> • {_e(event.get('trigger_timeframe') or event.get('style'))} • {_e(event.get('style'))} • {_e(event.get('direction'))}\n"
        f"{_event_timing_lines(event)}\n\n"
        f"🎯 Entry: <b>{_price(float(event.get('entry') or 0))}</b>\n"
        f"🛑 First Stop: <b>{_price(float(event.get('original_sl') or 0))}</b>\n"
        f"📈 Live Price: <b>{_price(float(event.get('live_price') or 0))}</b>\n"
    )
    if kind.startswith("TP"):
        text = (
            f"🎯 <b>{_e(kind)} HIT</b>\n\n" + common + "\n"
            f"━━━━━━━━━━━━━━━━━━\n📍 <b>وضعیت اهداف</b>\n{_tp_status_lines(event)}\n"
            f"━━━━━━━━━━━━━━━━━━\n📊 <b>جزئیات این پله</b>\n"
            f"• حجم بسته‌شده: <b>{float(event.get('weight', 0)):.0f}%</b>\n"
            f"• حرکت قیمت: <b>{float(event.get('leg_price_move_pct', 0)):+.2f}%</b>\n"
            f"• سود پله: <b>${float(event.get('leg_profit_usd', 0)):+.2f}</b>\n"
            f"• بازده پله با اهرم: <b>{float(event.get('leg_full_roi_pct', 0)):+.2f}%</b>\n"
            f"• اثر بر کل مارجین: <b>{float(event.get('leg_margin_roi_pct', 0)):+.2f}%</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n💼 مارجین: <b>${float(event.get('margin') or 0):.2f}</b>\n"
            f"⚙️ اهرم: <b>{int(event.get('leverage') or 1)}x</b>\n"
            f"🔒 Trailing SL جدید: <b>{_price(float(event.get('new_sl') or event.get('sl') or 0))}</b>"
        )
    else:
        hit_index = max(0, min(5, int(event.get("hit_index") or 0)))
        if kind == "TRAIL_STOP" and hit_index:
            # Once any TP is hit, the remaining size is a protected exit — it
            # must never be presented to members as a stop-loss.
            title = f"TP{hit_index} HIT • خروج محافظت‌شده باقی‌مانده"
            price_label = "📍 قیمت بسته‌شدن باقی‌مانده"
        else:
            title = "STOP LOSS HIT"
            price_label = "📍 Stop اجرا شد"
        icon = "🔐" if kind == "TRAIL_STOP" and hit_index else "⛔"
        text = (
            f"{icon} <b>{title}</b>\n\n" + common + "\n"
            f"━━━━━━━━━━━━━━━━━━\n📍 <b>وضعیت اهداف</b>\n{_tp_status_lines(event)}\n"
            f"━━━━━━━━━━━━━━━━━━\n{price_label}: <b>{_price(float(event.get('stop') or event.get('sl') or 0))}</b>\n"
            f"💰 سود/ضرر تجمعی: <b>${float(event.get('realized_profit_usd', 0)):+.2f}</b>\n"
            f"🚀 اثر نهایی بر کل مارجین: <b>{float(event.get('realized_margin_roi_pct', 0)):+.2f}%</b>"
        )
    try:
        candidate = _event_chart_candidate(event)
        ladder = (candidate.metadata or {}).get("target_ladder") or {}
        frame = _lifecycle_chart_frame(candidate, [candidate.planned_entry, candidate.sl, *(ladder.get("targets") or []), (candidate.metadata or {}).get("current_trailing_sl", 0)])
        chart = generate_chart(frame, candidate, confirmed=True) if frame is not None else None
    except Exception as exc:
        print(f"Live target chart warning {event.get('signal_id')}: {exc}")
        chart = None
    if chart:
        return send_photo(chart, text, target, reply_to_message_id=reply_id)
    return send_message(text, target, reply_to_message_id=reply_id)

