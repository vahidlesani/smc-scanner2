"""r29c: §29 channel slope-similarity + labels never on candles.

«چرا انجین تشخیص الگوها اسم الگوها رو اشتباه میزنه؟» — the SHIB 1H case:
rising bottom + mildly-rising top (one edge dominant) was named
CHANNEL_ASCENDING. §29: a channel needs SIMILAR slopes; a dominant-edge pair
is a triangle. And «نوشته هایی روی کندلها می‌افته» — the zone-chip TOP-EDGE
FALLBACK stacked chips straight onto the tape; it now walks above the candle
envelope (the in-box chooser already did).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


class _L:
    def __init__(self, slope, intercept=100.0, first_index=40):
        self.slope = slope
        self.intercept = intercept
        self.first_index = first_index
        self.last_index = 140

    def price_at(self, x):
        return self.slope * (x - self.first_index) + self.intercept


def _mod():
    from analysis import pattern_engine
    return pattern_engine


def test_dominant_edge_pair_is_triangle_not_channel():
    m = _mod()
    # upper rises 0.3 over the span, lower rises 3.0 — lower DOMINATES
    shape = m.classify_shape(_L(slope=0.0021, intercept=100.0),
                             _L(slope=0.021, intercept=60.0), 140)
    assert shape == "TRIANGLE", shape


def test_similar_slopes_stay_a_channel():
    m = _mod()
    shape = m.classify_shape(_L(slope=0.010, intercept=100.0),
                             _L(slope=0.0095, intercept=60.0), 140)
    assert shape == "CHANNEL_ASCENDING", shape


def test_channel_similarity_gate_is_in_source():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "analysis", "pattern_engine.py"),
               encoding="utf-8").read()
    assert "2.2 * max(min(_du, _dl)" in src
    web = open(os.path.join(root, "bot", "messages_v7.py"), encoding="utf-8").read()
    # the chip fallback must consult the candle envelope before printing
    assert "_hi9[_a9:_b9] >= _y9" in web and "_lo9[_a9:_b9] <= _y9" in web
