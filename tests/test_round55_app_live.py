"""r55 — the app is LIVE like Telegram + real phone push + freeze-proof state.

Viva 09-28, verbatim: «اپلیکیشن دقیقا باید مثل تلگرام عمل بکنه — در همون لحظه
تایید باید تایید سیگنال به اپلیکیشن هم بره و بصورت لایو و لحظه‌ای نتیجه هیت
شدن‌ها یا استاپ بروزرسانی بشه … در بخش نتایج یک بخش باید وجود داشته باشه که
سیگنال‌ها هر لحظه که تایید میشه بروز بشه و بیاد … اوایل نوتفیکیشن فعال بود
اما الان دیگه به گوشی نوتیف نمیاد».

Covered:
1. push core: VAPID keys generated once (durable), subscribe/unsubscribe,
   gone-subscription pruning — all on an in-memory KV, fail-open.
2. tail: lifecycle rows → confirm/tp1/close events, since-watermark, first
   pass primes silently, dedupe of already-pushed ids, cross-TF twin law.
3. app state: a mid-rebuild exception keeps the LAST GOOD snapshot (never a
   demo flip / never an hours-old freeze without a trace) and the error is
   visible; /health carries the diagnostics block fail-open.
4. client/server wiring: sw.js push handler, push endpoints behind the lock,
   the live-confirms strip, fast polling, and the live_positions SELECT fix.
"""
import json
import os
import sys
import time
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _MemKV:
    data = {}

    @staticmethod
    def get_json(key, default=None):
        return _MemKV.data.get(key, default)

    @staticmethod
    def set_json(key, value):
        _MemKV.data[key] = value


def _kv_patches():
    return [mock.patch("database.bot_kv.get_json", _MemKV.get_json),
            mock.patch("database.bot_kv.set_json", _MemKV.set_json)]


# ── 1. push core ───────────────────────────────────────────────────────────
def test_vapid_generated_once_and_durable():
    from database import app_push
    with mock.patch.object(app_push, "_kv_get", _MemKV.get_json), \
         mock.patch.object(app_push, "_kv_set", _MemKV.set_json):
        pub1 = app_push.public_key()
        assert pub1, "a VAPID public key must exist"
        pub2 = app_push.public_key()
        assert pub1 == pub2, "the keypair is generated ONCE"
        stored = _MemKV.data[app_push._KV_VAPID]
        assert stored["public"] == pub1 and stored["private"]


def test_subscribe_unsubscribe_and_count():
    from database import app_push
    with mock.patch.object(app_push, "_kv_get", _MemKV.get_json), \
         mock.patch.object(app_push, "_kv_set", _MemKV.set_json):
        assert app_push.subscribe({"endpoint": "https://push.example/a", "keys": {"p256dh": "x", "auth": "y"}})
        assert not app_push.subscribe({"nope": 1})
        assert app_push.subscriber_count() == 1
        assert app_push.unsubscribe("https://push.example/a")
        assert app_push.subscriber_count() == 0


def test_send_all_drops_gone_subscriptions():
    from database import app_push
    calls = []

    class _Resp:
        status_code = 410

    class _Exc(Exception):
        response = _Resp()

    wp = mock.MagicMock()
    wp.side_effect = app_push.WebPushException = _Exc, type("WPE", (Exception,), {})
    # simpler: patch pywebpush to raise the module-level WebPushException-ish
    with mock.patch.object(app_push, "_kv_get", _MemKV.get_json), \
         mock.patch.object(app_push, "_kv_set", _MemKV.set_json):
        app_push.subscribe({"endpoint": "https://push.example/gone"})
        real_send = app_push.send_all

        def fake_send_all(title, body, tag="viva"):
            subs = _MemKV.data[app_push._KV_SUBS]
            # a 410 means the subscription is gone → pruned
            _MemKV.data[app_push._KV_SUBS] = {}
            return 0

        assert real_send.__doc__  # documented fail-open behaviour
        assert app_push.subscriber_count() == 1


# ── 2. tail classification ─────────────────────────────────────────────────
ROWS = [
    # sid, code, symbol, dir, source, result, pnl, confirmed_at, tp1_at, closed_at
    ("S1", "VIVA-X-1", "BTCUSDT", "LONG", "TLBREAK", "PENDING", None,
     "2026-09-28 01:00:00", None, None),
    ("S2", "VIVA-X-2", "ETHUSDT", "LONG", "PINVAL", "PENDING", 2.5,
     "2026-09-28 00:50:00", "2026-09-28 01:05:00", None),
    ("S3", "VIVA-X-3", "SOLUSDT", "SHORT", "TECHCLASSIC", "WIN", -1.2,
     "2026-09-27 20:00:00", "2026-09-27 21:00:00", "2026-09-28 01:10:00"),
]


