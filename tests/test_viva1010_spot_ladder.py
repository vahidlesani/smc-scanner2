"""10-10 spot ladder surgery (his ENA 20x/day + chain/box laws).

Covers, with zero network use:
  T1  _best_break_per_tf — one BREAK per tf per pass (r58 for the ladder),
      TOUCH/NEAR untouched.
  T2  spot_break_lock_check/commit — kindless BREAK suppression per
      sym|tf|side per 1xTF; other side + non-BREAK passthrough; expiry.
  T4' _STAGE_COOLDOWN_H — DOWN 24h (re-breaks warn), UP 0 (confirm owns UP).
  T5  _spot_box_target — structural ceiling wins; dust/virgin air falls back
      to the TF size (never a flat 25%).
  T6  send_spot_alert chain — chartless updates REPLACE the previous text,
      reply to the FIRST post, numbered #1/#2/...
  T7  send_spot_alert chart-once — a stage charts once per chain; the repeat
      goes text-only quoting the first chart.
"""
import time

import database.bot_kv as KV


def _uniq(prefix="T73"):
    return f"{prefix}{time.time_ns() % 1000000}"


# ── T1 ────────────────────────────────────────────────────────────────
def _mk(stage, tf, x0, x1, npts):
    return {"stage": stage, "tf": tf,
            "pattern_commands": [{"lines": [{"x0": x0, "x1": x1,
                                             "points": [{"a": 1}] * npts}]}]}


def test_best_break_per_tf_keeps_strongest_break_only():
    from analysis.spot_engine import _best_break_per_tf
    items = [_mk("BREAK_DOWN", "4h", 0, 10, 2),    # weight 10*2 = 20
             _mk("BREAK_UP", "4h", 0, 50, 4),      # weight 50*4 = 200 → wins
             _mk("TOUCH", "4h", 0, 5, 2),
             _mk("NEAR_BREAK", "4h", 0, 6, 2),
             _mk("BREAK_DOWN", "8h", 0, 10, 2)]
    got = _best_break_per_tf(items)
    breaks4 = [i for i in got if i["tf"] == "4h"
               and str(i["stage"]).startswith("BREAK")]
    assert len(breaks4) == 1 and breaks4[0]["stage"] == "BREAK_UP"
    assert any(i["stage"] == "TOUCH" for i in got)
    assert any(i["stage"] == "NEAR_BREAK" for i in got)
    assert any(i["tf"] == "8h" for i in got)


# ── T2 ────────────────────────────────────────────────────────────────
def test_kindless_break_lock_suppresses_kind_flip_only():
    from analysis.spot_engine import (spot_break_lock_check as chk,
                                      spot_break_lock_commit as cmt,
                                      _spot_break_lock_key as K)
    sym = _uniq()
    a = {"symbol": sym, "tf": "4h", "stage": "BREAK_DOWN",
         "pattern": "TRIANGLE"}
    b = dict(a, pattern="WEDGE")          # KIND flip, same event
    assert chk(a) is True
    cmt(a)
    assert chk(b) is False                # suppressed across KINDs
    assert chk(dict(a, stage="BREAK_UP")) is True   # other side unaffected
    assert chk({"symbol": sym, "tf": "4h", "stage": "TOUCH",
                "pattern": "X"}) is True           # non-BREAK passthrough
    KV.set_json(K(a), {"ts": time.time() - 5 * 3600, "kind": "TRIANGLE"})
    assert chk(b) is True                 # 4h window expired → allowed


# ── T4' ───────────────────────────────────────────────────────────────
def test_break_cooldowns_down_24_up_never():
    from analysis.spot_engine import _STAGE_COOLDOWN_H
    assert _STAGE_COOLDOWN_H["BREAK_DOWN"] == 24.0   # re-breaks warn (no confirm lane)
    assert _STAGE_COOLDOWN_H["BREAK_UP"] == 0.0      # confirm lane owns every UP


