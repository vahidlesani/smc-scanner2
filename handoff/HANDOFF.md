# 
> **اضافهٔ ۰۹-۲۳ (راند ۱۷):** اپلیکیشن موبایل VIVA SIGNALS PRO لایو شد — `https://smc-scanner2-production.up.railway.app/app` (رمز: env `VIVA_APP_PASSWORD`). فید زنده + وین‌ریت هر ستاپ + کنترل توقف/ستاپ‌ها (bot_kv `webapp_control`، گیت fail-open در main.py دیسکاوری). APK در `/home/user/viva-android/`. کد: `webapp_viva.py` + `install_viva_app(app)` در dashboard/app.py. هر تغییری در وب‌اپ = فقط همان یک فایل.

HANDOFF.md — smc-scanner2 (VivaSignals Pro)
> **این فایل از روی کد نوشته شده، نه از روی حافظهٔ چت.** تاریخ: ۲۰۲۶-۰۹-۱۴ · HEAD `b21b50a` · بیلد لایو `2026.09.14-11b`
> ⚠️ `CHAT_CONTEXT.md` داخل ریپو **منسوخ و غلط است** (Render/Supabase/13 استراتژی/اسکن ۵ دقیقه). آن را نخوان؛ این فایل را بخوان.

## ۰) وضعیت زندهٔ راند ۱۶ (این بخش منبع حقیقتِ «الان کجاییم» است)
- شاخهٔ فعال: `main` `841202e` (round16 merge شد) — دیپلوی `dbe39015` SUCCESS، لاگ تمیز، هارت‌بیت فعال (۲۱:۲۵Z).
- توکن Railway UUID: تحویل شد و ذخیره است (پروژه gleaming-sparkle · production `86aa377b`). دیپلوی دستی با mutation `serviceInstanceDeploy` (اتو-دیپلوی نیست).
- تست‌ها: **۳۴۹ پاس / ۱ اسکیپ** · pyflakes تمیز.
- فاز ۱ (`2546437`): لَدر هشدار اسپات TOUCH → NEAR_BREAK → BREAK_DOWN (فقط هشدار) + تأیید یک‌کلوز صعودی · باکس تا سقف ساختاری از اولین هشدار · گیت ضدتکرار · بودجهٔ مستقل.
- فاز ۲ (`c876965`): SPOTBREAK (جداسازی کامل) · تریگرهای 4h/8h/12h/1d/3d · شناسهٔ VIVA-SPOT-E###### · سقف استاپ اسپات ۱۰٪ · لگاریتم همه‌گیر گارددار · حذف RANGE-hlines و NaNهای چپ · لنگر ابزار روی کندل لایو · لیبل VIVA-SPOT-MON · ابطال نوشتاری · دلایل هشدار.
- فاز ۲ب: سطل کانال 8h/12h · معافیت اسپات از گارد استاپ فیوچرز.
- صف بعدی و حکم‌ها و پروتکل پیوستگی: **`WORKLOG.md` (ریشهٔ ریپو)** — همیشه قبل از شروع کار خوانده شود.
- `CHAT_CONTEXT.md` ریشه منسوخ است؛ با merge بعدی حذف می‌شود (F15).

## ۱) هدف (۳ خط)
ربات تلگرامیِ سیگنال پرایس‌اکشن روی USDT-perp (دادهٔ Bybit، اجرا روی Ourbit). دو کانال: **هشدارها** = هشدار تفصیلیِ دائمی؛ **PRO** = یک اسلات زنده به ازای هر زنجیره که با آپدیت‌های شماره‌دار جایگزین می‌شود.
فلسفه: کیفیت بر کمیت — سیگنال فقط بعد از **کلوزِ معتبرِ کندل** و **بعد از ثبت ردیف در DB** منتشر می‌شود.

## ۲) استک و دستورها
| مورد | مقدار |
|---|---|
| زبان | Python 3.11 (`root` file = 3.11.9 · CI = 3.11 · sandbox فعلی 3.13) |
| میزبانی | **Railway** (نه Render) — `combined_service.py` + Waitress، اسکنر در نخ پس‌زمینه |
| DB | **Railway/Supabase Postgres** (`DATABASE_URL`) + `bot_kv` (JSON) + `signal_candidates`؛ fallback = SQLite در `/tmp` |
| نصب | `pip install -r requirements.txt pytest` |
| تست | ✅ `python -m pytest tests/ -q` → **116 passed, 1 skipped** (skipped = شرطی در `test_pattern_engine`) |
| تست روی PG واقعی | `DATABASE_URL=$(cat ~/.dburl) python -m pytest tests/ -q` |
| ❌ **اجرا نکن** | `python -m unittest discover -s tests` → فقط **۲۴ تست** می‌گیرد (CI الان همین است و باید عوض شود) |
| lint سریع | `python -m pyflakes main.py analysis/*.py bot/*.py database/*.py` (الان ۶ `undefined name` می‌دهد) |
| دیپلوی | bump `"build"` در `main.py:1118` → commit → push → `serviceInstanceDeploy(latestCommit:true)` → poll `bot_kv.boot_version` (~۱۰۰ ثانیه) |

