import sqlite3
import json
from datetime import datetime

DB_PATH = "/tmp/signals.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_code TEXT,
            symbol TEXT,
            source TEXT,
            direction TEXT,
            entry REAL,
            sl REAL,
            tp1 REAL,
            tp2 REAL,
            bias TEXT,
            confirmations TEXT,
            score INTEGER DEFAULT 0,
            leverage INTEGER DEFAULT 5,
            margin_pct REAL DEFAULT 0,
            risk_pct REAL DEFAULT 0,
            result TEXT DEFAULT 'PENDING',
            pnl_pct REAL DEFAULT 0,
            created_at TEXT,
            closed_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS counters (
            name TEXT PRIMARY KEY,
            value INTEGER DEFAULT 99
        )
    """)

    c.execute("""
        INSERT OR IGNORE INTO counters (name, value)
        VALUES ('signal', 99)
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS market_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            bias TEXT,
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
            updated_at TEXT,
            UNIQUE(symbol)
        )
    """)

    # مهاجرت ستون‌های قدیمی
    for col in [
        "signal_code TEXT",
        "score INTEGER DEFAULT 0",
        "leverage INTEGER DEFAULT 5",
        "margin_pct REAL DEFAULT 0",
        "risk_pct REAL DEFAULT 0"
    ]:
        try:
            c.execute(f"ALTER TABLE signals ADD COLUMN {col}")
        except:
            pass

    conn.commit()
    conn.close()


def next_signal_code() -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE counters SET value = value + 1 WHERE name='signal'")
    c.execute("SELECT value FROM counters WHERE name='signal'")
    num = c.fetchone()[0]
    conn.commit()
    conn.close()
    return f"VIVA{num:04d}"


def update_market_memory(symbol: str, data: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO market_memory
        (symbol, bias, near_ob, ob_top, ob_bottom, ob_strength,
         has_sweep, has_choch, rtm_pattern, rtm_fresh,
         ict_in_ote, ict_in_killzone, current_price, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            updated_at=excluded.updated_at
    """, (
        symbol,
        data.get("bias", ""),
        1 if data.get("near_ob") else 0,
        data.get("ob_top", 0),
        data.get("ob_bottom", 0),
        data.get("ob_strength", 0),
        1 if data.get("has_sweep") else 0,
        1 if data.get("has_choch") else 0,
        data.get("rtm_pattern", ""),
        1 if data.get("rtm_fresh") else 0,
        1 if data.get("ict_in_ote") else 0,
        1 if data.get("ict_in_killzone") else 0,
        data.get("current_price", 0),
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()


def get_market_memory(symbol: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT bias, near_ob, ob_top, ob_bottom, has_sweep,
               has_choch, rtm_pattern, ict_in_ote, ict_in_killzone,
               current_price, updated_at
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
        "updated_at": row[10]
    }


def save_signal(sig: dict) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO signals
        (signal_code, symbol, source, direction, entry, sl, tp1, tp2,
         bias, confirmations, score, leverage, margin_pct, risk_pct, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sig.get("signal_code", ""),
        sig["symbol"], sig["source"], sig["direction"],
        sig["entry"], sig["sl"], sig["tp1"], sig["tp2"],
        sig.get("bias", ""),
        json.dumps(sig.get("confirmations", [])),
        sig.get("score", 0),
        sig.get("leverage", 5),
        sig.get("margin_pct", 0),
        sig.get("risk_pct", 0),
        datetime.utcnow().isoformat()
    ))
    signal_id = c.lastrowid
    conn.commit()
    conn.close()
    return signal_id


def was_signal_sent_recently(symbol: str, source: str,
                              direction: str, hours: int = 4) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT created_at FROM signals
        WHERE symbol=? AND source=? AND direction=?
        AND created_at > datetime('now', ?)
        ORDER BY created_at DESC LIMIT 1
    """, (symbol, source, direction, f'-{hours} hours'))
    row = c.fetchone()
    conn.close()
    return row is not None


def get_performance_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
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
            "total": total,
            "wins": wins,
            "losses": losses,
            "winrate": winrate,
            "avg_pnl": avg_pnl or 0
        }
    return stats


def update_signal_result(signal_id: int, result: str, pnl_pct: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE signals SET result=?, pnl_pct=?, closed_at=?
        WHERE id=?
    """, (result, pnl_pct, datetime.utcnow().isoformat(), signal_id))
    conn.commit()
    conn.close()


def check_open_signals():
    from data.fetcher import get_klines

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, signal_code, symbol, source, direction,
               entry, sl, tp1, tp2, score
        FROM signals WHERE result='PENDING'
    """)
    open_signals = c.fetchall()
    conn.close()
    results = []

    for sig in open_signals:
        (sig_id, code, symbol, source, direction,
         entry, sl, tp1, tp2, score) = sig
        try:
            df = get_klines(symbol, "15m", 5)
            if df is None:
                continue

            curr_h = df["high"].iloc[-1]
            curr_l = df["low"].iloc[-1]
            closed = None

            if direction == "LONG":
                if curr_l <= sl:
                    pnl = ((sl - entry) / entry) * 100
                    closed = "LOSS"
                elif curr_h >= tp1:
                    pnl = ((tp1 - entry) / entry) * 100
                    closed = "WIN"
            else:
                if curr_h >= sl:
                    pnl = ((entry - sl) / entry) * 100
                    closed = "LOSS"
                elif curr_l <= tp1:
                    pnl = ((entry - tp1) / entry) * 100
                    closed = "WIN"

            if closed:
                update_signal_result(sig_id, closed, pnl)
                results.append({
                    "signal_code": code or f"ID{sig_id}",
                    "symbol": symbol,
                    "source": source,
                    "direction": direction,
                    "result": closed,
                    "pnl": pnl,
                    "score": score or 0
                })
        except:
            continue

    return results
