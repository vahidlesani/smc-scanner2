"""Viva 10-10 ENTRY/TP LAW: confirming AFTER the price printed AT or PAST
TP1 is a bug — void with NO exemptions (not even the fresh-break bypass)."""
import os


def test_long_tp_hit_voids_confirm():
    from analysis.quality_engine import _stale_tp_1010
    assert _stale_tp_1010("LONG", 104.0, 100.0, 104.5) is True
    assert _stale_tp_1010("LONG", 104.0, 100.0, 104.0) is True  # exact touch


def test_long_alive_before_tp():
    from analysis.quality_engine import _stale_tp_1010
    assert _stale_tp_1010("LONG", 104.0, 100.0, 101.0) is False


def test_short_tp_hit_voids_confirm():
    from analysis.quality_engine import _stale_tp_1010
    assert _stale_tp_1010("SHORT", 96.0, 100.0, 95.5) is True
    assert _stale_tp_1010("SHORT", 96.0, 100.0, 96.0) is True


def test_short_alive_before_tp():
    from analysis.quality_engine import _stale_tp_1010
    assert _stale_tp_1010("SHORT", 96.0, 100.0, 99.0) is False


def test_degenerate_ladders_fail_open():
    from analysis.quality_engine import _stale_tp_1010
    assert _stale_tp_1010("LONG", 0, 100.0, 150.0) is False        # no TP1
    assert _stale_tp_1010("LONG", 99.0, 100.0, 101.0) is False     # TP1 under entry
    assert _stale_tp_1010("SHORT", 101.0, 100.0, 99.0) is False    # TP1 over entry
    assert _stale_tp_1010("WEIRD", 104.0, 100.0, 105.0) is False   # bad direction
    assert _stale_tp_1010("LONG", "xx", 100.0, 105.0) is False     # garbage


def test_gate_is_wired_into_evaluate_confirmation():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "analysis", "quality_engine.py"),
               encoding="utf-8").read()
    assert "TP_HIT_BEFORE_CONFIRM" in src
    assert "_stale_tp_1010(candidate.direction" in src
