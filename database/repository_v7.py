"""Confirmed-signal repository and safe schema migrations for v7.

Educational candidates live only in the local candidate store. A technical
confirmation is staged in Supabase as AWAITING_PUBLICATION, but remains invisible
and unmonitorable until its complete Telegram publication is committed.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

from analysis.models import SignalCandidate
from analysis.risk import build_money_management
from analysis.trade_management import build_ladder, advance_ladder
from config import get_settings
from data.fetcher import get_klines
from database import db as legacy_db

SETTINGS = get_settings()

SIGNAL_COLUMNS = {
    "setup_code": "TEXT DEFAULT ''",
    "setup_name": "TEXT DEFAULT ''",
    "strategy_version": "TEXT DEFAULT ''",
    "trigger_timeframe": "TEXT DEFAULT ''",
    "evidence_json": "TEXT DEFAULT '[]'",
    "warnings_json": "TEXT DEFAULT '[]'",
    "mandatory_json": "TEXT DEFAULT '{}'",
    "market_json": "TEXT DEFAULT '{}'",
    "entry_zone_bottom": "REAL DEFAULT 0",
    "entry_zone_top": "REAL DEFAULT 0",
    "rr_tp1": "REAL DEFAULT 0",
    "rr_tp2": "REAL DEFAULT 0",
    "status": "TEXT DEFAULT 'CONFIRMED'",
    "confirmed_at": "TEXT",
    "confirmation_sent": "BOOLEAN DEFAULT FALSE",
    "confirmation_sent_at": "TEXT",
    "last_checked_at": "TEXT",
    "session_name": "TEXT DEFAULT ''",
    "pnl_usd": "REAL DEFAULT 0",
    "target_state_json": "TEXT DEFAULT '{}'",
    "pro_message_id": "INTEGER DEFAULT 0",
    "public_code": "TEXT DEFAULT ''",
    "first_tp_message_id": "INTEGER DEFAULT 0",
}

ACTIVE_COLUMNS = {
    "setup_code": "TEXT DEFAULT ''",
    "setup_name": "TEXT DEFAULT ''",
    "strategy_version": "TEXT DEFAULT ''",
    "style": "TEXT DEFAULT 'SWING'",
    "trigger_timeframe": "TEXT DEFAULT ''",
    "entry_zone_bottom": "REAL DEFAULT 0",
    "entry_zone_top": "REAL DEFAULT 0",
    "evidence_json": "TEXT DEFAULT '[]'",
    "status": "TEXT DEFAULT 'AWAITING_PUBLICATION'",
    "confirmed_at": "TEXT",
    "confirmation_sent": "BOOLEAN DEFAULT FALSE",
    "confirmation_sent_at": "TEXT",
    "last_checked_at": "TEXT",
    "target_state_json": "TEXT DEFAULT '{}'",
    "pro_message_id": "INTEGER DEFAULT 0",
    "public_code": "TEXT DEFAULT ''",
    "first_tp_message_id": "INTEGER DEFAULT 0",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _bool_value(value: bool):
    return bool(value) if legacy_db.USE_POSTGRES else int(bool(value))


def _table_columns(cursor, table: str) -> set:
    if legacy_db.USE_POSTGRES:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",
            (table,),
        )
        return {row[0] for row in cursor.fetchall()}
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _migrate_columns(cursor, table: str, definitions: Dict[str, str]) -> None:
    if legacy_db.USE_POSTGRES:
        # Atomic and safe when a web process and scanner start concurrently.
        # PostgreSQL takes the required schema lock and re-checks existence.
        for name, definition in definitions.items():
            cursor.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {definition}"
            )
        return

    # SQLite does not support ADD COLUMN IF NOT EXISTS on all deployed
    # versions, so introspection is retained for the local fallback.
    existing = _table_columns(cursor, table)
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_v7_schema() -> None:
    legacy_db.init_db()
    with legacy_db.db_cursor() as cursor:
        if legacy_db.USE_POSTGRES:
            # Serialize schema migration across scanner/web containers and
            # Gunicorn workers. The lock is released automatically on commit.
            cursor.execute("SELECT pg_advisory_xact_lock(866712370)")
        _migrate_columns(cursor, "signals", SIGNAL_COLUMNS)
        _migrate_columns(cursor, "active_signals", ACTIVE_COLUMNS)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_symbol_locks (
                symbol TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                state TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        if legacy_db.USE_POSTGRES:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id SERIAL PRIMARY KEY,
                    run_id TEXT UNIQUE,
                    symbol TEXT,
                    style TEXT,
                    days INTEGER,
                    strategy_version TEXT,
                    metrics_json TEXT,
                    by_setup_json TEXT,
                    methodology_json TEXT,
                    created_at TEXT
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT UNIQUE,
                    symbol TEXT,
                    style TEXT,
                    days INTEGER,
                    strategy_version TEXT,
                    metrics_json TEXT,
                    by_setup_json TEXT,
                    methodology_json TEXT,
                    created_at TEXT
                )
            """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_confirmed_result ON signals(confirmed, result)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_v7_publication "
            "ON signals(strategy_version, confirmation_sent, status, result, confirmed_at)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_style_setup ON signals(trade_style, setup_code)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_active_status ON active_signals(status, is_cancelled)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol_locks_expiry ON signal_symbol_locks(state, expires_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_runs_symbol ON backtest_runs(symbol, style, created_at)")
    print("✅ v7 database migrations applied safely")


