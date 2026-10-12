"""Stage-1: اعتبار هندسهٔ هستهٔ واحد (viva_geometry)."""
import math

import numpy as np
import pandas as pd

from analysis import viva_geometry as vg

BASE = math.log(100)


def mk_wedge(n=120, us=-0.004, u0=BASE + 0.55, ls=-0.0015, l0=BASE, swings=6,
             break_edge=None, break_bars=5, seed=7):
    """چارت تمیز: کلوز روی میانهٔ باند + نویز ریز؛ تماس‌ها دقیق روی لبه‌ها.
    ATR کوچک می‌ماند تا نوسان‌های الگو خیلی بزرگ‌تر از ۲×ATR باشند."""
    rng = np.random.default_rng(seed)
    i = np.arange(n)
    u = u0 + us * i
    lo = l0 + ls * i
    w = u - lo
    phase = np.sin(2 * np.pi * swings * i / n)
    close = (u + lo) / 2 + rng.normal(0, 0.002, n)
    high = np.where(phase > 0.99, u, close + 0.004)
    low = np.where(phase < -0.99, lo, close - 0.004)
    open_ = np.concatenate([[close[0]], close[:-1]])
    df = pd.DataFrame({"open": np.exp(open_), "high": np.exp(high),
                       "low": np.exp(low), "close": np.exp(close),
                       "volume": 1000 + rng.integers(0, 100, n)})
    if break_edge:
        extra = []
        for j in range(break_bars):
            k = n + j
            uv, lv = u0 + us * k, l0 + ls * k
            c = uv + 0.02 if break_edge == "UP" else lv - 0.02
            extra.append([c - 0.005, c + 0.008, c - 0.008, c])
        e = pd.DataFrame(np.exp(np.array(extra)), columns=["open", "high", "low", "close"])
        e["volume"] = 1200
        df = pd.concat([df, e], ignore_index=True)
    return df


def line(sl, ic, side="upper", touches=()):
    return vg.Line(sl, ic, side, touches, 0)


def test_wedge_name_independent_of_entry():
    u, l = line(-0.004, BASE + .3), line(-0.0015, BASE)
    s_up, _ = vg.classify_geometry(u, l, 0, 99, vg.Leg(vg.UP, .2, 20, 0, BASE), .01)
    s_dn, _ = vg.classify_geometry(u, l, 0, 99, vg.Leg(vg.DOWN, .2, 20, 0, BASE), .01)
    assert s_up == s_dn == "WEDGE_FALLING"
    u2, l2 = line(.0015, BASE + .3), line(.004, BASE)
    s2, _ = vg.classify_geometry(u2, l2, 0, 99, vg.Leg(vg.UP, .2, 20, 0, BASE), .01)
    assert s2 == "WEDGE_RISING"


def test_crossed_lines_rejected():
    u, l = line(-0.001, BASE + .3), line(.004, BASE)   # قطع پیش از x1
    assert vg.classify_geometry(u, l, 0, 99, atr=.01)[0] == "NONE"
    assert vg.measure(u, l, 0, 99) is None


def test_sym_slope_ratio_enforced():
    u, l = line(-0.002, BASE + .3), line(.0007, BASE)  # نسبت ~۲٫۹ — خارج از [0.4,2.5]
    assert vg.classify_geometry(u, l, 0, 99, atr=.01)[0] == "NONE"
    u2, l2 = line(-0.0015, BASE + .3), line(.001, BASE)
    assert vg.classify_geometry(u2, l2, 0, 99, atr=.01)[0] == "TRIANGLE_SYMMETRICAL"


def test_parallel_requires_slope_proximity():
    u, l = line(-0.002, BASE + .3), line(.002, BASE)   # عرض مشابه ولی شیب متضاد
    assert vg.classify_geometry(u, l, 0, 99, atr=.01)[0] == "NONE"
    u2, l2 = line(.003, BASE + .3), line(.0034, BASE)
    assert vg.classify_geometry(u2, l2, 0, 99, atr=.01)[0] == "CHANNEL_ASCENDING"


