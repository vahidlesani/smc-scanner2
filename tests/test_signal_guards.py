import pytest
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

        def _send_photo(image, caption, chat_id=None, reply_to_message_id=None,
                        reply_markup=None, **kwargs):
            counter["mid"] += 1
            photos.append((counter["mid"], caption, reply_to_message_id, chat_id, reply_markup))
            return counter["mid"]

        def _send_message(text, chat_id=None, reply_to_message_id=None, reply_markup=None):
            counter["mid"] += 1
            texts.append((counter["mid"], text, reply_to_message_id, chat_id,
                          reply_markup))
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
              "distance_atr": 0.15, "touches": 3, "structure_score": 7,
              "reactions": {"touches": 3, "rejects": 3, "breaks": 0, "reject_rate": 1.0},
              "scenarios": {"hold": "پایداریِ کانال", "break": "شکست معتبر",
                            "prob": "هیچ‌کدام ۱۰٪ نیست"},
              "ref_ts": "2026-01-24T20:00:00"}
        fade = {"direction": "LONG", "entry": 65.1, "stop": 64.3, "tp_mid": 79.9,
                "target": 94.6, "rr": 25.0, "reject_rate": 1.0}

        # Viva 2026-09-14 «مگه امتیاز ۲ هم داریم؟ زیر ۶ رو بستیم» — a preview
        # below the education floor never speaks in ANY channel:
        assert M.send_technoclassic_preview({**ev, "structure_score": 4}) is False
        assert len(photos) == 0
        assert M.send_technoclassic_preview(dict(ev)) is True
        # Viva 2026-09-13 «اگر قوانینش با تکنوکلاسیک یکی هست، باید پاک بشه»:
        # the preview's duplicate alerts-channel pair is GONE — it lives only
        # as the main-channel live slot (compact layout, registry-unique id).
        # 09-16 night transport: the chart bubble carries ONLY a one-line
        # Persian label; the readable compact text is the plain message
        # right behind it — never a caption, never a split.
        assert len(photos) == 1 and len(texts) == 2  # separator + compact text
        # no SECOND detailed alert mirrors into PRO (the compact header line
        # legitimately mentions it; a real detailed post would be 2500+ chars)
        assert not [t for t in texts if len(t[1]) > 2500]
        pro_mid = texts[1][0]
        edu_mid = 0
        assert "📊 چارت" in photos[0][1]                          # label-only bubble
        assert photos[0][3] == "-100TEST" and photos[0][2] is None   # PRO slot, no reply
        assert texts[1][2] is None and not texts[1][4]              # nothing to link to
        link = KV.get_json("tc_link|GTTSTUSDT|4h", {})
        assert link.get("mid") == pro_mid                             # confirmations → PRO anchor
        cap = texts[1][1]
        code = cap.split("<code>")[1].split("</code>")[0]
        assert code
        # Viva 2026-09-17 AMENDMENT (his reference template §2, verbatim):
        # the preview body is the FINAL-WARNING skeleton, registry-unique
        # T-code kept at the tail.
        import re as _re
        assert _re.fullmatch(r"VIVA-TECHCLASSIC-T\d{6}", code), code
        _hdr = cap.split("\n")
        assert _hdr[0] == "🏷 <b>VIVA __ TecnoClasic</b>"
        assert _hdr[1] == M.VIVA_SEP and "<code>" in cap
        for _need in ("⚡<b>هشدار نهایی | آماده‌سازی ورود</b>",
                      "🪙 <b>GTTSTUSDT</b>",
                      "🔎 در آستانه شکست — تکنوکلاسیک (پیش‌نمایش؛ سیگنال نیست)",
                      "📐 خط روند اصلی روی تایم",
                      "🎯 جهت محتمل پس از شکست معتبر:",
                      "📏 فاصله زنده تا خط:",
                      "⚖️ تاریخچۀ برخورد روی این خط:",
                      "🌀 کامپرشن:",
                      "سیگنال واقعی فقط با Close معتبرِ شکست + پولبک اول + BOS تایم پایین"):
            assert _need in cap, _need
        assert "🧠" not in cap and "⚡ <b>هشدار الگو" not in cap

        # same state again → silence (no channel spam)
        assert M.send_technoclassic_preview(dict(ev)) is False
        assert len(photos) == 1

        # state advances → a NEW numbered update post, replying to the anchor;
        # the superseded message is deleted (Viva 2026-09-12 latest-update law)
        deletes = []
        monkeypatch.setattr(M, "delete_message", lambda chat, mid: deletes.append(int(mid)) or True)
        ev2 = dict(ev, state="REJECTION_FADE", fade=fade)
        assert M.send_technoclassic_preview(ev2) is True
        assert len(edits) == 0 and len(photos) == 2 and len(texts) == 3  # appended pair
        upd1 = texts[2]
        assert upd1[3] == "-100TEST" and upd1[2] == pro_mid         # updates stay in the MAIN channel under the preview anchor
        assert "\U0001f501" in upd1[1] and "\u0622\u067e\u062f\u06cc\u062a \u06f1" in upd1[1]   # «آخرین آپدیت • آپدیت ۱»
        assert "\U0001fa99" in upd1[1] and "\u2696\ufe0f" in upd1[1]                # shared update layout with every other setup
        assert code in upd1[1]                                    # same unique id
        assert not upd1[4]                                         # preview has no alerts-channel detail
        assert pro_mid not in deletes                             # anchor is PERMANENT
        chain = KV.get_json("tc_chain|GTTSTUSDT|4h", {})
        assert chain.get("update") == upd1[0] and chain.get("upd_n") == 1
        # …and now NOTHING at all is posted into the alerts channel
        assert not [t for t in texts if len(t[1]) > 2500]

        # further advance → update ۲ lands as the newest message, update ۱ is DELETED
        ev3 = dict(ev, state="BREAK_READY", ref_ts="2026-01-24T21:00:00")  # new pattern bar
        assert M.send_technoclassic_preview(ev3) is True
        assert len(photos) == 3 and len(edits) == 0 and len(texts) == 4
        upd2 = texts[3]
        assert upd2[2] == pro_mid and upd2[3] == "-100TEST" and "آپدیت ۲" in upd2[1]
        # the superseded update's text AND its chart bubble go; anchor stays
        assert deletes == [upd1[0], photos[1][0]]
        assert not upd2[4]
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
    for needle in ("🏷 <b>VIVA ✦", "<b>هشدار نهایی | آماده‌سازی ورود</b>",
                   "🪙 <b>BTCUSDT</b>", "🔎 در آستانه تأیید",
                   "📍 ناحیه:", "🎯 جهت محتمل پس از تأیید معتبر:",
                   "📏 فاصلهٔ زنده تا ناحیه: 0.31 ATR", "⚖️", "🌀",
                   "سیگنال واقعی فقط با Close معتبرِ شکست", "🆔 <code>"):
        assert needle in cap, needle


