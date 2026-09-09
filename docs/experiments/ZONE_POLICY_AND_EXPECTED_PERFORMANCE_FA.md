# گزارش سیاست نواحی و برآورد عملکرد چهار ستاپ

**تاریخ:** 2026-09-09
**دامنه:** PINVAL/PINWALL، PINWALLQ، ALBROX و TLBREAK
**وضعیت:** پژوهشی و Shadow؛ بدون تغییر اجباری در Gateهای زنده

## جمع‌بندی اجرایی

هر چهار ستاپ اکنون می‌توانند همهٔ نواحی تعیین‌شده را به‌عنوان Context دریافت کنند: Demand، Supply، FVG، Flag Limit، Flip، Order Block، Liquidity Sweep و Premium/Discount. برای Long، Demand و Discount نقش هم‌جهت دارند؛ برای Short، Supply و Premium نقش هم‌جهت دارند. FVG، Flag Limit، Flip و Order Block در هر دو جهت قابل استفاده‌اند، مشروط به اینکه جهت Zone با سمت معامله سازگار باشد.

در این مرحله، سیاست‌ها فقط یک امتیاز پژوهشی تولید می‌کنند و به‌طور خودکار کاندید را حذف نمی‌کنند. این تصمیم لازم است، چون ریپو دادهٔ تاریخی Replay یا Journal کامل برای محاسبهٔ Win Rate واقعی ندارد. ارائهٔ درصد دقیق بدون اجرای Replay، عددسازی محسوب می‌شود.

## منطق فیلتر پیشنهادی

| ستاپ | مکان اصلی | Confluence ترجیحی | شرط ساختاری مستقل |
|---|---|---|---|
| PINVAL / PINWALL | Long در Demand یا Discount؛ Short در Supply یا Premium | FVG، Flip، Order Block | Pin anatomy، rejection، structural targets و ریسک معتبر |
| PINWALLQ | همان مکان، اما با سخت‌گیری بیشتر | FVG/IFVG، Flip، Order Block | کیفیت wick/body، compression، first-touch و عدم Counter-Polarity |
| ALBROX | ترجیحاً در Demand/Supply بعد از Sweep | Order Block، FVG، Flag Limit، Flip | Spike → Sweep/Reclaim → Base → Displacement → Pin/confirmation |
| TLBREAK | شکست معتبر به سمت Demand/Supply یا Flip | Flip، Breaker، FVG، Order Block | Geometry، Close بیرون خط، Retest، Rejection و Micro-BOS |

### امتیاز سیاستی

امتیاز پایهٔ پیشنهادی از این اجزا ساخته می‌شود:

| عامل | امتیاز |
|---|---:|
| مکان هم‌جهت با جهت معامله | +2 |
| وجود یکی از Zoneهای ترجیحی | +2 |
| FVG نزدیک | +1 |
| IFVG نزدیک | +1 |
| Order Block نزدیک | +1 |
| Breaker نزدیک | +1 |
| Flag Limit نزدیک | +1 |
| Liquidity Sweep نزدیک | +1 |
| Premium/Discount هم‌جهت | +1 |

سیاست معمول برای هر چهار ستاپ در امتیاز حداقل **۳ تا ۴** قابل بررسی است؛ حالت Strict در امتیاز **۵ تا ۶** بررسی می‌شود. برای TLBREAK، امتیاز Zone به‌هیچ‌وجه جایگزین Geometry و Retest نیست.

## تفاوت با ادعای «تنظیمات تریدرهای بزرگ»

هیچ تنظیم واحدی که به‌صورت عمومی و معتبر ثابت کند مثلاً یک FVG با اندازهٔ خاص یا یک Order Block مشخص همیشه Win Rate معینی دارد، وجود ندارد. منابع آموزشی عمومی بیشتر دربارهٔ تعریف و توالی مفاهیم صحبت می‌کنند، نه دربارهٔ یک پارامتر بهینهٔ جهانی. بنابراین تنظیمات زیر، **ترجمهٔ مهندسی‌شدهٔ اصول رایج به Rule قابل تست** هستند، نه ادعای نقل قول از یک تریدر خاص.

اصول استفاده‌شده عبارت‌اند از:

1. FVG باید یک عدم‌تعادل سه‌کندلی باشد و قبل از ورود، Retest/Fill یا واکنش مشخص نشان دهد.
2. IFVG زمانی معتبرتر است که FVG قبلی شکسته و از سمت مقابل Retest شود.
3. Order Block باید با Displacement و ترجیحاً Sweep یا Structure Break همراه باشد؛ هر کندل مخالف، Order Block معتبر نیست.
4. Liquidity Sweep باید با برگشت Close و سپس تأیید جهت همراه شود؛ صرفاً Wick زدن به یک Pivot کافی نیست.
5. TLBREAK باید Close معتبر و Retest داشته باشد؛ شکست بدون Retest برای حالت Strict کافی نیست.
6. Premium/Discount یک فیلتر مکانی است، نه سیگنال مستقل.

