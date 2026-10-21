"""R99q38n — vertical zoom when ONE spike owns the spot window (his 10-21 #17)."""
import numpy as np

from tools.render_spot_cryptocove import spot_spike_band


def _tape(n=160, spike_at=60, k=1.45, live_spike=False):
    rng = np.random.default_rng(7)
    close = 1.0 + np.cumsum(rng.normal(0, 0.004, n)) + 0.10 * np.sin(np.arange(n) / 9.0)
    open_ = close + rng.normal(0, 0.002, n)
    high = np.maximum(open_, close) + 0.004
    low = np.minimum(open_, close) - 0.004
    i = n - 1 if live_spike else spike_at
    high[i] = close[i] * k
    return low, high, open_, close


def test_a_lone_wick_no_longer_flattens_the_window():
    low, high, o, c = _tape()
    sl = slice(0, len(low))
    lo, hi = float(low.min()), float(high.max())
    b_lo, b_hi, applied = spot_spike_band(low, high, o, c, sl, lo, hi)
    assert applied is True
    assert (b_hi - b_lo) < 0.55 * (hi - lo)
    assert b_hi < hi                      # the wick is the only thing clipped


def test_a_spike_on_the_live_candle_is_never_zoomed():
    low, high, o, c = _tape(live_spike=True)
    sl = slice(0, len(low))
    lo, hi = float(low.min()), float(high.max())
    _, _, applied = spot_spike_band(low, high, o, c, sl, lo, hi)
    assert applied is False


def test_a_real_body_outside_the_band_blocks_the_zoom():
    """Only a WICK may be clipped — a body outside the band keeps the old window."""
    low, high, o, c = _tape()
    i = 60
    c[i] = c[i] * 1.40        # the spike bar CLOSES far above the band
    o[i] = c[i] * 0.99
    high[i] = c[i] * 1.01
    sl = slice(0, len(low))
    lo, hi = float(low.min()), float(high.max())
    _, _, applied = spot_spike_band(low, high, o, c, sl, lo, hi)
    assert applied is False


def test_a_quiet_tape_is_left_alone():
    low, high, o, c = _tape(k=1.0)
    sl = slice(0, len(low))
    lo, hi = float(low.min()), float(high.max())
    _, _, applied = spot_spike_band(low, high, o, c, sl, lo, hi)
    assert applied is False
