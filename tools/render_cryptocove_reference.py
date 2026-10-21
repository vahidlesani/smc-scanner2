"""CryptoCove Parallel Channel Engine & Reference Renderer for VIVA Signals Pro.

Recreates the exact CryptoCove spot signature:
1. Log-scale price coordinates.
2. Parallel descending channel (upper resistance + lower support with identical slope in log-space).
3. Breakout at the live end of the channel.
4. Green measured-move box with vertical profit arrow (+280%, +270%, etc.).
5. VIVA brand signature styling: Cream/vanilla background, crisp black/hollow candles,
   gold diamond badge, clear margins and sky-padding.
"""
import os
import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from data.fetcher import get_klines

# Theme definition
THEME = {
    "bg": "#F8F5EE",
    "panel": "#FFFFFF",
    "text": "#1A1A1A",
    "muted": "#7A766F",
    "grid": "#E8E4D9",
    "candle_up": "#242424",
    "candle_down": "#242424",
    "candle_wick": "#4A4A4A",
    "channel_line": "#1F2328",
    "box_green": "#4CAF50",
    "box_bg": "#C8E6C9",
    "box_alpha": 0.45,
    "brand_gold": "#D4AF37",
}


def fit_cryptocove_channel(df: pd.DataFrame):
    """Fit a mathematically clean CryptoCove parallel descending channel in log10 space."""
    n = len(df)
    if n < 60:
        return None

    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    close = df["close"].astype(float).to_numpy()

    log_h = np.log10(np.clip(high, 1e-12, None))
    log_l = np.log10(np.clip(low, 1e-12, None))
    log_c = np.log10(np.clip(close, 1e-12, None))

    # 1. Identify the major initial peak in the first 40% of the window
    first_half_len = int(n * 0.45)
    i_peak = int(np.argmax(log_h[:first_half_len]))
    x0, y0 = float(i_peak), float(log_h[i_peak])

    best_fit = None
    best_score = -1e9

    # Candidate second anchor for resistance line across the middle/later section
    for x1 in range(i_peak + 20, n - 4):
        y1 = float(log_h[x1])
        if y1 >= y0:
            continue
        slope = (y1 - y0) / (x1 - x0)
        intercept = y0 - slope * x0

        # Model line at all indices
        xs = np.arange(n)
        line_vals = slope * xs + intercept

        # Penalize candles cutting through the line before break
        violations = np.sum(log_h[:n - 5] > line_vals[:n - 5] + 0.015)
        if violations > 2:
            continue

        # Count touches (within 0.04 in log space)
        diffs = np.abs(log_h[i_peak:n - 5] - line_vals[i_peak:n - 5])
        touches = np.sum(diffs <= 0.035)

        # Ensure price breaks out at the live end (last 5 candles)
        recent_break = np.any(log_c[-5:] > line_vals[-5:])
        if not recent_break:
            continue

        # Measure lower channel offset: lowest low relative to upper line
        offsets = line_vals[i_peak:n] - log_l[i_peak:n]
        valid_offsets = offsets[offsets > 0]
        if len(valid_offsets) == 0:
            continue
        # Channel width is the 97th percentile offset so it catches major bottoms cleanly
        ch_width = float(np.percentile(valid_offsets, 97))

        score = touches * 10.0 + (x1 - x0) * 0.2 - violations * 25.0
        if score > best_score:
            best_score = score
            best_fit = {
                "x0": x0,
                "slope": slope,
                "intercept": intercept,
                "ch_width": ch_width,
                "touches": touches,
            }

    # Fallback if no clean break found: use standard descending channel
    if not best_fit:
        x1 = n - 15
        y1 = float(log_h[x1])
        slope = (y1 - y0) / max(1, x1 - x0)
        intercept = y0 - slope * x0
        xs = np.arange(n)
        line_vals = slope * xs + intercept
        offsets = line_vals[i_peak:] - log_l[i_peak:]
        ch_width = float(np.percentile(offsets[offsets > 0], 95)) if np.any(offsets > 0) else 0.3
        best_fit = {
            "x0": x0,
            "slope": slope,
            "intercept": intercept,
            "ch_width": ch_width,
            "touches": 3,
        }

    return best_fit


