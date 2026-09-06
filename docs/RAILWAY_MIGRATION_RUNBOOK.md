# چک‌لیست مهاجرت امن به اکانت/پروژهٔ جدید Railway

> هدف: انتقال کامل سرویس Viva Signals به اکانت Railway جدید، **بدون قطعیِ طولانی، بدون تداخل ربات، بدون نشت سکرت، و با حفظ کامل تاریخچهٔ دیتابیس.**

## ⚠️ سه قانون طلایی قبل از شروع
1. **ربات long-polling است** (`getUpdates` در `bot/commands.py`). **هرگز دو سرویس (قدیم و جدید) هم‌زمان اجرا نشوند** — وگرنه خطای 409 و از دست رفتن دستورها. کات‌اور: اول قدیمی کامل متوقف، بعد جدید استارت.
2. **سکرت فقط در Variables/Secretها** — هیچ‌وقت در گیت/کامیت. (`.env` و `*.db` از قبل در `.gitignore` هستند ✅)
3. **دیتابیس Postgres ماندگار است؛ SQLite روی `/tmp` با هر ری‌دیپلوی پاک می‌شود.** در پروژهٔ جدید حتماً Volume دائمی وصل کن.

---

## مرحله ۰ — پیش‌نیازها
- اکانت/ورک‌اسپیس جدید Railway.
- ریپو متصل: `vahidlesani/smc-scanner2` (برنچ حاوی منطق جدید قطبیت).
- دسترسی/توکن‌ها: `TELEGRAM_TOKEN`, `GEMINI_API_KEY`, `BYBIT_PROXY_URL` (در صورت استفاده)، شناسهٔ چهار چت، آدرس‌های ولت/رفرال.

## مرحله ۱ — ساخت سرویس و دیتابیس در پروژهٔ جدید
1. پروژهٔ جدید بساز و یک سرویس **GitHub Repo** از همان ریپو/برنچ ایجاد کن.
2. یک **PostgreSQL database service** جدید داخل همین پروژه بساز (Railway managed Postgres).
3. یک **Volume** بساز و به سرویس اپ وصل کن؛ مسیر پیشنهادی: `/data`.

## مرحله ۲ — مهاجرت کامل دیتابیس (انتقال تاریخچه)
اسکریپت آماده است: `scripts/migrate_postgres.sh`.

1. روی یک ماشین امن (که `pg_dump`/`pg_restore`/`psql` دارد) هر دو DATABASE_URL را ست کن:
   ```bash
   export OLD_DATABASE_URL='postgresql://...قدیمی...'
   export NEW_DATABASE_URL='postgresql://...جدید...'
   bash scripts/migrate_postgres.sh
   ```
2. اسکریپت: dump کامل (schema+data) → restore در جدید → **شمارش رکورد هر جدول و مقایسهٔ قدیم/جدید** → پاک‌کردن امن فایل dump بعد از موفقیت.
3. جدول‌هایی که اعتبارسنجی می‌شوند: `signals`, `active_signals`, `market_memory`, `strategy_stats`, `backtest_results`, `signal_symbol_locks`, `signal_telegram_events`, `signal_public_code_registry`, `backtest_runs`.
4. اگر mismatch داد، اسکریپت خروجی non-zero می‌دهد و dump را برای بررسی نگه می‌دارد — جلو نرو تا علت حل شود.

> گزینهٔ B جایگزین (اگر فعلاً فقط می‌خواهی سرویس بالا بیاید): سرویس جدید را موقتاً به همان Postgres قدیمی وصل کن (`DATABASE_URL` قدیم) و بعداً مهاجرت کامل را انجام بده؛ ولی برای رها شدن کامل از اکانت قدیم در نهایت باید گزینهٔ کامل اجرا شود.

## مرحله ۳ — Variables سرویس جدید
این‌ها را از سرویس قدیم به Variables سرویس جدید منتقل کن (و سه‌نقطه‌ای‌ها را کامل کپی کن):

**هسته و ربات**
- `TELEGRAM_TOKEN`
- `CHAT_ID`, `CHAT_ID_SIGNALS`, `CHAT_ID_APPROACHING`, `CHAT_ID_RESULTS`
- `CHANNEL_NAME` (و در صورت استفاده `CHANNEL_INVITE_URL`, `CHART_BRAND_NAME`, `CHART_BRAND_HANDLE`, `WALLET_*`, `REF_*`)

**دیتابیس / فایل دائمی**
- `DATABASE_URL` = رشتهٔ اتصال Postgres **جدید**
- `CANDIDATE_DB_PATH` = `/data/viva_candidates.db`  ← روی Volume دائمی

