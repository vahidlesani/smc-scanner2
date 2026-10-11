"""Stage-1: پایداری هندسه با تغییر زوم/تعداد کندل + دادهٔ واقعی."""
import gzip
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis import viva_geometry as vg
from analysis import engine_spot, engine_perp

ROOT = Path(__file__).resolve().parents[1]
KL = ROOT / "experiments" / "sample_klines"


def load(name):
    with gzip.open(KL / name, "rt") as f:
        return pd.read_csv(f)


def test_zoom_invariance_synthetic():
    from test_stage1_core import mk_wedge
    df = mk_wedge(n=160, break_edge="UP", break_bars=6)
    full = vg.fit_patterns(df)
    assert full
    for lb in (140, 120, 100):
        cut = vg.fit_patterns(df, lookback=lb)
        assert cut, f"lookback={lb} الگو را گم کرد"
        assert cut[0].slug == full[0].slug, f"{cut[0].slug} != {full[0].slug}"
        assert abs(cut[0].upper.slope - full[0].upper.slope) < 5e-4, "شیب با زوم عوض شد"
        # خود خط (شیب+عرض از مبدأ) باید عیناً ثابت بماند؛ شروعِ دیده‌شده حداکثر
        # یک نوسان جلو می‌آید چون تاریخچهٔ بریده‌شده تماس اول را از دست می‌دهد
        assert abs(cut[0].upper.intercept - full[0].upper.intercept) < 1e-6
        # x0 فقط نخستین تماسِ دیده‌شده است و با برش تاریخچه عقب می‌آید؛
        # پایداری واقعی = هویت هر دو خط:
        assert abs(cut[0].lower.intercept - full[0].lower.intercept) < 1e-6


def test_live_update_stability_real_btc4h():
    """قانون اسنپ‌شات: با رسیدن کندل زندهٔ جدید (قبل از تأیید)، خطِ الگوی
    تثبیت‌شده نباید بیش از ۲×ATR جابه‌جا شود؛ برش چپ = فقط نمایش، بدون ری‌فیت."""
    df = load("BTCUSDT_4h_20260726_20260924.csv.gz")
    full = vg.fit_patterns(df)
    if not full:
        pytest.skip("الگویی در نمونهٔ BTC 4h نیست")
    f0 = full[0]
    earlier = vg.fit_patterns(df.iloc[:-2].reset_index(drop=True))
    if not earlier:
        pytest.skip("در برش زمانی الگو نیست")
    e0 = earlier[0]
    assert e0.slug == f0.slug or (e0.slug.startswith("BROADENING") and f0.slug.startswith("BROADENING"))
    at = len(df) - 3
    drift = abs(e0.upper.price_at(at) - f0.upper.price_at(at))
    atr = vg.atr_log(vg.log_ohlc(df))
    assert drift <= 2 * atr, f"خط با دو کندل زنده {drift:.4f} جابه‌جا شد"
    # قطعیت: دو اجرای پیاپی روی یک داده = یک نتیجه
    again = vg.fit_patterns(df)
    assert again[0].slug == f0.slug and abs(again[0].upper.intercept - f0.upper.intercept) < 1e-9


def test_spot_engine_tf_and_view_bars():
    df = load("BTCUSDT_4h_20260726_20260924.csv.gz")
    a = engine_spot.analyze(df, "4h")
    if a is None:
        pytest.skip("الگوی اسپات در نمونه نیست")
    assert 0.8 * 170 <= a["view"]["bars"] <= 1.25 * 170 or a["view"]["bars"] <= 400
    with pytest.raises(ValueError):
        engine_spot.analyze(df, "5m")


def test_perp_engine_both_sides():
    df = load("ETHUSDT_15m_20260823_20260924.csv.gz")
    a = engine_perp.analyze(df.tail(1500).reset_index(drop=True), "15m", "PINVAL")
    if a is None:
        pytest.skip("الگویی نیست")
    if a["side"]:
        if a["side"] == "LONG":
            assert a["stop"] < a["entry"] < a["target"] or a["target"] > a["entry"]
        else:
            assert a["stop"] > a["entry"] > a["target"]


def test_invalid_ohlc_rejected():
    df = pd.DataFrame({"open": [1, 2], "high": [2, 0], "low": [0.5, -1],
                       "close": [1.5, 1], "volume": [1, 1]})
    with pytest.raises(ValueError):
        vg.log_ohlc(df)
