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

        def _send_message(text, chat_id=None, reply_to_message_id=None, reply_markup=None):
            counter["mid"] += 1
            texts.append((counter["mid"], text, reply_to_message_id))
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
        # Viva 2026-09-12 format law, now enforced on the TECHCLASSIC preview
        # channel too: registry-unique T-code + the exact detailed skeleton.
        import re as _re
        assert _re.fullmatch(r"VIVA-TECLASSIC-T\d{6}", code), code
        _hdr = photos[0][1].split("\n")
        assert _hdr[0] == "🏷 <b>VIVA-TECLASSIC</b>"
        assert _hdr[1].startswith("🆔 <code>") and _hdr[2] == M.VIVA_SEP
        for _need in ("📚 <b>تحلیل آموزشی | ستاپ در حال بررسی</b>",
                      "⛔ <b>این پیام تأیید ورود نیست</b>",
                      "👀 فقط برای رصد بازار و اهداف آموزشی",
                      "🪙 <b>GTTSTUSDT</b>  •  SWING  •  4H",
                      "🔎 <b>ناحیه،ای که زیر نظر داریم</b>" if False else "🔎 <b>ناحیه‌ای که زیر نظر داریم</b>",
                      "⛔ ورود، اهرم و حجم پوزیشن هنوز پیشنهاد نمی‌شود"):
            assert _need in photos[0][1], _need
        assert "🧠" not in photos[0][1] and "⚡ <b>هشدار الگو" not in photos[0][1]

        # same state again → silence (no channel spam)
        assert M.send_technoclassic_preview(dict(ev)) is False
        assert len(photos) == 2

        # state advances → a NEW numbered update post, replying to the anchor;
        # the superseded message is deleted (Viva 2026-09-12 latest-update law)
        deletes = []
        monkeypatch.setattr(M, "delete_message", lambda chat, mid: deletes.append(int(mid)) or True)
        ev2 = dict(ev, state="REJECTION_FADE", fade=fade)
        assert M.send_technoclassic_preview(ev2) is True
        assert len(edits) == 0 and len(photos) == 3              # never edited, always appended
        upd1 = photos[2]
        assert upd1[3] == "-1004000000001" and upd1[2] == edu_mid   # updates post in the ALERTS channel, under the detail — never main
        assert "\U0001f501" in upd1[1] and "\u0622\u067e\u062f\u06cc\u062a \u06f1" in upd1[1]   # «آخرین آپدیت • آپدیت ۱»
        assert "\U0001fa99" in upd1[1] and "\u2696\ufe0f" in upd1[1]                # shared update layout with every other setup
        assert code in upd1[1]                                    # same unique id
        assert upd1[4] and str(edu_mid) in upd1[4]["inline_keyboard"][0][0]["url"]
        assert pro_mid not in deletes                             # anchor is PERMANENT
        chain = KV.get_json("tc_chain|GTTSTUSDT|4h", {})
        assert chain.get("update") == upd1[0] and chain.get("upd_n") == 1
        # alerts channel also received the compact copy replying to the detail
        compacts = [t for t in texts if "📚 <b>تحلیل آموزشی" in t[1]]
        assert compacts and code in compacts[0][1] and compacts[0][2] == edu_mid

        # further advance → update ۲ lands as the newest message, update ۱ is DELETED
        ev3 = dict(ev, state="BREAK_READY")
        assert M.send_technoclassic_preview(ev3) is True
        assert len(photos) == 4 and len(edits) == 0
        upd2 = photos[3]
        assert upd2[2] == edu_mid and upd2[3] == "-1004000000001" and "آپدیت ۲" in upd2[1]
        assert deletes == [upd1[0]]                               # only the superseded one, never the anchor
        assert upd2[4] and str(edu_mid) in upd2[4]["inline_keyboard"][0][0]["url"]
        chain = KV.get_json("tc_chain|GTTSTUSDT|4h", {})
        assert chain.get("anchor") == pro_mid and chain.get("update") == upd2[0]
        assert chain.get("edu") == edu_mid and chain.get("upd_n") == 2
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


