"""r41 — the REAL-LIVE app round (Viva 09-26 evening messages).

His asks, verbatim:
  «نردبان لانگ و شورت در اپ اشتباه میشه … نمیشه دقیقا از دیتای تلگرام
   استفاده بکنه؟؟»
     → the chart fallback restores the PUBLISH-TIME build_ladder state
       (target_state_json: targets/weights/entry/original_sl) VERBATIM plus
       the real entry-zone columns — no more fake two-pill rebuilds.
  «اپ رو لایو واقعی بکن … بدون تاخیر … هم پرپچوآل و هم اسپات»
     → /app/api/version (one cheap SQL fingerprint) polled every 10s; the
       heavy state is pulled ONLY on change (Railway CPU stays flat).
  «در کارت هرکدام تیپی‌ها و قیمت لایو و استاپ … اگر هرکدوم تاچ شد نوتیف بیاد»
     → cards show ENTRY / trailing SL / TP1..TP3 with ✓ / LIVE; a 10s price
       probe (one cached public ticker call) fires toast+Notification on
       every TP touch, stop hit — trailing shown as SL ↟.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return open(os.path.join(REPO, "webapp_viva.py"), encoding="utf-8").read()


# ── 1. app chart = the Telegram tool, verbatim ──────────────────────────────

def _fake_row():
    return {
        "signal_id": "viva-tech-R41", "symbol": "SEIUSDT", "source": "TECHCLASSIC",
        "public_code": "R41-1", "market_json": "{}", "direction": "LONG",
        "entry": 0.0731, "sl": 0.0716, "tp1": 0.0739, "tp2": 0.0746,
        "score": 9, "confirmed": True, "trigger_timeframe": "15m",
        "trade_style": "DAYTRADE", "setup_code": "TECHCLASSIC",
        "created_at": "2026-09-26 09:18", "confirmed_at": "2026-09-26 09:20",
        "strategy_fa": "الگوی کلاسیک پیوتی",
        "target_state_json": json.dumps({
            "entry": 0.07308, "original_sl": 0.07162, "current_sl": 0.07313,
            "targets": [0.07396, 0.07465, 0.07535],
            "weights": [40.0, 30.0, 30.0], "hit_index": 1,
        }),
        "entry_zone_bottom": 0.07288, "entry_zone_top": 0.07338,
    }


def test_candidate_from_row_restores_publish_ladder_verbatim():
    import webapp_viva as W
    cand = W._candidate_from_row(_fake_row())
    md = cand.metadata
    lad = md["target_ladder"]
    assert lad["targets"] == [0.07396, 0.07465, 0.07535]   # NOT [tp1, tp2]
    assert lad["weights"] == [40.0, 30.0, 30.0]
    assert abs(cand.planned_entry - 0.07308) < 1e-12        # ladder entry
    assert abs(cand.sl - 0.07162) < 1e-12                   # original stop
    assert abs(cand.entry_zone_bottom - 0.07288) < 1e-12    # real zone columns
    assert abs(cand.entry_zone_top - 0.07338) < 1e-12


def test_candidate_from_row_legacy_row_falls_back_clean():
    import webapp_viva as W
    row = _fake_row()
    row["target_state_json"] = "{}"
    row["entry_zone_bottom"] = 0
    row["entry_zone_top"] = 0
    cand = W._candidate_from_row(row)
    assert cand.metadata["target_ladder"]["targets"] == [0.0739, 0.0746]
    assert abs(cand.entry_zone_bottom - 0.0731 * 0.999) < 1e-12


def test_chart_fallback_selects_target_state_column():
    src = _src()
    assert '"target_state_json", "entry_zone_bottom", "entry_zone_top"' in src


# ── 2. real-live endpoints ──────────────────────────────────────────────────

def test_version_endpoint_exists_and_is_no_store():
    src = _src()
    assert '@viva_app.route("/app/api/version")' in src
    assert "MAX(tp1_hit_at),'') FROM signals" in src   # one cheap query
    part = src.split('def api_version')[1].split("def api_prices")[0]
    assert "no-store" in part


def test_prices_endpoint_cached_and_fail_open():
    src = _src()
    assert '@viva_app.route("/app/api/prices")' in src
    part = src.split("def api_prices")[1][:1600]
    assert ">= 10" in part                    # 10s in-process cache
    assert "except Exception" in part         # fail-open


# ── 3. live cards + touch notifications ─────────────────────────────────────

def test_feed_rows_carry_ladder_view_fields():
    src = _src()
    assert "ladder_targets=_lv41" in src or "ladder_targets=" in src
    assert "current_sl=" in src and "sl_moved=" in src
    assert "tp3_hit" in src


def test_ladder_view_parses_state():
    import webapp_viva as W
    v = W._ladder_view(json.dumps({
        "entry": 100.0, "original_sl": 98.0, "current_sl": 100.15,
        "targets": [102.0, 104.0, 106.0], "weights": [40.0, 30.0, 30.0],
        "hit_index": 2}))
    assert v["targets"] == [102.0, 104.0, 106.0]
    assert v["hit_index"] == 2
    assert abs(v["current_sl"] - 100.15) < 1e-12
    assert v["sl_moved"] is True
    v2 = W._ladder_view("{}")
    assert v2["targets"] == [] and v2["current_sl"] is None and not v2["sl_moved"]


def test_card_shows_tp3_trailing_and_live():
    src = _src()
    assert "ladder_targets[2]" in src          # TP3 pill on the card
    assert "SL TRAIL" in src                   # trailing-stop marker
    assert "LIVE" in src.split("function sigCard")[1][:1400]


def test_touch_notifications_wired():
    src = _src()
    assert "function fireTouch" in src
    assert "pollPrices" in src
    assert "تاچ شد" in src                     # TP touch message (Persian)
    assert "TOUCH[key]" in src                 # one notification per event


# ── 4. MTF/refine parity across setups ─────────────────────────────────────

def test_albrox_wires_the_same_htf_enrich():
    src = open(os.path.join(REPO, "analysis", "setups_experimental.py"),
               encoding="utf-8").read()
    part = src.split("def detect_albrox")[1].split("ALBROX_DETECTORS")[0]
    assert "enrich_render" in part
    assert 'htf_df=bundle.get("4h") or bundle.get("1h")' in part


def test_every_other_setup_passes_htf_context():
    tl = open(os.path.join(REPO, "analysis", "setups_experimental.py"),
              encoding="utf-8").read()
    v7 = open(os.path.join(REPO, "analysis", "setups_v7.py"),
              encoding="utf-8").read()
    # TLBREAK watch lane
    assert 'enrich_render(candidate, trigger_df,\n                              htf_df=bundle.get("4h") or bundle.get("1h"))' in tl
    # v7 common lane (TECHCLASSIC + core setups)
    assert "enrich_render(_cand, trigger_df, htf_df=context_df)" in v7
    # pin family lane (PINVAL — the merged PINWALL LEGACY)
    pin = tl.split("def detect_pinbar_zone")[1].split("def _pinwall_quality_score")[0]
    assert "enrich_render" in pin and 'htf_df=bundle.get("4h") or bundle.get("1h")' in pin
