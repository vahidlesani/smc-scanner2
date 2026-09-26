> **R30 — 2026-09-24 (current working branch):** مرجع تصویری سبک CryptoCove دقیق شد: منظور فقط منطق هندسی/تشخیص و ترسیم الگوهاست، نه رنگ‌بندی. نمونه‌ها شامل کانال نزولی/ترندلاین و Bullish Rectangle هستند. موتور تشخیص مستقل از رندر است.
> - **Spot horizons restored to six:** 4H/8H = کوتاه‌مدت، 12H/1D = میان‌مدت، 3D/1W = بلندمدت. Spot remains LONG-only for confirmation; opposite-side touches/breaks remain warnings.
> - **MTF base architecture:** 5M and 15M are fetched directly; 1H/30M are resampled from 15M; 8H/12H are resampled from the 4H structural tape; 3D/1W are resampled from the 1D macro tape. 5M is never reconstructed from 15M. 4H/1D stay direct because reconstructing enough long history from 5M/15M would cost more API calls, not fewer.
> - **Spot charts reuse the already fetched bundle** for confirmation/alert rendering; no second candle download just to draw the Telegram chart.
> - **Clean chart mode:** zone detection is unchanged, but the renderer defaults to `CHART_CLEAN_ZONES=1`: only the most actionable structural zones are lightly painted and fresh FVG overlays are hidden. This is a visual/AI-readability change only; it does not remove zones from the engine.
> - **MTF candle evidence:** 8H/12H/1H/30M/3D/1W are explicitly marked as locally resampled in explanatory metadata; trigger timeframe is prioritized in the summary.
> - **Identity safety:** no Telegram message template/type, message-link chain, signal/public unique-ID contract was intentionally changed in R30.
> - **Validation:** branch `r30-spot-mtf-chart-handoff` is based directly on main `013cae5`. Full pytest/CI validation is required before merge.
>
#
> **افزودهٔ ۰۹-۲۳ (ممیزی فاز اول):** در HEAD `754f4d3` قانون مرز اطلاعات اصلاح شد: تأیید فقط از کندل‌های بسته‌شدهٔ **بعد از زمان هشدار** انجام می‌شود؛ fallback تاریخی حذف شد؛ ATR هر فریم با True Range واقعی یکسان شد؛ ارزیابی خط روند به بازهٔ دو پیوت clamp شد. NameError نردبان تارگت و وضعیت لاین اسپات رفع شد، شمارندهٔ شناسهٔ اسپات اصلاح شد، و CI از unittest ناقص به `pytest` کامل + lint هستهٔ معاملات تغییر کرد. راستی‌آزمایی: **۳۷۵ passed / ۱ skipped** و وب‌اپ **۷ passed**. هنوز Railway production در این تسک دیپلوی نشده است.
> **افزودهٔ ۰۹-۲۳ (فاز دوم کالیبراسیون):** موتور ترند/الگو اکنون برای هر edge قرارداد صریح `pattern_type → pattern_bias → break_edge → break_direction → trade_direction` تولید می‌کند. WEDGE_RISING فقط lower/DOWN/SHORT و WEDGE_FALLING فقط upper/UP/LONG را مجاز می‌کند؛ FLAG_BULL/FLAG_BEAR بعد از relabel شدن edge نامعتبر را حذف می‌کنند. confirmation contract اجازه نمی‌دهد لاین داخلی یا generic جهت شکست را معکوس کند. راستی‌آزمایی فاز دوم: **۳۷۶ passed / ۱ skipped**.
> **افزودهٔ ۰۹-۲۳ (فاز سوم geometry/snapshot/chart):** internal-entry اکنون فقط برای `RANGE`, `RECTANGLE`, `CHANNEL` و `CHANNEL_*` فعال است و فقط از ۲۰٪ لبهٔ صحیح به سمت دیوارهٔ مقابل برنامه‌ریزی می‌شود؛ وج/مثلث/الگوهای همگرا فقط با شکست + کلوز معتبر تأیید می‌شوند. در `absorb_update_into_chain`، هر زنجیرهٔ منتشرشده geometry خودش (`entry_zone`, `entry`, `sl`, `tp1`, `tp2`) را نگه می‌دارد و اسکن بعدیِ همان نماد نمی‌تواند ابزار آن را جابه‌جا کند؛ شناسهٔ جدید از geometry مستقل خود استفاده می‌کند. لیبل‌های LONG/SHORT و pillهای کنار ابزار از چارت حذف شدند و خطوط قیمت باقی مانده‌اند. راستی‌آزمایی نهایی: **۳۷۷ passed / ۱ skipped**.
> **اضافهٔ ۰۹-۲۳ (راند ۱۹):** فاز-۳ فیت لگاریتمی خطوط پیوت (span>۳٪ روی محور لگ) + باکس سبز هرگز نصف نمی‌شود (re-anchor) + چیپ‌های ناحیه روی هم نمی‌نشیند. ۳۵۹ تست سبز. دیپلوی `d8d5d872` SUCCESS. صف بعدی: موتور کریپتوکاو (ریجکت ترند بی‌معنی) · اسنپ‌شات شناسه · قانون استاپ (پشت سوینگ، فیوچرز ≤۲٪) · مانیتینگ زندهٔ VIVA-MON-SPOT + تأیید به‌موقع.

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

