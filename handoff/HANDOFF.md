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
