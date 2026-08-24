"""Local, transient candidate state.

Unconfirmed educational setups are deliberately NOT written to Supabase.
This SQLite store is operational state only and can be placed on a persistent
disk with CANDIDATE_DB_PATH if restart durability is desired.

Viva's locking model (v7.6): a pending scenario must NEVER block the whole
symbol. Locks are per (symbol, trigger timeframe) — a pending 1h swing still
allows scalp alerts on the same symbol's 5m/15m triggers.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from analysis.models import SignalCandidate, iso_now

DB_PATH = os.getenv("CANDIDATE_DB_PATH", "/tmp/viva_candidates.db")
# Non-confirmed lifecycles are throwaway: once resolved they are removed fast.
# Confirmed rows persist a bit longer (they are the only ones ALSO in Supabase).
RESOLVED_RETENTION_HOURS = int(os.getenv("CANDIDATE_RESOLVED_RETENTION_HOURS", "6"))
CONFIRMED_RETENTION_HOURS = int(os.getenv("CANDIDATE_CONFIRMED_RETENTION_HOURS", "48"))


@contextmanager
def _connection():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_candidate_store() -> None:
    with _connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_candidates (
                signal_id TEXT PRIMARY KEY,
                dedupe_key TEXT NOT NULL,
                symbol TEXT NOT NULL,
                style TEXT NOT NULL,
                setup_code TEXT NOT NULL,
                direction TEXT NOT NULL,
                score INTEGER NOT NULL,
                status TEXT NOT NULL,
                approaching_sent INTEGER DEFAULT 0,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        # Migration: per-timeframe locking needs the trigger TF as a column.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(signal_candidates)")}
        if "trigger_tf" not in columns:
            conn.execute("ALTER TABLE signal_candidates ADD COLUMN trigger_tf TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_active ON signal_candidates(status, expires_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_dedupe ON signal_candidates(dedupe_key, status)")


def _trigger_tf(candidate: SignalCandidate) -> str:
    return str(getattr(candidate, "trigger_timeframe", "") or "").lower()


def _dedupe_key(candidate: SignalCandidate) -> str:
    # One unresolved lifecycle per (symbol, trigger timeframe). A pending 1h
    # swing no longer blocks scalp setups on the same symbol's 5m trigger.
    return f"{candidate.symbol.upper()}:{_trigger_tf(candidate)}"


def _zone_kind(candidate: SignalCandidate) -> str:
    md = candidate.metadata or {}
    return str(md.get("pin_zone_kind") or md.get("zone_kind") or md.get("viva_pattern") or "").upper()


def _same_alert_lineage(previous: SignalCandidate, candidate: SignalCandidate) -> bool:
    """Conservative identity test for a *single alert scenario*.

    A same-symbol or same-trigger match is never enough: Viva allows multiple
    paper scenarios there.  Without an explicit detector lineage key, we only
    consider two alerts one lineage if their setup, direction, zone type and
    actual zone price are almost identical.  False negatives merely leave an
    extra alert visible; false positives could delete a valid setup, so they
    are intentionally avoided.
    """
    if (
        previous.symbol.upper() != candidate.symbol.upper()
        or _trigger_tf(previous) != _trigger_tf(candidate)
        or previous.setup_code.upper() != candidate.setup_code.upper()
        or previous.direction.upper() != candidate.direction.upper()
        or _zone_kind(previous) != _zone_kind(candidate)
    ):
        return False
    old_key = str((previous.metadata or {}).get("alert_lineage_key") or "")
    new_key = str((candidate.metadata or {}).get("alert_lineage_key") or "")
    if old_key or new_key:
        return bool(old_key and old_key == new_key)
    old_atr = float((previous.metadata or {}).get("atr", 0) or 0)
    new_atr = float((candidate.metadata or {}).get("atr", 0) or 0)
    # 0.08 ATR is deliberately tighter than the 0.20-ATR material-update
    # threshold. A moved zone is a new scenario, never a deletion candidate.
    tolerance = max(max(old_atr, new_atr) * 0.08, abs(previous.zone_mid) * 0.0001, 1e-12)
    return abs(float(previous.zone_mid) - float(candidate.zone_mid)) <= tolerance


def _live_candidates_for_symbol_tf(candidate: SignalCandidate) -> List[SignalCandidate]:
    now = iso_now()
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT payload FROM signal_candidates
            WHERE symbol=? AND trigger_tf=?
              AND status IN ('EDUCATIONAL', 'APPROACHING') AND expires_at>?
            ORDER BY created_at DESC
            """,
            (candidate.symbol.upper(), _trigger_tf(candidate), now),
        ).fetchall()
    return [SignalCandidate.from_json(row["payload"]) for row in rows]


def find_similar(candidate: SignalCandidate) -> Optional[SignalCandidate]:
    """Find only an update of the same scenario — never another BTC setup."""
    for previous in _live_candidates_for_symbol_tf(candidate):
        if _same_alert_lineage(previous, candidate):
            return previous
    return None


def supersede_alert_lineage(candidate: SignalCandidate) -> List[SignalCandidate]:
    """Supersede only older posts from this exact alert lineage.

    This is intentionally not a symbol-wide cleanup. Independent alerts on the
    same symbol/trigger remain visible and keep their own Telegram lifecycle.
    """
    previous = [
        item for item in _live_candidates_for_symbol_tf(candidate)
        if item.signal_id != candidate.signal_id and _same_alert_lineage(item, candidate)
    ]
    for item in previous:
        item.status = "SUPERSEDED"
        item.metadata["superseded_by"] = candidate.signal_id
        update_candidate(item)
    return previous