def confirmed_exists(signal_id: str) -> bool:
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"SELECT 1 FROM signals WHERE signal_id={p} LIMIT 1", (signal_id,))
        return cursor.fetchone() is not None


def symbol_lock_key(candidate: SignalCandidate) -> str:
    """v7.6: locks are per (symbol, trigger timeframe), stored in the existing
    `symbol` TEXT column as `SYMBOL:tf` — no schema change required. A pending
    1h swing no longer blocks scalp scenarios on this symbol's 5m trigger."""
    tf = str(getattr(candidate, "trigger_timeframe", "") or "").lower()
    return f"{candidate.symbol.upper()}:{tf}" if tf else candidate.symbol.upper()


def acquire_symbol_lock(candidate: SignalCandidate) -> bool:
    """Atomically persist a cross-restart lock without candidate history."""
    p = legacy_db._ph()
    symbol = symbol_lock_key(candidate)
    now = _now()
    expiry = _naive_timestamp(candidate.expires_at)
    expiry_text = (
        expiry.isoformat(sep=" ", timespec="seconds")
        if expiry is not None
        else now
    )
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO signal_symbol_locks
                (symbol, signal_id, strategy_version, state, expires_at, updated_at)
            VALUES ({','.join([p] * 6)})
            ON CONFLICT(symbol) DO UPDATE SET
                signal_id=excluded.signal_id,
                strategy_version=excluded.strategy_version,
                state=excluded.state,
                expires_at=excluded.expires_at,
                updated_at=excluded.updated_at
            WHERE signal_symbol_locks.strategy_version<>excluded.strategy_version
               OR signal_symbol_locks.state NOT IN ('EDUCATIONAL','APPROACHING','CONFIRMED')
               OR signal_symbol_locks.expires_at<=excluded.updated_at
            """,
            (
                symbol,
                candidate.signal_id,
                SETTINGS.strategy_version,
                candidate.status,
                expiry_text,
                now,
            ),
        )
        return cursor.rowcount == 1


def update_symbol_lock(candidate: SignalCandidate) -> None:
    p = legacy_db._ph()
    expiry = _naive_timestamp(candidate.expires_at)
    expiry_text = expiry.isoformat(sep=" ", timespec="seconds") if expiry is not None else _now()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE signal_symbol_locks
            SET state={p}, expires_at={p}, updated_at={p}
            WHERE symbol={p} AND signal_id={p} AND strategy_version={p}
            """,
            (
                candidate.status,
                expiry_text,
                _now(),
                symbol_lock_key(candidate),
                candidate.signal_id,
                SETTINGS.strategy_version,
            ),
        )


def release_symbol_lock(symbol: str, signal_id: str) -> None:
    """Release by signal_id — works for both plain-symbol and `SYMBOL:tf`
    composite lock rows."""
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"DELETE FROM signal_symbol_locks "
            f"WHERE signal_id={p} AND strategy_version={p}",
            (signal_id, SETTINGS.strategy_version),
        )


def has_unresolved_symbol(symbol: str, exclude_signal_id: str = "", trigger_tf: str = "") -> bool:
    """Block a duplicate confirmed lifecycle on the SAME symbol+trigger TF until
    its outcome. A pending PENDING swing on `1h` never blocks this symbol's
    `5m` scalp confirmations (Viva's per-TF locking rule)."""
    p = legacy_db._ph()
    params = [symbol.upper(), SETTINGS.strategy_version]
    tf_filter = ""
    if trigger_tf:
        tf_filter = f"AND trigger_timeframe={p}"
        params.append(str(trigger_tf).lower())
    exclude = ""
    if exclude_signal_id:
        exclude = f"AND signal_id<>{p}"
        params.append(exclude_signal_id)
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT 1 FROM signals
            WHERE symbol={p} AND strategy_version={p}
              AND confirmed_at IS NOT NULL
              AND status IN ('AWAITING_PUBLICATION', 'CONFIRMED')
              AND result='PENDING'
              {tf_filter}
              {exclude}
            LIMIT 1
            """,
            tuple(params),
        )
        return cursor.fetchone() is not None


def cancel_staged_confirmation(signal_id: str) -> None:
    """Release a symbol when an unpublished staged confirmation is cancelled."""
    p = legacy_db._ph()
    false = "FALSE" if legacy_db.USE_POSTGRES else "0"
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE signals SET status='CANCELLED', result='CANCELLED', closed_at={p}
            WHERE signal_id={p} AND strategy_version={p}
              AND confirmation_sent={false} AND status='AWAITING_PUBLICATION'
            """,
            (_now(), signal_id, SETTINGS.strategy_version),
        )
        cursor.execute(
            f"""
            UPDATE active_signals SET status='CANCELLED', is_cancelled={truth}
            WHERE signal_id={p} AND strategy_version={p}
              AND confirmation_sent={false} AND status='AWAITING_PUBLICATION'
            """,
            (signal_id, SETTINGS.strategy_version),
        )
        cursor.execute(
            f"DELETE FROM signal_symbol_locks WHERE signal_id={p} AND strategy_version={p}",
            (signal_id, SETTINGS.strategy_version),
        )


