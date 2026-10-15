"""TIERED SCAN (R99c) — shared scanner infra (VIVA_USER_LAWS.md §2).

Layers:
  * GUARD  — the existing fast lanes (candidate monitor 10s, line-watch,
             urgent confirms). UNTOUCHED by this pack — they already watch
             every chain every few seconds, so the deep pass can breathe.
  * DEEP   — discovery cadence (TIER_DEEP_MINUTES, default honors FULL_SCAN).
  * SPOT   — spot pass cadence (TIER_SPOT_DEEP_MINUTES, default 60).

The aggregation stair-step already lives in data.fetcher.get_market_bundle
(R64: venue fetches only 5m/15m/1h/4h/1d; everything else is derived).
AGG_MAP here is the single source of truth, and aggregate_frame() is the
pure, tested reference implementation (epoch-aligned buckets, COMPLETE
buckets only — a forming bar must never pretend to be closed).

Quality law (§13): at most VIVA_MAX_SIGNALS_PER_DAY new publishes/day
(counted per lane, capped on the TOTAL) and VIVA_MAX_CONCURRENT_POSITIONS
open chains. Confirms of already-alerted chains are NEVER gated — the cap
only trims NEW mints. Per-setup score floors land with each setup's own
completion (starting TECHCLASSIC).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

# derived TF -> (base TF, fold k). Verified against get_market_bundle (R99c).
AGG_MAP: Dict[str, Tuple[str, int]] = {
    "30m": ("15m", 2),
    "2h": ("1h", 2),
    "8h": ("4h", 2),
    "12h": ("4h", 3),
    "3d": ("1d", 3),
    "1w": ("1d", 7),
}
BASE_TFS = ("5m", "15m", "1h", "4h", "1d")
LANES = ("futures", "spot")


def aggregate_frame(df, k: int, base_seconds: int = 86400,
                    monday_shift: bool = False):
    """Fold k base candles into one higher-TF candle (pure; tested).

    Epoch-aligned buckets, complete buckets only. monday_shift=True moves
    weekly buckets to Mon→Sun (TradingView week, same as _aggregate_daily).
    base_seconds = one base candle in seconds (900 for 15m, 3600 for 1h…).
    """
    try:
        import pandas as pd  # local import: module stays light
        if df is None or getattr(df, "empty", True):
            return None
        k = int(k)
        _bs = int(base_seconds or 0)
        if k < 2 or _bs <= 0:
            return None
        d = df.reset_index(drop=True).copy()
        d["timestamp"] = pd.to_datetime(d["timestamp"])
        d = d.sort_values("timestamp")
        _ts = d["timestamp"]
        if getattr(_ts.dt, "tz", None) is not None:
            _ts = _ts.dt.tz_convert("UTC").dt.tz_localize(None)
        _epochs = (_ts.astype("int64") // 1_000_000_000)
        _shift = 3 * 86400 if (monday_shift and _bs == 86400) else 0
        d["_g"] = ((_epochs + _shift) // (_bs * k)).astype("int64")
        if d.empty or len(d) < k * 2:
            return None
        rows = []
        for _, g in d.groupby("_g"):
            if len(g) < k:
                continue
            rows.append({
                "timestamp": pd.Timestamp(g["timestamp"].iloc[0]),
                "open": float(g["open"].iloc[0]),
                "high": float(g["high"].max()),
                "low": float(g["low"].min()),
                "close": float(g["close"].iloc[-1]),
                "volume": float(g["volume"].sum()) if "volume" in g else 0.0,
            })
        if not rows:
            return None
        return pd.DataFrame(rows)
    except Exception:
        return None


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, "") or "").strip() or default)
    except Exception:
        return default


def deep_minutes() -> int:
    """Discovery cadence: TIER_DEEP_MINUTES or FULL_SCAN_MINUTES or 10."""
    if str(os.getenv("TIER_DEEP_MINUTES", "") or "").strip():
        return max(2, _int_env("TIER_DEEP_MINUTES", 10))
    return max(2, _int_env("FULL_SCAN_MINUTES", 10))


def guard_seconds() -> int:
    return max(15, _int_env("TIER_GUARD_SECONDS", 60))


def guard_enabled() -> bool:
    return str(os.getenv("TIER_GUARD_ENABLED", "1") or "1").strip().lower() in {
        "1", "true", "on", "yes"}


def spot_deep_minutes() -> int:
    if str(os.getenv("TIER_SPOT_DEEP_MINUTES", "") or "").strip():
        return max(15, _int_env("TIER_SPOT_DEEP_MINUTES", 60))
    return max(15, _int_env("SPOT_SCAN_MINUTES", 60))


def daily_cap() -> int:
    """Max NEW publishes/day TOTAL across lanes (quality law §13; 25)."""
    return max(1, _int_env("VIVA_MAX_SIGNALS_PER_DAY", 25))


def concurrent_cap() -> int:
    """Max concurrent open chains (quality law §13; default 3)."""
    return max(1, _int_env("VIVA_MAX_CONCURRENT_POSITIONS", 3))


def guard_band_pct() -> float:
    try:
        return max(0.1, float(os.getenv("TIER_GUARD_BAND_PCT", "1.0") or 1.0))
    except Exception:
        return 1.0


def _kv():
    from database import bot_kv as _bkv
    return _bkv


def _day_key(day: str, lane: str) -> str:
    return f"tier_day_count:{day}:{lane}"


def daily_count(day=None, lane: Optional[str] = None) -> int:
    """Published-signals counter: one lane, or TOTAL when lane is None."""
    try:
        _day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _lanes = (lane,) if lane else LANES
        return sum(max(0, int(_kv().get_json(_day_key(_day, _l), 0) or 0))
                   for _l in _lanes)
    except Exception:
        return 0


def daily_budget_ok(day=None) -> bool:
    """True while TOTAL is under the daily cap (fail-open: True)."""
    try:
        return daily_count(day) < daily_cap()
    except Exception:
        return True


def daily_count_incr(lane: str, day=None):
    """Increment one lane's counter after a successful publish (-1=skipped)."""
    try:
        if lane not in LANES:
            return -1
        _day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _n = max(0, int(_kv().get_json(_day_key(_day, lane), 0) or 0)) + 1
        _kv().set_json(_day_key(_day, lane), _n)
        return _n
    except Exception:
        return -1


