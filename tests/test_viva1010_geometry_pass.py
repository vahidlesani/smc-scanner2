"""Viva 10-10 geometry pass-through law: a mid-span cross by a mere wiggle
(swing size under 2 ruler units) is noise — the line passes THROUGH it to
the next on-path pivot. Only MAJOR crossings can veto a pair."""
import numpy as np
import pandas as pd


def _wiggle_df():
    """140-bar downtrend, HIGH side. Majors (full candles) at 30/70/110 on
    the line y = 103.75 - 0.125*i; small 3-bar swing bumps at 50 and 90,
    highs +0.5 over the line (prominence ~1.6 ruler units = noise)."""
    n = 140
    lin = lambda i: 103.75 - 0.125 * i
    o, h, l, c = [], [], [], []
    for i in range(n):
        base = lin(i) - 2.0
        o.append(base - 0.6); h.append(base); l.append(base - 1.0); c.append(base - 0.4)
    # majors: full candles shifted up to the line
    for i, px in ((30, 100.0), (70, 95.0), (110, 90.0)):
        h[i] = px; l[i] = px - 1.0; o[i] = px - 0.6; c[i] = px - 0.4
    # wiggles: small REAL swing bumps (full candles, normal 0.55 wicks — they
    # survive the noise filter as pivots). High pokes +0.5 over the line (a
    # counted pierce), body top sits -0.05 under it (body-cut guard silent),
    # swing ~2.5 price units ≈ 1.25 ruler units → wiggle, forgiven.
    for j in (50, 90):
        for k, lift in ((-1, 0.3), (0, 0.5), (1, 0.3)):
            i = j + k
            h[i] = lin(i) + lift
            o[i] = lin(i) - 0.35; c[i] = lin(i) - 0.05; l[i] = lin(i) - 0.65
    ts = pd.date_range("2026-09-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": l,
                         "close": c, "volume": 1000.0})


def test_wiggle_crossings_are_forgiven():
    from analysis.viva_tlbreak import _mid_wiggle_filter
    mid = np.array([3, 7, 9, 12])
    pidx = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0,
                     90.0, 100.0, 110.0, 120.0, 130.0])
    prom = {40: 0.8, 80: 5.2, 100: 1.1, 130: 3.3}
    out = _mid_wiggle_filter(mid, pidx, prom)
    assert list(out) == [7, 12]  # majors kept, wiggles dropped


def test_unknown_prominence_still_vetoes_fail_safe():
    from analysis.viva_tlbreak import _mid_wiggle_filter
    mid = np.array([2, 5])
    pidx = np.arange(10, dtype=float)
    out = _mid_wiggle_filter(mid, pidx, {})  # nothing known → keep all
    assert list(out) == [2, 5]


def test_major_line_survives_wiggle_pierces():
    """The (30,110) major pair is crossed mid-span by 2 wiggle pivots —
    old law rejects it (2 pierces), new law fits it."""
    from analysis.viva_tlbreak import fit_validated_line
    line = fit_validated_line(_wiggle_df(), "HIGH")
    assert line is not None
    assert abs(float(line.slope) - (-0.125)) < 0.03
    assert abs(float(line.intercept) - 103.75) < 1.0


def test_old_path_rejects_the_same_wiggle_line(monkeypatch):
    """Law proof: with the filter neutralised (pre-10-10 behaviour) the
    same tape yields NO line — the wiggles were the veto."""
    import analysis.viva_tlbreak as T
    monkeypatch.setattr(T, "_mid_wiggle_filter", lambda m, p, q: m)
    assert T.fit_validated_line(_wiggle_df(), "HIGH") is None
