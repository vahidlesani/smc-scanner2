# BACKLOG.md — لیست کامل کارها (smc-scanner2)
> منبع: قوانین Viva (از پیام‌ها و بکاپ) + ممیزی کد (AUDIT) + باگ‌های میدانی (بخش ۹).
> وضعیت: **منتظر تأیید Viva** — هیچ موردی بدون «شروع کن» اجرا نمی‌شود.
> هر آیتم: [شناسه] خواستهٔ تو / مشکل فعلی (file:line) / کار اصلاحی.

---

## گروه HOT — خونریزی فوری (باگ‌های بی‌صدا، بدون تغییر منطق)
| ID | مشکل (مکان) | اصلاح |
|---|---|---|
| HOT-1 | `NameError: resolved_at` → پیام نتیجهٔ معامله هرگز نمی‌رود (`database/repository_v7.py:1318`) | `"event_at": str(latest_checked or confirmed_at)` |
| HOT-2 | `NameError: _t` → gate تکراری‌ها مرده؛ سیگنال تکراری منتشر می‌شود ولی آمار می‌گوید نگه داشته شده (`main.py:828`) | حذف همان یک خط؛ بقیهٔ بلوک (CANCELLED + update + continue) می‌ماند |
| HOT-3 | `Optional` import نشده (`main.py:18,469,487`) | افزودن به import |
| HOT-4 | مارکر heartbeat/live-break **قبل از** ارسال موفق ذخیره می‌شود → آپدیتِ آن کندل برای همیشه گم (`main.py:800-812, 617-627`) | مارکر فقط بعد از `True` شدن ارسال |
| HOT-5 | `edu_chat` تعریف‌نشده (بمب) (`bot/messages_v7.py:2780`) | تعریف یا حذف شاخهٔ مرده |
| HOT-6 | CI فقط ۲۴ تست از ۱۱۷ را می‌گیرد؛ `pytest` در requirements نیست (`.github/workflows/tests.yml`) | CI → `pytest -q` + افزودن pytest به requirements-dev |
| HOT-7 | هیچ lint ای در CI نیست؛ ۶ `undefined name` زنده‌اند | افزودن `pyflakes` به CI |

## گروه LAW — قانون تأیید، همان که تو گفتی (نه بیشتر، نه کمتر)
> قانون تو: «بعد از بریک از هر جهت، در **اولین کلوز معتبر** تأیید شود؛ SL/TP طبق کد؛ RR وتو نیست.»
> چیزی که امروز اتفاق می‌افتد: تأیید در نوک اسپایک با R:R 0.03 و استاپ ۱۰٪.
| ID | مشکل (مکان) | اصلاح |
|---|---|---|
| LAW-1 | وتوی RR/chase کاملاً حذف شده؛ هیچ کف عقلانی نمانده (`quality_engine.py:375-399`، کامیت‌های a35d6db/b21b50a) | **کف پوچی** (نیازمند تصمیم DEC-1): مثلاً rr1 < 0.5 یا entry عبورکرده از TP1 = تأیید نشود؛ به‌جایش آپدیت: «بریک معتبر بود ولی ورود ارزش ندارد» |
| LAW-2 | fast-lane روی خودِ کندلِ لحظهٔ هشدار و حتی کندل‌های قبل از آن تأیید می‌دهد (`quality_engine.py:120-231`، F13) | اسکن فقط کندل‌های **بعد از** هشدار (strictly after)؛ حذف fallback `tail(2)` |
| LAW-3 | «ATR همان فریم» در واقع mean(high-low) است؛ در یک تابع دو تعریف ATR (`quality_engine.py:212`، F12) | یک تابع مشترک `frame_atr()` = true ATR همان فریم، استفاده در همهٔ gateها |
| LAW-4 | خط شیب‌دار بدون clamp؛ شیب انفجاری = خط عمودی (`quality_engine.py:196-207`، `main.py:585-600`، F14) | clamp ضریب به بازهٔ [0,1] برای ارزیابی + سقف شیب (DEC-8) |
| LAW-5 | SL/TP در دیتکشن فریز؛ entry = کلوز نوک اسپایک → استاپ ۱۰ برابر TP (XLM/BCH) | سیاست DEC-3: یا recomputation TPها از entry تأیید، یا باطل‌کردن وقتی entry از TP1 گذشته |
| LAW-6 | SCORE 0/10 روی چارت CONFIRMED با پیش‌فرض‌های کد غیرممکن است → ظن override در env لایو | بررسی env رایلوی (`EXECUTION_MIN_SCORE`/`EDUCATIONAL_MIN_SCORE`) + payload دو کد K878487/K831533؛ اگر override بود → حذف یا مستندسازی |

## گروه MSG — زنجیرهٔ پیام، عیناً طبق قانون تو
> قانون تو: هشدار تفصیلی (به‌ازای هر ستاپ با توضیح همان ستاپ) در کانال هشدارها · مختصر در کانال اصلی با لینک کد یکتا · آپدیت شماره‌دار (قبلی پاک شود) لینک به مختصر اولیه · هشدار نهایی/آماده‌سازی · تأیید لینک به هشدار نهایی · قالب/فونت/جداکننده‌ها طبق رفرنس.
| ID | مشکل (مکان) | اصلاح |
|---|---|---|
| MSG-1 | **برش سخت `caption[:1000]`** → پیام‌های با چارت نصفه؛ footer/🧩/AI گم (`messages_v7.py:536` و `edit_chart_message`)؛ تو هرگز سقف ۱۰۰۰ نگفتی — این سقف تلگرام است نه قانون تو | بودجهٔ کپشن: چارت + کپشن مختصرِ کامل (با footer)؛ متن تفصیلی اضافه به‌صورت پیام متنی دوم، لینک‌شده زیر همان چارت. هیچ برش硬ی بدون degration |
| MSG-2 | کمکی‌ها (🕐🌀) + نظر AI در `send_confirmed`/`send_approaching`/تفصیلی نیستند؛ در بقیه بعد از کاراکتر ۱۰۰۰ می‌افتند (قانون ۴) | `_tech_aids_lines` + خط AI در **همهٔ** انواع پیام؛ ترتیب بلوک‌ها طوری که مهم‌ترها اول باشند |
| MSG-3 | قالب فریز وجود ندارد: ۴ مسیر جدا در ۲٬۸۵۶ خط (قانون ۲) | یک builder مشترک با بخش‌های ترتیب‌دار؛ بخش خالی رندر نمی‌شود؛ رفرنس تو = snapshot تست (TEST-3) |
| MSG-4 | توضیح تفصیلی باید «طبق همان ستاپ» باشد (دکترین TLBREAK ≠ ALBROX ≠ TECHCLASSIC ≠ PINWALLQ ≠ PINVAL) | بلوک دکترین per-setup در builder تفصیلی؛ متن هر ستاپ از `strategies/viva_tlbreak/*.md` و doctrineها |
| MSG-5 | آپدیتِ بااهمیت که در پنجرهٔ ۳۰ ثانیه بیفتد **برای همیشه گم** می‌شود (`main.py:246-253`، F10) | صف «آپدیت معوق»: اگر throttle شد، پرچم بماند و در اولین فرصت بعد از gap ارسال شود |
| MSG-6 | سیل «هشدار نهایی»: absorb پرچم را ریست می‌کند (`candidate_store.py:276-278`) + ماندگاری غیراتمی (`main.py:769-772,845`) + بدون throttle برای approaching | approaching حداکثر یک‌بار per chain تا تغییر مادیال zone؛ ریست absorb فقط وقتی zone واقعاً جابه‌جا شده و نه بیشتر از ۱ بار در X ساعت (DEC-6) |
| MSG-7 | لینک کد یکتا (📚) باید روی **همهٔ** پیام‌های کانال اصلی باشد (مختصر، آپدیت‌ها، نهایی، تأیید، باطل) | audit همهٔ مسیرها؛ افزودن markup جاهای جاافتاده |
| MSG-8 | پیام‌های باطل/verdict: قالب و لینک مطابق رفرنس نیست؛ چرخهٔ verdict پینبال کد مرده است (`main.py:469-520`، F16) | تصمیم DEC-5: احیا یا حذف؛ اگر احیا: قالب رفرنس + لینک |
| MSG-9 | `edit_text_message[:4000]` برش سخت (`messages_v7.py:2618`) | همان سیاست MSG-1 |

## گروه CHART — چارت لایو/تأیید
| ID | مشکل (مکان) | اصلاح |
|---|---|---|
| CHART-1 | چهار منبع TF بدون حقیقت: `_chart_frame` (context)، عنوان (df tf)، `chart_view_tf` (metadata)، فراخوان‌ها (frames خودشان) → «اسکالپ ۱m با چارت 1h»، «عنوان 15M + VIEW 30M» (`main.py:74-81`، `messages_v7.py:1428-1429, 2345-2360`) | **منبع واحد**: کندل‌ها = trigger/pattern TF؛ zoom-out فقط وقتی لول‌ها جا نشوند و در آن صورت عنوان صریح: «ستاپ 15M · نمایش 1H»؛ فراخوان‌ها هرگز df خودشان را جایگزین نمی‌کنند |
| CHART-2 | خط روند لبه‌به‌لبه بدون لنگر نمایان؛ پیوت‌ها ریز (`messages_v7.py:1235-1260,1338-1350`) | خط فقط بین دو پیوت + dashed بعد از live؛ دو پیوت با dot برجسته + برچسب قیمت/زمان؛ در caption: «خط از پیوت A (قیمت، زمان) به پیوت B» |
| CHART-3 | سقف شیب نیست → خط عمودی (ATOM 4H) | reject فیت‌های با شیب > X ATR/کندل → fallback به لول افقی همان پیوت (DEC-8) |
| CHART-4 | zone/ATR روی فریم trigger حساب، روی کندل context رسم → ناحیه «جای دیگر» | همهٔ overlayها روی همان فریمی که کندل‌ها از آن‌اند |
| CHART-5 | چارت confirmed باید اعدادِ لحظهٔ تأیید را نشان دهد نه payload بازنویسی‌شده توسط absorb (`candidate_store.py:280-290`) | snapshot اعداد تأیید در metadata (`confirmed_entry/sl/tps/rr/score`)؛ چارت و پیام تأیید از snapshot |

## گروه LIFE — چرخهٔ حیات، DB، عملکرد
| ID | مشکل (مکان) | اصلاح |
|---|---|---|
| LIFE-1 | ماندگاری غیراتمی: تغییر در حافظه، ذخیره انتهای حلقه؛ هر استثنا = گم‌شدن state (سیل/گم‌شدن آپدیت) (`main.py:845-848`) | ذخیره بلافاصله بعد از هر mutation مهم (approaching_sent, hb_bar, live_break_bar, receipts) |
| LIFE-2 | ۲۱۸ `except Exception` / ۶۱ `pass` → هیچ خطایی دیده نمی‌شود (F6) | helper `_safe(label, fn)` با لاگ ساختاریافته + شمارندهٔ `error_tally` در bot_kv |
| LIFE-3 | absorb زنجیرهٔ زنده را بازنویسی می‌کند (score/zone/sl/tp) (`candidate_store.py:280-290`) | re-anchor zone مجاز (قانون تو) ولی score/SL/TP زنجیرهٔ APPROACHING عوض نمی‌شود؛ فقط زنجیرهٔ EDUCATIONAL |
| LIFE-4 | دو سیاست expiry متضاد (`setups_v7.py:113` vs `setups_experimental.py:863`، F8) | `expiry_hours_for` تنها منبع |
| LIFE-5 | هیچ connection pool نیست؛ هر query اتصال SSL تازه (F7) | `ThreadedConnectionPool` |
| LIFE-6 | throttle سراسری بین ۳ نخ + مانیتور هر 10s با `use_cache=False` + expiry تا 14 روز → بار رشد می‌کند (F9) | کش مانیتور (TTL 5-10s)؛ تفکیک throttle به ازای هدف (TP/SL > confirm > discovery)؛ سقف زنجیرهٔ فعال (DEC-7) |
| LIFE-7 | race بین نخ اسکن و نخ مانیتور روی همان ردیف‌ها/KV (F11) | یک قفل واحد برای همهٔ نویسنده‌های candidate/KV |
| LIFE-8 | `_dead_gate_recently_alerted` سهمیه را حتی در ارسال ناموفق مصرف می‌کند؛ dictها بدون تخلیه؛ بعد از redeploy ریست (`main.py:100-130`، F17) | تفکیک check/mark + persist throttle در bot_kv |
| LIFE-9 | pandas 3: `Timestamp.utcnow` ×3 + chained assignment در تست‌ها (F18) | جایگزینی + رفع warningها |

