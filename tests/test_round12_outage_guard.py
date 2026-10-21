"""Round-12 incident — «چرا تعداد شناسایی‌ها و آپدیت‌ها قطع شد؟».

Timeline of the outage (2026-09-21):
  * a connection of our own app stayed **idle in transaction** and held ACCESS
    SHARE on signal_candidates / signals for ~25 minutes;
  * the boot migrations (``ALTER TABLE … ADD COLUMN IF NOT EXISTS``) need ACCESS
    EXCLUSIVE, queued behind those locks and were cancelled by the database's
    2-minute statement_timeout;
  * ``combined_service._run_scanner`` treated that as fatal and called
    ``os._exit(1)`` → container restart → same lock → same crash: a loop with the
    dashboard up and the scanner dead. Detections, updates and monitors stopped
    while the deployment itself reported SUCCESS.

These tests freeze the four fixes: check-first migrations, guarded DDL that is
never fatal, non-fatal boot steps, and a scanner that restarts itself instead of
leaving the process silent.
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import combined_service  # noqa: E402
from database import candidate_store  # noqa: E402


class _FakeConn:
    """Records SQL; can be told to explode on ALTER (the lock/st timeout case)."""

    def __init__(self, existing_columns=(), fail_on=()):
        self.existing = set(existing_columns)
        self.fail_on = tuple(fail_on)
        self.sql = []
        self.followups = []

    def execute(self, sql, params=()):
        self.sql.append(sql.strip())
        up = sql.upper()
        if "INFORMATION_SCHEMA.COLUMNS" in up:
            hit = any(c in self.existing for c in (params or ()))
            self._row = {"ok": 1} if hit else None
            return self
        for token in self.fail_on:
            if token in sql:
                raise RuntimeError("canceling statement due to statement timeout")
        self._row = None
        return self

    def fetchone(self):
        return getattr(self, "_row", None)

    def fetchall(self):
        return []


def _patch_connection(monkeypatch, conn):
    import time
    from contextlib import contextmanager

    @contextmanager
    def _fake():
        yield conn

    monkeypatch.setattr(candidate_store, "_connection", _fake)
    monkeypatch.setattr(candidate_store, "_use_pg", lambda: True)
    # the guarded DDL backs off between attempts — instant in tests
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def test_existing_trigger_tf_column_never_triggers_an_alter(monkeypatch):
    """Check-first: in steady state we do not even ask for the exclusive lock."""
    conn = _FakeConn(existing_columns=("trigger_tf",))
    _patch_connection(monkeypatch, conn)
    candidate_store.init_candidate_store()
    assert not any(sql.upper().startswith("ALTER TABLE") for sql in conn.sql), conn.sql


def test_a_blocked_migration_is_never_fatal(monkeypatch):
    """The ALTER may time out — the scanner must still boot."""
    conn = _FakeConn(existing_columns=(), fail_on=("ALTER TABLE",))
    _patch_connection(monkeypatch, conn)
    candidate_store.init_candidate_store()  # must not raise
    assert any(sql.upper().startswith("ALTER TABLE") for sql in conn.sql)


def test_migration_asks_for_a_short_lock_timeout(monkeypatch):
    conn = _FakeConn(existing_columns=(), fail_on=("ALTER TABLE",))
    _patch_connection(monkeypatch, conn)
    candidate_store.init_candidate_store()
    assert any("lock_timeout" in sql.lower() for sql in conn.sql), conn.sql


def test_connections_carry_the_idle_in_transaction_guard():
    """No leaked transaction may hold a lock for 25 minutes again."""
    src = open("database/db.py", encoding="utf-8").read()
    assert "idle_in_transaction_session_timeout" in src
    assert "application_name" in src
    src2 = open("database/candidate_store.py", encoding="utf-8").read()
    assert "idle_in_transaction_session_timeout" in src2


def test_postgres_migration_only_alters_missing_columns():
    """repository_v7: one leaked reader must not make every ALTER queue."""
    src = open("database/repository_v7.py", encoding="utf-8").read()
    assert "missing = {k: v for k, v in definitions.items() if k not in existing}" in src
    assert "SET LOCAL lock_timeout" in src


def test_boot_steps_are_retried_and_not_fatal():
    src = open("main.py", encoding="utf-8").read()
    assert "for _label, _fn in ((\"candidate store\", init_candidate_store)," in src
    assert "scanner continues" in src


def test_scanner_thread_restarts_itself_instead_of_dying(monkeypatch):
    """A startup failure restarts the scanner loop; it is not an instant exit."""
    calls = {"n": 0, "slept": [], "exit": []}

    def _flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("blocked schema migration")

    monkeypatch.setattr(combined_service, "scanner_main", _flaky)
    monkeypatch.setattr(combined_service.os, "_exit", lambda code: calls["exit"].append(code))
    monkeypatch.setattr(combined_service.time, "sleep", lambda s: calls["slept"].append(s))
    combined_service._run_scanner()
    assert calls["n"] == 2, "the scanner was not restarted after the failure"
    assert calls["slept"] == [5], calls["slept"]
    assert calls["exit"] == [], "the container was taken down on the first failure"


def test_repeated_instant_failures_still_let_railway_rebuild(monkeypatch):
    calls = {"n": 0, "exit": []}

    def _always():
        calls["n"] += 1
        raise RuntimeError("db gone")

    monkeypatch.setattr(combined_service, "scanner_main", _always)

    def _fake_exit(code):
        calls["exit"].append(code)
        raise SystemExit(code)

    monkeypatch.setattr(combined_service.os, "_exit", _fake_exit)
    monkeypatch.setattr(combined_service.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):
        combined_service._run_scanner()
    assert calls["exit"] == [1]
