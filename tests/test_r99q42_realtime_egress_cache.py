from contextlib import contextmanager
import inspect

import database.realtime_monitor as realtime
import database.repository_v7 as repository


def test_pending_plan_rows_are_reused_until_a_lifecycle_write(monkeypatch):
    calls = {"select": 0}
    sample = [("sig-1", "BTCUSDT", "LONG", 100.0, 98.0, 5, 20.0,
               "DAYTRADE", "2026-10-22 00:00:00", "PINVAL", "Pinval",
               "smc-core-7.0", 0, "{}", "VIVA-P000001", "15m")]

    class Cursor:
        def execute(self, sql, params=()):
            assert "FROM signals" in sql
            calls["select"] += 1

        def fetchall(self):
            return list(sample)

    @contextmanager
    def fake_cursor():
        yield Cursor()

    monkeypatch.setattr(realtime.legacy_db, "db_cursor", fake_cursor)
    monkeypatch.setenv("REALTIME_DB_CACHE_SECONDS", "60")
    realtime.invalidate_pending_rows()

    assert realtime._pending_filled_rows() == sample
    assert realtime._pending_filled_rows() == sample
    assert calls["select"] == 1

    realtime.invalidate_pending_rows()  # fill/TP/SL/candle lifecycle transition
    assert realtime._pending_filled_rows() == sample
    assert calls["select"] == 2
    realtime.invalidate_pending_rows()


def test_phantom_integrity_sweep_defaults_to_fifteen_minutes(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr(realtime.time, "monotonic", lambda: clock["now"])
    monkeypatch.delenv("PHANTOM_SWEEP_SECONDS", raising=False)
    realtime._PHANTOM_SWEEP_AT = 0.0

    assert realtime._phantom_sweep_due() is True
    clock["now"] += 5
    assert realtime._phantom_sweep_due() is False
    clock["now"] += 896
    assert realtime._phantom_sweep_due() is True


def test_every_local_plan_writer_invalidates_the_cache():
    realtime_source = inspect.getsource(realtime.monitor_realtime_prices)
    candle_source = inspect.getsource(repository.monitor_confirmed_trades)
    phantom_source = inspect.getsource(realtime.void_phantom_positions)

    assert "if cache_dirty:" in realtime_source
    assert "invalidate_pending_rows()" in realtime_source
    assert "invalidate_pending_rows()" in candle_source
    assert "invalidate_pending_rows()" in phantom_source