## گروه DOC — یک حقیقت
| ID | کار |
|---|---|
| DOC-1 | حذف `CHAT_CONTEXT.md` (یک ماه غلط)؛ جایگزینی با `HANDOFF.md` + `PROJECT_MAP.md` (نوشته شده در handoff/) |
| DOC-2 | پر کردن `CHANGELOG.md` برای phase5/6/6b + یادداشت بازگشت وتوها |
| DOC-3 | تصمیم پرچم‌های ستاپ (قانون ۶ vs `config.py:164-165`) — DEC-4 |
| DOC-4 | بهداشت: حذف فایل `root`، تکراری `_next_aligned_scan`، شرط مردهٔ `cleanup_candidates`، کد مردهٔ `_pinv_*` (بر اساس DEC-5) |
| DOC-5 | ثبت تصمیم‌های DEC در `DECISIONS.md` تا دوباره بحث نشوند |

## گروه TEST — شبکهٔ ایمنی
| ID | کار |
|---|---|
| TEST-1 | تست مسیر legacy رویدادها (بدون target_state_json) → HOT-1 را می‌گرفت |
| TEST-2 | تست geometry-dup در monitor_candidates → HOT-2؛ تست send-fail برای heartbeat/live-break → HOT-4؛ تست resend برای approaching → MSG-6 |
| TEST-3 | **golden-format tests**: snapshot قالب هر نوع پیام در برابر رفرنس تو؛ هر drift قالبی = fail |
| TEST-4 | تست caption >1000 → سیاست MSG-1؛ تست TF chart (عنوان/کندل/برچسب) → CHART-1؛ تست clamp شیب → CHART-3 |

---

## ⚖️ تصمیم‌هایی که فقط تو می‌توانی بگیری (DEC)
1. **کف پوچی RR:** عدد؟ پیشنهاد: rr1 < 0.5 یا entry عبورکرده از TP1 ⇒ تأیید نشود + آپدیت «بریک معتبر، ورود بی‌ارزش». (قانون «RR وتو نیست» برای حالت‌های معقول حفظ می‌شود.)
2. **Chase:** یادداشت بماند یا وتو برگردد؟ پیشنهاد: یادداشت؛ ولی entry عبورکرده از TP1 = وتو.
3. **SL/TP در تأیید دیر:** recomputation از entry جدید، یا اعداد دیتکشن، یا باطل؟ (روی کیفیت پیام تأیید اثر مستقیم دارد.)
4. ~~TLBREAK در کد روشن شود؟~~ **حل‌شده توسط تو (پیام ۰۹-۱۴): هر ۵ ستاپ فعال، هرکدام ۳ مجوز نوبتی** → SETUP-1.
5. **چرخهٔ verdict پینبال (✅/❌/⚪ زیر هشدار):** احیا یا حذف کامل؟
6. **سقف re-fire هشدار نهایی بعد از absorb:** چند بار در چند ساعت per chain؟
7. **سقف زنجیره‌های فعال همزمان:** عدد؟ (بار سیستم به این وابسته است.)
8. **سقف شیب خط روند:** چند ATR به‌ازای هر کندل؟ (پیشنشان: 0.5)
9. **سیاست کپشن >1000:** (الف) چارت + کپشن مختصر کامل + متن تفصیلی به‌صورت پیام دوم لینک‌شده — پیشنهاد من؛ (ب) فشرده‌سازی بلوک‌ها تا جا شدن.
10. **برگشت کامیت‌ها:** (الف) اصلاح جراحی‌phase6/6b بدون revert — پیشنهاد من؛ (ب) revert کامل a35d6db+b21b50a و re-apply بخش‌های خوب (heartbeat, live-break, per-frame ATR intent)؛ (ج) revert تا c06ddc4 (phase5) و بازسازی.
11. **پیش‌نمایش تکنوکلاسیک (preview):** (الف) مشمول gate امتیاز ≥۶ شود و فقط با قالب زنجیرهٔ استاندارد؛ (ب) کلاً حذف شود (هشدار واقعی TC خودش زنجیره دارد). پیام امتیاز ۲/۱۰ تو از همین مسیر آمده (SCORE-1).

## ترتیب اجرای پیشنهادی من
1. HOT (۱ ساعت) — خونریزی بسته می‌شود.
2. LAW + DEC-1/2/3 (۲-۳ ساعت) — تأییدها به قانون تو برمی‌گردد.
3. MSG-1/2/6 + CHART-1/2/3 (۳-۴ ساعت) — چیزی که هر روز می‌بینی درست می‌شود.
4. LIFE-1/2/5/6 (۳ ساعت) — سیل و کندی و بی‌صدایی.
5. TEST (۲ ساعت) — تا دیگر بی‌صدا خراب نشود.
6. MSG-3/4/7/8/9 + CHART-4/5 + LIFE-3/4/7/8/9 + DOC (بقیه).

---

# بخش ۱۰ — خواسته‌های دو پیام ۰۹-۱۴ («گند زده شد») → افزوده‌ها به لیست

## CHAIN — شبکهٔ لینک/ریپلای، عیناً طبق دیاگرام تو
> زنجیرهٔ ریپلای در کانال اصلی: مختصر ← آپدیت۱ (ریپلای به مختصر) ← آپدیت۲ (**آپدیت۱ پاک شود** + ریپلای به مختصر) ← … ← هشدار نهایی (ریپلای به **آخرین** آپدیت) ← تأیید (ریپلای به هشدار نهایی) ← TP1 (ریپلای به تأیید) ← TP2 (ریپلای به TP1) ← … ← TP5 ← نتیجه نهایی (ریپلای به TP5 در وین / به استاپ‌هیت در لاس)؛ استاپ‌هیت = ریپلای به تأیید.
> زنجیرهٔ دکمهٔ کد یکتا (ناوبری معکوس): نتیجه↔کانال اصلی ↔ TP5/استاپ ↔ TP4 ↔ … ↔ TP1 ↔ تأیید ↔ هشدار نهایی ↔ آخرین آپدیت ↔ مختصر ↔ **تفصیلی در کانال هشدارها**.
> هر پیام TP/استاپ/نتیجه **همزمان** به کانال وین‌ریت می‌رود و با همتای خود در کانال اصلی لینک دوطرفه است.
| ID | کار |
|---|---|
| CHAIN-1 | پیاده‌سازی/ترمیم کل گراف ریپلای بالا برای **همهٔ ستاپ‌ها** (الان: آپدیت‌ها اسلات را in-place عوض می‌کنند و ریپلای به مختصر نیستند؛ TP1 پینوال به تأیید ریپلای نشده — شکایت صریح تو) |
| CHAIN-2 | دکمهٔ کد یکتا روی هر پیام = لینک به **مرحلهٔ قبلی** همان کد؛ تست ناوبری端到端 (نتیجه → تفصیلی) |
| CHAIN-3 | کانال وین‌ریت: لینک دوطرفه با همتای کانال اصلی (الان یک‌طرفه/ناقص) |
| CHAIN-4 | آپدیت N باید آپدیت N-1 را **پس از** landing موفق پاک کند؛ اگر پاک‌کردن fail شد، retry (يتیم نگذارد) |
| CHAIN-5 | جداکننده بین پیام‌های **کانال اصلی** (الان فقط کانال هشدارها دارد) — پیام‌ها قاطی نمی‌شوند |

## PNL — محاسبات نردبان/نتیجه (کیس واقعی: VIVA-PINWALLQ-K120563، ZECUSDT SHORT)
| ID | مشکل | کار |
|---|---|---|
| PNL-1 | سود لِگ TP1: پیام $+0.92 نشان داد، محاسبهٔ تو ≈ $2.5 (مارجین 40، لوریج 15 → ن notionال 600؛ 35% بسته در TP1) | فرمول `leg_profit_usd`/weight audit + تست با اعداد واقعی همین کیس |
| PNL-2 | پیام نهایی سود تجمعی لِگ‌های زده‌شده را ندارد (TP1 زده شده ولی نتیجه −0.16) | تجمیع realized legs در CLOSED event |
| PNL-3 | «این نتیجه وین بوده اما لوز شده»: klasyfikacja از لِگ باقی‌مانده تنها | result = sign(سود تجمعی کل)، نه لِگ آخر |
| PNL-4 | قانون BE تو: بعد از TP1 استاپ = **۵ تیک پایین‌تر از entry در شورت / ۵ تیک بالاتر در لانگ** | بررسی `advance_ladder`؛ اگر BE دقیقاً entry است یا جهت غلط → اصلاح + تست |
| PNL-5 | سمت TPها در شورت (TP1 باید زیر entry باشد) — sanity check جهت‌ها | guard: برای SHORT همهٔ TP < entry و stop > entry (و برعکس)؛ وگرنه reject در detection |

## SCORE/DUP — gate امتیاز و تکراری‌ها
| ID | مشکل | کار |
|---|---|---|
| SCORE-1 | پیام امتیاز **2/10** در کانال، در حالی که زیر ۶ بسته شده → مسیر **preview تکنوکلاسیک** از gate امتیاز رد نمی‌شود (`send_technoclassic_preview` + `technoclassic_preview_alerts`) | preview هم مشمول educational_min_score؛ یا حذف preview و ادغام در زنجیرهٔ استاندارد (تصمیم تو: DEC-11) |
| SCORE-2 | ~۵ هشدار تفصیلی TC در یک ناحیه/قیمت یکسان (ATOM 4h) → قانون same-zone برای preview/TC کار نمی‌کند | dedupe ناحیه‌ای روی همهٔ مسیرهای پست (preview شامل) |
| SCORE-3 | پیام مختصر تکراری می‌آید | dedupe امضا برای مختصر (مثل upd_sig) |

