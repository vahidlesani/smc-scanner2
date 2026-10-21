"""10-10 STAGED WATCH (his A/B/C/D design).

A (0.5%): text-only final watch — zero fetch, zero render.
B (0.3%): chart WITH frozen tools (READY-mode render) + snapshot freeze.
C: activation = zero-fetch/zero-render REPLY to B, levels from snapshot.
Gap (no B): falls through to the S1/S2 publish path (covered by the
fallback suite). Absorb-reset clears B state so A/B refire fresh.
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


def _cand(**kw):
    from datetime import datetime, timezone
    from analysis.models import SignalCandidate as _SC, EvidenceItem as _EV
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat(timespec="seconds")
    d = dict(signal_id="STG-1", symbol="TSTUSDT", style="DAYTRADE",
             setup_code="PINVAL", setup_name="VIVA-PINVAL", strategy_fa="x",
             direction="LONG", score=8, status="APPROACHING",
             entry_zone_bottom=99.9, entry_zone_top=100.0, planned_entry=99.95,
             sl=98.5, tp1=102.0, tp2=104.0, rr_tp1=2.0, rr_tp2=4.0, bias="BULLISH",
             trigger_timeframe="15m",
             evidence=[_EV("pin", "t", "d", True, 2)],
             confirmations=[], warnings=[], mandatory_gates={"rr": True},
             market={"turnover24h": 1e9, "spread_pct": 0.02, "tick_size": 0.01},
             metadata={"atr": 1.0, "public_code": "STG-1", "touched": True},
             created_at=now, confirmed_at=now)
    d.update(kw)
    return _SC(**d)


# ── stages ────────────────────────────────────────────────────────────
def test_stage_mapping_pct_and_zone():
    from analysis.quality_engine import approach_stage
    c = _cand()  # LONG zone [99.9, 100.0], atr 1.0
    assert approach_stage(c, 99.4)[0] == "FAR"    # 0.50%
    assert approach_stage(c, 99.55)[0] == "A"     # 0.35%
    assert approach_stage(c, 99.7)[0] == "B"      # 0.20%
    assert approach_stage(c, 99.95)[0] == "B"     # inside zone -> B
    assert approach_stage(c, None)[0] == "FAR"    # garbage -> FAR, no crash


def test_stage_atr_legs_and_short():
    from analysis.quality_engine import approach_stage
    c = _cand(metadata={"atr": 10.0})  # wide ATR: pct says A, ATR leg says B
    assert approach_stage(c, 99.4)[0] == "B"
    c2 = _cand(metadata={"atr": 2.0})  # pct says FAR, ATR leg says A
    assert approach_stage(c2, 99.32)[0] == "A"
    s = _cand(direction="SHORT", entry_zone_bottom=100.0, entry_zone_top=100.1,
              metadata={"atr": 1.0})
    assert approach_stage(s, 100.4)[0] == "B"     # SHORT mirrors
    assert approach_stage(s, 100.7)[0] == "FAR"


def test_approaching_entry_behavior_kept():
    from analysis.quality_engine import approaching_entry
    c = _cand()
    assert approaching_entry(c, 99.95) == (True, 0.0)
    assert approaching_entry(c, 99.4)[0] is False
    assert approaching_entry(c, 99.55)[0] is True


# ── stage A: text only, zero fetch/render ─────────────────────────────
def test_stage_a_text_only(monkeypatch):
    import bot.messages_v7 as m7
    import data.fetcher as _f
    monkeypatch.setattr(_f, "get_klines", lambda *a, **k: (_ for _ in ()).throw(AssertionError("A must not fetch")))
    monkeypatch.setattr(m7, "generate_chart", lambda *a, **k: (_ for _ in ()).throw(AssertionError("A must not render")))
    monkeypatch.setattr(m7, "_approaching_caption", lambda *a, **k: "CAP-A")
    sent = {}
    monkeypatch.setattr(m7, "send_message", lambda text, chat=None, **k: sent.setdefault("t", text) and 701 or 701)
    c = _cand()
    assert m7.send_stage_a_watch(c, 99.55, 0.35, 0.0035) is True
    assert sent["t"] == "CAP-A"


# ── stage B: chart + freeze ───────────────────────────────────────────
def _mock_b(monkeypatch, df):
    import bot.messages_v7 as m7
    import data.fetcher as _f
    calls = {"fetch": [], "render_kw": [], "post": [], "mirror": []}
    def fake_klines(symbol, tf, size, **k):
        calls["fetch"].append((tf, size))
        return _df()
    monkeypatch.setattr(_f, "get_klines", fake_klines)
    def fake_render(frame, cand, confirmed=False, **k):
        calls["render_kw"].append((confirmed, k.get("preconfirm_tool")))
        return b"PNG-B"
    monkeypatch.setattr(m7, "generate_chart", fake_render)
    monkeypatch.setattr(m7, "_approaching_caption", lambda *a, **k: "CAP-B")
    def fake_post(chart, text, target, **k):
        calls["post"].append((chart, text, k.get("reply_to")))
        return (111, 222)
    monkeypatch.setattr(m7, "_post_chart_then_text", fake_post)
    monkeypatch.setattr(m7, "_sig_mirror", lambda *a, **k: calls["mirror"].append(a[1]))
    return m7, calls


def test_stage_b_posts_chart_and_freezes(monkeypatch):
    m7, calls = _mock_b(monkeypatch, _df())
    c = _cand()
    assert m7.send_stage_b_ready(c, _df(), 99.7, 0.2) is True
    assert calls["render_kw"] == [(False, True)]  # READY-mode render
    assert calls["post"][0][0] == b"PNG-B"
    assert "فریز شد" in calls["post"][0][1]
    assert c.metadata.get("stage_b_sent") is True
    assert c.metadata.get("stage_b_chart_mid") == 111
    assert c.metadata.get("stage_b_text_mid") == 222
    snap = c.metadata.get("confirmed_snapshot") or {}
    assert snap.get("entry") == 99.95  # frozen at B
    assert not any(size >= 140 for _, size in calls["fetch"])  # frame given: no big fetch


def test_stage_b_bypass_fetch_when_no_frame(monkeypatch):
    m7, calls = _mock_b(monkeypatch, None)
    c = _cand()
    assert m7.send_stage_b_ready(c, None, 99.7, 0.2) is True
    assert any(tf == "15m" and size >= 140 for tf, size in calls["fetch"])


# ── stage C: activation reply, zero fetch/render ──────────────────────
def test_stage_c_activation_reply(monkeypatch):
    import bot.messages_v7 as m7
    import data.fetcher as _f
    from analysis.quality_engine import freeze_confirmed_snapshot
    from analysis.trade_management import build_ladder as _bl
    monkeypatch.setattr(_f, "get_klines", lambda *a, **k: (_ for _ in ()).throw(AssertionError("C must not fetch")))
    monkeypatch.setattr(m7, "generate_chart", lambda *a, **k: (_ for _ in ()).throw(AssertionError("C must not render")))
    sent = {}
    def fake_send(text, chat=None, **k):
        sent["t"] = text
        sent["reply"] = k.get("reply_to_message_id")
        return 333
    monkeypatch.setattr(m7, "send_message", fake_send)
    monkeypatch.setattr(m7, "_sig_mirror", lambda *a, **k: None)
    c = _cand()
    c.metadata["target_ladder"] = _bl(c.planned_entry, c.sl, c.direction, c.market, c.tp2,
                                      structural_tp1=c.tp1, fee_pct=0.0018)
    freeze_confirmed_snapshot(c)
    c.metadata["stage_b_sent"] = True
    c.metadata["stage_b_text_mid"] = 222
    c.metadata["stage_b_chart_mid"] = 111
    c.metadata["stage_b_at"] = c.created_at
    c.metadata["activation_price"] = 100.2
    assert m7.send_confirmed(c, None) is True
    assert sent["reply"] == 222  # replies to the B chart text
    assert "فعال شد" in sent["t"]
    assert "100.2" in sent["t"].replace("100.20", "100.2")
    assert c.metadata.get("confirmation_message_sent") is True
    assert c.metadata.get("confirmation_chart_sent") is True
    assert c.metadata.get("confirmation_chart_message_id") == 333


# ── absorb reset clears B state ───────────────────────────────────────
def test_absorb_reset_clears_b_state():
    from database.candidate_store import absorb_update_into_chain, init_candidate_store
    init_candidate_store()
    holder = _cand()
    holder.approaching_sent = True
    holder.status = "APPROACHING"
    holder.metadata["stage_b_sent"] = True
    holder.metadata["stage_b_chart_mid"] = 111
    holder.metadata["confirmed_snapshot"] = {"entry": 99.95}
    fresh = _cand(signal_id="STG-2", entry_zone_bottom=98.0, entry_zone_top=98.1,
                  planned_entry=98.05, metadata={"atr": 1.0})
    absorb_update_into_chain(holder, fresh)
    assert holder.status == "EDUCATIONAL"
    assert holder.approaching_sent is False
    assert "stage_b_sent" not in holder.metadata
    assert "stage_b_chart_mid" not in holder.metadata
    assert "confirmed_snapshot" not in holder.metadata


# ── READY-mode render smoke (real renderer, 3 modes) ──────────────────
def test_ready_mode_render_smoke(monkeypatch):
    import bot.messages_v7 as m7
    import data.fetcher as _f
    monkeypatch.setattr(_f, "get_klines", lambda *a, **k: None)
    from analysis.trade_management import build_ladder as _bl
    c = _cand()
    c.metadata["target_ladder"] = _bl(c.planned_entry, c.sl, c.direction, c.market, c.tp2,
                                      structural_tp1=c.tp1, fee_pct=0.0018)
    frame = _df(n=90)
    a = m7.generate_chart(frame, c, confirmed=False)
    b = m7.generate_chart(frame, c, confirmed=True)
    r = m7.generate_chart(frame, c, confirmed=False, preconfirm_tool=True)
    assert all(isinstance(x, bytes) and len(x) > 1000 for x in (a, b, r))
    assert len(r) != len(a)  # READY draws tools the ANALYSIS chart lacks