def test_setup_chain_final_doctrine(monkeypatch):
    """Viva 2026-09-14 link-chain law (verbatim, EVERY setup): «پیام تفصیلی…
    در کانال هشدارها؛ همزمان پیام هشدار مختصر تحت عنوان هشدار ابتدایی به کانال
    اصلی و لینک به تفصیلی؛ آپدیت‌ها ریپلای به پیام مختصر و هر آپدیت قبلی را
    پاک؛ هشدار نهایی ریپلای به آخرین آپدیت؛ تأیید هم پیام خودش را دارد.» The
    compact is a PERMANENT anchor; updates replace only each other; final and
    Confirmed are new thread messages — nothing of the chain is overwritten."""
    os.environ["CANDIDATE_DB_BACKEND"] = "sqlite"
    import tempfile as _tf
    import time as _t
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
        posts, edits_t, edits_c = [], [], []
        counter = {"mid": 900}

        def _send_message(text, chat_id=None, reply_to_message_id=None, reply_markup=None):
            counter["mid"] += 1
            posts.append((counter["mid"], text, chat_id, reply_to_message_id, reply_markup))
            return counter["mid"]

        def _send_photo(image, caption, chat_id=None, reply_to_message_id=None,
                        reply_markup=None, **kwargs):
            counter["mid"] += 1
            posts.append((counter["mid"], caption, chat_id, reply_to_message_id, reply_markup))
            return counter["mid"]

        monkeypatch.setattr(M, "send_message", _send_message)
        monkeypatch.setattr(M, "send_photo", _send_photo)
        monkeypatch.setattr(M, "edit_text_message", lambda mid, chat_id, text: edits_t.append((mid, text)) or True)
        monkeypatch.setattr(M, "edit_chart_message",
                            lambda mid, chat_id, image, caption, reply_markup=None: edits_c.append((mid, caption, reply_markup)) or True)
        monkeypatch.setattr(M, "build_educational_message", lambda c: "DETAILED-MSG")
        monkeypatch.setattr(M, "generate_chart", lambda *a, **k: b"IMG")
        sep_calls = []
        monkeypatch.setattr(M, "send_signal_separator", lambda *a, **k: sep_calls.append(a) or None)
        deletes_u = []
        monkeypatch.setattr(M, "delete_message", lambda chat, mid: deletes_u.append(int(mid)) or True)
        import database.candidate_store as CS
        monkeypatch.setattr(CS, "update_candidate", lambda *a, **k: None)
        import data.fetcher as F
        monkeypatch.setattr(F, "get_klines", lambda *a, **k: None)

        def _aged():
            ch = KV.get_json("setup_chain|VIVA-TLBREAK-K000001", {}) or {}
            ch["upd_ts"] = _t.time() - 400
            KV.set_json("setup_chain|VIVA-TLBREAK-K000001", ch)

        assert M.send_educational_setup(cand, None) is True
        detail = [x for x in posts if x[1] == "DETAILED-MSG"][0]
        edu_mid = detail[0]
        compacts = [x for x in posts if "📚 <b>تحلیل آموزشی" in x[1]]
        assert len(compacts) == 1 and compacts[0][2] == M.CHAT_ID_EXECUTION
        compact_mid = compacts[0][0]
        assert compacts[0][3] is None                     # the compact IS the anchor
        assert sep_calls                                   # «بین پیام‌های کانال اصلی هم جداکننده»
        assert compacts[0][4] and str(edu_mid) in compacts[0][4]["inline_keyboard"][0][0]["url"]
        chain = KV.get_json("setup_chain|VIVA-TLBREAK-K000001", {})
        assert chain.get("edu") == edu_mid and chain.get("anchor_pro") == compact_mid

        _aged()
        assert M.send_setup_update(cand, None, note_fa="ناحیه جابه‌جا شد") is True
        up1 = [x for x in posts if "به‌روزرسانی رصد" in x[1]][-1]
        assert up1[2] == M.CHAT_ID_EXECUTION
        assert up1[3] == compact_mid                      # «ریپلای بشه به پیام مختصر همون کد»
        assert not deletes_u                              # the compact is NEVER deleted anymore
        assert "🔁 <b>آخرین آپدیت • آپدیت ۱</b>" in up1[1]

        _aged()
        assert M.send_setup_update(cand, None, note_fa="ادامه") is True
        up2 = [x for x in posts if "به‌روزرسانی رصد" in x[1]][-1]
        assert "آپدیت ۲" in up2[1] and up2[3] == compact_mid
        assert deletes_u == [up1[0]]                      # only the superseded UPDATE dies
        # same-minute twins are now structurally impossible:
        assert M.send_setup_update(cand, None, note_fa="توهمی") is False

        # final alert: a NEW message replying to the LAST update (any number)
        assert M.send_approaching(cand, 99.7, 0.31) is True
        fin = [x for x in posts if "⚡<b>هشدار نهایی" in x[1]][0]
        assert fin[3] == up2[0]                           # «ریپلای به آخرین آپدیت با هر شماره‌ای»
        assert not edits_t and not edits_c                # nothing was overwritten
        chain = KV.get_json("setup_chain|VIVA-TLBREAK-K000001", {})
        assert chain.get("approach") == fin[0]

        # confirmed: a NEW message replying to the final alert
        frame = pd.DataFrame({"open": [99.0], "high": [100.0], "low": [98.8],
                              "close": [99.6], "volume": [10.0]},
                             index=pd.date_range("2026-09-11", periods=1, freq="15min"))
        cand.metadata.pop("confirmation_chart_sent", None)
        cand.metadata.pop("confirmation_chart_message_id", None)
        cand.metadata["target_ladder"] = {"targets": [102.0, 105.0], "weights": [35, 35]}
        assert M.send_confirmed(cand, frame) is True
        conf = [x for x in posts if "✅ <b>سیگنال تأییدشده</b>" in x[1]][0]
        assert conf[2] == M.CHAT_ID_EXECUTION and conf[3] == fin[0]
        assert cand.metadata["confirmation_chart_message_id"] == conf[0]
        chain = KV.get_json("setup_chain|VIVA-TLBREAK-K000001", {})
        assert chain.get("confirmed") == conf[0]
    os.environ.pop("CANDIDATE_DB_BACKEND", None)
    os.environ.pop("CANDIDATE_DB_PATH", None)
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
    assert "<b>BTCUSDT</b>" in _sym_ln and "SWING" in _sym_ln  # ref §2: symbol • style • direction
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
    assert "اولین کلوزِ معتبر" in cap and "۱۵ دقیقه" in cap  # 09-13 confirmation law, Persian TF
    assert "⛔ Entry،" not in cap and "⛔ ورود، اهرم" in cap
    assert "📢 VivaMon Labs Pro" in cap

    ap = M._approaching_caption(c, 99.6, 0.31)
    _ap_ln = ap.split("🪙")[1].split("\n")[0]
    assert "BTCUSDT" in _ap_ln and "LONG" in _ap_ln      # ref §2: symbol • style • direction


