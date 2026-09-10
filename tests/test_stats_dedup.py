"""Journal-fairness dedup: at most one closed result per symbol per 24h
feeds strategy_stats; raw per-signal rows are never dropped."""
import importlib
from datetime import datetime, timedelta, timezone


def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "dedup.db"))
    import config
    importlib.reload(config)
    import database.db as db
    db = importlib.reload(db)
    db.init_db()
    return db


def _seed(db, sig_id, symbol, result, closed_hours_ago):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    closed = (now - timedelta(hours=closed_hours_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with db.db_cursor() as c:
        c.execute(
            "INSERT INTO signals (symbol, source, result, closed_at, signal_id) "
            "VALUES (?,?,?,?,?)",
            (symbol, "PINWALLQ", result, closed, sig_id),
        )


def _stats(db):
    with db.db_cursor() as c:
        c.execute("SELECT total_signals, wins, losses FROM strategy_stats WHERE strategy='PINWALLQ'")
        return c.fetchone()


def test_first_close_counts_current_row_excluded_by_id(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    _seed(db, "S1", "AAAUSDT", "WIN", 0)
    # stats call for the same signal: its own row must NOT dedupe it
    assert db.update_strategy_stats(
        {"source": "PINWALLQ", "symbol": "AAAUSDT", "signal_id": "S1"}, "WIN", 2.0) is None
    assert _stats(db) == (1, 1, 0)


def test_second_same_symbol_inside_window_is_deduped(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    _seed(db, "S1", "AAAUSDT", "WIN", 1)
    assert db.update_strategy_stats(
        {"source": "PINWALLQ", "symbol": "AAAUSDT", "signal_id": "S2"}, "LOSS", -3.0) is False
    assert _stats(db) is None  # nothing was ever counted for the deduped call


def test_different_symbol_counts(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    _seed(db, "S1", "AAAUSDT", "WIN", 1)
    db.update_strategy_stats({"source": "PINWALLQ", "symbol": "AAAUSDT", "signal_id": "S1"}, "WIN", 1)
    assert db.update_strategy_stats(
        {"source": "PINWALLQ", "symbol": "BBBUSDT", "signal_id": "S2"}, "LOSS", -1) is None
    assert _stats(db) == (2, 1, 1)


def test_outside_window_counts_again(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    _seed(db, "S1", "AAAUSDT", "WIN", 25)  # older than 24h
    assert db.update_strategy_stats(
        {"source": "PINWALLQ", "symbol": "AAAUSDT", "signal_id": "S2"}, "LOSS", -1) is None
    assert _stats(db)[0] == 1


def test_dedup_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("STATS_DEDUP_HOURS", "0")
    db = _db(tmp_path, monkeypatch)
    _seed(db, "S1", "AAAUSDT", "WIN", 1)
    assert db.update_strategy_stats(
        {"source": "PINWALLQ", "symbol": "AAAUSDT", "signal_id": "S2"}, "LOSS", -1) is None
    assert _stats(db)[0] == 1
