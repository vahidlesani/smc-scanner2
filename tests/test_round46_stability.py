"""r46 — the «system is a mess» triage round (Viva 09-27, 03:41).

His report: «اپلیکیشن هم کلا خالی شد»، «از حدود ۲۰ شنبه تاییدها و شناسایی
موقعیت‌ها نزدیک به صفر شد»، «آپدیت‌های زیاد برای شکست‌هایی که تایید نگرفته
بودند هنوز می‌آید»، «روزانه باید جمع‌تر باشه که کندل‌های بیشتری نشون بده».

Ground truth found in the live DB (3050 signals intact — nothing was lost):
  1. The app journal was scoped to "since midnight UTC" — 30 minutes past
     midnight every headline read zero and the app looked wiped.
  2. Chains could post unbounded numbered updates (a BCH chain hit «آپدیت
     ۳۰») — the 09-14 UPDATE-SPAM(3) law was never enforced on this loop.
  3. The 1d chart lookback (96 bars) was tighter than his CryptoCove
     reference — daily/spot breakouts need more visible candles.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _web():
    return open(os.path.join(REPO, "webapp_viva.py"), encoding="utf-8").read()


def _msg():
    return open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()


# ── 1. the app journal is ALL-TIME — midnight can no longer blank it ───────

def test_feed_has_no_midnight_cutoff():
    src = _web()
    assert "WHERE created_at >= {cutoff}" not in src.split("_FEED_SQL")[1].split('"""')[0]
    assert "c.execute(_FEED_SQL)" in src


def test_strategy_and_hits_tables_are_all_time():
    src = _web()
    assert "GROUP BY source" in src
    part = src.split("GROUP BY source")[0][-400:]
    assert "WHERE created_at >=" not in part
    # the hits feed no longer takes a cutoff parameter
    assert 'LIMIT 80\n            """)' in src


def test_empty_state_copy_is_journal_wide():
    src = _web()
    assert "هنوز معاملهٔ بسته‌ای ثبت نشده" in src
    assert "هنوز معاملهٔ بسته‌ای امروز نیست" not in src


# ── 2. updates are capped at three per chain ────────────────────────────────

def test_chain_updates_capped_at_three():
    src = _msg()
    part = src.split('upd_n = int(chain.get("upd_n") or 0) + 1')[1][:400]
    assert "if upd_n > 3:" in part
    assert "return False" in part


# ── 3. the daily tape shows more candles (CryptoCove reference) ────────────

def test_daily_lookback_widened():
    src = _msg()
    assert '"1d": 210' in src   # r52 dictation: 12h/1d → 170-250 (mid 210)
    assert '"1d": 96' not in src
