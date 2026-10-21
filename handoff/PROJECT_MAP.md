# PROJECT_MAP.md — smc-scanner2
> نقشهٔ واقعی ریپو (از روی کد، ۲۰۲۶-۰۹-۱۴). `CHAT_CONTEXT.md` داخل ریپو **منسوخ** است.
> ۲۴٬۵۲۶ خط پایتون · ۱۰۰+ فایل

## ورودی‌ها و اجرا
| فایل | خط | مسئولیت | نکته |
|---|---|---|---|
| `main.py` | ۱۱۷۷ | **قلب سیستم.** حلقهٔ اصلی، زمان‌بند، اسکن discovery، مانیتور کاندیداها، انتشار رویدادها | ۳ نخ: اصلی (scheduler) + `_realtime_execution_loop` (هر ۵s) + `_candidate_monitor_loop` (هر ۱۰s) · ۵۰ `except` · ⚠️ F2, F3, F4, F16 |
| `combined_service.py` | — | سرویس Railway: Waitress در نخ اصلی + اسکنر در پس‌زمینه | `Procfile`, `railway.json`, `render.yaml` (قدیمی) |
| `config.py` | ۳۷۱ | همهٔ تنظیمات به‌صورت dataclass + override از env | منبع حقیقتِ فلگ‌ها؛ ⚠️ F6 |
| `dashboard/app.py` | ۳۸۳ | داشبورد Flask | |

## تحلیل (analysis/)
| فایل | خط | مسئولیت | نکته |
|---|---|---|---|
| `setups_v7.py` | ۱۱۳۶ | اسکن ستاپ‌ها، `TIMEFRAME_PROFILES`، `expiry_hours_for`، `enrich_candidate_context`، `candidates[:4]` | منبع حقیقتِ expiry ⚠️ F8 |
| `quality_engine.py` | ۴۳۹ | **`evaluate_confirmation`** (قانون یک‌کلوز، fast-lane، RR، chase) + ۴ موتور GRAND/SWING/DAYTRADE/SCALP + `scan_bundle` | ⚠️ F12, F13, F14 |
| `setups_experimental.py` | ۱۰۱۵ | خانوادهٔ پینبار (PINVAL/PINWALLQ)، ALBROX، polarity gate | ⚠️ expiry جداگانه در خط ۸۶۳ (F8) · `pd.Timestamp.utcnow()` در ۷۹۵ (F18) |
| `pattern_engine.py` | ۹۲۸ | الگوهای کلاسیک ۱h/۴h/۱d (TECHCLASSIC)، `htf_pattern_adjustment`، `send_prebreak_alerts` | ۱۹ `except` |
| `viva_tlbreak.py` | ۶۹۰ | ماشین حالت TLBREAK: `advance_live_state` | ⚠️ فلگ پیش‌فرض خاموش (F6) |
| `viva_tlbreak_state.py` | — | `VivaTLState` (S3_RETEST → S4_REJECTION → S5_MICRO_BOS → S6_CONFIRMED) | |
| `trigger_patterns.py` | ۲۲۲ | `multi_candle_trigger` — بیس چندکندلی به‌عنوان ماشهٔ جایگزین | |
| `zone_polarity.py` | ۴۴۲ | gate جهت/زمینه برای خانوادهٔ پین | |
| `strategies.py` | ۱۳۱۴ | ۱۳ استراتژی قدیمی v5/v6 | ⚠️ `core_v7_setups_enabled = False` → عملاً غیرفعال |
| `indicators.py` | ۱۸۲ | `atr` (ATR **واقعی**)، `candle_displacement` | ⚠️ در برابر `mean(high-low)` در quality_engine (F12) |
| `trade_management.py` | — | `advance_ladder` — نردبان ۵ هدفهٔ TP | مسیر سالمِ رویدادها |
| `mtf.py`, `smc.py`, `rtm.py`, `ict.py`, `structure.py`, `risk.py`, `models.py` | | لایه‌های SMC/RTM/ICT، ساختار، ریسک، `SignalCandidate` | `models.py:81 → expires_at: str = ""` |
| `backtest.py`, `viva_tlbreak_replay.py` | ۳۷۳ | بک‌تست walk-forward و replay | |