## ۰۹-۲۳ شب — راند ۱۶ فاز ۳ + ماژول فلو (لِین مایک) · لایو `460a45c4`
- **فاز ۳ لاگ‌فیت:** خطوط اعتبارسنجی‌شده وقتی چارت لاگاریتمی است در فضای log10 فیت و به‌صورت منحنی رسم می‌شوند (`fit_validated_line(log_fit_min_span)` · `line_y/line_xy` · پروجکشن لاگ در گیت‌های تأیید و اشعه‌های اسپات). چارت‌های خطی/فیوچرز بی‌تغییر. پروف: `/home/user/proof_phase3_loglines.png`. تست: `tests/test_round16_log_calibration.py`.
- **ماژول فلو رایگان:** `analysis/onchain_free.py` — CoinGecko + alternative.me + DefiLlama، fail-open، فقط **ترتیب** لاین اسپات (سر واچ‌لیست ثابت، هشدارها اول) و یک خط لاگ زمینه؛ صف فیوچرز دست‌نخورده. تست: `tests/test_round16_onchain_free_priority.py`.
- سوئیچ‌ها: `ONCHAIN_FREE_ENABLED` (پیش‌فرض on) · `ONCHAIN_CACHE_TTL_SECONDS` · `SPOT_FLOW_HEAD` (۶) · `TLBREAK_LOG_FIT_MIN_SPAN` (۰.۰۳).
- وضعیت: ۴۰۴ تست سبز / ۱ اسکیپ · دیپلوی با commitSha انجام و لاگ تمیز · گزارش + پروف برای ویوا ارسال شد.

## ۰۹-۲۵ شب — r28→r29e (گزارشِ نجاتِ چارت/اسپات/تأیید) · لایو `7455e53`
**زمینه:** ویوا ۱۱ اسکرین‌شات + فایلِ اصلاحیه داد؛ سه ضربهٔ اصلی در یک روز:
1. **زومِ هوشمند چارت (r28):** finalizeِ قبلی min/max(کندل‌ها∪ورود∪استاپ∪TP)+۶٪ بود → DASH جفت‌شده در ۵٪ بالا / WLD ۸۰٪ پر. حالا `_smart_y_window` (اشغالِ ۷۲٪، کفِ ۴·ATR، کپِ اورلی ۴۵٪·اسپن) + **قفلِ رندر از اولین تأیید** (`chart_zoom_frozen`؛ خروجِ قیمت از جعبه = بازمحاسبه = همان قانونِ TF-bump).
2. **اسپاتِ مرده (r29):** `_spot_stamp` قبل از ارسال مهر می‌زد → یک تلاشِ ناموفق، (نماد،تایم،الگو) را می‌سوزاند؛ حالا مهر فقط بعد از موفقیت + شمارنده‌های `stamp_skip/send_fail/chart_fail/last_error` + وضعیتِ `zero_sent` در اپ.
3. **هیچ تأییدی در 2H/4H (r29e):** هر اسکن برای همان لبهٔ شکسته signal_id نو می‌ساخت (خطِ شیبدار ۰.۲ATR دریفت → تستِ 0.08ATR lineage رد → supersede → ساعتِ تأیید صفر). فیکسِ R31.7b cherry-pick شد: `alert_lineage_key` = timestamp پیوت‌ها (ثابت)؛ تعویض فقط با >۱ATR جابه‌جایی؛ کلیدِ خاموش `R317_LEGACY=1`.
- **اپ:** serve-while-revalidate روی `/app/api/state` (بیلدِ ~60s از مسیرِ درخواست خارج شد؛ پاسخِ آنی + یک نوسازِ پس‌زمینه) + SW bump `viva-shell-r29d` (مرورگرِ ویوا شلِ کهنه را می‌اندازد). فانلِ کشف (`scan_summary`) حالا در `payload.funnel` است.
- **قاطی‌پاتیِ شمارهٔ TP (r29):** تخصیصِ pillها صعودیِ مونوتون (قبلاً mid-out بود). **اسمِ الگوها (r29c):** درِ شباهتِ شیبِ §29 — ضلعِ غالب >۲.۲× = TRIANGLE نه CHANNEL. **لیبل روی کندل:** فالبکِ چیپ بالای پاکتِ کندل راه می‌رود.
- **دستنخورده‌ها:** TLBREAK full-frame edge law · PILLS-EXIST · CONFIRM-AFTER-CLOSE · تک‌طبیعه.
- **صف (به ترتیبِ توافق):** (۱) خواندنِ پاسِ اسپات از state (اگر send_fail بالا → سمتِ تلگرام)، (۲) ادغامِ ممیزی‌شدهٔ بقیهٔ audit-0925b (P2/P5/P6 + ۱۸تست — برنچ `arena/01a0d606`)، (۳) استاپِ ساختاری 4H + سقفِ قانونی (V3 §18 — BTC/DASH پرونده‌ها)، (۴) TP ساختاری (§19 — RENDER targetِ زیرِ قیمت)، (۵) Trailing v2: BE@TP1، خروجِ کامل بعد از تاچِ TP2 + خروجِ زودتر با الگوی برگشتیِ کندلیِ تایمِ کوتاه‌تر، (۶) بک‌تستِ Entry2، (۷) Material-Event Engine (پچ J)، (۸) 15m/30m=SCALP (تصمیمِ ویوا: DAYTRADE@30m بماند یا SCALP شود؟)، (۹) آپدیت-۵۱ ($18→$28).
- **حکمِ برنچ‌ها:** `r30-spot-mtf-chart-handoff` = محتوا کامل در main (خالی). `feat/pinval-zone-polarity` + `exp/stage4-zone-policy` = بدون merge-base (ریپوی جدا — مرج ممنوع؛ ایده → پچِ دستیِ Direction). `arena/01a0d606` = عاملِ سوم — فقط R31.7b گرفته شد؛ بقیه در صفِ ممیزی.
- **زیرساخت:** توکنِ GitHub ۰۹-۲۵ رِووک شد → توکنِ نو در tokens.env (هر چرخشِ کانتینر: `.git/config` + pip پاک — لیست: flask waitress mplfinance arabic-reshaper python-bidi). Railway token فقط project-scoped و لیستِ پروژه ممنوع → تأییدِ دیپلوی فقط `/health` → `boot_sha` (از r27b).

