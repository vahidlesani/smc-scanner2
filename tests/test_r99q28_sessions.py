"""R99q28 — trading-session licences (Viva 10-19).

«سشن های معاملاتی رو مشخص بکنی ... نیویورک ۱۵ مجوز، لندن ۱۵، توکیو ۱۰ ... بقیه
 اوقات بین سشن ها کلا اسکن قطع بشه .. از ۱۵ دقیقه قبل از هر سشن»

The weekly wallet stays the outer ceiling; sessions shape the day. Everything
here is fail-open and switchable.
"""
import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analysis import trading_sessions as ts  # noqa: E402


def _at(h, m=0):
    return datetime(2026, 10, 19, h, m, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("VIVA_SESSION_LICENCES", "VIVA_SESSION_SCAN_GATE",
              "VIVA_SESSION_PREROLL_MIN", "VIVA_SESSION_TOKYO_LICENCE",
              "VIVA_SESSION_LONDON_LICENCE", "VIVA_SESSION_NEWYORK_LICENCE"):
        monkeypatch.delenv(k, raising=False)
    yield


def test_the_three_sessions_exist_with_his_counts():
    assert ts.session_licence_cap("TOKYO") == 10
    assert ts.session_licence_cap("LONDON") == 15
    assert ts.session_licence_cap("NEWYORK") == 15


def test_session_counts_are_env_tunable(monkeypatch):
    monkeypatch.setenv("VIVA_SESSION_TOKYO_LICENCE", "4")
    assert ts.session_licence_cap("TOKYO") == 4


def test_the_pre_roll_opens_discovery_early():
    # Tokyo is 00:00–09:00; the 15-minute pre-roll opens at 23:45
    assert ts.in_scan_window(_at(23, 50)) is True
    assert ts.current_session(_at(23, 50)) == "TOKYO"
    assert ts.in_scan_window(_at(23, 30)) is False


def test_between_sessions_discovery_is_paused_but_not_the_monitor():
    """21:30–23:45 UTC has no session: discovery pauses. The monitor loop is a
    different function and is deliberately not gated here."""
    assert ts.in_scan_window(_at(22)) is False
    assert ts.current_session(_at(22)) is None


def test_the_newest_session_wins_the_overlap():
    # 13:00 UTC: London (07–16) AND New York (12–21) are both open
    assert ts.current_session(_at(13)) == "NEWYORK"
    # 08:00: Tokyo (00–09) and London (07–16) overlap → London
    assert ts.current_session(_at(8)) == "LONDON"


def test_the_scan_gate_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("VIVA_SESSION_SCAN_GATE", "0")
    assert ts.in_scan_window(_at(22)) is True


def test_licences_stop_at_the_cap_and_the_count_is_per_setup(monkeypatch):
    store = {}

    class _KV:
        def get_json(self, k, d=None):
            return store.get(k, d)

        def set_json(self, k, v):
            store[k] = v

    monkeypatch.setattr(ts, "_kv", lambda: _KV())
    now = _at(3)                                   # Tokyo
    for i in range(10):
        assert ts.session_licence_ok("TLBREAK", now) is True
        ts.session_licence_incr("TLBREAK", now)
    assert ts.session_licence_ok("TLBREAK", now) is False
    # another setup has its own book
    assert ts.session_licence_ok("PINVAL", now) is True


def test_disabling_the_rule_restores_the_old_behaviour(monkeypatch):
    monkeypatch.setenv("VIVA_SESSION_LICENCES", "0")
    assert ts.session_licence_ok("TLBREAK", _at(22)) is True


def test_a_kv_failure_never_silences_the_bot(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(ts, "_kv", _boom)
    assert ts.session_licence_ok("TLBREAK", _at(3)) is True


def test_main_wires_both_lanes_and_spot_is_unlimited():
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "session_licence_ok(" in src
    assert "session_licence_incr(" in src
    assert "in_scan_window()" in src
    assert "VIVA_SPOT_UNLIMITED" in src
