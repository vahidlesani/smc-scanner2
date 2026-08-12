# bot/telegram_bot.py - Professional Signal Bot v5
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
        sig_type = detect_signal_type(sig)

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
                f"| {sig['direction']} | Score: {score}/10 | {sig_type}"
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


def detect_signal_type(sig: dict) -> str:
    """
    تشخیص نوع سیگنال: Swing یا Scalp
    بر اساس فاصله SL
    """
    entry = sig["entry"]
    sl = sig["sl"]
    sl_pct = abs(entry - sl) / entry * 100

    if sl_pct >= 1.5:
        return "📊 Swing"
    else:
        return "⚡ Scalp"


def calculate_score(sig: dict) -> dict:
    score = 0
    details = []
    confirmations = sig.get("confirmations", [])
    source = sig["source"]

    has_sweep = any("Sweep" in c and "✅" in c for c in confirmations)
    has_choch = any("CHoCH" in c and "✅" in c for c in confirmations)
    is_new = any("جدید" in c for c in confirmations)

    if sig.get("bias") in ["BULLISH", "BEARISH"]:
        score += 2
        details.append("✅ +2 ساختار HTF مشخص")
    else:
        details.append("❌ +0 ساختار HTF نامشخص")

    if source == "SMC" and sig.get("ob_zone"):
        score += 2
        details.append("✅ +2 قیمت داخل Order Block")
    elif source == "RTM" and sig.get("base_zone"):
        score += 2
        details.append("✅ +2 قیمت در ناحیه Base")
    elif source == "ICT" and sig.get("ote_zone"):
        score += 2
        details.append("✅ +2 قیمت در OTE Zone")

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
    """
    مدیریت سرمایه اصلاح شده:
    - حداکثر مارجین ۵٪ برای بهترین سیگنال
    - حداقل مارجین ۱٪ برای ضعیف‌ترین
    - لوریج متناسب با کیفیت
    """
    # لوریج بر اساس امتیاز
    leverage_map = {
        10: 20, 9: 20, 8: 15,
        7: 12, 6: 10, 5: 8,
        4: 6, 3: 5, 2: 5, 1: 5
    }
    leverage = leverage_map.get(score, 5)

    # درصد مارجین بر اساس امتیاز (حداکثر ۵٪)
    margin_pct_map = {
        10: 5.0, 9: 5.0, 8: 4.0,
        7: 3.5, 6: 3.0, 5: 2.5,
        4: 2.0, 3: 1.5, 2: 1.0, 1: 1.0
    }
    margin_pct = margin_pct_map.get(score, 1.0)

    # مارجین واقعی
    margin_usd = ACCOUNT_SIZE * (margin_pct / 100)

    # حجم پوزیشن
    position_size_usd = margin_usd * leverage

    # ریسک واقعی بر اساس SL
    entry = sig["entry"]
    sl = sig["sl"]
    sl_distance = abs(entry - sl)
    sl_pct = (sl_distance / entry) * 100
    if sl_pct == 0:
        sl_pct = 1.0

    # ریسک واقعی
    risk_amount = position_size_usd * (sl_pct / 100)
    risk_pct_of_account = (risk_amount / ACCOUNT_SIZE) * 100

    tp1 = sig["trade_params"]["tp1"]
    tp2 = sig["trade_params"]["tp2"]

    if sig["direction"] == "LONG":
        tp1_pct = ((tp1 - entry) / entry) * 100
        tp2_pct = ((tp2 - entry) / entry) * 100
    else:
        tp1_pct = ((entry - tp1) / entry) * 100
        tp2_pct = ((entry - tp2) / entry) * 100

    # سود واقعی
    tp1_profit = position_size_usd * (tp1_pct / 100)
    tp2_profit = position_size_usd * (tp2_pct / 100)

    # نقطه Mart: جایی که ستاپ باطل میشه
    # معمولاً ۵٪ فراتر از SL
    if sig["direction"] == "LONG":
        mart_point = sl * 0.995
    else:
        mart_point = sl * 1.005

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
        "mart_point": round(mart_point, 4),
    }


