"""Clean, evidence-driven Telegram messages for Viva Signal Bot v7."""
from __future__ import annotations

import html
import io
import re
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator, AutoMinorLocator
import matplotlib.image as mpimg
import mplfinance as mpf
import math
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
# Viva 2026-09-16 (PROP-1 approved): VIVA-MON-SIGNALS — the clean journal
# channel: ONLY final alert + Confirmed + TP/stops + final result, mirrored
# with its own internal reply-ladder. Current channels keep everything.
CHAT_ID_VIVA_SIGNALS = os.getenv("CHAT_ID_VIVA_SIGNALS", "")

# ── Round 15 (Viva 09-21): «برای هر تایم‌فریم یک کانال جدا بزنیم … فقط سیگنال
# تایید شده بیاد … کلا هر سیگنال تایید شده فقط به آخرین نتیجه لینک بشه».
# Confirmed-only mirrors of the main channel, one per timeframe family, plus the
# SPOT channel. Empty ids (the state until he creates them) make every path a
# no-op — the feature cannot touch the live channels before it exists.
# ── Viva 09-22: he handed over the real channels by NAME, so the buckets now
# follow HIS names (not the phase-1 guess): 15m/30m/1h live together in
# VIVA-MON-15M-1H, 2h+4h in VIVA-MON-2H-4H, the dailies in VIVA-MON-1D and the
# spot engine has VIVA-MON-SPOT. Old SWING_* names stay as fallbacks so no
# deploy can lose a channel by renaming.
CHAT_ID_SWING_SHORT = os.getenv("CHAT_ID_TF_15M_1H",
                                os.getenv("CHAT_ID_SWING_SHORT", ""))  # 15m · 30m · 1h
CHAT_ID_SWING_MID = os.getenv("CHAT_ID_TF_2H_4H",
                              os.getenv("CHAT_ID_SWING_MID", ""))      # 2h  · 4h
CHAT_ID_SWING_LONG = os.getenv("CHAT_ID_TF_1D",
                               os.getenv("CHAT_ID_SWING_LONG", ""))    # 1d  · 3d · 1w
CHAT_ID_SPOT = os.getenv("CHAT_ID_SPOT", "")                           # spot engine

# Viva 2026-09-11: ONE block template for every message in every channel —
# bold section titles, related emoji, ━ rules between logical blocks.
VIVA_SEP = "━" * 20
# FORMAT-3 (09-16): the thinner rule BETWEEN concepts inside one section —
# «بین مفاهیم خطوط جداکننده بیاد وگرنه نامفهوم است».
VIVA_SEP_ITEM = "━" * 10

# Viva 2026-09-16: «هیچ کلمه انگلیسی نیاد» — session codes speak Persian.
_SESS_FA = {"SYDNEY": "سدنی", "ASIA": "آسیا", "TOKYO": "توکیو",
            "LONDON": "لندن", "NY": "نیویورک", "NEW_YORK": "نیویورک",
            "LONDON_NY_OVERLAP": "هم‌پوشانی لندن-نیویورک",
            "LATE_NY": "پایان نیویورک", "OFF_HOURS": "خارج از سشن‌های اصلی",
            "OFF_SESSION": "خارج از سشن‌های اصلی"}


def _sep_bullets(block: str) -> str:
    """Viva 09-17 (reverses FORMAT-3): «خطوط جدا کننده زیاد بود» — bullets
    inside a section now stack with plain newlines; ━ lives ONLY between the
    major sections of the detailed message."""
    return block or ""
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
# CHART-8 (Viva 09-16, verbatim palette): «فلگ لیمیت و فیلیپ زون به ترتیب زرد
# لیمویی و نارنجی روشن برای نزولی؛ سبز فسفری روشن و آبی روشن برای صعودی؛
# اوردرابلاک نزولی قرمز کمرنگ مایل به صورتی، صعودی سبز چمنی روشن؛ بقیهٔ
# نواحی عرضه قرمز کمرنگ و تقاضا سبز کمرنگ» — very faint fills, NO border,
# Persian names printed in the candle-free margin, never over the candles.
ZONE_KIND_FA = {
    "FVG": "FVG", "ORDER_BLOCK": "اوردرابلاک",
    "OB + FVG CONFLUENCE": "اوردرابلاک + FVG",
    "INVERSE FVG / BREAKER": "IFVG / بریکر",
    "SUPPLY/DEMAND FLIP": "فیلیپ‌زون", "P1234 POINT-2 FLIP": "فیلیپ‌زون",
    "BROKEN TRENDLINE": "BOS / بریک‌رتست",
    "TRENDLINE BREAK WATCH (LINE ZONE)": "BOS / بریک‌رتست",
    "INTRA-BREAK BASE": "بیس داخلی شکست",
    "PINVAL": "ناحیهٔ پین‌بار", "ALBROX SPIKE RECLAIM BASE": "بیس البروکس",
}
ZONE_PALETTE = {
    ("FLAG", "SHORT"): ("#D4E157", "#827717"),   # زرد لیمویی
    ("FLAG", "LONG"): ("#B9F6CA", "#1B5E20"),    # سبز فسفری روشن
    ("FLIP", "SHORT"): ("#FFCC80", "#E65100"),   # نارنجی روشن
    ("FLIP", "LONG"): ("#81D4FA", "#01579B"),    # آبی روشن
    ("OB", "SHORT"): ("#F3C1C6", "#880E4F"),     # قرمز کمرنگ مایل به صورتی
    ("OB", "LONG"): ("#AED581", "#33691E"),      # سبز چمنی روشن
    ("SR", "SUPPLY"): ("#E8A9A9", "#B71C1C"),    # قرمز کمرنگ
    ("SR", "DEMAND"): ("#A9CDB0", "#1B5E20"),    # سبز کمرنگ
    ("DEF", "SHORT"): ("#E8A9A9", "#B71C1C"),
    ("DEF", "LONG"): ("#A9CDB0", "#1B5E20"),
}


def _zone_family(poi: str) -> str:
    p = str(poi or "").upper()
    if "FLAG" in p or "LIMIT" in p or "DIAMOND" in p:
        return "FLAG"
    if "FLIP" in p:
        return "FLIP"
    if "ORDER_BLOCK" in p or p.startswith("OB"):
        return "OB"
    return "DEF"


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

# ── Viva 09-21: «موتور تولید زبان فارسی در چارت خرابه» — Persian drawn into a
# figure needs a font WITH Arabic glyphs and needs shaping + bidi. Both live in
# analysis.fa_text; chart code must call fa_chart() for any Persian label.
from analysis.fa_text import fa as fa_chart, use_persian_font as _fa_use_font
SIGNAL_SEPARATOR = os.getenv(
    "SIGNAL_SEPARATOR_TEXT",
    "⬛⬛⬛",
)
        # v7.6 chart overlays (Viva's chart-design references)
_CHART_SCENARIO_ZIGZAG = os.getenv("CHART_SCENARIO_ZIGZAG", "off").strip().lower() in {"1", "on", "true", "yes"}
_CHART_RANGE_OVERLAY = os.getenv("CHART_RANGE_OVERLAY", "on").strip().lower() in {"1", "on", "true", "yes"}
# ── Round 15 (Viva 09-21, verbatim): «این باکس رو از چارت‌های پراپ فعلی مون در
# ۵ ستاپ حذف بکن … این باکس‌ها برای معاملات اسپات هستن نه فیوچرز» — the vertical
# green measured-move box leaves every futures chart (alert, update AND
# confirmation). The long/short trade tool is untouched; the box returns only on
# the SPOT charts, where it was asked for.
_CHART_MEASURE_BOX = os.getenv("CHART_MEASURE_BOX", "off").strip().lower() in {"1", "on", "true", "yes"}
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


_TF_FA = {"1d": "روزانه", "4h": "۴ ساعته", "2h": "۲ ساعته", "1h": "۱ ساعته",
          "30m": "۳۰ دقیقه", "15m": "۱۵ دقیقه", "5m": "۵ دقیقه",
          "3m": "۳ دقیقه", "1m": "۱ دقیقه"}

# ── Viva 09-20 time-axis law (verbatim ruling + his 09-20 clarification) ──
# «اگر قیمت و کندل‌ها قبل از تی‌پی یا استاپ از ابزار خارج شدند، در زمان
# تی‌پی‌ها و چارت‌های لایو اجازه دارند حرکت قیمت را در تایم‌فریم‌های بالاتر
# نشان بدهند و در یکی دو خط توضیح بدهند» + «اون ۴۰ کندل رو بعنوان مثال
# گفتم .. اگر تعداد کندل‌ها به هر تعدادی رسید که از ابزار خارج شد، با یک
# تایم بالاتر …؛ تا وقتی قیمت داخل ابزار لانگ/شورت است در همان تایم تریگر».
# So: NO magic count. The tool keeps its drawn region (its own right edge in
# time + its own price band); the moment candles/price leave that region —
# ANY number of them — every message that carries a LIVE chart shows the same
# anchored tool on one higher TF with a short Persian note.
LIFECYCLE_VIEW_LADDER = {
    "1m": ["3m", "5m", "15m", "1h", "4h"],
    "3m": ["5m", "15m", "1h", "4h"],
    "5m": ["15m", "1h", "4h"],
    "15m": ["1h", "4h", "1d"],
    "30m": ["1h", "4h", "1d"],
    "1h": ["4h", "1d"],
    "2h": ["4h", "1d"],
    "4h": ["1d"],
    "1d": [],
}
# The tool's own drawn right edge: the confirmed chart paints 42 blank bars
# ahead of the entry candle, so that margin IS the edge candles walk out of.
TOOL_FORWARD_BARS = 42
LIFECYCLE_MAX_VIEW_BARS = 110      # tool origin must stay on the 150-bar canvas


def _htf_context_bits(candidate: SignalCandidate) -> List[str]:
    """Higher-timeframe context BITS for every alert message — where we are
    relative to important zones and what just broke (Viva's context rule).
    Callers join them with the separator they need (FORMAT-3: item rules)."""
    md = candidate.metadata or {}
    bits: List[str] = []
    ctx_tf = (md.get("tl_context_tf") or md.get("pin_ctx_tf") or md.get("context_tf") or "").strip()
    if ctx_tf:
        tf_fa = _TF_FA.get(ctx_tf, ctx_tf.upper())
        if candidate.setup_code in ("TLBREAK", "TECHCLASSIC") and md.get("tl_pattern_fa"):
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
    return bits


def _htf_context_fa(candidate: SignalCandidate) -> str:
    return "🧭 <b>کانتکست تایم بالاتر</b>\n" + "\n".join(f"• {_e(b)}" for b in _htf_context_bits(candidate))


def _confirm_rule_fa(candidate: SignalCandidate) -> str:
    """Viva's requirement: every alert states the confirmation condition AND
    the invalidation condition up front, in one glanceable line."""
    md = candidate.metadata or {}
    if candidate.setup_code == "PINVAL":
        tf_fa = _TF_FA.get(str(md.get("pin_tf") or ""), candidate.trigger_timeframe)
        hi, lo = float(md.get("pin_high") or 0), float(md.get("pin_low") or 0)
        if candidate.direction == "LONG":
            cond = f"کلوز {tf_fa} بالای {_price(hi)}"
            kill = f"کلوز {tf_fa} زیر {_price(lo)}"
        else:
            cond = f"کلوز {tf_fa} زیر {_price(lo)}"
            kill = f"کلوز {tf_fa} بالای {_price(hi)}"
        # ── Viva 09-21 (round 15), verbatim: «چرا هنوز در توضیحات می‌گه تا ۳ کندل
        # یک ساعته کلوز بالای فلان شرط تایید است؟؟» — there is no candle cap in the
        # engine (his 09-17 rulilng removed it) and now the text says the same:
        # the FIRST valid close beyond the named level is the confirmation, and
        # it stays valid until the invalidation level is broken.
        return (f"⚖️ <b>شرط تأیید:</b> اولین کلوزِ معتبرِ {tf_fa} بالای/زیر سطحِ نام‌برده — "
                f"{cond} • <b>ابطال:</b> {kill}")
    ctf = str(md.get("confirm_tf") or "").upper()
    if not ctf:
        # never print a blank timeframe: fall back to the standard ladder
        # (one step below the pattern TF) — same rule the engine confirms on
        try:
            from analysis.setups_v7 import confirm_timeframe_for_pattern, timeframe_profile
            _ctx, _mid_tf, _trg = timeframe_profile(candidate.style)
            ctf = str(confirm_timeframe_for_pattern(
                _ctx, candidate.style, candidate.trigger_timeframe or _trg) or "").upper()
        except Exception:
            ctf = ""
    ctf_fa = _TF_FA.get(ctf.lower(), ctf) or "تایم تأیید"
    return (
        f"⚖️ <b>شرط تأیید:</b> اولین کلوزِ معتبرِ بسته‌شده فراتر از خط یا ضلعِ الگو، در {ctf_fa} یا تایم الگو، به جهت سناریو (پولبک شرط نیست)؛ برای سناریوهای داخلی: اولین نشانهٔ معتبر روی ناحیه (پین‌بار/کی‌بار/انگالف/BOS/کمپرشن)"
        f" • <b>ابطال:</b> عبور معتبر از {_price(candidate.sl)}"
    )


def _confirm_rule_block(candidate: SignalCandidate) -> str:
    """FORMAT-3 (Viva 09-16, his corrected paste): the ⚖️ section is THREE
    concepts split by item rules — the confirmation condition, the internal
    scenario doctrine (each term EXPLAINED, not just listed), and the
    invalidation. The active internal sign itself is analyzed in the 🔥 block."""
    full = _confirm_rule_fa(candidate)
    if " • <b>ابطال:</b> " in full:
        head, kill = full.split(" • <b>ابطال:</b> ", 1)
    else:
        head, kill = full, f"عبور معتبر از {_price(candidate.sl)}"
    parts = [head]
    if candidate.setup_code != "PINVAL":
        parts.append(
            "برای سناریوهای داخلی: اولین نشانهٔ معتبر روی ناحیه — "
            "<b>انگالفینگ</b> یعنی کندلی که بدنهٔ کندل پیشین را کامل می‌بلعد؛ "
            "<b>پین‌بار</b> یعنی شدوی بلند با بدنهٔ کوچک (جاروی نقدینگی)؛ "
            "<b>فشردگی/کامپرشن</b> یعنی پیلهٔ کندل‌های ریز پیش از انفجار حرکت؛ "
            "<b>BOS</b> یعنی شکست سطح ساختاری. هرکدام که همین حالا روی ناحیه شکل "
            "گرفته، در بخش «🔥 نشانهٔ فعال روی ناحیه» با تحلیل دوخطی آمده است.")
    parts.append(f"<b>ابطال:</b> {kill}")
    return "\n".join(parts)


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
    """Viva 09-17 (verbatim): «اعداد با دو اعشار بیشتر نیان در هیچ عددی ...
    حداکثر ۲ رقم اعشار» — big numbers 2 decimals; sub-$1 keeps 2 significant
    digits so cheap coins stay readable."""
    value = float(value)
    absolute = abs(value)
    if absolute >= 1000:
        return f"{value:,.2f}"
    if absolute >= 100:
        s = f"{value:.2f}"
    elif absolute >= 1:
        s = f"{value:.3f}"          # Viva 09-17: 1-99 -> 3 decimals
    elif value == 0:
        return "0"
    else:
        import math as _math        # sub-$1 -> 4 significant digits
        s = f"{value:.{max(1, 3 - _math.floor(_math.log10(absolute)))}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


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


def _audit_send(kind: str, chat_id, mid) -> None:
    """Viva 2026-09-13: every accepted Telegram post is journaled (last 10) in
    bot_kv — delivery claims must be checkable from the DB, not argued."""
    if not mid:
        return
    try:
        import time as _t
        from database.bot_kv import get_json as _gk, set_json as _sk
        log = _gk("send_audit", []) or []
        log.append({"t": int(_t.time()), "k": str(kind), "c": str(chat_id or ""), "m": int(mid)})
        _sk("send_audit", log[-10:])
    except Exception:
        pass


def send_message(
    text: str,
    chat_id: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    reply_markup: Optional[dict] = None,
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
        if reply_markup:
            import json as _j
            payload["reply_markup"] = _j.dumps(reply_markup)
        result = _tg_post(url, data=payload, timeout=15)
        if result and first_id is None:
            first_id = int(result.get("result", {}).get("message_id") or 0) or None
    _audit_send("text", target, first_id)
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


def _style_disp(candidate) -> str:
    """GRAND is the 1D tier of Viva's ladder — channels read it as SWING."""
    st = str(getattr(candidate, "style", "") or "").upper()
    return "SWING" if st == "GRAND" else st


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
    head = {True: "✅ <b>تأیید شد</b>", False: "❌ <b>تأیید نشد</b>", None: "⚪ <b>بدون تأیید</b>"}[ok]
    # Viva 2026-09-11: verdicts never pile up as extra posts — they replace the
    # chain's single UPDATE slot in the alerts channel (linked to the detail).
    try:
        if send_setup_update(candidate, note_fa=note_fa, state_fa=head):
            return True
    except Exception as exc:
        print(f"verdict slot warning {candidate.signal_id}: {exc}")
    text = (
        f"{head}\n"
        f"🪙 {_e(candidate.symbol)} • {_e(candidate.strategy_fa)}\n"
        f"{_e(note_fa)}\n"
        f"🆔 <code>{_e(_public_code(candidate))}</code>"
    )
    return bool(send_message(text, target, reply_to_message_id=mid))


def _balance_html_tags(text: str) -> str:
    """Drop/close any HTML tag a boundary cut orphaned, so both the trimmed
    head AND each continuation chunk stay valid Telegram HTML."""
    import re as _re
    for tag in ("b", "i", "code", "a"):
        opens = len(_re.findall(rf"<{tag}[ >]", text))
        closes = len(_re.findall(rf"</{tag}>", text))
        while opens > closes:
            at = text.rfind(f"<{tag}")
            if at < 0:
                break
            end = text.find(">", at)
            if end < 0:
                text = text[:at]
                break
            text = text[:at] + text[end + 1:]
            opens -= 1
        while closes > opens:
            at = text.rfind(f"</{tag}>")
            if at < 0:
                break
            text = text[:at] + text[at + len(f"</{tag}>"):]
            closes -= 1
    return text.rstrip()


def _split_caption(caption: str, limit: int = 1000) -> Tuple[str, List[str]]:
    """N1 (audit 09-15): _fit_caption used to cut on a line boundary and
    promise a continuation that was NEVER sent, so the promise itself was a
    half-message. Returns (head, tails): head carries the footer when tails
    exist, and send_photo posts the tail as the NEXT plain message right
    behind — NO reply quote (Viva 2026-09-15: «اصلا دوست ندارم یک پیام بشه
    ۲ پیام و بهم ریپلای بشه … ادامش پشتش میاد بدون ریپلای اوکیه»)."""
    footer = "\n📎 ادامهٔ پیام دقیقاً زیرِ همین پیام می‌آید"
    text = (caption or "").strip()
    if len(text) <= limit:
        return text, []
    head_limit = max(120, limit - len(footer))
    cut = text.rfind("\n", 0, head_limit)
    if cut < head_limit // 2:
        cut = text.rfind(" ", 0, head_limit)
    if cut < head_limit // 2:
        cut = head_limit
    head = _balance_html_tags(text[:cut].rstrip()) + footer
    tail = text[cut:].strip()
    return head, ([_balance_html_tags(tail)] if tail else [])


def _fit_caption(caption: str, limit: int = 1000) -> str:
    """Viva 2026-09-14 «پیام نصفه ول کردی»: a photo caption must NEVER be cut
    mid-sentence. Builders are expected to fit; this is the safety net that
    trims on a line boundary and closes/ drops any HTML tag the cut orphans.
    Trim-only (edit paths); send_photo uses _split_caption and DELIVERS the
    continuation instead of only promising it."""
    head, _tails = _split_caption(caption, limit)
    return head


def edit_photo_caption(message_id: int, chat_id: str, caption: str,
                       reply_markup: Optional[dict] = None) -> bool:
    """Caption-only edit of a photo message (no image re-upload)."""
    if not TOKEN or not chat_id or not message_id:
        return False
    payload = {"chat_id": str(chat_id), "message_id": int(message_id),
               "caption": _fit_caption(caption), "parse_mode": "HTML"}
    if reply_markup:
        import json as _j
        payload["reply_markup"] = _j.dumps(reply_markup)
    res = _tg_post(
        f"https://api.telegram.org/bot{TOKEN}/editMessageCaption",
        data=payload, timeout=15)
    return bool(res and res.get("ok"))


def _edit_reply_markup(chat_id: str, message_id: int, reply_markup: dict) -> bool:
    """Swap the button row under an existing message (no content edit) — the
    mechanism that wires main↔win-rate links once BOTH posts exist, per Viva's
    «لینک بشن به هم دیگه» law."""
    if not TOKEN or not chat_id or not message_id:
        return False
    try:
        import json as _j
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/editMessageReplyMarkup",
            json={"chat_id": str(chat_id), "message_id": int(message_id),
                  "reply_markup": _j.dumps(reply_markup)}, timeout=12)
        return bool(r.ok and (r.json() or {}).get("ok"))
    except Exception:
        return False


def attach_results_link(message_id: int, results_mid: int) -> bool:
    """Point the main-channel event message AT its win-rate mirror copy."""
    if not message_id or not results_mid:
        return False
    link = _telegram_message_link(CHAT_ID_RESULTS or CHAT_ID_ADMIN, int(results_mid))
    if not link:
        return False
    return _edit_reply_markup(str(CHAT_ID_EXECUTION or CHAT_ID_ADMIN), int(message_id),
                              {"inline_keyboard": [[{"text": "🔗 ثبت در کانال نتایج",
                                                      "url": link}]]})


_LAST_PHOTO_FILE: Dict[int, str] = {}   # photo message_id → telegram file_id


def send_photo(
    image: bytes,
    caption: str,
    chat_id: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    reply_markup: Optional[dict] = None,
    caption_limit: int = 1000,
) -> Optional[int]:
    target = chat_id or CHAT_ID_ADMIN
    if not TOKEN or not target or not image:
        return None
    # N1 (audit 09-15): the caption is split, not silently truncated — the
    # overflow really is delivered as reply-linked continuation messages
    # below, so «📎 ادامه در پیام لینک‌شده» is finally a true statement.
    # Viva 2026-09-16: callers that must stay ONE message (the compact
    # anchor) pass caption_limit=1024 — Telegram's hard photo-caption cap —
    # so no stray «ادامه» message can ever detach from the anchor again.
    _head, _tails = _split_caption(caption, caption_limit)
    payload = {"chat_id": target, "caption": _head, "parse_mode": "HTML"}
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
    mid = int(result.get("result", {}).get("message_id") or 0) or None
    # Round-19 (Viva 09-23: «از همون چارت‌های ساخته‌شده برای ربات تلگرام
    # استفاده کن، نمی‌خوام با ساخت چارت دوباره مصرف ریلوی بالا بره»): keep the
    # Telegram file_id so the mobile app serves the SAME image from Telegram's
    # CDN instead of re-rendering anything.
    try:
        _photos = (result.get("result", {}) or {}).get("photo") or []
        if mid and _photos:
            _LAST_PHOTO_FILE[int(mid)] = str(_photos[-1].get("file_id") or "")
    except Exception:
        pass
    _audit_send("photo", target, mid)
    if mid and _tails:
        # Viva 2026-09-15: the continuation comes RIGHT BEHIND as a plain
        # message — never reply-quoted («بهم ریپلای نشه»).
        try:
            send_message(_tails[0], target)
        except Exception as _tail_exc:
            print(f"caption continuation failed: {_tail_exc}")
    return mid


def _frame_x_of_ts(index, ts_value) -> float:
    """R31.7 (audit C1/C6): TRUE x of a pivot timestamp on a chart frame.

    ``np.searchsorted`` (a) clamps a pivot older than the frame to x=0 — the
    fit window (trigger tail 170) is longer than the chart lookback, so HTF
    lines were re-anchored on the wrong bar and hung in the air, with their
    first circle glued to the left edge — and (b) maps a lower-TF pivot that
    sits INSIDE a display candle to the NEXT candle (1 bar right on every
    stepped-up chart). This returns the containing bar, and extrapolates by
    the median bar spacing outside the frame (negative x = before bar 0)."""
    _t = pd.Timestamp(str(ts_value))
    _idx = index
    if len(_idx) == 0:
        return 0.0
    try:
        _dt = float(np.median(np.diff(_idx.asi8))) if len(_idx) >= 2 else 0.0
    except Exception:
        _dt = 0.0
    if _t < _idx[0]:
        return float((_t.value - _idx[0].value) / _dt) if _dt > 0 else 0.0
    _i = int(np.searchsorted(_idx, _t, side="right")) - 1
    if _i >= len(_idx) - 1 and _dt > 0:
        return float(len(_idx) - 1) + float(np.floor((_t.value - _idx[-1].value) / _dt))
    return float(_i)


def _pivot_line_fit(ax, frame, xs, ys):
    """Phase-3 (Viva 09-23 final ruling): on a LOG price axis whose visible
    span exceeds ~3%, pivot lines are fitted in LOG10 space — percentage-honest
    and visually straight ON the log chart (a linear fit drawn on log floats
    off the pivots on long horizons). Short-span/linear charts keep the classic
    linear fit (there log ≡ linear — the renderer's own scale guard)."""
    try:
        _pmin = float(frame["low"].min())
        _pmax = float(frame["high"].max())
        _span = _pmax / max(_pmin, 1e-12) - 1.0
        if str(getattr(ax, "get_yscale", lambda: "linear")()) == "log" and _span > 0.03:
            a, b = np.polyfit(np.asarray(xs, float), np.log10(np.asarray(ys, float)), 1)
            return "log", float(a), float(b)
    except Exception:
        pass
    a, b = np.polyfit(np.asarray(xs), np.asarray(ys), 1)
    return "lin", float(a), float(b)


def _level_tag(ax, x: float, y: float, label: str, color: str):
    """One right-column pill. OPAQUE background (Viva 09-23/24 night: dashed
    channel extensions were striking through the chip text) — and the artist
    is returned so the anti-overflow x-clamp can measure its real width."""
    try:
        rgb = matplotlib.colors.to_rgb(color)
        lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        text_color = "#131722" if lum > 0.62 else "#FFFFFF"
    except Exception:
        text_color = "#FFFFFF"
    return ax.text(
        x,
        y,
        label,
        color=text_color,
        fontsize=7.5,
        fontweight="bold",
        va="center",
        ha="left",
        zorder=12,
        clip_on=False,
        bbox={"boxstyle": "round,pad=0.28", "facecolor": color, "edgecolor": "none", "alpha": 1.0},
    )


# ── Viva 09-23/24 night (the 13-chart audit): the right label column had
# chips overlapping each other, spilling over the price axis and struck
# through by dashed extensions. ONE registry + ONE allocator now owns the
# column: LIVE, pattern-name chips and every ENTRY/TP/STOP pill take a slot,
# and the axes are widened (bounded) so no chip ever crosses the ladder.
def _slot_alloc(taken: List[float], y: float, span: float, step: float = 0.034) -> float:
    """Reserve the nearest free slot for `y`; existing slots never move."""
    lim = step * max(span, 1e-9)
    for _ in range(60):
        near = [t for t in taken if abs(t - y) < lim]
        if not near:
            taken.append(y)
            return y
        c = min(near, key=lambda t: abs(t - y))
        y = c + (lim if y >= c else -lim)
    taken.append(y)
    return y


def _relayout_pills(rows: List[List[float]], lo: float, hi: float, step: float) -> None:
    """Final guarantee (r23): clamp-after-alloc could fold two pills onto one
    slot (seen live: ADA ENTRY×LIVE, RENDER ENTRY×TP1, TAO LIVE×chip).
    Deterministic 1-D parking: clamp every row into the band, sort, forward-
    push to ≥step, then at most ONE uniform down-shift (a uniform shift keeps
    every gap). A degenerate panel (never on real charts) falls back to a
    reduced step instead of ever printing two pills on one line."""
    if not rows:
        return
    rows.sort(key=lambda r: r[0])
    _b0, _t0 = lo + step * 0.6, hi - step
    for _r in rows:
        _r[0] = min(max(_r[0], _b0), _t0)
    for _i in range(1, len(rows)):
        if rows[_i][0] - rows[_i - 1][0] < step:
            rows[_i][0] = rows[_i - 1][0] + step
    _over = rows[-1][0] - _t0
    if _over > 0:
        for _r in rows:
            _r[0] -= _over
    if rows[0][0] < lo:
        _need = (len(rows) - 1) * step
        _room = _t0 - _b0
        _s2 = step if _room >= _need else max(_room / max(len(rows) - 1, 1), 1e-9)
        for _i, _r in enumerate(rows):
            _r[0] = min(_b0 + _i * _s2, _t0)


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


def _add_setup_sticker(fig, candidate: SignalCandidate) -> bool:
    """Draw the setup's own badge; True when one was drawn."""
    path = _setup_identity(candidate)["sticker"]   # one source of truth
    if not os.path.isfile(path):
        return False
    try:
        # Header band keeps the branded setup sticker out of the candle area.
        # Separate high-resolution badge, kept in the empty upper-right margin.
        sticker_ax = fig.add_axes([0.685, 0.900, 0.070, 0.070], zorder=30)
        sticker_ax.imshow(mpimg.imread(path))
        sticker_ax.axis("off")
        return True
    except Exception as exc:
        print(f"Setup sticker warning: {exc}")
        return False


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
        f"{_public_code(candidate)}  •  {_setup_identity(candidate)['brand']}"
        f"  •  {_chart_market_label(candidate)}",
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
    # (the in-axes bottom-right brand mark is GONE — Viva 09-23/24: the chart
    # showed TWO watermarks; the figure footer + the center mark are the brand)


def _setup_identity(candidate: SignalCandidate) -> dict:
    """ONE source of truth for a setup's name — his 09-21 audit: «نام ستاپ در
    هدر، نام استیکر و footer باید از یک setup_identity مشترک بیاید؛ نه اینکه
    هر کدام از یک mapping جدا بخواند». Header word, corner sticker, chip badge
    and footer all read this dict (and the sticker file is derived from the
    same code), so a chart can never show one setup's sticker with another
    setup's name — his «استیکر PINVAL روی چارت PINWALLQ» complaint.
    """
    code = str(candidate.setup_code or "SETUP").upper()
    brands = {
        "PINVAL": "VIVA ✦ PINWALL LEGACY",
        "PINWALLQ": "VIVA ✦ PINWALL QUALITY",
        "TLBREAK": "VIVA ✦ TLBREAK",
        "TECHCLASSIC": "VIVA ✦ TECHCLASSIC",
        "P1234": "VIVA ✦ 1-2-3-4",
        "ALBROX": "VIVA ✦ ALBROX",
        "LSR": "VIVA ✦ LIQUIDITY",
        "SDR": "VIVA ✦ SUPPLY/DEMAND",
        "BOS1": "VIVA ✦ BOS RETEST",
        "IFVG": "VIVA ✦ FVG FLIP",
        "TLR": "VIVA ✦ TREND RETEST",
    }
    persian = {
        "PINVAL": "اعتبارسنجی پین‌بار",
        "PINWALLQ": "پین‌وال کیفیت",
        "TLBREAK": "شکست خط روند",
        "TECHCLASSIC": "الگوی کلاسیک پیوتی",
        "ALBROX": "بازپس‌گیری بیس",
    }
    color = (CHART_THEME["structure"] if code in {"P1234", "BOS1", "IFVG"}
             else (CHART_THEME["trend"] if code in {"TLBREAK", "TECHCLASSIC"}
                   else CHART_THEME["demand"]))
    return {
        "code": code,
        "brand": brands.get(code, f"VIVA ✦ {code}"),
        "name": code,
        "fa": persian.get(code, ""),
        "color": color,
        "sticker": os.path.join(SETUP_STICKER_DIR, f"{code.lower()}.png"),
    }


def _setup_badge(candidate: SignalCandidate) -> tuple[str, str]:
    """Branded, setup-specific sticker used consistently on chart and caption.

    Round 15c: it no longer keeps its own mapping — it asks _setup_identity so
    the chip, the header and the corner sticker can never disagree."""
    _ident = _setup_identity(candidate)
    return _ident["brand"], _ident["color"]


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