## 09-26 round r30 — `6ddfb3a` (LIVE boot_sha 6ddfb3afd125, boot 2026-09-25T21:15:16Z)
Suite 484P/1skip. Bug file «باگهای 😵‍💫😵‍💫.txt» + 17 screenshots → 8 laws shipped:
1. **NO-SOFT-INVALIDATION** (quality_engine.is_invalidated): pre-confirm invalidation only from the PROTECTIVE side — sl inside the zone never fires (LTC 69.404-in-63.6..70.9 kill); confirmed chains keep lifecycle stop.
2. **Builder clamp** (pattern_engine._build_candidate): break-stop clamped beyond zone edge (± buffer).
3. **OROR break-guard** (main._scenario_out_of_reach): touched/live_break_bar/JUST_BROKE + price beyond zone in direction → never «out of reach» (LTC 6.56-ATR cancel during breakout); untouched runaway still cancels (09-21 law preserved).
4. **Tombstones** (main._tombstone_write/_hit, KV `cancel_tombstones`, TTL 12h): cancelled scenario fingerprint (sym|setup|dir|zone-mid) blocks rediscovery — the invalidate→re-find→113-msg loop is dead. Tally counter: `dup` bucket reused.
5. **Iran clock** (messages_v7): update caption clock Asia/Tehran + «به وقتِ ایران» (was UTC).
6. **Update wording**: «از کندلِ هشدارِ اولیه N دقیقه می‌گذرد — این پیام همین حالا ارسال شده…» (never «arrived late»); r12 test re-anchored.
7. **Final result text-only** (send_trade_close_event): no fresh render — verdict replies under the last TP anchor (Viva: «نتیجه نهایی نیاز به چارت لایو نداره»); CPU saved.
8. **Atomic chart+text** (_post_chart_then_text + _chat_send_lock): per-chat lock — no more interleaved captions (charts detached from messages).
9. **30m/2h triggers** (config): TECHCLASSIC_PATTERN_TFS default = «30m,1h,2h,4h,1d» (Viva verdict: «۳۰ دقیقه و ۲ ساعته هم بد نیست، کیفیتی بهتر داره»). WATCH: CPU/scan-load on Railway with 2 extra pattern TFs.
INFRA: repo slug = **vahidlesani/smc-scanner2** (github token in tokens.env is the vahidlesani PAT — query api.github.com/user/repos if remote lost again). pip wipe list: flask waitress mplfinance arabic-reshaper python-bidi.
OPEN from bug file (next round): spot-pill «SCORE 0/10» vs text 8/10; AERO 15m one-candle entry/stop/TP sanity floor + PINWALL pin-bar validation; DASH 1D wedge miss (pattern-window zoom); mid-channel trade ban (APT) — CHANNEL-TRADE law not yet enforced in code; LTC-15m TARGET<LIVE class (RENDER leftover); re-measure post-r30 churn (complaint timestamps predated r29e deploy).

