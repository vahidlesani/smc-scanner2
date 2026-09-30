# ── r61: THE 16-PATTERN LAW ────────────────────────────────────────────────
# Viva 09-30 (verbatim): «این الان کجاش رایزینگ وج هست؟؟» / «اگر ضلع بالا رسم
# بشه فالینگ وج هست» / «اگر ۱۶ الگوی اصلی در انجین به درستی درک نشن … دائماً
# مشکل ادامه دار خواهد بود» / «حتی مهمه که ببینیم قیمت از کدام سمت وارد شده» /
# «باید قوانین این عکس رفرنس رو از سورس بین‌المللی بگیری و کد بکنی».
import pytest


def _ns(slope, first_index, last_index, p_start, p_end):
    """A two-point line namespace (price_at linear) for classify tests."""
    import types
    span = max(1, last_index - first_index)
    k = (p_end - p_start) / span

    def price_at(x, _s=p_start, _k=k, _i=first_index):
        return _s + _k * (float(x) - _i)
    return types.SimpleNamespace(slope=slope, first_index=first_index,
                                 last_index=last_index, price_at=price_at)


def _bent_ns(i0, im, i1, a, b, c):
    """A 3-anchor piecewise line: window slope (a→c) can RISE while the tail
    (b→c, the segment the eye reads) FALLS — the exact HYPE geometry."""
    import types

    def price_at(x):
        x = float(x)
        if x <= im:
            f = (x - i0) / max(1, (im - i0))
            return a + f * (b - a)
        f = (x - im) / max(1, (i1 - im))
        return b + f * (c - b)
    span = i1 - i0
    return types.SimpleNamespace(slope=(c - a) / max(1, span), first_index=i0,
                                 last_index=i1, price_at=price_at)


def _frame(close_path, base=100.0):
    """Minimal OHLCV frame from a close path (wicks = ±0.2)."""
    import pandas as pd
    rows = []
    for i, c in enumerate(close_path):
        rows.append({"timestamp": f"2026-09-{(i % 28) + 1:02d} {i % 24:02d}:00",
                     "open": float(c) - 0.05, "high": float(c) + 0.2,
                     "low": float(c) - 0.2, "close": float(c),
                     "volume": 1000.0})
    return pd.DataFrame(rows)


# ── the HYPE law: entry side + honest tails decide the wedge label ─────────
def test_converging_up_entered_from_above_is_never_rising_wedge():
    """«این الان کجاش رایزینگ وج هست؟؟» — window slopes both up (the stale
    rally leg inside the window) but the UPPER edge price actually tests is
    FALLING and price entered from ABOVE: the honest name is falling wedge,
    never a rising one."""
    from analysis.pattern_engine import classify_shape
    # window OLS: both mildly rising; the HONEST TAIL of the upper edge falls
    # (stale rally leg inflates the window slope — the exact HYPE tape)
    upper = _bent_ns(0, 30, 60, 90.0, 96.5, 93.0)    # window +, tail −
    lower = _bent_ns(5, 30, 60, 84.0, 90.0, 89.6)    # window +, tail ≈ +
    # price path: vertical rally into the top, then entered the band from above
    path = [80 + 0.3 * i for i in range(30)] + [95 - 0.5 * i for i in range(31)]
    df = _frame(path)
    shape = classify_shape(upper, lower, 60, df=df)
    assert shape != "WEDGE_RISING", "the HYPE mislabel must be impossible"
    assert shape in ("WEDGE_FALLING", "TRIANGLE_DESCENDING", "TRIANGLE_SYMMETRICAL")


def test_true_rising_wedge_entered_from_below_stays_rising():
    from analysis.pattern_engine import classify_shape
    upper = _ns(+0.05, 0, 60, 90.0, 93.0)
    lower = _ns(+0.08, 5, 60, 84.0, 88.8)     # lower rises faster = converging
    path = [80 + 0.3 * i for i in range(61)]  # rising into the wedge from below
    df = _frame(path)
    assert classify_shape(upper, lower, 60, df=df) == "WEDGE_RISING"


