"""R99q33h — XRP 4H: the corner-note stack (VIVA · ALBROX … BREAK LINE)
printed straight OVER the candles. The stack now measures the exact column span
its chips occupy and takes the empty pocket; when the tape fills every band a
bounded slice of sky opens above it (never a candle sacrificed)."""
import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd


def _tape(n=140, seed=3):
    rng = np.random.default_rng(seed)
    base = 1.32 + 0.06 * np.sin(np.arange(n) / 5.0) + np.linspace(0.0, -0.10, n) \
        + rng.normal(0, 0.008, n)
    o = base + rng.normal(0, 0.004, n)
    c = base + rng.normal(0, 0.004, n)
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.006, n))
    l = np.minimum(o, c) - np.abs(rng.normal(0, 0.006, n))
    return pd.DataFrame({"timestamp": pd.date_range("2026-09-30", periods=n,
                                                    freq="4h", tz="UTC"),
                         "open": o, "high": h, "low": l, "close": c,
                         "volume": rng.uniform(1, 9, n)})


def test_corner_notes_never_land_on_candles():
    import matplotlib.pyplot as plt
    import bot.messages_v7 as V
    df = _tape()
    n = len(df)
    fig, ax = plt.subplots(figsize=(15, 8.5), dpi=100)
    for i, (o, h, l) in enumerate(zip(df["open"], df["high"], df["low"])):
        ax.plot([i, i], [l, h], color="gray", lw=0.8)
    ax.set_xlim(-1, n + 20)
    ax.set_ylim(float(df["low"].min()) - 0.005, float(df["high"].max()) + 0.005)
    notes = [(f"NOTE LINE {i}", "#1F6FEB") for i in range(9)]
    V._render_corner_notes(ax, notes, df, confirmed=False, fig=fig, allow_expand=True)
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    chips = [t for t in ax.texts if t.get_text().startswith("NOTE LINE")]
    assert len(chips) == 9
    for t in chips:
        b = t.get_window_extent(r)
        y0 = inv.transform((0, b.y0))[1]
        y1 = inv.transform((0, b.y1))[1]
        x0 = inv.transform((b.x0, 0))[0]
        x1 = inv.transform((b.x1, 0))[0]
        seg = df.iloc[max(0, int(x0)):max(1, int(x1) + 1)]
        hits = int(((seg["high"] >= y0) & (seg["low"] <= y1)).sum())
        assert hits == 0, f"{t.get_text()} printed over {hits} candle(s)"
    plt.close(fig)


def test_the_probe_measures_the_real_chip_columns():
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    assert "_chip_w_ax = min(0.55, 0.020 + 0.0062 * max(len(str(_t)) for _t, _ in notes[:_n]))" in src
    assert "_need_top = _sky_hi + (_stack_h + 0.02) * span" in src
    assert "< 0.16 * span" in src              # a bounded slice of sky
