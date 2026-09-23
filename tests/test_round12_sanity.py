"""Round 12, second pass — «مطمئنم هنوز باگ داریم در برخی منطق ها یا ستاپها».

The first round-12 pass put the stop-horizon gate INSIDE one builder, so a
detector that assembles its own candidate (TECHCLASSIC) could still override the
stop and the targets after that gate and publish nonsense:

* DASH 15m SHORT — stop 24% away, target 34% away (measured-move projection);
* DASH 15m LONG — the stop sat ABOVE the entry the message showed, because only
  the stop had been rebuilt on the live price while the entry stayed at the POI
  middle.

These tests freeze the fixes: the central net in ``setups_v7.sanity_reject``,
the band clamp for projected distances, and the coherence of the entry a
candidate trades from.
"""

import pytest

from analysis.setups_v7 import sanity_reject, scan_setups, _SANITY_REJECT_LOG
from analysis.pattern_engine import measured_target
from analysis.trade_management import clamp_path_to_band, doctrine_path, band_for_tf


class _Cand:
    """Minimal stand-in for SignalCandidate (the net reads six fields)."""

    def __init__(self, direction="LONG", entry=100.0, sl=98.0, tp1=101.0, tp2=103.0,
                 tf="15m"):
        self.direction = direction
        self.planned_entry = entry
        self.sl = sl
        self.tp1 = tp1
        self.tp2 = tp2
        self.trigger_timeframe = tf
        self.symbol = "TESTUSDT"
        self.setup_code = "TEST"
        self.score = 7.0
        self.execution_ready = True


# ── the net ──────────────────────────────────────────────────────────────────

def test_long_stop_above_entry_is_rejected():
    """The DASH 15m case: a LONG carrying its stop above the entry."""
    assert sanity_reject(_Cand(direction="LONG", entry=54.42, sl=56.18,
                               tp1=55.0, tp2=57.0)) == "STOP_WRONG_SIDE"


def test_short_stop_below_entry_is_rejected():
    assert sanity_reject(_Cand(direction="SHORT", entry=100.0, sl=99.0,
                               tp1=99.0, tp2=97.0)) == "STOP_WRONG_SIDE"


def test_stop_farther_than_the_timeframe_horizon_is_rejected():
    """DASH 15m: a 24% stop against a 5% horizon."""
    assert sanity_reject(_Cand(direction="LONG", entry=54.4, sl=41.3,
                               tp1=55.0, tp2=57.0)) == "STOP_HORIZON"


def test_target_farther_than_the_timeframe_horizon_is_rejected():
    """The same candle also carried a 34% target (the measured move)."""
    assert sanity_reject(_Cand(direction="SHORT", entry=59.58, sl=60.0,
                               tp1=58.0, tp2=39.44)) == "TARGET_HORIZON"


def test_target_on_the_wrong_side_is_rejected():
    assert sanity_reject(_Cand(direction="LONG", entry=100.0, sl=98.0,
                               tp1=101.0, tp2=97.0)) == "TARGET_WRONG_SIDE"


def test_a_honest_candidate_passes_every_check():
    # round 14: a 15m stop lives inside 1.25% of price («۱.۲۵ صدم استاپ برای ۱۵ دقیقه»)
    assert sanity_reject(_Cand(direction="LONG", entry=100.0, sl=99.0,
                               tp1=101.3, tp2=104.0)) is None
    assert sanity_reject(_Cand(direction="SHORT", entry=100.0, sl=101.0,
                               tp1=98.7, tp2=96.0)) is None
    # 1.5% fits INSIDE the widened (09-23) 15m ceiling of 2.0%…
    assert sanity_reject(_Cand(direction="LONG", entry=100.0, sl=98.5,
                               tp1=101.3, tp2=104.0)) is None
    # …and 2.5% on the same 15m is genuinely past its ceiling now
    assert sanity_reject(_Cand(direction="LONG", entry=100.0, sl=97.5,
                               tp1=101.3, tp2=104.0)) == "STOP_HORIZON"


def test_the_net_runs_on_every_published_candidate():
    """scan_setups applies the net after the detectors, before the cap."""
    src = open("analysis/setups_v7.py", encoding="utf-8").read()
    assert "why = sanity_reject(cand)" in src
    assert src.index("why = sanity_reject(cand)") > src.index("def scan_setups(")
    assert "return kept[:4]" in src


# ── the projected distance (measured move) ───────────────────────────────────

def test_projected_distance_inside_the_band_keeps_its_own_value():
    entry = 100.0
    path, src = clamp_path_to_band(entry, "15m", entry * 0.04)
    assert abs(path - entry * 0.04) < 1e-9 and src == "MEASURED"


def test_projected_distance_beyond_the_ceiling_is_capped():
    entry = 59.58
    path, src = clamp_path_to_band(entry, "15m", entry * 0.34)  # the 34% DASH case
    assert src == "MEASURED_CAPPED"
    assert abs(path - entry * 0.05) < 1e-6  # 15m ceiling = 5%


def test_projected_distance_below_the_floor_is_lifted_to_the_floor():
    entry = 100.0
    path, src = clamp_path_to_band(entry, "15m", entry * 0.005)  # 0.5% projection
    lo, _hi = band_for_tf("15m")
    assert src == "MEASURED_FLOORED"
    assert abs(path - entry * lo / 100.0) < 1e-9


def test_measured_target_helper_returns_a_side_correct_target():
    long_to = measured_target(100.0, "LONG", "15m", 134.0)[0]
    short_to = measured_target(100.0, "SHORT", "15m", 66.0)[0]
    assert 0 < long_to - 100.0 <= 100.0 * 0.05 + 1e-6
    assert 0 < 100.0 - short_to <= 100.0 * 0.05 + 1e-6


def test_doctrine_path_still_owns_real_levels():
    """The round-11 law is untouched: a real level inside the band is the path."""
    entry = 100.0
    path, src = doctrine_path(entry, "15m", level=entry * 1.04)
    assert src == "STRUCTURE_LEVEL" and abs(path - entry * 0.04) < 1e-9