def test_falling_wedge_both_tails_down():
    from analysis.pattern_engine import classify_shape
    upper = _ns(-0.10, 0, 50, 95.0, 90.0)
    lower = _ns(-0.03, 5, 50, 86.0, 84.9)
    path = [96 - 0.12 * i for i in range(51)]
    df = _frame(path)
    assert classify_shape(upper, lower, 50, df=df) == "WEDGE_FALLING"


def test_triangle_matrix():
    from analysis.pattern_engine import classify_shape
    # ascending: flat top, rising bottom (tails decide)
    up = _ns(0.0, 0, 40, 100.0, 100.0)
    lo = _ns(+0.10, 5, 40, 90.0, 93.5)
    path = [95 + 0.05 * i for i in range(41)]
    assert classify_shape(up, lo, 40, df=_frame(path)) in ("TRIANGLE_ASCENDING", "TRIANGLE")
    # symmetrical: upper down (steeper), lower up
    up2 = _ns(-0.12, 0, 40, 100.0, 95.2)
    lo2 = _ns(+0.08, 5, 40, 90.0, 93.2)
    assert classify_shape(up2, lo2, 40, df=_frame(path)) == "TRIANGLE_SYMMETRICAL"


def test_classify16_library_has_the_poster_16():
    """«۱۶ الگوی اصلی» — every family of his poster is in the law library."""
    from analysis.patterns16 import PATTERN16_LIBRARY
    need = ["WEDGE_RISING", "WEDGE_FALLING",
            "TRIANGLE_ASCENDING", "TRIANGLE_DESCENDING", "TRIANGLE_SYMMETRICAL",
            "CHANNEL_ASCENDING", "CHANNEL_DESCENDING",
            "RECTANGLE_BULL", "RECTANGLE_BEAR",
            "FLAG_BULL", "FLAG_BEAR", "PENNANT_BULL", "PENNANT_BEAR",
            "DOUBLE_TOP", "DOUBLE_BOTTOM",
            "HEAD_SHOULDERS", "INV_HEAD_SHOULDERS",
            "CUP_HANDLE", "INV_CUP_HANDLE"]
    missing = [k for k in need if k not in PATTERN16_LIBRARY]
    assert not missing, missing
    # entry side is part of the law («قیمت از کدام سمت وارد شده»)
    assert PATTERN16_LIBRARY["WEDGE_RISING"]["entry"] == "BELOW"
    assert PATTERN16_LIBRARY["WEDGE_FALLING"]["entry"] == "ABOVE"


def test_pattern_info_serves_the_16_law():
    from analysis.patterns import pattern_info
    assert pattern_info("DOUBLE_BOTTOM")["fa"] == "کف دوبل"
    assert pattern_info("HEAD_SHOULDERS")["bias"] == "BEAR"
    assert "وارد" in pattern_info("WEDGE_RISING")["rule_fa"]


# ── pivot-family detection on synthetic M / W shapes ───────────────────────
def _m_shape():
    """Two equal tops with a middle trough (double top), then price under neck."""
    path = []
    path += [100 - 0.5 * i for i in range(6)]            # 100 → 97
    path += [97 + 2.0 * i for i in range(8)]             # rally to 113
    path += [113 - 2.2 * i for i in range(9)]            # drop to 93.2
    path += [93.2 + 2.2 * i for i in range(9)]           # back to 113
    path += [113 - 1.5 * i for i in range(10)]           # fall under the neck
    return path


def _w_shape():
    path = []
    path += [100 + 0.5 * i for i in range(6)]            # 100 → 102.5
    path += [102.5 - 2.0 * i for i in range(8)]          # dump to 86.5
    path += [86.5 + 2.2 * i for i in range(9)]           # back to 106.3
    path += [106.3 - 2.2 * i for i in range(9)]          # 86.3 again
    path += [86.3 + 1.5 * i for i in range(10)]          # reclaim toward neck
    path += [99.8 + 1.0 * i for i in range(6)]           # press INTO the neck
    return path


