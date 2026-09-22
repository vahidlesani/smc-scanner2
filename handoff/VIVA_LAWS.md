# قوانین ویوا — ثبت دائمی (به‌روز می‌شود؛ آخرین: 09-17)

## قانون اسکن چندستاپی (09-17،verbatim)
«هیچ نمادی نباید بعد از هشدار ابتدایی و مفصل تا زمان تأیید از چرخه اسکن بقیهٔ
ستاپ‌ها خارج شود. همهٔ ستاپ‌های ۵ گانه مجوز دارند روی یک نماد دنبال موقعیت
باشند و حتی تأیید کنند.»
وضعیت کد (audit 09-17): ✅ رعایت شده — همهٔ گیت‌ها per (symbol, setup, trigger_tf):
licence absorption / chains_last_24h / same-zone dedupe / 2% law (فقط بعد از
CONFIRMED) / pre-TP1 capacity (از 09-13 با setup_code)؛ find_similar فقط
هم‌خانواده (same lineage)؛ supersede نماد-محور صریحاً رد می‌شود.

## دکترین تأیید در تایم‌های بالا (09-17)
- تأیید رویدادمحور است نه کندل‌شمار: هیچ سقفِ «۳ کندل» وجود ندارد (حکم 09-17: «یا ۱۰۰ تا»).
- پنجرهٔ رصد باید از کندترین بیس معقول زنده بماند: بیس ۴ساعته/روزانه ۶–۱۰ کندل
  زمان می‌برد (دکترین بروکس: «at least 10 bars and two legs»).
- expiry بر اساس تایم تریگر: 15m→36h, 1h→96h, 4h→240h, 1d→360h (کد: EXPIRY_HOURS_BY_TRIGGER).
- شکست روزانه/۴ساعته برای ویوا بسیار مهم است: هشدار + تأیید همان لحظهٔ کلوز
  (نردبان: 4h←15m/1h-late, 1d←1h/4h-late؛ پنجرهٔ واکشی = ۴ دقیقهٔ اول بعد کلوز).
- تا وقتی زنجیرهٔ تایم‌بالا باز است، ستاپ‌های تایم پایین روی همان نماد آزادند
  (سوئینگ‌های کوتاه/میان‌مدت موازی).

## دکترین استاپ (09-17، بروکس‌محور)
«استاپ باید پشت آخرین کف یا آخرین سقف ماقبل با یک بافر استاندارد طبق دکترین
جهانی قرار بگیرد؛ استاپ کوچک فقط به شرط ورود در ابتدای شروع روند.»
- PINVAL/PINWALLQ: sl = دورترِ (لنگر نقدینگی، اکستریم پین ± بافر ≥0.25ATR) — کد اعمال شد.
- ALBROX: base_low/high ± 0.5ATR (موجود ✓).
- نمونهٔ چارت استاپ غلط را ویوا می‌فرستد → بعد از دریافت، بقیهٔ موارد اصلاح شود.
- باگ‌های اعلامی پین‌وال/کیو/البروکس (در دستور کار): تأییدهای بیجا، تأییدنکردن‌های
  بیجا، ورود در سقف/کف، ورود داخل تریدینگ رنج، ورود بعد از شکست ناحیهٔ معتبر؛
  راهکار پیشنهادی: تأییدیه با الگوهای کندلی بروکس (سیگنال‌بار قوی، H2/L2، شکست معتبر+فالو-ترو).

## کیفیت تحلیل (09-17)
- هدف‌ها باید در افق تایم تریگر معقول باشند: XRP 15m با هدف ۹۹ سنت مردود است.
  کد: هدف ساختاری > 25×ATR تریگر → measured target جایگزین می‌شود (TLBREAK).
- تأییدیه‌های کمکی باید «به جد و دقت» تحلیل شوند، نه فهرست تلگرافی.

## پروژهٔ تلفیق (09-17، در انتظار تصویب)
۵ ستاپ → نهایتاً ۲ خانوادهٔ خوانا (پیشنهاد PM، ویوا هنوز تصویب نکرده):
1. VIVA-BREAK (شکست و بازگشت): TLBREAK + ALBROX + TECHCLASSIC — دکترین مشترک:
   شکست + اولین کلوز معتبر + ری‌تست/پولبک + BOS تایم پایین؛ معاف از گیت مید-بیس.
2. VIVA-ZONE (واکنش ناحیه): PINVAL + PINWALL + PINWALLQ — دکترین مشترک: ناحیهٔ
   معتبر + پس‌زدگی/بیس/کامپرشن؛ استاپ پشت سیگنال‌بار.
زیرنوع‌ها در پیام و DB حفظ می‌شوند (تاریخچه خراب نشود)؛ فقط ارائه و پایپ‌لاین یکپارچه.

## بستهٔ چارت (09-17، صف اجرا)
- ناحیه‌ها ۵٪ اشباع رنگ بیشتر + دقت بالاتر در یافتن نواحی.
- کیفیت باکس/نوشتهٔ نواحی هم‌سطح بقیهٔ چارت.
- PINWALL/PINWALLQ/ALBROX هم ترند/وج/مثلث/کانال رسم کنند (مثل TC و TLBREAK).
- معتبرترین ترندها رسم شوند نه صرفاً نزدیک‌ترین‌ها (امتیاز = تعداد برخورد × فیت × طول).

## پلکان اعشار پیام‌ها (09-17، نسخهٔ نهایی — جایگزین حکم قبلی)
- ≥۱۰۰ → با کاما و ۲ اعشار • ۱۰۰ تا ۹۹۹ → ۲ اعشار • ۱ تا ۹۹ → ۳ اعشار
- زیر ۱ دلار → ۴ رقم معنادار (0.00004345 همان‌طور بماند؛ 0.3125 کامل)
- خط فیبو («فاصله دارد و در محدودهٔ واکنشِ این فیبو») → همیشه ۳ اعشار
- helperها: _price / _fmt / _n2 / _f همگی یک پلکان دارند.

## نام ستاپ تکنوکلاسیک (09-17، هشدار ویوا)
«TECHCLASSIC درست است؛ TC آن ستاپِ غیرفعال‌شدهٔ قدیمی است — اشتباه برداشت نکن.»
کد فقط TECHCLASSIC دارد ✓. اگر تکنوکلاسیک هیچ هشداری نمی‌داد، متغیر محیطی
TECHCLASSIC_ENABLED در پروداکشن suspected بود → 09-17 روی true ست شد.

## تصمیم‌های ویوا (09-17 شب):
- تلفیق ۵→۲: **فعلاً نه** — بعد از بستهٔ چارت/بروکس.
- معیار ترند معتبر: **امتیاز ترکیبی برخورد×فیت×طول** (اجرا شد در render_kit).
- دامنهٔ ارتقای بروکس: بعد از بررسی چارت‌های ارسالی پیشنهاد شود.
- سقف هدف: **همان 25×ATR تریگر**.

## سبک رسم الگوها = رفرنس CryptoCove (09-17، حکم ویوا)
رفرنس بصری: /home/user/uploads/IMG_20260814_2132*.jpg (زمینه سبز/گرادیانی
کریپتو کاو). قوانین رسم:
- خطوط ترند/کانال/وج/مثلث: **نازک (1.1)، تخت‌رنگ تیره، SOLID** — رنگ جهت‌دار ممنوع.
- وج/مثلث/کانال = دو خط همگرا/موازی + **باکس سبز measured-move** در پنل آینده:
  ارتفاع الگو از قیمت زنده projecting، fill سبز ~30٪، حاشیه نازک، ستون فلش
  دوسر وسط، لیبل بالا «ارتفاع (درصد٪)» با پلکان اعشار.
- باکس RANGE: حاشیه نازک SOLID + خط‌چین میانه.
- تشخیص وج: دو خط هم‌جهت همگرا در مختصات سراسری (باگ mixin پنجره‌ها رفع شد).

## قانون جایگذاری خط روند کلاسیک (09-18 — پیاده‌سازی شد)
- خط روند = جست‌وجوی جفت‌پیوت کلاسیک: دو پیوت اصلیِ موج، بدون هیچ پیوت هم‌سمتِ عبورکننده میان آن دو؛ عبورِ تنها یک پیوت فقط برای شانه‌های تخت H&S مجاز (|Δy|<0.5×ATR).
- خط تا نشکسته معتبر است: هیچ پیوت تأییدشده و هیچ کلوزی در سمت راست جفتِ تعریف‌کننده حق عبور از خط را ندارد (خط شکسته = تاریخ، رسم نمی‌شود).
- خط زنده: آخرین لمس ≤ ۴۰ کندل قبل؛ ارزش برون‌یابی‌شده در لبهٔ چارت ≤ ۸×ATR از قیمت فاصله (خط معلق در هوا ممنوع).
- بونوس اعتبار: خطی که از نقطهٔ اکستریم موج (قله/کف) شروع شود ×۲؛ امتیاز = لمس‌ها × √Span.
- لایهٔ رندر: require_alive=True + حداقل ۲ لمس؛ لایهٔ معامله: گیت‌های قبلی (۳ لمس) بدون require_alive (خط شکسته برای fade/breakout لازم است).
- جعبهٔ measured-move سبز داخل پنل clamp می‌شود (روی هدر نمی‌ریزد).

## قانون لنگر زمانی خطوط الگو (09-18 شب — ریشهٔ تمام خطاهای جانمایی)
- پنجرهٔ fit = tail(170) ولی فریم چارت = tail(150): خطوط با ایندکس رسم می‌شدند و ۲۰ کندل جابه‌جا می‌افتادند. حالا هر خط با TIMESTAMP پیوتِ لمس اول روی فریم searchsorted و لنگر می‌شود (همان روش TLBREAK قدیمی که ویوا تأیید کرد).
- سبک تأییدشدهٔ TLBREAK برای همهٔ الگوها: خط رنگی ضخیم (۲.۰) تا کندل زنده، داشد تا لبهٔ بوم، دایرهٔ توخالی روی هر پیوت لمس؛ بالا = supply قرمز، پایین = demand سبز.
- سایهٔ آبی/خاکستری بین دو خط (fill_between باند) حذف شد — «سایه آبی پشتش» ممنوع است.
- خط شکسته (کلوز عبور کرده) رسم نمی‌شود؛ برچسب الگو از هندسهٔ دو خطِ لنگرداده می‌آید (TRIANGLE_DESCENDING برای بالا-نزولی/پا-صعودی و…).

