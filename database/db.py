import sqlite3
import json
from datetime import datetime
import os

DB_PATH = os.environ.get("DB_PATH", "signals.db")

def init_db():
    """ساخت جداول اگه وجود نداشته باشن"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # جدول سیگنال‌ها
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            created_at TEXT,
            closed_at TEXT
        )
    """)
    
    # جدول performance
    c.execute("""
        CREATE TABLE IF NOT EXISTS performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            symbol TEXT,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_pnl REAL DEFAULT 0,
            updated_at TEXT
        )
    """)
    
    conn.commit()
    conn.close()


def save_signal(sig: dict) -> int:
    """ذخیره سیگنال جدید"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        INSERT INTO signals 
        (symbol, source, direction, entry, sl, tp1, tp2, 
         bias, confirmations, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sig["symbol"],
        sig["source"],
        sig["direction"],
        sig["entry"],
        sig["sl"],
        sig["tp1"],
        sig["tp2"],
        sig.get("bias", ""),
        json.dumps(sig.get("confirmations", [])),
        datetime.utcnow().isoformat()
    ))
    
    signal_id = c.lastrowid
    conn.commit()
    conn.close()
    return signal_id


def was_signal_sent_recently(symbol: str, source: str, 
                              direction: str, hours: int = 4) -> bool:
    """چک میکنه سیگنال تکراری نباشه"""
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
    """آمار کلی عملکرد"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        SELECT 
            source,
            COUNT(*) as total,
            SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
            AVG(pnl_pct) as avg_pnl
        FROM signals
        WHERE result != 'PENDING'
        GROUP BY source
    """)
    
    rows = c.fetchall()
    conn.close()
    
    stats = {}
    for row in rows:
        source, total, wins, losses, avg_pnl = row
        winrate = (wins/total*100) if total > 0 else 0
        stats[source] = {
            "total": total,
            "wins": wins,
            "losses": losses,
            "winrate": winrate,
            "avg_pnl": avg_pnl or 0
        }
    
    return stats


def update_signal_result(signal_id: int, result: str, pnl_pct: float):
    """آپدیت نتیجه سیگنال"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        UPDATE signals 
        SET result=?, pnl_pct=?, closed_at=?
        WHERE id=?
    """, (result, pnl_pct, datetime.utcnow().isoformat(), signal_id))
    
    conn.commit()
    conn.close()


def check_open_signals():
    """
    چک میکنه سیگنال‌های باز به TP یا SL رسیدن
    این رو هر اسکن صدا میزنیم
    """
    from data.fetcher import get_klines
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        SELECT id, symbol, direction, entry, sl, tp1, tp2
        FROM signals WHERE result='PENDING'
    """)
    
    open_signals = c.fetchall()
    conn.close()
    
    results = []
    
    for sig in open_signals:
        sig_id, symbol, direction, entry, sl, tp1, tp2 = sig
        
        try:
            df = get_klines(symbol, "15m", 10)
            if df is None:
                continue
            
            current_high = df["high"].iloc[-1]
            current_low = df["low"].iloc[-1]
            
            if direction == "LONG":
                if current_low <= sl:
                    pnl = ((sl - entry) / entry) * 100
                    update_signal_result(sig_id, "LOSS", pnl)
                    results.append({"id": sig_id, "symbol": symbol, 
                                   "result": "LOSS", "pnl": pnl})
                elif current_high >= tp1:
                    pnl = ((tp1 - entry) / entry) * 100
                    update_signal_result(sig_id, "WIN", pnl)
                    results.append({"id": sig_id, "symbol": symbol,
                                   "result": "WIN", "pnl": pnl})
            
            elif direction == "SHORT":
                if current_high >= sl:
                    pnl = ((entry - sl) / entry) * 100
                    update_signal_result(sig_id, "LOSS", pnl)
                    results.append({"id": sig_id, "symbol": symbol,
                                   "result": "LOSS", "pnl": pnl})
                elif current_low <= tp1:
                    pnl = ((entry - tp1) / entry) * 100
                    update_signal_result(sig_id, "WIN", pnl)
                    results.append({"id": sig_id, "symbol": symbol,
                                   "result": "WIN", "pnl": pnl})
        except:
            continue
    
    return results
