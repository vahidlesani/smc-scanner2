"""R99q27 — the daily licence share must be spent ACROSS the day, not in a burst.

His 10-19 evidence, read straight out of the production KV that evening:

    tier_day_setup:2026-10-19:ALBROX      = 25   last spent 01:32 UTC
    tier_day_setup:2026-10-19:PINVAL      = 25   last spent 01:02 UTC
    tier_day_setup:2026-10-19:TECHCLASSIC = 25   last spent 06:34 UTC
    tier_day_setup:2026-10-19:TLBREAK     = 25   last spent 07:02 UTC

with `pace = ceil(175/7) = 25` on the Monday of the week. Every setup hit the
wall before 10:30 Tehran and stayed silent for the remaining ~17 hours — the
exact «از ساعت ۱۰ صبح هیچ هشداری نیامده».

The weekly cap is HIS law and does not move here. What moves is only the
SHAPE of the spend: hour h of the UTC day may release ceil(pace*(h+1)/24).
"""
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _wire(monkeypatch, *, used_week, today_used, cap=200):
    from analysis import tiered_scan as ts

    monkeypatch.setattr(ts, "weekly_count", lambda *a, **k: used_week)
    monkeypatch.setattr(ts, "weekly_licence_cap", lambda *a, **k: cap)
    monkeypatch.setattr(ts, "daily_setup_count", lambda *a, **k: today_used)
    monkeypatch.delenv("VIVA_WEEKLY_PACE", raising=False)
    monkeypatch.delenv("VIVA_WEEKLY_PACE_SPREAD", raising=False)
    return ts


def _at(hour, day=19, month=10, year=2026):
    return datetime(year, month, day, hour, 0, tzinfo=timezone.utc)


def test_the_monday_burst_that_caused_the_drought_is_now_refused(monkeypatch):
    """The measured production numbers: 25 spent, pace 25."""
    ts = _wire(monkeypatch, used_week=25, today_used=25)
    # the old rule only looked at the pace, so 01:00 let all 25 out
    assert ts.weekly_pace_ok("PINVAL", now=_at(1)) is False
    assert ts.weekly_pace_ok("PINVAL", now=_at(6)) is False
    assert ts.weekly_pace_ok("PINVAL", now=_at(12)) is False


def test_the_same_quota_is_still_fully_spendable_late_in_the_day(monkeypatch):
    """Nothing is taken away — the wall only arrives later."""
    ts = _wire(monkeypatch, used_week=25, today_used=24)
    assert ts.weekly_pace_ok("PINVAL", now=_at(23)) is True      # 24 < 25
    assert ts.weekly_pace_ok("PINVAL", now=_at(23)) is True
    ts2 = _wire(monkeypatch, used_week=25, today_used=25)
    assert ts2.weekly_pace_ok("PINVAL", now=_at(23)) is False    # 25 < 25


def test_the_release_is_monotonic_across_the_day(monkeypatch):
    """Allowance can only grow; it never steps backwards."""
    ts = _wire(monkeypatch, used_week=25, today_used=0)
    seen = []
    for h in range(24):
        # binary-search the largest today_used the rule still allows
        lo = 0
        for n in range(0, 40):
            monkeypatch.setattr(ts, "daily_setup_count", lambda *a, **k: n)
            if not ts.weekly_pace_ok("PINVAL", now=_at(h)):
                break
            lo = n + 1
        seen.append(lo)
    assert seen == sorted(seen), seen
    assert seen[0] <= 2, seen          # midnight releases almost nothing
    assert seen[-1] == 25, seen        # 23:00 releases the whole share


def test_the_morning_can_no_longer_burn_the_whole_day(monkeypatch):
    ts = _wire(monkeypatch, used_week=25, today_used=0)
    allowed_at_1, allowed_at_23 = 0, 0
    for n in range(0, 40):
        monkeypatch.setattr(ts, "daily_setup_count", lambda *a, **k: n)
        if ts.weekly_pace_ok("PINVAL", now=_at(1)):
            allowed_at_1 = n + 1
        if ts.weekly_pace_ok("PINVAL", now=_at(23)):
            allowed_at_23 = n + 1
    assert allowed_at_1 <= 3, allowed_at_1          # 01:00 UTC ≈ 04:30 Tehran
    assert allowed_at_23 == 25


def test_the_weekly_wallet_is_still_the_ceiling(monkeypatch):
    ts = _wire(monkeypatch, used_week=200, today_used=0)
    assert ts.weekly_pace_ok("PINVAL", now=_at(23)) is False


def test_flat_switch_restores_yesterdays_rule(monkeypatch):
    ts = _wire(monkeypatch, used_week=25, today_used=25)
    monkeypatch.setenv("VIVA_WEEKLY_PACE_SPREAD", "0")
    assert ts.weekly_pace_ok("PINVAL", now=_at(1)) is False
    monkeypatch.setattr(ts, "daily_setup_count", lambda *a, **k: 24)
    assert ts.weekly_pace_ok("PINVAL", now=_at(1)) is True


def test_the_global_switch_still_disables_pacing(monkeypatch):
    ts = _wire(monkeypatch, used_week=25, today_used=25)
    monkeypatch.setenv("VIVA_WEEKLY_PACE", "0")
    assert ts.weekly_pace_ok("PINVAL", now=_at(1)) is True
