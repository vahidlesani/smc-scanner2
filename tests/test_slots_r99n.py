"""R99n — per-setup concurrent slots (Viva 10-15: no global pool)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import tiered_scan as _ts


def test_each_setup_owns_30():
    for _s in ("PINVAL", "ALBROX", "TLBREAK", "TECHCLASSIC", "SPOT"):
        assert _ts.setup_cap(_s) == 30, _s


def test_env_override_per_setup(monkeypatch):
    monkeypatch.setenv("TLBREAK_MAX_CONCURRENT_CHAINS", "5")
    assert _ts.setup_cap("TLBREAK") == 5
    assert _ts.setup_cap("PINVAL") == 30  # neighbour untouched


def test_unknown_setup_fail_open_30():
    assert _ts.setup_cap("SOMETHING_NEW") == 30


def test_count_groups_by_setup():
    _rows = [SimpleNamespace(setup_code="PINVAL")] * 24 + [
        SimpleNamespace(setup_code="tlbreak")]
    _by = _ts.count_open_by_setup(_rows)
    assert _by == {"PINVAL": 24, "TLBREAK": 1}, _by


def test_full_book_never_starves_neighbour():
    _by = {"PINVAL": 30, "TLBREAK": 0}
    assert _ts.concurrent_ok_for_setup("PINVAL", _by) is False
    assert _ts.concurrent_ok_for_setup("TLBREAK", _by) is True


def test_boundary_29_passes_30_blocks():
    assert _ts.concurrent_ok_for_setup("PINVAL", {"PINVAL": 29}) is True
    assert _ts.concurrent_ok_for_setup("PINVAL", {"PINVAL": 30}) is False


def test_garbage_fails_open():
    assert _ts.concurrent_ok_for_setup(None, None) is True
    assert _ts.concurrent_ok_for_setup("PINVAL", None) is True


def test_global_gate_untouched():
    # The old global gate still exists (behaviour preserved for any caller).
    assert _ts.concurrent_ok(2) is True
    assert _ts.concurrent_ok(3) is False
