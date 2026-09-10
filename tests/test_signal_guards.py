"""Viva 2026-09-11 guards: no identical-point re-confirms; TC preview chain
uses ONE replaceable update that replies to the permanent anchor."""
import datetime as dt
import os
import sqlite3
import tempfile


# ── geometry duplicate ──────────────────────────────────────────────────────

def _fresh_sqlite(tmp):
    from database import db
    db.USE_POSTGRES = False
    db.DB_PATH = os.path.join(tmp, "signals.db")
    db.init_db()
    from database.repository_v7 import init_v7_schema   # adds confirmed_at et al
    init_v7_schema()
    return db


def _iso(offset_hours=0.0):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=offset_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_recent_geometry_duplicate_across_timeframes_and_states():
    from config import get_settings
    from database.repository_v7 import recent_geometry_duplicate
    sv = get_settings().strategy_version
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_sqlite(tmp)
        with db.db_cursor() as cur:
            cur.execute(
                "INSERT INTO signals (symbol, direction, entry, sl, tp1, confirmed, "
                "confirmed_at, status, result, signal_id, trigger_timeframe, strategy_version) "
                "VALUES (?,?,?,?,?,?,?, 'CONFIRMED','PENDING','sig-1','4h',?)",
                ("SOLUSDT", "LONG", 100.0, 98.0, 105.0, 1, _iso(-1), sv))
            cur.execute(
                "INSERT INTO signals (symbol, direction, entry, sl, tp1, confirmed, "
                "confirmed_at, status, result, signal_id, trigger_timeframe, strategy_version) "
                "VALUES (?,?,?,?,?,?,?, 'CONFIRMED','CLOSED','sig-2','1h',?)",
                ("XMRUSDT", "LONG", 100.0, 98.0, 105.0, 1, _iso(-30), sv))
        # (a) same points from the OTHER timeframe -> duplicate
        assert recent_geometry_duplicate("SOLUSDT", "LONG", 100.02, 98.01, 105.1) is True
        # (b) price moved to a new zone -> allowed
        assert recent_geometry_duplicate("SOLUSDT", "LONG", 104.0, 101.5, 110.0) is False
        # (c) same points, opposite direction -> not a dup
        assert recent_geometry_duplicate("SOLUSDT", "SHORT", 100.0, 98.0, 105.0) is False
        # (d) closed position in-window still blocks identical re-fires…
        with db.db_cursor() as cur:  # fresh copy of XMR case inside the window
            cur.execute(
                "INSERT INTO signals (symbol, direction, entry, sl, tp1, confirmed, "
                "confirmed_at, status, result, signal_id, trigger_timeframe, strategy_version) "
                "VALUES (?,?,?,?,?,?,?, 'CONFIRMED','CLOSED_TP1','sig-3','4h',?)",
                ("XMRUSDT", "LONG", 100.0, 98.0, 105.0, 1, _iso(-5), sv))
        assert recent_geometry_duplicate("XMRUSDT", "LONG", 100.05, 98.05, 105.2) is True
        # …but older than 24h the level is fair game again (new test round)
        assert recent_geometry_duplicate("XMRUSDT", "LONG", 100.0, 98.0, 105.0, hours=0.5) is False


# ── TECHCLASSIC anchor + replaceable update ─────────────────────────────────

def _fake_frame(n=150):
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2026-01-01", periods=n, freq="4h")
    close = 100 + np.cumsum(np.full(n, -0.05)) + np.sin(np.arange(n) / 7.0)
    df = pd.DataFrame({"open": close - 0.1, "high": close + 0.5, "low": close - 0.5,
                       "close": close, "volume": np.full(n, 900.0),
                       "turnover": np.full(n, 40000.0)}, index=idx)
    df["timestamp"] = [ts.isoformat() for ts in idx]
    return df


