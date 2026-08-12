# database/db.py - Supabase PostgreSQL
import os
import json
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# اگه Supabase نبود، SQLite رو به عنوان backup استفاده میکنه
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor
else:
    import sqlite3
    DB_PATH = "/tmp/signals.db"


def get_conn():
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        # جدول سیگنال‌ها
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

        # جدول حافظه بازار
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

        # جدول سیگنال‌های فعال (برای چک باطل شدن)
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
                ob_top REAL DEFAULT 0, ob_bottom REAL DEFAULT 0,
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

    conn.commit()
    conn.close()
    print(f"✅ DB initialized ({'PostgreSQL' if USE_POSTGRES else 'SQLite'})")


def save_signal(sig: dict) -> int:
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            INSERT INTO signals
            (symbol, source, direction, entry, sl, tp1, tp2,
             bias, confirmations, signal_id, leverage, margin_usd, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            sig["symbol"], sig["source"], sig["direction"],
            sig["entry"], sig["sl"],
            sig["trade_params"]["tp1"], sig["trade_params"]["tp2"],
            sig.get("bias", ""),
            json.dumps(sig.get("confirmations", [])),
            sig.get("signal_id", ""),
            sig.get("leverage", 5),
            sig.get("margin_usd", 0),
            datetime.utcnow().isoformat()
        ))
        signal_db_id = c.fetchone()[0]
    else:
        c.execute("""
            INSERT INTO signals
            (symbol, source, direction, entry, sl, tp1, tp2,
             bias, confirmations, signal_id, leverage, margin_usd, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            sig["symbol"], sig["source"], sig["direction"],
            sig["entry"], sig["sl"],
            sig["trade_params"]["tp1"], sig["trade_params"]["tp2"],
            sig.get("bias", ""),
            json.dumps(sig.get("confirmations", [])),
            sig.get("signal_id", ""),
            sig.get("leverage", 5),
            sig.get("margin_usd", 0),
            datetime.utcnow().isoformat()
        ))
        signal_db_id = c.lastrowid

    conn.commit()
    conn.close()
    return signal_db_id


def save_active_signal(sig: dict):
    """ذخیره سیگنال فعال برای چک باطل شدن"""
    conn = get_conn()
    c = conn.cursor()

    from bot.telegram_bot import calculate_score, calculate_money_management
    score = calculate_score(sig)["score"]
    mm = calculate_money_management(sig, score)

    if USE_POSTGRES:
        c.execute("""
            INSERT INTO active_signals
            (signal_id, symbol, source, direction, entry, sl, tp1, tp2,
             bias, leverage, margin_usd, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (signal_id) DO NOTHING
        """, (
            sig.get("signal_id", ""),
            sig["symbol"], sig["source"], sig["direction"],
            sig["entry"], sig["sl"],
            sig["trade_params"]["tp1"], sig["trade_params"]["tp2"],
            sig.get("bias", ""),
            mm["leverage"], mm["margin_usd"],
            datetime.utcnow().isoformat()
        ))
    else:
        c.execute("""
            INSERT OR IGNORE INTO active_signals
            (signal_id, symbol, source, direction, entry, sl, tp1, tp2,
             bias, leverage, margin_usd, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            sig.get("signal_id", ""),
            sig["symbol"], sig["source"], sig["direction"],
            sig["entry"], sig["sl"],
            sig["trade_params"]["tp1"], sig["trade_params"]["tp2"],
            sig.get("bias", ""),
            mm["leverage"], mm["margin_usd"],
            datetime.utcnow().isoformat()
        ))

    conn.commit()
    conn.close()


def update_market_memory(symbol: str, data: dict):
    conn = get_conn()
    c = conn.cursor()

    # قیمت قبلی رو بگیر
    if USE_POSTGRES:
        c.execute(
            "SELECT current_price FROM market_memory WHERE symbol=%s",
            (symbol,)
        )
    else:
        c.execute(
            "SELECT current_price FROM market_memory WHERE symbol=?",
            (symbol,)
        )

    row = c.fetchone()
    prev_price = row[0] if row else 0
    current_price = data.get("current_price", 0)

    price_change_pct = 0
    if prev_price and prev_price > 0:
        price_change_pct = ((current_price - prev_price) / prev_price) * 100

    if USE_POSTGRES:
        c.execute("""
            INSERT INTO market_memory
            (symbol, bias, near_ob, ob_top, ob_bottom, ob_strength,
             has_sweep, has_choch, rtm_pattern, rtm_fresh,
             ict_in_ote, ict_in_killzone, current_price,
             prev_price, price_change_pct, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(symbol) DO UPDATE SET
                bias=EXCLUDED.bias, near_ob=EXCLUDED.near_ob,
                ob_top=EXCLUDED.ob_top, ob_bottom=EXCLUDED.ob_bottom,
                ob_strength=EXCLUDED.ob_strength,
                has_sweep=EXCLUDED.has_sweep, has_choch=EXCLUDED.has_choch,
                rtm_pattern=EXCLUDED.rtm_pattern,
                rtm_fresh=EXCLUDED.rtm_fresh,
                ict_in_ote=EXCLUDED.ict_in_ote,
                ict_in_killzone=EXCLUDED.ict_in_killzone,
                current_price=EXCLUDED.current_price,
                prev_price=EXCLUDED.prev_price,
                price_change_pct=EXCLUDED.price_change_pct,
                updated_at=EXCLUDED.updated_at
        """, (
            symbol, data.get("bias", ""),
            data.get("near_ob", False),
            data.get("ob_top", 0), data.get("ob_bottom", 0),
            data.get("ob_strength", 0),
            data.get("has_sweep", False), data.get("has_choch", False),
            data.get("rtm_pattern", ""), data.get("rtm_fresh", False),
            data.get("ict_in_ote", False), data.get("ict_in_killzone", False),
            current_price, prev_price, price_change_pct,
            datetime.utcnow().isoformat()
        ))
    else:
        c.execute("""
            INSERT INTO market_memory
            (symbol, bias, near_ob, ob_top, ob_bottom, ob_strength,
             has_sweep, has_choch, rtm_pattern, rtm_fresh,
             ict_in_ote, ict_in_killzone, current_price,
             prev_price, price_change_pct, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                bias=excluded.bias, near_ob=excluded.near_ob,
                ob_top=excluded.ob_top, ob_bottom=excluded.ob_bottom,
                ob_strength=excluded.ob_strength,
                has_sweep=excluded.has_sweep, has_choch=excluded.has_choch,
                rtm_pattern=excluded.rtm_pattern,
                rtm_fresh=excluded.rtm_fresh,
                ict_in_ote=excluded.ict_in_ote,
                ict_in_killzone=excluded.ict_in_killzone,
                current_price=excluded.current_price,
                prev_price=excluded.prev_price,
                price_change_pct=excluded.price_change_pct,
                updated_at=excluded.updated_at
        """, (
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
            current_price, prev_price, price_change_pct,
            datetime.utcnow().isoformat()
        ))

    conn.commit()
    conn.close()


def get_market_memory(symbol: str) -> dict:
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            SELECT bias, near_ob, ob_top, ob_bottom, has_sweep,
                   has_choch, rtm_pattern, ict_in_ote, ict_in_killzone,
                   current_price, prev_price, price_change_pct, updated_at
            FROM market_memory WHERE symbol=%s
        """, (symbol,))
    else:
        c.execute("""
            SELECT bias, near_ob, ob_top, ob_bottom, has_sweep,
                   has_choch, rtm_pattern, ict_in_ote, ict_in_killzone,
                   current_price, prev_price, price_change_pct, updated_at
            FROM market_memory WHERE symbol=?
        """, (symbol,))

    row = c.fetchone()
    conn.close()

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
        "updated_at": row[12]
    }


def was_signal_sent_recently(symbol: str, source: str,
                              direction: str, hours: int = 4) -> bool:
    conn = get_conn()
    c = conn.cursor()

    cutoff = f'-{hours} hours'
    if USE_POSTGRES:
        c.execute("""
            SELECT created_at FROM signals
            WHERE symbol=%s AND source=%s AND direction=%s
            AND created_at > (NOW() - INTERVAL '%s hours')
            ORDER BY created_at DESC LIMIT 1
        """, (symbol, source, direction, hours))
    else:
        c.execute("""
            SELECT created_at FROM signals
            WHERE symbol=? AND source=? AND direction=?
            AND created_at > datetime('now', ?)
            ORDER BY created_at DESC LIMIT 1
        """, (symbol, source, direction, cutoff))

    row = c.fetchone()
    conn.close()
    return row is not None


def get_active_signals() -> list:
    """گرفتن همه سیگنال‌های فعال برای چک باطل شدن"""
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            SELECT signal_id, symbol, source, direction,
                   entry, sl, tp1, tp2, bias, leverage, margin_usd
            FROM active_signals
            WHERE is_confirmed=FALSE AND is_cancelled=FALSE
            AND created_at > (NOW() - INTERVAL '24 hours')
        """)
    else:
        c.execute("""
            SELECT signal_id, symbol, source, direction,
                   entry, sl, tp1, tp2, bias, leverage, margin_usd
            FROM active_signals
            WHERE is_confirmed=0 AND is_cancelled=0
            AND created_at > datetime('now', '-24 hours')
        """)

    rows = c.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "signal_id": row[0], "symbol": row[1],
            "source": row[2], "direction": row[3],
            "entry": row[4], "sl": row[5],
            "tp1": row[6], "tp2": row[7],
            "bias": row[8], "leverage": row[9],
            "margin_usd": row[10]
        })
    return result