def build_signal_reason(sig: dict) -> str:
    """
    توضیح کامل فارسی - بدون اصطلاحات انگلیسی در متن
    """
    source = sig["source"]
    direction = sig["direction"]
    bias = sig.get("bias", "")
    confirmations = sig.get("confirmations", [])

    bias_fa = "صعودی" if bias == "BULLISH" else "نزولی"
    dir_fa = "خرید" if direction == "LONG" else "فروش"
    opp_fa = "حمایت" if direction == "LONG" else "مقاومت"

    if source == "SMC":
        has_sweep = any(
            "Sweep" in c and "✅" in c for c in confirmations)
        has_choch = any(
            "CHoCH" in c and "✅" in c for c in confirmations)
        ob_zone = sig.get("ob_zone", "")
        ob_strength = sig.get("ob_strength", "")

        reason = (
            f"📋 <b>دلیل صدور سیگنال:</b>\n\n"
            f"ساختار بازار در تایم‌فریم چهار ساعته {bias_fa} "
            f"تشخیص داده شد. قیمت به ناحیه سفارشات بزرگ "
            f"با قدرت {ob_strength} رسیده است.\n"
            f"محدوده ناحیه: <code>{ob_zone}</code>\n\n"
        )

        if has_sweep:
            reason += (
                f"نقدینگی بازار قبل از این ناحیه جمع‌آوری و "
                f"جذب شده است که نشانه آمادگی بازار برای "
                f"حرکت {bias_fa} است.\n\n"
            )
        else:
            reason += (
                f"نقدینگی بازار هنوز جمع‌آوری نشده. "
                f"بهتر است صبر کنید تا این مرحله تکمیل شود.\n\n"
            )

        if has_choch:
            reason += (
                f"در تایم‌فریم پانزده دقیقه، ساختار بازار "
                f"تغییر کرده و جهت {dir_fa} تایید شده است.\n\n"
            )
        else:
            reason += (
                f"تغییر ساختار در تایم‌فریم کوچک هنوز "
                f"تایید نشده است. این شرط مهم را دنبال کنید.\n\n"
            )

        reason += (
            f"🔑 <b>شرط ورود به پوزیشن:</b>\n"
            f"• مشاهده کندل تاییدیه {dir_fa} در ناحیه\n"
            f"• بسته شدن کندل {'بالای' if direction=='LONG' else 'زیر'} "
            f"سطح تغییر ساختار\n"
            f"• افزایش حجم معاملات\n"
        )

    elif source == "RTM":
        pattern = sig.get("pattern", "")
        base_zone = sig.get("base_zone", "")
        strength = sig.get("strength", "")

        patterns_fa = {
            "RBR": "حرکت صعودی، تجمیع، ادامه صعود",
            "DBD": "حرکت نزولی، تجمیع، ادامه نزول",
            "RBD": "حرکت صعودی، تجمیع، برگشت نزولی",
            "DBR": "حرکت نزولی، تجمیع، برگشت صعودی",
        }
        p_fa = patterns_fa.get(pattern, "الگوی ترکیبی")

        reason = (
            f"📋 <b>دلیل صدور سیگنال:</b>\n\n"
            f"الگوی {pattern} شناسایی شد. این الگو نشان‌دهنده "
            f"{p_fa} است.\n\n"
            f"بازار یک حرکت قوی داشته، سپس وارد فاز تجمیع "
            f"و آرامش شده. این ناحیه تجمیع هنوز تست نشده و "
            f"تازه است. قدرت الگو: {strength}\n"
            f"محدوده ناحیه: <code>{base_zone}</code>\n\n"
            f"ساختار کلی بازار {bias_fa} است و این الگو "
            f"در هم‌راستا با روند اصلی قرار دارد.\n\n"
            f"🔑 <b>شرط ورود به پوزیشن:</b>\n"
            f"• برگشت قیمت به ناحیه تجمیع\n"
            f"• مشاهده کندل تاییدیه {dir_fa}\n"
            f"• ترجیحاً در ساعات لندن یا نیویورک\n"
        )

    elif source == "ICT":
        ote_zone = sig.get("ote_zone", "")
        killzone = sig.get("killzone", "None")
        mss = sig.get("mss", False)
        pdh = sig.get("pdh")
        pdl = sig.get("pdl")

        kz_fa = {
            "London": "لندن (۱۰:۳۰ تا ۱۳:۳۰)",
            "NewYork": "نیویورک (۱۶:۳۰ تا ۱۹:۳۰)",
            "Asian": "آسیا (۳:۳۰ تا ۶:۳۰)",
        }.get(killzone, killzone)

        reason = (
            f"📋 <b>دلیل صدور سیگنال:</b>\n\n"
            f"قیمت وارد ناحیه بهینه ورود بر اساس فیبوناچی "
            f"شصت و دو تا هفتاد و نه درصد شده است.\n"
            f"محدوده ناحیه: <code>{ote_zone}</code>\n\n"
        )

        if killzone != "None":
            reason += (
                f"الان در ساعت طلایی {kz_fa} هستیم که "
                f"بهترین زمان برای ورود به معامله است.\n\n"
            )
        else:
            reason += (
                f"در حال حاضر خارج از ساعات طلایی هستیم. "
                f"با احتیاط بیشتری عمل کنید.\n\n"
            )

        if mss:
            reason += (
                f"ساختار بازار در تایم‌فریم کوچک تغییر کرده "
                f"و جهت {dir_fa} تایید شده است.\n\n"
            )
        else:
            reason += (
                f"تغییر ساختار در تایم‌فریم کوچک هنوز "
                f"تایید نشده. صبر کنید.\n\n"
            )

        if pdh and pdl:
            reason += (
                f"سطوح مهم روز قبل:\n"
                f"بالاترین: <code>{pdh:.4f}</code>  |  "
                f"پایین‌ترین: <code>{pdl:.4f}</code>\n\n"
            )

        reason += (
            f"🔑 <b>شرط ورود به پوزیشن:</b>\n"
            f"• تایید تغییر ساختار در تایم پانزده دقیقه\n"
            f"• ورود در ساعت طلایی\n"
            f"• هدف: سطوح مهم روز قبل\n"
        )

    else:
        reason = "📋 <b>دلیل:</b> تحلیل ترکیبی چند روش."

    return reason


