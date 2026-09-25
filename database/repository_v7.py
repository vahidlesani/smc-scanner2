"""Confirmed-signal repository and safe schema migrations for v7.

Educational candidates live only in the local candidate store. A technical
confirmation is staged in Supabase as AWAITING_PUBLICATION, but remains invisible
and unmonitorable until its complete Telegram publication is committed.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

from analysis.models import SignalCandidate, generate_viva_public_code
from analysis.risk import build_money_management
from analysis.trade_management import (build_ladder, advance_ladder, entry_touched,
                                       band_trailing, smart_exit_scan, reentry_setup)
from analysis.execution_integrity_r29 import trailing_from_ladder
from config import get_settings
from data.fetcher import get_klines
from database import db as legacy_db

# Viva 09-19 monitoring-hierarchy ruling (his delegation: «تو باید بگی»): the
# lifecycle of EVERY setup is watched on a FINER TF than the trade TF so
# fills, profit-floor trails and reversal scores see price sooner — 1D from
# 1H, 4H/2H/1H from 15m, 15m/30m from 5m (Ourbit has no 3m), 5m/3m from 1m.
# Falls back to the trade TF when the venue lacks the finer interval.
MONITOR_TF_FOR = {"1d": "1h", "4h": "15m", "2h": "15m", "1h": "15m",
                  "30m": "5m", "15m": "5m", "5m": "1m", "3m": "1m"}
TF_MINUTES = {"1m": 1.0, "3m": 3.0, "5m": 5.0, "15m": 15.0, "30m": 30.0,
              "1h": 60.0, "2h": 120.0, "4h": 240.0, "1d": 1440.0}


# «مدیریت ویوا» §6.1/§7 (09-20): the reversal early-warning lives ONE step
# finer than the monitor TF — for a 15m trade: orange on 3m, and the exit
# trigger is the confirmed reverse pin bar close on the 5m monitor frame.
FAST_WATCH_TF = {"1d": "15m", "4h": "5m", "2h": "5m", "1h": "5m", "30m": "3m",
                 "15m": "3m", "5m": "1m", "3m": "1m", "1m": "1m"}


def fast_watch_tf_for(trade_tf: str) -> str:
    return FAST_WATCH_TF.get(str(trade_tf or "").lower(), "3m")


def monitor_tf_for(tf: str) -> str:
    tf = str(tf or "").lower()
    return MONITOR_TF_FOR.get(tf, tf)


def vol_atr_n_for(trade_tf: str, monitor_tf: str) -> float:
    """√-time scaling (Viva 09-19 formula-flexibility ruling): n ATR on the
    monitor TF ≈ 1 ATR on the trade TF, so a finer candle stream never
    tightens the volatility stop in absolute price terms."""
    from analysis.trade_management import VOL_STOP_ATR_N
    tm = TF_MINUTES.get(str(trade_tf).lower(), 15.0)
    mm = TF_MINUTES.get(str(monitor_tf).lower(), tm)
    if mm <= 0:
        return VOL_STOP_ATR_N
    return VOL_STOP_ATR_N * math.sqrt(tm / mm)

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
    "partial_win": "BOOLEAN DEFAULT FALSE",
    "session_name": "TEXT DEFAULT ''",
    "pnl_usd": "REAL DEFAULT 0",
    "target_state_json": "TEXT DEFAULT '{}'",
    "pro_message_id": "INTEGER DEFAULT 0",
    "strategy_variant": "TEXT DEFAULT ''",
    "public_code": "TEXT DEFAULT ''",
    "first_tp_message_id": "INTEGER DEFAULT 0",
    "entry_filled": "BOOLEAN DEFAULT FALSE",
    "entry_filled_at": "TEXT",
    "cancel_reason": "TEXT DEFAULT ''",
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
    "partial_win": "BOOLEAN DEFAULT FALSE",
    "target_state_json": "TEXT DEFAULT '{}'",
    "pro_message_id": "INTEGER DEFAULT 0",
    "strategy_variant": "TEXT DEFAULT ''",
    "public_code": "TEXT DEFAULT ''",
    "first_tp_message_id": "INTEGER DEFAULT 0",
    "entry_filled": "BOOLEAN DEFAULT FALSE",
    "entry_filled_at": "TEXT",
    "cancel_reason": "TEXT DEFAULT ''",
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
        #
        # round-12 incident: *every* ALTER asks for an ACCESS EXCLUSIVE lock even
        # with IF NOT EXISTS, so a single leaked idle-in-transaction reader made
        # all of them queue and die on statement_timeout — and the scanner thread
        # died with them («تعداد شناسایی‌ها قطع شد»). Check first, ALTER only what
        # is really missing, and never wait forever for the lock.
        existing = _table_columns(cursor, table)
        missing = {k: v for k, v in definitions.items() if k not in existing}
        if not missing:
            return
        try:
            cursor.execute("SET LOCAL lock_timeout = '10000'")
        except Exception:
            pass
        for name, definition in missing.items():
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
        # Existing open positions predate the fill gate. Preserve their state
        # as already-filled once during this migration; only newly confirmed
        # records start unfilled.
        signals_before = _table_columns(cursor, "signals")
        active_before = _table_columns(cursor, "active_signals")
        _migrate_columns(cursor, "signals", SIGNAL_COLUMNS)
        _migrate_columns(cursor, "active_signals", ACTIVE_COLUMNS)
        if "entry_filled" not in signals_before:
            cursor.execute("UPDATE signals SET entry_filled=" + ("TRUE" if legacy_db.USE_POSTGRES else "1") + " WHERE status='CONFIRMED' AND result='PENDING'")
        if "entry_filled" not in active_before:
            cursor.execute("UPDATE active_signals SET entry_filled=" + ("TRUE" if legacy_db.USE_POSTGRES else "1") + " WHERE status='CONFIRMED'")
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
        # Telegram posts are immutable receipts.  The key is the database
        # signal_id + lifecycle event, never symbol, timeframe or public code.
        # This prevents two allowed positions on the same symbol from borrowing
        # each other's Confirmed/TP permalink.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_telegram_events (
                signal_id TEXT NOT NULL,
                event_key TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                message_id BIGINT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (signal_id, event_key)
            )
        """)
        # A public code is a permanent, human-facing position identity. The
        # primary key makes duplicate issuance impossible even across workers.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_public_code_registry (
                public_code TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
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
    """Durable lock receipt for one candidate, never a symbol-wide mutex.

    The legacy table has a single text primary key, so include the immutable
    signal id. This permits Viva's three independent paper positions on one
    symbol/trigger while retaining restart-safe release by signal_id.
    """
    tf = str(getattr(candidate, "trigger_timeframe", "") or "").lower()
    return f"{candidate.symbol.upper()}:{tf}:{candidate.signal_id}"


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
    """Return whether the configured paper capacity is full for a trigger.

    Historical callers used this as a one-position duplicate mutex. It now
    respects `MAX_SIGNALS_PER_SYMBOL_TRIGGER`, so it cannot silently suppress
    Viva's permitted independent scenarios."""
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
            SELECT COUNT(*) FROM signals
            WHERE symbol={p} AND strategy_version={p}
              AND confirmed_at IS NOT NULL
              AND status IN ('AWAITING_PUBLICATION', 'CONFIRMED')
              AND result='PENDING'
              {tf_filter}
              {exclude}
            """,
            tuple(params),
        )
        count = int((cursor.fetchone() or [0])[0] or 0)
        return count >= max(1, int(getattr(SETTINGS, "max_signals_per_symbol_trigger", 3)))


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


def has_open_pre_tp1_signal(symbol: str, trigger_timeframe: str,
                            setup_code: str | None = None) -> bool:
    """Paper-test capacity: allow up to N concurrent signals per
    (symbol, trigger, SETUP) — Viva 2026-09-13: an open ALBROX position may
    never freeze PINVAL's licences on the same symbol/trigger. Without an
    explicit setup the old symbol+trigger counting stays available."""
    p = legacy_db._ph()
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    _setup = str(setup_code or "").upper()
    with legacy_db.db_cursor() as cursor:
        if _setup:
            cursor.execute(
                f"SELECT COUNT(*) FROM signals WHERE symbol={p} AND trigger_timeframe={p} "
                f"AND upper(coalesce(setup_code,''))={p} "
                f"AND confirmed={truth} AND confirmation_sent={truth} "
                f"AND status='CONFIRMED' AND result='PENDING' AND strategy_version={p}",
                (str(symbol).upper(), str(trigger_timeframe).lower(), _setup, SETTINGS.strategy_version),
            )
        else:
            cursor.execute(
                f"SELECT COUNT(*) FROM signals WHERE symbol={p} AND trigger_timeframe={p} "
                f"AND confirmed={truth} AND confirmation_sent={truth} "
                f"AND status='CONFIRMED' AND result='PENDING' AND strategy_version={p}",
                (str(symbol).upper(), str(trigger_timeframe).lower(), SETTINGS.strategy_version),
            )
        count = int((cursor.fetchone() or [0])[0] or 0)
    return count >= max(1, int(getattr(SETTINGS, "max_signals_per_symbol_trigger", 3)))


def last_confirmed_entry(symbol: str, trigger_timeframe: str, setup_code: str,
                         within_hours: int = 24) -> Optional[float]:
    """Price of the latest CONFIRMED signal of this (symbol, trigger, setup)
    inside the rolling licence window. Viva 2026-09-13: the reference point
    for the «≥۲٪ فاصله از آخرین قیمتِ تأییدشده» law. None = never confirmed."""
    p_ = legacy_db._ph()
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=max(1, int(within_hours)))).strftime("%Y-%m-%d %H:%M:%S")
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"SELECT entry FROM signals WHERE symbol={p_} AND trigger_timeframe={p_} "
            f"AND upper(coalesce(setup_code,''))={p_} AND confirmed={truth} "
            f"AND status='CONFIRMED' AND confirmed_at IS NOT NULL AND confirmed_at>={p_} "
            f"ORDER BY confirmed_at DESC LIMIT 1",
            (str(symbol).upper(), str(trigger_timeframe).lower(),
             str(setup_code or "").upper(), cutoff),
        )
        row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def recent_geometry_duplicate(symbol: str, direction: str, entry, sl, tp1,
                              hours: int = 24) -> bool:
    """Viva 2026-09-11: a confirmed signal must carry NEW points. The same
    symbol+direction re-firing with (almost) identical entry/stop/target is the
    SAME trigger re-announced — whatever timeframe or scan cycle produced it.
    Only price moving to a genuinely new zone yields different geometry and is
    allowed even while an earlier signal is still open (max-3 capacity aside).
    History counts: the check spans open AND closed signals in the window."""
    try:
        entry, sl = float(entry), float(sl)
    except (TypeError, ValueError):
        return False
    if entry <= 0 or sl <= 0:
        return False
    p = legacy_db._ph()
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    try:
        with legacy_db.db_cursor() as cursor:
            cursor.execute(
                f"SELECT entry, sl, tp1, confirmed_at FROM signals WHERE symbol={p} "
                f"AND direction={p} AND confirmed={truth} AND confirmed_at IS NOT NULL "
                f"AND status='CONFIRMED' AND strategy_version={p} "
                f"ORDER BY confirmed_at DESC LIMIT 60",
                (str(symbol).upper(), str(direction).upper(), SETTINGS.strategy_version),
            )
            rows = list(cursor.fetchall() or [])
    except Exception:
        return False
    import datetime as _dt
    cut = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=float(hours))

    def _near(a, b, rel):
        try:
            a, b = float(a), float(b)
        except (TypeError, ValueError):
            return True  # missing side must not create a "different" signal
        return abs(a - b) <= max(abs(b) * rel, 1e-9)

    for row in rows:
        try:
            e_old, s_old, t_old, ts = row[0], row[1], row[2], row[3]
            when = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=_dt.timezone.utc)
        except Exception:
            continue
        if when < cut:
            break  # rows are newest-first — the rest are older still
        if _near(entry, e_old, 0.0045) and _near(sl, s_old, 0.0045) \
                and _near(tp1, t_old, 0.012):
            return True
    return False


def save_confirmed_signal(candidate: SignalCandidate) -> bool:
    if candidate.status != "CONFIRMED" or not candidate.confirmed_at:
        raise ValueError("Only a CONFIRMED candidate can be persisted")
    if candidate.score < SETTINGS.execution_min_score or not candidate.execution_ready:
        raise ValueError("Candidate does not meet execution quality gates")
    if confirmed_exists(candidate.signal_id):
        return False
    # The discovery check is not sufficient under retries/races. Enforce the
    # three-position paper capacity again at the persistence boundary — but on
    # the SAME key as the licence law: (symbol, trigger, setup). Viva
    # 2026-09-13: five setups × three licences must remain POSSIBLE to hold
    # confirmed concurrently; a setup-blind cap here made it impossible.
    if has_open_pre_tp1_signal(candidate.symbol, candidate.trigger_timeframe,
                               candidate.setup_code):
        raise RuntimeError(
            f"Paper capacity reached for {candidate.symbol}/{candidate.trigger_timeframe}/"
            f"{candidate.setup_code}: max={SETTINGS.max_signals_per_symbol_trigger}"
        )
    # Second line of defense (discovery already filters this): identical
    # points re-confirmed via a manual/alternate path are refused here too.
    if recent_geometry_duplicate(candidate.symbol, candidate.direction,
                                 candidate.planned_entry or candidate.entry_zone_bottom,
                                 candidate.sl, candidate.tp1):
        raise RuntimeError(
            f"Geometry-duplicate signal refused for {candidate.symbol}/{candidate.direction}: "
            "entry/stop/target match a confirmed signal from the last 24h — a new "
            "signal on this symbol requires a new zone (different points)")
    # Defensive second reservation: discovery reserves before educational
    # publication, while this protects direct/manual confirmation paths too.
    reserve_public_code(candidate)

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

    # Viva 09-19 ladder ruling: exits sit on the DRAWN levels (TP1 floor = 1R),
    # BE is net of the round-trip fee/slippage allowance (professional point 5).
    ladder = build_ladder(
        candidate.planned_entry, candidate.sl, candidate.direction, candidate.market,
        candidate.tp2, structural_tp1=candidate.tp1,
        fee_pct=(SETTINGS.fee_rate_percent + SETTINGS.slippage_percent) * 2.0 / 100.0,
        trigger_tf=str(candidate.trigger_timeframe or "15m"),
        wall_level=float((candidate.metadata or {}).get("internal_wall") or 0.0),
    )
    ladder_json = json.dumps(ladder, ensure_ascii=False)
    with legacy_db.db_cursor() as cursor:
        cursor.execute(sql, params)
        cursor.execute(active_sql, active_params)
        public_code = str(candidate.metadata.get("public_code") or candidate.signal_id)
        variant = str(candidate.metadata.get("strategy_variant") or "")
        # Every new confirmation begins as a scenario awaiting a real Entry touch.
        cursor.execute(f"UPDATE signals SET target_state_json={p}, public_code={p}, strategy_variant={p}, entry_filled={_bool_value(False)}, entry_filled_at=NULL, cancel_reason='' WHERE signal_id={p}", (ladder_json, public_code, variant, candidate.signal_id))
        cursor.execute(f"UPDATE active_signals SET target_state_json={p}, public_code={p}, strategy_variant={p}, entry_filled={_bool_value(False)}, entry_filled_at=NULL, cancel_reason='' WHERE signal_id={p}", (ladder_json, public_code, variant, candidate.signal_id))
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


def reserve_public_code(candidate: SignalCandidate) -> str:
    """Atomically reserve the only public code a position may ever use.

    Six digits are for readability/capacity; the registry primary key, not
    probability, is the guarantee. A collision retries before any Telegram
    message is published. The signal id has a UNIQUE constraint too, making
    retries/restarts return its original code.
    """
    p = legacy_db._ph()
    signal_id = str(candidate.signal_id)
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"SELECT public_code FROM signal_public_code_registry WHERE signal_id={p}", (signal_id,))
        existing = cursor.fetchone()
        if existing:
            code = str(existing[0])
            candidate.metadata["public_code"] = code
            return code

        preferred = str((candidate.metadata or {}).get("public_code") or "")
        # Viva 2026-09-12: an inherited code may belong to ANOTHER family (zone
        # absorbed from a TLBREAK chain, re-published by the TECHCLASSIC
        # engine). The alert id must state the family that is on the badge —
        # a mismatched carry-over is dropped and a fresh code is minted.
        if preferred:
            _fam = generate_viva_public_code(candidate.setup_code, candidate.style)[:-6]
            if not preferred.startswith(_fam):
                preferred = ""
        for attempt in range(64):
            code = preferred if attempt == 0 and preferred else generate_viva_public_code(candidate.setup_code, candidate.style)
            # Never reuse a historical code even if it predates the registry.
            cursor.execute(f"SELECT 1 FROM signals WHERE public_code={p} LIMIT 1", (code,))
            if cursor.fetchone():
                continue
            if legacy_db.USE_POSTGRES:
                cursor.execute(
                    f"INSERT INTO signal_public_code_registry (public_code,signal_id,created_at) "
                    f"VALUES ({p},{p},{p}) ON CONFLICT DO NOTHING",
                    (code, signal_id, _now()),
                )
            else:
                cursor.execute(
                    "INSERT OR IGNORE INTO signal_public_code_registry (public_code,signal_id,created_at) VALUES (?,?,?)",
                    (code, signal_id, _now()),
                )
            cursor.execute(f"SELECT public_code FROM signal_public_code_registry WHERE signal_id={p}", (signal_id,))
            row = cursor.fetchone()
            if row:
                code = str(row[0])
                candidate.metadata["public_code"] = code
                return code
    raise RuntimeError(f"Could not reserve unique public code for {signal_id}")


def set_pro_message_id(signal_id: str, message_id: int) -> None:
    """Persist the canonical VivaMon confirmed-message id for TP/result links."""
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"UPDATE signals SET pro_message_id={p} WHERE signal_id={p}", (int(message_id), signal_id))
        cursor.execute(f"UPDATE active_signals SET pro_message_id={p} WHERE signal_id={p}", (int(message_id), signal_id))


def record_telegram_event(signal_id: str, event_key: str, chat_id: str, message_id: int) -> int:
    """Store and return the canonical Telegram receipt for one exact lifecycle event.

    First write wins deliberately.  A retry may create a duplicate Telegram post,
    but it must never silently repoint historical Win Rate links to a newer trade
    with the same symbol or to a later retry.
    """
    signal_id, event_key = str(signal_id or ""), str(event_key or "").upper()
    if not signal_id or not event_key or not chat_id or not message_id:
        return 0
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        if legacy_db.USE_POSTGRES:
            cursor.execute(
                f"INSERT INTO signal_telegram_events (signal_id,event_key,chat_id,message_id,created_at) "
                f"VALUES ({p},{p},{p},{p},{p}) ON CONFLICT (signal_id,event_key) DO NOTHING",
                (signal_id, event_key, str(chat_id), int(message_id), _now()),
            )
        else:
            cursor.execute(
                "INSERT OR IGNORE INTO signal_telegram_events (signal_id,event_key,chat_id,message_id,created_at) VALUES (?,?,?,?,?)",
                (signal_id, event_key, str(chat_id), int(message_id), _now()),
            )
        cursor.execute(
            f"SELECT message_id FROM signal_telegram_events WHERE signal_id={p} AND event_key={p}",
            (signal_id, event_key),
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def get_telegram_event_message_id(signal_id: str, event_key: str) -> int:
    """Resolve only by immutable position id + event type; never by symbol."""
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"SELECT message_id FROM signal_telegram_events WHERE signal_id={p} AND event_key={p}",
            (str(signal_id), str(event_key).upper()),
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


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


def viva_tlbreak_performance() -> dict:
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"SELECT result, pnl_pct, pnl_usd FROM signals WHERE strategy_version={p} AND strategy_variant='VIVA_TLBREAK'", (SETTINGS.strategy_version,))
        rows = cursor.fetchall()
    wins = sum(1 for r, *_ in rows if r == "WIN")
    losses = sum(1 for r, *_ in rows if r == "LOSS")
    closed = wins + losses
    return {"total":len(rows),"wins":wins,"losses":losses,"pending":sum(1 for r,*_ in rows if r=="PENDING"),"winrate":wins/closed*100 if closed else 0.0,"pnl_pct":sum(float(x[1] or 0) for x in rows),"pnl_usd":sum(float(x[2] or 0) for x in rows)}


def setup_performance(source_code: str) -> dict:
    """Per-setup journal stats (Viva 09-19: the management panel must cover
    ALL five setups, not only TLBREAK) — wins/losses/WR plus average win and
    average loss so the R-asymmetry is visible, never hidden."""
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(
            f"SELECT result, pnl_pct, pnl_usd FROM signals "
            f"WHERE strategy_version={p} AND source={p}",
            (SETTINGS.strategy_version, str(source_code)),
        )
        rows = cursor.fetchall()
    wins = [float(x[1] or 0) for r, x in [(r[0], r) for r in rows] if r == "WIN"]
    wins = [float(r[1] or 0) for r in rows if r[0] == "WIN"]
    losses = [float(r[1] or 0) for r in rows if r[0] == "LOSS"]
    closed = len(wins) + len(losses)
    return {
        "total": len(rows), "wins": len(wins), "losses": len(losses),
        "pending": sum(1 for r in rows if r[0] == "PENDING"),
        "winrate": len(wins) / closed * 100 if closed else 0.0,
        "pnl_pct": sum(float(r[1] or 0) for r in rows),
        "pnl_usd": sum(float(r[2] or 0) for r in rows),
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
    }


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



def _reentry_event_from_row(row, cutoff) -> Optional[Dict]:
    """One row → one REENTRY_SIGNAL event, or None. Isolated on purpose.

    Round 13: this body used to run inline inside the scan, so a single bad row
    silenced the whole lane — and a raw `%` inside the LIKE wildcards made
    psycopg2 interpolate that string and raise `IndexError: tuple index out of
    range` on EVERY cycle. Viva's round-9 re-entry law («سیگنال ورود مجدد روی
    همان پول‌بک») therefore never produced one single signal; the patterns are
    parameters now and each row stands on its own.
    """
    p = legacy_db._ph()
    (signal_id, symbol, direction, entry, original_sl, leverage, margin, style,
     source, strategy_fa, strategy_version, pro_message_id, ladder_json,
     public_code, trigger_timeframe, closed_at) = row
    try:
        closed_dt = pd.to_datetime(closed_at).to_pydatetime() if closed_at is not None else None
    except Exception:
        closed_dt = None
    if closed_dt is None or closed_dt < cutoff:
        return None
    try:
        ladder = json.loads(ladder_json or "{}")
    except Exception:
        return None
    trade_tf = str(trigger_timeframe or "15m").lower()
    timeframe = monitor_tf_for(trade_tf)
    frame = get_klines(symbol, timeframe, 200, closed_only=True, use_cache=True)
    if frame is None or frame.empty:
        return None
    ts = pd.to_datetime(frame["timestamp"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    window = frame.loc[ts > (_naive_timestamp(closed_at) or ts.iloc[0])]
    if len(window) < 3:
        return None
    candles = [{"open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
                "volume": float(r["volume"] or 0.0)} for _, r in window.iterrows()]
    atr = 0.0
    try:
        atr = float((frame["high"].tail(14) - frame["low"].tail(14)).mean() or 0.0)
    except Exception:
        atr = 0.0
    setup = reentry_setup(direction, candles, ladder, atr=atr)
    if not setup:
        return None
    ladder["reentry_signaled"] = True
    ladder["reentry_levels"] = {k: float(setup[k]) for k in ("entry", "sl", "tp1", "tp2")}
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"UPDATE signals SET target_state_json={p} WHERE signal_id={p}",
                       (json.dumps(ladder, ensure_ascii=False), signal_id))
        cursor.execute(f"UPDATE active_signals SET target_state_json={p} WHERE signal_id={p}",
                       (json.dumps(ladder, ensure_ascii=False), signal_id))
    return {
        "event": "REENTRY_SIGNAL", "signal_id": signal_id, "symbol": symbol,
        "direction": direction, "style": style, "source": source,
        "strategy_fa": strategy_fa, "strategy_version": strategy_version,
        "pro_message_id": int(pro_message_id or 0), "public_code": public_code,
        "trigger_timeframe": trade_tf, "monitor_tf": timeframe,
        "entry": float(setup["entry"]), "sl": float(setup["sl"]),
        "tp1": float(setup["tp1"]), "tp2": float(setup["tp2"]),
        "entry_filled_at": "", "confirmation_sent": True,
        "reason_fa": str(setup.get("note_fa") or ""),
        "banked_tp1": (ladder.get("targets") or [None])[max(0, int(ladder.get("hit_index") or 1) - 1)],
        "hit_index": int(ladder.get("hit_index") or 0),
        "live_price": float(candles[-1]["close"]),
        "event_at": str(window.iloc[-1].get("timestamp") or ""),
    }


def reentry_scan_events(hours: int = 24) -> List[Dict]:
    """Viva 09-20 (round 9) — fresh entry signal on the pullback.

    A position closed by the protection phase (SMART_EXIT) keeps its TP1
    profit locked; if price then merely pulls back to the first-target area
    and a closed candle confirms, the ladder emits ONE re-entry signal for
    the same code. Bounded: only ladders armed in the last ``hours`` and not
    yet signalled are inspected, so a closed trade can never spam.
    """
    events: List[Dict] = []
    p = legacy_db._ph()
    try:
        with legacy_db.db_cursor() as cursor:
            cursor.execute(f"""
                SELECT signal_id, symbol, direction, entry, sl_original, leverage, margin_usd,
                       trade_style, source, strategy_fa, strategy_version, pro_message_id,
                       target_state_json, public_code, trigger_timeframe, closed_at
                FROM signals
                WHERE status='CLOSED'
                  AND closed_at IS NOT NULL
                  AND target_state_json LIKE {p}
                  AND target_state_json NOT LIKE {p}
                  AND strategy_version={p}
                ORDER BY closed_at DESC LIMIT 40
            """, ('%"reentry_armed": true%', '%"reentry_signaled": true%',
                  SETTINGS.strategy_version))
            rows = cursor.fetchall()
        if not rows:
            return events
        cutoff = _now() - timedelta(hours=int(hours or 24))
        for row in rows:
            try:
                _ev = _reentry_event_from_row(row, cutoff)
            except Exception as exc:
                # one bad row must never silence the whole lane (round 13)
                print(f"reentry row skipped ({row[0] if row else '?'}): {exc}")
                continue
            if _ev:
                events.append(_ev)
    except Exception as exc:  # fail-open: re-entry is an opportunity, not a gate
        print(f"reentry scan error: {exc}")
    return events


def monitor_confirmed_trades() -> List[Dict]:
    """Process each closed candle chronologically; no historical `.any()` shortcuts."""
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"""
            SELECT signal_id, symbol, direction, entry, sl_original, tp1, tp2,
                   leverage, margin_usd, trade_style, confirmed_at,
                   last_checked_at, tp1_hit, source, strategy_fa,
                   strategy_version, pro_message_id, target_state_json, public_code, first_tp_message_id, trigger_timeframe,
                   entry_filled, entry_filled_at
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
            entry_filled, entry_filled_at,
        ) = row
        # Viva 09-19 monitoring hierarchy (ALL setups): fills, ladder,
        # profit-floor trail and reversal score run on the FINER monitor TF
        # (1D→1H, 4H/1H→15m, 15m→5m, 5m→1m); falls back to the trade TF when
        # the venue has no finer interval for this symbol.
        trade_tf = str(trigger_timeframe or ("5m" if style == "SCALP" else "15m")).lower()
        timeframe = monitor_tf_for(trade_tf)
        key = (symbol, timeframe)
        if key not in by_symbol_tf:
            by_symbol_tf[key] = get_klines(symbol, timeframe, 300, closed_only=True, use_cache=False)
        frame = by_symbol_tf[key]
        if (frame is None or frame.empty) and timeframe != trade_tf:
            timeframe = trade_tf
            key = (symbol, timeframe)
            if key not in by_symbol_tf:
                by_symbol_tf[key] = get_klines(symbol, timeframe, 300, closed_only=True, use_cache=False)
            frame = by_symbol_tf[key]
        if frame is None or frame.empty:
            continue
        _atr_n = vol_atr_n_for(trade_tf, timeframe)
        start = _naive_timestamp(last_checked_at) or _naive_timestamp(confirmed_at)
        timestamps = pd.to_datetime(frame["timestamp"])
        if getattr(timestamps.dt, "tz", None) is not None:
            timestamps = timestamps.dt.tz_convert("UTC").dt.tz_localize(None)
        pending = frame.loc[timestamps > start].copy() if start is not None else frame.tail(1).copy()
        if pending.empty:
            continue

        # ── Entry Fill Gate ──────────────────────────────────────────────
        # Confirmed means the analysis was approved; it does NOT mean a limit
        # entry filled. Do not allow pre-entry price to hit a stop/TP and turn
        # an untouched scenario into a WIN or LOSS.
        if not bool(entry_filled):
            confirmed_ts = _naive_timestamp(confirmed_at)
            max_fill_bars = (
                SETTINGS.entry_fill_max_bars_swing if str(style).upper() == "SWING"
                else SETTINGS.entry_fill_max_bars_scalp if str(style).upper() == "SCALP"
                else SETTINGS.entry_fill_max_bars_daytrade
            )
            fill_candle = None
            ambiguous_entry_stop = False
            for _, candle in pending.iterrows():
                high, low = float(candle["high"]), float(candle["low"])
                if not entry_touched(float(entry), high, low):
                    continue
                # OHLC cannot prove ordering if entry and original stop were
                # both crossed in one candle. Fail closed as NO TRADE rather
                # than inventing a loss before an executable fill is proven.
                stop_crossed = low <= float(original_sl) if str(direction).upper() == "LONG" else high >= float(original_sl)
                if stop_crossed:
                    ambiguous_entry_stop = True
                else:
                    fill_candle = candle
                break

            if fill_candle is not None:
                filled_at = _naive_timestamp(fill_candle["timestamp"])
                filled_text = filled_at.isoformat(sep=" ", timespec="seconds") if filled_at is not None else _now()
                with legacy_db.db_cursor() as cursor:
                    cursor.execute(f"UPDATE signals SET entry_filled={truth}, entry_filled_at={p}, last_checked_at={p} WHERE signal_id={p}", (filled_text, filled_text, signal_id))
                    cursor.execute(f"UPDATE active_signals SET entry_filled={truth}, entry_filled_at={p}, last_checked_at={p} WHERE signal_id={p}", (filled_text, filled_text, signal_id))
                # Begin TP/stop accounting from the following monitor cycle;
                # this avoids taking credit for a target crossed before entry.
                continue

            # Viva 09-19 (his restated ruling): NO candle-count limit on
            # filling — an unfilled position is cancelled ONLY when its
            # time expiry (zone-invalidation horizon) passes, never because
            # N candles printed without a touch.
            from analysis.setups_v7 import expiry_hours_for
            _hrs = float(expiry_hours_for(str(style).upper(),
                                          str(trigger_timeframe or "")))
            _conf_ts = _naive_timestamp(confirmed_at)
            _now_ts = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
            expired = _conf_ts is not None and \
                _now_ts >= _conf_ts + pd.Timedelta(hours=_hrs)
            if ambiguous_entry_stop or expired:
                reason = "AMBIGUOUS_ENTRY_STOP_SAME_CANDLE" if ambiguous_entry_stop else "EXPIRED_UNFILLED"
                closed_at = _now()
                with legacy_db.db_cursor() as cursor:
                    cursor.execute(f"UPDATE signals SET status='CANCELLED', result='CANCELLED', cancel_reason={p}, closed_at={p}, last_checked_at={p} WHERE signal_id={p}", (reason, closed_at, closed_at, signal_id))
                    cursor.execute(f"UPDATE active_signals SET status='CANCELLED', is_cancelled={truth}, cancel_reason={p}, last_checked_at={p} WHERE signal_id={p}", (reason, closed_at, signal_id))
                    cursor.execute(f"DELETE FROM signal_symbol_locks WHERE symbol={p} AND signal_id={p} AND strategy_version={p}", (symbol, signal_id, SETTINGS.strategy_version))
                events.append({
                    "event": "NO_FILL", "signal_id": signal_id, "symbol": symbol, "direction": direction,
                    "style": style, "source": source, "strategy_fa": strategy_fa, "strategy_version": strategy_version,
                    "confirmed_at": str(confirmed_at), "confirmation_sent": True, "pro_message_id": int(pro_message_id or 0),
                    "public_code": public_code, "entry": float(entry), "original_sl": float(original_sl),
                    "trigger_timeframe": timeframe, "event_at": closed_at, "reason": reason,
                })
                continue

            # Still awaiting Entry: move the cursor only. This state has no
            # PnL and is excluded from Win Rate until a real fill exists.
            latest = _naive_timestamp(pending.iloc[-1]["timestamp"])
            if latest is not None:
                latest_text = latest.isoformat(sep=" ", timespec="seconds")
                with legacy_db.db_cursor() as cursor:
                    cursor.execute(f"UPDATE signals SET last_checked_at={p} WHERE signal_id={p}", (latest_text, signal_id))
                    cursor.execute(f"UPDATE active_signals SET last_checked_at={p} WHERE signal_id={p}", (latest_text, signal_id))
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
            for _cidx, candle in pending.iterrows():
                latest_checked = _naive_timestamp(candle["timestamp"])
                # FIX (review 09-25): the candle's position in `frame` is
                # resolved HERE, before any trailing maths. The R29 block
                # below used `'_pos' in locals()`, which was False before TP1
                # (→ frame.tail(31): the trailing stop of an OLD pending candle
                # was computed from FUTURE candles = look-ahead in results) and
                # stale by one candle after TP1.
                try:
                    _pos = int(frame.index.get_loc(_cidx))
                except Exception:
                    _pos = len(frame) - 1
                step = advance_ladder(ladder, float(candle["high"]), float(candle["low"]))
                ladder = step["state"]
                raw_events = list(step["events"])
                # R29 professional trailing is evaluated on every closed monitor candle.
                # Before TP1 it may only ratchet structural room; NET-BE is impossible
                # until TP1 is actually hit. After TP1 it includes fees/slippage.
                try:
                    _r29_frame = frame.iloc[max(0, _pos - 30):_pos + 1]
                    _r29_candles = [{"open": float(r["open"]), "high": float(r["high"]),
                                     "low": float(r["low"]), "close": float(r["close"])}
                                    for _, r in _r29_frame.iterrows()]
                    _r29trail = trailing_from_ladder(ladder, _r29_candles, direction)
                    ladder = _r29trail.get("state", ladder)
                    raw_events.extend(_r29trail.get("events") or [])
                except Exception as _r29trail_exc:
                    ladder["r29_trailing_error"] = str(_r29trail_exc)[:180]

                # Viva 09-19 smart-trailing ruling (+ his professional engine
                # spec §4/§5/§7/§9): after the first target prints, the stop
                # follows the formula-based protection floor between targets
                # (ratcheting, once per CLOSED candle — never per tick), and
                # the monitor TF scores reversal pressure. ONE sign = ORANGE
                # short warning; TWO+ concurrent signs = RED = close ALL
                # remainder at this candle's close (Viva 09-19/20: signs must
                # never stay warn-only in the protection phase), with an
                # explainable reason list.
                if (not ladder.get("closed") and int(ladder.get("version") or 1) >= 2
                        and int(ladder.get("hit_index") or 0) >= 1):
                    wcandles = []
                    try:
                        _win = frame.iloc[max(0, _pos - 30):_pos + 1]
                        wcandles = [{"open": float(r["open"]), "high": float(r["high"]),
                                     "low": float(r["low"]), "close": float(r["close"]),
                                     "volume": float(r["volume"] or 0.0)}
                                    for _, r in _win.iterrows()]
                    except Exception:
                        wcandles = []
                    if len(wcandles) >= 21:
                        tstep = band_trailing(ladder, wcandles, atr_n=_atr_n)
                        ladder = tstep["state"]
                        raw_events.extend(tstep["events"])
                        scan = smart_exit_scan(direction, wcandles, ladder)
                        # «مدیریت ویوا» §6.1 (09-20): the earliest reversal sign
                        # is read on the FAST frame (15m trade → 3m) and only
                        # raises the ORANGE warning; the exit itself stays on
                        # the monitor frame's confirmed close.
                        _fast_tf = ""
                        _fast_reason = ""
                        _fast_pin_tf = ""
                        _fast_pin_reason = ""
                        try:
                            _fast_tf = fast_watch_tf_for(trade_tf)
                            _fast_reason = ""
                            if _fast_tf != timeframe and _fast_tf in TF_MINUTES:
                                _fkey = (symbol, _fast_tf)
                                if _fkey not in by_symbol_tf:
                                    by_symbol_tf[_fkey] = get_klines(
                                        symbol, _fast_tf, 120, closed_only=True,
                                        use_cache=True)
                                _fframe = by_symbol_tf.get(_fkey)
                                if _fframe is not None and not _fframe.empty:
                                    _fc = [{"open": float(r["open"]), "high": float(r["high"]),
                                            "low": float(r["low"]), "close": float(r["close"]),
                                            "volume": float(r["volume"] or 0.0)}
                                           for _, r in _fframe.tail(30).iterrows()]
                                    _fscan = smart_exit_scan(direction, _fc, ladder)
                                    if int(_fscan.get("score") or 0) >= 1:
                                        _fast_reason = "; ".join(
                                            list(_fscan.get("reasons") or [])[:2])
                                    # Viva 09-20 (round 9, verbatim): «اولین
                                    # پین‌بارِ بسته‌شدهٔ معکوس روی ۵ دقیقه در
                                    # رنج TP1 تا TP2 = خروج فوری باقی‌مانده» —
                                    # the closure of the fast frame is the exit
                                    # itself (not just the orange preview).
                                    if _fscan.get("reverse_pin"):
                                        _fast_pin_tf = _fast_tf
                                        _fast_pin_reason = "; ".join(
                                            list(_fscan.get("reasons") or [])[:2])
                            if _fast_reason:
                                ladder["fast_watch_tf"] = _fast_tf
                                ladder["fast_watch_reason_fa"] = _fast_reason
                        except Exception:
                            _fast_reason = ""
                        # Viva 09-19/20 ruling (verbatim): in the PROFIT
                        # PROTECTION phase (after TP1) reversal signs must
                        # never «رد بشه و فقط هشدار بمونه» — two concurrent
                        # signs (candle pattern + sell pressure / volume)
                        # close ALL remainder at this monitor candle's close,
                        # even before price returns to TP1. One sign = short
                        # warning only; before TP1 the structural stop rules.
                        _pin_closed = (any("پین‌بار" in str(_r)
                                           for _r in (scan.get("reasons") or []))
                                       or bool(_fast_pin_reason))
                        if int(scan.get("score") or 0) >= 2 or _pin_closed:
                            _hit = int(ladder.get("hit_index") or 0)
                            _wts = [float(w) for w in (ladder.get("weights") or [])]
                            _remaining = 100.0 - sum(_wts[:_hit])
                            _close_px = float(candle["close"])
                            _risk = float(ladder.get("risk") or abs(float(entry) - float(original_sl)))
                            _exit_r = ((_close_px - float(entry)) / _risk
                                       if str(direction).upper() == "LONG"
                                       else ((float(entry) - _close_px) / _risk))
                            ladder["realized_r"] = float(ladder.get("realized_r") or 0.0) + _exit_r * _remaining / 100.0
                            ladder["current_sl"] = _close_px
                            ladder["closed"] = True
                            ladder["close_reason"] = "SMART_EXIT"
                            _reasons = list(scan.get("reasons") or [])
                            if _fast_pin_reason and not any(
                                    "پین‌بار" in str(_r) for _r in _reasons):
                                _reasons.insert(0, "پین‌بار معکوس بسته‌شده در تایم سریع "
                                                   f"{_fast_pin_tf} (رنج TP1→TP2): "
                                                   f"{_fast_pin_reason}")
                            if _pin_closed and len(_reasons) < 2:
                                _reasons.insert(0, "پین‌بار معکوس تأییدشده در تایم مانیتور "
                                                   "(«مدیریت ویوا» §۶٫۱: خروج باقی‌مانده)")
                            ladder["exit_reasons_fa"] = _reasons
                            # Viva 09-20: the banked TP1 profit stays locked;
                            # a pullback afterwards is a fresh entry signal.
                            ladder["reentry_armed"] = True
                        elif ((int(scan.get("score") or 0) == 1 or _fast_reason)
                                and int(ladder.get("warned_band") or 0) != int(ladder.get("hit_index") or 0)):
                            # «مدیریت ویوا» §6.1: the orange warning precedes the
                            # red exit — a fast-frame (3m) sign or a single
                            # monitor-frame sign raises it once per band.
                            ladder["warned_band"] = int(ladder.get("hit_index") or 0)
                            _warn_reasons = list(scan.get("reasons") or [])
                            if _fast_reason:
                                _warn_reasons = [
                                    f"نشانهٔ بازگشت در تایم سریع {_fast_tf}: {_fast_reason}"
                                ] + _warn_reasons
                            raw_events.append({
                                "event": "EXIT_WARNING", "score": int(scan.get("score") or 0),
                                "reasons_fa": _warn_reasons,
                                "fast_tf": str(_fast_tf or ""),
                                "hit_index": int(ladder.get("hit_index") or 0),
                            })
                for event in raw_events:
                    event.update({
                        "signal_id": signal_id, "symbol": symbol, "direction": direction,
                        "style": style, "source": source, "strategy_fa": strategy_fa,
                        "strategy_version": strategy_version, "confirmed_at": str(confirmed_at),
                        # 09-20 time-axis law: the chart needs the REAL fill
                        # candle so the position tool anchors there.
                        "entry_filled_at": str(entry_filled_at or confirmed_at or ""),
                        "confirmation_sent": True, "pro_message_id": int(pro_message_id or 0), "public_code": public_code,
                        "entry": float(entry), "sl": float(ladder["current_sl"]), "original_sl": float(original_sl),
                        "leverage": int(leverage or 1), "margin": float(margin or 0), "live_price": float(candle["close"]),
                        "event_at": str(candle["close_time"] if "close_time" in candle else candle["timestamp"]), "trigger_timeframe": str(trigger_timeframe or ""), "monitor_tf": str(timeframe), "targets": list(ladder["targets"]), "hit_index": int(ladder["hit_index"]), "last_tp_message_id": int(ladder.get("last_tp_message_id") or 0),
                    })
                    notional = float(margin or 0) * int(leverage or 1)
                    risk_pct_move = abs(float(entry) - float(original_sl)) / float(entry) * 100
                    if str(event.get("event", "")).startswith("TP"):
                        target_index = int(event["event"][2:]) - 1
                        # round 14: price distance to the TP, straight from prices
                        _tgs = list(ladder.get("targets") or [])
                        if _tgs and target_index < len(_tgs) and float(entry):
                            event["leg_price_move_pct"] = (abs(float(_tgs[target_index]) - float(entry))
                                                           / abs(float(entry)) * 100.0)
                        else:
                            leg_r = float(ladder.get("target_r", [])[target_index]) if target_index < len(ladder.get("target_r", [])) else 0.0
                            event["leg_price_move_pct"] = leg_r * risk_pct_move
                        event["leg_pnl_pct"] = event["leg_price_move_pct"] * float(event.get("weight", 0)) / 100
                        event["leg_profit_usd"] = notional * event["leg_pnl_pct"] / 100
                        event["leg_margin_roi_pct"] = event["leg_profit_usd"] / max(float(margin or 0), 1e-12) * 100
                        event["leg_full_roi_pct"] = event["leg_price_move_pct"] * int(leverage or 1)
                    else:
                        event["realized_pnl_pct"] = float(ladder.get("realized_r", 0)) * risk_pct_move
                        event["realized_profit_usd"] = notional * event["realized_pnl_pct"] / 100
                        event["realized_margin_roi_pct"] = event["realized_profit_usd"] / max(float(margin or 0), 1e-12) * 100
                    ladder_events.append(event)
                if ladder.get("closed"):
                    break
            with legacy_db.db_cursor() as cursor:
                if int(ladder.get("hit_index") or 0) >= 1:
                    cursor.execute(f"UPDATE signals SET tp1_hit={truth}, partial_win={truth} WHERE signal_id={p}", (signal_id,))
                    cursor.execute(f"UPDATE active_signals SET tp1_hit={truth}, partial_win={truth} WHERE signal_id={p}", (signal_id,))
                if latest_checked is not None:
                    checked_text = latest_checked.isoformat(sep=" ", timespec="seconds")
                    cursor.execute(f"UPDATE signals SET target_state_json={p}, sl={p}, last_checked_at={p} WHERE signal_id={p}",
                                   (json.dumps(ladder), float(ladder["current_sl"]), checked_text, signal_id))
                    cursor.execute(f"UPDATE active_signals SET target_state_json={p}, sl={p}, last_checked_at={p} WHERE signal_id={p}",
                                   (json.dumps(ladder), float(ladder["current_sl"]), checked_text, signal_id))
                if ladder.get("closed"):
                    notional = float(margin or 0) * int(leverage or 1)
                    gross_pnl = float(ladder.get("realized_r", 0)) * abs(float(entry) - float(original_sl)) / float(entry) * 100
                    # Viva 2026-09-14: settlement = gross minus the exchange
                    # round-trip FEE only; slippage is a display note. (ZEC
                    # K120563 proved the old double cut flips protected wins.)
                    net_pnl = gross_pnl - 2 * SETTINGS.fee_rate_percent
                    profit_usd = notional * net_pnl / 100
                    result = "WIN" if net_pnl > 0 else "LOSS"
                    cursor.execute(f"UPDATE signals SET result={p}, pnl_pct={p}, pnl_usd={p}, closed_at={p} WHERE signal_id={p}",
                                   (result, net_pnl, profit_usd, _now(), signal_id))
                    cursor.execute(f"UPDATE active_signals SET status='CLOSED', is_cancelled={truth} WHERE signal_id={p}", (signal_id,))
                    cursor.execute(f"DELETE FROM signal_symbol_locks WHERE symbol={p} AND signal_id={p} AND strategy_version={p}",
                                   (symbol, signal_id, SETTINGS.strategy_version))
                    ladder_events.append({
                        "event":"CLOSED", "signal_id":signal_id,"symbol":symbol,"style":style,"source":source,"strategy_fa":strategy_fa,
                        "strategy_version":strategy_version,"confirmed_at":str(confirmed_at),"confirmation_sent":True,
                        "pro_message_id":int(pro_message_id or 0),"public_code":public_code,
                        "result":result,"pnl":net_pnl,"gross_pnl":gross_pnl,"profit_usd":profit_usd,
                        "entry_filled_at": str(entry_filled_at or confirmed_at or ""),
                        "margin":float(margin or 0),"leverage":int(leverage or 1),
                        "margin_roi_pct":profit_usd / max(float(margin or 0),1e-12)*100,
                        "entry":float(entry),"original_sl":float(original_sl),"sl":float(ladder["current_sl"]),
                        "targets":list(ladder["targets"]),"hit_index":int(ladder["hit_index"]),
                        "event_at":str(latest_checked or confirmed_at),"trigger_timeframe":str(trigger_timeframe or ""),
                        "live_price":float(candle["close"]),
                        "trailing_used": bool(int(ladder.get("hit_index") or 0) > 0
                                              and abs(float(ladder.get("current_sl") or 0) - float(original_sl)) > 1e-9),
                        "close_reason": str(ladder.get("close_reason") or ""),
                        "exit_reasons_fa": list(ladder.get("exit_reasons_fa") or []),
                        "direction": direction,
                    })
            events.extend(ladder_events)
            continue

        state_tp1 = bool(tp1_hit)
        closed_event = None
        tp1_event = None
        latest_checked = start
        # Viva 09-19 P&L truth: a trailed stop that sits BETTER than the
        # original one IS the real exit level; booking the original stop
        # after a trail inflated losses. Zero targets = no target logic at
        # all (watch-style rows must never "hit TP1 at price 0").
        _live_sl = original_sl
        try:
            _row_sl = float(row.get("sl") or original_sl) if hasattr(row, "get") else original_sl
        except Exception:
            _row_sl = original_sl
        if direction == "LONG" and original_sl < _row_sl < entry:
            _live_sl = _row_sl
        if direction == "SHORT" and entry < _row_sl < original_sl:
            _live_sl = _row_sl
        _has_targets = float(tp1) > 0 and float(tp2) > 0
        for _, candle in pending.iterrows():
            latest_checked = _naive_timestamp(candle["timestamp"])
            high, low = float(candle["high"]), float(candle["low"])
            if direction == "LONG":
                stop_hit = low <= (max(entry, _live_sl) if state_tp1 else _live_sl)
                first_hit = _has_targets and high >= tp1
                final_hit = _has_targets and high >= tp2
            else:
                stop_hit = high >= (min(entry, _live_sl) if state_tp1 else _live_sl)
                first_hit = _has_targets and low <= tp1
                final_hit = _has_targets and low <= tp2

            # Conservative ambiguity rule: if stop and target occur in the same
            # candle, assume the stop happened first because tick order is unknown.
            if stop_hit:
                if state_tp1:
                    pnl = _weighted_win_pct(direction, entry, tp1, tp2, True)
                    result = "WIN"
                    reason = "TP1 سپس Breakeven"
                else:
                    pnl = ((_live_sl - entry) / entry * 100) if direction == "LONG" else ((entry - _live_sl) / entry * 100)
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
                    "entry_filled_at": str(entry_filled_at or confirmed_at or ""),
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
                roundtrip_cost = 2 * SETTINGS.fee_rate_percent
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
                    "entry_filled_at": str(entry_filled_at or confirmed_at or ""),
                    "confirmation_sent": True,
                    "pro_message_id": int(pro_message_id or 0), "public_code": public_code,
                    "trigger_timeframe": str(trigger_timeframe or ""), "original_sl": float(original_sl),
                    "entry": float(entry), "leverage": int(leverage or 1), "margin": float(margin or 0),
                    "live_price": float(candle.close) if "candle" in locals() else float(entry),
                    # HOT-1 (Viva audit 09-15): `resolved_at` never existed — the
                    # NameError here committed the CLOSED row but killed the
                    # event, so the result message never reached any channel.
                    # The ladder path uses the same truth: the candle that
                    # closed the position, else the last checked bar.
                    "event_at": str(latest_checked or confirmed_at),
                    "first_tp_message_id": int(first_tp_message_id or 0),
                })
        if tp1_event:
            events.append(tp1_event)
        if closed_event:
            events.append(closed_event)
    return events
