# bot/telegram_bot.py - Professional Signal Bot v7
# 3-signal flow: Initial → Approaching → Confirmed → Result
# کانال: vivasignalyst-Chanel
import requests
import io
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf

from analysis.risk import calculate_position

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID_SIGNALS = os.environ.get("CHAT_ID_SIGNALS", "")
CHAT_ID_APPROACHING = os.environ.get("CHAT_ID_APPROACHING", "")  # کانال هشدار نزدیک شدن
CHAT_ID_RESULTS = os.environ.get("CHAT_ID_RESULTS", "")
CHAT_ID_ADMIN = os.environ.get("CHAT_ID", "")

ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", "1000"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.5"))

CHANNEL_NAME = "vivasignalyst-Chanel"


def _split_telegram_text(text: str, limit: int = 4000):
    if len(text) <= limit:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return chunks


def send_message(text: str, chat_id: str = None) -> bool:
    if not chat_id:
        chat_id = CHAT_ID_ADMIN
    if not TOKEN or not chat_id:
        print("Message skipped: missing TELEGRAM_TOKEN or chat_id")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    ok = True
    try:
        for chunk in _split_telegram_text(text):
            r = requests.post(url, data={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML"
            }, timeout=10)
            if not r.ok:
                print(f"Message error {r.status_code}: {r.text[:200]}")
                ok = False
    except Exception as e:
        print(f"Message error: {e}")
        return False
    return ok


