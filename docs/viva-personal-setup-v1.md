# منطق شخصی Viva — Draft v1

> **وضعیت:** پیش‌نویس کاری برای جلسه فردا.  
> این سند هنوز «قانون live» نیست و هیچ ادعای سوددهی ندارد. قانون‌ها با نمونه‌چارت‌های Viva، candle-by-candle replay و forward-demo تکمیل می‌شوند.

---

## 1) هدف

هدف، ساخت یک ستاپ شخصی Viva است؛ نه اجرای کور همه‌ی قوانین خشک SMC/ICT.

هسته‌ی ایده:

```text
زون مهم / ساختار معتبر
→ پولبک یا برخورد قیمت
→ پین‌بار یا rejection باکیفیت
→ هشدار نهایی اولیه
→ تأیید تایم پایین با شکست ساختار خرد
→ ورود با Stop پشت base / swing واقعی
→ target ساختاری و مدیریت مرحله‌ای
```

اولویت کیفیت است، نه تعداد پیام. خروجی مطلوب می‌تواند چند فرصت محدود اما واضح در روز باشد.

---

## 2) تایم‌فریم‌های اولیه

| مدل | تایم ساختار/زون | تایم هشدار | تایم تأیید |
|---|---:|---:|---:|
| Intraday | 4H / 1H | 15M | 5M |
| Swing | 1D / 4H | 1H | 5M |
| Scalp محدود (فعلاً مستقل live نیست) | 1H / 15M | 5M | 1M |

**قانون:** تایم پایین برای پیدا کردن ورود استفاده می‌شود، نه برای نقض‌کردن بی‌دلیل context تایم بزرگ‌تر.

---

## 3) تعریف پین‌بار باکیفیت

پین‌بار فقط «شکل ظاهری» نیست.

### 3.1 حداقل کیفیت کندل

برای Long (Short برعکس):

- lower wick غالب باشد: `lower_wick / body >= 2.0` به‌عنوان نقطه شروع قابل‌تست.
- body کوچک باشد: `body / range <= 0.35`.
- close در نیمه بالایی range باشد؛ بهتر: 30٪ بالایی.
- range کندل نباید صرفاً 10 تا 15 tick باشد.
- حداقل دامنه باید بر حسب نوسان همان نماد سنجیده شود:

```text
pin_range >= max(0.6 تا 0.8 × ATR تایم هشدار، حداقل دامنه 5×tick)
```

اعداد بالا فرضیه‌اند و فردا با نمونه‌ها refine می‌شوند.

### 3.2 پین‌بار بی‌ارزش

پین‌بار، حتی اگر زیبا باشد، به‌تنهایی هشدار معاملاتی نیست اگر:

- وسط range بی‌هویت باشد؛
- در وسط flag/کانال بدون برخورد به لبه شکل گرفته باشد؛
- دامنه‌اش نسبت به ATR بسیار کوچک باشد؛
- پشت آن هیچ level، base، FVG، flip، trendline یا liquidity نباشد؛
- بعد از حرکت دورشده و late تشکیل شده باشد.

---

## 4) Location مهم‌تر از شکل پین‌بار است

پین‌بار باید در یکی از این موقعیت‌ها شکل بگیرد:

1. **RBR / DBD Base** تازه قبل از displacement
2. **Fresh Supply / Demand**
3. **FVG / Flag Limit**، به‌ویژه لبه‌ی زون نه وسط آن
4. **Flip Zone**، به‌خصوص سقف/کف شکسته‌شده قبلی
5. **Trading Range High / Low** معتبر
6. **Trendline / Channel / Wedge / Triangle edge**
7. **Liquidity sweep** سقف/کف قبل و برگشت معتبر
8. **Distribution / Accumulation edge** در تایم بالاتر

### معنای موقعیت نسبت به زون

| موقعیت پین‌بار | معنی اولیه |
|---|---|
| داخل/روی لبه Demand بعد از pullback | احتمال ادامه یا reversal Long؛ نیازمند تأیید پایین‌تایم |
| داخل/روی لبه Supply بعد از pullback | احتمال ادامه یا reversal Short؛ نیازمند تأیید پایین‌تایم |
| زیر Flag/Flip/Swing High در ناحیه توزیع | ارزش Short یا حداقل scalp/reaction دارد؛ Stop پشت سقف مرجع |
| بالای Flag/Flip/Swing Low در ناحیه accumulation | ارزش Long یا حداقل scalp/reaction دارد؛ Stop پشت کف مرجع |
| وسط flag یا وسط range | صرفاً observation؛ معمولاً هشدار معاملاتی نمی‌دهد |

---