def save_backtest_run(result: Dict) -> str:
    """Persist one aggregate walk-forward run without duplicating every trade."""
    run_id = f"bt-{result.get('symbol', 'NA')}-{result.get('style', 'NA')}-{uuid.uuid4().hex[:10]}"
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO backtest_runs
            (run_id, symbol, style, days, strategy_version,
             metrics_json, by_setup_json, methodology_json, created_at)
            VALUES ({','.join([p] * 9)})
            """,
            (
                run_id,
                str(result.get("symbol", "")),
                str(result.get("style", "")),
                int(result.get("days", 0)),
                SETTINGS.strategy_version,
                json.dumps(result.get("metrics", {}), ensure_ascii=False),
                json.dumps(result.get("by_setup", {}), ensure_ascii=False),
                json.dumps(result.get("methodology", {}), ensure_ascii=False),
                _now(),
            ),
        )
    return run_id


def portfolio_guard(candidate: SignalCandidate) -> Tuple[bool, str]:
    """Optional live-account allocation guard; disabled during research/demo."""
    if not getattr(SETTINGS, "portfolio_guard_enabled", False):
        return True, "Portfolio guard disabled for research/demo mode"
    p = legacy_db._ph()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM signals
            WHERE confirmed={truth} AND confirmation_sent={truth}
              AND status='CONFIRMED' AND strategy_version={p}
              AND result='PENDING'
            """,
            (SETTINGS.strategy_version,),
        )
        open_count = int((cursor.fetchone() or [0])[0] or 0)
        cursor.execute(
            f"""
            SELECT COALESCE(SUM(pnl_usd),0) FROM signals
            WHERE confirmed={truth} AND confirmation_sent={truth}
              AND strategy_version={p} AND result IN ('WIN','LOSS')
              AND closed_at>={p}
            """,
            (SETTINGS.strategy_version, today + " 00:00:00"),
        )
        daily_pnl_usd = float((cursor.fetchone() or [0])[0] or 0)
        cursor.execute(
            f"""
            SELECT symbol, direction, source, trade_style FROM signals
            WHERE confirmed={truth} AND confirmation_sent={truth}
              AND status='CONFIRMED' AND strategy_version={p}
              AND result='PENDING'
            """,
            (SETTINGS.strategy_version,),
        )
        open_rows = cursor.fetchall()

    if open_count >= SETTINGS.max_open_trades:
        return False, f"حداکثر {SETTINGS.max_open_trades} معامله هم‌زمان فعال است."
    if any(symbol == candidate.symbol for symbol, _direction, _source, _style in open_rows):
        return False, "تا تعیین نتیجه معامله فعال قبلی، سیگنال دیگری روی این نماد مجاز نیست."
    daily_loss_limit_usd = SETTINGS.account_size * SETTINGS.daily_loss_limit_percent / 100
    if daily_pnl_usd <= -abs(daily_loss_limit_usd):
        return False, (
            f"حد ضرر روزانه {SETTINGS.daily_loss_limit_percent}% "
            f"(${daily_loss_limit_usd:.2f}) فعال شده است."
        )
    # Crypto alts generally share market beta. BTC and ETH are treated as separate majors.
    if candidate.symbol not in {"BTCUSDT", "ETHUSDT"}:
        correlated = sum(
            1 for symbol, direction, _source, _style in open_rows
            if symbol not in {"BTCUSDT", "ETHUSDT"} and direction == candidate.direction
        )
        if correlated >= SETTINGS.max_correlated_trades:
            return False, "سقف معاملات هم‌جهت و همبسته آلت‌کوین‌ها پر شده است."
    return True, "Portfolio guard passed"


