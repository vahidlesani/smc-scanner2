"""R64 CANDLE-COUNT LAW — the ONE map of how many candles every timeframe
carries, for detection AND for the chart (chart ≡ trade geometry).

Viva 10-02 (verbatim): «فکر کنم ۲۵۰ تا ۳۵۰ کندل بسته به تایم‌فریم‌ها مناسب
باشه برای پیوت‌های بیشتر در تایم‌های بالاتر — مثل نمونه‌های کریپتوکاو؛ هم برای
اسپات هم پرپچوال، حتی روزانه».

Before R64 the engine fitted on 110-200 bars (1d 110, 4h 140, 2h 120) while
the chart showed 132-300, and spot scanned the WHOLE fetched tape (1d ≈ 1,480
bars) under a 210-bar picture — three different windows for one geometry.
Every consumer now reads this map:
  * analysis.pattern_engine._FIT_WINDOW   (TechnoClassic / ALBROX lane A)
  * bot.messages_v7._CHART_CANDLE_COUNTS  (render window + monitor fetches)
  * analysis.render_kit.enrich_render     (render patterns of the trigger TF)
  * analysis.spot_engine                  (spot detection window)
  * data.fetcher.get_market_bundle         (default fetch depth)
"""
from __future__ import annotations

CANDLE_COUNTS = {
    "5m": 300, "15m": 300, "30m": 300, "1h": 300, "2h": 250,
    "4h": 300, "8h": 280, "12h": 260, "1d": 300, "3d": 300, "1w": 250,
}


# ── R65 PICTURE DENSITY (Viva 10-02, verbatim: «تعداد کندل‌های خیلی زیاد خوب
# نشده فقط شلوغ‌تر شد و نواحی غیر قابل تشخیص‌تر … کندل ۱۹۰ تا ۲۱۰ تا کافیه اما
# زوم درست بشه»).
# Two numbers, two jobs, and they are deliberately different now:
#   * DETECTION keeps the dictated 250–350 bars (his «۲۵۰ تا ۳۵۰ کندل … برای
#     پیوت‌های بیشتر در تایم‌های بالاتر») — the engine must keep hunting pivots
#     on the deeper tape, that is where the major lines come from;
#   * the PICTURE on the low timeframes uses the 190–210 density he dictated,
#     so a 15m/30m/1h/2h chart is not a wall of needles. Higher frames keep the
#     dictated counts (they need the history for the shapes to exist at all).
# The renderer may still stretch back up to the detection count when a stored
# pattern anchor needs the older bars (r37 anchor law) — never further.
RENDER_COUNTS = dict(CANDLE_COUNTS)
# Viva Law 2026-10-08 (RESTORE of the R65 lock, reverted from ac1db7f
# «TradingView Calibrated Density» 85–145 which broke the locked tests AND the
# Oct-02 dictation «کندل ۱۹۰ تا ۲۱۰ تا کافیه»): intraday pictures are 210.
RENDER_COUNTS.update({"5m": 210, "15m": 210, "30m": 210, "1h": 210, "2h": 210})


# ── canonical TF → seconds (R65: the PINVAL freshness guard and the PINVAL
# verdict window both carried a map that stopped at 1h — a 30m/2h/4h pin was
# judged with a 300 s clock and silently dropped as «stale». One table, used by
# every lane; sub-hour frames which this product never fetches are included for
# completeness.)
TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
              "1h": 3600, "2h": 7200, "4h": 14400, "8h": 28800, "12h": 43200,
              "1d": 86400, "3d": 259200, "1w": 604800}


def tf_seconds(tf: str, default: int = 300) -> int:
    """Candle duration of ``tf`` in seconds (case-insensitive)."""
    return int(TF_SECONDS.get(str(tf or "").strip().lower(), default))


def candle_count(tf: str, default: int = 300) -> int:
    """Dictated DETECTION candle count for ``tf`` (case-insensitive)."""
    return int(CANDLE_COUNTS.get(str(tf or "").strip().lower(), default))


def render_count(tf: str, default: int = 300) -> int:
    """Dictated PICTURE candle count for ``tf`` (case-insensitive)."""
    return int(RENDER_COUNTS.get(str(tf or "").strip().lower(), default))


def fetch_limits(timeframes=None, pad: int = 40) -> dict:
    """Fetch depth per TF = dictated count + warm-up pad (bundle ``limits``)."""
    tfs = list(timeframes) if timeframes else list(CANDLE_COUNTS)
    return {str(tf).lower(): candle_count(tf) + int(pad) for tf in tfs
            if str(tf).lower() in CANDLE_COUNTS}
