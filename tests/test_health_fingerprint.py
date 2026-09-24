"""r27b: /health must expose the boot fingerprint (boot_sha/boot_at) so every
Railway deploy is verifiable from the public surface — «تأیید هر دیپلوی»."""
from __future__ import annotations

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_health_carries_boot_fingerprint(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "f895da7deadbeef1234")
    import dashboard.app as dash
    dash = importlib.reload(dash)          # env is read once at module boot
    client = dash.app.test_client()
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["boot_sha"].startswith("f895da7")
    assert body["boot_at"] and "T" in body["boot_at"]
    # legacy keys intact (Railway healthcheck + old clients)
    assert body["status"] == "ok" and body["confirmed_only"] is True
    assert "version" in body and "scanner_alive" in body


def test_boot_sha_falls_back_without_env(monkeypatch):
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("COMMIT_SHA", raising=False)
    import dashboard.app as dash
    dash = importlib.reload(dash)
    assert isinstance(dash._BOOT_SHA, str) and len(dash._BOOT_SHA) >= 7
