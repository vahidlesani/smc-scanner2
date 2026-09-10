"""Durability tests (Viva 2026-09-10): state must survive a redeploy.

The suite runs with DATABASE_URL set in the sandbox (Supabase) — exercising
the SAME Postgres path production uses; without it, the SQLite fallback is
covered. Both branches go through identical assertions.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analysis.models as models  # noqa: E402
from analysis.models import SignalCandidate, iso_now  # noqa: E402


def _candidate(status="EDUCATIONAL"):
    from datetime import datetime, timedelta, timezone
    exp = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(timespec="seconds")
    return SignalCandidate(
        signal_id=f"durtest-{uuid.uuid4().hex[:10]}", symbol="DURTESTUSDT",
        style="SWING", setup_code="TECHCLASSIC", setup_name="durability probe",
        strategy_fa="آزمون تداوم", direction="LONG", score=7, status=status,
        entry_zone_bottom=99.0, entry_zone_top=101.0, planned_entry=100.0,
        sl=98.0, tp1=106.0, tp2=110.0, rr_tp1=3.0, rr_tp2=5.0,
        bias="BULLISH", trigger_timeframe="4h", expires_at=exp,
    )


def test_candidate_store_roundtrip_and_idempotent_insert():
    from database.candidate_store import (add_candidate, find_similar,
                                          init_candidate_store, set_status,
                                          update_candidate, _use_pg)
    init_candidate_store()
    c = _candidate()
    assert add_candidate(c) is True
    again = add_candidate(c)  # same signal_id + same lineage -> refused
    assert again is False
    got = find_similar(c)
    assert got is not None and got.signal_id == c.signal_id
    set_status(c.signal_id, "EXPIRED")
    update_candidate(c, status="CONFIRMED")
    # cleanup path runs without exception on this backend too
    from database.candidate_store import cleanup_candidates
    cleanup_candidates()
    # purge test rows
    import sqlite3
    if _use_pg():
        from database.candidate_store import _pg_connect, _pg_sql
        conn = _pg_connect()
        conn.cursor().execute(_pg_sql("DELETE FROM signal_candidates WHERE signal_id=?"), (c.signal_id,))
        conn.commit()
        conn.close()
    else:
        conn = sqlite3.connect(os.getenv("CANDIDATE_DB_PATH", "/tmp/viva_candidates.db"))
        conn.execute("DELETE FROM signal_candidates WHERE signal_id=?", (c.signal_id,))
        conn.commit()
        conn.close()


def test_bot_kv_roundtrip():
    from database.bot_kv import get_json, set_json
    key = f"unittest_kv_{uuid.uuid4().hex[:8]}"
    try:
        assert get_json(key, None) is None
        assert set_json(key, {"a": 1, "ب": "متن فارسی"}) is True
        back = get_json(key, {})
        assert back["a"] == 1 and back["ب"] == "متن فارسی"
        assert set_json(key, {"a": 2}) is True  # upsert path
        assert get_json(key, {})["a"] == 2
    finally:
        from database.candidate_store import _connection, _use_pg
        with _connection() as conn:
            conn.execute("DELETE FROM bot_kv WHERE key=?", (key,))


def test_technoclassic_cooldown_survives_process_restart():
    """Simulate a redeploy: the in-memory stamp dict is thrown away; the
    second call must STILL be blocked, because the stamp was persisted."""
    import analysis.pattern_engine as m
    from database.bot_kv import set_json
    set_json(m._KV_KEY, {})          # start clean
    m._ALERT_SEEN = None
    key = f"UNITTEST|4h|WEDGE_FALLING|EDGE_NEAR|upper"
    try:
        assert m._cooldown_ok(key, m.STATE_NEAR) is True
        assert m._cooldown_ok(key, m.STATE_NEAR) is False   # in-memory guard
        m._ALERT_SEEN = None                                  # simulate restart
        assert m._cooldown_ok(key, m.STATE_NEAR) is False   # durable guard
    finally:
        set_json(m._KV_KEY, {})
        m._ALERT_SEEN = None


def test_pg_sql_adapter_shape():
    from database.candidate_store import _pg_sql
    out = _pg_sql("SELECT a FROM t WHERE x=? AND y>=?")
    assert "%s" in out and "?" not in out
