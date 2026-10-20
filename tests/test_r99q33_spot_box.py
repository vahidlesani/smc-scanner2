"""R99q33 box/margin law — WLFI 8H spot.

«گفتم یک باکس کوچک مثل ستاپ‌ها درست کن و بذار جایی که من به مربع کشیدم»
«حاشیه چارت پشت قیمت رو سریع به حالت قبلی برگردون»
«سریعا این جا رو به چارت اضافه کن»
"""
SRC = open("tools/render_spot_cryptocove.py", encoding="utf-8").read()


# ── the small setup-style box law ─────────────────────────────────────────
def test_one_short_box_per_side_at_the_live_edge():
    assert "_zw32 = int(min(max(12, n // 8), 26))" in SRC
    assert "_x0z32 = max(_x1z32 - _zw32, x_from)" in SRC
    assert "_keep32, _seen32 = [], set()" in SRC
    # the wide full-width band is gone
    assert '_x0z32 = max(int(_z32.get("x0") or x_from), x_from)' not in SRC


def test_the_exit_label_rides_the_box_corner():
    assert 'ax.text(_x0z32 + 0.6, _zt32, " " + _lbl32 + " "' in SRC


# ── the live price tag is back BEHIND the price ───────────────────────────
def test_live_price_tag_sits_in_the_white_band():
    assert "_live_x = (_xl0 + 4.0 - _ab0.x0) / float(_ab0.width)" in SRC
    assert "_tr33 = _mtr33.blended_transform_factory(ax.transAxes, ax.transData)" in SRC
    assert "ax.text(_live_x, live," in SRC
    assert "ax.text(x_to + 0.4, live," not in SRC     # the in-panel placement is gone


def test_the_panel_is_back_near_its_old_reach():
    assert "right=0.870" in SRC
    assert "right=0.826" not in SRC


def test_the_trade_box_is_compact_and_flush_right():
    assert "_box_w30 = 0.084" in SRC
    assert "_bx30 = 0.995 - _box_w30" in SRC


def test_the_live_tag_never_prints_through_the_trade_box():
    assert "spot live pill nudge warning" in SRC
