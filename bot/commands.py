# bot/commands.py - Public Telegram Bot UX: menus, instant analysis, membership.
# رابط کاربری عمومی ربات: منوها، تحلیل فوری، عضویت و معرفی‌نامه
from __future__ import annotations

import json
import html
import os
import threading
import time
from datetime import datetime, timezone

import requests

from config import get_settings
from bot import membership as mem

SETTINGS = get_settings()
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID_ADMIN = os.environ.get("CHAT_ID", "")
CHAT_ID_EXECUTION = os.environ.get("CHAT_ID_APPROACHING", "")
CHANNEL_NAME = SETTINGS.channel_name

def _e(value) -> str:
    return html.escape(str(value), quote=False)

CRYPTO_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
    "TRXUSDT", "ATOMUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT",
    "OPUSDT", "SUIUSDT", "INJUSDT", "DOTUSDT", "FILUSDT",
]
FOREX_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"]
CMDTY_SYMBOLS = ["XAUUSD", "XAGUSD", "BRN", "WTI"]
CMDTY_NAMES = {"XAUUSD": "طلا", "XAGUSD": "نقره", "BRN": "نفت برنت", "WTI": "نفت وست تگزاس"}
STOCK_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
                 "TSLA", "NFLX", "AMD", "COIN", "JPM", "DIS"]

# short-lived per-chat map: chat_id -> {token: SignalCandidate-ish dict index}
_setup_tokens: dict[str, dict[str, int]] = {}
_result_tokens: dict[str, dict[str, dict]] = {}


# ─── ابزارهای API ───

def api_call(method, params=None, files=None):
    if not TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        if files:
            r = requests.post(url, data=params, files=files, timeout=60)
        else:
            r = requests.post(url, json=params, timeout=10)
        if r.ok:
            return r.json()
    except Exception as e:
        print(f"API error {method}: {e}")
    return None


