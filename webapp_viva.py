"""VIVA SIGNALS PRO — the mobile app (PWA) + channel-mirror + control panel.

Viva 09-23: «یه اپلیکیشن حرفه‌ای برای اندروید و آیفون … همه قسمت‌هایی که به
کانال‌های تلگرام میره با همین زیبایی … و بتونم کنترلش بکنم … داشبورد سابقه
سیگنال‌ها که وین‌ریت هر ستاپ مشخص بشه».

Design laws
-----------
* ONE lock in front of EVERYTHING (the old dashboard included): the Railway
  domain is public, so no route answers without the session cookie. Fail-closed
  when ``VIVA_APP_PASSWORD`` is unset (only ``/health`` stays open for liveness).
* ``publish_allowed(candidate)`` is the bot-side gate (fail-OPEN on any error —
  the scanner must never die because the app is broken): it honours the master
  pause and the per-setup switches persisted in ``bot_kv`` key ``webapp_control``.
* DEMO mode: with no reachable DB the app still renders with synthetic data so
  the UI can be evaluated anywhere — clearly badged «نمایشی».
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, make_response, redirect, request, send_file

TEHRAN = ZoneInfo("Asia/Tehran")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ICON_DIR = os.path.join(_BASE_DIR, "assets", "app_icons")
_FONT_DIR = os.path.join(_BASE_DIR, "assets", "fonts")

DEFAULT_SETUPS = ["TLBREAK", "ALBROX", "PINWALLQ", "PINVAL", "TECHCLASSIC", "SPOT"]

viva_app = Blueprint("viva_app", __name__)


# ────────────────────────────── auth core ──────────────────────────────
def _password() -> str:
    return (os.getenv("VIVA_APP_PASSWORD") or "").strip()


def _serializer():
    pw = _password()
    if not pw:
        return None
    from itsdangerous import URLSafeSerializer
    secret = hashlib.sha256(("viva-app::" + pw).encode("utf-8")).digest()
    return URLSafeSerializer(secret, salt="viva-session")


_LOGIN_ATTEMPTS: Dict[str, List[float]] = {}


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    window = [t for t in _LOGIN_ATTEMPTS.get(ip, []) if now - t < 60.0]
    _LOGIN_ATTEMPTS[ip] = window
    return len(window) >= 10


def _note_attempt(ip: str) -> None:
    _LOGIN_ATTEMPTS.setdefault(ip, []).append(time.monotonic())


def _session_ok() -> bool:
    ser = _serializer()
    if ser is None:
        return False
    try:
        ser.loads(request.cookies.get("viva_session") or "", max_age=60 * 60 * 24 * 30)
        return True
    except Exception:
        return False


_PUBLIC_PREFIXES = (
    "/health", "/app/login", "/app/api/login", "/app/logout", "/app/manifest.webmanifest",
    "/app/sw.js", "/app/icons/", "/app/fonts/", "/app/favicon.png",
)


def install_viva_app(app) -> None:
    """Mount the app + the single login lock on the WHOLE Flask server."""
    app.register_blueprint(viva_app)

    @app.before_request
    def _viva_lock():
        path = request.path or "/"
        if any(path == p or path.startswith(p) for p in _PUBLIC_PREFIXES):
            return None
        if _password() and _session_ok():
            return None
        if path.startswith("/app/api") or request.is_json:
            return jsonify({"ok": False, "error": "locked"}), 401
        return redirect("/app/login", code=302)

    @app.context_processor
    def _viva_ctx():
        return {"demo_mode": _demo_mode()}


# ────────────────────────── control gate (bot side) ──────────────────────
_CTRL_CACHE: Dict[str, Any] = {"at": 0.0, "state": None}


def control_state(force: bool = False) -> Dict[str, Any]:
    """``bot_kv['webapp_control']`` with a 5s cache. Fail-open defaults."""
    if not force and _CTRL_CACHE["state"] is not None and time.monotonic() - _CTRL_CACHE["at"] < 5.0:
        return _CTRL_CACHE["state"]
    state: Dict[str, Any] = {"paused": False, "setups": {}, "updated_at": ""}
    try:
        from database.bot_kv import get_json
        raw = get_json("webapp_control", {}) or {}
        state["paused"] = bool(raw.get("paused"))
        state["setups"] = {str(k): bool(v) for k, v in (raw.get("setups") or {}).items()}
        state["updated_at"] = str(raw.get("updated_at") or "")
    except Exception:
        pass
    _CTRL_CACHE["at"] = time.monotonic()
    _CTRL_CACHE["state"] = state
    return state


def save_control(paused: Optional[bool] = None,
                 setups: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    state = control_state(force=True)
    if paused is not None:
        state["paused"] = bool(paused)
    if setups is not None:
        merged = dict(state.get("setups") or {})
        for k, v in dict(setups).items():
            merged[str(k)] = bool(v)
        state["setups"] = merged
    state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        from database.bot_kv import set_json
        set_json("webapp_control", {"paused": state["paused"], "setups": state["setups"],
                                    "updated_at": state["updated_at"]})
    except Exception:
        pass
    _CTRL_CACHE["at"] = time.monotonic()
    _CTRL_CACHE["state"] = state
    return state


def publish_allowed(candidate: Any) -> bool:
    """Scanner gate: master pause + per-setup switches. ALWAYS fail-open."""
    try:
        st = control_state()
        if st.get("paused"):
            return False
        code = str(getattr(candidate, "setup_code", "") or getattr(candidate, "source", "") or "").upper()
        switches = st.get("setups") or {}
        if code and code in switches and not switches[code]:
            return False
        if code == "SPOTBREAK":
            if switches.get("SPOT") is False:
                return False
    except Exception:
        return True
    return True


# ────────────────────────────── data layer ──────────────────────────────
def _demo_mode() -> bool:
    if (os.getenv("VIVA_APP_DEMO") or "").strip() == "1":
        return True   # sandbox/preview badge only — NEVER set in production
    try:
        from database import db as legacy_db
        return not bool(getattr(legacy_db, "USE_POSTGRES", False))
    except Exception:
        return True


def _demo_payload() -> Dict[str, Any]:
    now = datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M")
    feed = [
        dict(symbol="BTCUSDT", source="TLBREAK", strategy_fa="شکست خط روند", direction="LONG",
             entry="64,250–64,900", sl="62,180", tp1="67,400", tp2="71,200", result="PENDING",
             pnl=None, score=9, style="SWING", code="VIVA-K001204", tf="4H", time=now, spot=False),
        dict(symbol="ETHUSDT", source="PINWALLQ", strategy_fa="کیفیت پی‌ن‌بار", direction="LONG",
             entry="2,738–2,754", sl="2,688", tp1="2,815", tp2="2,910", result="WIN",
             pnl=2.8, score=8, style="SWING", code="VIVA-K001187", tf="1H", time=now, spot=False),
        dict(symbol="SOLUSDT", source="SPOTBREAK", strategy_fa="شکست اسپات", direction="LONG",
             entry="151.2–152.4", sl="146.8", tp1="159.0", tp2="168.5", result="PENDING",
             pnl=None, score=8, style="SWING", code="VIVA-SPOT-E000318", tf="4H", time=now, spot=True),
        dict(symbol="LINKUSDT", source="ALBROX", strategy_fa="البروکس", direction="SHORT",
             entry="14.85–15.05", sl="15.42", tp1="14.10", tp2="13.30", result="LOSS",
             pnl=-1.6, score=7, style="SWING", code="VIVA-K001101", tf="2H", time=now, spot=False),
        dict(symbol="HYPEUSDT", source="TLBREAK", strategy_fa="شکست خط روند", direction="LONG",
             entry="38.4–39.1", sl="36.9", tp1="41.8", tp2="45.5", result="CANCELLED",
             pnl=None, score=7, style="SWING", code="VIVA-K001088", tf="1H", time=now, spot=False),
    ]
    chains = [
        dict(symbol="BTCUSDT", badge="TLBREAK", direction="LONG", status="CONFIRMED", score=9,
             zone="64,250–64,900", updates=3, code="VIVA-K001204", tf="4H", spot=False),
        dict(symbol="SOLUSDT", badge="SPOTBREAK", direction="LONG", status="WATCH", score=8,
             zone="151.2–152.4", updates=1, code="VIVA-SPOT-E000318", tf="4H", spot=True),
    ]
    analytics = dict(
        rows=[
            dict(name="TLBREAK", fa="شکست خط روند", total=48, wins=31, losses=9, pending=8,
                 wr=77.5, avg_pnl=2.4, best=6.1, worst=-1.2, avg_score=8.2, last="۲ ساعت پیش"),
            dict(name="SPOTBREAK", fa="شکست اسپات", total=36, wins=24, losses=6, pending=6,
                 wr=80.0, avg_pnl=3.1, best=9.4, worst=-1.9, avg_score=8.0, last="۵ ساعت پیش"),
            dict(name="PINWALLQ", fa="کیفیت پی‌ن‌بار", total=27, wins=16, losses=7, pending=4,
                 wr=69.6, avg_pnl=1.7, best=5.2, worst=-1.4, avg_score=7.6, last="دیروز"),
            dict(name="ALBROX", fa="البروکس", total=22, wins=11, losses=8, pending=3,
                 wr=57.9, avg_pnl=0.9, best=4.0, worst=-2.1, avg_score=7.2, last="۲ روز پیش"),
            dict(name="PINVAL", fa="اعتبارسنجی پی‌ن", total=18, wins=9, losses=6, pending=3,
                 wr=60.0, avg_pnl=1.1, best=4.6, worst=-1.8, avg_score=7.4, last="۳ روز پیش"),
        ],
        spot=dict(wr=80.0, wins=24, losses=6, total=36),
        futures=dict(wr=71.4, wins=70, losses=28, total=125),
        summary=dict(total=161, wins=94, losses=34, winrate=73.4, avg_pnl=2.1),
    )
    return dict(demo=True, feed=feed, chains=chains, analytics=analytics,
                control=control_state(), scanner=dict(alive=True, mode="نمایشی"),
                server_time=now)


def _fetch_state() -> Dict[str, Any]:
    if (os.getenv("VIVA_APP_DEMO") or "").strip() == "1":
        return _demo_payload()
    try:
        from database.db import db_cursor, get_dashboard_summary, get_strategy_performance
        summary = get_dashboard_summary() or {}
        feed: List[Dict[str, Any]] = []
        spot = dict(wins=0, losses=0, total=0)
        fut = dict(wins=0, losses=0, total=0)
        rows_out: List[Dict[str, Any]] = []
        with db_cursor() as c:
            c.execute("""
                SELECT symbol, source, strategy_fa, direction, entry, sl, tp1, tp2,
                       result, pnl_pct, score, trade_style, public_code, trigger_timeframe,
                       created_at, closed_at, confirmed, partial_win
                FROM signals
                ORDER BY created_at DESC
                LIMIT 60
            """)
            rows = c.fetchall()
            for r in rows:
                (symbol, source, fa, direction, entry, sl, tp1, tp2, result, pnl, score,
                 style, code, tf, created_at, closed_at, confirmed, partial_win) = r
                code = str(code or "")
                is_spot = code.startswith("VIVA-SPOT-") or str(source or "") == "SPOTBREAK"
                res = "WIN" if (result == "WIN" or partial_win) else str(result or "PENDING")
                _acc = spot if is_spot else fut
                _acc["total"] += 1
                if res == "WIN":
                    _acc["wins"] += 1
                elif res == "LOSS":
                    _acc["losses"] += 1
                feed.append(dict(
                    symbol=symbol, source=source, strategy_fa=fa, direction=direction,
                    entry=_fmt_price(entry), sl=_fmt_price(sl), tp1=_fmt_price(tp1), tp2=_fmt_price(tp2),
                    result=res, pnl=(float(pnl) if pnl is not None else None), score=score,
                    style=style, code=code, tf=str(tf or "").upper(),
                    time=str(created_at or ""), spot=is_spot, confirmed=bool(confirmed),
                ))
            c.execute("""
                SELECT CASE WHEN public_code LIKE 'VIVA-SPOT-%%' THEN 'SPOT' ELSE 'FUT' END AS mkt,
                       COUNT(*) AS total,
                       SUM(CASE WHEN (result='WIN' OR partial_win=TRUE) THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
                       AVG(CASE WHEN result IN ('WIN','LOSS') THEN pnl_pct END) AS avg_pnl
                FROM signals
                WHERE result IN ('WIN','LOSS','PENDING','CANCELLED')
                GROUP BY 1
            """)
            mkt_rows = c.fetchall()
            for mkt, total, wins, losses, avg_pnl in mkt_rows:
                tgt = spot if mkt == "SPOT" else fut
                tgt.update(total=int(total or 0), wins=int(wins or 0), losses=int(losses or 0),
                           avg_pnl=(round(float(avg_pnl), 2) if avg_pnl is not None else None))
            c.execute("""
                SELECT source, MAX(strategy_fa) AS fa, COUNT(*) AS total,
                       SUM(CASE WHEN (result='WIN' OR partial_win=TRUE) THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
                       SUM(CASE WHEN result='PENDING' THEN 1 ELSE 0 END) AS pending,
                       AVG(CASE WHEN result IN ('WIN','LOSS') THEN pnl_pct END) AS avg_pnl,
                       MAX(CASE WHEN result IN ('WIN','LOSS') THEN pnl_pct END) AS best,
                       MIN(CASE WHEN result IN ('WIN','LOSS') THEN pnl_pct END) AS worst,
                       AVG(score) AS avg_score, MAX(created_at) AS last
                FROM signals
                GROUP BY source
                ORDER BY total DESC
            """)
            for r in c.fetchall():
                (name, fa, total, wins, losses, pending, avg_pnl, best, worst, avg_score, last) = r
                total, wins, losses = int(total or 0), int(wins or 0), int(losses or 0)
                closed = wins + losses
                rows_out.append(dict(
                    name=str(name or "?"), fa=str(fa or name or "?"), total=total,
                    wins=wins, losses=losses, pending=int(pending or 0),
                    wr=(round(wins * 100.0 / closed, 1) if closed else 0.0),
                    avg_pnl=(round(float(avg_pnl), 2) if avg_pnl is not None else None),
                    best=(round(float(best), 2) if best is not None else None),
                    worst=(round(float(worst), 2) if worst is not None else None),
                    avg_score=(round(float(avg_score), 1) if avg_score is not None else None),
                    last=_rel_fa(str(last or "")),
                ))
        chains: List[Dict[str, Any]] = []
        try:
            # live WATCH chains ( EDUCATIONAL/APPROACHING previews + slots )
            from database.candidate_store import get_active_candidates
            for cand in (get_active_candidates() or [])[:24]:
                md = getattr(cand, "metadata", None) or {}
                code = str(md.get("public_code") or "")
                chains.append(dict(
                    symbol=cand.symbol, badge=str(getattr(cand, "setup_code", "") or ""),
                    direction=getattr(cand, "direction", ""), status=str(getattr(cand, "status", "") or ""),
                    score=getattr(cand, "score", 0),
                    zone=f"{_fmt_price(getattr(cand, 'entry_zone_bottom', 0))}–{_fmt_price(getattr(cand, 'entry_zone_top', 0))}",
                    updates=int(md.get("update_count") or 0), code=code,
                    tf=str(getattr(cand, "trigger_timeframe", "") or "").upper(),
                    spot=code.startswith("VIVA-SPOT-"),
                ))
        except Exception:
            pass
        # live POSITIONS (confirmed, still running) on top of the chains list
        try:
            with db_cursor() as c2:
                c2.execute("""
                    SELECT symbol, source, strategy_fa, direction, entry, sl, score,
                           trade_style, public_code, trigger_timeframe, created_at
                    FROM signals
                    WHERE confirmed=TRUE AND result='PENDING'
                    ORDER BY created_at DESC LIMIT 12
                """)
                for r in c2.fetchall():
                    (symbol, source, fa, direction, entry, sl, score, style, code, tf, created_at) = r
                    code = str(code or "")
                    chains.insert(0, dict(
                        symbol=symbol, badge=str(source or ""), direction=direction,
                        status="CONFIRMED", score=score,
                        zone=_fmt_price(entry), updates=0, code=code,
                        tf=str(tf or "").upper(),
                        spot=code.startswith("VIVA-SPOT-") or str(source or "") == "SPOTBREAK",
                    ))
        except Exception:
            pass
        wr = lambda a: (round(a["wins"] * 100.0 / max(1, a["wins"] + a["losses"]), 1))
        spot["wr"], fut["wr"] = wr(spot), wr(fut)
        analytics = dict(rows=rows_out, spot=spot, futures=fut, summary=dict(
            total=int(summary.get("total_signals") or 0), wins=int(summary.get("wins") or 0),
            losses=int(summary.get("losses") or 0), winrate=float(summary.get("winrate") or 0.0),
            avg_pnl=float(summary.get("avg_pnl") or 0.0),
        ))
        scanner = dict(alive=True, mode="")
        try:
            from flask import current_app
            thr = current_app.config.get("VIVA_SCANNER_THREAD")
            if thr is not None:
                scanner["alive"] = bool(thr.is_alive())
        except Exception:
            pass
        return dict(demo=False, feed=feed, chains=chains, analytics=analytics,
                    control=control_state(), scanner=scanner,
                    server_time=datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M"))
    except Exception as exc:
        payload = _demo_payload()
        payload["db_error"] = str(exc)[:120]
        return payload


def _fmt_price(v: Any) -> str:
    try:
        f = float(v)
    except Exception:
        return "—"
    if f >= 1000:
        return f"{f:,.0f}"
    if f >= 10:
        return f"{f:,.2f}"
    if f >= 1:
        return f"{f:,.3f}"
    return f"{f:.6f}".rstrip("0")


def _rel_fa(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        mins = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
        if mins < 1:
            return "همین حالا"
        if mins < 60:
            return f"{mins} دقیقه پیش"
        if mins < 1440:
            return f"{mins // 60} ساعت پیش"
        return f"{mins // 1440} روز پیش"
    except Exception:
        return ""


# ──────────────────────────────── routes ────────────────────────────────
@viva_app.route("/app")
def app_shell():
    resp = make_response(APP_HTML)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@viva_app.route("/app/login", methods=["GET"])
def login_page():
    if _password() and _session_ok():
        return redirect("/app", code=302)
    resp = make_response(LOGIN_HTML.replace("__ERROR__", ""))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@viva_app.route("/app/api/login", methods=["POST"])
def api_login():
    if not _password():
        return jsonify({"ok": False, "error": "no-password"}), 503
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0]
    if _rate_limited(ip):
        return jsonify({"ok": False, "error": "rate"}), 429
    pw = str((request.get_json(silent=True) or {}).get("password") or request.form.get("password") or "")
    _note_attempt(ip)
    if not hmac.compare_digest(pw, _password()):
        return jsonify({"ok": False, "error": "bad"}), 401
    ser = _serializer()
    resp = jsonify({"ok": True})
    resp.set_cookie("viva_session", ser.dumps({"u": "viva", "t": time.time()}),
                    max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax")
    return resp


@viva_app.route("/app/logout", methods=["POST", "GET"])
def api_logout():
    resp = make_response("", 204) if request.method == "POST" else redirect("/app/login", code=302)
    if request.method == "POST":
        resp.delete_cookie("viva_session")
    return resp


@viva_app.route("/app/api/state")
def api_state():
    return jsonify(_fetch_state())


@viva_app.route("/app/api/control", methods=["POST"])
def api_control():
    body = request.get_json(silent=True) or {}
    state = save_control(paused=body.get("paused"),
                         setups=body.get("setups") if isinstance(body.get("setups"), dict) else None)
    return jsonify({"ok": True, "control": state})


# ────────────────────────────── PWA assets ──────────────────────────────
@viva_app.route("/app/manifest.webmanifest")
def pwa_manifest():
    manifest = {
        "name": "VIVA SIGNALS PRO", "short_name": "VIVA",
        "description": "داشبورد سیگنال‌ها و کنترل ربات ویوا",
        "lang": "fa", "dir": "rtl",
        "start_url": "/app", "scope": "/",
        "display": "standalone", "orientation": "portrait",
        "theme_color": "#0d1017", "background_color": "#0d1017",
        "icons": [
            {"src": "/app/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/app/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/app/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return jsonify(manifest)


@viva_app.route("/app/sw.js")
def pwa_sw():
    js = """
const SHELL = [['/app/fonts/Vazirmatn-Regular.woff2','font'],['/app/fonts/Vazirmatn-Bold.woff2','font'],
  ['/app/icons/icon-192.png','img'],['/app/icons/icon-512.png','img']];
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/app/api/')) return;         // live data: always network
  const hit = SHELL.find(([p]) => url.pathname === p);
  if (hit) {
    e.respondWith(caches.open('viva-shell-v1').then(async c => {
      const cached = await c.match(e.request);
      const fetchP = fetch(e.request).then(r => { c.put(e.request, r.clone()); return r; }).catch(() => cached);
      return cached || fetchP;
    }));
  }
});
"""
    resp = make_response(js)
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    return resp


@viva_app.route("/app/icons/<path:name>")
def pwa_icon(name):
    safe = {"icon-192.png", "icon-512.png", "apple-touch-icon.png", "favicon.png"}
    if name not in safe:
        return "", 404
    return send_file(os.path.join(_ICON_DIR, name), mimetype="image/png")


@viva_app.route("/app/favicon.png")
def pwa_favicon():
    return send_file(os.path.join(_ICON_DIR, "favicon.png"), mimetype="image/png")


@viva_app.route("/app/fonts/<path:name>")
def pwa_font(name):
    safe = {"Vazirmatn-Regular.woff2", "Vazirmatn-Bold.woff2"}
    if name not in safe:
        return "", 404
    return send_file(os.path.join(_FONT_DIR, name), mimetype="font/woff2")


# ──────────────────────────────── views ─────────────────────────────────
LOGIN_HTML = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>ورود — VIVA SIGNALS PRO</title>
<link rel="icon" href="/app/favicon.png">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;background:
 radial-gradient(1200px 600px at 70% -10%,#1a2130 0%,#0d1017 55%) ;font-family:Vazirmatn,Segoe UI,Tahoma,sans-serif;color:#e9e4da}
.card{width:min(92vw,380px);background:#151a22;border:1px solid rgba(232,182,76,.18);border-radius:22px;padding:34px 28px;box-shadow:0 24px 70px rgba(0,0,0,.5)}
.logo{display:block;margin:0 auto 14px;width:84px;height:84px;filter:drop-shadow(0 6px 18px rgba(232,182,76,.25))}
h1{font-size:19px;text-align:center;color:#e8b64c;letter-spacing:.06em}
p.sub{text-align:center;color:#8b93a1;font-size:12.5px;margin:8px 0 22px}
input{width:100%;background:#0d1017;border:1px solid #262d39;color:#e9e4da;border-radius:13px;padding:13px 15px;font-size:15px;font-family:inherit;outline:none;text-align:center;letter-spacing:.14em}
input:focus{border-color:#e8b64c}
button{width:100%;margin-top:14px;background:linear-gradient(135deg,#e8b64c,#c9962f);border:0;color:#171207;font-weight:800;font-family:inherit;font-size:15px;border-radius:13px;padding:13px;cursor:pointer}
button:active{transform:scale(.98)}
.err{color:#e5484d;font-size:12.5px;text-align:center;margin-top:12px;min-height:16px}
</style></head><body>
<div class="card">
<img class="logo" src="/app/icons/icon-192.png" alt="VIVA">
<h1>VIVA SIGNALS PRO</h1>
<p class="sub">ورود مدیر — دسترسی به فید زنده، عملکرد و کنترل</p>
<input id="pw" type="password" inputmode="text" autocomplete="current-password" placeholder="رمز ورود">
<button onclick="go()">ورود به اپ</button>
<div class="err" id="err">__ERROR__</div>
</div>
<script>
async function go(){
 const b=document.querySelector('button');b.textContent='...';b.disabled=true;
 try{
  const r=await fetch('/app/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password:document.getElementById('pw').value})});
  if(r.ok){location.href='/app';return}
  const j=await r.json().catch(()=>({}));
  document.getElementById('err').textContent = j.error==='rate' ? 'تلاش زیاد — یک دقیقه صبر کن'
    : j.error==='no-password' ? 'رمز روی سرور تنظیم نشده (VIVA_APP_PASSWORD)' : 'رمز درست نیست';
 }catch(e){document.getElementById('err').textContent='خطای شبکه'}
 b.textContent='ورود به اپ';b.disabled=false;
}
document.getElementById('pw').addEventListener('keydown',e=>{if(e.key==='Enter')go()});
</script></body></html>"""


