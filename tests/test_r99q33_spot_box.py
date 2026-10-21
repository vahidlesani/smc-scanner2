"""R99q33 box/margin law — WLFI 8H spot.

«گفتم یک باکس کوچک مثل ستاپ‌ها درست کن و بذار جایی که من به مربع کشیدم»
«حاشیه چارت پشت قیمت رو سریع به حالت قبلی برگردون»
«سریعا این جا رو به چارت اضافه کن»
"""
SRC = open("tools/render_spot_cryptocove.py", encoding="utf-8").read()


# ── the small setup-style box law (SUPERSEDED 10-21: no spot zones at all) ─
def test_the_spot_zone_boxes_are_retired():
    """His 10-21: «آقا اسپات نباید نواحی رو رندر بگیره.. نواحی فقط ستاپ‌ها است».
    The R99q33 small-box law targeted zone boxes that no longer exist; the spot
    canvas keeps only the target strip and the trade box."""
    assert "_zw32" not in SRC and "_lbl32" not in SRC
    assert "SPOT RENDERS NO ZONES" in SRC


# ── the live price tag sits BESIDE the price ladder ───────────────────────
def test_live_price_tag_sits_beside_the_measured_ladder():
    """R99q35: the ladder moved inside the panel, the pill moved with it."""
    assert "_lbl_px = float(_ladder_x0) * float(fig.bbox.width)" in SRC
    assert "_live_x = (_lbl_px - 6.0 - _ab0.x0) / float(_ab0.width)" in SRC
    assert "_tr33 = _mtr33.blended_transform_factory(ax.transAxes, ax.transData)" in SRC
    assert "ax.text(_live_x, live," in SRC
    assert "ax.text(x_to + 0.4, live," not in SRC     # the in-panel-over-candles placement is gone


def test_the_panel_reaches_the_canvas_edge():
    """His 10-20: «این قسمت سفید پشت قیمت‌ها باید به فضای نمودار کندل‌ها اضافه بشه»."""
    assert "right=SPOT_PANEL_RIGHT" in SRC
    assert "SPOT_PANEL_RIGHT = 0.9955" in SRC
    assert "right=0.870" not in SRC
    assert "right=0.826" not in SRC


def test_the_trade_box_is_compact_and_inside_the_corner():
    assert "_box_w30 = max(0.060, min(0.086, _room30))" in SRC
    assert "_bx30 = float(_ladder_x0) - 0.008 - _box_w30" in SRC


def test_the_live_tag_never_prints_through_the_trade_box():
    assert "spot live pill nudge warning" in SRC
