# گزارش ممیزی — smc-scanner2
**تاریخ:** ۲۰۲۶-۰۹-۱۴ · **HEAD:** `b21b50a` (= بیلد لایو `2026.09.14-11b`، مطابقت تأیید شد)
**حجم:** ۲۴٬۵۲۶ خط پایتون در ۱۰۰+ فایل · **تست:** `116 passed, 1 skipped` (مطابق ادعای بکاپ ✅)

---

## ۰) ⚠️ اول از همه: امنیت

در فایل بکاپ، **توکن GitHub به‌صورت متن‌باز نوشته شده** (`ghp_KHVN8dWR...`) و خودِ ریپو **عمومی (public)** است.
→ **همین الان توکن را در GitHub revoke کن** (Settings → Developer settings → Personal access tokens → Revoke) و توکن جدید بساز.
خبر خوب: داخل ریپو هیچ secret ای commit نشده (بررسی کردم: clean). شناسه کانال‌ها هم از env خوانده می‌شود، نه هاردکد. ✅

---

## ۱) وضعیت ۸ قانونِ بکاپ (دسته‌بندی: انجام‌شده / ناقص / متضاد)

| # | قانون | وضعیت | شاهد در کد |
|---|---|---|---|
| ۱ | اسلات زندهٔ کانال اصلی + آپدیت شماره‌دار + دکمه 📚 + حذف پیام قبلی | 🟡 **انجام شده، با ۲ ایراد** | `_pro_slot_post` (messages_v7:1723) درست است: اول post جدید، بعد حذف قدیمی، بعد KV. ایرادها: **F4** و **F11** |
| ۲ | قالب فریز / یک builder مشترک | 🔴 **ناتمام** | هیچ builder مشترکی وجود ندارد. `messages_v7.py` = **۲٬۸۵۶ خط** با مسیرهای جداگانه برای تفصیلی/مختصر/آپدیت/نهایی. «قالب فریز» عملاً = کپی در ۴ جا |
| ۳ | تأیید = اولین کلوز معتبر · ATR همان فریم · RR وتو نیست | 🟡 **پیاده شده، با ۳ انحراف** | `evaluate_confirmation` (quality_engine:135-240). انحراف‌ها: **F12** (ATR تعریف‌ناشده)، **F13** (کندلِ مرزی/خارجی)، **F14** (خطِ شیب‌دار وارونه) |
| ۴ | کمکی‌ها (🕐 سشن / 📊 EMA / 🌀 فیبو / 📈 واگرایی) **در همه پیام‌ها** | 🔴 **ناتمام — مهم** | `_tech_aids_lines` فقط در **۲** متن صدا زده می‌شود: `_compact_alert_caption` و `_setup_update_caption`. در `send_approaching`، **`send_confirmed`**، `send_educational_setup` (تفصیلی!)، `send_candidate_cancelled`، `send_verdict_reply`، `send_tp1_event`، `send_trade_result` → **صفر**. یعنی مهم‌ترین پیام (Confirmed) هیچ کمکی ندارد |
| ۵ | پایش مولتی‌تایم + heartbeat + هشدار فوری ⚡ | 🟡 **جدید (۰۹-۱۴)، ناقص** | `expiry_hours_for` = ۱۲/۱۲۰/۱۶۸/۳۳۶ ✅ دقیقاً مطابق قانون. `_live_break_watch` ✅. ولی **F4** (مارکر زودتر از ارسال) و **F16** (کد مردهٔ PINVAL) |
| ۶ | ۵ ستاپ فعال پیش‌فرض (TLBREAK, TECHCLASSIC, ALBROX, PINWALLQ, PINVAL) | 🔴 **متضاد با کد** | `config.py:164-165` → `experimental_tlbreak_enabled = False`، `viva_tlbreak_enabled = False`، و `core_v7_setups_enabled = False` (config:67). یعنی در کد فقط ۴ ستاپ روشن است: TECHCLASSIC, ALBROX, PINWALLQ, PINVAL. TLBREAK فقط از راه env روشن می‌شود → **کد و سند دو حقیقت متفاوت دارند** |
| ۷ | DB گیت · DEAD_GATE · anti-echo ۳۰۰s · بودجه ۱۶ · top-4 | 🟢 **انجام شده** | `education_max_per_scan = 16` ✅ · `setups_v7.py:1136 → candidates[:4]` ✅ · `chains_per_symbol_setup_24h = 3` ✅ · `license_min_sep_pct = 0.02` ✅ · `status<>'DEAD_GATE'` در chains/lineage ✅ · ایرادها: **F5** (throttle مرده در حافظه) و **F10** |
| ۸ | ماشهٔ پینوال دست‌نخورده · سؤال خشکسالی باز | 🟡 **بلاتکلیف** | ماشه دست‌نخورده ✅. ولی **expiry پینوال از قانون ۵ پیروی نمی‌کند** (**F8**) و کل چرخهٔ verdict پینوال **کد مرده** است (**F16**). سؤال خشکسالی: هیچ flag/کدی برایش پیدا نکردم → **هنوز باز** |

---

## ۲) 🔴 باگ‌های بحرانی — همین الان در لایو می‌شکنند (و بی‌صدا)