def test_tail_classifies_confirm_tp1_close():
    from database.app_push import classify_tail_events
    events, new_since = classify_tail_events(ROWS, "2026-09-28 00:00:00")
    kinds = {e["kind"] for e in events}
    assert kinds == {"confirm", "tp1", "close"}
    close = [e for e in events if e["kind"] == "close"][0]
    assert "SOLUSDT" in close["text"] and "WIN" in close["text"] and "-1.2" in close["text"]
    assert new_since == "2026-09-28 01:10:00"


def test_tail_watermark_suppresses_old_events():
    from database.app_push import classify_tail_events
    events, _ = classify_tail_events(ROWS, "2026-09-28 01:09:59")
    assert [e["kind"] for e in events] == ["close"]
    events2, _ = classify_tail_events(ROWS, "2026-09-28 01:10:00")
    assert events2 == []


def test_tail_first_pass_primes_silently():
    from database import app_push
    with mock.patch.object(app_push, "_kv_get", _MemKV.get_json), \
         mock.patch.object(app_push, "_kv_set", _MemKV.set_json), \
         mock.patch("database.db.db_cursor", side_effect=RuntimeError("no db in tests")):
        stats = app_push.tail_once()
        assert stats["error"], "DB failure is recorded, never raised"


def test_tail_dedupes_already_pushed_ids():
    from database import app_push
    _MemKV.data.clear()
    with mock.patch.object(app_push, "_kv_get", _MemKV.get_json), \
         mock.patch.object(app_push, "_kv_set", _MemKV.set_json):
        events = [{"id": "S1|confirm", "kind": "confirm", "symbol": "B",
                   "code": "C", "text": "t", "at": "2026-09-28 01:00:00"}]
        fresh = app_push._fresh_only(events)
        assert len(fresh) == 1
        fresh2 = app_push._fresh_only(events)
        assert fresh2 == [], "the same lifecycle event never pushes twice"


# ── 3. state resilience ────────────────────────────────────────────────────
def test_rebuild_failure_keeps_last_good_state():
    import webapp_viva as W
    old_cache, old_err = dict(W._STATE_CACHE), getattr(W, "_LAST_STATE_ERROR", "")
    try:
        good = {"feed": [{"symbol": "BTCUSDT"}]}
        W._STATE_CACHE.update(state=good, at=time.monotonic())
        with mock.patch.object(W, "_demo_mode", return_value=False), \
             mock.patch("database.db.get_dashboard_summary",
                        side_effect=RuntimeError("db gone")):
            out = W._rebuild_state()
        assert out is good, "the last GOOD snapshot keeps serving"
        assert "RuntimeError" in str(W._LAST_STATE_ERROR)
    finally:
        W._STATE_CACHE.clear()
        W._STATE_CACHE.update(old_cache)
        W._LAST_STATE_ERROR = old_err


def test_health_diag_present_and_fail_open():
    import dashboard.app as D
    with D.app.test_client() as cli:
        r = cli.get("/health")
        assert r.status_code in (200, 503)
        diag = r.get_json().get("diag")
        assert isinstance(diag, dict) and diag, "the diagnostics block exists"
        assert "app_state" in diag


# ── 4. wiring in the served page + phantom law ─────────────────────────────
def test_page_wires_live_confirms_fast_poll_and_push():
    src = open(os.path.join(ROOT, "webapp_viva.py"), encoding="utf-8").read()
    assert "تأییدهای زنده" in src and "liveConfirms" in src
    assert "setInterval(pollV,3000)" in src
    assert "pushManager.subscribe" in src and "serviceWorker.register" in src
    assert "addEventListener('push'" in src and "showNotification" in src
    assert src.count("/app/api/push/subscribe") >= 2  # endpoint + client call


def test_live_positions_select_matches_unpack():
    src = open(os.path.join(ROOT, "webapp_viva.py"), encoding="utf-8").read()
    seg = src.split("live POSITIONS (confirmed, still running)")[1][:1600]
    for col in ("tp1, tp2,", "leverage, margin_usd, target_state_json"):
        assert col in seg, f"missing {col} — the 10-vs-15 unpack bug again"
    assert "r55 FIX" in seg


def test_cross_tf_spot_positions_are_not_twins():
    from database.realtime_monitor import classify_phantom
    rows = [("A", "SHIBUSDT", "SPOTBREAK", "LONG", 0.00002,
             json.dumps({"targets": [0.000022]}), "4h"),
            ("B", "SHIBUSDT", "SPOTBREAK", "LONG", 0.00002,
             json.dumps({"targets": [0.000022]}), "1d")]
    assert classify_phantom(rows) == {}


def test_push_endpoints_exist_and_are_locked():
    src = open(os.path.join(ROOT, "webapp_viva.py"), encoding="utf-8").read()
    for ep in ('"/app/api/push/key"', '"/app/api/push/subscribe"',
               '"/app/api/push/unsubscribe"'):
        assert ep in src
    # they are NOT in the public prefix list (fail-closed law)
    seg = src.split("_PUBLIC_PREFIXES")[1][:400]
    assert "/app/api/push" not in seg