## 09-26 round r31 — `1b5fa94` (LIVE boot_sha 1b5fa94db2df, boot 2026-09-25T22:45:10Z)
Suite 490P/1skip. Screenshot round (PYTH T676953 + 2 TradingView):
1. **TECHCLASSIC typo** (models.generate_viva_public_code label_map): «VIVA-TECLASSIC» → «VIVA-TECHCLASSIC» (born 09-12; tests re-anchored). New codes spell it right; old reserved codes keep their IDs.
2. **Chart clocks = TEHRAN everywhere**: axis tick formatter + in-panel live pill + figure LIVE stamp all Asia/Tehran (UTC suffix gone).
3. **Exact render-moment live candle** (_live_candle): forming candle displayed at datetime.now(UTC) (bucket-open read hours-old on 1H+) + probe bypasses klines cache (use_cache=False, 3-bar call) — «چارت ۱:۵۷ اومده ⟶ مهر ۰۱:۵۷».
4. **Fresh-major-break recognition** (viva_tlbreak + pattern_engine): a substantial line (3+ touches, 30+ span) broken within `fresh_break_bars` (new cfg, default 12) is ADMITTED even when it died <10 bars after its last pivot; pattern_engine has a recognition branch (break_index fresh → STATE_BREAK without demanding a fresh displacement bar; ev gains fresh_break_recognition/bars_since_break). Ancient breaks stay history-only. Fixture lesson: pivot fixtures must be strictly-monotone sawtooths — plateaus crowd the pivot pool.
OPEN (user asked «قبلی‌ها همه؟»): score-pill 0/10 vs text 8/10; AERO one-candle sanity floor; DASH 1D wedge miss; CHANNEL-TRADE mid-channel ban; LTC-15m TARGET<LIVE class; CPU watch with 30m/2h TFs; 0925b audited merge still queued.

## 09-26 round r32 — `ce3953a` (LIVE boot_sha ce3953aa9237, boot 2026-09-25T23:40:56Z)
Suite 500P/1skip. User night feedback (5 screenshots) — ALL fixes setup-agnostic (30m/2h stays TC-triggers-only):
1. **Chart tool redesign** (Viva verbatim): tool column = bare TP numbers 1..5 ONLY (ENTRY/FIRST STOP/SL/LIVE pills removed); every level = faint dashed connector (0,(3,2) α.55) reaching its VALUE on the price axis (blue entry / green TPs / red stop, no words); **bottom-right Persian LEDGER**: ورود / استاپ اولیه (+✓ once trailed) / تریلینگ استاپ (— until set) / TP1..5 (+✓ on hit) / قیمت لایو — fa_chart() shaped; ledger via fig.text at ax corner (messages_v7 ~:2962).
2. **LIVE pill removed from confirmed charts** (lives in ledger now); unconfirmed keeps it.
3. **Info box**: publish_score snapshot (main.py sets metadata['publish_score'] before reserve) — 0/10 never printed; score hidden when both row+snapshot are 0.
4. **Smart zoom recent-floor**: `_smart_y_window(..., recent_lo=tail(40).min)` lifts dead history below a rising market (LTC 1D candles-at-top) — ladder keeps 45% cap headroom.
5. **Engine gates** (pattern_engine, all setups): LONG target < live impossible (≥ live+1.5·ATR; SHORT mirrored — LTC-15m class closed); height floor = 2× last trigger candle range (AERO one-candle); CHANNEL+STATE_BREAK requires ≥1.3× 20-bar avg volume (APT mid-channel ban = CHANNEL-TRADE law in code).
6. **DASH 1D wedge**: swing max_pattern_bars 90→150 (json + dataclass).
7. **Confirm mirror**: 30m confirm → MID channel, 4h confirm → SHORT channel (plain copy, primary keeps chain+link; Viva: extend to other setups if it reads well).
TEST LESSON: chart-pill tests MUST monkeypatch data.fetcher.get_klines→None — a real live candle on a synthetic ~100 tape blows up _tol grouping (this was the invisible flake). Visual harness: r32_render.png (LTC-like 1D render, verified).
APP (webapp) — QUEUED r33: «سیگنال‌های امروز» empty (feed = publishes; gates quiet ⇒ list empty — verify funnel) + RESULTS page overlapping/garbled cards (screenshots 02:51-52) needs layout repair + «سیگنال‌های امروز» design pass. PINVAL merge + Railway backup/migration = user-scheduled tomorrow. Railway cost optimization: partial (final-result no-render r30; full audit pending with store-retention).

