# bot/commands.py - Advanced Telegram Bot with Inline Buttons
# دستورات پیشرفته تلگرام با دکمه‌های شیک
import os
import requests
import threading
import time
import json
from datetime import datetime

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID_ADMIN = os.environ.get("CHAT_ID", "")
CHANNEL_NAME = "vivasignalyst-Chanel"


def api_call(method, params=None, files=None):
    """تماس با API تلگرام"""
    if not TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        if files:
            r = requests.post(url, data=params, files=files, timeout=30)
        else:
            r = requests.post(url, json=params, timeout=10)
        if r.ok:
            return r.json()
    except Exception as e:
        print(f"API error {method}: {e}")
    return None


def send_message(text, chat_id, reply_markup=None):
    """ارسال پیام با دکمه"""
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return api_call("sendMessage", params)


def answer_callback(callback_query_id, text=""):
    """پاسخ به callback"""
    return api_call("answerCallbackQuery", {
        "callback_query_id": callback_query_id,
        "text": text,
        "show_alert": False
    })


def edit_message(chat_id, message_id, text, reply_markup=None):
    """ویرایش پیام"""
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return api_call("editMessageText", params)


# ─── دکمه‌های اصلی ───

def main_menu_keyboard():
    """منوی اصلی با دکمه‌ها"""
    return {
        "inline_keyboard": [
            [
                {"text": "📊 آمار کلی", "callback_data": "stats"},
                {"text": "🔮 استراتژی‌ها", "callback_data": "strategies"}
            ],
            [
                {"text": "📋 سیگنال‌های اخیر", "callback_data": "signals"},
                {"text": "🔔 سیگنال‌های فعال", "callback_data": "active"}
            ],
            [
                {"text": "🧪 بک‌تست", "callback_data": "backtest_menu"},
                {"text": "📈 آمار استراتژی", "callback_data": "strategy_stats"}
            ],
            [
                {"text": "⚙️ وضعیت ربات", "callback_data": "status"},
                {"text": "❓ راهنما", "callback_data": "help"}
            ],
            [
                {"text": "🔄 بروزرسانی", "callback_data": "refresh"}
            ]
        ]
    }


def backtest_symbols_keyboard():
    """دکمه‌های انتخاب نماد برای بک‌تست"""
    return {
        "inline_keyboard": [
            [
                {"text": "₿ BTC", "callback_data": "bt_BTCUSDT"},
                {"text": "Ξ ETH", "callback_data": "bt_ETHUSDT"},
                {"text": "◎ SOL", "callback_data": "bt_SOLUSDT"}
            ],
            [
                {"text": "● BNB", "callback_data": "bt_BNBUSDT"},
                {"text": "✕ XRP", "callback_data": "bt_XRPUSDT"},
                {"text": "🐕 DOGE", "callback_data": "bt_DOGEUSDT"}
            ],
            [
                {"text": "🔷 SUI", "callback_data": "bt_SUIUSDT"},
                {"text": "🔴 ARB", "callback_data": "bt_ARBUSDT"},
                {"text": "🔴 OP", "callback_data": "bt_OPUSDT"}
            ],
            [
                {"text": "🔗 LINK", "callback_data": "bt_LINKUSDT"},
                {"text": "🌟 AVAX", "callback_data": "bt_AVAXUSDT"},
                {"text": "💎 ATOM", "callback_data": "bt_ATOMUSDT"}
            ],
            [
                {"text": "🔮 NEAR", "callback_data": "bt_NEARUSDT"},
                {"text": "🔥 INJ", "callback_data": "bt_INJUSDT"},
                {"text": "🎯 APT", "callback_data": "bt_APTUSDT"}
            ],
            [
                {"text": "◀️ بازگشت", "callback_data": "main_menu"}
            ]
        ]
    }


