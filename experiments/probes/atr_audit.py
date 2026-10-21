"""ATR audit (Viva 10-02: «اندازه atr زياد نيست؟؟ اصلا چي ميشه اگر atr رو حذف
کنيم؟»).

Measures the REAL ATR(14) of every product timeframe on the sample tapes and
expresses each ATR-scaled threshold of the engine in % of price, so the
question «is ATR too big?» is answered with numbers:

    python experiments/probes/atr_audit.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _tape import load  # noqa: E402

SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "SUIUSDT")
TFS = ("15m", "30m", "1h", "2h", "4h", "1d")
# every ATR-scaled threshold that can decide a signal today
MULTS = (("eps 0.02", 0.02), ("brooks 0.10", 0.10), ("touch 0.20", 0.20),
         ("residual 0.45", 0.45), ("body 0.5", 0.5), ("pin near 1.2", 1.2),
         ("ext DT 1.5", 1.5), ("pin block 1.8", 1.8), ("ext SW 2.0", 2.0),
         ("edge far 8.0", 8.0), ("horizon 45", 45.0))


def atr14(d, k=14):
    return float((d["high"] - d["low"]).tail(k).mean())


def main():
    head = f"{'TF':>5s} {'ATR%':>6s} {'medHL%':>7s} | " + " ".join(
        f"{lbl:>12s}" for lbl, _ in MULTS)
    print(head)
    print("-" * len(head))
    rows = []
    for tf in TFS:
        a, m = [], []
        for s in SYMS:
            d = load(s, tf)
            if d is None or len(d) < 30:
                continue
            px = float(d["close"].iloc[-1])
            a.append(atr14(d) / px * 100.0)
            m.append(float((d["high"] - d["low"]).tail(60).median()) / px * 100.0)
        if not a:
            continue
        A, M = float(np.mean(a)), float(np.mean(m))
        rows.append((tf, A, M))
        print(f"{tf:>5s} {A:6.2f} {M:7.2f} | " + " ".join(
            f"{mu * A:11.2f}%" for _, mu in MULTS))
    print()
    print("reading: ATR% is the average true range as a percent of price on the")
    print("sample tapes; the last columns turn every multiplier of the engine")
    print("into the percent of price it actually demands.")


if __name__ == "__main__":
    main()
