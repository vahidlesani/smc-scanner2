"""R99q30 — spot chart quality (his 10-20 report) + hourly cadence.

What he reported, in his words:
  «لوگو من در بالای چارت … اندازه و کیفیتش بالا بره … متن اسم خودم و برندم
   فقط جلوش بیاد … چرا بردی روی محور قیمت گذاشتی اونم خیلی کوچیک و بی کیفیت»
  «اطلاعات ورود به پوزیشن هم بیاد روبروی هیستوگرام های حجم»
  «چرا هیستوگرام های اسپات رو از روی چارت جدا کردی»
  «رنگ لیبلها هم تغییر کرده»
  «محور قیمتها همه قیمتها له شده به بالا»
  «پترن کج و داغون بی هویت»
  «فعلا که خشکه باید ساعتی کنیم»

Root cause found while fixing: the R99q28 design tests were pinned to
`analysis/spot_pattern_engine.py`, which is NO LONGER in the render path — the
live renderer is `tools/render_spot_cryptocove.py`. Every spot fix he asked for
on 10-19 was applied to the dead file.
"""
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPOT = open(os.path.join(ROOT, "tools", "render_spot_cryptocove.py"),
            encoding="utf-8").read()
MSG = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
TIER = open(os.path.join(ROOT, "analysis", "tiered_scan.py"),
            encoding="utf-8").read()
MAIN = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


# ── the logo: bigger, sharper, beside the full brand line ──────────────────
def test_the_spot_canvas_prints_at_the_setups_resolution():
    assert "dpi=240" in SPOT          # was 180 while setups printed 240


def test_the_mark_is_resampled_and_the_brand_sits_beside_it():
    assert "VAHID LESANI — VIVA SIGNALS PRO" in SPOT
    assert SPOT.count("interpolation=\"lanczos\"") >= 3
    assert "_logo_img()" in SPOT                       # the 4× asset loader
    assert "_lh30 = 0.062" in SPOT                    # bigger than the old 0.055


def test_the_credit_cannot_land_on_the_price_axis():
    # the panel top moved down to leave a real header band
    assert "top=0.898" in SPOT
    assert "top=0.915" not in SPOT


def test_a_hires_brand_asset_ships():
    p = os.path.join(ROOT, "assets", "vivasignals-logo@4x.png")
    assert os.path.isfile(p)
    from PIL import Image
    with Image.open(p) as im:
        assert im.size[0] >= 900 and im.size[1] >= 900


# ── colours and the histogram ──────────────────────────────────────────────
def test_spot_candles_are_teal_and_red_again():
    assert 'SPOT_UP = "#26A69A"' in SPOT
    assert 'SPOT_DN = "#EF5350"' in SPOT
    assert '"#FFFFFF" if bool(is_up)' not in SPOT       # the white/black drift


def test_the_volume_histogram_lives_in_the_price_panel_and_is_tinted():
    assert "_hgt = 0.088 * d_span" in SPOT             # readable, not tick marks
    assert "facecolor=SPOT_UP if c[i] >= o[i] else SPOT_DN" in SPOT
    assert "#AEB4BC" not in SPOT                       # the grey dashes are gone
    assert "ax.add_patch(Rectangle((i - 0.33, _base)" in SPOT


# ── the price axis ─────────────────────────────────────────────────────────
def test_price_ticks_are_round_on_a_log_axis():
    from tools.render_spot_cryptocove import _log_ticks
    ticks, dec = _log_ticks(0.40, 12.9)
    assert len(ticks) >= 6
    assert dec == 1
    # every label is a round mantissa, never 12.59 / 2.51
    assert all(abs(t - round(t, dec)) < 1e-9 for t in ticks)
    assert 0.4 in ticks and 10.0 in ticks
    # a narrow high-price window falls back to a linear round step
    t2, d2 = _log_ticks(380, 680)
    assert len(t2) >= 6 and d2 == 0 and 400.0 in t2


# ── the pattern must sit on its pivots ─────────────────────────────────────
def test_a_solid_edge_always_spans_first_pivot_to_last_touch():
    assert "_span_end = min(n - 1, max(_last_t, _first_i + 1))" in SPOT
    # the old collapse-to-one-bar form is gone
    assert "max(_last_t, int(getattr(ln, \"first_index\", x_from)))" not in SPOT