## 5) چرخه‌ی هشدار شخصی Viva

### مرحله A — هشدار نهایی اولیه

وقتی همه‌ی این‌ها هست:

```text
Location معتبر
+ pullback / برخورد واقعی
+ pinbar یا rejection باکیفیت
+ دامنه کافی نسبت به ATR/tick
```

هشدار اولیه با چارت و توضیح مختصر ارسال شود.

این پیام **Entry نیست**.

### مرحله B — تأیید تایم پایین

بعد از هشدار، تایم پایین باید حداقل یکی از این‌ها را بدهد:

- micro BOS/MSS در جهت سناریو؛
- engulf معتبر از داخل زون؛
- rejection close و شکست micro-high / micro-low؛
- close معتبر در جهت سناریو، بعد از pin/rejection.

قانون ضد-chase:

```text
entry_close نباید بیش از فاصله مجاز ATR از mid-zone دور شده باشد.
```

### مرحله C — آپدیت به جای قفل

- هیچ timeout کور «سه کندل و تمام» وجود ندارد.
- هشدار جدید و materially-valid همان نماد، هشدار قبلی را replace می‌کند.
- Candidate فقط با invalidation واقعی، ازبین‌رفتن base/zone یا update ساختاری بهتر تمام می‌شود.
- continuation retest باید setup مستقل با label مستقل باشد، نه تکرار بی‌ارزش first touch.

---

## 6) Stop / Invalidation

Stop نباید صرفاً پشت wick خام یا ATR نازک باشد.

ترتیب anchor:

```text
آخرین base معتبر
→ آخرین swing / liquidity معتبر پشت base
→ buffer
```

Buffer پیشنهادی:

```text
max(
  ATR buffer تایم ساختار/زون,
  5 × venue tick,
  2 × spread,
  floor درصدی متناسب با نوسان نماد
)
```

### نکته اجرایی

- Long: Stop زیر distal base یا swing low معتبر، با buffer.
- Short: Stop بالای distal base یا swing high معتبر، با buffer.
- برای فرصت distribution زیر سقف: Stop پشت همان swing high / سقف قبل.
- برای فرصت accumulation بالای کف: Stop پشت همان swing low / کف قبل.

---

## 7) Target اولیه

Target از ساختار می‌آید، نه صرفاً R ثابت:

1. نزدیک‌ترین liquidity / swing مخالف
2. لبه range یا supply/demand مقابل
3. level ساختاری بعدی

R:R فقط گیت کیفیت است؛ خودش target خلق نمی‌کند.

مدیریت چند TP و trailing بعداً به lifecycle جدا اضافه می‌شود؛ ابتدا entry/location باید با نمونه واقعی تایید شود.

---

## 8) مواردی که فردا با چارت بررسی می‌کنیم

برای هر نمونه Viva این جدول را پر می‌کنیم:

| مورد | پاسخ |
|---|---|
| Symbol / تاریخ / timezone | |
| مدل: Intraday یا Swing | |
| Structure TF | |
| Alert TF | |
| Confirm TF | |
| نوع location | Base / FVG / Flip / Range / Trend / Supply-Demand / Liquidity |
| پین‌بار چرا باکیفیت است؟ | range/ATR، wick/body، close position |
| location کجاست؟ | edge / inside / above / below / middle |
| چه چیزی هشدار اولیه را توجیه می‌کند؟ | |
| تأیید دقیق پایین‌تایم چیست؟ | |
| entry واقعی کجاست؟ | |
| invalidation منطقی کجاست؟ | |
| TP ساختاری چیست؟ | |
| outcome واقعی | TP / SL / no trade |

---

## 9) مرزهای ایمنی

- هیچ پین‌بار به‌تنهایی معامله نیست.
- هیچ مدل با چند نمونه «سودده» یا «مرده» اعلام نمی‌شود.
- هر پارامتر عددی در ابتدا hypothesis است.
- replay باید candle-by-candle باشد؛ موتور اجازه دیدن کندل آینده ندارد.
- نتایج باید setup-by-setup، IS/OOS و پس از fee/slippage گزارش شوند.

---

## 10) تصمیم جلسه فردا

1. فقط منطق Viva + نمونه‌چارت‌های Viva.
2. بدون اضافه‌کردن قانون خشک از AIهای دیگر.
3. ابتدا یک setup مرکزی انتخاب می‌کنیم:

```text
VIVA-TBRB:
Trend/Structure Break → RBR/DBD Base → First Pullback → Pin/Rejection → Lower-TF BOS
```

4. بعد از تعریف کامل با 20 تا 30 نمونه دستی، نسخه‌ی کد آزمایشی و replay ساخته می‌شود.