def cancel_active_signal(signal_id: str):
    """باطل کردن سیگنال"""
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            UPDATE active_signals SET is_cancelled=TRUE
            WHERE signal_id=%s
        """, (signal_id,))
    else:
        c.execute("""
            UPDATE active_signals SET is_cancelled=1
            WHERE signal_id=?
        """, (signal_id,))

    conn.commit()
    conn.close()


def confirm_active_signal(signal_id: str):
    """تایید ورود به پوزیشن"""
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            UPDATE active_signals SET is_confirmed=TRUE
            WHERE signal_id=%s
        """, (signal_id,))
    else:
        c.execute("""
            UPDATE active_signals SET is_confirmed=1
            WHERE signal_id=?
        """, (signal_id,))

    conn.commit()
    conn.close()


def get_performance_stats() -> dict:
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            SELECT source, COUNT(*) as total,
            SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
            AVG(pnl_pct) as avg_pnl
            FROM signals WHERE result != 'PENDING'
            GROUP BY source
        """)
    else:
        c.execute("""
            SELECT source, COUNT(*) as total,
            SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
            AVG(pnl_pct) as avg_pnl
            FROM signals WHERE result != 'PENDING'
            GROUP BY source
        """)

    rows = c.fetchall()
    conn.close()

    stats = {}
    for row in rows:
        source, total, wins, losses, avg_pnl = row
        winrate = (wins / total * 100) if total > 0 else 0
        stats[source] = {
            "total": total, "wins": wins,
            "losses": losses, "winrate": winrate,
            "avg_pnl": avg_pnl or 0
        }
    return stats


def update_signal_result(signal_id: str, result: str, pnl_pct: float):
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            UPDATE signals SET result=%s, pnl_pct=%s, closed_at=%s
            WHERE signal_id=%s
        """, (result, pnl_pct, datetime.utcnow().isoformat(), signal_id))
    else:
        c.execute("""
            UPDATE signals SET result=?, pnl_pct=?, closed_at=?
            WHERE signal_id=?
        """, (result, pnl_pct, datetime.utcnow().isoformat(), signal_id))

    conn.commit()
    conn.close()