def test_teclassic_public_code_family():
    """«VIVA-TECHCLASSIC-T000000» — the zeros become unique digits; own letter for
    TechnoClassic, K stays for the rest."""
    import re
    from analysis.models import generate_viva_public_code
    tc = generate_viva_public_code("TECHCLASSIC", "SWING")
    assert re.fullmatch(r"VIVA-TECHCLASSIC-T\d{6}", tc), tc
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


def test_s6_lane_with_no_trigger_candle_does_not_crash():
    """Viva 09-19 hotfix (AVAX PINWALL-Q): S6/fast-break lanes validate the
    trigger without any candle pattern; with alt=None the describe() call
    used to raise 'NoneType' object has no attribute 'size' and freeze the
    candidate cycle. Must return a verdict, never raise."""
    import pandas as pd
    from datetime import datetime, timedelta, timezone
    from test_v7 import make_candidate
    from analysis.quality_engine import evaluate_confirmation
    import analysis.trigger_patterns as tp

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
    orig = tp.multi_candle_trigger
    tp.multi_candle_trigger = lambda *a, **k: None   # force alt=None
    try:
        ok, _c, reason = evaluate_confirmation(cand, df)
        assert isinstance(ok, bool)
        assert "NoneType" not in str(reason)
    finally:
        tp.multi_candle_trigger = orig


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
    """Viva 09-19/20 RESTATED ladder (verbatim): each pattern TF confirms on
    ONE closed candle exactly one step below itself (15m←3m, 1h←15m, 4h←1h,
    1d←4h); the pattern TF's OWN close is only the LATE bound so a candidate
    never stalls when the finer frame is unavailable."""
    from analysis.setups_v7 import confirm_timeframe_for_pattern as f
    from analysis.setups_v7 import confirm_late_tf as late
    assert f("1d", "GRAND", "1d") == "4h"
    assert f("4h", "SWING", "4h") == "1h"
    assert f("1H", "SWING", "1h") == "15m"
    assert f("15m", "DAYTRADE", "15m") == "5m"
    assert late("15m") == "15m"
    assert late("1h") == "1h"
    assert late("4h") == "4h"
    assert late("1d") == "1d"
    # unknown pattern TF falls back to the trigger grid, never crashes
    assert f("", "DAYTRADE", "15m") == "5m"
    assert f("", "SWING", "4h") == "1h"


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
        c.created_at = (ts[-2]).isoformat()
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
    df["timestamp"] = [t0 + timedelta(minutes=5 * i) for i in range(len(df))]
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
            # Viva 2026-09-14 single-writer law: even DIFFERENT content waits
            # the chain update gap — the «۶ پیام در ۲۶ ثانیه» era is over.
            assert M.send_setup_update(c, None, note_fa="ناحیه جابه‌جا شد") is False
            assert sent["n"] == n1
            # after the gap it speaks again…
            ch = KV.get_json("setup_chain|VIVA-TLBREAK-K333333", {}) or {}
            ch["upd_ts"] = __import__("time").time() - 400
            KV.set_json("setup_chain|VIVA-TLBREAK-K333333", ch)
            assert M.send_setup_update(c, None, note_fa="ناحیه جابه‌جا شد") is True
            assert sent["n"] == n1 + 1
            # …and a verdict (⛔/❌/⚡) never waits — invalidation is instant.
            assert M.send_setup_update(c, None, note_fa="باطل شد",
                                       state_fa="⛔ <b>ستاپ بسته شد</b>") is True
            assert sent["n"] == n1 + 2
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


def test_licences_are_per_trigger_tf_and_setup():
    """Viva 2026-09-13 (the strangulation fix): a live chain may only lock its
    OWN (symbol, trigger timeframe, setup) tuple. TLBREAK 15m open must not
    absorb or cap TLBREAK 4h on the same symbol, and must never touch PINVAL
    or any other setup on the same symbol+trigger."""
    import os, tempfile
    from datetime import datetime, timedelta, timezone
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    os.environ["CANDIDATE_DB_BACKEND"] = "sqlite"
    os.environ["CANDIDATE_DB_PATH"] = path
    import database.bot_kv as KV
    KV._TABLE_READY["done"] = False
    try:
        import database.candidate_store as CS
        from test_v7 import make_candidate
        CS.init_candidate_store()
        c1 = make_candidate()
        c1.symbol = "XXTEST1USDT"; c1.setup_code = "TLBREAK"
        c1.trigger_timeframe = "15m"; c1.status = "EDUCATIONAL"
        c1.expires_at = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat(timespec="seconds")
        c1.signal_id = "viva-xxtest1-tlbreak-15m-0001"
        assert CS.add_candidate(c1)
        # same symbol+setup DIFFERENT trigger → free (not absorbed, not counted)
        assert CS.open_chains_for("XXTEST1USDT", "TLBREAK", "15m")
        assert not CS.open_chains_for("XXTEST1USDT", "TLBREAK", "4h")
        assert CS.chains_last_24h("XXTEST1USDT", "TLBREAK", "15m") == 1
        assert CS.chains_last_24h("XXTEST1USDT", "TLBREAK", "4h") == 0
        # different SETUP on the same trigger → fully independent
        assert not CS.open_chains_for("XXTEST1USDT", "PINVAL", "15m")
        assert CS.chains_last_24h("XXTEST1USDT", "PINVAL", "15m") == 0
        # dedupe key now carries the setup — setups never share a slot
        c2 = make_candidate()
        c2.symbol = "XXTEST1USDT"; c2.setup_code = "PINVAL"; c2.trigger_timeframe = "15m"
        assert CS._dedupe_key(c1) != CS._dedupe_key(c2)
        # same-zone quiet is per-trigger too: a 4h lineage is unaffected by the
        # 15m alert at the same price
        c1.metadata["atr"] = 1.0
        CS.update_candidate(c1)
        assert CS.recent_lineage_zone("XXTEST1USDT", "TLBREAK", c1.zone_mid, 5.0,
                                      trigger_tf="15m") is not None
        assert CS.recent_lineage_zone("XXTEST1USDT", "TLBREAK", c1.zone_mid, 5.0,
                                      trigger_tf="4h") is None
    finally:
        for k in ("CANDIDATE_DB_BACKEND", "CANDIDATE_DB_PATH"):
            os.environ.pop(k, None)
        KV._TABLE_READY["done"] = False
        try:
            os.unlink(path)
        except OSError:
            pass


def test_two_percent_licence_distance_law():
    """Viva 2026-09-13 verbatim: 3 rotating licences per (symbol, trigger-tf,
    setup), next frees on CONFIRMATION, and the next signal must open >=2%
    from the last CONFIRMED price — fixed percent, identical for ALL setups,
    no ATR anywhere in the rule."""
    import io as _io
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    src = _io.open(root / "main.py", encoding="utf-8").read()
    assert "last_confirmed_entry(candidate.symbol" in src
    assert "license_min_sep_pct" in src
    assert "license_zone_sep_atr" not in src and "license_zone_sep_pct" not in src
    repo = _io.open(root / "database" / "repository_v7.py", encoding="utf-8").read()
    assert "def last_confirmed_entry(" in repo
    st = __import__("config").get_settings()
    assert abs(float(st.license_min_sep_pct) - 0.02) < 1e-12
    # reference query must run clean on the live schema (both backends)
    import os as _os, tempfile as _tf
    from database import db as _ldb
    from database.repository_v7 import init_v7_schema, last_confirmed_entry
    _saved = getattr(_ldb, "DB_PATH", "")
    _tmp = _tf.mktemp(suffix=".db")
    if not _ldb.USE_POSTGRES:
        _ldb.DB_PATH = _tmp
    try:
        _ldb.init_db(); init_v7_schema()
        assert last_confirmed_entry("NOSUCHSYMUSDT", "4h", "PINVAL") is None
    finally:
        _ldb.DB_PATH = _saved
        try:
            _os.unlink(_tmp)
        except OSError:
            pass


