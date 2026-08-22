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

from analysis.viva_tlbreak import ValidatedLine, assess_closed_breakout, structure_score


def test_closed_breakout_scores_only_closed_directional_strength():
    df = pd.DataFrame([
        {"timestamp": pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=i), "open":100, "high":101, "low":99, "close":100, "volume":1000, "turnover":100000}
        for i in range(25)
    ])
    df.loc[24, ["open","high","low","close"]] = [100, 104, 99.8, 103.8]
    line = ValidatedLine("HIGH", 0.0, 101.0, 3, 0.1, 1, 20, tuple())
    out = assess_closed_breakout(df, line, "LONG")
    assert out is not None and out.passed and out.score >= 1.4


def test_structure_score_rewards_validated_not_two_point_line():
    line = ValidatedLine("HIGH", -0.1, 100, 3, 0.1, 1, 35, tuple())
    assert structure_score(line) >= 1.0
