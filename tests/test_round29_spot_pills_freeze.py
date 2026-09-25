"""r29: spot-lane rescue + TP pill monotone order + render freeze.

Live evidence chain: spot lane found 48/day, published 0 for ~2 days while the
channel got nothing — R30's bundle reuse kept `.get()` but the stamp marked
shapes BEFORE the send, so any failed attempt burned them for the window; and
zero visibility (reason/counters) hid the dead sender behind a green «فعال».
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_spot_stamp_has_commit_flag_and_marks_after_success():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "main.py"), encoding="utf-8").read()
    # the dedupe CHECK is read-only; the marker is written after publish
    assert "_spot_stamp(key, window, commit=False)" in src
    assert 'stats["published"] += 1' in src and "_spot_stamp(key, window)" in src
    # diagnostic counters land in the surfaced stats
    for counter in ("stamp_skip", "send_fail", "chart_fail", "last_error",
                    "budget_left", "dur_s"):
        assert f'"{counter}' in src, counter


def test_zero_sent_is_loud_not_a_green_ok():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "main.py"), encoding="utf-8").read()
    assert '"zero_sent"' in src, "found>0 & published==0 must not masquerade as ok"
    web = open(os.path.join(root, "webapp_viva.py"), encoding="utf-8").read()
    assert "zero_sent" in web and "last_error" in web, "app must show the why"


def test_tp_pills_allocate_in_ascending_level_order():
    """«شماره‌گذاری TPها چرا قاطی‌پاتی شده؟» — the finalize loop must iterate
    levels ascending; the old mid-out sort let crowded columns invert the
    numeric order (SHIB 1H: 2,4,5,3,1)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "sorted(_right_specs, key=lambda t: float(t[0]))" in src
    assert '-abs(float(t[0]) - (_lo2 + _hi2) / 2.0)' not in src, "mid-out scrambler removed"


def test_render_freeze_law_is_wired():
    """«از اولین تأیید … چارت نباید شکلش و زومش تغییر بکنه» — confirmed renders
    reuse the frozen window while live price stays inside it; escape recomputes
    and re-freezes (the same legal mutation his TF-bump law notes)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert '"chart_zoom_frozen"' in src
    assert "ax.set_ylim(*_froz28)" in src
    assert "_froz28[0] < _live28 < _froz28[1]" in src


def test_spot_still_imports_clean():
    import main  # noqa: F401  (module-level syntax/runtime guard)
    import bot.messages_v7 as m7  # noqa: F401
    assert callable(m7._smart_y_window)