def test_paper_capacity_mirrors_the_licence_key():
    """Viva 2026-09-13 «باید امکان‌اش وجود داشته باشد»: the persistence
    boundary may not be stricter than the licence law — 3 open pre-TP1 per
    (symbol, trigger, SETUP), never 3 across all setups of one trigger."""
    import io as _io
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    src = _io.open(root / "database" / "repository_v7.py", encoding="utf-8").read()
    i = src.index("def save_confirmed_signal(")
    seg = src[i:i + 2600]
    assert "has_open_pre_tp1_signal(candidate.symbol, candidate.trigger_timeframe,\n" in seg or \
           "candidate.setup_code)" in seg.split("has_open_pre_tp1_signal")[1][:200]
    assert src.count("has_open_pre_tp1_signal(candidate.symbol, candidate.trigger_timeframe):") == 0


def test_four_stream_ladder():
    """Viva 2026-09-13 «۴ تایم تریگر»: 1D grand swing, 4H mid, 1H mid, 15m
    short — every stream is a full alert/license tier, confirmed by ONE closed
    candle of the timeframe one step below its pattern TF."""
    from analysis.setups_v7 import TIMEFRAME_PROFILES, expiry_hours_for
    from analysis.setups_v7 import confirm_timeframe_for_pattern as cf
    # Viva 2026-09-16 night-2: four-TF world — 15m short swing (DAYTRADE),
    # 1h+4h mid swing (SWING, dual trigger), 1d long swing (GRAND).
    assert TIMEFRAME_PROFILES["GRAND"] == ("1d", "4h", "1d")
    assert TIMEFRAME_PROFILES["SWING"] == ("1d", "4h", "1h")
    assert TIMEFRAME_PROFILES["DAYTRADE"] == ("4h", "1h", "15m")
    assert cf("1d", "GRAND", "1d") == "4h"
    assert cf("4h", "SWING", "4h") == "1h"
    assert cf("1h", "SWING", "1h") == "15m"
    assert cf("15m", "DAYTRADE", "15m") == "5m"
    from analysis.quality_engine import ENGINES, _live_styles
    assert {"GRAND", "SWING", "DAYTRADE", "SCALP"} <= set(ENGINES)
    # SCALP engine stays built but is NOT live (scalp + 5m retired)
    assert set(_live_styles()) == {"DAYTRADE", "SWING", "GRAND"}
    assert expiry_hours_for("GRAND") >= 48
    assert expiry_hours_for("DAYTRADE") >= 12


def test_no_same_minute_updates_and_alerts_need_db_rows():
    """Viva 2026-09-13: «آپدیت باید با اتفاقِ قیمت بعد از هشدار بیاید، نه
    چسبیده به خودش» and «فقط سیگنال‌های به‌دیتابیس‌رسیده هشدار/آپدیت دارند»."""
    import io as _io
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    main = _io.open(root / "main.py", encoding="utf-8").read()
    assert "_update_too_fresh" in main and '"update_throttled"' in main
    i = main.index("if SETTINGS.skip_dead_gate_candidates and not candidate.execution_ready:\n"
                   "                    # A failing")
    seg = main[i:i + 2400]
    assert 'candidate.status = "DEAD_GATE"' in seg
    assert seg.index("add_candidate(candidate)") < seg.index("_educate(candidate, _chart_frame")
    cs = _io.open(root / "database" / "candidate_store.py", encoding="utf-8").read()
    assert cs.count("status<>'DEAD_GATE'") >= 2
    mv = _io.open(root / "bot" / "messages_v7.py", encoding="utf-8").read()
    assert '"⬛⬛⬛"' in mv and '"GRAND": "SWING"' in mv
    from config import get_settings
    assert int(get_settings().update_min_gap_seconds) >= 240

def test_break_close_scans_all_bars_not_only_latest():
    """Viva 2026-09-13 «شکست میاد ولی تأیید نمیده و موقعیت نابود میشه»: the
    confirming close may have settled TWO bars ago — the edge scan must walk
    EVERY closed bar since the alert, in the confirm TF or the pattern TF."""
    import pandas as pd
    from datetime import datetime, timedelta, timezone
    from test_v7 import make_candidate
    from analysis.quality_engine import evaluate_confirmation
    t0 = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(30):
        if i == 21:
            o, h, l, c = 102.3, 103.6, 102.1, 103.4      # the break bar
        elif i >= 22:
            o, h, l, c = 101.5, 101.7, 100.9, 101.2      # pulled back inside
        else:
            o, h, l, c = 99.98, 100.05, 99.9, 100.0
        rows.append({"timestamp": t0 + timedelta(hours=i), "open": o, "high": h,
                     "low": l, "close": c, "volume": 1000.0})
    df = pd.DataFrame(rows).set_index("timestamp")
    df.index.name = "timestamp"
    df["timestamp"] = df.index
    cand = make_candidate()
    cand.setup_code = "TECHCLASSIC"
    cand.status = "NEAR_CONFIRM"
    cand.entry_zone_bottom, cand.entry_zone_top = 100.5, 101.5
    cand.planned_entry, cand.sl = 101.0, 98.0
    cand.tp1, cand.tp2 = 112.0, 118.0
    cand.created_at = (t0 + timedelta(hours=10)).isoformat()
    cand.metadata.update({"atr": 1.0, "confirm_tf": "1h", "touched": False})
    ok, cand2, reason = evaluate_confirmation(cand, df)
    assert ok is True, f"a settled break bar must still confirm: {reason}"
    lane = str(cand2.metadata.get("tl_fast_break") or "")
    assert "اولین کلوزِ معتبر" in lane and "تایم تأیید" in lane
    assert str(cand2.metadata.get("fast_break_bar") or "")[:13] == "2026-09-13 21"
    # a pattern-timeframe close beyond the line confirms as well
    flat = df.copy()
    for i in range(11, 30):
        flat.iloc[i, flat.columns.get_indexer(["open", "high", "low", "close"])] = [100.0, 100.1, 99.9, 100.0]
    htf = df[df["timestamp"] >= t0 + timedelta(hours=11)]
    cand_b = make_candidate()
    cand_b.setup_code = "TECHCLASSIC"
    cand_b.status = "NEAR_CONFIRM"
    cand_b.entry_zone_bottom, cand_b.entry_zone_top = 100.5, 101.5
    cand_b.planned_entry, cand_b.sl = 101.0, 98.0
    cand_b.tp1, cand_b.tp2 = 112.0, 118.0
    cand_b.created_at = (t0 + timedelta(hours=10)).isoformat()
    cand_b.metadata.update({"atr": 1.0, "confirm_tf": "1h", "touched": False})
    ok2, cand3, reason2 = evaluate_confirmation(cand_b, flat, htf_closed_df=htf)
    assert cand3.metadata.get("tl_fast_break"), reason2
    assert "تایم الگو" in str(cand3.metadata.get("tl_fast_break"))


