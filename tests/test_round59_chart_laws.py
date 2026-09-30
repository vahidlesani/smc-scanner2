"""r59 — the chart dictation (Viva 09-28, verbatim anchors):
«باکس نواحی عرضه و تقاضا یا فلگ لیمیت یا اف وی جی اگر بالا یا پایین قیمت است
بدون خط حاشیه رسم بشه اما لیبلش در سمت نوشته ها یا جایی که روی کندل ها رو
نپوشونه … مثل باکس ساپلای قرمز کمرنگ باکس دیمند سبز کمرنگ · اف وی جی با
اوردر بلاک یا فلگ لیمیت بالای قیمت … ۴ رنگ متفاوت از خانواده قرمز و اگر پایین
قیمت بود ۴ رنگ از خانواده سبز · همه الگوها با رنگ آبی · ترندها و الگوهای
نزدیک قیمت بالا قرمز پایین سبز · همه ترندها و الگوها خط کامل تا لایو مارکت و
بعد خط چین» · backup: «از تنظیمات فعلی بک‌آپ بگیر بعنوان سیستم عالی».
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_zone_family_has_four_kinds():
    from bot.messages_v7 import _zone_family
    assert _zone_family("FVG") == "FVG"
    assert _zone_family("BEAR FVG") == "FVG"
    assert _zone_family("INVERSE FVG / BREAKER") == "FVG"
    assert _zone_family("ORDER_BLOCK") == "OB"
    assert _zone_family("OB + FVG CONFLUENCE") == "OB"   # OB wins the confluence
    assert _zone_family("SUPPLY/DEMAND FLIP") == "FLIP"
    assert _zone_family("FLAG LIMIT") == "FLAG"


def test_four_shades_red_above_green_below():
    from bot.messages_v7 import _ZONE_SHADES
    for fam in ("SR", "FVG", "OB", "FLAG"):
        assert fam in _ZONE_SHADES["above"], "۴ رنگ متفاوت از خانواده قرمز"
        assert fam in _ZONE_SHADES["below"], "۴ رنگ از خانواده سبز"
        assert _ZONE_SHADES["above"][fam] != _ZONE_SHADES["below"][fam]
    # within a side the four shades are DISTINCT
    assert len(set(_ZONE_SHADES["above"].values())) == 4
    assert len(set(_ZONE_SHADES["below"].values())) == 4


def test_far_patterns_paint_blue_near_keep_red_green():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "_PATTERN_BLUE" in src
    # the blue gate: classic shapes only, >2×ATR from the live close
    seg = src.split("_pblue9 = bool(_pat.get(\"far_major\"))")[1][:700]
    assert "TRENDLINE" in seg and "2.0 * _atr9" in seg
    # r59.1: the stored far major survives the window refit
    assert "far_major" in src.split("def _native_patterns_for_frame")[1][:8000] or \
        "_draw_pats.append({**_pm, \"far_major\": True})" in src


def test_range_near_red_green_far_blue():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    seg = src.split('if _pat.get("type") == "RANGE":')[1][:1500]
    assert "_rgfar9" in seg
    assert 'CHART_THEME["supply"], CHART_THEME["demand"]' in seg


def test_solid_to_live_dashed_after_everywhere():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    # the TLBREAK legacy block no longer runs solid into the margin
    assert "[xa, _xlv9]" in src and "[_xlv9, x_end]" in src
    assert "linestyle=(0, (6, 4))" in src   # dashed projection


def test_zone_far_uses_side_margin_label_no_border():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    seg = src.split("_away9 = (_zb9 > _cl9z)")[1][:1600]
    assert "ax.text(count + future * 0.45" in seg   # the notes-side legend
    assert "linewidth=0" in seg                     # fill only — no border


def test_cryptocove_candles_are_a_preview_switch():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'os.getenv("CHART_CANDLE_STYLE", "ink")' in src
    assert '#089981", down="#F23645' in src.replace("up=\"", "")


def test_backup_of_the_excellent_system_exists():
    assert os.path.exists(os.path.join(ROOT, "docs", "RENDER_BACKUP_r58.md"))
    txt = open(os.path.join(ROOT, "docs", "RENDER_BACKUP_r58.md"), encoding="utf-8").read()
    assert "ZONE_PALETTE" in txt and "_CHART_CANDLE_COUNTS" in txt


def test_spot_candle_counts_serve_perpetual_too():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    # no chart fetch path may bypass the dictated counts any more
    assert "get_klines(candidate.symbol, candidate.trigger_timeframe, 180," not in src
    assert "get_klines(sym, tf, 150," not in src
    assert src.count("_chart_fetch_size(") >= 4