def test_setup_chain_final_doctrine(monkeypatch):
    """Viva 2026-09-11 FINAL doctrine, verbatim-implemented:
    • education = detailed (permanent, charted) + ONE compact reply — BOTH in
      the alerts channel; the main channel receives NOTHING at this stage
      («عالمه پیام هشدار بدون چارت اومده به کانال اصلی» must be impossible).
    • updates = ONE self-editing message in the alerts channel, reply-linked to
      the detailed, AI opinion inside «تأییدهای کمکی».
    • PRO receives only the final alert (⚡ label) — the Confirmed REPLACES that
      same message in place and keeps the 📚 link to the detailed alert."""
    os.environ["CANDIDATE_DB_BACKEND"] = "sqlite"
    import tempfile as _tf
    import pandas as pd
    with _tf.TemporaryDirectory() as tmp:
        os.environ["CANDIDATE_DB_PATH"] = os.path.join(tmp, "cand.db")
        import database.bot_kv as KV
        KV._TABLE_READY["done"] = False
        import bot.messages_v7 as M
        from test_v7 import make_candidate
        cand = make_candidate()
        cand.metadata["public_code"] = "VIVA-TLBREAK-K000001"
        M.CHAT_ID_EDUCATION = "-1004000000001"
        M.CHAT_ID_EXECUTION = "-100TEST"
        texts, edits_t, edits_c = [], [], []
        counter = {"mid": 900}

        def _send_message(text, chat_id=None, reply_to_message_id=None, reply_markup=None):
            counter["mid"] += 1
            texts.append((counter["mid"], text, chat_id, reply_to_message_id, reply_markup))
            return counter["mid"]

        def _send_photo(image, caption, chat_id=None, reply_to_message_id=None, reply_markup=None):
            counter["mid"] += 1
            texts.append((counter["mid"], caption, chat_id, reply_to_message_id, reply_markup))
            return counter["mid"]

        monkeypatch.setattr(M, "send_message", _send_message)
        monkeypatch.setattr(M, "send_photo", _send_photo)
        monkeypatch.setattr(M, "edit_text_message", lambda mid, chat_id, text: edits_t.append((mid, text)) or True)
        monkeypatch.setattr(M, "edit_chart_message",
                            lambda mid, chat_id, image, caption, reply_markup=None: edits_c.append((mid, caption, reply_markup)) or True)
        monkeypatch.setattr(M, "build_educational_message", lambda c: "DETAILED-MSG")
        monkeypatch.setattr(M, "generate_chart", lambda *a, **k: b"IMG")
        monkeypatch.setattr(M, "send_signal_separator", lambda *a, **k: None)
        import database.candidate_store as CS
        monkeypatch.setattr(CS, "update_candidate", lambda *a, **k: None)

        assert M.send_educational_setup(cand, None) is True
        edu_mid = [t for t in texts if t[1] == "DETAILED-MSG"][0][0]
        compacts = [t for t in texts if "📚 <b>تحلیل آموزشی" in t[1]]
        assert len(compacts) == 1 and compacts[0][2] == M.CHAT_ID_EDUCATION
        assert compacts[0][3] == edu_mid                       # compact replies to the detail
        assert "🏷 <b>VIVA ✦" in compacts[0][1]                  # main-channel labels restored
        assert not any(t[2] == M.CHAT_ID_EXECUTION for t in texts)   # no PRO watch post at all
        chain = KV.get_json("setup_chain|VIVA-TLBREAK-K000001", {})
        assert chain.get("edu") == edu_mid and not chain.get("pro")

        # deterministic: the update's self-fetch must not hit the network
        import data.fetcher as F
        monkeypatch.setattr(F, "get_klines", lambda *a, **k: None)
        # Viva 2026-09-12 latest-update law for EVERY setup: the update is a
        # NEW numbered post linked to the detail; the previous update gets
        # deleted. In-place editing of the alerts channel is dead.
        deletes_u = []
        monkeypatch.setattr(M, "delete_message", lambda chat, mid: deletes_u.append(int(mid)) or True)
        assert M.send_setup_update(cand, None, note_fa="ناحیه جابه‌جا شد") is True
        upd = [t for t in texts if "به‌روزرسانی رصد" in t[1]][0]
        assert upd[2] == M.CHAT_ID_EDUCATION and upd[3] == edu_mid
        assert "🔁 <b>آخرین آپدیت • آپدیت ۱</b>" in upd[1]
        assert "🧩 <b>تأییدهای کمکی</b>" in upd[1] and "🤖" in upd[1]
        assert "ناحیه جابه‌جا شد" in upd[1]
        chain = KV.get_json("setup_chain|VIVA-TLBREAK-K000001", {})
        assert chain.get("upd") == upd[0] and chain.get("upd_n") == 1
        assert not edits_t and not deletes_u                       # first update: nothing to delete
        assert M.send_setup_update(cand, None, note_fa="ادامه") is True
        ups = [t for t in texts if "به‌روزرسانی رصد" in t[1]]
        assert len(ups) == 2 and "آپدیت ۲" in ups[1][1]        # numbered, appended
        assert deletes_u == [upd[0]] and ups[1][3] == edu_mid       # old one deleted, new replies to detail
        assert not edits_t                                           # NEVER edited in place

        # with a live frame available the new post carries a fresh chart too
        import pandas as _pd
        frame_ok = _pd.DataFrame({"open": [99.0]*40, "high": [99.5]*40, "low": [98.5]*40,
                                  "close": [99.1]*40, "volume": [10.0]*40},
                                 index=_pd.date_range("2026-09-11", periods=40, freq="15min"))
        monkeypatch.setattr(F, "get_klines", lambda *a, **k: frame_ok)
        assert M.send_setup_update(cand, None, note_fa="چارت زنده") is True
        last_up = [t for t in texts if "چارت زنده" in t[1]][-1]
        assert "آپدیت ۳" in last_up[1] and not edits_c
        assert deletes_u == [upd[0], ups[1][0]]

        # final alert → new PRO post (no education slot exists)
        assert M.send_approaching(cand, 99.7, 0.31) is True
        final = [t for t in texts if t[2] == M.CHAT_ID_EXECUTION and "⚡ <b>هشدار نهایی" in t[1]][0]
        chain = KV.get_json("setup_chain|VIVA-TLBREAK-K000001", {})
        assert chain.get("pro") == final[0]

        # confirmed REPLACES the final-alert slot in place, linked to the detail
        frame = pd.DataFrame({"open": [99.0], "high": [100.0], "low": [98.8],
                              "close": [99.6], "volume": [10.0]},
                             index=pd.date_range("2026-09-11", periods=1, freq="15min"))
        cand.metadata.pop("confirmation_chart_sent", None)
        cand.metadata.pop("confirmation_chart_message_id", None)
        cand.metadata["target_ladder"] = {"targets": [102.0, 105.0], "weights": [35, 35]}
        assert M.send_confirmed(cand, frame) is True
        assert edits_c and edits_c[-1][0] == final[0]
        assert "✅ <b>سیگنال تأییدشده</b>" in edits_c[-1][1]
        assert edits_c[-1][2] and "📚" in str(edits_c[-1][2])
        assert cand.metadata["confirmation_chart_message_id"] == final[0]
    os.environ.pop("CANDIDATE_DB_BACKEND", None)
    os.environ.pop("CANDIDATE_DB_PATH", None)
    KV._TABLE_READY["done"] = False