def check_open_signals():
    from data.fetcher import get_klines
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            SELECT signal_id, symbol, direction, entry, sl, tp1, tp2,
                   leverage, margin_usd
            FROM signals WHERE result='PENDING'
        """)
    else:
        c.execute("""
            SELECT signal_id, symbol, direction, entry, sl, tp1, tp2,
                   leverage, margin_usd
            FROM signals WHERE result='PENDING'
        """)

    open_signals = c.fetchall()
    conn.close()
    results = []

    for sig in open_signals:
        sig_id, symbol, direction, entry, sl, tp1, tp2, lev, margin = sig
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
                        "leverage": lev, "margin_usd": margin
                    })
                elif curr_h >= tp1:
                    pnl = ((tp1 - entry) / entry) * 100
                    update_signal_result(sig_id, "WIN", pnl)
                    results.append({
                        "signal_id": sig_id, "symbol": symbol,
                        "result": "WIN", "pnl": pnl,
                        "leverage": lev, "margin_usd": margin
                    })
            else:
                if curr_h >= sl:
                    pnl = ((entry - sl) / entry) * 100
                    update_signal_result(sig_id, "LOSS", pnl)
                    results.append({
                        "signal_id": sig_id, "symbol": symbol,
                        "result": "LOSS", "pnl": pnl,
                        "leverage": lev, "margin_usd": margin
                    })
                elif curr_l <= tp1:
                    pnl = ((entry - tp1) / entry) * 100
                    update_signal_result(sig_id, "WIN", pnl)
                    results.append({
                        "signal_id": sig_id, "symbol": symbol,
                        "result": "WIN", "pnl": pnl,
                        "leverage": lev, "margin_usd": margin
                    })
        except:
            continue

    return results
