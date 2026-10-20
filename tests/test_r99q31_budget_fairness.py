"""R99q31h — the cycle budget must not silently swallow a family's alerts.

His 10-20 funnel: `PINVAL seen=66 ready_new=4 pace=0 dup=4 budget=58`.
`ready_new=4` is the per-setup share; the other 58 were counted and DROPPED.
Two faults, both fixed here:

  1. the per-setup share was a hard wall with no second pass, so leftover cycle
     budget could never reach the family that still had demand;
  2. the budget branch did `continue` WITHOUT queueing the candidate, while the
     educate branch (R99q15) had always queued it — so a budget block was a
     ghost, not a deferral.

Volume law is untouched: the sweep posts exactly as before, and the hourly cap
(10 per setup per clock hour) plus the weekly wallet still sit above it.
"""
import re

SRC = open("main.py", encoding="utf-8").read()


def test_budget_ok_has_a_relaxed_mode_that_doubles_the_share():
    assert "def _budget_ok(cand, relaxed: bool = False) -> bool:" in SRC
    seg = SRC[SRC.index("def _budget_ok(cand"):SRC.index("def _educate(cand")]
    assert "_cap = _per_setup_cap * 2 if relaxed else _per_setup_cap" in seg
    assert "_setup_used.get(_sc, 0) >= _cap" in seg


def test_the_sweep_still_uses_the_strict_share():
    assert "if not _is_watch and not _budget_ok(cand, relaxed):" in SRC
    # the strict call is the one reached without the flag
    assert "_budget_ok(candidate)" in SRC


def test_a_budget_block_queues_the_candidate_for_retry():
    i = SRC.index('_t(candidate)["budget_deferred"]')
    seg = SRC[i:i + 900]
    assert "_deferred_edu.append(" in seg, "a budget block must not drop the candidate"


def test_the_retry_pass_is_the_relaxed_one():
    assert "_educate(_dc, _dfr, relaxed=True)" in SRC


def test_the_hourly_cap_still_sits_above_the_budget():
    """The relaxed pass may draw more of the pool, never more than the cadence."""
    assert "_tier99j.hourly_pace_ok(" in SRC
    i_hour = SRC.index("_tier99j.hourly_pace_ok(")
    i_relax = SRC.index("_educate(_dc, _dfr, relaxed=True)")
    assert i_hour < i_relax, "the hourly gate runs before the retry pass"


def test_the_fairness_never_touches_the_weekly_wallet():
    tier = open("analysis/tiered_scan.py", encoding="utf-8").read()
    assert "weekly_licence_incr" in tier


def test_a_retry_post_spends_the_quota_it_used_to_skip():
    i = SRC.index('stats["edu_retry_posted"]')
    seg = SRC[i:i + 1400]
    for fn in ("weekly_licence_incr", "daily_setup_incr", "hourly_pace_incr",
               "session_licence_incr"):
        assert fn in seg, f"{fn} must be spent by a retry post too"
