# database/db.py - Supabase PostgreSQL + SQLite fallback
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
    """فرمت یکسان برای هر دو DB - بدون T"""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _ph() -> str:
    """placeholder درست برای هر DB"""
    return "%s" if USE_POSTGRES else "?"


def generate_signal_id(symbol: str, source: str) -> str:
    ts = datetime.utcnow().strftime("%m%d%H%M")
    rand = uuid.uuid4().hex[:4].upper()
    clean = symbol.replace("USDT", "").replace(".P", "")
    return f"{clean}-{source}-{ts}-{rand}"


def get_conn():
    if USE_POSTGRES:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url, sslmode="require")
    return sqlite3.connect(DB_PATH)


@contextmanager
def db_cursor():
    """Context manager - جلوی connection leak رو میگیره"""
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
                    direction TEXT,
                    entry REAL,
                    sl REAL,
                    tp1 REAL,
                    tp2 REAL,
                    bias TEXT,
                    confirmations TEXT,
                    result TEXT DEFAULT 'PENDING',
                    pnl_pct REAL DEFAULT 0,
                    signal_id TEXT,
                    leverage INTEGER DEFAULT 5,
                    margin_usd REAL DEFAULT 0,
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
                    direction TEXT,
                    entry REAL,
                    sl REAL,
                    tp1 REAL,
                    tp2 REAL,
                    bias TEXT,
                    leverage INTEGER,
                    margin_usd REAL,
                    is_confirmed BOOLEAN DEFAULT FALSE,
                    is_cancelled BOOLEAN DEFAULT FALSE,
                    created_at TEXT
                )
            """)
        else:
            c.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT, source TEXT, direction TEXT,
                    entry REAL, sl REAL, tp1 REAL, tp2 REAL,
                    bias TEXT, confirmations TEXT,
                    result TEXT DEFAULT 'PENDING',
                    pnl_pct REAL DEFAULT 0,
                    signal_id TEXT, leverage INTEGER DEFAULT 5,
                    margin_usd REAL DEFAULT 0,
                    created_at TEXT, closed_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS market_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT UNIQUE, bias TEXT,
                    near_ob INTEGER DEFAULT 0,
                    ob_top REAL DEFAULT 0,
                    ob_bottom REAL DEFAULT 0,
                    ob_strength REAL DEFAULT 0,
                    has_sweep INTEGER DEFAULT 0,
                    has_choch INTEGER DEFAULT 0,
                    rtm_pattern TEXT DEFAULT '',
                    rtm_fresh INTEGER DEFAULT 0,
                    ict_in_ote INTEGER DEFAULT 0,
                    ict_in_killzone INTEGER DEFAULT 0,
                    current_price REAL DEFAULT 0,
                    prev_price REAL DEFAULT 0,
                    price_change_pct REAL DEFAULT 0,
                    updated_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS active_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT UNIQUE, symbol TEXT,
                    source TEXT, direction TEXT,
                    entry REAL, sl REAL, tp1 REAL, tp2 REAL,
                    bias TEXT, leverage INTEGER, margin_usd REAL,
                    is_confirmed INTEGER DEFAULT 0,
                    is_cancelled INTEGER DEFAULT 0,
                    created_at TEXT
                )
            """)

    print(f"✅ DB initialized ({'PostgreSQL' if USE_POSTGRES else 'SQLite'})")


def _get_tp(sig: dict, key: str) -> float:
    """tp1/tp2 رو از هر جایی که باشه میگیره"""
    if sig.get(key) is not None:
        return sig[key]
    return (sig.get("trade_params") or {}).get(key, 0)


def save_signal(sig: dict) -> int:
    # signal_id اگه نبود بساز
    if not sig.get("signal_id"):
        sig["signal_id"] = generate_signal_id(
            sig["symbol"], sig["source"]
        )

    p = _ph()
    sql = f"""
        INSERT INTO signals
        (symbol, source, direction, entry, sl, tp1, tp2,
         bias, confirmations, signal_id, leverage, margin_usd, created_at)
        VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """
    params = (
        sig["symbol"], sig["source"], sig["direction"],
        sig["entry"], sig["sl"],
        _get_tp(sig, "tp1"), _get_tp(sig, "tp2"),
        sig.get("bias", ""),
        json.dumps(sig.get("confirmations", [])),
        sig["signal_id"],
        sig.get("leverage", 5),
        sig.get("margin_usd", 0),
        _now(),
    )

    with db_cursor() as c:
        if USE_POSTGRES:
            c.execute(sql + " RETURNING id", params)
            return c.fetchone()[0]
        c.execute(sql, params)
        return c.lastrowid


