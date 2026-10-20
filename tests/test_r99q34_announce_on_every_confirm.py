"""R99q34 — «هنوز در کانال های مجزا هیچ پیام تاییدی نمیاد .. درحالیکه ۶ تایید داشتیم».

The A/B/C confirm design posts «پوزیشن فعال شد» as a reply in the MAIN channel
and returns — it never reached the announce-channel card further down
`send_confirmed`. Every setup that had sent its stage-B chart therefore
confirmed into the main channel and nowhere else. These tests pin both confirm
paths and the publisher's text-only retry.
"""
import matplotlib
matplotlib.use("Agg")

import pytest


def _cand():
    from analysis.models import SignalCandidate
    return SignalCandidate(
        signal_id="r99q34", symbol="ZECUSDT", style="x", setup_code="PINVAL",
        setup_name="PINVAL", strategy_fa="f", direction="LONG", score=8,
        status="WATCH", entry_zone_bottom=1148.0, entry_zone_top=1152.0,
        planned_entry=1150.0, sl=1099.0, tp1=1197.0, tp2=1220.0,
        rr_tp1=1.0, rr_tp2=2.0, bias="LONG", trigger_timeframe="4h",
        market={"asset_class": "CRYPTO", "venue": "BYBIT"},
        metadata={"market": "FUTURES", "engine": "SWING",
                  "public_code": "Z1", "stage_b_sent": True,
                  "stage_b_text_mid": 77},
    )


def test_activation_confirm_also_announces(monkeypatch):
    import bot.messages_v7 as M
    calls = []
    monkeypatch.setattr(M, "_send_activation_reply", lambda c: True)
    monkeypatch.setattr(M, "tf_channel_publish_confirmed",
                        lambda c, chart=None, **kw: calls.append((c.signal_id, chart)) or 4242)
    monkeypatch.setattr(M, "build_ladder", lambda *a, **k: {"targets": [1197.0, 1220.0]})
    cand = _cand()
    assert M.send_confirmed(cand, None) is True
    assert calls, "the activation path must publish the announce card"
    assert calls[0][0] == "r99q34"


def test_text_first_confirm_also_announces(monkeypatch):
    import bot.messages_v7 as M
    calls = []
    monkeypatch.setattr(M, "tf_channel_publish_confirmed",
                        lambda c, chart=None, **kw: calls.append(chart) or 4242)
    monkeypatch.setattr(M, "build_ladder", lambda *a, **k: {"targets": [1197.0, 1220.0]})
    monkeypatch.setattr(M, "generate_chart", lambda *a, **k: None)
    monkeypatch.setattr(M, "_bypass_trigger_frame", lambda c: None)
    monkeypatch.setattr(M, "_post_chart_then_text",
                        lambda *a, **k: (0, 555))
    monkeypatch.setattr(M, "_sig_mirror", lambda *a, **k: None)
    monkeypatch.setattr(M, "_setup_chain_get", lambda c: {})
    monkeypatch.setattr(M, "_setup_chain_set", lambda c, d: None)
    monkeypatch.setattr(M, "_confirmed_chart_caption", lambda c: "cap")
    monkeypatch.setattr(M, "_chart_label", lambda **k: "label")
    monkeypatch.setattr(M, "_public_code", lambda c: "Z1")
    cand = _cand()
    cand.metadata.pop("stage_b_sent", None)
    cand.metadata["chart_fail_attempts"] = 2       # third failure ⇒ text-first
    assert M.send_confirmed(cand, None) is True
    assert calls == [None], "text-first confirm must announce the card (no chart)"


def test_publisher_retries_text_only_when_the_chart_post_fails(monkeypatch):
    import bot.messages_v7 as M
    seen = []

    def _post(chart, text, chat, **kw):
        seen.append(chart)
        return (0, 0) if chart is not None else (0, 9002)   # photo failed

    monkeypatch.setattr(M, "_post_chart_then_text", _post)
    monkeypatch.setattr(M, "_tf_channel_text", lambda c, line: "card")
    monkeypatch.setattr(M, "_chart_label", lambda **k: "label")
    monkeypatch.setattr(M, "_chain_by_code_get", lambda code: {})
    monkeypatch.setattr(M, "_setup_chain_set_by_code", lambda code, d: None)
    monkeypatch.setattr(M, "_telegram_message_link", lambda *a: "")
    monkeypatch.setattr(M, "_public_code", lambda c: "Z1")
    monkeypatch.setattr(M, "CHAT_ID_SWING_SHORT", "-1001")
    mid = M.tf_channel_publish_confirmed(_cand(), chart=b"png")
    assert mid == 9002
    assert seen == [b"png", None], "the card must be retried without its chart"


def test_routing_still_returns_the_right_board(monkeypatch):
    import bot.messages_v7 as M
    monkeypatch.setattr(M, "CHAT_ID_SWING_SHORT", "-1001")
    monkeypatch.setattr(M, "CHAT_ID_SWING_MID", "-1002")
    assert M._setup_announce_channel("PINVAL") == "-1001"
    assert M._setup_announce_channel("PINWALLQ") == "-1001"
    for code in ("ALBROX", "TLBREAK", "TECHCLASSIC"):
        assert M._setup_announce_channel(code) == "-1002"
    assert M._setup_announce_channel("SPOTBREAK") == ""
