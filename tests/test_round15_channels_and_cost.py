"""Round-15 tests — cost optimization + the confirmed-only timeframe channels.

Two things Viva asked for on 09-21 («اسکلت کار رو بگو شروع کن اما مراقب باش سیسم
فعلی بهم نریزه»):

1. wasteful consumption must go (closed candles re-downloaded every 5 minutes,
   symbols re-analysed when nothing new closed, Gemini re-tried after 107
   straight HTTPErrors) — and none of it may change a single message;
2. four new channels: ONLY confirmed signals, NO reply chains, and every card's
   link always points at that signal's LATEST result in the Results channel.
   Every one of those paths must be a no-op while the channel ids are unset.
"""

import os
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 1. cost: the closed-candle cache ───────────────────────────────────────

def test_closed_candle_ttl_follows_the_candle_not_a_fixed_45s():
    from data.fetcher import closed_candle_ttl
    for tf, sec in (("15m", 900), ("1h", 3600), ("4h", 14400), ("1d", 86400)):
        ttl = closed_candle_ttl(tf)
        assert 20 <= ttl <= 1800, tf
        # never longer than the candle itself, never a flat 45 seconds
        assert ttl <= sec
    assert closed_candle_ttl("5m") >= 20
    # unknown timeframe → a safe default instead of an exception
    assert closed_candle_ttl("nonsense") >= 20


def test_closed_candle_ttl_is_capped_and_floor_guarded():
    from data.fetcher import closed_candle_ttl
    assert closed_candle_ttl("1d", cap=60) <= 60
    assert closed_candle_ttl("1m") >= 20  # never a zero-length cache


def test_ourbit_closed_ttl_matches_the_same_rule():
    from data.ourbit import _closed_ttl
    assert 20 <= _closed_ttl("15m") <= 1800
    assert 20 <= _closed_ttl("1d") <= 1800


def test_cost_counters_exist_and_are_a_copy():
    from data.fetcher import cost_counters
    a = cost_counters()
    assert {"kline_calls", "kline_cache_hits"} <= set(a)
    a["kline_calls"] = 999999
    assert cost_counters()["kline_calls"] != 999999