def _render_corner_notes(ax, notes: list, frame: pd.DataFrame, confirmed: bool = False,
                         fig=None) -> None:
    """Structural notes INSIDE the axes, parked in the EMPTY sky corner.

    Viva 09-23 (after the margin-carve experiment he rejected — «یک‌سوم
    کندل‌ها رو حذف کردی واسه ۶ تا کلمه مسخره»): the figure is NEVER
    re-laid-out and no candles are ever sacrificed for text. The stack sits in
    the emptier of the top/bottom spaces of the chart's OLDEST third — his own
    reference charts show exactly this (notes at the top-left sky, tape full
    width). A translucent chip keeps every line readable if a candle ever
    reaches it.
    """
    if not notes or frame is None or frame.empty:
        return
    if fig is None:
        return
    lo, hi = ax.get_ylim()
    span = max(hi - lo, 1e-12)
    sample = frame.iloc[:max(12, len(frame) // 3)]
    top_empty = max(0.0, (hi - float(sample["high"].max())) / span)
    bottom_empty = max(0.0, (float(sample["low"].min()) - lo) / span)
    _n = min(len(notes), 11)
    _step = 0.037
    _stack_h = _step * (_n - 1) + 0.030

    def _candle_hits(y_top: float, y_bot: float) -> float:
        """Share of the LEFT quarter candles piercing the candidate band —
        the ledger goes where the tape is NOT (Viva 09-23/24: BTC/RENDER
        renders parked the stack ON the early candles)."""
        try:
            _s = frame.iloc[:max(8, int(len(frame) * 0.27))]
            _hit = (( _s["high"] >= y_bot) & (_s["low"] <= y_top)).sum()
            return float(_hit) / max(1, len(_s))
        except Exception:
            return 0.0

    # candidate anchors (axes-fraction y of the stack's top line): top-left
    # sky, lower-left, and mid-left (below the confirmed trade box).
    _cands = []
    if not confirmed:
        _cands.append(("top", 0.975))
    _cands.append(("bottom", 0.025 + _stack_h - _step))
    _cands.append(("mid", 0.50 + _stack_h / 2.0))
    _best, _best_hits, _best_tag = None, None, None
    for _tag, _yc in _cands:
        _y_top = min(0.985, _yc)
        _y_bot = max(0.015, _yc - _stack_h)
        _d_top = lo + float(_y_top) * span
        _d_bot = lo + float(_y_bot) * span
        _hits = _candle_hits(_d_top, _d_bot)
        if _best_hits is None or _hits < _best_hits - 1e-9:
            _best, _best_hits, _best_tag = _yc, _hits, _tag
    _y0 = float(_best)
    for _i, (text, color) in enumerate(notes[:_n]):
        ax.text(0.012, _y0 - _step * _i, text,
                ha="left", va="center", color=color, fontsize=5.8,
                fontweight="bold", zorder=25, transform=ax.transAxes,
                bbox={"boxstyle": "round,pad=0.22", "facecolor": "white",
                      "edgecolor": "none", "alpha": 0.93})


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


_CHART_CACHE: Dict[tuple, bytes] = {}


# ── Viva 09-21 (round 12, second report): «وقتی حدود ۴۰ دقیقه اختلاف وجود داره …
# عملا من دارم گذشته مارکت رو می‌بینم» — the alert chart is drawn from CLOSED
# candles only (no repaint, no look-ahead), so on a 1h trigger the picture could
# be up to one candle behind the venue's own chart, and the message carried no
# clock at all: detection time, publication time and the source candle's close
# were all invisible. Three rules now:
#   1. every entry alert states the source candle's close, the detection time and
#      the send time, with the delay;
#   2. a delay past 15 minutes is printed as a warning, and past TWO trigger
#      candles the alert is no longer published as an entry (analysis note only) —
#      a past-market trade is not a trade;
#   3. the chart draws the forming candle as a NORMAL candle (round 13: «خط چین
#      نمی‌خوام … همون شکل کندل باید عادی باشه») and the LIVE pill carries the
#      live price + clock, so the picture is the market of this minute.
_TF_MINUTES: Dict[str, int] = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
                               "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
                               "1d": 1440}
STALE_WARN_MINUTES = 15


def _tf_minutes(tf) -> int:
    return int(_TF_MINUTES.get(str(tf or "").strip().lower(), 15) or 15)


def _parse_utc(value) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("UTC"))
    except Exception:
        return None


def _tehran_clock(dt: Optional[datetime], with_date: bool = False) -> str:
    if dt is None:
        return "—"
    try:
        fmt = "%m-%d %H:%M:%S" if with_date else "%H:%M:%S"
        return dt.astimezone(ZoneInfo("Asia/Tehran")).strftime(fmt)
    except Exception:
        return "—"


def _stamp_source_candle(candidate: SignalCandidate, chart_df=None) -> None:
    """Remember the clock of the candle this alert was born from (once)."""
    md = candidate.metadata if isinstance(candidate.metadata, dict) else {}
    if chart_df is not None and len(chart_df) and not md.get("source_candle_close_utc"):
        try:
            _last = pd.Timestamp(chart_df["timestamp"].iloc[-1])
            if _last.tzinfo is None:
                _last = _last.tz_localize("UTC")
            _close = _last + pd.Timedelta(minutes=_tf_minutes(candidate.trigger_timeframe))
            md["source_candle_close_utc"] = _close.tz_convert("UTC").isoformat()
            md["source_candle_open_utc"] = _last.tz_convert("UTC").isoformat()
        except Exception:
            pass
    if not md.get("alert_stamped_at_utc"):
        md["alert_stamped_at_utc"] = datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds")
    if not md.get("first_detected_at_utc"):
        md["first_detected_at_utc"] = (str(getattr(candidate, "created_at", "") or "")
                                       or md["alert_stamped_at_utc"])
    candidate.metadata = md


def _alert_lateness_minutes(candidate: SignalCandidate) -> int:
    """Minutes between the source candle's close and right now (0 when unknown)."""
    md = getattr(candidate, "metadata", None) or {}
    _close = _parse_utc(md.get("source_candle_close_utc"))
    if _close is None:
        return 0
    delta = (datetime.now(ZoneInfo("UTC")) - _close).total_seconds() / 60.0
    return max(0, int(round(delta)))