### F1 · `NameError: resolved_at` — پیام بسته‌شدن معامله هرگز ارسال نمی‌شود
`database/repository_v7.py:1318`
```python
"event_at": str(resolved_at),
```
`resolved_at` **در کل فایل هیچ‌جا تعریف نشده** (فقط همین یک بار استفاده شده — `grep` تأیید می‌کند).
- **مسیر:** فقط در ژنراتور **legacy** رویدادها (وقتی `target_state_json` خالی باشد). مسیر ladder (`continue` در خط ~1226) سالم است.
- **نتیجهٔ فاجعه‌بار:** ترتیب اجرا این است: (۱) UPDATE روی `signals` و `active_signals` → **commit می‌شود**، `status='CLOSED'`، (۲) بعد `closed_event.update({...})` → **NameError**. تابع با استثنا بیرون می‌آید → رویداد **هرگز** به لیست اضافه نمی‌شود → `send_trade_close_event` و `send_trade_result` صدا زده نمی‌شوند.
- چون ردیف حالا `CLOSED` است، کوئریِ سیکل بعد (`WHERE confirmed=TRUE AND confirmation_sent=TRUE` روی active) دیگر آن را برنمی‌گرداند → **پیام نتیجه برای همیشه گم می‌شود**. Win Rate/کانال نتایج بی‌خبر می‌ماند.
- **چرا تست نگرفت:** `tests/test_v7.py:386` فقط مسیر ladder را پوشش می‌دهد (TP1→TP2→TP3→TRAIL_STOP→CLOSED). مسیر legacy **هیچ تستی ندارد**.

### F2 · `NameError: _t` — سیگنال تأییدشده بی‌صدا CANCELLED می‌شود
`main.py:828`
```python
_t(candidate)["dup"] += 1        # داخل monitor_candidates()
```
`_t()` در `main.py:203` تعریف شده — **داخل `run_discovery_scan()`**. در `monitor_candidates()` (تعریف در خط ۶۷۰) وجود خارجی ندارد.
- **مسیر:** gateِ «geometry duplicate» (`main.py:821-835`) — یعنی دقیقاً وقتی یک تأییدِ تکراری باید بی‌صدا لغو شود.
- **ترتیب واقعی اجرا (بررسی شد):**
  ```
  1. stats["suppressed_geo_dup"] += 1     ✅ اجرا می‌شود  ← آمار دروغ می‌گوید
  2. _t(candidate)["dup"] += 1            💥 NameError    ← همین‌جا می‌ترکد
  3. candidate.status = "CANCELLED"       ❌ هرگز اجرا نمی‌شود
  4. update_candidate(candidate)          ❌ هرگز
  5. continue                             ❌ هرگز
  ```
  `NameError` زیرکلاسِ `RuntimeError` نیست، پس `except RuntimeError` (خط ۸۳۶) آن را نمی‌گیرد → از gate فرار می‌کند و **مستقیم به مسیر انتشار می‌رود**.
- **نتیجهٔ واقعی (بدتر از لغو شدن):** gate کاملاً از کار افتاده است. سیگنالِ تکراری **لغو نمی‌شود**؛ در عوض `save_confirmed_signal` → `send_confirmed` اجرا می‌شود و **همان تأییدِ تکراری منتشر می‌شود**.
  یعنی باگی که کامیت `e369fb1` («signal-quality: geometry-dup guard») و `b1e8aaf` آمده بودند حل کنند، **الان دوباره زنده است** — فقط بی‌صدا.
  و چون `suppressed_geo_dup` قبل از انفجار increment می‌شود، **آمار نشان می‌دهد که جلوی آن گرفته شده** در حالی که گرفته نشده. دقیقاً همان حسِ «ربات دارد کاری می‌کند ولی نتیجه‌اش را نمی‌بینم».
- **چرا تست نگرفت:** هیچ تستی `monitor_candidates` را با `recent_geometry_duplicate → True` صدا نمی‌زند.

### F3 · `NameError: Optional` — بمب ساعتی
`main.py:469` و `main.py:487` از `Optional[pd.DataFrame]` در امضا استفاده می‌کنند، ولی `main.py:18` فقط `Dict, Tuple` را import کرده.
الان به‌خاطر `from __future__ import annotations` مخفی است (annotation ها رشته‌اند). **هر لحظه** که آن import حذف شود، یا کسی `typing.get_type_hints()` بزند، یا این توابع از یک ماژول بدون future-import فراخوانی شوند → کل `main.py` موقع import می‌ترکد و سرویس بالا نمی‌آید.

### F4 · مارکر heartbeat / live-break **قبل از** ارسال موفق ثبت می‌شود → آپدیت برای همیشه گم
`main.py:800-812` (heartbeat) و `main.py:617-627` (live-break)
```python
candidate.metadata["hb_bar"] = _bts      # ← اول مارک می‌شود
...
if send_setup_update(candidate, _pat[0], note_fa=_hb_note):
    stats["heartbeat"] += 1              # ← اگر False شود، هیچ
```
`send_setup_update` در **سه** حالت `False` می‌دهد: (۱) Telegram fail، (۲) dedup امضا `upd_sig` یکسان، (۳) chart/send استثنا.
در هر سه حالت، مارکر `hb_bar`/`live_break_bar` قبلاً ذخیره شده → **آن کندل برای همیشه آپدیت نمی‌گیرد.**
در مورد live-break بدتر است: عبورِ شارپِ درون‌کندلی یک‌بار در هر کندل مجاز است؛ اگر همان یک بار به Telegram نخورد، **هشدار ⚡ برای آن حرکت مهم هرگز نمی‌آید** و هیچ retry ای در کار نیست.
→ **قاعدهٔ درست (که در `_pro_slot_post` رعایت شده):** مارکر فقط **بعد از** `mid` موفق.

---

## ۳) 🔴 چرا «۱۹ روزه هر روز بدتر می‌شود» — ۳ علت ساختاری

