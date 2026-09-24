"""Free, low-cost market-intelligence layer for Viva.

This module is deliberately additive: it never creates, deletes, flips, or scores a
setup. It reads public exchange data and stores a compact evidence packet in
candidate.metadata["market_intelligence"]. Telegram templates can render that
packet without changing IDs, separators, fonts, headings, or setup geometry.

Primary free source: Bybit public V5 market endpoints.
Optional external providers are intentionally not required; premium/limited
services such as Glassnode/CoinGlass can be added later behind adapters.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

import requests

_BASE_URLS = [
    x.strip().rstrip("/")
    for x in os.getenv(
        "BYBIT_BASE_URLS", "https://api.bybit.com,https://api.bytick.com"
    ).split(",")
    if x.strip()
]
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "viva-signal-bot/market-intel"})
_CACHE: Dict[tuple, tuple[float, Any]] = {}
_LOCK = threading.Lock()


def _cache_get(key: tuple) -> Any:
    with _LOCK:
        item = _CACHE.get(key)
        if not item or item[0] <= time.monotonic():
            _CACHE.pop(key, None)
            return None
        return item[1]


def _cache_set(key: tuple, value: Any, ttl: int) -> None:
    with _LOCK:
        _CACHE[key] = (time.monotonic() + ttl, value)
        if len(_CACHE) > 120:
            oldest = sorted(_CACHE, key=lambda k: _CACHE[k][0])[:20]
            for k in oldest:
                _CACHE.pop(k, None)


def _get(path: str, params: Dict[str, Any], ttl: int = 30) -> Optional[Dict[str, Any]]:
    key = (path, tuple(sorted((str(k), str(v)) for k, v in params.items())))
    cached = _cache_get(key)
    if cached is not None:
        return cached
    for base in _BASE_URLS:
        try:
            r = _SESSION.get(f"{base}{path}", params=params, timeout=8)
            if r.status_code in (403, 451):
                continue
            r.raise_for_status()
            payload = r.json()
            if int(payload.get("retCode", -1)) == 0:
                _cache_set(key, payload, ttl)
                return payload
        except Exception:
            continue
    return None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _depth_snapshot(symbol: str) -> Dict[str, Any]:
    payload = _get(
        "/v5/market/orderbook",
        {"category": "linear", "symbol": symbol.upper(), "limit": 50},
        ttl=15,
    )
    rows = ((payload or {}).get("result") or {})
    bids = [(_num(p), _num(q)) for p, q in (rows.get("b") or []) if _num(p) > 0 and _num(q) > 0]
    asks = [(_num(p), _num(q)) for p, q in (rows.get("a") or []) if _num(p) > 0 and _num(q) > 0]
    if not bids or not asks:
        return {"status": "UNAVAILABLE"}

    mid = (bids[0][0] + asks[0][0]) / 2.0
    if mid <= 0:
        return {"status": "UNAVAILABLE"}

    def band(rows_, side_: str, pct: float) -> float:
        lo, hi = mid * (1.0 - pct), mid * (1.0 + pct)
        total = 0.0
        for price, qty in rows_:
            if lo <= price <= hi:
                total += price * qty
        return total

    bid05, ask05 = band(bids, "bid", 0.005), band(asks, "ask", 0.005)
    bid1, ask1 = band(bids, "bid", 0.010), band(asks, "ask", 0.010)
    denom = bid1 + ask1
    imbalance = (bid1 - ask1) / denom if denom else 0.0

    nearest_bid = max(bids, key=lambda x: x[0] * x[1])
    nearest_ask = max(asks, key=lambda x: x[0] * x[1])
    bid_dist = abs(mid - nearest_bid[0]) / mid * 100.0
    ask_dist = abs(nearest_ask[0] - mid) / mid * 100.0

    return {
        "status": "OK",
        "mid": round(mid, 12),
        "spread_pct": round((asks[0][0] - bids[0][0]) / mid * 100.0, 5),
        "bid_depth_0_5_pct_usd": round(bid05, 2),
        "ask_depth_0_5_pct_usd": round(ask05, 2),
        "bid_depth_1_pct_usd": round(bid1, 2),
        "ask_depth_1_pct_usd": round(ask1, 2),
        "imbalance_1_pct": round(imbalance, 4),
        "nearest_bid_wall_pct": round(bid_dist, 4),
        "nearest_ask_wall_pct": round(ask_dist, 4),
    }


def _oi_and_funding(symbol: str) -> Dict[str, Any]:
    oi = _get(
        "/v5/market/open-interest",
        {"category": "linear", "symbol": symbol.upper(), "intervalTime": "5min", "limit": 24},
        ttl=45,
    )
    items = ((oi or {}).get("result") or {}).get("list") or []
    values = []
    for row in reversed(items):
        value = _num(row.get("openInterestValue") or row.get("singleOpenInterestValue"))
        if value <= 0:
            value = _num(row.get("openInterest"))
        if value > 0:
            values.append(value)
    oi_now = values[-1] if values else 0.0
    oi_change_pct = ((values[-1] / values[0]) - 1.0) * 100.0 if len(values) >= 2 and values[0] else 0.0

    funding = _get(
        "/v5/market/funding/history",
        {"category": "linear", "symbol": symbol.upper(), "limit": 8},
        ttl=60,
    )
    fr_items = ((funding or {}).get("result") or {}).get("list") or []
    rates = [_num(x.get("fundingRate")) for x in reversed(fr_items)]
    current_fr = rates[-1] if rates else 0.0
    return {
        "oi_usd": round(oi_now, 2),
        "oi_change_2h_pct": round(oi_change_pct, 3),
        "funding_rate": round(current_fr, 6),
        "funding_history": [round(x, 6) for x in rates[-6:]],
    }


def _positioning(symbol: str) -> Dict[str, Any]:
    payload = _get(
        "/v5/market/account-ratio",
        {"category": "linear", "symbol": symbol.upper(), "period": "5min", "limit": 12},
        ttl=60,
    )
    rows = ((payload or {}).get("result") or {}).get("list") or []
    if not rows:
        return {"status": "UNAVAILABLE"}
    row = rows[0]
    buy = _num(row.get("buyRatio"))
    sell = _num(row.get("sellRatio"))
    return {
        "status": "OK",
        "long_ratio": round(buy, 4),
        "short_ratio": round(sell, 4),
        "long_short_delta": round(buy - sell, 4),
    }


def build_market_intelligence(bundle) -> Dict[str, Any]:
    """Build one compact, cached evidence packet per symbol/scan cycle."""
    symbol = str(getattr(bundle, "symbol", "") or "").upper()
    if not symbol:
        return {"status": "UNAVAILABLE", "version": "MI-1"}

    key = ("bundle", symbol)
    cached = _cache_get(key)
    if cached is not None:
        return dict(cached)

    ticker = dict(getattr(bundle, "ticker", {}) or {})
    depth = _depth_snapshot(symbol)
    oi = _oi_and_funding(symbol)
    positioning = _positioning(symbol)

    volume_24h = _num(ticker.get("turnover24h") or ticker.get("volume24h"))
    result = {
        "status": "OK",
        "version": "MI-1",
        "source": "Bybit public market data",
        "volume_24h_usd": round(volume_24h, 2),
        "orderbook": depth,
        "derivatives": oi,
        "positioning": positioning,
        "onchain": {
            "status": "NOT_CONNECTED",
            "note": "No paid on-chain dependency is required by the baseline engine.",
        },
    }
    _cache_set(key, result, 20)
    return result


def intelligence_note(candidate) -> list[str]:
    """Two-to-four short Persian lines suitable for the existing final alert."""
    md = getattr(candidate, "metadata", None) or {}
    mi = md.get("market_intelligence") or {}
    if mi.get("status") != "OK":
        return ["دادهٔ حجم/دفتر سفارشات در این لحظه در دسترس کامل نیست؛ این بخش روی تصمیم ستاپ اثری ندارد."]

    lines = []
    ob = mi.get("orderbook") or {}
    deriv = mi.get("derivatives") or {}
    pos = mi.get("positioning") or {}

    imb = _num(ob.get("imbalance_1_pct"))
    if imb >= 0.18:
        lines.append("دفتر سفارشات در محدودهٔ نزدیک قیمت، برتری محسوس نقدینگی خرید را نشان می‌دهد.")
    elif imb <= -0.18:
        lines.append("دفتر سفارشات در محدودهٔ نزدیک قیمت، برتری محسوس نقدینگی فروش را نشان می‌دهد.")
    else:
        lines.append("دفتر سفارشات نزدیک قیمت فعلاً متعادل است و برتری واضح یک سمت دیده نمی‌شود.")

    oi_chg = _num(deriv.get("oi_change_2h_pct"))
    fr = _num(deriv.get("funding_rate"))
    if abs(oi_chg) >= 1.0:
        direction = "افزایش" if oi_chg > 0 else "کاهش"
        lines.append(f"حجم قراردادهای باز در حدود دو ساعت اخیر {direction} داشته است؛ این داده برای تشخیص ورود/خروج اهرم کمکی است.")
    if abs(fr) >= 0.0005:
        side = "مثبت" if fr > 0 else "منفی"
        lines.append(f"فاندینگ فعلی {side} است؛ ازدحام یک‌طرفه می‌تواند احتمال نوسان خلاف‌جهت را بالا ببرد.")

    if pos.get("status") == "OK":
        delta = _num(pos.get("long_short_delta"))
        if abs(delta) >= 0.10:
            side = "لانگ" if delta > 0 else "شورت"
            lines.append(f"نسبت حساب‌های خرید/فروش به سمت {side} متمایل است؛ این فقط تأیید کمکی است، نه سیگنال مستقل.")

    lines.append("این داده‌ها فقط لایهٔ کمکی‌اند و پایهٔ ستاپ، خطوط، شناسه و قالب پیام را تغییر نمی‌دهند.")
    return lines[:4]