def concurrent_ok(open_n: int) -> bool:
    try:
        return int(open_n or 0) < concurrent_cap()
    except Exception:
        return True


def spot_unchanged_skip(symbol: str, bundle,
                         tfs=("4h", "8h", "12h", "1d", "3d", "1w")) -> bool:
    """True when no spot TF closed a new candle since the last pass.

    Same idea as the discovery skip (Round-15): no new closed candle and
    the pass cannot see anything it did not already see. Stamp lives in
    durable kv (survives restarts). Fail-open: False (never skip on doubt).
    """
    try:
        _stamp = []
        for _tf in tfs:
            try:
                _df = bundle.get(_tf)
                _stamp.append(str(_df["timestamp"].iloc[-1])
                              if _df is not None and len(_df) else "-")
            except Exception:
                _stamp.append("?")
        _stamp = tuple(_stamp)
        _key = f"tier_spot_stamp:{str(symbol or '').upper()}"
        _prev = _kv().get_json(_key, None)
        _kv().set_json(_key, list(_stamp))
        return bool(_prev is not None and tuple(_prev) == _stamp
                    and "?" not in _stamp)
    except Exception:
        return False


def dist_to_entry_pct(side: str, entry, live) -> Optional[float]:
    """|live-entry|/entry in % (None when unusable)."""
    try:
        _e, _l = float(entry or 0), float(live or 0)
        if _e <= 0 or _l <= 0:
            return None
        return abs(_l - _e) / _e * 100.0
    except Exception:
        return None


def guard_should_fire(side: str, entry, live) -> bool:
    """True when a chain is inside the guard band (pure; tested)."""
    _d = dist_to_entry_pct(side, entry, live)
    return bool(_d is not None and _d <= guard_band_pct())
SETUP_SLOT_MODULES = {
    "PINVAL": "analysis.pinval",
    "ALBROX": "analysis.albrox",
    "TLBREAK": "analysis.tlbreak",
    "TECHCLASSIC": "analysis.techclassic",
    "SPOT": "analysis.spot",
}


def setup_cap(setup_code: str) -> int:
    """Concurrent-chain allowance OWNED by one setup (R99n).

    <SETUP>_MAX_CONCURRENT_CHAINS env wins; else the setup's own engine
    file (OWN_MAX_CONCURRENT_CHAINS); else 30. Fail-open: 30.
    """
    _code = str(setup_code or "").strip().upper()
    try:
        _env = (os.getenv(f"{_code}_MAX_CONCURRENT_CHAINS", "") or "").strip()
        if _env:
            return max(1, int(_env))
    except Exception:
        pass
    _mod = SETUP_SLOT_MODULES.get(_code)
    if _mod:
        try:
            import importlib as _il99n
            _v = getattr(_il99n.import_module(_mod),
                         "OWN_MAX_CONCURRENT_CHAINS", None)
            if _v is not None:
                return max(1, int(_v))
        except Exception:
            pass
    return 30


def count_open_by_setup(actives) -> dict:
    """Group open chains per setup (R99n). Fail-open: {}."""
    _out: dict = {}
    try:
        for _c in (actives or []):
            _k = str(getattr(_c, "setup_code", "") or "").strip().upper()
            if not _k:
                continue
            _out[_k] = int(_out.get(_k, 0) or 0) + 1
    except Exception:
        return {}
    return _out


def concurrent_ok_for_setup(setup_code, open_by_setup=None) -> bool:
    """True while THIS setup is under its own allowance (R99n)."""
    try:
        _code = str(setup_code or "").strip().upper()
        _n = int((open_by_setup or {}).get(_code, 0) or 0)
        return _n < setup_cap(_code)
    except Exception:
        return True
