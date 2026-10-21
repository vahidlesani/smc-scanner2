from database import app_push


def test_zero_subscribers_never_query_the_signal_tail(monkeypatch):
    calls = {"tail": 0}
    monkeypatch.setattr(app_push, "subscriber_count", lambda: 0)

    def forbidden_tail():
        calls["tail"] += 1
        raise AssertionError("zero-subscriber loop touched the signals table")

    monkeypatch.setattr(app_push, "tail_once", forbidden_tail)
    assert app_push._tail_pass_if_subscribed() is False
    assert calls["tail"] == 0
    assert app_push._tail_stats["idle"] == 1
    assert app_push._tail_stats["subs"] == 0


def test_subscriber_keeps_the_original_five_second_tail_path(monkeypatch):
    calls = {"tail": 0}
    monkeypatch.setattr(app_push, "subscriber_count", lambda: 1)

    def one_tail():
        calls["tail"] += 1
        return {"events": 1, "pushed": 1, "error": ""}

    monkeypatch.setattr(app_push, "tail_once", one_tail)
    assert app_push._tail_pass_if_subscribed() is True
    assert calls["tail"] == 1
    assert app_push._tail_stats["idle"] == 0
    assert app_push._tail_stats["subs"] == 1


def test_first_subscription_primes_now_and_wakes_idle_loop(monkeypatch):
    memory = {}
    writes = []
    monkeypatch.setattr(app_push, "_kv_get", lambda key, default=None: memory.get(key, default))

    def put(key, value):
        memory[key] = value
        writes.append((key, value))

    monkeypatch.setattr(app_push, "_kv_set", put)
    app_push._TAIL_WAKE.clear()
    assert app_push.subscribe({"endpoint": "https://push.example/new-phone"})
    assert app_push._TAIL_WAKE.is_set()
    assert app_push._KV_TAIL in memory
    assert memory[app_push._KV_TAIL]["since"]
    assert any(key == app_push._KV_SUBS for key, _ in writes)
    app_push._TAIL_WAKE.clear()
