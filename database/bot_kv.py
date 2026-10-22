"""Durable tiny key/value store for alert-state that must survive redeploys.

Production (Supabase DATABASE_URL) keeps it in Postgres; local/dev falls back
to the same SQLite file as the candidate store. Intentionally minimal: JSON
blobs keyed by name — alert cooldown stamps, funnel counters, cache markers.
Every accessor is fail-soft: a DB hiccup degrades to "no memory" (worst case
one duplicate preview after a restart), never to a crash in the scan loop.

Supabase egress guard (2026-10-22): scanner, spot and web paths used to perform
more than two million one-key SELECTs over the measured statistics window.
The combined service is the writer for these keys, so durable values are kept
as immutable JSON strings in a process-local write-through cache and reconciled
periodically. Decoding on every return prevents callers from mutating the cache.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from database.candidate_store import _active_cache_namespace, _connection, _use_pg

_TABLE_READY = {"done": False}
_KV_CACHE_LOCK = threading.RLock()
_KV_CACHE_NAMESPACE = None
_KV_CACHE = {}  # key -> (raw JSON string or None for missing, loaded monotonic time)


def _cache_seconds() -> float:
    try:
        return max(10.0, float(os.getenv("BOT_KV_CACHE_SECONDS", "900") or 900))
    except (TypeError, ValueError):
        return 900.0


def _cache_namespace_locked():
    """Reset automatically when tests switch SQLite files/backends."""
    global _KV_CACHE_NAMESPACE, _KV_CACHE
    namespace = _active_cache_namespace()
    if namespace != _KV_CACHE_NAMESPACE:
        _KV_CACHE_NAMESPACE = namespace
        _KV_CACHE = {}
        _TABLE_READY["done"] = False
    return namespace


def _reset_cache() -> None:
    """Force storage reconciliation on the next read (tests/maintenance)."""
    global _KV_CACHE_NAMESPACE, _KV_CACHE
    with _KV_CACHE_LOCK:
        _KV_CACHE_NAMESPACE = None
        _KV_CACHE = {}


def _decode(blob: Any, default: Any) -> Any:
    if blob is None:
        return default
    try:
        return json.loads(blob)
    except Exception:
        return default


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
    key = str(key)
    now = time.monotonic()
    stale = None
    with _KV_CACHE_LOCK:
        _cache_namespace_locked()
        cached = _KV_CACHE.get(key)
        if cached is not None:
            stale = cached[0]
            if now - cached[1] < _cache_seconds():
                return _decode(stale, default)
    try:
        with _connection() as conn:
            _ensure_table(conn)
            row = conn.execute("SELECT value FROM bot_kv WHERE key=?", (key,)).fetchone()
        blob = str(row["value"]) if row else None
        with _KV_CACHE_LOCK:
            _cache_namespace_locked()
            _KV_CACHE[key] = (blob, now)
        return _decode(blob, default)
    except Exception as exc:
        print(f"bot_kv get {key} degraded: {exc}")
        # A stale durable value is safer than forgetting alert state and sending
        # duplicates merely because one reconciliation query failed.
        return _decode(stale, default)


def set_json(key: str, value: Any) -> bool:
    from analysis.models import iso_now
    key = str(key)
    try:
        blob = json.dumps(value, ensure_ascii=False, default=str)
        with _KV_CACHE_LOCK:
            _cache_namespace_locked()
            cached = _KV_CACHE.get(key)
            if (cached is not None and cached[0] == blob
                    and time.monotonic() - cached[1] < _cache_seconds()):
                return True  # unchanged fresh local state needs no Supabase write
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
        with _KV_CACHE_LOCK:
            _cache_namespace_locked()
            _KV_CACHE[key] = (blob, time.monotonic())
        return True
    except Exception as exc:
        print(f"bot_kv set {key} degraded: {exc}")
        return False
