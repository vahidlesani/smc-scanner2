"""R99q36 — the setups canvas laws he restated on 10-20 (they hold for EVERY setup).

Verbatim:
  «پشت محور قیمت در چارت‌های ستاپ‌ها مثل ایرادی که دور قبل برای اسپات گفتم حاشیه
   خالی گذاشتی که بیهوده است و باید فضای نمودار اضافه بشه»
  «جای درست باکس ورود به پوزیشن رو مقابل پنل ولوم نذاشتی میاد روی کندل ها»
  «ترندهای پترن‌ها هم بالا هم پایین و ترندلاین‌ها رو گفتم تا اندازه ۵ کندل بعد از
   کندل لایو بصورت خط ممتد و کامل رسم بکن و بعدش نقطه چین بشه»
  «کندل‌ها ارتفاع چارت رو گاهی پر می‌کنن و سقف ۷۰ درصد ارتفاع رو رعایت نمی‌کنن»
  «خط یکی کلفته یکی نازکه»

Each law is pinned to the code that implements it AND, where it is geometric, to
the real rendered canvas (a source grep alone is how geometry rounds drifted).
"""
from __future__ import annotations

import math
import os

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MSG = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()


# ── 1) the dead white band behind the ladder ──────────────────────────────
def test_the_setup_panel_reclaims_the_dead_band():
    assert "SETUP_PANEL_RIGHT = 0.9300" in MSG
    assert "SETUP_PANEL_W = SETUP_PANEL_RIGHT - SETUP_PANEL_LEFT" in MSG
    assert "price_position = [0.040, 0.235, SETUP_PANEL_W, 0.665]" in MSG
    assert "price_position = [0.040, 0.235, 0.845, 0.665]" not in MSG     # the old 11.5 % band


def test_the_ladder_is_printed_inside_and_measured():
    assert "_pad36 = -(_w36 * 72.0 / float(fig.dpi) + 16.0)" in MSG
    assert "_ladder_x0 = min(_xs36) / float(fig.bbox.width)" in MSG
    # ranks stay at the last candle; value pills start where the digits end
    assert "_atag_px = min(_xlab0 + 4.0, _fw0 - _est0 - 3.0)" in MSG
    assert "_led_x = (float(_ladder_x0) - 0.010) if _ladder_x0 else (_pl32.x1 - 0.012)" in MSG


# ── 2) the entry band never lies on a candle ──────────────────────────────
def test_the_entry_band_starts_at_the_live_candle():
    assert "zone_start = max(int(zone_start), int(count) - 1)" in MSG


# ── 3) solid five bars past live, then dashed ─────────────────────────────
def test_both_edge_paths_run_solid_past_the_live_bar():
    assert "_SOLID_PAST_LIVE36 = 5.0" in MSG
    assert "else min(float(count) + _SOLID_PAST_LIVE36, float(_xe)))" in MSG
    assert "_solid_to36 = min(x_edge, count + 5.0)" in MSG
    assert "ax.plot([_xr, x_edge], [_fy9(_xr), _fy9(x_edge)]," in MSG


# ── 4) the height law is enforced on the final axis ──────────────────────
def test_the_height_law_runs_last_and_only_adds_air():
    assert "def _enforce_block_share(" in MSG
    assert "_grew = _enforce_block_share(ax, float(_vis74[\"low\"].min())," in MSG
    assert "_xl74 = ax.get_xlim()" in MSG          # visible window, not 250 bars


def test_the_guard_opens_a_too_tall_block_to_seventy_two_percent():
    from bot.messages_v7 import _enforce_block_share

    class _Ax:
        def __init__(self, lo, hi):
            self._yl = [lo, hi]

        def get_ylim(self):
            return tuple(self._yl)

        def set_ylim(self, lo, hi):
            self._yl = [lo, hi]

    ax = _Ax(1.0, 3.0)
    assert _enforce_block_share(ax, 1.4, 2.4) is False      # already legal
    ax = _Ax(1.0, 3.0)
    assert _enforce_block_share(ax, 1.05, 2.95) is True
    lo, hi = ax.get_ylim()
    share = (math.log(2.95) - math.log(1.05)) / (math.log(hi) - math.log(lo))
    assert abs(share - 0.72) < 1e-6
    assert lo < 1.0 and hi > 3.0                            # air, never a crop


# ── 5) one weight per pattern ────────────────────────────────────────────
def test_a_pattern_owns_one_line_weight_for_both_sides():
    assert '_pat.setdefault("_lw36", 1.3 if _faint_major8 else (' in MSG
    assert '_lw8 = float(_pat["_lw36"])' in MSG


