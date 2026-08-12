# bot/telegram_bot.py - Professional Signal Bot v6
# کانال: vivaanalyst-Chanel
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
CHAT_ID_RESULTS = os.environ.get("CHAT_ID_RESULTS", "")
CHAT_ID_ADMIN = os.environ.get("CHAT_ID", "")

ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", "1000"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.5"))

CHANNEL_NAME = "vivaanalyst-Chanel"


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

        score = calculate_score(sig)["score"]
        sig_type = detect_signal_type(sig)

        tp1 = _get_tp(sig, "tp1")
        tp2 = _get_tp(sig, "tp2")

        hlines = [sig["entry"], sig["sl"], tp1, tp2]
        colors = ['#ffffff', '#ff4444', '#00ff88', '#00aa55']

        dir_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"

        buf = io.BytesIO()
        mpf.plot(
            chart_df,
            type='candle',
            style=style,
            title=(
                f"\n{sig['symbol']} | {sig['source']} "
                f"| {sig['direction']} {dir_emoji} "
                f"| Score: {score}/10 | {sig_type}"
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
    """tp1/tp2 رو از هر جایی که باشه میگیره"""
    if sig.get(key) is not None:
        return sig[key]
    return (sig.get("trade_params") or {}).get(key, 0)


def detect_signal_type(sig: dict) -> str:
    entry = sig["entry"]
    sl = sig["sl"]
    sl_pct = abs(entry - sl) / entry * 100
    return "📊 Swing" if sl_pct >= 1.5 else "⚡ Scalp"


def calculate_score(sig: dict) -> dict:
    score = 0
    details = []
    confirmations = sig.get("confirmations", [])
    source = sig["source"]

    has_sweep = any("Sweep" in c and "✅" in c for c in confirmations)
    has_choch = any("CHoCH" in c and "✅" in c for c in confirmations)
    is_new = any("جدید" in c or "جدید" in c for c in confirmations)

    # ساختار HTF
    if sig.get("bias") in ["BULLISH", "BEARISH"]:
        score += 2
        details.append("✅ +2 ساختار HTF مشخص")
    else:
        details.append("❌ +0 ساختار HTF نامشخص")

    # ناحیه مناسب
    source_scores = {
        "SMC": ("ob_zone", "قیمت داخل Order Block"),
        "RTM": ("base_zone", "قیمت در ناحیه Base"),
        "ICT": ("ote_zone", "قیمت در OTE Zone"),
        "QM": ("zone_top", "قیمت در ناحیه QM"),
        "ENGULFING": ("zone_top", "کندل پوششی فعال"),
        "PINBAR": ("zone_top", "پین بار فعال"),
        "FVG": ("zone_top", "قیمت در FVG"),
        "IFVG": ("zone_top", "قیمت در IFVG"),
        "FLIPZONE": ("zone_top", "قیمت در فیلیپ زون"),
        "BREAKOUT": ("zone_top", "شکست سطح تأیید شد"),
        "ORDERBLOCK": ("zone_top", "قیمت در اوردر بلاک"),
        "CHOCH": ("zone_top", "تغییر ساختار تأیید شد"),
        "RETURN_AREA": ("zone_top", "بازگشت به ناحیه"),
    }

    if source in source_scores:
        zone_key, desc = source_scores[source]
        if sig.get(zone_key):
            score += 2
            details.append(f"✅ +2 {desc}")

    # Sweep
    if has_sweep:
        score += 2
        details.append("✅ +2 Liquidity Sweep تایید")
    else:
        details.append("⚠️ +0 Sweep هنوز نشده")

    # CHoCH/MSS
    if has_choch or sig.get("mss"):
        score += 2
        details.append("✅ +2 CHoCH/MSS تایید")
    else:
        details.append("⚠️ +0 CHoCH هنوز تایید نشده")

    # تغییر جدید
    if is_new:
        score += 1
        details.append("🆕 +1 تغییر جدید در بازار")

    # Killzone (فقط ICT)
    if source == "ICT" and sig.get("in_killzone"):
        score += 1
        details.append("⏰ +1 در Killzone هستیم")

    # قدرت OB
    if source == "SMC":
        try:
            s = float(
                str(sig.get("ob_strength", "1")).replace("x", "")
            )
            if s >= 3:
                score += 1
                details.append("💪 +1 OB بسیار قوی")
        except Exception:
            pass

    # امتیاز اضافی استراتژی
    if sig.get("score_bonus"):
        score += sig["score_bonus"]
        details.append(f"⭐ +{sig['score_bonus']} امتیاز استراتژی {source}")

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
    entry = sig["entry"]
    sl = sig["sl"]
    pos = calculate_position(entry, sl, sig["direction"], score, ACCOUNT_SIZE)

    tp1 = _get_tp(sig, "tp1")
    tp2 = _get_tp(sig, "tp2")

    if pos:
        leverage = pos["leverage"]
        margin_usd = pos["margin"]
        margin_pct = pos["margin_pct"]
        position_size_usd = pos["position_size"]
        risk_amount = pos["risk_amount"]
        risk_pct_of_account = pos["risk_pct"]
        sl_pct = pos["sl_pct"]
        if not tp1:
            tp1 = pos["tp1"]
        if not tp2:
            tp2 = pos["tp2"]
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

    tp1_profit = position_size_usd * (tp1_pct / 100)
    tp2_profit = position_size_usd * (tp2_pct / 100)

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


def attach_money_management(sig: dict) -> dict:
    """قبل از ذخیره در DB، اهرم و مارجین واقعی را روی سیگنال می‌گذارد."""
    score = calculate_score(sig)["score"]
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
    source = sig["source"]
    direction = sig["direction"]
    bias = sig.get("bias", "")
    confirmations = sig.get("confirmations", [])

    bias_fa = "صعودی" if bias == "BULLISH" else "نزولی"
    dir_fa = "خرید" if direction == "LONG" else "فروش"

    # اگه استراتژی توضیحات آموزشی داره، از اون استفاده کن
    if sig.get("description"):
        reason = f"📋 <b>دلیل صدور سیگنال:</b>\n\n"
        reason += f"{sig['description']}\n\n"
        
        if sig.get("entry_conditions"):
            reason += f"🔑 <b>شرط ورود به پوزیشن:</b>\n"
            for cond in sig["entry_conditions"]:
                reason += f"• {cond}\n"
        
        return reason

    # توضیحات پیش‌فرض بر اساس source
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
                f"نقدینگی بازار قبل از این ناحیه جمع‌آوری "
                f"و جذب شده است که نشانه آمادگی بازار برای "
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
            f"• بسته شدن کندل "
            f"{'بالای' if direction == 'LONG' else 'زیر'} "
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
        killzone = sig.get("killzone")
        mss = sig.get("mss", False)
        pdh = sig.get("pdh")
        pdl = sig.get("pdl")

        kz_fa = {
            "London": "لندن (۱۰:۳۰ تا ۱۳:۳۰)",
            "NewYork": "نیویورک (۱۶:۳۰ تا ۱۹:۳۰)",
            "Asian": "آسیا (۳:۳۰ تا ۶:۳۰)",
            "LondonClose": "کلوز لندن (۱۸:۳۰ تا ۲۰:۳۰)",
        }.get(killzone, killzone)

        reason = (
            f"📋 <b>دلیل صدور سیگنال:</b>\n\n"
            f"قیمت وارد ناحیه بهینه ورود بر اساس فیبوناچی "
            f"شصت و دو تا هفتاد و نه درصد شده است.\n"
            f"محدوده ناحیه: <code>{ote_zone}</code>\n\n"
        )

        if killzone:
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
        "SMC": "📊", "RTM": "🔷", "ICT": "💎",
        "QM": "🔮", "ENGULFING": "🔥", "PINBAR": "📌",
        "FVG": "📐", "IFVG": "🔄", "FLIPZONE": "🔁",
        "BREAKOUT": "💥", "ORDERBLOCK": "🧱",
        "CHOCH": "⚡", "RETURN_AREA": "🎯"
    }.get(sig["source"], "📌")

    dir_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"

    details_text = "\n".join(
        f"   {d}" for d in score_data["details"]
    )

    tp1 = _get_tp(sig, "tp1")
    tp2 = _get_tp(sig, "tp2")

    # ساخت کپشن با فرمت بهبود یافته
    caption = (
        f"✨ <b>New Signal</b> ✨\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{source_emoji} <b>{sig.get('strategy_fa', sig['source'])}</b>  •  "
        f"<code>{signal_id}</code>  {dir_emoji}\n"
        f"🪙 <b>{sig['symbol']}</b>  |  "
        f"<b>{sig['direction']}</b> {dir_emoji}\n"
        f"📈 Trend: <b>"
        f"{'Bullish 🟢' if sig.get('bias') == 'BULLISH' else 'Bearish 🔴'}"
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
        f"├ 🎯 Entry:   <b>{sig['entry']:.4f}</b>\n"
        f"├ 🛑 SL:      <b>{sig['sl']:.4f}</b>  "
        f"(-{mm['sl_pct']}%)\n"
        f"├ ⛔ Mart:    <b>{mm['mart_point']:.4f}</b>\n"
        f"├ 🥇 TP1:     <b>{tp1:.4f}</b>  "
        f"(+{mm['tp1_pct']}%)\n"
        f"└ 🥈 TP2:     <b>{tp2:.4f}</b>  "
        f"(+{mm['tp2_pct']}%)\n\n"

        f"💹 <b>Potential P&L</b>\n"
        f"├ ✅ Profit TP1: <b>+${mm['tp1_profit']}</b>\n"
        f"├ ✅ Profit TP2: <b>+${mm['tp2_profit']}</b>\n"
        f"└ ❌ Max Loss:   <b>-${mm['risk_amount']}</b>\n\n"

        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>همیشه چارت را خودتان بررسی کنید!</i>\n"
        f"🆔 <code>{signal_id}</code>\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )

    return caption


def build_confirmation_caption(sig: dict, signal_id: str,
                                current_price: float) -> str:
    """کپشن سیگنال تایید شده"""
    dir_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"
    
    caption = (
        f"✅ <b>Signal Confirmed!</b> ✅\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{signal_id}</code>\n"
        f"🪙 <b>{sig['symbol']}</b> | {sig['direction']} {dir_emoji}\n"
        f"🎯 Entry confirmed at <b>{current_price:.4f}</b>\n\n"
        f"✅ پوزیشن تایید شد!\n"
        f"📍 میتوانید وارد شوید.\n\n"
        f"⚠️ <i>مدیریت سرمایه را رعایت کنید</i>\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )
    return caption


def build_cancellation_caption(sig: dict, signal_id: str) -> str:
    """کپشن سیگنال باطل شده"""
    dir_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"
    
    caption = (
        f"❌ <b>Signal Cancelled!</b> ❌\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{signal_id}</code>\n"
        f"🪙 <b>{sig['symbol']}</b> | {sig['direction']} {dir_emoji}\n\n"
        f"⚠️ قیمت در جهت مخالف حرکت کرد.\n"
        f"❌ این سیگنال باطل شد - وارد نشوید!\n\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )
    return caption


def send_signal_with_chart(sig: dict, df_15m: pd.DataFrame):
    # ✅ signal_id رو از sig میگیره، اگه نبود میسازه
    signal_id = sig.get("signal_id")
    if not signal_id:
        from database.db import generate_signal_id
        signal_id = generate_signal_id(sig["symbol"], sig["source"])
        sig["signal_id"] = signal_id

    # اضافه کردن strategy_fa اگه نبود
    if not sig.get("strategy_fa"):
        strategy_names = {
            "SMC": "اسمارت مانی",
            "RTM": "RTM",
            "ICT": "ICT",
            "QM": "کوآزیمودو",
            "ENGULFING": "کندل پوششی",
            "PINBAR": "پین بار",
            "FVG": "شکاف قیمتی",
            "IFVG": "معکوس شکاف",
            "FLIPZONE": "فیلیپ زون",
            "BREAKOUT": "شکست سطح",
            "ORDERBLOCK": "اوردر بلاک",
            "CHOCH": "تغییر ساختار",
            "RETURN_AREA": "بازگشت به ناحیه"
        }
        sig["strategy_fa"] = strategy_names.get(sig["source"], sig["source"])

    target = CHAT_ID_SIGNALS if CHAT_ID_SIGNALS else CHAT_ID_ADMIN
    caption = build_full_caption(sig, signal_id)
    
    # کپشن کوتاه برای عکس
    dir_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"
    short_caption = (
        f"{sig['symbol']} | {sig.get('strategy_fa', sig['source'])} "
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
        f"📊 Result: <b>{'WIN' if result == 'WIN' else 'LOSS'}</b> "
        f"{result_emoji}\n"
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