def test_get_klines_serves_the_second_call_from_cache():
    """The route cache: two identical closed-candle requests ⇒ ONE upstream hit."""
    import pandas as pd
    from data import fetcher

    frame = pd.DataFrame({"timestamp": pd.date_range("2026-09-20", periods=30, freq="15min"),
                          "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 10.0})
    calls = {"n": 0}

    def fake_bybit(symbol, interval, limit, closed_only, use_cache, end_ms):
        calls["n"] += 1
        return frame.copy()

    fetcher.clear_market_cache()
    with patch.object(fetcher, "_get_klines_bybit", side_effect=fake_bybit):
        with patch.object(fetcher, "ourbit_listed", create=True, return_value=False):
            with patch("data.ourbit.ourbit_listed", return_value=False):
                before = fetcher.cost_counters()["kline_calls"]
                first = fetcher.get_klines("ZZZUSDT", "15m", 30, closed_only=True)
                second = fetcher.get_klines("ZZZUSDT", "15m", 30, closed_only=True)
    assert first is not None and second is not None and calls["n"] == 1
    assert fetcher.cost_counters()["kline_calls"] == before + 1


# ── 2. cost: the unchanged-symbol guard ────────────────────────────────────

def _bundle(stamps):
    import pandas as pd
    from data.fetcher import MarketBundle
    frames = {}
    for tf, stamp in stamps.items():
        frames[tf] = pd.DataFrame({"timestamp": [stamp], "open": [1.0], "high": [1.1],
                                   "low": [0.9], "close": [1.0], "volume": [1.0]})
    return MarketBundle(symbol="ZZZUSDT", frames=frames, ticker={})


def test_skip_guard_never_skips_a_fresh_symbol_or_an_open_chain():
    import main
    main._LAST_CLOSED_STAMPS.clear()
    main._LAST_FULL_SCAN_AT.clear()
    stamp = {tf: "2026-09-21 00:00" for tf in ("15m", "1h", "4h", "1d")}
    b = _bundle(stamp)
    assert main._symbol_may_skip("ZZZUSDT", b, set()) is False          # first sight
    main._LAST_FULL_SCAN_AT["ZZZUSDT"] = time.monotonic()
    assert main._symbol_may_skip("ZZZUSDT", b, set()) is True           # nothing new
    assert main._symbol_may_skip("ZZZUSDT", b, {"ZZZUSDT"}) is False    # open chain
    fresh = _bundle({**stamp, "15m": "2026-09-21 00:15"})
    assert main._symbol_may_skip("ZZZUSDT", fresh, set()) is False      # new candle
    main._LAST_FULL_SCAN_AT["ZZZUSDT"] = time.monotonic() - (main._UNCHANGED_RETRY_SECONDS + 5)
    assert main._symbol_may_skip("ZZZUSDT", b, set()) is False          # retry window


def test_skip_guard_is_fail_open_on_a_broken_bundle():
    import main
    main._LAST_CLOSED_STAMPS.clear()
    assert main._symbol_may_skip("ZZZUSDT", None, set()) is False


# ── 3. cost: the Gemini breaker ────────────────────────────────────────────

def test_gemini_breaker_opens_after_consecutive_failures_and_recovers():
    from ai import gemini_advisor as ga
    with patch.dict(os.environ, {"GEMINI_API_KEY": "x"}, clear=False):
        ga._BREAKER["fails"] = 0
        ga._BREAKER["until"] = 0.0

        class _C:
            signal_id = "t"
            symbol = "X"
            trigger_timeframe = "15m"
            style = "SWING"
            direction = "LONG"
            setup_code = "TLBREAK"
            score = 8
            planned_entry = sl = tp1 = tp2 = 1.0
            metadata = {}

        with patch("ai.gemini_advisor.requests.post", side_effect=RuntimeError("boom")):
            for _ in range(ga._BREAKER_THRESHOLD - 1):
                assert ga._generate(_C()) is None
            assert not ga._breaker_open()
            assert ga._generate(_C()) is None
            assert ga._breaker_open(), "breaker must open at the threshold"
        # while open, no HTTP call is even attempted
        calls = {"n": 0}

        def _explode(*a, **k):
            calls["n"] += 1
            raise AssertionError("must not be called while the breaker is open")

        with patch("ai.gemini_advisor.requests.post", side_effect=_explode):
            assert ga._generate(_C()) is None
        assert calls["n"] == 0
        # recovery resets the counter
        ga._BREAKER["until"] = 0.0

        class _Resp:
            ok = True
            status_code = 200

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

        with patch("ai.gemini_advisor.requests.post", return_value=_Resp()):
            assert ga._generate(_C()) == "ok"
        assert ga._BREAKER["fails"] == 0


# ── 4. the four channels: mapping + message shape ──────────────────────────

def test_timeframe_channel_mapping():
    """Round 15 phase 5: the buckets follow HIS channel names — 15m/30m/1h in
    VIVA-MON-15M-1H, 2h/4h in VIVA-MON-2H-4H, 1d/3d/1w in VIVA-MON-1D, and the
    spot engine owns VIVA-MON-SPOT."""
    import bot.messages_v7 as m
    assert m.tf_channel_bucket("15m") == "15M_1H"
    assert m.tf_channel_bucket("30m") == "15M_1H"
    assert m.tf_channel_bucket("1h") == "15M_1H"
    assert m.tf_channel_bucket("2h") == "2H_4H"
    assert m.tf_channel_bucket("4h") == "2H_4H"
    assert m.tf_channel_bucket("1d") == "1D"
    assert m.tf_channel_bucket("3d") == "1D"
    assert m.tf_channel_bucket("1w") == "1D"
    assert m.tf_channel_bucket("") == ""


def test_unset_channel_makes_every_path_a_noop():
    """The live system must be untouched until Viva creates the channels."""
    from bot import messages_v7 as m
    with patch.object(m, "CHAT_ID_SWING_SHORT", ""):
        assert m.tf_channel_id("15m") == ""
        assert m.tf_channel_publish_confirmed.__module__  # importable
    with patch.object(m, "send_message") as sm, patch.object(m, "send_photo") as sp:
        from analysis.models import SignalCandidate
        c = SignalCandidate(signal_id="x", symbol="ZZZUSDT", style="DAYTRADE",
                            setup_code="TLBREAK", setup_name="t", strategy_fa="t",
                            direction="LONG", score=8, status="CONFIRMED",
                            entry_zone_bottom=1.0, entry_zone_top=1.01,
                            planned_entry=1.0, sl=0.99, tp1=1.02, tp2=1.04,
                            rr_tp1=2.0, rr_tp2=4.0, bias="BULLISH",
                            trigger_timeframe="15m", mandatory_gates={}, metadata={})
        with patch.object(m, "CHAT_ID_SWING_SHORT", ""):
            assert m.tf_channel_publish_confirmed(c, b"png") == 0
        sm.assert_not_called()
        sp.assert_not_called()


def test_tf_channel_text_is_self_contained_and_rd_free():
    from analysis.models import SignalCandidate
    from bot import messages_v7 as m
    c = SignalCandidate(signal_id="x", symbol="ZZZUSDT", style="DAYTRADE",
                        setup_code="TLBREAK", setup_name="t", strategy_fa="t",
                        direction="LONG", score=8, status="CONFIRMED",
                        entry_zone_bottom=1.0, entry_zone_top=1.01,
                        planned_entry=100.0, sl=99.0, tp1=102.0, tp2=110.0,
                        rr_tp1=2.0, rr_tp2=10.0, bias="BULLISH",
                        trigger_timeframe="15m", mandatory_gates={},
                        metadata={"target_ladder": {"targets": [102.0, 104.0, 106.0],
                                                    "weights": [40, 30, 30]}})
    text = m._tf_channel_text(c, "🔗 آخرین نتیجه: <i>در انتظار نتیجه</i>")
    assert "سیگنال تأییدشده" in text
    assert "آخرین نتیجه" in text
    assert "٪ فاصله" in text
    # law of round 14: never an R multiple anywhere
    assert " R" not in text and "R:R" not in text
    assert "1:2" not in text
    assert "<b>100</b>" in text or "100" in text


def test_link_refresh_edits_the_card_and_falls_back_to_a_fresh_post():
    from bot import messages_v7 as m
    chain = {"tfc_chat": "-1001", "tfc_mid": 55,
             "tfc_text": "✅ card\\n🔗 آخرین نتیجه: <i>…</i>\\n\\n📌 <b>VIVAMON-Labs-Pro</b>"}
    edits = {}

    def _get(code):
        return dict(chain)

    def _set(code, value):
        chain.update(value)

    def _edit(chat, mid, text):
        edits["chat"], edits["mid"], edits["text"] = chat, mid, text
        return True

    with patch.object(m, "_chain_by_code_get", side_effect=_get), \
         patch.object(m, "_setup_chain_set_by_code", side_effect=_set), \
         patch.object(m, "_tf_channel_edit", side_effect=_edit):
        ok = m.tf_channel_set_latest_result("ZZZ-123", "-1002", 777, "TP2 HIT")
    assert ok is True
    assert edits["chat"] == "-1001" and edits["mid"] == 55
    assert "777" in edits["text"]
    assert "TP2 HIT" in edits["text"]
    assert chain.get("tfc_last_result") == "777"

    # purged card ⇒ fresh standalone post instead of an error
    chain2 = {"tfc_chat": "-1001", "tfc_mid": 55, "tfc_text": "✅ card"}
    with patch.object(m, "_chain_by_code_get", return_value=dict(chain2)), \
         patch.object(m, "_setup_chain_set_by_code", side_effect=lambda c, v: chain2.update(v)), \
         patch.object(m, "_tf_channel_edit", return_value=False), \
         patch.object(m, "send_message", return_value=99) as sm:
        assert m.tf_channel_set_latest_result("ZZZ-123", "-1002", 778, "TP3 HIT") is True
    sm.assert_called_once()


def test_setting_a_link_twice_for_the_same_result_does_not_edit_again():
    from bot import messages_v7 as m
    chain = {"tfc_chat": "-1001", "tfc_mid": 55, "tfc_text": "x", "tfc_last_result": "900"}
    with patch.object(m, "_chain_by_code_get", return_value=dict(chain)), \
         patch.object(m, "_tf_channel_edit") as ed:
        assert m.tf_channel_set_latest_result("C", "-1002", 900, "TP1 HIT") is True
    ed.assert_not_called()


# ── 5. the SPOT green box: off on futures, on for spot ─────────────────────

def test_measure_box_defaults_to_off_for_futures():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'os.getenv("CHART_MEASURE_BOX", "off")' in src
    assert "len(_lns) == 2 and not any(_flat8)" in src
    # round 15b/15e: the renderer itself refuses the box outside SPOT — a flag
    # is not a guarantee, so futures is hard-None by construction, and a SPOT
    # chart carries the box even when it is already confirmed.
    assert "_spot8" in src and '_mkt8 == "SPOT"' in src
    assert "spot_measured_box" in src
