# Viva Signal Bot v7 — Quality-First SMC Scanner

ربات تحلیل آموزشی و اجرای تأییدشده بازار قراردادهای USDT در Bybit.

> هدف v7 تعداد زیاد سیگنال نیست. هر Setup باید شواهد ساختاری قابل‌اندازه‌گیری داشته باشد و فقط بعد از Retest و بسته‌شدن کندل تأییدی وارد سابقه Supabase شود.

📢 Channel: **vivasignalyst-Chanel**

## جریان کانال‌ها

| متغیر | کاربرد |
|---|---|
| `CHAT_ID_SIGNALS` | کانال آموزشی؛ Setupهای امتیاز ۶+ با توضیح مفصل و برچسب «تأیید ورود نیست» |
| `CHAT_ID_APPROACHING` | کانال اجرا؛ فقط Approaching و سپس Confirmed + چارت و مدیریت سرمایه |
| `CHAT_ID_RESULTS` | فقط TP1 و نتیجه معاملات Confirmed |
| `CHAT_ID` | ادمین و دستورات ربات |

```text
Educational Setup (not an entry)
        ↓
Approaching Entry Zone (still not confirmed)
        ↓
Closed-candle Confirmation
        ↓
Supabase signals + active_signals
        ↓
TP1 → 60% close → SL to Breakeven
        ↓
TP2 / Breakeven / Stop → Results channel
```

Setupهای تأییدنشده وارد Supabase، Win Rate و کانال نتایج نمی‌شوند. وضعیت موقت آن‌ها در SQLite محلی (`CANDIDATE_DB_PATH`) نگهداری می‌شود.

## موتورهای مستقل

### Swing

```text
1D context → 4H bias → 1H POI → 15M trigger
```

### Scalp

```text
1H context → 15M POI → 5M trigger
```

Scalp دارای فیلتر سخت‌تر Turnover و Spread، انقضای کوتاه‌تر و بک‌تست مستقل است. شناسه سیگنال نوع معامله را نشان می‌دهد:

```text
viva-BTC-SW-LSR-08131230-A1B2
viva-SOL-SC-TLR-08131235-C3D4
```

## Setupهای اصلی v7

1. **LSR** — Liquidity Sweep → Displacement → MSS → fresh OB/FVG → first retest
2. **BOS1** — BOS continuation with displacement → first pullback
3. **TLR** — trendline built from ≥3 pivots → close breakout → first retest
4. **SDR** — multi-touch supply/demand break → flip → first retest
5. **IFVG** — failed opposite FVG → displacement → breaker/IFVG first retest

RSI regular/hidden divergence، Pin Bar، Engulfing، حجم و Session فقط تأیید کمکی‌اند و به‌تنهایی سیگنال ایجاد نمی‌کنند.

## شروط کیفیت

امتیاز ۱۰ بخشی از تصمیم است، اما جای شروط اجباری را نمی‌گیرد:

- هم‌راستایی HTF و موقعیت Premium/Discount
- رویداد ساختاری مختص Setup
- Displacement و شکست با Close
- POI تازه و First Retest
- R/R واقعی بعد از قیمت Confirmed
- Turnover و Spread مناسب
- کندل بسته‌شده LTF برای Confirmation

پیش‌فرض‌ها:

```env
EDUCATIONAL_MIN_SCORE=6
EXECUTION_MIN_SCORE=7
```

Confirmation دیرهنگام که R/R واقعی آن کمتر از 1.3R برای TP1 یا 2R برای TP2 شده باشد رد می‌شود.

## Dynamic Watchlist و Bybit Rate Safety

لیست ثابت نمادها با Watchlist پویا جایگزین شده است:

- قرارداد Linear USDT با وضعیت Trading
- حداقل سابقه Listing
- Top symbols by `turnover24h`
- نمادهای دارای Relative Volume بالا
- فیلتر Spread و حداقل گردش مالی
- محدودیت سخت‌تر برای Scalp

داده هر تایم‌فریم یک‌بار در هر Scan گرفته و بین تمام Detectorها به اشتراک گذاشته می‌شود. Client دارای Cache، Retry، Backoff، Throttle و Endpoint fallback است.

Bybit برای برخی کشورها و بعضی IP Rangeهای دیتاسنتر پاسخ 403 می‌دهد؛ این خطا Rate Limit نیست. Blueprint به‌صورت پیش‌فرض Region فرانکفورت را درخواست می‌کند. در صورت استفاده از Static Egress مجاز می‌توان `BYBIT_PROXY_URL` را فقط در Secrets پنل Render تنظیم کرد؛ Credentials پروکسی نباید داخل Git قرار گیرند. قوانین محل استقرار و شرایط استفاده Bybit باید رعایت شوند.