## پیام‌ها (bot/)
| فایل | خط | مسئولیت | نکته |
|---|---|---|---|
| `messages_v7.py` | **۲٬۸۵۶** | همهٔ قالب‌های پیام، چارت‌ها، اسلات PRO، زنجیرهٔ KV | بزرگ‌ترین فایل پروژه · ۴۵ `except` · ⚠️ F20 (edu_chat مرده در ۲۷۸۰) |
| `commands.py` | ۱٬۱۲۱ | منوی عمومی، تحلیل فوری، دستورات ادمین | ۲۳ `except` |
| `membership.py` | ۲۷۷ | عضویت/ارجاع/پرداخت (`bot_users`) | |
| `telegram_bot.py` | ۸۱۲ | لایهٔ ارسال (`send_message`, `send_photo`, `delete_message`) | read-back ممکن نیست؛ فقط `bot_kv`/`send_audit` |
| `railway_control.py` | — | کنترل دیپلوی | |

### توابع کلیدی در `messages_v7.py`
| تابع | خط | چه می‌کند |
|---|---|---|
| `_pro_slot_post` | ۱۷۲۳ | **اسلات زندهٔ PRO**: post جدید → حذف قبلی → نوشتن `slot`/`slot_kind`/`pro` در KV. ✅ ترتیب درست است |
| `send_setup_update` | ۱۸۷۲ | آپدیت شماره‌دار؛ dedup با `upd_sig`؛ چارت را خودش می‌گیرد اگر caller نداشت |
| `_setup_chain_get` / `_set` | ۱۶۹۷/۱۷۰۵ | خواندن/نوشتن `setup_chain\|<CODE>` در `bot_kv` |
| `_tech_aids_lines` | ۱۷۱۰ | کمکی‌ها (سشن/EMA/فیبو/واگرایی) — ⚠️ فقط در ۲ متن استفاده می‌شود (F: قانون ۴ ناتمام) |
| `_compact_alert_caption` | ۱۶۴۳ | متن مختصر |
| `_setup_update_caption` | ۱۸۲۹ | متن آپدیت + «آپدیت N» |
| `send_educational_setup` | ۱۷۵۴ | تفصیلی → کانال هشدارها؛ مختصر → اسلات PRO |
| `send_technoclassic_preview` | ۲۶۴۵ | preview فقط PRO (بدون تفصیلی در هشدارها) |
| `send_confirmed`, `send_approaching`, `send_verdict_reply`, `send_ladder_event`, `send_trade_result`, `send_trade_close_event` | | بقیهٔ چرخهٔ حیات |

**کمکی‌های جدید (fix8/fix9 — ۲۰۲۶-۰۹-۱۵):** `_split_caption` (کپشن >۱۰۲۴ → سر + دنباله؛ دنباله **بدون ریپلای** بلافاصله زیرِ پیام می‌آید)، `_balance_html_tags`، `_ladder_reply_id` (قانون نردبان TP: TP1→Confirmed، TPn→TP(n-1)، استاپ→Confirmed؛ نتیجه نهایی از `_final_lifecycle_anchor`)، `send_setup_update(..., critical=True)` (دور زدن گپ ۳۰۰ ثانیه برای ⚡live-break و آپدیت مادی)، `_compact_alert_caption` با تنزل تدریجی (هرگز دو پیام نمی‌شود)، `aids_bank._disambiguate` (جهت‌آگاهی متن کمکی‌ها)، `_ai_note` ستاپ‌آگاه (pin/ALBROX/TECHCLASSIC). خطوط جدول بالا مربوط به نسخهٔ ممیزی است و ممکن است جابه‌جا شده باشند — همیشه با grep پیدا کن.