### F5 · شبکهٔ ایمنی عملاً وجود ندارد: CI فقط **۲۴ تست از ۱۱۷** را اجرا می‌کند
`.github/workflows/tests.yml` دستورش این است:
```
python -m unittest discover -s tests -v
```
من هر دو را اجرا کردم:
| روش | تعداد |
|---|---|
| `python -m unittest discover -s tests` (همان که CI اجرا می‌کند) | **Ran 24 tests · OK** |
| `python -m pytest tests/ -q` (همان که شما دستی اجرا می‌کنید) | **116 passed, 1 skipped** |

دلیل: `unittest discover` فقط کلاس‌های `TestCase` را جمع می‌کند. **تنها** فایلی که `unittest.TestCase` دارد `tests/test_v7.py` است؛ ۱۰ فایل دیگر همه توابع pytest-سبک‌اند و **برای CI نامرئی‌اند**. ضمناً `pytest` در `requirements.txt` نیست، پس CI حتی نمی‌تواند آن را اجرا کند.
→ **F1 و F2 دقیقاً در همان ۹۳ تستِ نادیده‌گرفته‌شده جا می‌گرفتند.** چراغ سبز GitHub هیچ معنایی ندارد.

### F6 · ۲۱۸ `except Exception`، که ۶۱ تایشان `pass` خالی است
| فایل | تعداد `except` |
|---|---|
| `main.py` | ۵۰ |
| `bot/messages_v7.py` | ۴۵ |
| `bot/commands.py` | ۲۳ |
| `analysis/pattern_engine.py` | ۱۹ |
| کل پروژه | **۲۱۸** (۶۱ مورد `pass`/`continue` خالی) |

این **علت اصلی** تجربهٔ توست: وقتی قابلیتی می‌شکند، **هیچ صدایی تولید نمی‌کند** — فقط یک بخش از پیام نمی‌آید، یا یک آپدیت رد می‌شود. بعد تو «باگ» را می‌بینی، ولی هیچ اثری از علت در لاگ نیست → هر دورِ دیباگ تبدیل به حدس می‌شود → «همه‌چی بهم می‌ریزد».
**این یک خطِ مستقیم است از F1/F2 (که هر دو NameErrorِ بلعیده‌شده‌اند) تا حسِ ۱۹ روزهٔ تو.**

### F7 · هیچ connection pool ای وجود ندارد؛ هر query یک اتصال SSL تازه
`database/candidate_store.py:_connection()` و `database/db.py:db_cursor()` → هر دو `connect()` … `close()` در هر فراخوانی. `grep pool|ThreadedConnectionPool|pgbouncer` در کل `database/` → **صفر نتیجه**.
- هر سیکل اسکن، **به ازای هر کاندیدا** حداقل این‌ها را جداگانه صدا می‌زند: `open_chains_for`، `chains_last_24h`، `recent_lineage_zone`، `last_confirmed_entry`، `has_open_pre_tp1_signal`، `add_candidate` → با ۱۰۰ سمبل و چند کاندیدا در هر سمبل = **صدها اتصال تازهٔ Postgres در هر ۱۵ دقیقه**، هرکدام با handshake کامل TLS.
- به‌علاوهٔ مانیتور هر ۱۰ ثانیه (`get_active_candidates` + `update_candidate` برای هر ردیف) و اجرای بلادرنگ هر ۵ ثانیه.
- روی Railway/Supabase این یعنی **latency فزاینده + خطر «too many connections»** — و چون خطاها بلعیده می‌شوند (F6)، تو فقط «کندتر و بدتر شدن» را می‌بینی، نه علتش را.

### F9 · گلوگاه HTTP مشترک + مانیتور بدون کش + زنجیره‌هایی که ۵ تا ۱۴ روز زنده می‌مانند
- `data/fetcher.py:_throttle()` یک **قفل سراسری** روی همهٔ نخ‌هاست (`bybit_min_request_interval = 0.08`). سه مصرف‌کننده با هم رقابت می‌کنند: اسکن discovery (۱۰۰ سمبل × ۵ تایم‌فریم = **۵۰۰ ریکوئست**)، مانیتور کاندیدا (هر ۱۰ ثانیه)، و تیکر TP/SL (هر ۵ ثانیه).
- `_candidate_market_frames` صریحاً `use_cache=False` می‌دهد → برای هر سمبلِ فعال، ۲ تایم‌فریم، **هر ۱۰ ثانیه**، از شبکه.
- حالا قانون ۵ را بگذار رویش: expiry ها ۱۲ ساعت تا **۳۳۶ ساعت (۱۴ روز)**‌اند. یعنی تعداد زنجیره‌های فعال **هر روز بیشتر می‌شود** و بارِ هر سیکل مانیتور هم با آن رشد می‌کند.
→ **این دقیقاً همان «هر روز بدتر می‌شود» است: بار، تابعی از تعداد زنجیره‌های زنده است و آن تعداد یک‌طرفه رشد می‌کند.**

### F11 · race condition بین نخ اسکن و نخ مانیتور
`_CANDIDATE_MONITOR_LOCK` فقط مانیتور را از مانیتور محافظت می‌کند. `run_discovery_scan()` (نخ اصلی) **بدون هیچ قفلی** همان ردیف‌ها را می‌نویسد: `add_candidate`، `absorb_update_into_chain`، `update_candidate`، `send_setup_update`.
`update_candidate` یک read-modify-write روی **کل payload JSON** است → آپدیتِ گمشده (lost update) بین دو نخ → اسلاتِ KV (`setup_chain|CODE`) خراب می‌شود، پیام تکراری یا گمشده می‌آید.
ضمناً `_pro_slot_post` و `send_setup_update` هر دو جداگانه روی همان کلید KV می‌نویسند (دو بار `_setup_chain_get`/`_set`) → پنجرهٔ race دوم.

---

## ۴) 🟠 ناسازگاری‌های «کد vs سند» — ریشهٔ اصلی بهم‌ریختگی بعد از تغییر چت

