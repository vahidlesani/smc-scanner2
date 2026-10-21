"""Round 14 (Viva 09-21) — the stop ceiling per timeframe, and TP ⟂ stop.

His words, verbatim:

* «اون ۱.۲۵ صدم استاپ برای ۱۵ دقیقه است / ۱.۷۵ استاپ برای ۱ ساعته / استاپ ۲ تا
  ۲.۲۵ قیمت نماد در ۴ ساعته / استاپ ۲.۵ تا ۲.۷۵ قیمت در سویینگ‌های روزانه»
* «این در صورتی هست که سویینگ ساختاری در چارت نداشته باشیم؛ اگر هم کف یا سقف
  داشته باشیم نباید از این اعداد استاپ با بافرش بزرگ‌تر باشه»
* «و لطفا ارتباطی بین تی پی و استاپ نذار»
* «در روزانه شاید باید تا ۱۵ درصد رو هم در نظر بگیریم … اینم انجام بده تا فردا
  ببینیم چی بهتره که تغییر بکنه»
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.trade_management import (stop_ceiling_pct,
                                       clamp_stop_price, structural_buffer,
                                       band_for_tf, target_distance_cap_pct,
                                       doctrine_path, build_ladder)


# ── 1. the ceiling table is exactly his numbers ────────────────────────────

# Viva 09-23 (reversal, verbatim: «استاپها هنوز اشتباه هستن و خیلی کوچک و
# بلافاصله هانت میشیم … استاپ باید از کف بیس ۴ ساعته دربیاد … از نواحی تایم
# پایین‌تر از تایم تریگر») — the round-14 numbers made every LTF-structural
# stop a huntable squeeze; the ceilings widen so the base actually fits.
@pytest.mark.parametrize("tf,ceiling", [("15m", 2.00), ("5m", 1.50), ("3m", 1.25),
                                        ("30m", 2.25), ("1h", 2.75), ("2h", 3.25),
                                        ("4h", 4.50), ("1d", 8.00)])
def test_his_stop_ceiling_per_timeframe(tf, ceiling):
    assert stop_ceiling_pct(tf) == ceiling


def test_the_four_numbers_he_named():
    assert stop_ceiling_pct("15m") == 2.00
    assert stop_ceiling_pct("1h") == 2.75
    assert stop_ceiling_pct("4h") == 4.50
    assert stop_ceiling_pct("1d") == 8.00


def test_an_unknown_timeframe_falls_back_to_the_15m_ceiling():
    assert stop_ceiling_pct("") == 2.00
    assert stop_ceiling_pct("7h") == 2.00


# ── 2. a structural swing keeps its place while it fits the ceiling ────────

def test_a_swing_inside_the_ceiling_is_kept_as_it_is():
    # 1h: entry 100, structural swing + buffer at 98.70 → 1.30% ≤ 1.75% ✓
    stop, clamped = clamp_stop_price(100.0, "LONG", 98.70, "1h")
    assert clamped is False and stop == 98.70


def test_a_swing_farther_than_the_ceiling_is_cut_at_the_ceiling():
    stop, clamped = clamp_stop_price(100.0, "LONG", 96.0, "1h")
    assert clamped is True and stop == pytest.approx(100.0 - 2.75)   # 1h = 2.75% (09-23 table)
    stop4, clamped4 = clamp_stop_price(100.0, "SHORT", 104.0, "4h")
    # 4h ceiling is 4.5% now — a 4% swing FITS (no clamp)
    assert clamped4 is False and stop4 == pytest.approx(104.0)
    stop1d, clamped1d = clamp_stop_price(100.0, "LONG", 90.0, "1d")
    # 1d ceiling is 8% now — a 10% swing is cut to 8%
    assert clamped1d is True and stop1d == pytest.approx(100.0 - 8.0)
    stop15, clamped15 = clamp_stop_price(100.0, "SHORT", 103.0, "15m")
    # 15m ceiling is 2.0% now — 3% is cut
    assert clamped15 is True and stop15 == pytest.approx(100.0 + 2.0)


def test_the_clamp_never_crosses_the_entry_and_never_invents_a_side():
    for tf in ("15m", "1h", "4h", "1d"):
        stop, _c = clamp_stop_price(100.0, "LONG", 100.5, tf)   # already wrong side
        assert stop == 100.5                                    # left to the net to reject
        stop2, _c2 = clamp_stop_price(100.0, "SHORT", 99.0, tf)
        assert stop2 == 99.0


def test_the_structural_buffer_itself_is_inside_the_new_ceiling():
    """The buffer (5 ticks / 0.10%) is small enough that the ceiling still
    leaves room for a real swing on every timeframe."""
    for tf in ("15m", "1h", "4h", "1d"):
        assert structural_buffer(100.0) == pytest.approx(0.10)
        assert structural_buffer(100.0) < 100.0 * stop_ceiling_pct(tf) / 100.0 / 2.0


def test_every_lane_clamps_with_its_own_timeframe():
    """A single 1.25% ceiling for a daily chart was the round-12 stop bug; each
    lane now hands its trigger TF to the clamp."""
    for path in ("analysis/setups_v7.py", "analysis/pattern_engine.py",
                 "analysis/quality_engine.py", "analysis/setups_experimental.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "clamp_stop_price" in src, path
        assert "trigger_timeframe" in src or "trigger_tf" in src


# ── 3. daily TP room up to 15% (his ZEC observation) ───────────────────────

def test_the_daily_target_ceiling_is_fifteen_percent_now():
    assert target_distance_cap_pct("1d") == 15.0
    assert band_for_tf("1d") == (5.0, 15.0)
    path, _src = doctrine_path(100.0, "1d", level=114.0)
    assert path == pytest.approx(14.0)          # a 14% structural level is legal now
    capped, _src2 = doctrine_path(100.0, "1d", level=140.0)
    assert capped == pytest.approx(15.0)        # beyond 15% it is capped, not deleted


# ── 4. TP ⟂ stop ───────────────────────────────────────────────────────────

def test_the_target_path_never_reads_the_stop():
    """doctrine_path carries no stop/risk term at all."""
    import inspect
    sig = inspect.signature(doctrine_path)
    assert not {"sl", "stop", "risk"} & set(sig.parameters)
    for stop in (95.0, 98.0, 99.5):
        p, _s = doctrine_path(100.0, "1h", level=103.5)
        assert p == pytest.approx(3.5)


def test_the_ladder_prices_and_protection_floors_are_stop_independent():
    a = build_ladder(100.0, 98.0, "LONG", {"tick_size": 0.01}, 110.0, trigger_tf="1d")
    b = build_ladder(100.0, 95.0, "LONG", {"tick_size": 0.01}, 110.0, trigger_tf="1d")
    assert a["targets"] == b["targets"]
    assert a["target_pct"] == b["target_pct"]
    assert a["band_floors"] == b["band_floors"]
    assert a["band_ks"] == b["band_ks"]


def test_no_r_multiple_is_shown_to_him_any_more():
    src = io.open("bot/messages_v7.py", encoding="utf-8").read()
    assert "{r:.2f}R" not in src
    assert "R:R {fade.get('rr')}" not in src
    assert "٪" in src                              # percentages carry the read-out


def test_the_pnl_read_out_comes_from_prices_not_from_the_stop():
    rt = io.open("database/realtime_monitor.py", encoding="utf-8").read()
    repo = io.open("database/repository_v7.py", encoding="utf-8").read()
    for src in (rt, repo):
        assert 'leg_price_move_pct"] = ' in src
        assert "abs(float(_tg" in src or "abs(float(_tgs" in src