def has_open_pre_tp1_signal(symbol: str, trigger_timeframe: str) -> bool:
    """One protected exposure per symbol/trigger until TP1 is actually hit.
    This prevents the exact KORU pattern: a fresh same-TF confirmation while
    the remaining position of the prior trade is still live and protected."""
    p = legacy_db._ph()
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT 1 FROM signals
            WHERE symbol={p} AND trigger_timeframe={p}
              AND confirmed={truth} AND confirmation_sent={truth}
              AND status='CONFIRMED' AND result='PENDING'
              AND COALESCE(tp1_hit, {'FALSE' if legacy_db.USE_POSTGRES else '0'})={'FALSE' if legacy_db.USE_POSTGRES else '0'}
              AND strategy_version={p}
            LIMIT 1
            """,
            (str(symbol).upper(), str(trigger_timeframe).lower(), SETTINGS.strategy_version),
        )
        return cursor.fetchone() is not None


def save_confirmed_signal(candidate: SignalCandidate) -> bool:
    if candidate.status != "CONFIRMED" or not candidate.confirmed_at:
        raise ValueError("Only a CONFIRMED candidate can be persisted")
    if candidate.score < SETTINGS.execution_min_score or not candidate.execution_ready:
        raise ValueError("Candidate does not meet execution quality gates")
    if confirmed_exists(candidate.signal_id):
        return False

    allowed, reason = portfolio_guard(candidate)
    if not allowed:
        raise RuntimeError(reason)
    mm = build_money_management(candidate)
    if not mm:
        raise RuntimeError("Money-management plan could not be calculated")

    p = legacy_db._ph()
    created = candidate.confirmed_at.replace("T", " ").replace("+00:00", "")
    params = (
        candidate.symbol,
        candidate.setup_code,
        candidate.strategy_fa,
        candidate.direction,
        float(candidate.planned_entry),
        float(candidate.sl),
        float(candidate.sl),
        float(candidate.tp1),
        float(candidate.tp2),
        candidate.bias,
        json.dumps(candidate.confirmations, ensure_ascii=False),
        candidate.setup_name,
        json.dumps([item.detail for item in candidate.evidence], ensure_ascii=False),
        candidate.signal_id,
        int(mm["leverage"]),
        float(mm["margin"]),
        candidate.style,
        candidate.trigger_timeframe if candidate.style == "SCALP" else "",
        "4h" if candidate.style == "SWING" else "1h",
        str(candidate.metadata.get("htf_4h", "")),
        str(candidate.metadata.get("htf_1h", "")),
        str(candidate.metadata.get("htf_15m", "")),
        int(candidate.score),
        SETTINGS.partial_tp1_percent,
        SETTINGS.partial_tp2_percent,
        _bool_value(True),
        created,
        candidate.setup_code,
        candidate.setup_name,
        SETTINGS.strategy_version,
        candidate.trigger_timeframe,
        json.dumps([item.__dict__ for item in candidate.evidence], ensure_ascii=False, default=str),
        json.dumps(candidate.warnings, ensure_ascii=False),
        json.dumps(candidate.mandatory_gates, ensure_ascii=False),
        json.dumps(candidate.market, ensure_ascii=False, default=str),
        float(candidate.entry_zone_bottom),
        float(candidate.entry_zone_top),
        float(candidate.rr_tp1),
        float(candidate.rr_tp2),
        "AWAITING_PUBLICATION",
        created,
        _bool_value(False),
        None,
        created,
        str(candidate.metadata.get("session", "")),
    )
    sql = f"""
        INSERT INTO signals
        (symbol, source, strategy_fa, direction, entry, sl, sl_original,
         tp1, tp2, bias, confirmations, description, entry_conditions,
         signal_id, leverage, margin_usd, trade_style, scalp_tf, swing_tf,
         mtf_4h, mtf_1h, mtf_15m, score, partial_tp1_pct, partial_tp2_pct,
         confirmed, created_at, setup_code, setup_name, strategy_version,
         trigger_timeframe, evidence_json, warnings_json, mandatory_json,
         market_json, entry_zone_bottom, entry_zone_top, rr_tp1, rr_tp2,
         status, confirmed_at, confirmation_sent, confirmation_sent_at,
         last_checked_at, session_name)
        VALUES ({','.join([p] * 45)})
    """

    active_params = (
        candidate.signal_id,
        candidate.symbol,
        candidate.setup_code,
        candidate.strategy_fa,
        candidate.direction,
        float(candidate.planned_entry),
        float(candidate.sl),
        float(candidate.sl),
        float(candidate.tp1),
        float(candidate.tp2),
        candidate.bias,
        int(mm["leverage"]),
        float(mm["margin"]),
        int(candidate.score),
        _bool_value(True),
        created,
        candidate.setup_code,
        candidate.setup_name,
        SETTINGS.strategy_version,
        candidate.style,
        candidate.trigger_timeframe,
        float(candidate.entry_zone_bottom),
        float(candidate.entry_zone_top),
        json.dumps([item.__dict__ for item in candidate.evidence], ensure_ascii=False, default=str),
        "AWAITING_PUBLICATION",
        created,
        _bool_value(False),
        None,
        created,
    )
    active_sql = f"""
        INSERT INTO active_signals
        (signal_id, symbol, source, strategy_fa, direction, entry, sl,
         sl_original, tp1, tp2, bias, leverage, margin_usd, score,
         is_confirmed, created_at, setup_code, setup_name, strategy_version,
         style, trigger_timeframe, entry_zone_bottom, entry_zone_top,
         evidence_json, status, confirmed_at, confirmation_sent,
         confirmation_sent_at, last_checked_at)
        VALUES ({','.join([p] * 29)})
    """

    ladder = build_ladder(candidate.planned_entry, candidate.sl, candidate.direction, candidate.market, candidate.tp2)
    ladder_json = json.dumps(ladder, ensure_ascii=False)
    with legacy_db.db_cursor() as cursor:
        cursor.execute(sql, params)
        cursor.execute(active_sql, active_params)
        public_code = str(candidate.metadata.get("public_code") or candidate.signal_id)
        cursor.execute(f"UPDATE signals SET target_state_json={p}, public_code={p} WHERE signal_id={p}", (ladder_json, public_code, candidate.signal_id))
        cursor.execute(f"UPDATE active_signals SET target_state_json={p}, public_code={p} WHERE signal_id={p}", (ladder_json, public_code, candidate.signal_id))
    return True


def has_published_confirmation(signal_id: str, require_open: bool = False) -> bool:
    p = legacy_db._ph()
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    status_guard = "AND status='CONFIRMED'" if require_open else ""
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT 1 FROM signals
            WHERE signal_id={p}
              AND strategy_version={p}
              AND confirmed_at IS NOT NULL
              AND confirmation_sent={truth}
              AND confirmation_sent_at IS NOT NULL
              {status_guard}
            LIMIT 1
            """,
            (signal_id, SETTINGS.strategy_version),
        )
        return cursor.fetchone() is not None