def strategy_list_keyboard():
    """لیست استراتژی‌ها"""
    return {
        "inline_keyboard": [
            [
                {"text": "📊 SMC", "callback_data": "strat_SMC"},
                {"text": "🔷 RTM", "callback_data": "strat_RTM"},
                {"text": "💎 ICT", "callback_data": "strat_ICT"}
            ],
            [
                {"text": "🔮 QM", "callback_data": "strat_QM"},
                {"text": "🔥 Engulfing", "callback_data": "strat_ENGULFING"},
                {"text": "📌 PinBar", "callback_data": "strat_PINBAR"}
            ],
            [
                {"text": "📐 FVG", "callback_data": "strat_FVG"},
                {"text": "🔄 IFVG", "callback_data": "strat_IFVG"},
                {"text": "🔁 FlipZone", "callback_data": "strat_FLIPZONE"}
            ],
            [
                {"text": "💥 Breakout", "callback_data": "strat_BREAKOUT"},
                {"text": "🧱 OB", "callback_data": "strat_ORDERBLOCK"},
                {"text": "⚡ CHoCH", "callback_data": "strat_CHOCH"}
            ],
            [
                {"text": "🎯 Return Area", "callback_data": "strat_RETURN_AREA"}
            ],
            [
                {"text": "📊 همه استراتژی‌ها", "callback_data": "strategies"},
                {"text": "◀️ بازگشت", "callback_data": "main_menu"}
            ]
        ]
    }


# ─── پردازش دستورات ───

def handle_start(chat_id):
    """دستور /start"""
    text = (
        "🤖 <b>به Viva Signal Bot خوش آمدید!</b>\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔮 <b>۱۳ استراتژی پیشرفته</b>\n"
        "📊 SMC | 🔷 RTM | 💎 ICT\n"
        "🔮 QM | 🔥 Engulfing | 📌 PinBar\n"
        "📐 FVG | 🔄 IFVG | 🔁 FlipZone\n"
        "💥 Breakout | 🧱 OB | ⚡ CHoCH\n"
        "🎯 Return to Area\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "از دکمه‌های زیر استفاده کنید:"
    )
    send_message(text, chat_id, main_menu_keyboard())


def handle_stats(chat_id):
    """آمار کلی"""
    from database.db import get_dashboard_summary
    
    try:
        s = get_dashboard_summary()
        
        wr_emoji = "🏆" if s['winrate'] >= 60 else "⭐" if s['winrate'] >= 50 else "⚠️"
        
        text = (
            f"📊 <b>آمار کلی عملکرد</b>\n"
            f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📈 کل سیگنال‌ها: <b>{s['total_signals']}</b>\n"
            f"✅ برد: <b>{s['wins']}</b>\n"
            f"❌ باخت: <b>{s['losses']}</b>\n"
            f"⏳ در انتظار: <b>{s['pending']}</b>\n\n"
            f"{wr_emoji} Win Rate: <b>{s['winrate']}%</b>\n"
            f"💰 میانگین PnL: <b>{s['avg_pnl']}%</b>\n"
            f"🏆 بهترین: <b>{s['best_pnl']}%</b>\n"
            f"📉 بدترین: <b>{s['worst_pnl']}%</b>\n"
            f"⭐ میانگین امتیاز: <b>{s['avg_score']}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>{CHANNEL_NAME}</b>"
        )
        send_message(text, chat_id, main_menu_keyboard())
    except Exception as e:
        send_message(f"❌ خطا: {e}", chat_id)


