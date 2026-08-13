# گزارش اجرای کامل Viva Signal Bot v7

## وضعیت

- Branch: `arena/v7-quality-engine`
- Commit نهایی: خروجی `git log -1 --oneline`
- نام کانال: `vivasignalyst-Chanel`
- شناسه‌ها: `viva-{SYMBOL}-{SW|SC}-{SETUP}-{TIME}-{RANDOM}`

## ۱. پایداری و Bybit

- اسکن کامل از ۵ دقیقه به ۱۵ دقیقه تغییر کرد.
- زمان اسکن با بسته‌شدن کندل 15M هماهنگ شد: `:01/:16/:31/:46 UTC`.
- مانیتور Candidateها و معاملات Confirmed هر ۵ دقیقه مستقل اجرا می‌شود.
- داده‌های 1D/4H/1H/15M/5M برای هر نماد فقط یک‌بار گرفته و بین Detectorها به اشتراک گذاشته می‌شود.
- Cache، Throttle، Retry، Backoff، پاسخ 429 و Endpoint fallback اضافه شد.
- Pagination برای بیش از ۱۰۰۰ کندل اضافه شد.
- ابزار `scripts/diagnose_bybit.py` برای تست محیط Deploy اضافه شد.
- Render Blueprint روی Region فرانکفورت تنظیم شد؛ Static egress مجاز با Secret اختیاری `BYBIT_PROXY_URL` قابل تنظیم است.

## ۲. Dynamic Watchlist

- لیست ثابت به Fallback تبدیل شد.
- قراردادهای فعال Linear USDT از Bybit دریافت می‌شوند.
- فیلتر سابقه Listing، Turnover، Spread و نقدشوندگی اجرا می‌شود.
- Top 50 گردش مالی و Top 20 Relative Volume انتخاب می‌شوند.
- نمادهای موقتاً پرحجم حتی اگر Major نباشند وارد Watchlist می‌شوند.
- Scalp دارای حداقل Turnover و حداکثر Spread سخت‌گیرانه‌تر است.

## ۳. موتورهای مستقل

### Swing

`1D context → 4H bias → 1H POI → 15M trigger`

### Scalp

`1H context → 15M POI → 5M trigger`

Expiry، نقدشوندگی، R/R، تایم‌فریم Trigger، شناسه و بک‌تست این دو Engine مستقل هستند.

## ۴. Setupهای کیفیت‌محور

- `LSR`: Liquidity Sweep → Displacement → MSS → OB/FVG → First Retest
- `BOS1`: BOS Continuation → Fresh POI → First Pullback
- `TLR`: Trendline با حداقل سه Pivot → Close Break → First Retest
- `SDR`: شکست Supply/Demand چندواکنشی → Flip → First Retest
- `IFVG`: شکست FVG مخالف → Breaker/Inverse FVG → First Retest

OTE، Premium/Discount، RSI regular/hidden divergence، Session، Volume، Engulfing و Pin Bar به‌عنوان تأیید استفاده می‌شوند؛ موارد ضعیف به‌تنهایی سیگنال اجرایی نمی‌سازند.

## ۵. امتیاز و Mandatory Gates

- کانال آموزشی: پیش‌فرض ۶+
- کانال اجرا: پیش‌فرض ۷+ و عبور از تمام شروط اجباری
- Score نمی‌تواند نبود Sweep/BOS، Displacement، Fresh POI، R/R یا نقدشوندگی را جبران کند.
- Entry نهایی برابر Close کندل Confirmation است، نه Midpoint قدیمی ناحیه.
- اگر R/R بعد از Confirmation به کمتر از 1.3R/2R کاهش یافته باشد، ورود رد می‌شود.

## ۶. جریان تلگرام

### کانال آموزشی (`CHAT_ID_SIGNALS`)

- پیام مفصل برای هر Evidence
- عنوان «تحلیل آموزشی | ستاپ در حال بررسی»
- برچسب واضح «این پیام تأیید ورود نیست»
- ناحیه بررسی و سطح ابطال، بدون اهرم و دستور ورود

### کانال اجرا (`CHAT_ID_APPROACHING`)

- Approaching کوتاه و واضح
- سپس Confirmed با چارت Annotated
- دلایل شماره‌گذاری‌شده، Entry/SL/TP، R/R و مدیریت سرمایه

### کانال نتایج (`CHAT_ID_RESULTS`)

- فقط TP1 و نتیجه معاملات Confirmed
- Candidate کنسل‌شده در Win Rate حساب نمی‌شود.

## ۷. دیتابیس