def test_rotating_licences_one_chain_per_setup(monkeypatch):
    """Viva 2026-09-11 («نقش نوبتی»): while one chain of a (symbol, setup) pair
    is unresolved, a newer detection must NOT open a second alert — it refreshes
    the live chain and returns the zone-follow note for the update slot. A moved
    zone (>0.30 ATR) re-arms Approaching. Different setups stay independent."""
    os.environ["CANDIDATE_DB_BACKEND"] = "sqlite"
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        os.environ["CANDIDATE_DB_PATH"] = os.path.join(tmp, "lic.db")
        from database.candidate_store import (add_candidate, open_chains_for,
                                              absorb_update_into_chain, chains_last_24h,
                                              init_candidate_store)
        init_candidate_store()
        from test_v7 import make_candidate
        holder = make_candidate()
        holder.signal_id = "viva-holder-1"
        holder.status = "EDUCATIONAL"
        assert add_candidate(holder) is True
        fresh = make_candidate()
        fresh.signal_id = "viva-fresh-2"
        fresh.entry_zone_bottom, fresh.entry_zone_top = 105.0, 105.6   # moved ~6 ATR
        fresh.planned_entry, fresh.sl, fresh.tp1, fresh.tp2 = 105.3, 103.0, 115.0, 122.0
        fresh.score = 8
        live = [c for c in open_chains_for(fresh.symbol, fresh.setup_code) if c.signal_id != fresh.signal_id]
        assert len(live) == 1 and live[0].signal_id == "viva-holder-1"   # the gate fires
        note = absorb_update_into_chain(live[0], fresh)
        assert "جابه‌جا شد" in note
        refreshed = open_chains_for(fresh.symbol, fresh.setup_code)[0]
        assert abs(refreshed.entry_zone_bottom - 105.0) < 1e-9           # holder followed
        assert refreshed.metadata.get("public_code") == holder.metadata.get("public_code")
        assert int(refreshed.metadata.get("absorbed_scans") or 0) >= 1
        assert chains_last_24h(fresh.symbol, fresh.setup_code) >= 1      # licence counter
        assert chains_last_24h(fresh.symbol, "NOSUCHSETUP") == 0         # per-setup isolation
    os.environ.pop("CANDIDATE_DB_BACKEND", None)
    os.environ.pop("CANDIDATE_DB_PATH", None)