def test_rectangle_needs_both_edges_flat_and_channel_flat_without_leg():
    u, l = line(.0004, BASE + .3), line(.0004, BASE)
    s, _ = vg.classify_geometry(u, l, 0, 99, vg.Leg(vg.UP, .3, 15, 0, BASE), .01)
    assert s == "RECTANGLE_BULL"
    s2, _ = vg.classify_geometry(u, l, 0, 99, vg.Leg(), .01)
    assert s2 == "CHANNEL_FLAT"
    u3, l3 = line(.002, BASE + .3), line(-.002, BASE)  # غیرافقی و واگرا → هرگز مستطیل نیست
    assert vg.classify_geometry(u3, l3, 0, 99, vg.Leg(vg.UP, .3, 15, 0, BASE), .01)[0] \
        not in ("RECTANGLE_BULL", "CHANNEL_FLAT")


def test_entry_leg_picks_dominant_move():
    df = mk_wedge()
    L = vg.log_ohlc(df)
    atr = vg.atr_log(L)
    piv = [{"index": 2, "price": float(BASE - 0.02), "kind": "L", "confirmed": True},
           {"index": 20, "price": float(BASE + 0.03), "kind": "H", "confirmed": True},
           {"index": 34, "price": float(BASE - 0.01), "kind": "L", "confirmed": True}]
    leg = vg.entry_leg(L, piv, 45, atr, 0.2)
    # قوی‌ترین حرکت (از کف ۲)، نه صرفاً آخرین پیوت (۳۴)
    assert leg.direction == vg.UP
    assert leg.start_index == 2
    assert leg.move >= vg.LEG_MIN_ATR * atr


def test_spike_excluded_from_anchors():
    df = mk_wedge(seed=3)
    r0 = vg.fit_patterns(df)
    df2 = df.copy()
    df2.loc[60, "high"] = df2.loc[60, "high"] * 3.0   # اسپایک ویک پرت
    r1 = vg.fit_patterns(df2)
    assert r0 and r1
    assert r0[0].slug == r1[0].slug
    assert abs(r0[0].x0 - r1[0].x0) <= 2
    assert abs(r0[0].upper.slope - r1[0].upper.slope) < 1e-3


def test_breakout_lifecycle_event_based():
    df = mk_wedge(break_edge="UP", break_bars=8)
    res = vg.fit_patterns(df)[0]
    life = vg.breakout_lifecycle(df, res)
    assert life["status"] == "BREAK_UP_CLOSED"
    assert life["event_index"] is not None
    assert life["bars_since_break"] == len(df) - 1 - life["event_index"]
    # فیک: برگشت به داخل هر دو ضلع
    df3 = mk_wedge(break_edge="UP", break_bars=2)
    tail = df3.iloc[-1:].copy()
    i = len(df3)
    c = res.lower.price_at(i) + 0.001
    tail.loc[tail.index[0], ["open", "high", "low", "close"]] = [c, c + .001, c - .001, c]
    df3 = pd.concat([df3, tail], ignore_index=True)
    life3 = vg.breakout_lifecycle(df3, res)
    assert life3["status"] == "FALSE_BREAK_UP"


def test_double_top_detected():
    n = 90
    i = np.arange(n)
    base = BASE + 0.001 * i
    bump = 0.25 * np.exp(-((i - 20) ** 2) / 18) + 0.25 * np.exp(-((i - 60) ** 2) / 18)
    dip = -0.15 * np.exp(-((i - 40) ** 2) / 12)
    close = base + bump + dip
    df = pd.DataFrame({"open": np.exp(np.concatenate([[close[0]], close[:-1]])),
                       "high": np.exp(close + 0.004), "low": np.exp(close - 0.004),
                       "close": np.exp(close), "volume": 100})
    pats = vg.detect_pivot_patterns(df)
    assert any(p.slug == "DOUBLE_TOP" for p in pats)


def test_view_fill_and_limits():
    df = mk_wedge(n=160)
    res = vg.fit_patterns(df)[0]
    v = vg.choose_view(df, res, target_price=None, tf="4h")
    assert v["fill"] <= vg.MAX_FILL + 1e-6 or v["diagonal_pattern"]
    assert 120 <= v["bars"] <= 400
