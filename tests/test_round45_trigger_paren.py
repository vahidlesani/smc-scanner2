"""r45 — the parenthetical trigger-TF law in step-up note texts (Viva 09-26:
«یکی دو خط توضیح بده توی پرانتز ... تایم تریگر رو»). Both ordered note texts
(escape note, span note) must carry «(تایم تریگر: …)» in Persian, mirroring
the r44 chart-title stamp."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_escape_note_carries_trigger_parenthetical():
    from bot.messages_v7 import _escape_note
    out = _escape_note("15m", "1h", 7)
    assert "تایم تریگر: ۱۵ دقیقه" in out, out
    assert "۱ ساعته" in out

def test_span_note_carries_trigger_parenthetical():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    part = src.split("def _lifecycle_view_plan")[1].split("def _lifecycle_chart_frame")[0]
    assert "روی تایم {_TF_FA.get(_view8" in part
    assert "(تایم تریگر: {_TF_FA.get(base, base.upper())})." in part
