# 🚀 SMC Scanner v6 - vivasignalyst-Chanel

ربات تحلیلگر خودکار بازار ارز دیجیتال با ۱۳ استراتژی پیشرفته

📢 کانال: **vivasignalyst-Chanel**

## ✨ ویژگی‌های v6

- 🆔 شناسه یکتای سیگنال با پیشوند `viva-`
- 🔮 ۱۳ استراتژی پیشرفته پرایس اکشن
- 🔄 تحلیل چند تایم‌فریمی: 4H → 1H → 15M
- ⏱ اسکن هر ۵ دقیقه، ۲۴ ساعته، ۷ روز هفته
- 📊 Partial TP: 60% در TP1 + 40% در TP2
- 🔒 SL به Breakeven بعد از TP1
- 🔔 سیستم ۳ پیامه: اولیه → نزدیک شدن → تایید
- 📚 توضیحات آموزشی فارسی برای هر استراتژی
- 📊 داشبورد وب ساده و شکیل
- 🧪 ماژول بک‌تست

## 🔄 سیستم ۳ پیامه سیگنال

```
۱. 🔔 سیگنال اولیه (Setup Detected)
   ↓ ستاپ شکل گرفته ولی تایید نشده
   ↓ وارد نشوید!

۲. ⚡ هشدار نزدیک شدن (Approaching Entry)
   ↓ قیمت ۸۰% مسیر به Entry رو طی کرده
   ↓ آماده باشید!

۳. ✅ تایید ورود (Signal Confirmed)
   ↓ قیمت از Entry رد شده
   ↓ میتوانید وارد شوید!

۴. 🥇 TP1 Hit + SL to BE
   ↓ ۶۰% کلوز شد
   ↓ SL به Breakeven منتقل شد

۵. 🥈 TP2 Hit یا SL Breakeven
   ↓ نتیجه نهایی → کانال نتایج
```

## 📊 Partial Take Profit

```
Entry:     0.6845
SL:        0.7018

🥇 TP1:    0.6499  →  60% کلوز
🔒 SL:     0.6845  →  Breakeven (بعد از TP1)
🥈 TP2:    0.6326  →  40% باقیمانده

سود TP1 = position × 60% × (Entry - TP1)
سود TP2 = position × 40% × (Entry - TP2)
```

## 🔄 Multi-Timeframe

```
Swing: 4H (Bias) → 1H (Confirm) → 15M (Entry)
Scalp: 1H (Bias) → 15M (Confirm) → 5M (Entry)
```

## 📊 استراتژی‌ها

| # | استراتژی | نماد | توضیح |
|---|----------|------|-------|
| 1 | SMC | 📊 | اسمارت مانی - OB + نقدینگی |
| 2 | RTM | 🔷 | Rally-Base-Drop |
| 3 | ICT | 💎 | OTE + Killzone |
| 4 | QM | 🔮 | کوآزیمودو - بازگشتی قوی |
| 5 | Engulfing | 🔥 | کندل پوششی |
| 6 | PinBar | 📌 | چکش / ستاره دنباله‌دار |
| 7 | FVG | 📐 | شکاف قیمتی |
| 8 | IFVG | 🔄 | معکوس شکاف |
| 9 | FlipZone | 🔁 | تبدیل حمایت↔مقاومت |
| 10 | Breakout | 💥 | شکست سطح استاتیک |
| 11 | OrderBlock | 🧱 | ناحیه سفارشات بزرگ |
| 12 | CHoCH | ⚡ | تغییر ساختار |
| 13 | Return Area | 🎯 | بازگشت به ناحیه |

## 🆔 فرمت شناسه سیگنال

```
viva-SUI-RTM-08121624-31DE
│    │   │   │        │
│    │   │   │        └── کد تصادفی
│    │   │   └── تاریخ و زمان (MMDDHHMM)
│    │   └── استراتژی
│    └── نماد
└── پیشوند vivasignalyst
```

## ⚙️ تنظیمات

### متغیرهای محیطی
```env
TELEGRAM_TOKEN=your_bot_token
CHAT_ID_SIGNALS=channel_for_signals
CHAT_ID_RESULTS=channel_for_results
CHAT_ID=admin_chat_id
DATABASE_URL=postgresql://...  # Supabase
ACCOUNT_SIZE=1000
RISK_PERCENT=1.5
DASHBOARD_PORT=8080
```

## 🚀 نصب و اجرا

```bash
# نصب وابستگی‌ها
pip install -r requirements.txt

# اجرای اسکنر
python main.py

# اجرای داشبورد (در ترمینال جدا)
python dashboard/app.py
```

## 📊 داشبورد

داشبورد وب ساده و شکیل با:
- آمار کلی (کل سیگنال‌ها، برد، باخت، Win Rate)
- عملکرد هر استراتژی
- لیست سیگنال‌های اخیر
- نتایج بک‌تست
- Auto-refresh هر ۶۰ ثانیه

## 🧪 بک‌تست

ماژول بک‌تست برای بررسی عملکرد استراتژی‌ها:
- تست روی داده‌های تاریخی
- محاسبه Win Rate, PnL, Max Drawdown
- Partial TP simulation (60/40)
- SL to Breakeven after TP1

## 📊 مدیریت سرمایه

| امتیاز | ریسک | اهرم | کیفیت |
|--------|------|------|-------|
| 9-10 | 2.0% | 15-20x | 🏆 فوق‌العاده |
| 7-8 | 1.5% | 12-15x | ⭐ عالی |
| 5-6 | 1.0% | 8-12x | 👍 قابل قبول |
| 3-4 | 0.5% | 5-8x | ⚠️ متوسط |
| 1-2 | 0.25% | 5x | ❌ ضعیف |

## 📝 نکات مهم

- هر سیگنال یک شناسه یکتا با پیشوند `viva-` دارد
- سیگنال اولیه فقط هشدار است - وارد نشوید
- منتظر پیام Approaching و سپس Confirmation باشید
- بعد از TP1، SL به Breakeven منتقل می‌شود
- ۶۰% در TP1 و ۴۰% در TP2 کلوز می‌شود
- همیشه چارت را خودتان بررسی کنید

---

📢 **vivasignalyst-Chanel**
