"""R64.4 LINE-WATCH — instant touch/break alerts at ticker cost (Viva 10-03).

His law, verbatim: «هم مصرف ریلوی پایین بمونه هم در لحظه شکست‌ها یا برخوردها
هشدار بده — وگرنه ممکنه شکست یا برخورد یک کندل روزانه/۳روزه/هفتگی رو روز بعد/
۳روز بعد/یک هفته بعد متوجه بشیم».

Design
------
The pinned spot chains (ladder TOUCH / NEAR_BREAK / BREAK_DOWN) register their
structural edge ONCE (main.py pin writer). A monitor-cycle task then evaluates
those edges against the TICKER price — ONE public-ticker request per market
covers EVERY symbol — so a 1d/3d/1w edge break is spoken within seconds of the
cross, not at the next candle close, and the candle klines are still fetched
only on their closed-candle TTL. This lane is an ANALYTIC heads-up (reply
text, no chart, never a signal): the confirm laws stay untouched.

Fail-open everywhere: any KV/network problem only skips a cycle.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

_KV_KEY = "line_watch"
_TTL_SEC = 14 * 24 * 3600.0        # a watched edge dies with its chain window
_MIN_INTERVAL = 30.0               # ticker cadence — one request per market
_TOUCH_TOL = 0.0025                # «برخورد» = within 0.25% of the edge
_DEDUP_SEC = 6 * 3600.0            # one alert per kind per 6h
_LAST_RUN = {"ts": 0.0}


def upsert(symbol: str, tf: str, level: float, side: str = "HIGH",
           stage: str = "", market: str = "SPOT") -> None:
    """Register/refresh one watched edge (reads+writes its own KV entry)."""
    if not symbol or not tf or not level or level <= 0:
        return
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        import time as _t
        state = _g(_KV_KEY, {}) or {}
        key = f"{str(symbol).upper()}|{str(tf).lower()}|{str(side).upper()}"
        prev = state.get(key) or {}
        state[key] = {
            "symbol": str(symbol).upper(), "tf": str(tf).lower(),
            "market": str(market or "SPOT").upper(),
            "level": float(level), "side": str(side or "HIGH").upper(),
            "stage": str(stage or ""), "ts": _t.time(),
            "last_state": str(prev.get("last_state") or ""),
            "last_alert_ts": float(prev.get("last_alert_ts") or 0.0),
            "last_alert_kind": str(prev.get("last_alert_kind") or ""),
        }
        # keep the registry small: drop stale siblings while writing
        state = {k: v for k, v in state.items()
                 if _t.time() - float((v or {}).get("ts", 0)) < _TTL_SEC}
        _s(_KV_KEY, state)
    except Exception as exc:
        print(f"line watch upsert warning: {exc}")


def drop(symbol: str, tf: str, side: str = "") -> None:
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        import time as _t
        state = _g(_KV_KEY, {}) or {}
        prefix = f"{str(symbol).upper()}|{str(tf).lower()}|{str(side).upper()}"
        state = {k: v for k, v in state.items()
                 if not k.startswith(prefix.rstrip("|"))
                 or _t.time() - float((v or {}).get("ts", 0)) >= _TTL_SEC}
        _s(_KV_KEY, state)
    except Exception:
        pass


def _evaluate(entry: Dict, price: float, now: float) -> Tuple[str, Optional[Dict]]:
    """Pure state machine: (new_state, event|None).

    States: "" (unknown) → "above"/"below"/"near". An event fires ONLY on a
    real transition (a cross of the edge, or the first NEAR landing), and the
    same kind never repeats inside its dedup window.
    """
    level = float(entry.get("level") or 0.0)
    if level <= 0 or price <= 0:
        return str(entry.get("last_state") or ""), None
    prev = str(entry.get("last_state") or "")
    dist = (price - level) / level
    last_alert_ts = float(entry.get("last_alert_ts") or 0.0)
    last_kind = str(entry.get("last_alert_kind") or "")

    def _fire(kind: str, fa: str) -> Tuple[str, Dict]:
        entry["last_state"] = "near" if kind == "TOUCH" else (
            "above" if dist > 0 else "below")
        entry["last_alert_ts"] = now
        entry["last_alert_kind"] = kind
        return entry["last_state"], {"kind": kind, "fa": fa}

    if abs(dist) <= _TOUCH_TOL:
        if prev == "near":
            return "near", None
        if last_kind == "TOUCH" and now - last_alert_ts < _DEDUP_SEC:
            entry["last_state"] = "near"
            return "near", None
        return _fire("TOUCH", "برخورد لحظه‌ای به ضلع ساختاری")
    state = "above" if dist > 0 else "below"
    if prev in ("", state):
        entry["last_state"] = state
        return state, None
    # a real cross: the price was on the other side last tick
    if prev == "near":
        # from NEAR into beyond — speak the break in the direction moved
        kind = "BREAK_UP" if state == "above" else "BREAK_DOWN"
    else:
        kind = "BREAK_UP" if state == "above" else "BREAK_DOWN"
    if last_kind == kind and now - last_alert_ts < _DEDUP_SEC:
        entry["last_state"] = state
        return state, None
    fa = ("عبور لحظه‌ای به بالای ضلع ساختاری (شکست رو به بالا)"
          if kind == "BREAK_UP" else
          "عبور لحظه‌ای به زیر ضلع ساختاری (شکست رو به پایین)")
    return _fire(kind, fa)


def _ticker_prices(market: str) -> Dict[str, float]:
    from data.fetcher import get_tickers
    out: Dict[str, float] = {}
    for row in get_tickers(category=str(market or "SPOT").upper()) or []:
        sym = str(row.get("symbol") or "").upper()
        try:
            out[sym] = float(row.get("lastPrice") or 0.0)
        except Exception:
            continue
    return out


def run_once(force: bool = False) -> int:
    """Evaluate every watched edge against the live ticker. Returns alerts sent."""
    import time as _t
    now = _t.time()
    if not force and now - float(_LAST_RUN.get("ts") or 0.0) < _MIN_INTERVAL:
        return 0
    _LAST_RUN["ts"] = now
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        state = _g(_KV_KEY, {}) or {}
    except Exception:
        return 0
    state = {k: v for k, v in state.items()
             if now - float((v or {}).get("ts", 0)) < _TTL_SEC}
    if not state:
        return 0
    prices: Dict[str, Dict[str, float]] = {}
    changed = False
    sent = 0
    for key, entry in sorted(state.items()):
        market = str((entry or {}).get("market") or "SPOT").upper()
        if market not in prices:
            try:
                prices[market] = _ticker_prices(market)
            except Exception as exc:
                print(f"line watch tickers warning ({market}): {exc}")
                prices[market] = {}
        price = float((prices.get(market) or {}).get(str(entry.get("symbol") or "").upper()) or 0.0)
        if price <= 0:
            continue
        try:
            new_state, event = _evaluate(dict(entry), price, now)
        except Exception:
            continue
        if new_state != str(entry.get("last_state") or ""):
            entry["last_state"] = new_state
            changed = True
        if not event:
            continue
        changed = True
        sent += 1
        print(f"LINE_WATCH | {entry.get('symbol')} | {entry.get('tf')} | "
              f"{event['kind']} | px={price:.6g} lvl={float(entry['level']):.6g}")
        try:
            from bot.messages_v7 import send_line_watch_alert
            send_line_watch_alert(entry, event, price)
        except Exception as exc:
            print(f"line watch send warning: {exc}")
    if changed:
        try:
            _s(_KV_KEY, state)
        except Exception:
            pass
    return sent
