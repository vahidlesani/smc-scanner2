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


def acquire_symbol_lock(candidate: SignalCandidate) -> bool:
    """Atomically persist a cross-restart lock without candidate history."""
    p = legacy_db._ph()
    symbol = candidate.symbol.upper()
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
                candidate.symbol.upper(),
                candidate.signal_id,
                SETTINGS.strategy_version,
            ),
        )


def release_symbol_lock(symbol: str, signal_id: str) -> None:
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"DELETE FROM signal_symbol_locks "
            f"WHERE symbol={p} AND signal_id={p} AND strategy_version={p}",
            (symbol.upper(), signal_id, SETTINGS.strategy_version),
        )


def has_unresolved_symbol(symbol: str, exclude_signal_id: str = "") -> bool:
    """Block every duplicate confirmed lifecycle on a symbol until its outcome."""
    p = legacy_db._ph()
    params = [symbol.upper(), SETTINGS.strategy_version]
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
    """Prevent concentration and trading after the configured daily loss cap."""
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

    with legacy_db.db_cursor() as cursor:
        cursor.execute(sql, params)
        cursor.execute(active_sql, active_params)
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
    if event_type == "TP1":
        return bool(tp1_hit)
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


def monitor_confirmed_trades() -> List[Dict]:
    """Process each closed candle chronologically; no historical `.any()` shortcuts."""
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"""
            SELECT signal_id, symbol, direction, entry, sl_original, tp1, tp2,
                   leverage, margin_usd, trade_style, confirmed_at,
                   last_checked_at, tp1_hit, source, strategy_fa,
                   strategy_version
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
            tp1_hit, source, strategy_fa, strategy_version,
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
                })
        if tp1_event:
            events.append(tp1_event)
        if closed_event:
            events.append(closed_event)
    return events
