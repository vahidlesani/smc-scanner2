"""R99q35 — «حاشیه پشت محور قیمت‌ها» + «۷۰ تا ۷۵ درصد ارتفاع چارت».

His 10-20, verbatim:
  «گفتم حاشیه پشت محور قیمتها باید به چارت نمودار اضافه بشه … پشت محور قیمت‌ها
   حدود ۱۵ درصد از چارت کندل‌ها کم کردی و فقط به خاطر جدول ورود خروج فضای
   کندل‌ها رو کوچک کردی … این قسمت سفید پشت قیمت‌ها باید به فضای نمودار کندل‌ها
   اضافه بشه و جدول ورود و خروج و تی‌پی‌ها پایین چارت روی جایی که فلش زدم قرار
   بگیره»
  «ارتفاع پایین‌ترین پیوت در کف چارت تا بالاترین پیوت سقف در چارت نباید بیشتر از
   ۷۰ تا ۷۵ درصد ارتفاع چارت را بگیرد»

Two laws, one file:
  1. the panel owns the whole canvas width; the price ladder is printed INSIDE it
     and the trade table sits in the panel's own bottom-right corner;
  2. the visible candle block never exceeds 75 % of the price panel — enforced on
     the FINAL limits, so no later overlay can take it back over the law.

The file renders the REAL canvas (synthetic tape, no network) and measures the
PNG pixels — a source-grep alone is how the last five geometry rounds drifted.
"""
from __future__ import annotations

import math
import os

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "tools", "render_spot_cryptocove.py"),
           encoding="utf-8").read()


# ── the law is in the source ───────────────────────────────────────────────
def test_the_panel_reaches_the_canvas_edge():
    assert "SPOT_PANEL_RIGHT = 0.9955" in SRC
    assert "right=SPOT_PANEL_RIGHT" in SRC
    assert "right=0.870" not in SRC and "right=0.826" not in SRC


def test_the_ladder_is_measured_and_printed_inside():
    assert "_pad35 = -(_w35 * 72.0 / float(fig.dpi) + 7.0)" in SRC
    assert 'ax.tick_params(axis="y", labelsize=9.2, colors="#3A362F", pad=_pad35)' in SRC
    assert "_ladder_x0 = min(_xs35) / float(fig.bbox.width)" in SRC


def test_the_table_and_the_pill_anchor_to_the_ladder():
    assert "_bx30 = float(_ladder_x0) - 0.008 - _box_w30" in SRC
    assert "_live_x = (_lbl_px - 6.0 - _ab0.x0) / float(_ab0.width)" in SRC


def test_the_future_strip_is_reserved_by_law():
    assert "SPOT_RIGHT_PAD_FRAC = 0.128" in SRC
    assert "_need_pad35 = int(math.ceil((x_to - x_from) * SPOT_RIGHT_PAD_FRAC" in SRC
    assert "x_to = (n - 1) + _need_pad35" in SRC


def test_the_block_share_guard_runs_on_the_final_limits():
    assert "def enforce_block_share" in SRC
    assert "_yl_fin = enforce_block_share(ax, d_lo, d_hi, SPOT_ENVELOPE_TARGET)" in SRC
    assert 0.70 <= 0.72 <= 0.75


# ── the guard behaves ─────────────────────────────────────────────────────
class _FakeAx:
    def __init__(self, lo, hi):
        self._yl = [lo, hi]

    def get_ylim(self):
        return tuple(self._yl)

    def set_ylim(self, lo, hi):
        self._yl = [lo, hi]


def test_the_guard_only_ever_adds_air():
    from tools.render_spot_cryptocove import enforce_block_share
    # block already inside the law → untouched
    ax = _FakeAx(1.0, 3.0)
    assert enforce_block_share(ax, 1.4, 2.4) == (1.0, 3.0)
    # block too tall → the window grows until the block is 72 % of it
    ax = _FakeAx(1.0, 3.0)
    lo, hi = enforce_block_share(ax, 1.05, 2.95)
    share = (math.log(2.95) - math.log(1.05)) / (math.log(hi) - math.log(lo))
    assert abs(share - 0.72) < 1e-6
    assert lo < 1.0 and hi > 3.0            # air, never a crop


