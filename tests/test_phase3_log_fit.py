"""Phase-3 (Viva 09-23 final ruling): pivot lines fitted in LOG10 space when
the chart is log and the visible span exceeds ~3% — «در کد حتما بذار»."""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


class _FakeAx:
    def __init__(self, scale: str):
        self._s = scale

    def get_yscale(self):
        return self._s


class _FakeFrame:
    def __init__(self, lo, hi):
        self.low = pd.Series([float(lo)])
        self.high = pd.Series([float(hi)])

    def __getitem__(self, key):
        return {"low": self.low, "high": self.high}[key]


def test_log_fit_when_span_exceeds_3pct():
    from bot.messages_v7 import _pivot_line_fit
    xs = [0.0, 30.0, 60.0, 90.0]
    # a pure exponential path: 100 → 200 → 400 → 800 (percentage-honest line)
    ys = [100.0 * (2 ** (x / 30.0)) for x in xs]
    ax = _FakeAx("log")
    frame = _FakeFrame(90.0, 820.0)          # span ≈ 811% > 3%
    mode, a, b = _pivot_line_fit(ax, frame, xs, ys)
    assert mode == "log"
    for x, y in zip(xs, ys):
        assert abs(10 ** (a * x + b) - y) < 1e-6      # passes through every pivot
    # the SAME pivots fitted linearly would miss them badly on a log chart
    lin_a, lin_b = np.polyfit(xs, ys, 1)
    assert abs(10 ** (a * xs[1] + b) - ys[1]) < 1e-6
    assert abs(lin_a * xs[1] + lin_b - ys[1]) > 5.0   # linear fit is off


def test_linear_kept_for_short_span_or_linear_axis():
    from bot.messages_v7 import _pivot_line_fit
    xs = [0.0, 50.0, 100.0]
    ys = [100.0, 101.0, 102.0]                        # span 2.6% < 3% guard
    ax = _FakeAx("log")
    mode, a, b = _pivot_line_fit(ax, _FakeFrame(99.9, 102.5), xs, ys)
    assert mode == "lin"
    la, lb = np.polyfit(xs, ys, 1)
    assert abs(a - la) < 1e-9 and abs(b - lb) < 1e-9
    # linear axis, big span → still linear
    mode2, _, _ = _pivot_line_fit(_FakeAx("linear"), _FakeFrame(90.0, 820.0), xs, ys)
    assert mode2 == "lin"


def test_renderer_wires_the_log_fit():
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    assert "_pivot_line_fit" in src
    # both pivot-line sites go through the helper (no naked polyfit on ys left)
    body = src[src.index("def _pivot_line_fit"):]
    assert "np.log10(np.asarray(ys, float))" in body
    assert src.count("= _pivot_line_fit(ax, frame, xs, ys)") == 2