## قانون موتور چندمقیاسی و خطوط شکسته (09-18 شب، پس از شماتیک‌های دوم ویوا)
- موتور روی چهار مقیاس (کل/۱۳۰/۹۰/۶۰) برازش می‌کند: خط MAIN موج + یک خط SUB متمایز (کانال/وج/مثلث کوچک داخل روند) با هم رسم می‌شوند — انعطاف بروکسی: spike→channel→TR و بیس‌های کوچک.
- خط شکسته حذف نمی‌شود: تا کندلِ بریک توپر رسم می‌شود و آن‌طرف‌تر نه (آبی AAVE و قرمز LINK ویوا)؛ خط زنده تا LIVE توپر + داش تا لبه.
- خط تخت («ترندلی» افقی) ترند نیست: باکس SUPPLY/DEMAND از بیس است → باند ناحیه رسم می‌شود.
- الگوی تایم بالاتر (۴ساعته) روی چارت تریگر اعلام می‌شود: «PAT 4H · …».
- چیپ‌های برچسب الگو هرگز روی هم نمی‌نشینند (شیف عمودی خودکار).

## پله‌های بروکس + قوانین انتخاب زمینه‌ای (09-18 شب، پس از فایل مشخصات فنی ویوا)
- پله‌های بروکس (P1 سیگنال‌بار، P2 ورود دوم H2/L2 با استاپ پشت پولبک، P3 پایهٔ ضعیف→فقط آموزشی + سقف امتیاز ۶) **فقط روی ALBROX** پیاده شد + برچسب‌ها روی چارت و آیتم‌های شواهد؛ بقیهٔ ستاپ‌ها دست‌نخورده تا بازخورد لایو بیاید.
- قانون زمینه: قیمت روی دیمند معتبر/محلی ⇒ خط بالایی حتماً رسم شود (گیت‌های recency 90 و edge 16 ATR برای سمت HIGH)؛ روی ساپلای ⇒ خط پایینی (آینه). هدف: بریک خط = هشدار/تأیید ستاپ.
- قانون امتداد: هر ترند/الگو تا بعد از قیمت امتداد می‌یابد — خط زنده داش تا لبهٔ بوم، خط شکسته ادامهٔ نقطه‌چین کم‌رنگ در پنل آینده (بریک‌واچ).
- md["render_line_watch"] = مختصات خطوط اصلی برای وصل‌کردن هشدار بریک در مرحلهٔ بعد.
- نگاشت فایل مشخصات فنی: خوشه‌بندی لمس‌ها (§6.1)، بونوس زمینه (§9)، سبک والد/فرزند و FORMING/FAILED (§13)، بافر بریک ۰.۳۵ ATR (§10)، تو در تو main+sub (§8) = پیاده؛ مدل سیگنال JSON کامل، بک‌تست بدون سوگیری، امتیاز حجم و درخت ۳سطحی = مرحلهٔ بعد.
- ممیزی چرخه: هر ۵ خانوادهٔ ستاپ (TLBREAK, PINVAL/PINWALL, PINWALLQ, ALBROX, TECHCLASSIC) ACTIVE و در چرخهٔ اسکن؛ هیچ گیت فعال‌سازی تغییر نکرد.

## پنل ۵ ستاپ + حقیقت P&L + حذف سقف کندلی پر شدن (09-19)
- پنل «مدیریت ستاپ‌ها» حالا هر ۵ ستاپ را با آمار ژورنال نشان می‌دهد (تعداد/برد/باخت/WR/P&L/میانگین برد/میانگین باخت)؛ سوئیچ env فقط TLBREAK و TECHCLASSIC؛ بقیه همیشه فعال چرخهٔ اصلی.
- حقیقت P&L: استاپ تریل‌شدهٔ بهتر از استاپ اصلی، سطح خروج واقعی است (قبلاً ضرر بزرگ‌تر ثبت می‌شد)؛ هدف صفر/نامعتبر = هیچ منطق TP (محافظت در برابر TP1 در قیمت صفر).
- سقف کندلی «پر نشدن ورود» حذف شد: کنسلیِ بدون فیل فقط با انقضای زمانی (expiry_hours_for) یا ابهام هم‌کندلی entry/stop (fail-closed = NO TRADE). قانون: هیچ محدودیت تعداد کندل نه بر تأیید نه بر نگهداری/پر شدن؛ افق = ابطال ناحیه/انقضا.
- تشخیص عدم‌تقارن R: با WR بالا و P&L منفی، علت ساختاری = بردِ parziale TP1 کوچک در برابر باخت SL کامل؛ پیشنهاد حکم: کف TP1 = ۱× فاصله استاپ (منتظر حکم ویوا).

## 09-19 (round 2) — ALIGNED EXIT LADDER + SMART TRAILING (Viva ruling via ask_user + his attached professional engine spec)
ROOT CAUSE of WR73% / −22.68%: old hidden 5-segment ladder (35/35/20/5/5 over entry→TP2) banked +0.14R..+0.42R typical wins, max +0.84R, vs full −1R losses → breakeven WR 77–88%. Fixed by aligned ladder.
1. LADDER (new signals, version 2): exits sit ON drawn levels — 3 exits 50/30/20 when final ≥2R (TP1 = structural 40%-point or 1R floor whichever farther, TP2 = midpoint, TP3 = structural final); 2 exits 60/40 when ≥1R; single exit below 1R. TP1 FLOOR = 1×stop distance (his ruling). Live v1 rows keep old behavior until closed (version gate).
2. STOP LADDER: after TP1 → NET breakeven = entry + round-trip fee+slippage (professional point 5); after TPn → prior target + 5 ticks. Between targets: protection floor (his spec §4: α=0.40 of entry→TP1 band, β=0.50 of later bands) + volatility stop (recent 5-bar swing ∓ 1.0×ATR, §5.3); interpolates from post-TP stop toward band floor as price progresses; RATCHET ONLY (never loosens — his professional point list); updates once per CLOSED monitor candle, improvement gate = tick_gap (professional point 6: no per-tick churn).
3. SMART EXIT (spec §7/§9, armed only after TP1): monitor-TF signs score +1 each (structure low/high break, valid engulfing, reversed pin, volume ≥1.8×20-bar avg on directional candle, doji cluster after extended run, 3 consecutive directional closes with rising volume). ORANGE (2) = 🟠 warning note once per band (no close). RED (≥3) = close ALL remainder at that closed candle's close; result message carries the explainable Persian reason list (spec §2.2). Exchange klines (Bybit/Ourbit) carry NO taker-side volume split → pressure is a composite proxy (spec §8 subset); true taker delta needs the trades endpoint = deferred.
4. NEW SHORT ALERTS: 🔒 PROFIT_FLOOR + 🟠 EXIT_WARNING — text-only (consumption law), main channel + VIVA_SIGNALS mirror under last TP receipt; max ~2 per band. Result message: dynamic «هر N پله» + «خروج هوشمند» title when close_reason=SMART_EXIT.
5. MESSAGE/CHART TRUTH: confirmed message TP rows, chart pills and mm profit lines all read the SAME ladder (targets/weights) — no more 60/40-vs-35/35 split-brain. Chart pill art frozen; final pill keeps tp2 tint.
6. HIS 6 PROFESSIONAL POINTS mapping: (1) TP fill = closed-candle touch, conservative stop-first ordering — LIVE; (2) Reduce-Only/Stop-Market + Mark/Last trigger type — EXECUTION-LAYER law for the future real-exchange hookup (bot is alert + journal-simulation mode, spec §12) — recorded, N/A today; (3) error state machine — restart-safe ladder JSON in DB + ambiguous fail-close NO TRADE + startup repair job — LIVE; (4) 5–15s exchange reconciliation — EXECUTION-LAYER (no exchange orders exist); monitor is candle-closed by design; (5) net BE — LIVE now; (6) min-interval trailing updates — LIVE now (closed-candle + tick_gap gate).
7. TESTS: 143 incl. ladder/floor/ratchet/smart-exit/pill-regression suites. Chart pill de-indent regression guarded by test_chart_pills_match_ladder_exits.

## 09-19 (round 3) — MONITOR-TF HIERARCHY + ADAPTIVE FORMULAS + NOTE CHAIN (Viva rulings)
1. MONITORING HIERARCHY (ALL setups, his verbatim map + venue reality): lifecycle (fill gate, ladder, band trail, smart exit) runs on a FINER TF: 1D→1H, 4H/2H/1H→15m, 30m/15m→5m (Ourbit has NO 3m — «یا هرچی داریم»), 5m/3m→1m; falls back to trade TF if venue lacks the interval. repository_v7.monitor_tf_for / MONITOR_TF_FOR.
2. FORMULA FLEXIBILITY (his delegation «تو باید بگی»): volatility-stop n scales √-time: n_monitor = VOL_STOP_ATR_N × √(trade_min/monitor_min) (vol_atr_n_for) so finer candles never tighten the stop in price terms; protection-floor ratios k adapt to band WIDTH in R: k = clip(0.30 + 0.10×(width_R − 0.5), 0.30, 0.50) (his spec §4 corridor); everything else is R/ATR-relative ⇒ price-scale-free; decimals via the ladder naming law.
3. SHORT-NOTE CHAIN LAW: 🔒/🟠 notes carry the unique public code, REPLY to the LAST TP-HIT receipt of that code (walk TP{hit}→TP1, fallback Confirmed), and the journal mirror (results channel) buttons back to the note; TP-hit/stop receipts keep their routine AND now show monitor TF + the new 3-TP ladder weights/stops (all ladder-driven, no hardcoded 5).
4. FILE TRIAGE (his order): archived to handoff/specs/: RISK_ENGINE_SPEC, VOLUME_ONCHAIN_NEWS_ROADMAP, ONCHAIN_MACRO_SOURCES, PRICE_ACTION_SPEC(v2), VALIDATION_BACKTEST_PLAN(پلن۴), OBSERVABILITY_OPS_PLAN(پلن۷); DELETED from uploads: exact duplicates (×3), price-action spec v1 (same as v2), پلن۱/۲/۳/۵/۶ + نقشه_راه_اجرایی + برنامه_جامع (generic re-architecture conflicting with frozen laws / already-covered capabilities).
5. VOLUME/ONCHAIN/NEWS STANDING LAW (his verbatim): these may ONLY add plus-score/evidence/chips (like the ×1.15 context bonus) and analyses — NEVER gates/vetoes/bottlenecks; fail-open when a source is down. Phase order: P1 free keyless (F&G, DefiLlama stablecoins, mempool fees) → P2 flow via aggregator keys or execution-region VPS (Bybit 403/Binance 451 geo-blocks proven 09-19) → P3 news lexicon.