### F15 · `CHAT_CONTEXT.md` یک ماه است که **غلط** است
این فایل با جملهٔ «این فایل رو توی چت جدید آپلود کن تا من همه چیز یادم بیاد» شروع می‌شود — و **دقیقاً همان چیزی است که باعث فاجعه می‌شود**. ادعاهایش در برابر واقعیتِ کد:

| `CHAT_CONTEXT.md` (۲۰۲۶-۰۸-۱۳) | واقعیت کد (۲۰۲۶-۰۹-۱۴) |
|---|---|
| میزبانی: **Render** | Railway (`combined_service.py`, `railway.json`, `rw_api.py`) |
| دیتابیس: **Supabase** | Railway Postgres + `bot_kv` + `signal_candidates` |
| **۱۳ استراتژی فعال** | `core_v7_setups_enabled = False`؛ فقط TECHCLASSIC/ALBROX/PINWALLQ/PINVAL |
| اسکن هر **۵ دقیقه** | ۱۵ دقیقه (`full_scan_minutes = 15`) |
| ساختار فایل‌ها | `messages_v7.py`, `setups_v7.py`, `quality_engine.py`, `candidate_store.py`, `repository_v7.py` را اصلاً ذکر نکرده |
| `runtime.txt = python-3.10.11` | فایلِ `root` = `3.11.9` · CI = `3.11` |
| «ایده‌های آینده»: alert levels، MTF confirmation | همه **سال‌هاست** پیاده شده‌اند |

→ هر چت/ایجاد جدیدی که این فایل را بخواند، با ۶ فرض غلط شروع می‌کند و شروع می‌کند به «درست کردن» چیزهایی که خراب نیستند. **این بزرگ‌ترین دلیلِ «وقتی چت تغییر کرد همه‌چی بهم ریخت» است.**

### F19 · `CHANGELOG.md` ۲۹ روز عقب است
آخرین مدخل: `v7.6.0 — 2026-08-16`. از آن به بعد **۳۰ کامیت** آمده (phase5, phase6, phase6b, licence law, chain doctrine, ONE-CLOSE law, 5 stream ladder, heartbeat, live-break…) و **هیچ‌کدام در CHANGELOG نیستند**. تنها مستنداتِ این یک ماه، **متنِ کامیت‌ها**ست (که بسیار طولانی و پراکنده‌اند).

### F8 · دو سیاستِ expiry موازی و متضاد
| منبع | مقادیر |
|---|---|
| `analysis/setups_v7.py:113 expiry_hours_for` (قانون ۵) | SCALP 12 · DAYTRADE 120 · SWING 168 · GRAND 336 |
| `analysis/setups_experimental.py:863` (خانوادهٔ پینبار) | SWING **24** · DAYTRADE **10** · بقیه **3** |

→ PINVAL/PINWALLQ/ALBROX از قانون ۵ پیروی **نمی‌کنند**. و `_dead_gate_recently_alerted` / `_suppressed_edu_throttled` در `main.py` برای throttle از `expiry_hours_for` استفاده می‌کنند، در حالی که `expires_at` واقعی ردیف از فرمول دیگر آمده → **دو ساعتِ متفاوت برای یک ردیف**.
ضمناً این همان ناحیه‌ای است که زامبیِ `expires 2027` از آن بیرون آمد.

### F20 · دو ژنراتورِ رویداد با مجموعه فیلدهای متفاوت
مسیر **ladder** (`repository_v7.py:~1157-1226`) فیلدهای `direction`, `hit_index`, `margin_roi_pct`, `targets`, `leg_*` را می‌فرستد. مسیر **legacy** (`~1229-1320`) این‌ها را ندارد (و `direction` را هم ندارد!). مصرف‌کننده‌ها (`send_trade_close_event`, `send_trade_result`) با `.get()` می‌خوانند → **پیام‌های مسیر legacy با جای خالی/صفر رندر می‌شوند** (جهتِ معامله، ROI، شمارهٔ TP). یعنی قالب پیام بسته به اینکه سیگنال از کدام مسیر بسته شده **فرق می‌کند** — نقضِ «قالب فریز» (قانون ۲).

---

## ۵) 🟡 باگ‌های منطقی (درست کار می‌کند، ولی خلافِ قانونِ نوشته‌شده)

### F12 · «ATR همان فریم» در واقع ATR نیست
`quality_engine.py:212`:
```python
_f_atr = float((_frame["high"] - _frame["low"]).tail(14).mean() or 0.0) or _atr
```
این **میانگینِ دامنهٔ کندل** است، نه ATR واقعی (true range با احتساب gap). همان عبارت در `main.py:601` و `main.py:614` هم تکرار شده.
در کریپتو میانگین (high−low) معمولاً **کمتر** از ATR است → آستانه‌ها **شل‌تر** از چیزی است که قانون ۳ می‌گوید → تأییدهای زودتر/بیشتر.
بدتر: در **همان تابع**، `displacement["body_atr"]` از `analysis.indicators.atr` (ATR واقعی) می‌آید و gateِ `confirm_body_min_atr` با آن سنجیده می‌شود. پس «Body ≥ 0.25 ATR» در fast-lane با یک تعریف و در مسیر trigger با تعریف دیگر سنجیده می‌شود. **دو معیارِ متفاوت در یک تصمیم.**