def send_photo(image_bytes: bytes, caption: str, chat_id: str = None) -> bool:
    if not chat_id:
        chat_id = CHAT_ID_ADMIN
    if not TOKEN or not chat_id:
        print("Photo skipped: missing TELEGRAM_TOKEN or chat_id")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    try:
        r = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "caption": caption[:1024],
                "parse_mode": "HTML"
            },
            files={"photo": ("chart.png", image_bytes, "image/png")},
            timeout=30
        )
        if not r.ok:
            print(f"Photo error {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"Photo error: {e}")
        return False


def generate_chart(df: pd.DataFrame, sig: dict) -> bytes:
    try:
        chart_df = df.tail(80).copy()
        chart_df = chart_df.set_index("timestamp")
        chart_df.index = pd.DatetimeIndex(chart_df.index)

        mc = mpf.make_marketcolors(
            up='#00ff88', down='#ff4444',
            edge='inherit', wick='inherit', volume='in'
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            base_mpf_style='nightclouds',
            gridstyle=':'
        )

        score = sig.get("score", 5)
        tp1 = _get_tp(sig, "tp1")
        tp2 = _get_tp(sig, "tp2")

        hlines = [sig["entry"], sig["sl"], tp1, tp2]
        colors = ['#ffffff', '#ff4444', '#00ff88', '#00aa55']

        dir_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"
        trade_style = sig.get("trade_style", "SWING")

        buf = io.BytesIO()
        mpf.plot(
            chart_df,
            type='candle',
            style=style,
            title=(
                f"\n{sig['symbol']} | {sig.get('strategy_fa', sig['source'])} "
                f"| {sig['direction']} {dir_emoji} "
                f"| Score: {score}/10 | 📊 {trade_style}"
            ),
            ylabel='Price (USDT)',
            hlines=dict(
                hlines=hlines,
                colors=colors,
                linestyle='--',
                linewidths=1.2
            ),
            volume=True,
            savefig=dict(fname=buf, dpi=150, bbox_inches='tight'),
            figsize=(12, 7)
        )
        buf.seek(0)
        return buf.read()
    except Exception as e:
        print(f"Chart error: {e}")
        return None


def _get_tp(sig: dict, key: str) -> float:
    if sig.get(key) is not None:
        return sig[key]
    return (sig.get("trade_params") or {}).get(key, 0)


def detect_signal_type(sig: dict) -> str:
    entry = sig["entry"]
    sl = sig["sl"]
    sl_pct = abs(entry - sl) / entry * 100
    if sl_pct >= 1.5:
        return "📊 Swing"
    elif sl_pct >= 0.5:
        return "⚡ Scalp"
    else:
        return "🔥 Micro"


def calculate_score(sig: dict) -> dict:
    score = 0
    details = []
    confirmations = sig.get("confirmations", [])
    source = sig["source"]

    has_sweep = any("Sweep" in c and "✅" in c for c in confirmations)
    has_choch = any("CHoCH" in c and "✅" in c for c in confirmations)
    is_new = any("جدید" in c for c in confirmations)

    # MTF تایید
    mtf_confirmed = sig.get("mtf_confirmed", False)
    if mtf_confirmed:
        score += 2
        details.append("✅ +2 تایید چند تایم‌فریمی")
    else:
        details.append("⚠️ +0 بدون تایید MTF")

    # ساختار HTF
    if sig.get("bias") in ["BULLISH", "BEARISH"]:
        score += 2
        details.append("✅ +2 ساختار HTF مشخص")
    else:
        details.append("❌ +0 ساختار HTF نامشخص")

    # ناحیه مناسب
    source_scores = {
        "SMC": "قیمت داخل Order Block",
        "RTM": "قیمت در ناحیه Base",
        "ICT": "قیمت در OTE Zone",
        "QM": "قیمت در ناحیه QM",
        "ENGULFING": "کندل پوششی فعال",
        "PINBAR": "پین بار فعال",
        "FVG": "قیمت در FVG",
        "IFVG": "قیمت در IFVG",
        "FLIPZONE": "قیمت در فیلیپ زون",
        "BREAKOUT": "شکست سطح تأیید شد",
        "ORDERBLOCK": "قیمت در اوردر بلاک",
        "CHOCH": "تغییر ساختار تأیید شد",
        "RETURN_AREA": "بازگشت به ناحیه",
    }

    if source in source_scores:
        if sig.get("zone_top") or sig.get("ob_zone") or sig.get("base_zone") or sig.get("ote_zone"):
            score += 2
            details.append(f"✅ +2 {source_scores[source]}")

    if has_sweep:
        score += 2
        details.append("✅ +2 Liquidity Sweep تایید")
    else:
        details.append("⚠️ +0 Sweep هنوز نشده")

    if has_choch or sig.get("mss"):
        score += 2
        details.append("✅ +2 CHoCH/MSS تایید")
    else:
        details.append("⚠️ +0 CHoCH هنوز تایید نشده")

    if is_new:
        score += 1
        details.append("🆕 +1 تغییر جدید در بازار")

    if source == "ICT" and sig.get("in_killzone"):
        score += 1
        details.append("⏰ +1 در Killzone هستیم")

    if sig.get("score_bonus"):
        score += sig["score_bonus"]
        details.append(f"⭐ +{sig['score_bonus']} امتیاز استراتژی")

    score = max(1, min(10, score))

    if score >= 9:
        label = "🏆 فوق‌العاده"
    elif score >= 8:
        label = "⭐ عالی"
    elif score >= 6:
        label = "👍 قابل قبول"
    elif score >= 4:
        label = "⚠️ متوسط"
    else:
        label = "❌ ضعیف"

    bar = "█" * score + "░" * (10 - score)

    return {"score": score, "label": label, "bar": bar, "details": details}


def calculate_money_management(sig: dict, score: int) -> dict:
    entry = sig["entry"]
    sl = sig["sl"]
    pos = calculate_position(entry, sl, sig["direction"], score, ACCOUNT_SIZE)

    tp1 = _get_tp(sig, "tp1")
    tp2 = _get_tp(sig, "tp2")

    partial_tp1 = sig.get("partial_tp1_pct", 60)
    partial_tp2 = sig.get("partial_tp2_pct", 40)

    if pos:
        leverage = pos["leverage"]
        margin_usd = pos["margin"]
        margin_pct = pos["margin_pct"]
        position_size_usd = pos["position_size"]
        risk_amount = pos["risk_amount"]
        risk_pct_of_account = pos["risk_pct"]
        sl_pct = pos["sl_pct"]
        if not tp1: tp1 = pos["tp1"]
        if not tp2: tp2 = pos["tp2"]
    else:
        leverage = 5
        margin_usd = ACCOUNT_SIZE * 0.01
        margin_pct = 1.0
        position_size_usd = margin_usd * leverage
        sl_pct = abs(entry - sl) / entry * 100 if entry else 1.0
        risk_amount = position_size_usd * (sl_pct / 100)
        risk_pct_of_account = (risk_amount / ACCOUNT_SIZE) * 100 if ACCOUNT_SIZE else 0

    if sig["direction"] == "LONG":
        tp1_pct = ((tp1 - entry) / entry) * 100 if entry else 0
        tp2_pct = ((tp2 - entry) / entry) * 100 if entry else 0
        mart_point = sl * 0.995
    else:
        tp1_pct = ((entry - tp1) / entry) * 100 if entry else 0
        tp2_pct = ((entry - tp2) / entry) * 100 if entry else 0
        mart_point = sl * 1.005

    # Partial TP: 60% at TP1, 40% at TP2
    tp1_profit = position_size_usd * (tp1_pct / 100) * (partial_tp1 / 100)
    tp2_profit = position_size_usd * (tp2_pct / 100) * (partial_tp2 / 100)
    total_profit = tp1_profit + tp2_profit

    return {
        "leverage": leverage,
        "margin_usd": round(margin_usd, 2),
        "margin_pct": round(margin_pct, 1),
        "position_size_usd": round(position_size_usd, 0),
        "risk_amount": round(risk_amount, 2),
        "risk_pct": round(risk_pct_of_account, 2),
        "sl_pct": round(sl_pct, 2),
        "tp1_pct": round(tp1_pct, 2),
        "tp2_pct": round(tp2_pct, 2),
        "tp1_profit": round(tp1_profit, 2),
        "tp2_profit": round(tp2_profit, 2),
        "total_profit": round(total_profit, 2),
        "mart_point": round(mart_point, 4),
        "partial_tp1": partial_tp1,
        "partial_tp2": partial_tp2,
    }


def attach_money_management(sig: dict) -> dict:
    score_data = calculate_score(sig)
    score = score_data["score"]
    mm = calculate_money_management(sig, score)
    sig["score"] = score
    sig["leverage"] = mm["leverage"]
    sig["margin_usd"] = mm["margin_usd"]
    if not sig.get("tp1"):
        sig["tp1"] = _get_tp(sig, "tp1")
    if not sig.get("tp2"):
        sig["tp2"] = _get_tp(sig, "tp2")
    return mm


def build_signal_reason(sig: dict) -> str:
    direction = sig["direction"]
    bias = sig.get("bias", "")
    bias_fa = "صعودی" if bias == "BULLISH" else "نزولی"
    dir_fa = "خرید" if direction == "LONG" else "فروش"

    # اگه توضیحات آموزشی داره
    if sig.get("description"):
        reason = f"📋 <b>دلیل صدور سیگنال:</b>\n\n"
        reason += f"{sig['description']}\n\n"
        
        # MTF info
        if sig.get("mtf_text"):
            reason += f"📊 <b>تحلیل چند تایم‌فریمی:</b>\n{sig['mtf_text']}\n\n"
        
        if sig.get("entry_conditions"):
            reason += f"🔑 <b>شرط ورود به پوزیشن:</b>\n"
            for cond in sig["entry_conditions"]:
                reason += f"• {cond}\n"
        
        return reason

    # پیش‌فرض
    return f"📋 <b>دلیل:</b> تحلیل ترکیبی چند روش.\n🔑 جهت: {dir_fa} ({bias_fa})\n"


def build_initial_caption(sig: dict, signal_id: str) -> str:
    """کپشن سیگنال اولیه (Setup forming)"""
    score_data = calculate_score(sig)
    score = score_data["score"]
    mm = calculate_money_management(sig, score)
    reason = build_signal_reason(sig)
    sig_type = detect_signal_type(sig)

    source_emoji = {
        "SMC": "📊", "RTM": "🔷", "ICT": "💎",
        "QM": "🔮", "ENGULFING": "🔥", "PINBAR": "📌",
        "FVG": "📐", "IFVG": "🔄", "FLIPZONE": "🔁",
        "BREAKOUT": "💥", "ORDERBLOCK": "🧱",
        "CHOCH": "⚡", "RETURN_AREA": "🎯"
    }.get(sig["source"], "📌")

    dir_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"
    trade_style = sig.get("trade_style", "SWING")

    details_text = "\n".join(f"   {d}" for d in score_data["details"])

    tp1 = _get_tp(sig, "tp1")
    tp2 = _get_tp(sig, "tp2")

    partial_tp1 = sig.get("partial_tp1_pct", 60)
    partial_tp2 = sig.get("partial_tp2_pct", 40)

    caption = (
        f"🔔 <b>New Setup Detected</b> 🔔\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{source_emoji} <b>{sig.get('strategy_fa', sig['source'])}</b>  •  "
        f"<code>{signal_id}</code>  {dir_emoji}\n"
        f"🪙 <b>{sig['symbol']}</b>  |  "
        f"<b>{sig['direction']}</b> {dir_emoji}\n"
        f"📈 Trend: <b>"
        f"{'Bullish 🟢' if sig.get('bias') == 'BULLISH' else 'Bearish 🔴'}"
        f"</b>  |  {sig_type}  |  📊 {trade_style}\n\n"

        f"⭐ <b>Signal Score:</b> "
        f"{score_data['bar']} {score}/10\n"
        f"🏷 {score_data['label']}\n"
        f"{details_text}\n\n"

        f"━━━━━━━━━━━━━━━━━━\n"
        f"{reason}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"

        f"💼 <b>Money Management</b>\n"
        f"├ 💰 Account: ${ACCOUNT_SIZE:,.0f}\n"
        f"├ ⚡ Leverage: <b>{mm['leverage']}x</b>\n"
        f"├ 📊 Margin: <b>{mm['margin_pct']}%</b> = ${mm['margin_usd']}\n"
        f"├ ⚠️ Real Risk: <b>{mm['risk_pct']}%</b> = ${mm['risk_amount']}\n"
        f"└ 📦 Position Size: ~${mm['position_size_usd']:,.0f}\n\n"

        f"📌 <b>Trade Levels</b>\n"
        f"├ 🎯 Entry:   <b>{sig['entry']:.4f}</b>\n"
        f"├ 🛑 SL:      <b>{sig['sl']:.4f}</b>  (-{mm['sl_pct']}%)\n"
        f"├ ⛔ Mart:    <b>{mm['mart_point']:.4f}</b>\n"
        f"├ 🥇 TP1:     <b>{tp1:.4f}</b>  (+{mm['tp1_pct']}%) → {partial_tp1}% کلوز\n"
        f"└ 🥈 TP2:     <b>{tp2:.4f}</b>  (+{mm['tp2_pct']}%) → {partial_tp2}% باقیمانده\n\n"

        f"💹 <b>Potential P&L</b>\n"
        f"├ 🥇 TP1 Profit: <b>+${mm['tp1_profit']}</b> ({partial_tp1}% position)\n"
        f"├ 🥈 TP2 Profit: <b>+${mm['tp2_profit']}</b> ({partial_tp2}% position)\n"
        f"├ 💰 Total:      <b>+${mm['total_profit']}</b>\n"
        f"└ ❌ Max Loss:   <b>-${mm['risk_amount']}</b>\n\n"

        f"📌 <b>Partial TP:</b>\n"
        f"├ 🥇 TP1: {partial_tp1}% کلوز → SL به Breakeven\n"
        f"└ 🥈 TP2: {partial_tp2}% باقیمانده\n\n"

        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <i>این سیگنال هنوز تایید نشده - وارد نشوید!</i>\n"
        f"⚠️ <i>منتظر پیام Approaching و سپس Confirmation باشید</i>\n"
        f"🆔 <code>{signal_id}</code>\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )

    return caption


def build_approaching_caption(sig_data: dict, signal_id: str,
                               current_price: float, distance_pct: float) -> str:
    """کپشن هشدار نزدیک شدن به Entry (80%)"""
    dir_emoji = "🟢" if sig_data["direction"] == "LONG" else "🔴"
    entry = sig_data["entry"]
    strategy_fa = sig_data.get("strategy_fa", sig_data.get("source", ""))
    
    caption = (
        f"⚡ <b>Approaching Entry!</b> ⚡\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{signal_id}</code>\n"
        f"🪙 <b>{sig_data['symbol']}</b> | {sig_data['direction']} {dir_emoji}\n"
        f"🔮 استراتژی: <b>{strategy_fa}</b>\n\n"
        
        f"📍 Entry: <b>{entry:.4f}</b>\n"
        f"📍 قیمت فعلی: <b>{current_price:.4f}</b>\n"
        f"📏 فاصله: <b>{distance_pct:.2f}%</b>\n\n"
        
        f"🎯 <b>قیمت به ناحیه ورود نزدیک شده!</b>\n"
        f"👀 آماده باشید و چارت را زیر نظر بگیرید.\n\n"
        
        f"⏳ <i>منتظر پیام تایید ورود باشید</i>\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )
    
    return caption


def build_confirmation_caption(sig_data: dict, signal_id: str,
                                current_price: float) -> str:
    """کپشن سیگنال تایید شده"""
    dir_emoji = "🟢" if sig_data["direction"] == "LONG" else "🔴"
    strategy_fa = sig_data.get("strategy_fa", sig_data.get("source", ""))
    sl = sig_data.get("sl", 0)
    tp1 = sig_data.get("tp1", 0)
    tp2 = sig_data.get("tp2", 0)
    
    caption = (
        f"✅ <b>Signal Confirmed!</b> ✅\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{signal_id}</code>\n"
        f"🪙 <b>{sig_data['symbol']}</b> | {sig_data['direction']} {dir_emoji}\n"
        f"🔮 استراتژی: <b>{strategy_fa}</b>\n\n"
        
        f"🎯 Entry confirmed at <b>{current_price:.4f}</b>\n"
        f"🛑 SL: <b>{sl:.4f}</b>\n"
        f"🥇 TP1: <b>{tp1:.4f}</b>\n"
        f"🥈 TP2: <b>{tp2:.4f}</b>\n\n"
        
        f"✅ <b>پوزیشن تایید شد!</b>\n"
        f"📍 میتوانید وارد شوید.\n\n"
        
        f"📌 <b>Partial TP:</b>\n"
        f"├ 🥇 TP1: 60% کلوز → SL به Breakeven\n"
        f"└ 🥈 TP2: 40% باقیمانده\n\n"
        
        f"⚠️ <i>مدیریت سرمایه را رعایت کنید</i>\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )
    return caption


def build_cancellation_caption(sig_data: dict, signal_id: str) -> str:
    """کپشن سیگنال باطل شده"""
    dir_emoji = "🟢" if sig_data["direction"] == "LONG" else "🔴"
    strategy_fa = sig_data.get("strategy_fa", sig_data.get("source", ""))
    
    caption = (
        f"❌ <b>Signal Cancelled!</b> ❌\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{signal_id}</code>\n"
        f"🪙 <b>{sig_data['symbol']}</b> | {sig_data['direction']} {dir_emoji}\n"
        f"🔮 استراتژی: <b>{strategy_fa}</b>\n\n"
        f"⚠️ قیمت در جهت مخالف حرکت کرد.\n"
        f"❌ این سیگنال باطل شد - وارد نشوید!\n\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )
    return caption


def build_tp1_hit_caption(sig_data: dict, signal_id: str,
                           current_price: float) -> str:
    """کپشن TP1 hit + SL moved to breakeven"""
    dir_emoji = "🟢" if sig_data["direction"] == "LONG" else "🔴"
    strategy_fa = sig_data.get("strategy_fa", sig_data.get("source", ""))
    
    caption = (
        f"🥇 <b>TP1 Hit!</b> 🥇\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{signal_id}</code>\n"
        f"🪙 <b>{sig_data['symbol']}</b> | {sig_data['direction']} {dir_emoji}\n"
        f"🔮 استراتژی: <b>{strategy_fa}</b>\n\n"
        
        f"✅ <b>TP1 رسید!</b>\n"
        f"💰 60% پوزیشن کلوز شد\n\n"
        
        f"🔒 <b>SL به Breakeven منتقل شد!</b>\n"
        f"📍 SL جدید = Entry (نقطه ورود)\n"
        f"🎯 40% باقیمانده برای TP2\n\n"
        
        f"📢 <b>{CHANNEL_NAME}</b>"
    )
    return caption


def send_signal_with_chart(sig: dict, df_15m: pd.DataFrame):
    signal_id = sig.get("signal_id")
    if not signal_id:
        from database.db import generate_signal_id
        signal_id = generate_signal_id(sig["symbol"], sig["source"])
        sig["signal_id"] = signal_id

    if not sig.get("strategy_fa"):
        strategy_names = {
            "SMC": "اسمارت مانی", "RTM": "RTM", "ICT": "ICT",
            "QM": "کوآزیمودو", "ENGULFING": "کندل پوششی",
            "PINBAR": "پین بار", "FVG": "شکاف قیمتی",
            "IFVG": "معکوس شکاف", "FLIPZONE": "فیلیپ زون",
            "BREAKOUT": "شکست سطح", "ORDERBLOCK": "اوردر بلاک",
            "CHOCH": "تغییر ساختار", "RETURN_AREA": "بازگشت به ناحیه"
        }
        sig["strategy_fa"] = strategy_names.get(sig["source"], sig["source"])

    target = CHAT_ID_SIGNALS if CHAT_ID_SIGNALS else CHAT_ID_ADMIN
    caption = build_initial_caption(sig, signal_id)
    
    dir_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"
    short_caption = (
        f"🔔 {sig['symbol']} | {sig.get('strategy_fa', sig['source'])} "
        f"| {sig['direction']} {dir_emoji}\n"
        f"🎯 Entry {sig['entry']:.4f}  🛑 SL {sig['sl']:.4f}\n"
        f"🆔 <code>{signal_id}</code>\n"
        f"📢 {CHANNEL_NAME}"
    )

    try:
        chart_bytes = None
        if df_15m is not None:
            chart_bytes = generate_chart(df_15m, sig)

        if chart_bytes:
            photo_ok = send_photo(chart_bytes, short_caption, chat_id=target)
            send_message(caption, chat_id=target)
            if not photo_ok:
                print(f"Chart send failed for {signal_id}")
        else:
            send_message(caption, chat_id=target)

    except Exception as e:
        print(f"Send signal error: {e}")
        try:
            send_message(caption, chat_id=target)
        except Exception:
            pass


def send_approaching_alert(sig_data: dict, signal_id: str,
                           current_price: float):
    """ارسال هشدار نزدیک شدن به Entry"""
    entry = sig_data["entry"]
    distance_pct = abs(current_price - entry) / entry * 100
    
    target = CHAT_ID_SIGNALS if CHAT_ID_SIGNALS else CHAT_ID_ADMIN
    caption = build_approaching_caption(
        sig_data, signal_id, current_price, distance_pct
    )
    send_message(caption, chat_id=target)


def send_approaching_alert_to_channel(sig_data: dict, signal_id: str,
                                       current_price: float):
    """ارسال هشدار نزدیک شدن به کانال اختصاصی هشدار"""
    entry = sig_data["entry"]
    distance_pct = abs(current_price - entry) / entry * 100
    
    # ارسال به کانال هشدار اگه تنظیم شده
    target = CHAT_ID_APPROACHING if CHAT_ID_APPROACHING else (CHAT_ID_SIGNALS if CHAT_ID_SIGNALS else CHAT_ID_ADMIN)
    caption = build_approaching_caption(
        sig_data, signal_id, current_price, distance_pct
    )
    send_message(caption, chat_id=target)


def send_confirmation_signal(sig_data: dict, signal_id: str,
                              current_price: float):
    """ارسال سیگنال تایید شده"""
    target = CHAT_ID_SIGNALS if CHAT_ID_SIGNALS else CHAT_ID_ADMIN
    caption = build_confirmation_caption(sig_data, signal_id, current_price)
    send_message(caption, chat_id=target)


def send_cancellation_signal(sig_data: dict, signal_id: str):
    """ارسال سیگنال باطل شده"""
    target = CHAT_ID_SIGNALS if CHAT_ID_SIGNALS else CHAT_ID_ADMIN
    caption = build_cancellation_caption(sig_data, signal_id)
    send_message(caption, chat_id=target)


def send_tp1_hit_signal(sig_data: dict, signal_id: str,
                         current_price: float):
    """ارسال اعلان TP1 hit + SL to BE"""
    target = CHAT_ID_SIGNALS if CHAT_ID_SIGNALS else CHAT_ID_ADMIN
    caption = build_tp1_hit_caption(sig_data, signal_id, current_price)
    send_message(caption, chat_id=target)


def send_result_to_channel(symbol: str, signal_id: str,
                            result: str, pnl: float,
                            leverage: int, margin_usd: float):
    target = CHAT_ID_RESULTS if CHAT_ID_RESULTS else CHAT_ID_ADMIN

    profit_usd = margin_usd * leverage * (abs(pnl) / 100)
    result_emoji = "✅" if result == "WIN" else "❌"
    sign = "+" if result == "WIN" else "-"

    msg = (
        f"{result_emoji} <b>Signal Result</b>\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Code: <code>{signal_id}</code>\n"
        f"🪙 Symbol: <b>{symbol}</b>\n"
        f"📊 Result: <b>{'WIN' if result == 'WIN' else 'LOSS'}</b> {result_emoji}\n"
        f"⚡ Leverage: <b>{leverage}x</b>\n"
        f"💰 P&L: <b>{sign}${abs(profit_usd):.2f}</b>\n"
        f"📈 Return: <b>{sign}{abs(pnl):.2f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>بر اساس مدیریت سرمایه پیشنهادی محاسبه شده</i>\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )
    send_message(msg, chat_id=target)


def send_performance_report(stats: dict):
    target = CHAT_ID_RESULTS if CHAT_ID_RESULTS else CHAT_ID_ADMIN

    if not stats:
        send_message(
            f"📊 <b>Daily Report</b>\n"
            f"📢 کانال: <b>{CHANNEL_NAME}</b>\n\n"
            "هنوز سیگنال بسته‌ای نداریم.",
            chat_id=target
        )
        return

    tw = sum(s["wins"] for s in stats.values())
    tl = sum(s["losses"] for s in stats.values())
    total = tw + tl
    wr = (tw / total * 100) if total > 0 else 0

    lines = [
        f"📊 <b>Daily Winrate Report</b>",
        f"📢 کانال: <b>{CHANNEL_NAME}</b>",
        "━━━━━━━━━━━━━━━━━━\n"
    ]

    source_emojis = {
        "SMC": "📊", "RTM": "🔷", "ICT": "💎",
        "QM": "🔮", "ENGULFING": "🔥", "PINBAR": "📌",
        "FVG": "📐", "IFVG": "🔄", "FLIPZONE": "🔁",
        "BREAKOUT": "💥", "ORDERBLOCK": "🧱",
        "CHOCH": "⚡", "RETURN_AREA": "🎯"
    }

    for source, data in stats.items():
        e = source_emojis.get(source, "📌")
        lines.append(
            f"{e} <b>{source}</b>\n"
            f"├ ✅ Win: {data['wins']}\n"
            f"├ ❌ Loss: {data['losses']}\n"
            f"├ 📈 Winrate: <b>{data['winrate']:.1f}%</b>\n"
            f"└ 💰 Avg PnL: {data['avg_pnl']:.2f}%\n"
        )

    lines.append(
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Total Signals: {total}\n"
        f"🎯 Overall Winrate: <b>{wr:.1f}%</b>\n\n"
        f"⚠️ <i>نتایج بر اساس مدیریت سرمایه پیشنهادی</i>\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )

    send_message("\n".join(lines), chat_id=target)
