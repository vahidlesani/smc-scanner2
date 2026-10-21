"""R99k/R99l — futures design guards (spot-fidelity parity + layout laws)."""
import os
import re

import bot.messages_v7 as mv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    with open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8") as _f:
        return _f.read()


def _chart_region():
    _lines = _src().split("\n")
    _start = next(_i for _i, _l in enumerate(_lines)
                  if _l.startswith("def generate_chart("))
    _end = next((_i for _i in range(_start + 1, len(_lines))
                 if _lines[_i].startswith("def ") or _lines[_i].startswith("class ")),
                len(_lines))
    return "\n".join(_lines[_start:_end])


def test_light_preset_is_white():
    _light = mv._CHART_PRESETS["light"]
    assert _light["figure"] == "#FFFFFF"
    assert _light["panel"] == "#FFFFFF"


def test_green_red_candles_default_with_ink_hatch():
    assert 'os.getenv("CHART_CANDLE_STYLE", "cryptocove")' in _src()


def test_designer_signature_is_the_centre_watermark():
    """R99q (his 10-15) had «by: Vahid Lesani» in the corner, R99q20 tried a
    framed banner there, and R99q21 (his 10-16: «اونی که بالا گذاشتی هم بردار
    قشنگ نشد .. عکس خوب نشد شلوغ شد در اسپات و ستاپ‌ها») DELETED every corner
    credit. ONE signature remains: the author's name over the faint logo mark
    in the middle of the chart — and nothing else is stamped on the canvas."""
    _m = _src()                                   # the centre mark is its own helper
    # R99q23: the mark reads «VAHID LESANI ANALYSIS» and the corner badge is
    # replaced by the author's name + logo («اون برچسب جدید … نمی‌خواد، فقط به
    # کنار اسم من بالای سمت راست چارت لوگو رو اضافه کن»).
    assert '"VAHID LESANI ANALYSIS", transform=ax.transAxes' in _m
    assert 'fontsize=34, fontweight="bold"' in _m            # same size, both lanes
    assert "_add_author_credit(fig)" in _m                   # name + logo, top-right
    assert "_add_setup_sticker(fig, candidate)" not in _m     # badge retired from canvas
    assert "CHART_LOGO_PATH" in _m                           # logo behind it
    _r = _chart_region()
    assert "VIVA_CREDIT_LOGO_H" not in _r                    # corner credit retired
    assert "viva_credit_banner" not in _m
    assert "by: Vahid Lesani" not in _m


def test_price_axis_tags_colored_readable():
    # R99l: black tags retired (unreadable) — line-colored, white bold text.
    assert '"facecolor": _cv9' in _chart_region()
    assert 'color="white"' in _chart_region()


def test_no_emoji_tofu_in_chart_region():
    # Chart-drawn emoji (e.g. the old TARGET glyph) render as tofu boxes in
    # DejaVu — Telegram-text emoji outside generate_chart are unaffected.
    _bad = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u26FF]", _chart_region())
    assert not _bad, _bad[:5]


def test_corner_notes_single_column():
    # R99l: no wandering mid-chart column — one unified left stack.
    assert "_cols = 1" in _src()


def test_figure_has_thin_black_frame():
    assert 'edgecolor="black", linewidth=1.0, zorder=100' in _chart_region()


def test_webapp_behind_kill_switch_default_off():
    _db = open(os.path.join(ROOT, "dashboard", "app.py"), encoding="utf-8").read()
    assert 'os.getenv("WEBAPP_ENABLED", "0")' in _db
    assert "/health" in _db