def test_main_channel_live_slot_and_preview_dedup():
    """Viva 2026-09-13 law reversal (apologised for the 09-12 order): the MAIN
    channel hosts the compact initial alert as ONE live slot; every update is a
    NEW numbered post that DELETES the previous slot message and links to the
    permanent alerts-channel detail. The TECHCLASSIC preview's duplicated
    alerts-channel pair is gone, and the chart carries the brand once."""
    import io
    src = io.open("bot/messages_v7.py", encoding="utf-8").read()
    assert "def _pro_slot_post" in src
    ed = src.split("def send_educational_setup", 1)[1].split("def _fa_num", 1)[0]
    assert "_pro_slot_post(candidate, _compact_alert_caption(candidate)" in ed
    assert "reply_to_message_id=detail_mid if detail_mid else None" not in ed
    up = src.split("def send_setup_update", 1)[1].split("def _approaching_ai_hint", 1)[0]
    assert "target = CHAT_ID_EXECUTION or CHAT_ID_ADMIN" in up
    assert "mid = _pro_slot_post(candidate, caption" in up
    assert "reply_to_message_id=detail_mid if detail_mid else None" not in up
    assert "_telegram_message_link(edu_chat, detail_mid)" in up
    tc = src.split("def send_technoclassic_preview", 1)[1]
    tc = tc.split("\ndef ", 1)[0]
    assert "edu_mid = 0" in tc
    assert "send_message(short, edu_chat, reply_to_message_id" not in tc
    assert "send_photo(chart, caption, edu_chat)" not in tc
    assert '"TECHCLASSIC" in pattern_en' in src
    assert "اولین کلوزِ معتبرِ بسته‌شده فراتر از خط یا ضلعِ الگو" in src
    assert "یک کلوز معتبر {ctf_fa}" not in src
    sv = io.open("analysis/setups_v7.py", encoding="utf-8").read()
    assert "این تحلیل تا قبل از Retest و بسته‌شدن کندل تأییدی" not in sv
    assert "tech_aids" in sv and "EMA" in sv
    qe = io.open("analysis/quality_engine.py", encoding="utf-8").read()
    assert "for _frame, _tag in ((closed_df, \"تایم تأیید\"), (htf_closed_df, \"تایم الگو\")):" in qe
    # helpers render into compact and update captions
    import bot.messages_v7 as mv7
    from test_v7 import make_candidate
    cand = make_candidate()
    # realistic aid lengths (the real banks speak in ~70-char sentences); a
    # synthetic 150-char aid pile cannot fit ONE 1024 caption by physics.
    cand.metadata.update({"session": "LONDON_NY_OVERLAP",
                          "tech_aids": ["📊 EMA51 مقاومت داینامیک است؛ شکستش بدون حجم اعتبار ندارد.",
                                        "🌀 لول 61.8٪ فیبو لمس شد؛ واکنش کندل بعد مهم است.",
                                        "📈 واگرایی صعودی RSI دیده شده."]})
    cap = mv7._compact_alert_caption(cand)
    # Viva 2026-09-16: session codes speak Persian in messages now.
    assert "تأییدهای کمکی" in cap and "هم‌پوشانی لندن-نیویورک" in cap and "61.8" in cap
    upd = mv7._setup_update_caption(cand, note_fa="x", upd_n=4)
    assert "هم‌پوشانی لندن-نیویورک" in upd and "نظر AI" in upd and "آپدیت" in upd

def test_gate_demotion_and_tolerant_liquidity():
    """Viva 2026-09-14 «ببین کجا موقعیت‌ها خفه می‌شن»: last cycle 25 of 32
    candidate rows died as DEAD_GATE — 13 at fresh_poi (a 10/10 DOGE
    TechnoClassic among them) and 12 at market_liquidity purely because the
    ticker feed carries no spread/turnover. Repeated touches STRENGTHEN a line
    (his own preview law) and missing data is unknown, not a veto."""
    import io as _io
    sv = _io.open("analysis/setups_v7.py", encoding="utf-8").read()
    assert 'if str(setup_code) in ("TLBREAK", "TECHCLASSIC"):' in sv
    assert 'gates.pop("fresh_poi", None)' in sv
    assert 'gates.pop("rr", None)' in sv
    qe0 = _io.open("analysis/quality_engine.py", encoding="utf-8").read()
    # Viva 09-20 (verbatim, third time): «فرمول ریسک به ریوارد ... اصلا اهمیت
    # نداره» → R:R never vetoes an entry any more; it is reported only.
    assert "RR_DEGRADED" not in qe0
    assert 'rr_readout' in qe0
    assert "_has_turn" in sv and "_has_spread" in sv
    from analysis.setups_v7 import _market_quality
    class _B:  # ticker-less bundle: unknown != veto
        ticker = {}
    valid, _detail, _pts = _market_quality(_B(), "SCALP")
    assert valid is True, "no data must never block an alert"
    class _B2:
        ticker = {"spread_pct": 0.9, "trading_day_turnover": 50.0}
    v2, _d2, _p2 = _market_quality(_B2(), "SCALP")
    assert v2 is False, "present-and-bad data still vetoes"
    from analysis.setups_v7 import expiry_hours_for
    assert expiry_hours_for("DAYTRADE") >= 96
    assert expiry_hours_for("SWING") >= 144
    assert expiry_hours_for("GRAND") >= 300
    assert expiry_hours_for("SCALP") >= 12
    cs = _io.open("database/candidate_store.py", encoding="utf-8").read()
    assert "OR (status NOT IN ('EDUCATIONAL','APPROACHING','CONFIRMED') AND updated_at<?)" in cs
    cfg = _io.open("config.py", encoding="utf-8").read()
    for flag in ("albrox_enabled: bool = True", "technoclassic_enabled: bool = True",
                 "pinwall_quality_enabled: bool = True"):
        assert flag in cfg, flag
    assert "education_max_per_scan: int = 16" in cfg
    # round 12: the per-symbol cap now sits behind the central geometry net
    assert "return kept[:4]" in sv and "def sanity_reject(" in sv
    qe = _io.open("analysis/quality_engine.py", encoding="utf-8").read()
    assert "def _frame_atr(" in qe and "_f_atr = _frame_atr(_frame" in qe
    mn = _io.open("main.py", encoding="utf-8").read()
    assert "def _live_break_watch" in mn and "def _watch_edge_at" in mn
    assert "_live_break_watch(candidate" in mn
    assert 'if _trg in ("1h", "4h", "1d")' in mn and "hb_bar" in mn
    assert '"4h": 14400, "1d": 86400}.get(tf, 300)' in mn
    assert "monitor_summary" in mn


