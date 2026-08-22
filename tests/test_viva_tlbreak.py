import pandas as pd
from analysis.viva_tlbreak import load_config, fit_validated_line


def _frame():
    rows=[]
    for i in range(80):
        base=100-i*0.1
        rows.append({"timestamp":pd.Timestamp("2026-01-01")+pd.Timedelta(hours=i),"open":base,"high":base+1,"low":base-1,"close":base,"volume":1000,"turnover":100000})
    return pd.DataFrame(rows)


def test_config_isolated_and_loadable():
    cfg=load_config()
    assert cfg.min_touches == 3
    assert cfg.pivot_left == 5


def test_line_requires_validated_three_pivot_geometry():
    # Synthetic monotonic data has no confirmed alternating fractal highs;
    # it must not fabricate a line.
    assert fit_validated_line(_frame(), "HIGH") is None
