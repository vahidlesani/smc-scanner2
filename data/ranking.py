"""Global futures-liquidity ranking — deliberately a DIFFERENT venue from the
candle provider so a coin with real global volume is never dropped just
because the candle venue lists it thinly.

Primary: OKX USDT-margined SWAP 24h turnover (global top-3 venue).
Fallback: Bybit linear 24h turnover.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional

import requests

from config import get_settings

_RANK_CACHE_LOCK = threading.Lock()
_RANK_CACHE: List[str] = []
_RANK_METRICS: Dict[str, Dict] = {}
_RANK_FETCHED_AT = 0.0
_RANK_TTL = int(os.getenv("RANKING_CACHE_SECONDS", "900"))
_TIMEOUT = float(os.getenv("RANKING_TIMEOUT_SECONDS", "10"))
_SOURCE_PREF = os.getenv("RANKING_SOURCE", "okx").strip().lower()


def _okx_ranking() -> Optional[Dict[str, Dict]]:
    try:
        response = requests.get(
            "https://www.okx.com/api/v5/market/tickers",
            params={"instType": "SWAP"},
            timeout=_TIMEOUT,
            headers={"User-Agent": "viva-signal-bot/7.6"},
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None
    if str(payload.get("code")) != "0":
        return None
    rows: Dict[str, Dict] = {}
    for item in payload.get("data") or []:
        inst_id = str(item.get("instId", ""))
        if not inst_id.endswith("-USDT-SWAP"):
            continue
        base = inst_id.split("-")[0]
        symbol = f"{base}USDT"
        try:
            last = float(item.get("last") or 0)
            vol_ccy = float(item.get("volCcy24h") or 0)
        except (TypeError, ValueError):
            continue
        if last <= 0 or vol_ccy <= 0:
            continue
        rows[symbol] = {
            "global_turnover24h": last * vol_ccy,
            "source": "OKX",
        }
    return rows or None


def _bybit_ranking() -> Optional[Dict[str, Dict]]:
    try:
        from data.fetcher import get_tickers

        rows: Dict[str, Dict] = {}
        for ticker in get_tickers() or []:
            symbol = str(ticker.get("symbol", ""))
            if not symbol.endswith("USDT"):
                continue
            turnover = float(ticker.get("turnover24h") or 0)
            if turnover <= 0:
                continue
            rows[symbol] = {"global_turnover24h": turnover, "source": "BYBIT"}
        return rows or None
    except Exception:
        return None


def get_global_ranking(force: bool = False) -> Dict[str, Dict]:
    """{symbol: {global_turnover24h, source}} — refreshed every RANK_TTL."""
    global _RANK_CACHE, _RANK_METRICS, _RANK_FETCHED_AT
    with _RANK_CACHE_LOCK:
        fresh = _RANK_METRICS and (time.monotonic() - _RANK_FETCHED_AT < _RANK_TTL)
        if fresh and not force:
            return dict(_RANK_METRICS)
        rows = None
        if _SOURCE_PREF != "bybit":
            rows = _okx_ranking()
        if rows is None:
            rows = _bybit_ranking()
        if rows is None:
            return dict(_RANK_METRICS)
        _RANK_METRICS = rows
        _RANK_CACHE = sorted(rows, key=lambda s: rows[s]["global_turnover24h"], reverse=True)
        _RANK_FETCHED_AT = time.monotonic()
        return dict(_RANK_METRICS)


def get_ranked_symbols(force: bool = False) -> List[str]:
    with _RANK_CACHE_LOCK:
        fresh = _RANK_METRICS and (time.monotonic() - _RANK_FETCHED_AT < _RANK_TTL)
    if not fresh or force or not _RANK_CACHE:
        get_global_ranking(force=force)
    with _RANK_CACHE_LOCK:
        return list(_RANK_CACHE)
