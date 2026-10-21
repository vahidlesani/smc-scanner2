# چک‌لیست انتقال به اکانت جدید ریلوی (مهلت تقریبی: ۱۰ روز)

هدف: هیچ متغیری جا نماند و مصرف همچنان در سقف ~۰٫۱۲ دلار/روز بماند.
مقدارها را از داشبورد اکانت فعلی (Environment → Variables) کپی کن؛ اینجا فقط
**نام‌ها و نقش‌شان** ثبت شده تا چیزی گم نشود. کد طوری نوشته شده که اگر
متغیری ست نشود، پیش‌فرضِ درستِ کد اعمال می‌شود (ستون «پیش‌فرض کد»).

## ۱) حیاتی (بدون این‌ها بات بالا نمی‌آید)
| نام | نقش | پیش‌فرض کد |
|---|---|---|
| TELEGRAM_TOKEN | توکن بات | ندارد — الزامی |
| CHAT_ID_VIVA_SIGNALS | کانال سیگنال‌ها | ندارد — الزامی |
| CHAT_ID / CHAT_ID_SIGNALS / CHAT_ID_RESULTS / CHAT_ID_APPROACHING | کانال‌های دیگر محصول | برخی خالی مجاز |
| ADMIN_USERNAMES | مدیرهای بات | خالی |
| DATABASE URL / رشتهٔ اتصال DB گیت بودجه | اگر در داشبورد هست عیناً کپی شود | — |

## ۲) حکم‌های ویوا (حتماًexplicit ست شوند، به پیش‌فرض اعتماد نکن)
| نام | مقدار مصوب | پیش‌فرض کد |
|---|---|---|
| LIVE_STYLES | DAYTRADE,SWING,GRAND | همان (اسکلپ خاموش) |
| MONITOR_MINUTES | 3 | همان |
| FULL_SCAN_MINUTES | 15 | همان |
| SCAN_OFFSET_MINUTE / MONITOR_OFFSET_MINUTE | 1 / 1 | همان |
| VIVA_TLBREAK_ENABLED | مقدار فعلی داشبورد | — |
| PINVAL_SYMBOLS / PINVAL_ALLOWED_* / TECHCLASSIC_* / ALBROX_SYMBOLS / EXPERIMENTAL_TLBREAK_SYMBOLS / RANGE_FRACTION_SYMBOLS | لیست‌های فعلی داشبورد عیناً کپی | پیش‌فرض‌های کد |

## ۳) برند/فرمت چارت و پیام (کپی عینی از داشبورد)
CHART_STYLE, CHART_BRAND_NAME, CHART_BRAND_HANDLE, CHART_RANGE_OVERLAY,
CHART_STRUCTURE_LINES, CHART_SCENARIO_ZIGZAG, CHANNEL_NAME,
CHANNEL_INVITE_URL, WALLET_* , REF_*_URL

## ۴) مصرف/مصرف‌سازی (دست نزن مگر با حکم ویوا)
WATCHLIST_MAX_SYMBOLS, WATCHLIST_TOP_TURNOVER, WATCHLIST_REFRESH_MINUTES,
BYBIT_CACHE_SECONDS, BYBIT_TIMEOUT_SECONDS, CANDIDATE_EXPIRY_HOURS_*,
ENTRY_FILL_MAX_BARS_*, MAX_OPEN_TRADES, MAX_CORRELATED_TRADES,
MAX_SIGNALS_PER_SYMBOL_TRIGGER, UPDATE_MIN_GAP_SECONDS,
TELEGRAM_MIN_SEND_GAP, CANDIDATE_MONITOR_SECONDS, REALTIME_EXECUTION_SECONDS

## ۵) بعد از انتقال
1. دیپلوی اول را بگیر و تا SUCCESS صبر کن؛ سپس یک چرخهٔ اسکن + یک چرخهٔ
   مانیتور را در لاگ ببین (نباید خطای توکن/چت‌آیدی بدهد).
2. مصرف روز اول اکانت جدید را با ~۰٫۱۰–۰٫۱۲ دلار مقایسه کن؛ اگر بیشتر شد،
   اول MONITOR_MINUTES و WATCHLIST_MAX_SYMBOLS را چک کن.
3. سرویس قدیمی را فقط بعد از دیدن اولین پیام زندهٔ کانال از اکانت جدید خاموش کن.