# ── entry / stop / targets beside the volume ──────────────────────────────
def test_the_trade_strip_exists_and_is_opt_in():
    assert "def render(df: pd.DataFrame, a: dict, path: str = None, symbol: str = \"\"," in SPOT
    assert "trade: dict = None" in SPOT
    assert "uid: str = \"\"" in SPOT          # R99q31b unique id
    assert "TRADE BOX" in SPOT
    for tag in ('"ENTRY"', '"STOP"', 'f"TP{_i30 + 1}"'):
        assert tag in SPOT
    assert "_by30 = 0.062" in SPOT       # level with the volume band
    # R99q33g (his 10-20): the box is COMPACT and sits flush to the right edge
    assert "_bx30 = 0.995 - _box_w30" in SPOT   # the RIGHT column, flush
    assert "_box_w30 = 0.084" in SPOT           # one small grouped box


def test_the_candidate_supplies_the_strip():
    assert "trade=_trade30 or None" in MSG
    assert '"stop": float(getattr(candidate, "sl", 0) or 0)' in MSG
    assert "target_ladder" in MSG


# ── hourly cadence (his «باید ساعتی کنیم») ────────────────────────────────
def test_the_hourly_cap_exists_and_defaults_to_ten():
    assert 'os.getenv("VIVA_HOURLY_CAP", "10")' in TIER
    assert "def hourly_pace_ok(" in TIER
    assert "def hourly_pace_incr(" in TIER


def test_the_scan_gate_is_the_hourly_cap_not_the_stacked_pace():
    assert "_tier99j.hourly_pace_ok(" in MAIN
    # the stacked gate that produced pace=92 / ready_new=0 is retired
    assert "if not _tier99j.sessions_enabled():" not in MAIN
    assert "_tier99j3.hourly_pace_incr(" in MAIN


def test_hourly_cap_behaves():
    from analysis import tiered_scan as t
    seen = {}

    class _KV:
        def get_json(self, k, d=None):
            return seen.get(k, d)

        def set_json(self, k, v):
            seen[k] = v
            return True

    old = t._kv
    t._kv = lambda: _KV()
    try:
        os.environ.pop("VIVA_HOURLY_CAP", None)
        assert t.hourly_cap() == 10
        code = "ZZTEST"
        for i in range(10):
            assert t.hourly_pace_ok(code) is True
            t.hourly_pace_incr(code)
        assert t.hourly_pace_ok(code) is False        # the 11th waits
        os.environ["VIVA_HOURLY_CAP"] = "0"
        assert t.hourly_pace_ok(code) is True         # kill switch
    finally:
        os.environ.pop("VIVA_HOURLY_CAP", None)
        t._kv = old


# ── R99q31b: geometry of the spot chrome ───────────────────────────────────
def test_the_credit_stays_inside_the_frame():
    """His 10-20: «گوشه سمت راست بالا اسم و برند و لوگو من از کادر خارج شده»."""
    assert "_right30 = 0.982" in SPOT
    assert "_lx30 = _right30 - _lw30" in SPOT
    assert "0.990 - _lw30" not in SPOT          # the clipped placement is gone


def test_the_panel_leaves_a_column_for_the_trade_box():
    """R99q33g: the panel is back near its old reach — «حاشیه چارت پشت قیمت
    رو سریع به حالت قبلی برگردون» + «این جا رو به چارت اضافه کن». The dead
    white column of R99q31b (0.826) is gone, but a narrow strip remains for
    the trade box AND the live price tag (never over the candles)."""
    assert "right=0.870" in SPOT
    assert "right=0.826" not in SPOT            # the dead column is retired
    assert "right=0.952" not in SPOT            # and the edge-cramped one too


def test_the_unique_id_is_drawn_and_sits_clear_of_the_time_axis():
    assert 'f"ID  {uid}"' in SPOT
    assert 'fig.text(0.020, 0.032, f"ID  {uid}"' in SPOT
    assert 'uid=str((candidate.metadata or {}).get("public_code")' in MSG