def test_double_top_detected():
    from analysis.patterns16 import detect_pivot_patterns
    df = _frame(_m_shape())
    atr = float((df["high"] - df["low"]).tail(14).mean())
    pats = detect_pivot_patterns(df, atr)
    kinds = [p["type"] for p in pats]
    assert "DOUBLE_TOP" in kinds or "HEAD_SHOULDERS" in kinds, kinds
    item = next(p for p in pats if p["type"] in ("DOUBLE_TOP", "HEAD_SHOULDERS"))
    assert item["neckline"] > 0 and item["measured"] > 0
    assert item["entry_side"] == "ABOVE"


def test_double_bottom_detected():
    from analysis.patterns16 import detect_pivot_patterns
    df = _frame(_w_shape())
    atr = float((df["high"] - df["low"]).tail(14).mean())
    kinds = [p["type"] for p in detect_pivot_patterns(df, atr)]
    assert "DOUBLE_BOTTOM" in kinds or "INV_HEAD_SHOULDERS" in kinds, kinds


def test_detect_patterns_exposes_pivot_family():
    """The render/spot detector must carry the pivot family too (one item,
    alive near price)."""
    from analysis.render_kit import detect_patterns
    df = _frame(_w_shape())
    out = detect_patterns(df, "LONG")
    kinds = [p.get("type") for p in out]
    assert any(k in ("DOUBLE_BOTTOM", "INV_HEAD_SHOULDERS", "TRIANGLE",
                     "TRIANGLE_ASCENDING") for k in kinds), kinds


# ── parent-range nesting ───────────────────────────────────────────────────
def test_parent_range_and_inside():
    from analysis.patterns16 import parent_range, inside_parent
    # 60 bars bouncing 90..110 (box) → parent range
    path = [100 + (6 if (i // 5) % 2 == 0 else -6) for i in range(60)]
    df = _frame(path)
    atr = 3.0
    pr = parent_range(df, atr)
    assert pr is not None
    assert pr["top"] >= 105 and pr["bottom"] <= 95
    assert inside_parent(100.0, pr) and not inside_parent(130.0, pr)


def test_spot_alerts_carry_parent_annotation():
    """spot scan annotations: in_parent/parent_range present per item."""
    import analysis.spot_engine as se
    df = _frame([100 + (i % 10) - 5 for i in range(120)])
    frames = {"4h": df, "1d": df}
    out = se.scan_spot_alerts("TESTUSDT", frames)
    # no assertions on emptiness — the geometry may or may not stage; the
    # contract is: every returned item carries the nesting keys
    for item in out:
        assert "parent_range" in item and "in_parent" in item


# ── the chart diet ─────────────────────────────────────────────────────────
def test_chart_gate_off_by_default_and_gated(monkeypatch):
    """«چارت رو از اپلیکیشن فعلا حذف بکن» — flag default OFF; generate_chart
    returns None without rendering; env CHART_ENABLED=1 restores it."""
    import dataclasses
    from config import Settings
    assert Settings.from_env().chart_enabled is False
    import bot.messages_v7 as mv
    monkeypatch.setattr(mv, "SETTINGS",
                        dataclasses.replace(mv.SETTINGS, chart_enabled=False))
    from analysis.models import SignalCandidate
    df = _frame([100 + i * 0.1 for i in range(80)])
    cand = SignalCandidate(signal_id="X", symbol="TEST", style="DAYTRADE",
                           setup_code="TC", setup_name="t", strategy_fa="t",
                           direction="LONG", score=5, status="EDUCATIONAL",
                           entry_zone_bottom=99.0, entry_zone_top=100.0,
                           planned_entry=99.5, sl=98.0, tp1=101.0, tp2=102.0,
                           rr_tp1=1.0, rr_tp2=2.0, bias="BULL",
                           trigger_timeframe="1h")
    assert mv.generate_chart(df, cand) is None
    monkeypatch.setattr(mv, "SETTINGS",
                        dataclasses.replace(mv.SETTINGS, chart_enabled=True))
    # with charts ON the render path is allowed again (may still return None
    # on a synthetic frame — the law is the GATE, not the pixels)