## ۳) چهار جریان (stream) — `analysis/setups_v7.py:TIMEFRAME_PROFILES`
| استریم | trigger/pattern TF | context | confirm | expiry |
|---|---|---|---|---|
| GRAND | 1d | 4h | 1d | ۳۳۶ ساعت |
| SWING | 4h | 1d | 4h | ۱۶۸ ساعت |
| DAYTRADE | 1h | 4h | 1h | ۱۲۰ ساعت |
| SCALP | 15m | 1h | 15m | ۱۲ ساعت |

`live_styles` پیش‌فرض = هر چهار. **«۴» یعنی ۴ استریمِ تایم‌فریم، نه ۴ ستاپ.**

## ۴) ستاپ‌ها — ⚠️ کد و سند در تضادند
| ستاپ | flag در `config.py` | مقدار پیش‌فرض |
|---|---|---|
| TECHCLASSIC | `technoclassic_enabled` | **True** (+ `technoclassic_preview_alerts = True`) |
| ALBROX | `albrox_enabled` | **True** |
| PINWALLQ | `pinwall_quality_enabled` | **True** |
| PINVAL | `pinv_enabled` | **True** |
| TLBREAK | `viva_tlbreak_enabled` / `experimental_tlbreak_enabled` | **False / False** ← قانون ۶ می‌گوید باید True باشد |
| ۵ ستاپ قدیمی v7 | `core_v7_setups_enabled` | **False** |

→ **تصمیم باز:** یا فلگ‌های TLBREAK در کد True شوند، یا قانون ۶ اصلاح شود. (احتمالاً در env لایو True شده — باید بررسی شود.)

## ۵) قوانین حیاتیِ سیستم (آن‌ها را نشکن)
1. **DB گیت:** سیگنال فقط بعد از row دیتابیس. `DEAD_GATE` = row ذخیره می‌شود، licence مصرف نمی‌کند، مانیتور نمی‌شود، ولی اجازهٔ پست دارد.
2. **قانون یک‌کلوز:** تأیید = اولین کندلِ بسته‌شدهٔ معتبر فراتر از خط/لبه (≥۰.۱۰ ATRِ **همان فریم** پشت لبه، Body ≥۰.۲۵ ATR، جهت‌دار). پولبک شرط نیست. روی **همهٔ کندل‌های بعد از هشدار** اسکن می‌شود، هم در تایم تأیید هم تایم الگو.
3. **RR هرگز وتو نیست** وقتی `tl_fast_break` ست شده — فقط `rr_degraded_note` گزارش می‌شود. Chase-cap هم در fast-lane وتو نیست، فقط `chase_note`.
4. **وتوهای مطلق:** `CLOSE_THROUGH_INVALIDATION` (عبور از SL) و expiry. این‌ها هیچ‌وقت bypass نمی‌شوند.
5. **Licence:** ۳ زنجیرهٔ چرخشی روی `(symbol, trigger_tf, setup)`؛ بعدی وقتی آزاد می‌شود که قبلی **CONFIRM** شود؛ فاصلهٔ اجباری ≥۲٪ از آخرین قیمتِ تأییدشده (`license_min_sep_pct`)؛ dedupeٔ ناحیهٔ یکسان ۲۴ ساعت (`recent_lineage_zone`).
6. **بودجه:** ۱۶ هشدار تفصیلی در هر اسکن (`education_max_per_scan`) + `candidates[:4]` در هر سمبل.
7. **Anti-echo:** یک آپدیت باید **خبرِ بعد از هشدار** داشته باشد؛ فاصلهٔ حداقل ۳۰۰ ثانیه (`update_min_gap_seconds`) + dedup با `upd_sig` (md5 از state/note/score/zone/sl).
8. **اسلات PRO:** یک پیام زنده به ازای هر زنجیره. اول پیام جدید post می‌شود، بعد پیام قبلی **حذف** می‌شود، بعد KV آپدیت می‌شود. تفصیلیِ کانال هشدارها **هرگز** ویرایش/حذف نمی‌شود.
9. **کلید زنجیره:** `bot_kv` → `setup_chain|<PUBLIC_CODE>` با فیلدهای `slot / slot_kind / edu / upd / upd_n / upd_sig / last_update_ts / hb_bar`.
10. **AI (Gemini):** فقط advisory، async، کاملاً جدا از scoring/confirmation/risk. outage فقط می‌تواند متن را حذف کند، هرگز سیگنال را.