### F13 · fast-lane می‌تواند با کندلِ **قبل از هشدار** تأیید کند
`_bars_since_candidate` (quality_engine:120):
```python
after = closed_df.loc[timestamps >= created].copy()
return after if not after.empty else closed_df.tail(2).copy()   # ← fallback
```
دو مشکل:
1. `>=` یعنی **خودِ کندلی که هشدار در لحظهٔ کلوزش ساخته شده** هم کاندیدای تأیید است (نباید باشد؛ قانون می‌گوید «همه کندل‌های **بعد از** هشدار»).
2. اگر هیچ کندلی بعد از `created_at` نباشد (skew ساعت، یا تبدیل tz که در آن `created` را `tz_localize(None)` می‌کند ولی `timestamps` را نه)، **دو کندلِ آخرِ تاریخ** برگردانده می‌شود → fast-lane روی دادهٔ **قبل از هشدار** اجرا می‌شود → تأییدِ بی‌اساس، بلافاصله بعد از هشدار.

### F14 · خط شیب‌دار بدون clamp درون‌یابی می‌شود
`_edge_at` / `_watch_edge_at` ضریب `_frac` را **بدون محدود کردن به [0,1]** حساب می‌کنند. اگر pivot B از A قدیمی‌تر باشد (`_dt < 0`)، یا کندل بیرونِ بازهٔ A–B باشد، **شیبِ خط برعکس می‌شود** → مرجعِ تأیید به سمت اشتباه حرکت می‌کند.

### F10 · آپدیتِ throttle‌شده **هرگز** جبران نمی‌شود
`main.py:246-253`: اگر `_update_too_fresh(holder)` → فقط `stats["update_throttled"] += 1` و **nothing else**.
ولی `absorb_update_into_chain(holder, candidate)` **قبلاً** زنجیره را تغییر داده. با مانیتورِ هر ۱۰ ثانیه و فاصلهٔ مجازِ ۳۰۰ ثانیه، یک رخدادِ بااهمیت که در پنجرهٔ throttle بیفتد **برای همیشه بدون پیام می‌ماند** (خبر در DB هست، در کانال نیست). هیچ صف/پرچم «بعداً بفرست» وجود ندارد.

### F16 · کل چرخهٔ verdict پینبال = کد مرده
`_pinv_window_expired` (main.py:469)، `_resolve_pinv_verdict` (main.py:487)، `_pinv_done` → **هیچ‌جا صدا زده نمی‌شوند** (فقط تعریف). داخل `monitor_candidates` بلوکی هست که `pin_frame` را محاسبه می‌کند و **هرگز استفاده نمی‌کند** (pyflakes هم می‌گوید: `local variable 'pin_frame' is assigned to but never used`)، با کامنتی که می‌گوید «دیگر verdict timeout خودسرانه نداریم».
→ وضعیت‌های `VERDICT_YES` / `VERDICT_NO` / `VERDICT_TIMEOUT` عملاً تولید نمی‌شوند؛ PINVAL فقط از راه `EXPIRED`/`CANCELLED`/`CONFIRMED` بسته می‌شود، ولی `send_verdict_reply` در مسیرهای expiry/invalidation صدا زده می‌شود با متن‌هایی که به آن چرخهٔ حذف‌شده اشاره دارند. **منطقِ نصفه‌حذف‌شده.**

### F17 · `_dead_gate_recently_alerted` یک «پرسش» با عارضهٔ جانبی است
تابع هم **چک** می‌کند و هم در همان لحظه **مارک** می‌کند (`_DEAD_GATE_ALERTED[key] = now` قبل از `return False`). پس:
- هیچ راهی برای پرسیدنِ «آیا قبلاً هشدار داده؟» بدون مصرف‌کردنِ سهمیه وجود ندارد.
- اگر `add_candidate` ناموفق شود یا `_educate` به بودجه بخورد، باز هم سهمیه مصرف شده → آن ستاپ تا پایان expiry **خاموش** می‌ماند.
ضمناً دو dict سراسری (`_DEAD_GATE_ALERTED`, `_SUPPRESSED_EDU_ALERTED`) **بدون هیچ تخلیه‌ای** رشد می‌کنند و با `time.monotonic()` کار می‌کنند → بعد از redeploy همه‌چیز ریست می‌شود (یعنی یک burstِ تکراری بعد از هر دیپلوی ممکن است).

### F18 · سازگاری با pandas 3.0
- `requirements.txt`: `pandas>=2.1.0,<3.0` → نصبِ تازه **همیشه** ۲.۲.۳ می‌گیرد (الان هم همین است). خوب.
- ولی `pd.Timestamp.utcnow()` در **۳ جای کد اصلی** استفاده شده (`main.py:606`, `main.py:805`, `analysis/setups_experimental.py:795`) — در pandas 2.2 **deprecated** است و در 3.0 حذف می‌شود.
- ۱۸ warning در تست‌ها، از جمله `SettingWithCopyWarning` و `FutureWarning: ChainedAssignmentError` — این‌ها در pandas 3 (CoW) **دیگر کار نمی‌کنند**، یعنی تست‌ها بی‌صدا معنایشان را عوض می‌کنند.

---

## ۶) 🟢 بهداشتِ کد (کم‌خطر، ولی نشانهٔ همان بیماری)

- **`pyflakes` ۱۰ ثانیه‌ای که هیچ‌وقت اجرا نشده** — خروجی کاملش روی ۶ فایل اصلی:
  ```
  main.py:469,487        undefined name 'Optional'
  main.py:828            undefined name '_t'
  main.py:699            local variable 'pin_frame' is assigned to but never used
  bot/messages_v7.py:2780 undefined name 'edu_chat'
  database/repository_v7.py:1317 undefined name 'resolution_candle'
  database/repository_v7.py:1318 undefined name 'resolved_at'
  database/repository_v7.py:1008 local variable 'truth' is assigned to but never used
  + ۶ import بلااستفاده در main.py (supersede_similar, acquire_symbol_lock, has_unresolved_symbol)
  + ۴ متغیر بلااستفاده در messages_v7.py
  ```
  `bot/messages_v7.py:2780` → `edu_chat` تعریف‌نشده داخل `send_technoclassic_preview`. الان با `if edu_mid:` و `edu_mid = 0` هاردکد محافظت شده (یعنی **کد مرده**)، ولی به محض اینکه کسی preview را دوباره به کانال هشدارها وصل کند → crash.
  `resolution_candle` با `if "resolution_candle" in locals()` محافظت شده — یعنی همیشه `float(entry)` می‌شود؛ آن شاخه **هرگز** قیمتِ واقعیِ لحظهٔ بسته‌شدن را گزارش نمی‌کند.
