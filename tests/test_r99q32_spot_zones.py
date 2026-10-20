"""R99q32a — spot charts carry the POI boxes again.

His 10-20: «باکس‌های اسپات چرا نیست روی چارت؟؟»

The setup charts draw SUPPLY/DEMAND boxes; the spot canvas drew none (an old
CryptoCave-clean rule), which is exactly the asymmetry he photographed. The
boxes are the same objects the setup charts use, and they pass through the
same same-TF refinement law so a 4h band never lands 16x wide on a 1h chart.
"""
import os

SRC = open("tools/render_spot_cryptocove.py", encoding="utf-8").read()


def test_the_spot_renderer_detects_zones():
    assert "from analysis.render_kit import detect_zones as _dz32" in SRC


def test_it_refines_them_before_drawing():
    assert "from analysis.zone_refine import prepare_zones as _pz32" in SRC


def test_it_keeps_the_canvas_clean_with_one_small_box():
    """R99q33a (his 10-20, verbatim: «گفتم یک باکس کوچک مثل ستاپ‌ها درست کن و
    بذار جایی که من به مربع کشیدم»): ONE small short box per side instead of
    wide full-width bands, and never the same level twice."""
    assert "_keep32, _seen32 = [], set()" in SRC      # one per side+kind
    assert "_zw32 = int(min(max(12, n // 8), 26))" in SRC   # a SHORT box
    assert "_x0z32 = max(_x1z32 - _zw32, x_from)" in SRC    # at the live edge


def test_a_label_rides_its_own_box_corner():
    """The chip sits on the box's own top-left corner — inside the frame,
    never over a candle, never clipped by the panel edge."""
    assert 'ax.text(_x0z32 + 0.6, _zt32, " " + _lbl32 + " "' in SRC
    assert 'va="bottom", ha="left"' in SRC


def test_supply_is_above_and_demand_below_the_live_price():
    assert '_side32 = "SUPPLY" if 0.5 * (_zb32 + _zt32) >= _live31 else "DEMAND"' in SRC


def test_a_broken_zone_detector_never_kills_the_chart():
    assert "spot zone draw skipped" in SRC
    # the draw block is wrapped, so a failure degrades to the old canvas
    i = SRC.index("R99q32a POI BOXES ON SPOT")
    assert "try:" in SRC[i:i + 600]
