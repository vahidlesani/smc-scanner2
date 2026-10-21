"""10-11 spam surgery (his «هر تایم تریگر اجازه صدور یک پوزیشن بده فعلا» +
«نوبت دوم و سوم سیگنال به ستاپها و اسپات رو ببند» + «آپدیت الکی و بیهوده
رو جلوش بگیر»). Zero network use.

  R1  journey chain key is per (symbol, TF) — kind flip-flops share it.
  R2  kind-flip warnings share ONE journey meta (code/reply/slots).
  R3  spot TF position gate: 2nd confirm (any pattern) inside 24h blocked.
  R4  position gate expires after its window (fresh journey next day).
  R5  setup licence default is ONE chain per (symbol, setup, TF) / 24h.
  R6  spot update events are OFF unless Railway opts back in.
"""
import time

import database.bot_kv as KV


def _uniq(prefix="R71"):
    return f"{prefix}{time.time_ns() % 1000000}"


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


def _item(sym, stage, pattern="TRIANGLE"):
    return {"symbol": sym, "tf": "4h", "stage": stage, "side": "HIGH",
            "pattern": pattern, "pattern_fa": "مثلث",
            "rule_fa": "قانون", "vol_ratio": 0.0, "distance_pct": 0.1}


# ── R1 ────────────────────────────────────────────────────────────────
def test_chain_key_tf_wide_kind_flip_shares_it():
    import bot.messages_v7 as M
    sym = _uniq("K71")
    k1 = M._spot_ladder_chain_key(sym, "4h", "TRIANGLE")
    k2 = M._spot_ladder_chain_key(sym, "4H", "CHANNEL_ASCENDING")
    k3 = M._spot_ladder_chain_key(sym, "4h", "EDGE")
    assert k1 == k2 == k3 == f"spot_chain|{sym}|4H"


# ── R2 ────────────────────────────────────────────────────────────────
def test_kind_flip_warnings_share_one_journey_meta():
    import bot.messages_v7 as M
    calls = {"msgs": [], "photos": [], "dels": []}
    orig = _mock_tg(M, calls)
    try:
        sym = _uniq("J71")
        m1 = M.send_spot_alert(_item(sym, "TOUCH", "TRIANGLE"), chart=b"p1")
        m2 = M.send_spot_alert(_item(sym, "NEAR_BREAK", "CHANNEL"), chart=None)
        assert m1 and m2
        meta = KV.get_json(f"spot_chain|{sym}|4H", {})
        assert meta.get("n") == 2            # one journey, two numbered posts
        assert meta.get("head") == m1        # second quotes the first chart
        assert calls["msgs"][0]["reply"] == m1
        code = meta.get("code")
        assert code
        # no per-pattern side chains were minted
        assert KV.get_json(f"spot_chain|{sym}|4H|TRIANGLE", {}) == {}
        assert KV.get_json(f"spot_chain|{sym}|4H|CHANNEL", {}) == {}
    finally:
        _restore_tg(M, orig)


# ── R3 ────────────────────────────────────────────────────────────────
def test_position_gate_blocks_second_confirm_any_pattern():
    import main as MAIN
    sym = _uniq("P71")
    assert MAIN._spot_tf_position_open(sym, "4h") is False
    MAIN._spot_tf_position_commit(sym, "4h")
    assert MAIN._spot_tf_position_open(sym, "4h") is True
    assert MAIN._spot_tf_position_open(sym, "4H") is True   # case-proof
    assert MAIN._spot_tf_position_open(sym, "1d") is False  # other TF free
    assert MAIN._spot_tf_position_open(sym + "X", "4h") is False


# ── R4 ────────────────────────────────────────────────────────────────
def test_position_gate_expires_after_window(monkeypatch):
    import main as MAIN
    sym = _uniq("E71")
    monkeypatch.setenv("SPOT_ONE_POSITION_HOURS", "24")
    assert MAIN._spot_tf_position_hours() == 24.0
    state = dict(KV.get_json("spot_tf_position", {}) or {})
    state[f"{sym}|4H"] = time.time() - 25 * 3600.0
    KV.set_json("spot_tf_position", state)
    assert MAIN._spot_tf_position_open(sym, "4h") is False
    monkeypatch.setenv("SPOT_ONE_POSITION_HOURS", "48")
    assert MAIN._spot_tf_position_hours() == 48.0
    assert MAIN._spot_tf_position_open(sym, "4h") is True  # window widened


# ── R5 ────────────────────────────────────────────────────────────────
def test_setup_licence_default_is_concurrent_three():
    """R5's «one per 24h» is SUPERSEDED by Viva 10-15 (verbatim): «اون ۳ زنجیره
    ۳ سیگنال همزمان روی یک نماد در یک تایم فریمه … نه اینکه سقف هشدار و
    تایید» — the licence is three CONCURRENT seats, no 24h publish quota."""
    from config import Settings
    assert Settings().chains_per_symbol_setup_24h == 3


# ── R6 ────────────────────────────────────────────────────────────────
def test_update_events_default_off_env_opts_in(monkeypatch):
    import main as MAIN
    monkeypatch.delenv("SPOT_UPDATE_EVENTS_ENABLED", raising=False)
    assert MAIN._spot_update_events_enabled() is False
    monkeypatch.setenv("SPOT_UPDATE_EVENTS_ENABLED", "1")
    assert MAIN._spot_update_events_enabled() is True
    monkeypatch.setenv("SPOT_UPDATE_EVENTS_ENABLED", "0")
    assert MAIN._spot_update_events_enabled() is False
