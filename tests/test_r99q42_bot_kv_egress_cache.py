import importlib
from contextlib import contextmanager


def test_bot_kv_is_immutable_write_through_and_periodically_reconciled(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDIDATE_DB_BACKEND", "sqlite")
    monkeypatch.setenv("CANDIDATE_DB_PATH", str(tmp_path / "kv-cache.sqlite"))
    monkeypatch.delenv("BOT_KV_CACHE_SECONDS", raising=False)

    import database.bot_kv as kv
    kv = importlib.reload(kv)  # earlier legacy tests replace module callables directly

    kv._TABLE_READY["done"] = False
    kv._reset_cache()
    clock = {"now": 100.0}
    monkeypatch.setattr(kv.time, "monotonic", lambda: clock["now"])

    assert kv.set_json("probe", {"nested": {"value": 1}})
    kv._reset_cache()  # simulate a fresh process before the first durable read

    real_connection = kv._connection
    calls = {"select": 0, "upsert": 0}

    @contextmanager
    def counted_connection():
        with real_connection() as raw:
            class Proxy:
                def execute(self, sql, params=()):
                    normalized = " ".join(sql.upper().split())
                    if normalized.startswith("SELECT VALUE FROM BOT_KV"):
                        calls["select"] += 1
                    if normalized.startswith("INSERT INTO BOT_KV"):
                        calls["upsert"] += 1
                    return raw.execute(sql, params)

            yield Proxy()

    monkeypatch.setattr(kv, "_connection", counted_connection)

    first = kv.get_json("probe", {})
    first["nested"]["value"] = 99
    assert kv.get_json("probe", {})["nested"]["value"] == 1
    assert calls["select"] == 1

    # A caller setting the already-cached JSON does not touch Supabase.
    assert kv.set_json("probe", {"nested": {"value": 1}})
    assert calls["upsert"] == 0

    # Manual/external SQL remains visible after the 15-minute safety interval.
    with real_connection() as conn:
        conn.execute(
            "UPDATE bot_kv SET value=? WHERE key=?",
            ('{"nested": {"value": 2}}', "probe"),
        )
    assert kv.get_json("probe", {})["nested"]["value"] == 1
    clock["now"] += 901
    assert kv.get_json("probe", {})["nested"]["value"] == 2
    assert calls["select"] == 2

    # Production has tens of thousands of historical keys; the process cache
    # must retain only the hot working set rather than grow for its lifetime.
    monkeypatch.setenv("BOT_KV_CACHE_MAX_ENTRIES", "64")
    with kv._KV_CACHE_LOCK:
        for n in range(65):
            kv._cache_put_locked(f"bound-{n}", "{}", clock["now"])
        assert len(kv._KV_CACHE) == 64
        assert "bound-0" not in kv._KV_CACHE
        assert "bound-64" in kv._KV_CACHE
