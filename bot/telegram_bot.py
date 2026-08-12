# bot/telegram_bot.py - Professional Signal Bot v4
import requests
import io
import os
import pandas as pd
import mplfinance as mpf
import matplotlib
matplotlib.use('Agg')

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID_SIGNALS = os.environ.get("CHAT_ID_SIGNALS", "")
CHAT_ID_RESULTS = os.environ.get("CHAT_ID_RESULTS", "")
CHAT_ID_ADMIN = os.environ.get("CHAT_ID", "")

ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", "1000"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.5"))

_signal_counter = [100]


def generate_signal_id() -> str:
    _signal_counter[0] += 1
    return f"VIVA{_signal_counter[0]:04d}"


def send_message(text: str, chat_id: str = None):
    if not chat_id:
        chat_id = CHAT_ID_ADMIN
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"Message error: {e}")


def send_photo(image_bytes: bytes, caption: str, chat_id: str = None):
    if not chat_id:
        chat_id = CHAT_ID_ADMIN
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    try:
        requests.post(url,
            data={
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML"
            },
            files={"photo": ("chart.png", image_bytes, "image/png")},
            timeout=30
        )
    except Exception as e:
        print(f"Photo error: {e}")


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

        score = calculate_score(sig)["score"]

        hlines = [
            sig["entry"],
            sig["sl"],
            sig["trade_params"]["tp1"],
            sig["trade_params"]["tp2"]
        ]
        colors = ['#ffffff', '#ff4444', '#00ff88', '#00aa55']

        buf = io.BytesIO()
        mpf.plot(
            chart_df,
            type='candle',
            style=style,
            title=(
                f"\n{sig['symbol']} | {sig['source']} "
                f"| {sig['direction']} | Score: {score}/10"
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


def calculate_score(sig: dict) -> dict:
    score = 0
    details = []
    confirmations = sig.get("confirmations", [])
    source = sig["source"]

    has_sweep = any("Sweep" in c and "✅" in c for c in confirmations)
    has_choch = any("CHoCH" in c and "✅" in c for c in confirmations)
    is_new = any("جدید" in c for c in confirmations)

    # ساختار HTF
    if sig.get("bias") in ["BULLISH", "BEARISH"]:
        score += 2
        details.append("✅ +2 ساختار HTF مشخص")
    else:
        details.append("❌ +0 ساختار HTF نامشخص")

    # OB / Base / OTE
    if source == "SMC" and sig.get("ob_zone"):
        score += 2
        details.append("✅ +2 قیمت داخل Order Block")
    elif source == "RTM" and sig.get("base_zone"):
        score += 2
        details.append("✅ +2 قیمت در ناحیه Base")
    elif source == "ICT" and sig.get("ote_zone"):
        score += 2
        details.append("✅ +2 قیمت در OTE Zone")

    # Liquidity Sweep
    if has_sweep:
        score += 2
        details.append("✅ +2 Liquidity Sweep تایید")
    else:
        details.append("⚠️ +0 Sweep هنوز نشده")

    # CHoCH / MSS
    if has_choch or sig.get("mss"):
        score += 2
        details.append("✅ +2 CHoCH/MSS تایید")
    else:
        details.append("⚠️ +0 CHoCH هنوز تایید نشده")

    # بونوس‌ها
    if is_new:
        score += 1
        details.append("🆕 +1 تغییر جدید در بازار")

    if source == "ICT" and sig.get("in_killzone"):
        score += 1
        details.append("⏰ +1 در Killzone هستیم")

    if source == "SMC":
        try:
            s = float(str(sig.get("ob_strength", "1")).replace("x", ""))
            if s >= 3:
                score += 1
                details.append("💪 +1 OB بسیار قوی")
        except:
            pass

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

    return {
        "score": score,
        "label": label,
        "bar": bar,
        "details": details
    }


def calculate_money_management(sig: dict, score: int) -> dict:
    leverage_map = {
        10: 20, 9: 20, 8: 15,
        7: 12, 6: 10, 5: 8,
        4: 6, 3: 5, 2: 5, 1: 5
    }
    leverage = leverage_map.get(score, 5)

    risk_amount = ACCOUNT_SIZE * (RISK_PERCENT / 100)

    entry = sig["entry"]
    sl = sig["sl"]
    sl_distance = abs(entry - sl)
    sl_pct = (sl_distance / entry) * 100
    if sl_pct == 0:
        sl_pct = 1.0

    position_size_usd = risk_amount / (sl_pct / 100)
    margin_required = position_size_usd / leverage
    margin_pct = (margin_required / ACCOUNT_SIZE) * 100

    tp1 = sig["trade_params"]["tp1"]
    tp2 = sig["trade_params"]["tp2"]

    if sig["direction"] == "LONG":
        tp1_pct = ((tp1 - entry) / entry) * 100
        tp2_pct = ((tp2 - entry) / entry) * 100
    else:
        tp1_pct = ((entry - tp1) / entry) * 100
        tp2_pct = ((entry - tp2) / entry) * 100

    tp1_profit = risk_amount * 2
    tp2_profit = risk_amount * 3

    return {
        "leverage": leverage,
        "margin_required": round(margin_required, 2),
        "margin_pct": round(margin_pct, 1),
        "position_size_usd": round(position_size_usd, 0),
        "risk_amount": round(risk_amount, 2),
        "risk_pct": RISK_PERCENT,
        "sl_pct": round(sl_pct, 2),
        "tp1_pct": round(tp1_pct, 2),
        "tp2_pct": round(tp2_pct, 2),
        "tp1_profit": round(tp1_profit, 2),
        "tp2_profit": round(tp2_profit, 2),
    }


def build_signal_reason(sig: dict, signal_id: str) -> str:
    source = sig["source"]
    direction = sig["direction"]
    bias = sig.get("bias", "")
    bias_fa = "📈 صعودی" if bias == "BULLISH" else "📉 نزولی"
    dir_fa = "LONG 🟢" if direction == "LONG" else "SHORT 🔴"
    confirmations = sig.get("confirmations", [])

    if source == "SMC":
        has_sweep = any("Sweep" in c and "✅" in c for c in confirmations)
        has_choch = any("CHoCH" in c and "✅" in c for c in confirmations)
        ob_zone = sig.get("ob_zone", "")
        ob_strength = sig.get("ob_strength", "")

        reason = (
            f"📋 <b>دلیل صدور سیگنال:</b>\n"
            f"استراتژی <b>SMC</b> شناسایی کرد:\n\n"
            f"۱. ساختار ۴ ساعته <b>{bias_fa}</b> (HH/HL)\n"
            f"۲. قیمت وارد <b>Order Block</b> قدرت {ob_strength} شد\n"
            f"   📌 محدوده: <code>{ob_zone}</code>\n"
            f"۳. {'✅ Liquidity Sweep تایید شد' if has_sweep else '⚠️ انتظار Sweep'}\n"
            f"۴. {'✅ CHoCH در ۱۵m تایید شد' if has_choch else '⚠️ انتظار CHoCH'}\n\n"
            f"🔑 <b>شرط ورود:</b>\n"
            f"• کندل تاییدیه {dir_fa} در OB\n"
            f"• بسته شدن "
            f"{'بالای' if direction == 'LONG' else 'زیر'} سطح CHoCH\n"
            f"• حجم بالاتر از میانگین\n"
        )

    elif source == "RTM":
        pattern = sig.get("pattern", "")
        base_zone = sig.get("base_zone", "")
        strength = sig.get("strength", "")
        patterns_fa = {
            "RBR": ("Rally-Base-Rally", "ادامه صعود"),
            "DBD": ("Drop-Base-Drop", "ادامه نزول"),
            "RBD": ("Rally-Base-Drop", "برگشت نزولی"),
            "DBR": ("Drop-Base-Rally", "برگشت صعودی"),
        }
        p_en, p_fa = patterns_fa.get(pattern, (pattern, "ستاپ ترکیبی"))

        reason = (
            f"📋 <b>دلیل صدور سیگنال:</b>\n"
            f"استراتژی <b>RTM</b> شناسایی کرد:\n\n"
            f"۱. الگوی <b>{p_en}</b> ({p_fa})\n"
            f"۲. ساختار کلی {bias_fa}\n"
            f"۳. ناحیه Base: <code>{base_zone}</code>\n"
            f"۴. قدرت ستاپ: <b>{strength}</b>\n"
            f"۵. ✅ ناحیه هنوز <b>Fresh</b> است\n\n"
            f"🔑 <b>شرط ورود:</b>\n"
            f"• برگشت قیمت به Base\n"
            f"• کندل تاییدیه {dir_fa}\n"
            f"• ترجیحاً در Killzone لندن/نیویورک\n"
        )

    elif source == "ICT":
        ote_zone = sig.get("ote_zone", "")
        killzone = sig.get("killzone", "None")
        mss = sig.get("mss", False)
        pdh = sig.get("pdh")
        pdl = sig.get("pdl")

        reason = (
            f"📋 <b>دلیل صدور سیگنال:</b>\n"
            f"استراتژی <b>ICT</b> شناسایی کرد:\n\n"
            f"۱. ساختار {bias_fa}\n"
            f"۲. قیمت در <b>OTE</b> (فیبو ۶۲٪-۷۹٪)\n"
            f"   📌 محدوده: <code>{ote_zone}</code>\n"
            f"۳. {'✅ Killzone: ' + killzone if killzone != 'None' else '⚠️ خارج Killzone'}\n"
            f"۴. {'✅ MSS تایید شد' if mss else '⚠️ انتظار MSS'}\n"
        )
        if pdh and pdl:
            reason += (
                f"۵. PDH: <code>{pdh:.4f}</code> | "
                f"PDL: <code>{pdl:.4f}</code>\n"
            )
        reason += (
            f"\n🔑 <b>شرط ورود:</b>\n"
            f"• تایید MSS در ۵ یا ۱۵ دقیقه\n"
            f"• ورود در Killzone\n"
            f"• هدف: PDH یا PDL روز قبل\n"
        )
    else:
        reason = "📋 تحلیل ترکیبی چند استراتژی."

    return reason


def build_full_caption(sig: dict, signal_id: str) -> str:
    score_data = calculate_score(sig)
    score = score_data["score"]
    mm = calculate_money_management(sig, score)
    reason = build_signal_reason(sig, signal_id)

    source_emoji = {
        "SMC": "📊", "RTM": "🔷", "ICT": "💎"
    }.get(sig["source"], "📌")
    dir_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"

    details_text = "\n".join(
        f"   {d}" for d in score_data["details"]
    )

    caption = (
        f"✨ <b>سیگنال جدید</b> ✨\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{source_emoji} <b>{sig['source']}</b>  •  "
        f"<code>{signal_id}</code>  {dir_emoji}\n"
        f"🪙 <b>{sig['symbol']}</b>  |  "
        f"{'LONG 🟢' if sig['direction']=='LONG' else 'SHORT 🔴'}\n"
        f"📈 روند: <b>"
        f"{'صعودی' if sig.get('bias')=='BULLISH' else 'نزولی'}</b>\n\n"

        f"⭐ <b>امتیاز:</b> {score_data['bar']} {score}/10\n"
        f"🏷 {score_data['label']}\n"
        f"{details_text}\n\n"

        f"━━━━━━━━━━━━━━━━━━\n"
        f"{reason}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"

        f"💼 <b>مدیریت سرمایه</b>\n"
        f"├ 💰 سرمایه: ${ACCOUNT_SIZE:,.0f}\n"
        f"├ ⚡ لوریج پیشنهادی: <b>{mm['leverage']}x</b>\n"
        f"├ 📊 مارجین: <b>{mm['margin_pct']}%</b> "
        f"= ${mm['margin_required']}\n"
        f"├ ⚠️ ریسک: <b>{mm['risk_pct']}%</b> "
        f"= ${mm['risk_amount']}\n"
        f"└ 📦 حجم پوزیشن: ~${mm['position_size_usd']:,.0f}\n\n"

        f"📌 <b>نقاط معاملاتی</b>\n"
        f"├ 📍 ورود:   <b>{sig['entry']:.4f}</b>\n"
        f"├ 🛑 استاپ:  {sig['sl']:.4f}  "
        f"(-{mm['sl_pct']}%)\n"
        f"├ 🥇 هدف ۱: {sig['trade_params']['tp1']:.4f}  "
        f"(+{mm['tp1_pct']}%)\n"
        f"└ 🥈 هدف ۲: {sig['trade_params']['tp2']:.4f}  "
        f"(+{mm['tp2_pct']}%)\n\n"

        f"💹 <b>سود/زیان احتمالی</b>\n"
        f"├ ✅ سود هدف ۱: +${mm['tp1_profit']}\n"
        f"├ ✅ سود هدف ۲: +${mm['tp2_profit']}\n"
        f"└ ❌ زیان: -${mm['risk_amount']}\n\n"

        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>همیشه چارت را خودتان بررسی کنید!</i>\n"
        f"🆔 <code>{signal_id}</code>"
    )

    return caption


def send_signal_with_chart(sig: dict, df_15m: pd.DataFrame):
    signal_id = generate_signal_id()
    sig["signal_id"] = signal_id

    target = CHAT_ID_SIGNALS if CHAT_ID_SIGNALS else CHAT_ID_ADMIN
    caption = build_full_caption(sig, signal_id)

    try:
        chart_bytes = None
        if df_15m is not None:
            chart_bytes = generate_chart(df_15m, sig)

        if chart_bytes:
            send_photo(chart_bytes, caption, chat_id=target)
        else:
            send_message(caption, chat_id=target)

    except Exception as e:
        print(f"Send signal error: {e}")
        try:
            send_message(caption, chat_id=target)
        except:
            pass


def send_result_to_channel(symbol: str, signal_id: str,
                            result: str, pnl: float,
                            leverage: int, risk_amount: float):
    target = CHAT_ID_RESULTS if CHAT_ID_RESULTS else CHAT_ID_ADMIN

    profit_usd = abs(risk_amount * (pnl / 1.5))
    result_emoji = "✅" if result == "WIN" else "❌"
    result_fa = "برد" if result == "WIN" else "باخت"
    sign = "+" if result == "WIN" else "-"

    msg = (
        f"{result_emoji} <b>نتیجه سیگنال</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 کد: <code>{signal_id}</code>\n"
        f"🪙 {symbol}\n"
        f"📊 نتیجه: <b>{result_fa}</b> {result_emoji}\n"
        f"⚡ لوریج: {leverage}x\n"
        f"💰 سود/زیان: <b>{sign}${abs(profit_usd):.2f}</b>\n"
        f"📈 PnL: <b>{sign}{abs(pnl):.2f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>بر اساس مدیریت سرمایه پیشنهادی</i>"
    )
    send_message(msg, chat_id=target)


def send_performance_report(stats: dict):
    target = CHAT_ID_RESULTS if CHAT_ID_RESULTS else CHAT_ID_ADMIN

    if not stats:
        send_message(
            "📊 <b>گزارش روزانه</b>\n\n"
            "هنوز سیگنال بسته‌ای نداریم.",
            chat_id=target
        )
        return

    tw = sum(s["wins"] for s in stats.values())
    tl = sum(s["losses"] for s in stats.values())
    total = tw + tl
    wr = (tw / total * 100) if total > 0 else 0

    lines = [
        "📊 <b>گزارش روزانه وین‌ریت</b>",
        "━━━━━━━━━━━━━━━━━━\n"
    ]

    for source, data in stats.items():
        e = {"SMC": "📊", "RTM": "🔷", "ICT": "💎"}.get(source, "📌")
        lines.append(
            f"{e} <b>{source}</b>\n"
            f"├ ✅ برد: {data['wins']}\n"
            f"├ ❌ باخت: {data['losses']}\n"
            f"├ 📈 وین‌ریت: <b>{data['winrate']:.1f}%</b>\n"
            f"└ 💰 میانگین PnL: {data['avg_pnl']:.2f}%\n"
        )

    lines.append(
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏆 مجموع: {total} سیگنال\n"
        f"🎯 وین‌ریت کل: <b>{wr:.1f}%</b>"
    )

    send_message("\n".join(lines), chat_id=target)