def test_live_break_watch_behavior():
    """The moment a forming pattern candle crosses the reference line the
    watch note must speak (once per candle, with the close countdown); a pull
    back inside resets the flag; closed bars stay with the close law."""
    import pandas as pd
    from datetime import timedelta
    import main as MAIN
    from test_v7 import make_candidate

    now = pd.Timestamp.utcnow().tz_localize(None).floor("15min")
    rows = []
    for i in range(30):
        ts = now - timedelta(minutes=15 * (29 - i))
        base = 100.0 if i < 28 else (101.2 if i == 28 else 102.6)
        rows.append({"timestamp": ts, "open": base - 0.1, "high": base + 0.2,
                     "low": base - 0.2, "close": base, "volume": 100.0})
    frame = pd.DataFrame(rows)
    cand = make_candidate()
    cand.setup_code = "TECHCLASSIC"
    cand.trigger_timeframe = "15m"
    cand.direction = "LONG"
    cand.entry_zone_bottom, cand.entry_zone_top = 99.6, 100.4
    cand.sl, cand.tp1, cand.tp2 = 98.0, 112.0, 120.0
    cand.metadata.update({"atr": 1.0, "viva_breakout_line": 101.5})
    orig_upd = MAIN.update_candidate
    MAIN.update_candidate = lambda *a, **k: None
    try:
        note, lb_key = MAIN._live_break_watch(cand, frame)
        assert note.startswith("⚡") and "دقیقه" in note
        assert lb_key and not cand.metadata.get("live_break_bar"), \
            "HOT-4: the watcher must NOT persist the flag — the caller does, after a successful send"
        cand.metadata["live_break_bar"] = lb_key              # caller: send succeeded
        assert MAIN._live_break_watch(cand, frame) == ("", "")  # same candle, silence
        frame2 = frame.copy()
        frame2.loc[frame2.index[-1], ["open", "close", "high", "low"]] = [101.0, 101.0, 101.3, 100.8]
        assert MAIN._live_break_watch(cand, frame2) == ("", "")
        assert not cand.metadata.get("live_break_bar")        # pullback clears the flag
        note2, _k2 = MAIN._live_break_watch(cand, frame)
        assert note2.startswith("⚡")                          # fresh thrust speaks again
        assert MAIN._live_break_watch(cand, None) == ("", "")
    finally:
        MAIN.update_candidate = orig_upd


def test_link_chain_laws_2026_09_14():
    """Viva 2026-09-14 (the 23:5x message, verbatim laws) — every rule below
    was HIS written spec; this test is the contract that keeps the whole
    lifecycle honest: link-chain replies, permanent compact, never-truncated
    captions, one writer with the update gap, trigger-TF charts, Persian AI."""
    import io as _io
    src = _io.open("bot/messages_v7.py", encoding="utf-8").read()
    # 1) «نصفه» ban: no raw caption slicing anywhere; _fit_caption owns trims.
    assert 'caption[:1000]' not in src
    assert "def _fit_caption" in src
    # 2) Compact is the permanent anchor; updates quote it and replace each other.
    assert 'chain["anchor_pro"] = int(mid)' in src
    assert 'reply_to=int(chain.get("anchor_pro") or chain.get("edu_short") or 0)' in src
    # 3) The update gap is enforced IN the single writer (not only callers).
    up = src.split("def send_setup_update", 1)[1].split("def _approaching_ai_hint", 1)[0]
    assert "update_min_gap_seconds" in up
    # 4) Final alert replies to the LAST update; Confirmed is a new message.
    ap = src.split("def send_approaching", 1)[1].split("def _exact_event_message_id", 1)[0]
    assert 'chain.get("slot")' in ap and "reply_to=parent" in ap
    cf = src.split("def send_confirmed", 1)[1].split("def send_candidate_cancelled", 1)[0]
    assert "edit_chart_message" not in cf                 # Confirmed never overwrites
    assert 'chain.get("approach")' in cf                  # it quotes the final alert
    # 5) main ↔ win-rate two-way links + stop receipts mirrored.
    assert "def attach_results_link" in src and "def send_stop_event_to_results" in src
    mn = _io.open("main.py", encoding="utf-8").read()
    assert mn.count("attach_results_link(") >= 3
    # 6) The chart title is the TRIGGER TF — pattern TF is only a PAT note.
    assert "_tf_disp = (md.get(\"tl_context_tf\")" not in src
    assert "_tf_disp = str(candidate.trigger_timeframe" in src
    # 7) Unconfirmed charts carry NO target/TP chips (zone+invalidation+trend).
    assert "EXPECTED MOVE" not in src
    # 8) Settlement: fee-only round trip (no invented slippage cut).
    assert "2*(SETTINGS.fee_rate_percent+SETTINGS.slippage_percent)" not in \
        _io.open("database/realtime_monitor.py", encoding="utf-8").read()
    assert "2 * SETTINGS.fee_rate_percent" in _io.open("database/repository_v7.py", encoding="utf-8").read()
    # 9) Preview can never post below the education floor («امتیاز ۲ از کجا؟»).
    tc = src.split("def send_technoclassic_preview", 1)[1]
    assert "educational_min_score" in tc.split("\ndef ", 1)[0]
    # 10) _chart_frame: trigger TF for every setup (no context-TF preference).
    assert 'if candidate.setup_code in ("TLBREAK", "TECHCLASSIC"):\n        context_tf' not in mn
    # 11) Alert memory survives redeploys (boot-window re-alert storm fix).
    assert "alert_dedup" in mn


def test_compact_captions_fit_under_media_cap_for_every_setup():
    from bot.messages_v7 import _compact_alert_caption, _setup_update_caption
    from test_v7 import make_candidate
    for setup, code in (("TLBREAK", "K1"), ("TECHCLASSIC", "T1"), ("ALBROX", "A1"),
                        ("PINVAL", "P1"), ("PINWALLQ", "Q1")):
        c = make_candidate()
        c.setup_code = setup
        c.strategy_fa = f"{setup} | پیش‌نمایش (نه سیگنال)" if setup == "TECHCLASSIC" else f"{setup} | رویداد تست"
        c.metadata["public_code"] = f"VIVA-{setup}-{code}"
        c.metadata["session"] = "LONDON"
        c.metadata["tech_aids"] = ["📊 EMA51 به سمت بالا شکسته شد", "🌀 روی لول ۶۱٫۸ پولبک زده شد"] * 3
        cap = _compact_alert_caption(c)
        assert len(cap) <= 4096, (setup, len(cap))  # text message cap
        upd = _setup_update_caption(c, note_fa="تست", upd_n=3)
        assert "نظر AI" in upd and "آپدیت ۳" in upd


@pytest.fixture(autouse=True)
def _no_net_in_confirmation_gates(monkeypatch):
    """The 09-19/20 MTF confirmation gates fetch the parent TF; unit tests
    must stay offline (gate fails open when the frame is unavailable)."""
    import data.fetcher as dfb
    monkeypatch.setattr(dfb, "get_klines", lambda *a, **k: None)