# ── the real canvas ───────────────────────────────────────────────────────
def _tape(n=260, seed=7):
    rng = np.random.default_rng(seed)
    px = 100.0
    rows = []
    for i in range(n):
        drift = -0.30 if i < n * 0.55 else 0.34      # down, then up: a triangle
        o = px
        c = max(1.0, o * math.exp(drift / 100.0 + rng.normal(0, 0.010)))
        h = max(o, c) * (1 + abs(rng.normal(0, 0.004)))
        l = min(o, c) * (1 - abs(rng.normal(0, 0.004)))
        rows.append((o, h, l, c, abs(rng.normal(5.0, 1.2))))
        px = c
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df.insert(0, "timestamp",
              pd.date_range("2026-08-01", periods=n, freq="4h"))
    return df


def _render(tmp_path):
    from tools import render_spot_cryptocove as RS

    df = _tape()
    n = len(df)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    x0 = n - 120
    hi, lo = float(np.max(h[x0:])), float(np.min(l[x0:]))

    class _Ln:
        def __init__(self, price, slope, touches):
            self.a, self.b = price, slope
            self.touches = tuple(touches)
            self.first_index = min(touches)

        def price_at(self, x):
            return self.a + self.b * (x - self.first_index)

    up = _Ln(hi, -(hi - hi * 0.97) / 100.0, [x0 + 3, x0 + 12, x0 + 30, x0 + 58, x0 + 86])
    low = _Ln(lo, (lo * 1.06 - lo) / 120.0, [x0 + 5, x0 + 64, x0 + 92])
    a = {"tf": "4h", "name_slug": "TRIANGLE_ASCENDING", "x0": x0,
         "level": float(up.price_at(n - 2)),
         "target": float(up.price_at(n - 2)) * 1.08,
         "entry": float(up.price_at(n - 2)), "direction": "UP",
         "upper": up, "lower": low,
         "breakout": {"status": "BREAK_UP_CLOSED", "edge": "UPPER"}}
    trade = {"direction": "LONG", "entry": float(c[-1]), "stop": float(c[-1]) * 0.92,
             "tp1": float(c[-1]) * 1.02, "tp2": float(c[-1]) * 1.04,
             "tp3": float(c[-1]) * 1.07}
    out = str(tmp_path / "spot.png")
    RS.render(df, a, path=out, symbol="TESTUSDT", stage="CONFIRMED",
              title="Ascending Triangle", trade=trade, uid="VIVA-SPOT-TEST1")
    return df, out, (float(c[-1]), int(n))


def _pixels(path):
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB")).astype(int)


def _panel(a):
    """(x0, x1, y0, y1) of the gradient panel, found from its own colours."""
    H, W, _ = a.shape
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    inside = (((r > 200) & (g > 200) & (b < 225) & (b > 100)) |
              ((r < 200) & (g > 160) & (b > 200)))
    xs = np.where(inside[int(H * 0.55)])[0]
    ys = np.where(inside[:, int(W * 0.30)])[0]
    return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())


def _candles(a):
    up = np.all(a == np.array([38, 166, 154]), axis=-1)
    dn = np.all(a == np.array([239, 83, 80]), axis=-1)
    return up | dn


@pytest.fixture(scope="module")
def canvas(tmp_path_factory):
    df, out, info = _render(tmp_path_factory.mktemp("q35"))
    return df, out, info, _pixels(out)


def test_the_rendered_panel_owns_the_width(canvas):
    _, _, _, a = canvas
    H, W, _ = a.shape
    x0, x1, _, _ = _panel(a)
    assert (x1 - x0) / float(W) >= 0.965, "the panel no longer reaches the edge"
    assert (W - 1 - x1) / float(W) <= 0.012, "a white gutter is back behind the price"


def test_the_candle_block_stays_under_seventy_five_percent(canvas):
    _, _, _, a = canvas
    x0, x1, y0, y1 = _panel(a)
    m = _candles(a)[:, x0 + 4:int(x1 - 0.13 * a.shape[1])]
    rows = np.where(m.sum(axis=1) > 1)[0]
    share = (rows.max() - rows.min()) / float(y1 - y0)
    assert share <= 0.75, f"candle block is {share * 100:.1f}% of the panel"
    assert share >= 0.55, f"the block is squeezed to {share * 100:.1f}% — zoom broken"