## 09-19/20 (round 4) — CORRECTION ROUND (Viva chart review + kartabel)
KARTABEL: handoff/KARTABEL.md holds the categorized action card (done / P1 / pending-his-ruling).
1. LADDER v3 (his revisit, overrides the 1R-floor ruling): tool shape = ORIGINAL five pills (five equal segments entry→final); TP1 distance exactly as before (TP1 و استاپ هم‌اندازه نیستند — floor RETIRED); exits 40/30/30 on TP1..TP3; TP4/TP5 = INFO pills (zero weight, position closes when weight exhausts or last segment prints). Net-BE + adaptive floors + ratchet + smart exit unchanged on top. TP COUNT may change later (he thinks; maybe 4) — journal data decides.
2. COUNTER-TREND LAW: touch of line/zone against structure = ALERT ONLY; confirmation requires a CLOSED structure break in trade direction (close beyond nearest 10-bar swing). 1D counter setups additionally need the 4H structure-break close first, then the daily close beyond the pattern's far side (ZEC ruling; sellers/get hunted at the touch → liquidity for at least a short reversal).
3. MTF OPPOSING-ZONE GATE at confirmation: parent TF chain 5m→15m→1h→4h→1d (never small-vs-daily); LONG within 0.5×ATR(parent) below a recent parent pivot-high cluster (supply side) or SHORT above a pivot-low cluster (demand side) → reject NEAR_OPPOSING_ZONE_MTF; break first, confirm on pullback.
4. DEGENERATE GEOMETRY sanity (SUI 1D R:R 0.02/0.03 case): rr_tp1 < 0.25 or rr_tp2 < 0.50 → reject at confirmation (scenario stays alert/analysis). Distinct from the RR-veto law (degraded-but-real ratios still confirm).
5. OURBIT HAS 3m (Viva: «اوربیت ۳ دقیقه داره ها»): TF_MAP Min3 added; monitor hierarchy 15m→3m (30m→5m, 5m/3m→1m, 1h/4h→15m, 1D→1H), √-time ATR scaling unchanged.
6. P1 NEXT (kartabel): lifecycle chart time-axis law (never slide the tool; re-render same anchored tool on higher TF + one note line «پس از پایان کندل‌های X این پوزیشن در تایم Y نمایش داده شده است»); nested bearish sub-trend drawing inside uptrends (LTC case); cross-TF same-symbol scenario dedup (POL K124739 dup, ZEC two scenarios); trend/pattern calibration review vs archived spec.
7. FILES: uploads spec set archived to handoff/specs/ (6 files) and the rest deleted per his order — DONE previous round; this round's 15 annotated jpgs kept in uploads as chart ground-truth references.

## 09-19/20 (round 5) — CONFIRMATION LADDER RESTORED + NO-STALL (Viva: «دقیق بگو»)
HIS VERBATIM LADDER (restored this round, overrides the 09-17 amendment): early confirmation = ONE closed candle exactly ONE step below the pattern TF: 15m←3m (Ourbit HAS 3m), 1h←15m, 4h←1h, 1d←4h. LATE bound = the pattern TF's OWN close (only if the finer frame never printed the valid close) — a candidate must NEVER stall: main candidate loop now falls back trigger→late when the confirm frame is missing (metadata confirm_tf_fallback records it).
ROOT CAUSE of the drift he felt: the 09-17 amendment set early confirm to 3m for 15m/1h while Ourbit TF_MAP had NO 3m (added 09-19/20) → finer frame fetch returned None → candidates stalled/waited on coarser closes. Also the early ladder had drifted finer than his ruling (1h←3m, 4h←15m, 1d←1h) — now corrected to his ladder.
SECONDS MONITORS ALIVE (unchanged): realtime ticker loop REALTIME_EXECUTION_SECONDS=5 (instant TP/stop messages, ticker-advanced ladder), candidate monitor loop CANDIDATE_MONITOR_SECONDS=10 (confirmation checks), candle journal monitor = execution cycle (now on the monitor-TF hierarchy 15m→3m etc.). MTF zone awareness: parent-TF opposing-zone veto (added round 4) is AUXILIARY only + context-TF zones as before.

## 09-19/20 (round 6) — PROTECTION-PHASE INSTANT CLOSE + 5M SIGNS TF + MM REFINE (Viva verbatim rulings)
1. EXIT RULE (his words: «نه اینکه رد بشه و فقط هشدار بمونه»): in the PROFIT-PROTECTION phase (after TP1 prints), TWO concurrent reversal signs on the monitor TF (candle pattern + sell-pressure/volume, any two of the six) = IMMEDIATE close of ALL remainder at that closed monitor candle's close — even before price returns to TP1 — with the red alert + reason list. ONE sign = short warning only. BEFORE TP1 the structural stop rules (signs never close a full-risk position — noise would churn us). Between TP2→TP3 the same rule applies (his «حوالی TP3 با هشدار قرمز» case).
2. 5M IS THE SIGNS TF (his «تایم ۵ دقیقه رو نیاز داریم»): confirmation ladder 15m←5m (was 3m), monitor hierarchy 15m→5m; rest unchanged (1h←15m/→15m, 4h←1h/→15m, 1d←4h/→1h). 3m stays in the venue TF_MAP for future use. √-time ATR scaling auto-adapts (n=√3 for 15m-on-5m).
3. MONEY-MANAGEMENT REFINE (his «روی محاسبات و لوریج رضایت ندارم»): (a) round-trip fee+slippage (0.18%) now INSIDE effective risk per unit → true loss at stop ≈ planned risk (mm exposes cost_pct + eff_risk_pct); (b) wide-stop volatility penalty: sl>10% → risk×0.60, >18% → ×0.35, >30% → unsizeable (None); (c) rr_tp1 < 1.0 → leverage capped at 2×; (d) existing guards kept (quality leverage caps, liquidation ≥2.5× invalidation, margin caps). P1 remains: journal-based daily-loss brake.

## 09-20 (round 7) — TIME-AXIS LAW IMPLEMENTED + PROFESSIONAL AUDIT TRIAGED (Viva verbatim + 2 audit files)
HIS VERBATIM (this round): «قیمت مثلا کلی از ابزار گذشته اما ابزار لانگ و شورت هنوز روی محور تاریخ و زمان حرکت میکنه … در زمان تیپیها و چارتهای لایو اجازه داشته باشن این حرکت قیمت رو در تایمفریمهای بالاتر نشان بدهند و توضیح بده در یکی دو خط … اگر ۱۵ دقیقه حتی ۴۰ کندلهام بیرون رفته باشه از ابزار با تایمفریم ۱ ساعته کلا هنوز ۱۰ تا کندله که روی ابزار مشخص باشه نقاط ورود و تیپی و یا استاپ کجا بوده» + «کیفیت خروج اضطراری برای حفظ سود رو دقیق بررسی نکردم .. اونو بعد میگم».
1. TOOL NEVER SLIDES ON THE TIME AXIS (root cause fixed): `enrich_render` now stamps `tool_anchor_ts` ONCE (55-bar window origin at alert time) and never re-stamps it; the position tool starts at the REAL fill candle (`tool_entry_ts` from `entry_filled_at`, fallback confirmed_at) — previously `tool_start = max(0, count-20)` re-anchored to «the last candle» on every render, which is exactly the sliding he saw. Zone boxes and range boxes carry `ts0` (origin timestamp) and the renderer anchors by `pd.searchsorted(frame.index, ts)` on every frame.
2. LIFECYCLE TF STEP-UP — CLARIFIED BY HIM SAME DAY («اون ۴۰ کندل رو بعنوان مثال گفتم .. اگر تعداد کندل‌ها به هر تعدادی رسید که از ابزار خارج شد، با یک تایم بالاتر …؛ تا وقتی قیمت داخل ابزار لانگ/شورت هست در همان تایم تریگر»): NO magic count. `_tool_escape()` measures how many CLOSED candles left the TOOL REGION — past its right edge (`tool_entry_ts + 42 trigger bars`, the same forward margin the confirmed chart paints) or outside its PRICE BAND (above the top pill for a long / below it for a short, or through the stop). 0 escaped = whichever messages have a LIVE chart stay on the trigger TF (analysis + updates before/around confirmation included, as long as price is inside the tool); ≥1 escaped = ONE step up (`_pick_view_tf`: 15m→1h, 1h→4h, 4h→1d …, capped so the tool origin still fits ≤110 bars). If no frame is passed, the clock alone decides (never stalls). Slopes/break-bars rescale by `chart_tf_scale` (15m→1h = 0.25) so angles stay true; the tool keeps its time origin. ALERT + CONFIRMATION charts stay pinned to the trigger TF (09-14 «چارت ۱ ساعته میذاری پوزیشن رو ۱۵ دقیقه؟!» remains law there) — only TP hits, live updates and final results may step up, exactly as he ruled.
3. ONE/TWO-LINE PERSIAN NOTE in the message (Persian digits): «🕒 پس از خروج ۶۵ کندل ۱۵ دقیقه از ابزار، این پوزیشن در تایم فریم ۱ ساعته نمایش داده شده است.» + «ابزار روی محور زمان جابهجا نشده؛ ورود، استاپ و TPها سر جای اولاند …» — never painted on the chart (chart Persian stays banned).
4. VENUE FALLBACK: if Ourbit cannot serve the higher frame, the render falls back to the trigger TF with NO note (honest degradation, no stall) — mirrors the confirmation-ladder no-stall law.
5. REVERSAL-THRESHOLD HONESTY (audit finding, fixed): `SMART_EXIT_RED` 3→2 and `SMART_EXIT_ORANGE` 2→1 so constants/docstring/tests now match his ruling + runtime (repository monitor has always closed at score ≥2, warned at 1). New regression tests pin BOTH sides: 2 signs → RED/close, 1 sign → ORANGE/warn (long + short mirrors).
6. AUDIT FILES TRIAGE (`گزارش_بررسی_موتورهای_پیشرفته` + `بررسی_snapshot_جدید`): no conflict with standing laws — findings mapped to kartabel. DONE: CI `pytest` install (P1). P1/P2 REMAINING (not blocking live): backtest profile registry/Live-parity (P0 for BACKTEST trust only — our live path is unaffected, and no risk decision rests on backtest numbers), backtest replay of the real confirm_tf, structured logging instead of silent `except Exception: pass`, legacy `analysis/structure.py`/`mtf.py` centered-swing quarantine, NumPy/Pandas timestamp deprecations, funnel report per style/setup, shadow mode for TechnoClassic/Viva-TLBreak.
7. HANDOFF OF HIS DEFERRAL: «کیفیت خروج اضطراری برای حفظ سود» review is OURS to prepare — emergency-exit quality evidence pack (per-band sign hit rates, close price vs next-candle price, saved-vs-given-back R) will be produced from the journal so he can judge with data; nothing about the emergency exit changes until his ruling.

