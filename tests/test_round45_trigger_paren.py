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
    """Viva 10-10: the span-based step-up is RETIRED (only a tool escape may
    step the view up) — but the escape note keeps speaking Persian with the
    trigger-TF parenthetical."""
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    plan = src.split("def _lifecycle_view_plan")[1].split("def _lifecycle_chart_frame")[0]
    assert "کش می‌آمد" not in plan
    esc = src.split("def _escape_note")[1].split("def _lifecycle_view_plan")[0]
    assert "تایم تریگر" in esc