def handle_strategies(chat_id):
    """آمار استراتژی‌ها"""
    from database.db import get_strategy_performance
    
    try:
        strategies = get_strategy_performance()
        
        if not strategies:
            send_message(
                "📊 هنوز داده‌ای ثبت نشده.\n"
                "ربات در حال اسکن است...",
                chat_id, main_menu_keyboard()
            )
            return
        
        lines = [
            f"🔮 <b>عملکرد استراتژی‌ها</b>",
            f"📢 کانال: <b>{CHANNEL_NAME}</b>",
            "━━━━━━━━━━━━━━━━━━\n"
        ]
        
        for s in strategies:
            emoji = "🏆" if s['winrate'] >= 70 else "⭐" if s['winrate'] >= 55 else "⚠️" if s['winrate'] >= 40 else "❌"
            lines.append(
                f"{emoji} <b>{s['strategy_fa']}</b>\n"
                f"├ 📈 کل: {s['total']} (برد:{s['wins']} باخت:{s['losses']})\n"
                f"├ 🎯 Win Rate: <b>{s['winrate']:.1f}%</b>\n"
                f"├ 💰 Avg PnL: {s['avg_pnl']:+.2f}%\n"
                f"└ ⭐ امتیاز: {s['avg_score']}\n"
            )
        
        lines.extend([
            "━━━━━━━━━━━━━━━━━━",
            f"📢 <b>{CHANNEL_NAME}</b>"
        ])
        send_message("\n".join(lines), chat_id, main_menu_keyboard())
    except Exception as e:
        send_message(f"❌ خطا: {e}", chat_id)


def handle_backtest(chat_id, symbol):
    """بک‌تست"""
    from analysis.backtest import run_full_backtest, generate_backtest_report
    
    try:
        send_message(
            f"🧪 <b>در حال بک‌تست {symbol}...</b>\n"
            "لطفاً ۳۰-۶۰ ثانیه صبر کنید.",
            chat_id
        )
        
        results = run_full_backtest(symbol, days=14)
        report = generate_backtest_report(results)
        
        send_message(report, chat_id, main_menu_keyboard())
    except Exception as e:
        send_message(f"❌ خطا: {e}", chat_id, main_menu_keyboard())


def handle_recent_signals(chat_id):
    """آخرین سیگنال‌ها"""
    from database.db import get_recent_signals
    
    try:
        signals = get_recent_signals(10)
        
        if not signals:
            send_message(
                "📋 هنوز سیگنالی ثبت نشده.\n"
                "ربات در حال اسکن است...",
                chat_id, main_menu_keyboard()
            )
            return
        
        lines = [
            f"📋 <b>آخرین سیگنال‌ها</b>",
            f"📢 کانال: <b>{CHANNEL_NAME}</b>",
            "━━━━━━━━━━━━━━━━━━\n"
        ]
        
        for s in signals:
            dir_emoji = "🟢" if s['direction'] == "LONG" else "🔴"
            result_emoji = {"WIN": "✅", "LOSS": "❌", "PENDING": "⏳"}.get(s['result'], "⏳")
            
            lines.append(
                f"{result_emoji} <code>{s['signal_id']}</code>\n"
                f"🪙 {s['symbol']} | {s['direction']} {dir_emoji}\n"
                f"🔮 {s['strategy_fa']} | ⭐ {s['score']}\n"
                f"🎯 {s['entry']:.4f} | 🛑 {s['sl']:.4f}\n"
                f"📊 {s['result']} {s['pnl_pct']:+.2f}%\n"
            )
        
        lines.extend([
            "━━━━━━━━━━━━━━━━━━",
            f"📢 <b>{CHANNEL_NAME}</b>"
        ])
        send_message("\n".join(lines), chat_id, main_menu_keyboard())
    except Exception as e:
        send_message(f"❌ خطا: {e}", chat_id)


def handle_active_signals(chat_id):
    """سیگنال‌های فعال"""
    from database.db import get_active_signals
    
    try:
        signals = get_active_signals()
        
        if not signals:
            send_message(
                "📋 سیگنال فعالی نداریم.",
                chat_id, main_menu_keyboard()
            )
            return
        
        lines = [
            f"🔔 <b>سیگنال‌های فعال</b>",
            f"📢 کانال: <b>{CHANNEL_NAME}</b>",
            "━━━━━━━━━━━━━━━━━━\n"
        ]
        
        for s in signals:
            dir_emoji = "🟢" if s['direction'] == "LONG" else "🔴"
            
            lines.append(
                f"<code>{s['signal_id']}</code>\n"
                f"🪙 {s['symbol']} | {s['direction']} {dir_emoji}\n"
                f"🔮 {s.get('strategy_fa', s['source'])}\n"
                f"🎯 Entry: {s['entry']:.4f}\n"
                f"🛑 SL: {s['sl']:.4f}\n"
            )
        
        lines.extend([
            "━━━━━━━━━━━━━━━━━━",
            f"📢 <b>{CHANNEL_NAME}</b>"
        ])
        send_message("\n".join(lines), chat_id, main_menu_keyboard())
    except Exception as e:
        send_message(f"❌ خطا: {e}", chat_id)