def test_same_zone_quiet_for_24h():
    """«دیگه واسه یک ارز در یک ناحیه مشخص هی پیام مفصل و مختصر نیاد هر روز» —
    a zone this symbol+setup watched within 24h is silent even after the chain
    resolved; only a genuinely new zone may open the next licence."""
    os.environ["CANDIDATE_DB_BACKEND"] = "sqlite"
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        os.environ["CANDIDATE_DB_PATH"] = os.path.join(tmp, "quiet.db")
        from database.candidate_store import (add_candidate, init_candidate_store,
                                              recent_lineage_zone, update_candidate)
        from test_v7 import make_candidate
        init_candidate_store()
        first = make_candidate()
        first.signal_id = "viva-quiet-1"
        assert add_candidate(first) is True
        update_candidate(first, "CANCELLED")           # chain ended, still within 24h
        near = make_candidate()
        near.signal_id = "viva-quiet-2"
        near.entry_zone_bottom, near.entry_zone_top = first.entry_zone_bottom + 0.01, first.entry_zone_top + 0.01
        assert recent_lineage_zone(near.symbol, near.setup_code, float(near.zone_mid), 0.2) is not None
        far = make_candidate()
        far.signal_id = "viva-quiet-3"
        far.entry_zone_bottom, far.entry_zone_top = first.entry_zone_top + 6.0, first.entry_zone_top + 6.6
        assert recent_lineage_zone(far.symbol, far.setup_code, float(far.zone_mid), 0.2) is None
    os.environ.pop("CANDIDATE_DB_BACKEND", None)
    os.environ.pop("CANDIDATE_DB_PATH", None)


def test_viva_exact_format_detailed_and_compact():
    """Viva 2026-09-12, his samples VERBATIM: detailed alert = 🏷 badge, 🆔 on
    the second line (same as hit messages), educational block, SYMBOL • STYLE •
    TF line, ━━━ between every concept to the end; compact alert follows the
    second sample exactly. No English word may START a title; no 🧠 inventions."""
    import bot.messages_v7 as M
    from test_v7 import make_candidate
    c = make_candidate()
    c.setup_code = "TLBREAK"
    c.metadata["confirm_tf"] = "15m"
    from analysis.models import EvidenceItem
    _titles = ["ساختار و موقعیت تایم‌فریم بالاتر", "شکست ساختار و Displacement", "ناحیه ورود و Freshness", "اهداف ساختاری و نسبت سود به زیان", "نقدشوندگی و شرایط بازار", "شکست ساختاری - VIVA-TLBREAK"]
    _keys = ["htf", "displacement", "poi", "rr", "market", "viva"]
    c.evidence = [EvidenceItem(k, t, "جزئیات نمونه.", i % 2 == 0, 2)
                  for i, (k, t) in enumerate(zip(_keys, _titles))]
    msg = M.build_educational_message(c)
    lines = [ln for ln in msg.split("\n")]
    assert lines[0].startswith("🏷 <b>VIVA-TLBREAK</b>")
    nonempty = [ln for ln in lines if ln.strip()]
    assert nonempty[1].startswith("🆔 <code>")          # id right under the badge
    assert lines[1].startswith("🆔 <code>") and lines[2].startswith("━")  # id directly under badge, separator next
    assert "🎯 ستاپ: <b>VIVA-TLBREAK</b> |" in msg
    assert "📚 <b>تحلیل آموزشی | ستاپ در حال بررسی</b>" in msg
    assert "⛔ <b>این پیام تأیید ورود نیست</b>" in msg
    _sym_ln = msg.split("🪙")[1].split("\n")[0]
    assert "<b>BTCUSDT</b>" in _sym_ln and "SWING" in _sym_ln and "15M" in _sym_ln  # TF beside symbol
    assert "🧠" not in msg                                      # no invented sections
    assert "⛔ ورود، اهرم و حجم پوزیشن هنوز پیشنهاد نمی‌شود" in msg
    assert "⛔ Entry،" not in msg                               # English-first lines banned
    assert msg.count("━━━━━━━━") >= 6                           # separators to the end
    # every bold section title is Persian-first (emoji, then Persian, English allowed later)
    for title in _titles:

        assert f"<b>{title}</b>" in msg, title

    cap = M._compact_alert_caption(c)
    assert cap.split("\n")[0].startswith("🏷 <b>VIVA ✦ TLBREAK</b>")
    assert "🪙 <b>BTCUSDT</b>  •  SWING  •  15M" in cap
    assert "⭐ امتیاز فعلی: 6/10\n🆔 <code>" in cap or "🆔" in cap.split("⭐ امتیاز فعلی")[1][:60]
    assert "کلوز معتبر ۱۵ دقیقه" in cap                        # Persian TF name, no gap
    assert "⛔ Entry،" not in cap and "⛔ ورود، اهرم" in cap
    assert "📢 VivaMon Labs Pro" in cap

    ap = M._approaching_caption(c, 99.6, 0.31)
    _ap_ln = ap.split("🪙")[1].split("\n")[0]
    assert "BTCUSDT" in _ap_ln and "15M" in _ap_ln       # TF beside the symbol