- Educational Candidate در Supabase ذخیره نمی‌شود.
- Candidate موقت در SQLite محلی نگهداری می‌شود.
- Confirmation تکنیکال ابتدا با وضعیت داخلی `AWAITING_PUBLICATION` و `confirmation_sent=FALSE` در `signals` و `active_signals` Stage می‌شود؛ این ردیف تاریخچه اجرایی محسوب نمی‌شود.
- فقط بعد از موفقیت هر دو جزء چارت و متن کامل Telegram، Publication Gate به‌صورت اتمیک به `confirmation_sent=TRUE` و `status='CONFIRMED'` تغییر می‌کند.
- Migrationهای Additive و Idempotent برای Supabase اضافه شدند؛ داده‌های قدیمی حذف نمی‌شوند.
- Dashboard، API، Portfolio Guard، Lifecycle Monitor و آمار فقط ردیف دارای نسخه فعلی v7، `confirmed_at`، `status='CONFIRMED'` و `confirmation_sent=TRUE` را می‌پذیرند.
- ردیف‌های Legacy و Confirmationهای منتشرنشده از مانیتور و آمار v7 قرنطینه‌اند.
- اسکریپت Dry-run پاک‌سازی داده قدیمی: `scripts/purge_legacy_unconfirmed.py`.

## ۸. چرخه نتیجه

- کندل‌ها به‌ترتیب زمانی بررسی می‌شوند.
- استفاده اشتباه از `.any()` روی کل تاریخ حذف شد.
- ابهام لمس SL و TP در یک کندل با قانون محافظه‌کارانه Stop-first حل می‌شود.
- TP1 → بستن ۶۰٪ → SL باقیمانده به Entry.
- TP2 یا BE نتیجه را می‌بندد.
- Fee و Slippage در PnL خالص لحاظ می‌شوند.

## ۹. مدیریت سرمایه

- Score فقط Risk Grade را مشخص می‌کند و Leverage را زیاد نمی‌کند.
- Leverage بر اساس فاصله SL و Style محاسبه می‌شود.
- سقف Margin، حداکثر معامله باز، محدودیت آلت‌کوین‌های همبسته و Daily Loss Limit اضافه شد.
- حجم پوزیشن در صورت نیاز برای رعایت سقف Margin کاهش می‌یابد.
- TPها ساختاری‌اند و در قیمت اجرای واقعی دوباره R/R آن‌ها بررسی می‌شود.

## ۱۰. بک‌تست

- موتور لایو و بک‌تست مشترک شد.
- Bias در هر Timestamp تاریخی محاسبه می‌شود؛ Look-ahead قدیمی حذف شد.
- Retest و Confirmation باید در کندل‌های آینده رخ دهند.
- Fee، Slippage، Stop-first و Pagination اضافه شدند.
- Swing و Scalp مستقل‌اند.
- Win Rate، Expectancy، Profit Factor، Max Drawdown و Average Bars گزارش می‌شوند.
- Aggregate هر Run در `backtest_runs` ذخیره و در Dashboard نمایش داده می‌شود.

## ۱۱. Dashboard و Deploy

- Dashboard فقط Confirmedها را نمایش می‌دهد.
- Style سیگنال و معیارهای جدید Backtest اضافه شدند.
- `/health` اضافه شد.
- `render.yaml` شامل Worker و Web Dashboard است.
- GitHub Actions برای Compile و Unit Tests اضافه شد.

## ۱۲. تست‌ها

- Compile تمام فایل‌ها: موفق
- Import تمام Moduleها: موفق
- ۱۲ Unit Test: موفق
- SQLite migration/persistence و Publication Gate: موفق
- ممنوعیت نمایش/مانیتور Confirmation منتشرنشده: موفق
- قرنطینه Legacy از Lifecycle، Dashboard و Statistics: موفق
- Fail-closed بودن Result sender بدون Publication Proof: موفق
- Retry انتشار بدون تکرار چارت: موفق
- TP1 سپس Breakeven به‌ترتیب زمانی: موفق
- Dashboard و تمام APIها: HTTP 200
- Main startup/shutdown smoke test: موفق
- Secret scan: پاک

## اقدام‌های Deploy

1. توکن GitHub افشاشده را Revoke کنید.
2. Branch/Commit را با احراز هویت امن Push کنید.
3. در Render، Blueprint را Apply و Secrets را تنظیم کنید.
4. برای Candidate Store یک Persistent Disk اختیاری متصل کنید.
5. `python scripts/diagnose_bybit.py` را در محیط Render اجرا کنید.
6. ابتدا حداقل یک هفته Shadow/Educational Mode را بررسی کنید.
7. قبل از افزایش Risk، برای هر Setup نمونه Out-of-sample کافی جمع‌آوری شود.

هیچ استراتژی تضمین Win Rate یا سود نمی‌دهد؛ معیار ارتقا باید Expectancy مثبت، Profit Factor مناسب، Drawdown کنترل‌شده و Sample Size کافی باشد.