## 09-20 (round 8) — «مدیریت ویوا» SPEC v1.0 + 5 CORRECTION CHARTS (Viva)
SOURCE: uploads/سند_فنی_اصلاح_منطق_سیگنال،_خروج_و_مدیریت_سرمایه.md → archived as handoff/specs/VIVA-MANAGEMENT-SPEC-v1.0.md (now source of truth for the VIVA management profile; must stay SEPARATE from «مدیریت سرمایه استاندارد», §14).
A) ALREADY-LAW (doc confirms, nothing to change): touch ≠ entry, confirming close in trade direction (§2.1); internal-entry vs breakout-entry separation with structural stop behind the internal structure and target BEFORE the opposite boundary (§2.2/§3.2); stop = behind last valid swing/base/zone boundary, target distance NEVER derived from stop distance or fixed R:R (§3.3/§11); exits 40/30/30 (§5); after-TP1 reversal management on lower TFs; orange warning must precede the red exit; exit only after a CONFIRMED (closed) reverse pin bar (§6.1) — our RED close already preempts swing breaks, and now a single closed reverse pin on the monitor frame also closes (previously required 2 signs); multi-TF structure (§7) matches our confirm + monitor ladder.
B) IMPLEMENTED THIS ROUND:
1. §4 TF DISTANCE CEILING (his XRP 19%-target chart): 1d 10% · 4h 7% · 1h 5% · 15m 5% (sub-15m inherit 15m until he rules). `cap_final_target()` clamps the FINAL target at confirmation (quality_engine, with `target_cap_note` + `raw_structural_tp2` audit) and `build_ladder(..., trigger_tf=)` clamps the ladder (audit fields `cap_pct/target_capped/raw_final_target`). Five equal segments INSIDE the ceiling — never derived from the stop; art untouched (still five pills, TP4/TP5 INFO).
2. §5 ZERO-WEIGHT PILLS ARE NOT EXITS: advance_ladder stops walking at TP3 when exit weight is exhausted — a candle that also prints TP4/TP5 emits NO receipts (previously they printed as LADDER_COMPLETE followers). His ETHFI chart showed «TP1/TP2/TP3 = 35%» legacy rows next to a 3-TP ladder — old tool, new ones all read 40/30/30.
3. §4 DECISION (his judge role, recorded): the doc's 3%–5% band is a CHOICE range; we clamp at the 5% ceiling. Audit note for him: with equal segments and his TP1R 1.5–2.5R gates, TP2/TP3 land beyond the ceiling on 15m trades (XRP: TP1 1.0% → TP2 3.0% → TP3 5.0% = the ceiling itself) — a "cluster TP1/TTP2/TTP3 inside a few % of each other" alternative is queued as PENDING HIS RULING, not invented.
4. §6.1 FAST WATCH (his 3m example): `fast_watch_tf_for()` (15m→3m, 1h→5m, 1d→15m …) reads the earliest reversal sign on the finer frame and raises the ORANGE warning (with the fast-TF reason line); the RED exit stays on the monitor frame's closed candle.
5. §8 MONEY-MANAGEMENT PROFILE (separate, switchable): `analysis/risk.py::viva_position()` — <5$ → 30$ · 5 to <50$ → 40$ · ≥50$ → 50$, flat 20×, behind `SETTINGS.viva_management_profile` (default OFF; standard engine untouched while OFF). At 20× the liquidation distance is ≈5%, so a wider stop would be liquidated first: the profile REPORTS `liq_warning_fa` instead of silently resizing (his table is explicit).
C) NOT DONE ON PURPOSE (needs his word, per §13): the deep-pullback RE-ENTRY flow (§6.2 — a second position after the reverse exit) is a NEW product feature, not a tweak: pending his go. Open ambiguities kept flagged, no new logic invented: «بیس معتبر» definition, pin/engulf/doji algorithms (we use vol+body+wick thresholds), which close validates the «first pin», orange-vs-red messaging wording, pullback-vs-reversal classifier, five-part split interplay, short final target (prior low vs next low), symbols exactly at 5$/50$, zone priority across TFs, gaps.
D) CONFLICT REPORT (his charts + doc vs our RR law): his charts carry R:R 1.59–2.87 while §3.3/§11 forbids R:R-driven targets — no contradiction inside the system (R:R is REPORTED, never a target formula), BUT `rr_ok = rr1 ≥ 1.5 and rr2 ≥ 2.2` is an ENTRY GATE (analysis/setups_v7.py) — the doc keeps that kind of floor in the validation list (§9.9/§9.10) yet §3.3 says R:R must not limit the STYLE. Flagged for his ruling: keep the gate as a quality filter or retire it in favour of the TF ceiling alone.
E) CHART DIAGNOSES FROM HIS 5 IMAGES (own triage, and fixes where the fault was ours):
1. XRPUSDT (K897568): 15m SHORT, TP1 1.329 (1.65R) but TP5 1.119 = 19% away → §4 ceiling now clamps to 1.3119; measured-move box no longer painted into the red risk zone.
2. ASTERUSDT (K804880): same 19%-spread issue; three stacked «TRENDLINE» labels → render_kit now de-duplicates near-identical lines (same side within 0.35×ATR) and caps each side at 2 parents + 1 child.
3. AAVEUSDT (K367026): same; dot-dash projection of the rising channel into the trade zone removed with the measured-move gate on confirmed charts.
4. RENDERUSDT (K537184): same; the rising-channel upper line no longer paints over the stop zone.
5. ETHFIUSDT (K247492): LADDER v2 legacy (TP1/TP2/TP3 = 35% rows) while the caption says CLOSED with a live chart — legacy ladder rows (version < 2) behave as designed and close out; the chart still renders live per the 09-20 time-axis law (his ruling). TP1 0.7633 vs entry 0.7367 = -6.2% for a SHORT (TP1 above entry) → that row predates the SHORT structural-target sign fix; new rows are validated by DEGENERATE_GEOMETRY + counter-trend gate. Trailing SL above entry on a short = the LADDER-v2 post-TP1 BE/trail path, superseded by ladder v3 (net BE + protection floors) — no new action.
6. SUIUSDT (his earlier chart): 1D SHORT, range 0.7153–0.7365 drawn flat while price is live at ~0.713 → the range overlay no longer re-anchors to «the last candle» (ts0 anchoring, 09-20) and stale-range-as-live overlay remains on the P1 list (draw only while price is inside, else label as broken history).

## 09-20 (round 9) — حکم‌های اجرایی: مدیریت ویوا روشن + بازنویسی دکترین TP + ورود مجدد + لِین ورود داخلی
HIS VERBATIM (this round): «بله مدیریت سرمایه جدید ویوا اعمال بشه» · «هیچ ارتباطی بین اندازه فاصله قیمت تا استاپ یا تارگت‌ها قرار نده … من نمی‌خوام فرمول ریسک به ریوارد داشته باشم … اصلا اهمیت نداره» · «تی‌پی‌ها رو منطقی نسبت به تایم فریم انتخاب کن … در پوزیشن صعودی تا سقف بعدی آن تایم تریگر یا در شورت تا کف قبل، و نواحی مهم در همان تایم و در تایم‌های بالاتر را در نظر بگیر» · «چارت‌ها هم بررسی دقیق کن» · «اگر نفهمیدی بگو بیشتر توضیح بدم؛ با برداشت خودت چیزی رو تغییر نده».

