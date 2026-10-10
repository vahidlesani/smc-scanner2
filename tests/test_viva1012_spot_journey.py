"""10-12 spot journey law (his final spec): each chain charts at most twice
(s1 first warning incl. ticker-instant, s2 first break), the break text
upgrades to chart, a divider separates every spot post, and the ticker
respects the spot flag. Detection (pins/recheck/confirms) is untouched —
only the 2000/day notification flood dies.

  J1  _spot_journey_slot table (chain side).
  J2  _lw_edge_slot table (edge side, kindless).
  J3  upsert stores pattern; level-move >0.5% resets the edge journey.
  J4  chain-key unity: sender writes the key the shared builder builds.
  J5  divider is the first line of a ladder post.
  J6  chart-upgrade deletes the pending text.
  J7  _journey_slot persists s1/s2 mids.
  J8  run_once returns 0 while SPOT_ENGINE_ENABLED=0 (no network).
  J9  _lw_touch_item structure.
"""
import time

import database.bot_kv as KV


def _uniq(prefix="J12"):
    return f"{prefix}{time.time_ns() % 1000000}"


# ── J1 ────────────────────────────────────────────────────────────────
def test_chain_slot_table():
    from analysis.spot_engine import _spot_journey_slot as S
    now = time.time()
    assert S({}, "s1", now) == "s1"
    assert S({"s1": 5}, "s1", now) is None
    assert S({"s1p": now}, "s1", now) is None            # fresh pending blocks
    assert S({"s1p": now - 700}, "s1", now) == "s1"      # stale pending frees
    assert S({}, "s2", now) == "s2"
    assert S({"s2": 9}, "s2", now) is None
    assert S({}, "s3", now) is None
    assert S(None, "s1", now) == "s1"


# ── J2 ────────────────────────────────────────────────────────────────
def test_edge_slot_table():
    from analysis.line_watch import _lw_edge_slot as E
    now = time.time()
    assert E({}, "s1", now) == "s1"
    assert E({"j1": now}, "s1", now) is None
    assert E({"j1p": now}, "s1", now) is None
    assert E({"j1p": now - 700}, "s1", now) == "s1"
    assert E({"j1": now}, "s2", now) == "s2"             # slots independent
    assert E({}, "s9", now) is None


# ── J3 ────────────────────────────────────────────────────────────────
def test_upsert_pattern_and_level_reset():
    from analysis.line_watch import upsert
    sym = _uniq()
    upsert(sym, "4h", 100.0, side="HIGH", stage="TOUCH", pattern="TRIANGLE")
    st = KV.get_json("line_watch", {})
    e = st.get(f"{sym}|4h|HIGH")
    assert e and e.get("pattern") == "TRIANGLE"
    # seed a journey, then move the level a little (kept) and a lot (reset)
    e["j1"] = time.time()
    st[f"{sym}|4h|HIGH"] = e
    KV.set_json("line_watch", st)
    upsert(sym, "4h", 100.1, side="HIGH", stage="TOUCH", pattern="TRIANGLE")
    assert KV.get_json("line_watch", {})[f"{sym}|4h|HIGH"]["j1"] > 0
    upsert(sym, "4h", 102.0, side="HIGH", stage="TOUCH", pattern="WEDGE")
    e2 = KV.get_json("line_watch", {})[f"{sym}|4h|HIGH"]
    assert e2["j1"] == 0.0 and e2["pattern"] == "WEDGE"


# ── J4..J7 helpers ────────────────────────────────────────────────────
def _mock_tg(M, calls):
    orig = (M.send_message, M.send_photo, M.delete_message, M.CHAT_ID_SPOT)
    mids = {"n": 900}

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


def _item(sym, stage, slot=None):
    it = {"symbol": sym, "tf": "4h", "stage": stage, "side": "HIGH",
          "pattern": "TRIANGLE", "pattern_fa": "مثلث", "rule_fa": "قانون",
          "vol_ratio": 0.0, "distance_pct": 0.1}
    if slot:
        it["_journey_slot"] = slot
    return it


def test_chain_key_unity_divider_and_slot_persist():
    import bot.messages_v7 as M
    calls = {"msgs": [], "photos": [], "dels": []}
    orig = _mock_tg(M, calls)
    try:
        sym = _uniq("K12")
        m1 = M.send_spot_alert(_item(sym, "TOUCH", "s1"), chart=b"png-1")
        assert m1
        want = M._spot_ladder_chain_key(sym, "4h", "TRIANGLE")
        assert want == f"spot_chain|{sym}|4H|TRIANGLE"
        meta = KV.get_json(want, {})
        assert meta.get("s1") == m1 and meta.get("n") == 1
        assert calls["photos"][0]["text"].split("\n")[0] == M._SPOT_DIV73
        # s2 text then s2 chart-upgrade: text replaced, slot = chart mid
        m2 = M.send_spot_alert(_item(sym, "BREAK_DOWN", "s2"), chart=None)
        assert calls["msgs"][0]["text"].split("\n")[0] == M._SPOT_DIV73
        m3 = M.send_spot_alert(_item(sym, "BREAK_DOWN", "s2"),
                               chart=b"png-2")
        assert calls["dels"] == [m2]
        meta2 = KV.get_json(want, {})
        assert meta2.get("s2") == m3 and meta2.get("last_text") == 0
    finally:
        _restore_tg(M, orig)


# ── J8 ────────────────────────────────────────────────────────────────
def test_run_once_respects_spot_flag(monkeypatch):
    import analysis.line_watch as LW
    sym = _uniq("F12")
    st = KV.get_json("line_watch", {}) or {}
    st[f"{sym}|4h|HIGH"] = {"symbol": sym, "tf": "4h", "market": "SPOT",
                            "level": 100.0, "side": "HIGH", "stage": "TOUCH",
                            "ts": time.time(), "last_state": "below",
                            "last_alert_ts": 0.0, "last_alert_kind": ""}
    KV.set_json("line_watch", st)
    monkeypatch.setenv("SPOT_ENGINE_ENABLED", "0")
    assert LW.run_once(force=True) == 0     # flag gates even forced runs


# ── J9 ────────────────────────────────────────────────────────────────
def test_touch_item_structure():
    from analysis.line_watch import _lw_touch_item as T
    entry = {"symbol": "enausdt", "tf": "4h", "level": 100.0, "side": "HIGH"}
    it = T(entry, 100.1, "", {"type": "X", "lines": []})
    assert it["symbol"] == "ENAUSDT" and it["stage"] == "TOUCH"
    assert it["_journey_slot"] == "s1" and it["pattern_commands"] == [{"type": "X", "lines": []}]
    assert abs(it["distance_pct"] - 0.1) < 1e-9
    assert it["close"] == 100.1 and it["edge"] == 100.0
    it2 = T(entry, 99.0, "", None)
    assert it2["pattern_commands"] == []