def build_full_caption(sig: dict, signal_id: str) -> str:
    score_data = calculate_score(sig)
    score = score_data["score"]
    mm = calculate_money_management(sig, score)
    reason = build_signal_reason(sig)
    sig_type = detect_signal_type(sig)

    source_emoji = {
        "SMC": "📊", "RTM": "🔷", "ICT": "💎"
    }.get(sig["source"], "📌")
    dir_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"

    details_text = "\n".join(
        f"   {d}" for d in score_data["details"]
    )

    caption = (
        f"✨ <b>New Signal</b> ✨\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{source_emoji} <b>{sig['source']}</b>  •  "
        f"<code>{signal_id}</code>  {dir_emoji}\n"
        f"🪙 <b>{sig['symbol']}</b>  |  "
        f"<b>{sig['direction']}</b> {dir_emoji}\n"
        f"📈 Trend: <b>"
        f"{'Bullish 🟢' if sig.get('bias')=='BULLISH' else 'Bearish 🔴'}"
        f"</b>  |  {sig_type}\n\n"

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
        f"├ 📊 Margin: <b>{mm['margin_pct']}%</b> "
        f"= ${mm['margin_usd']}\n"
        f"├ ⚠️ Real Risk: <b>{mm['risk_pct']}%</b> "
        f"= ${mm['risk_amount']}\n"
        f"└ 📦 Position Size: ~${mm['position_size_usd']:,.0f}\n\n"

        f"📌 <b>Trade Levels</b>\n"
        f"├ 📍 Entry:   <b>{sig['entry']:.4f}</b>\n"
        f"├ 🛑 SL:      {sig['sl']:.4f}  "
        f"(-{mm['sl_pct']}%)\n"
        f"├ ⛔ Mart:    {mm['mart_point']:.4f}\n"
        f"├ 🥇 TP1:     {sig['trade_params']['tp1']:.4f}  "
        f"(+{mm['tp1_pct']}%)\n"
        f"└ 🥈 TP2:     {sig['trade_params']['tp2']:.4f}  "
        f"(+{mm['tp2_pct']}%)\n\n"

        f"💹 <b>Potential P&L</b>\n"
        f"├ ✅ Profit TP1: +${mm['tp1_profit']}\n"
        f"├ ✅ Profit TP2: +${mm['tp2_profit']}\n"
        f"└ ❌ Max Loss:   -${mm['risk_amount']}\n\n"

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
                            leverage: int, margin_usd: float):
    target = CHAT_ID_RESULTS if CHAT_ID_RESULTS else CHAT_ID_ADMIN

    profit_usd = margin_usd * leverage * (abs(pnl) / 100)
    result_emoji = "✅" if result == "WIN" else "❌"
    sign = "+" if result == "WIN" else "-"

    msg = (
        f"{result_emoji} <b>Signal Result</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Code: <code>{signal_id}</code>\n"
        f"🪙 Symbol: <b>{symbol}</b>\n"
        f"📊 Result: <b>{'WIN' if result=='WIN' else 'LOSS'}</b> "
        f"{result_emoji}\n"
        f"⚡ Leverage: <b>{leverage}x</b>\n"
        f"💰 P&L: <b>{sign}${abs(profit_usd):.2f}</b>\n"
        f"📈 Return: <b>{sign}{abs(pnl):.2f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>بر اساس مدیریت سرمایه پیشنهادی محاسبه شده</i>"
    )
    send_message(msg, chat_id=target)


def send_performance_report(stats: dict):
    target = CHAT_ID_RESULTS if CHAT_ID_RESULTS else CHAT_ID_ADMIN

    if not stats:
        send_message(
            "📊 <b>Daily Report</b>\n\n"
            "هنوز سیگنال بسته‌ای نداریم.",
            chat_id=target
        )
        return

    tw = sum(s["wins"] for s in stats.values())
    tl = sum(s["losses"] for s in stats.values())
    total = tw + tl
    wr = (tw / total * 100) if total > 0 else 0

    lines = [
        "📊 <b>Daily Winrate Report</b>",
        "━━━━━━━━━━━━━━━━━━\n"
    ]

    for source, data in stats.items():
        e = {"SMC": "📊", "RTM": "🔷", "ICT": "💎"}.get(source, "📌")
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
        f"⚠️ <i>نتایج بر اساس مدیریت سرمایه پیشنهادی</i>"
    )

    send_message("\n".join(lines), chat_id=target)
