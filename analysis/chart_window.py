"""Viva 10-09 NEED-BASED chart window (his «تعداد کندل هوشمند» law).

One shared ruler for BOTH renderers (futures ivory + spot CryptoCove):

  • the window shows what the TRADE needs — the pattern's defining anchors
    + the live block + a context margin. A 90-bar triangle shows ~90 bars, a
    250-bar triangle ~250: the count is a CONSEQUENCE, never a setting.
    (His STX-15M «چرا ۳۰۰ کندل؟»: the anchors spanned ~170 — need shows ~185,
    no cap involved.)
  • NO maximum (his «محدودیت نباید باشه») — only a 45-bar minimum floor.
  • two-sided shapes (triangle / wedge / channel / range) show the FULL body
    (earliest anchor → live): the formation IS the decision context.
  • SINGLE trendlines show from the second-to-last touch: the ancient first
    touch is represented by the PROJECTED line (frozen geometry draws the
    same line at any window), not by a month of dead candles.
  • geometry NEVER depends on the window: lines are drawn from frozen
    timestamp-anchored snapshots (r33/R63/R65 + spot snapshot lock), so the
    same setup draws the same lines at 90 or 300 bars.
"""
from __future__ import annotations

from typing import Dict, List, Optional

NEED_MARGIN = 14      # context bars before the first needed anchor
# Viva 10-09: NO floor and NO ceiling on the count (his «بدون محدودیت کف و
# سقف») — NEED_MIN_BARS is DELETED; the live block is the only anchor and
# the count is purely need + live + margin.

# the live block the trade lives on, per chart TF (a floor, never a cap)
LIVE_BLOCK_BY_TF = {
    "5m": 60, "15m": 60, "30m": 60, "1h": 60, "2h": 60,
    "4h": 60, "8h": 60, "12h": 60,
    "1d": 45, "3d": 30, "1w": 30,
}

TWO_SIDED_SHAPES = ("converging", "parallel")


def live_block_for_tf(tf: str) -> int:
    return int(LIVE_BLOCK_BY_TF.get(str(tf or "").lower(), 60))


def is_two_sided(shape: str) -> bool:
    return str(shape or "single") in TWO_SIDED_SHAPES


def ref_touch(points: List[Dict], two_sided: bool) -> Optional[Dict]:
    """The window's reference touch of ONE drawn line.

    Two-sided shapes anchor on the FIRST touch (full body); single lines on
    the SECOND-TO-LAST touch (recent validation — the ancient first touch
    projects). Returns None when the line carries no points.
    """
    pts = [p for p in (points or []) if isinstance(p, dict)]
    if not pts:
        return None
    if two_sided or len(pts) < 2:
        return pts[0]
    return pts[-2]


def need_start(n_total: int, refs_idx: List[int],
               live_block: int = 60, margin: int = NEED_MARGIN) -> int:
    """First visible bar index for a need-based window.

    ``refs_idx`` — pre-selected reference positions in frame coordinates
    (via ref_touch per drawn line, plus any must-show indices). Empty →
    live block only. Returns start in [0, n-45]; NO upper clamp.
    """
    n = max(int(n_total or 0), 1)
    refs = sorted(int(a) for a in (refs_idx or []) if a is not None)
    if refs:
        start = min(int(refs[0]) - int(margin), n - int(live_block))
    else:
        start = n - int(live_block)
    start = max(0, int(start))
    return int(start)


def need_count(n_total: int, refs_idx: List[int],
               live_block: int = 60, margin: int = NEED_MARGIN) -> int:
    """Bar COUNT of the need-based window (convenience over need_start)."""
    return int(n_total) - need_start(n_total, refs_idx, live_block, margin)
