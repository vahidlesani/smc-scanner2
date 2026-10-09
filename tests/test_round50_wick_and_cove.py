"""r50 — wick-noise pivots + CryptoCove candle counts (Viva 09-27).

His words, verbatim:
  «شدوهای نویز رو نگیره بعنوان پیوت … همه پیوت‌ها در یک راستا داینامیک
   هستند وسطش یا اولش یا آخرین یه شدو نویز داره — از اونها نگیره، رسم ترند
   رو از بادی اونها بگیره» — trend/pattern pivot anchors use the BODY when a
   candle's wick is disproportionate (≥1.5× body AND ≥0.30× ATR14).
  «تعداد کندل‌های تایم‌های مختلف کریپتوکاو رو بسنج و به چارت اضافه کن …
   برای اسپات دقیقاً اونو» — the reference batch measures a dense tape
   (~150–190 candles); high-TF charts now render at that density and the
   spot bundle FETCHES those depths (1w:140 ≈ 985 daily bars, one call).
  «با توجه به لگاریتمی شدن چارت‌ها موتور الگوها و ترندها رو تنظیم کن» — the
   r16 fits are already log-based (log_fit_min_span guard); on a log axis a
   2-point data-space segment renders screen-straight, so the log-fit line
   draws straight with no extra work. Structural pivots (sweeps/BOS/stops)
   keep the RAW wick — a sweep IS the wick.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _frame(prices, wick_mult=0.0, body=0.4):
    """rows: each candle [open, high, low, close]; highs get wick_mult×ATR14 wick."""
    rows = []
    ts = pd.Timestamp("2026-09-01 00:00")
    for i, px in enumerate(prices):
        o = px
        c = px + (0.05 if i % 2 else -0.05)
        hi = max(o, c) + wick_mult
        lo = min(o, c) - 0.05
        rows.append(dict(timestamp=ts + pd.Timedelta(hours=i),
                         open=o, high=hi, low=lo, close=c, volume=1000.0))
    return pd.DataFrame(rows)


# ── 1. the wick-noise pivot filter ──────────────────────────────────────────

def test_noisy_wick_pivot_anchors_to_body_when_enabled():
    from analysis.indicators import pivots
    # flat-ish tape where index 10 pokes a 1.2-unit wick (bodies ~0.05-0.45)
    prices = [10.0] * 8 + [10.3, 10.6] + [10.9] + [10.6, 10.3] + [10.0] * 8
    df = _frame(prices, wick_mult=0.0)
    df.loc[10, "high"] = 12.1                       # huge noise shadow
    raw_h, _ = pivots(df, 3, 3)                     # default: raw wick
    hit_raw = [p for p in raw_h if p["index"] == 10]
    assert hit_raw and hit_raw[0]["price"] == 12.1
    hit_body = None
    fh, _ = pivots(df, 3, 3, wick_noise_filter=True)
    hit_body = [p for p in fh if p["index"] == 10]
    assert hit_body, fh
    assert hit_body[0]["anchor"] == "body"
    assert hit_body[0]["price"] < 12.1              # body extreme, not the wick
    assert hit_body[0]["raw_price"] == 12.1


def test_normal_pivot_keeps_its_wick():
    from analysis.indicators import pivots
    prices = [10.0] * 8 + [10.3, 10.6] + [10.9] + [10.6, 10.3] + [10.0] * 8
    df = _frame(prices)
    fh, _ = pivots(df, 3, 3, wick_noise_filter=True)
    hit = [p for p in fh if p["index"] == 10]
    assert hit and hit[0]["anchor"] == "wick"       # proportionate wick stays
    assert hit[0]["price"] == hit[0]["raw_price"]


def test_trend_fit_sites_opt_in():
    src = open(os.path.join(REPO, "analysis", "viva_tlbreak.py"), encoding="utf-8").read()
    assert src.count("wick_noise_filter=True") == 3
    # structural consumers stay raw
    src2 = open(os.path.join(REPO, "analysis", "setups_v7.py"), encoding="utf-8").read()
    assert "wick_noise_filter" not in src2


# ── 2. CryptoCove density ───────────────────────────────────────────────────

def test_cryptocove_lookbacks():
    # r52 — HIS dictation (09-28): 4h/8h→140-200, 12h/1d→170-250, 3d→250-350,
    # 1w→170-250 (mid-points shipped); r50 measured numbers are superseded.
    # R64 — HIS 10-02 dictation supersedes r52: 250..350 candles per TF, spot
    # AND perpetual, daily included — one map in analysis.candle_counts.
    from analysis.candle_counts import CANDLE_COUNTS as C
    assert (C["4h"], C["8h"], C["12h"], C["1d"], C["3d"], C["1w"]) == (300, 280, 260, 300, 300, 250)


def test_spot_bundle_fetches_the_depths():
    src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    # R64: the spot bundle reads the ONE candle-count map (+40 warm-up)
    assert src.count('fromlist=["fetch_limits"]).fetch_limits()') == 2
    from analysis.candle_counts import fetch_limits
    lim = fetch_limits()
    assert lim["3d"] == 340 and lim["1w"] == 290 and lim["4h"] == 340
    src2 = open(os.path.join(REPO, "data", "fetcher.py"), encoding="utf-8").read()
    assert 'limits.get("4h", 200)' in src2
    assert 'limits.get("1w", 210)) * 7 + 7' in src2
    # deep dailies ride the one-time history store (Railway cost law)
    assert 'get_deep_daily' in src2


def test_spot_triggers_already_cover_the_high_lanes():
    from analysis.spot_engine import SPOT_TRIGGERS
    assert set(("4h", "8h", "12h", "1d", "3d", "1w")).issubset(set(SPOT_TRIGGERS))