## AID/FORMAT/AI — محتوا و قالب
| ID | کار |
|---|---|
| AID-1 | **کتابخانهٔ توضیح توصیفی** (نه وضعیت خام): ≥۱۵ عبارت برای فیبو (پولبک به 0.38 / بریک 0.618 به بالا / ریجکت در 1.27 …)، ≥۱۵ تا برای هر EMA (نزدیک به 51 / بریک 51 به بالا …)، ≥۱۵ تا برای RSI (واگرایی معمولی/مخفی، OB/OS، حمایت/مقاومت RSI)، ۱-۲ خط برای هر سشن. انتخاب عبارت بر اساس وضعیت واقعی کندل آخر |
| FORMAT-1 | قالب تفصیلی PINWALLQ / ALBROX / PINVAL = رفرنس (الان فقط TLBREAK/TC آپدیت شده‌اند) |
| AI-1 | نظر AI: فارسی، چند جملهٔ معنادار (نه برچسب کوتاه انگلیسی)؛ در همهٔ انواع پیام |
| CHART-6 | رسم شکل الگوها روی چارت مثل رفرنس‌های تو (وج/مثلث/کانال/FVG/فلگ با اضلاع و برچسب) — نه فقط خط و ناحیه |

## SETUPS/INFRA
| ID | کار |
|---|---|
| SETUP-1 | **هر ۵ ستاپ فعال** (PINVAL, PINWALLQ, ALBROX, TLBREAK, TECHCLASSIC) هرکدام با ۳ مجوز نوبتی — DEC-4 توسط تو حل شد: همه روشن |
| INFRA-1 | بررسی اینکه کار دیشب واقعاً دیپلوی شده یا silent-skip خورده (boot_version در bot_kv vs HEAD؛ در صورت گیر، re-trigger) |
| INFRA-2 | بررسی env لایو: EXECUTION_MIN_SCORE / EDUCATIONAL_MIN_SCORE / LIVE_STYLES / پرچم‌های ستاپ (منبع ظن SCORE 0 و 2) |

## DEF — تعریف انجام‌شده (قول من وقتی گفتی «شروع کن»)
فهم → لیست → خواندن کد → اصلاح → **تست** → push → دیپلوی → تأیید ساکسز (boot_version + تست لایو) → گزارش دقیق و واضح به تو.

---

# بخش ۱۱ — راستی‌آزمایی phase7 (کامیت e32e1e2 + استمپ 0b72040، ۰۹-۱5 ۰۰:۳۷Z)
> تست‌ها: 120 passed, 1 skipped ✅ · pyflakes: همان ۳ NameError قبلی هنوز هست ❌ · CI دست‌نخورده ❌

## ✅ درست شده (در کد دیده شد)
| آیتم | شاهد |
|---|---|
| CHAIN-1 (تا حدود زیاد) | آپدیت‌ها reply به anchor مختصر (`_pro_slot_post(reply_to=anchor_pro)`)؛ هشدار نهایی پیام مستقل reply به آخرین آپدیت (`send_approaching` جدید)؛ Confirmed reply به approach/anchor |
| CHAIN-5 | جداکننده یک‌بار در هر زنجیره روی کانال اصلی (`pro_sep`) |
| MSG-1 (نصفه) | `_fit_caption`: برش روی مرز خط + بستن تگ‌های HTML باز |
| AI-1 | `_fa_advisory` (حداقل ۲۴ کاراکتر و فارسی) + `_ai_rich_note` |
| AID-1 | `analysis/aids_bank.py` بانک‌های ۱۵/۱۵/۱۵/۸ + انتخاب state-aware (CROSS/NEAR/RETEST…) با seed پایدار درون کندل |
| FORMAT-1 | `build_educational_message` + `_ai_detail_block` برای همهٔ ستاپ‌ها |
| CHART-1 | عنوان و نوار چارت = trigger TF همیشه؛ escalation و `chart_view_tf` حذف شد؛ PAT در زیرنویس |
| SCORE-1 | preview زیر educational_min_score صحبت نمی‌کند |
| SCORE-2 (preview) | هر کندل الگو حداکثر یک آپدیت preview (`upd_bar`) |
| PNL-2/3 (علت اصلی) | settlement = فقط کارمزد صرافی؛ slippage نمایشی → کیس ZEC دیگر LOSS نمی‌شود |
| CHAIN-3 (ناقص) | آینه‌کردن stop به کانال نتایج + `attach_results_link` دوطرفه برای TP/stop/CLOSED |
| INFRA (قسمتی) | boot_version از BUILD_INFO + APP_VERSION، بدون رشتهٔ دستی |

## ❌ هنوز خراب (phase7 دست نزده)
HOT-1 (`resolved_at`) · HOT-2 (`_t`) · HOT-3 (`Optional`) · HOT-4 (مارکر قبل از ارسال) · HOT-6/7 (CI unittest + بدون pyflakes) · LAW-1..6 (quality_engine دست‌نخورده: کف پوچی RR، کندل‌های بعد از هشدار، ATR واحد، clamp) · LIFE-1/2/5/6/7 (ماندگاری اتمی، _safe، pool، throttle، قفل) · MSG-5 (صف آپدیت معوق) · CHART-2/3 (لنگر پیوت‌ها + سقف شیب — «art frozen») · CHART-6 (رسم شکل الگوها) · F8 (دو سیاست expiry) · F16 (کد مرده پینوال) · PNL-1/4/5 (فرمول لِگ، قانون ۵ تیک، جهت TP) · DOC همه.

## ⚠️ ایرادهای جدیدِ خودِ phase7
| ID | ایراد |
|---|---|
| N1 | `_fit_caption` فوتر می‌گذارد «📎 ادامه در پیام لینک‌شدهٔ همین کد» ولی **هیچ کدی آن پیام ادامه را نمی‌فرستد** → محتوا باز هم گم می‌شود، فقط مرتب‌تر |
| N2 | gate جدید ۳۰۰ ثانیه‌ای `send_setup_update` فقط ایموجی‌های `state_fa` را critical می‌داند؛ ولی **⚡live-break و heartbeat با `note_fa` می‌آیند** → ⚡ دومِ همان زنجیره داخل ۵ دقیقه بلعیده می‌شود (خلاف قانون «در لحظه») |
| N3 | `alert_dedup` در bot_kv یک read-modify-write روی یک کلید از چند نخ است → race می‌تواند مدخل‌ها را گم کند |
| N4 | `attach_results_link` کل reply_markup پیام اصلی را **جایگزین** می‌کند → اگر روزی آن پیام دکمهٔ دیگری (📚) داشته باشد، پاک می‌شود |

## 🔇 تشخیص سکوت (از ۰۱:۴۰ ایران = 22:10Z)
phase7 ساعت **23:30Z** کامیت شده — یعنی سکوت **قبل از وجود phase7** شروع شده و روی بیلد قدیمی (-11b) اتفاق افتاده. پس phase7 علت سکوت نیست؛ یا سرویس/DB در 22:10Z مرده (ظن اول: exhaustion اتصال‌ها — LIFE-5/F7) یا دیپلویphase7 اصلاً بالا نیامده.
**سه چک دو-دقیقه‌ای (نیازمند دسترسی Railway/DB):**
۱) `bot_kv.boot_version` → sha باید `3bf6a964d` باشد؛ اگر نه، phase7 هرگز بالا نیامده (silent-skip) → re-trigger.
۲) `bot_kv.monitor_summary.when` و `scan_summary.when` → اگر تازه‌اند (هر چند دقیقه) موتور زنده است و سکوت از gateهاست؛ اگر کهنه‌اند، سرویس مرده/لوپ کرش.
۳) لاگ Railway از 22:10Z به بعد: `Discovery error` / `Candidate monitor error` / خطاهای اتصال Postgres / restart.

---

# بخش ۱۲ — حکم‌های جدید Viva + ریشهٔ خشکسالی پین‌بار (تشخیص تجربیِ من)

## حکم‌های ثبت‌شده (۰۹-۱۵)
| ID | حکم | اثر روی لیست |
|---|---|---|
| R-1 | چارت = تایم تریگر، **با یک استثنا**: چارت‌های چرخهٔ حیات (TP/استاپ/نتیجه) اگر ابزار LONG/SHORT در ۲۰-۳۰ کندل جا نشد/از کادر بیرون زد، مجازند روی تایم بالاتر رندر شوند تا ابزار خراب نشود. تحلیل اولیه/هشدار/تأیید = همیشه تایم تریگر | CHART-1 اصلاح شد؛ CHART-1b جدید: escalation فقط برای چارت‌های lifecycle و فقط با برچسب صریح |
| R-2 | SCALP قبلاً خاموش بوده، الان روشن شده؛ **مشروط**: اگر جای استاپ/TPها درست بود چند روز بماند، وگرنه دوباره خاموش | SETUP-2: قبل از روشن‌ماندن، گاردهای PNL-5/LAW-1 لازم است؛ وگرنه اسکالپ با R:R 0.03 چاپ می‌کند |
| R-3 | نردبان: ۱D=سویینگ بلندمدت، ۴H=سویینگ میان‌مدت، ۱H=سویینگ میان‌مدت، ۱۵M=سویینگ کوتاه‌مدت | MSG-LABEL: همین نام‌های فارسی در هدر پیام‌ها و چارت‌ها |
| R-4 | «هر کندل الگو یک آپدیت» فقط برای **heartbeat پایان کندل** و flipهای درون‌کندلی preview است. **بریک/رویداد مادی = آپدیت فوری** (قبلی پاک + شمارهٔ بعدی)، بدون سقف هر کندل. تأیید = کلوز تایم تریگر | N2 باید دقیقاً همین شود: ⚡ و بریک‌ها از gate 300s/upd_bar مستثنا |
| R-5 | لینک‌ها: زنجیرهٔ کد **یک‌طرفه** است (هر پیام → مرحلهٔ قبل). تنها جهت دوم: دکمهٔ کد روی پیام کانال نتایج → همتای خودش در کانال اصلی. دکمه‌ها **هنگام ساخت** پیام ست می‌شوند (📚 مرحلهٔ قبل + 🔗 نتایج)، نه با edit بعدی | CHAIN-2/3 بازنویسی شد؛ N4 حذف شد |

## 🔬 خشکسالی خانوادهٔ پین‌بار — اثبات تجربی (۴ پنجرهٔ زمانی × ۱۲ نماد × ۴ استریم = ۱۹۲ تلاش per detector، دادهٔ زندهٔ Bybit)
| لایه | عدد | معنی |
|---|---|---|
| پین‌های تشخیص‌داده‌شده | ≥۲۳ (۲۱ رد polarity + ۲ base) | دیتکشن کار می‌کند |
| ردِ gate قطبیت (zone_polarity) | ۲۱ | طبق طراحی؛ قاتل اصلی نیست |
| base ردشده از `detect_pinbar_zone` | **۲ از ۱۹۲** | gateهای شکل/ناحیه بسیار تنگ |
| امتیاز PINWALLQ روی baseها | **۵۲ و ۴۷** (اجزا: anatomy 7/2، location 27، context 8، bias 10) | آستانه **۷۸** در این رژیم **غیرممکن** است |
| بازماندهٔ PINWALLQ/PINVAL/ALBROX | **صفر** | خشکسالی تأیید شد |
| ALBROX (اسپایک ۳.0 ATR) | ۰ از ۱۹۲ | آستانه هرگز رخ نمی‌دهد |
| مکانیسم مرگ PINVAL | وقتی `pinwall_quality_enabled=True`، دیتکتور PINVAL **اصلاً ثبت نمی‌شود** (`setups_v7.py:1137-1143`: Q جای PINVAL را می‌گیرد) → base_score=9 هرگز منتشر نمی‌شود | یعنی یک فلگ، هر دو مسیر را با هم خاموش کرده |

