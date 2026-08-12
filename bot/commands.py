# bot/commands.py - Telegram Command Handler
# دستورات تلگرام برای کنترل ربات
import os
import requests
import threading
import time
from datetime import datetime

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID_ADMIN = os.environ.get("CHAT_ID", "")


def get_updates(offset=None):
    """دریافت آپدیت‌های تلگرام"""
    if not TOKEN:
        return []
    
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 5, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.ok:
            data = r.json()
            return data.get("result", [])
    except Exception as e:
        print(f"Get updates error: {e}")
    return []


def send_telegram(text: str, chat_id: str = None):
    """ارسال پیام تلگرام"""
    if not chat_id:
        chat_id = CHAT_ID_ADMIN
    if not TOKEN or not chat_id:
        return
    
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception:
        pass


def handle_command(message: dict):
    """پردازش دستورات تلگرام"""
    text = message.get("text", "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))
    
    if not text.startswith("/"):
        return
    
    cmd = text.split()[0].lower()
    args = text.split()[1:] if len(text.split()) > 1 else []
    
    # فقط ادمین میتونه دستور بده
    if CHAT_ID_ADMIN and chat_id != CHAT_ID_ADMIN:
        send_telegram("⛔ شما دسترسی ندارید.", chat_id)
        return
    
    if cmd == "/start" or cmd == "/help":
        help_text = (
            "🤖 <b>Viva Signal Bot v6</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📋 <b>دستورات:</b>\n\n"
            "/stats - آمار کلی عملکرد\n"
            "/strategies - آمار هر استراتژی\n"
            "/backtest <symbol> - بک‌تست یک نماد\n"
            "/signals - آخرین سیگنال‌ها\n"
            "/active - سیگنال‌های فعال\n"
            "/status - وضعیت ربات\n"
            "/help - راهنما\n\n"
            "📢 <b>vivasignalyst-Chanel</b>"
        )
        send_telegram(help_text, chat_id)
    
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


def handle_stats(chat_id: str):
    """آمار کلی"""
    from database.db import get_dashboard_summary
    
    try:
        s = get_dashboard_summary()
        
        msg = (
            f"📊 <b>عملکرد کلی</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📈 کل سیگنال‌ها: <b>{s['total_signals']}</b>\n"
            f"✅ برد: <b>{s['wins']}</b>\n"
            f"❌ باخت: <b>{s['losses']}</b>\n"
            f"⏳ در انتظار: <b>{s['pending']}</b>\n"
            f"🎯 Win Rate: <b>{s['winrate']}%</b>\n"
            f"💰 میانگین PnL: <b>{s['avg_pnl']}%</b>\n"
            f"🏆 بهترین: <b>{s['best_pnl']}%</b>\n"
            f"📉 بدترین: <b>{s['worst_pnl']}%</b>\n"
            f"⭐ میانگین امتیاز: <b>{s['avg_score']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>vivasignalyst-Chanel</b>"
        )
        send_telegram(msg, chat_id)
    except Exception as e:
        send_telegram(f"❌ خطا: {e}", chat_id)


def handle_strategies(chat_id: str):
    """آمار استراتژی‌ها"""
    from database.db import get_strategy_performance
    
    try:
        strategies = get_strategy_performance()
        
        if not strategies:
            send_telegram("📊 هنوز داده‌ای ثبت نشده.", chat_id)
            return
        
        lines = [
            "🔮 <b>عملکرد استراتژی‌ها</b>",
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
        
        lines.append(f"📢 <b>vivasignalyst-Chanel</b>")
        send_telegram("\n".join(lines), chat_id)
    except Exception as e:
        send_telegram(f"❌ خطا: {e}", chat_id)


def handle_backtest(chat_id: str, symbol: str):
    """بک‌تست یک نماد"""
    from analysis.backtest import run_full_backtest, generate_backtest_report
    
    try:
        send_telegram(f"🧪 در حال بک‌تست {symbol}... لطفاً صبر کنید.", chat_id)
        
        results = run_full_backtest(symbol, days=14)
        report = generate_backtest_report(results)
        
        send_telegram(report, chat_id)
    except Exception as e:
        send_telegram(f"❌ خطا در بک‌تست: {e}", chat_id)


def handle_recent_signals(chat_id: str):
    """آخرین سیگنال‌ها"""
    from database.db import get_recent_signals
    
    try:
        signals = get_recent_signals(10)
        
        if not signals:
            send_telegram("📋 هنوز سیگنالی ثبت نشده.", chat_id)
            return
        
        lines = [
            "📋 <b>آخرین سیگنال‌ها</b>",
            "━━━━━━━━━━━━━━━━━━\n"
        ]
        
        for s in signals:
            dir_emoji = "🟢" if s['direction'] == "LONG" else "🔴"
            result_emoji = {"WIN": "✅", "LOSS": "❌", "PENDING": "⏳"}.get(s['result'], "⏳")
            
            lines.append(
                f"{result_emoji} <code>{s['signal_id']}</code>\n"
                f"🪙 {s['symbol']} | {s['direction']} {dir_emoji}\n"
                f"🔮 {s['strategy_fa']} | امتیاز: {s['score']}\n"
                f"🎯 Entry: {s['entry']:.4f} | SL: {s['sl']:.4f}\n"
                f"📊 نتیجه: {s['result']} {s['pnl_pct']:+.2f}%\n"
            )
        
        lines.append(f"📢 <b>vivasignalyst-Chanel</b>")
        send_telegram("\n".join(lines), chat_id)
    except Exception as e:
        send_telegram(f"❌ خطا: {e}", chat_id)


def handle_active_signals(chat_id: str):
    """سیگنال‌های فعال"""
    from database.db import get_active_signals
    
    try:
        signals = get_active_signals()
        
        if not signals:
            send_telegram("📋 سیگنال فعالی نداریم.", chat_id)
            return
        
        lines = [
            "🔔 <b>سیگنال‌های فعال</b>",
            "━━━━━━━━━━━━━━━━━━\n"
        ]
        
        for s in signals:
            dir_emoji = "🟢" if s['direction'] == "LONG" else "🔴"
            status = "✅ تایید شده" if s.get('approaching_sent') else "⏳ در انتظار"
            
            lines.append(
                f"<code>{s['signal_id']}</code>\n"
                f"🪙 {s['symbol']} | {s['direction']} {dir_emoji}\n"
                f"🔮 {s.get('strategy_fa', s['source'])}\n"
                f"🎯 Entry: {s['entry']:.4f} | SL: {s['sl']:.4f}\n"
                f"📊 وضعیت: {status}\n"
            )
        
        lines.append(f"📢 <b>vivasignalyst-Chanel</b>")
        send_telegram("\n".join(lines), chat_id)
    except Exception as e:
        send_telegram(f"❌ خطا: {e}", chat_id)


def handle_status(chat_id: str):
    """وضعیت ربات"""
    msg = (
        f"🤖 <b>وضعیت ربات</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🟢 ربات فعال است\n"
        f"⏱ زمان: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"📊 نسخه: v6\n"
        f"🔄 اسکن: هر ۵ دقیقه\n"
        f"📈 استراتژی‌ها: ۱۳ عدد\n"
        f"⏰ MTF: 4H→1H→15M (Swing) | 1H→15M→5M (Scalp)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>vivasignalyst-Chanel</b>"
    )
    send_telegram(msg, chat_id)


def command_listener():
    """گوش دادن به دستورات تلگرام در پس‌زمینه"""
    print("🤖 Telegram command listener started")
    offset = None
    
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if message:
                    handle_command(message)
            time.sleep(2)
        except Exception as e:
            print(f"Command listener error: {e}")
            time.sleep(5)


def start_command_listener():
    """شروع listener در ترد جدا"""
    thread = threading.Thread(target=command_listener, daemon=True)
    thread.start()
    return thread