def test_teclassic_public_code_family():
    """«VIVA-TECLASSIC-T000000» — the zeros become unique digits; own letter for
    TechnoClassic, K stays for the rest."""
    import re
    from analysis.models import generate_viva_public_code
    tc = generate_viva_public_code("TECHCLASSIC", "SWING")
    assert re.fullmatch(r"VIVA-TECLASSIC-T\d{6}", tc), tc
    digits = tc.rsplit("T", 1)[1]
    assert len(set(digits)) >= 2          # never a uniform block
    tlb = generate_viva_public_code("TLBREAK", "SWING")
    assert re.fullmatch(r"VIVA-TLBREAK-K\d{6}", tlb), tlb


def test_s6_fast_confirm_survives_later_ticks():
    """The bug that killed runaways: the fast lane marked S6, a same-tick RR/
    chase rejection threw the chain back, and every later tick froze in
    WAIT_S6_CONFIRMED. The one-close verdict must now persist while the
    scenario is not invalidated."""
    import pandas as pd
    from datetime import datetime, timedelta, timezone
    from test_v7 import make_candidate
    from analysis.quality_engine import evaluate_confirmation
    t0 = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(32):
        base = 98.0 if i < 28 else 100.2
        rows.append({"timestamp": t0 + timedelta(minutes=15 * i), "open": base - 0.02,
                     "high": base + 0.05, "low": base - 0.10, "close": base, "volume": 1000.0})
    df = pd.DataFrame(rows).set_index("timestamp")
    df.index.name = "timestamp"
    df["timestamp"] = df.index
    cand = make_candidate()
    cand.setup_code = "TLBREAK"
    cand.status = "NEAR_CONFIRM"
    cand.entry_zone_bottom, cand.entry_zone_top = 99.8, 100.2
    cand.planned_entry, cand.sl = 100.1, 98.6
    cand.tp1, cand.tp2 = 106.0, 109.0
    cand.created_at = (t0 + timedelta(minutes=15 * 27)).isoformat()
    cand.metadata.update({
        "strategy_variant": "VIVA_TLBREAK", "viva_breakout_line": 100.0, "atr": 1.0,
        "confirm_tf": "15m", "touched": True, "viva_state": "S6_CONFIRMED",
        "viva_state_machine": {"stage": "S6_CONFIRMED"},
    })
    ok, _c, reason = evaluate_confirmation(cand, df)
    assert ok is True, f"S6 chain must stay confirmable: {reason}"
    # invalidation still owns the kill switch: a LONG whose close breaks BELOW
    # the SL must never confirm, S6 or not
    df2 = df.copy()
    df2.loc[df2.index[-1], ["close", "open", "low"]] = [98.0, 98.4, 97.8]
    cand2 = make_candidate()
    cand2.setup_code = "TLBREAK"
    cand2.status = "NEAR_CONFIRM"
    cand2.entry_zone_bottom, cand2.entry_zone_top = 99.8, 100.2
    cand2.planned_entry, cand2.sl = 100.1, 98.6
    cand2.tp1, cand2.tp2 = 106.0, 109.0
    cand2.created_at = cand.created_at
    cand2.metadata.update(dict(cand.metadata, viva_state="S6_CONFIRMED"))
    ok2, _c3, why2 = evaluate_confirmation(cand2, df2)
    assert ok2 is False and "ابطال" in (why2 or "") or "INVALIDATION" in str(
        cand2.metadata.get("last_reject_code") or "")