### اصلاح پیشنهادی (قابل اجرا بدون دیپلوی برای دو مورد اول، چون env هستند)
| ID | کار |
|---|---|
| DROUGHT-1 | `PINWALL_QUALITY_MIN_SCORE` در env رایلوی: 78 → **60** (و سایه‌لاگ امتیازها برای کالیبراسیون یک‌هفته‌ای) |
| DROUGHT-2 | `ALBROX_MIN_SPIKE_ATR` → **2.2** و `ALBROX_MIN_RECLAIM_FRAC` → **0.35** در env |
| DROUGHT-3 | **کد**: fallback پینوال — اگر Q به‌خاطر امتیاز رد شد ولی base_score ≥ educational_min_score بود، همان بار به‌عنوان PINVAL (با برچسب خودش) منتشر شود؛ dedupe همان میله حفظ شود |
| DROUGHT-4 | سایه‌لاگ: امتیاز Q و دلیل رد هر پین در `bot_kv.pin_funnel` (۲۴ مورد آخر) تا دفعهٔ بعد حدس نزنیم |

---

## 13) FIX8 BATCH — EXECUTED & DEPLOYED (2026-09-15, ~17:30 Tehran)

**Commits:** `7757421` (fix8) + `a380149` (BUILD_INFO stamp) → pushed to `main`.
**Railway deploy:** `41910978` — BUILDING→DEPLOYING→SUCCESS in ~80s (13:53:34Z), stable on re-check +3min.
**Env now live (DROUGHT-1/2 applied):** `PINWALL_QUALITY_MIN_SCORE=60` (was 78), `ALBROX_MIN_SPIKE_ATR=2.2` (was 3.0), `ALBROX_MIN_RECLAIM_FRAC=0.35` (was 0.45).

| Item | Fix | Files |
|---|---|---|
| HOT-1 | confirmation-event NameError (`resolved_at`/`resolution_candle` undefined) → `event_at = str(latest_checked or confirmed_at)` (closing-candle ts), `live_price = candle.close` | database/repository_v7.py |
| HOT-2 | geometry-dup cancel crashed on `_t()` (out of scope) → gate worked silently NO more; counter line removed, CANCELLED path clean | main.py |
| HOT-3 | `Optional` import added | main.py |
| HOT-4 | dedup markers set ONLY after successful Telegram send: heartbeat `hb_bar` (set+persist inside send-success branch) and ⚡live-break (`_live_break_watch` now returns `(note, key)`; caller persists `live_break_bar` after success) — a failed send retries next cycle instead of eating the one-per-candle alert | main.py, tests/test_signal_guards.py |
| N2/R-4 | `send_setup_update(..., critical=False)` param; `_critical = critical or state-prefix`; ⚡live-break passes critical=True; MATERIAL absorb updates bypass the 300s gap (`elif`→`if`, stat kept for observability) — identical repeats still swallowed by content-hash | bot/messages_v7.py, main.py |
| DROUGHT-3 (R-5) | PINVAL ALWAYS registered as pin-family fallback when `pinwall_quality_enabled` (was `elif` — the killer); `scan_setups` dedupes same symbol+direction PINWALLQ/PINVAL pair (Q wins) → pins rejected by Q score now speak via PINVAL; no double-post | analysis/setups_v7.py |
| FORMAT-2 | 🧩 merge: no more `• •` double bullets; empty-fallback «تأیید کمکی اضافه‌ای ثبت نشده» only when confirmations+aids BOTH empty; pin-family doctrine prose blocks: PINVAL 4 (anatomy/zone-location/polarity-bias/targets-RR from detector vars), PINWALLQ 4 quality components (anatomy 30/location 27/context 20/bias 10, ✅ at ≥60%) prepended before base blocks | analysis/setups_experimental.py, bot/messages_v7.py |
| N1 | `_split_caption` → (head, tails); `send_photo` posts the tail as a reply-linked continuation message (tag-balanced via `_balance_html_tags`); `_fit_caption` = head-only safety net for edit paths — «📎 ادامه در پیام لینک‌شده» now TRUE | bot/messages_v7.py |

**Verification:** `pytest tests/` → 120 passed, 1 skipped. pyflakes on all touched files → no NEW findings (331/335 = known walrus false positives). Smoke script `/home/user/smoke_fmt.py`: golden-shape PINWALLQ message renders header→intro→⭐→doctrine ✅/⚠️ blocks (━━━)→🔎→⚖️→🧭→🧩 (single bullets)→⚠️→AI→footer; split/fit round-trip OK.

**Expected live behavior after this deploy:** pin family un-droughted (Q ≥60 speaks as PINWALLQ; 40-59-grade pins speak as PINVAL with full doctrine blocks); ALBROX spike gate reachable at 2.2 ATR; ⚡live-break + material absorbs immediate; heartbeats never lost to send failures; no half-cut captions.

**Still open (next rounds):** DROUGHT-4 shadow funnel log (`bot_kv.pin_funnel`); CHART-7 faint trigger-TF zone boxes on PINWALL/ALBROX charts (no borders, very faint fill); VISION-1 multi-TF reversal-swing engine for PINWALL/PINVAL (higher+lower TF identification candles, ride the move early, NOT ATR-dryness-gated) — build gradually with Viva; awaiting his chart samples for FORMAT-2 visual check.

---

## 14) FIX9 — VIVA'S 09-15 EVENING RULINGS + PROPOSALS QUEUE

**Rulings received (his words) → codified:**
- **R-6** «اصلا دوست ندارم یک پیام بشه ۲ پیام و بهم ریپلای بشه» — no message may ever become two reply-quoted messages. Detailed-message overflow: continuation comes RIGHT BEHIND as a plain message (current behavior he approved: «ادامش پشتش میاد بدون ریپلای اوکیه اینجوری بمونه»). MOST messages must fit in one long message anyway.
- **R-7** «پیام مختصر ... باید در یک پیام باشه و ریپلای بشه به پیام تفصیلی اولیه در کانال هشدارها» — the compact initial alert in the MAIN channel = ALWAYS exactly ONE message, linked to the permanent detailed alert in the ALERTS channel (cross-channel reply is impossible in Telegram; the 📚 URL button is the link mechanism — already wired since phase7).
- **R-8** TP ladder (re-confirmed; was already implemented in phase7, now TEST-LOCKED): TP1→Confirmed receipt; TP2→TP1; TP3→TP2; TP4→TP3; TP5→TP4; final result→TP5 when WIN at TP5 (generally: WIN→exact last TP receipt; stop-exit→its stop receipt, per 09-14 verbatim). Stop/TRAIL_STOP receipts→Confirmed (09-14). His «۴ به ۴» read as typo for «۴ به ۳» — confirmed by code+test; flagged to him in reply.
- **R-9** aids & AI note: delegated improvement («اگر فکر میکنی میشه بهترش کرد انجام بده») — DONE in fix9 (direction-aware phrasing, 2 RSI-bank content bugs fixed, setup-aware AI doctrine lines).
- **R-10** PROCESS LAW: «همیشه اول لیست کن کارها و پیشنهادها رو؛ هرچی با هم توافق کردیم در هندآف و فایل اطلاعات پروژه آپدیت کن» — every round: list tasks/proposals FIRST; agreed items → HANDOFF/PROJECT_MAP/BACKLOG.

**fix9 execution:** commits `a659beb` + `32103e6` → pushed `main`; Railway deploy `80687e25` SUCCESS (~14:37Z). Tests 122 passed / 1 skipped (2 new: ladder-chain contract, compact single-message contract). Compact degrade order: rule-shorten → extra-lines → aids one-by-one → bias line; core never drops; 998-char test case keeps ALL aids in one message.

**Content-hash dedup — explained to user (kept, pending his veto):** it swallows ONLY byte-identical update repeats (same state/note/score/zone/SL = zero news), which is his own 09-12 law («توی ثانیه چه تغییری شده که آپدیت میده؟!»). Nothing new is ever silenced: ⚡live-break, verdicts, confirmations and MATERIAL absorbs (zone moved ≥0.2×ATR or structure changed) all bypass the 300s gap since fix8.