- فایل سرگردان `root` (محتوا: `3.11.9`) در ریشهٔ ریپو commit شده — احتمالاً خروجیِ یک `python -V > root` که اشتباه redirect شده. باید حذف شود.
- `_next_aligned` و `_next_aligned_scan` (main.py:929 و 940) **کد تکراریِ یکسان**اند؛ دومی فقط اسمش فرق می‌کند.
- `cleanup_candidates` سه شرط OR دارد که سومی (`status NOT IN (...) AND updated_at < legacy_cutoff`) **کاملاً** زیرمجموعهٔ اولی (`... AND updated_at < resolved_cutoff`) است، چون ۶ ساعت < ۷ روز → شرط مرده.
- هیچ lint/format/CI-pyflakes ای در پروژه نیست (فقط `compileall` که NameError را نمی‌گیرد — چون NameError زمانِ اجرا رخ می‌دهد، نه زمانِ کامپایل).

---

## ۷) نقشهٔ اصلاح — به ترتیب اولویت

### فاز ۱ · خونریزی را بند بیاور (۳۰ دقیقه، بدون تغییر منطق)
1. `repository_v7.py:1318` → `"event_at": str(latest_checked or confirmed_at)` (همان الگویی که مسیر ladder استفاده می‌کند).
2. `main.py:828` → **فقط همین یک خط را حذف کن**: `_t(candidate)["dup"] += 1`. بقیهٔ بلوک (`status="CANCELLED"`، `update_candidate`، `continue`) باید بماند تا gate واقعاً جلوی انتشارِ سیگنالِ تکراری را بگیرد. اگر فقط خط را کامنت کنی و `continue` نماند، F2 بدتر می‌شود.
3. `main.py:18` → `from typing import Dict, Optional, Tuple`.
4. مارکرها را بعد از ارسال موفق بگذار: در heartbeat `hb_bar` و در live-break `live_break_bar` فقط وقتی `send_setup_update(...)` → `True`.
5. `bot/messages_v7.py:2780` → `edu_chat = CHAT_ID_EDUCATION or CHAT_ID_ADMIN` را بالای تابع تعریف کن (یا شاخهٔ مرده را کامل حذف کن).
6. `.github/workflows/tests.yml` → `pip install pytest` + `python -m pytest tests/ -q` (و `pytest` را به `requirements-dev.txt` اضافه کن).
7. `python -m pyflakes .` را به CI اضافه کن (همین یک خط، F1/F2/F3 را **قبل از merge** می‌گرفت).

### فاز ۲ · صدای پروژه را وصل کن (۱-۲ ساعت)
8. یک helper واحد: `def _safe(label, fn, default=None)` که استثنا را **با `print`/لاگ ساختاریافته** گزارش کند؛ همهٔ ۶۱ `except: pass` را با آن عوض کن. حداقل در `main.py` و `messages_v7.py`.
9. یک شمارندهٔ خطا در `bot_kv` (`error_tally`) تا «چرا پیام نیامد» از DB قابل پاسخ باشد — همان کاری که برای `scan_summary` کردی، برای خطاها.

### فاز ۳ · بار را کم کن (۲-۳ ساعت)
10. **connection pool** برای Postgres (`psycopg2.pool.ThreadedConnectionPool`) — بزرگ‌ترین بردِ عملکردیِ پروژه.
11. `_candidate_market_frames` را با کشِ کوتاه (۵-۱۰ ثانیه) یا با `use_cache=True` + TTL اجرا کن؛ مانیتور هر ۱۰ ثانیه نیاز به دادهٔ خامِ شبکه ندارد.
12. throttle را **به ازای هر نخ/هدف** جدا کن (یا یک صف با اولویت: TP/SL > confirmation > discovery) تا اسکنِ ۵۰۰ ریکوئستی، خروجِ معامله را معطل نکند.
13. `watchlist_max_symbols = 100` را بازبینی کن؛ با ۵ تایم‌فریم = ۵۰۰ ریکوئست در هر سیکل.
14. یک سقف برای تعداد زنجیرهٔ فعال بگذار، وگرنه expiry های ۵-۱۴ روزه بار را یک‌طرفه زیاد می‌کنند (F9).

### فاز ۴ · یک حقیقت (۲-۳ ساعت)
15. `CHAT_CONTEXT.md` را **حذف** کن (یا با `HANDOFF.md` واقعی جایگزین کن).
16. `HANDOFF.md` + `PROJECT_MAP.md` + `DECISIONS.md` بساز — از روی **کد**، نه از روی حافظهٔ چت.
17. سیاست expiry را **یکجا** کن: `expiry_hours_for` تنها منبع؛ `setups_experimental.py:863` را به آن وصل کن (F8).
18. فلگ‌های ستاپ‌ها را با قانون ۶ آشتی بده: یا `viva_tlbreak_enabled = True` در کد، یا قانون را اصلاح کن (F6/قانون ۶).
19. `_tech_aids_lines` را به `send_confirmed`، `send_approaching`، `send_educational_setup` و `send_verdict_reply` وصل کن (قانون ۴).
20. دو ژنراتور رویداد را یکی کن، یا فیلدهای مشترک را در هر دو تضمین کن (F20).
21. `CHANGELOG.md` را برای phase5/6/6b پر کن.
22. کد مرده را حذف کن: `_pinv_*`، `resolution_candle`-guard، شرط سوم `cleanup_candidates`، `_next_aligned_scan`، فایل `root`.

