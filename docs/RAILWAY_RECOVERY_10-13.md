# Railway Recovery — 10-13 («ریلوی رو درست کن»)

## شواهد از داخل سندباکس (قبل از هر اقدام)
- `curl https://smc-scanner2-production.up.railway.app/` و `/app` و `/health` →
  **HTTP 404 "Application not found"**. یعنی پشت دامنه هیچ سرویس فعالی نیست
  (کرش نبودگی 502/503 می‌دهد؛ 404 یعنی سرویس/دیپلوی فعال روی دامنه نیست).
- دیتابیس امن است: Supabase جدای از Railway است (`docs/MIGRATION_KIT.md`)؛
  دمپ محلی: `backup/viva_db_dump/`.
- کد تعمیر آماده است: کامیت `c513f3f` روی شاخهٔ `repair/main-10-13`
  (والد = `6629af5` یعنی main فعلی گیت‌هاب) + باندل کوچک
  `backup/viva-repair-10-13.bundle` (۱۱۲KB).
- سندباکس هیچ توکن Railway/GitHub ندارد. توجه: بر خلاف یادداشت قدیمی
  `ops/railway/README.md`، شبکهٔ سندباکس به `backboard.railway.com` اکنون
  **باز** است (تست ۱۰-13: HTTP 200) → با یک Account/Project token معتبر،
  کوئری GraphQL مستقیم از اینجا ممکن است؛ مسیر بدون‌توکن همان ورک‌فلو
  `railway-ops` روی GitHub Actions است.

## گام ۱ — تشخیص ۶۰ ثانیه‌ای (داشبورد Railway، پروژهٔ gleaming-sparkle)
| آنچه می‌بینید | یعنی | اقدام |
|---|---|---|
| A) پروژه/سرویس نیست | حذف شده ( دستی یا پایان trial ) | New Service ← Deploy from GitHub repo ← branch `main` ← متغیرها طبق جدول `ops/railway/README.md` ← دامنهٔ عمومی پورت 8080 |
| B) سرویس هست، آخرین دیپلوی قرمز/crashloop | کد یا env خراب | Logs دیپلوی را ببینید؛ Redeploy آخرین کامیت سبز |
| C) سرویس سبز است ولی دامنه 404 | دامنهٔ عمومی detach شده | Settings ← Networking ← تولید/اتصال دوبارهٔ public domain (پورت 8080) |
| D) Account/Plan suspended | billing/trial | Account ← Plan ← فعال‌سازی؛ سرویس با آخرین دیپلوی برمی‌گردد |

بعد از هر مسیر: `curl -sS https://smc-scanner2-production.up.railway.app/health`
باید 200 بدهد و `boot_sha` برابر کامیت مورد نظر باشد.

## گام ۲ — اگر می‌خواهید خودم انجامش دهم (پیشنهاد من)
یک PAT تازهٔ GitHub (scope: `repo` + `workflow`) بدهید. ترتیب کار من:
1. پوش `c513f3f` به `repair/main-10-13` (یا main، با حکم شما)؛
2. اجرای Actions ← `railway-ops` با `action=access` و خواندن وضعیت
   پروژه/سرویس/دیپلوی/متغیرها از لاگ ورک‌فلو؛
3. تعمیر مطابق جدول بالا (redeploy / متغیر / دامنه) از طریق همان ورک‌فلو؛
4. گزارش نهایی: health 200 + boot_sha + مصرف ۷ روز (`action=usage`).
توکن Railway هرگز به چت نمی‌آید — فقط در GitHub Secrets می‌ماند.

## گام ۳ — بدون توکن دادن به من
GitHub ← Actions ← `railway-ops` ← Run workflow (فایل
`ops/railway/request.json` با `action=access` و nonce بالا رفته) ←
لاگ اجرا را اینجا پیست کنید. اگر secretِ `RAILWAY_TOKEN` منقضی بود:
Railway ← Settings ← Tokens ← Project Token تازه ← جایگذاری در Secrets.

## خط قرمز مصرف (بعد از بالا آمدن سرویس نباید نقض شود)
پیش‌فرض‌های کد اکنون کم‌مصرف‌اند و env جدید نمی‌خواهند:
monitor idle = 30s (`main.py`)، `WEB_THREADS=2` (`combined_service.py`)،
`line_watch._MIN_INTERVAL=30`، کش بایت چارت 12 slot
(`docs/RAILWAY_CONSUMPTION.md`). هر دیپلوی باید این‌ها را نگه دارد.