def test_fast_break_followthrough_confirms_without_retest():
    """Viva 2026-09-11: BTCUSDT/CRVUSDT burn case — price breaks the fitted
    line and RUNS. Two consecutive closes beyond the line with displacement
    must confirm via the FAST lane even though the zone was never retested,
    and RETEST_WINDOW_EXPIRED must no longer veto it."""
    import pandas as pd
    from datetime import datetime, timedelta, timezone
    from test_v7 import make_candidate
    from analysis.quality_engine import evaluate_confirmation

    cand = make_candidate()
    cand.status = "NEAR_CONFIRM"
    cand.entry_zone_bottom, cand.entry_zone_top = 99.8, 100.2
    cand.planned_entry, cand.sl = 100.1, 98.5
    cand.tp1, cand.tp2 = 106.0, 109.0
    cand.metadata.update({
        "strategy_variant": "VIVA_TLBREAK",
        "viva_breakout_line": 100.0, "atr": 1.0,
        "viva_state_machine": {"stage": "S2_BREAKOUT"},
        "structure_level": 100.0,
    })
    ts = pd.date_range("2026-09-10 12:00", periods=30, freq="15min")
    closes = [98.0] * 24 + [99.0, 99.6, 100.3, 100.6, 100.5, 100.75]
    opens = [c - 0.15 for c in closes[:26]] + [99.75, 100.1, 100.35, 100.3]
    highs = [c + 0.2 for c in closes[:26]] + [99.95, 100.45, 100.7, 100.95]
    lows = [c - 0.3 for c in closes[:26]] + [99.55, 99.8, 100.2, 100.15]
    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": [1000.0] * 30,
    }, index=ts)
    df.index.name = "timestamp"
    df["timestamp"] = df.index
    # candidate born two closes after the break: the FOLLOW-THROUGH confirms it
    cand.created_at = (ts[-3]).isoformat()
    cand.metadata["created_at"] = cand.created_at
    ok, cand2, reason = evaluate_confirmation(cand, df)
    assert ok is True, f"expected fast-lane confirm, got: {reason}"
    assert cand2.metadata.get("tl_fast_break")
    # either the fast lane itself (S6) or the alt-cluster fast path (S5) may
    # carry the confirmation — both are legitimate, NO_TOUCH never vetoes here
    assert cand2.metadata.get("viva_state") in {"S5_MICRO_BOS", "S6_CONFIRMED"}

    # …and without the two closes beyond the line the lane must NOT fire
    cand_slow = make_candidate()
    cand_slow.status = "NEAR_CONFIRM"
    cand_slow.entry_zone_bottom, cand_slow.entry_zone_top = 99.8, 100.2
    cand_slow.planned_entry, cand_slow.sl = 100.1, 98.5
    cand_slow.tp1, cand_slow.tp2 = 106.0, 109.0
    cand_slow.metadata.update({
        "strategy_variant": "VIVA_TLBREAK",
        "viva_breakout_line": 100.0, "atr": 1.0,
        "viva_state_machine": {"stage": "S2_BREAKOUT"},
        "structure_level": 100.0,
    })
    flat = [98.0] * 26 + [99.2, 99.0, 99.1, 99.3]
    df_flat = df.copy()
    df_flat["close"] = flat
    cand_slow.created_at = (ts[-3]).isoformat()
    cand_slow.metadata["created_at"] = cand_slow.created_at
    ok2, _, reason2 = evaluate_confirmation(cand_slow, df_flat)
    assert ok2 is False  # no touch of the zone, no follow-through → still gated


def test_confirmation_ladder_one_step_below_pattern():
    """Viva 2026-09-11 ladder: 1D→4H, 4H→1H, 1H→15m, 15m→5m, 5m→1m."""
    from analysis.setups_v7 import confirm_timeframe_for_pattern as f
    assert f("1d", "SWING", "4h") == "4h"
    assert f("4h", "SWING", "15m") == "1h"
    assert f("1H", "DAYTRADE", "15m") == "15m"
    assert f("15m", "DAYTRADE", "5m") == "5m"
    assert f("5m", "SCALP", "1m") == "1m"
    # unknown pattern TF falls back to the legacy trigger grid, never crashes
    assert f("", "SCALP", "15m") == "5m"