### فاز ۵ · تستِ مسیرهای بی‌صدا
23. تست برای **مسیر legacy** رویدادها (بدون `target_state_json`) → همان‌جا F1 را می‌گرفت.
24. تست برای `monitor_candidates` وقتی `recent_geometry_duplicate` → True (F2).
25. تست برای heartbeat/live-break وقتی `send_setup_update` → False (F4).

---

## ۸) جمع‌بندی یک‌خطی

پروژه **منطقِ درستی دارد** (قوانین ۵ و ۷ تمیز پیاده شده‌اند) ولی **سه بیماریِ ساختاری** دارد که با هم ترکیب شده‌اند:
**(الف)** شبکهٔ ایمنیِ تست عملاً خاموش است (۲۴ از ۱۱۷) → **(ب)** هر خطایی با `except: pass` بلعیده می‌شود → **(ج)** بارِ DB/HTTP با تعداد زنجیره‌های زنده رشد می‌کند و pool ای در کار نیست.
نتیجه: باگ‌ها **بی‌صدا** وارد می‌شوند، **بی‌صدا** می‌مانند، و سیستم **هر روز سنگین‌تر** می‌شود. این دقیقاً همان چیزی است که در ۱۹ روز دیده‌ای — و ربطی به «بدشانسی» یا «تغییر چت» ندارد؛ تغییر چت فقط آن را **دیدنی** کرد.

---

# بخش ۹ — باگ‌های گزارش‌شدهٔ میدانی (۲۰۶-۹-۱۴ شب) → نگاشت به کد

> این بخش بعد از دیدن چارت‌ها و پیام‌های واقعی اضافه شد. هر بند: symptom → مکان → مکانیسم.

## B1+B2 · پوزیشن با استاپ ۴ تا ۳۰ برابر TP · تأیید در انتهای اسپایک (XLM K878487، BCH K831533، LINK K584068)
**یک ریشه، سه تقویت‌کننده:**
1. **حذف وتوی RR و chase** — کامیت‌های `a35d6db` (phase6) و `b21b50a` (phase6b):
   `analysis/quality_engine.py:375-399` — اگر `tl_fast_break` ست شده باشد، `ENTRY_TOO_FAR` و `RR_DEGRADED` **دیگر reject نمی‌کنند**؛ فقط `chase_note` / `rr_degraded_note`. این عیناً قانون مصوب Viva است — ولی یعنی **هیچ کفِ عقلانی‌ای نمانده**: R:R 0.03 هم CONFIRMED می‌شود.
2. **fast-lane روی خودِ کندل اسپایک تأیید می‌دهد** — `quality_engine.py:214-231`: همهٔ کندل‌های بعد از هشدار اسکن می‌شوند (از جمله کندلِ نوک اسپایک)؛ آستانه‌ها با `mean(high-low)` همان فریم (F12) که در اسپایک **کوچک‌تر** می‌شود → عبور از آستانه آسان‌تر. + F13 (کندل مرزی/`tail(2)`).
3. **SL و TP در لحظهٔ دیتکشن فریز می‌شوند** ولی `planned_entry = close` تأیید است → در نوک اسپایک: entry بالای منطقه، SL ساختاری خیلی پایین، TPها نزدیک entry → R:R 0.03/0.14. (نمودار XLM: risk ≈ ۱۰٪، reward ≈ ۰.۳٪.)
4. **`absorb_update_into_chain` اعداد زنجیرهٔ زنده را بازنویسی می‌کند** — `database/candidate_store.py:280-290`: `holder.score/entry_zone/sl/tp1/tp2/evidence/mandatory_gates` از دیتکشن تازه جایگزین می‌شود → چارت/اعداد یک زنجیرهٔ زنده می‌تواند وسط عمر عوض شود (از جمله score → 0).
**⚠️ ناسازگاری قابل‌بررسی:** با پیش‌فرض‌های ریپو (`config.py:108-109` → educational=6، execution=7) تأیید با **SCORE 0/10** از `evaluate_confirmation` **غیرممکن** است (gate در `quality_engine.py:~413`). پس یا در env لایو `EXECUTION_MIN_SCORE`/`EDUCATIONAL_MIN_SCORE` override شده، یا این چارت‌ها بعداً از payload بازنویسی‌شده توسط absorb رندر شده‌اند.
**چک:** env رایلوی + payload ردیف‌های `VIVA-TLBREAK-K878487` / `K831533` در `signal_candidates` (فیلدهای `score`, `rr_tp1`, `metadata.last_reject_code`, `updated_at`).

## B3 · ۴۰-۵۰ «هشدار نهایی» در ۲ ساعت
«هشدار نهایی | آماده‌سازی ورود» = `send_approaching` (`bot/messages_v7.py:1977`). سه مکانیسم همزمان:
1. **absorb زنجیره را ریست می‌کند:** `database/candidate_store.py:276-278` → `holder.approaching_sent = False; holder.status = "EDUCATIONAL"` هر بار که zone جابه‌جایی معنادار داشته باشد. در بازار اسپایکی، zone در هر اسکن جابه‌جا می‌شود → approaching **دوباره** ارسال می‌شود. برای approaching هیچ throttle ای وجود ندارد (قانون anti-echo 300s فقط آپدیت‌ها را می‌پوشاند).
2. **ماندگاری غیراتمی:** `main.py:769-772` → `approaching_sent=True` فقط در حافظه؛ ذخیره در `update_candidate` انتهای حلقه (`main.py:845`). هر استثنا بین این دو (که با `except` در `main.py:847` بلعیده می‌شود) = از دست رفتن پرچم = ارسال مجدد در سیکل بعد (سیکل‌ها الان دقیقه‌ای‌اند — F9).
3. **تقویت‌کننده:** F12 (ATR آب‌رفته) → `distance_atr <= 0.30` برای زنجیره‌های زیاد همزمان درست می‌شود → burst.