# ── T5 ────────────────────────────────────────────────────────────────
def test_spot_box_target_ceiling_first_tf_fallback():
    from analysis.spot_pattern_engine import _spot_box_target as box
    assert box(100.0, "4h", 180.0) == 180.0     # structural ceiling wins
    assert box(100.0, "1d", 100.2) == 175.0     # dust → 1d fallback 1.75x
    assert box(100.0, "4h", 0) == 125.0
    assert box(100.0, "8h", None) == 135.0
    assert box(100.0, "12h", None) == 150.0
    assert box(100.0, "3d", None) == 250.0
    assert box(100.0, "1w", None) == 300.0


# ── T6/T7 helpers ─────────────────────────────────────────────────────
def _mock_tg(M, calls):
    orig = (M.send_message, M.send_photo, M.delete_message, M.CHAT_ID_SPOT)
    mids = {"n": 700}

    def fake_send_message(text, chat, reply_to_message_id=None):
        mids["n"] += 1
        calls["msgs"].append({"mid": mids["n"], "text": text,
                              "reply": reply_to_message_id})
        return mids["n"]

    def fake_send_photo(photo, text, chat, reply_to_message_id=None):
        mids["n"] += 1
        calls["photos"].append({"mid": mids["n"], "text": text,
                                "reply": reply_to_message_id})
        return mids["n"]

    def fake_delete(chat_id, message_id):
        calls["dels"].append(int(message_id))
        return True

    M.send_message, M.send_photo, M.delete_message = (
        fake_send_message, fake_send_photo, fake_delete)
    M.CHAT_ID_SPOT = "test-spot"
    return orig


def _restore_tg(M, orig):
    M.send_message, M.send_photo, M.delete_message, M.CHAT_ID_SPOT = orig


def _item(sym, stage):
    return {"symbol": sym, "tf": "4h", "stage": stage, "side": "HIGH",
            "pattern": "TRIANGLE", "pattern_fa": "مثلث",
            "rule_fa": "قانون", "vol_ratio": 0.0, "distance_pct": 0.1}


def test_chain_text_updates_replace_reply_first_numbered():
    import bot.messages_v7 as M
    calls = {"msgs": [], "photos": [], "dels": []}
    orig = _mock_tg(M, calls)
    try:
        sym = _uniq("C73")
        m1 = M.send_spot_alert(_item(sym, "NEAR_BREAK"), chart=None)
        m2 = M.send_spot_alert(_item(sym, "NEAR_BREAK"), chart=None)
        assert m1 and m2 and m1 != m2
        assert calls["photos"] == []
        assert calls["dels"] == [m1]            # previous text replaced
        assert calls["msgs"][1]["reply"] == m1  # quotes the FIRST post
        assert "#1" in calls["msgs"][0]["text"]
        assert "#2" in calls["msgs"][1]["text"]
        meta = KV.get_json(f"spot_chain|{sym}|4H|TRIANGLE", {})
        assert meta.get("n") == 2 and meta.get("last_text") == m2
        assert meta.get("head") == m1 and meta.get("first") == 0
    finally:
        _restore_tg(M, orig)


def test_chain_stage_charts_once_repeat_goes_text():
    import bot.messages_v7 as M
    calls = {"msgs": [], "photos": [], "dels": []}
    orig = _mock_tg(M, calls)
    try:
        sym = _uniq("D73")
        m1 = M.send_spot_alert(_item(sym, "BREAK_DOWN"), chart=b"fake-png")
        m2 = M.send_spot_alert(_item(sym, "BREAK_DOWN"), chart=b"fake-png-2")
        assert m1 and m2
        assert len(calls["photos"]) == 1        # second BREAK: no new chart
        assert len(calls["msgs"]) == 1
        assert calls["msgs"][0]["reply"] == m1  # quotes the first chart
        assert calls["dels"] == []              # no pure-text to replace yet
        meta = KV.get_json(f"spot_chain|{sym}|4H|TRIANGLE", {})
        assert meta.get("chart_stages") == ["BREAK_DOWN"]
        assert meta.get("first") == m1 and meta.get("n") == 2
    finally:
        _restore_tg(M, orig)