def test_single_close_confirms_fast_lane():
    """ONE valid close on the confirm TF past the line = confirmed (Viva rule);
    a doji-thin close beyond the line is not enough (0.25 ATR body)."""
    import pandas as pd
    from test_v7 import make_candidate
    from analysis.quality_engine import evaluate_confirmation
    ts = pd.date_range("2026-09-10 12:00", periods=30, freq="15min")
    closes = [98.0] * 29 + [100.4]
    opens = [c - 0.1 for c in closes]
    opens[-1] = 100.0
    df = pd.DataFrame({
        "open": opens, "high": [c + 0.05 for c in closes],
        "low": [c - 0.2 for c in closes], "close": closes,
        "volume": [1000.0] * 30,
    }, index=ts)
    df.index.name = "timestamp"
    df["timestamp"] = df.index
    # the single post-creation candle never dips into the zone (low > zone top):
    # only the FAST lane can confirm it — and per Viva's rule it must.
    df.loc[df.index[-1], "low"] = 100.25

    def _cand():
        c = make_candidate()
        c.status = "NEAR_CONFIRM"
        c.entry_zone_bottom, c.entry_zone_top = 99.8, 100.2
        c.planned_entry, c.sl = 100.1, 98.6
        c.tp1, c.tp2 = 106.0, 109.0
        c.metadata.update({"strategy_variant": "VIVA_TLBREAK", "viva_breakout_line": 100.0,
                           "atr": 1.0, "confirm_tf": "15m",
                           "viva_state_machine": {"stage": "S2_BREAKOUT"}})
        c.created_at = (ts[-1]).isoformat()
        c.metadata["created_at"] = c.created_at
        return c

    ok, c2, reason = evaluate_confirmation(_cand(), df)
    assert ok is True, f"single valid close must confirm: {reason}"
    assert c2.metadata.get("tl_fast_break")

    # no breakout close at all: a thin doji drifting below the line → must not
    # confirm (the alt-cluster RECLAIM lane is also kept honest this way)
    weak = df.copy()
    weak.loc[weak.index[-2], ["close", "open", "high", "low"]] = [99.85, 99.80, 99.90, 99.75]
    weak.loc[weak.index[-1], ["close", "open", "high", "low"]] = [99.90, 99.88, 99.98, 99.80]
    ok2, _, _ = evaluate_confirmation(_cand(), weak)
    assert ok2 is False  # a thin doji past nothing is not the confirmation


def test_one_close_law_confirms_first_break_for_every_setup():
    """Viva 2026-09-12 (the rage fix): NOBODY said confirmation requires a
    retest. One valid closed candle beyond the break edge confirms — for a
    TECHCLASSIC-style candidate with no VIVA_TLBREAK variant and never a zone
    touch after creation."""
    import pandas as pd
    from datetime import datetime, timedelta, timezone
    from test_v7 import make_candidate
    from analysis.quality_engine import evaluate_confirmation
    t0 = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(32):
        if i < 30:
            o = h = l = c = 99.0
        elif i == 30:
            o, h, l, c = 99.9, 100.95, 99.85, 100.9
        else:
            o, h, l, c = 100.55, 101.25, 100.5, 101.2
        rows.append({"timestamp": t0 + timedelta(minutes=5 * i), "open": o, "high": h,
                     "low": l, "close": c, "volume": 1000.0})
    df = pd.DataFrame(rows)
    df["timestamp"] = df.index
    cand = make_candidate()
    cand.setup_code = "TECHCLASSIC"
    cand.status = "NEAR_CONFIRM"
    cand.direction = "LONG"
    cand.entry_zone_bottom, cand.entry_zone_top = 100.0, 100.4
    cand.planned_entry, cand.sl = 100.2, 99.2
    cand.tp1, cand.tp2 = 105.0, 108.0
    cand.created_at = (t0 + timedelta(minutes=5 * 29)).isoformat()
    cand.metadata.pop("strategy_variant", None)
    cand.metadata.update({"atr": 0.8, "confirm_tf": "5m", "touched": False})
    cand.mandatory_gates = {"liquidity": True, "displacement": True, "location": True}
    ok, out, why = evaluate_confirmation(cand, df)
    assert ok is True, f"clean first break must confirm without any pullback: {why}"
    assert out.status == "CONFIRMED"
    assert "پولبک شرط نیست" in str(out.metadata.get("tl_fast_break") or "")
    # and the wait-reject now only fires when price has NOT even reached the edge
    cand2 = make_candidate()
    cand2.setup_code = "TECHCLASSIC"
    cand2.status = "NEAR_CONFIRM"
    cand2.direction = "LONG"
    cand2.entry_zone_bottom, cand2.entry_zone_top = 103.0, 103.4
    cand2.planned_entry, cand2.sl = 103.2, 99.2
    cand2.tp1, cand2.tp2 = 107.0, 109.0
    cand2.created_at = cand.created_at
    cand2.metadata.pop("strategy_variant", None)
    cand2.metadata.update({"atr": 0.8, "confirm_tf": "5m", "touched": False})
    cand2.mandatory_gates = {"liquidity": True, "displacement": True, "location": True}
    ok2, _o2, _w2 = evaluate_confirmation(cand2, df)
    assert ok2 is False   # price never touched nor passed that zone — still waiting