## B4 · خط روند: مشخص نیست از کدام پیوت شروع شده / خط تقریباً عمودی (ATOM 4H)
- فیت = دو پیوت آخرِ context-TF؛ ولی **رسم روی کل عرض بوم** کشیده می‌شود (کامیت `3f975c1`؛ `bot/messages_v7.py:1235-1260` و `1338-1350`) و **extrapolation بدون clamp** است (F14: `quality_engine.py:196-207`، `main.py:585-600`). اگر دو پیوت در زمان نزدیک باشند → شیب انفجاری → خط عمودی که از کادر بیرون می‌زند.
- نقطه‌های پیوت کوچک‌اند و خط لبه‌به‌لبه است → چشم نمی‌تواند لنگرگاه‌ها را پیدا کند. **نه سقف شیب وجود دارد، نه نشانهٔ واضح «این دو پیوتِ من».**

## B5 · تایم‌فریم چارت ≠ تایم‌فریم ستاپ (اسکالپ ۱۵m با چارت ۱h؛ یک‌ساعته با چارت ۴h؛ عنوان 15M + VIEW 30M)
**چهار تصمیم‌گیرندهٔ مستقل TF، بدون منبع حقیقت:**
1. `_chart_frame` (`main.py:74-81`): برای TLBREAK/TECHCLASSIC چارت = **context** tf (SCALP→1h، DAYTRADE→4h). طراحی عمدی — ولی کاربر پیام را با زبان trigger می‌خواند.
2. عنوان چارت (`bot/messages_v7.py:1428-1429`): TF اصلیِ عنوان = tfِ دیتافریم/ویو؛ زیرنویس `TRIG x` + `VIEW y` از metadata.
3. انتخاب‌کنندهٔ `chart_view_tf` (`bot/messages_v7.py:2345-2360`): تا جایی zoom-out می‌کند که همهٔ لول‌ها جا شوند (15m→30m→1h) و metadata را ست می‌کند.
4. **فراخوان‌ها گاهی دیتافریم خودشان را می‌دهند** (مثلاً `frames[(symbol, trigger)]` در مسیر confirmed) و دیتافریمِ انتخاب‌شده را دور می‌اندازند → برچسب و کندل در **هر دو جهت** اختلاف می‌کنند.
+ zone/ATR/آستانه‌ها روی فریم trigger/pattern حساب می‌شوند ولی روی کندل‌های context رسم می‌شوند → ناحیه از نظر چشم «جای دیگر» است.

## B6+B7 · پیام‌های مختصر/تفصیلی نصفه می‌آیند · کمکی‌ها و نظر AI «نیامده‌اند»
**ریشه: `caption[:1000]`** — `bot/messages_v7.py:536` (`send_photo`) و همان برش در `edit_chart_message`. تلگرام برای کپشن عکس سقف ۱۰۲۴ دارد و کد **بدون هیچ degration ای** در ۱۰۰۰ می‌برد:
- هر پیامِ با چارت که از ۱۰۰۰ کاراکتر بگذرد، دمش گم می‌شود: footer (⛔/✅/📢)، یا بلوک 🧩، یا خط نظر AI — بسته به ترتیب.
- dump اول شما («…سپس Con») و dump دوم (تمام شدن بعد از 🧩) هر دو دقیقاً همین برش‌اند. پیام رفرنس ETHFI چون <۱۰۰۰ کاراکتر بود سالم ماند.
- `send_message` درست chunk می‌کند (`_chunks` با سقف ۳۹۰۰ و شکست روی پاراگراف) — پس پیام‌های بدون چارت سالم‌اند؛ **فقط پیام‌های با چارت بریده می‌شوند.**
- «قرار بود کمکی‌ها و نظر AI اضافه شود»: اضافه **شده‌اند** (`_tech_aids_lines`) ولی چون بعد از کاراکتر ۱۰۰۰ می‌افتند، در بسیاری از پیام‌ها **هرگز دیده نمی‌شوند** → حسِ «نیامده». ضمناً در `send_confirmed` / `send_approaching` / تفصیلی اصلاً صدا زده نمی‌شوند (قانون ۴ ناتمام).
- `edit_text_message` هم `text[:4000]` می‌برد (`messages_v7.py:2618`).

## جمع‌بندی بخش ۹
هیچ‌کدام از این هفت مورد «تصادفی» نیستند؛ همه از **چهار تصمیمِ تک‌نقطه‌ای** بیرون می‌آیند:
(۱) حذف وتوهای RR/chase بدون کف جایگزین → B1/B2؛
(۲) absorb که زنجیرهٔ زنده را بازنویسی/ریست می‌کند → B3 + جهش اعداد؛
(۳) ماندگاریِ «اول تغییر در حافظه، بعد ذخیره در انتهای حلقه» + except‌های بلعنده → B3 و F4؛
(۴) برش سخت ۱۰۰۰ کاراکتری کپشن → B6/B7.
به‌علاوهٔ دو تصمیمِ نمایشی: رسم لبه‌به‌لبهٔ خط بدون clamp/لنگر (B4) و چهار منبع TF برای یک چارت (B5).