**PROPOSALS QUEUE (awaiting Viva's agreement — do NOT build before he says yes):**
- **PROP-1 (his idea, I endorse): Confirmed-signals back-channel.** New env `CHAT_ID_SIGNALS`; MIRROR (current channels unchanged, per «کیفیت کانالهای فعلی همین بمونه») of: final alert/Approaching + Confirmed + TP1–5 + stop/trail + result — each posted with the same ladder reply-chain inside the new channel and its code button back to the detailed alert. Clean high-S/N journal for serious members. Needs: Viva creates the channel, adds the bot as admin with post rights, sends the chat id.
- **PROP-2 (mine): Position-card root.** In PROP-1 channel, each confirmed signal opens with ONE summary card (entry/stop/ladder/RR/weight plan); all lifecycle receipts reply to the card → instant read of an open position.
- **PROP-3 (mine): Weekly digest.** Friday auto-post in PROP-1 channel: signals count, confirm rate, win/loss, avg RR, best/worst — from the existing results ledger.
- **PROP-4 (mine): Pinned legend.** One pinned message in PROP-1 explaining icons/structure once (⛔/⚡/🕐/🎯/🔐/❌).
- Carried from §12/§13: **DROUGHT-4** shadow funnel log; **CHART-7** faint trigger-TF zone boxes (awaiting his chart samples); **VISION-1** multi-TF reversal-swing engine (gradual co-build, NOT ATR-dryness-gated).

**Open questions sent to Viva this round:** (1) PROP-1 mirror-vs-move confirmation + channel creation; (2) «۴ به ۴» typo confirmation; (3) compact template — «قالب و فرمتش اینه» with no new attachment received; asked to re-send if a specific new template was meant (current = shared skeleton + per-setup concepts, which matches «مفاهیم هر ستاپ مربوط به خودش»).

## 15) FIX10 — FORMAT-3 + کانال ژورنال (PROP-1) — EXECUTED & DEPLOYED (2026-09-16 صبح، تهران)

**Deploy:** commits `fc394a4` + `6a9f62c` → pushed main; Railway deployment **37b2daa3 SUCCESS** (~16:24Z). Env **CHAT_ID_VIVA_SIGNALS=-1003915517132** upserted before deploy. Tests **122 passed / 1 skipped**; smoke PASS.

**PROP-1 LIVE (کانال VIVA-MON-SIGNALS):** `_sig_mirror(code, kind, text, chart, reply_kind)` در messages_v7 — mirror افزونه‌ای است، کانال‌های فعلی دست‌نخورده. چهار هوک: Approaching(new post) / Confirmed(reply→approach) / tail پله‌ها و استاپ در send_ladder_event (reply→tp{n-1} یا confirmed؛ stop→confirmed) / نتیجه در send_trade_close_event (reply→tp{hit} وگرنه stop). زنجیرهٔ reply مستقل با کلیدهای `sig_*` در bot_kv (`setup_chain|<CODE>`) — قوانین «بدون reply-linked split» و «دکمه‌ها فقط هنگام ساخت» رعایت شده (mirror همان دکمهٔ کد را دارد).

**FORMAT-3 (پارت ۲ تفصیلی، طبق paste دستی او):** ترتیب ⚖️ شرط تأیید → 🧭 کانتکست → 🧩 تأییدهای کمکی → 🔥 نشانهٔ فعال → ⚠️ هشدارها → 📐 تحلیل → 🤖 → 💼. بین هر مفهوم `VIVA_SEP_ITEM` (━×10)؛ عنوان همهٔ بخش‌ها bold در ابتدای خط؛ بلوک ⚖️ سه‌تکه (شرط / دکترین سناریوی داخلی با توضیح هر ترم / ابطال)؛ `_sep_bullets` روی بخش‌های tlbreak/ai/management.

**🔥 zone_trigger (دکترین تریگر):** `detect_zone_trigger(df, dir, zone_b, zone_t, atr)` در setups_v7 — اولویت engulfing → pin → doji/کی‌بار → compression، خروجی `{title_fa, lines[2]}` در `md["zone_trigger"]`؛ پین‌وال/ALBROX واریانت پین خودش را از detect_pinbar_zone می‌گیرد. فقط وقتی واقعاً رخ داده چاپ می‌شود؛ لحن هر ستاپ جدا (messages_viva_tlbreak._STAGE_FA + ai_advisory_fa/management_fa فارسی شدند).

**Compact = یک پیام (رولینگ جدید):** قالب فعلی حفظ شد؛ اما ۴ تحلیل کامل + هسته در ۱۰۲۴ کاراکتر کپشن فیزیکاً جا نمی‌شود ⇒ compact **دیجست چهارخانواده** می‌برد: سشن فارسی | نردبان EMA (یک خط) در ردیف اول؛ فیبو | RSI (کوتاه‌شده تا «؛») در ردیف دوم — هر دو با ━ جدا. تحلیل کامل در تفصیلی می‌ماند. Degrade gate: 1000→**1020** (سقف واقعی تلگرام 1024) با `_fit_caption(out,1015)`؛ هنگام drop هر aid، ردیف ━ قبلی‌اش هم می‌رود. پروب: ۱۰۱۷ کاراکتر، هر ۴ خانواده، بدون continuation.

**Persian-everywhere:** `_SESS_FA` module-level (کدهای واقعی indicators: LONDON/NEW_YORK/ASIA/LONDON_NY_OVERLAP/OFF_SESSION)؛ PATTERN_FA برای اسامی الگوها؛ رویداد close (ورود/استاپ ابتدایی/قیمت زنده-خروج/برد✅/باخت❌)؛ هشدارها Stop→استاپ؛ حذف خط تکراری سشن در confirmations.

**تست‌های به‌روز (رولینگ نو، نه بازگشت رفتار):** asserts سشن فارسی؛ aids تستی در اندازهٔ واقعی بانک؛ cap تست compact ≤1020.

**اقلام باز:** (1) دو واژهٔ «Approaching/Confirmed» هنوز در خط پایانی compact (متن قانون مصوب قدیمی) — منتظر رأی او برای فارسی‌سازی نام حالت‌ها؛ (2) **CHARTS = دور بعد**: باکس نواحی + trendline/wedge/triangle/channel مثل ۸ رفرنس uploads — اول PLAN ارائه شود، قبل از هر کار شکننده اجازه بگیر (قانون PROCESS); (3) سپس دور کالیبراسیون ستاپ‌ها/تأییدیه‌ها.

## 16) FIX11 — لینک‌چین ژورنال + نوشتن merge-safe + گزارش جمعه (PROP-3) — DEPLOYED (2026-09-16)

**Deploy:** `eac5980`+`b7248e0` pushed; Railway **f495077b SUCCESS**. Tests 122 passed/1 skipped.

**ریشهٔ «هیچی لینک/ریپلای نیست» در کانال سیگنال:** نویسنده‌های همزمان lifecycle دیکت قدیمی chain را روی bot_kv می‌کوبیدند و کلیدهای `sig_*` می‌پریدند ⇒ `_setup_chain_set_by_code` حالا MERGE می‌کند (read-modify-write). زنجیرهٔ ریپلای داخلی ژورنال از این به بعد یتیم نمی‌شود.

**لینک‌چین توافق‌شده، یک‌طرفه، بین‌کانالی با دکمهٔ URL:** approach/confirmed ژورنال → دکمهٔ « پیام مختصر در کانال اصلی» (anchor compact)؛ TP/stop/result ژورنال → دکمهٔ «🔗 همین پیام در کانال اصلی». ادامهٔ_walk داخل کانال اصلی بدون تغییر: compact → هشدار ابتدایی → مفصل. کانال نتایج از قبل دوطرفه لینک است (attach_results_link + لینک inline در send_stop/tp_event_to_results) — دست‌نخورده.

**PROP-3 زنده:** `build_weekly_results_digest()` — جمعه‌ها ۱۹:۰۰ تهران (هوک main loop با کلید هفتهٔ ایزو) یک پیام شیک: به تفکیک ستاپ تعداد/برد/باخت/وین‌ریت/سود-ضرر دلاری (margin×leverage×pnl%) + جمع کل؛ در CHAT_ID_RESULTS و CHAT_ID_VIVA_SIGNALS؛ کانال اصلی دست‌نخورده. پیش‌نمایش روی ledger مصنوعی تأیید شد.

**CHART-8 (SPEC تاییدشدهٔ Viva 09-16 شب — اجرای مرحله‌ای پس از پرسش‌وپاسخ):**
- رفرنس: uploads/TradingView_Screenshot_1789497505707.jpg + ۸ رفرنس قبلی. بکگراند/کندل/لوگو/واترمارک/ضخامت خطوط = فعلی (او تغییر رنگ بکگراند/کندل را KONCEL کرد؛ فقط شکل و رنگ باکس‌ها از رفرنس).
- رنگ باکس‌ها (نیمه‌شفاف بسیار ملایم، بدون بوردر ضخیم): فلگ‌لیمیت نزولی=زرد لیمویی / صعودی=سبز فسفری روشن؛ فیلیپ‌زون نزولی=نارنجی روشن / صعودی=آبی روشن؛ اوردرابلاک نزولی=قرمز کمرنگ مایل به صورتی / صعودی=سبز چمنی روشن؛ بقیهٔ نواحی عرضه=قرمز کمرنگ / تقاضا=سبز کمرنگ.
- نام هر باکس روی چارت در جای مناسب، روی کندل/قیمت نیفتد (Persian، چیپ کوچک نیمه‌شفاف).
- نواحی و الگوها بعد از تأیید، در چارت‌های هیت/استاپ حذف نشوند.
- خطوط TP: یکپارچه (solid) بهتر از خط‌چین (در صورت امکان).
- ابزار لانگ/شورت فعلی خوبه؛ شبیه‌تر به TV اختیاری.

## 17) FIX12 — پیام مختصر هرگز دومessage نمی‌شود + صف بهینه‌سازی (منتظر تایید) — DEPLOYED

**Deploy:** `9ce2e39`+stamp pushed; Railway **6e3f6541 SUCCESS**. Tests **123 passed / 1 skipped** (تست جدید: قرارداد «بدون پیام ادامهٔ جدا»).

**ریشهٔ پیام سرگردان موینگ‌اوریج:** send_photo کپشن را از ۱۰۰۰ کاراکتر می‌شکست در حالی که builder مختصر تا ۱۰۲۰ مجاز بود ⇒ خط دیجست تأییدهای کمکی گاهی به‌صورت پیام دومِ جدا می‌رفت. حالا: `send_photo(caption_limit=…)`؛ نویسندهٔ تک‌کانالی اصلی (`_pro_slot_post`) با **caption_limit=1024** (سقف سخت تلگرام برای کپشن عکس) پست می‌کند ⇒ مختصر و همهٔ آپدیت‌های شماره‌دار همیشه **یک پیام**. آپدیتِ بلندتر از ۱۰۲۴ اول به دیجست سوییچ می‌کند؛ فقط اگر یادداشت خودش هنوز نگنجید، ادامهٔ بدون‌ریپلای (قانون ۰۹-۱۵) پشتش می‌آید.

**پاسخ‌های ثبت‌شده به Viva:** (۱) «چرا ۱۰۲۴؟» → سقف سخت کپشن عکس تلگرام؛ پیام تفصیلی پیام متنی است (سقف ۴۰۹۶) پس ۲۰۰۰ کاراکتر در یک پیام جا می‌شود؛ مختصر روی عکس سوار است. (۲) «ریپلای به پیام تفصیلی» → ریپلای در تلگرام فقط داخل همان چت ممکن است؛ مختصر در کانال اصلی و تفصیلی در کانال هشدارهاست ⇒ غیرممکن؛ جایش دکمهٔ 📚 (لینک‌چین یک‌طرفهٔ توافق‌شده) می‌ماند. گزینهٔ باز برای رأی او: انتقال تفصیلی به کانال اصلی (توصیه نمی‌شود: کیفیت کانال اصلی).

**صف بهینه‌سازی (پیام ۰۹-۱۶ شبه‌شب او — اجرای هر بند پس از تایید صریح):**
- **T1 باگ استاپ اسکالپ ۵/۱۵دقیقه:** حدضررهای غیرمعقول هنوز تأیید می‌شوند (در چارت‌های ارسالی مشخص است). پیشنهاد گارد: فاصلهٔ استاپ از ورود در بازهٔ [۰٫۶×ATR، ۲٫۵×ATR] تایم تریگر؛ هرگز آن‌سوی لبهٔ نزدیک‌ترین ناحیهٔ مخالف؛ وگرنه confirm رد می‌شود. اول چارت‌های ارسالی‌اش بررسی می‌شود.
- **T2 PINWALL (هر دو: لجسی و کوآلیتی):** سیگنال وسط روند ممنوع؛ فقط وقتی پین روی ناحیهٔ مهم است و قیمت یا ناحیه را ریجکت می‌کند یا می‌شکند.
- **T3 دور بهینه‌سازی کیفیت PINWALL** — نقطهٔ شروع او؛ با چارت‌های دستی خط‌خوردهٔ خودش به‌عنوان نمونهٔ آموزشی («اینجوری شد تایید شورت بده»).
- **T4 CHART-8:** باکس نواحی + نام فارسی روی چارت (پالت رنگی او)، ماندن نواحی/الگوها در چارت‌های هیت/استاپ، خطوط TP یکپارچه، و چارت PINWALL باید نواحی کف/سقف/میانه را نشان بدهد. پیش‌فرض‌های منتظر رأی: برچسب داخل باکس سمت خلوت‌تر؛ سقف ۶ باکس مرتبط.
- **T5 جریان آموزشی:** چارت‌های anotated او → قاعده‌گذاری تأییدها.

## 18) FIX13 — حمل‌ونقل «اول عکس، بلافاصله متن» + رأی ادغام ستاپ‌ها — DEPLOYED

**Deploy:** `748c82a`+stamp; Railway deployment (ثبت در گزارش). Tests 123 passed/1 skipped.

**حکم ۰۹-۱۶ شب:** «پیام مختصر رو بصورت کپشن نذار؛ اول عکس چارت، بلافاصله پیام مختصر». `_post_chart_then_text()`: حباب عکس فقط با برچسب یک‌خطی فارسی («📊 چارت SYMBOL • CODE • عنوان») + کل متن خوانا به‌صورت پیام متنی بلافاصله پشتش (سقف ۴۰۹۶ ⇒ هر طولی یک پیام، صفر دنبالهٔ کپشن). اعمال شد بر: مختصر، آپدیت‌های شماره‌دار، approach، Confirmed، پله‌های TP/استاپ، نتیجهٔ نهایی، لنگر+آپدیت پیش‌نمایش تکنوکلاسیک، و mirror ژورنال. کلیدهای chain désormais شناسهٔ پیام متنی را نگه می‌دارند + دوقلوهای *_photo؛ حذفِ جایگزینی، جفت را حذف می‌کند. مختصر چهار تحلیل کامل تأییدهای کمکی را با جداکننده‌ها پس گرفت؛ دیجست دوران کپشن بازنشسته شد.

**رأی من به پرسش ادغام او (ثبت برای تصمیم نهایی‌اش):** ۵ ستاپ جدا بمانند + لایهٔ «خانواده» اضافه شود. دلیل: (۱) دکترین تأیید و متن تفصیلی هر ستاپ جداست (قانون خود او)؛ ورود TLR (بیس داخل کندل شکست) با TECHNO (کلوز تأیید روی خط + حالت‌های preview) یکی نیست؛ (۲) آمار وین‌ریت/کالیبراسیون به تفکیک ستاپ لازم است — ادغام granularity را درست وقتی می‌کشد که دور کالیبراسیون شروع شده؛ (۳) بودجهٔ انتشار (۳ لایسنس چرخشی/ستاپ، گیت DB 16/top-4) با ادغام غیرقابل پیش‌بینی می‌شود. آنچه واقعاً آزار می‌دهد (سیگنال موازی روی یک نماد) با **سرکوب هم‌خانواده** حل می‌شود: دو ستاپ یک خانواده روی یک نماد+جهت در پنجرهٔ مشخص ⇒ فقط امتیاز بالاتر منتشر شود؛ و گزارش جمعه گروه‌های خانوادگی (پین: PINWALL+PINVAL+ALBROX / شکست‌خط: TLBREAK+TECHNO) را جدا نشان دهد. اگر بعد از کالیبراسیون هنوز ادغام می‌خواهد، داده تصمیم می‌گیرد.

## 19) CHART-8 فاز ۱ ساخته‌شده (منتظر تایید Viva) + درس‌های کالیبراسیون از چارت‌های خط‌خوردهٔ او

**شبیه‌سازی برای تایید:** /home/user/sim_chart_ch8.png (LONG، اوردرابلاک صعودی سبز چمنی) و sim_chart_ch8_short.png (SHORT، فیلیپ‌زون نزولی نارنجی روشن). محتوا: باکس ورود با رنگ پالت او + نام فارسی (Vazirmatn bundlé + bidi/reshaper برای رندر درست در matplotlib)، باکس‌های ساپلای/دیماند سویینگ‌ها (سقف ۳، کمرنگ، بدون بوردر)، نام‌ها روی لبهٔ بالای باکس با چیپ نیمه‌شفاف (نه روی کندل/قیمت)، خطوط TP/استاپ یکپارچه (solid)، نواحی/الگوها در چارت confirmed هم می‌مانند. **هنوز push نشده** — حکم: «تایید کردم پوش کن تست کن و ریپلوی».

**درس‌های کالیبراسیون (خوراک T1/T2/T3):**
- L1 پین پایان روند = بازگشتی خلاف جهت روند (نمونهٔ INJ 15m: شورت اعلام‌شده ولی ساختار لانگ بود)؛ پین وسط روند فقط روی ناحیهٔ مهم (ریجکت/بریک).
- L2 لانگ رو به سوی HTF = باطل (LINK 15m): ناحیهٔ تایم بالاتر باید روی چارت دیده شود و باکس در تایم تریگر ریفاین شود.
- L3 داخل کانال/رنج = ستاپ‌های کندلاستیک پرایس‌اکشن روی لبه‌ها (رفرنس الگوهای کندلی ضمیمه).
- L4 نمونه‌های تاییدشدهٔ او (ARB/XLM شورت از سقف رنج): استاپ بالای سویینگ‌های، ورود روی پین/ناحیه، TPها پلکانی — قوانین فعلی درست‌اند.
- L5 استاپ اسکالپ باید پشت نزدیک‌ترین سویینگ مخالف باشد، نه فاصلهٔ نامعقول (T1).
- L6 واژگان الگوها (فلگ/پننت/کنج/DT/DB/HS) + برگهٔ الگوهای کندلی = منبع نام‌های zone_trigger و اورلی الگوها.

## 20) RENDER-KIT: لایهٔ «تشخیص → دستور رسم» مشترک همهٔ ستاپ‌ها (CHART-8 فاز ۲، منتظر تایید)

**معماری جدید (analysis/render_kit.py):** `detect_zones()` (FVG تازه، IFVG معکوس‌شده، OB، FLIP سطح شکست‌خوردهٔ ری‌تست‌شده، BOS، خوشه‌های SUPPLY/DEMAND؛ سهمیه per-kind تا پلکان FVG نقشه را نبلعد) + `detect_patterns()` (fit_validated_line بالا/پایین + classify_shape صادقانهٔ وج/مثلث/کانال/پرچم + باکس RANGE) + `enrich_render(candidate, trigger_df, htf_df)` که `md["render_zones"]/["render_patterns"]/["htf_zones"]` می‌گذارد. **همهٔ ستاپ‌ها:** _base_candidate (هر ۵ ستاپ اصلی + ALBROX) و detect_pinbar_zone (PINVAL) صدا می‌زنند. رندرر فقط اطاعت می‌کند: md را می‌خواند وگرنه fallback روی فریم.
**برچسب‌ها ENG abbrev per ruling 09-16 شب:** OB/FVG/IFVG/FLIP ZONE/BOS/SUPPLY/DEMAND + «· POI / ENTRY»؛ چیپ‌ها روی لبهٔ بالای باکس با shift ضدبرخورد؛ فارسی و فونت وزیر از چارت حذف شد (کد و requirements تمیز).
**پاسخ به نقد شبیه‌سازی اول:** کانال‌های sim قبلی placeholder دستی من بودند (نه خروجی دتکتور)؛ حالا کانال/وج/مثلث فقط اگر دتکتور اعتبارسنجی کند رسم می‌شود و ناحیهٔ ورود در sim جدید عمداً روی لبهٔ پایین کانال نشسته = ارتباط الگو و سیگنال قابل دیدن.
**اینونتوری صادقانهٔ توابع (پاسخ به پرسش او):** داشتیم: FVG/OB (_find_fvg_near/_find_order_block)، IFVG/BOS جزئی، classify_shape+fit_edge_line (فقط سیم‌کشی‌شده به TECHCLASSIC/TLBREAK)، range overlay. نداشتیم (حالا داریم): نقشهٔ منطقهٔ متحد همهٔ ستاپ‌ها، دستور رسم الگو برای همهٔ ستاپ‌ها، HTF zones در متادیتا. هنوز نداریم: دتکتور DIAMOND و FLAG-LIMIT به‌عنوان نوع ناحیه (رزرو)، گیت تأیید مبتنی بر htf_zones (T2)، هدف‌گیری پایان روند (T3).
**هنوز PUSH نشده** — منتظر تایید شبیه‌سازی.

## 21) دکترین بیس/ادامه‌روند و قفل TP بیرونی (حکم 09-16 شب دوم — پیاده شد، منتظر تایید)

**اصطلاح کلیدی («سقف دنبال نزولی، کف دنبال صعودی»):** داخل رنج/کانالِ خالص، سقف فقط به شورت و کف فقط به لانگ voed می‌دهد (نوسان لبه‌به‌لبه). هیچ سقف/کفی به‌خودی‌خود «ممنوعیت ادامهٔ روند» نمی‌سازد.
**بیس پس از اسپایک/ترند = ساختار ادامه‌دهنده** (مستطیل/وج نزولی/مثلث نزولی/بیس ساده/IFVG/ساپلای...): برخورد به ضلع = فقط هشدار (WARN-CONT ادامه / WARN-REV بازگشت)؛ ورود = بریک + اولین کلوز تایم تریگر، یا پولبک به ضلع شکسته (touch_from از بیرون). بریک ضلع مقابل = ورود جهت مخالف. وسط بیس = بدون ورود (REJECT-MID).
**کد:** analysis/render_kit.py → detect_base (باکس ۲۴ کندله منهای کندلِ بازیگر؛ ترند از دریفت پنجرهٔ قبل؛ side/touch_from)، base_gate (ماتریس ALLOW/WARN/REJECT)، gate_ladder (TPهای بیرونی قفل POST-BREAK تا بریک ضلع). enrich_render پر می‌کند: md["base_watch"], md["base_gate"], md["tp_gates"]. ستاپ‌ها: verdict غیر ALLOW ⇒ candidate None (هم _base_candidate هم PINVAL). رندرر: چیپ «• POST-BREAK» روی پیل TPهای قفل‌شده (خطوط همچنان solid per law).
**تست‌ها:** tests/test_doctrine.py (۶ تست: ماتریس گیت رنج خالص، ادامهٔ ترند بالا/پایین، آیینه، قفل نردبان و بیداری پس از بریک). مجموع ۱۲۹ سبز.
**جریان هشدار برخورد (WARN) هنوز پیام ندارد** — اسککنر فعلاً ساکت می‌ماند؛ جریان هشدار = قلم بعدی (نیاز به فرمت پیام تازه با تایید ویوا).
**دیپلوی:** 76ad947 → deployment 336e7c36 (فاز ۲ CHART-8)؛ دکترین بالا push نشده تا تایید simها.

## 22) چهار تایم‌فریم + خاموشی اسکلپ/۵دقیقه + برچسب داخل باکس (حکم 09-16 شب سوم — منتظر تایید)

**تایم‌فریم‌ها (حکم او):** ۱۵دقیقه = سویینگ کوتاه‌مدت؛ ۱ساعته و ۴ساعته = سویینگ میان‌مدت؛ ۱روزه = سویینگ بلندمدت. اسکلپ و ۵دقیقه خاموش؛ ۵m/3m فقط مانیتور انسانی؛ تأیید فقط روی ۱۵m و ۱h.
**کد:** config live_styles="DAYTRADE,SWING,GRAND" (SCALP خاموش ولی موتور ساخته مانده)، monitor_minutes 5→15؛ setups_v7: CONFIRM_TF/BY_TRIGGER/BY_PATTERN همه به {15m,1h}؛ TIMEFRAME_PROFILES: DAYTRADE=(4h,1h,15m) تریگر ۱۵m، SWING=(1d,4h,1h) تریگر ۱h + PROFILE_OVERRIDE برای تریگر دوم 4h (SwingEngine دو پاس)، GRAND=(1d,4h,1d)؛ PINVAL_TF_BY_STYLE بدون SCALP + GRAND=4h؛ quality_engine: DayTrade frames بدون 5m، SwingEngine حلقهٔ دو تریگر؛ fetcher: باندل اسکن ("1d","4h","1h","15m") با limits 120/200/200/200.
**RAM ریلوی:** کندل‌ها به‌ازای هر نماد 1200→720 (-40%)؛ حذف کامل واکشی 5m؛ چرخهٔ مانیتور ۵→۱۵ دقیقه (-66% فراخوانی)؛ حذف یک پاس اسکن SCALP؛ 3m هرگز واکشی نمی‌شد (در TF_MAP نیست) = هزینهٔ صفر. هزینهٔ افزوده: پاس دوم SWING روی 4h (جبران‌شده با موارد بالا).
**برچسب نواحی:** تابع _place_in_box در رندرر: نام ناحیه داخل باکس خودش، در اولین جای خالی از [انتهای راست، وسط، ابتدای چپ] با تست اشغال کندل‌ها (high/low vs باند برچسب)؛ فقط اگر هر سه جا پر باشد چیپ به لبهٔ بالای باکس در ابتدای چپ لنگر می‌افتد (نه شناور در آسمان). RANGE هم همان قاعده.
**FLAG-LIMIT:** الگوی FLAG_BULL/BEAR حالا یک ناحیهٔ لیمیت روی لبهٔ دور پرچم به render_zones اضافه می‌کند (kind=FLAG-LIMIT، پالت FLAG).
**تست‌های نگهبان به‌روز شد** (test_signal_guards: دو تست نردبان قدیمی به حکم جدید amend شدند). ۱۲۹ سبز.
**push نشده** — منتظر تایید sim جدید.

## 23) نردبان تأیید مانیتور-پایه + پالس سکوت (حکم 09-17 — زنده)

**حکم او:** مانیتور هیچ‌وقت هم‌تایم تریگر نیست؛ از تایم پایین‌تر جهت/بیس/بریک زودتر دیده می‌شود. نردبان نهایی:
| تریگر | تأیید زودهنگام (مانیتور) | تأیید دیرهنگام (bound) |
|---|---|---|
| 15m | 3m | 15m |
| 1h | 3m | 15m |
| 4h | 15m | 1h |
| 1d | 1h | 4h |
چرخهٔ مانیتور = ۳ دقیقه (config + env MONITOR_MINUTES=3 با skipDeploys و تک‌دیپلوی، بدون race).
**کد:** CONFIRM_TF/BY_TRIGGER/BY_PATTERN به نردبان بالا؛ CONFIRM_LATE_BY_TRIGGER + confirm_late_tf()؛ main._candidate_market_frames هم late tf را واکشی می‌کند؛ در monitor_candidates اگر مانیتور تأیید نکرد، evaluate_confirmation روی فریم late تکرار می‌شود. TF_MAP += "3m":"3".
**پالس سکوت:** ۴ اسکن پیاپی بدون کاندید (یا هر error) ⇒ یک پیام تک‌خطی به CHAT_ID_RESULTS با شمارنده‌های seen/absorbed/liccap/quiet/low_score/errors تا «چرا پیام نیامد» از خود کانال جواب داشته باشد.
**تشخیص سکوت کانال (بررسی زنده):** چارت/enrich سالم؛ گیت بیس مقصر نبود (bypass = همان صفر)؛ اسکن محلی روی دادهٔ زنده پین‌های score=8 داد (ETH/XRP/LINK/LTC) یعنی خط لوله سالم است و کاندیدها روی کلوز کندل می‌آیند؛ متغیرهای CHAT_ID_VIVA_SIGNALS/TELEGRAM_TOKEN/DATABASE_URL در env موجودند. نتیجه: جریان پرتکرار 5m/SCALP (طبق حکم خود او) حذف شده و در بازار آرام چهار تایم سویینگ کم ستاپ می‌دهند + گیت مجوز تکرارها را جذب می‌کند. پالس + فانل لاگ («Discovery scan finished») جواب قطعی می‌دهند.
**دیپلوی:** ba48ace → a6f4762e SUCCESS. تست ۱۲۹ سبز.

## 24) بازگشت قالب‌ها و رفع بلع سیگنال‌ها (09-17، زنده)

**ریشه‌های خرابی (اعتراف):** (۱) گیت بیس من جریان‌های بریک/واچ (TLBREAK/TECHCLASSIC/ALBROX/PINWALLQ/S0_WATCH) را می‌بلعید — حالا معاف‌اند (خودِ دکترین یعنی بریک+کلوز=ورود)؛ (۲) enrich پین اشتباهی داخل detect_pinwall_quality نشسته بود: PINVAL بدون الگو/ناحیه روی چارت و PINWALLQ کشته — اصلاح: enrich در detect_pinbar_zone قبل از return best، بدون gate-kill؛ (۳) سقف ۳ کندلی verdict پین تأیید دیرهنگام را می‌کشت — حذف شد، فقط expiry/ابطال پایان می‌دهد (حکم: تأیید روی کندل ۵م یا ۲۰م یا ۱۰۰م مانیتور)؛ (۴) پیش‌نمایش تکنوکلاسیک به قالب کامپکت/آموزشی برده شده بود — به اسکلت «هشدار نهایی» رفرنس §۲ عیناً برگشت.
**رفرنس قطعی:** handoff/MESSAGE_REFERENCE.md (دو قالب + قواعد یکسان‌سازی) + tests/test_formats_audit.py که ترتیب مارکرهای هر دو اسکلت را assertion می‌کند؛ تست نگهبان TC هم به اسکلت جدید amend شد. پیام تفصیلی هر ۵ ستاپ از یک بیلدر مشترک (build_educational_message) می‌آید = یکسان‌سازی ساختاری؛ بخش‌های TLBREAK روی همان اسکلت سوارند.
**دیپلوی:** e5aec1a → 23c9b601 SUCCESS (هات‌فیکس عملکردی)؛ سپس کامیت قالب‌ها → دیپلوی SUCCESS (پایان این نشست). تست ۱۳۱ سبز.

## 25) سکوت کانال سیگنال پس از تأییدها (09-17 شب دوم — زنده)

**شکایت:** تأییدشده‌ها از ~۱:۳۵ به کانال VIVA-MON-SIGNALS نمی‌رسیدند.
**دو شکاف یافته و بسته شده:** (۱) _sig_mirror اگر والد reply (پیام جایگزین/حذف‌شده) مرده بود، خطای ۴۰۰ می‌خورد و بی‌صدا می‌افتاد — حالا یک بار بدون reply دوباره می‌فرستد و در هر شکست کامل لاگ بلند می‌زند؛ (۲) send_confirmed ژورنال را به موفقیت پست کانال اجرا گره زده بود (return False پیش از mirror) — حالا ژورنال مستقل می‌فرستد و پست اجرا در چرخهٔ بعد خودبه خود retry می‌شود (confirmation_chart_sent تا موفقیت False می‌ماند).
**کیفیت/قالب پیام‌ها:** بدون تغییر (حکم او: فعلاً همین‌ها؛ اگر نیاز بود می‌گوید).
**دیپلوی‌ها:** df2058c → a8acd6bc SUCCESS؛ 55a96e4 → دیپلوی SUCCESS پایان نشست. تست ۱۳۱ سبز.

## 26) یکسان‌سازی اسکلت رفرنس روی همهٔ کلاس‌های پیام (09-17 شب سوم — زنده)

**یافتهٔ تشخیصی:** پیام SUI که ویوا فرستاد خروجی بیلدر COMPACT بود (🆔 بعد از ⭐، بدون بخش‌های ✅) نه build_educational_message؛ یعنی یا پست مفصل در کانال هشدارها بی‌صدا ناموفق بوده یا پیام از کانال اصلی (اسلات کامپکت) کپی شده. اقدام: retry + لاگ بلند برای پست مفصل؛ اگر باز ناموفق بود لاگ «DETAILED alert post FAILED twice».
**تغییرات:** _approaching_caption (هشدار نهایی همهٔ ستاپ‌ها) = اسکلت رفرنس §۲ (/⚡/ sym•style•dir/🔎//🎯//⚖️/🌀/جملهٔ کلوز/🆔)؛ چارت‌های WATCH تی‌ال‌بریک با enrich ناحیه/الگو می‌گیرند؛ fallback تگ TF در کامپکت؛ تست‌های نگهبان به رفرنس amend شدند.
**نگاه به آینده:** کانال‌ها: مفصل دائمی در CHAT_ID_SIGNALS(=EDUCATION)؛ کامپکت اسلات زنده در کانال اصلی با دکمهٔ 📚 به مفصل؛ ژورنال VIVA-MON-SIGNALS فقط حالت‌های نهایی. اگر ویوا پیام کوتاه را در کانال هشدارها دید یعنی جای پست مفصل خالی است → لاگ جدید دقیقاً می‌گوید.
**دیپلوی:** 7de4e9d → (پول تا SUCCESS). تست ۱۳۱ سبز.

## 27) ریشهٔ الاکلنگ + مصرف + خط‌های عمودی (09-17 شب چهارم — زنده)

**الاکلنگ (پین‌وال/تی‌ال‌بریک/تکنوکلاسیک نوبتی):** بودجهٔ آموزشی هر اسکن (education_max_per_scan=16) بین همهٔ کاندیدها مشترک بود؛ سیل هشدارهای WATCH تی‌ال‌بریک (که بعد از معافیت گیت آزاد شدند) بودجه را می‌خورد و بقیهٔ خانواده‌ها deferred می‌شدند → حس «یکی وصل، بقیه قطع». حالا WATCH/پیش‌نمایش بودجهٔ جدا ۴/اسکن دارد؛ خانواده‌ها هرگز سهم هم را نمی‌خورند.
**مصرف ریلوی:** (۱) کش بایت چارت: هر (هشدار، فریم، حالت) فقط یک‌بار رندر؛ retry/میرور/کانال‌های دیگر بایت همان را می‌برند (پاسخ به «نکنه واسه هر کانال رندر میشه»: میرورها از اول بایت مشترک داشتند؛ اتلاف، رندرهای تکراری retry/update بود)؛ (۲) پنجرهٔ واکشی زنده: فریم هر TF فقط در دقیقه‌های پس از کلوز کندلش واکشی می‌شود (3m همیشه، 15m چهار دقیقهٔ اول هر ربع، 1h/4h/1d چهار دقیقهٔ اول کلوز خودشان) — بین پنجره‌ها هیچ تأییدی ممکن نیست، پس هیچ واکشی‌ای هم نیست.
**چارت:** دو خط عمودی کم‌رنگ لبهٔ ابزار (ax.vlines) طبق حکم یخ‌زده حذف شد (قبلاً در چتِ از دست رفته حذف شده بود ولی کامیت نشده بود).
**کانال سیگنال:** هشدار نهایی (اسکلت §۲) از مسیر میرور «approach» با retry بدون ریپلای می‌رسد؛ Confirmed/TP/استاپ/نتیجه هم طبق PROP-1. پیام مفصل دائمی در کانال هشدارها می‌ماند + دکمهٔ 📚 روی کامپکت.
**دیپلوی:** کامیت night-4 → پول تا SUCCESS. تست ۱۳۱ سبز.

## 28) فاجعهٔ snapshot کهنه + کرش‌لوپ پایتون ۳٫۱۱ (09-17 — حل شد، زنده)

**ریشهٔ مادر («چرا هیچ‌چیز درست نمی‌شد»):** `serviceInstanceDeploy` در ریلوی **snapshot کهنه** را دوباره دیپلوی می‌کرد، نه main最新 گیت‌هاب را. دیپلوی «موفق» edf024fa از کامیت a864de4 ساخته شده بود — **۶۵ کامیت عقب‌تر از HEAD**. یعنی کل کارهای این نشست (فرمت‌ها، ژورنال، گیت‌ها، بودجه‌ها) تا امروز هرگز live نشده بودند؛ بات با کد هفته‌ها پیش می‌دوید. راه‌حل: (۱) mutation `serviceInstanceDeployV2(commitSha,…)` برای دیپلوی با کامیت صریح؛ (۲) نصب `deploymentTriggerCreate` روی github/vahidlesani/smc-scanner2/main → حالا هر push واقعاً دیپلوی می‌شود (trigger id 107b7ac6). **قانون جدید: بعد از هر دیپلوی، meta.commitHash را چک کن.**
**دسترسی جدید:** `deploymentLogs(deploymentId, limit, filter)` در backboard GraphQL کار می‌کند (قبلاً «dead end» پنداشته می‌شد) — لاگ runtime/build قابل خواندن است.
**کرش‌لوپ اول (9e17db0a/ed1f695d CRASHED):** `messages_v7.py:1181` f-string چندخطی — فقط پایتون ۳٫۱۲+ (PEP 701)؛ ریلوی ۳٫۱۱ است → SyntaxError هنگام import → کرش‌لوپ تا Railway متوقفش کرد (سکوت کامل کانال‌ها از ~۱۰:۳۰ به بعد). کد از کامیت 76ad947 (CHART-8 فاز ۲) بود. Fix: متغیر جدا قبل از f-string (کامیت 4a021a4).
**باگ دوم (از لاگ زنده):** `analysis/setups_experimental.py:332/336` — walrus `:=` **داخل f-string بدون پرانتز** در پایتون <۳٫۱۲ به‌عنوان format spec تفسیر می‌شود → `NameError: _price_watch is not defined` در **هر فراخوانی** `detect_trendline_breakout` → دتکتور TLBREAK کاملاً مرده بود (خطا per-symbol بلعیده می‌شد). Fix: حذف walrus (کامیت 4d35c0e). این احتمالاً بخشی از رفتارهای عجیب تاریخی TLBREAK را هم توضیح می‌دهد.
**نگهبان دائمی:** `tests/test_py_compat_lint.py` — دو lint: walrus-داخل-f-string و f-string چندخطی؛ به‌علاوه verify دستی با `uv python 3.11` + `py_compile` روی همهٔ ۷۷ فایل قبل از هر دیپلوی بزرگ. تست‌ها: ۱۳۳ سبز.
**وضعیت نهایی:** دیپلوی 1d5687ca = کامیت 4d35c0e SUCCESS، stable، صفر خطا در لاگ، مانیتورها فعال (execution 5s / candidates 10s)، اسکن ۴۰ نماد در جریان. کل backlog شصت‌وکامیتی برای اولین بار واقعاً live است: §1 detailed، §2 final warning، compact+📚، ژورنال با retry، بودجهٔ جدا WATCH (الاکلنگ)، پنجرهٔ واکشی + کش چارت (مصرف)، حذف خط‌های عمودی چارت.
**درس‌ها:** (۱) SUCCESS بدون چک commitHash بی‌معنی است؛ (۲) پایتون sandbox (۳٫۱۳) ≠ پایتون prod (۳٫۱۱) — syntax را با ۳٫۱۱ compile کن؛ (۳) deploymentLogs همیشه اول چک شود.

## 29) بیس واحد پیام تفصیلی + احکام پنج‌گانه 09-17 (زنده)

اعلام مصرف توسط ویوا: ~۳–۵ سنت در ۲۴ ساعت (زیر سقف) → حلقه‌های ۵s/۱۰s دست‌نخورده
(پاسخ صادقانه: اینها روی «تأیید» اثر ندارند — تأیید همان نردبان کلوز ۳ دقیقه‌ای است؛
فایده‌شان فوریت TP/SL معاملات باز و آپدیت فوری شکست/هشدار نهایی است).
تغییرات: `_price`/`_fmt`/`_f`/`_n2` = قانون ۲ اعشار/۲ رقم معنادار؛ فاصلهٔ زندهٔ ATR
۳→۲ اعشار (approaching + TC preview)؛ `_sep_bullets` و سه join بولت در detailed =
خط ساده (FORMAT-3 نقض‌شد: جداکننده فقط بین بخش‌های اصلی)؛ `_fa_start` روی tech_aids
(EMA/RSI… اول خط فارسی می‌شوند)؛ «سطح {pattern}» در شکست ساختاری؛ «خطِ {TF}» در
context-line؛ تست needle «0.31 ATR». Sweep حسابرسی روی هر ۶ کد ستاپ (detailed+approaching+
compact+management_fa+detailed_warning_fa) = ALL OK (بدون عدد >۲ اعشار، بدون انگلیسی
اول خط). تکنوکلاسیک: build+tests سالم. ۱۳۳ تست سبز؛ همهٔ فایل‌ها با py3.11 compile شدند.
MESSAGE_REFERENCE.md بخش DETAIL-REFERENCE اضافه شد.

## 30) سه کار جدید 09-17: قوانین، دکترین تایم‌بالا، استاپ/بروکس (زنده)

۱) قانون اسکن چندستاپی در VIVA_LAWS.md ثبت + audit شد: کد از قبل مطابق است
(همهٔ گیت‌ها per tuple؛ find_similar هم‌خانواده؛ supersede نماد-محور ممنوع).
۲) سکوت ۴ساعته/روزانه: sweep زنده ۱۶ نماد → GRAND یک کاندید ALBROX 1d score8 ساخت
(پایپ‌لاین سالم، بازار کم‌جان)؛ ریشهٔ اصلی = expiry کوتاه (GRAND 96h = ۴ کندل روزانه!)
که زنجیره را پیش از بلوغ می‌کشت → EXPIRY_HOURS_BY_TRIGGER (1d=360h, 4h=240h, 1h=96h, 15m=36h).
۳) هدف نامعقول (XRP 15m → ۹۹ سنت): cap افق تریگر = ۲۵×ATR؛ آن‌سو → measured target.
۴) استاپ پین‌وال/کیو: کفِ بروکسی (اکستریم پین ± بافر ≥0.25ATR؛ دورترِ آن با لنگر نقدینگی).
۵) تحقیق بروکس از منابع اصلی: بدون سقف کندلی («wait for clarity»)؛ بیس «≥10 bars/2 legs»؛
۸۰٪ شکست‌های TR فیل می‌شوند؛ TR ۵–۲۰ کندل = تعادل سفت؛ >۲۰ کندل = احتمال معکوس ۵۰٪؛
استاپ = آن‌سوی سیگنال‌بار یا آخرین سوئینگ + بافر؛ ورود stop-order یک تیک آن‌سوی سیگنال‌بار؛
H2/L2 (تلاش دوم) معتبرتر از H1/L1؛ barb-wire: هرگز روی شکست وارد نشو.
در دستور کار بعدی: ارتقای تأییدهای ALBROX/پین با الگوهای کندلی بروکس + نمونهٔ چارت استاپ از ویوا
+ بستهٔ چارت (اشباع ۵٪، باکس/لیبل، ترند/وج/مثلث/کانال روی پین‌وال/کیو/البروکس، معتبرترین ترند)
+ پیشنهاد تلفیق ۲ خانواده‌ای در VIVA_LAWS.md (در انتظار تصویب ویوا).