def render_cryptocove_chart(symbol: str, tf: str, df: pd.DataFrame, out_path: str):
    """Render a high-resolution CryptoCove-styled chart matching the user's reference exactly."""
    fit = fit_cryptocove_channel(df)
    if not fit:
        print(f"Failed to fit channel for {symbol}")
        return False

    n = len(df)
    future_pad = 45  # Space for measured move box
    total_x = n + future_pad

    fig, ax = plt.subplots(figsize=(16, 9), dpi=140)
    fig.patch.set_facecolor(THEME["bg"])
    ax.set_facecolor(THEME["bg"])

    # Log scale for price
    ax.set_yscale("log")

    # Plot grid
    ax.grid(True, which="both", color=THEME["grid"], linestyle="-", linewidth=0.6, alpha=0.7)

    # Plot Candlesticks
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    opens = df["open"].astype(float).values
    closes = df["close"].astype(float).values

    width = 0.58
    for i in range(n):
        o, c, h, l = opens[i], closes[i], highs[i], lows[i]
        # Wick
        ax.plot([i, i], [l, h], color=THEME["candle_wick"], linewidth=1.1, zorder=3)
        # Body: hollow for up, solid black for down (TradingView clean mono style)
        if c >= o:
            rect = patches.Rectangle((i - width/2, o), width, max(c - o, 1e-6),
                                     facecolor=THEME["panel"], edgecolor=THEME["candle_up"],
                                     linewidth=1.2, zorder=4)
        else:
            rect = patches.Rectangle((i - width/2, c), width, max(o - c, 1e-6),
                                     facecolor=THEME["candle_down"], edgecolor=THEME["candle_down"],
                                     linewidth=1.2, zorder=4)
        ax.add_patch(rect)

    # Calculate channel lines
    x0 = fit["x0"]
    slope = fit["slope"]
    ic_up = fit["intercept"]
    w = fit["ch_width"]
    ic_lo = ic_up - w

    # Extend line to the breakout area + small forward projection
    x_end = n + 10
    xs_line = np.linspace(x0, x_end, 200)
    y_up = 10.0 ** (slope * xs_line + ic_up)
    y_lo = 10.0 ** (slope * xs_line + ic_lo)

    # Plot Upper and Lower Channel Lines (Crisp Black like CryptoCove reference)
    ax.plot(xs_line, y_up, color=THEME["channel_line"], linewidth=2.0, zorder=6, solid_capstyle="round")
    ax.plot(xs_line, y_lo, color=THEME["channel_line"], linewidth=2.0, zorder=6, solid_capstyle="round")

    # Measured Move Box at Breakout
    # Breakout candle: last candle or near last candle
    i_break = n - 1
    p_break = 10.0 ** (slope * i_break + ic_up)
    target_mult = 10.0 ** w
    p_target = p_break * target_mult
    profit_pct = (target_mult - 1.0) * 100.0

    box_x0 = i_break
    box_x1 = i_break + 35
    box_w = box_x1 - box_x0

    # Draw Green Target Box
    rect_box = patches.Rectangle(
        (box_x0, p_break), box_w, p_target - p_break,
        facecolor=THEME["box_bg"], edgecolor=THEME["box_green"],
        linewidth=1.5, alpha=THEME["box_alpha"], zorder=5
    )
    ax.add_patch(rect_box)

    # Vertical arrow inside the box
    arrow_x = box_x0 + box_w * 0.5
    ax.annotate(
        "", xy=(arrow_x, p_target), xytext=(arrow_x, p_break),
        arrowprops=dict(arrowstyle="->", color=THEME["box_green"], lw=2.0, mutation_scale=15),
        zorder=7
    )

    # Profit percentage label at top of arrow
    ax.text(
        arrow_x, p_target * 1.05, f"{p_target - p_break:.4g} (+{profit_pct:.1f}%)",
        color="#1B5E20", fontsize=10.5, fontweight="bold", ha="center", va="bottom", zorder=8
    )

    # Horizontal guideline from breakout level
    ax.hlines(p_break, box_x0, box_x1, colors=THEME["channel_line"], linestyles="-", linewidth=1.2, zorder=5)

    # Watermark / Symbol Label in center background
    y_mid = math.sqrt(float(np.min(lows)) * float(np.max(highs)))
    ax.text(
        n * 0.45, y_mid, f"{symbol}, {tf.upper()}",
        color="#E2DDD2", fontsize=48, fontweight="bold", ha="center", va="center", zorder=1
    )

    # Header / Meta
    fig.text(0.04, 0.95, f"{symbol}  •  {tf.upper()}  •  SPOTBREAK", fontsize=16, fontweight="bold", color=THEME["text"])
    fig.text(0.04, 0.92, "CryptoCove Parallel Channel  •  Log Scale  •  Measured Target Box", fontsize=11, color=THEME["muted"])

    # CryptoCove Badge in bottom right
    fig.text(0.95, 0.04, "CryptoCove  •  VIVA SIGNALS PRO", fontsize=13, fontweight="bold", color=THEME["text"], ha="right")

    # Set smart axis limits with sky padding
    y_min_val = float(np.min(y_lo)) * 0.82
    y_max_val = max(float(np.max(highs)), p_target) * 1.35
    ax.set_ylim(y_min_val, y_max_val)
    ax.set_xlim(-5, total_x)

    # Clean axes
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(True)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(THEME["muted"])
    ax.spines["right"].set_color(THEME["muted"])
    ax.tick_params(colors=THEME["muted"], labelsize=10)

    # Format Y-axis to neat numbers
    from matplotlib.ticker import FuncFormatter
    def price_fmt(x, _):
        if x >= 1000:
            return f"{x:,.0f}"
        elif x >= 1:
            return f"{x:.2f}"
        elif x >= 0.01:
            return f"{x:.4f}"
        else:
            return f"{x:.6f}"
    ax.yaxis.set_major_formatter(FuncFormatter(price_fmt))
    ax.yaxis.tick_right()

    plt.tight_layout(rect=[0.02, 0.02, 0.98, 0.94])
    plt.savefig(out_path, facecolor=THEME["bg"])
    plt.close()
    print(f"Saved: {out_path}")
    return True


if __name__ == "__main__":
    targets = [
        ("ZROUSDT", "3d", "/home/user/cryptocove_render_ZROUSDT_3D.png"),
        ("JASMYUSDT", "3d", "/home/user/cryptocove_render_JASMYUSDT_3D.png"),
        ("REZUSDT", "3d", "/home/user/cryptocove_render_REZUSDT_3D.png"),
        ("WLDUSDT", "3d", "/home/user/cryptocove_render_WLDUSDT_3D.png"),
    ]
    for sym, tf, path in targets:
        df = get_klines(sym, tf, limit=200)
        if df is not None and not df.empty:
            render_cryptocove_chart(sym, tf, df, path)
        else:
            print(f"Skipping {sym}: no data")
