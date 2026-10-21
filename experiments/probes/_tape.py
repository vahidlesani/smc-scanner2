"""Shared tape loader for the R65 probes (survives restarts because it lives
INSIDE the repo — the old /home/user/probe_*.py helpers were lost with the
sandbox re-provision on 2026-10-02).

`load(symbol, tf)` reads the gz fixtures in `experiments/sample_klines`;
frames the fixtures do not ship (30m/1h/2h/8h/12h/3d/1w) are RESAMPLED from the
15m/4h/1d bases with the same rules the product's aggregator uses, so a probe
sees the same candles the live scanner would.
"""
from __future__ import annotations

import glob
import gzip
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINES = os.path.join(ROOT, "experiments", "sample_klines")

_RULE = {"30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h", "8h": "8h",
         "12h": "12h", "1d": "1D", "3d": "3D", "1w": "1W"}


def load(symbol: str, tf: str) -> pd.DataFrame | None:
    """Native fixture for (symbol, tf), else the closest base resampled."""
    pat = os.path.join(KLINES, f"{symbol.upper()}_{tf}_*.csv.gz")
    hits = sorted(glob.glob(pat))
    if hits:
        d = pd.read_csv(gzip.open(hits[-1]))
        d["timestamp"] = pd.to_datetime(d["timestamp"])
        return d.reset_index(drop=True)
    for base_tf in ("15m", "4h", "1d", "5m"):
        if base_tf == tf:
            continue
        hits = sorted(glob.glob(os.path.join(KLINES,
                                             f"{symbol.upper()}_{base_tf}_*.csv.gz")))
        if not hits:
            continue
        base = pd.read_csv(gzip.open(hits[-1]))
        base["timestamp"] = pd.to_datetime(base["timestamp"])
        out = resample(base, tf)
        if out is not None and len(out) >= 30:
            return out
    return None


def resample(d: pd.DataFrame, tf: str) -> pd.DataFrame | None:
    rule = _RULE.get(str(tf).lower())
    if rule is None or d is None or d.empty:
        return None
    x = d.copy()
    if "timestamp" in x.columns:
        x = x.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    for c in ("volume", "turnover"):
        if c in x.columns:
            agg[c] = "sum"
    o = x.resample(rule, label="left", closed="left").agg(agg).dropna()
    return o.reset_index()
