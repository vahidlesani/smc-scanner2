"""R99q31c — a higher-TF zone must be REFINED on the lower TF, never pasted.

His 10-20, verbatim:
  «اصلا نمی‌خوام یک زون تایم یا تایم‌های بالاتر بیاد توی تایم‌های کوچیک‌تر ...
   هر تایم پایین‌تر که میاد ریفاین بشه نه اینکه یه باکس یا چندتا باکس خیلی
   عریض و بزرگ بپره وسط چارت ۱۵ دقیقه»

The bug: `detect_zones` stores a bar INDEX (`x0`). Repainted on a 15m frame,
that index points at a different moment and the box is ~16× too wide.
"""
import numpy as np
import pandas as pd

from analysis.zone_refine import (MAX_ZONE_FRACTION, clip_zone_to_frame,
                                  prepare_zones, refine_zone_same_tf,
                                  zone_report)


def _mk(n, freq, start, base=100.0, vol=0.01, seed=3):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=n, freq=freq)
    c = base * (1 + rng.normal(0, vol, n)).cumprod()
    o = c * (1 + rng.normal(0, vol / 2, n))
    h = np.maximum(o, c) * (1 + abs(rng.normal(0, vol / 2, n)))
    l = np.minimum(o, c) * (1 - abs(rng.normal(0, vol / 2, n)))
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h,
                         "low": l, "close": c, "volume": 1.0})


def _zone(ts0, bottom=95.0, top=115.0):
    return {"kind": "SUPPLY", "bottom": bottom, "top": top, "x0": 100,
            "bias": "SUPPLY", "ts0": str(ts0)}


# ── law 1: re-anchor by TIME ───────────────────────────────────────────────
def test_a_zone_older_than_the_window_clips_to_the_first_visible_bar():
    small = _mk(300, "15min", "2026-10-18")
    z = _zone("2026-08-17 16:00")
    got = clip_zone_to_frame(z, small)
    assert got is not None
    assert got["x0"] == 0                     # clipped to the window edge
    assert got["clipped"] is True
    assert got["x1"] == len(small) - 1


def test_a_zone_inside_the_window_lands_on_its_real_bar():
    small = _mk(300, "15min", "2026-10-18")
    real = small["timestamp"].iloc[140]
    got = clip_zone_to_frame(_zone(real), small)
    assert got is not None
    assert abs(got["x0"] - 140) <= 1          # searchsorted, same bar
    assert got["clipped"] is False


def test_a_zone_without_a_timestamp_is_left_alone():
    assert clip_zone_to_frame({"kind": "X", "bottom": 1, "top": 2, "x0": 5},
                              _mk(60, "15min", "2026-10-18")) is None


# ── law 2: refine the edges on the TF being drawn ──────────────────────────
def test_refining_re_measures_the_edges_from_this_frames_tape():
    # a frame that only ever trades 99..101 inside a 95..115 band
    n = 120
    ts = pd.date_range("2026-10-18", periods=n, freq="15min")
    c = np.full(n, 100.0)
    df = pd.DataFrame({"timestamp": ts, "open": c, "close": c,
                       "high": c + 1.0, "low": c - 1.0, "volume": 1.0})
    got = refine_zone_same_tf(_zone(ts[10]), df)
    assert got is not None
    assert got["refined"] is True
    assert got["bottom"] >= 98.9 and got["top"] <= 101.1
    assert got["top"] - got["bottom"] < 20.0     # the 20-wide stamp is gone


def test_a_zone_the_lower_tf_never_visited_is_gone():
    n = 120
    ts = pd.date_range("2026-10-18", periods=n, freq="15min")
    c = np.full(n, 100.0)
    df = pd.DataFrame({"timestamp": ts, "open": c, "close": c,
                       "high": c + 0.5, "low": c - 0.5, "volume": 1.0})
    # a 300..400 zone: this TF never traded there
    z = {"kind": "SUPPLY", "bottom": 300.0, "top": 400.0, "x0": 5,
         "ts0": str(ts[5])}
    out = prepare_zones([z], df)
    assert out == []


# ── law 3: the poster guard ────────────────────────────────────────────────
def test_a_box_wider_than_a_third_of_the_chart_is_not_drawn():
    df = _mk(200, "15min", "2026-10-18", vol=0.004)
    px_lo, px_hi = float(df["low"].min()), float(df["high"].max())
    span = px_hi - px_lo
    z = {"kind": "SUPPLY", "bottom": px_lo, "top": px_hi,
         "x0": 10, "ts0": str(df["timestamp"].iloc[10])}
    out = prepare_zones([z], df)
    assert out == []
    # and a sane box of the same shape survives
    z2 = {"kind": "SUPPLY", "bottom": px_hi * 0.995, "top": px_hi * 1.005,
          "x0": 10, "ts0": str(df["timestamp"].iloc[10])}
    assert len(prepare_zones([z2], df)) == 1


def test_the_report_line_counts_both_laws():
    small = _mk(200, "15min", "2026-10-18")
    z = _zone("2026-08-17 16:00", bottom=99.0, top=101.5)
    out = prepare_zones([z], small)
    txt = zone_report(out)
    assert txt.startswith("zones=")
    assert "clipped=" in txt and "refined=" in txt


def test_prepare_never_raises_on_garbage():
    df = _mk(60, "15min", "2026-10-18")
    assert prepare_zones([], df) == []
    assert prepare_zones([{}, {"bottom": "x"}], df) == []
    # an empty frame is not evidence: the caller's list is handed back intact
    assert prepare_zones([{"bottom": 1, "top": 2}], pd.DataFrame()) == \
        [{"bottom": 1, "top": 2}]