## داده و DB
| فایل | خط | مسئولیت | نکته |
|---|---|---|---|
| `database/repository_v7.py` | ۱٬۳۲۵ | سیگنال‌های تأییدشده، licence، `monitor_confirmed_trades` | ⚠️ **F1** (خط ۱۳۱۸) · **F20** دو ژنراتور رویداد |
| `database/db.py` | ۱٬۲۲۷ | schema، `db_cursor`، داشبورد | ⚠️ **F7** بدون pool |
| `database/candidate_store.py` | ۵۰۸ | `signal_candidates` (چرخهٔ حیات کاندیدا)، chains، lineage، `cleanup_candidates` | ⚠️ **F7** اتصال تازه در هر فراخوانی · `_pg_sql` با `replace("?", "%s")` شکننده است |
| `database/bot_kv.py` | — | KV با مقدار JSON | کلیدها: پایین |
| `database/realtime_monitor.py` | — | `monitor_realtime_prices` — TP/SL از تیکر زنده (مسیر **سالم** رویدادها) | |
| `data/fetcher.py` | ۳۰۸ | Bybit klines/tickers، `_throttle` سراسری، کش ۴۵s | ⚠️ **F9** |
| `data/ourbit.py` | ۲۴۰ | Ourbit candles/contracts/tickers | |
| `data/universe.py` | ۳۹۴ | watchlist پویا (رتبه‌بندی نقدشوندگی) | `watchlist_max_symbols = 100` |
| `data/ranking.py`, `data/marketcap.py` | | رتبه‌بندی OKX/Bybit، فلزات | |

### کلیدهای `bot_kv`
| کلید | محتوا |
|---|---|
| `setup_chain\|<PUBLIC_CODE>` | `slot`, `slot_kind`, `pro`, `edu`, `upd`, `upd_n`, `upd_sig`, `upd_ts`, `hb_bar`, `code`, `pattern`, `state`, `fade` |
| `tc_chain\|<SYM>\|<tf>` | زنجیرهٔ TECHCLASSIC |
| `tc_link\|<SYM>\|<tf>` | لینک به اسلات PRO |
| `tc_pro_sep` | جداکنندهٔ روزانهٔ PRO |
| `scan_summary` / `scan_history` (۲۴ سیکل آخر) | قیف اسکن: `detected/new/errors/absorbed/quiet/liccap/sep2pct/updthrottle/deadgate/pre_tp1/deferred/tally` |
| `monitor_summary` | `active/live_break/heartbeat/confirmed/cancelled/rejects` |
| `send_audit` | رسیدِ ارسال‌ها |
| `boot_version` | `sha`/`build`/`when` — **اثبات دیپلوی** |

## تست‌ها
| فایل | خط | چه چیزی را می‌پوشاند |
|---|---|---|
| `test_v7.py` | ۵۲۱ | **تنها فایل `unittest.TestCase`** → تنها چیزی که CI اجرا می‌کند (۲۴ تست). شامل مسیر **ladder** رویدادها |
| `test_signal_guards.py` | ۱٬۰۷۷ | گیت‌های سیگنال، زنجیره، اسلات KV |
| `test_pattern_engine.py` | ۴۲۴ | الگوهای کلاسیک (۱ تست conditional skip) |
| `test_alert_lineage.py`, `test_lifecycle_linking.py`, `test_durable_state.py`, `test_stats_dedup.py` | | lineage، پیوند پیام‌ها، ماندگاری، dedup |
| `test_tlbreak_confirm.py`, `test_viva_tlbreak.py`, `test_viva_tlbreak_state.py` | | TLBREAK و ماشین حالت |
| `test_trigger_patterns.py`, `test_trade_management.py`, `test_zone_polarity.py` | | ماشه‌ها، نردبان TP، polarity |
| ❌ **پوشش ندارند** | | `main.py` (حلقهٔ تولید!)، `setups_v7.py`، `candidate_store.py`، `repository_v7.py` مسیر **legacy**، `telegram_bot.py`، `commands.py` |

## پوشه‌های دیگر
`tools/` (بک‌تست تکنوکلاسیک، ساخت preview) · `experiments/` (collect_replay, diagnose_funnel, p1234_*, okx_feed) · `scripts/` (diagnose_bybit, migrate_postgres, purge_legacy_unconfirmed) · `docs/` (RAILWAY_MIGRATION_RUNBOOK, ROADMAP_V7, REVIEW_PINWALL_POLARITY, viva-personal-setup-v1) · `strategies/viva_tlbreak/` (PLAN, SCORING, STATE_MACHINE, config.json) · `assets/stickers/`

## فایل‌های بیرون ریپو (در sandbox چت قبلی — بعد از ریست **از بین رفته‌اند**)
`~/.railway_token` · `~/.dburl` (Postgres لایو) · `~/.tgbot_token` · `~/rw_api.py` (هلپر GraphQL دیپلوی)
→ در sandbox جدید باید دوباره ساخته شوند. ⚠️ توکن GitHub که در بکاپ لو رفته **باید revoke شود**.
