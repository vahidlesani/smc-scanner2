"""r54 — pattern-doctrine law (Viva 09-28, the LIT falling-wedge short).

His verbatim law: «این الگو ذاتا صعودی است و با بریک ضلع بالا تایید میشه …
اگر نزولی قراره بده اون هم با بریکِ ترند پایین و کلوز یا سیستم توهم باید
تایید بشه .. مگر اینکه در مولتی تایم فریم به این جمع بندی رسیده باشه یا
تحلیل فاندا یا ججمنت سفارشات در سمت تایید و عوامل دیگه که باید بگه و توضیح
بده در پیام تایید».

Covered here:
1. Every one-nature pattern has a DOCTRINE direction (falling wedge → LONG).
2. Counter FADE with zero supporting judgment → never minted; with support →
   allowed and the factors travel on metadata.
3. Wrong-side CLOSE-break of a one-nature pattern → confirmable counter
   BREAK (one-close law / TOHOM on that edge); a live-only cross stays a
   warn-only violation.
4. The confirmation message shows «چرا این جهت» for counter trades.
5. Converging trendline pairs are clipped at their apex in the renderer.
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _tape(n=140, drift=-0.004, seed=4, start="2026-08-01", freq="4h"):
    rng = np.random.default_rng(seed)
    base = 5.0 * np.exp(np.cumsum(rng.normal(drift / 20, 0.010, n)))
    ts = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": np.concatenate([[base[0]], base[:-1]]), "close": base,
        "high": base * 1.008, "low": base * 0.992,
        "volume": np.full(n, 1500.0),
    })


class _Bundle:
    def __init__(self, frames):
        self._f = frames

    def get(self, tf):
        return self._f.get(tf)


# ── 1. doctrine map ────────────────────────────────────────────────────────
def test_doctrine_directions():
    from analysis.pattern_engine import _DOCTRINE_DIRECTION
    assert _DOCTRINE_DIRECTION.get("WEDGE_FALLING") == "LONG"
    assert _DOCTRINE_DIRECTION.get("WEDGE_RISING") == "SHORT"
    assert _DOCTRINE_DIRECTION.get("TRIANGLE_ASCENDING") == "LONG"
    assert _DOCTRINE_DIRECTION.get("TRIANGLE_DESCENDING") == "SHORT"
    assert _DOCTRINE_DIRECTION.get("CHANNEL_DESCENDING") == "SHORT"


# ── 2. the counter gate ────────────────────────────────────────────────────
def test_counter_gate_allows_doctrine_and_break_blocks_bare_fade():
    from analysis.pattern_engine import _counter_doctrine_gate
    trig = _tape()
    bearish_4h = _tape(160, drift=-0.02)   # clear down-swing structure
    bundle = _Bundle({"4h": bearish_4h})

    # with-the-doctrine: always allowed, no factors needed
    ok, factors, doc = _counter_doctrine_gate("WEDGE_FALLING", "LONG", False, bundle, trig)
    assert ok and doc == "LONG"

    # counter FADE with NO support → blocked (the tape must carry no
    # directional body pressure either — an oscillating tape has none)
    n = 140
    tick = np.tile([5.00, 5.01, 5.00, 4.99, 5.00, 5.01], n // 6 + 1)[:n]
    ts = pd.date_range("2026-08-01", periods=n, freq="4h", tz="UTC")
    calm = pd.DataFrame({"timestamp": ts,
                         "open": np.roll(tick, 1), "close": tick,
                         "high": tick + 0.002, "low": tick - 0.002,
                         "volume": np.full(n, 1500.0)})
    flat = _Bundle({})
    ok2, f2, doc2 = _counter_doctrine_gate("WEDGE_FALLING", "SHORT", False, flat, calm)
    assert not ok2, f2
    assert doc2 == "LONG"

    # counter BREAK (opposite side closed through): allowed even without factors
    ok3, f3, doc3 = _counter_doctrine_gate("WEDGE_FALLING", "SHORT", True, flat, calm)
    assert ok3 and doc3 == "LONG"


def test_counter_support_factors_pick_htf_and_pressure():
    from analysis.pattern_engine import _counter_support_factors
    trig = _tape()
    up = _tape(160, drift=0.03)
    b = _Bundle({"4h": up})
    f = _counter_support_factors(b, "LONG", trig)
    assert f and any("۴h" in x or "4h" in x for x in f)


# ── 3. wrong-side break events ─────────────────────────────────────────────
def test_wrong_side_close_break_is_a_counter_event_in_source():
    src = open(os.path.join(ROOT, "analysis", "pattern_engine.py"),
               encoding="utf-8").read()
    # the close-cross promotion exists (not just warn-only)
    assert "_cc54" in src and "_counter54 = True" in src
    assert 'direction = "LONG" if side == "upper" else "SHORT"' in src
    # fades never run on the counter side
    assert "fade_enabled and not _counter54 and is_parallel" in src
    # events carry the flags
    assert '"counter_doctrine": bool(_counter54)' in src


def test_candidate_metadata_carries_counter_and_factors():
    src = open(os.path.join(ROOT, "analysis", "pattern_engine.py"),
               encoding="utf-8").read()
    assert '"counter_doctrine": _counter54' in src
    assert '"direction_why_fa": (_factors54 if _counter54 else [])' in src
    # the gate runs in _build_candidate before anything is minted
    assert "_counter_doctrine_gate(" in src.split("def _build_candidate")[1][:2000]


# ── 4. the confirm message explains the direction ──────────────────────────
def test_confirm_message_has_the_why_block():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "چرا این جهت (خلافِ ماهیت الگو)" in src
    seg = src.split("چرا این جهت (خلافِ ماهیت الگو)")[1][:600]
    assert "direction_why_fa" in seg
    assert "ضلعِ مقابلِ الگو" in seg  # the fallback line when no factors exist


# ── 5. apex clip in the renderer ───────────────────────────────────────────
def test_converging_lines_clip_at_apex():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "_apex9" in src
    assert "x_edge = min(x_edge, max(0.0, _apex9))" in src
    # the apex solve exists for the upper/lower pair
    seg = src.split("_apex9 = None")[1][:900]
    assert "_l9[4] - _u9[4]" in seg


def test_render_still_works_with_converging_pair(monkeypatch):
    """Smoke: a wedge-like frame + upper/lower viva points renders, and the
    clip path does not crash (full generate_chart). The live-candle probe is
    patched out (auto-reverted by monkeypatch) — otherwise _live_candle
    fetches REAL market klines for the fixture symbol and paints them over
    the synthetic tape."""
    import warnings
    warnings.filterwarnings("ignore")
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    monkeypatch.setattr("data.fetcher.get_klines", lambda *a, **k: None)
    from test_v7 import make_candidate
    import bot.messages_v7 as M
    n = 120
    up = np.linspace(1.60, 1.30, n)      # falling upper
    lo = np.linspace(1.30, 1.22, n)      # falling lower, slower → converging
    rng = np.random.default_rng(2)
    close = (up + lo) / 2 * (1 + rng.normal(0, 0.003, n))
    ts = pd.date_range("2026-09-20", periods=n, freq="15min", tz="UTC")
    frame = pd.DataFrame({"timestamp": ts,
                          "open": np.concatenate([[close[0]], close[:-1]]),
                          "close": close, "high": close * 1.004,
                          "low": close * 0.996, "volume": np.full(n, 900.0)})
    cand = make_candidate()
    cand.symbol = "LITUSDT"
    cand.entry_zone_bottom = 1.24
    cand.entry_zone_top = 1.28
    cand.planned_entry = 1.26
    cand.sl = 1.30
    cand.tp1 = 1.22
    cand.tp2 = 1.18
    cand.trigger_timeframe = "15m"
    cand.metadata["viva_upper_points"] = [
        {"timestamp": str(ts[10]), "price": float(up[10])},
        {"timestamp": str(ts[100]), "price": float(up[100])}]
    cand.metadata["viva_lower_points"] = [
        {"timestamp": str(ts[20]), "price": float(lo[20])},
        {"timestamp": str(ts[110]), "price": float(lo[110])}]
    cand.metadata["strategy_variant"] = "VIVA_TLBREAK"
    out = M.generate_chart(frame, cand, confirmed=True)
    assert isinstance(out, bytes) and len(out) > 20000
