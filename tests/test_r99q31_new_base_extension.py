"""R99q31d — a line named by the NAMING layer must also reach the new base.

His JUP/ZEC law (10-12): «وقتی قیمت یک ترند را رد کرد و بیس جدید ساخت، ترند
تا بیس جدید ادامه پیدا می‌کند». `extend_line_to_new_base` was written for it
and is called inside `detect_patterns` — but a pair named by
`analysis/pattern_naming.py` never passed through it, so the render kept a
line that cut straight through a base the price had already left.
"""
import numpy as np
import pandas as pd


def _ext_frame(fakeout=False, n=60):
    """A descending upper rail, then price closes ABOVE it and bases there."""
    ts = pd.date_range("2026-09-01", periods=n, freq="4h", tz="UTC")
    line = lambda x: 100.0 - 0.2 * (x - 10)   # anchor (10,100), slope -0.2
    c = np.array([line(x) - 0.5 for x in range(n)])
    h = c + 0.3
    l = c - 0.3
    if not fakeout:
        for x in range(40, 56):               # three+ closes beyond the rail
            c[x] = line(x) + 1.0
            h[x] = c[x] + 0.3
            l[x] = c[x] - 0.3
        h[50] = line(50) + 2.0                # the new extreme pivot
        c[50] = line(50) + 1.5
    else:
        h[45] = line(45) + 2.0                # lone wick pierce, bodies inside
    return (pd.DataFrame({"timestamp": ts, "open": c, "high": h, "low": l,
                          "close": c, "volume": np.full(n, 100.0)}), line)


def test_the_naming_layer_routes_both_edges_through_the_extension():
    """Source-level: the call must sit INSIDE the block that builds `shape`."""
    src = open("analysis/pattern_naming.py", encoding="utf-8").read()
    i_shape = src.index("shape = {")
    i_call = src.index("extend_line_to_new_base")
    assert i_call < i_shape, "extension must run before the shape is built"
    assert "_df31 = df.reset_index(drop=True)" in src
    assert '_ext31(upper, _df31, "HIGH")' in src
    assert '_ext31(lower, _df31, "LOW")' in src


def test_the_extension_still_behaves_on_a_real_cross():
    from analysis.render_kit import extend_line_to_new_base as E
    df, _ = _ext_frame()
    ln = {"side": "HIGH", "slope": -0.2, "intercept": 102.0, "x0": 10,
          "x1": 59, "points": [{"ts": "2026-09-01", "price": 100.0}]}
    out = E(ln, df, "HIGH")
    assert out.get("extended73") is True
    assert len(out["points"]) == 2


def test_a_wick_only_fakeout_is_still_ignored():
    from analysis.render_kit import extend_line_to_new_base as E
    df, _ = _ext_frame(fakeout=True)
    ln = {"side": "HIGH", "slope": -0.2, "intercept": 102.0, "x0": 10,
          "x1": 59, "points": [{"ts": "2026-09-01", "price": 100.0}]}
    assert E(ln, df, "HIGH") is ln


def test_a_missing_edge_does_not_break_the_naming_layer():
    """upper=None must never raise — the mirror side still renders."""
    from analysis.render_kit import extend_line_to_new_base as E
    df, _ = _ext_frame()
    assert E(None, df, "HIGH") is None