## ۶) وضعیت فعلی
### ✅ سالم و تأییدشده
- بیلد لایو با HEAD مطابقت دارد؛ `boot_version` در DB قابل اثبات است.
- ۱۱۶ تست سبز (sqlite و PG).
- قوانین ۵ (expiry/heartbeat/live-break) و ۷ (DB گیت/بودجه/licence/anti-echo) پیاده‌شده و با config هم‌عدد.
- هیچ secret ای در ریپو commit نشده.

### 🔴 خراب — اولویت ۱ (جزئیات: `AUDIT-smc-scanner2.md`)
| کد | مکان | چیست |
|---|---|---|
| F1 | `database/repository_v7.py:1318` | `NameError: resolved_at` → معامله بسته می‌شود، DB آپدیت می‌شود، ولی **پیام نتیجه هرگز ارسال نمی‌شود** (فقط مسیر legacy) |
| F2 | `main.py:828` | `NameError: _t` در gateِ geometry-dup → gate **کاملاً از کار افتاده**: سیگنالِ تکراری لغو نمی‌شود بلکه **منتشر می‌شود**، ولی آمار `suppressed_geo_dup` وانمود می‌کند که گرفته شده. باگی که کامیت `e369fb1` حل کرده بود دوباره زنده است |
| F3 | `main.py:469,487` | `Optional` import نشده (الان با `from __future__ import annotations` مخفی است) |
| F4 | `main.py:800-812`, `617-627` | مارکر heartbeat/live-break **قبل از** ارسال موفق ذخیره می‌شود → اگر ارسال رد شود، آن کندل **برای همیشه** آپدیت نمی‌گیرد |
| F5 | `.github/workflows/tests.yml` | CI با `unittest discover` فقط **۲۴ تست از ۱۱۷** را اجرا می‌کند؛ `pytest` هم در requirements نیست |
| F6 | کل پروژه | ۲۱۸ `except Exception`، ۶۱ تایشان `pass` خالی → هیچ خطایی دیده نمی‌شود |
| F7 | `database/` | **هیچ connection pool ای نیست**؛ هر query یک اتصال SSL تازه |
| F9 | `main.py`, `data/fetcher.py` | throttle سراسری بین ۳ نخ + مانیتور هر ۱۰ ثانیه با `use_cache=False` + expiry تا ۱۴ روز → **بار با گذشت زمان رشد می‌کند** |

### 🟠 ناسازگاری کد/سند
| کد | چیست |
|---|---|
| F15 | `CHAT_CONTEXT.md` یک ماه است غلط است (Render/Supabase/13 استراتژی/۵ دقیقه) → **حذف یا جایگزینی** |
| F19 | `CHANGELOG.md` از ۲۰۲۶-۰۸-۱۶ به‌روز نشده؛ ۳۰ کامیتِ phase5/6/6b بی‌سند |
| F8 | دو سیاست expiry متضاد: `expiry_hours_for` (۱۲/۱۲۰/۱۶۸/۳۳۶) در برابر `setups_experimental.py:863` (۲۴/۱۰/۳) → خانوادهٔ پینبار از قانون ۵ پیروی نمی‌کند |
| F6 | ستاپ‌ها: قانون ۶ می‌گوید ۵ ستاپ روشن؛ کد می‌گوید TLBREAK خاموش |
| F20 | دو ژنراتور رویداد (ladder / legacy) با فیلدهای متفاوت → قالب پیامِ نتیجه بسته به مسیر فرق می‌کند (legacy حتی `direction` ندارد) |

