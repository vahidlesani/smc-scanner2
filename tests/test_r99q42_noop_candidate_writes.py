from datetime import datetime, timedelta, timezone
import inspect

from analysis.models import SignalCandidate
from main import (
    _candidate_lock_fingerprint,
    _candidate_persist_fingerprint,
    monitor_candidates,
)


def _candidate() -> SignalCandidate:
    now = datetime.now(timezone.utc)
    return SignalCandidate(
        signal_id="noop-write-1",
        symbol="QUIETUSDT",
        style="DAYTRADE",
        setup_code="PINVAL",
        setup_name="quiet probe",
        strategy_fa="quiet probe",
        direction="LONG",
        score=8,
        status="EDUCATIONAL",
        entry_zone_bottom=99.8,
        entry_zone_top=100.2,
        planned_entry=100.0,
        sl=98.0,
        tp1=103.0,
        tp2=106.0,
        rr_tp1=1.5,
        rr_tp2=3.0,
        bias="BULLISH",
        trigger_timeframe="15m",
        metadata={"atr": 1.0, "last_reject_code": "NO_NEW_BAR"},
        created_at=now.isoformat(timespec="seconds"),
        expires_at=(now + timedelta(hours=6)).isoformat(timespec="seconds"),
    )


def test_quiet_tick_has_identical_durable_payload_and_lock():
    candidate = _candidate()
    payload = _candidate_persist_fingerprint(candidate)
    lock = _candidate_lock_fingerprint(candidate)

    # Re-applying the same verdict is what most 10-second ticks do.
    candidate.metadata["last_reject_code"] = "NO_NEW_BAR"
    assert _candidate_persist_fingerprint(candidate) == payload
    assert _candidate_lock_fingerprint(candidate) == lock


def test_metadata_change_writes_candidate_but_not_lock():
    candidate = _candidate()
    payload = _candidate_persist_fingerprint(candidate)
    lock = _candidate_lock_fingerprint(candidate)

    candidate.metadata["stage_a_sent"] = True
    assert _candidate_persist_fingerprint(candidate) != payload
    assert _candidate_lock_fingerprint(candidate) == lock


def test_status_or_expiry_transition_updates_the_lock():
    candidate = _candidate()
    lock = _candidate_lock_fingerprint(candidate)
    candidate.status = "APPROACHING"
    assert _candidate_lock_fingerprint(candidate) != lock

    lock = _candidate_lock_fingerprint(candidate)
    candidate.expires_at = (datetime.now(timezone.utc) + timedelta(hours=7)).isoformat(
        timespec="seconds"
    )
    assert _candidate_lock_fingerprint(candidate) != lock


def test_monitor_writes_only_on_fingerprint_transition():
    source = inspect.getsource(monitor_candidates)
    assert "_payload42 != _persisted_payload.get" in source
    assert "_lock42 != _persisted_lock.get" in source