def is_confirmation_published(signal_id: str) -> bool:
    return has_published_confirmation(signal_id, require_open=True)


def is_lifecycle_event_publishable(
    signal_id: str, event_type: str, result: Optional[str] = None
) -> bool:
    """Validate that a lifecycle notification matches committed v7 DB state."""
    p = legacy_db._ph()
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT result, tp1_hit, closed_at FROM signals
            WHERE signal_id={p}
              AND strategy_version={p}
              AND status='CONFIRMED'
              AND confirmed_at IS NOT NULL
              AND confirmation_sent={truth}
              AND confirmation_sent_at IS NOT NULL
            LIMIT 1
            """,
            (signal_id, SETTINGS.strategy_version),
        )
        row = cursor.fetchone()
    if not row:
        return False
    db_result, tp1_hit, closed_at = row
    if str(event_type).startswith("TP"):
        # TP events are emitted only by the durable ladder monitor; publication
        # proof is the confirmed signal itself, not the legacy tp1_hit column.
        return True
    if event_type == "CLOSED":
        return result in {"WIN", "LOSS"} and db_result == result and closed_at is not None
    return False


def mark_confirmation_published(signal_id: str) -> None:
    """Arm result monitoring only after the Telegram confirmation is public."""
    p = legacy_db._ph()
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    published_at = _now()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE signals
            SET confirmation_sent={truth}, confirmation_sent_at={p},
                status='CONFIRMED', last_checked_at={p}
            WHERE signal_id={p} AND strategy_version={p}
              AND confirmed_at IS NOT NULL
              AND status IN ('AWAITING_PUBLICATION', 'CONFIRMED')
            """,
            (published_at, published_at, signal_id, SETTINGS.strategy_version),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Cannot publish unknown or ineligible signal: {signal_id}")
        cursor.execute(
            f"""
            UPDATE active_signals
            SET confirmation_sent={truth}, confirmation_sent_at={p},
                status='CONFIRMED', last_checked_at={p}
            WHERE signal_id={p} AND strategy_version={p}
              AND status IN ('AWAITING_PUBLICATION', 'CONFIRMED')
            """,
            (published_at, published_at, signal_id, SETTINGS.strategy_version),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Missing active publication row: {signal_id}")
        cursor.execute(
            f"""
            UPDATE signal_symbol_locks SET state='CONFIRMED', updated_at={p}
            WHERE signal_id={p} AND strategy_version={p}
            """,
            (published_at, signal_id, SETTINGS.strategy_version),
        )


def set_pro_message_id(signal_id: str, message_id: int) -> None:
    """Persist the canonical VivaMon confirmed-message id for TP/result links."""
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"UPDATE signals SET pro_message_id={p} WHERE signal_id={p}", (int(message_id), signal_id))
        cursor.execute(f"UPDATE active_signals SET pro_message_id={p} WHERE signal_id={p}", (int(message_id), signal_id))


def set_first_tp_message_id(signal_id: str, message_id: int) -> None:
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"UPDATE signals SET first_tp_message_id={p} WHERE signal_id={p}", (int(message_id), signal_id))
        cursor.execute(f"UPDATE active_signals SET first_tp_message_id={p} WHERE signal_id={p}", (int(message_id), signal_id))


def set_last_tp_message_id(signal_id: str, message_id: int) -> None:
    """Persist latest main-channel TP reply for chronological TP threading."""
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"SELECT target_state_json FROM signals WHERE signal_id={p}", (signal_id,))
        row = cursor.fetchone()
        if not row:
            return
        try:
            state = json.loads(row[0] or "{}")
        except Exception:
            state = {}
        state["last_tp_message_id"] = int(message_id)
        raw = json.dumps(state)
        cursor.execute(f"UPDATE signals SET target_state_json={p} WHERE signal_id={p}", (raw, signal_id))
        cursor.execute(f"UPDATE active_signals SET target_state_json={p} WHERE signal_id={p}", (raw, signal_id))