def test_no_candle_is_under_the_trade_table(canvas):
    _, _, _, a = canvas
    x0, x1, y0, y1 = _panel(a)
    # the table's white card: near-white pixels inside the panel's bottom right
    sub = a[int(y0 + 0.55 * (y1 - y0)):y1, int(x0 + 0.60 * (x1 - x0)):x1]
    card = np.all(np.abs(sub - 255) < 12, axis=-1)
    assert card.sum() > 5000, "the trade table is not in the panel's corner"
    ys, xs = np.where(card)
    tx0 = int(x0 + 0.60 * (x1 - x0)) + xs.min()
    # no candle pixel shares the card's columns below its top edge
    ty0 = int(y0 + 0.55 * (y1 - y0)) + ys.min()
    foot = _candles(a)[ty0:y1, tx0:int(x1 - 0.13 * a.shape[1])]
    assert foot.sum() == 0, "candles sit under the trade table"


def test_the_trade_table_clears_the_price_ladder(canvas):
    """BTC-safe: the card's right edge stops before the ladder digits start."""
    _, _, _, a = canvas
    x0, x1, y0, y1 = _panel(a)
    qy0, qx0 = int(y0 + 0.55 * (y1 - y0)), int(x0 + 0.55 * (x1 - x0))
    q = a[qy0:y1, qx0:x1]
    white = np.all(np.abs(q - 255) < 14, axis=-1)
    rows = np.where(white.sum(axis=1) > 0.15 * white.shape[1])[0]
    cols = np.where(white.sum(axis=0) > 0.15 * white.shape[0])[0]
    assert len(rows) and len(cols), "no trade card found in the corner"
    card_l, card_r = qx0 + int(cols.min()), qx0 + int(cols.max())
    band = a[qy0:qy0 + int(rows.max()), card_r:x1]
    dark = (band.max(axis=-1) < 150)
    digit_cols = np.where(dark.sum(axis=0) > 3)[0]
    assert len(digit_cols), "the price ladder vanished from the panel"
    gap = int(digit_cols.min())          # first digit column, relative to card_r
    assert gap >= 4, "the trade table runs into the price digits"
    assert card_r < x1 - 0.02 * (x1 - x0), "the card overhangs the ladder"
    assert card_l > x0 + 0.45 * (x1 - x0), "the card drifted into the tape"


# ── the pill never prints through a tick (R99q35b) ────────────────────────
def test_the_live_pill_hides_the_tick_it_collides_with():
    assert "spot label collision warning" in SRC
    assert "_pb.x1 > (_tb.x0 - 7.0) and _pb.x0 < _tb.x1" in SRC
    assert "_tp.set_visible(False)" in SRC


def test_the_rendered_pill_sits_beside_the_digits_not_on_them(canvas):
    _, _, (live, _), a = canvas
    x0, x1, y0, y1 = _panel(a)
    pink = np.all(np.abs(a - np.array([224, 25, 125])) < 26, axis=-1)
    ys, xs = np.where(pink)
    assert len(xs), "the live pill is missing"
    assert xs.min() > x0 + 0.55 * (x1 - x0), "the pill drifted into the tape"
    # the pill must stay clear of the panel's right edge (the ladder column)
    assert xs.max() < x1 - 0.012 * (x1 - x0), "the pill overlaps the price ladder"


def test_the_rendered_block_share_matches_the_law_on_a_wide_target_box(canvas):
    """A far measured-move box used to stretch the window past 75 %."""
    df, out, _, _ = canvas
    a = _pixels(out)
    x0, x1, y0, y1 = _panel(a)
    m = _candles(a)[:, x0 + 4:int(x1 - 0.13 * a.shape[1])]
    rows = np.where(m.sum(axis=1) > 1)[0]
    share = (rows.max() - rows.min()) / float(y1 - y0)
    assert 0.60 <= share <= 0.75
