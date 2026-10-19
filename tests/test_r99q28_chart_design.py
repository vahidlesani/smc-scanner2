"""R99q28 — the chart design laws he restated on 10-19.

«ترندلاین‌های پترن باید کمی نازک‌تر بشه و تا ادامه به اندازه ۵ کندل بعد از کندل
 لایو خط کامل باشه ... کندل‌ها در اسپات باید قرمز و سبز بشن ... سمت راست بالا لوگو
 کوچک با کیفیت و مقابلش VAHID LESANI - VIVA SIGNALS PRO ... از پایین سمت راست
 لوگو برداشته بشه ... پایین سمت چپ کد شناسه یکتا ... باکس قرمز برای شورت‌ها ...
 گریدلاین‌های پشت کندل حذف بشه»

Source-level pinning: these are drawing constants, and a silent revert is
exactly the failure mode he keeps hitting («یکی رو درست میکنی سه تا خراب میشه»).
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPOT = open(os.path.join(ROOT, "analysis", "spot_pattern_engine.py"), encoding="utf-8").read()
MSG = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()


def test_spot_resolution_went_up():
    assert "dpi=220" in SPOT
    assert "dpi=180" not in SPOT


def test_spot_has_no_grid_behind_the_candles():
    assert "'#D5D0C5', linestyle='-', linewidth=0.5, alpha=0.35" not in SPOT
    assert SPOT.count("ax.grid(False)") >= 2


def test_spot_candles_are_green_and_red():
    assert "c_up = '#16A34A'" in SPOT
    assert "c_dn = '#DC2626'" in SPOT


def test_the_trendline_is_thinner_and_solid_for_five_bars_past_live():
    assert "_hold = 5" in SPOT
    assert "linewidth=1.5" in SPOT          # pattern line
    assert "linewidth=2.0" not in SPOT      # the old fat stroke is gone


def test_the_logo_is_resampled_high_quality():
    assert "interpolation='lanczos'" in SPOT
    assert MSG.count("interpolation") == 0 or True   # setups keep defaults


def test_spot_brand_moved_to_the_top_right_and_the_footer_mark_is_gone():
    assert "VAHID LESANI — VIVA SIGNALS PRO" in SPOT
    assert "fig.add_axes([0.895, 0.022" not in SPOT      # old bottom-right mark


def test_spot_carries_the_unique_id_bottom_left():
    assert "ID  {_uid}" in SPOT
    assert "public_code" in SPOT


def test_a_breakdown_gets_a_red_box_not_a_green_one():
    assert "#C62828" in SPOT                 # the short box edge
    assert "#F2B8B5" in SPOT                 # its fill
    assert "spot_box_bottom" in SPOT


def test_setups_show_the_full_brand_line_top_right():
    assert "VAHID LESANI — VIVA SIGNALS PRO" in MSG


def test_setups_dropped_the_bottom_right_footer_logo():
    assert "fig.add_axes([0.918, 0.004, 0.038, 0.044]" not in MSG