def _naive_timestamp(value) -> Optional[pd.Timestamp]:
    if not value:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _weighted_win_pct(direction: str, entry: float, tp1: float, tp2: float, partial_only: bool) -> float:
    move1 = (tp1 - entry) / entry * 100 if direction == "LONG" else (entry - tp1) / entry * 100
    if partial_only:
        return move1 * SETTINGS.partial_tp1_percent / 100
    move2 = (tp2 - entry) / entry * 100 if direction == "LONG" else (entry - tp2) / entry * 100
    return move1 * SETTINGS.partial_tp1_percent / 100 + move2 * SETTINGS.partial_tp2_percent / 100


def protected_exit_audit(limit: int = 100) -> dict:
    """Forensic report for losses that may actually contain protected profit."""
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"SELECT signal_id, symbol, source, direction, entry, sl, sl_original, tp1, tp2, "
            f"tp1_hit, sl_moved_to_be, leverage, margin_usd, pnl_pct, pnl_usd, created_at, closed_at "
            f"FROM signals WHERE strategy_version={p} AND result='LOSS' ORDER BY closed_at DESC LIMIT {p}",
            (SETTINGS.strategy_version, int(limit)),
        )
        rows = cursor.fetchall()
    records = []
    for row in rows:
        (sid, symbol, source, direction, entry, sl, sl_original, tp1, tp2, tp1_hit, moved_be, leverage, margin, pnl_pct, pnl_usd, created_at, closed_at) = row
        entry_f, sl_f = float(entry), float(sl or sl_original)
        price_protected = (str(direction) == "LONG" and sl_f >= entry_f) or (str(direction) == "SHORT" and sl_f <= entry_f)
        suspicious = bool(tp1_hit) or bool(moved_be) or price_protected
        records.append({
            "signal_id": sid, "symbol": symbol, "setup": source, "direction": direction,
            "entry": entry_f, "stop": sl_f, "tp1": float(tp1), "tp2": float(tp2),
            "tp1_hit": bool(tp1_hit), "sl_moved_to_be": bool(moved_be),
            "price_protected": price_protected, "suspicious": suspicious,
            "leverage": int(leverage or 0), "margin": float(margin or 0),
            "pnl_pct": float(pnl_pct or 0), "pnl_usd": float(pnl_usd or 0),
            "created_at": str(created_at or ""), "closed_at": str(closed_at or ""),
        })
    return {"total_losses": len(records), "protected_candidates": sum(1 for item in records if item["suspicious"]), "records": records}


def repair_legacy_tp1_misclassified_results() -> int:
    """Repair legacy trades that were labelled LOSS after profit protection.

    A position with TP1 recorded or a stop moved to/through entry cannot be
    counted as a full initial-stop loss. Legacy rows did exactly that.
    """
    p = legacy_db._ph()
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"SELECT signal_id, direction, entry, sl, sl_original, tp1, tp2, leverage, margin_usd, tp1_hit, sl_moved_to_be "
            f"FROM signals WHERE strategy_version={p} AND result='LOSS'",
            (SETTINGS.strategy_version,),
        )
        rows = cursor.fetchall()
        repaired = 0
        for signal_id, direction, entry, current_sl, original_sl, tp1, tp2, leverage, margin_usd, tp1_hit, moved_be in rows:
            entry, current_sl = float(entry), float(current_sl or original_sl)
            protected = bool(tp1_hit) or bool(moved_be) or (direction == "LONG" and current_sl >= entry) or (direction == "SHORT" and current_sl <= entry)
            if not protected:
                continue
            # At minimum TP1 partial profit was realized. If data lacks a
            # tp1 flag but stop is protected, keep the conservative TP1 share.
            gross = _weighted_win_pct(direction, entry, float(tp1), float(tp2), True)
            if gross <= 0:
                continue
            profit_usd = float(margin_usd or 0) * int(leverage or 1) * gross / 100
            cursor.execute(
                f"UPDATE signals SET result='WIN', pnl_pct={p}, pnl_usd={p} WHERE signal_id={p}",
                (gross, profit_usd, signal_id),
            )
            repaired += 1
    return repaired


