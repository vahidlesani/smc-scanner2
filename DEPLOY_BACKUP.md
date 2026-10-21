# DEPLOY BACKUP — نسخهٔ نهایی روی Railway (r41)

**تاریخ قفل:** 2026-09-26 · **کامیت دیپلوی‌شده:** `25a85da` (boot_sha `25a85daa1e52`، بوت 15:20Z = 18:50 تهران)
**تگ:** `railway-final-r41` → همین وضعیت روی GitHub قابل بازگشت/بازدهی است.
HEAD مخزن (`10c1c2b`) فقط مستندات دارد؛ کدِ اجرایی = `25a85da`.

این فایل دستورِ نجات است: هر چه برای Railway یا هر هاست دیگر پیش آمد، از همین مخزن در چند دقیقه بالا می‌آید.

---

## 1) چه چیزی روی Railway اجراست

- بیلدر: NIXPACKS · `pip install -r requirements.txt`
- استارت: `python combined_service.py` (بات + وب‌اپ در یک پروسه؛ بند Procfile: `worker: main.py` / `web: combined_service.py`)
- هلت‌چک: `GET /health` → `boot_sha` را نشان می‌دهد؛ همیشه با HEAD مقایسه شود.
- مرز تست: `python -m pytest tests/ -q` → 567 passed / 1 skipped

## 2) متغیرهای محیطی (فقط نام‌ها — مقدار هرگز کامیت نمی‌شود)

منبع رسمی فهرست: `render.yaml` (مانیفست قبلی، همان نام‌ها):

```
TELEGRAM_TOKEN · CHAT_ID_SIGNALS · CHAT_ID_APPROACHING · CHAT_ID_RESULTS · CHAT_ID
VIVA_APP_PASSWORD · DATABASE_URL · DATABASE_URL(write) · PYTHON_VERSION=3.11.9
FULL_SCAN_MINUTES · MONITOR_MINUTES · EDUCATIONAL_MIN_SCORE · EXECUTION_MIN_SCORE
ACCOUNT_SIZE · BYBIT_PROXY_URL · DASHBOARD_PORT
GITHUB_TOKEN (فقط برای push ران‌تایم، اگر لازم شد) · DB_PATH (اگر SQLite روی Volume)
```

قانون ثابت: توکن‌ها در `/home/user/tokens.env` و `.railway_token` محلی می‌مانند؛ هرگز در مخزن.

## 3) دیتابیس و بک‌آپ داده‌ها

- موتور: SQLite (`DB_PATH`، پیش‌فرض `/tmp/signals.db`) — اگر `DATABASE_URL` ست باشد → Postgres.
- روی Railway، `DB_PATH` باید به **Volume** اشاره کند؛ اگر روی `/tmp` باشد، با هر دیپلوی داده می‌پرد (بررسی شود؛ بخش مهاجرت).
- **گرفتن بک‌آپ فوری (SQLite):**
  ```bash
  # داخل کانتینر (railway ssh) یا هر جا فایل DB هست:
  sqlite3 "$DB_PATH" ".dump" > signals-$(date +%Y%m%d).sql
  # بازسازی در هر جای دنیا:
  sqlite3 new.db < signals-YYYYMMDD.sql
  ```
- **Postgres:** `pg_dump "$DATABASE_URL" > signals-$(date +%Y%m%d).sql` / بازسازی با `psql < file`.
- KVهای حیاتی که در همان DB هستند: `render_identity:{sid}` و `zoom_freeze:{sid}` (هویت چارت‌ها)، `app_chart|{sid}` (میرور تلگرام)، `webapp_control`، نردبان‌ها (`target_state_json` روی خود ردیف‌ها). با dump بالا همه می‌آیند.

## 4) بازدهی روی Railway (اگر اکانت/پروژه از بین رفت)

1. GitHub → repo `vahidlesani/smc-scanner2` → `git checkout railway-final-r41`
2. Railway → New Project → Deploy from GitHub repo
3. متغیرهای بخش 2 را دستی وارد کن (یا از خروجی `railway variables` قبلی).
4. اگر Volume داری: همان mount path را به `DB_PATH` بده و dump را بازگردان.
5. `/health` تا دیدن boot_sha جدید.

## 5) بازدهی روی هر VPS ارزان/کریپتو‌پرداخت (BitLaunch · Cloudzy · Njalla · …)

```bash
git clone https://github.com/vahidlesani/smc-scanner2 && cd smc-scanner2
git checkout railway-final-r41
pip install -r requirements.txt
export TELEGRAM_TOKEN=... CHAT_ID_SIGNALS=... CHAT_ID_APPROACHING=... \
       CHAT_ID_RESULTS=... CHAT_ID=... VIVA_APP_PASSWORD=... \
       DB_PATH=/opt/viva/signals.db
python main.py            # بات + مانیتور
python combined_service.py   # وب‌اپ (یا فقط همین یکی — خودش هر دو را بالا می‌آورد)
# سرویس دائم: systemd یا tmux; فایروال فقط پورت وب‌اپ
```
- الزامات شبکه: دسترسی خروجی به Ourbit/Bybit/Telegram (دبی، فرانکفورت، آمستردام همه اوکی‌اند؛ **IP ایران ممنوع** — صرافی‌ها بلاک می‌کنند).
- حداقل منابع: 1 vCPU / 1GB RAM / 5GB دیسک (استک فعلی سبک است).
- پرداخت کریپتو (USDT) این ارائه‌دهنده‌ها را از تحریمِ کارت بین‌المللی بی‌نیاز می‌کند.

## 6) چک‌لیست سلامت بعد از هر بازدهی

- [ ] `/health` → status ok + boot_sha = HEAD
- [ ] بات: `/status` در تلگرام جواب می‌دهد
- [ ] اپ: لاگین → فید پر است → چارت نمونه 200
- [ ] قیمت لایو کارت‌ها: `/app/api/prices?...` مقدار واقعی برمی‌گرداند
- [ ] نردبان یک سیگنال قدیمی: TPها با تلگرام یکی است (r41)
