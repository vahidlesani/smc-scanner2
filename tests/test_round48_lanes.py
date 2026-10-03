"""r48 — the new trigger lanes + final channel mapping (Viva 09-27, 04:50).

His words, verbatim:
  «تایم‌های تریگر ۳۰ دقیقه و ۲ ساعته باید بعنوان تریگر جدید به ۴ ستاپ
   فیوچرز اضافه بشه» + «برای ۳۰ دقیقه و ۲ ساعته هم از فرمول بدست بیاد
   دوباره اسکن نشه» — same engines, two more lanes, zero new pipelines.
  «به‌جای جدا سازی تایمها ستاپ‌ها رو جدا کردیم … فقط کانال میان مدت قبلی
   دوتا ستاپ میگیره» — the three renamed channels:
     VIVA-MON-Pival      (TF_15M_1H) → PINVAL family, all its TFs
     VIVA-MON-AlboroxTLB (TF_2H_4H)  → ALBROX + TLBREAK (the only 2-setup one)
     VIVA-MON-TECH       (TF_1D)     → TECHCLASSIC, all its TFs
  «قرار بود فیوچرز هم لگاریتمی باشه … لگاریتمی از جایی فعال میشه که نیاز
   باشه — در تایم کوتاه که فرق نداره» — LOG axis when the window spans ≥30%.
"""
from __future__ import annotations

import os
import sys
import types

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 1. the two new trigger lanes ride the SAME engines ─────────────────────

def test_swing_engine_scans_four_streams_with_profiles():
    src = open(os.path.join(REPO, "analysis", "quality_engine.py"), encoding="utf-8").read()
    part = src.split("class SwingEngine")[1].split("class ")[0]
    assert '("30m", ("2h", "1h", "30m"))' in part
    assert '("2h", ("1d", "4h", "2h"))' in part
    assert '("1h", ("1d", "4h", "1h"))' in part and '("4h", ("1d", "4h", "4h"))' in part


def test_pintval_swing_lane_covers_four_tfs():
    src = open(os.path.join(REPO, "analysis", "setups_experimental.py"), encoding="utf-8").read()
    assert '"SWING": ("30m", "1h", "2h", "4h")' in src


def test_bundle_and_stamps_carry_new_frames():
    src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    assert '("1d", "4h", "2h", "1h", "30m", "15m", "5m")' in src
    assert 'for tf in ("15m", "30m", "1h", "2h", "4h", "1d"):' in src


def test_two_hour_frame_derives_from_fifteen_minute_base():
    from data.fetcher import _derive_from_base
    ts = pd.Timestamp("2026-09-27 00:00")
    base = pd.DataFrame([dict(timestamp=ts + pd.Timedelta(minutes=15 * i),
                              open=1.0, high=1.01, low=0.99, close=1.005,
                              volume=10.0) for i in range(32)])
    out = _derive_from_base(base, None, None, ("2h",), {})
    df2 = out.get("2h")
    assert df2 is not None and len(df2) == 4          # 8×15m = 2h bars
    assert df2["close"].iloc[-1] == base["close"].iloc[-1]


def test_expiry_map_has_the_new_tfs():
    from analysis.setups_v7 import EXPIRY_HOURS_BY_TRIGGER
    assert EXPIRY_HOURS_BY_TRIGGER["30m"] == 48
    assert EXPIRY_HOURS_BY_TRIGGER["2h"] == 168


# ── 2. the final channel mapping (three renamed channels) ──────────────────

def test_routing_map_is_setup_final():
    # r53 (Viva 09-28: «بازهم قاطی پاتی میاد … گفتی انجام دادی اما انجام نشده»):
    # the channel is chosen by SETUP ONLY via _setup_announce_channel, and the
    # mirror block is GONE — one signal lands in exactly ONE announce channel.
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    part = src.split("def _setup_announce_channel")[1].split("def tf_channel_publish_confirmed")[0]
    assert '"PINVAL", "PINWALLQ", "PINWALL"' in part
    assert "CHAT_ID_SWING_SHORT" in part
    assert '"ALBROX", "TLBREAK"' in part and "CHAT_ID_SWING_MID" in part
    assert '"TECHCLASSIC"' in part and "CHAT_ID_SWING_LONG" in part
    assert "_setup_routes" not in src          # the TF-routed primary + mirrors are gone
    assert 'tf_channel_id(str(candidate.trigger_timeframe or ""))' not in src


def test_legacy_tf_mirror_is_gone():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert '.get(_tf32)) if not chat_override else None' not in src
    assert "TF-channel mirror failed" not in src


def test_swing_channel_constants_read_the_tf_env_names():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'os.getenv("CHAT_ID_TF_15M_1H"' in src
    assert 'os.getenv("CHAT_ID_TF_2H_4H"' in src
    assert 'os.getenv("CHAT_ID_TF_1D"' in src


# ── 3. futures LOG axis, threshold-gated ───────────────────────────────────

def test_log_axis_is_threshold_based():
    """r57→R66 (Viva: «چارت حتماً لگاریتمی باشه، در اسپات و فیوچرز»): the
    price axis is LOG on EVERY chart — the old spot/span>=1.30 gate is gone,
    the plain-formatter kit (_log_axis_decorate) stays mandatory on the site."""
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert 'use_log = True' in src
    assert 'ax.set_yscale("log")' in src
    assert 'if _is_spot or _span48 >= 1.30:' not in src
    assert 'if _is_spot:\n            try:\n                ax.set_yscale' not in src
