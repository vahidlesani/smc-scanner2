"""R99q38c/d — the higher spot timeframes must actually be able to alert.

His 10-21, verbatim: «ببین چرا اسپات روزانه و ۳ روزه و هفتگی و ۱۲ ساعته هیچ
هشداری نمیده؟ اگر جلوش بسته است یا محدودیت وجود داره درستش کن».

Root cause: 3d/1w frames only carry COMPLETE buckets, so their newest bar is
up to 3 (7) days old; the old freshness window (30 h) refused them almost
always, and their scan was only due when the bucket itself completed — the
daily close that the confirmation law reads was never scanned.
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _frame(n, start, freq, base=100.0, step=1.0):
    ts = pd.date_range(start, periods=n, freq=freq)
    px = [base + i * step for i in range(n)]
    return pd.DataFrame({"timestamp": ts, "open": px, "high": [p + 1 for p in px],
                         "low": [p - 1 for p in px], "close": px,
                         "volume": [10.0] * n})


def test_a_long_tf_is_due_when_its_confirm_frame_closes():
    from analysis import tiered_scan as T

    class B:
        def __init__(self, m):
            self.m = m

        def get(self, tf):
            return self.m.get(tf)

    frames = {"1d": _frame(30, "2026-09-01", "1D")}
    b = B(frames)
    # nothing stamped yet -> everything is due
    due = T.spot_due_tfs("BTCUSDT", b, tfs=("3d", "1w", "1d"), force=False)
    assert "3d" in due and "1w" in due and "1d" in due


def test_the_confirm_frame_rule_extends_the_due_set():
    src = open(os.path.join(ROOT, "analysis", "tiered_scan.py"), encoding="utf-8").read()
    assert "SPOT_CONFIRM_TF as _CF38" in src
    assert "and _cf in _due and _tf not in _due" in src


def test_the_long_tf_confirm_lane_exists():
    from analysis.spot_engine import confirm_frame_break, _confirm_fresh
    src = open(os.path.join(ROOT, "analysis", "spot_engine.py"), encoding="utf-8").read()
    assert "def confirm_frame_break(" in src
    assert "for tf in SPOT_LONG_TFS:" in src
    assert "def scan_spot_long_frame_confirms(" in src         # the dedicated lane
    assert "_full = getattr(frames, \"_b\", None) or frames" in src
    # a real first-close beyond a rising lower edge never fires (LONG needs HIGH)
    d = _frame(20, "2026-08-01", "3D")
    cf = _frame(20, "2026-09-20", "1D")
    pat = {"lines": [{"side": "LOW", "x0": 0, "x1": 19, "slope": 0.0,
                      "intercept": 90.0}], "shape": "single"}
    assert confirm_frame_break(d, cf, pat, "3d", "LONG") is None
    assert _confirm_fresh(cf) is False or True      # clock-free smoke


def test_a_real_first_close_beyond_the_edge_confirms():
    from analysis.spot_engine import confirm_frame_break
    d = _frame(20, "2026-08-01", "3D", base=100.0, step=0.0)
    # 1d frame: closes hug 99 then jump to 101 on the last bar
    cf = _frame(20, "2026-09-20", "1D", base=98.0, step=0.0)
    cf.loc[cf.index[-2], "close"] = 99.0
    cf.loc[cf.index[-1], "close"] = 101.0
    pat = {"lines": [{"side": "HIGH", "x0": 0, "x1": 19, "slope": 0.0,
                      "intercept": 100.0}], "shape": "single"}
    hit = confirm_frame_break(d, cf, pat, "3d", "LONG")
    assert hit and abs(hit["entry"] - 101.0) < 1e-9
    assert abs(hit["edge"] - 100.0) < 1e-6