این اصول با توضیحات آموزشی عمومی دربارهٔ FVG/IFVG، واکنش به Midpoint و Retest در [TrendSpider](https://trendspider.com/learning-center/fair-value-gap-trading-strategy/) و تعریف FVG، IFVG، Order Block، Sweep و Breaker در [TradeZella](https://www.tradezella.com/learning-items/key-ict-concepts) سازگارند. این منابع آموزشی‌اند و تضمین عملکرد یا توصیهٔ سرمایه‌گذاری نیستند.

## گزارش تعداد سیگنال و Win Rate

### چیزی که اکنون با صداقت می‌توان گفت

در نسخهٔ فعلی ریپو، دادهٔ Replay تاریخی کافی برای محاسبهٔ این جدول وجود ندارد. بنابراین مقدارهای واقعی زیر عمداً خالی گذاشته شده‌اند:

| ستاپ | سیگنال قبل | سیگنال بعد از Policy | Win Rate قبل | Win Rate بعد | وضعیت |
|---|---:|---:|---:|---:|---|
| PINVAL/PINWALL | ناموجود در Journal قابل Replay | ناموجود | ناموجود | ناموجود | نیازمند Replay |
| PINWALLQ | ناموجود در Journal قابل Replay | ناموجود | ناموجود | ناموجود | نیازمند Replay |
| ALBROX | ناموجود در Journal قابل Replay | ناموجود | ناموجود | ناموجود | نیازمند Replay |
| TLBREAK | ناموجود در Journal قابل Replay | ناموجود | ناموجود | ناموجود | نیازمند Replay |

عدد حدودی قبلی که کاربر برای Pinwall ذکر کرده بود، برای تحلیل اولیه مفید است، اما چون فایل خام، بازهٔ زمانی، نمادها، تعریف Win، کارمزد، Slippage و نسخهٔ دقیق منطق آن مشخص نیست، به‌عنوان Benchmark رسمی این گزارش استفاده نشده است.

### برآورد آزمایشی، نه نتیجهٔ تاریخی

برای برنامه‌ریزی آزمایش می‌توان انتظار کیفی زیر را داشت؛ این جدول **پیش‌بینی Win Rate نیست**:

| ستاپ | اثر مورد انتظار از فیلتر Zone | اثر مورد انتظار بر تعداد سیگنال | اثر مورد انتظار بر کیفیت |
|---|---|---|---|
| PINVAL/PINWALL | حذف Pinهای Counter-Polarity | کاهش ملایم تا متوسط | بهبود احتمالی در کیفیت مکان |
| PINWALLQ | حذف بیشتر کاندیدهای کم‌کیفیت | کاهش متوسط تا زیاد | کیفیت احتمالی بالاتر، نمونهٔ کمتر |
| ALBROX | نگه‌داشتن Spike/Reclaimهای دارای OB/FVG/Flag | کاهش زیاد در بازار رنج | بهبود احتمالی در Selection، حساس به تعریف Sweep |
| TLBREAK | الزام Context در Retest، بدون حذف Geometry | کاهش ملایم | کاهش Breakoutهای بی‌پشتوانه، اما وابسته به کیفیت Retest |

برای هدف روزانهٔ ۱۵ تا ۲۰ هشدار، ابتدا حالت معمولی با حداقل امتیاز ۳ یا ۴ باید Shadow شود. حالت Strict با امتیاز ۵ یا ۶ احتمالاً تعداد هشدار را کمتر می‌کند و نباید بدون Replay فعال شود.

## طراحی Replay لازم برای تولید اعداد واقعی

برای هر رکورد باید این فیلدها ثبت شوند:

| فیلد | توضیح |
|---|---|
| `timestamp`, `symbol`, `style`, `setup_code` | هویت سیگنال |
| `direction`, `zone_primary_kind`, `zone_candidates` | طبقه‌بندی ناحیه |
| `zone_policy.score`, `strict`, `reasons` | نتیجهٔ فیلتر |
| `entry`, `sl`, `tp1..tp5`, `hit_index` | مسیر معامله |
| `exit_reason`, `PROTECTED_EXIT` | جلوگیری از خطای حسابداری قبلی |
| `fees`, `slippage`, `net_pnl` | نتیجهٔ خالص |
| `bars_to_entry`, `bars_to_exit` | سنجش سرعت و ماندگاری |

Win Rate باید به‌صورت جداگانه برای این تعریف‌ها گزارش شود:

- **TP1 Hit Rate**
- **Net Win Rate** بعد از کارمزد و Slippage
- **Protected-Exit Rate**
- **Full Ladder Rate**
- **Expectancy in R**
- **Maximum losing streak**

فرمول پایه:

```text
Net Win Rate = تعداد خروج‌های net_pnl > 0 / تعداد معاملات بسته‌شده
Expectancy_R = میانگین(net_pnl / initial_risk)
```

این معیارها باید با Split زمانی Out-of-Sample، نمادهای جداگانه و جلوگیری از Look-Ahead محاسبه شوند. یک بازهٔ زمانی واحد یا فقط بهترین نمادها برای انتخاب تنظیمات کافی نیست.

## تصمیم پیشنهادی برای فعال‌سازی بعدی

1. ابتدا همهٔ Zoneها و `zone_policy` در Shadow ثبت شوند.
2. حداقل نمونهٔ اولیه برای هر ترکیب Setup × Zone × Direction جمع‌آوری شود.
3. فقط ترکیب‌هایی که در Out-of-Sample هم Expectancy مثبت و هم نمونهٔ کافی دارند وارد Gate شوند.
4. سپس برای هر ستاپ Gate جدا تنظیم شود؛ یک فیلتر مشترک برای هر چهار ستاپ توصیه نمی‌شود.
5. بعد از آن آستانهٔ خروجی روزانه با نرخ هشدار، کیفیت و هم‌بستگی سیگنال‌ها تنظیم شود.

> این گزارش پژوهشی است و توصیهٔ خریدوفروش یا تضمین Win Rate نیست. هیچ عدد احتمالی در این متن جایگزین Replay واقعی نمی‌شود.