def send_message(text, chat_id, reply_markup=None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return api_call("sendMessage", params)


def send_photo(chat_id, photo_bytes, caption="", reply_markup=None):
    params = {"chat_id": chat_id, "caption": caption[:1000], "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    files = {"photo": ("chart.png", photo_bytes, "image/png")}
    return api_call("sendPhoto", params, files)


def answer_callback(callback_query_id, text=""):
    return api_call("answerCallbackQuery", {
        "callback_query_id": callback_query_id,
        "text": text,
        "show_alert": bool(text),
    })


def edit_message(chat_id, message_id, text, reply_markup=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return api_call("editMessageText", params)


def _is_admin(user_id) -> bool:
    return mem.is_admin_chat(int(user_id)) or (CHAT_ID_ADMIN and str(user_id) == CHAT_ID_ADMIN)


def _uname(user: dict) -> str:
    return (user or {}).get("username", "") or ""


# ─── کیبوردها ───

def reply_menu_keyboard(user_id=None):
    """Persistent VivaMon-style lower Telegram menu (no scanner logic copied)."""
    rows = [
        [{"text": "🔎 تحلیل فوری"}, {"text": "📡 ستاپ‌های فعال"}],
        [{"text": "🕘 موارد اخیر"}, {"text": "📊 نتایج ستاپ‌ها"}],
        [{"text": "🩺 وضعیت سامانه"}, {"text": "📚 مسیر یادگیری"}],
        [{"text": "🚪 ورود به کانال"}, {"text": "💎 حساب و دسترسی"}],
        [{"text": "🛡 اصول ایمنی"}, {"text": "🪪 شناسه من"}],
        [{"text": "🔄 بروزرسانی ربات"}],
    ]
    if user_id is not None and _is_admin(user_id):
        rows.append([{"text": "🧪 گزارش آزمون"}, {"text": "🧹 پاکسازی هشدارها"}])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


def main_menu_keyboard(user_id=None):
    rows = [
        [
            {"text": "⚡ تحلیل فوری", "callback_data": "ia_menu"},
            {"text": "🔔 ستاپ‌های فعال", "callback_data": "setups"},
        ],
        [
            {"text": "📊 ژورنال و نتایج", "callback_data": "strategies"},
            {"text": "📚 آموزش اصطلاحات", "callback_data": "education"},
        ],
        [
            {"text": "🖥 وضعیت ربات", "callback_data": "status"},
            {"text": "❓ راهنما", "callback_data": "help"},
        ],
    ]
    if user_id is not None and _is_admin(user_id):
        rows.append([
            {"text": "🧪 بک‌تست (ادمین)", "callback_data": "backtest_menu"},
            {"text": "🧹 پاکسازی هشدارها", "callback_data": "purge_alerts"},
        ])
    return {"inline_keyboard": rows}


def _back_row(to="main_menu"):
    return [[{"text": "◀️ بازگشت", "callback_data": to}]]


def ia_classes_keyboard():
    return {"inline_keyboard": [
        [{"text": "🪙 کریپتو", "callback_data": "ia_crypto"},
         {"text": "💱 فارکس", "callback_data": "ia_forex"}],
        [{"text": "🥇 کامادیتی", "callback_data": "ia_cmdty"},
         {"text": "📈 استاکس", "callback_data": "ia_stocks"}],
        *_back_row(),
    ]}


def _symbol_grid(symbols, prefix, per_row=4, names=None):
    rows, row = [], []
    for s in symbols:
        label = names.get(s, s) if names else s.replace("USDT", "")
        row.append({"text": label, "callback_data": f"{prefix}{s}"})
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": "◀️ بازگشت", "callback_data": "ia_menu"}])
    return {"inline_keyboard": rows}


def backtest_symbols_keyboard():
    return _symbol_grid(CRYPTO_SYMBOLS[:9], "bt_", per_row=3)


def mem_menu_keyboard():
    return {"inline_keyboard": [
        [{"text": "💚 عضویت رایگان (معرفی‌نامه صرافی)", "callback_data": "mem_free"}],
        [{"text": "💳 عضویت ویژه (پرداخت)", "callback_data": "mem_paid"}],
        [{"text": "🪪 وضعیت من", "callback_data": "mem_status"}],
        *_back_row(),
    ]}


def strategy_list_keyboard():
    return {"inline_keyboard": [
        [{"text": "💧 Sweep + MSS", "callback_data": "strat_LSR"},
         {"text": "📈 BOS First Pullback", "callback_data": "strat_BOS1"}],
        [{"text": "📐 Trendline Retest", "callback_data": "strat_TLR"},
         {"text": "🏦 Supply/Demand", "callback_data": "strat_SDR"}],
        [{"text": "🔄 Breaker / IFVG", "callback_data": "strat_IFVG"},
         {"text": "🧬 P1234", "callback_data": "strat_P1234"}],
        [{"text": "📏 Channel Break", "callback_data": "strat_TLBREAK"}],
        [{"text": "📊 همه نتایج Setupها", "callback_data": "strategies"},
         {"text": "◀️ بازگشت", "callback_data": "main_menu"}],
    ]}


# ─── منو و راهنما ───

def handle_start(chat_id, user=None):
    user = user or {}
    mem.register_user(int(user.get("id", chat_id)), _uname(user),
                      user.get("first_name", ""))
    text = (
        "🏁 <b>Viva Signal Bot</b>\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 موتور SMC v7 + ستاپ‌های اعتبارسنجی‌شده 📐\n"
        "⚡ تحلیل فوری نماد دلخواهت با چارت\n"
        "🔔 ستاپ‌های فعال با نقطه ورود/خروج دقیق\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{mem.plan_status_fa(int(user.get('id', chat_id)), _uname(user))}\n"
        "از دکمه‌ها شروع کن 👇"
    )
    # Clear the old persistent reply keyboard once; navigation stays in Telegram's bottom Menu.
    api_call("sendMessage", {"chat_id": chat_id, "text": "🔄 منوی پایین بروزرسانی شد.", "reply_markup": json.dumps({"remove_keyboard": True})})
    send_message(text, chat_id, main_menu_keyboard(user.get("id")))


def handle_help(chat_id, user_id=None):
    text = (
        "❓ <b>راهنما</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>تحلیل فوری</b> — نماد رو انتخاب کن، اسکن زنده + چارت می‌گیری.\n"
        "🔔 <b>ستاپ‌های فعال</b> — ۱۰ ستاپ آخر با دکمه‌ی جزئیات و چارت.\n"
        "💎 <b>عضویت</b> — رایگان با معرفی‌نامه صرافی یا ویژه.\n\n"
        "📊 <b>چرخه سیگنال کانال:</b>\n"
        "۱) 🔔 Setup شکل گرفت ۲) ⚡ نزدیک ورود ۳) ✅ تأیید ورود\n"
        "۴) 🥇 TP1: ۶۰٪ بستن + استاپ به ورود ۵) 📊 نتیجه نهایی\n\n"
        "📋 دستورات: /start /analysis /setups /membership /stats /status"
    )
    if user_id is not None and _is_admin(user_id):
        text += ("\n\n👑 <b>ادمین:</b> /backtest SYMBOL /approve UID "
                 "/activate UID MONTHS /users /signals")
    send_message(text, chat_id, main_menu_keyboard(user_id))


# ─── وضعیت و آمار ───

def handle_status(chat_id, user_id=None):
    from database.db import get_dashboard_summary
    try:
        s = get_dashboard_summary()
        sig_line = f"📡 سیگنال‌های تأییدشده: <b>{s['total_signals']}</b>  🎯 WR: <b>{s['winrate']}%</b>"
    except Exception:
        sig_line = "📡 اتصال دیتابیس در دسترس نیست"
    try:
        from database.candidate_store import get_active_candidates
        active = len(get_active_candidates())
    except Exception:
        active = "؟"
    text = (
        "🖥 <b>وضعیت ربات</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🟢 آنلاین  •  ⏱ {datetime.now(timezone.utc).strftime('%H:%M')} UTC\n"
        f"📦 نسخه: {SETTINGS.version}\n"
        f"🔔 ستاپ‌های فعال: <b>{active}</b>\n"
        f"{sig_line}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧭 چیدمان اسکن (هم‌راستا با بستن کندل):\n"
        f"├ اسکن کامل: هر {SETTINGS.full_scan_minutes} دقیقه\n"
        f"└ مانیتور: هر {SETTINGS.monitor_minutes} دقیقه (دقیقه ۱ هر کندل)\n"
        "📊 MTF: 1D→4H→1H→15M | 1H→15M→5M"
    )
    send_message(text, chat_id, main_menu_keyboard(user_id))


def handle_stats(chat_id, user_id=None):
    from database.db import get_dashboard_summary, get_strategy_performance
    try:
        s = get_dashboard_summary()
        wr_e = "🏆" if s['winrate'] >= 60 else "⭐" if s['winrate'] >= 50 else "⚠️"
        lines = [
            "📊 <b>آمار کانال</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"📈 کل سیگنال‌ها: <b>{s['total_signals']}</b>  (✅ {s['wins']} | ❌ {s['losses']} | ⏳ {s['pending']})",
            f"{wr_e} Win Rate: <b>{s['winrate']}%</b>",
            f"💰 میانگین PnL: <b>{s['avg_pnl']:+.2f}%</b>",
            f"🚀 بهترین: {s['best_pnl']:+.2f}%  •  🕳 بدترین: {s['worst_pnl']:+.2f}%",
            f"⭐ میانگین امتیاز: {s['avg_score']}",
        ]
        try:
            strats = get_strategy_performance()[:5]
            if strats:
                lines.append("━━━━━━━━━━━━━━━━━━\n🔮 <b>برترین ستاپ‌ها:</b>")
                for st in strats:
                    e = "🏆" if st['winrate'] >= 70 else "⭐" if st['winrate'] >= 55 else "⚠️"
                    lines.append(
                        f"{e} {st['strategy_fa']} — {st['total']} ترید | "
                        f"WR {st['winrate']:.0f}% | {st['avg_pnl']:+.2f}%"
                    )
        except Exception:
            pass
        lines.append("━━━━━━━━━━━━━━━━━━\n🧪 آمار زنده کانال است، نه بک‌تست.")
        send_message("\n".join(lines), chat_id, main_menu_keyboard(user_id))
    except Exception as e:
        send_message(f"❌ خطا در دریافت آمار: {e}", chat_id, main_menu_keyboard(user_id))


# ─── تحلیل فوری ───

def handle_ia_menu(chat_id, message_id=None):
    text = (
        "⚡ <b>تحلیل فوری</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "بازار رو انتخاب کن؛ اسکن زنده SMC انجام میشه و چارت + نقاط ورود/خروج می‌گیری.\n"
        f"💡 سهمیه رایگان: {mem.FREE_ANALYSIS_LIMIT} تحلیل"
    )
    if message_id:
        edit_message(chat_id, message_id, text, ia_classes_keyboard())
    else:
        send_message(text, chat_id, ia_classes_keyboard())


def handle_instant_analysis(chat_id, symbol, user):
    uid, uname = int(user.get("id", chat_id)), _uname(user)
    ok, reason = mem.can_use_analysis(uid, uname)
    if not ok:
        send_message(reason, chat_id, mem_menu_keyboard())
        return
    send_message(f"⏳ در حال اسکن زنده <b>{symbol}</b> …", chat_id)

    def _work():
        try:
            from analysis.quality_engine import scan_bundle
            from data.fetcher import get_market_bundle
            bundle = get_market_bundle(symbol)
            candidates = scan_bundle(bundle)
            ready = [c for c in candidates if c.execution_ready]
            pool = ready or candidates
            if not pool:
                tk = bundle.ticker or {}
                chg = tk.get("price24hPcnt")
                try:
                    chg_txt = f"{float(chg) * 100:+.2f}%" if chg is not None else "—"
                except Exception:
                    chg_txt = "—"
                mem.consume_analysis(uid, uname)
                send_message(
                    f"🪙 <b>{symbol}</b>\n━━━━━━━━━━━━━━━━━━\n"
                    "🔍 الان ستاپ تمیزی نداریم؛ بازار وسط ناحیه‌هاست. "
                    "وقتی قیمت به ناحیه معتبر برسه، آلارم کانال میاد.\n"
                    f"📈 تغییر ۲۴ساعته: {chg_txt}",
                    chat_id, main_menu_keyboard(uid))
                return
            best = max(pool, key=lambda c: c.score)
            mem.consume_analysis(uid, uname)
            _send_candidate_card(chat_id, best, bundle=bundle, title="⚡ تحلیل فوری")
            send_message(f"💡 {mem.plan_status_fa(uid, uname)}", chat_id,
                         main_menu_keyboard(uid))
        except Exception as e:
            send_message(f"❌ خطا در تحلیل {symbol}: {e}", chat_id,
                         ia_classes_keyboard())

    threading.Thread(target=_work, daemon=True).start()


def handle_unsupported_market(chat_id, symbol, label):
    send_message(
        f"{label} <b>{symbol}</b>\n━━━━━━━━━━━━━━━━━━\n"
        "🗓 دیتای لحظه‌ای این بازار هنوز به موتور اسکن وصل نیست؛ "
        "در نسخه بعدی فعال می‌شود. فعلاً «🪙 کریپتو» کامل در دسترسه.",
        chat_id, ia_classes_keyboard())


# ─── کارت ستاپ (مشترک) ───

def _fmt(p: float) -> str:
    if p >= 100:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.3f}"
    return f"{p:.5f}".rstrip("0")


def _analysis_card_text(c, title: str) -> str:
    dir_e = "🟢 LONG" if c.direction == "LONG" else "🔴 SHORT"
    style_fa = "سوینگ 🌊" if c.style == "SWING" else "اسکالپ ⚡"
    entry, sl, tp1, tp2 = c.planned_entry, c.sl, c.tp1, c.tp2
    risk = abs(entry - sl)
    risk_pct = (risk / entry * 100) if entry else 0
    lines = [
        f"{title} — <b>{c.symbol}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🧭 جهت: <b>{dir_e}</b>  |  {style_fa}",
        f"🔮 ستاپ: {c.strategy_fa}  ⭐ {c.score}/10",
        "━━━━━━━━━━━━━━━━━━",
        f"📥 ناحیه ورود: {_fmt(c.entry_zone_bottom)} – {_fmt(c.entry_zone_top)}",
        f"🎯 ورود پیشنهادی: <b>{_fmt(entry)}</b>",
        f"🛑 استاپ: <code>{_fmt(sl)}</code> (ریسک {risk_pct:.2f}%)",
        f"🥇 تارگت اول: {_fmt(tp1)} (R {c.rr_tp1:.2f}) ← ۶۰٪ ببند، استاپ ببر به ورود",
        f"🥈 تارگت دوم: {_fmt(tp2)} (R {c.rr_tp2:.2f}) ← باقی پوزیشن",
    ]
    try:
        from bot.messages_v7 import _ai_note
        note = _ai_note(c)
        if note:
            lines.append("━━━━━━━━━━━━━━━━━━")
            lines.append(note)
    except Exception:
        pass
    lines.append("⚠️ مدیریت سرمایه با خودته؛ این یک هشدار آموزشیه، نه دستور قطعی.")
    return "\n".join(lines)


def _send_candidate_card(chat_id, c, bundle=None, title="🔔 ستاپ فعال"):
    df = None
    if bundle is not None:
        df = bundle.get(c.metadata.get("tl_context_tf")) if c.setup_code == "TLBREAK" else None
        if df is None:
            df = bundle.get(c.trigger_timeframe)
    else:
        try:
            from data.fetcher import get_klines
            tf = (c.metadata.get("tl_context_tf") if c.setup_code == "TLBREAK"
                  else None) or c.trigger_timeframe
            df = get_klines(c.symbol, tf, 200)
        except Exception:
            df = None
    caption = _analysis_card_text(c, title)
    back = {"inline_keyboard": [[{"text": "◀️ بازگشت", "callback_data": "setups"}]]}
    if df is not None and len(df) > 30:
        try:
            from bot.messages_v7 import generate_chart
            png = generate_chart(df, c, confirmed=False)
            if png:
                send_photo(chat_id, png, caption, back)
                return
        except Exception as e:
            print(f"chart error: {e}")
    send_message(caption, chat_id, back)


# ─── ستاپ‌های فعال ───

def handle_setups(chat_id, message_id=None):
    try:
        from database.candidate_store import get_active_candidates
        cands = get_active_candidates() or []
    except Exception as e:
        send_message(f"❌ خطا: {e}", chat_id, main_menu_keyboard())
        return
    cands = cands[-10:][::-1]
    if not cands:
        send_message(
            "🔔 <b>ستاپ‌های فعال</b>\n━━━━━━━━━━━━━━━━━━\n"
            "الان ستاپ فعالی نداریم — موتور در حال اسکنه؛ اولین آلارم توی کانال میاد.",
            chat_id, main_menu_keyboard())
        return
    tokens = {}
    rows = []
    for i, c in enumerate(cands):
        tok = f"su_{i}"
        tokens[tok] = c
        dir_e = "🟢" if c.direction == "LONG" else "🔴"
        rows.append([{"text": f"{dir_e} {c.symbol.replace('USDT','')} · {c.setup_code} · ⭐{c.score} · {c.style[:1]}",
                      "callback_data": tok}])
    rows.append([{"text": "◀️ بازگشت", "callback_data": "main_menu"}])
    _setup_tokens[str(chat_id)] = tokens
    text = ("🔔 <b>ستاپ‌های فعال</b> (۱۰ مورد آخر)\n━━━━━━━━━━━━━━━━━━\n"
            "روی هر کدوم بزن تا کارت کامل + چارت زنده رو ببینی 👇")
    if message_id:
        edit_message(chat_id, message_id, text, {"inline_keyboard": rows})
    else:
        send_message(text, chat_id, {"inline_keyboard": rows})


def handle_setup_detail(chat_id, token):
    c = _setup_tokens.get(str(chat_id), {}).get(token)
    if c is None:
        send_message("⏳ این لیست قدیمی شده؛ دوباره «🔔 ستاپ‌های فعال» رو باز کن.",
                     chat_id, main_menu_keyboard())
        return
    send_message(f"⏳ آماده‌سازی چارت <b>{c.symbol}</b> …", chat_id)

    def _work():
        _send_candidate_card(chat_id, c, title="🔔 ستاپ فعال")

    threading.Thread(target=_work, daemon=True).start()


# ─── عضویت ───

def handle_membership(chat_id, user, message_id=None):
    uid, uname = int(user.get("id", chat_id)), _uname(user)
    text = (
        "💎 <b>عضویت ویوا مون لب</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🪪 وضعیت فعلی: {mem.plan_status_fa(uid, uname)}\n\n"
        "💚 <b>رایگان:</b> واریز حداقل ۵۰$ از لینک معرفی‌نامه ما در یکی از صرافی‌ها "
        "و ارسال UID → لینک یک‌بارمصرف کانال سیگنال.\n"
        "💳 <b>ویژه:</b> ۱۵$ ماهانه • ۳۰$ سه‌ماهه • ۵۰$ شش‌ماهه.\n"
        "🧪 فروش رسمی پس از اتمام دوره تست چندماهه فعال می‌شود؛ الان پیش‌ثبت‌نامه."
    )
    if message_id:
        edit_message(chat_id, message_id, text, mem_menu_keyboard())
    else:
        send_message(text, chat_id, mem_menu_keyboard())


def handle_mem_free(chat_id, user):
    uid = int(user.get("id", chat_id))
    rows = [[{"text": f"🏦 {name}", "url": url}] for name, url in mem.REF_LINKS.items()]
    rows.append([{"text": "✍️ ثبت UID", "callback_data": "mem_uid"}])
    rows.append([{"text": "◀️ بازگشت", "callback_data": "mem_menu"}])
    send_message(
        "💚 <b>عضویت رایگان با معرفی‌نامه</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "۱️⃣ در یکی از صرافی‌های زیر با لینک ما ثبت‌نام کن\n"
        "۲️⃣ حداقل ۵۰$ واریز کن\n"
        "۳️⃣ دکمه «✍️ ثبت UID» رو بزن و UID اکانتت رو بفرست\n"
        "۴️⃣ بعد از تأیید، لینک یک‌بارمصرف کانال برات میاد 🔗",
        chat_id, {"inline_keyboard": rows})


def handle_mem_paid(chat_id, user=None):
    wallet = mem.WALLET_ADDRESS or "(به‌زودی اعلام می‌شود)"
    rows = [
        [{"text": "۱ ماهه ۱۵$", "callback_data": "mem_plan_1m"},
         {"text": "۳ ماهه ۳۰$", "callback_data": "mem_plan_3m"},
         {"text": "۶ ماهه ۵۰$", "callback_data": "mem_plan_6m"}],
        [{"text": "✍️ ثبت TXID پرداخت", "callback_data": "mem_tx"}],
        [{"text": "◀️ بازگشت", "callback_data": "mem_menu"}],
    ]
    send_message(
        "💳 <b>عضویت ویژه</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📅 ۱ ماهه: <b>15$</b>  •  ۳ ماهه: <b>30$</b>  •  ۶ ماهه: <b>50$</b>\n\n"
        f"🏦 آدرس ولت (USDT):\n<code>{wallet}</code>\n"
        "۱️⃣ مبلغ پلن رو واریز کن\n"
        "۲️⃣ «✍️ ثبت TXID» رو بزن و کد تراکنش رو بفرست\n"
        "۳️⃣ بعد از تأیید ادمین، دسترسی فعال می‌شه ✅\n\n"
        "🧪 فروش رسمی پس از اتمام دوره تست آغاز می‌شود؛ ثبت TXID الان = پیش‌رزرو.",
        chat_id, {"inline_keyboard": rows})
    if mem.WALLET_QR_PATH and os.path.exists(mem.WALLET_QR_PATH):
        try:
            with open(mem.WALLET_QR_PATH, "rb") as f:
                send_photo(chat_id, f.read(), "📷 QR ولت")
        except Exception:
            pass


def _handle_pending_text(message) -> bool:
    """Returns True if the text was consumed as UID/TX capture."""
    user = message.get("from", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    uid, uname = int(user.get("id", 0) or 0), _uname(user)
    state = mem.get_pending(uid)
    text = message.get("text", "").strip()
    if not state or not text:
        return False
    mem.set_pending(uid, None)
    if state == "await_uid":
        mem.mark_uid(uid, text)
        send_message(
            "✅ UID ثبت شد!\nکارشناس ما واریز ۵۰$ رو بررسی می‌کنه و "
            "لینک یک‌بارمصرف کانال برات ارسال می‌شه 🔗\n(معمولاً کمتر از ۲۴ ساعت)",
            chat_id, main_menu_keyboard(uid))
        if CHAT_ID_ADMIN:
            send_message(
                f"🆕 درخواست معرفی‌نامه\n👤 @{uname or '—'} (<code>{uid}</code>)\n"
                f"🆔 UID: <code>{text}</code>",
                CHAT_ID_ADMIN,
                {"inline_keyboard": [[
                    {"text": "✅ تأیید و ارسال لینک", "callback_data": f"appr_{uid}"},
                    {"text": "❌ رد", "callback_data": f"rej_{uid}"}]]})
    elif state == "await_tx":
        mem.mark_tx(uid, text)
        send_message(
            "✅ TXID ثبت شد!\nپرداختت بررسی می‌شه و عضویت ویژه فعال می‌شه 💎\n"
            "🧪 این ثبت در دوره تست = پیش‌رزرو محسوب میشه.",
            chat_id, main_menu_keyboard(uid))
        if CHAT_ID_ADMIN:
            send_message(
                f"💰 درخواست عضویت ویژه\n👤 @{uname or '—'} (<code>{uid}</code>)\n"
                f"🧾 TXID: <code>{text}</code>\n"
                f"فعال‌سازی: /activate {uid} MONTHS (1/3/6)",
                CHAT_ID_ADMIN)
    return True


# ─── بک‌تست و جزئیات استراتژی (ادمین) ───

def handle_backtest(chat_id, symbol, style="BOTH"):
    from analysis.backtest import run_full_backtest, generate_backtest_report
    style = style.upper() if style else "BOTH"
    if style not in {"SWING", "SCALP", "BOTH"}:
        style = "BOTH"
    try:
        send_message(
            f"🧪 <b>در حال بک‌تست {symbol} • {style}...</b>\n"
            "Bias تاریخی، تأیید کندل بسته، Fee و Slippage بررسی می‌شوند.",
            chat_id)
        results = run_full_backtest(symbol, days=14, style=style)
        send_message(generate_backtest_report(results), chat_id,
                     main_menu_keyboard(chat_id))
    except Exception as e:
        send_message(f"❌ خطا: {e}", chat_id, main_menu_keyboard(chat_id))


def handle_strategies(chat_id):
    """Professional results hub: per-setup stats plus drill-down buttons."""
    from database.db import get_strategy_performance
    try:
        strategies = get_strategy_performance()
        if not strategies:
            send_message("📊 هنوز سیگنال Confirmed ثبت نشده.", chat_id, main_menu_keyboard())
            return
        lines = ["📊 <b>ژورنال عملکرد ستاپ‌ها</b>", "━━━━━━━━━━━━━━━━━━"]
        rows, row = [], []
        for s in strategies:
            emoji = "🏆" if s['winrate'] >= 70 else "⭐" if s['winrate'] >= 55 else "⚠️" if s['winrate'] >= 40 else "❌"
            code = str(s.get('source') or s.get('setup_code') or '')
            lines.append(
                f"{emoji} <b>{s['strategy_fa']}</b> • <code>{_e(code)}</code>\n"
                f"├ 📈 {s['total']} Confirmed (✅{s['wins']} ❌{s['losses']})\n"
                f"├ 🎯 WR {s['winrate']:.1f}%  •  Avg {s['avg_pnl']:+.2f}%\n"
                f"└ ⭐ کیفیت میانگین {s['avg_score']}")
            if code:
                row.append({"text": f"📌 {code}", "callback_data": f"res_{code}"})
                if len(row) == 3:
                    rows.append(row); row=[]
        if row: rows.append(row)
        rows.append([{"text": "📋 آخرین Confirmها", "callback_data": "recent_results"}, {"text": "◀️ منو", "callback_data": "main_menu"}])
        send_message("\n━━━━━━━━━━━━━━━━━━\n".join(lines), chat_id, {"inline_keyboard": rows})
    except Exception as e:
        send_message(f"❌ خطا در ژورنال نتایج: {e}", chat_id, main_menu_keyboard())


def handle_setup_results(chat_id, setup_code):
    from database.db import get_recent_signals
    code = str(setup_code).upper()
    signals = [x for x in get_recent_signals(80) if str(x.get("source") or "").upper() == code]
    if not signals:
        send_message(f"📌 هنوز نتیجه‌ای برای <b>{_e(code)}</b> ثبت نشده.", chat_id, main_menu_keyboard())
        return
    lines = [f"📌 <b>ژورنال { _e(code) }</b>", "━━━━━━━━━━━━━━━━━━"]
    rows, token_map = [], {}
    for i, item in enumerate(signals[:12]):
        result = {"WIN":"✅", "LOSS":"❌", "PENDING":"⏳"}.get(item.get("result"), "⏳")
        lines.append(f"{result} <code>{_e(item.get('public_code') or item.get('signal_id'))}</code> • {_e(item.get('symbol'))} • {float(item.get('pnl_pct') or 0):+.2f}%")
        token = f"jr{i}"
        token_map[token] = item
        rows.append([{"text": f"{result} {item.get('symbol')} • جزئیات و چارت", "callback_data": token}])
    _result_tokens[str(chat_id)] = token_map
    rows += [[{"text":"◀️ ژورنال ستاپ‌ها","callback_data":"strategies"}], [{"text":"🏠 منو","callback_data":"main_menu"}]]
    send_message("\n".join(lines), chat_id, {"inline_keyboard": rows})


def handle_recent_signals(chat_id):
    from database.db import get_recent_signals
    try:
        signals = get_recent_signals(10)
        if not signals:
            send_message("📋 هنوز سیگنالی ثبت نشده.", chat_id, main_menu_keyboard())
            return
        lines = ["📋 <b>آخرین سیگنال‌ها</b>", "━━━━━━━━━━━━━━━━━━"]
        for s in signals:
            dir_emoji = "🟢" if s['direction'] == "LONG" else "🔴"
            res = {"WIN": "✅", "LOSS": "❌", "PENDING": "⏳"}.get(s['result'], "⏳")
            lines.append(
                f"{res} <code>{s['signal_id']}</code>\n"
                f"🪙 {s['symbol']} | {s['direction']} {dir_emoji} | 🔮 {s['strategy_fa']}\n"
                f"🎯 {s['entry']:.4f} | 🛑 {s['sl']:.4f} | {s['pnl_pct']:+.2f}%")
        send_message("\n".join(lines), chat_id, main_menu_keyboard())
    except Exception as e:
        send_message(f"❌ خطا: {e}", chat_id)


def handle_strategy_detail(chat_id, strategy):
    descriptions = {
        "LSR": ("💧 Liquidity Sweep + MSS", "جمع‌آوری نقدینگی، Displacement، تغییر ساختار و اولین Retest به OB/FVG تازه."),
        "BOS1": ("📈 BOS First Pullback", "شکست ساختار با Close و Displacement؛ فقط اولین پولبک به ناحیه مبدأ."),
        "TLR": ("📐 Trendline Break + Retest", "خط ساخته‌شده از حداقل سه Pivot، شکست معتبر و اولین پولبک."),
        "SDR": ("🏦 Supply/Demand Break", "شکست ناحیه چندواکنشی و اولین Retest به Flip Zone."),
        "IFVG": ("🔄 Breaker / IFVG", "Inverse FVG بعد از شکست ساختار."),
        "P1234": ("🧬 الگوی 1-2-3-4", "برگشت از نقطه 4 در جهت ساختار؛ مطالعه‌شده روی SOL با فیلتر ADX."),
        "TLBREAK": ("📏 Channel/Trendline Break", "شکست کانال/ترندلاین داینامیک با ورود روی بیس داخل کندل شکست، هدف اولین ناحیه مقابل."),
    }
    name, desc = descriptions.get(strategy, (strategy, ""))
    send_message(f"{name}\n━━━━━━━━━━━━━━━━━━\n{desc}", chat_id,
                 strategy_list_keyboard())


def handle_result_detail(chat_id, token):
    item = _result_tokens.get(str(chat_id), {}).get(token)
    if not item:
        send_message("⚠️ این ژورنال منقضی شده؛ دوباره از منوی نتایج بازش کن.", chat_id, main_menu_keyboard())
        return
    from analysis.models import SignalCandidate
    from bot.messages_v7 import generate_chart
    from data.fetcher import get_klines
    entry, sl = float(item.get("entry") or 0), float(item.get("sl") or 0)
    c = SignalCandidate(signal_id=str(item.get("signal_id")), symbol=str(item.get("symbol")), style=str(item.get("trade_style") or "DAYTRADE"), setup_code=str(item.get("source") or "SETUP"), setup_name=str(item.get("source") or "SETUP"), strategy_fa=str(item.get("strategy_fa") or "SETUP"), direction=str(item.get("direction") or "LONG"), score=int(item.get("score") or 0), status="CONFIRMED", entry_zone_bottom=entry, entry_zone_top=entry, planned_entry=entry, sl=sl, tp1=float(item.get("tp1") or entry), tp2=float(item.get("tp2") or entry), rr_tp1=0, rr_tp2=0, bias="BULLISH" if item.get("direction")=="LONG" else "BEARISH", trigger_timeframe="15m", metadata={"public_code":item.get("public_code") or item.get("signal_id")})
    try:
        frame=get_klines(c.symbol, "15m", 180, closed_only=False, use_cache=False)
        chart=generate_chart(frame,c,confirmed=True) if frame is not None else None
    except Exception: chart=None
    result={"WIN":"✅ WIN","LOSS":"❌ LOSS","PENDING":"⏳ OPEN"}.get(item.get("result"),"⏳")
    caption=f"📊 <b>جزئیات ژورنال</b> • {_e(c.setup_code)}\n🪙 {_e(c.symbol)} • {_e(c.direction)} • {result}\n🎯 Entry {_e(entry)} | SL {_e(sl)}\n🏁 TP1 {_e(item.get('tp1'))} | TP2 {_e(item.get('tp2'))}\n📈 PnL {float(item.get('pnl_pct') or 0):+.2f}%\n🆔 <code>{_e(item.get('public_code') or item.get('signal_id'))}</code>"
    def _msg_url(mid):
        raw = str(CHAT_ID_EXECUTION or "")
        return f"https://t.me/c/{raw[4:]}/{int(mid)}" if raw.startswith("-100") and mid else ""
    rows = []
    confirmed_url = _msg_url(item.get("pro_message_id"))
    tp_url = _msg_url(item.get("first_tp_message_id"))
    if confirmed_url: rows.append([{"text":"📌 چارت Confirmed اصلی", "url":confirmed_url}])
    if tp_url: rows.append([{"text":"🏁 چارت تاریخی TP1", "url":tp_url}])
    markup = {"inline_keyboard": rows} if rows else None
    if chart: send_photo(chat_id, chart, caption, markup)
    else: send_message(caption,chat_id, markup)


def handle_education(chat_id):
    text = (
        "📚 <b>آموزش اصطلاحات چارت</b>\n━━━━━━━━━━━━━━━━━━\n"
        "• <b>BOS / MSS</b>: شکست ساختار یا تغییر رفتار ساختاری.\n"
        "• <b>FVG</b>: ناکارآمدی بین کندل‌ها؛ ناحیه‌ای که ممکن است قیمت به آن برگردد.\n"
        "• <b>Supply / Demand</b>: زون عرضه یا تقاضا که واکنش معتبر قبلی دارد.\n"
        "• <b>Liquidity Sweep</b>: جمع‌کردن سقف/کف و برگشت قیمت.\n"
        "• <b>Retest</b>: بازگشت قیمت برای تست سطح شکسته‌شده.\n"
        "• <b>Displacement</b>: حرکت جهت‌دار با بدنه معتبر نسبت به ATR.\n"
        "• <b>ATR</b>: واحد نوسان واقعی همان نماد و همان تایم‌فریم.\n"
        "• <b>R:R</b>: نسبت سود بالقوه به فاصله ابطال.\n"
        "• <b>Invalidation</b>: سطحی که عبور معتبر از آن، سناریو را باطل می‌کند."
    )
    send_message(text, chat_id, main_menu_keyboard())


# ─── پردازش Callback ───

def handle_callback(callback_query):
    data = callback_query.get("data", "")
    chat_id = str(callback_query["message"]["chat"]["id"])
    message_id = callback_query["message"]["message_id"]
    callback_id = callback_query["id"]
    user = callback_query.get("from", {})
    uid = int(user.get("id", 0) or 0)
    uname = _uname(user)

    answer_callback(callback_id)

    if data == "main_menu":
        edit_message(chat_id, message_id,
                     "🏠 <b>منوی اصلی</b> — یکی رو انتخاب کن:",
                     main_menu_keyboard(uid))
    elif data == "stats":
        handle_stats(chat_id, uid)
    elif data == "strategies":
        handle_strategies(chat_id)
    elif data == "education":
        handle_education(chat_id)
    elif data == "recent_results":
        handle_recent_signals(chat_id)
    elif data.startswith("res_"):
        handle_setup_results(chat_id, data[4:])
    elif data.startswith("jr"):
        handle_result_detail(chat_id, data)
    elif data == "signals":
        if _is_admin(uid):
            handle_recent_signals(chat_id)
        else:
            answer_callback(callback_id, "این بخش فقط برای ادمینه 🔒")
    elif data == "status":
        handle_status(chat_id, uid)
    elif data == "purge_alerts":
        if _is_admin(uid):
            from bot.messages_v7 import purge_resolved_alert_posts
            count = purge_resolved_alert_posts()
            send_message(f"🧹 {count} پیام حل‌شده از کانال هشدار پاک شد.", chat_id, main_menu_keyboard(uid))
        else:
            answer_callback(callback_id, "این بخش فقط برای ادمینه 🔒")
    elif data == "help":
        handle_help(chat_id, uid)
    # تحلیل فوری
    elif data == "ia_menu":
        handle_ia_menu(chat_id, message_id)
    elif data == "ia_crypto":
        edit_message(chat_id, message_id,
                     "🪙 <b>کریپتو</b> — نماد رو انتخاب کن:",
                     _symbol_grid(CRYPTO_SYMBOLS, "an_"))
    elif data == "ia_forex":
        edit_message(chat_id, message_id,
                     "💱 <b>فارکس</b> — جفت‌ارز رو انتخاب کن:",
                     _symbol_grid(FOREX_SYMBOLS, "fx_", per_row=3))
    elif data == "ia_cmdty":
        edit_message(chat_id, message_id,
                     "🥇 <b>کامادیتی</b> — دارایی رو انتخاب کن:",
                     _symbol_grid(CMDTY_SYMBOLS, "cm_", per_row=2, names=CMDTY_NAMES))
    elif data == "ia_stocks":
        edit_message(chat_id, message_id,
                     "📈 <b>استاکس</b> — سهم رو انتخاب کن:",
                     _symbol_grid(STOCK_SYMBOLS, "st_", per_row=4))
    elif data.startswith("an_"):
        handle_instant_analysis(chat_id, data[3:], user)
    elif data.startswith(("fx_", "cm_", "st_")):
        label = {"fx_": "💱", "cm_": "🥇", "st_": "📈"}[data[:3]]
        handle_unsupported_market(chat_id, data[3:], label)
    # ستاپ‌های فعال
    elif data == "setups":
        handle_setups(chat_id, message_id)
    elif data.startswith("su_"):
        answer_callback(callback_id)
        handle_setup_detail(chat_id, data)
    # عضویت
    elif data == "mem_menu":
        handle_membership(chat_id, user, message_id)
    elif data == "mem_free":
        handle_mem_free(chat_id, user)
    elif data == "mem_paid" or data.startswith("mem_plan_"):
        handle_mem_paid(chat_id, user)
    elif data == "mem_uid":
        mem.set_pending(uid, "await_uid")
        send_message("✍️ UID اکانت صرافیت رو همینجا بفرست (فقط عدد/کد):", chat_id)
    elif data == "mem_tx":
        mem.set_pending(uid, "await_tx")
        send_message("✍️ TXID تراکنش رو همینجا بفرست:", chat_id)
    elif data == "mem_status":
        answer_callback(callback_id, mem.plan_status_fa(uid, uname))
    # تأیید ادمین برای معرفی‌نامه
    elif data.startswith("appr_") and _is_admin(uid):
        target = int(data[5:])
        mem.approve_referral(target)
        invite = mem.CHANNEL_INVITE_URL or "(لینک کانال در ENV تنظیم نشده)"
        send_message(
            f"🎉 تبریک! عضویتت تأیید شد 💚\n🔗 لینک یک‌بارمصرف کانال:\n{invite}",
            str(target))
        edit_message(chat_id, message_id, "✅ تأیید شد و لینک ارسال گردید.")
    elif data.startswith("rej_") and _is_admin(uid):
        send_message("❌ متأسفانه درخواستت تأیید نشد؛ با پشتیبانی در تماس باش.",
                     data[4:])
        edit_message(chat_id, message_id, "❌ رد شد.")
    # فقط ادمین
    elif data in {"backtest_menu", "refresh"} or data.startswith(("bt_", "strat_")):
        if not _is_admin(uid):
            answer_callback(callback_id, "این بخش فقط برای ادمینه 🔒")
            return
        if data == "backtest_menu":
            edit_message(chat_id, message_id, "🧪 نماد را انتخاب کن:",
                         backtest_symbols_keyboard())
        elif data == "refresh":
            edit_message(chat_id, message_id, "🔄 بروزرسانی شد!",
                         main_menu_keyboard(uid))
        elif data.startswith("bt_"):
            handle_backtest(chat_id, data[3:])
        else:
            handle_strategy_detail(chat_id, data[6:])


# ─── پردازش پیام متنی ───

def handle_message(message):
    text = message.get("text", "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))
    user = message.get("from", {})
    uid = int(user.get("id", 0) or 0)

    if not text.startswith("/"):
        from bot.messages_v7 import purge_resolved_alert_posts
        quick = {
            "🔎 تحلیل فوری": lambda: handle_ia_menu(chat_id),
            "📡 ستاپ‌های فعال": lambda: handle_setups(chat_id),
            "🕘 موارد اخیر": lambda: handle_recent_signals(chat_id),
            "📊 نتایج ستاپ‌ها": lambda: handle_strategies(chat_id),
            "🩺 وضعیت سامانه": lambda: handle_status(chat_id, uid),
            "📚 مسیر یادگیری": lambda: handle_education(chat_id),
            "💎 حساب و دسترسی": lambda: handle_membership(chat_id, user),
            "🚪 ورود به کانال": lambda: send_message(mem.CHANNEL_INVITE_URL or "لینک کانال تنظیم نشده.", chat_id),
            "🛡 اصول ایمنی": lambda: handle_help(chat_id, uid),
            "🪪 شناسه من": lambda: send_message(f"🪪 شناسه Telegram شما: <code>{uid}</code>", chat_id),
            "🔄 بروزرسانی ربات": lambda: handle_start(chat_id, user),
            "🧪 گزارش آزمون": lambda: handle_backtest(chat_id, "BTCUSDT") if _is_admin(uid) else None,
            "🧹 پاکسازی هشدارها": lambda: send_message(f"🧹 {purge_resolved_alert_posts()} پیام پاک شد.", chat_id) if _is_admin(uid) else None,
        }
        if text in quick:
            quick[text]()
            return
        _handle_pending_text(message)
        return

    cmd = text.split()[0].lower().split("@")[0]
    args = text.split()[1:] if len(text.split()) > 1 else []

    if cmd == "/start":
        handle_start(chat_id, user)
    elif cmd == "/help":
        handle_help(chat_id, uid)
    elif cmd == "/analysis":
        handle_ia_menu(chat_id)
    elif cmd == "/setups":
        handle_setups(chat_id)
    elif cmd in {"/membership", "/sub", "/subscribe"}:
        handle_membership(chat_id, user)
    elif cmd in {"/stats", "/results"}:
        handle_strategies(chat_id)
    elif cmd == "/recent":
        handle_recent_signals(chat_id)
    elif cmd == "/guide":
        handle_education(chat_id)
    elif cmd == "/join":
        send_message(mem.CHANNEL_INVITE_URL or "لینک کانال تنظیم نشده.", chat_id)
    elif cmd == "/account":
        handle_membership(chat_id, user)
    elif cmd in {"/id", "/refresh"}:
        if cmd == "/refresh":
            handle_start(chat_id, user)
        else:
            send_message(f"🪪 شناسه Telegram شما: <code>{uid}</code>", chat_id)
    elif cmd == "/status":
        handle_status(chat_id, uid)
    elif cmd == "/backtest" and _is_admin(uid):
        symbol = args[0].upper() if args else "BTCUSDT"
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        style = args[1].upper() if len(args) > 1 else "BOTH"
        handle_backtest(chat_id, symbol, style)
    elif cmd == "/signals" and _is_admin(uid):
        handle_recent_signals(chat_id)
    elif cmd == "/approve" and _is_admin(uid) and args:
        target = int(args[0])
        mem.approve_referral(target)
        invite = mem.CHANNEL_INVITE_URL or "(لینک تنظیم نشده)"
        send_message(f"🎉 عضویتت تأیید شد 💚\n🔗 لینک کانال:\n{invite}", str(target))
        send_message(f"✅ کاربر {target} تأیید شد.", chat_id)
    elif cmd == "/activate" and _is_admin(uid) and len(args) >= 2:
        target, months = int(args[0]), int(args[1])
        mem.activate_plan(target, months)
        send_message(f"💎 عضویت ویژه‌ت ({months} ماهه) فعال شد!", str(target))
        send_message(f"✅ پلن {months} ماهه برای {target} فعال شد.", chat_id)
    elif cmd == "/users" and _is_admin(uid):
        send_message(f"👥 کاربران ثبت‌شده: <b>{mem.count_users()}</b>", chat_id)


def register_bot_menu():
    """Telegram bottom-left Menu command catalog; avoids a permanent keyboard."""
    commands = [
        {"command": "start", "description": "منوی اصلی VivaMon"},
        {"command": "analysis", "description": "تحلیل فوری دارایی"},
        {"command": "setups", "description": "ستاپ‌های فعال"},
        {"command": "recent", "description": "موارد اخیر"},
        {"command": "results", "description": "ژورنال و نتایج"},
        {"command": "status", "description": "وضعیت سامانه"},
        {"command": "guide", "description": "مسیر یادگیری و اصطلاحات"},
        {"command": "join", "description": "ورود به کانال"},
        {"command": "account", "description": "حساب و دسترسی"},
        {"command": "id", "description": "شناسه Telegram من"},
        {"command": "refresh", "description": "بروزرسانی منو"},
    ]
    api_call("setMyCommands", {"commands": commands})
    api_call("setChatMenuButton", {"menu_button": {"type": "commands"}})


# ─── Listener ───

def get_updates(offset=None):
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


def command_listener():
    print("🤖 Telegram bot started - listening for commands")
    try:
        mem.ensure_schema()
    except Exception as e:
        print(f"membership schema init: {e}")
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
    register_bot_menu()
    thread = threading.Thread(target=command_listener, daemon=True)
    thread.start()
    return thread
