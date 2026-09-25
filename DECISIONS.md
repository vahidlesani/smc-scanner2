# DECISIONS — یک خط برای هر تصمیم مهم (WORKING_RULES §16)

- 2026-09-25 (R31.4) — fast-lane خط روند با **امتداد خط در زمانِ کندل** (نه شمارهٔ ردیف) ارزیابی می‌شود؛ تصمیم clamp روز ۰۹-۲۳ لغو شد. بازگشت اضطراری: `CONFIRM_TL_EXTRAPOLATE=0`.
- 2026-09-25 (R31.4) — ریجکتِ تأیید هرگز طرح (entry/SL/TP/lane) را تغییر نمی‌دهد؛ snapshot قبل از ارزیابی و بازگردانی روی هر reject.
- 2026-09-25 (R31.5) — باندلِ discovery فریم **30m** دارد (`main._DISCOVERY_TFS`، resample از همان 15m، بدون API اضافه)؛ جریان PINVAL/PINWALLQ DAYTRADE از R31.2 عملاً خاموش بود. گارد تازگی پین هم 30m/4h/1d را می‌شناسد.
- 2026-09-25 (R31.5) — ارزیابی آماری ستاپ‌ها فقط با `experiments/replay_live_setups.py` (walk-forward، همان کد لایو، زمان منجمد، بدون look-ahead) و workflow `replay`؛ نتیجه از Checks API برمی‌گردد. هر تغییر فیلتر/آستانه باید قبل از merge یک A/B روی همین هارنس داشته باشد.