def test_identical_updates_are_swallowed():
    """«توی ثانیه چه تغییری شده که آپدیت میده؟!» — an update posts only when
    the content actually changed; a repeat with identical content dies before
    Telegram."""
    import bot.messages_v7 as M
    import database.bot_kv as KV
    KV._TABLE_READY["done"] = False
    from test_v7 import make_candidate
    os.environ["CANDIDATE_DB_BACKEND"] = "sqlite"
    import tempfile, os as _os
    fd, path = tempfile.mkstemp(suffix=".db"); _os.close(fd)
    os.environ["CANDIDATE_DB_PATH"] = path
    KV._TABLE_READY["done"] = False
    sent = {"n": 0}
    old_send = M.send_message
    M.CHAT_ID_EDUCATION = "-1004000000001"

    def fake_send(text, chat_id=None, reply_to_message_id=None, reply_markup=None):
        sent["n"] += 1
        return 7000 + sent["n"]
    M.send_message = fake_send
    try:
        KV.set_json("setup_chain|VIVA-TLBREAK-K333333", {"edu": 5, "upd": 0, "upd_n": 0})
        c = make_candidate()
        c.metadata["public_code"] = "VIVA-TLBREAK-K333333"
        import data.fetcher as F
        old_kl = F.get_klines
        F.get_klines = lambda *a, **k: None
        try:
            assert M.send_setup_update(c, None, note_fa="تازه") is True
            n1 = sent["n"]
            assert M.send_setup_update(c, None, note_fa="تازه") is False   # identical → swallowed
            assert sent["n"] == n1                                          # nothing new posted
            assert M.send_setup_update(c, None, note_fa="ناحیه جابه‌جا شد") is True
            assert sent["n"] == n1 + 1
        finally:
            F.get_klines = old_kl
    finally:
        M.send_message = old_send
        for k in ("CANDIDATE_DB_BACKEND", "CANDIDATE_DB_PATH"):
            os.environ.pop(k, None)
        KV._TABLE_READY["done"] = False
        try:
            _os.unlink(path)
        except OSError:
            pass


def test_confirm_rule_law_text_and_no_gaps():
    import bot.messages_v7 as M
    from test_v7 import make_candidate
    c = make_candidate()
    c.setup_code = "TLBREAK"
    rule = M._confirm_rule_fa(c)
    assert "پولبک شرط نیست" in rule
    assert "بازگشت به ناحیه" not in rule
    assert "کلوز معتبر  " not in rule and " معتبر \u0641ر" not in rule   # never a blank TF
    c.metadata.pop("confirm_tf", None)
    rule2 = M._confirm_rule_fa(c)
    import re as _re
    assert not _re.search(r"کلوز معتبر ف", rule2.replace("فراتر", "فَراتر")) or "  " not in rule2.replace("‌", "")
    # thin candidate: NO empty separator gap, NO empty ⚠️ block
    c.evidence = []
    c.warnings = []
    msg = M.build_educational_message(c)
    assert "\u2501"*20 + "\n\n\n\n" not in msg
    assert "</b>\n\n━━━━━━━━━━━━━━━━━━━━\n🔎" in msg   # ONE separator, then 🔎 — no empty block
    assert "فقط رصد بازار است" in msg                       # default warnings carry meaning
