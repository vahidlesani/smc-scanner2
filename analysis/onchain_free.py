"""Free on-chain / flow context — priority ONLY, never a gate.

Viva's ruling (09-22, standing): «سرویس پولی آنچین نه — فقط مسیرهای رایگان»
and «فقط اولویتدهی رصد، هرگز گیت». So this module can never confirm, reject,
delay or resize a signal. It exists to answer one question cheaply: *which*
symbols deserve to be looked at first when a scan is cut short by its budget.

Sources (all keyless, all reachable from Railway; the paid aggregators are not
used and the geo-blocked venues — Bybit/Binance taker flow — are not touched):

  • CoinGecko `/coins/markets`  → per-symbol 24h volume, market cap and 24h
    change: turnover (volume/mcap) is a serviceable participation proxy.
  • alternative.me `/fng`       → market-wide Fear & Greed (context line only).
  • DefiLlama `/overview/dexs`  → 24h DEX volume + its change: the tide the
    whole book swims in (context line only).

Everything is fail-open and cached: no key, no network, a 500, a timeout or a
schema change all degrade to «no context» — the scanner behaves exactly as
before. Nothing here is allowed to raise into a scan.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Dict, List, Optional, Sequence

COINGECKO = "https://api.coingecko.com/api/v3"
FNG = "https://api.alternative.me/fng/?limit=2&format=json"
LLAMA_DEX = "https://api.llama.fi/overview/dexs?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"

CACHE_TTL_S = float(os.getenv("ONCHAIN_CACHE_TTL_SECONDS", "1800") or 1800)
HTTP_TIMEOUT_S = float(os.getenv("ONCHAIN_HTTP_TIMEOUT_SECONDS", "6") or 6)
ENABLED = (os.getenv("ONCHAIN_FREE_ENABLED", "on") or "on").strip().lower() not in {
    "0", "off", "false", "no"}

# CoinGecko ids for the majors we can map without a search call; everything
# else resolves through /search once per process (cached).
_KNOWN_IDS = {
    "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana",
    "BNBUSDT": "binancecoin", "XRPUSDT": "ripple", "ADAUSDT": "cardano",
    "DOGEUSDT": "dogecoin", "AVAXUSDT": "avalanche-2", "LINKUSDT": "chainlink",
    "DOTUSDT": "polkadot", "MATICUSDT": "matic-network", "POLUSDT": "polygon-ecosystem-token",
    "TRXUSDT": "tron", "LTCUSDT": "litecoin", "TONUSDT": "the-open-network",
    "SUIUSDT": "sui", "APTUSDT": "aptos", "ARBUSDT": "arbitrum", "OPUSDT": "optimism",
    "INJUSDT": "injective-protocol", "SEIUSDT": "sei-network", "TIAUSDT": "celestia",
    "ATOMUSDT": "cosmos", "NEARUSDT": "near", "FILUSDT": "filecoin",
    "RENDERUSDT": "render-token", "TAOUSDT": "bittensor", "HBARUSDT": "hedera-hashgraph",
    "ENAUSDT": "ethena", "PENDLEUSDT": "pendle", "AAVEUSDT": "aave",
    "UNIUSDT": "uniswap", "CRVUSDT": "curve-dao-token", "LDOUSDT": "lido-dao",
}

_CACHE: Dict[str, tuple] = {}
_ID_CACHE: Dict[str, str] = {}


# ─────────────────────────────── plumbing ───────────────────────────────
def _get_json(url: str, timeout: float = HTTP_TIMEOUT_S):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "viva-mon/1.0",
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _cached(key: str, loader, ttl: float = CACHE_TTL_S):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        value = loader()
    except Exception:
        # fail-open: a provider that explodes must never reach a caller —
        # the scanner keeps yesterday's answer, or none at all.
        value = None
    if value is not None:
        _CACHE[key] = (now, value)
        return value
    return hit[1] if hit else None


def _base_asset(symbol: str) -> str:
    raw = str(symbol or "").upper().strip()
    for quote in ("USDT", "USDC", "USD", "PERP"):
        if raw.endswith(quote) and len(raw) > len(quote):
            return raw[: -len(quote)]
    return raw


def _resolve_id(symbol: str) -> Optional[str]:
    """CoinGecko id for a venue symbol (cached; one /search per unknown)."""
    sym = str(symbol or "").upper().strip()
    if sym in _KNOWN_IDS:
        return _KNOWN_IDS[sym]
    base = _base_asset(sym)
    if base in _ID_CACHE:
        return _ID_CACHE[base] or None
    data = _cached(f"search|{base}",
                   lambda: _get_json(f"{COINGECKO}/search?query={base}"), ttl=86400.0)
    coin_id = ""
    try:
        for row in (data or {}).get("coins") or []:
            if str(row.get("symbol") or "").upper() == base:
                coin_id = str(row.get("id") or "")
                break
    except Exception:
        coin_id = ""
    _ID_CACHE[base] = coin_id
    return coin_id or None


# ─────────────────────────────── context ───────────────────────────────
def fear_greed() -> Dict:
    data = _cached("fng", lambda: _get_json(FNG))
    try:
        row = (data or {}).get("data") or []
        if not row:
            return {}
        latest = row[0]
        prev = row[1] if len(row) > 1 else {}
        return {"value": int(latest.get("value")),
                "label": str(latest.get("value_classification") or ""),
                "prev": int(prev.get("value")) if prev.get("value") else None}
    except Exception:
        return {}


def dex_tide() -> Dict:
    """24h DEX volume + change — the market-wide risk appetite line."""
    data = _cached("dex_tide", lambda: _get_json(LLAMA_DEX))
    try:
        if not isinstance(data, dict):
            return {}
        total = data.get("total24h")
        change = data.get("change_1d")
        if total is None and change is None:
            return {}
        return {"volume_24h": float(total) if total else None,
                "change_1d_pct": float(change) if change is not None else None}
    except Exception:
        return {}


def market_snapshot() -> Dict:
    """Everything market-wide, in one fail-open dict (may be empty)."""
    if not ENABLED:
        return {}
    snap = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    fng = fear_greed()
    if fng:
        snap["fear_greed"] = fng
    tide = dex_tide()
    if tide:
        snap["dex"] = tide
    return snap


def symbol_stats(symbols: Sequence[str], max_calls: int = 25) -> Dict[str, Dict]:
    """Per-symbol 24h turnover for the first `max_calls` resolvable symbols."""
    out: Dict[str, Dict] = {}
    if not ENABLED:
        return out
    wanted, ids = [], []
    for sym in list(symbols)[: max(1, int(max_calls))]:
        coin_id = _resolve_id(sym)
        if not coin_id:
            continue
        wanted.append((str(sym).upper(), coin_id))
        ids.append(coin_id)
    if not ids:
        return out
    key = "markets|" + ",".join(sorted(ids))
    data = _cached(key, lambda: _get_json(
        f"{COINGECKO}/coins/markets?vs_currency=usd&ids={','.join(ids)}"
        "&price_change_percentage=24h"), ttl=600.0)
    by_id = {}
    for row in data or []:
        try:
            by_id[str(row.get("id"))] = row
        except Exception:
            continue
    for sym, coin_id in wanted:
        row = by_id.get(coin_id)
        if not row:
            continue
        try:
            vol = float(row.get("total_volume") or 0.0)
            cap = float(row.get("market_cap") or 0.0)
            chg = row.get("price_change_percentage_24h")
            out[sym] = {"turnover": (vol / cap) if cap > 0 else 0.0,
                        "volume_24h": vol, "market_cap": cap,
                        "change_24h_pct": float(chg) if chg is not None else None}
        except Exception:
            continue
    return out


def priority_bump(symbol: str, stats: Optional[Dict] = None) -> float:
    """0…2 bonus used ONLY to order a scan queue. Never a gate, never a veto.

    Turnover (24h volume ÷ market cap) says how actively the book is trading
    the name right now; a hot tape gets looked at first when a scan is cut
    short. Unknown symbol, missing data or a dead API → 0.0 (neutral).
    """
    if not ENABLED:
        return 0.0
    try:
        row = (stats or {}).get(str(symbol).upper()) or {}
        turnover = float(row.get("turnover") or 0.0)
        if turnover <= 0:
            return 0.0
        # 0.02 (sleepy) → 0.0 · 0.10 → 1.0 · 0.30+ (hot) → 2.0
        return float(max(0.0, min(2.0, (turnover - 0.02) / 0.14 * 1.0)))
    except Exception:
        return 0.0


def order_symbols(symbols: Sequence[str], pinned: Sequence[str] = (),
                  head: int = 20, stats: Optional[Dict] = None) -> List[str]:
    """Priority order for a scan list.

    Viva's law stays intact: `pinned` symbols (open alerts) keep their exact
    order at the FRONT, and the first `head` symbols of the original list stay
    put too — a queue that reshuffles its top can starve a name for days. Only
    the remainder is re-ordered by flow participation (stable, cached).
    """
    try:
        syms = [str(s) for s in symbols]
        pin = [str(s) for s in pinned if str(s) in syms]
        rest = [s for s in syms if s not in pin]
        keep, tail = rest[: max(0, int(head))], rest[max(0, int(head)):]
        if len(tail) < 2:
            return pin + rest
        data = stats if stats is not None else symbol_stats(tail, max_calls=min(25, len(tail)))
        ranked = sorted(tail, key=lambda s: (-priority_bump(s, data), tail.index(s)))
        return pin + keep + ranked
    except Exception:
        return [str(s) for s in symbols]


def context_line_fa() -> str:
    """One Persian line for logs / the app (empty when nothing is known)."""
    snap = market_snapshot()
    if not snap:
        return ""
    bits = []
    fng = snap.get("fear_greed") or {}
    if fng.get("value"):
        bits.append(f"شاخص ترس/طمع {fng['value']}")
    dex = snap.get("dex") or {}
    if dex.get("change_1d_pct") is not None:
        bits.append(f"حجم DEX ۲۴ساعته {dex['change_1d_pct']:+.1f}٪")
    return " · ".join(bits)