1. «مدیریت ویوا» فعال شد: `SETTINGS.viva_management_profile = True` (env `VIVA_MANAGEMENT_PROFILE`, تا اطلاع ثانوی). جدول ثابت: قیمت <۵$ → ۳۰$ مارجین · ۵ تا <۵۰$ → ۴۰$ · ≥۵۰$ → ۵۰$ — همه با اهرم ۲۰×. `calculate_position` وقتی پرچم روشن است از این جدول سایز می‌دهد (`profile="VIVA"`)، و با خاموش‌کردن پرچم، موتور استاندارد دست‌نخورده برمی‌گردد. دو پروفایل هرگز با هم مخلوط نمی‌شوند (هر دو در `handoff/specs/CAPITAL-MANAGEMENT-PROFILES-v1.0.md` با نام دقیق مستند شده‌اند).
2. گیت R:R (rr1≥1.5 و rr2≥2.2) به‌طور کامل بازنشسته شد: R:R حالا فقط «گزارش» است (`rr_readout`) و هیچ ورودی‌ای را رد نمی‌کند. صحت هندسه به زبان مطلق بازنویسی شد: کل مسیر هدف < ~۰٫۶×ATR (یا ۰٫۳٪ قیمت) = ابزار بی‌معنی، و استاپ > ۳ برابر سقف فاصلهٔ همان تایم‌فریم = بی‌معنی (مورد SUI روزانه).
3. بازنویسی اهداف بر پایهٔ ساختارِ تایم تریگر + تایم‌های بالاتر: `_structural_targets` اولین سطح معنادارِ فراتر از ورود را TP1 و سطح بعدی را هدف نهایی می‌گیرد (فیب/پیوت‌های همان تایم + نواحی مهم تایم بالاتر به‌عنوان extra_df)؛ هیچ‌جای فرمول به فاصلهٔ استاپ وابسته نیست. اگر سطحی نبود، فال‌بک = سهم درصدی از سقف همان تایم (نه مضربی از استاپ).
4. سقف فاصله (بند ۴ سند): **روزانه ۱۰٪ · ۴ساعته ۵–۷٪ · ۱ساعته و ۱۵دقیقه ۳–۵٪** — روی هدف نهایی اعمال می‌شود.
5. رفع باگ گپ بزرگ TP1→TP2 (چارت خودش): فاصلهٔ TP1 تا پیل آخر به‌صورت **یکنواخت** بین ۵ پیل تقسیم می‌شود و هیچ گپی از ۱٫۳ برابر گام پنج‌قسمتی پهن‌تر نمی‌شود؛ اگر TP1 ساختاری نزدیک ورود باشد، چهار پیل بعدی یکنواخت فشرده می‌شوند (نه یک جهش بزرگ). پیل پنجم = همان سقف/کف ساختاریِ کلمپ‌شده. خروج‌ها همان ۴۰/۳۰/۳۰ روی TP1..TP3.
6. ورود مجدد پس از TP1: بسته‌شدن **اولین پین‌بار معکوس در تایم سریع** (۱۵m←۵m/۳m) در رنج TP1→TP2 = خروج فوری باقی‌مانده + هشدار قرمز؛ سود TP1 قفل می‌ماند (`reentry_armed`)، و اگر حرکت فقط پول‌بک بود، روی همان پول‌بک یک **سیگنال ورود مجدد** با استاپ پشت سوینگ پول‌بک و اهداف باقی‌ماندهٔ نردبان صادر می‌شود (`reentry_setup` + `REENTRY_SIGNAL` + پیام 🔁 متصل به رسید TP1).
7. لِین ورود داخلی (بند ۲٫۲ سند، حالا فعال): داخل کانال/رنج جانبی، لانگ فقط از کف با تأیید کندل بسته‌شده، استاپ پشت ضلع کانال با بافر، اهداف **زیر سقف کانال**؛ شورت آینهٔ آن (از سقف، استاپ بالای کانال، اهداف بالای کف). این ورودها `viva_entry_type="INTERNAL"` می‌گیرند و از گیت containment شکست معاف‌اند.
8. گیت containment (round 9، ادامه): «قیمت هنوز داخل وج/کانال/مثلث ولی تأیید شده» = اشتباه → کلوزِ تأیید باید بیرون ضلع مربوطه باشد (`INSIDE_PATTERN_NO_BREAK`)؛ پول‌بک سطحی (شدو داخل، کلوز بیرون) منتظر شکست تازه نمی‌ماند، اما برگشت عمیق به داخل ناحیه `deep_pullback` را ست می‌کند و یادداشت فارسی آن روی پیام می‌آید.

## 09-20 (round 10) — «چرا دوباره تی‌پی‌ها این‌جوریه؟» — دکترین مسیر هدف + پاک‌سازی چارت
HIS VERBATIM (this round, 6 chart photos): «در داخل تریدینگ رنج یا کانال: ورود از کف بعد از تایید الگوهای کندلی، استاپ پشت کانال و بافر از آخرین سویینگ طبق عکس چارت و تی‌پی فاصله تا سقف کانال یا تریدینگ رنج» · «خارج از الگوها پس از بریک هم اگر در تایم سقف و کف معتبری داشتیم فاصله نقطه ورود تا آن‌جا به ۵ قسمت اما خروج در تی‌پی ۱ تا ۳» · «اگر کف و سقف معتبر نبود در آن تایم یا تایم بالاتر، طبق درصدهای اعلان‌شده مثلا در ۱۵ دقیقه ۳ تا ۵ درصد قیمت در سمت هدف مشخص و از نقطه ورود تا آن‌جا به ۵ قسمت تقسیم اما در ۳ تای اول خارج میشیم» · «تاساعت ۲۳:۰۴ چند پیام تایید اومده که کاملا غلط است … سریع درستش کن» · «من گفتم وسط الگو پوزیشن تایید بشه: در سقف با ریجکت و دیدن الگوهای کندلی شورت و در کف با دیدن الگوهای کندلی لانگ؛ هدف در شورت کف الگو و در صعودی زیر سقف الگو» · «موتور شناسایی بهترین ترندها و الگوها داره گیج میزنه … ترندهای بی‌معنی میکشه … ترندهای خوبی که باید رسم می‌شد شناسایی نشده».
1. مسیر هدف = یک **فاصله قیمت** (نه نسبت R:R): اول ضلع مقابل الگو (ورود داخلی)، بعد سقف/کف معتبر تایم تریگر یا تایم بالاتر (سطحی که دست‌کم به اندازهٔ کفِ نُرم همان تایم دور باشد: ۱۵m/۱h ۳٪ · ۴h ۵٪)، وگرنه نُرم درصدی همان تایم (۱۵m/۱h ۵٪ · ۴h ۷٪ · ۱d ۱۰٪). این مسیر به **۵ قسمت مساوی** تقسیم می‌شود و خروج‌ها روی TP1..TP3 (۴۰/۳۰/۳۰) یعنی ۲۰٪/۴۰٪/۶۰٪ مسیر است — همیشه پیش از رسیدن به سطح.
2. TP1 دیگر روی سطح ساختاری نزدیک «قفل» نمی‌شود: مثلاً BNB شورت با سطح ۰٫۹٪ دور، لدر ۰٫۱۸٪/۰٫۳۵٪/۰٫۵۳٪ می‌ساخت که همان چارت مردودش بود؛ حالا TP1=۱٪، TP2=۲٪، TP3=۳٪ (مسیر ۵٪ ۱۵ دقیقه). «اسنپ» به سطح ساختاری فقط زمانی که آن سطح در ±۲۰٪ گام پنج‌قسمتی باشد.
3. R:R به‌طور کامل از محصول حذف شد: از پنل چارت، از پیام تأیید، از یادداشت AI و از راهنمای آموزشی (چارت‌های خودش R:R منفی/کهنه نشان می‌دادند: −۰٫۱۳/۰٫۳۸).
4. ورود داخلی (کانال/رنج): ورود فقط از لبه (کف برای لانگ، سقف با ریجکت برای شورت) با تأیید کندل بسته‌شده؛ استاپ = عقب‌تر از (ضلع کانال، آخرین سویینگ سازندهٔ کف/سقف) + بافر؛ هدف = ضلع مقابل؛ TP1 = یک‌پنجم مسیر تا ضلع مقابل، خروج‌ها در ۶۰٪ مسیر ⇒ همیشه زیر/بالای ضلع مقابل.
5. گیت containment برای **همهٔ** الگوهای دوخطی فعال شد (نه فقط وج/کانال/مثلث): BROADENING/MEGAPHONE و باقی انواع؛ چارت WLD شورت داخل Broadening تأیید شده بود و از همین شکاف رد شده بود.
6. پاک‌سازی ترندها: امتیاز خط اعتباردهی حالا جریمهٔ فاصله دارد (خطی که لبهٔ راستش چند ATR از قیمت «در هوا» مانده، خط اصلی نمی‌شود)، و هر خطی که با جهت معامله تناقض دارد کشیده نمی‌شود: در شورت، خط نزولیِ سقف جای خط صعودی را می‌گیرد و خط حمایتیِ صعودیِ رهاشده (قیمت ۲ ATR زیرش) حذف می‌شود (مورد BNB: «این ترند قرمز لنگ در هوا چه اژه؟»)؛ الگویی که یک ضلعش حذف شود به TRENDLINE ساده تنزل می‌کند، نه چارت شلوغ.
7. در انتظار حکم (پرسیده شد، بدون برداشت خودسرانه): (الف) وقتی سطح معتبر نیست، مسیر = ۵٪ (سقف نُرم) یا ۳٪ (کف نُرم)؟ (ب) استاپ پوزیشن‌های شکست: همان فلور فعلی (حداقل ۱٫۲٪ روزانه) یا بافر کوچک ۰٫۲۵–۰٫۳۵ ATR پشت آخرین سویینگ؟ (ج) TP1 = یک‌پنجم مسیر یا اولین سطح ساختاری معتبر؟

## 09-20 (round 11) — پاسخ سه پرسش: بدون ATR، بافر پشت آخرین سویینگ، مسیرِ سطح/باند روی همهٔ ستاپ‌ها
HIS VERBATIM: «هم سقف و هم کف ۳ تا ۵ درصد بسته با موقعیت پوزیشن و سقف و کف قبلی» · «بدون atr» · «پشت آخرین سویینگ با بافر» · «اگر سطح معتبر در سقف یا کف وجود داشت همان فاصله به ۵ قسمت تقسیم و ۴۰ درصد در تی‌پی۱ و دو تا ۳۰ درصد تا ۲ و ۳ خالی بشه ... البته خروج اضطراری طبق همون قانونی که گفتم» · «ضمنا همه این تغییرات و اصلاحات و مدیریت سرمایه و .. روی همه ستاپها».
1. **استاپ بدون ATR:** `structural_buffer()` = ۵ تیک صرافی یا ۰٫۱۰٪ قیمت (به‌همراه ۲ برابر اسپرد) — تمام ترم‌های ATR (atr_buffer، volatility_floor) و فلورهای درصدی از فرمول ابطال حذف شدند. لنگر = **آخرین سوینگ** (آخرین پیوت مقابل با بزرگ‌ترین ایندکس)، نه دورترین پیوت؛ اگر پیوتی نبود، لبهٔ POI. نتیجه روی داده زنده: BNB استاپ از ۲٫۳۲٪ به **۰٫۵۵٪**، XLM ۱٫۰۰٪، DASH ۱٫۴۸٪ (WLD ۳٫۵۹٪ چون آخرین سقف سوینگ واقعاً دور است).
2. **مسیر هدف (سه‌پله‌ای):** (الف) سطح معتبر (داخل باند همان تایم، یا تایم بالاتر) → همان فاصله؛ اگر از سقف باند دورتر بود → سقف باند؛ اگر نزدیک‌تر از کف باند بود، سطح معتبر نیست (ساختار بعدی است). (ب) بدون سطح → فاصله تا **سقف/کف قبلی**، کلمپ‌شده در باند ۳–۵٪ (۴h: ۵–۷٪ · ۱d: ۵–۱۰٪) — یعنی موقعیت قیمت داخل باند تصمیم می‌گیرد. (ج) بدون هیچ مرجعی → میانهٔ باند (۴٪ در ۱۵m). تقسیم به ۵ قسمت مساوی، TP1 = ۱/۵ مسیر، خروج ۴۰/۳۰/۳۰ = ۲۰/۴۰/۶۰٪ مسیر؛ **خروج اضطراری دست‌نخورده** (۲ نشانه یا پین‌بار بستهٔ معکوس).
3. **ضلع الگو (ورود داخلی):** مسیر = فاصلهٔ ورود تا ضلع مقابل و همین به ۵ قسمت؛ خروج‌ها زیر/بالای ضلع مقابل.
4. **روی همهٔ ستاپ‌ها:** یک قیف مشترک اعمال شد — `_structural_targets` (ALBROX/TLBREAK/TECHCLASSIC/PINWALLQ/PINVAL در setups_v7)، `pattern_engine` (TECHCLASSIC: بافر بدون ATR، حذف گیت R:R و سقف ATR، TP1 = ۱/۵ مسیر)، `setups_experimental` (VIVA-TLBREAK: بافر بدون ATR + مسیر ساختاری، PINVAL: حذف گیت rr≥۱٫۳/۲٫۰ و هدف‌گیری دوکترینی، ALBROX: استاپ بیس + بافر بدون ATR)، `quality_engine` (بافر لِین داخلی بدون ATR، و پس از کلمپ سقف، TP1 دوباره ۱/۵ مسیر کلمپ‌شده). مدیریت سرمایه «مدیریت ویوا» هم از قبل روی همهٔ ستاپ‌ها یکسان است (یک `build_money_management`).
5. تست: `tests/test_round11_doctrine.py` (۷ تست) + کل مجموعه ۱۸۸ پاس / ۱ اسکیپ.

