import importlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from analysis.models import EvidenceItem, SignalCandidate


def _candidate() -> SignalCandidate:
    now = datetime.now(timezone.utc)
    return SignalCandidate(
        signal_id="cache-egress-1",
        symbol="CACHEUSDT",
        style="DAYTRADE",
        setup_code="TLBREAK",
        setup_name="cache probe",
        strategy_fa="cache probe",
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
        evidence=[EvidenceItem("cache", "cache", "cache", True, 1)],
        metadata={"atr": 1.0, "blob": "x" * 30_000},
        created_at=now.isoformat(timespec="seconds"),
        expires_at=(now + timedelta(hours=6)).isoformat(timespec="seconds"),
    )


def test_active_payload_reconciliation_defaults_to_fifteen_minutes(monkeypatch):
    monkeypatch.delenv("CANDIDATE_ACTIVE_CACHE_SECONDS", raising=False)
    import database.candidate_store as store
    assert store._active_cache_seconds() == 900.0


def test_active_payload_is_read_once_then_kept_write_through(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDIDATE_DB_BACKEND", "sqlite")
    monkeypatch.setenv("CANDIDATE_DB_PATH", str(tmp_path / "candidate-cache.sqlite"))
    monkeypatch.setenv("CANDIDATE_ACTIVE_CACHE_SECONDS", "300")

    import database.candidate_store as store
    store = importlib.reload(store)
    store.init_candidate_store()
    candidate = _candidate()
    assert store.add_candidate(candidate)

    real_connection = store._connection
    reads = {"active": 0}

    @contextmanager
    def counted_connection():
        with real_connection() as raw:
            class Proxy:
                def __getattr__(self, name):
                    return getattr(raw, name)

                def execute(self, sql, params=()):
                    if "SELECT signal_id, created_at, payload FROM signal_candidates" in sql:
                        reads["active"] += 1
                    return raw.execute(sql, params)

            yield Proxy()

    monkeypatch.setattr(store, "_connection", counted_connection)

    first = store.get_active_candidates()
    second = store.get_active_candidates()
    assert [item.signal_id for item in first] == [candidate.signal_id]
    assert [item.signal_id for item in second] == [candidate.signal_id]
    assert reads["active"] == 1

    candidate.score = 9
    store.update_candidate(candidate)
    assert store.get_active_candidates()[0].score == 9
    assert reads["active"] == 1  # the write updated the immutable JSON cache

    store.update_candidate(candidate, status="EXPIRED")
    assert store.get_active_candidates() == []
    assert reads["active"] == 1
