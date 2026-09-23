"""Round-17: the VIVA mobile app (PWA) — lock, control gate, PWA assets.

Viva 09-23: «همه قسمت‌هایی که به کانال‌های تلگرام میره … و بتونم کنترلش بکنم
… داشبورد وین‌ریت هر ستاپ».
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("VIVA_APP_PASSWORD", "test-pass-123")
    import webapp_viva
    flask_app = Flask(__name__)
    webapp_viva.install_viva_app(flask_app)
    flask_app.config["TESTING"] = True
    return flask_app


def test_locked_without_password_and_open_health(app):
    client = app.test_client()
    # health stays public (Railway liveness) — NOT redirected by the lock
    assert client.get("/health").status_code != 302
    # everything else redirects to the login page
    r = client.get("/app")
    assert r.status_code == 302 and "/app/login" in r.headers["Location"]
    r2 = client.get("/api/strategies")
    assert r2.status_code == 302  # the classic dashboard is behind the lock too


def test_login_flow_sets_session(app):
    client = app.test_client()
    bad = client.post("/app/api/login", json={"password": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/app/api/login", json={"password": "test-pass-123"})
    assert ok.status_code == 200 and "viva_session" in (ok.headers.get("Set-Cookie") or "")
    page = client.get("/app")
    assert page.status_code == 200 and "VIVA SIGNALS PRO".encode() in page.data
    assert client.get("/app/api/state").status_code == 200
    # with the cookie the lock no longer redirects
    assert client.get("/api/strategies").status_code != 302


def test_state_and_control_roundtrip(app, monkeypatch):
    import webapp_viva
    monkeypatch.setattr(webapp_viva, "save_control",
                        lambda paused=None, setups=None: {"paused": bool(paused),
                                                          "setups": setups or {}, "updated_at": "x"})
    client = app.test_client()
    client.post("/app/api/login", json={"password": "test-pass-123"})
    assert client.get("/app/api/state").status_code == 200
    r = client.post("/app/api/control", json={"paused": True})
    assert r.status_code == 200 and r.get_json()["control"]["paused"] is True


def test_pwa_assets_are_public():
    from webapp_viva import _PUBLIC_PREFIXES
    joined = tuple(_PUBLIC_PREFIXES)
    assert "/app/manifest.webmanifest" in joined and "/app/sw.js" in joined
    assert "/health" in joined


def test_publish_allowed_fail_open_and_gate(monkeypatch):
    import webapp_viva

    class C:
        setup_code = "TLBREAK"
        source = "TLBREAK"

    # KV broken → fail-open
    def _boom(key, default=None):
        raise RuntimeError("db down")
    monkeypatch.setattr("database.bot_kv.get_json", _boom)
    assert webapp_viva.publish_allowed(C()) is True

    # paused → nothing publishes
    monkeypatch.setattr("database.bot_kv.get_json",
                        lambda key, default=None: {"paused": True, "setups": {}})
    webapp_viva._CTRL_CACHE["at"] = 0.0
    assert webapp_viva.publish_allowed(C()) is False

    # setup disabled → only that setup is gated
    monkeypatch.setattr("database.bot_kv.get_json",
                        lambda key, default=None: {"paused": False, "setups": {"TLBREAK": False}})
    webapp_viva._CTRL_CACHE["at"] = 0.0
    assert webapp_viva.publish_allowed(C()) is False

    class C2:
        setup_code = "ALBROX"
        source = "ALBROX"
    assert webapp_viva.publish_allowed(C2()) is True

    # scanner source gate honours the scanner main.py insertion
    src = open("main.py", encoding="utf-8").read()
    assert "from webapp_viva import publish_allowed" in src
