"""R99q19 — SETUP GEOMETRY LAWS (Viva 10-16, the 16:5x chart batch).

Verbatim: «چرا تکنوکلاسیک هنوز حتی یک پترن درست نمی‌ده ؟؟ ترندلاین‌های ول از
گذشته .. زوم اشتباه .. پترن رو نمی‌شناسه .. تعداد کندل رو تشخیص نمی‌ده .. از
پترن‌ها فقط فالینگ وج رو گاهی درست می‌کشن بقیه پترن‌ها رو انگار اصلا نمی‌شناسن
.. حتما درستش کن».

Three laws are pinned:
  1. ONE COORDINATE SPACE — render patterns are fitted on a tail window; the
     TC/ALBROX validators must judge them with the FIT window's live index
     (LIT 1h: 340-bar frame vs 205-bar fit → every sloped pattern died
     «stale-end», only the RANGE band survived, and the chart invented lines).
  2. A REAL SHAPE IS NEVER KILLED FOR ITS NAME — two lines on ≥3 pivots whose
     family differs from the label is relabeled to its own geometry, not thrown
     away (kept = drawn = believable); under-touched noise still dies.
  3. NO INVENTED EDGES — the canvas fallbacks (zone-lane hull / shell refit /
     validated-line fit) may never paint a line that leaves the visible candle
     envelope by more than 2 ATR, and never when the alert's own pattern lines
     are already painted.
"""
import math
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.techclassic import (tc_validate_pattern, tc_candles_for,   # noqa: E402
                                  tc_refine_geometry, _TC_FRAME_CAP)
from analysis.albrox import albrox_candles_for                            # noqa: E402
from analysis.render_kit import pattern_live_index                       # noqa: E402


def _df(n, lo=50.0, hi=60.0):
    ts = pd.date_range("2026-09-01", periods=n, freq="1h")
    mid = (lo + hi) / 2
    return pd.DataFrame({"timestamp": ts, "open": mid,
                         "high": [hi] * n, "low": [lo] * n, "close": mid,
                         "volume": [1.0] * n})


def _pat(ptype, lines):
    return {"type": ptype, "lines": lines}


def _line(side, x0, x1, npts, slope=0.0, icept=55.0):
    return {"side": side, "x0": x0, "x1": x1, "slope": slope, "intercept": icept,
            "log_fit": False,
            "points": [{"ts": f"2026-10-{1 + i:02d} 00:00:00", "price": 55.0}
                       for i in range(npts)]}


class _Cand:
    def __init__(self, md, tf="1h"):
        self.metadata = md
        self.trigger_timeframe = tf
        self.setup_code = "TECHCLASSIC"


def test_r99q19_live_index_follows_the_fit_window():
    """LIT 1h chain: 340-bar frame, 205-bar fit window."""
    md = {"pattern_frame_bars": 205}
    assert pattern_live_index(md) == 204
    # legacy chain without the stamp: the longest stored x1 is the fallback
    legacy = {"render_patterns": [_pat("WEDGE_FALLING", [_line("HIGH", 115, 204, 4)])]}
    assert pattern_live_index(legacy, pats=legacy["render_patterns"]) == 204


def test_r99q19_a_real_shape_survives_a_label_mismatch():
    """His law: «فقط فالینگ وج رو گاهی درست می‌کشن» — the others must live too."""
    wedge = _pat("WEDGE_FALLING", [_line("HIGH", 115, 204, 4, -0.006),
                                   _line("LOW", 36, 204, 4, -0.004)])
    keep, reason, new_type = tc_validate_pattern(wedge, "CHANNEL", 204, "1h")
    assert keep is True
    assert reason == "relabel-shape"
    assert new_type == "WEDGE_FALLING"        # honest label = drawn geometry
    # under-touched junk still dies
    noise = _pat("WEDGE_FALLING", [_line("HIGH", 100, 180, 1),
                                   _line("LOW", 110, 180, 1)])
    assert tc_validate_pattern(noise, "WEDGE", 180, "1h")[0] is False


def test_r99q19_anchor_cap_follows_the_tf_and_the_shape():
    """A 7-day wedge on 4 pivots is not «ancient trash» (LIT 1h, x0 115→204)."""
    pat = _pat("WEDGE_FALLING", [_line("HIGH", 115, 204, 4, -0.006),
                                 _line("LOW", 36, 204, 4, -0.004)])
    assert tc_validate_pattern(pat, "WEDGE", 204, "1h")[0] is True
    # a RELIC (400 bars of history) still dies on every TF
    relic = _pat("WEDGE_FALLING", [_line("HIGH", 5, 204, 4, -0.006),
                                   _line("LOW", 12, 204, 4, -0.004)])
    assert tc_validate_pattern(relic, "WEDGE", 204, "1h") == (False, "ancient-anchor", None)
    assert tc_validate_pattern(relic, "WEDGE", 204, "3d")[0] is True   # 3d cap = 270


def test_r99q19_refine_keeps_a_sloped_pattern_end_to_end():
    """The whole LIT 1h story: with the fit window known, the wedge is minted."""
    md = {"pattern_frame_bars": 205,
          "tl_pattern": "CHANNEL_ASCENDING",
          "render_patterns": [_pat("RANGE", []),
                              _pat("WEDGE_FALLING", [_line("HIGH", 115, 204, 4, -0.006),
                                                     _line("LOW", 36, 204, 4, -0.004)])]}
    cand = _Cand(md)
    tc_refine_geometry(cand, bundle={"1h": _df(340)})
    types = [p.get("type") for p in cand.metadata["render_patterns"]]
    assert "WEDGE_FALLING" in types, f"wedge lost: {types} ({cand.metadata.get('tc_dropped')})"
    assert cand.metadata["tc_pattern_span"] >= 80


def test_r99q19_candle_ceiling_follows_the_pattern():
    """«سقفش با توجه شکل و نوع پترن، تایم‌فریم و ترندلاین» — the R99q9 per-TF
    ceiling stays the law; the bug was pattern_span collapsing to 0 because
    every sloped pattern died, so the frame never reached the cap."""
    assert tc_candles_for("1h", 168, "WEDGE_FALLING") == 170      # span+pad, ≤ cap
    assert tc_candles_for("1h", 0, "WEDGE_FALLING") == 120        # the floor
    assert albrox_candles_for("1h", 117, "TRIANGLE") == 180   # span+2×pad, ≤ cap
    # runaway span is stopped by the TF cap (never a road)
    assert tc_candles_for("1h", 4000, "WEDGE_FALLING") == _TC_FRAME_CAP["1h"]
    assert tc_candles_for("15m", 4000, "WEDGE_FALLING") == _TC_FRAME_CAP["15m"]


def test_r99q19_wild_line_gate_and_twin_drop_exist_in_the_painter():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "def _wild_line9(" in src                 # LOCAL envelope gate
    assert src.count("_wild_line9(") >= 2           # gated where a fit is faked
    assert "_painted99q19" in src                   # never invent over drawn edges
    assert "R99q19 EXACT-TWIN DROP" in src          # DASH 4H painted one triangle 3×