def monitor_confirmed_trades() -> List[Dict]:
    """Process each closed candle chronologically; no historical `.any()` shortcuts."""
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"""
            SELECT signal_id, symbol, direction, entry, sl_original, tp1, tp2,
                   leverage, margin_usd, trade_style, confirmed_at,
                   last_checked_at, tp1_hit, source, strategy_fa,
                   strategy_version, pro_message_id, target_state_json, public_code, first_tp_message_id, trigger_timeframe
            FROM signals
            WHERE confirmed={truth}
              AND confirmation_sent={truth}
              AND status='CONFIRMED'
              AND confirmed_at IS NOT NULL
              AND confirmation_sent_at IS NOT NULL
              AND strategy_version={legacy_db._ph()}
              AND result='PENDING'
            ORDER BY confirmed_at
        """, (SETTINGS.strategy_version,))
        rows = cursor.fetchall()
    if not rows:
        return []

    by_symbol_tf: Dict[Tuple[str, str], pd.DataFrame] = {}
    events: List[Dict] = []
    p = legacy_db._ph()
    for row in rows:
        (
            signal_id, symbol, direction, entry, original_sl, tp1, tp2,
            leverage, margin, style, confirmed_at, last_checked_at,
            tp1_hit, source, strategy_fa, strategy_version, pro_message_id, target_state_json, public_code, first_tp_message_id, trigger_timeframe,
        ) = row
        timeframe = "5m" if style == "SCALP" else "15m"
        key = (symbol, timeframe)
        if key not in by_symbol_tf:
            by_symbol_tf[key] = get_klines(symbol, timeframe, 300, closed_only=True, use_cache=False)
        frame = by_symbol_tf[key]
        if frame is None or frame.empty:
            continue
        start = _naive_timestamp(last_checked_at) or _naive_timestamp(confirmed_at)
        timestamps = pd.to_datetime(frame["timestamp"])
        if getattr(timestamps.dt, "tz", None) is not None:
            timestamps = timestamps.dt.tz_convert("UTC").dt.tz_localize(None)
        pending = frame.loc[timestamps > start].copy() if start is not None else frame.tail(1).copy()
        if pending.empty:
            continue

        # New signals carry a durable 5-TP ladder. Legacy rows keep the old
        # two-target monitor so historical result data remains untouched.
        try:
            ladder = json.loads(target_state_json or "{}")
        except Exception:
            ladder = {}
        if ladder and ladder.get("targets") and not ladder.get("closed"):
            ladder_events = []
            latest_checked = start
            for _, candle in pending.iterrows():
                latest_checked = _naive_timestamp(candle["timestamp"])
                step = advance_ladder(ladder, float(candle["high"]), float(candle["low"]))
                ladder = step["state"]
                for event in step["events"]:
                    event.update({
                        "signal_id": signal_id, "symbol": symbol, "direction": direction,
                        "style": style, "source": source, "strategy_fa": strategy_fa,
                        "strategy_version": strategy_version, "confirmed_at": str(confirmed_at),
                        "confirmation_sent": True, "pro_message_id": int(pro_message_id or 0),
                        "entry": float(entry), "sl": float(ladder["current_sl"]), "original_sl": float(original_sl),
                        "trigger_timeframe": str(trigger_timeframe or ""), "targets": list(ladder["targets"]), "hit_index": int(ladder["hit_index"]), "last_tp_message_id": int(ladder.get("last_tp_message_id") or 0),
                    })
                    notional = float(margin or 0) * int(leverage or 1)
                    risk_pct_move = abs(float(entry) - float(original_sl)) / float(entry) * 100
                    if str(event.get("event", "")).startswith("TP"):
                        target_index = int(event["event"][2:]) - 1
                        leg_r = float(ladder.get("target_r", [])[target_index]) if target_index < len(ladder.get("target_r", [])) else 0.0
                        event["leg_price_move_pct"] = leg_r * risk_pct_move
                        event["leg_pnl_pct"] = event["leg_price_move_pct"] * float(event.get("weight", 0)) / 100
                        event["leg_profit_usd"] = notional * event["leg_pnl_pct"] / 100
                        event["leg_margin_roi_pct"] = event["leg_profit_usd"] / max(float(margin or 0), 1e-12) * 100
                    else:
                        event["realized_pnl_pct"] = float(ladder.get("realized_r", 0)) * risk_pct_move
                        event["realized_profit_usd"] = notional * event["realized_pnl_pct"] / 100
                        event["realized_margin_roi_pct"] = event["realized_profit_usd"] / max(float(margin or 0), 1e-12) * 100
                    ladder_events.append(event)
                if ladder.get("closed"):
                    break
            with legacy_db.db_cursor() as cursor:
                if latest_checked is not None:
                    checked_text = latest_checked.isoformat(sep=" ", timespec="seconds")
                    cursor.execute(f"UPDATE signals SET target_state_json={p}, sl={p}, last_checked_at={p} WHERE signal_id={p}",
                                   (json.dumps(ladder), float(ladder["current_sl"]), checked_text, signal_id))
                    cursor.execute(f"UPDATE active_signals SET target_state_json={p}, sl={p}, last_checked_at={p} WHERE signal_id={p}",
                                   (json.dumps(ladder), float(ladder["current_sl"]), checked_text, signal_id))
                if ladder.get("closed"):
                    notional = float(margin or 0) * int(leverage or 1)
                    gross_pnl = float(ladder.get("realized_r", 0)) * abs(float(entry) - float(original_sl)) / float(entry) * 100
                    net_pnl = gross_pnl - 2 * (SETTINGS.fee_rate_percent + SETTINGS.slippage_percent)
                    profit_usd = notional * net_pnl / 100
                    result = "WIN" if net_pnl > 0 else "LOSS"
                    cursor.execute(f"UPDATE signals SET result={p}, pnl_pct={p}, pnl_usd={p}, closed_at={p} WHERE signal_id={p}",
                                   (result, net_pnl, profit_usd, _now(), signal_id))
                    cursor.execute(f"UPDATE active_signals SET status='CLOSED', is_cancelled={truth} WHERE signal_id={p}", (signal_id,))
                    cursor.execute(f"DELETE FROM signal_symbol_locks WHERE symbol={p} AND signal_id={p} AND strategy_version={p}",
                                   (symbol, signal_id, SETTINGS.strategy_version))
                    ladder_events.append({"event":"CLOSED", "signal_id":signal_id,"symbol":symbol,"style":style,"source":source,"strategy_fa":strategy_fa,"strategy_version":strategy_version,"confirmed_at":str(confirmed_at),"confirmation_sent":True,"pro_message_id":int(pro_message_id or 0),"result":result,"pnl":net_pnl,"profit_usd":profit_usd})
            events.extend(ladder_events)
            continue

        state_tp1 = bool(tp1_hit)
        closed_event = None
        tp1_event = None
        latest_checked = start
        for _, candle in pending.iterrows():
            latest_checked = _naive_timestamp(candle["timestamp"])
            high, low = float(candle["high"]), float(candle["low"])
            if direction == "LONG":
                stop_hit = low <= (entry if state_tp1 else original_sl)
                first_hit = high >= tp1
                final_hit = high >= tp2
            else:
                stop_hit = high >= (entry if state_tp1 else original_sl)
                first_hit = low <= tp1
                final_hit = low <= tp2

            # Conservative ambiguity rule: if stop and target occur in the same
            # candle, assume the stop happened first because tick order is unknown.
            if stop_hit:
                if state_tp1:
                    pnl = _weighted_win_pct(direction, entry, tp1, tp2, True)
                    result = "WIN"
                    reason = "TP1 سپس Breakeven"
                else:
                    pnl = ((original_sl - entry) / entry * 100) if direction == "LONG" else ((entry - original_sl) / entry * 100)
                    result = "LOSS"
                    reason = "Stop Loss"
                closed_event = {"result": result, "pnl": pnl, "reason": reason}
                break
            if final_hit:
                pnl = _weighted_win_pct(direction, entry, tp1, tp2, False)
                closed_event = {"result": "WIN", "pnl": pnl, "reason": "TP2"}
                break
            if first_hit and not state_tp1:
                state_tp1 = True
                tp1_event = {
                    "event": "TP1", "signal_id": signal_id, "symbol": symbol,
                    "style": style, "source": source, "strategy_fa": strategy_fa,
                    "strategy_version": strategy_version,
                    "confirmed_at": str(confirmed_at),
                    "confirmation_sent": True,
                    "pro_message_id": int(pro_message_id or 0),
                }

        with legacy_db.db_cursor() as cursor:
            if state_tp1 and not tp1_hit:
                cursor.execute(
                    f"UPDATE signals SET tp1_hit={truth}, tp1_hit_at={p}, sl_moved_to_be={truth}, sl=entry WHERE signal_id={p}",
                    (_now(), signal_id),
                )
                cursor.execute(
                    f"UPDATE active_signals SET tp1_hit={truth}, sl_moved_to_be={truth}, sl=entry WHERE signal_id={p}",
                    (signal_id,),
                )
            if latest_checked is not None:
                checked_text = latest_checked.isoformat(sep=" ", timespec="seconds")
                cursor.execute(f"UPDATE signals SET last_checked_at={p} WHERE signal_id={p}", (checked_text, signal_id))
                cursor.execute(f"UPDATE active_signals SET last_checked_at={p} WHERE signal_id={p}", (checked_text, signal_id))
            if closed_event:
                notional = float(margin or 0) * int(leverage or 1)
                gross_pnl = float(closed_event["pnl"])
                roundtrip_cost = 2 * (SETTINGS.fee_rate_percent + SETTINGS.slippage_percent)
                net_pnl = gross_pnl - roundtrip_cost
                closed_event["gross_pnl"] = gross_pnl
                closed_event["pnl"] = net_pnl
                closed_event["result"] = "WIN" if net_pnl > 0 else "LOSS"
                profit_usd = notional * net_pnl / 100
                cursor.execute(
                    f"UPDATE signals SET result={p}, pnl_pct={p}, pnl_usd={p}, closed_at={p} WHERE signal_id={p}",
                    (closed_event["result"], net_pnl, profit_usd, _now(), signal_id),
                )
                cursor.execute(
                    f"UPDATE active_signals SET status='CLOSED', is_cancelled={truth} WHERE signal_id={p}",
                    (signal_id,),
                )
                cursor.execute(
                    f"DELETE FROM signal_symbol_locks "
                    f"WHERE symbol={p} AND signal_id={p} AND strategy_version={p}",
                    (symbol, signal_id, SETTINGS.strategy_version),
                )
                closed_event.update({
                    "event": "CLOSED", "signal_id": signal_id, "symbol": symbol,
                    "style": style, "source": source, "strategy_fa": strategy_fa,
                    "profit_usd": profit_usd,
                    "strategy_version": strategy_version,
                    "confirmed_at": str(confirmed_at),
                    "confirmation_sent": True,
                    "pro_message_id": int(pro_message_id or 0), "public_code": public_code,
                    "trigger_timeframe": str(trigger_timeframe or ""), "original_sl": float(original_sl),
                    "first_tp_message_id": int(first_tp_message_id or 0),
                })
        if tp1_event:
            events.append(tp1_event)
        if closed_event:
            events.append(closed_event)
    return events