def save_active_signal(sig: dict):
    """
    ذخیره سیگنال فعال
    ✅ بدون import از telegram_bot
    """
    if not sig.get("signal_id"):
        sig["signal_id"] = generate_signal_id(
            sig["symbol"], sig["source"]
        )

    p = _ph()
    params = (
        sig["signal_id"],
        sig["symbol"], sig["source"], sig["direction"],
        sig["entry"], sig["sl"],
        _get_tp(sig, "tp1"), _get_tp(sig, "tp2"),
        sig.get("bias", ""),
        sig.get("leverage", 5),
        sig.get("margin_usd", 0),
        _now(),
    )

    with db_cursor() as c:
        if USE_POSTGRES:
            c.execute(f"""
                INSERT INTO active_signals
                (signal_id, symbol, source, direction, entry, sl,
                 tp1, tp2, bias, leverage, margin_usd, created_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                ON CONFLICT (signal_id) DO NOTHING
            """, params)
        else:
            c.execute(f"""
                INSERT OR IGNORE INTO active_signals
                (signal_id, symbol, source, direction, entry, sl,
                 tp1, tp2, bias, leverage, margin_usd, created_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
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
        "bias": row[0],
        "near_ob": bool(row[1]),
        "ob_top": row[2],
        "ob_bottom": row[3],
        "has_sweep": bool(row[4]),
        "has_choch": bool(row[5]),
        "rtm_pattern": row[6],
        "ict_in_ote": bool(row[7]),
        "ict_in_killzone": bool(row[8]),
        "current_price": row[9],
        "prev_price": row[10],
        "price_change_pct": row[11],
        "updated_at": row[12],
    }


def was_signal_sent_recently(symbol: str, source: str,
                             direction: str, hours: int = 4) -> bool:
    """
    ✅ cutoff تو پایتون حساب میشه - هم SQLite هم Postgres درست کار میکنه
    """
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
    cutoff = (datetime.utcnow() - timedelta(hours=24)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    if USE_POSTGRES:
        cond = "is_confirmed=FALSE AND is_cancelled=FALSE"
    else:
        cond = "is_confirmed=0 AND is_cancelled=0"

    with db_cursor() as c:
        c.execute(f"""
            SELECT signal_id, symbol, source, direction,
                   entry, sl, tp1, tp2, bias, leverage, margin_usd
            FROM active_signals
            WHERE {cond} AND created_at > {p}
        """, (cutoff,))
        rows = c.fetchall()

    return [
        {
            "signal_id": r[0], "symbol": r[1],
            "source": r[2], "direction": r[3],
            "entry": r[4], "sl": r[5],
            "tp1": r[6], "tp2": r[7],
            "bias": r[8], "leverage": r[9],
            "margin_usd": r[10],
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
            "total": total,
            "wins": wins,
            "losses": losses or 0,
            "winrate": (wins / total * 100) if total > 0 else 0,
            "avg_pnl": avg_pnl or 0,
        }
    return stats


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


def check_open_signals():
    from data.fetcher import get_klines

    with db_cursor() as c:
        c.execute("""
            SELECT signal_id, symbol, direction, entry, sl, tp1, tp2,
                   leverage, margin_usd
            FROM signals WHERE result='PENDING'
        """)
        open_signals = c.fetchall()

    results = []
    for sig in open_signals:
        sig_id, symbol, direction, entry, sl, tp1, tp2, lev, margin = sig
        if not sig_id:
            continue
        try:
            df = get_klines(symbol, "15m", 5)
            if df is None:
                continue

            curr_h = df["high"].iloc[-1]
            curr_l = df["low"].iloc[-1]

            if direction == "LONG":
                if curr_l <= sl:
                    pnl = ((sl - entry) / entry) * 100
                    update_signal_result(sig_id, "LOSS", pnl)
                    results.append({
                        "signal_id": sig_id, "symbol": symbol,
                        "result": "LOSS", "pnl": pnl,
                        "leverage": lev, "margin_usd": margin,
                    })
                elif curr_h >= tp1:
                    pnl = ((tp1 - entry) / entry) * 100
                    update_signal_result(sig_id, "WIN", pnl)
                    results.append({
                        "signal_id": sig_id, "symbol": symbol,
                        "result": "WIN", "pnl": pnl,
                        "leverage": lev, "margin_usd": margin,
                    })
            else:
                if curr_h >= sl:
                    pnl = ((entry - sl) / entry) * 100
                    update_signal_result(sig_id, "LOSS", pnl)
                    results.append({
                        "signal_id": sig_id, "symbol": symbol,
                        "result": "LOSS", "pnl": pnl,
                        "leverage": lev, "margin_usd": margin,
                    })
                elif curr_l <= tp1:
                    pnl = ((entry - tp1) / entry) * 100
                    update_signal_result(sig_id, "WIN", pnl)
                    results.append({
                        "signal_id": sig_id, "symbol": symbol,
                        "result": "WIN", "pnl": pnl,
                        "leverage": lev, "margin_usd": margin,
                    })
        except Exception as e:
            print(f"check_open_signals error {symbol}: {e}")
            continue

    return results
