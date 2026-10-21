import json
import sqlite3

import webapp_viva as app


def test_feed_messages_use_one_manifest_and_only_reload_changed_values(monkeypatch):
    connection = sqlite3.connect(":memory:")
    cursor = connection.cursor()
    cursor.execute(
        "CREATE TABLE bot_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    cursor.executemany(
        "INSERT INTO bot_kv(key,value,updated_at) VALUES (?,?,?)",
        [
            ("app_msg|sig-1|compact", json.dumps({"html": "compact-1"}), "t1"),
            ("app_msg|sig-1|update", json.dumps({"html": "update-1"}), "t2"),
            ("app_msg|sig-2|compact", json.dumps({"html": "compact-2"}), "t1"),
        ],
    )
    connection.commit()

    monkeypatch.setattr(app, "_db_placeholder", lambda: "?")
    app._APP_MSG_CACHE.clear()
    statements = []
    connection.set_trace_callback(statements.append)

    first = app._app_messages_for_feed(cursor, ["sig-1", "sig-2", "missing"])
    assert first == {"sig-1": "update-1", "sig-2": "compact-2"}
    first_value_reads = sum("SELECT key, value, updated_at" in sql for sql in statements)
    assert first_value_reads == 1

    # No body changed: only the tiny key/timestamp manifest crosses the wire.
    statements.clear()
    second = app._app_messages_for_feed(cursor, ["sig-1", "sig-2", "missing"])
    assert second == first
    assert not any("SELECT key, value, updated_at" in sql for sql in statements)

    # One changed timestamp reloads exactly that selected message.
    cursor.execute(
        "UPDATE bot_kv SET value=?, updated_at=? WHERE key=?",
        (json.dumps({"html": "update-1-new"}), "t3", "app_msg|sig-1|update"),
    )
    connection.commit()
    statements.clear()
    third = app._app_messages_for_feed(cursor, ["sig-1", "sig-2"])
    assert third == {"sig-1": "update-1-new", "sig-2": "compact-2"}
    value_selects = [sql for sql in statements if "SELECT key, value, updated_at" in sql]
    assert len(value_selects) == 1
    assert "app_msg|sig-1|update" in value_selects[0]
    assert "app_msg|sig-2|compact" not in value_selects[0]
    connection.close()
