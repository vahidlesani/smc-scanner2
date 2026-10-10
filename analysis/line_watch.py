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

import os
from typing import Dict, Optional, Tuple

_KV_KEY = "line_watch"
_TTL_SEC = 14 * 24 * 3600.0        # a watched edge dies with its chain window
_MIN_INTERVAL = 30.0               # ticker cadence — one request per market
_TOUCH_TOL = 0.0025                # «برخورد» = within 0.25% of the edge
_DEDUP_SEC = 6 * 3600.0            # one alert per kind per 6h
_LAST_RUN = {"ts": 0.0}


def _lw_edge_slot(edge: dict, slot: str, now: float):
    """10-12 journey (edge side, kindless): may this edge claim slot s1/s2?
    Pending claims older than 10 min are stale. Pure (unit-tested)."""
    try:
        if slot == "s1":
            if float((edge or {}).get("j1") or 0.0):
                return None
            if float((edge or {}).get("j1p") or 0.0) and now - float(edge.get("j1p")) <= 600.0:
                return None
            return "s1"
        if slot == "s2":
            if float((edge or {}).get("j2") or 0.0):
                return None
            if float((edge or {}).get("j2p") or 0.0) and now - float(edge.get("j2p")) <= 600.0:
                return None
            return "s2"
        return None
    except Exception:
        return None


def _lw_touch_item(entry: dict, price: float, pattern: str, shape) -> dict:
    """10-12 journey: the ticker's warning as a ladder-grade item so it rides
    the SAME chain/numbering/replace machinery."""
    try:
        lvl = float((entry or {}).get("level") or 0.0)
        px = float(price or 0.0)
    except Exception:
        lvl, px = 0.0, 0.0
    dist = abs(px - lvl) / lvl * 100.0 if lvl > 0 else 0.0
    fa, rule = "", ""
    try:
        from analysis.patterns import pattern_info as _pi73
        _info73 = _pi73(str(pattern or "")) or {}
        fa = str(_info73.get("fa") or "")
        rule = str(_info73.get("rule_fa") or "")
    except Exception:
        pass
    import time as _t73
    return {
        "symbol": str((entry or {}).get("symbol") or "").upper(),
        "tf": str((entry or {}).get("tf") or ""),
        "stage": "TOUCH", "side": str((entry or {}).get("side") or "HIGH"),
        "pattern": str(pattern or ""), "pattern_fa": fa, "rule_fa": rule,
        "distance_pct": dist, "vol_ratio": 0.0,
        "close": px, "edge": lvl,
        "pattern_commands": [shape] if shape else [],
        "detected_at": _t73.strftime("%Y-%m-%dT%H:%M:%S", _t73.gmtime()),
        "_journey_slot": "s1",
    }


