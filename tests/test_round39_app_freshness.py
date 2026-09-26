"""r39 — the app-freshness round (Viva 09-26 morning report).

His bugs, verbatim:
  «اپلیکیشن آپدیت نمیشه … کلا ۲۷ تا پوزیشن از اول وارد شده و دیگه آپدیت نمیشه»
     → the shell + /app/api/state responses are now Cache-Control: no-store,
       and the JS refreshes the moment the PWA is resumed.
  «عکس چارتم فقط برای تایید باید بیاد که اونهم نمیاد»
     → /app/api/chart is mirror-FIRST but now RENDERS as a fallback (the
       r33 identity/freeze laws make the re-render faithful); mirror-only
       404-ed every signal whose Telegram file_id mirror missed.
  About copy fixes: «لسانی» (not لساتی), «مالکیت تجاری ایده», the project is
  «در حال توسعه», and a formal bilingual disclaimer (no financial offer,
  user responsibility, no developer liability).
"""
from __future__ import annotations

import contextlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return open(os.path.join(REPO, "webapp_viva.py"), encoding="utf-8").read()


# ── 1. chart fallback render ─────────────────────────────────────────────
def test_chart_renders_as_fallback_when_mirror_misses(monkeypatch):
    import webapp_viva as W

    monkeypatch.setattr(W, "_demo_mode", lambda: False)
    monkeypatch.setattr(W, "_app_mirror", lambda sid, kind: None)

    row = ["viva-tech-T1", "PROOFUSDT", "TECHCLASSIC", "VIVA-TECHCLASSIC-T1",
           "{}", "LONG", 1.0, 0.985, 1.02, 1.04, 8, True, "4h", "DAYTRADE",
           "TECHCLASSIC", "2026-09-26 06:00", "2026-09-26 06:05", "تکنوکلاسیک"]

    class _Cur:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return row

    @contextlib.contextmanager
    def _fake_cursor():
        yield _Cur()

    import database.db as DB
    monkeypatch.setattr(DB, "db_cursor", _fake_cursor)

    import pandas as pd
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-09-25", periods=60, freq="1h"),
        "open": [1.0] * 60, "high": [1.01] * 60, "low": [0.99] * 60,
        "close": [1.0] * 60, "volume": [1000.0] * 60,
    })
    import data.fetcher as F
    monkeypatch.setattr(F, "get_klines", lambda *a, **k: df)

    import bot.messages_v7 as M
    monkeypatch.setattr(M, "generate_chart", lambda *a, **k: b"\x89PNG-fallback")

    W._CHART_CACHE.pop("viva-tech-T1", None)
    png = W._signal_chart_png("viva-tech-T1")
    assert png == b"\x89PNG-fallback"
    # and the render is cached for 30 min
    assert W._CHART_CACHE.get("viva-tech-T1")[0] == b"\x89PNG-fallback"


def test_chart_still_prefers_the_telegram_mirror(monkeypatch):
    import webapp_viva as W

    monkeypatch.setattr(W, "_demo_mode", lambda: False)
    monkeypatch.setattr(W, "_app_mirror", lambda sid, kind: {"fid": "FID-1"})
    monkeypatch.setattr(W, "_tg_file_bytes", lambda fid: b"\x89PNG-mirror")
    W._CHART_CACHE.pop("viva-mirror-1", None)
    assert W._signal_chart_png("viva-mirror-1") == b"\x89PNG-mirror"


def test_fallback_marks_spot_rows_log_scale(monkeypatch):
    """A spot row's fallback render must keep the r35/r37 spot laws."""
    src = _src()
    assert '"log_scale": True, "spot_measured_box": True, "engine": "SPOT"' in src
    assert "use_cache=True" in src and "190" in src


# ── 2. freshness: no-store + resume refresh ─────────────────────────────
def test_shell_and_state_are_no_store():
    os.environ["VIVA_APP_PASSWORD"] = "test-pass-123"
    import webapp_viva as W
    from flask import Flask
    app = Flask(__name__)
    W.install_viva_app(app)
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/app", follow_redirects=False)
    assert r.status_code in (200, 302)
    if r.status_code == 200:
        assert "no-store" in (r.headers.get("Cache-Control") or "")
    r2 = client.get("/app/login")
    assert "no-store" in (r2.headers.get("Cache-Control") or "")
    assert "no-store" in _src().split("def api_state")[1][:220]


def test_js_refreshes_on_resume():
    src = _src()
    assert "visibilitychange" in src and "pageshow" in src
    assert "setInterval(load,60000)" in src


# ── 3. About copy fixes ─────────────────────────────────────────────────
def test_surname_is_lesani_not_lesati():
    src = _src()
    assert "وحید لسانی" in src
    assert "لساتی" not in src


def test_ip_covers_the_idea_and_active_development():
    src = _src()
    assert "مالکیت تجاریِ ایده" in src
    assert "در حال توسعهٔ مداوم" in src
    assert "commercial ownership of the idea" in src
    assert "continuous development" in src


def test_formal_bilingual_disclaimer():
    src = _src()
    assert "سلب مسئولیت" in src
    assert "هیچ‌گونه پیشنهاد یا توصیهٔ مالی ارائه نمی‌شود" in src
    assert "کاملاً بر عهدهٔ کاربر است" in src
    assert "هیچ‌گونه مسئولیت حقوقی" in src
    assert "constitutes a financial offer, solicitation or investment advice" in src
    assert "entirely at the user's own responsibility" in src
    assert "assume no legal liability" in src