def handle_status(chat_id):
    """وضعیت ربات"""
    from database.db import get_dashboard_summary
    
    try:
        s = get_dashboard_summary()
        text = (
            f"🤖 <b>وضعیت ربات</b>\n"
            f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 <b>ربات فعال است</b>\n"
            f"⏱ زمان: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n"
            f"📊 نسخه: v6\n"
            f"🔄 اسکن: هر ۵ دقیقه\n"
            f"📈 استراتژی‌ها: ۱۳ عدد\n"
            f"📌 نمادها: ۶۰+\n"
            f"📊 کل سیگنال‌ها: {s['total_signals']}\n\n"
            f"⏰ MTF:\n"
            f"├ Swing: 4H→1H→15M\n"
            f"└ Scalp: 1H→15M→5M\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>{CHANNEL_NAME}</b>"
        )
        send_message(text, chat_id, main_menu_keyboard())
    except Exception as e:
        send_message(
            f"🤖 <b>وضعیت ربات</b>\n"
            f"🟢 فعال\n"
            f"⏱ {datetime.utcnow().strftime('%H:%M')} UTC\n"
            f"❌ خطا در دریافت آمار: {e}",
            chat_id, main_menu_keyboard()
        )


def handle_help(chat_id):
    """راهنما"""
    text = (
        f"❓ <b>راهنما</b>\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 <b>دستورات:</b>\n"
        f"/start - منوی اصلی\n"
        f"/stats - آمار کلی\n"
        f"/strategies - آمار استراتژی‌ها\n"
        f"/backtest SYMBOL - بک‌تست\n"
        f"/signals - آخرین سیگنال‌ها\n"
        f"/active - سیگنال‌های فعال\n"
        f"/status - وضعیت ربات\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>سیستم سیگنال:</b>\n"
        f"۱. 🔔 Setup Detected - ستاپ شکل گرفته\n"
        f"۲. ⚡ Approaching - نزدیک Entry\n"
        f"۳. ✅ Confirmed - تایید ورود\n"
        f"۴. 🥇 TP1 Hit - 60% کلوز + SL→BE\n"
        f"۵. 📊 Result - نتیجه نهایی\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )
    send_message(text, chat_id, main_menu_keyboard())


# ─── پردازش Callback ───

def handle_callback(callback_query):
    """پردازش دکمه‌ها"""
    data = callback_query.get("data", "")
    chat_id = str(callback_query["message"]["chat"]["id"])
    message_id = callback_query["message"]["message_id"]
    callback_id = callback_query["id"]
    
    # فقط ادمین
    if CHAT_ID_ADMIN and chat_id != CHAT_ID_ADMIN:
        answer_callback(callback_id, "⛔ دسترسی ندارید")
        return
    
    answer_callback(callback_id)
    
    if data == "main_menu":
        edit_message(chat_id, message_id,
                    "🏠 <b>منوی اصلی</b>\nیکی از گزینه‌ها رو انتخاب کنید:",
                    main_menu_keyboard())
    
    elif data == "stats":
        handle_stats(chat_id)
    
    elif data == "strategies":
        handle_strategies(chat_id)
    
    elif data == "signals":
        handle_recent_signals(chat_id)
    
    elif data == "active":
        handle_active_signals(chat_id)
    
    elif data == "status":
        handle_status(chat_id)
    
    elif data == "help":
        handle_help(chat_id)
    
    elif data == "refresh":
        edit_message(chat_id, message_id,
                    "🔄 بروزرسانی شد!\nیکی از گزینه‌ها رو انتخاب کنید:",
                    main_menu_keyboard())
    
    elif data == "backtest_menu":
        edit_message(chat_id, message_id,
                    "🧪 <b>نماد مورد نظر رو انتخاب کنید:</b>",
                    backtest_symbols_keyboard())
    
    elif data == "strategy_stats":
        handle_strategies(chat_id)
    
    elif data.startswith("bt_"):
        symbol = data[3:]
        handle_backtest(chat_id, symbol)
    
    elif data.startswith("strat_"):
        strategy = data[6:]
        handle_strategy_detail(chat_id, strategy)


def handle_strategy_detail(chat_id, strategy):
    """جزئیات یک استراتژی"""
    descriptions = {
        "SMC": ("📊 اسمارت مانی", "Order Block + Liquidity Sweep + CHoCH"),
        "RTM": ("🔷 RTM", "Rally-Base-Drop, Drop-Base-Rally"),
        "ICT": ("💎 ICT", "OTE Zone + Killzone + MSS"),
        "QM": ("🔮 کوآزیمودو", "الگوی بازگشتی قوی با Sweep"),
        "ENGULFING": ("🔥 کندل پوششی", "Bullish/Bearish Engulfing"),
        "PINBAR": ("📌 پین بار", "Hammer / Shooting Star"),
        "FVG": ("📐 شکاف قیمتی", "Fair Value Gap"),
        "IFVG": ("🔄 معکوس شکاف", "Inverse FVG"),
        "FLIPZONE": ("🔁 فیلیپ زون", "Support↔Resistance flip"),
        "BREAKOUT": ("💥 شکست سطح", "Static level breakout"),
        "ORDERBLOCK": ("🧱 اوردر بلاک", "Last candle before impulse"),
        "CHOCH": ("⚡ تغییر ساختار", "Change of Character"),
        "RETURN_AREA": ("🎯 بازگشت به ناحیه", "Supply/Demand retest"),
    }
    
    name, desc = descriptions.get(strategy, (strategy, ""))
    
    text = (
        f"{name}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{desc}\n\n"
        f"📢 <b>{CHANNEL_NAME}</b>"
    )
    send_message(text, chat_id, strategy_list_keyboard())


# ─── Listener ───

def get_updates(offset=None):
    """دریافت آپدیت‌ها"""
    if not TOKEN:
        return []
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 5, "allowed_updates": ["message", "callback_query"]}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.ok:
            return r.json().get("result", [])
    except Exception as e:
        print(f"Get updates error: {e}")
    return []


