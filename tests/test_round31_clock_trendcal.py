"""r31 (Viva 09-26 screenshots): Tehran chart clocks, exact live-candle stamp,
fresh-major-break recognition, and the TECHCLASSIC typo."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest


REPO = "/home/user/smc-scanner2"


# ── 1. the family code spells TECHCLASSIC (PYTH T676953 screenshot) ──────
def test_public_code_spells_techclassic():
    from analysis.models import generate_viva_public_code
    for _ in range(20):
        code = generate_viva_public_code("TECHCLASSIC", "SWING")
        assert code.startswith("VIVA-TECHCLASSIC-"), code
        assert "TECLASSIC-" not in code.replace("TECHCLASSIC-", "")


# ── 2. every chart clock is TEHRAN, never UTC ─────────────────────────────
def test_chart_clocks_are_tehran():
    src = open(f"{REPO}/bot/messages_v7.py", encoding="utf-8").read()
    assert '_tk = _tk.tz_convert("Asia/Tehran")' in src            # axis ticks
    # r37: LIVE-STAMP-NOW enforced for real — the clock is the Tehran render
    # moment, not the candle bucket (bucket stamps froze on 12h/3d/1w spot).
    assert ('_live_clock = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%H:%M")' in src
            and '_live_stamp = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%m-%d %H:%M")' in src)
    assert '.strftime("%m-%d %H:%M UTC")' not in src
    assert '.strftime("%H:%M UTC")' not in src


# ── 3. live candle carries the EXACT render moment, uncached probe ────────
def test_live_candle_stamped_at_render_moment(monkeypatch):
    import bot.messages_v7 as mv
    import data.fetcher as fetcher

    now = datetime.now(timezone.utc)
    bucket = (pd.Timestamp(now) - pd.Timedelta(minutes=20)).floor("1h")
    live_df = pd.DataFrame([{"timestamp": bucket, "open": 1.0, "high": 1.2,
                             "low": 0.9, "close": 1.1, "volume": 5.0}])
    seen = {}

    def _fake_klines(symbol, tf, limit, closed_only=True, use_cache=True, **kw):
        seen["use_cache"] = use_cache
        return live_df

    monkeypatch.setattr(fetcher, "get_klines", _fake_klines)
    chart_df = pd.DataFrame([{"timestamp": bucket - pd.Timedelta(hours=1),
                              "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}])
    cand = SimpleNamespace(symbol="BTCUSDT", trigger_timeframe="1h", metadata={})
    row = mv._live_candle(cand, chart_df)
    assert row is not None
    assert seen["use_cache"] is False, "live probe must bypass the klines cache"
    ts = pd.Timestamp(row["timestamp"])
    assert ts.tzinfo is not None
    delta = abs((ts.tz_convert("UTC") - pd.Timestamp(now)).total_seconds())
    assert delta < 120, "displayed live candle must be the render moment, not the bucket"


# ── 4. fresh break of a MAJOR line is admitted (PYTH calibration) ─────────
def _tl_cfg():
    from analysis.viva_tlbreak import VivaTLBreakConfig
    return VivaTLBreakConfig(pivot_left=5, pivot_right=5, min_touches=3,
                             touch_tolerance_atr=0.15, max_fit_residual_atr=0.25)


def _line_df(n, break_at=58):
    """Rising 0.4/bar resistance touched at 15/40/52, pierced at `break_at`.

    Strictly-monotone sawtooth segments — flat plateaus would register as
    pivot clusters and crowd the pivot pool."""
    line = lambda i: 100.0 + 0.4 * i

    pivs = {15: line(15) + 0.10, 40: line(40) + 0.10, 52: line(52) + 0.10,
            break_at: line(break_at) + 1.20}
    # 55/57 dip keeps bars 53..57 strictly below pivot 52 (pivot_right=5)
    anchors = {0: 102.5, 7: 102.0, 27: 104.0, 46: 112.0, 55: 116.0, 57: 116.5,
               n: pivs[break_at] - 5.0}
    anchors.update(pivs)
    rows = []
    for i in range(n + 1):
        rows.append({"timestamp": pd.Timestamp("2026-09-20 00:00") + pd.Timedelta(hours=i),
                     "open": 0.0, "high": 0.0, "low": 0.0,
                     "close": 0.0, "volume": 10.0})
    order = sorted(anchors)
    for a, b in zip(order, order[1:]):
        va, vb = float(anchors[a]), float(anchors[b])
        for i in range(a, b + 1):
            rows[i]["high"] = va + (vb - va) * (i - a) / float(b - a)
    for r in rows:
        r["open"] = r["high"] - 0.5
        r["low"] = r["high"] - 2.0
        r["close"] = r["high"] - 0.8
    return pd.DataFrame(rows)


def test_freshly_broken_major_is_admitted():
    from analysis.viva_tlbreak import fit_validated_line
    df = _line_df(n=65, break_at=58)          # break 7 bars before the edge
    line = fit_validated_line(df, "HIGH", _tl_cfg())
    assert line is not None, "fresh major break must survive admission"
    assert line.break_index is not None and int(line.break_index) == 58
    assert line.touch_count >= 3


def test_old_broken_line_stays_history_only():
    from analysis.viva_tlbreak import fit_validated_line, load_config
    fresh = int(load_config().fresh_break_bars)
    # r33 LAW: within the 50-bar window a broken line stays admissible
    df95 = _line_df(n=95, break_at=58)        # break 37 bars before the edge
    ln95 = fit_validated_line(df95, "HIGH", _tl_cfg())
    assert ln95 is not None and ln95.break_index is not None, \
        "a 37-bar-old break must stay admissible inside the 50-bar window"
    # far beyond the window → history only, never a fresh event
    df130 = _line_df(n=130, break_at=58)      # break 72 bars before the edge
    ln130 = fit_validated_line(df130, "HIGH", _tl_cfg())
    assert ln130 is None or ln130.break_index is None, \
        "an ancient break must never re-arm as a fresh event"
    assert fresh == 50


def test_engine_recognises_the_fresh_break():
    src = open(f"{REPO}/analysis/pattern_engine.py", encoding="utf-8").read()
    assert "_fresh_bk31" in src and "fresh_break_recognition" in src
    assert "bars_since_break" in src
    seg = src[src.index("_bk31 = getattr"):]
    seg = seg[:seg.index("elif crossed and displacement")]
    assert "STATE_BREAK" in seg