### 🟡 منطقی
| کد | چیست |
|---|---|
| F12 | «ATR همان فریم» در واقع `mean(high-low)` است نه ATR واقعی؛ و در همان تابع gate دیگر با ATR واقعی سنجیده می‌شود → دو معیار در یک تصمیم |
| F13 | `_bars_since_candidate` با `>=` خودِ کندلِ هشدار را شامل می‌شود؛ و fallback آن `tail(2)` است → امکان تأیید با کندلِ **قبل از** هشدار |
| F14 | `_edge_at`/`_watch_edge_at` ضریب خط شیب‌دار را clamp نمی‌کنند → اگر B قدیمی‌تر از A باشد، شیب برعکس می‌شود |
| F10 | آپدیتِ throttle‌شده هیچ retry ای ندارد → خبر برای همیشه گم |
| F16 | `_pinv_window_expired` / `_resolve_pinv_verdict` / `_pinv_done` = **کد مرده**؛ `pin_frame` حساب می‌شود و استفاده نمی‌شود؛ `VERDICT_YES/NO/TIMEOUT` عملاً تولید نمی‌شوند |
| F17 | `_dead_gate_recently_alerted` هم چک می‌کند هم مارک → سهمیه حتی اگر ارسال ناموفق باشد مصرف می‌شود؛ دو dict سراسری بدون تخلیه رشد می‌کنند و بعد از redeploy ریست می‌شوند |
| F18 | `pd.Timestamp.utcnow()` در ۳ جای کد اصلی (deprecated) + ۱۸ warning در تست‌ها (CoW در pandas 3 معنای تست‌ها را عوض می‌کند) |

## ۷) قدم بعدی (به ترتیب)
0. **راند ۱۶ (۰۹-۲۲):** فاز ۱ (لَدر هشدار) + فاز ۲ (جداسازی کامل SPOTBREAK · تریگرهای 4h/8h/12h/1d/3d · شناسه VIVA-SPOT-E · سقف استاپ ۱۰٪ اسپات · لگاریتم همه‌گیر گارددار · حذف RANGE-hlines · لنگر ابزار روی کندل لایو · لیبل VIVA-SPOT-MON) اجرا، تست (۳۴۶ سبز) و پوش شد روی شاخهٔ `round16-spot-alerts` — **هنوز merge به main نه**. توکن‌های GitHub و Railway تحویل شد (پروژه `gleaming-sparkle`، آخرین دیپلوی SUCCESS = round15e). مانده: کالیبراسیون با ۶ نمونهٔ مرجع + حکم‌های باز (تریگر 1d فیوچرز؟ OI/دفتر سفارشات: VPS یا پولی؟) + merge/دیپلوی با تأیید Viva.
1. **revoke کردن توکن GitHub** که در بکاپ لو رفته.
2. فاز ۱ ممیزی (۷ اصلاح یک‌خطی/کوچک) → بعد **CI را به pytest تغییر بده** و `pyflakes` را اضافه کن.
3. فاز ۲ → اتصال صدا به خطاها (`_safe` + `error_tally` در `bot_kv`).
4. فاز ۳ → **connection pool** (بزرگ‌ترین بردِ عملکردی)، بعد کشِ مانیتور، بعد تفکیک throttle.
5. فاز ۴ → یک حقیقت: حذف `CHAT_CONTEXT.md`، یکسان‌سازی expiry، تصمیم TLBREAK، وصل‌کردن `_tech_aids_lines` به `send_confirmed`.
6. فاز ۵ → تست مسیرهای بی‌صدا (legacy event path, geometry-dup, heartbeat-fail).

## ۸) تصمیم‌های باز (باید Viva جواب بدهد)
- **قانون ۴:** کمکی‌ها (🕐/📊/🌀/📈) الان فقط در پیامِ مختصر و آپدیت هستند، نه در Confirmed و نه در تفصیلی. قانون می‌گوید «در همه پیام‌ها». وصل شوند؟
- **قانون ۶:** TLBREAK در کد خاموش است. در env لایو روشن است یا باید در کد روشن شود؟
- **قانون ۸ (باز از قبل):** خشکسالی پینوال → (الف) پنجرهٔ عریض‌تر یا (ب) سمبل بیشتر؟ هنوز بی‌جواب.
- **F9:** سقف زنجیره‌های فعالِ همزمان چند باشد؟ با expiry تا ۱۴ روز، بار یک‌طرفه رشد می‌کند.
- **F12:** آستانه‌ها با ATR واقعی سنجیده شوند یا میانگین دامنه؟ (الان هر دو در یک تابع)

## ۹) کارهای ممنوع
- `python -m unittest discover` را به‌عنوان «تست سبز» قبول نکن.
- هیچ `except: pass` جدیدی اضافه نکن.
- expiry را در دو جا تنظیم نکن (فقط `expiry_hours_for`).
- KV `setup_chain|CODE` را بدون خواندن مجدد آپدیت نکن (دو نویسنده دارد).
- مارکر dedup را **قبل از** ارسال موفق ذخیره نکن.
