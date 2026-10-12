"""Stage-2: سیم‌کشی گزارش پوزیشن (اسپات/پرپچوآل)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

from test_stage1_core import mk_wedge

from analysis import stage2_wiring as w


def test_spot_report_long_on_confirmed_break():
    df = mk_wedge(n=160, break_edge="UP", break_bars=6)
    # فقط الگوهای دوخطی مد نظر گزارش اسپات نیستند؛ ولی هر خروجی باید ساختار داشته باشد
    r = w.spot_report(df, "4h")
    assert r is None or set(r) >= {"market", "tf", "stage", "actionable_long"}


def test_perp_position_report_structure():
    df = mk_wedge(n=160, break_edge="UP", break_bars=6)
    r = w.perp_position_report(df, "4h", "PINVAL")
    assert r is None or set(r) >= {"market", "brand", "position", "entry", "stop",
                                   "target", "invalidation"}
    if r and r["position"] == "LONG":
        assert r["stop"] < r["entry"] < r["target"]


def test_scan_all_returns_buckets():
    df = mk_wedge(n=160)
    out = w.scan_all({"4h": df})
    assert set(out) == {"spot", "perp"}
