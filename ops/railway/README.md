# دسترسی امن به Railway با CLI (R62-ARENA ops)

> سندباکس آرنا هیچ مسیر شبکه‌ای به Railway ندارد (اتصال به `backboard.railway.com` و
> `railway.com` بسته است). برای همین کار با CLI روی **GitHub Actions** اجرا می‌شود. توکن فقط
> در Secrets گیت‌هاب نگه داشته می‌شود و هیچ‌وقت در چت، ریپو یا لاگ نمی‌آید.

## ۱) یک‌بار: ساخت توکن و گذاشتن در GitHub (فقط خودتان)
1. Railway ← پروژهٔ فعلی ← **Settings → Tokens** ← یک **Project Token** برای محیط
   `production` بسازید (نام: `viva-ops-migration`).
2. GitHub ← `vahidlesani/smc-scanner2` ← **Settings → Secrets and variables → Actions →
   New repository secret**:
   | نام | مقدار | لازم؟ |
   |---|---|---|
   | `RAILWAY_TOKEN` | همان Project Token | بله |
   | `BACKUP_PASSPHRASE` | یک رمز طولانی (≥ ۲۴ کاراکتر) که **فقط خودتان** نگه می‌دارید | برای بک‌آپ |
   | `RAILWAY_API_TOKEN` | Account Token (Account Settings → Tokens) | اختیاری: مصرف کل اکانت |
3. بعد از انتقال به اکانت جدید، توکن قدیمی را در Railway **Revoke** کنید.

## ۲) اجرا (من از داخل آرنا این کار را انجام می‌دهم)
فایل `ops/railway/request.json` را ویرایش می‌کنم (`action` + بالا بردن `nonce`) و پوش می‌کنم.
ورک‌فلو `railway-ops` روی GitHub اجرا می‌شود و من گزارش را از لاگ آن می‌خوانم.

| action | کار | خروجی |
|---|---|---|
| `access` | پروژه، محیط‌ها، سرویس‌ها، آخرین دیپلوی، Volumeها، **نام** متغیرها | لاگ (بدون مقدار) |
| `usage` | CPU / RAM / شبکه / دیسک هر سرویس در ۷ روز + روند روزانه | لاگ |
| `backup` | متغیرهای همهٔ سرویس‌ها + `pg_dump` دیتابیس، رمزگذاری‌شده با AES-256 | آرتیفکت ۷روزه `viva-railway-backup-encrypted` |
| `deploy` | اجرای کل تست‌ها و سپس `railway up --service <name>` | لاگ |

از UI گیت‌هاب هم می‌شود اجرا کرد: Actions ← railway-ops ← Run workflow (بعد از merge در main).

## ۳) امنیت بک‌آپ
- همهٔ مقدارها پیش از هر چاپی با `::add-mask::` پوشانده می‌شوند.
- آرشیو فقط به شکل `*.tgz.gpg` (AES-256 متقارن) از runner خارج می‌شود. فایل‌های خام با `shred`
  پاک می‌شوند. آرتیفکت بعد از ۷ روز خودکار حذف می‌شود.
- دانلود: GitHub ← Actions ← همان اجرا ← Artifacts. بازکردن فقط با رمز خودتان:
  ```bash
  gpg -d viva-railway-YYYYMMDD-HHMMSS.tgz.gpg | tar xz
  pg_restore --no-owner -d "$NEW_DATABASE_URL" db.dump
  ```

## ۴) اجرای محلی (روی کامپیوتر خودتان، در صورت نیاز)
```bash
npm i -g @railway/cli
railway login            # یا: export RAILWAY_TOKEN=<project token>
git clone https://github.com/vahidlesani/smc-scanner2 && cd smc-scanner2
bash ops/railway/ops.sh access
BACKUP_PASSPHRASE='...' bash ops/railway/ops.sh backup
```