def _timing_lines(candidate: SignalCandidate) -> List[str]:
    """The clock block of every entry alert (his 09-21 request, verbatim:
    «تاخیر در زمان شناسایی و زمان انتشار و ارسال به تلگرام رو در هشدار مفصل نداشتیم»)."""
    md = getattr(candidate, "metadata", None) or {}
    tf_tag = str(getattr(candidate, "trigger_timeframe", "") or "").upper()
    close = _parse_utc(md.get("source_candle_close_utc"))
    # ── round 12: «شناسایی» is the FIRST sighting. A chain's payload carries the
    # latest re-stamp, so created_at alone printed a later clock than the send
    # («شناسایی ۰۲:۳۵ • ارسال ۰۲:۳۰» on the VVV card). The earliest of the two
    # known stamps wins, and dates ride along so a two-day-old chain is obvious.
    _det_candidates = [d for d in (_parse_utc(getattr(candidate, "created_at", "")),
                                   _parse_utc(md.get("alert_stamped_at_utc")),
                                   _parse_utc(md.get("first_detected_at_utc"))) if d is not None]
    detected = min(_det_candidates) if _det_candidates else None
    sent = datetime.now(ZoneInfo("UTC"))
    rows = ["🕒 <b>ساعت‌ها (ایران)</b>"]
    if close is not None:
        rows.append(f"• 🕯 کندل مبدا {_e(tf_tag)} — بسته‌شده در {_tehran_clock(close, True)}")
    if detected is not None:
        rows.append(f"• 🔎 شناسایی: {_tehran_clock(detected, True)}")
    rows.append(f"• 📤 ارسال به تلگرام: {_tehran_clock(sent, True)}")
    _age_days = int((sent - detected).total_seconds() // 86400) if detected else 0
    if _age_days >= 1:
        rows.append(f"• 🗓 عمر این سناریو: {_fa_num(_age_days)} روز (قیمت‌های ورود/ابطال "
                    "همان قیمت‌های روز اول‌اند و با بازار امروز جابه‌جا نشده‌اند)")
    if close is not None and detected is not None:
        _gap = max(0, int((detected - close).total_seconds() // 60))
        rows.append(f"• ⏱ فاصلهٔ بسته‌شدن کندل تا شناسایی: {_fa_num(_gap)} دقیقه")
    late = _alert_lateness_minutes(candidate)
    if late >= STALE_WARN_MINUTES or md.get("stale_detection"):
        _late = int(md.get("stale_detection") or late)
        rows.append(f"• ⚠️ این هشدار {_fa_num(_late)} دقیقه بعد از بسته‌شدن کندل منتشر شد؛ "
                    "قبل از هر تصمیم، وضعیت لحظه‌ای بازار را ببین.")
    return rows


def _stale_alert_verdict(candidate: SignalCandidate) -> tuple:
    """(publish_as_entry, lateness_minutes): a market of the past is not tradeable.

    Past TWO trigger candles the alert is no longer an entry alert at all — the
    family still speaks (a short analysis note), but never as a position.
    """
    late = _alert_lateness_minutes(candidate)
    if late <= 0:
        md = getattr(candidate, "metadata", None) or {}
        late = int(md.get("stale_detection") or 0)
    limit = 2 * _tf_minutes(getattr(candidate, "trigger_timeframe", "15m"))
    return (late <= limit), late


def _live_candle(candidate: SignalCandidate, chart_df) -> Optional[Dict[str, float]]:
    """The FORMING candle of the charted timeframe (None when the tape is closed)."""
    try:
        from data.fetcher import get_klines
        _md = getattr(candidate, "metadata", None) or {}
        tf = str(_md.get("chart_view_tf") or getattr(candidate, "trigger_timeframe", "15m") or "15m")
        live = get_klines(getattr(candidate, "symbol", ""), tf, 3, closed_only=False, use_cache=True)
        if live is None or getattr(live, "empty", True):
            return None
        row = live.iloc[-1]
        ts = pd.Timestamp(row["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        if chart_df is None or not len(chart_df):
            return None
        last_closed = pd.Timestamp(chart_df["timestamp"].iloc[-1])
        if last_closed.tzinfo is None:
            last_closed = last_closed.tz_localize("UTC")
        if ts <= last_closed:
            return None  # the tape has already closed; nothing is forming
        _vol = float(row["volume"]) if "volume" in getattr(live, "columns", []) else 0.0
        return {"timestamp": ts, "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]), "volume": _vol}
    except Exception:
        return None


def _frame_with_live_candle(df: pd.DataFrame, candidate: SignalCandidate) -> tuple:
    """(frame, live_row): the forming candle rides as a NORMAL candle.

    Viva 09-21 (round 13), verbatim: «این رو درست کن با خط چین نمی‌خوام .. خط چین
    کندل لایو اصلا نه دیده میشه برای تصمیم گیری خوب نیست همون شکل کندل باید عادی
    باشه». The live bucket is no longer a dashed ghost floating past the tape — it
    is APPENDED to the frame, so mplfinance draws it with the very same body/wick
    colours, width and volume bar as every closed candle. Nothing else changes:
    the tape below stays the closed candles the analysis used.
    """
    if df is None or df.empty:
        return df, None
    live = _live_candle(candidate, df)
    if live is None:
        return df, None
    try:
        row = {c: live[c] for c in ("open", "high", "low", "close") if c in live}
        # the tape's own tz-awareness wins: never mix naive and aware stamps
        _ts_live = pd.Timestamp(live["timestamp"])
        try:
            _ts_last = pd.Timestamp(df["timestamp"].iloc[-1])
            if _ts_last.tzinfo is None and _ts_live.tzinfo is not None:
                _ts_live = _ts_live.tz_convert("UTC").tz_localize(None)
            elif _ts_last.tzinfo is not None and _ts_live.tzinfo is None:
                _ts_live = _ts_live.tz_localize("UTC")
        except Exception:
            pass
        row["timestamp"] = _ts_live
        row["volume"] = float(live.get("volume") or 0.0)
        if "volume" not in df.columns:
            row.pop("volume", None)
        frame = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        return frame, row
    except Exception as exc:
        print(f"live-candle append skipped: {exc}")
        return df, None


def _chart_cache_key(df: pd.DataFrame, candidate: SignalCandidate, confirmed: bool) -> tuple:
    """Cache identity of a render — the LIVE close is part of it.

    Round 13 (his report): the key used to stop at the newest TIMESTAMP, and the
    forming candle keeps one timestamp for a whole hour/four hours/day — so the
    rendered picture froze for the length of the candle and every later update
    re-posted «گذشته مارکت». The live price now rides in the key, so a chart is
    only reused while the market on it is genuinely unchanged.
    """
    try:
        _last_px = round(float(df["close"].iloc[-1]), 10)
    except Exception:
        _last_px = 0.0
    return (str(getattr(candidate, "signal_id", "")), bool(confirmed),
            str(df["timestamp"].iloc[-1]), len(df),
            str((candidate.metadata or {}).get("chart_view_tf") or ""), _last_px)


def _chart_cache_get(key: tuple):
    return _CHART_CACHE.get(key)


def _chart_cache_set(key: tuple, val: bytes) -> None:
    _CHART_CACHE[key] = val
    # Railway RAM guard (Viva 09-17): PNGs are ~2MB each — keep only the last 6
    # (instant retries/mirrors reuse them); anything bigger risks an OOM kill.
    if len(_CHART_CACHE) > 6:
        for _k in list(_CHART_CACHE.keys())[:len(_CHART_CACHE) - 6]:
            _CHART_CACHE.pop(_k, None)


def _clean_render_frame(df: pd.DataFrame, window: int = 150) -> pd.DataFrame:
    """Viva 09-22/23: «یک‌سوم سمت چپ چارت کامل با کندلها بیاد مثل قبل».

    The left-third blank was EMPTY ROWS inside the render window: NaN rows
    (aggregation/pagination padding) and all-zero placeholder rows render as
    blank vertical strips in mplfinance — candles start mid-chart while every
    overlay assumes a full window. This guard drops them so the visible window
    is ALL candles, edge to edge (the designed blank stays on the RIGHT margin
    only)."""
    if df is None or df.empty:
        return df
    frame = df.tail(window).copy()
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    for col in ("open", "high", "low", "close"):
        frame = frame[pd.to_numeric(frame[col], errors="coerce") > 0]
    # keep the renderer's contract: the frame is INDEXED by timestamp
    frame = frame.set_index("timestamp")
    frame.index = pd.DatetimeIndex(frame.index)
    return frame


def generate_chart(df: pd.DataFrame, candidate: SignalCandidate, confirmed: bool = False) -> Optional[bytes]:
    """Render a branded TradingView-inspired 1440×900 chart."""
    if df is None or df.empty:
        return None
    candidate = _final_stop_guard(candidate)
    # Persian labels (setup notes, spot charts) must shape correctly; the font
    # is bundled in assets/fonts and registered once per process.
    try:
        _fam = _fa_use_font()
        if _fam:
            import matplotlib as _mpl
            _mpl.rcParams["font.family"] = [_fam, "DejaVu Sans"]
    except Exception:
        pass
    # ── the forming candle joins the tape as one more NORMAL candle (round 13)
    df, _live_row = _frame_with_live_candle(df, candidate)
    # Viva 09-17 cost ruling: one render per (alert, frame, state) — retries,
    # mirrors and cross-channel posts reuse the bytes from this cache. Round 13:
    # the state now includes the live price (see _chart_cache_key).
    _ck = _chart_cache_key(df, candidate, confirmed)
    _hit = _chart_cache_get(_ck)
    if _hit is not None:
        return _hit
    # Always initialize chart-only price-axis tags before entering any render branch.
    # This is display state only and never affects setup detection or message format.
    _axis_tags: list = []
    try:
        # Preserve enough history for real channel / wedge / range geometry;
        # the blank future panel is added separately, never by sacrificing bars.
        # Macro timeframes need LESS zoom: fewer, larger candles expose the
        # same structural swings traders see on daily/3D/weekly CryptoCove-style
        # charts. Lower TFs keep the denser view used for entries.
        _chart_tf = str((candidate.metadata or {}).get("chart_view_tf")
                        or getattr(candidate, "trigger_timeframe", "15m") or "15m").lower()
        _lookback = {"1d": 96, "4h": 120, "2h": 132, "1h": 150,
                     "30m": 160, "15m": 164, "5m": 164}.get(_chart_tf, 164)
        frame = _clean_render_frame(df, window=_lookback)
        # Viva 09-18 ruling (PINWALL/PINWALL-Q/ALBROX must paint trends too):
        # ABSOLUTE safety net — any candidate that reaches the chart without
        # render commands (old alert metadata, exotic path) gets enriched HERE.
        try:
            _md0 = getattr(candidate, "metadata", None) or {}
            if not _md0.get("render_patterns") and not _md0.get("render_zones"):
                from analysis.render_kit import enrich_render
                enrich_render(candidate, frame.reset_index())
        except Exception:
            pass
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
        # ── SPOT charts are LOG-scale (Viva 09-22, verbatim: «اسپات لاگ‌اسکیل»).
        # The scale is applied AFTER mplfinance draws, so candles, zones, lines,
        # the ladder and the corner notes — all painted in DATA coordinates —
        # are re-projected through the log transform in one go. Volume stays
        # linear, and no futures chart is ever touched.
        if bool((candidate.metadata or {}).get("log_scale")):
            try:
                for _a9 in axes:
                    _pos9 = _a9.get_position()
                    _yl9 = list(_a9.get_ylim())
                    if _pos9.height > 0.30 and _yl9[0] > 0 and _yl9[1] > _yl9[0]:
                        _a9.set_yscale("log")
            except Exception as exc:
                print(f"Chart log-scale warning: {exc}")
        elif bool(getattr(SETTINGS, "chart_log_all", False)):
            # ── Viva 09-22 round 16 (his question, YES with a guard): log on
            # EVERY price panel — pivots/trendlines/zones fit the percent
            # reality better even on 1h–4h. When the visible span is tiny
            # (<3%) log and linear are identical, so linear stays (cleaner
            # ticks); anything non-positive (impossible for USDT pairs) also
            # stays linear.
            try:
                for _a9 in axes:
                    _pos9 = _a9.get_position()
                    _yl9 = list(_a9.get_ylim())
                    if (_pos9.height > 0.30 and _yl9[0] > 0
                            and _yl9[1] > _yl9[0]
                            and _yl9[1] / _yl9[0] > 1.03):
                        _a9.set_yscale("log")
                        _a9.yaxis.set_major_formatter(FuncFormatter(_axis_price))
            except Exception as exc:
                print(f"Chart log-all warning: {exc}")
        # mplfinance creates manually positioned axes, so set the panel geometry
        # directly: wide price area, compact volume, and a small branded footer.
        # Wide candle-free future area: at 120dpi this is ~7cm from the last
        # candle to the price ladder, leaving every chart label readable.
        # Viva 09-23: «مثل چارت تریدینگ ویو کامل باشه» — the tape owns the
        # width; only a slim right margin stays for the price ladder.
        price_position = [0.040, 0.235, 0.845, 0.665]
        volume_position = [0.040, 0.085, 0.845, 0.125]
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
        from matplotlib.ticker import NullFormatter as _NF
        for _price_ax in axes[:2]:
            _price_ax.yaxis.set_major_formatter(FuncFormatter(_axis_price))
            # log-scale minor ticks otherwise print scientific snippets (9×10¹)
            _price_ax.yaxis.set_minor_formatter(_NF())
        # ── Viva 09-23 («ستون‌های حجم خراب شده و کل محور زمانی نابود شده» +
        # «در کندل لایو حتماً تاریخ و ساعت مشخص باشه»): the time axis carries
        # REAL UTC dates — majors on UTC-day boundaries, plus a bold LIVE tag
        # under the youngest candle; the live PRICE gets a TV-style tag on the
        # price ladder; volume ticks go compact K/M with no scientific offset.
        # (registered BEFORE the volume try: the right-column registry must
        # exist on every path — chips/LIVE/pattern labels all reserve slots)
        _right_slots: List[float] = []
        _right_texts: List[Any] = []
        _right_specs: list = []      # (level, label, color) → pills built AFTER ylim finalize
        _vol_ax = axes[2]
        try:
            for _va in axes[2:]:
                _va.yaxis.offsetText.set_visible(False)
                _va.yaxis.offsetText.set_text("")
            _vol_ax = axes[2]
            def _fmt_vol(v, pos):
                v = float(v)
                if v >= 1e9: return f"{v / 1e9:.0f}B"
                if v >= 1e6: return f"{v / 1e6:.0f}M"
                if v >= 1e3: return f"{v / 1e3:.0f}K"
                return f"{v:.0f}"
            _vol_ax.yaxis.set_major_formatter(FuncFormatter(_fmt_vol))
            # mplfinance appends the ScalarFormatter offset («$10^{6}$») INTO
            # the ylabel — strip it; the K/M formatter already carries magnitude
            _vol_ax.set_ylabel("VOLUME")
        except Exception:
            pass
        _times = list(frame.index)
        def _fmt_time(x, pos):
            i = int(round(float(x)))
            if 0 <= i < len(_times):
                return pd.Timestamp(_times[i]).strftime("%m-%d\n%H:%M")
            return ""
        _day_ticks = []
        _seen_days = set()
        _min_gap = max(1, len(_times) // 9)
        _last_i = -10 ** 9
        for _i, _t in enumerate(_times):
            _d = pd.Timestamp(_t).date()
            if _d not in _seen_days and _i - _last_i >= _min_gap:
                _day_ticks.append(_i)
                _seen_days.add(_d)
                _last_i = _i
        # NOTE: the youngest candle does NOT get a tick — the dark LIVE stamp
        # (figure-level, below) IS its label; two labels would overlap.
        _vol_ax.set_xticks(_day_ticks)
        _vol_ax.xaxis.set_major_formatter(FuncFormatter(_fmt_time))
        # (مهر زمان لایو سطح فیگور کشیده می‌شود — بعد از قطعی‌شدن xlim؛ پایین فایل)
        # TV-style LIVE tag ON the in-panel label column (Viva 09-23/24: the
        # old x=1.0 anchor sat ON the price-axis numbers — «لیو روی اعداد»).
        try:
            _live_px = float(frame["close"].iloc[-1])
            _right_specs.append((float(_live_px), f" LIVE {_price(_live_px)} ", "#2b2f3a"))
        except Exception as _exc:
            print(f"Chart live-price tag warning: {_exc}")
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
        if ax.get_yscale() == "linear":   # AutoMinorLocator is linear-only
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
        # ── Viva 09-23 (his marker on the probe chart): the huge reserved
        # future margin read as «یک سوم خالی» — HALVE it and let real
        # candles fill the reclaimed width (his reference charts keep
        # only a slim right margin for the pills).
        future = 28 if confirmed else 26
        for chart_ax in axes:
            chart_ax.set_xlim(-1, count + future)

        # ── Viva 09-20 time-axis law ─────────────────────────────────────
        # Every drawing command that carried a timestamp is re-anchored to
        # THAT time on the current frame, so a tool drawn yesterday keeps the
        # same x-position today (no sliding). When a lifecycle render steps
        # up to a higher TF, `chart_tf_scale` converts trigger-TF slopes into
        # view-TF bars (price per bar is 4× larger on 1h than on 15m).
        _tfscale = float((candidate.metadata or {}).get("chart_tf_scale") or 1.0)
        if not math.isfinite(_tfscale) or _tfscale <= 0:
            _tfscale = 1.0

        def _anchored_x(ts_value, fallback: float) -> float:
            if not ts_value:
                return float(fallback)
            try:
                _x = float(np.searchsorted(frame.index,
                                           pd.Timestamp(str(ts_value))))
            except Exception:
                return float(fallback)
            return float(min(max(_x, 0.0), float(count)))

        def _x_of_ts(ts_value) -> float:
            return _frame_x_of_ts(frame.index, ts_value)

        # higher-context charts (TLBREAK 4h/1h or any 1d frame) render on a
        # log price axis so long-term trendline touches/breaks stay visible.
        notes = []
        md0 = candidate.metadata or {}
        # ── Viva 09-22: the SPOT signature on the canvas corner — «لیبل spot
        # در چارت … و لیبل VIVA-SPOT-MON در پیام‌های اسپات فراموش نشه»
        if str(md0.get("market") or "").upper() == "SPOT":
            notes.append(("VIVA-SPOT-MON · SPOT", CHART_THEME["muted"]))
        ctx_for_log = md0.get("tl_context_tf")
        use_log = (
            getattr(SETTINGS, "chart_log_htf", True)
            and _STYLE_NAME != "dark"
            and (
                (candidate.setup_code in ("TLBREAK", "TECHCLASSIC") and ctx_for_log in ("4h", "1d"))
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

        # The POI / entry box keeps its ORIGINAL time origin (stamped once at
        # alert time) and still extends into the candle-free margin — the
        # origin never slides right as candles print.
        zone_start = int(_anchored_x((candidate.metadata or {}).get("tool_anchor_ts"),
                                     max(0, count - 55)))
        zone_end = count + future - 0.5  # box extends into the candle-free margin
        _dir_key = "LONG" if candidate.direction == "LONG" else "SHORT"
        _poi = str((candidate.metadata or {}).get("poi_type") or "").upper()
        _fam = _zone_family(_poi)
        _fill, _ztxt = ZONE_PALETTE.get((_fam, _dir_key),
                                        ZONE_PALETTE[("DEF", _dir_key)])
        zone_color, zone_text_color = _fill, _ztxt
        _POI_TOKEN = {"ORDER_BLOCK": "OB", "FVG": "FVG",
                      "OB + FVG CONFLUENCE": "OB + FVG",
                      "INVERSE FVG / BREAKER": "IFVG",
                      "SUPPLY/DEMAND FLIP": "FLIP ZONE",
                      "P1234 POINT-2 FLIP": "FLIP ZONE",
                      "BROKEN TRENDLINE": "BOS",
                      "TRENDLINE BREAK WATCH (LINE ZONE)": "BOS",
                      "PINVAL": "PIN BASE",
                      "ALBROX SPIKE RECLAIM BASE": "OB"}
        # Python 3.11-safe: no multi-line f-string expressions (PEP 701 is 3.12+)
        _zone_tok = _POI_TOKEN.get(_poi, "DEMAND" if _dir_key == "LONG" else "SUPPLY")
        zone_name = f"{_zone_tok}  ·  POI / ENTRY"
        ax.fill_between(
            [zone_start, zone_end],
            candidate.entry_zone_bottom,
            candidate.entry_zone_top,
            color=zone_color,
            alpha=0.26,
            zorder=1,
            linewidth=0,
        )
        # CHART-8 (Viva 09-16 night-3): zone NAMES live INSIDE their own box,
        # in a candle-free spot at the box right end / middle / left end —
        # never floating in mid-air, never over candles.  Only when every
        # in-box spot is occupied does the chip anchor to the box top edge.
        _zone_items = [{"x0": zone_start, "x1": zone_end,
                        "bottom": float(candidate.entry_zone_bottom),
                        "top": float(candidate.entry_zone_top),
                        "text": zone_name, "color": zone_text_color}]
        # CHART-8 unified kit: every setup stores detect→render commands in
        # metadata; the renderer obeys them (fallback: detect on this frame).
        _rz = (candidate.metadata or {}).get("render_zones")
        if _rz is None:
            try:
                from analysis.render_kit import detect_zones as _dz8
                _rz = _dz8(frame.reset_index(drop=True), candidate.direction,
                           float(candidate.entry_zone_bottom),
                           float(candidate.entry_zone_top))
            except Exception:
                _rz = []
        # Viva 09-22: «نواحی مهم، فقط مهم‌ترینهاش … باکس‌های عرضه و تقاضای مهم
        # در سقف‌ها و کف‌های مشخص» — the clutter box-stack becomes a diet: at
        # most two zones per side, chosen by importance = near the live price
        # AND tall (a real base/ceiling), never every imbalance on the tape.
        _rz_list = list(_rz or [])
        _clean_zone_view = str(os.getenv("CHART_CLEAN_ZONES", "1")).strip().lower() \
            in {"1", "true", "on", "yes"}
        if _rz_list:
            _live8z = float(frame["close"].iloc[-1])

            def _zone_importance(_z8: dict) -> float:
                _lo8 = float(_z8.get("lo", _z8.get("bottom", 0)) or 0)
                _hi8 = float(_z8.get("hi", _z8.get("top", 0)) or 0)
                _mid8 = (_lo8 + _hi8) / 2.0
                _h8 = abs(_hi8 - _lo8)
                return abs(_mid8 - _live8z) - 0.9 * _h8

            _by_side: dict = {}
            for _zc in _rz_list:
                _s8 = str(_zc.get("bias") or "").upper() or \
                    ("DEMAND" if _dir_key == "LONG" else "SUPPLY")
                _by_side.setdefault(_s8, []).append(_zc)
            # Keep the long-standing two-zones-per-side source contract;
            # clean mode trims the already-ranked result to the most actionable
            # two overall, without changing detection.
            _rz_list = [z8 for _zs8 in _by_side.values()
                        for z8 in sorted(_zs8, key=_zone_importance)[:2]]
            if _clean_zone_view and len(_rz_list) > 2:
                _rz_list = sorted(_rz_list, key=_zone_importance)[:2]
        for _z in _rz_list:
            # timestamp-anchored when the zone carries its origin time (every
            # zone detected since 09-20 does); legacy rows keep the old rule.
            if _z.get("ts0"):
                _x0 = max(0, int(_anchored_x(_z.get("ts0"), zone_start)) - 2)
            else:
                _x0 = max(zone_start, int(_z.get("x0", zone_start)) - 2)
            _bias8 = _z.get("bias") or ("DEMAND" if _dir_key == "LONG" else "SUPPLY")
            _f8, _t8 = ZONE_PALETTE[("SR", _bias8 if _bias8 in ("SUPPLY", "DEMAND")
                                     else ("DEMAND" if _dir_key == "LONG" else "SUPPLY"))]
            _fam8 = _zone_family(_z.get("kind", ""))
            if (_fam8, _dir_key) in ZONE_PALETTE and _fam8 != "DEF":
                _f8, _t8 = ZONE_PALETTE[(_fam8, _dir_key)]
            ax.fill_between([_x0, zone_end], float(_z["bottom"]),
                            float(_z["top"]), color=_f8,
                            alpha=0.10 if _clean_zone_view else 0.18,
                            linewidth=0, zorder=1)
            _zone_items.append({"x0": float(_x0), "x1": float(zone_end),
                                "bottom": float(_z["bottom"]),
                                "top": float(_z["top"]),
                                "text": str(_z.get("kind") or ""),
                                "color": _t8})
        _yr9 = max(float(frame["high"].max()) - float(frame["low"].min()), 1e-9)
        _hi9 = frame["high"].to_numpy(float)
        _lo9 = frame["low"].to_numpy(float)
        _n9 = int(len(frame))

        _chip_taken: list = []

        def _place_in_box(_it):
            _wb = 1.4 + 0.52 * len(_it["text"])
            _mid = 0.5 * (_it["bottom"] + _it["top"])
            _hh = max(0.35 * (_it["top"] - _it["bottom"]), 0.015 * _yr9)
            _x0, _x1 = _it["x0"], min(_it["x1"], _n9 - 0.2)
            for _cx in (_x1 - _wb - 0.6, 0.5 * (_x0 + _x1) - _wb * 0.5,
                        _x0 + 0.6):
                _cx = min(max(_cx, 0.0), max(0.0, _n9 - _wb - 0.2))
                _a, _b = int(_cx), int(min(_n9, _cx + _wb + 1))
                if _b <= _a:
                    continue
                if not np.any((_hi9[_a:_b] >= _mid - _hh) &
                              (_lo9[_a:_b] <= _mid + _hh)):
                    if any((abs(_mid - _ty) < 0.030 * _yr9)
                           and (_cx < _tx1 + 1.0) and (_cx + _wb + 1.0 > _tx0)
                           for _tx0, _tx1, _ty in _chip_taken):
                        continue   # a sibling chip already lives here (FLIP↔DEMAND)
                    return _cx, _mid, "center"
            return None

        # Viva 09-23 polish («FLIP↔DEMAND overlap»): one occupancy registry for
        # every placed zone chip — an in-box spot that would touch an already
        # drawn chip (FLIP over DEMAND POI, etc.) is rejected, so the chip
        # falls through to the staggered top-edge anchors instead.
        _anchored = []
        for _it in _zone_items:
            _spot = _place_in_box(_it)
            if _spot:
                ax.text(_spot[0], _spot[1], _it["text"], color=_it["color"],
                        fontsize=7, va=_spot[2], ha="left", fontweight="bold",
                        zorder=12,
                        bbox={"boxstyle": "round,pad=0.26",
                              "facecolor": CHART_THEME["panel"],
                              "edgecolor": "none", "alpha": 1.0})
                _chip_taken.append((float(_spot[0]),
                                    float(_spot[0]) + 1.4 + 0.52 * len(_it["text"]),
                                    float(_spot[1])))
            else:
                _anchored.append(_it)
        # fallback: chip anchored to the box TOP edge at its left end
        _anchored.sort(key=lambda _it: -_it["top"])
        _prev9 = None
        for _it in _anchored:
            _y9 = float(_it["top"])
            if _prev9 is not None and _prev9 - _y9 < 0.035 * _yr9:
                _y9 = _prev9 - 0.035 * _yr9
            _prev9 = _y9
            ax.text(_it["x0"] + 0.6, _y9, _it["text"], color=_it["color"],
                    fontsize=7, va="bottom", ha="left", fontweight="bold",
                    zorder=12,
                    bbox={"boxstyle": "round,pad=0.26",
                          "facecolor": CHART_THEME["panel"],
                          "edgecolor": "none", "alpha": 0.78})
        _chip_ys8 = []
        for _bl8 in ((candidate.metadata or {}).get("brooks_labels") or []):
            notes.append((str(_bl8), CHART_THEME["muted"]))
        _htfp = (candidate.metadata or {}).get("render_htf_pattern")
        if _htfp:
            notes.append((f"PAT 4H · {str(_htfp)}", CHART_THEME["muted"]))
        # pattern render commands: wedge / triangle / channel / flag / range
        from analysis.render_kit import line_xy as _line_xy, line_y as _line_y_cal
        # R31.7 audit C4 (clutter): the setup's OWN validated lines (VIVA
        # upper/lower pivots) are drawn later; a render-kit pattern edge that
        # is the SAME line (same pivots, ≤0.35 ATR apart over its visible
        # stretch) is not painted a second/third time — BTC 15m 09-08 showed
        # three near-identical teal lines converging on one pivot.
        _ref_lines8 = []
        _ref_pivots8 = set()

        def _pv_key(_price) -> str:
            return f"{float(_price):.6g}"
        try:
            for _k8 in ("viva_upper_points", "viva_lower_points"):
                _p8 = (candidate.metadata or {}).get(_k8) or []
                _ref_pivots8.update(_pv_key(q["price"]) for q in _p8 if q.get("price") is not None)
                if len(_p8) >= 2:
                    _xx = [_x_of_ts(q.get("timestamp")) for q in _p8]
                    _yy = [float(q["price"]) for q in _p8]
                    if max(_xx) - min(_xx) > 1e-9:
                        _a8r, _b8r = np.polyfit(_xx, _yy, 1)
                        _ref_lines8.append(lambda x, a=float(_a8r), b=float(_b8r): a * x + b)
        except Exception:
            _ref_lines8 = []

        def _dup_of_drawn(_lnq, _xa_q: float, _atr_q: float, _child: bool = False) -> bool:
            # pivot sharing: a line built on the SAME swing points as a line
            # already on the canvas (2 shared pivots; a child line: 1) is a
            # redundant redraw of that structure
            try:
                _sh = sum(1 for q in (_lnq.get("points") or [])
                          if _pv_key(q.get("price")) in _ref_pivots8)
            except Exception:
                _sh = 0
            if _sh >= 2 or (_child and _sh >= 1):
                return True
            if _atr_q <= 0 or not _ref_lines8:
                return False
            _xs_q = (max(_xa_q, float(count) - 40.0), float(count))
            for _f in _ref_lines8:
                try:
                    if all(abs(float(_line_y_cal(_lnq, _xq)) - _f(_xq)) <= 0.35 * _atr_q
                           for _xq in _xs_q):
                        return True
                except Exception:
                    continue
            return False
        for _pat in ((candidate.metadata or {}).get("render_patterns") or []):
            if _pat.get("type") == "RANGE":
                # anchored to its oldest tested pivot when it carries a time
                _range_start = int(_anchored_x(_pat.get("ts0"), zone_start))
                ax.fill_between([_range_start, zone_end], float(_pat["lo"]),
                                float(_pat["hi"]), color=CHART_THEME["muted"],
                                alpha=0.07, linewidth=0, zorder=1)
                # CryptoCove reference (his 08-14 green-bg charts): a range
                # box carries a thin solid border AND a dashed midline.
                ax.plot([_range_start, _range_start, zone_end, zone_end, _range_start],
                        [float(_pat["lo"]), float(_pat["hi"]), float(_pat["hi"]),
                         float(_pat["lo"]), float(_pat["lo"])],
                        color=CHART_THEME["muted"], linewidth=0.7, alpha=0.5,
                        zorder=2)
                _mid8 = (float(_pat["lo"]) + float(_pat["hi"])) / 2
                ax.hlines(_mid8, _range_start, zone_end,
                          colors=CHART_THEME["muted"], linestyles="--",
                          linewidth=0.7, alpha=0.55, zorder=2)
                _rg = _place_in_box({"x0": float(_range_start),
                                     "x1": float(zone_end),
                                     "bottom": float(_pat["lo"]),
                                     "top": float(_pat["hi"]),
                                     "text": "RANGE"})
                if _rg:
                    ax.text(_rg[0], _rg[1], "RANGE", color=CHART_THEME["muted"],
                            fontsize=7, va=_rg[2], ha="left", fontweight="bold",
                            zorder=12,
                            bbox={"boxstyle": "round,pad=0.26",
                                  "facecolor": CHART_THEME["panel"],
                                  "edgecolor": "none", "alpha": 0.78})
                else:
                    ax.text(zone_start + 0.6, float(_pat["hi"]), "RANGE",
                            color=CHART_THEME["muted"], fontsize=7,
                            va="bottom", ha="left", fontweight="bold",
                            zorder=12,
                            bbox={"boxstyle": "round,pad=0.26",
                                  "facecolor": CHART_THEME["panel"],
                                  "edgecolor": "none", "alpha": 0.78})
                continue
            # Viva 09-18 placement law: lines are re-anchored by PIVOT
            # TIMESTAMP onto THIS frame (the fit window and the chart frame
            # are different slices — index coords misplaced every line) and
            # painted in the approved TLBREAK valid-line style: solid colored
            # edge through LIVE, dashed to the canvas edge, hollow circles on
            # every touch pivot.
            _lns = []
            for _ln0 in (_pat.get("lines") or []):
                # the stored slope is price per TRIGGER-TF bar; on a stepped-up
                # display TF a bar spans more time, so the slope rescales by
                # 1/scale (15m→1h: ×4) — the line keeps its true angle.
                _sl8 = float(_ln0["slope"]) / _tfscale
                _pt8 = _ln0.get("points") or []
                if _pt8:
                    _x0f = _x_of_ts(_pt8[0].get("ts"))
                    _ic8 = float(_pt8[0].get("price")) - _sl8 * _x0f
                else:
                    _x0f = max(0.0, (float(_ln0.get("x0", 0))
                                     - max(0, len(df) - len(frame))) * _tfscale)
                    _ic8 = float(_ln0["intercept"])
                _ln8 = {**_ln0, "slope": _sl8, "intercept": _ic8, "x0": _x0f}
                # R16 phase 3: a log-calibrated line rescales in LOG space
                # (log_slope/scale, re-anchored on the same pivot) — scaling
                # the linear tangent would bend it away from its pivots.
                if _ln0.get("log_fit"):
                    try:
                        import math as _m8
                        _ls8 = float(_ln0.get("log_slope") or 0.0) / _tfscale
                        _anch = ((_pt8[0].get("price") if _pt8 else None)
                                 or 10.0 ** (float(_ln0.get("log_slope") or 0.0)
                                             * float(_ln0.get("x0") or 0.0)
                                             + float(_ln0.get("log_intercept") or 0.0)))
                        _li8 = _m8.log10(float(_anch)) - _ls8 * _x0f
                        _y_now = 10.0 ** (_ls8 * (count + future) + _li8)
                        _ln8["log_slope"] = _ls8
                        _ln8["log_intercept"] = _li8
                        _ln8["slope"] = _m8.log(10.0) * _ls8 * _y_now
                        _ln8["intercept"] = _y_now - _ln8["slope"] * (count + future)
                    except Exception:
                        _ln8["log_fit"] = False
                _lns.append(_ln8)
            _atr9 = float((frame["high"] - frame["low"]).tail(14).mean())
            _flat8 = []
            _brk8 = []
            for _ln in _lns:
                _sl, _ic = float(_ln["slope"]), float(_ln["intercept"])
                _xa = max(0.0, float(_ln.get("x0", 0)))
                _xe = count + future - 0.5
                if _dup_of_drawn(_ln, _xa, _atr9, bool(_pat.get("child"))):
                    _flat8.append(False)
                    _brk8.append(False)
                    continue
                # later pattern edges are compared against this one too
                _ref_lines8.append(lambda x, _q=_ln: float(_line_y_cal(_q, x)))
                try:
                    _ref_pivots8.update(_pv_key(q.get("price")) for q in (_ln.get("points") or []))
                except Exception:
                    pass
                _col8 = CHART_THEME["supply"] if _ln.get("side") == "HIGH" \
                    else CHART_THEME["demand"]
                # Viva 09-18 (his AAVE ruling): a FLAT «trendline» is not a
                # trend — it is the supply/demand box of the base it came
                # from, so paint it as a zone band instead of a line.
                if _atr9 > 0 and abs(_sl) * max(1.0, count - _xa) < 0.5 * _atr9:
                    _y8 = _line_y_cal(_ln, count)
                    ax.fill_between([_xa, _xe], _y8 - 0.12 * _atr9,
                                    _y8 + 0.12 * _atr9, color=_col8,
                                    alpha=0.10, linewidth=0, zorder=1)
                    ax.text(_xe - 1.0, _y8,
                            "SUPPLY" if _ln.get("side") == "HIGH" else "DEMAND",
                            color=_col8, fontsize=6.5, va="center", ha="right",
                            fontweight="bold", zorder=12)
                    _flat8.append(True)
                    _brk8.append(False)
                    continue
                _flat8.append(False)
                # a BROKEN leg-trend paints only UP TO its break bar (his
                # AAVE blue ends where price crossed it); a live trend runs
                # solid to LIVE and dashed to the canvas edge.
                # the break bar is anchored by TIME when known (a bare index
                # would land on the wrong candle after a TF step-up)
                if _ln.get("break_ts"):
                    _bx8 = _anchored_x(_ln.get("break_ts"), 0.0) or None
                elif _ln.get("break_x") is not None and _tfscale != 1.0:
                    _bx8 = float(_ln.get("break_x")) * _tfscale
                else:
                    _bx8 = _ln.get("break_x")
                _brk8.append(_bx8 is not None)
                _xend8 = min(float(count), float(_bx8)) \
                    if _bx8 is not None else float(count)
                # spec §13: parent patterns thick & solid, children thin
                _lw8 = 1.2 if _pat.get("child") else 2.0
                _al8 = 0.60 if _pat.get("child") else 0.95
                # R16 phase 3: draw the CALIBRATED geometry. A log-fitted line
                # is a curve on a log axis, so it is painted as a polyline
                # through its own fit — that is what makes it touch the pivots
                # instead of hanging in the air. Linear lines keep the exact
                # two-point segment they always had.
                _xsA, _ysA = _line_xy(_ln, _xa, _xend8)
                ax.plot(_xsA, _ysA,
                        color=_col8, linewidth=_lw8, alpha=_al8, zorder=7,
                        solid_capstyle="round")
                if _bx8 is None and count < _xe - 0.6:
                    _xsB, _ysB = _line_xy(_ln, count, _xe)
                    ax.plot(_xsB, _ysB,
                            color=_col8, linewidth=_lw8 * 0.7, alpha=_al8 * 0.75,
                            zorder=6, linestyle=(0, (6, 4)),
                            solid_capstyle="butt")
                elif _bx8 is not None and _bx8 < _xe - 0.6:
                    # Viva 09-18: every trend EXTENDS past price so its break
                    # stays visible & alertable — broken history continues as
                    # a faint dotted projection into the future panel.
                    _xsC, _ysC = _line_xy(_ln, _xend8, _xe)
                    ax.plot(_xsC, _ysC,
                            color=_col8, linewidth=0.9, alpha=0.35, zorder=5,
                            linestyle=(0, (2, 3)), solid_capstyle="butt")
                _px8, _xs8 = [], []
                for q in (_ln.get("points") or []):
                    _qx = _x_of_ts(q.get("ts"))
                    if 0.0 <= _qx <= _xend8 + 0.5:
                        _xs8.append(_qx); _px8.append(float(q.get("price")))
                if _xs8:
                    ax.scatter(_xs8, _px8, s=30, color=CHART_THEME["panel"],
                               edgecolors=_col8, linewidths=1.4, zorder=9)
            # Viva 09-20 (his XRP/ASTER/AAVE/RENDER correction charts): on a
            # CONFIRMED chart the pattern's measured-move box was painted
            # straight into the red risk zone of a short tool — two geometries
            # fighting on one canvas. The trade tool owns a confirmed chart;
            # the pattern projection stays on analysis/alerts charts only.
            # Viva 09-21 (round 15 phase 2), repeated: «باکس سبز برای اسپات
            # است، روی فیوچرز نه». A switch is not a guarantee — a second render
            # path could still paint it. So the renderer itself refuses unless
            # the candidate declares the SPOT market: for futures the box is
            # hard-None, whatever CHART_MEASURE_BOX says.
            _mkt8 = str((candidate.metadata or {}).get("market")
                        or getattr(candidate, "market", "") or "").upper()
            _spot8 = bool(_mkt8 == "SPOT" or (candidate.metadata or {}).get("is_spot"))
            # ── Viva 09-22: the green measured-move box is a SPOT signature
            # («باکس‌های عمودی برای معاملات اسپات هستن») — so on a spot chart it
            # is always allowed (the feature flag is irrelevant, and spot cards
            # are born confirmed), while futures can never reach this branch.
            _spot8_box = bool(_spot8 and (not confirmed
                                          or (candidate.metadata or {}).get("spot_measured_box")))
            if _spot8_box and len(_lns) == 2 and not any(_flat8) and not any(_brk8):
                # CryptoCove measured-move box: pattern height projected from
                # the live price into the future panel — translucent green,
                # double-arrow spine, small value label on top.
                try:
                    _a8, _b8 = _lns[0], _lns[1]
                    _x8 = max(float(_a8.get("x0", 0)), float(_b8.get("x0", 0)))
                    _ya8 = float(_a8["slope"]) * _x8 + float(_a8["intercept"])
                    _yb8 = float(_b8["slope"]) * _x8 + float(_b8["intercept"])
                    _h8 = abs(_ya8 - _yb8)
                    _lc8 = float(frame["close"].iloc[-1])
                    _mean_sl8 = (float(_a8["slope"]) + float(_b8["slope"])) / 2
                    # ── Round 16 (Viva 09-22): from the FIRST warning onward
                    # the green box rides UP to the NEXT STRUCTURAL HIGH (+1%)
                    # — his CryptoCove reference («تا سقف بعدی ساختاری و کمی
                    # بالاترش رسم بشه») — instead of the raw pattern height.
                    _sbt8 = float((candidate.metadata or {}).get("spot_box_top") or 0.0)
                    if _sbt8 > _lc8:
                        _h8 = _sbt8 - _lc8
                    if _h8 > 0 and _lc8 > 0:
                        if _sbt8 > _lc8:
                            _bt8, _tp8 = _lc8, _sbt8
                        elif _mean_sl8 < 0:
                            _bt8, _tp8 = _lc8, _lc8 + _h8
                        else:
                            _bt8, _tp8 = _lc8 - _h8, _lc8
                        # keep the box INSIDE the visible panel (a 15%-tall
                        # wedge must not paint over the header like a banner)
                        _lo8 = float(frame["low"].min()); _hi8 = float(frame["high"].max())
                        _pd8 = 0.03 * (_hi8 - _lo8)
                        _bt8c = max(_bt8, _lo8 - _pd8); _tp8c = min(_tp8, _hi8 + _pd8)
                        if (_tp8c - _bt8c) < 0.25 * _h8:
                            _bt8c, _tp8c = _bt8, _tp8
                        _clamp8 = _tp8c < _tp8 - 1e-12
                        _label_clamp8 = _clamp8   # only the VALUE label clamps
                        _bt8, _tp8 = _bt8c, _tp8c
                        _bx0, _bx1 = count + 2, count + 2 + max(8, int(future * 0.55))
                        # Viva 09-23 polish: a box riding the chart's top edge
                        # keeps its value label INSIDE (va="top") — the label
                        # used to clip at the axes top.
                        # «باکس نصفش رو نزن» — a box sliced by the panel top is
                        # re-anchored DOWN so the whole box stays visible; the
                        # measured % label rides its top edge INSIDE the panel.
                        _hi8p = float(frame["high"].max())
                        _lo8p = float(frame["low"].min())
                        _rng8l = (_hi8p - _lo8p) or 1.0
                        if _tp8 > _hi8p + 0.02 * _rng8l and _bt8 < _hi8p:
                            _shift8 = _tp8 - (_hi8p - 0.03 * _rng8l)
                            _bt8 -= _shift8
                            _tp8 -= _shift8
                        _va8l, _yy8l = "bottom", _tp8
                        if _tp8 > _hi8p - 0.05 * _rng8l:
                            _va8l, _yy8l = "top", _tp8 - 0.014 * _rng8l
                        ax.fill_between([_bx0, _bx1], _bt8, _tp8,
                                        color=CHART_THEME["demand"],
                                        alpha=0.30, linewidth=0, zorder=2)
                        ax.plot([_bx0, _bx0, _bx1, _bx1, _bx0],
                                [_bt8, _tp8, _tp8, _bt8, _bt8],
                                color=CHART_THEME["demand"], linewidth=0.7,
                                alpha=0.55, zorder=3)
                        _mx8 = (_bx0 + _bx1) / 2
                        ax.annotate("", xy=(_mx8, _tp8), xytext=(_mx8, _bt8),
                                    arrowprops=dict(arrowstyle="<->",
                                                    color=CHART_THEME["text"],
                                                    lw=0.7, alpha=0.8),
                                    zorder=8)
                        ax.text(_mx8, _yy8l if _va8l == "top" else _tp8,
                                f"{_price(_h8)} ({_h8 / _lc8 * 100:.1f}%)",
                                color=CHART_THEME["muted"], fontsize=6.5,
                                ha="center",
                                va="top" if (_clamp8 or _va8l == "top") else "bottom",
                                zorder=9)
                except Exception:
                    pass
            elif _spot8_box and _lns and str((candidate.metadata or {}).get("engine") or "") == "SPOT":
                # ── Viva 09-22: a spot signal built on ONE broken line (his
                # «شکست خط روند نزولی») carries no wedge width, so the measured
                # box is the trade's own path: live price → last ladder target,
                # drawn the same way (upward, green, value + % label).
                try:
                    _lc9 = float(frame["close"].iloc[-1])
                    _tg9 = [float(x) for x in ((candidate.metadata or {}).get("target_ladder") or {})
                            .get("targets") or []]
                    if _tg9 and _lc9 > 0:
                        _tp9 = max(_tg9)
                        # Round 16: the structural top outranks the ladder's own
                        # last rung when the chart carries one (his CryptoCove law)
                        _sbt9 = float((candidate.metadata or {}).get("spot_box_top") or 0.0)
                        if _sbt9 > _lc9:
                            _tp9 = _sbt9
                        _h9 = _tp9 - _lc9
                        if _h9 > 0:
                            _bx0, _bx1 = count + 2, count + 2 + max(8, int(future * 0.55))
                            ax.fill_between([_bx0, _bx1], _lc9, _tp9,
                                            color=CHART_THEME["demand"],
                                            alpha=0.30, linewidth=0, zorder=2)
                            ax.plot([_bx0, _bx0, _bx1, _bx1, _bx0],
                                    [_lc9, _tp9, _tp9, _lc9, _lc9],
                                    color=CHART_THEME["demand"], linewidth=0.7,
                                    alpha=0.55, zorder=3)
                            _mx9 = (_bx0 + _bx1) / 2
                            _rng9l = (float(frame["high"].max()) - float(frame["low"].min())) or 1.0
                            _va9l, _yy9l = "bottom", _tp9
                            if _tp9 > float(frame["high"].max()) - 0.05 * _rng9l:
                                _va9l, _yy9l = "top", _tp9 - 0.014 * _rng9l
                            ax.annotate("", xy=(_mx9, _tp9), xytext=(_mx9, _lc9),
                                        arrowprops=dict(arrowstyle="<->",
                                                        color=CHART_THEME["text"],
                                                        lw=0.7, alpha=0.8),
                                        zorder=8)
                            ax.text(_mx9, _yy9l, f"{_price(_h9)} ({_h9 / _lc9 * 100:.1f}%)",
                                    color=CHART_THEME["muted"], fontsize=6.5,
                                    ha="center", va=_va9l, zorder=9)
                except Exception:
                    pass
            if _lns:
                _l0 = _lns[0]
                _cy8 = float(_l0["slope"]) * count + float(_l0["intercept"])
                # chips must never sit on top of each other (Viva 09-18)
                _rng8 = float(frame["high"].max() - frame["low"].min()) or 1.0
                for _yy8 in list(_chip_ys8):
                    if abs(_cy8 - _yy8) < 0.035 * _rng8:
                        _cy8 = _yy8 + 0.045 * _rng8
                _fr_span8 = max(float(frame["high"].max() - frame["low"].min()), 1e-12)
                # r23: clamp BEFORE the slot (the old order broke the gap it
                # had just reserved) and reserve a chip-sized footprint so
                # LIVE/pills can never print on the label again (TAO 15m)
                _cy8 = min(max(_cy8, float(frame["low"].min()) + 0.06 * _fr_span8),
                           float(frame["high"].max()) - 0.06 * _fr_span8)
                _cy8 = _slot_alloc(_right_slots, _cy8, _fr_span8, step=0.056)
                _right_texts.append(ax.text(count + 4.85, _cy8,
                        str(_pat.get("label") or _pat.get("type")), color=CHART_THEME["text"],
                        fontsize=7, va="center", ha="left", fontweight="bold",
                        zorder=12, clip_on=False,
                        bbox={"boxstyle": "round,pad=0.26",
                              "facecolor": CHART_THEME["panel"],
                              "edgecolor": "none", "alpha": 1.0}))

        # TLBREAK: draw the dynamic channel/trendline + parallel bound with
        # thin solid lines (Viva's chart style) using pivot timestamps.
        md = candidate.metadata or {}
        if md.get("tl_a_ts") and md.get("tl_b_ts"):
            try:
                idx = frame.index
                xa = _x_of_ts(md["tl_a_ts"])
                xb = _x_of_ts(md["tl_b_ts"])
                xanc = _x_of_ts(md.get("tl_anchor_ts") or md["tl_b_ts"])
                pa, pb = float(md["tl_a_price"]), float(md["tl_b_price"])
                if xb > xa:
                    slope = (pb - pa) / (xb - xa)
                    # R31.7 C1: slope from the TRUE pivot x; the painted
                    # segment starts at the frame edge on the same line
                    if xa < 0:
                        pa, xa = pa + slope * (0.0 - xa), 0.0
                    x_end = count + future - 0.5
                    ax.plot([xa, x_end], [pa, pa + slope * (x_end - xa)],
                            color=CHART_THEME["trend"], linewidth=1.65, alpha=0.92, zorder=8,
                            solid_capstyle="round", antialiased=True)
                    p_anc = float(md["tl_anchor_price"])
                    if xanc < 0:
                        p_anc, xanc = p_anc + slope * (0.0 - xanc), 0.0
                    ax.plot([xanc, x_end], [p_anc, p_anc + slope * (x_end - xanc)],
                            color=CHART_THEME["trend"], linewidth=1.35, alpha=0.75, zorder=8,
                            solid_capstyle="round", antialiased=True)
                    stage = md.get("tl_stage", "")
                    pattern_en = (md.get("tl_pattern") or "CHANNEL").upper()
                    if "TECHCLASSIC" in pattern_en:
                        # Viva 2026-09-13 «چرا دوتا تکنوکلاسیک داریم؟» — the badge
                        # chip brands the chart; the corner note must not repeat it.
                        pattern_en = str(md.get("tc_pattern") or "EDGE").upper()
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
        # PINWALL-specific second/risk entry: same candidate metadata and same
        # chart coordinates used by Telegram, so WebApp mirrors the exact line.
        try:
            _pw_e2 = float((candidate.metadata or {}).get("pinwall_entry2") or 0.0)
            if candidate.setup_code in {"PINVAL", "PINWALLQ"} and _pw_e2 > 0:
                ax.hlines(_pw_e2, line_start, line_end,
                          color=CHART_THEME["entry"], linewidth=1.05,
                          linestyles=(0, (3, 2)), zorder=7)
                notes.append((f"PINWALL ENTRY 2  {_price(_pw_e2)}", CHART_THEME["entry"]))
        except Exception:
            pass
        live_price = float(frame["close"].iloc[-1])
        # ── Round 13: the forming candle is part of `frame` now (appended above),
        # so it is drawn by the candle painter itself — same body, same wicks,
        # same width. No dashed ghost, no «FORMING» label. The LIVE pill keeps
        # carrying the live price with its clock (UTC, like the candle axis).
        _live_clock = ""
        try:
            _lt = pd.Timestamp(frame.index[-1])
            _lt = pd.Timestamp(_lt)
            if _lt.tzinfo is None:
                _lt = _lt.tz_localize("UTC")
            _live_clock = _lt.tz_convert("UTC").strftime("%H:%M UTC")
        except Exception:
            _live_clock = ""
        # Viva 09-23 («این قیمت نیاز به لیبل جداگانهٔ لایو روی چارت نداره؛ روی
        # همون ستون قیمت‌ها مشخص بشه»): NO floating live pill on the canvas —
        # the live price lives ON the price ladder as a TV-style tag (drawn
        # with the time-axis block below) and the live CLOCK lives on the time
        # axis under the youngest candle, so a glance answers «لایوه یا قدیمی؟».

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

        # Viva 2026-09-14 «این چه استاپ‌هایی هست گذاشتی روی ستاپ‌ها؟!» — an
        # UNCONFIRMED chart shows zone + trendline + invalidation ONLY.
        # Targets/trailing belong to the Confirmed chart; before confirmation
        # a TP line is a rumor painted over someone's plan. (This also removes
        # the TP1-vs-entry-label collision he flagged on ATOM/XLM/BCH.)

        if confirmed:
            # Viva 09-20 time-axis law: the LONG/SHORT position tool starts at
            # the REAL fill candle (fallback: the confirmation candle) and
            # extends to the live edge. It is never re-anchored to «the last
            # candle» on every render — that was the sliding he rejected.
            _entry_ts = ((candidate.metadata or {}).get("tool_entry_ts")
                         or getattr(candidate, "confirmed_at", "")
                         or (candidate.metadata or {}).get("tool_anchor_ts"))
            tool_start = int(_anchored_x(_entry_ts, max(0, count - 20)))
            tool_start = max(0, min(tool_start, count - 1))
            tool_end = count + 4.5
            # Viva 09-22: «اون فلش سبزِ کوچولو رو روی کندل‌ها و ابزار ننویس» —
            # the entry triangle and LONG/SHORT position label are gone. The
            # chart keeps only clean price lines/fills; direction remains in
            # the Telegram text and metadata, not over the candles.
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
            ladder = (candidate.metadata or {}).get("target_ladder") or {}
            ladder_targets = list(ladder.get("targets") or [candidate.tp1, candidate.tp2])
            ladder_weights = list(ladder.get("weights") or [50, 30, 20])
            levels = [
                (candidate.planned_entry, "ENTRY", CHART_THEME["entry"]),
                (candidate.sl, "FIRST STOP", CHART_THEME["invalidation"]),
            ]
            _tpg = (candidate.metadata or {}).get("tp_gates") or {}
            _tp_locked = set(_tpg.get("locked") or [])
            # Display labels are ranked by actual price path, not by the
            # storage order of legacy ladders. LONG: low→high; SHORT: high→low.
            # This fixes charts such as INJ where TP labels appeared 2,5,4,3,1
            # while preserving the underlying target values and lifecycle IDs.
            _display_targets = sorted(
                [(idx, float(level)) for idx, level in enumerate(ladder_targets)],
                key=lambda item: item[1], reverse=(str(candidate.direction).upper() == "SHORT"))
            for _rank, (_idx, level) in enumerate(_display_targets, start=1):
                label = str(_rank)
                levels.append((float(level), label,
                               CHART_THEME["tp1"] if (_rank <= 3 and _rank < len(ladder_targets)) else CHART_THEME["tp2"]))
            # Viva 09-23/24 night (13-chart audit): ONE pill per level. The old
            # 3%-merge produced mega-chips («TP4 INFO … · TP5 INFO …») that
            # spilled over the price axis, and near-level pills overlapped.
            # Now: every level gets its own pill; the slot allocator spaces
            # them (LIVE + pattern chips keep their already-taken slots), the
            # guide line always stays at the TRUE level, and the x-clamp below
            # widens the panel so nothing ever crosses the ladder.
            _yr0 = max(float(frame["high"].max()) - float(frame["low"].min()), 1e-9)
            _tol = 0.004 * _yr0          # collapse only near-identical levels
            _tags = list(levels)
            hit_index = int(ladder.get("hit_index") or (candidate.metadata or {}).get("hit_index") or 0)
            trailing_sl = float((candidate.metadata or {}).get("current_trailing_sl") or 0)
            if hit_index > 0 and trailing_sl > 0:
                _tags.append((trailing_sl, "SL", CHART_THEME["liquidity"]))
            _groups: list = []
            for level, label, color in _tags:
                for grp in _groups:
                    if abs(grp[0] - float(level)) <= _tol:
                        grp[1].append((label, float(level), color))
                        break
                else:
                    _groups.append([float(level), [(label, float(level), color)]])
            _groups.sort(key=lambda g: float(g[0]))
            # Pills are SPECs here and materialize AFTER the final y-limits
            # exist (the in-render ylim is still autoscale garbage — that was
            # the «pills in the sky» bug). The guide line always draws NOW at
            # the true level. (The interleave idea from the parallel branch —
            # dropping the pills entirely — was tried and Viva rejected it:
            # the pills ARE the tool, 09-23/24.)
            for _lvl, _items in _groups:
                for label, level, color in _items:
                    # Viva 09-16: solid guide lines read cleaner than dashes;
                    # only the trailing stop keeps its own tight dash.
                    _is_sl9 = str(label) == "SL"
                    _dash = (0, (2, 2)) if _is_sl9 else "-"
                    ax.hlines(level, tool_start, tool_end, color=color,
                              linewidth=1.25 if _is_sl9 else 1.15,
                              linestyles=_dash,
                              zorder=9 if _is_sl9 else 8)
                # Viva 09-24: numeric tags ride the column; the VALUES print ON
                # the price axis in the TP line's own colour (or live in the
                # confirmation message) — no big labels over candles/tool.
                _right_specs.append((
                    float(_lvl),
                    "  ·  ".join(str(_lb) for _lb, _pc, _c in _items),
                    _items[-1][2]))
                for _lb, _pc, _c in _items:
                    if (str(_lb).isdigit() or str(_lb) in ("SL", "ENTRY", "FIRST STOP")):
                        _axis_tags.append((float(_pc), _price(_pc), _c))

            # (Viva 2026-09-11) slanted PROJECTED-SCENARIO arrows removed from
            # confirmed charts too — the tagged TP ladder lines above are the
            # direction, drawn at true price levels, not guessed angles.

            # Viva 09-20 round 10: the R:R read-out is gone from the chart
            # panel too (his charts carried stale/negative ratios like
            # "R:R -0.13 / 0.38", which he crossed out — R:R is not part of
            # the decision any more, so it is not part of the picture).
            # Viva 09-21: «PATH 0.00%» on a confirmed chart was one of the
            # broken read-outs — a path that does not exist is not printed.
            _pathp8 = float(((candidate.metadata or {}).get("target_ladder") or {})
                            .get("path_pct") or 0.0)
            info = (
                f"{candidate.direction}  •  {_style_disp(candidate)}\n"
                f"SETUP  {candidate.setup_code}\n"
                f"SCORE  {candidate.score}/10"
            )
            if _pathp8 >= 0.5:
                info += f"\nPATH  {_pathp8:.2f}%  → 5 PARTS"
            _posi = ax.get_position()
            fig.text(
                _posi.x0 + 0.012,
                _posi.y0 + _posi.height - 0.028,
                info,
                ha="left",
                va="top",
                color=CHART_THEME["text"],
                fontsize=7.4,
                linespacing=1.4,
                zorder=25,
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
                ax.hlines(float(hi), max(0, count - 50), count - 0.5,
                          color=CHART_THEME["invalidation"], linestyle=(0, (1, 3)),
                          linewidth=0.8, alpha=0.5, zorder=4)
                notes.append((f"SWING HIGH  {_price(float(hi))}", CHART_THEME["invalidation"]))
            if pl:
                lo = min(p["price"] for p in pl[-6:])
                ax.hlines(float(lo), max(0, count - 50), count - 0.5,
                          color=CHART_THEME["demand"], linestyle=(0, (1, 3)),
                          linewidth=0.8, alpha=0.5, zorder=4)
                notes.append((f"SWING LOW  {_price(float(lo))}", CHART_THEME["demand"]))
        except Exception:
            pass

        # ── Viva v7.6 · valid trading range overlay ──────────────────────
        # If the frame contains a real range (top & bottom validated by >=2
        # pivot touches each), draw both boundaries across the chart and say
        # plainly whether price is INSIDE it (entry blocked until a break).
        if _CHART_RANGE_OVERLAY and not md.get("tc_clean"):
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
                            # ── Viva 09-22 (round 16): the full-width RANGE
                            # hlines are GONE — «یک خط طوسی ادامه میده اونم
                            # باز می‌افته روی کندل لایو و دید رو کور میکنه ..
                            # اونم حذف بشه». The corner notes + the INSIDE/
                            # OUTSIDE verdict keep the information; the candles
                            # keep the view.
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
                _up0 = md.get("viva_upper_points") or []
                _lo0 = md.get("viva_lower_points") or []
                if len(_up0) >= 2 and len(_lo0) >= 2:
                    try:
                        def _fitpts(pts):
                            xs_ = [_x_of_ts(p.get("timestamp")) for p in pts]
                            ys_ = [float(p["price"]) for p in pts]
                            if not all(math.isfinite(v) for v in xs_ + ys_) \
                                    or max(xs_) - min(xs_) < 1e-9:
                                raise ValueError("degenerate fit span")
                            s_, b_ = np.polyfit(xs_, ys_, 1)
                            return s_, b_
                        # Viva 09-18: the grey-blue band between the two
                        # valid lines («سایه آبی پشتش») is GONE — lines only.
                    except Exception:
                        pass
                for key, color, label in (("viva_upper_points", CHART_THEME["supply"], "VALID UPPER LINE"), ("viva_lower_points", CHART_THEME["demand"], "VALID LOWER LINE")):
                    points = md.get(key) or []
                    if len(points) < 2:
                        continue
                    xs, ys = [], []
                    for point in points:
                        x = _x_of_ts(point.get("timestamp"))
                        xs.append(x); ys.append(float(point["price"]))
                    if len(xs) < 2 or not all(math.isfinite(v) for v in xs + ys) \
                            or max(xs) - min(xs) < 1e-9:
                        continue
                    # Phase-3: log-space fit when the log axis is live & span>3%
                    _mode9, slope, intercept = _pivot_line_fit(ax, frame, xs, ys)
                    def _fy9(_x9, _s=slope, _b=intercept, _m=_mode9):
                        return 10 ** (_s * _x9 + _b) if _m == "log" else _s * _x9 + _b
                    def _fx9(_p9, _s=slope, _b=intercept, _m=_mode9):
                        return (math.log10(_p9) - _b) / _s if _m == "log" else (_p9 - _b) / _s
                    # Viva 2026-09-11 (v2, the «هرچی میگم انجام نمیشه» fix): the
                    # edge spans the WHOLE frame — from the first bar where it
                    # is inside the visible price range (major-pivot start),
                    # solid through LIVE, dashed past it to the canvas edge.
                    x_edge = count + future - .5
                    _pmin = float(frame["low"].min())
                    _pmax = float(frame["high"].max())
                    x0 = min(xs)
                    if abs(slope) > 1e-12:
                        _xa = _fx9(_pmax)
                        _xb = _fx9(_pmin)
                        x_left = max(0.0, min(_xa, _xb))
                        x0 = min(x0, x_left)
                    else:
                        x0 = 0.0
                    x0 = max(0.0, x0)   # R31.7 C1: pivots may predate the frame
                    x1 = min(max(xs) + 0.15 * max(1.0, max(xs) - min(xs)), x_edge, count)
                    _xr = max(x1, min(x_edge, count))
                    ax.plot([x0, _xr], [_fy9(x0), _fy9(_xr)],
                            color=color, linewidth=2.3, alpha=.95, zorder=7, solid_capstyle="round")
                    if count < x_edge - 0.6:
                        ax.plot([count, x_edge], [_fy9(count), _fy9(x_edge)],
                                color=color, linewidth=1.5, alpha=.72, zorder=6,
                                linestyle=(0, (6, 4)), solid_capstyle="butt")
                    _vis9 = [(x_, y_) for x_, y_ in zip(xs, ys) if x_ >= 0.0]
                    if _vis9:
                        ax.scatter([v[0] for v in _vis9], [v[1] for v in _vis9], s=42,
                                   color=CHART_THEME["panel"], edgecolors=color, linewidths=1.7, zorder=9)
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
                proj = md.get("tc_projection")
                if proj:
                    try:
                        p_from = float(proj.get("from")); p_to = float(proj.get("to"))
                        d = str(proj.get("direction") or "LONG").upper()
                        col = CHART_THEME["demand"] if d == "LONG" else CHART_THEME["supply"]
                        if md.get("tc_clean"):
                            # family style (same as TLBREAK/ALBROX previews): dashed
                            # level + small right-edge tag — no giant projection box
                            bx1 = count + future - 0.5
                            for lvl, tag in ((p_to, "TC TARGET"),
                                             *(  [(float(md["tc_mid"]), "TC MID")] if md.get("tc_mid") else [])):
                                if lvl <= 0:
                                    continue
                                ax.hlines(lvl, count - 1, bx1, color=col, linewidth=1.0,
                                          linestyles=(0, (4, 3)), zorder=6)
                                ax.text(bx1, lvl, f"{tag}  {_price(lvl)}", color="white",
                                        fontsize=7.5, fontweight="bold", ha="right", va="center", zorder=9,
                                        bbox=dict(boxstyle="round,pad=0.28", facecolor=col, edgecolor="none"))
                        else:
                            # Viva 2026-09-11: the giant projection RECTANGLE is
                            # deleted everywhere — even a non-clean candidate now
                            # renders the tagged-level style instead of a box.
                            bx1 = count + future - 0.5
                            ax.hlines(p_to, count - 1, bx1, color=col, linewidth=1.0,
                                      linestyles=(0, (4, 3)), zorder=6)
                            ax.text(bx1, p_to, f"TARGET  {_price(p_to)}", color="white",
                                    fontsize=7.5, fontweight="bold", ha="right", va="center", zorder=9,
                                    bbox=dict(boxstyle="round,pad=0.28", facecolor=col, edgecolor="none"))
                        notes.append((f"MEASURED TARGET  {_price(p_to)}", col))
                    except Exception:
                        pass
                bbase = md.get("tc_base")
                if bbase and len(bbase) == 2 and not md.get("tc_clean"):
                    try:
                        blo, bhi = sorted((float(bbase[0]), float(bbase[1])))
                        x0b = max(0, count - 9)
                        ax.fill_between([x0b, count], blo, bhi, color=CHART_THEME["muted"],
                                        alpha=0.10, zorder=2)
                        ax.plot([x0b, count, count, x0b, x0b], [blo, blo, bhi, bhi, blo],
                                color=CHART_THEME["muted"], linewidth=1.0, alpha=0.7, zorder=5)
                        ax.hlines((blo + bhi) / 2, x0b, count, color=CHART_THEME["muted"],
                                  linestyles=(0, (4, 3)), linewidth=0.8, alpha=0.7, zorder=5)
                        notes.append(("BASE BOX", CHART_THEME["muted"]))
                    except Exception:
                        pass
                watch_points = md.get("viva_watch_points") or []
                if len(watch_points) == 2:
                    # own try/except: a degenerate 2-pivot fit must not kill the
                    # score note below it, and must not spam the overlay warning
                    try:
                        xs, ys = [], []
                        for point in watch_points:
                            xs.append(_x_of_ts(point.get("timestamp")))
                            ys.append(float(point["price"]))
                        if not all(math.isfinite(v) for v in xs + ys) or max(xs) - min(xs) < 1e-9:
                            raise ValueError("degenerate watch fit")
                        _modew, slope, intercept = _pivot_line_fit(ax, frame, xs, ys)
                        def _fyw(_xw, _s=slope, _b=intercept, _m=_modew):
                            return 10 ** (_s * _xw + _b) if _m == "log" else _s * _xw + _b
                        _xw0 = max(0.0, xs[0])
                        ax.plot([_xw0, count + future - .5], [_fyw(_xw0), _fyw(count + future - .5)], color=CHART_THEME["liquidity"], linewidth=1.25, linestyle=(0,(3,3)), alpha=.85, zorder=6)
                        _visw = [(x_, y_) for x_, y_ in zip(xs, ys) if x_ >= 0.0]
                        xs, ys = [v[0] for v in _visw], [v[1] for v in _visw]
                        ax.scatter(xs, ys, s=22, color=CHART_THEME["panel"], edgecolors=CHART_THEME["liquidity"], linewidths=1.0, zorder=9)
                        notes.append(("2-PIVOT WATCH · NO ENTRY", CHART_THEME["liquidity"]))
                    except Exception:
                        pass
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
        if (_CHART_STRUCTURE_LINES and not md.get("tc_clean")
                and candidate.setup_code not in ("TLBREAK", "TECHCLASSIC") and bool(md.get("chart_validated_trendline"))):
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
        # Clean structure mode keeps detection unchanged but removes visual noise:
        # the engine still sees every zone/FVG/candle; the chart shows only the
        # most actionable structural zones so the geometry remains readable.
        notes = _setup_stickers(candidate, confirmed) + notes
        if not _clean_zone_view:
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

        # ── FINAL pill materialization (Viva 09-23/24): with the y-limits now
        # FINAL, allocate the label column and draw every pill — then widen
        # the panel (bounded) until the whole column sits INSIDE the axes.
        try:
            fig.canvas.draw()
            _lo2, _hi2 = ax.get_ylim()
            _sp2 = max(_hi2 - _lo2, 1e-9)
            _right_specs.sort(key=lambda t: float(t[0]))
            _b2 = 0.025 * _sp2
            _rows2: List[List[float]] = []
            for _lvl2, _lab2, _col2 in sorted(
                    _right_specs, key=lambda t: -abs(float(t[0]) - (_lo2 + _hi2) / 2.0)):
                # clamp BEFORE allocating (the old order let a clamped pill
                # land on an already-taken slot → ADA ENTRY×LIVE overlap)
                _tgt2 = min(max(float(_lvl2), _lo2 + _b2), _hi2 - _b2)
                _y2 = _slot_alloc(_right_slots, _tgt2, _sp2, step=0.042)
                _rows2.append([_y2, _lab2, _col2])
            # r23: the clamp/push above can still fold neighbours — one
            # deterministic pass now GUARANTEES the gap on every chart
            _relayout_pills(_rows2, _lo2 + _b2, _hi2 - _b2, 0.036 * _sp2)
            for _y2, _lab2, _col2 in _rows2:
                _right_texts.append(_level_tag(ax, count + 4.85, _y2, _lab2, _col2))
            # Viva 09-24: TP/SL VALUES as TV-style tags ON the price ladder,
            # coloured by their own line — never a big label over the candles.
            if _axis_tags:
                import matplotlib.transforms as _mtr9
                _tr9 = _mtr9.blended_transform_factory(ax.transAxes, ax.transData)
                for _lv9, _pv9, _cv9 in _axis_tags:
                    _yv9 = min(max(_lv9, _lo2), _hi2)
                    ax.text(1.004, _yv9, _pv9, transform=_tr9, color=_cv9,
                            fontsize=6.3, va="center", ha="left", zorder=13,
                            clip_on=False,
                            bbox={"boxstyle": "round,pad=0.22",
                                  "facecolor": CHART_THEME["panel"],
                                  "edgecolor": _cv9, "alpha": 0.95,
                                  "linewidth": 0.5})
            fig.canvas.draw()
            _rend = fig.canvas.get_renderer()
            _inv = ax.transData.inverted()
            _need = float(count + future)
            for _t in _right_texts:
                try:
                    _bb = _t.get_window_extent(_rend)
                    _need = max(_need, float(_inv.transform((_bb.x1 + 7, 0))[0]) + 1.2)
                except Exception:
                    continue
            if _need > count + future:
                _fut2 = min(_need - count, future + 30.0)
                for _ca in axes:
                    _ca.set_xlim(-1, count + _fut2)
                fig.canvas.draw()
        except Exception as exc:
            print(f"chip column clamp warning: {exc}")
        _render_corner_notes(ax, notes, frame, confirmed=confirmed, fig=fig)

        # Viva 2026-09-14 «تایم‌فریم پوزیشن یک‌ساعته‌ست، چارت ۴ ساعته میدی؟!» —
        # the title is ALWAYS the position's own trigger timeframe, on every
        # setup. The pattern timeframe is a PAT reference in the subline and
        # can never override the title or the tape underneath it.
        _tf_disp = str(candidate.trigger_timeframe or md.get("pin_tf") or "").upper()
        fig.text(
            0.055,
            0.952,
            f"{candidate.symbol}  •  {str(_tf_disp).upper()}  •  {_style_disp(candidate)}  •  {candidate.direction}",
            color=CHART_THEME["text"],
            fontsize=14,
            fontweight="bold",
            va="center",
        )
        fig.text(
            0.055,
            0.922,
            f"{candidate.setup_code}  ·  {_chart_market_label(candidate)}  ·  TRIG {candidate.trigger_timeframe.upper()}"
            f"{' · PAT ' + str(md.get('tl_context_tf')).upper() if md.get('tl_context_tf') else ''}"
            f"  ·  {_setup_identity(candidate)['brand']} ✦ "
            f"{'CONFIRMED' if confirmed else 'ANALYSIS'}",
            color=CHART_THEME["muted"],
            fontsize=8,
            va="center",
        )
        # ── Viva 09-21: «چرا چارت پینوال کیو استیکر بنام خودش نداره و بنام viva
        # setup درج میشه در جای استیکر هر ستاپ؟» — the header word is the FALLBACK
        # only. When the setup's own badge exists it is the label; when it does
        # not, the setup's own name stands there (never a generic brand word
        # pretending to be a setup badge). Every setup in the live DB now has a
        # badge file: PINVAL · PINWALLQ · TLBREAK · TECHCLASSIC · ALBROX.
        _has_sticker = _add_setup_sticker(fig, candidate)
        if not _has_sticker:
            fig.text(0.762, 0.931, str(candidate.setup_code or "").upper(),
                     color=CHART_THEME["text"], fontsize=9.5, fontweight="bold", va="center")
        _add_branding(fig, ax, candidate)

        # ── Viva 09-23 («در کندل لایو حتماً تاریخ و ساعت مشخص باشه که متوجه
        # بشم لایوه یا قدیمیه»): figure-level LIVE stamp under the YOUNGEST
        # candle — drawn after the final xlim so the data→figure mapping is
        # exact, and ABOVE every axes (nothing can bury it).
        try:
            _lt = pd.Timestamp(frame.index[-1])
            if _lt.tzinfo is None:
                _lt = _lt.tz_localize("UTC")
            _live_stamp = _lt.tz_convert("UTC").strftime("%m-%d %H:%M UTC")
            fig.canvas.draw()
            _xd = fig.transFigure.inverted().transform(
                axes[2].transData.transform((len(frame) - 1, 0.0))
            )[0]
            _vol_y0 = axes[2].get_position().y0
            fig.text(_xd, _vol_y0 - 0.022, f" {_live_stamp} ",
                     ha="center", va="top", fontsize=7.6, fontweight="bold",
                     color="white", zorder=40,
                     bbox={"boxstyle": "round,pad=0.3", "facecolor": "#2b2f3a",
                           "edgecolor": "none"})
        except Exception as _exc:
            print(f"Chart live-stamp warning: {_exc}")

        buffer = io.BytesIO()
        fig.savefig(
            buffer,
            format="png",
            dpi=int(os.getenv("CHART_DPI", "240") or 240),
            facecolor=CHART_THEME["figure"],
            edgecolor="none",
        )
        plt.close(fig)
        buffer.seek(0)
        _png = buffer.read()
        _chart_cache_set(_ck, _png)
        return _png
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


def _final_stop_guard(candidate: SignalCandidate) -> SignalCandidate:
    """Viva 09-22 (his ADAUSDT 1h chart: entry 0.2197 / stop 0.2397 ≈ 9%):
    «استاپ طبق سقف همان تایم‌فریم». Whatever path built the stop — pinbar,
    structure, absorb, snapshot — the LAST touch before a chart or a message is
    published clamps it onto the timeframe's own ceiling (R14 table), never
    onto the entry, and reports the clamp so the message can say it.
    """
    try:
        from analysis.trade_management import stop_ceiling_pct
        tf = str(getattr(candidate, "trigger_timeframe", "15m") or "15m").lower()
        entry = float(getattr(candidate, "planned_entry", 0) or 0)
        sl = float(getattr(candidate, "sl", 0) or 0)
        if entry <= 0 or sl <= 0:
            return candidate
        # ── round 16 (Viva 09-22, «هیچ ارتباطی بین ستاپ‌های فیوچرز و اسپات»):
        # a SPOT card is clamped by SPOT's own 10% law — the futures per-TF
        # table (2.75% on 1d …) must never touch the spot engine.
        _mdg = candidate.metadata if candidate.metadata is not None else {}
        if str(_mdg.get("market") or getattr(candidate, "market", "") or "").upper() == "SPOT":
            from analysis.spot_engine import SPOT_STOP_CAP_PCT
            cap_pct = float(SPOT_STOP_CAP_PCT) / 100.0
        else:
            cap_pct = float(stop_ceiling_pct(tf)) / 100.0
        dist = abs(sl - entry) / entry
        if dist <= cap_pct + 1e-12:
            return candidate
        new_sl = entry * (1.0 - cap_pct) if str(candidate.direction).upper() == "LONG" \
            else entry * (1.0 + cap_pct)
        candidate.sl = float(new_sl)
        md = candidate.metadata if candidate.metadata is not None else {}
        md["stop_clamped"] = f"{cap_pct * 100:.2f}%"
        md["stop_clamped_fa"] = (
            f"استاپ ساختاری {dist * 100:.2f}٪ از ورود فاصله داشت؛ طبق سقف تایم "
            f"{tf.upper()} روی {cap_pct * 100:.2f}٪ بریده شد (سناریو حذف نمی‌شود).")
        return candidate
    except Exception:
        return candidate


def build_educational_message(candidate: SignalCandidate) -> str:
    candidate = _final_stop_guard(candidate)
    _clock_block = "\n".join(_timing_lines(candidate))
    direction_fa = "سناریوی احتمالی خرید" if candidate.direction == "LONG" else "سناریوی احتمالی فروش"
    evidence_blocks = []
    for item in candidate.evidence:
        status = "✅" if item.confirmed else "⚠️"
        evidence_blocks.append(f"{status} <b>{_e(item.title)}</b>\n\n{_e(item.detail)}")
    # FORMAT-2 (audit 09-15): the 🧩 section merges candidate.confirmations
    # with the technical aids. Two bugs fixed: (1) _tech_aids_lines already
    # carries its own "• " — re-bulleting produced "• • 📊"; (2) the empty
    # fallback «تأیید کمکی اضافه‌ای ثبت نشده است.» used to print even when
    # aids existed right below it — a self-contradicting message. The
    # fallback now only speaks when the merged list is truly empty.
    # FORMAT-3 (Viva 09-16): part-2 concepts are SEPARATED by item rules and
    # every title is bold — «بین مفاهیم خطوط جداکننده بیاد، وگرنه نامفهوم است».
    _aid_lines = _tech_aids_lines(candidate)
    _conf_lines = [f"• {_e(item)}" for item in candidate.confirmations] + _aid_lines
    if not _conf_lines:
        _conf_lines = ["• تأیید کمکی اضافه‌ای ثبت نشده است."]
    warn_items = [str(x) for x in (candidate.warnings or []) if str(x).strip()]
    if not warn_items:
        warn_items = ["این پیام فقط رصد بازار است؛ شرط تبدیل به سیگنال در بخش ⚖️ آمده است.",
                      f"عبور معتبر از {_price(candidate.sl)} سناریو را باطل می‌کند."]
    _warn_lines = [f"• {_e(x)}" for x in warn_items]
    # «مهم‌ترین نشانهٔ داخلی روی ناحیه + تحلیل دوخطی» — whichever of
    # engulfing/pin/doji/compression actually formed, in the setup's own voice.
    _zt = (candidate.metadata or {}).get("zone_trigger") or {}
    _zt_sec = ""
    if _zt.get("title_fa"):
        _zt_sec = (f"🔥 <b>نشانهٔ فعال روی ناحیه</b>\n<b>{_e(str(_zt['title_fa']))}</b>\n"
                   + "\n".join(_e(str(x)) for x in (_zt.get("lines") or [])) + "\n"
                   + VIVA_SEP + "\n")
    # empty sections never print as a gap between two separators (Viva law
    # 2026-09-12): the block exists only when it carries content
    if evidence_blocks:
        evidence_sec = ("\n\n" + VIVA_SEP + "\n\n"
                        + ("\n\n" + VIVA_SEP + "\n\n").join(evidence_blocks)
                        + "\n\n" + VIVA_SEP + "\n")
    else:
        evidence_sec = "\n" + VIVA_SEP + "\n"
    tf_tag = str(candidate.trigger_timeframe or "").upper()
    head = str(candidate.strategy_fa)
    setup_line_fa = head.split("|", 1)[-1].strip() if "|" in head else head
    return (
        # Viva 2026-09-12 (verbatim skeleton): 🏷 label first, the unique 🆔
        # code right under it (same rule as the hit messages), then the fixed
        # educational header block; every concept separated by ━━━ to the end.
        f"🏷 <b>VIVA-{_e(candidate.setup_code)}</b>\n"
        f"🆔 <code>{_e(_public_code(candidate))}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📚 <b>تحلیل آموزشی | ستاپ در حال بررسی</b>\n"
        f"⛔ <b>این پیام تأیید ورود نیست</b>\n"
        f"👀 فقط برای رصد بازار و اهداف آموزشی\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>{_e(candidate.symbol)}</b>  •  {_e(candidate.style)}  •  {_e(tf_tag)}\n"
        f"🌐 {_e(_market_label(candidate))}\n"
        f"🧭 {_e(direction_fa)}\n"
        f"🎯 ستاپ: <b>VIVA-{_e(candidate.setup_code)}</b> | {_e(setup_line_fa)}\n"
        f"⭐ امتیاز فعلی: <b>{candidate.score}/10</b>\n"
        + evidence_sec
        +        f"🔎 <b>ناحیه‌ای که زیر نظر داریم</b>\n\n"
        f"از <b>{_price(candidate.entry_zone_bottom)}</b> تا <b>{_price(candidate.entry_zone_top)}</b>\n"
        f"سطح ابطال سناریو: <b>{_price(candidate.sl)}</b>\n"
        + ("🛑 استاپ ساختاری دورتر از سقفِ این تایم‌فریم بود؛ طبق قانون ۰۹-۲۱ استاپ روی سقف "
           "تنظیم شد و سناریو حفظ شد.\n" if (candidate.metadata or {}).get("stop_clamped") else "")
        + (f"🎯 <b>ورود دوم ریسکی PINWALL: {_price(float((candidate.metadata or {}).get('pinwall_entry2')))}</b>\n"
           f"این ورود فقط برای PINWALL است؛ بعد از کلوز معتبر، نزدیک سویینگ محلی قرار می‌گیرد و استاپ اصلی پشت همان سویینگ می‌ماند.\n"
           if candidate.setup_code in {"PINVAL","PINWALLQ"} and float((candidate.metadata or {}).get("pinwall_entry2") or 0) > 0 else "")
        +
        f"{VIVA_SEP}\n"
        + _confirm_rule_block(candidate) + "\n"
        f"{VIVA_SEP}\n"
        f"🧭 <b>کانتکست تایم بالاتر</b>\n"
        + "\n".join(
            f"• {_e(b)}" for b in _htf_context_bits(candidate)) + "\n"
        f"{VIVA_SEP}\n"
        f"🧩 <b>تأییدهای کمکی</b>\n"
        + "\n".join(_conf_lines) + "\n"
        f"{VIVA_SEP}\n"
        + _zt_sec
        + "⚠️ <b>شرایط و هشدارها</b>\n"
        + "\n".join(_warn_lines) + "\n"
        + f"{VIVA_SEP}\n"
        + _ai_detail_block(candidate)
        + f"⛔ ورود، اهرم و حجم پوزیشن هنوز پیشنهاد نمی‌شود\n"
        f"✅ در صورت تکمیل شرایط، ابتدا Approaching و سپس Confirmed ارسال می‌شود.\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        + _clock_block + "\n"
        + f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>{_e(SETTINGS.channel_name)}</b>"
    )


def _ai_detail_block(candidate: SignalCandidate) -> str:
    """Viva 2026-09-14 «این فرمت و قوانین بصری برای همهٔ ستاپ‌ها یکسان است»:
    the detailed alert ALWAYS carries the AI read + the management preview —
    the sections VIVA-TLBREAK used to own. PINWALLQ, PINWALL, ALBROX and
    PINVAL now speak with the same voice; only the content differs per setup."""
    out: List[str] = []
    try:
        variant = str((candidate.metadata or {}).get("strategy_variant") or "")
        if variant == "VIVA_TLBREAK":
            out.append(_sep_bullets(_viva_tlbreak_sections(candidate)) + "\n")
        else:
            out.append(_sep_bullets(_ai_note(candidate)) + "\n")
            try:
                from bot.messages_viva_tlbreak import management_fa
                final = float((candidate.metadata or {}).get("viva_final_target")
                              or candidate.tp2 or 0)
                if final:
                    out.append(_sep_bullets(management_fa(candidate.planned_entry, candidate.sl, final,
                                             candidate.direction,
                                             title=f"VIVA-{candidate.setup_code}")) + "\n")
            except Exception:
                pass
    except Exception:
        return ""
    out.append(f"{VIVA_SEP}\n")
    return "\n".join(x for x in out if x.strip())


def _market_intelligence_block(candidate: SignalCandidate) -> str:
    """R31 — compact auxiliary order-flow/derivatives read.

    This section is additive only: it cannot alter setup geometry, unique IDs,
    message chaining, fonts, headings, or execution decisions.
    """
    try:
        from analysis.market_intelligence import intelligence_note
        lines = intelligence_note(candidate)
    except Exception:
        lines = []
    if not lines:
        return ""
    return "📡 <b>تحلیل کمکی جریان بازار</b>\\n" + "\\n".join(f"• {_e(x)}" for x in lines)


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
    elif candidate.setup_code in ("PINWALLQ", "PINVAL", "PINWALL"):
        # Viva 2026-09-15 («نظر هوش مصنوعی و ... هم بهینه کن»): the pin family
        # gets its OWN doctrine read — what the pin did, what activates the
        # scenario, and the quality anatomy when the Q score exists.
        _q = md.get("pinwall_quality") or {}
        if _q:
            lines.append(
                f"اجزای امتیاز کیفیت: آناتومی {float(_q.get('anatomy') or 0):g}/30، "
                f"موقعیت {float(_q.get('location') or 0):g}/27، "
                f"کانتکست {float(_q.get('context') or 0):g}/20، "
                f"بایاس {float(_q.get('bias') or 0):g}/10.")
        lines.append("پین‌بار نقدشوندگیِ ناحیه را جارو کرده و بسته‌شدنش نشانهٔ ورودِ پولِ مخالف است؛ "
                     "اما خودِ پین دستور ورود نیست — اعتبار با اولین کلوزِ معتبر به جهت سناریو است.")
        lines.append("بازگشت قیمت به میانهٔ بدنهٔ پین، نشانهٔ ضعفِ سناریوی بازگشتی است؛ "
                     "تا آن لحظه ناحیه زیر نظر می‌ماند.")
        if md.get("pin_zone_fa"):
            lines.append(f"محل پین: {str(md['pin_zone_fa'])} — هرچه ناحیه تازه‌تر و لمس‌نشده‌تر، واکنش معتبرتر.")
    elif candidate.setup_code == "ALBROX":
        lines.append("اسپایک غیرعادی، بازپس‌گیری جزئی و بیسِ فشردهٔ ۶ تا ۱۰ کندلی با کلوز شکسته شده — "
                     "دکترین: ادامهٔ حرکت به جهتِ بازپس‌گیری.")
        lines.append("نقضِ سناریو: بازگشت کلوز به داخلِ بیس؛ تا بیرون ماندنِ کلوز، بریک معتبر است.")
        if md.get("albrox_pinwall_confirm"):
            lines.append("پین‌بارِ هم‌جهت هم روی ناحیه ثبت شده — تأییدیهٔ کمکیِ پینوال برای همین سناریو.")
    elif candidate.setup_code == "TECHCLASSIC":
        lines.append("الگوی کلاسیک روی لبهٔ ناحیه شکل گرفته — ابطالِ الگو همان سطحِ ابطالِ سناریو است؛ "
                     "منتظر کلوزِ فراتر از ضلعِ الگو بمان، نه شدوی لحظه‌ای.")
    # Viva 09-20 round 10: the rr advice line is retired together with the
    # gate — the ladder is a price path, not a ratio, so no R:R warning.

    if not candidate.execution_ready:
        lines.append("یکی از گیت‌های اجباری هنوز سبز نیست؛ این تحلیل آموزشی است و وارد فاز اجرایی نمی‌شود.")
    adx_ctx = float(md.get("adx", 0) or 0)
    if adx_ctx >= 25:
        lines.append(f"روند پرانرژی است (ADX≈{adx_ctx:.0f})؛ پولبک‌های کوتاه‌مدت‌تر از انتظار معمول‌اند.")
    lines.append(f"ابطال سناریو: عبور معتبر از {_price(candidate.sl)} — قبل از آن هیچ تصمیمی نگیر.")
    return "🤖 <b>پیشنهاد هوش مصنوعی</b>\n" + "\n".join(f"• {_e(x)}" for x in lines)


def build_approaching_message(candidate: SignalCandidate, current_price: float, distance_atr: float) -> str:
    candidate = _final_stop_guard(candidate)
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
        f"{_market_intelligence_block(candidate)}\n\n"
        f"{_ai_note(candidate)}\n\n"
        f"👀 آماده بررسی چارت باشید، اما تا پیام Confirmed وارد نشوید.\n"
        f"📢 <b>{_e(SETTINGS.channel_name)}</b>"
    )


def build_confirmed_message(candidate: SignalCandidate) -> str:
    candidate = _final_stop_guard(candidate)
    mm = build_money_management(candidate)
    reasons = []
    for index, item in enumerate([item for item in candidate.evidence if item.confirmed], start=1):
        reasons.append(f"<b>{index}. {_e(item.title)}</b>\n{_e(item.detail)}")
    mm_warning = "\n⚠️ حجم به سقف Margin مجاز محدود شده است." if mm.get("margin_capped") else ""
    invalidation_label = (
        "قیمت ابطال تحلیل (مرجع محاسبه، نه دستور اجباری Stop)"
        if candidate.style.upper() in {"SWING", "GRAND"}
        else "قیمت ابطال تحلیل / Stop پیشنهادی"
    )
    management_note = (
        "در Swing این سطح مرز ابطال تحلیل است؛ محل سفارش Stop و نحوه خروج باید با مدیریت شخصی معامله‌گر تنظیم شود."
        if candidate.style.upper() in {"SWING", "GRAND"}
        else "Stop و اندازه پوزیشن صرفاً پیشنهاد سیستم‌اند و باید با مدیریت شخصی معامله‌گر تطبیق داده شوند."
    )
    # Viva 09-19 ladder ruling: the confirmed message must show the SAME
    # levels/weights the monitor executes — read them from the ladder itself.
    _lad = (candidate.metadata or {}).get("target_ladder") or {}
    _tgts = [float(t) for t in (_lad.get("targets") or [])] or [candidate.tp1, candidate.tp2]
    _wts = [float(w) for w in (_lad.get("weights") or [])] or [SETTINGS.partial_tp1_percent, SETTINGS.partial_tp2_percent]
    # round 14: distances are shown as PERCENT of price — never as R multiples
    _pcts = [abs(float(t) - float(candidate.planned_entry))
             / max(abs(float(candidate.planned_entry)), 1e-12) * 100.0 for t in _tgts]
    _tp_rows = "\n".join(
        f"{'└' if i == len(_tgts) - 1 else '├'} TP{i + 1}: <b>{_price(t)}</b> • {r:.1f}٪ • "
        + (f"بستن {w:.0f}%" if w > 0 else "بدون خروج — سطح اطلاع‌رسانی")
        for i, (t, r, w) in enumerate(zip(_tgts, _pcts, _wts)))
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
        f"{_market_intelligence_block(candidate)}\n\n"
        f"📍 <b>سطوح معامله</b>\n"
        f"├ Entry: <b>{_price(candidate.planned_entry)}</b>\n"
        f"├ {_e(invalidation_label)}: <b>{_price(candidate.sl)}</b>\n"
        f"{_tp_rows}\n\n"
        f"💼 <b>مدیریت سرمایه بهینه</b>\n"
        f"├ اندازه حساب: <b>${mm.get('account', 0):,.0f}</b>\n"
        f"├ ریسک محاسباتی تا ابطال: <b>{mm.get('risk_pct', 0):.2f}% = ${mm.get('risk_amount', 0):.2f}</b>\n"
        f"├ اهرم کیفیت‌محور و ایمن: <b>{mm.get('leverage', 1)}x</b> (سقف کیفیت {mm.get('quality_leverage_cap', 1)}x)\n"
        f"├ Margin پیشنهادی: <b>${mm.get('margin', 0):.2f} ({mm.get('margin_pct', 0):.1f}%)</b>\n"
        f"├ سقف Margin این کیفیت: <b>{mm.get('margin_limit_pct', 0):.1f}% حساب</b>\n"
        f"├ Position Size: <b>${mm.get('position_size', 0):,.0f}</b>\n"
        f"├ سود تقریبی TP1: <b>${mm.get('tp1_profit', 0):.2f}</b>\n"
        f"├ سود تقریبی هدف نهایی (باقی‌مانده): <b>${mm.get('tp2_profit', 0):.2f}</b>\n"
        f"└ هزینه تخمینی Fee/Slippage: <b>${mm.get('estimated_roundtrip_cost', 0):.2f}</b>"
        f"{mm_warning}\n\n"
        f"{_ai_note(candidate)}\n\n"
        f"📌 پیشنهاد سیستم: بعد از TP1 استاپ به ورودِ خالص (ورود + کارمزد/لغزش) منتقل می‌شود و بین هر دو هدف، کف حفاظتیِ فرمول‌محور فقط در جهت سود حرکت می‌کند (بدون برگشت).\n"
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


_BIAS_FA = {"BULLISH": "صعودی 🟢", "BEARISH": "نزولی 🔴", "NEUTRAL": "خنثی ⚪"}


def _compact_alert_caption(candidate: SignalCandidate, extra_lines: Optional[list] = None,
                           score: Optional[int] = None) -> str:
    """Viva 2026-09-11: the ONE-LINE-FAMILY compact alert (نمونه AAVE) — the
    full paragraphs live ONLY in the permanent detailed alert of the alerts
    channel; PRO and the alerts short post use this layout."""
    code = _public_code(candidate)
    head = str(candidate.strategy_fa)
    setup_line = head.split("|", 1)[-1].strip() if "|" in head else head
    # «🎯 ستاپ: VIVA-TLBREAK | VIVA-TLBREAK» — a brand echoed twice is noise.
    if setup_line.upper().replace(" ", "") in {f"VIVA-{str(candidate.setup_code).upper()}",
                                               str(candidate.setup_code).upper()}:
        setup_line = ""
    dir_fa = "🧭 سناریوی احتمالی خرید" if candidate.direction == "LONG" else "🧭 سناریوی احتمالی فروش"
    badge, _ = _setup_badge(candidate)
    tf_tag = str(candidate.trigger_timeframe or "").upper()
    if not tf_tag:  # never print an empty TF slot (Viva 09-17)
        from analysis.setups_v7 import timeframe_profile as _tfp9
        tf_tag = str(_tfp9(candidate.style)[2]).upper()
    rows = [
        f"🏷 <b>{_e(badge)}</b>",
        VIVA_SEP,
        "📚 <b>تحلیل آموزشی | ستاپ در حال بررسی</b>",
        "⛔ <b>این پیام تأیید ورود نیست</b>",
        "👀 فقط برای رصد بازار و اهداف آموزشی",
        VIVA_SEP,
        f"🪙 <b>{_e(candidate.symbol)}</b>  •  {_e(candidate.style)}  •  {_e(tf_tag)}",
        f"🌐 {_e(_market_label(candidate))}",
        dir_fa,
        (f"🎯 ستاپ: <b>VIVA-{_e(candidate.setup_code)}</b> | {_e(setup_line)}"
         if setup_line else f"🎯 ستاپ: <b>VIVA-{_e(candidate.setup_code)}</b>"),
        f"⭐ امتیاز فعلی: {int(candidate.score if score is None else score)}/10",
        f"🆔 <code>{_e(code)}</code>",
        VIVA_SEP,
        "🔎 <b>ناحیه‌ای که زیر نظر داریم</b>",
        f"از {_price(candidate.entry_zone_bottom)} تا {_price(candidate.entry_zone_top)}",
        f"سطح ابطال سناریو: {_price(candidate.sl)}"
        + (" • 🛑 استاپ ساختاری دورتر بود؛ طبق قانون ۰۹-۲۱ روی سقفِ همین تایم‌فریم تنظیم شد."
           if (candidate.metadata or {}).get("stop_clamped") else ""),
        "",
    ]
    # The long rule paragraph lives in the DETAILED alert; the compact keeps
    # its essence so the caption never overruns Telegram's 1024 media cap and
    # gets cut «نصفه».
    _rule = _confirm_rule_fa(candidate).replace(" (پولبک شرط نیست)", "")
    _rule = _rule.split("؛ برای سناریوهای داخلی", 1)[0]
    if len(_rule) > 210:
        cut = _rule.rfind(" ", 0, 210)
        _rule = (_rule[:cut] if cut > 120 else _rule[:210]) + "…"
    rows.append(_rule)
    rows.append("")
    rows += [
        "🧭 <b>کانتکست تایم بالاتر</b>",
        f"• بایاس ساختاری: {_BIAS_FA.get(str(candidate.bias).upper(), _e(str(candidate.bias)))}",
    ]
    rows += _timing_lines(candidate)
    for line in (extra_lines or []):
        rows.append(line)
    # FORMAT-3 + 09-16 NIGHT RULING (verbatim): «پیام مختصر رو بصورت کپشن
    # نذار؛ اول عکس چارت، بلافاصله پیام مختصر» — the compact travels as a
    # PLAIN TEXT message right behind its chart bubble, so the 4096 text cap
    # holds the FOUR FULL aid analyses with item separators, exactly like the
    # detailed alert. No digest, no caption, no split, no continuation.
    _aids = _tech_aids_lines(candidate)
    if _aids:
        rows += [VIVA_SEP_ITEM, "🧩 <b>تأییدهای کمکی</b>"]
        for _i, _a in enumerate(_aids):
            if _i:
                rows.append(VIVA_SEP_ITEM)
            rows.append(_a)
    rows += [
        VIVA_SEP,
        "⛔ ورود، اهرم و حجم پوزیشن هنوز پیشنهاد نمی‌شود",
        "✅ در صورت تکمیل شرایط، ابتدا Approaching و سپس Confirmed ارسال می‌شود.",
        VIVA_SEP,
        "📢 VivaMon Labs Pro",
    ]
    out = "\n".join(rows)
    # one-message law under the 4096 TEXT cap: degrade only in the impossible
    # case (aids one-by-one from the bottom; core never drops).
    if len(out) > 4090:
        _aid_marks = ("🕐 سشن", "📊", "", "")

        def _is_aid(r: str) -> bool:
            return r.startswith("• ") and any(m in r for m in _aid_marks)

        while len(out) > 4090:
            _idxs = [i for i, r in enumerate(rows) if _is_aid(r)]
            if not _idxs:
                break
            _drop = _idxs[-1]
            rows.pop(_drop)
            if _drop > 0 and rows[_drop - 1] == VIVA_SEP_ITEM:
                rows.pop(_drop - 1)
            out = "\n".join(rows)
    return out


def _setup_chain_get(candidate: SignalCandidate) -> dict:
    try:
        from database.bot_kv import get_json
        return dict(get_json(f"setup_chain|{_public_code(candidate)}", {}) or {})
    except Exception:
        return {}


def _setup_chain_set(candidate: SignalCandidate, value: dict) -> None:
    _setup_chain_set_by_code(_public_code(candidate), value)


def _setup_chain_set_by_code(code: str, value: dict) -> None:
    # Viva 2026-09-16: MERGE, never overwrite — concurrent lifecycle writers
    # used to clobber the journal channel's sig_* reply keys with stale dicts,
    # which is why the VIVA-MON-SIGNALS ladder arrived un-linked.
    try:
        from database.bot_kv import get_json, set_json
        cur = dict(get_json(f"setup_chain|{code}", {}) or {})
        cur.update(dict(value))
        set_json(f"setup_chain|{code}", cur)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"setup chain persist warning {code}: {exc}")


def _chain_by_code_get(code: str) -> dict:
    try:
        from database.bot_kv import get_json
        return dict(get_json(f"setup_chain|{code}", {}) or {})
    except Exception:
        return {}


def _chart_label(symbol: str = "", code: str = "", title_fa: str = "") -> str:
    """ONE-line Persian label for a chart photo bubble (Viva 2026-09-16: the
    readable text must NEVER ride as a photo caption again)."""
    parts = [p for p in (f"📊 چارت {_e(symbol)}" if symbol else "📊 چارت",
                         f"<code>{_e(code)}</code>" if code else "",
                         title_fa)]
    return " • ".join(p for p in parts if p)


def _send_photo_file_id(file_id: str, chat_id: str, label: str = "",
                        reply_to_message_id: Optional[int] = None,
                        reply_markup: Optional[dict] = None) -> Optional[int]:
    """Mirror an already-rendered Telegram chart by file_id.
    No PNG upload, no rendering, no chart bytes copied through Railway."""
    if not TOKEN or not chat_id or not file_id:
        return None
    payload = {"chat_id": chat_id, "photo": str(file_id), "caption": label or "📊 چارت",
               "parse_mode": "HTML"}
    if reply_to_message_id:
        payload["reply_to_message_id"] = int(reply_to_message_id)
        payload["allow_sending_without_reply"] = True
    if reply_markup:
        import json
        payload["reply_markup"] = json.dumps(reply_markup)
    result = _tg_post("https://api.telegram.org/bot" + TOKEN + "/sendPhoto",
                      data=payload, timeout=20)
    if not result:
        return None
    mid = int(result.get("result", {}).get("message_id") or 0) or None
    _audit_send("photo-file-id", chat_id, mid)
    return mid


def _post_chart_then_text(chart, text: str, target, reply_to=None,
                          reply_markup=None, label: str = "", file_id: str = "") -> tuple:
    """Viva 2026-09-16 (verbatim ruling): «پیام مختصر رو بصورت کپشن نذار؛ اول
    عکس چارت، بلافاصله پیام مختصر، تا پیام چندپاره و نصفه نشه» — the chart goes
    up as its own photo bubble carrying ONLY a one-line Persian label, then
    the whole text follows IMMEDIATELY as a plain message (4096 cap ⇒ never
    split, never a detached caption tail, any length fits ONE message).
    The text message carries the chain (reply/markup) and its id is what the
    chain stores. Returns (photo_mid, text_mid)."""
    photo_mid = 0
    if file_id:
        photo_mid = int(_send_photo_file_id(file_id, target, label=label,
                                            reply_to_message_id=reply_to,
                                            reply_markup=reply_markup) or 0)
    elif chart:
        photo_mid = int(send_photo(chart, label or "📊 چارت", target,
                                   caption_limit=1024) or 0)
    text_mid = int(send_message(text, target,
                                reply_to_message_id=int(reply_to or 0) or None,
                                reply_markup=reply_markup) or 0)
    return photo_mid, text_mid


def _sig_mirror(code: str, kind: str, text: str, chart=None, reply_kind: str = "",
                link: str = "", link_text: str = "", file_id: str = "") -> int:
    """PROP-1 (Viva 09-16, approved — channel VIVA-MON-SIGNALS he created and
    admined the bot on): the clean journal mirror. ONLY final alert,
    Confirmed, TP1–5, stop/trail and the final result land there, each quoting
    its predecessor INSIDE that channel (sig_* chain keys), while the existing
    channels keep every message exactly as before. The agreed link-chain walk
    continues cross-channel via a URL button back into the main channel
    («پیام تایید شدن به پیام مختصر کانال اصلی، از اونجا به هشدار ابتدایی و
    بعد پیام مفصل»)."""
    if not CHAT_ID_VIVA_SIGNALS or not code:
        return 0
    try:
        chain = _chain_by_code_get(code)
        reply = int(chain.get(f"sig_{reply_kind}") or 0) or None
        markup = ({"inline_keyboard": [[{"text": link_text, "url": link}]]}
                  if link else None)
        _ttl = {"approach": "هشدار آماده‌سازی", "confirmed": "تأیید سیگنال",
                "stop": "استاپ / تریل", "result": "نتیجه نهایی"}.get(kind, "")
        if kind.startswith("tp"):
            _ttl = f"هدف {kind[2:]} زده شد"
        _ph, mid = _post_chart_then_text(
            chart, text, CHAT_ID_VIVA_SIGNALS, reply_to=reply,
            reply_markup=markup, label=_chart_label(code=code, title_fa=_ttl),
            file_id=file_id)
        if not mid and reply:
            # Viva 09-17: a journal entry must NEVER die because its parent
            # (a replaced/deleted update) is gone — retry as a plain post.
            print(f"viva-signals mirror {code}/{kind}: reply target unusable, retry plain")
            _ph, mid = _post_chart_then_text(
                chart, text, CHAT_ID_VIVA_SIGNALS, reply_to=None,
                reply_markup=markup, label=_chart_label(code=code, title_fa=_ttl),
                file_id=file_id)
        if not mid:
            print(f"viva-signals mirror FAILED {code}/{kind}: no message id")
        if mid:
            chain[f"sig_{kind}"] = int(mid)
            _setup_chain_set_by_code(code, chain)
        return int(mid or 0)
    except Exception as exc:
        print(f"viva-signals mirror warning {code}/{kind}: {exc}")
        return 0


def _fa_start(text: str) -> str:
    """Viva 09-17: «هیچ اصطلاح و کلمه انگلیسی اول جمله‌ها در هیچ خطی نیاد» —
    but technical terms are never deleted; they just may not be FIRST. Emoji
    prefixes stay put; an ASCII-leading word gets a Persian opener."""
    m = re.match(r"^([^\w]*)([A-Za-z])", text or "")
    if m:
        head = m.group(1)
        return f"{head}اندیکاتور {text[len(head):]}"
    return text


def _tech_aids_lines(candidate) -> list:
    """Viva 2026-09-13: session + EMA ladder + Fibo level + divergence in
    EVERY lifecycle message — detailed, compact, updates, final."""
    md = candidate.metadata or {}
    rows = []
    sess = str(md.get("session") or "").strip()
    if sess:
        rows.append(f"• 🕐 سشن آخرین کندل: {_e(_SESS_FA.get(sess.upper(), sess))}")
    for line in (md.get("tech_aids") or []):
        rows.append(f"• {_e(_fa_start(str(line)))}")
    return rows


def _pro_slot_post(candidate, caption: str, chart=None, markup=None,
                   kind: str = "update", reply_to: Optional[int] = None) -> int:
    """The ONE main-channel writer for every setup (Viva 2026-09-14 link-chain
    law, verbatim): «پیام مختصر همون کد» is the PERMANENT compact anchor —
    updates never delete or edit it; each numbered update REPLACES only the
    previous update and QUOTES the compact (reply_to); thread events (final
    alert / Confirmed) are new messages replying to their predecessor.
    The permanent detailed alert in the alerts channel is untouched here and
    the chain's unique code links the two. Every PRO write in the whole bot
    must route through this function — side-writers are what produced
    «۶ پیام در ۲۶ ثانیه» on ATOM and are illegal now."""
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    # Viva 2026-09-16 (verbatim): «پیام مختصر رو بصورت کپشن نذار؛ اول عکس
    # چارت، بلافاصله پیام مختصر» — chart bubble first with a one-line label,
    # the readable text right behind as a plain message: never split, never
    # a detached continuation, any length fits ONE message.
    _kind_title = {"compact": "پیام مختصر ستاپ",
                   "update": "به‌روزرسانی رصد"}.get(kind, "")
    _photo_mid, mid = _post_chart_then_text(
        chart, caption, target, reply_to=int(reply_to or 0) or None,
        reply_markup=markup,
        label=_chart_label(symbol=getattr(candidate, "symbol", ""),
                           code=_public_code(candidate), title_fa=_kind_title))
    if not mid:
        return 0
    try:
        chain = _setup_chain_get(candidate)
        if kind == "compact":
            # permanent anchor: never a delete, never a second live compact
            old_anchor = int(chain.get("anchor_pro") or 0)
            if old_anchor and old_anchor != int(mid):
                # a re-firing compact (chain recreated) REPLACES its own kind
                try:
                    delete_message(str(target), old_anchor)
                    _oph = int(chain.get("anchor_photo") or 0)
                    if _oph:
                        delete_message(str(target), _oph)
                except Exception:
                    pass
            chain["anchor_pro"] = int(mid)
            chain["anchor_photo"] = int(_photo_mid or 0)
            chain["edu_short"] = int(mid)
        elif kind == "update":
            old_slot = int(chain.get("slot") or 0)
            if old_slot and old_slot != int(mid) and old_slot != int(chain.get("anchor_pro") or 0):
                try:
                    delete_message(str(target), old_slot)
                    _oph = int(chain.get("slot_photo") or 0)
                    if _oph:
                        delete_message(str(target), _oph)
                except Exception:
                    pass
            chain["slot"] = int(mid)
            chain["slot_photo"] = int(_photo_mid or 0)
        else:
            chain[str(kind)] = int(mid)
        chain["slot_kind"] = str(kind)
        chain["pro"] = int(mid)
        _setup_chain_set(candidate, chain)
    except Exception as exc:
        print(f"pro slot chain warning {getattr(candidate, 'signal_id', '?')}: {exc}")
    # ── Round-19: the app mirrors EXACTLY what the channel received — the
    # chart via its Telegram file_id, the message text verbatim (HTML+emoji).
    # No re-render, no second copy of the message logic.
    try:
        from database.bot_kv import set_json
        _sid = str(getattr(candidate, "signal_id", "") or "")
        if _sid:
            _fid = _LAST_PHOTO_FILE.get(int(_photo_mid or 0)) if _photo_mid else ""
            if _fid:
                set_json(f"app_chart|{_sid}", {"fid": _fid, "mid": int(_photo_mid)})
            if str(kind) != "update":
                set_json(f"app_msg|{_sid}|{kind}", {"html": str(caption)[:6000]})
            else:
                set_json(f"app_msg|{_sid}|update", {"html": str(caption)[:6000]})
    except Exception as exc:
        print(f"pro slot app-mirror warning {getattr(candidate, 'signal_id', '?')}: {exc}")
    return int(mid)


def send_educational_setup(candidate: SignalCandidate, chart_df: Optional[pd.DataFrame]) -> bool:
    target = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
    # ── round 12: the clock of the candle this alert was born from, plus the
    # past-market guard. An alert older than TWO trigger candles is not an entry
    # alert any more (his words: «عملا من دارم گذشته مارکت رو می‌بینم و اصلا به
    # هیچ دردی نمی‌خوره») — it goes out as an analysis note, never as a position.
    _stamp_source_candle(candidate, chart_df)
    _as_entry, _late_min = _stale_alert_verdict(candidate)
    if not _as_entry:
        candidate.metadata["stale_detection"] = int(_late_min)
        print(f"⏳ STALE_DETECTION {candidate.signal_id}: source candle closed "
              f"{_late_min} minutes ago (> 2×{candidate.trigger_timeframe}) — analysis note only")
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
        polarity_fa = str(md.get("pin_polarity_reason_fa") or "").strip()
        polarity_line = f"\n🧭 {_e(polarity_fa)}" if polarity_fa else ""
        caption = (
            f"🚨 {_e(candidate.symbol)} • {_e(candidate.trigger_timeframe)} • پین‌بار "
            f"{'🟢 صعودی' if candidate.direction == 'LONG' else '🔴 نزولی'}\n"
            f"📍 داخل {_e(zone_fa)}" + (f" (کانتکست {_e(ctx_fa)})" if ctx_fa else "") + polarity_line + "\n"
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
    if not mid:  # Viva 09-17: the DETAILED alert must never silent-die
        print(f"DETAILED alert post failed {candidate.signal_id}; retrying once")
        mid = send_message(build_educational_message(candidate), target)
        if not mid:
            print(f"DETAILED alert post FAILED twice {candidate.signal_id}")
    _store_alert_message_id(candidate, "education_message_id", mid)
    # Viva 2026-09-11 (final doctrine, verbatim): the main channel receives
    # ONLY the final alert (and later the Confirmed which replaces it) — the
    # education phase must never put a text-only watch post there («عالمه
    # پیام هشدار بدون چارت اومده به کانال اصلی»). The alerts channel keeps the
    # permanent detailed alert plus ONE compact reply carrying the same live
    # chart — every message outside the win-rate channel ships with a chart.
    try:
        # Viva 2026-09-13 (his own correction of the 09-12 law): the COMPACT
        # initial alert belongs to the MAIN channel and is the live slot that
        # every future update replaces; it carries the live chart and a button
        # linking to this permanent detailed alert (located through the chain's
        # unique code, so a link can never cross into another chain).
        markup = None
        if mid:
            link = _telegram_message_link(target, int(mid))
            if link:
                markup = {"inline_keyboard": [[{"text": "📚 توضیحات کامل هشدار",
                                                "url": link}]]}
        try:  # «بین پیام‌های کانال اصلی هم جداکننده نمیاد که قاطی بشن»
            _c0 = _setup_chain_get(candidate)
            if not _c0.get("pro_sep"):
                if send_signal_separator(CHAT_ID_EXECUTION or CHAT_ID_ADMIN):
                    _c0["pro_sep"] = 1
                    _setup_chain_set(candidate, _c0)
        except Exception:
            pass
        slot_mid = _pro_slot_post(candidate, _compact_alert_caption(candidate),
                                  chart=chart, markup=markup, kind="compact")
        if slot_mid:
            candidate.metadata["alerts_short_message_id"] = int(slot_mid)
        chain = _setup_chain_get(candidate)
        if mid:
            chain["edu"] = int(mid)
        if slot_mid:
            chain["edu_short"] = int(slot_mid)
        _setup_chain_set(candidate, chain)
    except Exception as exc:  # pragma: no cover - chain must never kill education
        print(f"setup chain education warning {candidate.signal_id}: {exc}")
    return bool(mid)


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa_num(value) -> str:
    return str(value).translate(_FA_DIGITS)


def _setup_update_caption(candidate: SignalCandidate, note_fa: str = "",
                          state_fa: str = "🔄 <b>به‌روزرسانی رصد</b>",
                          upd_n: int = 0) -> str:
    """One-line-family live status of a chain. Viva 2026-09-12 (latest-update
    law): every state change is a NEW numbered post — header «🔄 آخرین آپدیت • آپدیت N»
    — so the newest message in the channel is always the newest update; the
    superseded one is deleted. In-place editing of old messages is dead."""
    code = _public_code(candidate)
    badge, _ = _setup_badge(candidate)
    dir_fa = "🧭 سناریوی خرید" if candidate.direction == "LONG" else "🧭 سناریوی فروش"
    advisory = _fa_advisory(str((candidate.metadata or {}).get("gemini_advisory") or "").strip()
                            or str(getattr(candidate, "ai_reason", "") or "").strip()) \
        or _ai_rich_note(candidate)
    confirm_tf = str((candidate.metadata or {}).get("confirm_tf") or "").upper()
    rows = []
    if upd_n:
        rows.append(f"🔁 <b>آخرین آپدیت • آپدیت {_fa_num(upd_n)}</b>")
    # Viva 09-23 («چون از هشدار اولیه ۶ ساعت گذشته اون چارت رو برای ۶ ساعت قبل
    # معرفی میکنه که این اشتباهه»): every update says EXPLICITLY that the
    # attached chart is LIVE up to the current candle — the «کندل مبدا» clock
    # below is the SIGNAL's origin, never the chart's age.
    try:
        _now_clock = datetime.now(ZoneInfo("UTC")).strftime("%H:%M")
    except Exception:
        _now_clock = ""
    rows += [
        f"🏷 <b>{_e(badge)}</b>",
        VIVA_SEP,
        state_fa,
        (f"📊 چارت پیوست: <b>لایو</b> — تا کندلِ جاری {_e(_now_clock)} UTC"
         if _now_clock else "📊 چارت پیوست: <b>لایو</b>"),
        "⛔ تأیید ورود نیست",
        VIVA_SEP,
        f"🪙 <b>{_e(candidate.symbol)}</b>  •  {_e(candidate.style)}  •  {_e(str(candidate.trigger_timeframe or '').upper())}",
        f"📍 ناحیه: {_price(candidate.entry_zone_bottom)} تا {_price(candidate.entry_zone_top)} • ابطال: {_price(candidate.sl)}",
        f"⭐ امتیاز فعلی: {int(candidate.score)}/10 • {dir_fa}",
    ]
    if note_fa:
        rows += [VIVA_SEP, _e(note_fa)]
    rows += [
        VIVA_SEP,
        "🧩 <b>تأییدهای کمکی</b>",
        f"• 🤖 <b>نظر AI:</b> {_e(advisory)}",
        _confirm_rule_fa(candidate).replace("⚖️ ", "• ⚖️ "),
    ]
    rows += _tech_aids_lines(candidate)
    rows += [
        VIVA_SEP,
        f"🆔 <code>{_e(code)}</code>",
    ]
    rows += _timing_lines(candidate)
    return "\n".join(rows)


def send_setup_update(candidate: SignalCandidate, chart_df=None,
                      note_fa: str = "", state_fa: str = "",
                      critical: bool = False) -> bool:
    """The single UPDATE message of a chain (alerts channel, reply-linked to the
    permanent detailed alert). Every newer update EDITS the same message; a
    chain never accumulates more than one — Viva's «آپدیت جدید با آپدیت قبلی
    جایگزین میشه» rule. Carries the live chart like every other message."""
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    edu_chat = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
    chain = _setup_chain_get(candidate)
    detail_mid = int(chain.get("edu") or candidate.metadata.get("education_message_id") or 0)
    chart = None
    # Viva 09-20 time-axis law: updates carry a LIVE chart. While price is
    # still inside the long/short tool (and in every pre-confirmation update)
    # the tape is the trigger TF; once candles have left the tool, the same
    # anchored tool is shown on one higher TF. An update must NEVER fall back
    # to an empty chart just because the higher frame is unavailable.
    # confirmed charts are the first that carry the drawn tool; before a fill
    # the tool is anchored at the confirmation candle (tool_entry_ts fallback)
    _chart_is_live = bool(getattr(candidate, "confirmed_at", ""))
    if chart_df is not None and _chart_is_live:
        try:
            _live_frame = _lifecycle_chart_frame(candidate, [])
            if _live_frame is not None:
                chart_df = _live_frame
        except Exception:
            pass
    if chart_df is not None:
        try:
            chart = generate_chart(chart_df, candidate, confirmed=False)
        except Exception:
            chart = None
    if chart is None and chart_df is None:
        # «همه پیامها با چارت» — the update fetches its own live frame when the
        # caller had none (verdict/expiry paths), never posting chartless.
        try:
            from data.fetcher import get_klines
            _tf = str((candidate.metadata or {}).get("confirm_tf")
                      or candidate.trigger_timeframe)
            frame = get_klines(candidate.symbol, _tf, 180, closed_only=False, use_cache=True)
            if frame is not None and len(frame) >= 30:
                chart = generate_chart(frame, candidate, confirmed=False)
        except Exception:
            chart = None
    import time as _time
    import hashlib as _hash
    # Viva 2026-09-14 «هر روز یه روز بدتر — سی تا پیام مختصر همون دقیقه!»:
    # even a REAL change waits update_min_gap_seconds on this chain's slot.
    # Verdicts / cancellations / confirmations / ⚡live-break (❌⚪⛔✅⚡) are
    # single events and never wait.
    # N2/R-4 (audit 09-15): callers may force the bypass with critical=True —
    # ⚡live-break and MATERIAL absorb updates are «شکست واقعی ⇒ آپدیت فوری»
    # events; identical repeats are still swallowed by the content-hash below.
    _critical = critical or str(state_fa or "")[:2].lstrip("<b ").strip()[:1] in {"❌", "⚪", "⛔", "✅", "⚡"}
    if not _critical and _time.time() - float(chain.get("upd_ts") or 0) < max(
            120, int(getattr(SETTINGS, "update_min_gap_seconds", 300) or 300)):
        return False
    # Viva 2026-09-12: «توی ثانیه چه تغییری شده که آپدیت میده؟!» — an update
    # must carry NEWS; identical content repeats are swallowed before Telegram
    # ever sees them. Real changes (absorb note, verdict, closure) differ in
    # the signature and always pass.
    sig = _hash.md5("|".join([
        str(state_fa), str(note_fa), str(candidate.score),
        f"{candidate.entry_zone_bottom:.10g}", f"{candidate.entry_zone_top:.10g}",
        f"{candidate.sl:.10g}",
    ]).encode()).hexdigest()
    if chain.get("upd_sig") == sig:
        return False
    upd_n = int(chain.get("upd_n") or 0) + 1
    # the ordered one/two-line explanation rides along whenever this update's
    # chart was stepped up to a higher TF (09-20 time-axis law)
    _view_note = str((candidate.metadata or {}).get("chart_view_note") or "")
    if _view_note:
        note_fa = f"{note_fa}\n\n{_view_note}" if str(note_fa or "").strip() else _view_note
    caption = _setup_update_caption(
        candidate, note_fa, state_fa or "🔄 <b>به‌روزرسانی رصد</b>", upd_n)
    link = _telegram_message_link(edu_chat, detail_mid) if detail_mid and edu_chat else ""
    markup = ({"inline_keyboard": [[{"text": "📚 توضیحات کامل هشدار", "url": link}]]}
              if link else None)
    # Viva 2026-09-12 (latest-update law, EVERY setup): the update POSTS as the
    # newest message of the channel — reply-linked to the permanent detailed
    # alert wherever it lives (even 300 posts back) — numbered «آپدیت N», and the
    # message it supersedes is DELETED once the new one lands.
    # Viva 2026-09-13: numbered updates land in the MAIN channel as the
    # chain's live slot — post the new one first, delete the superseded
    # compact/update after; the 📚 button points at the permanent detailed
    # alert in the alerts channel. A fresh live chart rides along.
    mid = _pro_slot_post(candidate, caption, chart=chart, markup=markup, kind="update",
                         reply_to=int(chain.get("anchor_pro") or chain.get("edu_short") or 0) or None)
    if mid:
        chain = _setup_chain_get(candidate)
        chain["upd"] = int(mid)
        chain["upd_n"] = upd_n
        chain["upd_sig"] = sig
        chain["upd_ts"] = _time.time()
        _setup_chain_set(candidate, chain)
    return bool(mid)
def _approaching_ai_hint(candidate: SignalCandidate) -> str:
    md = candidate.metadata or {}
    if candidate.setup_code in ("TLBREAK", "TECHCLASSIC"):
        return "فقط بعد از Close معتبر پشت خط و حفظ بیس وارد شو؛ تعقیب قیمت ممنوع."
    if candidate.setup_code == "PINVAL":
        return "پین‌بار فقط location است؛ تأیید با شکست micro-structure تایم پایین معتبر می‌شود."
    if md.get("nearest_zones"):
        return "زون نزدیک را ببین؛ تأیید تایم پایین را به‌خاطر هیجان حرکت جا ننداز."
    return "تا کلوز تأییدی و حفظ ابطال، این فقط سناریوی تحت‌نظر است."


def _ai_watch_hint(candidate: SignalCandidate) -> str:
    """One concise, deterministic assistant note; never an entry command."""
    md = candidate.metadata or {}
    if candidate.setup_code in ("TLBREAK", "TECHCLASSIC"):
        return "فقط بعد از Close معتبر پشت خط و حفظ base؛ chase ممنوع."
    if candidate.setup_code == "PINVAL":
        return "پین‌بار فقط rejection است؛ ورود بعد از MSS/BOS تایم پایین."
    if md.get("structure_level"):
        return "تأیید فقط با شکست ساختار خرد پس از retest ناحیه معتبر است."
    return "سناریو زیر نظر است؛ تا کلوز تأییدی هیچ ورود اجرایی نداریم."


def _fa_advisory(text: str) -> str:
    """Viva 2026-09-14 «نظر AI چرا انگلیسی است»: the AI row is Persian prose.
    A raw Latin token (RR_DEGRADED and friends) or a <24-char stub is not an
    opinion — return empty so callers fall back to the composed note."""
    t = str(text or "").strip()
    if not t:
        return ""
    latin = sum(1 for ch in t if "a" <= ch.lower() <= "z")
    if len(t) < 24 or latin / max(len(t), 1) > 0.60:
        return ""
    return t


def _ai_rich_note(candidate: SignalCandidate) -> str:
    """2-4 sentence Persian read assembled from live state — the engine's own
    «analysis», never a boilerplate token. Deterministic per candle."""
    md = candidate.metadata or {}
    bits: List[str] = []
    try:
        from analysis.aids_bank import session_note
        sess = session_note(str(md.get("session") or ""))
        if sess:
            bits.append(sess)
    except Exception:
        pass
    bias = str(candidate.bias or "").upper()
    if bias in {"BULLISH", "BEARISH"}:
        agree = (bias == "BULLISH") == (str(candidate.direction).upper() == "LONG")
        bits.append(f"بایاس ساختاریِ تایم بالا {('صعودی 🟢' if bias == 'BULLISH' else 'نزولی 🔴')} است و سناریوی فعلی "
                    + ("در هم‌جهتِ آن نوشته شده — قانون جریان؛ فقط صبر برای تأیید."
                       if agree else "خلافِ آن است؛ بدون نشانهٔ قویِ بازگشت (MSS+کندلِ بازیگر) ورود ندارد."))
    else:
        bits.append("بایاس تایم بالا خنثی است؛ یعنی حقِ تعجیل به هیچ سمتی نداریم و ناحیه حرف اول را می‌زند.")
    # Viva 09-20 round 10: no R:R advice anywhere in the AI note — the path
    # (5-part, TF-banded) is the only target doctrine now.
    bits.append(_ai_watch_hint(candidate))
    return " ".join(bits)


def _approaching_caption(candidate: SignalCandidate, current_price: float, distance_atr: float) -> str:
    why = candidate.strategy_fa
    badge, _ = _setup_badge(candidate)
    advisory = _fa_advisory(str((candidate.metadata or {}).get("gemini_advisory") or "").strip()
                           or str(getattr(candidate, "ai_reason", "") or "").strip())
    # Viva 2026-09-14 «نظر AI چرا اینقدر کوتاه و انگلیسی هست؟» — the AI row is
    # a full Persian read on every message; a Latin token never stands alone.
    ai_line = f"🤖 <b>نظر AI:</b> {_e(advisory or _ai_rich_note(candidate))}\n"
    # Viva 2026-09-11 (UNIUSDT نمونه): 🎯 = VIVA-CODE | setup , 🚨 = رویدادها + امتیاز
    name, _, event = str(why).partition("|")
    head = f"VIVA-{_e(candidate.setup_code)}"
    if event.strip():
        target_line = (f"🎯 <b>{head}</b> | {_e(name.strip())}\n"
                       f"🚨{_e(event.strip())} | ⭐ {candidate.score}/10\n")
    else:
        target_line = f"🎯 <b>{head}</b> | {_e(why)} • ⭐ {candidate.score}/10\n"
    return (
        f"🏷 <b>{_e(badge)}</b>\n{VIVA_SEP}\n"
        f"⚡<b>هشدار نهایی | آماده‌سازی ورود</b>\n\n"
        f"🪙 <b>{_e(candidate.symbol)}</b> • {_e(candidate.style)} • "
        f"{_e(candidate.direction)}\n{VIVA_SEP}\n"
        f"🔎 در آستانه تأیید — {_e(name.strip() or head)}\n"
        f"📍 ناحیه: {_price(candidate.entry_zone_bottom)} تا "
        f"{_price(candidate.entry_zone_top)} • ابطال: {_price(candidate.sl)}\n"
        f"{VIVA_SEP}\n"
        f"🎯 جهت محتمل پس از تأیید معتبر: "
        f"{'نزولی (SHORT)' if candidate.direction == 'SHORT' else 'صعودی (LONG)'}\n"
        f"📏 فاصله زنده تا ناحیه: {distance_atr:.2f} ATR\n"
        f"{VIVA_SEP}\n"
        f"⚖️ {event.strip() or 'شرایط در آستانهٔ کامل‌شدن'}\n"
        f"🌀 {_e(advisory or 'شرط خاص اضافه‌ای ثبت نشده.')}\n"
        f"{VIVA_SEP}\n"
        f"سیگنال واقعی فقط با Close معتبرِ شکست + پولبک اول + BOS تایم پایین "
        f"صادر می‌شود.\n"
        f"{VIVA_SEP}\n"
        f"🆔 <code>{_e(_public_code(candidate))}</code>"
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
    caption = _approaching_caption(candidate, current_price, distance_atr)
    source_mid = (candidate.metadata.get("education_chart_message_id")
                  or candidate.metadata.get("education_message_id")
                  or _setup_chain_get(candidate).get("edu") or 0)
    source_link = _telegram_message_link(CHAT_ID_EDUCATION or CHAT_ID_ADMIN, int(source_mid)) if source_mid else ""
    markup = {"inline_keyboard": [[{"text": "📚 تحلیل و چارت هشدار اولیه", "url": source_link}]]} if source_link else None
    # Viva 2026-09-14 link-chain law (verbatim): «پیام هشدار نهایی و
    # آماده‌سازی که اومد ریپلای بشه به آخرین آپدیت با هر شماره‌ای». The final
    # alert is its OWN message quoting the chain's last update (or the compact
    # when no update ran) — it never overwrites or deletes them. A re-fire of
    # the same stage edits THIS message in place instead of stacking a twin.
    chain = _setup_chain_get(candidate)
    own = int(chain.get("approach") or 0)
    parent = (int(chain.get("slot") or 0)
              or int(chain.get("anchor_pro") or chain.get("edu_short") or 0)) or None
    done = False
    _lbl = _chart_label(symbol=candidate.symbol, code=_public_code(candidate),
                        title_fa="هشدار آماده‌سازی")
    if own:
        done = edit_text_message(own, str(target), caption)
        if done and chart:
            _ph0 = int(chain.get("approach_photo") or 0)
            if _ph0:
                try:
                    edit_chart_message(_ph0, str(target), chart, _lbl)
                except Exception:
                    pass
    if done:
        mid = own
    else:
        _ph, mid = _post_chart_then_text(chart, caption, target, reply_to=parent,
                                         reply_markup=markup, label=_lbl)
        if mid:
            chain["approach"] = int(mid)
            chain["approach_photo"] = int(_ph or 0)
            _setup_chain_set(candidate, chain)
            # PROP-1 mirror: the final alert opens the chain in VIVA-MON-SIGNALS,
            # buttoned back to the main channel's compact anchor (the walk then
            # continues compact → initial alert → detailed, all one-way).
            _anchor = (int(chain.get("anchor_pro") or 0)
                       or int(chain.get("slot") or 0)
                       or int(chain.get("edu_short") or 0))
            _lnk = _telegram_message_link(CHAT_ID_EXECUTION or CHAT_ID_ADMIN, _anchor) if _anchor else ""
            _sig_mirror(_public_code(candidate), "approach", caption, chart,
                        link=_lnk, link_text="🔗 پیام مختصر در کانال اصلی")
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


_TF_CHANNEL_BUCKETS = (
    ("15M_1H", {"15m", "30m", "1h"}, CHAT_ID_SWING_SHORT),
    # round 16: his spot triggers 8h/12h live with the mid family
    ("2H_4H", {"2h", "4h", "8h", "12h"}, CHAT_ID_SWING_MID),
    ("1D", {"1d", "3d", "1w"}, CHAT_ID_SWING_LONG),
)


def tf_channel_bucket(trigger_tf: str) -> str:
    """Which of the three swing families a trigger timeframe belongs to."""
    tf = str(trigger_tf or "").strip().lower()
    for name, tfs, _chat in _TF_CHANNEL_BUCKETS:
        if tf in tfs:
            return name
    return ""


def tf_channel_id(trigger_tf: str) -> str:
    tf = str(trigger_tf or "").strip().lower()
    for _name, tfs, chat in _TF_CHANNEL_BUCKETS:
        if tf in tfs:
            return chat or ""
    return ""


def _tf_channel_text(candidate: SignalCandidate, result_line: str) -> str:
    """Self-contained confirmed message: no reply chain, no update history —
    Viva intends to purge these channels periodically, so every message must
    stand alone and carry its own latest-result link."""
    md = candidate.metadata or {}
    ladder = md.get("target_ladder") or {}
    targets = list(ladder.get("targets") or [candidate.tp1, candidate.tp2])
    weights = list(ladder.get("weights") or [40, 30, 30])
    direction = str(candidate.direction or "").upper()
    arrow = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    stops = md.get("stop_clamped") or md.get("stop_reanchored")
    # ── Viva 09-22: the SPOT signature in the message («لیبل VIVA-SPOT-MON در
    # پیام‌های اسپات فراموش نشه») + the written invalidation numbers
    # («عدد ضرر و ابطال پوزیشن نوشتاری با پیام بیاد»)
    _is_spot = str(md.get("market") or "").upper() == "SPOT"
    _spot_tag = "🪙 <b>VIVA-SPOT-MON</b> · SPOT\n" if _is_spot else ""
    try:
        _kill_pct = abs(float(candidate.planned_entry) - float(candidate.sl)) \
            / max(abs(float(candidate.planned_entry)), 1e-12) * 100.0
    except Exception:
        _kill_pct = 0.0
    _spot_kill = (f"\n🧯 ابطال پوزیشن: <b>{_price(candidate.sl)}</b> "
                  f"(حداکثر ضرر ≈ {_kill_pct:.1f}٪ · سقف اسپات ۱۰٪)"
                  if _is_spot else "")
    head = (f"✅ <b>سیگنال تأییدشده</b>   🆔 <code>{_e(_public_code(candidate))}</code>\n\n"
            f"{_spot_tag}"
            f"🏦 <b>{_e(candidate.symbol)}</b> • {_e(str(candidate.trigger_timeframe or ''))} • "
            f"{_e(str(candidate.style or ''))} • {arrow}\n"
            f"🏷 <b>{_e(_setup_display(candidate.setup_code))}</b>   ⭐ {candidate.score}/10\n\n"
            f"🔰 ورود: <b>{_price(candidate.planned_entry)}</b>\n"
            f"⛔️ استاپ: <b>{_price(candidate.sl)}</b>{_spot_kill}"
            + ("\n<i>استاپ روی سقفِ همین تایم‌فریم تنظیم شده است.</i>" if stops else "")
            + "\n\n🎯 <b>اهداف</b>\n")
    rows = []
    for i, tgt in enumerate(targets, start=1):
        try:
            dist = abs(float(tgt) - float(candidate.planned_entry)) / max(abs(float(candidate.planned_entry)), 1e-12) * 100.0
        except Exception:
            dist = 0.0
        w = weights[i - 1] if i - 1 < len(weights) else 0
        tag = "ℹ️" if i >= 4 else f"{w:.0f}%"
        rows.append(f"• TP{i}: <b>{_price(tgt)}</b> · {dist:.2f}٪ فاصله · {tag}")
    return head + "\n".join(rows) + "\n\n" + result_line + "\n\n📌 <b>VIVAMON-Labs-Pro</b>"


_SPOT_ALERT_TITLE = {
    "TOUCH": "🖐 برخورد اولیه به الگو",
    "NEAR_BREAK": "⏳ نزدیک شدن به شکست",
    "BREAK_DOWN": "💥 هشدار شکست نزولی",
}


def send_spot_alert(item: dict, chart: Optional[bytes] = None) -> bool:
    """Round 16 — the spot ladder's warning post: analysis only, never a trade
    signal («بقیه فقط هشدار ها و تحلیل های مختصر بشه»). The ONE confirmation
    stays the valid close above the shape's upper side, published through the
    normal confirmed path."""
    chat = str(CHAT_ID_SPOT or "")
    if not chat:
        return False
    stage = str(item.get("stage") or "TOUCH")
    side = str(item.get("side") or "HIGH")
    dist = abs(float(item.get("distance_pct") or 0.0))
    sym = str(item.get("symbol") or "")
    tf = str(item.get("tf") or "").upper()
    fa = str(item.get("pattern_fa") or "")
    if stage == "BREAK_DOWN":
        geometry = ("کلوز معتبر زیر ضلع پایین الگو ثبت شد — شرط صعودیِ الگو نقض شده؛ "
                    "فقط هشدار تحلیلی است، سیگنال نیست.")
    elif stage == "NEAR_BREAK":
        side_fa = "بالا" if side == "HIGH" else "پایین"
        geometry = (f"قیمت به ضلع {side_fa} الگو چسبیده (فاصله ≈ {dist:.2f}%) — "
                    "آماده‌باش شکست؛ تأیید فقط با کلوز معتبر آن‌طرفِ ضلع.")
    else:
        side_fa = "بالا" if side == "HIGH" else "پایین"
        geometry = (f"برخورد اولیه به ضلع {side_fa} الگو (فاصله تا ضلع ≈ {dist:.2f}%) — "
                    "هشدار تماس؛ روند قیمت را از همین‌جا رصد کنید.")
    # ── Viva 09-22: honest REASON lines in his own style («دلایل جهت لانگ
    # اعلام بشه … مثلا بگه این الگو نشان‌دهنده حرکت صعودی ممکن است بزودی بریک
    # شود … حجم معاملات …») — pattern meaning + the volume witness. Free data
    # only, never a gate, never an order-book claim.
    try:
        vr = float(item.get("vol_ratio") or 0.0)
    except Exception:
        vr = 0.0
    if stage == "NEAR_BREAK":
        why = ("این الگو نشان‌دهندهٔ احتمال حرکت صعودی است و ممکن است بزودی بشکند؛ "
               "تأیید فقط با کلوز معتبر آن‌طرفِ ضلع صادر می‌شود.")
    elif stage == "BREAK_DOWN":
        why = ("شرط صعودی الگو فعلاً نقض شده است؛ سیگنالی صادر نمی‌شود — "
               "این پیام فقط هشدار تحلیلی برای پرهیز از ورود زودهنگام است.")
    else:
        why = ("این الگو نشان‌دهندهٔ حرکت صعودی بالقوه است؛ برخورد اولیه ثبت شده و "
               "رصدِ فشردگی به سمت ضلع آغاز می‌شود.")
    lines = [
        f"🪙 <b>VIVA-SPOT-MON</b>",
        f"<b>{_e(_SPOT_ALERT_TITLE.get(stage, '🪙 هشدار اسپات'))}</b>",
        f"<code>{_e(sym)}/USDT · {_e(tf)} · {_e(fa)}</code>",
        "",
        _e(geometry),
        "",
        _e(why),
    ]
    if vr >= 1.2:
        lines.append(f"📊 حجم کندل ≈ {vr:.1f}× میانگین ۲۰کندله — همسو با فشار خرید.")
    elif 0 < vr < 0.8:
        lines.append(f"📉 حجم کندل ≈ {vr:.1f}× میانگین ۲۰کندله — شکستِ بدون حجم کم‌اعتبارتر است.")
    rule = str(item.get("rule_fa") or "").strip()
    if rule:
        lines += ["", f"📘 {_e(rule)}"]
    lines += ["",
              "⚠️ هشدار تحلیلی اسپات — تأیید معامله فقط صعودی است (کلوز معتبر بالای الگو).",
              "📌 <b>VIVAMON-Labs-Pro</b>"]
    text = "\n".join(lines)
    try:
        from bot.telegram_bot import send_message, send_photo
        if chart:
            return bool(send_photo(chart, text, chat))
        return bool(send_message(text, chat))
    except Exception as exc:
        print(f"spot alert send error {sym}: {exc}")
        return False


def tf_channel_publish_confirmed(candidate: SignalCandidate, chart=None,
                                 chat_override: str = "", file_id: str = "") -> int:
    """Post the confirmed signal into its timeframe family's channel.

    `chat_override` is how the SPOT lane reaches VIVA-MON-SPOT: the same
    self-contained card, the same single latest-result link, no reply chain.
    """
    code = _public_code(candidate)
    chat = str(chat_override or "") or tf_channel_id(str(candidate.trigger_timeframe or ""))
    if not chat or not code:
        return 0
    result_line = "🔗 آخرین نتیجه: <i>در انتظار نتیجه</i>"
    text = _tf_channel_text(candidate, result_line)
    try:
        _ph, mid = _post_chart_then_text(
            chart, text, chat,
            label=_chart_label(symbol=candidate.symbol, code=code, title_fa="تأیید سیگنال"),
            file_id=file_id)
        if not mid:
            print(f"TF-channel publish failed {code} → {chat}")
            return 0
        chain = _chain_by_code_get(code)
        chain["tfc_chat"] = str(chat)
        chain["tfc_mid"] = int(mid)
        chain["tfc_text"] = text
        chain["tfc_result_label"] = ""
        _setup_chain_set_by_code(code, chain)
        return int(mid)
    except Exception as exc:
        print(f"TF-channel publish error {code}: {exc}")
        return 0


def _tf_channel_edit(chat: str, mid: int, text: str) -> bool:
    if not TOKEN or not chat or not mid:
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
    result = _tg_post(url, data={"chat_id": str(chat), "message_id": int(mid),
                                 "text": text, "parse_mode": "HTML",
                                 "disable_web_page_preview": True}, timeout=15)
    return bool(result)


def tf_channel_set_latest_result(code: str, results_chat: str, results_mid: int,
                                 label: str) -> bool:
    """«هر سیگنال تایید شده فقط به آخرین نتیجه لینک بشه» — rewrite the link line
    of that signal's channel message on every result event. If the message was
    purged (his stated workflow), fall back to a fresh self-contained post."""
    code = str(code or "")
    if not code or not results_mid:
        return False
    chain = _chain_by_code_get(code)
    chat = str(chain.get("tfc_chat") or "")
    mid = int(chain.get("tfc_mid") or 0)
    if not chat or not mid:
        return False
    if str(chain.get("tfc_last_result") or "") == f"{results_mid}":
        return True
    link = _telegram_message_link(results_chat, int(results_mid))
    line = (f'🔗 آخرین نتیجه: <a href="{link}">{_e(label)}</a>' if link
            else f"🔗 آخرین نتیجه: {_e(label)}")
    text = str(chain.get("tfc_text") or "")
    if "🔗 آخرین نتیجه:" in text:
        head = text.split("🔗 آخرین نتیجه:")[0].rstrip()
        new_text = head + "\n" + line + "\n\n📌 <b>VIVAMON-Labs-Pro</b>"
    else:
        new_text = text
    ok = _tf_channel_edit(chat, mid, new_text)
    if ok:
        chain["tfc_text"] = new_text
    else:
        # purged message → post a fresh standalone card with the live link
        try:
            fresh = send_message((text.split("📌 <b>VIVAMON")[0].rstrip() + "\n" + line
                                  + "\n\n📌 <b>VIVAMON-Labs-Pro</b>"), chat)
            if fresh:
                chain["tfc_mid"] = int(fresh)
                chain["tfc_text"] = text
                ok = True
        except Exception as exc:
            print(f"TF-channel refresh fallback error {code}: {exc}")
    if ok:
        chain["tfc_last_result"] = f"{results_mid}"
        try:
            _setup_chain_set_by_code(code, chain)
        except Exception:
            pass
    return bool(ok)


def _telegram_message_link(chat_id: str, message_id: int) -> str:
    """Member-visible direct channel/supergroup permalink."""
    raw = str(chat_id or "")
    if raw.startswith("-100"):
        return f"https://t.me/c/{raw[4:]}/{int(message_id)}"
    return ""


def _confirmed_chart_caption(candidate: SignalCandidate) -> str:
    mm = build_money_management(candidate)
    style_fa = {"DAYTRADE": "DAYTRADE", "SWING": "SWING", "SCALP": "SCALP",
                "GRAND": "SWING"}.get(candidate.style.upper(), candidate.style)
    badge, _ = _setup_badge(candidate)
    advisory = _fa_advisory(str((candidate.metadata or {}).get("gemini_advisory") or "").strip())
    rows = [
        f"🏷 <b>{_e(badge)}</b>",
        f"✅ <b>سیگنال تأییدشده</b> • {_e(candidate.setup_code)}",
        f"🪙 <b>{_e(candidate.symbol)}</b> • {_e(candidate.trigger_timeframe)} • {_e(style_fa)} • {_e(candidate.direction)}",
        f"🕓 زمان تأیید — ایران: {_iran_time(candidate)}",
        f"📨 زمان ارسال — ایران: {_iran_now()}",
        f"📡 تأخیر ارسال: {_candidate_send_latency(candidate)}",
        *_timing_lines(candidate),
        VIVA_SEP,
        f"🎯 Entry: <b>{_price(candidate.planned_entry)}</b>",
        f"🛑 First Stop: <b>{_price(candidate.sl)}</b>",
        *([f"🎯 PinWall Entry 2: <b>{_price(float((candidate.metadata or {}).get('pinwall_entry2')))}</b>"] if candidate.setup_code in {"PINVAL","PINWALLQ"} and float((candidate.metadata or {}).get("pinwall_entry2") or 0) > 0 else []),
        f"📈 Live Price: <b>{_price(float((candidate.metadata or {}).get('live_price') or candidate.planned_entry))}</b>",
        *[f"🏁 TP{i+1}: {_price(level)} • {weight:.0f}%" for i, (level, weight) in enumerate(zip((candidate.metadata.get('target_ladder') or {}).get('targets', [candidate.tp1, candidate.tp2]), (candidate.metadata.get('target_ladder') or {}).get('weights', [50, 30, 20])))],
        # Viva 09-20 (third time, verbatim): «فرمول ریسک به ریوارد ... اصلا
        # اهمیت نداره» → shown as a read-out only, never as a criterion.
        # Viva 09-20 round 10: no R:R row in the trade message at all — the
        # ladder is a PRICE PATH (5 parts), not a ratio.
        f"⭐ امتیاز ساختاری: {candidate.score}/10",
    ]
    rows.append(f"🤖 <b>نظر AI:</b> {_e(advisory or _ai_rich_note(candidate))}")
    if mm:
        # Viva 09-20: the ACTIVE management profile is named in the message so
        # «مدیریت سرمایه استاندارد» and «مدیریت ویوا» can never be mixed up.
        _prof = str(mm.get("profile") or "").upper()
        _prof_fa = "«مدیریت ویوا»" if _prof == "VIVA" else "«مدیریت سرمایه استاندارد»"
        rows.extend([
            VIVA_SEP,
            f"🏦 پروفایل مدیریت: <b>{_prof_fa}</b>",
            f"💼 حجم پوزیشن: <b>${mm['position_size']:,.0f}</b>",
            f"🧱 مارجین: <b>${mm['margin']:,.2f}</b>",
            f"⚙️ اهرم: <b>{mm['leverage']}x</b>",
            f"🛡 ریسک: <b>{mm['risk_pct']:.2f}%</b>",
        ])
        if mm.get("liq_warning_fa"):
            rows.append(f"⚠️ {_e(mm['liq_warning_fa'])}")
    rows.append(f"🆔 <code>{_e(candidate.metadata.get('public_code') or candidate.signal_id)}</code>")
    return "\n".join(rows)


def send_confirmed(candidate: SignalCandidate, chart_df: Optional[pd.DataFrame]) -> bool:
    """Execution channel is intentionally chart-first: confirmed trade numbers
    plus a one-click link back to its educational alert/chart."""
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    # ── Viva 09-23 (round 20): the confirmed ladder's FIRST pill also obeys
    # the lower-TF law — snap it to the nearest LTF swing (the touch a member
    # actually watches) instead of a pure 20%-of-path step. Fail-open.
    _ltf_df_conf = None
    try:
        from analysis.trade_management import ltf_for_trigger, TP1_CAP_BY_TF
        from data.fetcher import get_klines as _gk
        _ltf_df_conf = _gk(str(candidate.symbol),
                           ltf_for_trigger(str(candidate.trigger_timeframe or "15m")),
                           60, closed_only=False, use_cache=True)
    except Exception:
        _ltf_df_conf = None
    candidate.metadata["target_ladder"] = build_ladder(
        candidate.planned_entry, candidate.sl, candidate.direction, candidate.market,
        candidate.tp2, structural_tp1=candidate.tp1,
        fee_pct=(SETTINGS.fee_rate_percent + SETTINGS.slippage_percent) * 2.0 / 100.0,
        trigger_tf=str(candidate.trigger_timeframe or "15m"),
        wall_level=float((candidate.metadata or {}).get("internal_wall") or 0.0),
        ltf_df=_ltf_df_conf,
        ltf_cap_pct=float(TP1_CAP_BY_TF.get(str(candidate.trigger_timeframe or "15m"), 2.0))
        if _ltf_df_conf is not None else 0.0,
    )
    if chart_df is not None and not chart_df.empty and "close" in chart_df.columns:
        candidate.metadata["live_price"] = float(chart_df["close"].iloc[-1])
        # ── Viva 09-22 round 16: «زمان تایید ابتدای ابزار لانگ و شورت دقیقا از
        # کندل لایو شروع بشه … نهایتا ۲ کندل آخر داخل ابزار» — the tool is
        # anchored to the LIVE candle at the confirmation moment (the forming
        # candle appended by the renderer makes it at most two bars inside).
        # A real fill stamp from the ladder events always outranks this.
        if not candidate.metadata.get("tool_entry_ts") \
                and "timestamp" in chart_df.columns:
            candidate.metadata["tool_entry_ts"] = str(chart_df["timestamp"].iloc[-1])
    if not candidate.metadata.get("confirmation_chart_sent"):
        chart = generate_chart(chart_df, candidate, confirmed=True) if chart_df is not None else None
        if not chart:
            print(f"Confirmed publication blocked: chart unavailable for {candidate.signal_id}")
            return False
        source_chat = CHAT_ID_EDUCATION or CHAT_ID_ADMIN
        source_mid = candidate.metadata.get("education_chart_message_id") or candidate.metadata.get("education_message_id")
        link = _telegram_message_link(source_chat, int(source_mid)) if source_mid else ""
        keyboard = {"inline_keyboard": [[{"text": "📚 چارت و توضیحات هشدار اولیه", "url": link}]]} if link else None
        # Viva 2026-09-14 link-chain law: Confirmed is its OWN new message
        # replying to the final alert (or the last update / the compact when no
        # final alert ran). It never overwrites them — TP and stop receipts
        # will quote THIS message id.
        chain = _setup_chain_get(candidate)
        parent = (int(chain.get("approach") or candidate.metadata.get("approaching_message_id") or 0)
                  or int(chain.get("slot") or 0)
                  or int(chain.get("anchor_pro") or chain.get("edu_short") or 0)) or None
        _ph, mid = _post_chart_then_text(
            chart, _confirmed_chart_caption(candidate), target, reply_to=parent,
            reply_markup=keyboard,
            label=_chart_label(symbol=candidate.symbol, code=_public_code(candidate),
                               title_fa="تأیید سیگنال"))
        if mid:
            chain["confirmed"] = int(mid)
            chain["confirmed_photo"] = int(_ph or 0)
            _setup_chain_set(candidate, chain)
            candidate.metadata["confirmation_chart_message_id"] = int(mid)
            candidate.metadata["confirmation_chart_sent"] = True
        else:
            print(f"Confirmed execution-channel post failed {candidate.signal_id}")
        # PROP-1 mirror: Confirmed quotes the final alert inside the journal
        # and buttons back to the main channel's compact anchor.  Viva 09-17:
        # the journal receives Confirmed EVEN IF the execution post failed —
        # the signals channel must never go quiet because of another channel.
        _anchor = (int(chain.get("anchor_pro") or 0)
                   or int(chain.get("slot") or 0)
                   or int(chain.get("edu_short") or 0)
                   or int(chain.get("approach") or 0))
        _lnk = _telegram_message_link(CHAT_ID_EXECUTION or CHAT_ID_ADMIN, _anchor) if _anchor else ""
        _sig_mirror(_public_code(candidate), "confirmed",
                    _confirmed_chart_caption(candidate), chart, reply_kind="approach",
                    link=_lnk, link_text="🔗 پیام مختصر در کانال اصلی",
                    file_id=_LAST_PHOTO_FILE.get(int(_ph or 0), ""))
    # ── Round 15: the confirmed-only mirror of this signal into its
    # timeframe family's channel (no-op while those channel ids are unset).
    try:
        tf_channel_publish_confirmed(candidate, chart if candidate.metadata.get("confirmation_chart_sent") else None,
                                     file_id=_LAST_PHOTO_FILE.get(int(_ph or 0), ""))
    except Exception as exc:
        print(f"TF-channel mirror skipped {candidate.signal_id}: {exc}")
    # Deliberately no second verbose message in VivaMon Labs Pro.
    candidate.metadata["confirmation_message_sent"] = True
    return True


def send_candidate_cancelled(candidate: SignalCandidate, reason: str) -> bool:
    """Viva 2026-09-11 (final doctrine): the detailed alert is PERMANENT — a
    cancelled/expired chain never deletes anything. Its single UPDATE slot in
    the alerts channel is edited to ⛔ (so the chain visibly closes where it
    started), and an already-published PRO final-alert slot — if any — is
    edited in place to say the position was never activated."""
    closed = False
    try:
        closed = send_setup_update(
            candidate, note_fa=f"❌ {reason}",
            state_fa="⛔ <b>ستاپ بسته شد | پیش از تأیید ابطال/منقضی گردید</b>")
    except Exception as exc:
        print(f"cancel update-slot warning {candidate.signal_id}: {exc}")
    if candidate.metadata.get("approaching_sent"):
        _ch = _setup_chain_get(candidate)
        slot = int(_ch.get("approach") or _ch.get("pro") or 0) or int(
            candidate.metadata.get("approaching_message_id") or 0)
        if slot:
            try:
                edit_text_message(
                    slot, str(CHAT_ID_EXECUTION or CHAT_ID_ADMIN),
                    "⛔ <b>ستاپ بسته شد</b> — پوزیشنی فعال نشد.\n"
                    f"{_e(reason)}\n🆔 <code>{_e(_public_code(candidate))}</code>")
                closed = True
            except Exception as exc:
                print(f"cancel pro-slot warning {candidate.signal_id}: {exc}")
    print(f"Alert closed in place {candidate.signal_id}: {reason} • slot={closed}")
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
    # ── Viva 09-21: «هر الگویی اسم داره» — every setup now carries BOTH its
    # brand name (the sticker / channel language he asked for) and the Persian
    # meaning of the pattern family, so a member and the owner read the same
    # line without decoding an English slug.
    return {
        "PINVAL": "PINWALL LEGACY · پین‌وال کلاسیک",
        "PINWALLQ": "PINWALL QUALITY · پین‌وال کیفیت",
        "PINWALL_QUALITY": "PINWALL QUALITY · پین‌وال کیفیت",
        "ALBROX": "ALBROX ORIGINAL · بازپس‌گیری بیس",
        "TLBREAK": "VIVA-TLBREAK · شکست خط روند",
        "TECHCLASSIC": "TECHCLASSIC · الگوی کلاسیک پیوتی",
    }.get(code, code or "SETUP")


def _event_timing_lines(event: dict, include_confirmed: bool = False) -> str:
    """Compact Persian timing block shared by Main and Win Rate templates."""
    def iran(value):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            return dt.astimezone(ZoneInfo("Asia/Tehran")).strftime("%m-%d • %H:%M")
        except Exception:
            return "—"
    _event_iran, duration, latency = _event_clock(event)
    rows = ["⏰️ <b>زمان‌ها — ایران</b>"]
    if include_confirmed:
        rows.append(f"🟢 Confirmed: <b>{iran(event.get('confirmed_at'))}</b>")
    rows.extend([
        f"🕛 رویداد بازار: <b>{iran(event.get('event_at'))}</b>",
        f"📨 ارسال ربات: <b>{datetime.now(ZoneInfo('Asia/Tehran')).strftime('%m-%d • %H:%M')}</b>",
        f"⏱ مدت پوزیشن: <b>{duration}</b>",
    ])
    if latency not in {"—", "0m 0s"}:
        rows.append(f"📡 تأخیر ارسال: <b>{latency}</b>")
    return "\n".join(rows)


def _tp_status_lines(event: dict) -> str:
    hit = max(0, min(5, int(event.get("hit_index") or 0)))
    weights = [35, 35, 20, 5, 5]
    rows = []
    for i, weight in enumerate(weights, start=1):
        if i <= hit:
            rows.append(f"🎯 TP{i}  |  {weight}%  |  ✅️")
        else:
            rows.append(f"⏳ TP{i}  |  {weight}%  |  💰")
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
    _tp_mid = int(send_message(
        f"🎯 <b>{_e(signal.get('event') or 'TP')} HIT</b>   {code_line}\n\n"
        f"🏷 <b>{_e(setup)}</b>\n\n"
        f"🏦 <b>{_e(signal['symbol'])}</b> • {_e(signal.get('trigger_timeframe') or signal.get('style', ''))} • {_e(signal.get('style',''))} • {_e(signal.get('direction',''))}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n{_event_timing_lines(signal, include_confirmed=True)}\n"
        f"━━━━━━━━━━━━━━━━━━\n🔰 Entry: <b>{_price(float(signal.get('entry') or 0))}</b>\n"
        f"⭕️ First Stop: <b>{_price(float(signal.get('original_sl') or 0))}</b>\n"
        f"📈 Live Price: <b>{_price(float(signal.get('live_price') or 0))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n📊 <b>جزئیات این پله</b>\n\n"
        f"• حجم بسته‌شده: <b>{float(signal.get('weight', 0)):.0f}%</b>\n\n"
        f"• حرکت قیمت: <b>{float(signal.get('leg_price_move_pct', 0)):+.2f}%</b>\n\n"
        f"• سود پله: <b>${float(signal.get('leg_profit_usd', 0)):+.2f}</b>\n\n"
        f"• بازده پله با اهرم: <b>{float(signal.get('leg_full_roi_pct', 0)):+.2f}%</b>\n\n"
        f"• اثر بر کل مارجین: <b>{float(signal.get('leg_margin_roi_pct', 0)):+.2f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n💼 مارجین: <b>${float(signal.get('margin') or 0):.2f}</b>    ⚙️ اهرم: <b>{int(signal.get('leverage') or 1)}x</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n🔒 Trailing SL جدید: <b>{_price(float(signal.get('new_sl') or signal.get('sl') or 0))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n📌 <b>VIVAMON-Labs-Pro</b>",
        target,
    ) or 0)
    try:
        tf_channel_set_latest_result(str(signal.get("public_code") or ""), target,
                                     _tp_mid, f"{event_key} HIT")
    except Exception as exc:
        print(f"TF-channel link refresh skipped ({event_key}): {exc}")
    return _tp_mid


def send_stop_event_to_results(event: dict, pro_mid: int) -> int:
    """Viva 2026-09-14 (verbatim): «اول پیام هیت شدن استاپ میاد که ریپلای میشه
    به پیام تایید... بعد این پیام میره به کانال وین ریت و لینک بشه به هم دیگه»
    — the stop receipt belongs to the win-rate ledger with a two-way code link."""
    kind = str(event.get("event") or "")
    if kind not in {"TRAIL_STOP", "STOP"}:
        return 0
    target = CHAT_ID_RESULTS or CHAT_ID_ADMIN
    code = _e(event.get("public_code") or event.get("signal_id"))
    main_link = _telegram_message_link(CHAT_ID_EXECUTION or CHAT_ID_ADMIN, int(pro_mid or 0))
    code_line = f'<a href="{main_link}">🆔 <code>{code}</code></a>' if main_link else f"🆔 <code>{code}</code>"
    setup = _setup_display(event.get("source") or event.get("strategy_fa"))
    hit = int(event.get("hit_index") or 0)
    trailed = bool(event.get("trailing_used")) or (
        hit > 0 and abs(float(event.get("sl") or 0) - float(event.get("original_sl") or 0)) > 1e-9)
    title = (f"🔐 TP{hit} HIT • خروجِ محافظت‌شده باقی‌مانده" if trailed else "⛔ STOP LOSS HIT")
    send_signal_separator(target)
    _stop_mid = int(send_message(
        f"{title}   {code_line}\n\n"
        f"🏷 <b>{_e(setup)}</b>\n\n"
        f"🏦 <b>{_e(event.get('symbol'))}</b> • {_e(event.get('trigger_timeframe') or event.get('style'))} • "
        f"{_e(event.get('style'))} • {_e(event.get('direction'))}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n{_event_timing_lines(event)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔰 Entry: <b>{_price(float(event.get('entry') or 0))}</b>\n"
        f"⭕️ First Stop: <b>{_price(float(event.get('original_sl') or 0))}</b>\n"
        f"📍 استاپِ اجراشده: <b>{_price(float(event.get('stop') or event.get('sl') or 0))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• سود/ضرر تجمعی: <b>${float(event.get('realized_profit_usd', 0)):+.2f}</b>\n\n"
        f"• اثر نهایی بر کل مارجین: <b>{float(event.get('realized_margin_roi_pct', 0)):+.2f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n📌 <b>VIVAMON-Labs-Pro</b>",
        target) or 0)
    try:
        tf_channel_set_latest_result(str(event.get("public_code") or ""), target,
                                     _stop_mid, "خروج با استاپ" if not trailed else f"خروج محافظت‌شده TP{hit}")
    except Exception as exc:
        print(f"TF-channel stop-link refresh skipped: {exc}")
    return _stop_mid


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
    # Viva 2026-09-14 (verbatim): «نتیجه نهایی هم ریپلای میشه به پیام هیت
    # شدن استاپ لاس با همون کد» — quote the position's own stop-hit receipt;
    # only a position that never printed a stop falls back to Confirmed.
    for _stop_key in ("TRAIL_STOP", "STOP"):
        _mid = _exact_event_message_id(signal_id, _stop_key)
        if _mid:
            return _mid
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


def _event_ts(value) -> Optional[pd.Timestamp]:
    """Parse a stored event/candidate timestamp into naive UTC."""
    if not value:
        return None
    try:
        _t = pd.Timestamp(str(value))
    except Exception:
        return None
    try:
        if _t.tzinfo is not None:
            _t = _t.tz_convert("UTC").tz_localize(None)
    except Exception:
        pass
    return _t


def _tool_band(candidate: SignalCandidate) -> tuple[float, float]:
    """(bottom, top) of the DRAWN long/short tool — exactly what the chart
    paints: the red box down to the stop, the green box up to the final
    target, plus every drawn TP pill. Price inside this band = «داخل ابزار»."""
    md = candidate.metadata or {}
    ladder = md.get("target_ladder") or {}
    targets = [float(t) for t in (ladder.get("targets") or []) if float(t or 0) > 0]
    entry = float(getattr(candidate, "planned_entry", 0) or 0)
    sl = float(getattr(candidate, "sl", 0) or 0)
    tp2 = float(getattr(candidate, "tp2", 0) or 0)
    levels = [x for x in [entry, tp2, *targets] if x > 0]
    if not levels:
        return 0.0, 0.0
    if str(getattr(candidate, "direction", "LONG")).upper() == "LONG":
        return (min([entry, sl] if sl > 0 else [entry]), max(levels))
    return (min(levels), max([entry, sl] if sl > 0 else [entry]))


def _tool_escape(candidate: SignalCandidate, frame: Optional[pd.DataFrame],
                 now: Optional[pd.Timestamp] = None) -> int:
    """How many CLOSED candles have left the drawn tool region.

    Viva 09-20 (clarified): the 40 bars were only an example — the count is
    whatever the tool's own geometry produces. A candle is OUTSIDE when it
    printed past the tool's right edge (TOOL_FORWARD_BARS forward bars from
    the entry candle, the same margin the confirmed chart paints) or when its
    close sits beyond the tool's price band (above the top pill for a long /
    below it for a short, or through the stop on the other side). Zero = the
    price is still inside the long/short tool → trigger TF everywhere.
    """
    md = candidate.metadata or {}
    band_lo, band_hi = _tool_band(candidate)
    entry = _event_ts(md.get("tool_entry_ts")) \
        or _event_ts(getattr(candidate, "confirmed_at", "")) \
        or _event_ts(getattr(candidate, "created_at", ""))
    if entry is None:
        return 0
    right = _event_ts(md.get("tool_right_ts"))
    if right is None:
        try:
            from database.repository_v7 import TF_MINUTES
            _m = float(TF_MINUTES.get(str(candidate.trigger_timeframe or "15m").lower(),
                                      TF_MINUTES.get("15m")) or 15)
        except Exception:
            _m = 15.0
        right = entry + pd.Timedelta(minutes=_m * TOOL_FORWARD_BARS)
    if frame is None or getattr(frame, "empty", True):
        # no tape to measure: fall back to the clock alone (never stalls)
        if now is None:
            return 0
        _m = max((right - entry).total_seconds() / 60.0 / TOOL_FORWARD_BARS, 1e-9)
        bars = int(((now - entry).total_seconds() / 60.0) // _m)
        return max(0, bars - TOOL_FORWARD_BARS)
    _tol = 0.0005 * max(abs(band_hi), abs(band_lo), 1e-9)
    out = 0
    for _, row in frame.iterrows():
        ts = _event_ts(row.get("timestamp"))
        if ts is None or ts <= entry:
            continue
        if ts > right:
            out += 1
            continue
        if band_hi <= 0:
            continue
        _close = float(row.get("close") or 0)
        if _close > band_hi + _tol or _close < band_lo - _tol:
            out += 1
    return out


def _pick_view_tf(candidate: SignalCandidate, now: Optional[pd.Timestamp] = None) -> str:
    """ONE step up in the ladder (his «یک تایم بالاتر»), never more than the
    canvas needs: the finest higher TF where the tool's origin still fits."""
    from database.repository_v7 import TF_MINUTES
    base = str(candidate.trigger_timeframe or "15m").lower()
    ladder = LIFECYCLE_VIEW_LADDER.get(base) or []
    if not ladder:
        return base
    md = candidate.metadata or {}
    created = _event_ts(md.get("tool_anchor_ts")) \
        or _event_ts(getattr(candidate, "confirmed_at", "")) \
        or _event_ts(getattr(candidate, "created_at", ""))
    if created is None:
        return ladder[0]
    _now = now if now is not None else pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
    age_min = max(0.0, (_now - created).total_seconds() / 60.0)
    for _tf in ladder:
        _m = float(TF_MINUTES.get(_tf, 0) or 0)
        if _m > 0 and age_min / _m <= LIFECYCLE_MAX_VIEW_BARS:
            return _tf
    return ladder[-1]


def _escape_note(base: str, view: str, escaped: int) -> str:
    """His ordered one/two-line explanation — in the MESSAGE, never on the chart."""
    return (
        f"🕒 پس از خروج {_fa_num(int(escaped))} کندل از ابزار، این پوزیشن در "
        f"تایم فریم {_TF_FA.get(view, view.upper())} نمایش داده شده است.\n"
        "ابزار روی محور زمان جابه‌جا نشده؛ ورود، استاپ و TPها روی همان زمان و "
        "قیمت اولیه‌اند و حرکت قیمت روی همان ابزار دیده می‌شود."
    )


def _lifecycle_view_plan(candidate: SignalCandidate,
                         now: Optional[pd.Timestamp] = None,
                         frame: Optional[pd.DataFrame] = None) -> tuple[str, int, str]:
    """Pick the display TF for every render that carries a LIVE chart.

    Viva 09-20 (final form): while the price is still INSIDE the long/short
    tool — and in every analysis/update before confirmation — the tape stays
    on the position's own trigger TF. The moment ANY candle has left the
    tool, the same anchored tool is re-rendered one TF higher with the
    ordered short note. Returns (view_tf, escaped_candles, note_fa).
    """
    from database.repository_v7 import TF_MINUTES
    base = str(candidate.trigger_timeframe or "15m").lower()
    if base not in TF_MINUTES:
        return str(candidate.trigger_timeframe or "15m"), 0, ""
    try:
        escaped = int(_tool_escape(candidate, frame, now=now))
    except Exception:
        escaped = 0
    # Viva 09-22: the tool itself must not come out STRETCHED («مثل چارت لینک
    # کش اومده»). Besides a candle leaving the tool, a tool that already spans
    # more bars than a clean canvas allows is rendered ONE TF UP — his words:
    # «به جاش یه تایم بالاتر بره یا دو تایم بالاتر … اگر باز کندل‌ها خارج می‌شد
    # ۲ ساعته». Shape and place stay the tool's own; only the tape steps up.
    _span_bars = 0
    try:
        _m8 = float(TF_MINUTES.get(base, 0) or 0)
        _e8 = _event_ts((candidate.metadata or {}).get("tool_entry_ts")) \
            or _event_ts(getattr(candidate, "confirmed_at", "")) \
            or _event_ts(getattr(candidate, "created_at", ""))
        _now8 = now if now is not None else pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
        if _m8 > 0 and _e8 is not None:
            _span_bars = int(max(0.0, (pd.Timestamp(_now8) - _e8).total_seconds() / 60.0 / _m8))
    except Exception:
        _span_bars = 0
    # …the trigger TF is only left when the tool is wider than the tool's OWN
    # designed span (TOOL_FORWARD_BARS = the 42 forward bars the confirmed
    # chart paints); anything inside that is the normal tape, not a stretch.
    # …plus two bars of slack: the forming candle and the boundary rounding
    # (the 09-20 ruling «the 42-bar tape is still the trigger TF» stays true).
    _wide_limit = max(int(TOOL_FORWARD_BARS) + 2,
                      int(os.getenv("TOOL_MAX_VIEW_BARS", TOOL_FORWARD_BARS + 2)
                          or TOOL_FORWARD_BARS + 2))
    if escaped < 1 and _span_bars <= _wide_limit:
        return base, 0, ""
    if escaped < 1 and _span_bars > _wide_limit:
        _ladder8 = LIFECYCLE_VIEW_LADDER.get(base) or []
        _view8 = _ladder8[0] if _ladder8 else base
        if _view8 == base:
            return base, 0, ""
        return _view8, 0, (
            f"ابزار لانگ/شورت روی تایم {base.upper()} کش می‌آمد "
            f"(حدود {_span_bars} کندل) — همان ابزار با همان شکل، "
            f"روی تایم {_view8.upper()} نمایش داده شده است.")
    view = _pick_view_tf(candidate, now=now)
    if view == base:
        return base, escaped, ""
    return view, escaped, _escape_note(base, view, escaped)


def _lifecycle_chart_frame(candidate: SignalCandidate, levels: list[float],
                           now: Optional[pd.Timestamp] = None) -> Optional[pd.DataFrame]:
    """Chart frame for every render that carries a LIVE chart.

    ALERT and CONFIRMATION charts keep the 09-14 pin (trigger TF). TP hits,
    stop receipts, live updates and final results obey the 09-20 law: while
    the price is still inside the drawn long/short tool they, too, stay on the
    trigger TF — the moment ANY candle has left the tool, the SAME anchored
    tool is re-rendered ONE TF higher with the ordered short note (never a
    slide on the time axis). A venue that cannot serve the higher frame falls
    back to the trigger TF WITHOUT a note — honest degradation, no stall.
    """
    from data.fetcher import get_klines
    from database.repository_v7 import TF_MINUTES
    base = str(candidate.trigger_timeframe or "15m").lower()
    # the trigger tape is ALWAYS fetched: it is what tells us whether price
    # is still inside the tool (the venue cache makes the second fetch cheap)
    try:
        frame = get_klines(candidate.symbol, base, 180, closed_only=False, use_cache=True)
    except Exception:
        frame = None
    if frame is None or getattr(frame, "empty", True):
        return None
    view, escaped, note = _lifecycle_view_plan(candidate, now=now, frame=frame)
    if view != base:
        _stepped = None
        try:
            _stepped = get_klines(candidate.symbol, view, 180, closed_only=False, use_cache=True)
        except Exception:
            _stepped = None
        if _stepped is not None and not getattr(_stepped, "empty", True):
            frame = _stepped
        else:
            # venue cannot serve that frame (or it has no tape yet): stay on
            # the trigger TF WITHOUT the note — honest degradation, never a stall
            view, escaped, note = base, 0, ""
    candidate.metadata["chart_view_tf"] = view
    candidate.metadata["chart_view_escaped"] = int(escaped)
    candidate.metadata["chart_view_note"] = note
    m_base = float(TF_MINUTES.get(base, 15) or 15)
    m_view = float(TF_MINUTES.get(view, m_base) or m_base)
    candidate.metadata["chart_tf_scale"] = (m_base / m_view) if m_view else 1.0
    return frame


def send_trade_close_event(event: dict) -> bool:
    """Final result with a live chart under its exact lifecycle parent."""
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    reply_id = _final_lifecycle_anchor(event) or None
    result = str(event.get("result") or "")
    emoji = "✅" if result == "WIN" else "❌" if result == "LOSS" else "⚪"
    code = _e(event.get("public_code") or event.get("signal_id"))
    setup = _setup_display(event.get("source") or event.get("strategy_fa"))
    hit = int(event.get("hit_index") or 0)
    # Viva 2026-09-14 ZEC K120563: banking TP1 then exiting at the BE-locked
    # trail was mislabelled «INITIAL STOP LOSS». Name what actually executed.
    trailed = bool(event.get("trailing_used")) or (
        hit > 0 and abs(float(event.get("sl") or 0) - float(event.get("original_sl") or 0)) > 1e-9)
    # Viva 2026-09-16: «هیچ کلمه انگلیسی نیاد» — exit kinds and the verdict
    # speak Persian (TP stays as the ladder code members already know).
    # Viva 09-19: the ladder now carries 2–3 aligned exits (was 5 hidden
    # segments); name the count dynamically and surface SMART_EXIT reasons
    # (spec §2.2: every decision must be explainable).
    _n_tgts = len(event.get("targets") or []) or 3
    _smart = str(event.get("close_reason") or "") == "SMART_EXIT"
    exit_kind = ("خروج هوشمند — تأیید بازگشت در تایم مانیتور" if _smart else
                 (f"هر {_n_tgts} پله" if hit >= _n_tgts else
                  (f"TP{hit} + خروجِ محافظت‌شده با استاپ تریل‌شده" if trailed
                   else (f"TP{hit} + خروجِ محافظت‌شده" if hit and result == "WIN"
                         else "استاپ ابتدایی"))))
    _reasons = list(event.get("exit_reasons_fa") or [])
    _why = ("🧠 علت خروج هوشمند (روی کندل بستهٔ تایم مانیتور):\n"
            + "\n".join(f"• {_e(r)}" for r in _reasons) + "\n\n") if _smart and _reasons else ""
    result_fa = {"WIN": "برد ✅", "LOSS": "باخت ❌"}.get(result, "بدون معامله ⚪")
    text = (
        f"{emoji} <b>نتیجه نهایی پوزیشن</b>   🆔 <code>{code}</code>\n\n"
        f"🏷 <b>{_e(setup)}</b>\n\n"
        f"🏦 {_e(event.get('symbol'))} • {_e(event.get('trigger_timeframe') or event.get('style'))} • {_e(event.get('style'))} • {_e(event.get('direction'))}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n{_event_timing_lines(event, include_confirmed=True)}\n"
        f"━━━━━━━━━━━━━━━━━━\n🔰 ورود: <b>{_price(float(event.get('entry') or 0))}</b>\n"
        f"⭕️ استاپ ابتدایی: <b>{_price(float(event.get('original_sl') or 0))}</b>\n"
        f"📈 قیمت زنده/خروج: <b>{_price(float(event.get('live_price') or 0))}</b>\n"
        f"🏁 TPهای زده‌شده: <b>{hit}/{_n_tgts}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n📌 نوع خروج: <b>{exit_kind}</b>\n\n"
        f"{_why}"
        f"• سود/ضرر نهایی: <b>${float(event.get('profit_usd') or 0):+.2f}</b>\n\n"
        f"• بازده قیمت: <b>{float(event.get('pnl') or 0):+.2f}%</b>\n\n"
        f"• اثر نهایی بر کل مارجین: <b>{float(event.get('margin_roi_pct') or 0):+.2f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n📍 نتیجه: <b>{result_fa}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n📌 <b>VIVAMON-Labs-Pro</b>"
    )
    _view_note = ""
    try:
        candidate = _event_chart_candidate(event)
        ladder = (candidate.metadata or {}).get("target_ladder") or {}
        frame = _lifecycle_chart_frame(candidate, [candidate.planned_entry, candidate.sl, *(ladder.get("targets") or []), (candidate.metadata or {}).get("current_trailing_sl", 0)])
        chart = generate_chart(frame, candidate, confirmed=True) if frame is not None else None
        _view_note = str((candidate.metadata or {}).get("chart_view_note") or "")
    except Exception:
        chart = None
    if _view_note:
        text = text.replace("📌 <b>VIVAMON-Labs-Pro</b>",
                            f"{_view_note}\n📌 <b>VIVAMON-Labs-Pro</b>")
    _ph, _tm = _post_chart_then_text(
        chart, text, target, reply_to=reply_id,
        label=_chart_label(symbol=str(event.get("symbol") or ""),
                           code=str(event.get("public_code") or ""),
                           title_fa="نتیجه نهایی پوزیشن"))
    mid = int(_tm or 0)
    if mid:
        # PROP-1 mirror: the final result closes the journal chain under the
        # last TP receipt (or the stop receipt when no TP was reached),
        # buttoned back to this exact receipt in the main channel.
        _lnk = _telegram_message_link(str(target), int(mid)) if mid else ""
        _sig_mirror(str(event.get("public_code") or ""), "result", text, chart,
                    reply_kind=(f"tp{hit}" if hit else "stop"),
                    link=_lnk, link_text="🔗 همین پیام در کانال اصلی")
    return mid


def build_weekly_results_digest() -> str:
    """PROP-3 (Viva 09-16 approved, verbatim): «هر جمعه تعداد پوزیشنهای هر
    ستاپ و وین و لوز و درصد هر کدوم و سود و ضرر دلاری هر کدوم رو در یک پیام
    بده با خط کشی و ایموجی و شیک و تر و تمیز» — ONE chic message, per-setup
    rows + an overall total, from the closed-results ledger of the last
    seven days (Tehran week boundary)."""
    from datetime import datetime, timezone, timedelta
    from database.db import get_recent_signals
    teh = timezone(timedelta(hours=3, minutes=30))
    now = datetime.now(teh)
    week_ago = now - timedelta(days=7)
    groups: dict = {}
    tot = {"n": 0, "w": 0, "l": 0, "usd": 0.0}
    for sig in get_recent_signals(600):
        closed = str(sig.get("closed_at") or "")
        if not closed:
            continue
        try:
            dt = datetime.fromisoformat(closed.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < week_ago:
            continue
        res = str(sig.get("result") or "").upper()
        if res not in ("WIN", "LOSS"):
            continue
        usd = (float(sig.get("margin_usd") or 0) * float(sig.get("leverage") or 1)
               * float(sig.get("pnl_pct") or 0) / 100.0)
        g = groups.setdefault(str(sig.get("source") or "?"),
                              {"n": 0, "w": 0, "l": 0, "usd": 0.0})
        for bucket in (g, tot):
            bucket["n"] += 1
            bucket["usd"] += usd
            bucket["w" if res == "WIN" else "l"] += 1
    lines = ["📊 <b>گزارش هفتگی نتایج ستاپ‌ها</b>",
             f"🗓 هفتهٔ منتهی به {now.strftime('%Y/%m/%d')} (تهران)",
             VIVA_SEP]
    if not groups:
        lines.append("• این هفته نتیجهٔ بسته‌شده‌ای ثبت نشده است؛ هفتهٔ بعد در خدمتیم.")
    for code, g in sorted(groups.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        wr = (100.0 * g["w"] / g["n"]) if g["n"] else 0.0
        lines += [f"• <b>{_setup_display(code)}</b>",
                  f"   🔢 تعداد پوزیشن: {g['n']} | ✅ برد: {g['w']} | ❌ باخت: {g['l']}",
                  f"   🎯 وین‌ریت: <b>{wr:.0f}٪</b> | 💵 سود/ضرر: <b>{g['usd']:+.2f}$</b>",
                  VIVA_SEP_ITEM]
    wr_tot = (100.0 * tot["w"] / tot["n"]) if tot["n"] else 0.0
    lines += [VIVA_SEP,
              "🧮 <b>جمع کل هفته</b>",
              f"• 🔢 {tot['n']} پوزیشن | ✅ {tot['w']} | ❌ {tot['l']} | 🎯 وین‌ریت <b>{wr_tot:.0f}٪</b>",
              f"• 💵 سود/ضرر دلاری کل: <b>{tot['usd']:+.2f}$</b>",
              "━━━━━━━━━━━━━━━━━━",
              "📌 <b>VIVAMON-Labs-Pro</b>"]
    return "\n".join(lines)


def send_weekly_results_digest() -> int:
    """Friday digest to the results ledger channel AND the clean journal
    (VIVA-MON-SIGNALS); the main channel stays untouched per «کیفیت کانال
    اصلی همین بمونه»."""
    text = build_weekly_results_digest()
    mid = 0
    for chat in (CHAT_ID_RESULTS, CHAT_ID_VIVA_SIGNALS):
        if chat:
            try:
                send_signal_separator(chat)
                mid = int(send_message(text, chat) or 0) or mid
            except Exception as exc:
                print(f"weekly digest warning {chat}: {exc}")
    return mid


def send_trade_result(event: dict) -> bool:
    """Viva 09-21: the final result is also the newest link target of this
    signal's timeframe-channel card (see tf_channel_set_latest_result)."""
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
    _res_mid = int(send_message(
        f"{emoji} <b>نتیجه نهایی پوزیشن</b>   {link_line}\n"
        f"🏷 <b>{_e(setup)}</b>\n\n"
        f"🏦 <b>{_e(event.get('symbol'))}</b> • {_e(event.get('trigger_timeframe') or event.get('style', ''))} • {_e(event.get('style', ''))} • {_e(event.get('direction',''))}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n{_event_timing_lines(event, include_confirmed=True)}\n"
        f"━━━━━━━━━━━━━━━━━━\n🔰 Entry: <b>{_price(float(event.get('entry') or 0))}</b>\n"
        f"⭕️ First Stop: <b>{_price(float(event.get('original_sl') or 0))}</b>\n"
        f"📈 Live / Exit Price: <b>{_price(float(event.get('live_price') or 0))}</b>\n"
        f"🏁 TPهای زده‌شده: <b>{int(event.get('hit_index') or 0)}/5</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n📊 <b>نتیجه نهایی</b>\n\n"
        f"• سود/ضرر نهایی: <b>${float(event.get('profit_usd', 0)):+.2f}</b>\n\n"
        f"• بازده قیمت: <b>{float(event.get('pnl', 0)):+.2f}%</b>\n\n"
        f"• اثر نهایی بر کل مارجین: <b>{float(event.get('margin_roi_pct') or 0):+.2f}%</b>\n\n"
        f"📍 نتیجه: <b>{_e(result)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n📌 <b>VIVAMON-Labs-Pro</b>",
        target,
    ) or 0)
    try:
        tf_channel_set_latest_result(str(event.get("public_code") or ""), target,
                                     _res_mid, f"نتیجه نهایی {result}")
    except Exception as exc:
        print(f"TF-channel final-link refresh skipped: {exc}")
    return _res_mid


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
    # Viva 2026-09-14 «ترندها را چرا برداشتی؟!» + SCORE 0/10 on confirmed
    # boxes: lifecycle charts must NOT render from a stripped synthetic
    # candidate. Load the chain's REAL row first — trendline points, zone,
    # score, RR and the market label all live in its metadata — and only fall
    # back to event-only geometry when the store no longer has the candidate.
    cand = None
    try:
        from database.candidate_store import get_active_candidates, get_resolved_candidates
        _sid = str(event.get("signal_id") or "")
        for row in list(get_active_candidates()) + list(get_resolved_candidates(limit=400)):
            if str(getattr(row, "signal_id", "")) == _sid:
                cand = row
                break
    except Exception:
        cand = None
    if cand is None:
        cand = SignalCandidate(
            signal_id=str(event.get("signal_id") or ""), symbol=str(event.get("symbol") or ""),
            style=str(event.get("style") or "DAYTRADE"), setup_code=str(event.get("source") or "SETUP"),
            setup_name=str(event.get("source") or "SETUP"), strategy_fa=str(event.get("strategy_fa") or event.get("source") or "SETUP"),
            direction=direction, score=int(event.get("score") or 0), status="CONFIRMED", entry_zone_bottom=entry,
            entry_zone_top=entry, planned_entry=entry, sl=sl, tp1=tp1, tp2=tp2,
            rr_tp1=rr1, rr_tp2=rr2, bias="BULLISH" if direction == "LONG" else "BEARISH",
            trigger_timeframe=str(event.get("trigger_timeframe") or ("5m" if str(event.get("style")) == "SCALP" else "15m")),
            metadata={},
        )
    cand.metadata = dict(cand.metadata or {})
    cand.metadata.update({
        "target_event": str(event.get("event") or ""),
        "public_code": event.get("public_code") or cand.metadata.get("public_code") or cand.signal_id,
        # Static Entry / First Stop / five TP geometry is carried into
        # every lifecycle chart. Only live price and the trailing line move.
        "target_ladder": {
            "targets": targets or build_ladder(
                entry, sl, direction, {}, tp2,
                trigger_tf=str(event.get("trigger_timeframe") or "15m")).get("targets", []),
            "weights": [35, 35, 20, 5, 5],
            "hit_index": int(event.get("hit_index") or 0),
        },
        "current_trailing_sl": float(event.get("sl") or event.get("new_sl") or 0),
        "hit_index": int(event.get("hit_index") or 0),
        # the tool's real time anchors: where the entry candle was and when
        # the tool was drawn — the renderer keeps both fixed (09-20 law).
        "tool_entry_ts": str(event.get("entry_filled_at")
                             or event.get("confirmed_at") or ""),
    })
    if not cand.metadata.get("tool_anchor_ts"):
        cand.metadata["tool_anchor_ts"] = str(event.get("confirmed_at")
                                              or event.get("entry_filled_at") or "")
    # The trade tape starts on the position's own trigger timeframe; the
    # 09-20 law may step the DISPLAY TF up from here when candles outrun it.
    if str(event.get("trigger_timeframe") or ""):
        cand.trigger_timeframe = str(event["trigger_timeframe"])
    return cand


def _ladder_reply_id(event: dict, kind: str) -> Optional[int]:
    """Viva ladder law (re-confirmed 2026-09-15, verbatim): «تی پی ها هر کدوم
    به تی پی قبلی لینک بشه، فقط اولین تی پی به پیام تایید سیگنال لینک میشه،
    تی پی ۲ به ۱، تی پی ۳ به ۲، ۴ به ۳ و ۵ به ۴، و پیام نتیجه به ۵».
    TP1 quotes the Confirmed receipt (pro_message_id); every later TP quotes
    the previous TP receipt (last_tp_message_id). Stop/trailing receipts quote
    Confirmed (09-14 verbatim). The FINAL result anchors through
    _final_lifecycle_anchor: WIN → the exact last TP receipt (…→TP5), a
    stop-exit → its own stop receipt, never anything else."""
    if kind.startswith("TP"):
        return (int(event.get("last_tp_message_id") or 0)
                or int(event.get("pro_message_id") or 0) or None)
    return int(event.get("pro_message_id") or 0) or None


def send_ladder_event(event: dict) -> bool:
    """Detailed live TP/trailing reply in VivaMon."""
    kind = str(event.get("event") or "")
    if kind not in {"TP1", "TP2", "TP3", "TP4", "TP5", "TRAIL_STOP", "STOP"}:
        return False
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    reply_id = _ladder_reply_id(event, kind)
    code = _e(event.get("public_code") or event.get("signal_id"))
    setup = _setup_display(event.get("source") or event.get("strategy_fa"))
    _mtf = str(event.get("monitor_tf") or "")
    common = (
        f"🏷 <b>{_e(setup)}</b>\n\n"
        f"🏦 <b>{_e(event.get('symbol'))}</b> • {_e(event.get('trigger_timeframe') or event.get('style'))} • {_e(event.get('style'))} • {_e(event.get('direction'))}"
        + (f" • مانیتور {_e(_mtf)}" if _mtf else "") + "\n\n"
        f"━━━━━━━━━━━━━━━━━━\n{_event_timing_lines(event)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔰 Entry: <b>{_price(float(event.get('entry') or 0))}</b>\n"
        f"⭕️ First Stop: <b>{_price(float(event.get('original_sl') or 0))}</b>\n"
        f"📈 Live Price: <b>{_price(float(event.get('live_price') or 0))}</b>\n"
    )
    if kind.startswith("TP"):
        text = (
            f"🎯 <b>{_e(kind)} HIT</b>   🆔 <code>{code}</code>\n\n" + common + "\n"
            f"━━━━━━━━━━━━━━━━━━\n📍 <b>وضعیت اهداف</b>\n\n{_tp_status_lines(event)}\n"
            f"━━━━━━━━━━━━━━━━━━\n📊 <b>جزئیات این پله</b>\n\n"
            f"• حجم بسته‌شده: <b>{float(event.get('weight', 0)):.0f}%</b>\n\n"
            f"• حرکت قیمت: <b>{float(event.get('leg_price_move_pct', 0)):+.2f}%</b>\n\n"
            f"• سود پله: <b>${float(event.get('leg_profit_usd', 0)):+.2f}</b>\n\n"
            f"• شیوۀ محاسبه: <code>{float(event.get('weight', 0)):.0f}%</code> × "
            f"<code>${float(event.get('margin') or 0) * int(event.get('leverage') or 1):,.0f}</code> × "
            f"<code>{float(event.get('leg_price_move_pct', 0)):+.2f}%</code> — ناخالص؛ کارمزد در پیام نتیجه کسر می‌شود\n\n"
            f"• بازده پله با اهرم: <b>{float(event.get('leg_full_roi_pct', 0)):+.2f}%</b>\n\n"
            f"• اثر بر کل مارجین: <b>{float(event.get('leg_margin_roi_pct', 0)):+.2f}%</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n💼 مارجین: <b>${float(event.get('margin') or 0):.2f}</b>    ⚙️ اهرم: <b>{int(event.get('leverage') or 1)}x</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n🔒 Trailing SL جدید: <b>{_price(float(event.get('new_sl') or event.get('sl') or 0))}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n📌 <b>VIVAMON-Labs-Pro</b>"
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
            f"{icon} <b>{title}</b>   🆔 <code>{code}</code>\n\n" + common + "\n"
            f"━━━━━━━━━━━━━━━━━━\n📍 <b>وضعیت اهداف</b>\n\n{_tp_status_lines(event)}\n"
            f"━━━━━━━━━━━━━━━━━━\n{price_label}: <b>{_price(float(event.get('stop') or event.get('sl') or 0))}</b>\n\n"
            f"• سود/ضرر تجمعی: <b>${float(event.get('realized_profit_usd', 0)):+.2f}</b>\n\n"
            f"• اثر نهایی بر کل مارجین: <b>{float(event.get('realized_margin_roi_pct', 0)):+.2f}%</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n📌 <b>VIVAMON-Labs-Pro</b>"
        )
    _view_note = ""
    try:
        candidate = _event_chart_candidate(event)
        ladder = (candidate.metadata or {}).get("target_ladder") or {}
        frame = _lifecycle_chart_frame(candidate, [candidate.planned_entry, candidate.sl, *(ladder.get("targets") or []), (candidate.metadata or {}).get("current_trailing_sl", 0)])
        chart = generate_chart(frame, candidate, confirmed=True) if frame is not None else None
        # Viva 09-20 (verbatim): TP charts may show the move on a higher TF
        # and explain it in one or two lines. Tool never slides.
        _view_note = str((candidate.metadata or {}).get("chart_view_note") or "")
    except Exception as exc:
        print(f"Live target chart warning {event.get('signal_id')}: {exc}")
        chart = None
    if _view_note:
        text = text.replace("📌 <b>VIVAMON-Labs-Pro</b>",
                            f"{_view_note}\n📌 <b>VIVAMON-Labs-Pro</b>")
    _ttl = f"هدف {kind[2:]} زده شد" if kind.startswith("TP") else "استاپ / تریل"
    _ph, _tm = _post_chart_then_text(
        chart, text, target, reply_to=reply_id,
        label=_chart_label(symbol=str(event.get("symbol") or ""),
                           code=str(event.get("public_code") or ""),
                           title_fa=_ttl))
    mid = _tm
    if mid:
        # PROP-1 mirror: the journal channel gets the same ladder — TP1 under
        # Confirmed, TPn under TP(n-1), stops under Confirmed — buttoned back
        # to this exact receipt in the main channel.
        _code = str(event.get("public_code") or "")
        _lnk = _telegram_message_link(str(target), int(mid)) if mid else ""
        if kind.startswith("TP"):
            _n = int(kind[2:] or 0)
            _sig_mirror(_code, f"tp{_n}", text, chart,
                        reply_kind="confirmed" if _n == 1 else f"tp{_n - 1}",
                        link=_lnk, link_text="🔗 همین پیام در کانال اصلی")
        else:
            _sig_mirror(_code, "stop", text, chart, reply_kind="confirmed",
                        link=_lnk, link_text="🔗 همین پیام در کانال اصلی")
    return mid



def send_trailing_note(event: dict) -> int:
    """Viva 09-19 smart-trailing ruling: SHORT lifecycle notes — profit-floor
    upgrades (🔒) and orange exit warnings (🟠) land in the main channel and
    the journal mirror. No chart (consumption law); these are one-liners."""
    kind = str(event.get("event") or "")
    if kind not in {"PROFIT_FLOOR", "EXIT_WARNING"}:
        return 0
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    code = _e(event.get("public_code") or event.get("signal_id"))
    setup = _setup_display(event.get("source") or event.get("strategy_fa"))
    hit = int(event.get("hit_index") or 0)
    # Viva 09-19 (verbatim): the short note REPLIES to the last TP-HIT receipt
    # of the same unique code; the journal mirror then buttons back to it.
    reply_id = 0
    for _n in range(hit, 0, -1):
        reply_id = int(_exact_event_message_id(str(event.get("signal_id") or ""), f"TP{_n}") or 0)
        if reply_id:
            break
    reply_id = reply_id or int(event.get("pro_message_id") or 0) or None
    _mtf = str(event.get("monitor_tf") or "")
    head = (f"🏷 <b>{_e(setup)}</b>\n"
            f"🏦 <b>{_e(event.get('symbol'))}</b> • {_e(event.get('trigger_timeframe') or event.get('style'))} • {_e(event.get('direction'))}"
            + (f" • مانیتور {_e(_mtf)}" if _mtf else "") + "\n"
            f"🆔 <code>{code}</code>")
    if kind == "PROFIT_FLOOR":
        text = (
            f"🔒 <b>کف حفاظتی سود فعال شد</b> (پس از TP{hit})\n\n{head}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"استاپ محافظتی: <b>{_price(float(event.get('new_sl') or event.get('sl') or 0))}</b>\n"
            f"طبق فرمول مرحله‌ای، استاپ از این سطح در جهت ضرر برنمی‌گردد.\n"
            f"📌 <b>VIVAMON-Labs-Pro</b>"
        )
        _ttl = "کف حفاظتی سود"
    else:
        reasons = list(event.get("reasons_fa") or [])
        text = (
            f"🟠 <b>هشدار خروج — {int(event.get('score') or 0)} نشانهٔ بازگشت در تایم مانیتور</b>\n\n{head}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(f"• {_e(r)}" for r in reasons) + "\n"
            f"اقدام: فقط هشدار — استاپ محافظتی فعال است. خروج کامل با تأیید قرمز (۳ نشانهٔ هم‌زمان) یا استاپ.\n"
            f"📌 <b>VIVAMON-Labs-Pro</b>"
        )
        _ttl = "هشدار خروج"
    _ph, mid = _post_chart_then_text(
        None, text, target, reply_to=reply_id,
        label=_chart_label(symbol=str(event.get("symbol") or ""),
                           code=str(event.get("public_code") or ""), title_fa=_ttl))
    mid = int(mid or 0)
    if mid:
        _lnk = _telegram_message_link(str(target), mid)
        _sig_mirror(str(event.get("public_code") or ""), "stop", text, None,
                    reply_kind=(f"tp{hit}" if hit else "confirmed"),
                    link=_lnk, link_text="🔗 همین پیام در کانال اصلی")
    return mid



def send_reentry_note(event: dict) -> int:
    """Viva 09-20 (round 9) — «سیگنال ورود مجدد روی همان پول‌بک».

    After TP1 was banked and the protection phase closed the remainder, a
    pullback that holds with a confirmed candle is a fresh entry on the SAME
    code. The note replies to the last TP receipt of that code so the chain
    shows: TP1 receipt → protected exit → this re-entry.
    """
    if str(event.get("event") or "") != "REENTRY_SIGNAL":
        return 0
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    code = _e(event.get("public_code") or event.get("signal_id"))
    setup = _setup_display(event.get("source") or event.get("strategy_fa"))
    hit = int(event.get("hit_index") or 0)
    reply_id = 0
    for _n in range(max(hit, 1), 0, -1):
        reply_id = int(_exact_event_message_id(str(event.get("signal_id") or ""), f"TP{_n}") or 0)
        if reply_id:
            break
    reply_id = reply_id or int(event.get("pro_message_id") or 0) or None
    text = (
        f"🔁 <b>سیگنال ورود مجدد روی پول‌بک</b>\n\n"
        f"🏷 <b>{_e(setup)}</b>\n"
        f"🏦 <b>{_e(event.get('symbol'))}</b> • {_e(event.get('trigger_timeframe') or event.get('style'))} • {_e(event.get('direction'))}\n"
        f"🆔 <code>{code}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"ورود: <b>{_price(float(event.get('entry') or 0))}</b>\n"
        f"استاپ: <b>{_price(float(event.get('sl') or 0))}</b>\n"
        f"هدف اول: <b>{_price(float(event.get('tp1') or 0))}</b> • هدف بعدی: <b>{_price(float(event.get('tp2') or 0))}</b>\n"
        f"{_e(event.get('reason_fa') or '')}\n"
        f"🔒 سود هدف اول قبلاً گرفته و قفل شده است؛ این ورود فقط روی پول‌بک همان سناریو است.\n"
        f"📌 <b>VIVAMON-Labs-Pro</b>"
    )
    _ph, mid = _post_chart_then_text(
        None, text, target, reply_to=reply_id,
        label=_chart_label(symbol=str(event.get("symbol") or ""),
                           code=str(event.get("public_code") or ""), title_fa="ورود مجدد"))
    mid = int(mid or 0)
    if mid:
        _lnk = _telegram_message_link(str(target), mid)
        _sig_mirror(str(event.get("public_code") or ""), "stop", text, None,
                    reply_kind=(f"tp{hit}" if hit else "confirmed"),
                    link=_lnk, link_text="🔗 همین پیام در کانال اصلی")
    return mid

def _technoclassic_preview_candidate(ev: dict):
    """Lightweight, never-saved SignalCandidate used ONLY to render a
    preview chart (break-pending / standby / fade plan) with the validated
    pattern lines and the E&M/Brooks overlay kit."""
    from analysis.models import SignalCandidate
    line = float(ev.get("line_price") or 0.0)
    fade = ev.get("fade") or {}
    is_fade = str(ev.get("state")) == "REJECTION_FADE" or bool(fade)
    direction = str((fade.get("direction") if is_fade else ev.get("direction")) or "LONG").upper()
    price = float(fade.get("entry") or ev.get("live") or line)
    stop = line
    if is_fade:
        tgt = float(fade.get("target") or line)
        stop = float(fade.get("stop") or line)
        pct = (tgt - price) / price * 100.0 if price else 0.0
        proj = {"from": price, "to": tgt, "direction": direction, "pct": round(pct, 1)}
        stage = "REJECTED_AT_EDGE"
    else:
        proj = dict(ev.get("measured") or {}, direction=str(ev.get("direction") or "LONG"))
        stage = "JUST_BROKE" if str(ev.get("state")) == "BREAK_READY" else "NEAR"
    tgt = float(proj.get("to") or 0.0)
    # real numbers so the renderer's scenario/TP machinery draws the plan, not zeros
    tp1 = tp2 = tgt
    risk = abs(price - stop)
    reward = abs(tgt - price) if tgt else 0.0
    rr1 = rr2 = round(reward / risk, 2) if risk > 0 and reward > 0 else 0.0
    atr_band = max(abs(float(proj.get("from") or line) * 0.001), 1e-9)
    return SignalCandidate(
        signal_id=f"tc-preview-{ev['symbol']}-{ev.get('pattern_tf')}-{ev.get('ref_ts','')}"[:64],
        symbol=str(ev["symbol"]), style="SWING", setup_code="TECHCLASSIC",
        setup_name="TechnoClassic pre-break preview",
        strategy_fa="تکنوکلاسیک | پیش‌نمایش (نه سیگنال)",
        direction=direction, score=0, status="EDUCATIONAL",
        entry_zone_bottom=price - 0.15 * atr_band, entry_zone_top=price + 0.15 * atr_band,
        planned_entry=price, sl=stop, tp1=tp1, tp2=tp2, rr_tp1=rr1, rr_tp2=rr2,
        bias="BULLISH" if direction == "LONG" else "BEARISH",
        trigger_timeframe=str(ev.get("pattern_tf") or "4h"),
        mandatory_gates={"technoclassic_preview_only": False},
        metadata={
            "strategy_variant": "VIVA_TLBREAK",
            "public_code": "",  # registry-reserved in send_technoclassic_preview
            "tc_clean": True,
            "tc_scenario": "fade" if is_fade else ("ready" if stage == "JUST_BROKE" else "near"),
            "tl_context_tf": ev.get("pattern_tf"), "tl_pattern": ev.get("pattern"),
            "tl_pattern_fa": ev.get("pattern_fa") or ev.get("pattern"),
            "tl_stage": stage,
            "tl_line": line, "tl_touches": ev.get("touches", 0),
            "viva_upper_points": ev.get("upper_points") or [],
            "viva_lower_points": ev.get("lower_points") or [],
            "viva_breakout_line": line,
            "tc_projection": proj,
            "tc_base": ev.get("base_box") or [],
            "tc_mid": (float(fade.get("tp_mid")) if is_fade and fade.get("tp_mid") else 0.0),
            "tc_fade": bool(is_fade),
        },
    )


def edit_text_message(message_id: int, chat_id: str, text: str) -> bool:
    """In-place text edit of an existing message (chart-less fallback of
    edit_chart_message). Same lifecycle rule: updates replace, never pile up."""
    if not TOKEN or not chat_id or not message_id:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/editMessageText",
            json={"chat_id": str(chat_id), "message_id": int(message_id),
                  "text": text[:4000], "parse_mode": "HTML",
                  "disable_web_page_preview": True}, timeout=12)
        return bool(r.ok and (r.json() or {}).get("ok"))
    except Exception:
        return False


def edit_chart_message(message_id: int, chat_id: str, image: bytes, caption: str,
                       reply_markup: Optional[dict] = None) -> bool:
    """Replace a photo message IN PLACE (chart + caption) — the mechanism that
    makes 'updates supersede the previous update' real instead of a trail of
    new posts. Telegram keeps the reply-link to the original anchor."""
    if not TOKEN or not chat_id or not message_id or not image:
        return False
    import json as _j
    media = {"type": "photo", "media": "attach://photo",
             "caption": _fit_caption(caption), "parse_mode": "HTML"}
    if reply_markup:
        media["reply_markup"] = reply_markup
    payload = {"chat_id": str(chat_id), "message_id": str(int(message_id)),
               "media": _j.dumps(media)}
    res = _tg_post(
        f"https://api.telegram.org/bot{TOKEN}/editMessageMedia",
        data=payload, files={"photo": ("viva-chart.png", image, "image/png")}, timeout=35)
    return bool(res and res.get("ok"))


def send_pattern_violation(ev: dict) -> bool:
    """Viva 09-24 (his nature sheets + txt verbatim): the wrong-side break of a
    ONE-NATURE pattern warns ONLY — «تنها باید هشدار و توضیحاتش بیاد اما نباید
    سیگنال صعودی بده یا حتی نزولی بده». Light text on the execution/admin
    chain; 24h cooldown per (symbol, tf, edge) so a live violation does not
    spam on every scan."""
    import time as _tpv
    from database.bot_kv import get_json as _gk, set_json as _sk
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    if not target:
        return False
    key = (f"pv:{str(ev.get('symbol') or '?')}:{str(ev.get('pattern_tf') or '?')}"
           f":{str(ev.get('break_edge') or '?')}")
    now = _tpv.time()
    try:
        prev = _gk(key) or {}
        if now - float(prev.get("ts", 0) or 0) < 24 * 3600:
            return False
    except Exception:
        pass
    text = ("⛔ <b>هشدار نقض الگو</b> — "
            f"{str(ev.get('symbol') or '')}\n"
            f"{str(ev.get('violation_fa') or '')}\n"
            f"قیمت لحظه‌ای: <code>{ev.get('live')}</code> · فاصله: "
            f"{ev.get('distance_atr')} ATR")
    sent = send_message(text, chat_id=target)
    if sent:
        try:
            _sk(key, {"ts": now})
        except Exception:
            pass
    return bool(sent)


def send_technoclassic_preview(ev: dict) -> bool:
    """Edge alert in the SAME caption family as the other setups' approaching
    alerts, on Viva's chain-lifecycle rule (2026-09-11): the FIRST alert is
    the permanent anchor; every later state of the same (symbol, timeframe)
    edge is ONE update message that REPLACES the previous update in place and
    replies to the anchor. Nothing is 100% before confirmation."""
    import time as _t
    from data.fetcher import get_klines
    from database.bot_kv import get_json as _gk, set_json as _sk
    target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN
    sym = str(ev["symbol"]).upper()
    tf = str(ev.get("pattern_tf") or "4h")
    state = str(ev.get("state") or "")
    react = ev.get("reactions") or {}
    fade = ev.get("fade") or {}
    scen = ev.get("scenarios") or {}
    is_fade = state == "REJECTION_FADE"
    # Viva 2026-09-14 «مگه امتیاز ۲ هم داریم؟ پایین‌تر از ۶ رو بستیم!» — a
    # preview below the education floor must never speak in any channel.
    if int(ev.get("structure_score") or 0) < int(getattr(SETTINGS, "educational_min_score", 6) or 6):
        return False
    cand = None
    frame = None
    try:
        frame = get_klines(sym, tf, 150, closed_only=False, use_cache=False)
    except Exception as exc:
        print(f"TECHCLASSIC preview tape unavailable: {exc}")
    cand = _technoclassic_preview_candidate(ev)

    def _chart_for(public_code: str):
        """Chart is rendered AFTER the unique code is settled, so the chart's
        footer and the caption always carry the identical identifier."""
        if frame is None or getattr(frame, "empty", True):
            return None
        cand.metadata["public_code"] = public_code
        try:
            return generate_chart(frame, cand, confirmed=False)
        except Exception as exc:
            print(f"TECHCLASSIC preview chart unavailable: {exc}")
            return None

    side_fa = "سقف" if ev.get("side") == "upper" else "کف"
    ck = f"tc_chain|{sym}|{tf}"
    chain = _gk(ck, {}) or {}
    now = _t.time()
    fresh = bool(chain.get("anchor")) and (now - float(chain.get("ts") or 0)) < 48 * 3600 \
        and chain.get("pattern") == str(ev.get("pattern"))
    if not fresh:
        # ── new ANCHOR: full alert, permanent, starts a fresh unique code ──
        badge, _ = _setup_badge(cand)
        # Viva 2026-09-12: the preview channel shares the ONE identifier
        # engine — registry-backed unique VIVA-TECLASSIC-T##### codes. The old
        # TC-SYM-tf-date mashup was not unique at all and broke the format law.
        try:
            from database.repository_v7 import reserve_public_code as _reserve
            code = _reserve(cand)
        except Exception:
            from analysis.models import generate_viva_public_code
            code = generate_viva_public_code("TECHCLASSIC", "SWING")
            cand.metadata["public_code"] = code
        chart = _chart_for(code)
        plan_line = ""
        if is_fade and fade:
            plan_line = (f"↩️ پلنِ بازگشت روی ضلع (کمک‌تأیید قانون آلفونسو): ورود {_price(fade.get('entry'))} • "
                         f"استاپ {_price(fade.get('stop'))} • TP میانه {_price(fade.get('tp_mid'))} • "
                         f"TP ضلع مقابل {_price(fade.get('target'))}\n")
        dir_fa = ("سناریوی احتمالی فروش" if str(ev.get("direction")) == "SHORT"
                    else "سناریوی احتمالی خرید")
        plan_sec = (VIVA_SEP + "\n" + plan_line) if plan_line else ""
        # Viva 2026-09-12 (format law, verbatim skeleton): 🏷 + 🆔 header,
        # educational block, 🪙 with STYLE + TF beside the symbol, ━━━ sections,
        # 🔎 zone block, the standard ⛔/✅ tail and 📢 footer.
        # Viva 09-17 «هشدار نهایی رو برگردان» — the preview body IS the
        # final-warning skeleton (MESSAGE_REFERENCE §2), verbatim order.
        _react = ev.get("reactions") or {}
        _comp = ev.get("compression") or {}
        _dir_fa = ("نزولی (SHORT)" if str(ev.get("direction")) == "SHORT"
                   else "صعودی (LONG)")
        _rej = int(_react.get("rejects", 0) or 0)
        _brk = int(_react.get("breaks", 0) or 0)
        _tot = max(1, _rej + _brk)
        caption = (
            f"🏷 <b>VIVA __ TecnoClasic</b>\n{VIVA_SEP}\n"
            f"⚡<b>هشدار نهایی | آماده‌سازی ورود</b>\n\n"
            f"🪙 <b>{_e(sym)}</b> • {_e(str(getattr(cand, 'style', '') or 'SWING'))} • "
            f"{_e(str(ev.get('direction') or ''))}\n{VIVA_SEP}\n"
            f"🔎 در آستانه شکست — تکنوکلاسیک (پیش‌نمایش؛ سیگنال نیست)\n"
            f"📐 خط روند اصلی روی تایم {_e(str(ev.get('pattern_tf') or ''))} • ضلع {side_fa}\n"
            f"{VIVA_SEP}\n"
            f"🎯 جهت محتمل پس از شکست معتبر: {_dir_fa}\n"
            f"📏 فاصله زنده تا خط: {float(ev.get('distance_atr') or 0):.2f} ATR • "
            f"پیوت‌های معتبر: {ev.get('touches')} (خطای فیت "
            f"{float(ev.get('fit_error_atr') or 0):.2f} ATR)\n"
            f"{VIVA_SEP}\n"
            f"⚖️ تاریخچۀ برخورد روی این خط: {_rej} دفع / {_brk} شکست از {_tot} برخورد "
            f"(نرخ دفع {int(float(_react.get('reject_rate', 0) or 0) * 100)}٪)\n"
            f"🌀 کامپرشن: {'قوی' if _comp.get('squeeze_ok') else 'ضعیف'} • "
            f"دوجی/کندل کوچک: {int(_comp.get('doji_count', 0) or 0)}\n"
            f"{VIVA_SEP}\n"
            f"سیگنال واقعی فقط با Close معتبرِ شکست + پولبک اول + BOS تایم پایین "
            f"صادر می‌شود.\n"
            f"{VIVA_SEP}\n"
            f"🆔<code>{_e(code)}</code>"
        )
        try:  # once-per-day separator
            today = _iran_now()[:10]
            if (_gk("tc_pro_sep", {}) or {}).get("day") != today:
                _mid = send_message("<b>━━━━━━━━ VIVA-MON-LABS ━━━━━━━━</b>", target)
                if _mid:
                    _sk("tc_pro_sep", {"day": today, "mid": int(_mid)})
        except Exception:
            pass
        # Viva 2026-09-11 family spec (now for EVERY setup incl. TC): the
        # alerts channel keeps the permanent DETAILED alert and receives a
        # compact copy replying to it; PRO carries the COMPACT alert as the
        # single live slot — every later update/final state replaces THIS post
        # in place and the 📚 button points at the detailed alert.
        # Viva 2026-09-13 «اگر قوانینش با تکنوکلاسیک یکی هست، این باید پاک
        # بشه»: the preview no longer mirrors a SECOND detailed alert into the
        # alerts channel. It lives only as the main/PRO live slot; a real TC
        # alert (DB-backed chain) keeps the permanent detailed post there.
        edu_mid = 0
        _dist = float(ev.get("distance_atr") or 0)
        _dist = float(ev.get('distance_atr') or 0)
        # (the retired preview pair no longer posts into the alerts channel)
        markup = None
        if edu_mid:
            link = _telegram_message_link(CHAT_ID_EDUCATION or CHAT_ID_ADMIN, int(edu_mid))
            if link:
                markup = {"inline_keyboard": [[{"text": "📚 چارت و توضیحات هشدار اولیه",
                                                "url": link}]]}
        _ph, mid = _post_chart_then_text(
            chart, caption, target, reply_markup=markup,
            label=_chart_label(symbol=str(getattr(cand, "symbol", "") or ""),
                               code=code, title_fa="هشدار نهایی"))
        if mid:
            # PRO anchor == the permanent compact; the first state change
            # posts a REPLACEMENT update above it and replies to this anchor.
            _sk(ck, {"anchor": int(mid), "anchor_photo": int(_ph or 0),
                     "edu": int(edu_mid or 0), "update": 0, "upd_n": 0,
                     "ts": now, "last_upd_ts": now, "code": code, "pattern": str(ev.get("pattern")),
                     "state": state, "fade": bool(is_fade)})
            # confirmation messages quote the PRO anchor — updates never move that link
            _sk(f"tc_link|{sym}|{tf}", {"mid": int(mid), "ts": now, "state": state})
        return bool(mid)
    # ── existing anchor: state must have MOVED, else stay silent ────────────
    if chain.get("state") == state and bool(chain.get("fade")) == bool(is_fade):
        return False
    # Viva 2026-09-14 «۵ هشدار روی یک ناحیه و قیمت یکسان» — the FIRST state
    # change after the anchor speaks; every further preview update waits for a
    # NEW pattern bar. Intra-candle flips must not ping-pong the channel.
    _bar = str(ev.get("ref_ts") or "")[:16] or f"bar{int(now // 3600)}"
    if chain.get("upd_bar") == _bar:
        return False
    code = str(chain.get("code") or cand.metadata.get("public_code") or "")
    cand.metadata["public_code"] = code
    chart = _chart_for(code)
    upd_n = int(chain.get("upd_n") or 0) + 1
    state_fa = {"REJECTION_FADE": "↩️ کندلِ دفع در کانال — پلنِ بازگشت روی تابلو (تأییدِ تایم‌پایین لازم)",
                "BREAK_READY": "⏱ آماده‌باشِ شکست — خط تست شد؛ تأییدِ کلوز لازم است",
                "EDGE_NEAR": "👀 هنوز فقط نزدیکِ ضلع؛ ربات منتظرِ نشانه است"}.get(state, state)
    plan = ""
    if is_fade and fade:
        plan = (f"↩️ پلن: ورود {_price(fade.get('entry'))} • استاپ {_price(fade.get('stop'))} • "
                f"TP میانه {_price(fade.get('tp_mid'))} • TP مقابل {_price(fade.get('target'))}")
    # ONE update template for EVERY setup (Viva 2026-09-12): same numbered
    # caption, separators, rule line and 🆔 position as TLBREAK/ALBROX/PINVAL
    # — only the note carries the preview state.
    caption = _setup_update_caption(
        cand, note_fa=(state_fa + "\n" + plan) if plan else state_fa,
        state_fa="🔁 <b>به‌روزرسانیِ پیش‌نمایش (همان شناسه)</b>", upd_n=upd_n)
    anchor_mid = int(chain.get("anchor") or 0)
    upd = int(chain.get("update") or 0)
    edu_mid = int(chain.get("edu") or 0)
    markup = None
    if edu_mid:
        link = _telegram_message_link(CHAT_ID_EDUCATION or CHAT_ID_ADMIN, edu_mid)
        if link:
            markup = {"inline_keyboard": [[{"text": "📚 چارت و توضیحات هشدار اولیه",
                                            "url": link}]]}
    # Viva 2026-09-12: «چرا در کانال اصلی پیام آپدیت میاد؟!» — never again.
    # TC state changes post UNDER the detailed alert in the alerts channel;
    # the main channel keeps only its permanent compact anchor. A legacy chain
    # without a stored edu id falls back to the old PRO-slot behaviour.
    _alerts_chat = str(CHAT_ID_EDUCATION or CHAT_ID_ADMIN or "")
    _under_detail = bool(edu_mid) and bool(_alerts_chat)
    upd_chat = _alerts_chat if _under_detail else str(target)
    reply_to = (int(edu_mid) if _under_detail else (anchor_mid or None)) or None
    _ph, new_mid = _post_chart_then_text(
        chart, caption, upd_chat, reply_to=reply_to, reply_markup=markup,
        label=_chart_label(symbol=str(getattr(cand, "symbol", "") or ""),
                           code=code, title_fa="به‌روزرسانی رصد"))
    done = bool(new_mid)
    if done:
        if upd and upd != anchor_mid:
            try:
                delete_message(str(chain.get("upd_chat") or target), upd)
                _oph = int(chain.get("update_photo") or 0)
                if _oph:
                    delete_message(str(chain.get("upd_chat") or target), _oph)
            except Exception:
                pass
        upd = int(new_mid)
        _sk(ck, {"anchor": anchor_mid, "update": upd, "edu": edu_mid, "ts": now,
                 "upd_n": upd_n, "upd_chat": upd_chat, "code": code,
                 "upd_bar": _bar, "last_upd_ts": now,
                 "update_photo": int(_ph or 0),
                 "pattern": str(ev.get("pattern")),
                 "state": state, "fade": bool(is_fade)})
        try:  # keep the anchor→confirmation link state fresh without moving it
            _link = _gk(f"tc_link|{sym}|{tf}", {}) or {}
            if _link.get("mid"):
                _sk(f"tc_link|{sym}|{tf}", {"mid": int(_link["mid"]), "ts": now, "state": state})
        except Exception:
            pass
    return done
