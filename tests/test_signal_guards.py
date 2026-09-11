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
        M.CHAT_ID_EDUCATION = "-1004000000001"
        photos, texts, edits, edits_t = [], [], [], []
        counter = {"mid": 5000}

        def _send_photo(image, caption, chat_id=None, reply_to_message_id=None, reply_markup=None):
            counter["mid"] += 1
            photos.append((counter["mid"], caption, reply_to_message_id, chat_id, reply_markup))
            return counter["mid"]

        def _send_message(text, chat_id=None, reply_to_message_id=None):
            counter["mid"] += 1
            texts.append((counter["mid"], text))
            return counter["mid"]

        def _edit_photo(mid, chat_id, image, caption, reply_markup=None):
            edits.append((mid, caption, reply_markup))
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
        # family chain: detailed anchor in the ALERTS channel, PRO post linked to it
        assert len(photos) == 2
        edu_mid, pro_mid = photos[0][0], photos[1][0]
        assert photos[0][3] == "-1004000000001" and photos[1][3] == "-100TEST"
        assert photos[1][4] and "📚" in photos[1][4]["inline_keyboard"][0][0]["text"]
        assert str(edu_mid) in photos[1][4]["inline_keyboard"][0][0]["url"]
        assert photos[1][2] is None                                # PRO anchor: no reply
        link = KV.get_json("tc_link|GTTSTUSDT|4h", {})
        assert link.get("mid") == pro_mid                          # confirmations → PRO anchor
        code = photos[0][1].split("<code>")[1].split("</code>")[0]
        assert code in photos[1][1]                                 # same unique id, both channels

        # same state again → silence (no channel spam)
        assert M.send_technoclassic_preview(dict(ev)) is False
        assert len(photos) == 2

        # state advances → ONE update post, replied to the PRO anchor, button kept
        ev2 = dict(ev, state="REJECTION_FADE", fade=fade)
        assert M.send_technoclassic_preview(ev2) is True
        assert len(photos) == 3 and photos[2][2] == pro_mid
        assert photos[2][4] and str(edu_mid) in photos[2][4]["inline_keyboard"][0][0]["url"]
        upd_mid = photos[2][0]
        assert "🔁" in photos[2][1] and code in photos[2][1]         # same unique id

        # further advance → the update itself is EDITED, nothing new posted
        ev3 = dict(ev, state="BREAK_READY")
        assert M.send_technoclassic_preview(ev3) is True
        assert len(photos) == 3 and len(edits) == 1 and edits[0][0] == upd_mid
        assert edits[0][2] and str(edu_mid) in edits[0][2]["inline_keyboard"][0][0]["url"]
        chain = KV.get_json("tc_chain|GTTSTUSDT|4h", {})
        assert chain.get("anchor") == pro_mid and chain.get("update") == upd_mid
        assert chain.get("edu") == edu_mid
        # the confirmation link still points at the PRO anchor, never at an update
        link = KV.get_json("tc_link|GTTSTUSDT|4h", {})
        assert link.get("mid") == pro_mid
        assert link.get("state") == "BREAK_READY"
    os.environ.pop("CANDIDATE_DB_BACKEND", None)
    os.environ.pop("CANDIDATE_DB_PATH", None)
    KV._TABLE_READY["done"] = False


def test_family_block_template_everywhere():
    """Viva 2026-09-11: every message family uses the SAME block template —
    🏷 badge, ━ rules between logical blocks, bold section titles, 🆔 last."""
    from bot.messages_v7 import VIVA_SEP, _approaching_caption
    from test_v7 import make_candidate
    cap = _approaching_caption(make_candidate(), 99.7, 0.31)
    assert cap.count(VIVA_SEP) >= 4                      # blocks separated
    for needle in ("🏷 <b>VIVA ✦", "⚡ <b>هشدار نهایی", "🪙 <b>BTCUSDT</b>",
                   "🕓 <b>زمان رصد — ایران:</b>", "📨 <b>زمان ارسال — ایران:</b>",
                   "🎯 <b>", "🤖 <b>نظر AI:</b>", "📍 <b>زون:</b>", "💲 <b>قیمت:</b>",
                   "⚖️ <b>در انتظار کلوز تأییدی", "🚩 <b>فاصله:</b> 0.31 ATR",
                   "🛑 <b>ابطال:</b>", "🆔 <code>"):
        assert needle in cap, needle