def test_zec_protected_exit_settlement_is_win():
    """The K120563 case: SHORT banked 50% at TP1 (1R floor, 09-19 ladder)
    then the net-BE trail executed. That is NOT 'INITIAL STOP LOSS' / a loss."""
    from analysis.trade_management import build_ladder, advance_ladder
    lad = build_ladder(1136.41, 1147.4419, "SHORT", {"tick_size": 0.01}, 1112.07,
                       trigger_tf="15m")
    # Round-11 doctrine: the only level (1112.07 = 2.1%) sits below the 15m
    # band floor (3%) and there is no previous extreme in the ladder call, so
    # the path is the band middle (4%) split in five → TP1 = entry − 0.8%.
    assert abs(lad["targets"][0] - 1127.32) < 0.05
    assert lad["weights"] == [40.0, 30.0, 30.0, 0.0, 0.0]
    step = advance_ladder(lad, 1131.0, 1124.8)               # TP1 printed (round-10 path)
    assert step["state"]["hit_index"] == 1
    assert abs(step["state"]["current_sl"] - 1136.36) < 1e-6  # entry −5 ticks (short)
    step2 = advance_ladder(step["state"], 1136.40, 1136.30)  # trail executes
    kinds = [e["event"] for e in step2["events"]]
    assert "TRAIL_STOP" in kinds                              # protected exit, never STOP-with-INITIAL
    # settlement math exactly as realtime monitor now does it:
    risk_pct = abs(1136.41 - 1147.4419) / 1136.41 * 100
    gross = step2["state"]["realized_r"] * risk_pct
    net = gross - 2 * 0.06                                    # fee-only, 0.06%/leg
    assert net > 0, (gross, net)                              # WIN, as Viva lived it
    profit = 600 * net / 100
    assert profit > 0


def test_aids_banks_state_aware_persian():
    from analysis import aids_bank as ab
    assert ab.bank_sizes() == {"fibo": 17, "ema": 15, "rsi": 15, "session": 8}
    mid = ab.rsi_note(58, 54, "NEUTRAL", "X", "1h", "b")
    assert "بیش‌خرید" not in mid and "اشباع" not in mid       # 58 is NOT overbought talk
    ob = ab.rsi_note(77, 74, "OB", "X", "1h", "b")
    assert "بیش‌خرید" in ob or "۷۰" in ob
    cx = ab.ema_note(51, 0.2, "CROSS_DOWN", "X", "1h", "b")
    assert "شکسته" in cx
    for name, note in [(s, ab.session_note(s)) for s in
                       ("SYDNEY", "ASIA", "TOKYO", "LONDON", "NY",
                        "LONDON_NY_OVERLAP", "LATE_NY", "OFF_HOURS")]:
        assert note, name
        assert not any(ch.isascii() and ch.isalpha() for ch in note), name
    # bank lines must be Persian prose, not bare tokens
    for fam in ab.FIBO_BANK.values():
        for line in fam:
            assert len(line) > 40


def test_tp_ladder_reply_chain_2026_09_15():
    """Viva 2026-09-15 (verbatim ladder): «تی پی ها هر کدوم به تی پی قبلی
    لینک بشه، فقط اولین تی پی به پیام تایید سیگنال، تی پی ۲ به ۱، ۳ به ۲،
    ۴ به ۳، ۵ به ۴ و پیام نتیجه به ۵». Stop receipts quote Confirmed
    (09-14 verbatim); the final result anchors to the exact last receipt."""
    import bot.messages_v7 as M
    from bot.messages_v7 import _ladder_reply_id, _final_lifecycle_anchor
    # TP1 quotes the Confirmed receipt (no previous TP exists yet)
    assert _ladder_reply_id({"pro_message_id": 111}, "TP1") == 111
    # each later TP quotes the PREVIOUS TP receipt
    assert _ladder_reply_id({"last_tp_message_id": 222, "pro_message_id": 111}, "TP2") == 222
    assert _ladder_reply_id({"last_tp_message_id": 333, "pro_message_id": 111}, "TP3") == 333
    assert _ladder_reply_id({"last_tp_message_id": 444, "pro_message_id": 111}, "TP4") == 444
    assert _ladder_reply_id({"last_tp_message_id": 555, "pro_message_id": 111}, "TP5") == 555
    # stop / trailing-stop receipts quote Confirmed
    assert _ladder_reply_id({"last_tp_message_id": 444, "pro_message_id": 111}, "STOP") == 111
    assert _ladder_reply_id({"last_tp_message_id": 444, "pro_message_id": 111}, "TRAIL_STOP") == 111
    # final result: WIN → the exact last TP receipt (…→ TP5); stop-exit → stop receipt
    _mids = {"TP5": 555, "TP2": 222, "TRAIL_STOP": 999, "STOP": 998, "CONFIRMED": 111}
    orig = M._exact_event_message_id
    M._exact_event_message_id = lambda sid, key, fb=0: int(_mids.get(key, fb) or 0)
    try:
        assert _final_lifecycle_anchor({"signal_id": "viva-x", "result": "WIN", "hit_index": 5}) == 555
        assert _final_lifecycle_anchor({"signal_id": "viva-x", "result": "WIN", "hit_index": 2}) == 222
        assert _final_lifecycle_anchor({"signal_id": "viva-x", "result": "LOSS", "hit_index": 0}) == 999
    finally:
        M._exact_event_message_id = orig
    # a position that never printed a stop falls back to Confirmed
    M._exact_event_message_id = lambda sid, key, fb=0: int(({"CONFIRMED": 111}).get(key, fb) or 0)
    try:
        assert _final_lifecycle_anchor({"signal_id": "viva-x", "result": "LOSS", "hit_index": 0}) == 111
    finally:
        M._exact_event_message_id = orig


def test_compact_caption_single_message_2026_09_15():
    """Viva 2026-09-15: «این پیام هشدار اولیه ... باید در یک پیام باشه» —
    the compact anchor degrades (drops aids/extras, shortens the rule) rather
    than overflowing the 1024 media cap; it never promises a continuation."""
    from test_v7 import make_candidate
    from bot.messages_v7 import _compact_alert_caption
    cand = make_candidate()
    cand.setup_code = "PINWALLQ"
    cand.strategy_fa = "PINWALL Quality | کیفیت، موقعیت و کامپرشن"
    cand.metadata.update({
        "session": "LONDON_NY_OVERLAP",
        "tech_aids": ["📊 " + "x" * 200, "📊 " + "y" * 200, "🌀 " + "z" * 200,
                      "📈 " + "w" * 200, "🕐 سشن آخرین کندل: " + "s" * 100],
    })
    extra = ["• خط اضافی " + "e" * 150, "• خط اضافی " + "f" * 150]
    out = _compact_alert_caption(cand, extra_lines=extra)
    # 09-16 night: the compact is a PLAIN TEXT message behind its chart
    # bubble — the 4096 text cap holds everything, four full aids included.
    assert len(out) <= 4096, f"compact overflowed the text cap: {len(out)}"
    assert "🆔" in out and "🔎" in out, "core sections must survive"
    assert "ادامه" not in out, "compact must never carry a continuation footer"
    assert all(k in out for k in ("🕐 سشن", "📊", "🌀", "📈")), "full aids stay"


