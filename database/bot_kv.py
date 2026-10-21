"""Durable tiny key/value store for alert-state that must survive redeploys.

Production (Supabase DATABASE_URL) keeps it in Postgres; local/dev falls back
to the same SQLite file as the candidate store. Intentionally minimal: JSON
blobs keyed by name — alert cooldown stamps, funnel counters, cache markers.
Every accessor is fail-soft: a DB hiccup degrades to "no memory" (worst case
one duplicate preview after a restart), never to a crash in the scan loop.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from database.candidate_store import _connection, _use_pg

_TABLE_READY = {"done": False}


def _ensure_table(conn) -> None:
    if _TABLE_READY["done"]:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    _TABLE_READY["done"] = True


def get_json(key: str, default: Any = None) -> Any:
    try:
        with _connection() as conn:
            _ensure_table(conn)
            row = conn.execute("SELECT value FROM bot_kv WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        return json.loads(row["value"])
    except Exception as exc:
        print(f"bot_kv get {key} degraded: {exc}")
        return default


def set_json(key: str, value: Any) -> bool:
    from analysis.models import iso_now
    try:
        blob = json.dumps(value, ensure_ascii=False, default=str)
        upsert = (
            """INSERT INTO bot_kv (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT (key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"""
            if _use_pg() else
            """INSERT INTO bot_kv (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT (key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"""
        )
        with _connection() as conn:
            _ensure_table(conn)
            conn.execute(upsert, (key, blob, iso_now()))
        return True
    except Exception as exc:
        print(f"bot_kv set {key} degraded: {exc}")
        return False