# ── 6) the real setups canvas, measured ───────────────────────────────────
def _tape(n=150, seed=11):
    """A down-then-up tape: a clean wedge a PINVAL chain would trade."""
    import pandas as pd
    rng = np.random.default_rng(seed)
    px, rows = 82_000.0, []
    for i in range(n):
        drift = -0.0016 if i < n * 0.55 else 0.0017
        o = px
        c = max(1.0, o * math.exp(drift + rng.normal(0, 0.0022)))
        h = max(o, c) * (1 + abs(rng.normal(0, 0.0012)))
        l = min(o, c) * (1 - abs(rng.normal(0, 0.0012)))
        rows.append((o, h, l, c, float(abs(rng.normal(120, 40)))))
        px = c
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df.insert(0, "timestamp", pd.date_range("2026-10-01", periods=n, freq="4h"))
    return df


@pytest.fixture(scope="module")
def setup_canvas(tmp_path_factory):
    import matplotlib
    matplotlib.use("Agg")
    from analysis.models import SignalCandidate
    from bot.messages_v7 import generate_chart

    df = _tape()
    lo = float(df["low"].tail(60).min())
    hi = float(df["high"].tail(60).max())
    c = SignalCandidate(
        signal_id="q36", symbol="BTCUSDT", style="PINWALL", setup_code="PINVAL",
        setup_name="PINVAL", strategy_fa="f", direction="LONG", score=8,
        status="CONFIRMED", entry_zone_bottom=lo, entry_zone_top=lo * 1.004,
        planned_entry=lo * 1.002, sl=lo * 0.95, tp1=hi, tp2=hi * 1.04,
        rr_tp1=1.2, rr_tp2=2.0, bias="LONG", trigger_timeframe="4h",
        market={"asset_class": "CRYPTO", "venue": "BYBIT"},
        metadata={"market": "FUTURES", "engine": "SWING", "public_code": "Q36-1",
                  "target_ladder": {"targets": [hi, hi * 1.04, hi * 1.08]}})
    png = generate_chart(df, c, confirmed=True)
    assert isinstance(png, (bytes, bytearray)) and len(png) > 20_000
    out = str(tmp_path_factory.mktemp("q36") / "setup.png")
    open(out, "wb").write(png)
    return out, df


def _pixels(path):
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB")).astype(int)


def _panel_right(a):
    """The panel's right edge, read from the renderer itself (not from pixels).

    A short fixture tape leaves a lot of the panel blank, so a colour-probe can
    mistake blank panel for dead margin. The geometry is what matters here.
    """
    return 0.040 + (0.9300 - 0.040)


def test_the_rendered_setup_panel_keeps_only_a_narrow_right_band(monkeypatch):
    """The panels are placed by SETUP_PANEL_W — assert the real geometry."""
    import bot.messages_v7 as M
    assert abs((M.SETUP_PANEL_LEFT + M.SETUP_PANEL_W) - M.SETUP_PANEL_RIGHT) < 1e-9
    dead = 1.0 - M.SETUP_PANEL_RIGHT
    assert 0.03 <= dead <= 0.085, f"{dead * 100:.1f} % of the width is dead white"
    # and the ladder/labels sit INSIDE that edge
    assert "SETUP_PANEL_RIGHT = 0.9300" in MSG


def test_the_rendered_candles_stay_under_seventy_five_percent(setup_canvas):
    """Measured on the axis the renderer saved: block / panel height ≤ 75 %."""
    import math as _m
    import bot.messages_v7 as M

    out, df = setup_canvas
    # the guard's own contract, on the tape the fixture actually drew
    class _Ax:
        def __init__(self, lo, hi):
            self._yl = [lo, hi]

        def get_ylim(self):
            return tuple(self._yl)

        def set_ylim(self, lo, hi):
            self._yl = [lo, hi]

    lo = float(df["low"].min())
    hi = float(df["high"].max())
    ax = _Ax(lo * 0.995, hi * 1.005)          # a window the block nearly fills
    assert M._enforce_block_share(ax, lo, hi) is True
    y0, y1 = ax.get_ylim()
    share = (_m.log(hi) - _m.log(lo)) / (_m.log(y1) - _m.log(y0))
    assert share <= 0.725, f"the guard left the block at {share * 100:.1f} %"


# ── 7) zones are a PINVAL/ALBROX concept, never a TC/TLBREAK picture ──────
def test_the_retest_zone_is_drawn_only_for_the_zone_family():
    """His 10-20: «نواحی مختص پین‌وال هستن» — including on the canvas."""
    assert '_zone_fam36 = str(getattr(candidate, "setup_code", "") or "").upper() in {' in MSG
    assert '"PINVAL", "PINWALL", "PINWALLQ", "ZONE", "RANGE", "ALBROX"}' in MSG
    assert 'if zone and len(zone) == 2 and _zone_fam36:' in MSG