def handle_message(message):
    """پردازش پیام متنی"""
    text = message.get("text", "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))
    
    if not text.startswith("/"):
        return
    
    cmd = text.split()[0].lower()
    args = text.split()[1:] if len(text.split()) > 1 else []
    
    if cmd == "/start":
        handle_start(chat_id)
    elif cmd == "/help":
        handle_help(chat_id)
    elif cmd == "/stats":
        handle_stats(chat_id)
    elif cmd == "/strategies":
        handle_strategies(chat_id)
    elif cmd == "/backtest":
        symbol = args[0].upper() if args else "BTCUSDT"
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        handle_backtest(chat_id, symbol)
    elif cmd == "/signals":
        handle_recent_signals(chat_id)
    elif cmd == "/active":
        handle_active_signals(chat_id)
    elif cmd == "/status":
        handle_status(chat_id)


def command_listener():
    """گوش دادن به دستورات"""
    print("🤖 Telegram bot started - listening for commands")
    offset = None
    
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
                elif "message" in update:
                    handle_message(update["message"])
            
            time.sleep(1)
        except Exception as e:
            print(f"Listener error: {e}")
            time.sleep(3)


def start_command_listener():
    """شروع در ترد جدا"""
    thread = threading.Thread(target=command_listener, daemon=True)
    thread.start()
    return thread