## 09-21 (round 12) — قانون «جهت شکست» روی همهٔ ستاپ‌ها + استاپ صادقانه + سقف افق استاپ
HIS VERBATIM: «چرا بعد از شکست ترند رو به بالا پوزیشن شورت اعلان میشه توی برخی ستاپها؟» · «چرا گاهی در برخی ستاپها بعد از شکست الگوها یا ترند به سمت پایین و کلوز بعدش به جای سیگنال شورت لانگ اعلام میکنه؟» · «حدود ۱۲ درصد استاپ؟؟» · «جای استاپ ها هم امیدوارم فهمیده باشی چی بذاری» · «مطمئنم هنوز باگ داریم در برخی منطق ها یا ستاپها».
1. **گیت «جهت شکست» (BREAK_SIDE_MISMATCH) در لایهٔ تأیید — روی همهٔ ستاپ‌ها:** هر خط اعتبارسنجی‌شده با دو نقطهٔ لنگر (زمان+قیمت) روی کاندید ذخیره می‌شود (`render_line_watch.p0/p1`) و در لحظهٔ تأیید روی همان کندل تصویر می‌شود. اگر کلوزِ تأیید، خط حمایتی را به پایین بشکند در حالی که سناریو لانگ است، یا خط مقاومتی را به بالا بشکند در حالی که سناریو شورت است → تأیید **صادر نمی‌شود** (با پیام فارسی). خطوطی که بیش از ۳×ATR از قیمت دورند (تاریخ مرده) هیچ‌چیز را وتو نمی‌کنند. ورودهای داخلی/فِید طبق طراحی معاف‌اند. همین قانون برای الگوهای دوخطی هم با کد اختصاصی (کلوز بیرون ضلع مخالف) اعمال شد.
2. **استاپ صادقانه (پشت آخرین سویینگ، نه دورترین پیوت):**
   - PINVAL: لنگر = **آخرین** سویینگ بالای ورود (شورت) یا پایین ورود (لانگ) — قبلاً بیشینهٔ ۶ پیوت آخر گرفته می‌شد که همان استاپ‌های ۱۰–۱۴٪ (SEI/LIT) را می‌ساخت؛ اگر پیوتی سمت درست نبود، بافر از خودِ ورود.
   - TLBREAK: استاپ = لنگر ساختاری خود الگو (آخرین نقطهٔ ضلع مقابل) + بافر؛ `min/max` که استاپ **دورترِ** دو منبع را نگه می‌داشت حذف شد.
3. **سقف افق استاپ (هیچ ۱۲ درصدی دیگر):** فاصلهٔ استاپ از ورود باید داخل همان افق فاصلهٔ تی‌پی‌ها باشد — ۱۵m/۱h ۵٪ · ۴h ۷٪ · ۱d ۱۰٪. اگر استاپ ساختاری دورتر بود، آن سناریو **منتشر نمی‌شود** (نه به‌عنوان اعلان و نه تأیید؛ کد `DEGENERATE_GEOMETRY` با پیام فارسی که خودِ قاعده را توضیح می‌دهد).
4. تست: `tests/test_round12_break_side.py` (۸ تست: شورت بعد از شکست صعودی رد می‌شود، لانگ بعد از شکست نزولی رد می‌شود، خط مرده وتو نمی‌کند، استاپ PINVAL/TLBREAK، سقف افق) — کل مجموعه ۱۹۵ پاس / ۱ اسکیپ.
5. پرسش‌های باقی‌مانده برای حکم: (الف) سناریوهایی که استاپشان از افق بزرگ‌تر است، کاملاً حذف شوند یا به‌صورت «تحلیل/هشدار بدون ورود» منتشر شوند؟ (ب) عدد بافر ۰٫۱۰٪ تأیید است؟

### ۰۹-۲۱ — پاس دوم دورهٔ ۱۲ (پس از عیب‌یابی خودم: «هنوز باگ داریم در برخی منطق ها یا ستاپها»)
گیت‌های پاس اول داخل *یک* سازنده بودند؛ هر ستاپی که کاندید خودش را می‌ساخت (تکنوکلاسیک/PINVAL…) می‌توانست بعد از آن گیت، استاپ و تی‌پی‌ها را **بازنویسی** کند. نتیجهٔ زنده: DASH ۱۵m شورت با استاپ ۲۴٪ و تارگت ۳۴٪، و DASH لانگ با استاپ **بالای** ورود.
1. **تور سختِ هندسه (یک قیف برای همهٔ کانال‌ها)** — `setups_v7.sanity_reject` روی خروجی هر دیتکتور اجرا می‌شود:
   - استاپ باید در سمت درست همان ورودی باشد که پیام نشان می‌دهد (لانگ: زیر ورود · شورت: بالای ورود) → وگرنه `STOP_WRONG_SIDE`.
   - فاصلهٔ استاپ باید داخل افق همان تایم‌فریم باشد (۱۵m/۱h ۵٪ · ۴h ۷٪ · ۱d ۱۰٪) → وگرنه `STOP_HORIZON`.
   - هر دو تی‌پی باید سمت درست و داخل همان افق باشند → `TARGET_WRONG_SIDE` / `TARGET_HORIZON`.
   - رد شدن = **منتشر نمی‌شود** (لاگ `🧱 SANITY_REJECT`). در تأیید هم دوباره چک می‌شود (`STOP_WRONG_SIDE` در پیام فارسی، و قاعدهٔ قبلی استاپ دور).
2. **ورودیِ صادقانه:** هر کاندید باید `planned_entry` را همان قیمتی بگذارد که هندسهٔ خودش (استاپ/تارگت) از آن حساب شده؛ تکنوکلاسیک قبلاً ورود را روی وسط زون نگه می‌داشت ولی استاپ را روی قیمت زنده می‌ساخت → استاپ «سمت اشتباه».
3. **تارگت پروجکشن (Measured Move) داخل باند:** حرکت اندازه‌گیری‌شده یک *سطح زنده* نیست؛ حالا با `clamp_path_to_band` داخل باند همان تایم‌فریم بریده می‌شود (۰٫۵٪ → کف باند، ۳۴٪ → سقف باند) و بعد به ۵ قسمت تقسیم می‌شود. برای فِید، دیوار مقابل الگو مسیر است (فقط سقف افق می‌تواند کوتاهش کند).
4. **پروب زندهٔ ۲۰ نماد × ۴ استایل:** بیشترین استاپ ۴٫۹٪ (۱۵m/۱h) · صفر تخلف سمت/افق؛ دو کاندید (ENA ۱h ۹٫۴٪ و ATOM ۱h ۵٫۹٪) توسط تور سخت حذف شدند. DASH در همان زمان عکس‌هایش: استاپ ۱٫۱۴٪ (لانگ ۱۵m) و ۴٫۹۴٪ (شورت ۴h) — مسیر هر دو داخل باند.
5. تست: `tests/test_round12_sanity.py` (۱۲ تست) → کل مجموعه ۲۰۷ پاس / ۱ اسکیپ.
6. نکتهٔ باز برای حکم: روی یک نماد ممکن است ۱۵m یک کانال نزولی را رو به بالا و ۴h یک کانال صعودی را رو به پایین بشکند (هر دو درست) → آیا ترجیح می‌دهید فقط سمت تایم‌فریم بالاتر منتشر شود؟

### ۰۹-۲۱ — حادثهٔ قطع شناسایی‌ها (رکورد عملیاتی، قانون «سکوت ممنوع»)
- علت ریشه‌ای: یک اتصال از خود برنامه در حالت **idle in transaction** قفل ACCESS SHARE روی `signal_candidates`/`signals` را ۲۵ دقیقه نگه داشته بود؛ مایگریشن‌های بوت (`ALTER TABLE … ADD COLUMN IF NOT EXISTS`) پشت آن در صف ماندند و با `statement_timeout` دو دقیقه‌ای دیتابیس لغو شدند → ترد اسکنر با `os._exit(1)` کشته شد → کانتینر در حلقه ری‌استارت افتاد؛ داشبورد سالم بود و فقط **سکوت** دیده می‌شد.
- درس‌ها (قوانین جدید، برای همیشه): ۱) مایگریشن‌ها **check-first** هستند؛ اگر ستون هست، حتی درخواست قفل انحصاری هم زده نمی‌شود. ۲) هر DDL با `SET LOCAL lock_timeout` (۱۰ ثانیه)، ۳ تلاش با بک‌آف و **هرگز کشنده**. ۳) هر اتصال با `idle_in_transaction_session_timeout=120s` + `application_name` → هیچ ترنزکشن رهاشده‌ای نمی‌تواند قفل را ساعت‌ها نگه دارد. ۴) بوتِ اسکنر: مراحل اسکیمـا ۳ بار تلاش و در صورت شکست فقط لاگ + ادامه. ۵) `_run_scanner` سوپروایزر دارد: ری‌استارت با بک‌آف؛ فقط ۵ شکست پشت‌سرهم در کمتر از ۶۰ ثانیه کانتینر را پایین می‌آورد. ۶) **قلب تپنده:** هر ۵ دقیقه یک هارتبیت در لاگ و در `bot_kv` (کلید `scanner_heartbeat`) نوشته می‌شود تا زنده‌بودن اسکنر از بیرون قابل اثبات باشد.
- تأیید پس از رفع: کشتن نشست‌های قفل‌شده → بوت سالم (`v7 database migrations applied safely`) → اسکن کامل: `detected=35 new=16 errors=0`؛ تور سخت دورهٔ ۱۲ هم در تولید فعال است (`🧱 SANITY_REJECT STOP_HORIZON` برای ALGO/ATOM ۱h).
- تست: `tests/test_round12_outage_guard.py` (۸ تست) → کل مجموعه ۲۱۵ پاس / ۱ اسکیپ.