```env
FULL_SCAN_MINUTES=15
MONITOR_MINUTES=5
SCAN_OFFSET_MINUTE=1
```

اسکن کامل در `:01/:16/:31/:46 UTC`، یک دقیقه پس از بسته‌شدن کندل 15M انجام می‌شود. مانیتور Candidateها با یک درخواست برای هر نماد/تایم‌فریم فعال اجرا می‌شود.

## مدیریت سرمایه

- ریسک بر اساس Grade کیفیت، با سقف `MAX_RISK_PERCENT`
- Leverage بر اساس فاصله واقعی SL و سبک معامله؛ Score اهرم را افزایش نمی‌دهد
- سقف Margin
- حداکثر معاملات هم‌زمان
- محدودیت پوزیشن‌های هم‌جهت و همبسته آلت‌کوین‌ها
- Daily Loss Limit
- TPهای ساختاری با حداقل R/R
- Fee و Slippage در محاسبات سود و بک‌تست
- Partial TP: 60/40 و انتقال SL به BE بعد از TP1

## بک‌تست v7

بک‌تست از همان Setup Engine لایو استفاده می‌کند:

- HTF bias در هر Timestamp تاریخی
- بدون استفاده از آینده
- Pagination بیش از ۱۰۰۰ کندل
- انتظار برای Retest و Confirmation آینده
- قانون محافظه‌کارانه Stop-first در کندل مبهم
- Fee و Slippage
- گزارش Win Rate، Expectancy، Profit Factor و Max Drawdown

```text
/backtest BTCUSDT SWING
/backtest BTCUSDT SCALP
/backtest BTCUSDT BOTH
```

## نصب

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py
```

ابزارهای نگهداری:

```bash
# تست دسترسی Bybit در محیط Deploy
python scripts/diagnose_bybit.py

# فقط نمایش تعداد داده‌های قدیمی تأییدنشده
python scripts/purge_legacy_unconfirmed.py

# حذف بعد از Backup و بررسی Dry-run
python scripts/purge_legacy_unconfirmed.py --apply
```

Dashboard:

```bash
python dashboard/app.py
# or
gunicorn --bind 0.0.0.0:8080 dashboard.app:app
```

## متغیرهای محیطی اصلی

```env
TELEGRAM_TOKEN=
CHAT_ID_SIGNALS=
CHAT_ID_APPROACHING=
CHAT_ID_RESULTS=
CHAT_ID=
DATABASE_URL=postgresql://...

ACCOUNT_SIZE=1000
RISK_PERCENT=1.0
MAX_RISK_PERCENT=1.25
MAX_MARGIN_PERCENT=25
MAX_OPEN_TRADES=5
MAX_CORRELATED_TRADES=2
DAILY_LOSS_LIMIT_PERCENT=3

FULL_SCAN_MINUTES=15
MONITOR_MINUTES=5
EDUCATIONAL_MIN_SCORE=6
EXECUTION_MIN_SCORE=7

WATCHLIST_TOP_TURNOVER=50
WATCHLIST_TOP_RELATIVE_VOLUME=20
WATCHLIST_MAX_SYMBOLS=70
WATCHLIST_MIN_TURNOVER_USD=5000000
SCALP_MIN_TURNOVER_USD=20000000
CANDIDATE_DB_PATH=/tmp/viva_candidates.db
```

برای دوام Candidateها در Restart، در Render یک Persistent Disk متصل و `CANDIDATE_DB_PATH` روی مسیر آن تنظیم شود. هیچ Token یا Secret نباید داخل Git، README یا فایل `.env` Commit شود.

## Render

`render.yaml` شامل دو سرویس است:

- `viva-signal-worker`
- `viva-signal-dashboard`

Secrets باید از پنل Render برای هر سرویس تنظیم شوند. Dashboard فقط آمار سیگنال‌های Confirmed را نمایش می‌دهد و endpoint سلامت آن `/health` است.

## هشدار

این پروژه ابزار تحلیل و آموزش است و تضمین سود یا Win Rate مشخص ارائه نمی‌کند. هر نسخه استراتژی باید با داده کافی، Out-of-sample و معیارهای Expectancy/Drawdown ارزیابی شود.