def supersede_symbol_alerts(symbol: str, replacement_id: str) -> List[SignalCandidate]:
    """Deprecated safety shim: symbol-only deletion is forbidden.

    Kept only so an accidental old caller cannot erase unrelated alerts.
    """
    print(f"Refused unsafe symbol-wide alert supersede for {symbol} -> {replacement_id}")
    return []


def is_material_update(previous: SignalCandidate, candidate: SignalCandidate) -> bool:
    """Avoid reposting identical scans; replace only when the live scenario
    meaningfully changed (direction/setup/zone/structure)."""
    if previous.setup_code != candidate.setup_code or previous.direction != candidate.direction:
        return True
    old_atr = float(previous.metadata.get("atr", 0) or 0)
    threshold = max(old_atr * 0.20, abs(previous.zone_mid) * 0.0005, 1e-12)
    if abs(previous.zone_mid - candidate.zone_mid) > threshold:
        return True
    old_level = float(previous.metadata.get("structure_level", 0) or 0)
    new_level = float(candidate.metadata.get("structure_level", 0) or 0)
    return bool(old_level and new_level and abs(old_level - new_level) > threshold)


def supersede_similar(candidate: SignalCandidate) -> Optional[SignalCandidate]:
    """Keep only the freshest live alert for one symbol/trigger timeframe.
    Confirmed trades are never superseded; only alert-channel clutter is."""
    previous = find_similar(candidate)
    if not previous:
        return None
    previous.status = "SUPERSEDED"
    previous.metadata["superseded_by"] = candidate.signal_id
    update_candidate(previous)
    return previous


def add_candidate(candidate: SignalCandidate) -> bool:
    if find_similar(candidate):
        return False
    now = iso_now()
    with _connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO signal_candidates
            (signal_id, dedupe_key, symbol, style, setup_code, direction,
             score, status, approaching_sent, payload, created_at, updated_at, expires_at, trigger_tf)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.signal_id,
                _dedupe_key(candidate),
                candidate.symbol,
                candidate.style,
                candidate.setup_code,
                candidate.direction,
                candidate.score,
                candidate.status,
                int(candidate.approaching_sent),
                candidate.to_json(),
                candidate.created_at,
                now,
                candidate.expires_at,
                _trigger_tf(candidate),
            ),
        )
        return conn.total_changes > 0


def update_candidate(candidate: SignalCandidate, status: Optional[str] = None) -> None:
    if status:
        candidate.status = status
    with _connection() as conn:
        conn.execute(
            """
            UPDATE signal_candidates
            SET score=?, status=?, approaching_sent=?, payload=?, updated_at=?, expires_at=?, trigger_tf=?
            WHERE signal_id=?
            """,
            (
                candidate.score,
                candidate.status,
                int(candidate.approaching_sent),
                candidate.to_json(),
                iso_now(),
                candidate.expires_at,
                _trigger_tf(candidate),
                candidate.signal_id,
            ),
        )


def get_active_candidates() -> List[SignalCandidate]:
    now = iso_now()
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT payload FROM signal_candidates
            WHERE status IN ('EDUCATIONAL', 'APPROACHING') AND expires_at>?
            ORDER BY created_at
            """,
            (now,),
        ).fetchall()
    return [SignalCandidate.from_json(row["payload"]) for row in rows]


def set_status(signal_id: str, status: str) -> None:
    with _connection() as conn:
        row = conn.execute("SELECT payload FROM signal_candidates WHERE signal_id=?", (signal_id,)).fetchone()
        if not row:
            return
        candidate = SignalCandidate.from_json(row["payload"])
        candidate.status = status
        conn.execute(
            "UPDATE signal_candidates SET status=?, payload=?, updated_at=? WHERE signal_id=?",
            (status, candidate.to_json(), iso_now(), signal_id),
        )


def cleanup_candidates(retention_days: int = 7) -> int:
    """Aggressive slimming (Viva's DB policy): only confirmed signals deserve
    history — and those already persist in Supabase. Everything resolved and
    non-confirmed disappears after RESOLVED_RETENTION_HOURS."""
    now_dt = datetime.now(timezone.utc)
    resolved_cutoff = (now_dt - timedelta(hours=RESOLVED_RETENTION_HOURS)).isoformat(timespec="seconds")
    confirmed_cutoff = (now_dt - timedelta(hours=CONFIRMED_RETENTION_HOURS)).isoformat(timespec="seconds")
    legacy_cutoff = (now_dt - timedelta(days=retention_days)).isoformat(timespec="seconds")
    now = iso_now()
    with _connection() as conn:
        conn.execute(
            "UPDATE signal_candidates SET status='EXPIRED', updated_at=? WHERE expires_at<=? AND status IN ('EDUCATIONAL','APPROACHING')",
            (now, now),
        )
        cursor = conn.execute(
            """
            DELETE FROM signal_candidates
            WHERE (status NOT IN ('CONFIRMED','EDUCATIONAL','APPROACHING') AND updated_at<?)
               OR (status='CONFIRMED' AND updated_at<?)
               OR (updated_at<?)
            """,
            (resolved_cutoff, confirmed_cutoff, legacy_cutoff),
        )
        return cursor.rowcount


def get_resolved_candidates(limit: int = 400) -> List[SignalCandidate]:
    """Transient alert records eligible for Telegram-channel cleanup only."""
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT payload FROM signal_candidates
            WHERE status NOT IN ('EDUCATIONAL','APPROACHING','CONFIRMED')
            ORDER BY updated_at ASC LIMIT ?
            """, (int(limit),)
        ).fetchall()
    return [SignalCandidate.from_json(row["payload"]) for row in rows]
