# database/db.py - Supabase PostgreSQL + SQLite fallback
# v6: Multi-signal flow, partial TP, strategy tracking, MTF
import os
import json
import uuid
from datetime import datetime, timedelta
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
else:
    import sqlite3
    DB_PATH = os.environ.get("DB_PATH", "/tmp/signals.db")


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _ph() -> str:
    return "%s" if USE_POSTGRES else "?"


def generate_signal_id(symbol: str, source: str) -> str:
    ts = datetime.utcnow().strftime("%m%d%H%M")
    rand = uuid.uuid4().hex[:4].upper()
    clean = symbol.replace("USDT", "").replace(".P", "")
    return f"viva-{clean}-{source}-{ts}-{rand}"


def get_conn():
    if USE_POSTGRES:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url, sslmode="require")
    return sqlite3.connect(DB_PATH)


@contextmanager
def db_cursor():
    conn = get_conn()
    try:
        c = conn.cursor()
        yield c
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db_cursor() as c:
        if USE_POSTGRES:
            c.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id SERIAL PRIMARY KEY,
                    symbol TEXT,
                    source TEXT,
                    strategy_fa TEXT DEFAULT '',
                    direction TEXT,
                    entry REAL,
                    sl REAL,
                    sl_original REAL,
                    tp1 REAL,
                    tp2 REAL,
                    bias TEXT,
                    confirmations TEXT,
                    description TEXT DEFAULT '',
                    entry_conditions TEXT DEFAULT '',
                    result TEXT DEFAULT 'PENDING',
                    pnl_pct REAL DEFAULT 0,
                    signal_id TEXT,
                    leverage INTEGER DEFAULT 5,
                    margin_usd REAL DEFAULT 0,
                    trade_style TEXT DEFAULT 'SWING',
                    scalp_tf TEXT DEFAULT '',
                    swing_tf TEXT DEFAULT '',
                    mtf_4h TEXT DEFAULT '',
                    mtf_1h TEXT DEFAULT '',
                    mtf_15m TEXT DEFAULT '',
                    score INTEGER DEFAULT 0,
                    tp1_hit BOOLEAN DEFAULT FALSE,
                    tp1_hit_at TEXT,
                    sl_moved_to_be BOOLEAN DEFAULT FALSE,
                    partial_tp1_pct REAL DEFAULT 60,
                    partial_tp2_pct REAL DEFAULT 40,
                    approaching_sent BOOLEAN DEFAULT FALSE,
                    confirmed BOOLEAN DEFAULT FALSE,
                    created_at TEXT,
                    closed_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS market_memory (
                    id SERIAL PRIMARY KEY,
                    symbol TEXT UNIQUE,
                    bias TEXT,
                    near_ob BOOLEAN DEFAULT FALSE,
                    ob_top REAL DEFAULT 0,
                    ob_bottom REAL DEFAULT 0,
                    ob_strength REAL DEFAULT 0,
                    has_sweep BOOLEAN DEFAULT FALSE,
                    has_choch BOOLEAN DEFAULT FALSE,
                    rtm_pattern TEXT DEFAULT '',
                    rtm_fresh BOOLEAN DEFAULT FALSE,
                    ict_in_ote BOOLEAN DEFAULT FALSE,
                    ict_in_killzone BOOLEAN DEFAULT FALSE,
                    current_price REAL DEFAULT 0,
                    prev_price REAL DEFAULT 0,
                    price_change_pct REAL DEFAULT 0,
                    updated_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS active_signals (
                    id SERIAL PRIMARY KEY,
                    signal_id TEXT UNIQUE,
                    symbol TEXT,
                    source TEXT,
                    strategy_fa TEXT DEFAULT '',
                    direction TEXT,
                    entry REAL,
                    sl REAL,
                    sl_original REAL,
                    tp1 REAL,
                    tp2 REAL,
                    bias TEXT,
                    leverage INTEGER,
                    margin_usd REAL,
                    score INTEGER DEFAULT 0,
                    is_confirmed BOOLEAN DEFAULT FALSE,
                    is_cancelled BOOLEAN DEFAULT FALSE,
                    approaching_sent BOOLEAN DEFAULT FALSE,
                    tp1_hit BOOLEAN DEFAULT FALSE,
                    sl_moved_to_be BOOLEAN DEFAULT FALSE,
                    partial_tp1_pct REAL DEFAULT 60,
                    partial_tp2_pct REAL DEFAULT 40,
                    created_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS strategy_stats (
                    id SERIAL PRIMARY KEY,
                    strategy TEXT UNIQUE,
                    strategy_fa TEXT DEFAULT '',
                    total_signals INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    pending INTEGER DEFAULT 0,
                    total_pnl_pct REAL DEFAULT 0,
                    best_pnl REAL DEFAULT 0,
                    worst_pnl REAL DEFAULT 0,
                    avg_pnl REAL DEFAULT 0,
                    winrate REAL DEFAULT 0,
                    avg_score REAL DEFAULT 0,
                    last_signal_at TEXT,
                    updated_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id SERIAL PRIMARY KEY,
                    strategy TEXT,
                    symbol TEXT,
                    direction TEXT,
                    entry REAL,
                    sl REAL,
                    tp1 REAL,
                    tp2 REAL,
                    result TEXT,
                    pnl_pct REAL DEFAULT 0,
                    bars_held INTEGER DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    created_at TEXT
                )
            """)
        else:
            c.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT, source TEXT, strategy_fa TEXT DEFAULT '',
                    direction TEXT, entry REAL, sl REAL, sl_original REAL,
                    tp1 REAL, tp2 REAL, bias TEXT, confirmations TEXT,
                    description TEXT DEFAULT '', entry_conditions TEXT DEFAULT '',
                    result TEXT DEFAULT 'PENDING', pnl_pct REAL DEFAULT 0,
                    signal_id TEXT, leverage INTEGER DEFAULT 5,
                    margin_usd REAL DEFAULT 0, trade_style TEXT DEFAULT 'SWING',
                    scalp_tf TEXT DEFAULT '', swing_tf TEXT DEFAULT '',
                    mtf_4h TEXT DEFAULT '', mtf_1h TEXT DEFAULT '',
                    mtf_15m TEXT DEFAULT '', score INTEGER DEFAULT 0,
                    tp1_hit INTEGER DEFAULT 0, tp1_hit_at TEXT,
                    sl_moved_to_be INTEGER DEFAULT 0,
                    partial_tp1_pct REAL DEFAULT 60,
                    partial_tp2_pct REAL DEFAULT 40,
                    approaching_sent INTEGER DEFAULT 0,
                    confirmed INTEGER DEFAULT 0,
                    created_at TEXT, closed_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS market_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT UNIQUE, bias TEXT,
                    near_ob INTEGER DEFAULT 0,
                    ob_top REAL DEFAULT 0, ob_bottom REAL DEFAULT 0,
                    ob_strength REAL DEFAULT 0,
                    has_sweep INTEGER DEFAULT 0, has_choch INTEGER DEFAULT 0,
                    rtm_pattern TEXT DEFAULT '', rtm_fresh INTEGER DEFAULT 0,
                    ict_in_ote INTEGER DEFAULT 0, ict_in_killzone INTEGER DEFAULT 0,
                    current_price REAL DEFAULT 0, prev_price REAL DEFAULT 0,
                    price_change_pct REAL DEFAULT 0, updated_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS active_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT UNIQUE, symbol TEXT, source TEXT,
                    strategy_fa TEXT DEFAULT '', direction TEXT,
                    entry REAL, sl REAL, sl_original REAL,
                    tp1 REAL, tp2 REAL, bias TEXT,
                    leverage INTEGER, margin_usd REAL, score INTEGER DEFAULT 0,
                    is_confirmed INTEGER DEFAULT 0, is_cancelled INTEGER DEFAULT 0,
                    approaching_sent INTEGER DEFAULT 0,
                    tp1_hit INTEGER DEFAULT 0, sl_moved_to_be INTEGER DEFAULT 0,
                    partial_tp1_pct REAL DEFAULT 60,
                    partial_tp2_pct REAL DEFAULT 40,
                    created_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS strategy_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT UNIQUE, strategy_fa TEXT DEFAULT '',
                    total_signals INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
                    pending INTEGER DEFAULT 0,
                    total_pnl_pct REAL DEFAULT 0,
                    best_pnl REAL DEFAULT 0, worst_pnl REAL DEFAULT 0,
                    avg_pnl REAL DEFAULT 0, winrate REAL DEFAULT 0,
                    avg_score REAL DEFAULT 0,
                    last_signal_at TEXT, updated_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT, symbol TEXT, direction TEXT,
                    entry REAL, sl REAL, tp1 REAL, tp2 REAL,
                    result TEXT, pnl_pct REAL DEFAULT 0,
                    bars_held INTEGER DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    created_at TEXT
                )
            """)

    print(f"✅ DB initialized ({'PostgreSQL' if USE_POSTGRES else 'SQLite'})")


def _get_tp(sig: dict, key: str) -> float:
    if sig.get(key) is not None:
        return sig[key]
    return (sig.get("trade_params") or {}).get(key, 0)


def save_signal(sig: dict) -> int:
    if not sig.get("signal_id"):
        sig["signal_id"] = generate_signal_id(
            sig["symbol"], sig["source"]
        )

    p = _ph()
    sql = f"""
        INSERT INTO signals
        (symbol, source, strategy_fa, direction, entry, sl, sl_original,
         tp1, tp2, bias, confirmations, description, entry_conditions,
         signal_id, leverage, margin_usd, trade_style,
         scalp_tf, swing_tf, mtf_4h, mtf_1h, mtf_15m,
         score, partial_tp1_pct, partial_tp2_pct, created_at)
        VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},
                {p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """
    params = (
        sig["symbol"], sig["source"],
        sig.get("strategy_fa", sig["source"]),
        sig["direction"], sig["entry"], sig["sl"],
        sig.get("sl_original", sig["sl"]),
        _get_tp(sig, "tp1"), _get_tp(sig, "tp2"),
        sig.get("bias", ""),
        json.dumps(sig.get("confirmations", []), ensure_ascii=False),
        sig.get("description", ""),
        json.dumps(sig.get("entry_conditions", []), ensure_ascii=False),
        sig["signal_id"],
        sig.get("leverage", 5), sig.get("margin_usd", 0),
        sig.get("trade_style", "SWING"),
        sig.get("scalp_tf", ""), sig.get("swing_tf", ""),
        sig.get("mtf_4h", ""), sig.get("mtf_1h", ""),
        sig.get("mtf_15m", ""),
        sig.get("score", 0),
        sig.get("partial_tp1_pct", 60),
        sig.get("partial_tp2_pct", 40),
        _now(),
    )

    with db_cursor() as c:
        if USE_POSTGRES:
            c.execute(sql + " RETURNING id", params)
            return c.fetchone()[0]
        c.execute(sql, params)
        return c.lastrowid


def save_active_signal(sig: dict):
    if not sig.get("signal_id"):
        sig["signal_id"] = generate_signal_id(
            sig["symbol"], sig["source"]
        )

    p = _ph()
    params = (
        sig["signal_id"],
        sig["symbol"], sig["source"],
        sig.get("strategy_fa", sig["source"]),
        sig["direction"],
        sig["entry"], sig["sl"],
        sig.get("sl_original", sig["sl"]),
        _get_tp(sig, "tp1"), _get_tp(sig, "tp2"),
        sig.get("bias", ""),
        sig.get("leverage", 5), sig.get("margin_usd", 0),
        sig.get("score", 0),
        _now(),
    )

    with db_cursor() as c:
        if USE_POSTGRES:
            c.execute(f"""
                INSERT INTO active_signals
                (signal_id, symbol, source, strategy_fa, direction,
                 entry, sl, sl_original, tp1, tp2, bias,
                 leverage, margin_usd, score, created_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},
                        {p},{p},{p},{p},{p})
                ON CONFLICT (signal_id) DO NOTHING
            """, params)
        else:
            c.execute(f"""
                INSERT OR IGNORE INTO active_signals
                (signal_id, symbol, source, strategy_fa, direction,
                 entry, sl, sl_original, tp1, tp2, bias,
                 leverage, margin_usd, score, created_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},
                        {p},{p},{p},{p},{p})
            """, params)


def update_market_memory(symbol: str, data: dict):
    p = _ph()
    current_price = data.get("current_price", 0)

    with db_cursor() as c:
        c.execute(
            f"SELECT current_price FROM market_memory WHERE symbol={p}",
            (symbol,),
        )
        row = c.fetchone()
        prev_price = row[0] if row else 0

        price_change_pct = 0
        if prev_price and prev_price > 0:
            price_change_pct = (
                (current_price - prev_price) / prev_price
            ) * 100

        if USE_POSTGRES:
            vals = (
                symbol, data.get("bias", ""),
                bool(data.get("near_ob")),
                data.get("ob_top", 0), data.get("ob_bottom", 0),
                data.get("ob_strength", 0),
                bool(data.get("has_sweep")),
                bool(data.get("has_choch")),
                data.get("rtm_pattern", ""),
                bool(data.get("rtm_fresh")),
                bool(data.get("ict_in_ote")),
                bool(data.get("ict_in_killzone")),
                current_price, prev_price, price_change_pct, _now(),
            )
            c.execute(f"""
                INSERT INTO market_memory
                (symbol, bias, near_ob, ob_top, ob_bottom, ob_strength,
                 has_sweep, has_choch, rtm_pattern, rtm_fresh,
                 ict_in_ote, ict_in_killzone, current_price,
                 prev_price, price_change_pct, updated_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},
                        {p},{p},{p},{p},{p},{p},{p},{p})
                ON CONFLICT(symbol) DO UPDATE SET
                    bias=EXCLUDED.bias,
                    near_ob=EXCLUDED.near_ob,
                    ob_top=EXCLUDED.ob_top,
                    ob_bottom=EXCLUDED.ob_bottom,
                    ob_strength=EXCLUDED.ob_strength,
                    has_sweep=EXCLUDED.has_sweep,
                    has_choch=EXCLUDED.has_choch,
                    rtm_pattern=EXCLUDED.rtm_pattern,
                    rtm_fresh=EXCLUDED.rtm_fresh,
                    ict_in_ote=EXCLUDED.ict_in_ote,
                    ict_in_killzone=EXCLUDED.ict_in_killzone,
                    current_price=EXCLUDED.current_price,
                    prev_price=EXCLUDED.prev_price,
                    price_change_pct=EXCLUDED.price_change_pct,
                    updated_at=EXCLUDED.updated_at
            """, vals)
        else:
            vals = (
                symbol, data.get("bias", ""),
                1 if data.get("near_ob") else 0,
                data.get("ob_top", 0), data.get("ob_bottom", 0),
                data.get("ob_strength", 0),
                1 if data.get("has_sweep") else 0,
                1 if data.get("has_choch") else 0,
                data.get("rtm_pattern", ""),
                1 if data.get("rtm_fresh") else 0,
                1 if data.get("ict_in_ote") else 0,
                1 if data.get("ict_in_killzone") else 0,
                current_price, prev_price, price_change_pct, _now(),
            )
            c.execute(f"""
                INSERT INTO market_memory
                (symbol, bias, near_ob, ob_top, ob_bottom, ob_strength,
                 has_sweep, has_choch, rtm_pattern, rtm_fresh,
                 ict_in_ote, ict_in_killzone, current_price,
                 prev_price, price_change_pct, updated_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},
                        {p},{p},{p},{p},{p},{p},{p},{p})
                ON CONFLICT(symbol) DO UPDATE SET
                    bias=excluded.bias,
                    near_ob=excluded.near_ob,
                    ob_top=excluded.ob_top,
                    ob_bottom=excluded.ob_bottom,
                    ob_strength=excluded.ob_strength,
                    has_sweep=excluded.has_sweep,
                    has_choch=excluded.has_choch,
                    rtm_pattern=excluded.rtm_pattern,
                    rtm_fresh=excluded.rtm_fresh,
                    ict_in_ote=excluded.ict_in_ote,
                    ict_in_killzone=excluded.ict_in_killzone,
                    current_price=excluded.current_price,
                    prev_price=excluded.prev_price,
                    price_change_pct=excluded.price_change_pct,
                    updated_at=excluded.updated_at
            """, vals)


def get_market_memory(symbol: str) -> dict:
    p = _ph()
    with db_cursor() as c:
        c.execute(f"""
            SELECT bias, near_ob, ob_top, ob_bottom, has_sweep,
                   has_choch, rtm_pattern, ict_in_ote, ict_in_killzone,
                   current_price, prev_price, price_change_pct, updated_at
            FROM market_memory WHERE symbol={p}
        """, (symbol,))
        row = c.fetchone()

    if not row:
        return {}

    return {
        "bias": row[0], "near_ob": bool(row[1]),
        "ob_top": row[2], "ob_bottom": row[3],
        "has_sweep": bool(row[4]), "has_choch": bool(row[5]),
        "rtm_pattern": row[6], "ict_in_ote": bool(row[7]),
        "ict_in_killzone": bool(row[8]),
        "current_price": row[9], "prev_price": row[10],
        "price_change_pct": row[11], "updated_at": row[12],
    }


def was_signal_sent_recently(symbol: str, source: str,
                             direction: str, hours: int = 4) -> bool:
    p = _ph()
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with db_cursor() as c:
        c.execute(f"""
            SELECT created_at FROM signals
            WHERE symbol={p} AND source={p} AND direction={p}
              AND created_at > {p}
            ORDER BY created_at DESC LIMIT 1
        """, (symbol, source, direction, cutoff))
        row = c.fetchone()
    return row is not None


def get_active_signals() -> list:
    p = _ph()
    cutoff = (datetime.utcnow() - timedelta(hours=48)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    if USE_POSTGRES:
        cond = "is_confirmed=FALSE AND is_cancelled=FALSE"
    else:
        cond = "is_confirmed=0 AND is_cancelled=0"

    with db_cursor() as c:
        c.execute(f"""
            SELECT signal_id, symbol, source, strategy_fa, direction,
                   entry, sl, sl_original, tp1, tp2, bias, leverage,
                   margin_usd, score, approaching_sent, tp1_hit,
                   sl_moved_to_be, partial_tp1_pct, partial_tp2_pct
            FROM active_signals
            WHERE {cond} AND created_at > {p}
        """, (cutoff,))
        rows = c.fetchall()

    return [
        {
            "signal_id": r[0], "symbol": r[1],
            "source": r[2], "strategy_fa": r[3],
            "direction": r[4], "entry": r[5],
            "sl": r[6], "sl_original": r[7],
            "tp1": r[8], "tp2": r[9],
            "bias": r[10], "leverage": r[11],
            "margin_usd": r[12], "score": r[13],
            "approaching_sent": bool(r[14]),
            "tp1_hit": bool(r[15]),
            "sl_moved_to_be": bool(r[16]),
            "partial_tp1_pct": r[17] or 60,
            "partial_tp2_pct": r[18] or 40,
        }
        for r in rows
    ]


def cancel_active_signal(signal_id: str):
    if not signal_id:
        return
    p = _ph()
    val = "TRUE" if USE_POSTGRES else "1"
    with db_cursor() as c:
        c.execute(
            f"UPDATE active_signals SET is_cancelled={val} "
            f"WHERE signal_id={p}",
            (signal_id,),
        )


def confirm_active_signal(signal_id: str):
    if not signal_id:
        return
    p = _ph()
    val = "TRUE" if USE_POSTGRES else "1"
    with db_cursor() as c:
        c.execute(
            f"UPDATE active_signals SET is_confirmed={val} "
            f"WHERE signal_id={p}",
            (signal_id,),
        )
        # همچنین در signals table هم آپدیت کن
        c.execute(
            f"UPDATE signals SET confirmed={val} "
            f"WHERE signal_id={p}",
            (signal_id,),
        )


def mark_approaching_sent(signal_id: str):
    if not signal_id:
        return
    p = _ph()
    val = "TRUE" if USE_POSTGRES else "1"
    with db_cursor() as c:
        c.execute(
            f"UPDATE active_signals SET approaching_sent={val} "
            f"WHERE signal_id={p}",
            (signal_id,),
        )
        c.execute(
            f"UPDATE signals SET approaching_sent={val} "
            f"WHERE signal_id={p}",
            (signal_id,),
        )


def mark_tp1_hit(signal_id: str):
    if not signal_id:
        return
    p = _ph()
    val = "TRUE" if USE_POSTGRES else "1"
    with db_cursor() as c:
        c.execute(
            f"UPDATE active_signals SET tp1_hit={val} "
            f"WHERE signal_id={p}",
            (signal_id,),
        )
        c.execute(
            f"UPDATE signals SET tp1_hit={val}, tp1_hit_at={p} "
            f"WHERE signal_id={p}",
            (_now(), signal_id),
        )


def mark_sl_moved_to_be(signal_id: str):
    if not signal_id:
        return
    p = _ph()
    val = "TRUE" if USE_POSTGRES else "1"
    with db_cursor() as c:
        c.execute(
            f"UPDATE active_signals SET sl_moved_to_be={val} "
            f"WHERE signal_id={p}",
            (signal_id,),
        )
        c.execute(
            f"UPDATE signals SET sl_moved_to_be={val}, sl=entry "
            f"WHERE signal_id={p}",
            (signal_id,),
        )


def get_performance_stats() -> dict:
    with db_cursor() as c:
        c.execute("""
            SELECT source, COUNT(*) as total,
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
                   AVG(pnl_pct) as avg_pnl
            FROM signals WHERE result != 'PENDING'
            GROUP BY source
        """)
        rows = c.fetchall()

    stats = {}
    for source, total, wins, losses, avg_pnl in rows:
        wins = wins or 0
        total = total or 0
        stats[source] = {
            "total": total, "wins": wins,
            "losses": losses or 0,
            "winrate": (wins / total * 100) if total > 0 else 0,
            "avg_pnl": avg_pnl or 0,
        }
    return stats


def get_strategy_performance() -> list:
    """آمار عملکرد هر استراتژی"""
    with db_cursor() as c:
        c.execute("""
            SELECT source, strategy_fa,
                   COUNT(*) as total,
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
                   SUM(CASE WHEN result='PENDING' THEN 1 ELSE 0 END) as pending,
                   AVG(pnl_pct) as avg_pnl,
                   MAX(pnl_pct) as best_pnl,
                   MIN(pnl_pct) as worst_pnl,
                   AVG(score) as avg_score,
                   MAX(created_at) as last_signal
            FROM signals
            GROUP BY source, strategy_fa
            ORDER BY total DESC
        """)
        rows = c.fetchall()

    result = []
    for row in rows:
        source, strategy_fa, total, wins, losses, pending, avg_pnl, best_pnl, worst_pnl, avg_score, last_signal = row
        wins = wins or 0
        losses = losses or 0
        closed = wins + losses
        result.append({
            "strategy": source,
            "strategy_fa": strategy_fa or source,
            "total": total or 0,
            "wins": wins,
            "losses": losses,
            "pending": pending or 0,
            "winrate": (wins / closed * 100) if closed > 0 else 0,
            "avg_pnl": round(avg_pnl or 0, 2),
            "best_pnl": round(best_pnl or 0, 2),
            "worst_pnl": round(worst_pnl or 0, 2),
            "avg_score": round(avg_score or 0, 1),
            "last_signal": last_signal,
        })

    return result


def update_strategy_stats(sig: dict, result: str, pnl: float):
    """آپدیت آمار استراتژی بعد از بسته شدن سیگنال"""
    p = _ph()
    strategy = sig.get("source", "")
    strategy_fa = sig.get("strategy_fa", strategy)

    with db_cursor() as c:
        # اول چک کن آیا ردیف وجود داره
        c.execute(
            f"SELECT id FROM strategy_stats WHERE strategy={p}",
            (strategy,)
        )
        exists = c.fetchone()

        if exists:
            c.execute(f"""
                UPDATE strategy_stats SET
                    total_signals = total_signals + 1,
                    wins = wins + {1 if result == 'WIN' else 0},
                    losses = losses + {1 if result == 'LOSS' else 0},
                    total_pnl_pct = total_pnl_pct + {p},
                    best_pnl = GREATEST(best_pnl, {p}),
                    worst_pnl = LEAST(worst_pnl, {p}),
                    last_signal_at = {p},
                    updated_at = {p}
                WHERE strategy={p}
            """, (pnl, pnl, _now(), _now(), strategy))
        else:
            c.execute(f"""
                INSERT INTO strategy_stats
                (strategy, strategy_fa, total_signals, wins, losses,
                 total_pnl_pct, best_pnl, worst_pnl, last_signal_at, updated_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
            """, (
                strategy, strategy_fa, 1,
                1 if result == 'WIN' else 0,
                1 if result == 'LOSS' else 0,
                pnl, pnl, pnl, _now(), _now()
            ))


def save_backtest_result(strategy: str, symbol: str, direction: str,
                         entry: float, sl: float, tp1: float, tp2: float,
                         result: str, pnl: float, bars: int, dd: float):
    p = _ph()
    with db_cursor() as c:
        c.execute(f"""
            INSERT INTO backtest_results
            (strategy, symbol, direction, entry, sl, tp1, tp2,
             result, pnl_pct, bars_held, max_drawdown, created_at)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
        """, (strategy, symbol, direction, entry, sl, tp1, tp2,
              result, pnl, bars, dd, _now()))


def get_backtest_stats() -> list:
    with db_cursor() as c:
        c.execute("""
            SELECT strategy,
                   COUNT(*) as total,
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
                   AVG(pnl_pct) as avg_pnl,
                   MAX(pnl_pct) as best,
                   MIN(pnl_pct) as worst,
                   AVG(bars_held) as avg_bars,
                   AVG(max_drawdown) as avg_dd
            FROM backtest_results
            GROUP BY strategy
            ORDER BY avg_pnl DESC
        """)
        rows = c.fetchall()

    return [
        {
            "strategy": r[0], "total": r[1],
            "wins": r[2] or 0, "losses": r[3] or 0,
            "winrate": ((r[2] or 0) / (r[1] or 1)) * 100,
            "avg_pnl": round(r[4] or 0, 2),
            "best": round(r[5] or 0, 2),
            "worst": round(r[6] or 0, 2),
            "avg_bars": round(r[7] or 0, 1),
            "avg_dd": round(r[8] or 0, 2),
        }
        for r in rows
    ]


def get_recent_signals(limit: int = 50) -> list:
    """سیگنال‌های اخیر برای داشبورد"""
    with db_cursor() as c:
        c.execute(f"""
            SELECT signal_id, symbol, source, strategy_fa, direction,
                   entry, sl, tp1, tp2, result, pnl_pct, score,
                   leverage, margin_usd, trade_style, created_at, closed_at
            FROM signals
            ORDER BY created_at DESC
            LIMIT {limit}
        """)
        rows = c.fetchall()

    return [
        {
            "signal_id": r[0], "symbol": r[1], "source": r[2],
            "strategy_fa": r[3], "direction": r[4],
            "entry": r[5], "sl": r[6], "tp1": r[7], "tp2": r[8],
            "result": r[9], "pnl_pct": r[10], "score": r[11],
            "leverage": r[12], "margin_usd": r[13],
            "trade_style": r[14],
            "created_at": r[15], "closed_at": r[16],
        }
        for r in rows
    ]


def get_dashboard_summary() -> dict:
    """خلاصه آمار برای داشبورد"""
    with db_cursor() as c:
        c.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN result='PENDING' THEN 1 ELSE 0 END) as pending,
                AVG(CASE WHEN result != 'PENDING' THEN pnl_pct END) as avg_pnl,
                MAX(pnl_pct) as best_pnl,
                MIN(pnl_pct) as worst_pnl,
                AVG(score) as avg_score
            FROM signals
        """)
        row = c.fetchone()

    total = row[0] or 0
    wins = row[1] or 0
    losses = row[2] or 0
    pending = row[3] or 0
    closed = wins + losses

    return {
        "total_signals": total,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "winrate": round((wins / closed * 100) if closed > 0 else 0, 1),
        "avg_pnl": round(row[4] or 0, 2),
        "best_pnl": round(row[5] or 0, 2),
        "worst_pnl": round(row[6] or 0, 2),
        "avg_score": round(row[7] or 0, 1),
    }


def update_signal_result(signal_id: str, result: str, pnl_pct: float):
    if not signal_id:
        return
    p = _ph()
    with db_cursor() as c:
        c.execute(f"""
            UPDATE signals
            SET result={p}, pnl_pct={p}, closed_at={p}
            WHERE signal_id={p}
        """, (result, pnl_pct, _now(), signal_id))


def _parse_created_at(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).replace("T", " ").split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def check_open_signals():
    from data.fetcher import get_klines

    with db_cursor() as c:
        c.execute("""
            SELECT signal_id, symbol, direction, entry, sl, tp1, tp2,
                   leverage, margin_usd, created_at,
                   tp1_hit, sl_moved_to_be, partial_tp1_pct, partial_tp2_pct
            FROM signals WHERE result='PENDING'
        """)
        open_signals = c.fetchall()

    results = []
    for sig in open_signals:
        (sig_id, symbol, direction, entry, sl, tp1, tp2,
         lev, margin, created_at, tp1_hit, sl_moved_be,
         p_tp1, p_tp2) = sig
        if not sig_id:
            continue
        try:
            df = get_klines(symbol, "15m", 80, closed_only=False)
            if df is None or df.empty:
                continue

            created = _parse_created_at(created_at)
            if created is not None:
                ts = pd_to_naive(df["timestamp"])
                after = df[ts >= created]
                if after.empty:
                    after = df.tail(1)
            else:
                after = df.tail(8)

            hit_sl = False
            hit_tp1 = False
            hit_tp2 = False

            if direction == "LONG":
                hit_sl = bool((after["low"] <= sl).any())
                hit_tp1 = bool((after["high"] >= tp1).any())
                hit_tp2 = bool((after["high"] >= tp2).any())
            else:
                hit_sl = bool((after["high"] >= sl).any())
                hit_tp1 = bool((after["low"] <= tp1).any())
                hit_tp2 = bool((after["low"] <= tp2).any())

            # اگه TP1 قبلاً خورده بود ولی SL جدید (breakeven) خورده
            if tp1_hit and hit_sl:
                # SL breakeven خورده → بستن با سود partial
                p_tp1 = p_tp1 or 60
                pnl_tp1 = p_tp1 / 100 * (
                    ((tp1 - entry) / entry * 100) if direction == "LONG"
                    else ((entry - tp1) / entry * 100)
                )
                # remaining 40% با BE = 0
                total_pnl = pnl_tp1  # فقط سود 60%
                update_signal_result(sig_id, "WIN", total_pnl)
                update_strategy_stats(
                    {"source": "N/A", "strategy_fa": "N/A"},
                    "WIN", total_pnl
                )
                results.append({
                    "signal_id": sig_id, "symbol": symbol,
                    "result": "WIN", "pnl": total_pnl,
                    "leverage": lev or 5, "margin_usd": margin or 0,
                })
            elif hit_sl:
                # SL اصلی خورده
                if direction == "LONG":
                    pnl = ((sl - entry) / entry) * 100
                else:
                    pnl = ((entry - sl) / entry) * 100
                update_signal_result(sig_id, "LOSS", pnl)
                update_strategy_stats(
                    {"source": "N/A", "strategy_fa": "N/A"},
                    "LOSS", pnl
                )
                results.append({
                    "signal_id": sig_id, "symbol": symbol,
                    "result": "LOSS", "pnl": pnl,
                    "leverage": lev or 5, "margin_usd": margin or 0,
                })
            elif hit_tp2:
                # TP2 خورده → بستن کامل
                p_tp1 = p_tp1 or 60
                p_tp2 = p_tp2 or 40
                if direction == "LONG":
                    pnl_1 = ((tp1 - entry) / entry) * 100 * (p_tp1 / 100)
                    pnl_2 = ((tp2 - entry) / entry) * 100 * (p_tp2 / 100)
                else:
                    pnl_1 = ((entry - tp1) / entry) * 100 * (p_tp1 / 100)
                    pnl_2 = ((entry - tp2) / entry) * 100 * (p_tp2 / 100)
                total_pnl = pnl_1 + pnl_2
                update_signal_result(sig_id, "WIN", total_pnl)
                update_strategy_stats(
                    {"source": "N/A", "strategy_fa": "N/A"},
                    "WIN", total_pnl
                )
                results.append({
                    "signal_id": sig_id, "symbol": symbol,
                    "result": "WIN", "pnl": total_pnl,
                    "leverage": lev or 5, "margin_usd": margin or 0,
                })
            elif hit_tp1 and not tp1_hit:
                # TP1 برای اولین بار خورده → partial close + move SL to BE
                mark_tp1_hit(sig_id)
                mark_sl_moved_to_be(sig_id)
                # نتیجه هنوز بسته نشده - ادامه میدیم

        except Exception as e:
            print(f"check_open_signals error {symbol}: {e}")
            continue

    return results


def pd_to_naive(series):
    import pandas as pd
    ts = pd.to_datetime(series)
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    return ts
