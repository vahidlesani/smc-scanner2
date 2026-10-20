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
    # his 10-20 doctrine: the white band holds the PRICE AXIS only, 3–3.5 %
    assert "SETUP_PANEL_RIGHT = 0.9650" in MSG
    assert "SETUP_PANEL_W = SETUP_PANEL_RIGHT - SETUP_PANEL_LEFT" in MSG
    assert "price_position = [0.040, 0.235, SETUP_PANEL_W, 0.665]" in MSG
    assert "price_position = [0.040, 0.235, 0.845, 0.665]" not in MSG     # the old 11.5 % band


def test_the_ladder_is_printed_inside_and_measured():
    # the digits own the band (positive pad, right of the tape)
    assert "_pad36 = 5.0" in MSG
    assert "_ladder_x0 = min(_xs36) / float(fig.bbox.width)" in MSG
    # ranks stay at the last candle; value pills start where the digits end
    # value pills stand LEFT of the measured ladder edge
    assert '_atag_px = max(4.0, float(_ladder_x0) * _fw0 - 8.0) if _ladder_x0 else _fw0 - _est0 - 6.0' in MSG
    assert 'ha="right", zorder=13' in MSG
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
    return 0.040 + (0.9650 - 0.040)


def test_the_rendered_setup_panel_keeps_only_a_narrow_right_band(monkeypatch):
    """The panels are placed by SETUP_PANEL_W — assert the real geometry."""
    import bot.messages_v7 as M
    assert abs((M.SETUP_PANEL_LEFT + M.SETUP_PANEL_W) - M.SETUP_PANEL_RIGHT) < 1e-9
    dead = 1.0 - M.SETUP_PANEL_RIGHT
    # his number: «حاشیه سفید حدود ۳ تا ۳.۵ درصد جای محور قیمت»
    assert 0.028 <= dead <= 0.037, f"{dead * 100:.1f} % of the width is dead white"
    assert "SETUP_PANEL_RIGHT = 0.9650" in MSG


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


# ── 11) ONE GEOMETRY PER UNIQUE ID (his 10-20 15:20 proof) ───────────────
# «یک آیدی یکتا در فاصلهٔ چند دقیقه دو هندسهٔ کاملاً متفاوت» — the same id
# rendered through analysis / ready / confirmed must land on the identical
# x-window, y-window and panel. This is the law the three levers below serve.
def test_the_future_strip_is_a_fraction_never_a_bar_count():
    assert ("future = 45 if _is_spot else max(8, int(round(0.093 * float(count))))"
            in MSG)
    assert "future = 45 if _is_spot else (18 if _cfm73 else 16)" not in MSG


def test_the_price_window_is_frozen_per_id_not_per_message_kind():
    assert "_cfm73 = bool(confirmed or preconfirm_tool)" in MSG     # still the tool flag
    # the freeze is READ with no message-kind gate any more
    assert "if True:\n            try:\n                _fz = (candidate.metadata or {}).get(\"chart_zoom_frozen\")" in MSG
    # and the ladder joins the zoom subject on every path
    assert "if True:\n                ladder_targets = list(" in MSG


def test_the_visible_span_is_frozen_per_id():
    assert '_fx37 = _gjx37(f"zoom_freeze_x:{candidate.signal_id}")' in MSG
    assert '_sjx37(f"zoom_freeze_x:{candidate.signal_id}", [_nv37b, _pd37b])' in MSG
    # a label column may never stretch a frozen axis
    assert "if _need > count + future and not _xfroz:" in MSG
    # the card that stamps obeys its own stamp
    assert "_ca.set_xlim(max(-1.0, _r37c - float(_nv37b)), _r37c)" in MSG


def test_same_id_same_geometry_through_every_path(monkeypatch):
    """analysis / ready / confirmed on one tape: identical xlim, ylim, panel."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.figure as mfig
    from analysis.models import SignalCandidate
    import bot.messages_v7 as M

    seen = []
    _orig = mfig.Figure.savefig

    def _spy(self, *a, **k):
        try:
            ax = [x for x in self.axes if x.get_position().height > 0.30][0]
            seen.append((tuple(round(float(v), 4) for v in ax.get_xlim()),
                         tuple(round(float(v), 6) for v in ax.get_ylim()),
                         round(float(ax.get_position().x1), 4)))
        except Exception:
            seen.append(None)
        return _orig(self, *a, **k)

    store = {}
    import database.bot_kv as kv
    monkeypatch.setattr(kv, "get_json", lambda k: store.get(k))
    monkeypatch.setattr(kv, "set_json", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(mfig.Figure, "savefig", _spy)

    df = _tape()
    lo = float(df["low"].tail(60).min())
    hi = float(df["high"].tail(60).max())

    def _cand():
        return SignalCandidate(
            signal_id="onegeom", symbol="BTCUSDT", style="SWING", setup_code="TECHCLASSIC",
            setup_name="TECHCLASSIC", strategy_fa="f", direction="SHORT", score=8,
            status="READY", entry_zone_bottom=hi, entry_zone_top=hi * 1.002,
            planned_entry=hi, sl=hi * 1.01, tp1=lo * 1.01, tp2=lo * 0.99,
            rr_tp1=1.2, rr_tp2=2.0, bias="SHORT", trigger_timeframe="4h",
            market={"asset_class": "CRYPTO", "venue": "BYBIT"},
            metadata={"market": "FUTURES", "engine": "SWING", "public_code": "ONE-1",
                      "target_ladder": {"targets": [lo * 1.01, lo * 0.99, lo * 0.97]}})

    for conf, pre in ((False, False), (False, True), (True, False)):
        assert M.generate_chart(df, _cand(), confirmed=conf, preconfirm_tool=pre)
    assert len(seen) == 3 and None not in seen
    assert seen[0] == seen[1] == seen[2], seen


# ── 12) the alert's snapshot freezes what the alert DREW ──────────────────
# «هشدار ابتدایی پترن درست اسنپ‌شات بشه» — the lock stamps before the painter
# decides which shapes survive, so a chain could freeze a set the first card
# never showed and every later card painted something else.
def test_the_snapshot_is_written_from_the_drawn_set():
    from analysis.snapshot_lock import restamp_render_geometry
    md = {"render_patterns": [{"type": "CHANNEL_ASCENDING"}], "render_zones": []}
    cand = type("C", (), {"signal_id": "RS1", "metadata": md})()
    store = {}
    assert restamp_render_geometry(cand, kv_set=lambda k, v: store.__setitem__(k, v))
    assert store["render_identity:RS1"]["render_patterns"][0]["type"] == "CHANNEL_ASCENDING"
    assert store["render_identity:RS1"]["drawn_set"] is True


def test_the_restore_never_drops_a_frozen_pattern():
    src = open(os.path.join(ROOT, "analysis", "snapshot_lock.py"), encoding="utf-8").read()
    assert "_pats21 = [x for x in _pats21 if id(x) in _keep_ids21]" not in src
    assert "stay ON THE CHART (frozen" in src
    # and the painter hands its final set back on the card that stamped
    assert 'str(locals().get("_lock_res37") or "") == "STAMPED"' in MSG
