"""r55 — the app's LIVE bridge + real phone push (Viva 09-28 dictation).

«اپلیکیشن دقیقا باید مثل تلگرام عمل بکنه — در همون لحظه تایید باید تایید
سیگنال به اپلیکیشن هم بره و بصورت لایو و لحظه‌ای نتیجه هیت شدن‌ها یا استاپ
بروزرسانی بشه … اوایل نوتفیکیشن فعال بود اما الان دیگه به گوشی نوتیف نمیاد».

Two jobs, both fail-open (a dead push layer must NEVER touch trading):

* PUSH — real Web Push (VAPID) to the phone: the PWA service worker gets a
  `push` handler, the app registers a subscription, and this module delivers
  confirm / TP-hit / stop-close events. The VAPID keypair is generated ONCE
  and stored in bot_kv (durable, prod-side) — never in the repo, same law as
  every other token.

* TAIL — a 5s poller over the `signals` lifecycle stamps (confirmed_at,
  tp1_hit_at, closed_at). Whatever writes a row (any lane, any code path),
  the app sees it within seconds and the phone gets the push. The pure
  classifier lives in `classify_tail_events` so tests need no DB.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

_KV_VAPID = "vapid_keys"
_KV_SUBS = "push_subs"
_KV_SEEN = "push_seen"
_KV_TAIL = "push_tail"
_TAIL_SECONDS = 5.0
_SEEN_MAX = 800


# ────────────────────────────── VAPID keys ──────────────────────────────
def _kv_get(key: str, default=None):
    try:
        from database.bot_kv import get_json
        return get_json(key, default)
    except Exception:
        return default


def _kv_set(key: str, value) -> None:
    try:
        from database.bot_kv import set_json
        set_json(key, value)
    except Exception:
        pass


def _vapid() -> Tuple[str, str]:
    """(public, private) VAPID keys — generated once, durable in bot_kv."""
    raw = _kv_get(_KV_VAPID) or {}
    pub, priv = str(raw.get("public") or ""), str(raw.get("private") or "")
    if pub and priv:
        return pub, priv
    try:
        import base64 as _b64
        from cryptography.hazmat.primitives import serialization as _ser
        from cryptography.hazmat.primitives.asymmetric import ec as _ec
        _priv = _ec.generate_private_key(_ec.SECP256R1())
        _priv_der = _priv.private_bytes(_ser.Encoding.DER,
                                        _ser.PrivateFormat.PKCS8,
                                        _ser.NoEncryption())
        _pub_raw = _priv.public_key().public_bytes(
            _ser.Encoding.X962, _ser.PublicFormat.UncompressedPoint)
        priv = _b64.urlsafe_b64encode(_priv_der).decode()
        pub = _b64.urlsafe_b64encode(_pub_raw).decode()
        _kv_set(_KV_VAPID, {"public": pub, "private": priv})
        return pub, priv
    except Exception:
        return "", ""


def public_key() -> str:
    return _vapid()[0]


# ─────────────────────────── subscriptions ────────────────────────────
def _endpoint_hash(subscription: Dict[str, Any]) -> str:
    ep = str((subscription or {}).get("endpoint") or "")
    return hashlib.sha256(ep.encode() or b"?").hexdigest()[:32]


def subscribe(subscription: Dict[str, Any]) -> bool:
    if not isinstance(subscription, dict) or not subscription.get("endpoint"):
        return False
    subs = _kv_get(_KV_SUBS, {}) or {}
    subs[_endpoint_hash(subscription)] = {
        "sub": subscription, "added_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _kv_set(_KV_SUBS, subs)
    return True


def unsubscribe(endpoint: str) -> bool:
    subs = _kv_get(_KV_SUBS, {}) or {}
    h = _endpoint_hash({"endpoint": endpoint})
    if h in subs:
        subs.pop(h)
        _kv_set(_KV_SUBS, subs)
        return True
    return False


def subscriber_count() -> int:
    return len(_kv_get(_KV_SUBS, {}) or {})


def send_all(title: str, body: str, tag: str = "viva") -> int:
    """Web Push to every live subscription. Returns delivered count."""
    subs = _kv_get(_KV_SUBS, {}) or {}
    if not subs:
        return 0
    pub, priv = _vapid()
    if not pub or not priv:
        return 0
    sent = 0
    try:
        from pywebpush import WebPushException, webpush
    except Exception:
        return 0
    dead = []
    for h, item in subs.items():
        sub = (item or {}).get("sub") or {}
        try:
            import base64 as _b64d
            webpush(subscription_info=sub,
                    data=json.dumps({"title": title, "body": body, "tag": tag}),
                    vapid_private_key=_b64d.urlsafe_b64decode(priv),
                    vapid_claims={"sub": "mailto:viva@viva-mon.labs"})
            sent += 1
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", 0)
            if code in (404, 410):     # gone — drop it
                dead.append(h)
        except Exception:
            continue
    if dead:
        for h in dead:
            subs.pop(h, None)
        _kv_set(_KV_SUBS, subs)
    return sent


# ─────────────────────── lifecycle tail (pure core) ──────────────────────
def classify_tail_events(rows, since: str) -> Tuple[List[Dict[str, str]], str]:
    """(events, new_since) — events newer than `since` from signal rows.

    rows: (signal_id, public_code, symbol, direction, source, result, pnl_pct,
           confirmed_at, tp1_hit_at, closed_at) — stamps 'YYYY-MM-DD HH:MM:SS'.
    Kinds: confirm → tp1 → close, one event per (signal_id, kind)."""
    events: List[Dict[str, str]] = []
    new_since = since
    for (sid, code, symbol, direction, source, result, pnl,
         confirmed_at, tp1_at, closed_at) in rows:
        sid = str(sid or "")
        symbol = str(symbol or "?")
        direction = str(direction or "")
        for kind, stamp in (("confirm", confirmed_at),
                            ("tp1", tp1_at),
                            ("close", closed_at)):
            if not stamp:
                continue
            stamp = str(stamp)[:19]
            if since and str(stamp) <= str(since):
                continue
            if not new_since or str(stamp) > str(new_since):
                new_since = stamp
            if kind == "confirm":
                text = f"✅ تأیید شد — {symbol} {direction}"
            elif kind == "tp1":
                text = f"🎯 هدف اول {symbol} هیت شد"
            else:
                try:
                    pv = float(pnl or 0)
                    ptxt = f" ({'+' if pv >= 0 else ''}{pv:.2f}%)"
                except Exception:
                    ptxt = ""
                text = f"🏁 {symbol} بسته شد — {result}{ptxt}"
            events.append({"id": f"{sid}|{kind}", "kind": kind,
                           "symbol": symbol, "code": str(code or ""),
                           "text": text, "at": stamp})
    return events, new_since


def _fresh_only(events: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set(_kv_get(_KV_SEEN, []) or [])
    fresh = [e for e in events if e["id"] not in seen]
    if fresh:
        seen |= {e["id"] for e in fresh}
        seen = set(sorted(seen)[-_SEEN_MAX:])
        _kv_set(_KV_SEEN, sorted(seen))
    return fresh


def tail_once() -> Dict[str, int]:
    """One tail pass: new lifecycle events → push. Returns health stats."""
    stats = {"events": 0, "pushed": 0, "error": ""}
    try:
        from database import db as legacy_db
        from database.db import db_cursor
        tail = _kv_get(_KV_TAIL, {}) or {}
        since = str(tail.get("since") or "")
        p = legacy_db._ph()
        with db_cursor() as c:
            c.execute(f"""
                SELECT signal_id, public_code, symbol, direction, source, result,
                       pnl_pct, confirmed_at, tp1_hit_at, closed_at
                FROM signals
                WHERE COALESCE(confirmed_at, tp1_hit_at, closed_at) IS NOT NULL
                  AND COALESCE(confirmed_at, tp1_hit_at, closed_at) > {p}
                ORDER BY COALESCE(confirmed_at, tp1_hit_at, closed_at) DESC
                LIMIT 400
            """, (since or "1970-01-01 00:00:00",))
            rows = c.fetchall()
        if not since:
            # first pass after boot: prime silently — never replay history
            _, new_since = classify_tail_events(rows, since)
            _kv_set(_KV_TAIL, {"since": new_since, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            return dict(stats, primed=1)
        events, new_since = classify_tail_events(rows, since)
        fresh = _fresh_only(events)
        stats["events"] = len(fresh)
        for e in fresh:
            stats["pushed"] += send_all("VIVA · " + e["symbol"], e["text"],
                                        tag=e["id"])
        if new_since and new_since != since:
            _kv_set(_KV_TAIL, {"since": new_since, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    except Exception as exc:
        stats["error"] = str(exc)[:140]
    return stats


_tail_thread: Optional[threading.Thread] = None
_tail_stats: Dict[str, Any] = {"at": "", "events": 0, "pushed": 0, "error": "", "subs": 0}


def _tail_loop() -> None:
    while True:
        try:
            s = tail_once()
            s["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            s["subs"] = subscriber_count()
            _tail_stats.update(s)
        except Exception:
            pass
        time.sleep(_TAIL_SECONDS)


def start_push_tailer() -> None:
    global _tail_thread
    if _tail_thread is not None and _tail_thread.is_alive():
        return
    _tail_thread = threading.Thread(target=_tail_loop,
                                    name="viva-app-push-tail", daemon=True)
    _tail_thread.start()


def tail_health() -> Dict[str, Any]:
    return dict(_tail_stats)
