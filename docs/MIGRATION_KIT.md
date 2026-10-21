# MIGRATION KIT — خروج از Railway (r61)

دستور ۰۹-۳۰: «همه فایلهای مورد نیاز رو برای مهاجرت از ریلوی بردار». این سند
همهٔ آن چیزی است که برای بالا آوردنِ سرویس روی هر هاست دیگر لازم است — با این
کیت، مهاجرت در چند دقیقه انجام می‌شود.

## ۱) فایلهای موجود در مخزن (آمادهٔ استفاده)
| فایل | نقش |
|---|---|
| `Procfile` | `worker: main.py` / `web: combined_service.py` — هر هاستی که Procfile می‌فهمد |
| `combined_service.py` | بات + داشبورد در یک پروسه (نقطهٔ ورود تک‌کانتینری) |
| `railway.json` / `render.yaml` | مانیفست‌های فعلی/قبلی — فهرستِ کاملِ متغیرهای محیطی در render.yaml |
| `requirements.txt` | کل وابستگی‌ها (pip install -r) |
| `DEPLOY_BACKUP.md` | دستور نجات r41 — بکاپ/بازسازی DB و متغیرها |
| `docs/RAILWAY_MIGRATION_RUNBOOK.md` | ران‌بوک قبلی مهاجرت |

## ۲) متغیرهای محیطی (نام‌ها — مقدار هرگز کامیت نمی‌شود)
```
TELEGRAM_TOKEN · CHAT_ID_SIGNALS · CHAT_ID_APPROACHING · CHAT_ID_RESULTS · CHAT_ID
VIVA_APP_PASSWORD · DATABASE_URL · PYTHON_VERSION=3.11.9
FULL_SCAN_MINUTES · MONITOR_MINUTES · EDUCATIONAL_MIN_SCORE · EXECUTION_MIN_SCORE
ACCOUNT_SIZE · BYBIT_PROXY_URL · DASHBOARD_PORT · CHART_ENABLED
GITHUB_TOKEN (فقط برای push ران‌تایم) · DB_PATH (اگر SQLite روی Volume)
```
- توکن‌ها محلی در `/home/user/tokens.env` و `.railway_token` — هرگز در مخزن.
- `CHART_ENABLED` (r61): پیش‌فرض خاموش (رژیمِ کم‌مصرف)؛ روی هاستِ تازه می‌توان `1` داد.

## ۳) دیتابیس
- SQLite پیش‌فرض (`DB_PATH`)؛ اگر `DATABASE_URL` ست شود → Postgres.
- **بکاپ فوری:** `sqlite3 "$DB_PATH" ".dump" > signals-$(date +%Y%m%d).sql`
- **بازسازی:** فایل dump را روی مقصد اجرا کنید؛ روی Railway حتماً DB_PATH به Volume.
- `scripts/migrate_postgres.sh` برای مهاجرت به Postgres موجود است.

## ۴) سه مسیر مقصد
### الف) VPS (پیشنهادی — ارزان‌ترین با این مصرف)
```bash
git clone https://github.com/vahidlesani/smc-scanner2 && cd smc-scanner2
pip install -r requirements.txt
# systemd واحد ۱: بات
python main.py            # یا: worker پروسه
# systemd واحد ۲: داشبورد+بات یکپارچه
python combined_service.py
```
- nginx روی DASHBOARD_PORT؛ SSL با certbot؛ DB روی دیسک محلی (سریع‌تر از هر Volume).

### ب) Docker (هر ابری)
```dockerfile
FROM python:3.11.9-slim
WORKDIR /app
COPY requirements.txt . && RUN pip install -r requirements.txt
COPY . .
CMD ["python", "combined_service.py"]
```

### ج) Render/Fly/هر PaaS
- Build: `pip install -r requirements.txt` · Start: `python combined_service.py`
- همان متغیرهای بخش ۲؛ هلت‌چک: `GET /health`.

## ۵) چک‌لیست بریدن از Railway
1. بکاپ DB (بخش ۳) + ذخیرهٔ متغیرها از پنل Railway.
2. دیپلوی مقصد با همین کیت؛ `GET /health` → `boot_sha` باید = HEAD مخزن.
3. یک سیکل کامل اسکن را تماشا: پیام تلگرام + `/health` + داشبورد.
4. DNS/دامنه اگر منتقل شده؛ اپ اندروید (PWA) فقط URL را می‌شناسد — اگر دامنه عوض شود نسخهٔ جدید APK لازم می‌شود (pwabuilder، همان keystore، appVersionCode+1).
5. Railway را در پایان PAUSE/حذف کنید تا کریدت نسوزد.

## ۶) نکتهٔ مصرف Railway (دستور ۰۹-۳۰)
- از r61 رندر چارت خاموش است (`CHART_ENABLED` نامشخص = OFF) — سنگین‌ترین کارِ CPU.
- اگر بعد از مهاجرت چارت بخواهد: روی VPS هزینهٔ رندر = صفر تقریبی؛ فلگ را `1` کنید.