## 31) بستهٔ چارت/اعشار/تکنوکلاسیک (09-17 شب دوم — زنده)

**اعشار (حکم نهایی ویوا):** پلکان جدید در چهار helper: ≥1000 کاما+۲؛ ۱۰۰–۹۹۹ →۲؛
۱–۹۹ →۳؛ زیر ۱ →۴ رقم معنادار؛ خط فیبو ۳ اعشار (aids_bank).
**تکنوکلاسیک:** تنها کد = TECHCLASSIC؛ «TC» ستاپ غیرفعال قدیمی است (هشدار ویوا).
متغیر TECHCLASSIC_ENABLED در prod روی true ست شد (skipDeploys + یک دیپلوی با کد).
**چارت — رسم الگو (CRV/FIL/HYPE):** render_kit حالا (۱) fit را روی سه پنجره
(90/130/کل) می‌گیرد و با امتیاز ترکیبی لمس×فیت×طول بهترین خط هر سمت را انتخاب
می‌کند (گزینهٔ ۱ ویوا)؛ (۲) کانفیگ RENDER-ONLY جدا از تشخیص معامله
(min_touches=2, residual≤0.45, pivot 3/3) — تشخیص ترید دست‌نخورده سخت می‌ماند؛
(۳) وقتی شکل کلاسیفه نشود هر دو خط جدا رسم می‌شوند (CRV: جفت خط آبی او)؛
(۴) خط تکی هم رسم می‌شود (FIL: ترند صعودی از کف)؛ (۵) fallback وج: دو خط هم‌جهت
همگرا = WEDGE_FALLING/RISING. خروجی تست زنده: CRV دو خط نزولی، FIL کانال صعودی،
HYPE کانال صعودی.
**نواحی:** اشباع +۵٪ (alpha 0.13→0.18) + فیلتر کیفیت: ناحیهٔ دورتر از ۸×ATR حذف.
**استاپ HYPE:** کفِ جدید = پشت آخرین سوئینگ پیوت تریگر + بافر (عقب‌تر از کف پین/لنگر).
تصمیم‌های ویوا ثبت شد: تلفیق=بعداً؛ ترند=امتیاز ترکیبی؛ بروکس=بعد از چارت‌ها؛ سقف=25×ATR.

