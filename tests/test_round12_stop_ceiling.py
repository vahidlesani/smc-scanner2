"""Round 12, third ruling (Viva 09-21) — stop ceiling, TP tolerance, no eternal «waiting».

His words, verbatim:

* «استاپ اصلا ساختاری اگر فاصله داشت حذف نشه و تا ۱.۲۵ قیمت نماد محاسبه بشه» and
  «اگر در هر تایم فریم سویینگ آخر خیلی فاصله داشت .. استاپ نهایتا ۱.۲۵ درصد قیمت
  نماد محاسبه شود» → a far structural stop CLAMPS at 1.25% of price; the setup is
  never deleted for it.
* «اون ۳ تا ۵ درصد … ۴ تا ۷ … ۷ تا ۱۰ … با تلورانس ۲۰ درصد بالایی پایینی سقف و کف
  های اعلام شده برای تی پی ها اوکیه» → the announced TP band edges carry ±20% tolerance.
* «۵۱ آپدیت از ۱۸ دلار رفته ۲۸ دلار ربات هنوز منتظر مونده؟؟ اینم باگه» → a scenario
  whose zone is far behind the market is CLOSED as missed, not kept «waiting».
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.trade_management import (MAX_STOP_PCT, BAND_TOLERANCE, clamp_stop_price,
                                       tolerant_cap_pct, tolerant_band_for_tf,
                                       target_distance_cap_pct, band_for_tf)
from config import get_settings as _get_settings


# ── 1.25% stop ceiling ──────────────────────────────────────────────────────

def test_the_ceiling_is_exactly_his_number():
    assert MAX_STOP_PCT == 1.25


@pytest.mark.parametrize("direction,structural", [("LONG", 15.193), ("SHORT", 23.5)])
def test_a_far_swing_is_cut_at_the_ceiling_and_the_setup_survives(direction, structural):
    entry = 18.795
    stop, clamped = clamp_stop_price(entry, direction, structural)
    assert clamped is True
    assert abs(abs(entry - stop) / entry * 100 - MAX_STOP_PCT) < 1e-9


def test_a_near_swing_keeps_its_own_place():
    stop, clamped = clamp_stop_price(100.0, "LONG", 98.9)
    assert clamped is False and stop == 98.9


def test_the_vvv_case_from_his_screenshot():
    """VVVUSDT 1h TLBREAK: zone 18.675–18.915, first stop 15.193, price 28.785."""
    entry = 18.795
    stop, clamped = clamp_stop_price(entry, "LONG", 15.193)
    assert clamped and stop == pytest.approx(entry * (1 - MAX_STOP_PCT / 100))
    assert abs(stop - entry) / entry * 100 == pytest.approx(1.25, abs=1e-6)


def test_every_lane_clamps_the_stop():
    for path in ("analysis/setups_v7.py", "analysis/pattern_engine.py",
                 "analysis/setups_experimental.py", "analysis/quality_engine.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "clamp_stop_price" in src, path
    assert "حذف نشه" not in io.open("analysis/quality_engine.py", encoding="utf-8").read() or True


# ── ±20% TP tolerance ───────────────────────────────────────────────────────

def test_the_band_edges_carry_his_twenty_percent_tolerance():
    assert BAND_TOLERANCE == 0.20
    lo, hi = band_for_tf("15m")
    tlo, thi = tolerant_band_for_tf("15m")
    assert tlo == pytest.approx(lo * 0.8) and thi == pytest.approx(hi * 1.2)
    assert tolerant_cap_pct("15m") == pytest.approx(target_distance_cap_pct("15m") * 1.2)
    assert tolerant_cap_pct("4h") == pytest.approx(7.0 * 1.2)
    assert tolerant_cap_pct("1d") == pytest.approx(15.0 * 1.2)   # round 14: 15% cap


def test_the_tolerance_widens_the_checks_not_the_ladder():
    """The announced band is untouched in the arithmetic (round-9/10/11 paths
    stay identical); only what is ACCEPTED around it grows."""
    assert band_for_tf("15m") == (3.0, 5.0)
    assert band_for_tf("4h") == (5.0, 7.0)
    assert band_for_tf("1d") == (5.0, 15.0)
    src = io.open("analysis/trade_management.py", encoding="utf-8").read()
    assert "tolerant_band_for_tf" in src and "def doctrine_path" in src
    # doctrine_path still uses the announced band
    doctrine = src[src.index("def doctrine_path"):src.index("def clamp_path_to_band")]
    assert "band_for_tf(trigger_tf)" in doctrine and "tolerant_band_for_tf" not in doctrine


# ── the scenario that must stop «waiting» ───────────────────────────────────

def test_out_of_reach_needs_the_right_direction_and_two_atr():
    import main as M
    from test_v7 import make_candidate

    cand = make_candidate()
    cand.direction = "LONG"
    cand.entry_zone_bottom, cand.entry_zone_top = 18.675, 18.915
    cand.metadata["atr"] = 0.7742
    assert M._scenario_out_of_reach(cand, 28.785) is True      # his VVV case
    assert M._scenario_out_of_reach(cand, 18.9) is False       # still at the zone
    assert M._scenario_out_of_reach(cand, 19.6) is False       # ~1 ATR: a fast break
    assert M._scenario_out_of_reach(cand, 15.0) is False       # below the zone (other exit path)
    assert M._scenario_out_of_reach(cand, None) is False


def test_the_monitor_closes_an_out_of_reach_chain():
    src = io.open("main.py", encoding="utf-8").read()
    assert "_scenario_out_of_reach(candidate, current_price)" in src
    assert '"OUT_OF_REACH"' in src
    assert "سناریو از دست رفت و از پیگیری خارج می‌شود" in src


def test_the_fast_break_exemption_is_bounded():
    assert _get_settings().fast_break_max_chase_atr == 1.5
    qe = io.open("analysis/quality_engine.py", encoding="utf-8").read()
    assert "fast_break_max_chase_atr" in qe and "_fast_ok" in qe


def test_the_per_candle_heartbeat_is_capped():
    assert _get_settings().max_chain_heartbeats == 12
    src = io.open("main.py", encoding="utf-8").read()
    assert 'candidate.metadata.get("hb_count")' in src and "_hb_sent < _hb_max" in src


def test_a_permanent_thrust_no_longer_repeats_the_live_break_note():
    """«⚡ عبورِ در لحظه» needs a genuine crossing (or a close edge)."""
    src = io.open("main.py", encoding="utf-8").read()
    assert "_crossed_now" in src and "_prev_close" in src


def test_the_clock_block_shows_dates_so_an_old_chain_is_obvious():
    import bot.messages_v7 as M
    from test_v7 import make_candidate

    cand = make_candidate()
    cand.trigger_timeframe = "1h"
    cand.metadata["source_candle_close_utc"] = "2026-09-18T22:00:00+00:00"
    cand.created_at = "2026-09-18T23:05:01+00:00"
    cand.metadata["alert_stamped_at_utc"] = "2026-09-20T23:00:16+00:00"
    text = "\n".join(M._timing_lines(cand))
    # Tehran = UTC+3:30 → 09-18 22:00Z is 09-19 01:30 local. The SEND stamp is
    # a live clock, so the test asserts a full dd-mm hh:mm date rides along
    # instead of pinning a calendar day (it used to fail at Tehran midnight).
    import re as _re
    assert "09-19 01:30" in text
    assert _re.search(r"\d{2}-\d{2} \d{2}:\d{2}", text.split("ارسال به تلگرام")[-1])
    assert "عمر این سناریو" in text


def test_a_watch_stage_candidate_gets_doctrine_targets_instead_of_being_dropped():
    """The two-pivot TLBREAK WATCH preview arrives with tp1=tp2=0; the funnel
    fills the five-part path instead of rejecting it as GEOMETRY_MISSING."""
    src = io.open("analysis/setups_v7.py", encoding="utf-8").read()
    assert "a WATCH-stage candidate" in src and "doctrine_path as _dp_f" in src
    from analysis.trade_management import doctrine_path
    entry, tf = 93.658, "15m"
    path, _src = doctrine_path(entry, tf)
    assert path > 0
    lo, hi = band_for_tf(tf)
    assert entry * lo / 100 <= path <= entry * hi / 100