### ۰۹-۲۱ — قانون «ساعت‌ها» و «کندل در جریان» (پاسخ به: «حدود ۴۰ دقیقه اختلاف … من دارم گذشته مارکت رو می‌بینم»)
**ریشهٔ دقیق مورد GRAM 1h (K952125):** کندل مبدا ساعت ۲۲:۰۰ بسته شد؛ ربات در آن فاصله در حلقهٔ ری‌استارت خرابی بود، پس اسکن ۲۲:۰۰ انجام نشد و اولین اسکن بعد از ریکاوری، همان پین‌بار را ۲۲:۳۹ شناسایی و منتشر کرد → **۳۹ دقیقه تأخیر واقعی**. روی این، چارت هم فقط کندل‌های **بسته‌شده** را می‌کشید (قانون ضدِ ری‌پینت)، پس تصویر تا یک کندل کامل از چارت زندهٔ صرافی عقب‌تر بود؛ و پیام هیچ ساعتی نداشت که این تأخیر را لو بدهد.
**سه قانون جدید (روی همهٔ ستاپها و همهٔ پیام‌ها):**
1. **بلوک ساعت‌ها در هر هشدار:** «کندل مبدا (تایم‌فریم) — بسته‌شده در HH:MM:SS ایران»، «شناسایی»، «ارسال به تلگرام»، «فاصلهٔ بسته‌شدن کندل تا شناسایی» — در هشدار مفصل، پیام مختصر، آپدیت‌ها و پیام Confirmed.
2. **گاردِ بازارِ گذشته:** تأخیر بیش از ۱۵ دقیقه با ⚠️ در متن اعلام می‌شود؛ تأخیر بیش از **دو کندلِ همان تایم‌فریم** یعنی هشدار دیگر «ورود» نیست (فقط یادداشت تحلیلی، لاگ `⏳ STALE_DETECTION`).
3. **کندل در جریان روی چارت:** کندل تشکیل‌نشدهٔ همان تایم‌فریم به‌صورت کندل خط‌چین با برچسب `FORMING` کشیده می‌شود و پیل `LIVE` قیمت زنده + ساعت (UTC، هم‌مقیاس با محور) را نشان می‌دهد → تصویر، بازارِ همین دقیقه است، نه گذشته.
- تست: `tests/test_round12_clock_and_live.py` (۱۱ تست) → کل مجموعه ۲۲۶ پاس / ۱ اسکیپ. نمونهٔ چارت: `/home/user/proof_round12_clock.png`.

### ۰۹-۲۱ — حکم سوم دورهٔ ۱۲: سقف استاپ ۱٫۲۵٪ + تلورانس ۲۰٪ تی‌پی + بستن سناریوی «منتظر»
**حکم‌های او (عیناً):** «استاپ اصلا ساختاری اگر فاصله داشت حذف نشه و تا ۱.۲۵ قیمت نماد محاسبه بشه» · «اگر در هر تایم فریم سویینگ آخر خیلی فاصله داشت .. استاپ نهایتا ۱.۲۵ درصد قیمت نماد محاسبه شود» · «اون ۳ تا ۵ درصد رو برای ۱ ساعته و ۱۵ دقیقه … ۴ تا ۷ درصد رو برای ۴ ساعته و ۷ تا ۱۰ درصد روزانه هم با تلورانس ۲۰ درصد بالایی پایینی سقف و کف های اعلام شده برای تی پی ها اوکیه» · «۵۱ آپدیت از ۱۸ دلار رفته ۲۸ دلار ربات هنوز منتظر مونده؟؟ اینم باگه».
1. **سقف استاپ = ۱٫۲۵٪ قیمت نماد، در همهٔ تایم‌فریم‌ها:** اگر آخرین سویینگ دورتر باشد، استاپ **بریده** می‌شود (نه اینکه سناریو حذف شود). در همهٔ خطوط اعمال شد: سازندهٔ عمومی، TECHCLASSIC/TLBREAK، PINVAL/ALBROX، و در لحظهٔ تأیید. یادداشت فارسی «استاپ ساختاری دورتر بود؛ روی سقف ۱٫۲۵٪ تنظیم شد» در پیام می‌آید و `stop_clamped` در متادیتا ثبت می‌شود.
2. **تلورانس ۲۰٪ سقف/کف تی‌پی:** باندهای اعلامی (۳–۵٪ · ۵–۷٪ · ۷–۱۰٪) در **محاسبهٔ نردبان دست‌نخورده** می‌مانند؛ فقط مرزهای **پذیرش** در گیت‌ها ±۲۰٪ باز می‌شوند (`tolerant_band_for_tf` / `tolerant_cap_pct`).
3. **دیگر «انتظار بی‌پایان» نداریم:** اگر سناریو تأیید نشده باشد و قیمت بیش از **۲ ATR** در جهت سناریو از ناحیه دور شده باشد → سناریو با کد `OUT_OF_REACH` **بسته** می‌شود (پیام فارسی + پاسخ حکم) و زنجیره ادامه پیدا نمی‌کند. معافیت «شکست سریع» هم محدود شد به ≤ ۱٫۵ ATR (قبلاً بی‌نهایت بود و همان چیزی بود که VVV را ۲ روز «منتظر» نگه داشت).
4. **آپدیت‌های 💓 سقف گرفتند:** حداکثر ۱۲ آپدیت پایان‌کندل در هر زنجیره (قبلاً ۵۱ آپدیت در دو روز).
5. **«⚡ عبور در لحظه» یعنی واقعاً عبور:** فقط اگر کندل بستهٔ قبلی سمت دیگر خط بود یا فاصله ≤ ۲ ATR باشد؛ نه وقتی قیمت روزها بالای خط نشسته است.
6. **اصلاح باگ ساعتِ خودم:** بلوک ساعت‌ها حالا **تاریخ** هم دارد و «شناسایی» = زودترین مهر ثبت‌شده (قبلاً روی زنجیرهٔ دو روزه، تاریخ‌ها نبود و «ارسال» زودتر از «شناسایی» دیده می‌شد).
- پروب زندهٔ ۲۰ نماد: بیشترین استاپ ۱٫۲۵٪ · ۵ مورد بریده‌شده · صفر تخلف (ATOM/CRV/BCH/DASH/BTC که قبلاً حذف می‌شدند، حالا با استاپ سالم منتشر می‌شوند). تست: `tests/test_round12_stop_ceiling.py` (۱۴) → کل ۲۴۰ پاس / ۱ اسکیپ.

### ۰۹-۲۱ — دورهٔ ۱۳: کندل لایو «عادی»، به‌روزرسانی زندهٔ همهٔ تایم‌فریم‌ها، و دروازهٔ پنجرهٔ کندل
**حکم‌های او (عیناً):** «این رو درست کن با خط چین نمی‌خوام» · «خط چین کندل لایو اصلا نه دیده میشه برای تصمیم گیری خوب نیست همون شکل کندل باید عادی باشه» · «آیا در تایم اسکن یا مانیتور کردن ۳ دقیقه تایید یا ۵ دقیقه تایید .. ۱: در چارت یکساعته تغییرات روی کندل لایو تایم‌فریم‌های بالاتر اعمال میشه یا ۲: کندل یکساعته و ۴ ساعته و روزانه هر یک‌ساعته و ۴ ساعت و یک روز یکبار بروز میشه؟؟ اگر جواب گزینه ۲ هست .. کاملا اشتباهه و غلط» · «من هنوز سیگنال روزانه ندیدم که تایید بشه یا واسش آپدیت بیاد ۴ ساعته هم زیاد ندیدم .. حالا دقیق بررسی کن» · «در اون زمان ریستارت بودیم پس مشکلی نیست».
1. **کندل در جریان = کندل عادی:** کندلِ لایو دیگر «شبح خط‌چین/FORMING» نیست؛ به تِیپ اضافه می‌شود و با همان بدنه/سایه/عرض و همان رنگ‌های بقیهٔ کندل‌ها نقاشی می‌شود. پیل «LIVE قیمت + ساعت» سر جایش می‌ماند.
2. **کلید کش چارت قیمتِ لایو را هم دارد:** قبلاً کلید کش فقط تا «تایم‌استمپ آخرین کندل» می‌رفت و کندل لایو یک ساعت/چهار ساعت/روز کامل یک تایم‌استمپ داشت ⇒ تصویر برای طول همان کندل یخ می‌زد و آپدیت‌ها «گذشتهٔ مارکت» می‌فرستادند. حالا هر تغییر قیمت ⇒ رندر تازه.
3. **پاسخ سؤال فنی او:** تحلیل و تأیید **فقط روی کندل بسته** است (قانون خودش: تأیید = کلوز معتبر)؛ ولی مانیتور ۳دقیقه‌ای و تیکر ۵ثانیه‌ای زنده‌اند و کندل لایو هر تایم‌فریم با هر رندر/تیک جابه‌جا می‌شود. یعنی نه «هر یک ساعت یک‌بار».
4. **ریشهٔ «۴ ساعته/روزانه خبری نیست»:** دروازهٔ هزینهٔ ۰۹-۱۷ هر فریم را فقط «۴ دقیقهٔ اول بعد از کلوز کندل خودش» می‌گرفت؛ سهم ۴ساعته ≈ ۶٪ روز و روزانه ≈ ۱٪ روز (۱۶ دقیقه) بود و هر ریستارت داخل همان ۴ دقیقه، کلِ آن کندل را می‌خورد: نه تأیید، نه آپدیت، نه هارت‌بیت. حالا پنجره‌ها چند سایکل ۳دقیقه‌ای را پوشش می‌دهند: ۵m/۳m آزاد · ۱۵m دقیقه ۰–۵ · ۱h دقیقه ۰–۱۱ · ۴h دقیقه ۰–۱۹ · ۱d ساعت ۰۰ و دقیقه ۰–۴۴.
5. **پایداری زندهٔ هر زنجیره مستقل از پنجره:** قیمتِ لحظه‌ای از تیکرِ صرافی (کشِ خودش) برای همهٔ زنجیره‌ها هر سایکل خوانده می‌شود ⇒ ابطال پیش از تأیید، هشدار نزدیکی و قانون «از ناحیه دور شد» برای ۴ساعته و روزانه هم زنده کار می‌کند. فقط **تأیید** منتظر کندل بسته می‌ماند (و در نبود فریم، دیگر کدِ NO_DATA روی زنجیره ثبت نمی‌شود).
6. **قانون گذشته‌بازار برای تأیید هم اجرا می‌شود:** اگر کندلِ تأییدکننده بیش از دو کندلِ تایم تأیید قدمت داشته باشد، ورود صادر نمی‌شود (فقط یادداشت تحلیلی) — همان قانون هشدارِ کهنه، این بار برای کانفرم.
7. **تست:** `tests/test_round13_live_candle.py` (۱۰) → کل ۲۵۱ پاس / ۱ اسکیپ. شاهد تصویری: `proof_round13_live_candle.png` (کندل لایو عادی + LIVE pill).
8. **باگ جانبی که در همین بررسی پیدا و بسته شد:** اسکنِ ورود مجدد (قانون دورهٔ ۹: «سیگنال ورود مجدد روی همان پول‌بک») از روز اول روی **هر سیکل** خطای psycopg2 می‌داد (کاراکتر `%` داخل الگوی LIKE در کوئری پارامتری) و کلِ خط را می‌بست ⇒ **هیچ سیگنال ورود مجددی صادر نشده بود**. الگوها پارامتری شدند و هر ردیف جدا محافظت می‌شود. (تست: `test_reentry_scan_query_parameterises_its_like_patterns`.)