## 09-26 round r33 — `7175631` (LIVE boot_sha 7175631e0194, boot 2026-09-26T00:18:23Z = 03:48 Tehran)
Suite 509P/1skip. Channel-screenshot forensics (03:15-03:28 Tehran):
1. **OUT_OF_REACH ROOT CAUSE (the big one)**: distance was measured from the zone MID — FIL 4H live 1.018 INSIDE 0.889-1.05 zone read «4.59 ATR away» → cancelled; LTC 72.35 inside 63.37-72.4 → cancelled. FIXED: inside-zone → NEVER; distance to the NEAREST EDGE; r30 touched-breakout exemption kept (beyond-zone in-direction + touched → exempt). Cancel message now prints edge-based ATR.
2. **Zone-stop heal** (`_heal_zone_stop`, wired in monitor pre-approach): pre-r30 chains still DISPLAYING an invalidation inside the zone (LTC 70.244 in 63.37-72.4) get one protective repair (LONG → below floor / SHORT → above ceiling, structural buffer) + persist + stop_clamped flag. Confirmed chains untouched.
3. **LINE LIFECYCLE LAW (Viva verbatim 09-26)**: `fresh_break_bars` 12 → **50** (recognition + admission + retest); render `_recently_broken` floor 12 → **50** (broken line paints dotted ≥50 candles for retest visibility; replaced only by a better-ranked valid line). NOTE for next chat: user asked «چرا ۱۰ شده ۱۲؟» — the old `break_at - x1 < 10` was MIN-LIFE-BEFORE-BREAK, never post-break persistence; the real law is now 50.
4. **RENDER IDENTITY** (Viva: «ترندلاین‌ها با تغییر زوم بهم میریزند»): patterns/trendlines detected ONCE per chain, stored in bot_kv `render_identity:{signal_id}` and REUSED on every zoom/update — never re-fitted per render. Zoom freeze also persisted: `zoom_freeze:{signal_id}` (metadata copy was lost between reloaded rows → zoom changed between messages).
5. **«ATR 0.00» display**: distance lines now say «قیمت همین حالا داخل ناحیهٔ بررسی است» when distance=0 (approaching + final-watch builders).
TEST LESSON: SimpleNamespace test doubles must carry symbol/signal_id if the prod path prints them; chart-pill tests must monkeypatch get_klines (r32). Re-anchored r12 (15.0 below-zone now True — symmetric edge law) and r30 tests.
OPEN: PINVAL merge + Railway backup/migration (user-scheduled 09-27); app feed «سیگنال‌های امروز» + RESULTS page layout (r33+); Railway cost audit; spot publish-rate watch (gates still filtering 48/48).