def upsert(symbol: str, tf: str, level: float, side: str = "HIGH",
           stage: str = "", market: str = "SPOT", pattern: str = "") -> None:
    """Register/refresh one watched edge (reads+writes its own KV entry)."""
    if not symbol or not tf or not level or level <= 0:
        return
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        import time as _t
        state = _g(_KV_KEY, {}) or {}
        key = f"{str(symbol).upper()}|{str(tf).lower()}|{str(side).upper()}"
        prev = state.get(key) or {}
        _pl73 = float(prev.get("level") or 0.0)
        _reset73 = (_pl73 > 0 and abs(float(level) - _pl73) / _pl73 > 0.005)
        state[key] = {
            "symbol": str(symbol).upper(), "tf": str(tf).lower(),
            "market": str(market or "SPOT").upper(),
            "level": float(level), "side": str(side or "HIGH").upper(),
            "stage": str(stage or ""), "ts": _t.time(),
            "pattern": str(pattern or prev.get("pattern") or ""),
            "last_state": str(prev.get("last_state") or ""),
            "last_alert_ts": float(prev.get("last_alert_ts") or 0.0),
            "last_alert_kind": str(prev.get("last_alert_kind") or ""),
            "j1": 0.0 if _reset73 else float(prev.get("j1") or 0.0),
            "j1p": 0.0 if _reset73 else float(prev.get("j1p") or 0.0),
            "j2": 0.0 if _reset73 else float(prev.get("j2") or 0.0),
            "j2p": 0.0 if _reset73 else float(prev.get("j2p") or 0.0),
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
    # 10-12: the ticker IS the spot lane's real-time — it respects the spot
    # flag (no ghost-edge flood while spot is off).
    if str(os.getenv("SPOT_ENGINE_ENABLED", "1")).strip().lower() not in {"1", "true", "on", "yes"}:
        return 0
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
    _sent73 = 0
    _muted73 = 0
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
        # ── 10-12 journey: the ticker is detection-hot but notification-
        # capped — s1 (first touch, WITH CHART, instant) + s2 (break heads-up
        # text, upgraded to chart by the closed candle). Pins/recheck/confirm
        # laws are untouched; only the 2000/day flood dies here.
        try:
            _kind73 = str(event.get("kind") or "")
            _patt73 = str(entry.get("pattern") or "")
            if not _patt73:
                try:
                    from database.bot_kv import get_json as _g73p
                    _pins73 = _g73p("spot_urgent_watch", {}) or {}
                    _pk73 = f"{str(entry.get('symbol') or '').upper()}|{str(entry.get('tf') or '')}"
                    _pin73 = _pins73.get(_pk73) or _pins73.get(_pk73.upper()) or {}
                    _patt73 = str((_pin73.get("shape") or {}).get("type") or "")
                except Exception:
                    _patt73 = ""
            from bot.messages_v7 import _spot_ladder_chain_key as _ck73
            from analysis.spot_engine import _spot_journey_slot as _js73
            from database.bot_kv import get_json as _g73j, set_json as _s73j
            _ckey73 = _ck73(str(entry.get("symbol") or ""), str(entry.get("tf") or ""), _patt73 or "EDGE")
            _jm73 = _g73j(_ckey73, {}) or {}
            _slot73 = None
            if _kind73 == "TOUCH":
                if _js73(_jm73, "s1", now) == "s1" and _lw_edge_slot(entry, "s1", now) == "s1":
                    _slot73 = "s1"
            elif _kind73 in ("BREAK_UP", "BREAK_DOWN"):
                if not int(_jm73.get("s1") or 0) and not float(_jm73.get("s1p") or 0.0):
                    _slot73 = None   # break-before-warn: the ladder owns it
                elif _js73(_jm73, "s2", now) == "s2" and _lw_edge_slot(entry, "s2", now) == "s2":
                    _slot73 = "s2"
            if _slot73 is None:
                _muted73 += 1
            elif _slot73 == "s1":
                _jm73["s1p"] = now
                _s73j(_ckey73, _jm73)
                entry["j1p"] = now
                _shape73 = None
                try:
                    from database.bot_kv import get_json as _g73s
                    _pins73b = _g73s("spot_urgent_watch", {}) or {}
                    _pk73b = f"{str(entry.get('symbol') or '').upper()}|{str(entry.get('tf') or '')}"
                    _pin73b = _pins73b.get(_pk73b) or _pins73b.get(_pk73b.upper()) or {}
                    _shape73 = (_pin73b.get("shape") or None)
                except Exception:
                    _shape73 = None
                _titem73 = _lw_touch_item(entry, price, _patt73 or "EDGE", _shape73)
                _tchart73 = None
                if _shape73:
                    try:
                        from data.fetcher import get_market_bundle as _gmb73
                        from analysis.candle_counts import fetch_limits as _fl73
                        from analysis.spot_engine import build_spot_alert_candidate as _bsac73
                        from bot.messages_v7 import generate_chart as _gc73
                        _bun73 = _gmb73(str(entry.get("symbol") or "").upper(), (str(entry.get("tf") or "").lower(),), limits=_fl73())
                        _frm73 = (_bun73.get(str(entry.get("tf") or "").lower()) if _bun73 else None)
                        if _frm73 is not None:
                            _tcand73 = _bsac73(_titem73)
                            _tchart73 = _gc73(_frm73, _tcand73, confirmed=False)
                    except Exception as _r73exc:
                        print(f"line watch s1 render skipped: {_r73exc}")
                        _tchart73 = None
                from bot.messages_v7 import send_spot_alert as _ssa73
                if _ssa73(_titem73, _tchart73):
                    entry["j1"] = now
                    _sent73 += 1
                    print(f"LINE_WATCH s1 {'chart' if _tchart73 else 'text'} {entry.get('symbol')}|{entry.get('tf')}")
                else:
                    print("line watch s1 send failed (pending expires in 10 min)")
            elif _slot73 == "s2":
                _jm73["s2p"] = now
                _s73j(_ckey73, _jm73)
                entry["j2p"] = now
                _bitem73 = _lw_touch_item(entry, price, _patt73 or "EDGE", None)
                _bitem73.update({"stage": _kind73, "_journey_slot": "s2"})
                from bot.messages_v7 import send_spot_alert as _ssa73b
                if _ssa73b(_bitem73, None):
                    entry["j2"] = now
                    _sent73 += 1
                    print(f"LINE_WATCH s2 text {entry.get('symbol')}|{entry.get('tf')}|{_kind73}")
                else:
                    print("line watch s2 send failed (pending expires in 10 min)")
        except Exception as exc:
            print(f"line watch send warning: {exc}")
    if changed:
        try:
            _s(_KV_KEY, state)
        except Exception:
            pass
    if sent or _muted73:
        print(f"LINE_WATCH pass: events={sent} sent={_sent73} muted={_muted73}")
    return sent
