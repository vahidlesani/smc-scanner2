"""r44 — the chart-TF stamp law (Viva 09-26, night).

His words, verbatim:
  «اگر تایم ۱ ساعته چارت رو میسازه همون تایم ۱ ساعته بخوره … هر چارتی تایم
   خودش رو باید بگیره» and for step-up charts: «کنارش داخل پرانتز بزنه مثلا
   ۱۵ دقیقه — تا متوجه بشیم تریگر ۱۵ دقیقه است و چارت بعلت عدم تغییر ابزار
   نردبان لانگ و شورت با تایم بالاتر نشان داده شده».

The bug he screenshotted: an initial-warning chart drawn on 1h candles
stamped «15M» — the title used the TRIGGER field, never the drawn tape.
r44: the stamp is inferred from the candle spacing actually rendered, and a
no-tool-change step-up prints «1H (TRIG 15M)».
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cand(trigger="15m", view=None):
    md = {"chart_view_tf": view} if view else {}
    return SimpleNamespace(trigger_timeframe=trigger, metadata=md)


def _frame(minutes: float, n=8) -> pd.DataFrame:
    ts = pd.Timestamp("2026-09-26 12:00:00")
    return pd.DataFrame({"timestamp": [ts + pd.Timedelta(minutes=minutes * i)
                                       for i in range(n)]})


# ── 1. inference reads the tape, not the trigger field ─────────────────────

def test_infer_reads_one_hour_tape():
    from bot.messages_v7 import _infer_chart_tf
    assert _infer_chart_tf(_frame(60), _cand(trigger="15m")) == "1h"


def test_infer_reads_trigger_matching_tape():
    from bot.messages_v7 import _infer_chart_tf
    assert _infer_chart_tf(_frame(15), _cand(trigger="15m")) == "15m"
    assert _infer_chart_tf(_frame(240), _cand(trigger="4h")) == "4h"


def test_infer_handles_aggregated_spot_tapes():
    from bot.messages_v7 import _infer_chart_tf
    assert _infer_chart_tf(_frame(4320), _cand(trigger="1d")) == "3d"


def test_infer_falls_back_on_tiny_or_broken_tape():
    from bot.messages_v7 import _infer_chart_tf
    assert _infer_chart_tf(_frame(60, n=2), _cand(trigger="15m")) == "15m"
    assert _infer_chart_tf(None, _cand(trigger="15m")) == "15m"


# ── 2. the stamp token: own TF, trigger in parentheses on step-ups ─────────

def test_token_plain_when_tape_matches_trigger():
    from bot.messages_v7 import _chart_tf_token
    assert _chart_tf_token(_cand(trigger="15m"), _frame(15)) == "15M"


def test_token_parenthetical_on_step_up():
    from bot.messages_v7 import _chart_tf_token
    assert _chart_tf_token(_cand(trigger="15m"), _frame(60)) == "1H (TRIG 15M)"
    # r52: the TAPE wins — a stale chart_view_tf (SUI «4h tape stamped 15M»)
    # must never outrank the frame's own spacing; metadata is only a fallback
    # when inference fails.
    assert _chart_tf_token(_cand(trigger="15m", view="2h"),
                           _frame(60)) == "1H (TRIG 15M)"


# ── 3. the title block really uses the token ───────────────────────────────

def test_chart_title_uses_drawn_tf_token():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "_tf_disp = _chart_tf_token(candidate, frame)" in src
    assert 'f"{candidate.symbol}  •  {_tf_disp}' in src
    # the old trigger-only title expression is gone
    old = '_tf_disp = str(candidate.trigger_timeframe or md.get("pin_tf") or "").upper()'
    assert old not in src
