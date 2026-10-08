# Gold References — Viva 10-06/10-08 annotated charts (his verdicts, verbatim sense)

Production look target: every spot AND perpetual signal must be this clean.
Full annotated pack (89 files, incl. his two doctrine txt files) lives in
`docs/references_annotated_10_08/`.

## 🥇 GOLD (score 20 — production reference, do not regress)
- `gold_UNI_4H_spotbreak.jpg` — UNI 4H SPOTBREAK, descending triangle, log scale.
  His words: «نمره ۲۰ … باید بعنوان رفرنس تولید پروژه در مخزن گیت‌هاب ذخیره بشه».
  Law pinned: confirm at the 4H close above the pattern's upper trend; zoom right,
  candle height right. THE look every signal must match.
- `gold_ADA_1D_spotbreak.jpg` — ADA 1D SPOTBREAK, rising wedge/channel, log scale.
  His words: «فوق‌العاده عالی … باید بره جزو رفرنس‌ها». Daily-density reference.

## 👍 GOOD (excellent geometry, timing fault noted)
- `good_DOGE_4H_late-confirm.jpg` — «عالیه فقط باید زودتر تایید می‌داد» + draw the
  lower trend too (his pink line). Timing law, not geometry.
- `good_FET_4H_late-detect.jpg` — «این الگو عالیه .. اگر سر وقت تشخیص داده میشد».
  Detection latency fault (≈36h), geometry praised.
- `good_ONDO_4H_wick-exclusion.jpg` — spike wick CORRECTLY excluded from the trend
  («اگر میگرفتیم شیب ترندلاین رو بی‌اعتبار میکرد»). Keep this behavior.

## 👎 BAD (fault catalogue — each maps to a law/fix)
- `bad_XRP_4H_shadows.jpg` — shadows disrespected; «چرا بعضیا عالی و بعضیا ضعیف».
- `bad_HYPE_4H_box.jpg` — box misplaced («جای باکس هم اشتباهه»), sloppy drawing.
- `bad_LINK_8H_channel.jpg` — half-baked lines vs his pink/green channel.
- `bad_AAVE_4H_pinval.jpg` — upper good/lower bad; zoom must follow patterns but
  pivots must never leave their anchors after zoom («از لنز پیوت‌های درست خارج نشه»).
- `bad_FET_4H_weekly-box_FIXED.jpg` — weekly pink box on a 4H chart → fixed by the
  HTF-range clamp (ac1db7f, locked in test_viva1008).
- `bad_STX_15M_many-candles_FIXED.jpg` — ~300 bars + tall candles on 15M → fixed by
  the render-count window cap (locked in test_viva1008).
- `bad_CRV_28h-late.jpg` — «۲۸ ساعت قبل باید تایید میشده» — late-confirm case family.

## 🔒 Lock protocol (his standing order)
No change to geometry/confirm/zoom behavior without re-checking these images.
New faults ship with their chart added here + a test in `tests/test_viva1008*`.
