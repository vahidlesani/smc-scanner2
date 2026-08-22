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

from analysis.viva_tlbreak import RetestAssessment, assess_retest_rejection, assess_micro_bos


def test_retest_rejection_and_micro_bos_are_separate_states():
    rows=[]
    for i in range(40):
        rows.append({"timestamp":pd.Timestamp("2026-01-01")+pd.Timedelta(minutes=15*i),"open":100.,"high":101.,"low":99.,"close":100.,"volume":1000.,"turnover":100000.})
    # breakout candle, retest pin, then BOS
    rows[30].update({"open":100.,"high":104.,"low":99.8,"close":103.5})
    rows[31].update({"open":101.,"high":101.5,"low":99.6,"close":101.3})
    rows[32].update({"open":101.2,"high":103.5,"low":101.,"close":103.2})
    df=pd.DataFrame(rows)
    line=ValidatedLine("HIGH",0.0,101.,3,.1,1,25,tuple())
    retest=assess_retest_rejection(df,line,"LONG",breakout_index=30,pattern_height=4,max_window_bars=5)
    assert retest is not None and retest.passed
    bos=assess_micro_bos(df,"LONG",not_before_index=retest.retest_index)
    assert bos is not None and bos.passed
