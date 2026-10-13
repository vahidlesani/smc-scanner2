"""Pixel-level gridline audit for rendered sheets (Viva 10-13 law #1).

Flags rows/cols whose deviation from a smooth neighbourhood spans >=85% of
the candle pane — i.e. real gridlines. Design elements (box borders, target
arrow, pane separators, tool dashes) are reported separately by position so
they are never mistaken for gridlines.

Usage: python tools/gridline_audit.py <png> [<png> ...]
"""
import sys

import numpy as np
from PIL import Image


def audit(path: str, y_top: float = 0.14, y_bot: float = 0.86,
          x_lo: float = 0.09, x_hi: float = 0.90, thr: float = 8.0,
          span: float = 0.85):
    im = np.asarray(Image.open(path).convert("L"), dtype=float)
    h, w = im.shape
    panel = im[int(h * y_top):int(h * y_bot), int(w * x_lo):int(w * x_hi)]
    ph, pw = panel.shape
    hits = {"h": [], "v": []}
    for y in range(3, ph - 3):
        dev = np.abs(panel[y] - (panel[y - 3] + panel[y + 3]) / 2) > thr
        if dev.mean() >= span:
            hits["h"].append(y)
    for x in range(3, pw - 3):
        dev = np.abs(panel[:, x] - (panel[:, x - 3] + panel[:, x + 3]) / 2) > thr
        if dev.mean() >= span:
            hits["v"].append(x)
    return hits


def main() -> None:
    for f in sys.argv[1:]:
        r = audit(f)
        print(f"{f}: h={len(r['h'])} v={len(r['v'])} {r if (r['h'] or r['v']) else ''}")


if __name__ == "__main__":
    main()