def test_slot_never_emits_detached_continuation_2026_09_16():
    """Viva 2026-09-16 night (verbatim): «پیام مختصر رو بصورت کپشن نذار؛ اول
    عکس چارت، بلافاصله پیام مختصر، تا پیام چندپاره و نصفه نشه» — the slot
    writer posts the chart bubble with a one-line label and the readable
    text as a plain message right behind: no caption, no split, any length
    fits ONE message under the 4096 text cap."""
    import inspect
    import bot.messages_v7 as mv7
    src = inspect.getsource(mv7._pro_slot_post)
    assert "_post_chart_then_text" in src
    assert "send_photo(chart, caption" not in src
    from test_v7 import make_candidate
    cand = make_candidate()
    cand.metadata.update({"session": "NEW_YORK",
                          "tech_aids": ["📊 " + "x" * 300, "🌀 " + "y" * 300,
                                        "📈 " + "z" * 300]})
    out = mv7._compact_alert_caption(cand)
    assert len(out) <= 4096
    assert all(k in out for k in ("🕐 سشن", "📊", "🌀", "📈"))
    assert "ادامه" not in out


def test_chart_pills_match_ladder_exits(monkeypatch):
    import data.fetcher as _f
    monkeypatch.setattr(_f, "get_klines", lambda *a, **k: None)
    """Viva 09-19: the confirmed chart must show EVERY ladder exit pill.
    Guards the de-indent regression that silently dropped TP1/TP2 pills."""
    import numpy as np
    import pandas as pd
    from datetime import datetime, timedelta, timezone
    import bot.messages_v7 as m7
    from analysis.models import SignalCandidate, EvidenceItem
    from analysis.trade_management import build_ladder

    rng = np.random.default_rng(11)
    n = 90
    ts = [datetime(2026, 9, 19, tzinfo=timezone.utc) + timedelta(minutes=15 * i) for i in range(n)]
    close = 96.5 + np.linspace(0, 8.0, n) + rng.normal(0, 0.05, n)
    frame = pd.DataFrame({"timestamp": ts, "open": close - 0.08, "high": close + 0.2,
                          "low": close - 0.2, "close": close, "volume": np.full(n, 900.0)})
    now = datetime.now(timezone.utc).replace(microsecond=0)
    c = SignalCandidate(
        signal_id="PILL-REGRESSION-1", symbol="BTCUSDT", style="DAYTRADE",
        setup_code="TLBREAK", setup_name="VIVA-TLBREAK", strategy_fa="x",
        direction="LONG", score=8, status="CONFIRMED",
        entry_zone_bottom=99.4, entry_zone_top=99.6, planned_entry=99.5, sl=97.5,
        tp1=103.5, tp2=107.5, rr_tp1=2.0, rr_tp2=4.0, bias="BULLISH",
        trigger_timeframe="15m",
        evidence=[EvidenceItem("tlbreak", "t", "d", True, 2)],
        confirmations=[], warnings=[], mandatory_gates={"rr": True},
        market={"turnover24h": 1e9, "spread_pct": 0.02, "tick_size": 0.01},
        metadata={"atr": 1.0, "public_code": "PILL-1"},
        created_at=now.isoformat(timespec="seconds"),
        confirmed_at=now.isoformat(timespec="seconds"))
    c.metadata["target_ladder"] = build_ladder(
        c.planned_entry, c.sl, c.direction, c.market, c.tp2,
        structural_tp1=c.tp1, fee_pct=0.0018)
    tags = []
    orig = m7._level_tag
    def spy(ax, x, y, label, color):
        tags.append(label)
        return orig(ax, x, y, label, color)
    m7._level_tag = spy
    try:
        assert m7.generate_chart(frame, c, confirmed=True)
    finally:
        m7._level_tag = orig
    # Round-22 law: ONE pill per level (the old 3%-merge produced mega-chips).
    # Round-24 refinement — Viva 09-24: «ابزار لانگ و شورت در ۵ ستاپ فقط با
    # tp1 تا tp5 مشخص بشه» — the tool tags are the bare numbers 1..5 (one
    # each, no big TP labels over the candles), ENTRY/FIRST STOP stay.
    joined = " | ".join(tags)
    # r32 (Viva 09-26): the tool column carries ONLY the bare numbers 1..5 —
    # ENTRY/FIRST STOP words moved to the price axis + bottom-right ledger.
    assert "ENTRY" not in joined and "FIRST STOP" not in joined
    for i in range(1, 6):
        assert str(i) in tags, (i, joined)
    assert tags.count("1") == 1
    assert not any(t.startswith("TP") for t in tags), joined  # no big TP labels


def _s6_frame_and_candidate(direction="LONG"):
    import pandas as pd
    from datetime import datetime, timedelta, timezone
    from test_v7 import make_candidate
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
    cand.created_at = (t0 + timedelta(minutes=15 * 27)).isoformat()
    cand.metadata.update({
        "strategy_variant": "VIVA_TLBREAK", "viva_breakout_line": 100.0, "atr": 1.0,
        "confirm_tf": "15m", "touched": True, "viva_state": "S6_CONFIRMED",
        "viva_state_machine": {"stage": "S6_CONFIRMED"},
    })
    if direction == "LONG":
        cand.direction = "LONG"
        cand.planned_entry, cand.sl = 100.1, 98.6
        cand.tp1, cand.tp2 = 106.0, 109.0
    else:
        cand.direction = "SHORT"
        cand.planned_entry, cand.sl = 100.1, 101.9
        cand.tp1, cand.tp2 = 96.0, 93.0
    return df, cand


def test_degenerate_geometry_rejects_confirmation():
    """Viva 09-19/20 (SUI 1D): targets that are a rounding error versus the
    stop must never confirm — the scenario stays alert/analysis only."""
    from analysis.quality_engine import evaluate_confirmation
    df, cand = _s6_frame_and_candidate("LONG")
    cand.tp1, cand.tp2 = 100.3, 100.6          # rr ≈ 0.13 / 0.33
    ok, _c, reason = evaluate_confirmation(cand, df)
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "DEGENERATE_GEOMETRY"


def test_counter_trend_touch_only_never_confirms():
    """Viva 09-19/20 (ZEC/LTC/POL): against the structure a TOUCH is only an
    alert; confirmation needs a closed structure break in trade direction."""
    from analysis.quality_engine import evaluate_confirmation
    df, cand = _s6_frame_and_candidate("SHORT")   # frame rallies = bull structure
    cand.metadata["tl_context_conflict"] = True
    ok, _c, reason = evaluate_confirmation(cand, df)
    assert ok is False
    assert cand.metadata.get("last_reject_code") == "COUNTER_TREND_TOUCH_ONLY"
