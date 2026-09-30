"""r30 (Viva 09-26 bug file) — NO-SOFT-INVALIDATION + anti-flood + Iran-clock laws."""
import ast
import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cand(direction="LONG", sl=None, zb=None, zt=None, confirmed=False):
    md = {}
    if confirmed:
        md["technical_confirmation_complete"] = True
    return SimpleNamespace(
        symbol="LTCUSDT", setup_code="TECHCLASSIC", direction=direction,
        entry_zone_bottom=zb, entry_zone_top=zt, sl=sl, metadata=md,
    )


# ── law 1: NO-SOFT-INVALIDATION — «ابطال نمی‌تونه بین ناحیه باشه» ─────────
def test_invalidation_inside_zone_never_fires_pre_confirm():
    from analysis.quality_engine import is_invalidated
    # LTC shape: zone 63.602-70.98, sl 69.404 INSIDE the zone — rallying into
    # the zone crossed 69.404 and must NOT invalidate the scenario.
    c = _cand("LONG", sl=69.404, zb=63.602, zt=70.98)
    assert is_invalidated(c, 69.404) is False
    assert is_invalidated(c, 70.5) is False


def test_invalidation_beyond_zone_still_fires():
    from analysis.quality_engine import is_invalidated
    c = _cand("LONG", sl=62.0, zb=63.602, zt=70.98)  # protective side, below zone
    assert is_invalidated(c, 61.5) is True
    s = _cand("SHORT", sl=73.0, zb=63.602, zt=70.98)  # above zone for a short
    assert is_invalidated(s, 73.5) is True


def test_confirmed_chain_keeps_stop_ownership():
    from analysis.quality_engine import is_invalidated
    c = _cand("LONG", sl=69.404, zb=63.602, zt=70.98, confirmed=True)
    assert is_invalidated(c, 69.0) is True  # lifecycle stop still governs


def test_builder_clamps_stop_outside_zone():
    src = open(os.path.join(REPO, "analysis", "pattern_engine.py"), encoding="utf-8").read()
    assert "must sit BEYOND the entry zone" in src
    assert "candidate.sl = round(_zb30 - buffer, 8)" in src


# ── law 2: OUT_OF_REACH must never cancel a breakout in progress ─────────
def test_out_of_reach_exempts_price_beyond_zone_in_direction():
    import main as m
    c = SimpleNamespace(
        direction="LONG", entry_zone_bottom=63.602, entry_zone_top=70.98,
        metadata={"atr": 0.6},
    )
    # untouched zone + price ran away above = premise gone (09-21 law stands)
    assert m._scenario_out_of_reach(c, 75.5) is True
    # market TOUCHED the zone, then price ran beyond it = breakout in progress
    c.metadata["touched"] = True
    assert m._scenario_out_of_reach(c, 75.5) is False
    # r33 nearest-edge law: price INSIDE the zone is never out of reach
    assert m._scenario_out_of_reach(c, 70.5) is False
    # far on either side of the zone = premise gone (symmetric, 09-21 law)
    assert m._scenario_out_of_reach(c, 55.0) is True


# ── law 3: tombstone — cancelled scenario can't be re-fired (113-msg flood)
def test_tombstone_roundtrip_suppresses_rediscovery():
    import main as m
    from database.bot_kv import get_json as _g, set_json as _s
    _s("cancel_tombstones", {k: v for k, v in (_g("cancel_tombstones", {}) or {}).items()
                             if "LTCUSDT|TECHCLASSIC" not in k})
    c = _cand("LONG", sl=62.0, zb=63.602, zt=70.98)
    assert m._tombstone_hit(c) is False
    m._tombstone_write(c, hours=12)
    assert m._tombstone_hit(c) is True
    # a materially different zone is a NEW scenario — not tombstoned
    c2 = _cand("LONG", sl=50.0, zb=40.0, zt=48.0)
    assert m._tombstone_hit(c2) is False
    src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    assert '_tombstone_hit(candidate)' in src and '_tombstone_write(candidate)' in src


# ── law 4: Iran clock everywhere on chart captions ────────────────────────
def test_chart_caption_clock_is_tehran_not_utc():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'ZoneInfo("Asia/Tehran")).strftime("%H:%M")' in src
    assert "به وقتِ ایران" in src
    assert "— تا کندلِ جاری" in src
    assert "تا کندلِ جاری" in src and " UTC\"" not in src.split("چارت پیوست")[1][:200]


# ── law 5: update text = NOW + elapsed-since-origin, never «arrived late» ──
def test_update_timing_wording_is_now_framed():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "از کندلِ هشدارِ اولیه" in src and "این پیام همین حالا ارسال شده" in src
    assert "دقیقه بعد از بسته‌شدن کندل منتشر شد" not in src


# ── law 6: final result = text under the TP anchor, NO fresh render ───────
def test_final_result_message_has_no_fresh_chart():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    seg = src[src.index("def send_trade_close_event"):]
    seg = seg[:seg.index("\ndef ", 1)]
    assert "generate_chart" not in seg and "_lifecycle_chart_frame" not in seg
    # reply anchor + atomic pair still intact
    assert "_final_lifecycle_anchor" in seg and "_post_chart_then_text" in seg


# ── law 7: chart+text atomic per chat ─────────────────────────────────────
def test_chart_text_pair_is_lock_atomic():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "_CHAT_SEND_LOCKS" in src and "_chat_send_lock(target)" in src


# ── law 8: approved trigger TFs — 30m + 2h join TechnoClassic ─────────────
def test_technoclassic_pattern_tfs_include_30m_2h():
    from config import get_settings
    settings = get_settings()
    tfs = [t.strip() for t in settings.technoclassic_pattern_tfs.split(",")]
    assert "30m" in tfs and "2h" in tfs and "1h" in tfs and "4h" in tfs and "1d" in tfs
