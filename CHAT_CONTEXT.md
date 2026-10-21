# 📋 Viva Signal Bot - خلاصه کامل پروژه
# این فایل رو توی چت جدید آپلود کن تا من همه چیز یادم بیاد

## ✅ وضعیت فعلی: v7 Quality-First (2026-08-13)

- اسکن Discovery هر ۱۵ دقیقه، هماهنگ با بسته‌شدن کندل 15M
- مانیتور Approaching/Confirmation هر ۵ دقیقه
- Watchlist پویا بر اساس Bybit Turnover، Relative Volume و Spread
- کانال آموزشی: Setupهای ۶+ با توضیح مفصل و برچسب «تأیید ورود نیست»
- کانال اجرا: فقط Approaching و سپس Confirmed + چارت + مدیریت سرمایه
- Supabase و کانال نتایج: فقط معاملات Confirmed
- Candidateهای تأییدنشده: SQLite محلی موقت، خارج از Supabase
- Swing و Scalp دارای Engine، تایم‌فریم، انقضا و بک‌تست مستقل
- Core setups: LSR، BOS First Pullback، Trendline First Retest، Supply/Demand First Retest، Breaker/IFVG
- RSI Divergence، Engulfing و PinBar فقط Confirmation هستند
- شناسه‌ها با `viva-` و کد SW/SC ادامه دارند
- Backtest جدید Walk-forward، بدون Look-ahead و با Fee/Slippage
- فایل‌های اصلی جدید: `config.py`, `analysis/setups_v7.py`, `analysis/quality_engine.py`, `data/universe.py`, `database/repository_v7.py`, `bot/messages_v7.py`


## 👤 کاربر: Viva (ویوا)
- کانال تلگرام: vivasignalyst-Chanel
- ریپو: https://github.com/vahidlesani/smc-scanner2.git
- دیتابیس: Supabase (PostgreSQL)
- میزبانی: Render

---

## 📅 تاریخچه کار انجام شده

### v5 - ۱۳ استراتژی + شناسه viva
- ✅ ۱۳ استراتژی پرایس اکشن (SMC, RTM, ICT, QM, Engulfing, PinBar, FVG, IFVG, FlipZone, Breakout, OrderBlock, CHoCH, Return Area)
- ✅ شناسه یکتای سیگنال با پیشوند `viva-`
- ✅ توضیحات آموزشی فارسی برای هر استراتژی
- ✅ ذکر کانال `vivasignalyst-Chanel` در همه پیام‌ها

### v6 - MTF + Partial TP + 3-Phase Alerts
- ✅ تحلیل چند تایم‌فریمی: 4H→1H→15M (Swing) | 1H→15M→5M (Scalp)
- ✅ اسکن هر ۵ دقیقه، ۲۴/۷
- ✅ Partial TP: 60% در TP1 + 40% در TP2
- ✅ SL به Breakeven بعد از TP1
- ✅ سیستم ۳ پیامه: Initial → Approaching (80%) → Confirmed
- ✅ داشبورد وب (Flask)
- ✅ ماژول بک‌تست
- ✅ دستورات تلگرام (/help /stats /strategies /backtest /signals /active /status)
- ✅ ۶۰+ نماد

---

## 📁 ساختار فایل‌ها

```
smc-scanner2/
├── main.py                    ← اسکنر اصلی
├── analysis/
│   ├── strategies.py          ← ۱۳ استراتژی
│   ├── mtf.py                 ← Multi-Timeframe
│   ├── backtest.py            ← بک‌تست
│   ├── smc.py                 ← SMC (Order Block, Liquidity)
│   ├── rtm.py                 ← RTM (RBR, DBD, RBD, DBR)
│   ├── ict.py                 ← ICT (OTE, Killzone, MSS)
│   ├── structure.py           ← Swing Points, BOS, CHoCH
│   └── risk.py                ← مدیریت سرمایه
├── bot/
│   ├── telegram_bot.py        ← ارسال سیگنال (v7)
│   └── commands.py            ← دستورات تلگرام
├── database/
│   └── db.py                  ← Supabase + SQLite fallback
├── dashboard/
│   ├── app.py                 ← داشبورد وب (Flask)
│   └── __init__.py
├── data/
│   └── fetcher.py             ← دریافت داده از Bybit
├── requirements.txt
├── Procfile                   ← Render: worker: python main.py
├── runtime.txt                ← python-3.10.11
├── README.md
└── .gitignore
```

---

## 🔄 فلوی سیگنال (مهم!)