**ستاپ/منطق (جدید)**
- `PINVAL_POLARITY_GATE_ENABLED=true`
- `PINVAL_POLARITY_NEAR_ATR=1.2`
- `PINVAL_POLARITY_BLOCK_ATR=1.8`
- `PINVAL_POLARITY_BREAKOUT_BODY_ATR=0.5`
- `PINVAL_POLARITY_BYPASS_LEGACY_FILTERS=true`
- هنگام استقرار منطق جدید، فیلترهای وصله‌ای قدیمی دیگر لازم نیستند:
  `PINVAL_ALLOWED_DIRECTIONS` و `PINVAL_ALLOWED_ZONE_KINDS` را **حذف یا خالی** کن (گیت قطبیت خودش تصمیم می‌گیرد و SHORTهای درست را آزاد می‌کند).

**سایر در صورت استفاده**
- `GEMINI_API_KEY`, `GEMINI_MODEL`
- `BYBIT_PROXY_URL`
- `LIVE_STYLES`, `CORE_V7_SETUPS_ENABLED`, `VIVA_TLBREAK_ENABLED`, `EXPERIMENTAL_*`
- برای کنترل از داخل ربات روی پروژهٔ جدید:
  `RAILWAY_PROJECT_ID`, `RAILWAY_ENVIRONMENT_ID`, `RAILWAY_SERVICE_ID` و یک **توکن جدید** `RAILWAY_CONTROL_TOKEN` (توکن قدیمی متعلق به اکانت قدیم را با هماهنگی باطل کن).

> Railway مقدار `PORT` را خودش تزریق می‌کند؛ لازم نیست دستی ست شود.

## مرحله ۴ — استقرار
1. فایل `railway.json` (اضافه شد) استقرار تک‌سرویسه را تعریف می‌کند:
   - `startCommand: python combined_service.py` (Waitress + اسکنر در یک پروسه، روی `$PORT`).
   - `healthcheckPath: /health`، restart policy روشن.
2. مطمئن شو سرویس با همین دستور بالا می‌آید و روی `0.0.0.0:$PORT` گوش می‌دهد (`combined_service.py` همین‌طور است ✅).
3. Volume روی `/data` سوار باشد و `CANDIDATE_DB_PATH=/data/viva_candidates.db`.

## مرحله ۵ — برش ترافیک (cutover) — به همین ترتیب
1. روی سرویس **قدیمی**: استقرار را متوقف/سرویس را پایین بیاور (تا پولر تلگرام آزاد شود).
2. مطمئن شو هیچ نمونه‌ای از ربات روی اکانت قدیم اجرا نمی‌شود (وگرنه 409).
3. سرویس **جدید** را Deploy/Start کن.
4. در لاگ دنبال این خطوط بگرد:
   - `🌐 Viva combined service listening on 0.0.0.0:<port>`
   - `⚡ Realtime execution monitor active`
   - `Discovery scan started for ... dynamic symbols`
5. سلامت داشبورد: باز کردن `/health` سرویس جدید (HTTP 200).
6. در تلگرام یک دستور بده (مثلاً `/status`) و از پاسخ مطمئن شو.

## مرحله ۶ — اعتبارسنجی پس از برش
- شمارش رکوردها در داشبورد جدید با قدیم برابر باشد (همان خروجی مرحله ۲).
- یک سیکل کامل Discovery رد شود و در صورت وجود کاندیدا، پیام آموزشی در کانال آموزشی بیاید.
- تأیید کن `CANDIDATE_DB_PATH` روی Volume است (با یک ری‌استارت، کاندیداهای در حال انتظار پاک نشوند).
- مانیتور TP/SL زنده برای معاملات CONFIRM شده کار کند.

## مرحله ۷ — پاک‌سازی و امنیت
- توکن Railway قدیمی (`RAILWAY_CONTROL_TOKEN` قدیم) را **باطل/چرخش** کن.
- بعد از چند روز پایداری، سرویس و (در صورت تصمیم) Postgres قدیمی را حذف کن.
- هیچ‌وقت سکرتی در گیت کامیت نکن؛ در صورت لو رفتن هر توکن حین جابه‌جایی، فوراً همان توکن را rotate کن.

---

### نکته برای فعال‌سازی منطق جدید پین‌وال
کد جدید گیت قطبیت پشت فلگ است و **پیش‌فرض روشن** است (`PINVAL_POLARITY_GATE_ENABLED=true`)، ولی توصیهٔ فرایندی:
1. اول با همان دادهٔ واقعی، بک‌تست/پِیپرتدینگ روی سه رژیم (صعودی/رنج/اصلاح نزولی) تأیید شود (هدف بازگشت وین‌ریت اصلاح نزولی به ~۷۵٪+).
2. سپس فیلترهای وصله‌ای قدیمی (`PINVAL_ALLOWED_DIRECTIONS`, `PINVAL_ALLOWED_ZONE_KINDS`) حذف/خالی شوند تا SHORTهای درستِ روی عرضه آزاد شوند.
3. اگر نیاز به خاموش‌کردن موقت بود: `PINVAL_POLARITY_GATE_ENABLED=false` منطق قدیمی (بدون گیت) را برمی‌گرداند.