def test_tc_preview_anchor_update_lifecycle(monkeypatch):
    os.environ["CANDIDATE_DB_BACKEND"] = "sqlite"
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CANDIDATE_DB_PATH"] = os.path.join(tmp, "cand.db")
        import database.bot_kv as KV
        KV._TABLE_READY["done"] = False
        import data.fetcher as F
        monkeypatch.setattr(F, "get_klines", lambda *a, **k: _fake_frame())
        import bot.messages_v7 as M
        M.CHAT_ID_EXECUTION = "-100TEST"
        photos, texts, edits, edits_t = [], [], [], []
        counter = {"mid": 5000}

        def _send_photo(image, caption, chat_id=None, reply_to_message_id=None, reply_markup=None):
            counter["mid"] += 1
            photos.append((counter["mid"], caption, reply_to_message_id))
            return counter["mid"]

        def _send_message(text, chat_id=None, reply_to_message_id=None):
            counter["mid"] += 1
            texts.append((counter["mid"], text))
            return counter["mid"]

        def _edit_photo(mid, chat_id, image, caption):
            edits.append((mid, caption))
            return True

        def _edit_text(mid, chat_id, text):
            edits_t.append((mid, text))
            return True

        monkeypatch.setattr(M, "send_photo", _send_photo)
        monkeypatch.setattr(M, "send_message", _send_message)
        monkeypatch.setattr(M, "edit_chart_message", _edit_photo)
        monkeypatch.setattr(M, "edit_text_message", _edit_text)

        ev = {"symbol": "GTTSTUSDT", "pattern_tf": "4h", "state": "EDGE_NEAR",
              "pattern": "CHANNEL_DESCENDING", "pattern_fa": "کانال نزولی",
              "side": "lower", "direction": "SHORT", "line_price": 65.0, "live": 65.1,
              "distance_atr": 0.15, "touches": 3, "structure_score": 5,
              "reactions": {"touches": 3, "rejects": 3, "breaks": 0, "reject_rate": 1.0},
              "scenarios": {"hold": "پایداریِ کانال", "break": "شکست معتبر",
                            "prob": "هیچ‌کدام ۱۰٪ نیست"},
              "ref_ts": "2026-01-24T20:00:00"}
        fade = {"direction": "LONG", "entry": 65.1, "stop": 64.3, "tp_mid": 79.9,
                "target": 94.6, "rr": 25.0, "reject_rate": 1.0}

        assert M.send_technoclassic_preview(dict(ev)) is True
        assert len(photos) == 1 and photos[0][2] is None          # anchor: no reply
        anchor_mid = photos[0][0]
        link = KV.get_json("tc_link|GTTSTUSDT|4h", {})
        assert link.get("mid") == anchor_mid                      # confirmations → anchor
        code = photos[0][1].split("<code>")[1].split("</code>")[0]

        # same state again → silence (no channel spam)
        assert M.send_technoclassic_preview(dict(ev)) is False
        assert len(photos) == 1

        # state advances → ONE update, replied to the anchor
        ev2 = dict(ev, state="REJECTION_FADE", fade=fade)
        assert M.send_technoclassic_preview(ev2) is True
        assert len(photos) == 2 and photos[1][2] == anchor_mid
        upd_mid = photos[1][0]
        assert "🔁" in photos[1][1] and code in photos[1][1]       # same unique id

        # further advance → the update itself is EDITED, nothing new posted
        ev3 = dict(ev, state="BREAK_READY")
        assert M.send_technoclassic_preview(ev3) is True
        assert len(photos) == 2 and len(edits) == 1 and edits[0][0] == upd_mid
        chain = KV.get_json("tc_chain|GTTSTUSDT|4h", {})
        assert chain.get("anchor") == anchor_mid and chain.get("update") == upd_mid
        # the confirmation link still points at the ANCHOR, never at an update
        link = KV.get_json("tc_link|GTTSTUSDT|4h", {})
        assert link.get("mid") == anchor_mid
        assert link.get("state") == "BREAK_READY"
    os.environ.pop("CANDIDATE_DB_BACKEND", None)
    os.environ.pop("CANDIDATE_DB_PATH", None)
    KV._TABLE_READY["done"] = False
