"""R99q38k — spot renders NO zones (his 10-21, verbatim).

«آقا اسپات نباید نواحی رو رندر بگیره.. نواحی فقط ستاپ‌ها است .. فقط نواحی
ریفاین شده همون تایم‌فریم... من حتی در ستاپ‌ها هم نباید نواحی پهن‌تر از عرض
۱ سانتی‌متر ببینم»
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_spot_canvas_draws_no_zone_boxes():
    src = open(os.path.join(ROOT, "tools", "render_spot_cryptocove.py"),
               encoding="utf-8").read()
    assert "detect_zones" not in src
    assert "prepare_zones" not in src
    assert "SPOT RENDERS NO ZONES" in src


def test_setup_zones_are_at_most_one_centimetre_wide():
    import bot.messages_v7 as M
    assert M.ZONE_MAX_WIDTH_FRAC <= 0.14
    # the clamp applies to the POI box, every render_zones box and the tool
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert src.count("_zone_left_edge(") >= 4
    assert "tool_start = int(_zone_left_edge(tool_end, tool_start, span=count))" in src


def test_spot_still_draws_its_shape_and_trade_box():
    src = open(os.path.join(ROOT, "tools", "render_spot_cryptocove.py"),
               encoding="utf-8").read()
    assert "TRADE ·" in src or "TRADE" in src