## §32 — بازنویسی fitter خط کلاسیک (09-18، DONE)
- fit_validated_line: جست‌وجوی جفت‌پیوت + قید عبورناپذیری + valid-until-broken + alive-rules (render-only) + بونوس اکستریم موج؛ تست‌ها 133 سبز؛ رندر CRV/LINK/AVAX مطابق شماتیک‌های ویوا.

## §33 — رفع جانمایی خطوط + سبک TLBREAK برای همهٔ الگوها (09-18 شب، DONE)
- ریشه: ناهمخوانی پنجرهٔ fit (170) و فریم (150) → لنگر زمانی شد؛ سایهٔ باند حذف؛ دایره پیوت‌ها + خط ضخیم رنگی؛验证 روی CRV/BCH/BTC/AAVE مطابق شماتیک‌های دستی ویوا (uploads/IMG_20260917_05*.jpg).

## دورهٔ ۱۵ (۰۹-۲۱) — در انتظار تأیید ویوا: چهار کانال جدید + موتور اسپات + بهینه‌سازی هزینه
- سند کامل پیشنهاد: `SPEC-ROUND15-CHANNELS-AND-SPOT.md` (ارسال شد در پیوی تلگرام، همراه با `proof_spot_feasibility.png`).
- مقصد: ۴ کانال (۱۵m/۳۰m · ۱h/۲h · ۴h/۱d · اسپات) — فقط تأییدشده، بدون ریپلای، لینک هر سیگنال به «آخرین نتیجه»اش در کانال نتایج با ویرایش در هر تی‌پی.
- موتور اسپات: TLBREAK + TECHCLASSIC · فقط LONG · ۴h/۱d/۳d/۱w (۳d و ۱w از تجمیع روزانه‌های بسته) · چارت لگاریتمی + خطوط دو-پیوتی + باکس سبز · استاپ ساختاری یا ۱۲–۱۵٪ · تارگت مستقل از استاپ.
- حذف باکس سبز عمودی از چارت‌های ۵ ستاپ فیوچرز (ابزار پوزیشن دست‌نخورده).
- فاز ۱ بهینه‌سازی: کش کندل بسته تا کلوز بعدی · رد نماد بی‌تغییر · تقویم ۱۵m/۵m · breaker برای Gemini (۱۰۷ HTTPError امروز) · کش رندر · کنتور مصرف روزانه.
- دادهٔ رایگان تأییدشده از سرور (۲۰۰ OK): CoinGecko، DexScreener، DefiLlama، alternative.me (F&G). بای‌بیت/بایننس همچنان ۴۰۳/۴۵۱؛ راه‌حل = VPS یا سرویس پولی.
- شناسه‌های فعلی: CHAT_ID=۲۲۷۸۰۳۱۶۱ · EXECUTION=-۱۰۰۴۳۱۵۸۶۶۹۰۰ · RESULTS=-۱۰۰۳۹۸۰۵۳۸۸۶۲ · EDUCATION=-۱۰۰۴۴۵۵۱۰۳۳۸ · VIVA_SIGNALS=-۱۰۰۳۹۱۵۱۷۱۳۲ (توکن بات در `.secrets/telegram_token`، بدون کامیت).
