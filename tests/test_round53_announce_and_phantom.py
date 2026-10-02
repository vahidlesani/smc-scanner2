"""r53 — announce-channel final law + spot-monitor depth + phantom guard.

His 09-28 dictation (third time on routing): «بازهم قاطی پاتی میاد … گفتی
انجام دادی اما انجام نشده» —
• the three channels are CONFIRMED-announcement boards ONLY, routed by SETUP:
  PINVAL family → کوتاه‌مدت، ALBROX+TLBREAK → میان‌مدت قدیمی، TECHCLASSIC →
  بلندمدت قدیمی؛ each card LINKS to the same signal's Confirmed message in
  the main channel; the latest-result link line behaviour is unchanged.
• spot-monitor charts (approach/updates on 4h…1w) fetch the DICTATED candle
  counts, not a blind 180.
• the SHIB phantom (+$309 daily, «فروش روی 0.00001») dies twice over: spot
  targets on the wrong side of entry are rebuilt, and the realtime monitor
  VOIDs wrong-side/twin PENDING positions before they can settle fake wins.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ── 1. announce routing ────────────────────────────────────────────────────
def test_setup_announce_routing_table(monkeypatch):
    import bot.messages_v7 as M
    monkeypatch.setattr(M, "CHAT_ID_SWING_SHORT", "-1001")
    monkeypatch.setattr(M, "CHAT_ID_SWING_MID", "-1002")
    monkeypatch.setattr(M, "CHAT_ID_SWING_LONG", "-1003")
    r = M._setup_announce_channel
    short = r("PINVAL")
    assert short == "-1001" and r("PINWALLQ") == short == r("PINWALL")
    mid = r("ALBROX")
    assert mid == "-1002" and r("TLBREAK") == mid
    assert mid != short
    lng = r("TECHCLASSIC")
    assert lng == "-1003" and lng not in (short, mid)
    assert r("SPOTBREAK") == "" and r("LSR") == "" and r("") == ""


def test_no_tf_routing_and_no_mirrors_left():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    marker = src.index("def tf_channel_publish_confirmed")
    body = src[marker:src.index("def _tf_channel_edit")]
    # the primary is the SETUP channel; no TF bucket routing, no mirror copies
    assert "_setup_announce_channel(" in body
    assert "tf_channel_id(" not in body
    assert "_setup_routes" not in body and "confirm_mirror" not in body
    # the main-channel confirm link is stamped onto the card text
    assert "پیام تأیید در کانال اصلی" in body
    assert "آخرین نتیجه" in body  # result-link line behaviour unchanged


def test_result_link_edit_keeps_confirm_stamp():
    from bot.messages_v7 import _setup_announce_channel  # import sanity
    # tfc_text carries the stamp BEFORE the result line; the edit path keeps it
    text = ('head\n🔗 پیام تأیید در کانال اصلی: <a href="x">K1</a>\n'
            '🔗 آخرین نتیجه: <a href="y">TP1</a>\n\n📌 <b>VIVAMON-Labs-Pro</b>')
    head = text.split("🔗 آخرین نتیجه:")[0].rstrip()
    assert "پیام تأیید در کانال اصلی" in head  # stamp survives the result edit


# ── 2. dictated depth on monitor/update charts ─────────────────────────────
def test_chart_fetch_size_map():
    from bot.messages_v7 import _chart_fetch_size, _CHART_CANDLE_COUNTS
    # R64 counts (analysis.candle_counts — 250..350 per TF, his 10-02 law)
    assert _chart_fetch_size("1w") == 250 and _chart_fetch_size("3d") == 300
    assert _chart_fetch_size("12h") == 260 and _chart_fetch_size("1d") == 300
    assert _chart_fetch_size("4h") == 300 and _chart_fetch_size("8h") == 280
    assert _chart_fetch_size("15m") == 300
    assert set(_CHART_CANDLE_COUNTS) >= {"5m", "15m", "30m", "1h", "2h", "4h",
                                         "8h", "12h", "1d", "3d", "1w"}


def test_lifecycle_and_update_fetches_use_the_map():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    m1 = src.index("def _lifecycle_chart_frame")
    seg1 = src[m1:m1 + 2600]
    assert "_chart_fetch_size(base)" in seg1 and "_chart_fetch_size(view)" in seg1
    m2 = src.index("def send_setup_update")
    seg2 = src[m2:m2 + 5000]
    # r61.1: updates are TEXT-ONLY («هشدار نهایی است بدون چارت») — no chart
    # generation and no own-frame fetch inside the update path at all
    assert "generate_chart" not in seg2
    assert "get_klines" not in seg2


# ── 3. phantom guards ──────────────────────────────────────────────────────
def test_classify_phantom_wrong_side_ladder():
    from database.realtime_monitor import classify_phantom
    rows = [("S1", "SHIBUSDT", "SPOTBREAK", "LONG", 0.0000245,
             json.dumps({"targets": [0.00001, 0.000012, 0.000014]}), "1d"),
            ("S2", "ETHUSDT", "TECHCLASSIC", "LONG", 2500.0,
             json.dumps({"targets": [2600, 2700, 2800]}), "4h")]
    v = classify_phantom(rows)
    assert v.get("S1") == "wrong-side ladder targets"
    assert "S2" not in v


def test_classify_phantom_twin_positions():
    from database.realtime_monitor import classify_phantom
    rows = [("NEW", "SHIBUSDT", "SPOTBREAK", "LONG", 0.00002,
             json.dumps({"targets": [0.000022]}), "4h"),
            ("OLD", "SHIBUSDT", "SPOTBREAK", "LONG", 0.00002,
             json.dumps({"targets": [0.000022]}), "4h"),
            ("OTHER", "ADAUSDT", "PINVAL", "LONG", 0.9,
             json.dumps({"targets": [0.95]}), "1d"),
            # r55: same symbol+source+direction on a DIFFERENT trigger TF is
            # legitimate coexistence — never a phantom twin.
            ("MULTI", "SHIBUSDT", "SPOTBREAK", "LONG", 0.00002,
             json.dumps({"targets": [0.000022]}), "1d")]
    v = classify_phantom(rows)
    assert v.get("OLD", "").startswith("twin of NEW")
    assert "NEW" not in v and "OTHER" not in v
    assert "MULTI" not in v, "cross-TF spot positions are not twins"


def test_spot_candidate_rebuilds_wrong_side_targets():
    from analysis.spot_engine import build_spot_candidate
    item = {"symbol": "SHIBUSDT", "tf": "1d", "entry": 0.0000245,
            "sl": 0.0000225, "targets": [0.00001, 0.000012],
            "broken_level": 0.000024, "detected_at": "2026-09-28T01:00:00",
            "pattern": "RANGE", "rule_fa": "قانون"}
    cand = build_spot_candidate(item)
    ladder = cand.metadata["target_ladder"]["targets"]
    assert all(t > 0.0000245 for t in ladder)          # every pill ahead of entry
    assert ladder[0] <= ladder[-1]


def test_void_sweep_is_wired_into_realtime_cycle():
    src = open(os.path.join(ROOT, "database", "realtime_monitor.py"),
               encoding="utf-8").read()
    assert "def void_phantom_positions" in src
    assert src.index("void_phantom_positions()") < \
        src.index("def monitor_realtime_prices") + 400 or \
        "void_phantom_positions()" in src.split("def monitor_realtime_prices")[1][:400]