APP_HTML = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0d1017">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="VIVA">
<title>VIVA SIGNALS PRO</title>
<link rel="manifest" href="/app/manifest.webmanifest">
<link rel="apple-touch-icon" href="/app/icons/apple-touch-icon.png">
<link rel="icon" href="/app/favicon.png">
<style>
@font-face{font-family:Vazirmatn;src:url(/app/fonts/Vazirmatn-Regular.woff2) format('woff2');font-weight:400;font-display:swap}
@font-face{font-family:Vazirmatn;src:url(/app/fonts/Vazirmatn-Bold.woff2) format('woff2');font-weight:700;font-display:swap}
:root{
 --bg:#0d1017;--panel:#151a22;--panel2:#1a212c;--line:rgba(232,182,76,.14);--line2:#242c39;
 --gold:#e8b64c;--gold2:#c9962f;--text:#e9e4da;--muted:#8b93a1;
 --long:#1fae7c;--short:#e5484d;--tp1:#2fbf9b;--tp2:#4c8dff;--stop:#e5484d;--entry:#98a2b3;
 --amber:#e2a336;--chip:#202836;
 --sat:env(safe-area-inset-top,0px);--sab:env(safe-area-inset-bottom,0px);
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{background:radial-gradient(900px 420px at 80% -8%,#161d2a 0%,var(--bg) 60%);color:var(--text);
 font-family:Vazirmatn,Segoe UI,Tahoma,sans-serif;font-size:14px;padding-bottom:calc(70px + var(--sab))}
header{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:10px;padding:calc(10px + var(--sat)) 14px 10px;
 background:rgba(13,16,23,.86);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
header img{width:34px;height:34px;border-radius:9px}
.ht{flex:1}
.ht b{display:block;font-size:14.5px;letter-spacing:.05em;color:var(--gold)}
.ht span{font-size:10.5px;color:var(--muted)}
.live{display:flex;align-items:center;gap:6px;font-size:10.5px;color:var(--muted);background:var(--chip);padding:5px 9px;border-radius:20px;border:1px solid var(--line2)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--long);box-shadow:0 0 0 0 rgba(31,174,124,.6);animation:pulse 1.8s infinite}
@keyframes pulse{70%{box-shadow:0 0 0 7px rgba(31,174,124,0)}100%{box-shadow:0 0 0 0 rgba(31,174,124,0)}}
main{padding:12px 12px 8px;max-width:640px;margin:0 auto}
.page{display:none}.page.on{display:block}
.demo{margin:0 0 10px;text-align:center;font-size:11px;color:var(--amber);background:rgba(226,163,54,.08);border:1px dashed rgba(226,163,54,.4);border-radius:10px;padding:6px}
.sect{display:flex;align-items:center;justify-content:space-between;margin:14px 2px 8px}
.sect h2{font-size:13px;color:var(--gold);letter-spacing:.04em}
.sect small{color:var(--muted);font-size:10.5px}
.card{background:linear-gradient(180deg,var(--panel) 0%,#131820 100%);border:1px solid var(--line2);border-radius:16px;padding:12px 13px;margin-bottom:10px;box-shadow:0 8px 24px rgba(0,0,0,.28)}
.card:active{border-color:var(--line)}
.row1{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.sym{font-size:15.5px;font-weight:800;letter-spacing:.02em}
.badge{font-size:10px;font-weight:700;color:var(--gold);border:1px solid rgba(232,182,76,.4);background:rgba(232,182,76,.07);padding:2.5px 8px;border-radius:8px}
.chip{font-size:10px;font-weight:700;padding:2.5px 8px;border-radius:8px}
.chip.LONG{color:#39d9a4;background:rgba(31,174,124,.12);border:1px solid rgba(31,174,124,.35)}
.chip.SHORT{color:#ff7b80;background:rgba(229,72,77,.12);border:1px solid rgba(229,72,77,.35)}
.chip.SPOT{color:#9db7ff;background:rgba(76,141,255,.12);border:1px solid rgba(76,141,255,.35)}
.chip.score{color:var(--text);background:var(--chip);border:1px solid var(--line2)}
.pills{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}
.pill{display:flex;align-items:center;justify-content:space-between;background:#10151d;border:1px solid var(--line2);border-radius:10px;padding:7px 10px}
.pill i{font-style:normal;font-size:9.5px;font-weight:800;letter-spacing:.04em}
.pill b{font-size:12px;font-weight:700}
.pill.entry i{color:var(--entry)} .pill.stop i{color:var(--stop)}
.pill.tp1 i{color:var(--tp1)} .pill.tp2 i{color:var(--tp2)}
.ftr{display:flex;align-items:center;justify-content:space-between;margin-top:9px}
.code{font-size:10.5px;color:var(--muted);font-family:ui-monospace,Menlo,monospace;direction:ltr}
.time{font-size:10.5px;color:var(--muted)}
.res{font-size:10px;font-weight:800;padding:3px 9px;border-radius:8px}
.res.PENDING{color:var(--amber);background:rgba(226,163,54,.1);border:1px solid rgba(226,163,54,.35)}
.res.WIN{color:#39d9a4;background:rgba(31,174,124,.12);border:1px solid rgba(31,174,124,.4)}
.res.LOSS{color:#ff7b80;background:rgba(229,72,77,.12);border:1px solid rgba(229,72,77,.4)}
.res.CANCELLED{color:var(--muted);background:var(--chip);border:1px solid var(--line2)}
.chain .row1{margin-bottom:8px}
.upd{font-size:10.5px;color:var(--amber);background:rgba(226,163,54,.08);border:1px solid rgba(226,163,54,.3);padding:2px 8px;border-radius:8px}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}
.tile{background:var(--panel);border:1px solid var(--line2);border-radius:14px;padding:11px 8px;text-align:center}
.tile b{display:block;font-size:17px}
.tile span{font-size:10px;color:var(--muted)}
.tile.gold b{color:var(--gold)} .tile.green b{color:#39d9a4} .tile.red b{color:#ff7b80}
.wr{height:6px;background:#0d1017;border-radius:6px;margin-top:8px;overflow:hidden;border:1px solid var(--line2)}
.wr i{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,var(--gold2),var(--gold));transition:width .7s}
.strat{margin-bottom:8px}
.strat .row1{margin-bottom:2px}
.strat .nm{font-size:13px;font-weight:700;flex:1}
.mini{font-size:10px;color:var(--muted)}
.pnlp{color:#39d9a4}.pnln{color:#ff7b80}
.sf{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:4px}
.sf .tile{text-align:right;padding:12px}
.sf .tile small{display:block;margin-bottom:3px}
.toggle-row{display:flex;align-items:center;justify-content:space-between;padding:12px 2px;border-bottom:1px solid var(--line2)}
.toggle-row:last-child{border-bottom:0}
.tl b{font-size:13.5px;display:block}
.tl span{font-size:10.5px;color:var(--muted)}
.sw{position:relative;width:46px;height:26px;border-radius:20px;background:#232b38;border:1px solid var(--line2);cursor:pointer;transition:.25s;flex-shrink:0}
.sw::after{content:'';position:absolute;top:2px;right:2px;width:20px;height:20px;border-radius:50%;background:#8b93a1;transition:.25s}
.sw.on{background:rgba(31,174,124,.25);border-color:rgba(31,174,124,.5)}
.sw.on::after{background:#39d9a4;transform:translateX(-19px)}
.master .sw{width:56px;height:30px}.master .sw::after{width:24px;height:24px}
.master .sw.on::after{transform:translateX(-25px)}
.hint{font-size:10.5px;color:var(--muted);line-height:1.9;margin-top:10px}
.btn{width:100%;margin-top:14px;background:linear-gradient(135deg,var(--gold),var(--gold2));border:0;color:#171207;font-weight:800;font-family:inherit;font-size:14px;border-radius:13px;padding:12px;cursor:pointer}
.statline{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.stat{font-size:10.5px;color:var(--muted);background:var(--chip);border:1px solid var(--line2);border-radius:9px;padding:5px 10px}
.stat b{color:var(--text)}
nav{position:fixed;bottom:0;right:0;left:0;z-index:60;display:flex;background:rgba(13,16,23,.92);backdrop-filter:blur(16px);border-top:1px solid var(--line);padding:8px 10px calc(8px + var(--sab))}
nav button{flex:1;background:none;border:0;color:var(--muted);font-family:inherit;font-size:10.5px;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;padding:4px}
nav button svg{width:21px;height:21px}
nav button.on{color:var(--gold)}
.empty{text-align:center;color:var(--muted);font-size:12px;padding:26px 0}
.refresh{position:fixed;top:calc(8px + var(--sat));left:12px;z-index:70;font-size:10px;color:var(--muted);background:rgba(13,16,23,.7);padding:3px 8px;border-radius:8px;opacity:0;transition:.3s}
.refresh.on{opacity:1}
</style></head><body>
<div class="refresh" id="refresh">به‌روزرسانی…</div>
<header>
 <img src="/app/icons/icon-192.png" alt="">
 <div class="ht"><b>VIVA SIGNALS PRO</b><span>فید زندهٔ سیگنال‌ها • کنترل • عملکرد</span></div>
 <div class="live"><span class="dot" id="dot"></span><span id="clock">—</span></div>
</header>
<main>
<div class="demo" id="demo" style="display:none">حالت نمایشی — متصل به دیتابیس زنده نیست</div>

<section class="page on" id="page-feed">
  <div class="sect"><h2>⛓ زنجیره‌های رصد فعال</h2><small id="chainsN"></small></div>
  <div id="chains"></div>
  <div class="sect"><h2>📡 فید سیگنال‌ها</h2><small id="feedN"></small></div>
  <div id="feed"></div>
</section>

<section class="page" id="page-perf">
  <div class="tiles" id="sumTiles"></div>
  <div class="sect"><h2>🏆 وین‌ریت هر ستاپ</h2><small>بردها ÷ (برد+باخت)</small></div>
  <div id="strats"></div>
  <div class="sect"><h2>💎 اسپات در برابر فیوچرز</h2></div>
  <div class="sf" id="sf"></div>
</section>

<section class="page" id="page-ctrl">
  <div class="sect"><h2>🎛 کنترل انتشار</h2><small id="ctrlSaved"></small></div>
  <div class="card master">
    <div class="toggle-row">
      <div class="tl"><b>توقف کل سیگنال‌های جدید</b><span>مانیتور زنجیره‌های باز ادامه دارد؛ فقط انتشارِ جدید متوقف می‌شود</span></div>
      <div class="sw" id="swPause" onclick="flipPause()"></div>
    </div>
  </div>
  <div class="sect"><h2>⚙️ ستاپ‌ها</h2><small>روشن/خاموش هر ستاپ</small></div>
  <div class="card" id="setups"></div>
  <button class="btn" onclick="saveCtrl()">ذخیرهٔ تنظیمات کنترل</button>
  <div class="statline" id="botstat"></div>
  <p class="hint">راهنما: «توقف کل» همان کلید اضطراری است — هیچ سیگنال جدیدی منتشر نمی‌شود تا وقتی خاموشش کنی. خاموش‌کردن یک ستاپ فقط مانع انتشارِ همان ستاپ می‌شود. تغییرات تا ۵ ثانیه بعد روی ربات اعمال می‌شود.</p>
</section>
</main>

<nav>
 <button class="on" data-p="feed" onclick="tab('feed',this)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>فید زنده</button>
 <button data-p="perf" onclick="tab('perf',this)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>عملکرد</button>
 <button data-p="ctrl" onclick="tab('ctrl',this)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 8h10M18 8h2M4 16h2M10 16h10"/><circle cx="16" cy="8" r="2"/><circle cx="8" cy="16" r="2"/></svg>کنترل</button>
</nav>

<script>
const $=q=>document.querySelector(q);
let STATE=null;
const fnum=v=>{if(v===null||v===undefined||v==='')return '—';return String(v)};
function tehran(iso){try{const d=new Date(iso);if(isNaN(d))return iso||'';return d.toLocaleString('fa-IR',{timeZone:'Asia/Tehran',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}catch(e){return iso||''}}
function resFa(r){return {PENDING:'در جریان',WIN:'برد ✦',LOSS:'باخت',CANCELLED:'ابطال'}[r]||r}
function tab(p,btn){document.querySelectorAll('.page').forEach(x=>x.classList.remove('on'));$('#page-'+p).classList.add('on');
 document.querySelectorAll('nav button').forEach(b=>b.classList.remove('on'));btn.classList.add('on');window.scrollTo(0,0)}
function feedCard(s){
 const dir=s.spot?'LONG':(s.direction||'');
 return `<div class="card">
  <div class="row1"><span class="sym">${fnum(s.symbol)}</span>
   <span class="badge">${fnum(s.source)}</span>
   ${dir?`<span class="chip ${dir}">${dir==='LONG'?'خرید 🟢':'فروش 🔴'}</span>`:''}
   ${s.spot?'<span class="chip SPOT">اسپات</span>':''}
   ${s.tf?`<span class="chip score">${fnum(s.tf)}</span>`:''}
   ${s.score?`<span class="chip score">★ ${s.score}/10</span>`:''}</div>
  <div class="pills">
   <div class="pill entry"><i>ورود</i><b>${fnum(s.entry)}</b></div>
   <div class="pill stop"><i>استاپ</i><b>${fnum(s.sl)}</b></div>
   <div class="pill tp1"><i>TP1</i><b>${fnum(s.tp1)}</b></div>
   <div class="pill tp2"><i>TP2</i><b>${fnum(s.tp2)}</b></div></div>
  <div class="ftr"><span class="code">${fnum(s.code)}</span>
   <span class="res ${s.result}">${resFa(s.result)}${s.pnl!==null&&s.pnl!==undefined?` ${s.pnl>0?'+':''}${s.pnl}%`:''}</span>
   <span class="time">${tehran(s.time)}</span></div></div>`}
function chainCard(c){
 const dir=c.spot?'LONG':(c.direction||'');
 return `<div class="card chain">
  <div class="row1"><span class="sym">${fnum(c.symbol)}</span>
   <span class="badge">${fnum(c.badge)}</span>
   ${dir?`<span class="chip ${dir}">${dir==='LONG'?'خرید 🟢':'فروش 🔴'}</span>`:''}
   ${c.spot?'<span class="chip SPOT">اسپات</span>':''}
   ${c.tf?`<span class="chip score">${fnum(c.tf)}</span>`:''}
   ${c.score?`<span class="chip score">★ ${c.score}/10</span>`:''}</div>
  <div class="row1"><span class="mini">ناحیه: ${fnum(c.zone)}</span>
   ${c.updates?`<span class="upd">آپدیت ${c.updates}</span>`:''}</div>
  <div class="ftr"><span class="code">${fnum(c.code)}</span><span class="res PENDING">${fnum(c.status)}</span></div></div>`}
function render(){
 if(!STATE)return;
 $('#demo').style.display=STATE.demo?'block':'none';
 $('#clock').textContent=STATE.server_time||'—';
 $('#dot').style.background=(STATE.scanner&&STATE.scanner.alive)?'#1fae7c':'#e5484d';
 const chains=STATE.chains||[],feed=STATE.feed||[];
 $('#chains').innerHTML=chains.length?chains.map(chainCard).join(''):'<div class="empty">زنجیرهٔ فعالی نیست</div>';
 $('#feed').innerHTML=feed.length?feed.map(feedCard).join(''):'<div class="empty">سیگنالی ثبت نشده</div>';
 $('#chainsN').textContent=chains.length?`${chains.length} فعال`:'';
 $('#feedN').textContent=feed.length?`${feed.length} مورد آخر`:'';
 const a=STATE.analytics||{},sm=a.summary||{};
 $('#sumTiles').innerHTML=`
  <div class="tile gold"><b>${sm.total??'—'}</b><span>کل سیگنال‌ها</span></div>
  <div class="tile green"><b>${sm.wins??'—'}</b><span>برد</span></div>
  <div class="tile red"><b>${sm.losses??'—'}</b><span>باخت</span></div>
  <div class="tile gold"><b>%${sm.winrate??'—'}</b><span>وین‌ریت کل</span></div>
  <div class="tile gold"><b>${sm.avg_pnl??'—'}%</b><span>میانگین PnL</span></div>
  <div class="tile"><b>${(a.rows||[]).length}</b><span>ستاپ‌ها</span></div>`;
 $('#strats').innerHTML=(a.rows||[]).map(r=>`
  <div class="card strat">
   <div class="row1"><span class="nm">${fnum(r.fa)}</span><span class="badge">${fnum(r.name)}</span>
    <span class="chip score">★ ${r.avg_score??'—'}</span></div>
   <div class="row1"><span class="mini">${r.wins}W / ${r.losses}L / ${r.pending} باز • بهترین ${r.best??'—'}% • بدترین ${r.worst??'—'}% • ${r.last||''}</span>
    <span style="flex:1"></span><b class="${(r.avg_pnl??0)>=0?'pnlp':'pnln'}">${r.avg_pnl!==null&&r.avg_pnl!==undefined?(r.avg_pnl>0?'+':'')+r.avg_pnl+'%':'—'}</b></div>
   <div class="wr"><i style="width:${Math.max(2,Math.min(100,r.wr||0))}%"></i></div>
   <div class="mini" style="margin-top:3px">وین‌ریت ${r.wr}% از ${r.wins+r.losses} سیگنال بسته‌شده</div></div>`).join('');
 const sp=a.spot||{},fu=a.futures||{};
 $('#sf').innerHTML=`
  <div class="tile"><small>💎 اسپات</small><b style="color:#39d9a4">%${sp.wr??'—'}</b><span>${sp.wins??0}W / ${sp.losses??0}L از ${sp.total??0}</span></div>
  <div class="tile"><small>⚡ فیوچرز</small><b style="color:#4c8dff">%${fu.wr??'—'}</b><span>${fu.wins??0}W / ${fu.losses??0}L از ${fu.total??0}</span></div>`;
 renderCtrl();
 const sc=STATE.scanner||{};
 $('#botstat').innerHTML=`<span class="stat">موتور اسکن: <b>${sc.alive?'فعال ✅':'خاموش ⛔'}</b></span>
  <span class="stat">زمان سرور: <b>${STATE.server_time||'—'}</b></span>
  ${sc.mode?`<span class="stat">${sc.mode}</span>`:''}`;
}
let PEND={paused:null,setups:null};
function renderCtrl(){
 const c=(STATE&&STATE.control)||{};
 const paused=PEND.paused===null?!!c.paused:PEND.paused;
 $('#swPause').classList.toggle('on',paused);
 const sw=Object.assign({},c.setups||{});
 if(PEND.setups)Object.assign(sw,PEND.setups);
 const names=Object.keys(sw).concat(['TLBREAK','ALBROX','PINWALLQ','PINVAL','TECHCLASSIC','SPOT']);
 const uniq=[...new Set(names)];
 $('#setups').innerHTML=uniq.map(k=>`
  <div class="toggle-row"><div class="tl"><b>${k}</b><span>${sw[k]===false?'خاموش — منتشر نمی‌شود':'فعال'}</span></div>
   <div class="sw ${sw[k]===false?'':'on'}" data-k="${k}" onclick="flipSetup('${k}',this)"></div></div>`).join('');
 $('#ctrlSaved').textContent=c.updated_at?`آخرین ذخیره: ${c.updated_at}`:'';
}
function flipPause(){PEND.paused=!(PEND.paused===null?!!(STATE.control||{}).paused:PEND.paused);renderCtrl()}
function flipSetup(k,el){const cur=!(el.classList.contains('on'));PEND.setups=PEND.setups||{};
 const base=Object.assign({},(STATE.control||{}).setups||{},PEND.setups);base[k]=cur;PEND.setups=base;renderCtrl()}
async function saveCtrl(){
 const body={};
 if(PEND.paused!==null)body.paused=PEND.paused;
 if(PEND.setups)body.setups=PEND.setups;
 if(!Object.keys(body).length)return;
 const r=await fetch('/app/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(r.ok){const j=await r.json();STATE.control=j.control;PEND={paused:null,setups:null};renderCtrl();
  $('#ctrlSaved').textContent='✅ ذخیره شد — روی ربات اعمال می‌شود'}}
async function load(){
 $('#refresh').classList.add('on');
 try{const r=await fetch('/app/api/state');if(r.status===401){location.href='/app/login';return}
  STATE=await r.json();render()}catch(e){}
 setTimeout(()=>$('#refresh').classList.remove('on'),500);
}
load();setInterval(load,20000);
if('serviceWorker' in navigator){navigator.serviceWorker.register('/app/sw.js').catch(()=>{})}
</script></body></html>"""