### ۰۹-۲۱ — تأییدِ نهایی بافر (پاسخ او: «بافر اعلامی مورد تایید است»)
- **بافر استاپ = حداکثر «۵ تیک صرافی» یا «۰٫۱۰٪ قیمت نماد»** (به‌علاوهٔ ۲×اسپرد در سطح ابطال) — قفل شد؛ همین عدد در `structural_buffer()` پیاده است و تغییر نمی‌کند.
- **سؤال‌وپاسخ‌های همان پیام (ثبت برای قانون):**
  1. آپدیت‌های ۱ ساعته/۴ ساعته/روزانه (و هیت‌ها) با **چارت لایو و کندل واقعی همان لحظه** می‌آیند؛ کندلِ در جریان هر تایم‌فریم با هر رندر به‌روز می‌شود و کلید کش رندر قیمتِ لایو را هم شامل می‌شود (پیش‌تر تا یک کندل کامل یخ می‌زد ⇒ تصویر «گذشتهٔ بازار»).
  2. **تأیید فقط با کلوز می‌آید:** ۱d ← ۴h · ۴h ← ۱h · ۱h ← ۱۵m · ۱۵m ← ۵m (قانون یک‌کلوز). هیتِ تی‌پی/استاپ/آپدیت‌ها منتظر کلوز نمی‌مانند (تیکر ۵ ثانیه + مانیتور ۳ دقیقه).
  3. **کندلِ تأییدِ کهنه = تحلیل، نه ورود:** اگر کندلِ تأیید بیش از دو کندلِ تایم تأیید قدمت داشته باشد، ورود صادر نمی‌شود و فقط یادداشت تحلیلی می‌آید.
  4. شاهد زنده: دو سیگنال روزانه **ZECUSDT 1d** (تأیید ۰۰:۰۵ UTC، پیام ۲۳۴۴۴) و **INJUSDT 1d** (تأیید ۰۰:۰۳ UTC، پیام ۲۳۴۲۵) چند دقیقه پس از کلوز ۴ساعتهٔ ۰۰:۰۰ منتشر شدند؛ چارت بازسازی‌شدهٔ همان مسیر: `proof_round13_daily_confirm_live.png`.

### ۰۹-۲۱ — دورهٔ ۱۴: سقف استاپ به تفکیک تایم‌فریم + جدا شدن کامل تی‌پی از استاپ
**حکم‌های او (عیناً):** «اون ۱.۲۵ صدم استاپ برای ۱۵ دقیقه است / ۱.۷۵ استاپ برای ۱ ساعته / استاپ ۲ تا ۲.۲۵ قیمت نماد در ۴ ساعته / استاپ ۲.۵ تا ۲.۷۵ قیمت در سویینگ‌های روزانه» · «این در صورتی هست که سویینگ ساختاری در چارت نداشته باشیم؛ اگر هم کف یا سقف داشته باشیم نباید از این اعداد استاپ با بافرش بزرگ‌تر باشه» · «و لطفا ارتباطی بین تی پی و استاپ نذار» · «در روزانه شاید باید تا ۱۵ درصد رو هم در نظر بگیریم … اینم انجام بده تا فردا ببینیم چی بهتره».
1. **سقف استاپ به تفکیک تایم:** ۵m/۳m/۱m و ۱۵m = **۱٫۲۵٪** · ۳۰m = **۱٫۵٪** (انتخاب من) · ۱h = **۱٫۷۵٪** · ۲h = **۲٫۰٪** (انتخاب من) · ۴h = **۲٫۲۵٪** · ۱d = **۲٫۷۵٪** (`MAX_STOP_PCT_BY_TF` + `stop_ceiling_pct(tf)`).
2. **قانون ساختار:** اگر کف/سقف ساختاری (آخرین سویینگ) هست، استاپ پشت همان + بافر (۵ تیک یا ۰٫۱۰٪) می‌ماند **تا وقتی داخل سقفِ همان تایم باشد**؛ اگر دورتر بود روی سقف بریده می‌شود (هیچ سناریویی حذف نمی‌شود). در همهٔ خطوط (سازنده، TECHCLASSIC، PINVAL، TLBREAK، ALBROX، لحظهٔ تأیید) تابع برش با تایم‌فریم صدا زده می‌شود.
3. **تی‌پی ⟂ استاپ:** هیچ تی‌پی از استاپ/ریسک محاسبه نمی‌شود؛ مسیر فقط ساختار/باند همان تایم و تقسیم ۵ قسمتی است. R:R از پیام‌ها و چارت‌ها حذف شد (به‌جایش «درصد فاصله» هر TP). فلورهای حفاظتی هم از «R» به «پلهٔ نردبان» تغییر کرد و گیت `rew ≥ 1.3×risk` در فِید برداشته شد. تست اثباتی: با تغییر استاپ (۹۸→۹۵) تی‌پی‌ها/فلورها عیناً ثابت می‌مانند.
4. **سقف روزانه ۱۵٪** (موقت — «تا فردا ببینیم چه بهتره»): `TARGET_MAX_PCT_BY_TF['1d']=15`، `band_for_tf('1d')=(5,15)`؛ تلورانس ۲۰٪ روی همان (۱۸٪ در گیت‌ها).
5. **تور سخت:** `STOP_HORIZON` حالا با سقف استاپِ همان تایم‌فریم سنجیده می‌شود، نه با باند تی‌پی.
- پروب زندهٔ ۱۵ نماد: ۱۵m → ۱٫۲۵٪ · ۱h → ۱٫۷۵٪ · صفر تخلف. تست: `tests/test_round14_stop_table.py` (۲۰) → کل ۲۷۲ پاس / ۱ اسکیپ.

### ۰۹-۲۱ — دورهٔ ۱۴b: استاپ هرگز روی خودِ ورود نمی‌افتد
- **موردِ زندهٔ پیداشده در لاگِ دیپلوی ۱۴:** `🧱 SANITY_REJECT STOP_WRONG_SIDE • TRXUSDT DAYTRADE TLBREAK SHORT entry=0.34352 sl=0.34352 tp1=0.34077184 tp2=0.3297792 tf=15m`. خطِ استاپ از «اکسترممِ همان کندلِ آخرِ تریگر» آمده بود و آن کندل روی سقفش بسته شده بود ⇒ استاپ = ورود (فاصلهٔ صفر) و تور هندسی کل سناریو را انداخت؛ خلاف قانون «حذف نشه».
- **قانون جدید (در بن‌بستِ مشترکِ `scan_setups`، پیش از سقف‌گیری):** اگر استاپ روی سمتِ غلطِ ورود باشد یا فاصله‌اش از ورود کمتر از یک بافرِ استاندارد باشد، سطح ابطال از **اکستریمِ ساختاریِ ۸ کندلِ آخرِ فریمِ تریگر + بافر** بازسازی می‌شود (فلگ `stop_reanchored`)؛ سپس سقفِ همان تایم‌فریم برش نهایی را می‌دهد. هیچ فریمی نبود ⇒ دست‌نزدن (fail-open) و تصمیمِ نهایی همان تور هندسی می‌ماند.
- **چرا این‌جای حذف:** فلسفهٔ او «استاپِ ساختاری اگر فاصله داشت حذف نشه» است؛ سناریویی که هندسه‌اش با یک سطحِ ساختاری درست می‌شود نباید بی‌صدا از کانال غیب شود.
- **تست:** `tests/test_round14b_stop_anchor.py` (۸ تست: هلپر + بن‌بست، ازجمله بازتولیدِ عینِ TRX) → کل مجموعه ۲۸۰ پاس / ۱ اسکیپ.
- **دیپلوی‌ها:** دورهٔ ۱۴ → `2dd8207` = deploy `2b9baa84-f783-4dcc-8d55-e83295f5c5dc` (SUCCESS) · دورهٔ ۱۴b → `b0fa779` = deploy `7bac97c7-2871-4c8f-94e4-5794af82caa5` (SUCCESS، لاگ: ۰ خطا، ۰ SANITY_REJECT، ۰ خطای ورود مجدد).
