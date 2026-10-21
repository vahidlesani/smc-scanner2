"""10-10 publish-lateness surgery.

S1 PUBLISH-BYPASS: send_confirmed force-fetches its trigger frame when the
monitor's window-gated frames dict has nothing (TOHOM early-confirms were
born stuck: chart_df None -> blocked forever outside the window).
S2 TEXT-FIRST: after 3 failed chart attempts the TEXT publishes NOW (results
arm on it); the photo follows as a reply when a render works. A decided
confirm is never erased by a chart failure.
S3 EARLY-WATCH: approaching band widened with his 0.5% gate (0.30 ATR sat
~0.1% from the zone on fast frames — the final watch came AT the touch).
"""

import pandas as pd


def _df(n=60, px=100.0):
    import numpy as _np
    from datetime import datetime, timedelta, timezone
    ts = [datetime(2026, 10, 9, tzinfo=timezone.utc) + timedelta(minutes=15 * i) for i in range(n)]
    close = px + _np.linspace(0, 1.0, n)
    return pd.DataFrame({"timestamp": ts, "open": close - 0.05, "high": close + 0.1,
                         "low": close - 0.1, "close": close,
                         "volume": _np.full(n, 900.0)})


def _cand():
    from datetime import datetime, timezone
    from analysis.models import SignalCandidate as _SC, EvidenceItem as _EV
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat(timespec="seconds")
    return _SC(signal_id="PUB-1", symbol="TSTUSDT", style="DAYTRADE",
               setup_code="PINVAL", setup_name="VIVA-PINVAL", strategy_fa="x",
               direction="LONG", score=8, status="CONFIRMED",
               entry_zone_bottom=99.9, entry_zone_top=100.0, planned_entry=99.95,
               sl=98.5, tp1=102.0, tp2=104.0, rr_tp1=2.0, rr_tp2=4.0, bias="BULLISH",
               trigger_timeframe="15m",
               evidence=[_EV("pin", "t", "d", True, 2)],
               confirmations=[], warnings=[], mandatory_gates={"rr": True},
               market={"turnover24h": 1e9, "spread_pct": 0.02, "tick_size": 0.01},
               metadata={"atr": 1.0, "public_code": "PUB-1", "touched": True},
               created_at=now, confirmed_at=now)


def _mock_env(monkeypatch, klines_ret, chart_ret):
    import bot.messages_v7 as m7
    import data.fetcher as _f
    calls = {"fetch": [], "post": [], "photo": [], "mirror": []}
    def fake_klines(symbol, tf, size, **k):
        calls["fetch"].append((symbol, tf, size))
        return klines_ret() if callable(klines_ret) else klines_ret
    monkeypatch.setattr(_f, "get_klines", fake_klines)
    monkeypatch.setattr(m7, "generate_chart", lambda *a, **k: chart_ret() if callable(chart_ret) else chart_ret)
    def fake_post(chart, text, target, **k):
        calls["post"].append((chart, text, k.get("reply_to")))
        return (101, 202)
    monkeypatch.setattr(m7, "_post_chart_then_text", fake_post)
    def fake_photo(image, caption, chat_id=None, **k):
        calls["photo"].append((image, k.get("reply_to_message_id")))
        return 303
    monkeypatch.setattr(m7, "send_photo", fake_photo)
    monkeypatch.setattr(m7, "_sig_mirror", lambda *a, **k: calls["mirror"].append(a[1]))
    return m7, calls


def test_bypass_fetch_cures_none_chart_df(monkeypatch):
    m7, calls = _mock_env(monkeypatch, _df(), b"PNG")
    c = _cand()
    assert m7.send_confirmed(c, None) is True
    assert any(tf == "15m" and size >= 140 for _, tf, size in calls["fetch"])
    assert calls["post"][0][0] == b"PNG"  # real chart bytes posted
    assert c.metadata.get("confirmation_chart_sent") is True


def test_text_fallback_after_3_attempts(monkeypatch):
    m7, calls = _mock_env(monkeypatch, None, None)
    c = _cand()
    assert m7.send_confirmed(c, None) is False
    assert m7.send_confirmed(c, None) is False
    assert len(calls["post"]) == 0  # no premature text
    assert m7.send_confirmed(c, None) is True  # 3rd: TEXT now
    assert calls["post"][0][0] is None  # text-only
    assert "تأخیر ارسال" in (calls["post"][0][1] or "")
    assert c.metadata.get("confirmation_message_sent") is True
    assert c.metadata.get("confirmation_photo_pending") is True
    assert not c.metadata.get("confirmation_chart_sent")


def test_no_duplicate_text_while_photo_pending(monkeypatch):
    m7, calls = _mock_env(monkeypatch, None, None)
    c = _cand()
    c.metadata["chart_fail_attempts"] = 5
    c.metadata["confirmation_message_sent"] = True
    c.metadata["confirmation_photo_pending"] = True
    assert m7.send_confirmed(c, None) is False
    assert len(calls["post"]) == 0  # text already out: no twin


def test_photo_followup_posts_reply(monkeypatch):
    m7, calls = _mock_env(monkeypatch, _df(), b"PNG2")
    c = _cand()
    c.metadata["confirmation_message_sent"] = True
    c.metadata["confirmation_photo_pending"] = True
    c.metadata["confirmation_chart_message_id"] = 202
    assert m7.send_confirmed_photo_followup(c) is True
    assert calls["photo"][0] == (b"PNG2", 202)  # photo replies to the text
    assert c.metadata.get("confirmation_chart_sent") is True
    assert not c.metadata.get("confirmation_photo_pending")


def test_photo_followup_no_text_no_photo(monkeypatch):
    m7, calls = _mock_env(monkeypatch, _df(), b"PNG2")
    c = _cand()  # message never sent: followup must not fire
    assert m7.send_confirmed_photo_followup(c) is False
    assert len(calls["photo"]) == 0


def test_approach_band_half_percent():
    from analysis.quality_engine import approaching_entry
    c = _cand()  # LONG zone [99.9, 100.0], atr 1.0
    assert approaching_entry(c, 99.6)[0] is True    # 0.30 ATR: old gate
    assert approaching_entry(c, 99.55)[0] is True   # 0.45%: NEW 0.5% gate
    assert approaching_entry(c, 99.4)[0] is False   # 0.60%: still quiet
