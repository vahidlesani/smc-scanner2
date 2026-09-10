"""Render TechnoClassic preview charts for EVERY classical model using the
REAL fit pipeline (scan_edges) and the REAL branded renderer (generate_chart).
Output: /home/user/tc_previews/<model>.png + contact_sheet.png
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

N = 140
WICK = 0.6


def build_pattern(u0, su, l0, sl, up_idx, lo_idx, lower_scatter=False, keys_override=None):
    U = lambda i: u0 + su * i
    L = lambda i: l0 + sl * i
    if keys_override is not None:
        keys = sorted(keys_override)
        vals = np.zeros(N)
        for (i0, v0), (i1, v1) in zip(keys, keys[1:]):
            seg = np.linspace(v0, v1, i1 - i0 + 1)
            vals[i0:i1 + 1] = seg[: i1 - i0 + 1]
        ts = pd.date_range("2026-01-01", periods=N, freq="4h")
        return pd.DataFrame({
            "timestamp": ts, "open": vals - 0.01, "high": vals + WICK,
            "low": vals - WICK, "close": vals + 0.01,
            "volume": np.full(N, 1000.0), "turnover": np.full(N, 50000.0),
        })
    keys = [(0, (U(0) + L(0)) / 2.0)]
    for i in sorted(set(list(up_idx) + list(lo_idx))):
        if i in up_idx:
            keys.append((i, U(i) - WICK))
        elif lower_scatter:
            keys.append((i, L(i) + WICK + 4.0 * (i % 3)))
        else:
            keys.append((i, L(i) + WICK))
    keys.append((N - 1, (U(N - 1) + L(N - 1)) / 2.0))
    vals = np.zeros(N)
    for (i0, v0), (i1, v1) in zip(keys, keys[1:]):
        seg = np.linspace(v0, v1, i1 - i0 + 1)
        vals[i0:i1 + 1] = seg[: i1 - i0 + 1]
    ts = pd.date_range("2026-01-01", periods=N, freq="4h")
    return pd.DataFrame({
        "timestamp": ts, "open": vals - 0.01, "high": vals + WICK,
        "low": vals - WICK, "close": vals + 0.01,
        "volume": np.full(N, 1000.0), "turnover": np.full(N, 50000.0),
    })


def build_trigger(pattern, side, direction):
    line_now = float(pattern["high"].iloc[-1]) if False else None
    # line at last bar: recompute via same formulas from stored meta
    from analysis.pattern_engine import scan_edges  # noqa (cycle-free here)
    atr = float((pattern["high"] - pattern["low"]).tail(14).mean())
    anchor = float(pattern["close"].iloc[-1])
    tn = 34
    mid = np.full(tn, anchor - 0.5 * atr if direction == "LONG" else anchor + 0.5 * atr)
    o = mid.copy(); c = mid.copy()
    h = mid + 0.2 * atr; lo = mid - 0.2 * atr
    line = ANCHOR_LINE[0]
    if direction == "LONG":
        o[-1] = line - 0.15 * atr if side == "upper" else line - 1.3 * atr
        c[-1] = line + 1.2 * atr
    else:
        o[-1] = line + 0.15 * atr if side == "lower" else line + 1.3 * atr
        c[-1] = line - 1.2 * atr
    h[-1] = max(o[-1], c[-1]) + 0.05 * atr
    lo[-1] = min(o[-1], c[-1]) - 0.05 * atr
    ts = pd.date_range("2026-08-01", periods=tn, freq="15min")
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": lo, "close": c,
                         "volume": np.full(tn, 300.0), "turnover": np.full(tn, 15000.0)})


ANCHOR_LINE = {}


def preview(name, u0, su, l0, sl, up_idx, lo_idx, side, direction, state_break,
            lower_scatter=False, fade=False, keys_override=None):
    from analysis.pattern_engine import scan_edges, STATE_BREAK
    global ANCHOR_LINE
    pattern = build_pattern(u0, su, l0, sl, up_idx, lo_idx, lower_scatter, keys_override)
    n = N - 1
    # exact fitted line price at last bar (touches are on the formula line)
    line_now = (u0 + su * n) if side == "upper" else (l0 + sl * n)
    ANCHOR_LINE[0] = line_now
    atr = float((pattern["high"] - pattern["low"]).tail(14).mean())
    trig = build_trigger(pattern, side, direction)
    if fade:
        # Brooks/Alfonso rejection bar: wick beyond the tested line, close back inside
        if side == "upper":
            op, cl, hi, lw = line_now - .4 * atr, line_now - .15 * atr, line_now + .5 * atr, line_now - .6 * atr
        else:
            op, cl, hi, lw = line_now + .4 * atr, line_now + .15 * atr, line_now + .6 * atr, line_now - .5 * atr
    elif not state_break:  # NEAR: sit just inside the edge
        cl = line_now - 0.8 * atr if direction == "LONG" else line_now + 0.8 * atr
        op = cl - 0.02 * atr
        hi, lw = max(op, cl) + 0.05 * atr, min(op, cl) - 0.05 * atr
    if fade or not state_break:
        for col, val in (("open", op), ("close", cl), ("high", hi), ("low", lw)):
            trig.iat[-1, trig.columns.get_loc(col)] = val
    # keep the printed chart honest: the live candle on the pattern frame
    # must match the trigger close (production shows both from the same tape)
    for _c in ("open", "close", "high", "low"):
        pattern.iat[-1, pattern.columns.get_loc(_c)] = float(trig[_c].iloc[-1])
    pattern.iat[-1, pattern.columns.get_loc("high")] = max(float(pattern["high"].iloc[-1]),
                                                           float(trig["high"].iloc[-1]))
    pattern.iat[-1, pattern.columns.get_loc("low")] = min(float(pattern["low"].iloc[-1]),
                                                          float(trig["low"].iloc[-1]))
    events = [e for e in scan_edges(pattern, trig, "4h")
              if e["side"] == side and e["direction"] == direction]
    assert events, f"{name}: engine produced no event"
    ev = dict(events[0]); ev["symbol"] = name.split("_", 1)[1].upper()
    from bot.messages_v7 import _technoclassic_preview_candidate, generate_chart
    if fade and ev.get("fade"):
        assert ev["state"] == "REJECTION_FADE", f"{name}: {ev['state']}"
    if not state_break and not fade:
        ev["state"] = "EDGE_NEAR"
    cand = _technoclassic_preview_candidate(ev)
    png = generate_chart(pattern, cand, confirmed=state_break)
    assert png, f"{name}: renderer returned None"
    out = f"/home/user/tc_previews/{name}.png"
    with open(out, "wb") as f:
        f.write(png)
    print("saved", out, "| pattern:", ev["pattern"], "| state:", ev["state"],
          "| target:", round(ev["measured"]["to"], 2), f'({ev["measured"]["pct"]:+.1f}%)')
    return out, f"{name}  [{ev['pattern']} / {ev['state']}]"


def main():
    os.makedirs("/home/user/tc_previews", exist_ok=True)
    up_idx = (45, 95, 125)
    lo_idx = (70, 112, 132)
    made = []
    made.append(preview("01_falling_wedge_NEAR", 100, -0.10, 72, -0.04, up_idx, lo_idx, "upper", "LONG", False))
    made.append(preview("02_falling_wedge_BREAK", 100, -0.10, 72, -0.04, up_idx, lo_idx, "upper", "LONG", True))
    made.append(preview("03_rising_wedge_BREAK_short", 80, 0.05, 44, 0.12, (30, 95, 125), (55, 112, 132), "lower", "SHORT", True))
    made.append(preview("04_ascending_triangle_BREAK", 95.5, 0.0, 58, 0.10, up_idx, lo_idx, "upper", "LONG", True))
    made.append(preview("05_descending_triangle_BREAK", 100, -0.10, 60, 0.0, up_idx, lo_idx, "lower", "SHORT", True))
    made.append(preview("06_symmetrical_triangle_BREAK", 100, -0.08, 52, 0.10, up_idx, lo_idx, "upper", "LONG", True))
    made.append(preview("07_descending_channel_BREAK", 100, -0.045, 62, -0.045, up_idx, lo_idx, "upper", "LONG", True))
    made.append(preview("08_ascending_channel_BREAK_short", 60, 0.05, 30, 0.05, up_idx, lo_idx, "lower", "SHORT", True))
    made.append(preview("09_majortrendline_BREAK", 100, -0.10, 55, -0.02, up_idx, (70, 112, 132), "upper", "LONG", True, lower_scatter=True))
    made.append(preview("10_descending_channel_NEAR", 100, -0.045, 62, -0.045, up_idx, lo_idx, "upper", "LONG", False))
    # 11: bounce trade — allowed only inside a PARALLEL (dynamic) channel
    made.append(preview("11_channel_floor_bounce_FADE", 100, -0.045, 72, -0.045, up_idx, lo_idx, "lower", "SHORT", False, fade=True))
    # 12: same rejection candle on a TRIANGLE: no bounce trade — warning only
    made.append(preview("12_triangle_rejection_NO_BOUNCE", 100, -0.08, 52, 0.10, up_idx, lo_idx, "upper", "LONG", False, fade=True))
    made.append(preview("13_head_shoulders_BREAK", 100, 0.0, 70, 0.0, up_idx, lo_idx, "upper", "LONG", True,
                        keys_override=[(0, 84.3), (45, 99.4), (52, 80.0), (70, 108.0), (88, 78.0),
                                       (105, 99.4), (118, 92.0), (132, 99.4), (139, 84.0)]))
    made.append(preview("14_triple_top_FADE", 100, 0.0, 68, 0.0, (45, 95, 125), (58, 112, 132), "upper", "LONG", False, fade=True,
                        keys_override=[(0, 84.3), (45, 99.4), (60, 68.6), (95, 99.4), (112, 68.6),
                                       (125, 99.4), (132, 68.6), (139, 84.0)]))
    made.append(preview("15_broadening_megaphone", 80, 0.12, 80, -0.10, up_idx, lo_idx, "upper", "LONG", False))
    made.append(preview("16_bull_flag_pennant", 100, 0.0, 95, 0.0, (45, 95, 125), (70, 112, 132), "upper", "LONG", True,
                        keys_override=[(0, 97.0), (35, 70.0), (45, 99.4), (70, 95.6), (95, 99.4),
                                       (112, 95.6), (125, 99.4), (139, 97.0)]))
    # contact sheet
    from PIL import Image, ImageDraw
    tiles = []
    TW, TH = 900, 510
    for path, label in made:
        im = Image.open(path).convert("RGB").resize((TW, TH), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, TW, 22], fill=(37, 39, 43))
        d.text((6, 4), label, fill=(255, 255, 255))
        tiles.append(im)
    cols, rows = 2, (len(tiles) + 1) // 2
    sheet = Image.new("RGB", (cols * TW, rows * TH), (248, 241, 231))
    for k, t in enumerate(tiles):
        sheet.paste(t, ((k % cols) * TW, (k // cols) * TH))
    sheet.save("/home/user/tc_previews/contact_sheet.png", optimize=True)
    print("contact sheet:", sheet.size)


if __name__ == "__main__":
    main()