## 09-26 round r34 — `40d270c` (LIVE boot_sha 40d270cc604f, boot 2026-09-26T01:02:55Z = 04:32 Tehran)
Suite 510P/1skip. User's 3-item night list:
1. **Chart ledger → ENGLISH** (Viva: «با entry و مخفف انگلیسی بنویس، خوانا، نه خیلی بزرگ»): ENTRY / INITIAL STOP (+✓) / TRAILING (— until set) / TP1..5 (+✓) / LIVE, fontsize 7.6.
2. **App RESULTS CONTROL board** («داشبورد کنترل… سود زیان به‌ازای لوریج»): payload.results = same-day closed rows with pnl_lev (price%×lev) + pnl_usd (margin×pnl%×lev/100) + usd_total/win/loss tiles; table UI (#resultsBoard, .rtable CSS) + feed card shows $ PnL. App charts were ALREADY mirror-only (zero render) — verified again, no re-render path.
3. **Railway cost**: report file `/home/user/گزارش-هزینه-ریلوی.md` (real funnel numbers: TC 11 dup / PINVAL 3 / TLBREAK 1 filtered; SWR 0s; savings table + next 3 levers: live-probe share, retention, off-peak scan).
MIGRATION BACKUP: `/home/user/railway_backup/export_backup.py` (fixed: POST /app/api/login JSON) + state-*.json (feed 16, chains 24, funnel) + health-*.json. DB full dump still needs Railway dashboard pg_dump at migration day.
Re-anchored: r32 ledger test (English). Lint lesson: py-compat linter flags any string literal containing an unclosed `{` on one line (naive PEP701 check) — keep braces balanced inside test string literals.
OPEN: PINVAL merge (user-scheduled 09-27); app «سیگنال‌های امروز» design pass + RESULTS layout polish after his review; cost lever #2 retention.

## 09-26 round r35 — `33bfd5f` (LIVE boot_sha 33bfd5f05f12, boot 2026-09-26T01:22:43Z = 04:52 Tehran)
Suite 516P/1skip. User: «قوانین امشب روی اسپات هم اعمال بشه»:
1. **VERIFIED — spot DOES inherit everything**: both spot publishers (confirmed + ladder) render via the shared bot.messages_v7.generate_chart ⇒ Tehran clocks, 50-bar line lifecycle, render identity/frozen zoom, numeric-only pills, English ledger, smart-zoom recent floor, zone-stop heal… all already apply. Nothing to port.
2. **CryptoCave-clean spot charts**: market=SPOT ⇒ no FVG/IFVG strips + no POI zone boxes (only the measured green box + the shape's own lines + tool). Both-side touches/breaks stay in the TEXT (ladder).
3. **Budgets un-strangled**: SPOT_MAX_PER_DAY 2→16, SPOT_ALERT_MAX_PER_DAY 8→30. Dedup stamps + stage cooldowns remain the anti-spam layer (r29e pass was found 48 / published 0 with cap 2 + 72h/36h stamps).
4. **On-chain REFERENCE block on confirmed spot cards**: free witness engine (analysis/onchain_free — CoinGecko markets + Fear&Greed + DefiLlama, cached 10-30min, fail-open) was built & enabled but never displayed; now renders ≤4 lines under the TP ladder («رفرنس آنچین — فقط زمینه، هرگز شرطِ سیگنال نیست»). Classic 12-16 pattern set: spot engine uses render_kit.detect_patterns (full classical set incl. wedges/flags/H&S) — touch/break of BOTH sides announced by ladder (TOUCH/NEAR_BREAK/BREAK_DOWN), signals only on bullish close above (opposite side = warn-only by construction).
BUG LESSON: r35 first cut used _spot_clean35 before defining it AND deleted the original _rz assignment — renderer died («cannot access local variable '_rz'») on every chart; 7 tests caught it. Order matters inside the 3000-line render fn: define at FIRST use.
Render proof: r35_spot_render.png (DOGE spot, clean view + English ledger).
OPEN: PINVAL merge (today per user); app RESULTS polish after review; retention; TP-pill visibility when ladder far from candles (smart-zoom cap clips by design — check on real spot posts).

## 09-26 round r36 — `bc100bc` (LIVE boot_sha bc100bc11f6e, boot 2026-09-26T02:06:15Z = 05:36 Tehran)
Suite 516P/1skip. User sent 12 screenshots: 10 = bolt.new «VivaSignals Pro» reference (design-only), 2 = current app broken on phone (overlapping cards, broken chart img). User: «اپلیکیشن هم اینو میخوام در نهایت» + «انگار به اندازه موبایل اهمیت نمیده».
1. **APP_HTML fully rebuilt (webapp_viva.py)** — mobile-first, LTR navy/teal like reference. 5 bottom tabs: **Home** (4 KPI tiles TOTAL/WINRATE/AVG PNL/CUM PNL + SVG equity curve from today's closed trades [pnl_usd when all present else pnl%] + Result-Distribution donut + Top-3 strategies + 5 recent signals) / **Signals** (chips ALL/PENDING/WIN/LOSS/SPOT with counts + compact cards, tap → detail bottom-sheet: Entry/SL/TP1/TP2 tiles, Score/Leverage/Margin/PnL%, PnL مارجین/PnL دلاری rows, chart img with onerror placeholder «نمودار این سیگنال در دسترس نیست», telegram text) / **Strategies** (rows_active cards + expandable 9-stat grid + rows_archive) / **Alerts** (Notification.permission honest status + enable button + hits history) / **Control** (PnL خالص/سودها/باخت‌ها/اسکنر tiles + results table SYM/RES/PRICE/LEV/MARGIN/USD + master-pause & per-setup switches → existing /app/api/control + funnel tally). NO absolute-positioned cards anywhere → overlap structurally impossible; all flow layout, max-width 640.
2. Data: same /app/api/state contract, zero API changes. SW cache bumped viva-shell-r29d→r36 (only fonts/icons cached; HTML always network). Demo bar unchanged.
3. Tests: re-anchored r32 results-board test `resultsBoard`→`ctlTable`/`ctlTiles` (r34 board now lives in Control tab). Verified via node --check on served JS + jsdom end-to-end (tabs render, chips counts, sheet opens, placeholder fires, switches toggle). Login env name: VIVA_APP_PASSWORD (not VIVA_APP_PW).
LESSON: APP_HTML is a NON-raw Python string — `\'` inside becomes `'` (ate the escape → JS syntax error). No backslash escapes in the block now; keep it that way. Bash pkill/pgrep -f with a pattern that appears in your own command kills the shell itself — use printf-built patterns or start_process.
OPEN (queued): PINWAL merge + Railway migration 09-27; user's live phone review of r36 may spawn polish round r37 (fonts/colors per his taste, «سیگنال‌های امروز» empty-state copy).

## 09-26 round r37 — `dceeb3a` (LIVE boot_sha dceeb3a86118, boot 2026-09-26T03:11:14Z = 06:41 Tehran)
Suite 531P/1skip (new tests/test_round37_chart_laws.py ×15). User sent 17 screenshots: zoom/tool/label/target/stop/live-clock breakage on BOTH futures + spot. Root causes + fixes, ALL unified across every setup:
1. ZOOM «کندلها مرکز صفحه»: _smart_y_window rewritten — centers the RECENT 40-bar block (≥60% target, symmetric), includes entry/SL/TP/box overlays IN FULL (the r28 45%/side CLIP law was the «نصفه ابزار» bug — dead now); growth cap max(base, 2.2×span) keeps the r28 DASH far-stop clamp.
2. «ترندهای ماژور/مینور رسم نمیشن»: r33 identity anchors could fall OUTSIDE the per-render lookback → lines clamped to x=0 and floated. Render window now WIDENS (≤2.2×) to cover stored anchors before cutting the frame.
3. «برچسب ترندلاین و اسم الگوها رو بردار»: the dark right-column name pills (TRENDLINE/WEDGE_RISING/CHANNEL_ASCENDING…) deleted from the renderer — geometry still draws, words live in the text.
4. SPOT «ابزار لانگ/شورت نداره؛ فقط باکس سبز»: _is_spot flag set at render top → the whole futures tool (fills, dashed guides, pills, axis tags, INFO box, bottom ledger) is SKIPPED on market=SPOT; green box anchors at the shape's UPPER EDGE AT THE LAST CANDLE → up to spot_box_top (live-anchored / descending boxes impossible), panel clamps REMOVED (they squashed it to a 2% sliver), NO arrow inside. Spot keeps: clean tape + shape lines + DEMAND/FLIP chips + corner notes + LIVE ladder tag.
5. LIVE clock «ساعت لایو درست نیست»: _live_clock + figure _live_stamp = Tehran render moment NOW (bucket stamps froze on 12h/3d/1w); NEW _synthetic_live_candle — 3d/1w only (aggregate TFs have no forming bucket by round-15 law) synthesize from a 1h probe; other TFs keep the r12 closed-tape honesty.
6. «تارگت‌ها احمقانه» (ENA 1d +9.8%): tc_projection is NOT drawn when it outruns max(ladder)+1% or the TF sanity band (15m 5% … 1d 15%). Pills (the trade's real targets) unchanged.
7. SPOT stops «احمقانه» (DOGE −10.00% artifacts): scan_spot_symbol used min(swing, pattern lower edges) → every stop dragged to the pattern base → cap printed mechanical −10%. NEW spot_risk_levels(): stop = minor swing only (10% cap law unchanged); targets anchor on real overhead resistance (last-120-bar highs inside 1.15×path) with ATR floors + monotone guarantee; raw fractions only as fallback.
PROOFS: /home/user/r37_futures_proof.png (tool whole, no name pills, stamp=now) + /home/user/r37_spot_proof.png (box-only, no tool/arrow).
NOTE for his review: r29/r33 freeze laws still apply — chains already frozen keep their frozen zoom until price exits the box; every NEW chain/render uses the r37 engine.
OPEN: his phone re-check; PINWAL merge + Railway migration 09-27.

## 09-26 round r38 — `6a73d1c` (LIVE boot_sha 6a73d1cbfe5a, boot 2026-09-26T03:31:35Z = 07:01 Tehran)
Suite 537P/1skip (new tests/test_round38_about_brand.py ×6). User: owner brand in the app + an About section:
1. REAL logo (assets/vivasignals-logo.png, the golden diamond = channel avatar) now served at /app/icons/brand-logo.png and used in: shell header (replaced the 🎯 placeholder), a NEW Home hero card (logo + VIVA-MON.labs + «Macro & Political-Economy Strategy · SMC Scanner v7»), and the About page hero.
2. Header title → **VIVA-MON.labs** («VivaSignals Pro · SMC Scanner v7» subtitle).
3. NEW 6th nav tab **About** (معرفی): bilingual owner bio — وحید لساتی «ویوا»، کارشناس و تحلیلگر اقتصاد کلان و استراتژیست اقتصاد سیاسی، تریدر، تحصیلات مدیریت بانکی دانشگاه شاهرود، فعال از ۱۳۹۶ در سهام و کریپتو / EN mirror (Shahroud University, since 2017) + chips; project blurb (EN + FA: private SMC scanner, modular engines, 500+ tests); FORMAL bilingual IP notice (trademark VIVA-MON.labs/VivaSignals, golden-diamond logo, app + GitHub repo exclusively Vahid Lesani's; no reproduction without written consent) + © 2026 footer.
4. SW cache r36→r38, app-version R38. About verified end-to-end via jsdom (6 tabs, 3 cards, images) + live prod (logo 200 = the real 73,817-B PNG).
OPEN: his phone review of r37 charts + r38 brand; PINWAL merge + Railway migration 09-27.

## 09-26 round r39(+r39b) — `bb1e2bb`/`f8817ac` (LIVE boot_sha f8817acfadac, boot 2026-09-26T11:25:33Z = 14:55 Tehran)
Suite 545P/1skip (new tests/test_round39_app_freshness.py ×8). His morning report + About corrections:
1. **APP NEVER UPDATES** («کلا ۲۷ پوزیشن... دیگه آپدیت نمیشه»): root causes found — (a) the PWA shell had NO Cache-Control (old HTML/JS could persist), (b) state polling relied on the 60s interval only. Fixes: Cache-Control no-store+must-revalidate on /app, /app/login, no-store on /app/api/state; JS now ALSO reloads on visibilitychange (resume) and pageshow (persisted nav). SW cache r38→r39, app-version R39.
2. **CONFIRM CHART NEVER APPEARED**: /app/api/chart was MIRROR-ONLY (Telegram file_id or 404) — any signal whose app_chart|sid KV missed rendered nothing, ever. Fix: mirror-FIRST (unchanged), then a bounded RENDER FALLBACK: signals row → _candidate_from_row (+spot laws log_scale/spot_measured_box/engine for spot rows) → get_klines(view_tf, 190, cached) → generate_chart (r33 identity/freeze KV makes it faithful) → 30-min cache. Verified live: viva-pinv-AAVEUSDT-1h chart = 200, real PNG, tool+ledger+live-now stamp.
3. **r39b**: price-axis tags sat ON the ladder numbers («159.9210.00») — now placed under their number (x=1.052, va=top).
4. **About copy**: surname «لسانی» (لساتی everywhere purged), «مالکیت تجاریِ ایده» added to the IP notice (FA+EN), «در حال توسعهٔ مداوم» in project + IP cards, NEW formal bilingual Disclaimer card: no financial offer/solicitation to any person/entity; signal-use losses entirely the user's responsibility; project & developer assume no legal liability.
5. **Flaky test root-caused**: test_round23 law_guard hit LIVE BTC via get_klines inside quality_engine (green offline at boot, red once the sandbox had network + BTC dumped) → autouse fixture get_klines→None (same isolation law as chart pills).
LIVE PROOF at 14:53-14:55 Tehran: /app no-store headers ✓, state 53 rows ✓, confirm chart 200 ✓.
OPEN: his device review of r39 (feed freshness + confirm charts); PINWAL merge + Railway migration 09-27.

## 09-26 round r40 — `cc1abbb` (LIVE boot_sha cc1abbb8a41a, boot 2026-09-26T14:06:08Z = 17:36 Tehran)
Suite 556P/1skip (new tests/test_round40_laws.py ×11; ladder geometry tests re-anchored to 3 pills). His evening report + 20 screenshots; diagnosis FIRST (I viewed the charts myself — SEI/POL/TAO/PYTH), then patch-only fixes, spot + all five setups:
1. **CHART-FILL / «زوم هوشمند رو کالیبره بکن»**: ROOT CAUSE FOUND — r37 _smart_y_window guaranteed ONLY the recent-40 block + overlays; on a pumped frame (SEI/POL 15m) the early candles sat BELOW the window and rendered INVISIBLE → the left half of the PRICE panel looked empty while VOLUME painted full (panels share xlim, not ylim). Fix: the whole rendered tape is now a HARD BOUND (ylo=min(...,c_lo), yhi=max(...,c_hi) before AND after the overlay cap); high volatility → axis grows (shorter candles), the tool still fits, nothing sticks out; trendline/pattern geometry recalibrates because y now always covers the tape its anchors live on. Pills number 1..3 only. Info box «PATH x% → 3 PARTS».
2. **50-candle pivot-age cap «نباید ترندهای معتبر رو بکشه»**: three gates — (a) pattern_engine _line_alive 0.30·n (~49 bars on 164) → max(90, 0.85·n); (b) range/edge newest-pivot recency 0.30·n → max(40, 0.75·n); (c) render_kit HTF pattern window 170 → 240 bars. viva_tlbreak fitters had NO 50-bar pivot-age cap (its liveness keys off recency_bars=40/edge_atr=8 only when require_alive — unchanged).
3. **CONFIRM-GATE «قبل از بریک تأیید نشه؛ لانگ روی ترند شکسته‌به‌پایین ممنوع»**: root cause — the r12 BREAK-SIDE veto only saw lines within 3·ATR of price; a FRESHLY broken line is walked away from fast → skip → LONG confirmed on a down-broken support. Fix: before the relevance filter, the last 6 closed bars are scanned — any close through a LOW-side line below it vetoes LONG (mirror SHORT) with BREAK_SIDE_MISMATCH. Own-direction closes stay allowed (break/retest lane). INSIDE ranges/channels the INTERNAL edge-entry lane is now restricted to ALBROX + pin family (PINVAL/PINWALLQ) — TECHCLASSIC/TLBREAK inside a range fall to the containment gate (INSIDE_PATTERN_NO_BREAK).
4. **PINWAL merge «فقط PINWALL LEGACY بمونه»**: PINWALL_QUALITY_DETECTORS = [] (no new PINWALLQ candidates; budget saved); detect_pinbar_zone now folds the Q audit (anatomy/location/context/bias, +1 score when ≥78) into the classic pin as evidence + metadata pinwall_quality. detect_pinwall_quality and all legacy display branches stay for old rows.
5. **LADDER «TP4 و TP5 حذف بشه»**: build_ladder splits the path into THREE equal thirds; targets=[⅓,⅔,3/3], TP3 IS the final target; weights (40,30,30); trail_stops/band_floors/BE laws unchanged; internal-lane tp1 now path/3; ledger prints 3 TPs. WHY the tool correlated with wrong-side confirms (his question): it did NOT cause them — the confirm bug was the veto gap in (3); the 5-pill ladder only made bad confirms LOUD (5 targets, tall stack). Report delivered in-chat.
6. **Trend-engine debug**: major/minor chains = viva_tlbreak fit_validated_line (render clone in render_kit, identity KV r33); the «ترندها دیده نمیشن» family traces to the r37 window-widen + (2) age gates — both fixed; live POL re-render verified: whole tape edge-to-edge, shorter ladder, nothing clipped (r40_live_chart_POL.png + r40_zoom_proof.png).
LIVE PROOF 17:43 Tehran: /health cc1abbb8a41a ✓; login+state no-store ✓ (55 feed rows); /app/api/chart POLUSDT 200 = 3600×2040 PNG, viewed ✓.
OPEN: his device review of r40; older opens: ENA-15M FIRST-STOP-above-ENTRY2 path; SEI/AXS 8-min dedupe; UNI-3D INSIDE-RANGE co-display; Railway migration 09-27.
