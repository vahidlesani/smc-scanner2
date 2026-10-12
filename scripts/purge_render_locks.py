"""پاکسازی یک‌بارهٔ قفل‌های رندر قدیمی (render_identity / zoom_freeze).

درخواست ویوا ۲۰۲۶-۱۰-۱۲: «کش رو خالی کن». با مارکر یک‌بار اجرا می‌شود تا
زنجیره‌های زنده با کدِ ترمیم‌شده دوباره رندر شوند؛ بعد خودش غیرفعال می‌ماند.
"""
from __future__ import annotations

MARKER = "render_locks_purge_20261012_done"


def purge_once() -> int:
    try:
        from database import bot_kv
        if bot_kv.get_json(MARKER):
            return 0
        from database.candidate_store import _connection
        with _connection() as conn:
            cur = conn.execute(
                "DELETE FROM bot_kv WHERE key LIKE 'render_identity:%' "
                "OR key LIKE 'zoom_freeze:%'")
            n = getattr(cur, "rowcount", -1)
        bot_kv.set_json(MARKER, {"purged": n})
        print(f"render locks purged: {n}")
        return n
    except Exception as exc:
        print(f"purge_render_locks degraded: {exc}")
        return 0


if __name__ == "__main__":
    purge_once()
