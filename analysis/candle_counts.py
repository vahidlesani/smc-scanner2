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


# ── R68 CRYPTOCOVE PICTURE DENSITY (Viva 10-04, LTC/ARB/ENA verbatim:
# «چه مدل زوم هست .. ارتفاع کندلها باید کمتر بشه و تعداد کندلها کمتر تا کل نمودار
# پر از کندل باشه و الگو اینقدر احمقانه رسم نشه .. روی زوم و تعداد کندلها در اسپات
# بصورت هوشمند باید انجام بشه تا بتونیم چارتهایی شبیه رفرنسهای اسپات CryptoCove داشته باشیم»).
# Macro & mid timeframes on the drawn chart now use the exact CryptoCove
# golden density (140–180 candles):
#   * 4h / 8h / 12h → 160 candles (readable swings, thick clear bodies)
#   * 1d → 180 candles
#   * 3d / 1w → 180–220 candles
# Detection (CANDLE_COUNTS) keeps the deep 250–350 bars for discovering majors.
RENDER_COUNTS = dict(CANDLE_COUNTS)
RENDER_COUNTS.update({
    "5m": 210, "15m": 210, "30m": 210, "1h": 210, "2h": 210,
    "4h": 160, "8h": 160, "12h": 160, "1d": 180, "3d": 220, "1w": 180,
})


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
