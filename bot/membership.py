"""
bot/membership.py — membership, referral & usage-gate for the public bot.

Plans:
  free     : 3 lifetime "instant analysis" uses; reports/education open.
  referred : free user who deposited ≥$50 via our exchange link and sent UID
             (approved by admin) → channel invite link + analysis cap lifted.
  paid     : wallet payment ($15/mo, $30/3mo, $50/6mo) → full access.

Whitelist (env ADMIN_USERNAMES) bypasses everything.
Degrades gracefully (in-memory allow + log) when the DB is unavailable.
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

FREE_ANALYSIS_LIMIT = int(os.getenv("FREE_ANALYSIS_LIMIT", "3"))

PLANS = {
    "1m": (15, 1),
    "3m": (30, 3),
    "6m": (50, 6),
}

REF_LINKS = {
    "Ourbit": os.getenv("REF_OURBIT_URL", "https://www.ourbit.com"),
    "XT": os.getenv("REF_XT_URL", "https://www.xt.com"),
    "Bitunix": os.getenv("REF_BITUNIX_URL", "https://www.bitunix.com"),
    "Tabdeal": os.getenv("REF_TABDEAL_URL", "https://tabdeal.org"),
}

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")
WALLET_QR_PATH = os.getenv("WALLET_QR_PATH", "assets/wallet_qr.png")
WALLET_USDT_ADDRESS = os.getenv("WALLET_USDT_ADDRESS", WALLET_ADDRESS)
CHANNEL_INVITE_URL = os.getenv("CHANNEL_INVITE_URL", "")
ADMIN_USERNAMES = {
    u.strip().lstrip("@").lower()
    for u in os.getenv("ADMIN_USERNAMES", "vahidlesani,Sogandddkia,vivamonlabs").split(",")
    if u.strip()
}

# in-memory text-capture states: user_id -> "await_uid" | "await_tx"
_pending: dict[int, str] = {}
_mem_fallback: dict[int, dict] = {}


# ---------------------------------------------------------------- DB helpers

def _db():
    """(connection, placeholder) — works for Postgres and sqlite fallback."""
    from database import db as _d
    return _d.get_conn(), ("%s" if _d.USE_POSTGRES else "?")


def _exec(sql: str, params: tuple = (), fetch: bool = False):
    conn, ph = _db()
    cur = conn.cursor()
    cur.execute(sql.replace("%s", ph), params)
    rows = cur.fetchall() if fetch else None
    conn.commit()
    cur.close()
    conn.close()
    return rows


def ensure_schema() -> None:
    try:
        from database import db as _d
        dt = "TIMESTAMPTZ" if _d.USE_POSTGRES else "TEXT"
        conflict = (
            "ON CONFLICT (user_id) DO NOTHING" if _d.USE_POSTGRES
            else "INSERT OR IGNORE"
        )
        _exec(
            f"""
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                plan TEXT NOT NULL DEFAULT 'free',
                plan_expires {dt},
                analysis_used INT NOT NULL DEFAULT 0,
                referred BOOLEAN NOT NULL DEFAULT FALSE,
                exchange_uid TEXT,
                tx_ref TEXT,
                joined_at {dt}
            );
            """ if _d.USE_POSTGRES else
            """
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                plan TEXT NOT NULL DEFAULT 'free',
                plan_expires TEXT,
                analysis_used INTEGER NOT NULL DEFAULT 0,
                referred INTEGER NOT NULL DEFAULT 0,
                exchange_uid TEXT,
                tx_ref TEXT,
                joined_at TEXT
            );
            """
        )
        logger.info("bot_users schema ready (conflict helper: %s)", conflict)
    except Exception as e:
        logger.warning("membership schema init skipped: %s", e)


def register_user(user_id: int, username: str = "", first_name: str = "") -> dict:
    fb = _mem_fallback.setdefault(user_id, {
        "plan": "free", "analysis_used": 0, "referred": False, "plan_expires": None,
    })
    try:
        from database import db as _d
        now = datetime.now(timezone.utc)
        if _d.USE_POSTGRES:
            _exec(
                """INSERT INTO bot_users (user_id, username, first_name, joined_at)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (user_id) DO UPDATE SET username=EXCLUDED.username""",
                (user_id, username, first_name, now),
            )
        else:
            _exec(
                "INSERT OR IGNORE INTO bot_users (user_id, username, first_name, joined_at) VALUES (?,?,?,?)",
                (user_id, username, first_name, now.isoformat()),
            )
        rows = _exec(
            "SELECT plan, analysis_used, referred, plan_expires FROM bot_users WHERE user_id=%s",
            (user_id,), fetch=True,
        )
        if rows:
            r = rows[0]
            exp = r[3]
            if isinstance(exp, str):
                try:
                    exp = datetime.fromisoformat(exp)
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                except Exception:
                    exp = None
            return {"plan": r[0], "analysis_used": r[1], "referred": bool(r[2]), "plan_expires": exp}
    except Exception as e:
        logger.debug("register_user fallback (%s)", e)
    return fb


# ------------------------------------------------------------------- access

def is_whitelisted(username: str) -> bool:
    return (username or "").lstrip("@").lower() in ADMIN_USERNAMES


def is_admin_chat(user_id: int) -> bool:
    try:
        from config import get_settings
        return str(user_id) == str(get_settings().CHAT_ID_ADMIN)
    except Exception:
        return False


def _plan_active(row: dict) -> bool:
    exp = row.get("plan_expires")
    if isinstance(exp, datetime) and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return row.get("plan") == "paid" and isinstance(exp, datetime) and exp > datetime.now(timezone.utc)


def has_full_access(user_id: int, username: str = "") -> bool:
    if is_whitelisted(username) or is_admin_chat(user_id):
        return True
    return _plan_active(register_user(user_id, username))


def can_use_analysis(user_id: int, username: str = "") -> tuple[bool, str]:
    """Returns (allowed, reason_fa)."""
    if has_full_access(user_id, username):
        return True, ""
    row = register_user(user_id, username)
    if row.get("referred"):
        return True, ""
    if int(row.get("analysis_used") or 0) < FREE_ANALYSIS_LIMIT:
        return True, ""
    return False, (
        f"⛔️ سهمیهٔ رایگان «تحلیل فوری» تمام شد ({FREE_ANALYSIS_LIMIT} بار).\n"
        "برای ادامه، از بخش «💎 عضویت» یکی از روش‌ها را فعال کن."
    )


def consume_analysis(user_id: int, username: str = "") -> None:
    if has_full_access(user_id, username):
        return
    row = register_user(user_id, username)
    if row.get("referred"):
        return
    _mem_fallback.setdefault(user_id, {}).update(
        {"analysis_used": int(row.get("analysis_used") or 0) + 1}
    )
    try:
        _exec("UPDATE bot_users SET analysis_used = analysis_used + 1 WHERE user_id=%s", (user_id,))
    except Exception:
        pass


# ---------------------------------------------------------------- capture

def set_pending(user_id: int, state: Optional[str]) -> None:
    if state:
        _pending[user_id] = state
    else:
        _pending.pop(user_id, None)


def get_pending(user_id: int) -> Optional[str]:
    return _pending.get(user_id)


def mark_uid(user_id: int, uid: str) -> None:
    try:
        _exec("UPDATE bot_users SET exchange_uid=%s WHERE user_id=%s", (uid, user_id))
    except Exception:
        pass


def approve_referral(user_id: int) -> None:
    try:
        from database import db as _d
        val = True if _d.USE_POSTGRES else 1
        _exec("UPDATE bot_users SET referred=%s WHERE user_id=%s", (val, user_id))
    except Exception:
        pass
    _mem_fallback.setdefault(user_id, {}).update({"referred": True})


def mark_tx(user_id: int, tx: str) -> None:
    try:
        _exec("UPDATE bot_users SET tx_ref=%s WHERE user_id=%s", (tx, user_id))
    except Exception:
        pass


def activate_plan(user_id: int, months: int) -> None:
    exp = datetime.now(timezone.utc) + timedelta(days=30 * months)
    try:
        _exec("UPDATE bot_users SET plan='paid', plan_expires=%s WHERE user_id=%s", (exp, user_id))
    except Exception:
        pass
    _mem_fallback.setdefault(user_id, {}).update({"plan": "paid", "plan_expires": exp})


def count_users() -> int:
    try:
        rows = _exec("SELECT COUNT(*) FROM bot_users", fetch=True)
        return int(rows[0][0]) if rows else 0
    except Exception:
        return len(_mem_fallback)


# ------------------------------------------------------------------- labels

def plan_status_fa(user_id: int, username: str = "") -> str:
    if is_whitelisted(username) or is_admin_chat(user_id):
        return "دسترسی نامحدود 👑"
    row = register_user(user_id, username)
    if _plan_active(row):
        exp = row["plan_expires"].strftime("%Y-%m-%d")
        return f"عضویت ویژه تا {exp} 💎"
    if row.get("referred"):
        return "عضو کانال با معرفی‌نامه 💚"
    used = int(row.get("analysis_used") or 0)
    left = max(0, FREE_ANALYSIS_LIMIT - used)
    return f"رایگان 🆓 — {left} تحلیل فوری باقی مانده"
