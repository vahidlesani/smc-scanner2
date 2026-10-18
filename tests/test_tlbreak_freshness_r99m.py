"""R99m — TLBREAK stale/late veto (Viva 10-15, FIL-SW: confirmed 7.5h after
the break with live 9% past entry and TP1+TP2 already printed).

Surgery lives in analysis/tlbreak.py ONLY (his per-engine law): the R99i
caller stands down on any non-CONFIRM decision, so no shared file changes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.tlbreak import tlbreak_entry_check as _check


def test_fil_replay_stale_vetoed():
    # Live FIL row viva-FIL-SW-TLBREAK-10141600-EDEC, caller-resolved args:
    # live=tohom close 1.0966, entry=md.entry(live-at-freeze stamp) 1.0968,
    # tp1=candidate.tp1 1.1864589151376148, SHORT.
    _r = _check(broke=True, closed_after_break=True, direction="SHORT",
                live=1.0966, entry=1.0968, tp1=1.1864589151376148)
    assert _r["decision"] != "CONFIRM", _r
    assert any("STALE" in _x or "LATE" in _x for _x in _r["reasons"]), _r


def test_fresh_break_confirms():
    # Healthy SHORT: live at entry, TP1 untouched.
    _r = _check(broke=True, closed_after_break=True, direction="SHORT",
                live=1.1980, entry=1.1984, tp1=1.1785)
    assert _r["decision"] == "CONFIRM", _r


def test_first_close_older_than_two_trigger_bars_is_not_reconfirmed():
    _r = _check(broke=True, closed_after_break=True, direction="LONG",
                live=100.1, entry=100.0, tp1=105.0, break_age_bars=3)
    assert _r["decision"] == "STALE", _r
    assert any("STALE" in reason for reason in _r["reasons"])


def test_fresh_long_confirms():
    _r = _check(broke=True, closed_after_break=True, direction="LONG",
                live=100.1, entry=100.0, tp1=104.0)
    assert _r["decision"] == "CONFIRM", _r


def test_half_chased_vetoed():
    # SHORT: live ate 50% of entry->TP1 before the confirm — chase.
    _r = _check(broke=True, closed_after_break=True, direction="SHORT",
                live=1.1884, entry=1.1984, tp1=1.1785)
    assert _r["decision"] != "CONFIRM", _r


def test_long_beyond_tp1_vetoed():
    _r = _check(broke=True, closed_after_break=True, direction="LONG",
                live=105.0, entry=100.0, tp1=104.0)
    assert _r["decision"] != "CONFIRM", _r


def test_adverse_drift_still_confirms():
    # SHORT with live ABOVE entry (pullback, not chase) is not our veto.
    _r = _check(broke=True, closed_after_break=True, direction="SHORT",
                live=1.2050, entry=1.1984, tp1=1.1785)
    assert _r["decision"] == "CONFIRM", _r


def test_no_break_still_waits():
    _r = _check(broke=False, closed_after_break=False, direction="SHORT",
                live=1.09, entry=1.19, tp1=1.17)
    assert _r["decision"] == "WAIT", _r


def test_missing_levels_fail_open():
    # Garbage in -> old behaviour (confirm), never a freeze.
    _r = _check(broke=True, closed_after_break=True, direction="SHORT",
                live=None, entry=None, tp1=None)
    assert _r["decision"] in ("CONFIRM", "DEFERRED_BUDGET"), _r