```
۱. 🔔 Setup Detected (سیگنال اولیه)
   → ستاپ شکل گرفته ولی تایید نشده
   → وارد نشوید!
   ↓
۲. ⚡ Approaching Entry (80%)
   → قیمت ۸۰% مسیر به Entry رو طی کرده
   → آماده باشید!
   ↓
۳. ✅ Signal Confirmed
   → قیمت از Entry رد شده
   → میتونید وارد شوید!
   ↓
۴. 🥇 TP1 Hit
   → ۶۰% کلوز + SL به Breakeven
   ↓
۵. 🥈 TP2 Hit یا SL Breakeven
   → نتیجه نهایی → کانال نتایج
```

---

## 📊 Partial TP (مهم!)

```
Entry:     0.6845
SL:        0.7018

🥇 TP1:    0.6499  →  60% کلوز → سود محاسبه میشه
🔒 SL:     0.6845  →  Breakeven (بعد از TP1)
🥈 TP2:    0.6326  →  40% باقیمانده → سود نهایی
```

---

## 🔮 استراتژی‌ها

| # | کد | فارسی | توضیح |
|---|-----|-------|-------|
| 1 | SMC | اسمارت مانی | Order Block + Liquidity |
| 2 | RTM | RTM | RBR, DBD, RBD, DBR |
| 3 | ICT | ICT | OTE + Killzone + MSS |
| 4 | QM | کوآزیمودو | بازگشتی قوی |
| 5 | ENGULFING | کندل پوششی | Bullish/Bearish |
| 6 | PINBAR | پین بار | چکش / ستاره |
| 7 | FVG | شکاف قیمتی | Fair Value Gap |
| 8 | IFVG | معکوس شکاف | Inverse FVG |
| 9 | FLIPZONE | فیلیپ زون | S→R یا R→S |
| 10 | BREAKOUT | شکست سطح | Static breakout |
| 11 | ORDERBLOCK | اوردر بلاک | ناحیه سفارشات |
| 12 | CHOCH | تغییر ساختار | Change of Character |
| 13 | RETURN_AREA | بازگشت به ناحیه | Supply/Demand |

---

## 🔄 Multi-Timeframe

```
Swing: 4H (Bias) → 1H (Confirm) → 15M (Entry)
Scalp: 1H (Bias) → 15M (Confirm) → 5M (Entry)
```

---

## 🤖 دستورات تلگرام

| دستور | توضیح |
|-------|-------|
| `/help` | راهنما |
| `/stats` | آمار کلی |
| `/strategies` | آمار استراتژی‌ها |
| `/backtest SYMBOL` | بک‌تست |
| `/signals` | آخرین سیگنال‌ها |
| `/active` | سیگنال‌های فعال |
| `/status` | وضعیت ربات |

---

## ⚙️ تنظیمات Render

### Environment Variables:
```
TELEGRAM_TOKEN = توکن ربات تلگرام
CHAT_ID_SIGNALS = آیدی کانال سیگنال‌ها
CHAT_ID_RESULTS = آیدی کانال نتایج
CHAT_ID = آیدی چت ادمین
DATABASE_URL = لینک Supabase (postgresql://...)
ACCOUNT_SIZE = 1000
RISK_PERCENT = 1.5
```

### Procfile:
```
worker: python main.py
```

---

## 📊 داشبورد وب

فایل: `dashboard/app.py`
پورت: 8080
برای اجرا: `python dashboard/app.py`

شامل:
- آمار کلی (Win Rate, PnL)
- عملکرد هر استراتژی
- لیست سیگنال‌های اخیر
- نتایج بک‌تست

---

## 🗄️ دیتابیس Supabase

### جداول:
1. `signals` - همه سیگنال‌ها
2. `active_signals` - سیگنال‌های فعال
3. `market_memory` - حافظه بازار
4. `strategy_stats` - آمار استراتژی‌ها
5. `backtest_results` - نتایج بک‌تست

### نکته مهم:
جداول خودکار ساخته میشن - نیازی به دستی نیست.

---

## 🔮 ایده‌های آینده

- [ ] Multi-timeframe confirmation بهتر
- [ ] Alert levels (هشدار ۸۰% نزدیکی)
- [ ] Backtest module پیشرفته‌تر
- [ ] Web dashboard شکیل‌تر
- [ ] Auto-close partial TP
- [ ] آمار استراتژی‌ها در تلگرام

---

## 📝 نکات مهم برای چت بعدی

1. ریپو: `https://github.com/vahidlesani/smc-scanner2.git`
2. کانال: `vivasignalyst-Chanel`
3. همه سیگنال‌ها با `viva-` شروع میشن
4. Partial TP: 60% + 40%
5. SL به Breakeven بعد از TP1
6. ۱۳ استراتژی فعال
7. ۶۰+ نماد
8. اسکن هر ۵ دقیقه

---

**ساخته شده توسط Arena.ai Agent Mode**
**تاریخ: 2026-08-13**
**کاربر: Viva**
