"""Fetch a SMALL real-OHLCV sample into experiments/sample_klines/ (R31.7).

The development sandbox is geo-blocked from every exchange, but it can reach
github.com. The `sample-klines` workflow runs this inside GitHub Actions and
commits the gzip CSVs back to the branch, so charts and detectors can be
debugged locally on REAL candles:

    REPLAY_CACHE_DIR=experiments/sample_klines PYTHONPATH=. \
        python experiments/replay_live_setups.py --symbol BTCUSDT --days 20 --end 2026-09-24

File names follow experiments.replay_data.load's cache contract.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

os.environ.setdefault("REPLAY_CACHE_DIR", os.path.join(os.path.dirname(__file__), "sample_klines"))

from experiments.replay_data import load  # noqa: E402

WARM = {"5m": 4, "15m": 12, "4h": 40, "1d": 160}     # == replay_live_setups.real_base


def main() -> None:
    symbols = (sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT,ETHUSDT,SOLUSDT,SUIUSDT").split(",")
    days = int(os.getenv("SAMPLE_DAYS", "20"))
    end = date.fromisoformat(os.getenv("SAMPLE_END", "2026-09-24"))
    start = end - timedelta(days=days)
    for s in symbols:
        for tf, w in WARM.items():
            df = load(s.strip().upper(), tf, start - timedelta(days=w), end)
            print(s, tf, None if df is None else len(df))


if __name__ == "__main__":
    main()
