"""VIVA SIGNALS PRO — the mobile app (PWA) + channel-mirror + control panel.

Round-18 (Viva 09-23, after his first live review):
* «منو باید خیلی حرفه‌ای تر باشه» → slide-in drawer (Binance/TV-grade): profile
  header, iconed navigation, engine status footer, logout.
* «هر سیگنال قابل رصد باشه توی صفحه جدا … هیت شدنها اعلان بشه» → per-signal
  DETAIL page: the bot's REAL chart rendered on demand by the same engine the
  Telegram channel uses, the concise description/confirmations, the TP ladder
  progress and a full lifecycle timeline.
* «توضیحات مختصر و تایید و چارت باید با فشردن روی هر سیگنال …» → tapping any
  feed card opens that page.
* «چرا آمار کلی گذاشتی واسه ستاپهایی که دوماهه خاموش هستن» → the winrate
  board shows only setups active in the last 30 days; dead setups move to a
  clearly-labelled archive section, excluded from the headline tiles.

Round-17 laws still stand: ONE lock in front of EVERYTHING (fail-closed), the
control gate is fail-open scanner-side, demo mode only behind VIVA_APP_DEMO=1.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, make_response, redirect, request, send_file

TEHRAN = ZoneInfo("Asia/Tehran")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ICON_DIR = os.path.join(_BASE_DIR, "assets", "app_icons")
_FONT_DIR = os.path.join(_BASE_DIR, "assets", "fonts")

DEFAULT_SETUPS = ["PINVAL", "PINWALLQ", "ALBROX", "TLBREAK", "TECHCLASSIC"]
ACTIVE_WINDOW_DAYS = 1  # app is intentionally scoped to the current Tehran calendar day

def _today_start_utc() -> str:
    now = datetime.now(TEHRAN)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")

def _db_placeholder() -> str:
    try:
        from database import db as _db
        return "%s" if getattr(_db, "USE_POSTGRES", False) else "?"
    except Exception:
        return "%s"
          # «ستاپی که دوماهه خاموشه» → archive

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


def _parse_iso(iso: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _days_since(iso: str) -> Optional[float]:
    dt = _parse_iso(iso)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)


def _rel_fa(iso: str) -> str:
    days = _days_since(iso)
    if days is None:
        return ""
    mins = int(days * 1440)
    if mins < 1:
        return "همین حالا"
    if mins < 60:
        return f"{mins} دقیقه پیش"
    if mins < 1440:
        return f"{mins // 60} ساعت پیش"
    return f"{mins // 1440} روز پیش"


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


def _fmt_tehran(iso: str) -> str:
    dt = _parse_iso(iso)
    if dt is None:
        return str(iso or "")
    return dt.astimezone(TEHRAN).strftime("%m-%d • %H:%M")


def _demo_payload() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    def iso_ago(**kw):
        return (now - timedelta(**kw)).isoformat()
    feed = [
        dict(signal_id="demo-1", symbol="BTCUSDT", source="TLBREAK", strategy_fa="شکست خط روند",
             direction="LONG", entry="64,250–64,900", sl="62,180", tp1="67,400", tp2="71,200",
             result="PENDING", pnl=None, score=9, style="SWING", code="VIVA-K001204", tf="4H",
             time=iso_ago(hours=2), spot=False, confirmed=True,
             summary="کلوز ۴ساعته بالای خط روند نزولی با حجم بالا؛ هدف اول پولبک روی خط شکست.",
             tp1_hit=False, tp2_hit=False),
        dict(signal_id="demo-2", symbol="ETHUSDT", source="PINWALLQ", strategy_fa="کیفیت پی‌ن‌بار",
             direction="LONG", entry="2,738–2,754", sl="2,688", tp1="2,815", tp2="2,910",
             result="WIN", pnl=2.8, score=8, style="SWING", code="VIVA-K001187", tf="1H",
             time=iso_ago(hours=7), spot=False, confirmed=True, tp1_hit=True, tp2_hit=True,
             summary="پی‌ن‌بار بلند روی حمایت دی‌ماند با رد قوی؛ TP1 و TP2 هیت شد."),
        dict(signal_id="demo-3", symbol="SOLUSDT", source="SPOTBREAK", strategy_fa="شکست اسپات",
             direction="LONG", entry="151.2–152.4", sl="146.8", tp1="159.0", tp2="168.5",
             result="PENDING", pnl=None, score=8, style="SWING", code="VIVA-SPOT-E000318",
             tf="4H", time=iso_ago(hours=11), spot=True, confirmed=True, tp1_hit=False, tp2_hit=False,
             summary="شکست سقف الگوی پرچم صعودی در اسپات؛ ابزار لانگ/شورت ندارد."),
        dict(signal_id="demo-4", symbol="LINKUSDT", source="ALBROX", strategy_fa="البروکس",
             direction="SHORT", entry="14.85–15.05", sl="15.42", tp1="14.10", tp2="13.30",
             result="LOSS", pnl=-1.6, score=7, style="SWING", code="VIVA-K001101", tf="2H",
             time=iso_ago(days=1), spot=False, confirmed=True, tp1_hit=False, tp2_hit=False,
             summary="البروکس نزولی؛ استاپ با فاصلهٔ کم هیت شد."),
        dict(signal_id="demo-5", symbol="HYPEUSDT", source="TLBREAK", strategy_fa="شکست خط روند",
             direction="LONG", entry="38.4–39.1", sl="36.9", tp1="41.8", tp2="45.5",
             result="CANCELLED", pnl=None, score=7, style="SWING", code="VIVA-K001088", tf="1H",
             time=iso_ago(days=2), spot=False, confirmed=False, tp1_hit=False, tp2_hit=False,
             summary="شکست لفظی بود و کلوز تأییدکننده نیامد؛ سناریو بسته شد."),
    ]
    chains = [
        dict(signal_id="demo-1", symbol="BTCUSDT", badge="TLBREAK", direction="LONG",
             status="CONFIRMED", score=9, zone="64,250–64,900", updates=3,
             code="VIVA-K001204", tf="4H", spot=False),
        dict(signal_id="demo-3", symbol="SOLUSDT", badge="SPOTBREAK", direction="LONG",
             status="WATCH", score=8, zone="151.2–152.4", updates=1,
             code="VIVA-SPOT-E000318", tf="4H", spot=True),
    ]
    analytics = dict(
        rows_active=[
            dict(name="TLBREAK", fa="شکست خط روند", total=48, wins=31, losses=9, pending=8,
                 wr=77.5, avg_pnl=2.4, best=6.1, worst=-1.2, avg_score=8.2,
                 last=_rel_fa(iso_ago(hours=2)), active=True),
            dict(name="SPOTBREAK", fa="شکست اسپات", total=36, wins=24, losses=6, pending=6,
                 wr=80.0, avg_pnl=3.1, best=9.4, worst=-1.9, avg_score=8.0,
                 last=_rel_fa(iso_ago(hours=11)), active=True),
            dict(name="PINWALLQ", fa="کیفیت پی‌ن‌بار", total=27, wins=16, losses=7, pending=4,
                 wr=69.6, avg_pnl=1.7, best=5.2, worst=-1.4, avg_score=7.6,
                 last=_rel_fa(iso_ago(days=1)), active=True),
        ],
        rows_archive=[
            dict(name="ALBROX", fa="البروکس", total=22, wins=11, losses=8, pending=3,
                 wr=57.9, avg_pnl=0.9, best=4.0, worst=-2.1, avg_score=7.2,
                 last=_rel_fa(iso_ago(days=48)), active=False),
            dict(name="PINVAL", fa="اعتبارسنجی پی‌ن", total=18, wins=9, losses=6, pending=3,
                 wr=60.0, avg_pnl=1.1, best=4.6, worst=-1.8, avg_score=7.4,
                 last=_rel_fa(iso_ago(days=64)), active=False),
        ],
        spot=dict(wr=80.0, wins=24, losses=6, total=36),
        futures=dict(wr=71.4, wins=70, losses=28, total=125),
        summary=dict(total=133, wins=85, losses=30, winrate=73.9, avg_pnl=2.2),
    )
    hits = [
        dict(kind="tp2", symbol="ETHUSDT", code="VIVA-K001187", detail="هدف دوم 2,910 هیت شد",
             pnl=2.8, time=iso_ago(hours=6)),
        dict(kind="confirm", symbol="SOLUSDT", code="VIVA-SPOT-E000318",
             detail="تأیید شکست اسپات روی کلوز ۴ساعته", pnl=None, time=iso_ago(hours=11)),
        dict(kind="sl", symbol="LINKUSDT", code="VIVA-K001101", detail="استاپ 15.42 هیت شد",
             pnl=-1.6, time=iso_ago(days=1)),
        dict(kind="tp1", symbol="BTCUSDT", code="VIVA-K001204", detail="هدف اول 67,400 هیت شد",
             pnl=None, time=iso_ago(hours=1)),
    ]
    return dict(demo=True, feed=feed, chains=chains, live_positions=chains, analytics=analytics, hits=hits,
                results=dict(rows=[], usd_total=0, usd_win=0, usd_loss=0),
                control=control_state(), scanner=dict(alive=True, mode="نمایشی"),
                server_time=datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M"))


_FEED_SQL = """
    SELECT signal_id, symbol, source, strategy_fa, direction, entry, sl, tp1, tp2,
           result, pnl_pct, score, trade_style, public_code, trigger_timeframe,
           created_at, closed_at, confirmed, partial_win, market_json,
           tp1_hit, tp1_hit_at, sl_moved_to_be, description, entry_conditions,
           confirmations, setup_code, target_state_json, leverage, margin_usd
    FROM signals
    WHERE created_at >= {cutoff}
    ORDER BY created_at DESC
    LIMIT 120
"""


def _row_is_spot(code: str, source: Any, market_json: Any) -> bool:
    mkt = str(market_json or "")
    return (str(code or "").startswith("VIVA-SPOT-")
            or str(source or "") == "SPOTBREAK"
            or '"SPOT"' in mkt or "'SPOT'" in mkt)


def _ladder_hits(target_state_json: Any) -> tuple[bool, bool]:
    """(tp1_hit, tp2_hit) از نردبان ذخیره‌شده — tolerant to schema drift."""
    try:
        lad = json.loads(target_state_json or "{}") if isinstance(target_state_json, (str, bytes)) \
            else (target_state_json or {})
        ts = lad.get("targets") or []
        def _hit(t):
            return bool(t.get("hit") or t.get("hit_at") or t.get("filled"))
        h1 = _hit(ts[0]) if len(ts) > 0 else False
        h2 = _hit(ts[1]) if len(ts) > 1 else False
        return h1, h2
    except Exception:
        return False, False


def _ladder_view(target_state_json: Any) -> Dict[str, Any]:
    """r41 — the publish-time ladder state VERBATIM for the app cards:
    targets (floats), hit flags (hit_index OR per-pill flags), the TRAILING
    stop (current_sl) and whether it has ratcheted off the original."""
    out: Dict[str, Any] = {"targets": [], "hit_index": 0, "current_sl": None,
                           "sl_moved": False}
    try:
        lad = json.loads(target_state_json or "{}") if isinstance(target_state_json, (str, bytes)) \
            else (target_state_json or {})
        if not isinstance(lad, dict):
            return out
        vals: List[float] = []
        for _t in (lad.get("targets") or [])[:5]:
            _v = _t.get("price") if isinstance(_t, dict) else _t
            try:
                _f = float(_v)
                if math.isfinite(_f) and _f > 0:
                    vals.append(_f)
            except Exception:
                continue
        out["targets"] = vals
        out["hit_index"] = int(lad.get("hit_index") or 0)
        try:
            _cur = float(lad.get("current_sl") or 0)
            _org = float(lad.get("original_sl") or 0)
            if _cur > 0:
                out["current_sl"] = _cur
                out["sl_moved"] = bool(_org > 0 and abs(_cur - _org) > 1e-12)
        except Exception:
            pass
    except Exception:
        pass
    return out


def _fetch_state() -> Dict[str, Any]:
    """r29d SERVE-WHILE-REVALIDATE — «اپلیکیشن هنوز بالا نمیاد».

    The old 8s snapshot cache rebuilt state INLINE on every miss, and one
    rebuild costs ~60s on Railway — every poll past the TTL spun the browser
    for a minute. Now: a fresh snapshot answers instantly; a STALE snapshot
    answers INSTANTLY while one background thread rebuilds (at most one
    concurrent rebuild — duplicate tabs no longer multiply DB/CPU work).
    Cold boot still builds once inline (there is nothing to serve yet)."""
    global _STATE_CACHE, _STATE_REBUILDING
    if _demo_mode():
        return _demo_payload()
    _now = time.monotonic()
    if _STATE_CACHE["state"] is not None and _now - _STATE_CACHE["at"] < 8.0:
        return _STATE_CACHE["state"]
    if _STATE_CACHE["state"] is not None:
        if not _STATE_REBUILDING["flag"]:
            _STATE_REBUILDING["flag"] = True

            def _bg_rebuild():
                try:
                    _rebuild_state()
                except Exception as _exc:
                    print(f"state bg rebuild failed: {_exc}")
                finally:
                    _STATE_REBUILDING["flag"] = False

            threading.Thread(target=_bg_rebuild, daemon=True).start()
        return _STATE_CACHE["state"]
    return _rebuild_state()


def _rebuild_state() -> Dict[str, Any]:
    # Short server-side snapshot cache: the dashboard polls frequently, but the
    # underlying state is DB-heavy. This keeps refresh responsiveness while
    # preventing duplicate full DB snapshots across tabs/clients.
    global _STATE_CACHE
    if _demo_mode():
        return _demo_payload()
    try:
        from database.db import db_cursor, get_dashboard_summary
        summary = get_dashboard_summary() or {}
        feed: List[Dict[str, Any]] = []
        spot = dict(wins=0, losses=0, total=0)
        fut = dict(wins=0, losses=0, total=0)
        rows_active: List[Dict[str, Any]] = []
        rows_archive: List[Dict[str, Any]] = []
        hits: List[Dict[str, Any]] = []
        with db_cursor() as c:
            _cutoff = _today_start_utc()
            c.execute(_FEED_SQL.format(cutoff=_db_placeholder()), (_cutoff,))
            for r in c.fetchall():
                (sid, symbol, source, fa, direction, entry, sl, tp1, tp2, result, pnl, score,
                 style, code, tf, created_at, closed_at, confirmed, partial_win, market_json,
                 tp1_hit, tp1_hit_at, sl_moved, description, entry_conditions, confirmations,
                 setup_code, target_state_json, leverage, margin_usd) = r
                code = str(code or "")
                is_spot = _row_is_spot(code, source, market_json)
                try:
                    _market_obj_feed = json.loads(market_json or "{}") if isinstance(market_json, (str, bytes)) else (market_json or {})
                except Exception:
                    _market_obj_feed = {}
                _mi_feed = _market_obj_feed.get("market_intelligence") or {}
                res = "WIN" if result == "WIN" else str(result or "PENDING")
                _acc = spot if is_spot else fut
                _acc["total"] += 1
                if res == "WIN":
                    _acc["wins"] += 1
                elif res == "LOSS":
                    _acc["losses"] += 1
                lh1, lh2 = _ladder_hits(target_state_json)
                _lv41 = _ladder_view(target_state_json)
                tp1_hit = bool(tp1_hit or lh1 or _lv41["hit_index"] >= 1)
                tp2_hit = bool(lh2 or _lv41["hit_index"] >= 2)
                tp3_hit = bool(_lv41["hit_index"] >= 3)
                feed.append(dict(
                    signal_id=str(sid or ""), symbol=symbol, source=source, strategy_fa=fa,
                    direction=direction, entry=_fmt_price(entry), sl=_fmt_price(sl),
                    tp1=_fmt_price(tp1), tp2=_fmt_price(tp2), result=res,
                    pnl=(float(pnl) if pnl is not None else None), score=score,
                    style=style, code=code, tf=str(tf or "").upper(),
                    time=str(created_at or ""), spot=is_spot, confirmed=bool(confirmed),
                    tp1_hit=tp1_hit, tp2_hit=tp2_hit, tp3_hit=tp3_hit, partial_win=bool(partial_win),
                    # r41 REAL-LIVE cards: the ladder's OWN targets (incl. TP3),
                    # the trailing stop and whether it ratcheted — verbatim.
                    ladder_targets=_lv41["targets"],
                    current_sl=(_fmt_price(_lv41["current_sl"])
                                if _lv41["current_sl"] else None),
                    sl_moved=_lv41["sl_moved"],
                    market_intelligence=_mi_feed,
                    summary=str(description or fa or "")[:220],
                    telegram_text="",
                    leverage=int(leverage or 0),
                    margin=float(margin_usd or 0),
                    # r34 (Viva: «سود زیان باید به‌ازای لوریج اعلام بشه») —
                    # price move %, margin move % (= price × lev) and the
                    # dollar PnL on the trade's own margin.
                    pnl_lev=(round(float(pnl) * float(leverage or 0), 2)
                             if pnl is not None else None),
                    pnl_usd=(round(float(margin_usd or 0) * float(pnl or 0)
                                   * float(leverage or 0) / 100.0, 2)
                             if pnl is not None else None),
                ))
                try:
                    from database.bot_kv import get_json as _app_gj
                    _am = _app_gj(f"app_msg|{sid}|update", {}) or _app_gj(f"app_msg|{sid}|compact", {}) or {}
                    feed[-1]["telegram_text"] = str(_am.get("html") or "")
                except Exception:
                    pass
            # App is a same-day journal: headline totals are derived from the
            # exact feed shown above, never from the historical dashboard aggregate.
            _closed_feed = [x for x in feed if x.get("result") in ("WIN", "LOSS")]
            _wins = sum(1 for x in _closed_feed if x.get("result") == "WIN")
            _losses = sum(1 for x in _closed_feed if x.get("result") == "LOSS")
            _pnl_vals = [float(x.get("pnl") or 0) for x in _closed_feed]
            summary = dict(
                total_signals=len(feed), wins=_wins, losses=_losses,
                pending=sum(1 for x in feed if x.get("result") == "PENDING"),
                winrate=round(_wins * 100.0 / max(1, _wins + _losses), 1),
                avg_pnl=round(sum(_pnl_vals) / len(_pnl_vals), 2) if _pnl_vals else 0.0,
            )

            # ── winrate per setup: current day only
            c.execute(f"""
                SELECT source, MAX(strategy_fa) AS fa, COUNT(*) AS total,
                       SUM(CASE WHEN (result='WIN' OR partial_win=TRUE) THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
                       SUM(CASE WHEN result='PENDING' THEN 1 ELSE 0 END) AS pending,
                       AVG(CASE WHEN result IN ('WIN','LOSS') THEN pnl_pct END) AS avg_pnl,
                       AVG(CASE WHEN result='WIN' THEN pnl_pct END) AS avg_win,
                       AVG(CASE WHEN result='LOSS' THEN pnl_pct END) AS avg_loss,
                       MAX(CASE WHEN result IN ('WIN','LOSS') THEN pnl_pct END) AS best,
                       MIN(CASE WHEN result IN ('WIN','LOSS') THEN pnl_pct END) AS worst,
                       AVG(score) AS avg_score, MAX(created_at) AS last
                FROM signals
                WHERE created_at >= {_db_placeholder()}
                GROUP BY source
                ORDER BY MAX(created_at) DESC
            """, (_today_start_utc(),))
            for r in c.fetchall():
                (name, fa, total, wins, losses, pending, avg_pnl, avg_win, avg_loss, best, worst, avg_score, last) = r
                total, wins, losses = int(total or 0), int(wins or 0), int(losses or 0)
                closed = wins + losses
                last_iso = str(last or "")
                days = _days_since(last_iso)
                active = days is not None and days <= ACTIVE_WINDOW_DAYS
                row = dict(
                    name=str(name or "?"), fa=str(fa or name or "?"), total=total,
                    wins=wins, losses=losses, pending=int(pending or 0),
                    wr=(round(wins * 100.0 / closed, 1) if closed else 0.0),
                    avg_pnl=(round(float(avg_pnl), 2) if avg_pnl is not None else None),
                    avg_win=(round(float(avg_win), 2) if avg_win is not None else None),
                    avg_loss=(round(float(avg_loss), 2) if avg_loss is not None else None),
                    best=(round(float(best), 2) if best is not None else None),
                    worst=(round(float(worst), 2) if worst is not None else None),
                    avg_score=(round(float(avg_score), 1) if avg_score is not None else None),
                    last=_rel_fa(last_iso), active=active,
                )
                (rows_active if active else rows_archive).append(row)
            # Keep all five production futures lanes visible even when one has no
            # signal today; this is observability, not a ranking.
            _known = {str(x["name"]).upper() for x in rows_active}
            for _setup in DEFAULT_SETUPS:
                if _setup not in _known:
                    rows_active.append(dict(name=_setup, fa=_setup, total=0, wins=0, losses=0,
                                            pending=0, wr=0.0, avg_pnl=None, avg_win=None, avg_loss=None, best=None,
                                            worst=None, avg_score=None, last="امروز بدون سیگنال", active=True))
            # ── hit notifications (TP/SL/close/confirm lifecycle feed)
            c.execute(f"""
                SELECT symbol, public_code, tp1_hit_at, closed_at, result, pnl_pct,
                       created_at, confirmed_at, partial_win, tp1, tp2, sl
                FROM signals
                WHERE created_at >= {_db_placeholder()} AND (
                       tp1_hit=TRUE OR result IN ('WIN','LOSS')
                       OR (confirmed=TRUE AND result='PENDING')
                   )
                ORDER BY COALESCE(closed_at, tp1_hit_at, confirmed_at, created_at) DESC
                LIMIT 80
            """, (_today_start_utc(),))
            for r in c.fetchall():
                (symbol, code, tp1_at, closed_at, result, pnl, created_at, confirmed_at,
                 partial_win, tp1, tp2, sl) = r
                res = "WIN" if (result == "WIN" or partial_win) else str(result or "PENDING")
                if closed_at and res in ("WIN", "LOSS"):
                    kind = "win" if res == "WIN" else "loss"
                    stamp = closed_at
                    detail = f"معامله بسته شد — نتیجهٔ نهایی {res}"
                elif tp1_at:
                    kind = "tp1"
                    stamp = tp1_at
                    detail = f"هدف اول {_fmt_price(tp1)} هیت شد"
                elif confirmed_at:
                    kind = "confirm"
                    stamp = confirmed_at
                    detail = "تأیید روی کلوز کندل ثبت شد"
                else:
                    continue
                hits.append(dict(kind=kind, symbol=symbol, code=str(code or ""),
                                 detail=detail,
                                 pnl=(float(pnl) if pnl is not None else None),
                                 time=str(stamp or "")))
        chains: List[Dict[str, Any]] = []
        live_positions: List[Dict[str, Any]] = []
        try:
            # live WATCH chains ( EDUCATIONAL/APPROACHING previews + slots )
            from database.candidate_store import get_active_candidates
            for cand in (get_active_candidates() or [])[:24]:
                md = getattr(cand, "metadata", None) or {}
                code = str(md.get("public_code") or "")
                chains.append(dict(
                    signal_id=getattr(cand, "signal_id", ""),
                    symbol=cand.symbol, badge=str(getattr(cand, "setup_code", "") or ""),
                    direction=getattr(cand, "direction", ""), status=str(getattr(cand, "status", "") or ""),
                    score=getattr(cand, "score", 0),
                    zone=f"{_fmt_price(getattr(cand, 'entry_zone_bottom', 0))}–{_fmt_price(getattr(cand, 'entry_zone_top', 0))}",
                    updates=int(md.get("update_count") or 0), code=code,
                    tf=str(getattr(cand, "trigger_timeframe", "") or "").upper(),
                    spot=code.startswith("VIVA-SPOT-") or str(getattr(cand, "source", "")) == "SPOTBREAK",
                ))
        except Exception:
            pass
        # live POSITIONS (confirmed, still running) on top of the chains list
        try:
            with db_cursor() as c2:
                c2.execute(f"""
                    SELECT signal_id, symbol, source, direction, entry, sl, score,
                           public_code, trigger_timeframe, created_at
                    FROM signals
                    WHERE created_at >= {_db_placeholder()} AND confirmed=TRUE AND result='PENDING' AND closed_at IS NULL
                    ORDER BY created_at DESC LIMIT 12
                """, (_today_start_utc(),))
                for r in c2.fetchall():
                    (sid, symbol, source, direction, entry, sl, score, code, tf, created_at, tp1, tp2, leverage, margin, target_state) = r
                    code = str(code or "")
                    live_positions.append(dict(
                        signal_id=str(sid or ""), symbol=symbol, badge=str(source or ""),
                        direction=direction, status="CONFIRMED", score=score,
                        zone=_fmt_price(entry), updates=0, code=code,
                        tf=str(tf or "").upper(),
                        spot=_row_is_spot(code, source, ""),
                        tp1=_fmt_price(tp1), tp2=_fmt_price(tp2), leverage=int(leverage or 0),
                        margin=float(margin or 0), target_state=target_state or "{}",
                    ))
        except Exception:
            pass
        wr = lambda a: (round(a["wins"] * 100.0 / max(1, a["wins"] + a["losses"]), 1))
        spot["wr"], fut["wr"] = wr(spot), wr(fut)
        analytics = dict(rows_active=rows_active, rows_archive=rows_archive,
                         spot=spot, futures=fut, summary=dict(
            total=int(summary.get("total_signals") or 0), wins=int(summary.get("wins") or 0),
            losses=int(summary.get("losses") or 0), winrate=float(summary.get("winrate") or 0.0),
            avg_pnl=float(summary.get("avg_pnl") or 0.0),
        ))
        scanner = dict(alive=True, mode="")
        # r34: the RESULTS CONTROL board — same-day closed trades with the
        # leverage-adjusted PnL the user asked to steer by.
        _crows = [x for x in feed if x.get("result") in ("WIN", "LOSS")]
        _usd = [(x, float(x.get("pnl_usd") or 0)) for x in _crows]
        results = dict(
            rows=_crows,
            usd_total=round(sum(u for _, u in _usd), 2),
            usd_win=round(sum(u for x, u in _usd if x["result"] == "WIN"), 2),
            usd_loss=round(sum(u for x, u in _usd if x["result"] == "LOSS"), 2),
        )
        # ── Viva 09-23/24 («چرا اسپات رو فعال نمیکنی؟؟»): the spot lane's
        # real state is visible in the app — reason + last pass, from KV.
        try:
            from database.bot_kv import get_json as _gj
            _spot = _gj("spot_lane_status", {}) or {}
            _st = (_spot.get("stats") or {})
            _rs = str(_spot.get("reason") or "")
            _fa = {"ok": "فعال", "zero_sent": "فعال — اما ارسال صفر! (گزارش: " + str(_st.get("last_error") or "?")[:60] + ")",
                   "no_spot_channel": "بدون کانال اسپوت (CHAT_ID_SPOT تنظیم نشده)",
                   "disabled": "خاموش", "import_failed": "خطای ایمپورت"}.get(
                _rs, ("خطا" if _rs.startswith("import_failed") else (_rs or "هنوز پاس نگرفته")))
            scanner["spot"] = dict(
                state=_fa, at=str(_spot.get("at") or ""),
                symbols=int(_st.get("symbols") or 0), found=int(_st.get("found") or 0),
                published=int(_st.get("published") or 0),
                errors=int(_st.get("errors") or 0), alerts=int(_st.get("alerts") or 0),
                stamp_skip=int(_st.get("stamp_skip") or 0),
                send_fail=int(_st.get("send_fail") or 0),
                chart_fail=int(_st.get("chart_fail") or 0),
                dur_s=_st.get("dur_s") or "", last_error=str(_st.get("last_error") or "")[:120])
        except Exception:
            pass
        try:
            from flask import current_app
            thr = current_app.config.get("VIVA_SCANNER_THREAD")
            if thr is not None:
                scanner["alive"] = bool(thr.is_alive())
        except Exception:
            pass
        payload = dict(demo=False, feed=feed, chains=chains, live_positions=live_positions, analytics=analytics, hits=hits,
                       results=results,
                       control=control_state(), scanner=scanner,
                       server_time=datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M"))
        # r29e: the discovery funnel (R31.1) is READABLE from the dashboard —
        # «تا از قسمت داشبورد بتونم کنترل کنم نتایج رو»: which gate swallows
        # candidates per cycle (dead_gate/quiet/liccap/low_score/...).
        try:
            from database.bot_kv import get_json as _gj9
            payload["funnel"] = _gj9("scan_summary", {}) or {}
        except Exception:
            payload["funnel"] = {}
        _STATE_CACHE.update(state=payload, at=time.monotonic())
        return payload
    except Exception as exc:
        payload = _demo_payload()
        payload["db_error"] = str(exc)[:120]
        return payload


# ─────────────────────── per-signal detail + chart ───────────────────────
_EVENT_FA = {
    "initial_alert": "هشدار اولیه", "detailed_alert": "هشدار تفصیلی",
    "confirm": "تأیید ورود", "confirmation": "تأیید ورود", "update": "به‌روزرسانی رصد",
    "tp1": "برخورد هدف اول", "tp2": "برخورد هدف دوم", "stop": "استاپ",
    "close": "بستن معامله", "cancel": "ابطال سناریو", "educational": "پیش‌نمایش آموزشی",
}


def _event_fa(key: str) -> str:
    k = str(key or "").lower()
    for frag, fa in _EVENT_FA.items():
        if frag in k:
            return fa
    return str(key or "رویداد")


def _candidate_from_row(row: dict) -> Any:
    """Rebuild the renderer's candidate from a `signals` row (live chart).
    r41 (Viva 09-26, «چرا نردبان اپ با تلگرام فرق داره؟ دقیقاً از دیتای
    تلگرام استفاده کنه»): the render fallback used to rebuild a FAKE
    two-pill ladder from the raw tp1/tp2 columns — different pills, different
    zoom from the channel chart. The publish-time build_ladder state is
    stored on the row (target_state_json): its targets/weights/entry/
    original_sl ARE the Telegram tool — restore them VERBATIM; the real
    entry-zone columns replace the ±0.1% synthetic zone."""
    from analysis.models import SignalCandidate
    is_spot = _row_is_spot(str(row.get("public_code") or ""), row.get("source"), row.get("market_json"))
    # publish-time ladder state (the tool Telegram drew)
    try:
        _tsj = row.get("target_state_json")
        _lad41 = json.loads(_tsj) if isinstance(_tsj, (str, bytes)) else (_tsj or {})
    except Exception:
        _lad41 = {}
    if not isinstance(_lad41, dict):
        _lad41 = {}
    try:
        _ltargets = [float(v) for v in (_lad41.get("targets") or [])
                     if v is not None and math.isfinite(float(v)) and float(v) > 0]
    except Exception:
        _ltargets = []
    try:
        _lweights = [float(w) for w in (_lad41.get("weights") or []) if w is not None]
    except Exception:
        _lweights = []
    _lentry = float(_lad41.get("entry") or 0)
    _lsl = float(_lad41.get("original_sl") or 0)
    entry = _lentry if _lentry > 0 else float(row.get("entry") or 0)
    sl = _lsl if _lsl > 0 else float(row.get("sl") or 0)
    tp1 = float(row.get("tp1") or 0)
    tp2 = float(row.get("tp2") or entry * 1.02)
    def _rr(t: float) -> float:
        try:
            return round(abs(t - entry) / max(1e-12, abs(entry - sl)), 2)
        except Exception:
            return 0.0
    if _ltargets:
        ladder_md = {"targets": _ltargets,
                     "weights": _lweights or [40.0, 30.0, 30.0][:len(_ltargets)]}
    else:
        ladder_md = {"targets": [tp1, tp2], "weights": [40, 30, 30]}
    md = {
        "public_code": str(row.get("public_code") or ""),
        "market": "SPOT" if is_spot else "FUTURES",
        "target_ladder": ladder_md,
        "tool_entry_ts": str(row.get("confirmed_at") or row.get("created_at") or ""),
        "confirm_tf": str(row.get("trigger_timeframe") or ""),
    }
    try:
        _ezb = float(row.get("entry_zone_bottom") or 0)
        _ezt = float(row.get("entry_zone_top") or 0)
    except Exception:
        _ezb = _ezt = 0.0
    if not (_ezb > 0 and _ezt > _ezb):
        _ezb, _ezt = entry * 0.999, entry * 1.001
    return SignalCandidate(
        signal_id=str(row.get("signal_id") or ""), symbol=str(row.get("symbol") or ""),
        style=str(row.get("trade_style") or "SWING"),
        setup_code=str(row.get("setup_code") or row.get("source") or ""),
        setup_name=str(row.get("setup_code") or row.get("source") or ""),
        strategy_fa=str(row.get("strategy_fa") or ""), direction=str(row.get("direction") or "LONG"),
        score=int(row.get("score") or 0), status="CONFIRMED" if row.get("confirmed") else "WATCH",
        entry_zone_bottom=_ezb, entry_zone_top=_ezt, planned_entry=entry,
        sl=sl, tp1=tp1, tp2=tp2, rr_tp1=_rr(tp1), rr_tp2=_rr(tp2),
        bias="BULL" if str(row.get("direction")) == "LONG" else "BEAR",
        trigger_timeframe=str(row.get("trigger_timeframe") or "4h"),
        evidence=[], confirmations=[], warnings=[], mandatory_gates={},
        market={"asset_class": "CRYPTO", "venue": "BYBIT"}, metadata=md,
        created_at=str(row.get("created_at") or ""),
        confirmed_at=str(row.get("confirmed_at") or ""),
    )


_CHART_CACHE: Dict[str, Any] = {}  # sid -> (png, monotonic); bounded below


_TG_IMG_CACHE: Dict[str, Any] = {}   # file_id → (bytes, monotonic)


def _app_mirror(sid: str, kind: str) -> Optional[Dict[str, Any]]:
    try:
        from database.bot_kv import get_json
        return get_json(f"app_chart|{sid}" if kind == "chart" else f"app_msg|{sid}|{kind}", {}) or None
    except Exception:
        return None


def _tg_file_bytes(file_id: str) -> Optional[bytes]:
    """The bot's ALREADY-SENT chart, from Telegram's own CDN (Viva 09-23:
    «از همون چارت‌های ساخته‌شده برای ربات تلگرام استفاده کن») — one getFile +
    one download, ZERO renderer CPU. 30-minute in-process cache."""
    hit = _TG_IMG_CACHE.get(file_id)
    now = time.monotonic()
    if hit and now - hit[1] < 1800:
        return hit[0]
    try:
        import os as _os
        import urllib.request
        import urllib.parse
        token = (_os.getenv("TELEGRAM_TOKEN") or "").strip()
        if not token:
            return None
        q = urllib.parse.urlencode({"file_id": file_id})
        with urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/getFile?{q}", timeout=10) as r:
            import json as _json
            path = str(((_json.loads(r.read()) or {}).get("result") or {}).get("path") or "")
        if not path:
            return None
        with urllib.request.urlopen(
                f"https://api.telegram.org/file/bot{token}/{path}", timeout=25) as r:
            data = r.read()
        if data[:4] == b"\x89PNG" and len(data) > 1000:
            if len(_TG_IMG_CACHE) > 80:
                _TG_IMG_CACHE.clear()
            _TG_IMG_CACHE[file_id] = (data, now)
            return data
    except Exception as exc:
        print(f"app telegram chart fetch failed: {exc}")
    return None


def _signal_chart_png(sid: str) -> Optional[bytes]:
    """The chart the CHANNEL already sent (mirror); renderer only as fallback."""
    if _demo_mode():
        return _demo_chart_png()
    now = time.monotonic()
    # Telegram mirror is authoritative. Check it BEFORE the render cache so a
    # fallback render created a moment earlier can never hide the exact
    # Telegram image for the next 90 seconds.
    try:
        mirror = _app_mirror(sid, "chart") or {}
        fid = str(mirror.get("fid") or "")
        if fid:
            data = _tg_file_bytes(fid)
            if data:
                if len(_CHART_CACHE) >= 48:
                    _CHART_CACHE.pop(next(iter(_CHART_CACHE)))
                _CHART_CACHE[sid] = (data, now)
                return data
    except Exception:
        pass
    hit = _CHART_CACHE.get(sid)
    if hit and now - hit[1] < 1800:
        return hit[0]
    # r39 (Viva 09-26, «عکس چارتم فقط برای تایید باید بیاد که اونهم نمیاد»):
    # MIRROR-ONLY starved the app — every signal whose Telegram file_id
    # mirror missed (pending rows, spot cards, older chains) 404-ed forever.
    # The renderer is identity-faithful now (r33 render_identity + zoom_freeze
    # live in KV per signal_id), so the dashboard re-render reproduces the
    # channel's own picture. Bounded: mirror first, render once per sid,
    # 30-minute cache, the SAME cached tape the bot drew from.
    try:
        from database.db import db_cursor
        _cols39 = ["signal_id", "symbol", "source", "public_code", "market_json",
                   "direction", "entry", "sl", "tp1", "tp2", "score", "confirmed",
                   "trigger_timeframe", "trade_style", "setup_code",
                   "created_at", "confirmed_at", "strategy_fa",
                   "target_state_json", "entry_zone_bottom", "entry_zone_top"]
        with db_cursor() as c39:
            c39.execute(f"SELECT {', '.join(_cols39)} FROM signals WHERE signal_id=%s", (sid,))
            _r39 = c39.fetchone()
        if _r39:
            _row39 = dict(zip(_cols39, _r39))
            _cand39 = _candidate_from_row(_row39)
            _md39 = _cand39.metadata if isinstance(_cand39.metadata, dict) else {}
            _is_spot39 = str(_md39.get("market") or "").upper() == "SPOT"
            if _is_spot39:
                _md39.update({"log_scale": True, "spot_measured_box": True, "engine": "SPOT"})
            _tf39 = (str(_md39.get("confirm_tf") or _row39.get("trigger_timeframe") or "4h")
                     .lower())
            _md39["chart_view_tf"] = _tf39
            _cand39.metadata = _md39
            from data.fetcher import get_klines
            _df39 = get_klines(str(_row39.get("symbol") or ""), _tf39, 190,
                               closed_only=False, use_cache=True)
            if _df39 is not None and not getattr(_df39, "empty", True):
                from bot.messages_v7 import generate_chart
                _png39 = generate_chart(_df39, _cand39,
                                        confirmed=bool(_row39.get("confirmed")))
                if _png39:
                    if len(_CHART_CACHE) >= 48:
                        _CHART_CACHE.pop(next(iter(_CHART_CACHE)))
                    _CHART_CACHE[sid] = (_png39, now)
                    return _png39
    except Exception as _exc:
        print(f"chart fallback render failed {sid}: {_exc}")
    return None



def _demo_chart_png() -> Optional[bytes]:
    import pandas as pd
    import numpy as np
    n = 150
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="4h")
    rng = np.random.RandomState(11)
    close = np.concatenate([np.linspace(70, 100, n // 2), 100 + np.cumsum(rng.randn(n - n // 2) * 1.5)])
    df = pd.DataFrame({"timestamp": idx, "open": close + rng.randn(n) * 0.4,
                       "high": close + abs(rng.randn(n)) * 1.5 + 0.6,
                       "low": close - abs(rng.randn(n)) * 1.5 - 0.6, "close": close,
                       "volume": rng.rand(n) * 1_500_000 + 200_000})
    from analysis.models import SignalCandidate
    md = {"target_ladder": {"targets": [close[-1] * 1.02, close[-1] * 1.06], "weights": [40, 30, 30]},
          "tool_entry_ts": str(idx[-1]),
          "render_zones": [{"x0": n - 30, "x1": n - 8, "bottom": close[-1] - 3, "top": close[-1] - 1,
                            "poi_type": "DEMAND", "label": "DEMAND · POI / ENTRY"}]}
    cand = SignalCandidate(signal_id="demo", symbol="DEMOUSDT", style="SWING", setup_code="TLBREAK",
                           setup_name="تست", strategy_fa="نمایشی", direction="LONG", score=8,
                           status="CONFIRMED", entry_zone_bottom=close[-1] - 3,
                           entry_zone_top=close[-1] - 1, planned_entry=float(close[-1]),
                           sl=float(close[-1] * 0.97), tp1=float(close[-1] * 1.02),
                           tp2=float(close[-1] * 1.06), rr_tp1=1.0, rr_tp2=2.0, bias="BULL",
                           trigger_timeframe="4h", mandatory_gates={},
                           market={"asset_class": "CRYPTO", "venue": "BYBIT"}, metadata=md,
                           created_at=str(idx[-1]), confirmed_at=str(idx[-1]))
    try:
        from bot.messages_v7 import generate_chart
        return generate_chart(df, cand, confirmed=True)
    except Exception:
        return None


def _signal_detail(sid: str) -> Optional[Dict[str, Any]]:
    if _demo_mode():
        demo = next((f for f in _demo_payload()["feed"] if f["signal_id"] == sid), None)
        base = demo or _demo_payload()["feed"][0]
        base = dict(base)
        base.update(dict(
            messages={
                "compact": "🎯 <b>VIVA ✦ TLBREAK</b> — DEMOUSDT خرید\nکلوز بالای خط روند نزولی؛ ابزار لانگ فعال شد.",
                "confirmed": "✅ <b>تأیید ورود</b>\n📊 جدول مدیریت سرمایه:\n• ورود: همان ناحیه\n• حجم: 1-2٪ ریسک\n• استاپ: پشت بیس",
            },
            hit_log=[dict(label="TP1", ok=True, time=base.get("time", ""))],
            created_at=base.get("time", ""), confirmed_at=base.get("time", ""),
            closed_at=(base.get("time") if base.get("result") in ("WIN", "LOSS") else ""),
            entry_conditions="شرط ورود: کلوز کندلِ تایم‌فریم بالای سطح شکست + حجم بالاتر از میانگین ۲۰.",
            confirmations=["کلوز تأییدکننده بالای خط روند", "حجم بالای میانگین", "RSI > 50"],
            timeline=[
                dict(fa="هشدار تفصیلی", time=base.get("time", "")),
                dict(fa="تأیید ورود", time=base.get("time", "")),
                dict(fa="به‌روزرسانی رصد", time=base.get("time", "")),
            ],
            ladder=[dict(price=base.get("tp1", ""), hit=bool(base.get("tp1_hit"))),
                    dict(price=base.get("tp2", ""), hit=bool(base.get("tp2_hit")))],
        ))
        return base
    try:
        from database.db import db_cursor
        with db_cursor() as c:
            c.execute("""
                SELECT signal_id, symbol, source, strategy_fa, direction, entry, sl, tp1, tp2,
                       result, pnl_pct, score, trade_style, public_code, trigger_timeframe,
                       created_at, closed_at, confirmed, partial_win, market_json,
                       tp1_hit, tp1_hit_at, sl_moved_to_be, description, entry_conditions,
                       confirmations, setup_code, target_state_json, leverage, margin_usd
                FROM signals WHERE signal_id=%s
            """, (sid,))
            rows = c.fetchall()
            timeline: List[Dict[str, str]] = []
            try:
                c.execute("""
                    SELECT event_key, created_at FROM signal_telegram_events
                    WHERE signal_id=%s ORDER BY created_at ASC LIMIT 30
                """, (sid,))
                timeline = [dict(fa=_event_fa(r[0]), time=str(r[1] or "")) for r in c.fetchall()]
            except Exception:
                pass
        if not rows:
            return None
        cols = ["signal_id", "symbol", "source", "strategy_fa", "direction", "entry", "sl",
                "tp1", "tp2", "result", "pnl_pct", "score", "trade_style", "public_code",
                "trigger_timeframe", "created_at", "closed_at", "confirmed", "partial_win",
                "market_json", "tp1_hit", "tp1_hit_at", "sl_moved_to_be", "description",
                "entry_conditions", "confirmations", "setup_code", "target_state_json", "leverage", "margin_usd"]
        row = dict(zip(cols, rows[0]))
        res = "WIN" if (row.get("result") == "WIN" or row.get("partial_win")) else str(row.get("result") or "PENDING")
        lh1, lh2 = _ladder_hits(row.get("target_state_json"))
        try:
            conf = json.loads(row.get("confirmations") or "[]")
            if not isinstance(conf, list):
                conf = [str(conf)]
        except Exception:
            conf = [str(row.get("confirmations") or "")] if row.get("confirmations") else []
        is_spot = _row_is_spot(str(row.get("public_code") or ""), row.get("source"), row.get("market_json"))
        try:
            _market_obj = json.loads(row.get("market_json") or "{}") if isinstance(row.get("market_json"), (str, bytes)) else (row.get("market_json") or {})
        except Exception:
            _market_obj = {}
        _analysis_obj = _market_obj.get("viva_analysis") or {}
        _market_intelligence = _market_obj.get("market_intelligence") or {}
        _mtf_candles = _analysis_obj.get("mtf_candles") or {}
        _classic_patterns = _analysis_obj.get("classic_patterns") or []
        # ── hit log with CLOCK (Viva 09-23: «هیت شدن‌ها با تیک و ساعت هیت شدن؛
        # استاپ‌ها هم همین») — TP1/TP2/SL each carry its exact stamp.
        hit_log: List[Dict[str, Any]] = []
        if row.get("tp1_hit"):
            hit_log.append(dict(label="TP1", ok=True,
                                time=str(row.get("tp1_hit_at") or "")))
        try:
            _ts = json.loads(row.get("target_state_json") or "{}") if isinstance(
                row.get("target_state_json"), (str, bytes)) else (row.get("target_state_json") or {})
            for _i, _t in enumerate((_ts.get("targets") or [])[:2]):
                _ht = str(_t.get("hit_at") or (_t.get("ts") if _t.get("hit") else "") or "")
                if _ht:
                    hit_log.append(dict(label=f"TP{_i + 1}", ok=True, time=_ht))
        except Exception:
            pass
        if str(row.get("result")) == "LOSS" and row.get("closed_at"):
            hit_log.append(dict(label="STOP", ok=False, time=str(row.get("closed_at"))))
        elif str(row.get("result")) == "WIN" and row.get("closed_at"):
            hit_log.append(dict(label="CLOSE", ok=True, time=str(row.get("closed_at"))))
        try:
            _ladder_obj = json.loads(row.get("target_state_json") or "{}") if isinstance(row.get("target_state_json"), (str, bytes)) else (row.get("target_state_json") or {})
        except Exception:
            _ladder_obj = {}
        _management = dict(leverage=int(row.get("leverage") or 0), margin=float(row.get("margin_usd") or 0),
                            trailing_sl=_fmt_price(_ladder_obj.get("current_sl") or row.get("sl") or 0),
                            hit_index=int(_ladder_obj.get("hit_index") or 0),
                            trail_regime=str(_ladder_obj.get("r29_regime") or ""))
        _messages: Dict[str, str] = {}
        for _k in ("compact", "confirmed", "confirm", "final", "detailed"):
            _m = _app_mirror(str(sid), _k)
            if _m and _m.get("html"):
                _messages[_k] = str(_m["html"])[:6000]
        return dict(
            signal_id=str(row.get("signal_id") or ""), symbol=row.get("symbol"),
            source=row.get("source"), strategy_fa=row.get("strategy_fa"),
            direction=row.get("direction"), entry=_fmt_price(row.get("entry")),
            sl=_fmt_price(row.get("sl")), tp1=_fmt_price(row.get("tp1")),
            tp2=_fmt_price(row.get("tp2")), result=res,
            pnl=(float(row.get("pnl_pct")) if row.get("pnl_pct") is not None else None),
            score=row.get("score"), style=row.get("trade_style"),
            code=str(row.get("public_code") or ""), tf=str(row.get("trigger_timeframe") or "").upper(),
            time=str(row.get("created_at") or ""), spot=is_spot, confirmed=bool(row.get("confirmed")),
            tp1_hit=bool(row.get("tp1_hit") or lh1), tp2_hit=bool(lh2),
            sl_moved_to_be=bool(row.get("sl_moved_to_be")),
            created_at=str(row.get("created_at") or ""),
            confirmed_at=str(row.get("confirmed_at") or ""),
            closed_at=str(row.get("closed_at") or ""),
            summary=str(row.get("description") or row.get("strategy_fa") or ""),
            entry_conditions=str(row.get("entry_conditions") or ""),
            confirmations=[str(x) for x in conf],
            ladder=[dict(price=_fmt_price(row.get("tp1")), hit=bool(row.get("tp1_hit") or lh1)),
                    dict(price=_fmt_price(row.get("tp2")), hit=lh2)],
            hit_log=hit_log,
            messages=_messages,
            timeline=timeline,
            mtf_candles=_mtf_candles,
            market_intelligence=_market_intelligence,
            classic_patterns=[str(x) for x in _classic_patterns],
            management=_management,
        )
    except Exception as exc:
        print(f"app signal detail failed {sid}: {exc}")
        return None


# ──────────────────────────────── routes ────────────────────────────────
@viva_app.route("/app")
def app_shell():
    # Keep the private app deterministic: unauthenticated visits must land on
    # the login screen instead of receiving an empty shell that later redirects
    # after a failed /api/state request.
    if _password() and not _session_ok():
        return redirect("/app/login", code=302)
    resp = make_response(APP_HTML)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    # r39: an installed PWA must NEVER live on a stale shell — every open
    # revalidates (his «اپلیکیشن آپدیت نمیشه» bug report).
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


@viva_app.route("/app/login", methods=["GET"])
def login_page():
    if _password() and _session_ok():
        return redirect("/app", code=302)
    resp = make_response(LOGIN_HTML.replace("__ERROR__", ""))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
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


_STATE_CACHE: Dict[str, Any] = {"state": None, "at": 0.0}
_STATE_REBUILDING = {"flag": False}


@viva_app.route("/app/api/state")
def api_state():
    resp = jsonify(_fetch_state())
    resp.headers["Cache-Control"] = "no-store"
    return resp


_VERSION_SQL = ("SELECT COUNT(*), COALESCE(MAX(created_at),''), "
                "COALESCE(MAX(last_checked_at),''), COALESCE(MAX(confirmed_at),''), "
                "COALESCE(MAX(closed_at),''), COALESCE(MAX(tp1_hit_at),'') FROM signals")


@viva_app.route("/app/api/version")
def api_version():
    """r41 REAL-LIVE (Viva 09-26, «اپ لایو واقعی، بدون تاخیر») — a fingerprint
    of the signals table from ONE cheap query; the shell polls it every 10s
    and only pulls the heavy /app/api/state when something actually changed
    (Railway CPU stays flat)."""
    ver = ""
    try:
        from database.db import db_cursor
        with db_cursor() as c41:
            c41.execute(_VERSION_SQL)
            r41 = c41.fetchone() or ()
        ver = "|".join(str(x) for x in r41)
    except Exception as _exc:
        print(f"version probe failed: {_exc}")
        ver = f"t{int(time.time())}"
    resp = jsonify(version=ver)
    resp.headers["Cache-Control"] = "no-store"
    return resp


_PRICES_CACHE: Dict[str, Any] = {"at": 0.0, "data": {}}


@viva_app.route("/app/api/prices")
def api_prices():
    """r41 LIVE card prices — one public ticker call per 10s (in-process
    cache), fail-open to the last known values. Zero renderer/kline cost."""
    syms = [s.strip().upper() for s in (request.args.get("symbols") or "").split(",")
            if s.strip()][:24]
    if not syms:
        return jsonify(prices={})
    now = time.monotonic()
    data = dict(_PRICES_CACHE["data"] or {})
    if not data or now - _PRICES_CACHE["at"] >= 10:
        # r41d: THE SAME source the bot's own realtime monitor uses
        # (main._live_price_map): ourbit tickers first, engine tickers as
        # fallback — the proven egress, one cached call per 10s window.
        try:
            from data.ourbit import get_ourbit_tickers
            for row in get_ourbit_tickers(use_cache=True):
                _s = str(row.get("symbol") or "").upper()
                try:
                    _px = float(row.get("last_price") or 0)
                except Exception:
                    continue
                if _px > 0:
                    data[_s] = _px
        except Exception as _exc:
            print(f"ourbit price probe failed: {_exc}")
        if not data:
            try:
                from data.fetcher import get_tickers
                for row in get_tickers():
                    _s = str(row.get("symbol") or "").upper()
                    try:
                        _px = float(row.get("last_price") or 0)
                    except Exception:
                        continue
                    if _px > 0:
                        data[_s] = _px
            except Exception as _exc:
                print(f"engine price probe failed: {_exc}")
        if data:
            if len(_PRICES_CACHE["data"]) > 200:
                _PRICES_CACHE["data"] = {}
            _PRICES_CACHE["data"].update(data)
            _PRICES_CACHE["at"] = now
    out = {s: _PRICES_CACHE["data"].get(s) for s in syms
           if _PRICES_CACHE["data"].get(s)}
    resp = jsonify(prices=out)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@viva_app.route("/app/api/signal/<sid>")
def api_signal(sid):
    d = _signal_detail(sid)
    if d is None:
        return jsonify({"ok": False, "error": "not-found"}), 404
    return jsonify(d)


@viva_app.route("/app/api/chart/<sid>")
def api_chart(sid):
    png = _signal_chart_png(sid)
    if not png:
        return jsonify({"ok": False, "error": "chart-unavailable"}), 404
    resp = make_response(send_file(io.BytesIO(png), mimetype="image/png", download_name=f"{sid}.png"))
    resp.headers["Cache-Control"] = "private, max-age=1800"
    return resp


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
        "description": "Professional crypto signals dashboard and Telegram mirror",
        "lang": "en", "dir": "ltr",
        "version": "R41",
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
    e.respondWith(caches.open('viva-shell-r41').then(async c => {
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
    safe = {"icon-192.png", "icon-512.png", "apple-touch-icon.png", "favicon.png",
            "brand-logo.png"}
    if name not in safe:
        return "", 404
    if name == "brand-logo.png":
        return send_file(os.path.join(_BASE_DIR, "assets", "vivasignals-logo.png"),
                         mimetype="image/png")
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
/* R31 LUXURY SHELL — visual-only: Telegram typography/content/IDs are untouched. */
body:before{content:'';position:fixed;inset:0;pointer-events:none;z-index:-1;
 background:radial-gradient(520px 260px at 8% 12%,rgba(232,182,76,.07),transparent 70%),
            radial-gradient(620px 300px at 92% 42%,rgba(76,141,255,.045),transparent 72%)}
header{box-shadow:0 8px 30px rgba(0,0,0,.20)}
.card{position:relative;overflow:hidden;box-shadow:0 14px 38px rgba(0,0,0,.34),inset 0 1px 0 rgba(255,255,255,.025)}
.card:before{content:'';position:absolute;inset:0 0 auto 0;height:1px;background:linear-gradient(90deg,transparent,rgba(232,182,76,.42),transparent);opacity:.7}
.card:hover{border-color:rgba(232,182,76,.22);box-shadow:0 18px 44px rgba(0,0,0,.38),inset 0 1px 0 rgba(255,255,255,.035)}
.badge,.chip,.stat,.live,.pill,.tile,.explain{box-shadow:inset 0 1px 0 rgba(255,255,255,.025)}
.thumb{box-shadow:inset 0 0 0 1px rgba(255,255,255,.018)}
.tile{background:linear-gradient(145deg,rgba(255,255,255,.028),rgba(255,255,255,.008)),var(--panel);box-shadow:0 10px 28px rgba(0,0,0,.22)}
.dhead{box-shadow:0 8px 28px rgba(0,0,0,.22)}
.chartbox{box-shadow:0 18px 48px rgba(0,0,0,.42)}
nav{box-shadow:0 -10px 34px rgba(0,0,0,.28)}
@media(min-width:681px){main,.dbody{max-width:760px}.card{border-radius:20px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
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


APP_HTML = """<!doctype html><html lang="en" dir="ltr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a0f1a">
<meta name="application-name" content="VIVA SIGNALS PRO">
<meta name="app-version" content="R41">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="VIVA">
<title>VivaSignals Pro — SMC Scanner v7</title>
<link rel="manifest" href="/app/manifest.webmanifest">
<link rel="apple-touch-icon" href="/app/icons/apple-touch-icon.png">
<link rel="icon" href="/app/favicon.png">
<style>
@font-face{font-family:Vazirmatn;src:url(/app/fonts/Vazirmatn-Regular.woff2) format('woff2');font-weight:400;font-display:swap}
@font-face{font-family:Vazirmatn;src:url(/app/fonts/Vazirmatn-Bold.woff2) format('woff2');font-weight:700;font-display:swap}
:root{
 --bg:#0a0f1a;--card:#101a2c;--card2:#0d1524;--line:#1d2a42;--line2:#16223a;
 --tx:#e7edf6;--mut:#8b9cb5;--grn:#2ce5a7;--red:#ff5c66;--amb:#ffb020;--blu:#4c8dff;--tea:#19d3c5;
 --sat:env(safe-area-inset-top,0px);--sab:env(safe-area-inset-bottom,0px);
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--tx);font-family:Vazirmatn,-apple-system,'Segoe UI',Roboto,sans-serif;font-size:14px;padding-bottom:calc(72px + var(--sab))}
header{position:sticky;top:0;z-index:40;display:flex;align-items:center;gap:10px;padding:calc(10px + var(--sat)) 14px 10px;background:rgba(10,15,26,.92);backdrop-filter:blur(14px);border-bottom:1px solid var(--line2)}
.logo{width:38px;height:38px;border-radius:12px;object-fit:cover;background:#0d1524;border:1px solid rgba(232,182,76,.45);display:grid;place-items:center;font-size:17px}
.ht{flex:1;min-width:0}.ht b{display:block;font-size:15px}.ht span{font-size:10.5px;color:var(--mut)}
.hbtn{width:36px;height:36px;border-radius:11px;background:var(--card);border:1px solid var(--line);color:var(--grn);display:grid;place-items:center;font-size:15px;cursor:pointer}
.hbtn.busy{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
main{max-width:640px;margin:0 auto;padding:14px 12px 10px}
.page{display:none}.page.on{display:block;animation:fade .18s ease}@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
h1.pg{font-size:22px;font-weight:800;margin:2px 2px 10px}
.sub{color:var(--mut);font-size:11.5px;margin:-8px 2px 12px}
.sect{display:flex;align-items:center;justify-content:space-between;margin:18px 2px 8px}
.sect h2{font-size:12px;font-weight:800;letter-spacing:.09em;color:var(--mut)}
.sect a{color:var(--tea);font-size:12px;font-weight:700;text-decoration:none;cursor:pointer}
.card{background:var(--card);border:1px solid var(--line2);border-radius:16px;padding:14px;margin-bottom:10px}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
.tile{background:var(--card);border:1px solid var(--line2);border-radius:16px;padding:13px 14px}
.tile span{display:block;font-size:9.5px;font-weight:800;letter-spacing:.08em;color:var(--mut)}
.tile b{display:block;font-size:24px;font-weight:800;margin-top:6px}
.tile i{font-style:normal;font-size:10.5px;color:var(--mut)}
.grn{color:var(--grn)}.red{color:var(--red)}.amb{color:var(--amb)}.blu{color:var(--blu)}
.bar{height:5px;border-radius:99px;background:var(--line2);overflow:hidden;margin:9px 0 2px}
.bar>div{height:100%;border-radius:99px;background:var(--grn)}
/* equity + donut */
.eq{display:flex;align-items:flex-start;justify-content:space-between}
.eq b.t{font-size:16px}.eq span{font-size:9.5px;font-weight:800;letter-spacing:.08em;color:var(--mut);display:block}
.eqfoot{display:flex;justify-content:space-between;color:var(--mut);font-size:10.5px;margin-top:6px}
.donutwrap{display:flex;align-items:center;gap:16px;margin-top:6px}
.dlegend{flex:1}
.dlegend .row{display:flex;align-items:center;gap:8px;font-size:12.5px;padding:4px 0}
.dlegend .row b{margin-left:auto}
.dotk{width:11px;height:11px;border-radius:4px}
.minitrack{height:4px;border-radius:99px;background:var(--line2);margin-top:4px}.minitrack>div{height:100%;border-radius:99px}
/* signal cards */
.fchips{display:flex;gap:7px;overflow-x:auto;padding:2px 0 10px;scrollbar-width:none}
.fchips::-webkit-scrollbar{display:none}
.fchip{flex:0 0 auto;font-size:11.5px;font-weight:700;color:var(--mut);background:var(--card);border:1px solid var(--line2);border-radius:99px;padding:7px 13px;cursor:pointer}
.fchip.on{background:var(--grn);color:#042115;border-color:var(--grn)}
.scard{background:var(--card);border:1px solid var(--line2);border-radius:16px;padding:12px 13px;margin-bottom:10px;cursor:pointer}
.scard:active{transform:scale(.99)}
.sr1{display:flex;align-items:center;gap:9px}
.sico{width:34px;height:34px;border-radius:11px;display:grid;place-items:center;font-size:15px;background:var(--card2);border:1px solid var(--line2)}
.sico.up{color:var(--grn)}.sico.dn{color:var(--red)}
.sym{font-size:15px;font-weight:800}.ssub{font-size:10.5px;color:var(--mut)}
.sres{margin-left:auto;text-align:right}
.sres b{font-size:14px}.sres span{display:block;font-size:10px;color:var(--mut)}
.tag{font-size:9.5px;font-weight:800;padding:2px 8px;border-radius:8px;letter-spacing:.05em}
.tag.WIN{color:var(--grn);background:rgba(44,229,167,.12)}.tag.LOSS{color:var(--red);background:rgba(255,92,102,.12)}
.tag.PENDING{color:var(--amb);background:rgba(255,176,32,.12)}.tag.BREAKEVEN{color:var(--amb);background:rgba(255,176,32,.12)}
.spills{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:10px}
.spill{background:var(--card2);border:1px solid var(--line2);border-radius:11px;padding:7px 9px}
.spill span{display:block;font-size:9px;font-weight:800;letter-spacing:.06em;color:var(--mut)}
.spill b{font-size:12px}
/* strategies */
.strat{background:var(--card);border:1px solid var(--line2);border-radius:16px;padding:14px;margin-bottom:10px}
.strat .r1{display:flex;align-items:center;gap:9px}
.strat .r1 b{font-size:16px;letter-spacing:.03em}
.strat .r1 .fa{font-size:10.5px;color:var(--mut)}
.scoreb{margin-left:auto;font-size:12px;font-weight:800;color:var(--amb);background:rgba(255,176,32,.1);border:1px solid rgba(255,176,32,.35);padding:3px 9px;border-radius:9px}
.caret{color:var(--mut);cursor:pointer;font-size:12px}
.st3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:11px}
.st3>div{background:var(--card2);border:1px solid var(--line2);border-radius:11px;padding:8px;text-align:center}
.st3 span{font-size:9px;font-weight:800;letter-spacing:.07em;color:var(--mut);display:block}
.st3 b{font-size:16px}
.kv{display:flex;justify-content:space-between;font-size:12px;padding:7px 0;border-bottom:1px solid var(--line2)}
.kv:last-child{border-bottom:0}.kv span{color:var(--mut)}
/* alerts */
.note{font-size:12.5px;padding:11px;border-radius:12px;border:1px solid var(--line2);background:var(--card2);color:var(--mut);line-height:1.7}
.note.bad{color:#ff9ba1;border-color:rgba(255,92,102,.35)}
.note.ok{color:#7df0c8;border-color:rgba(44,229,167,.35)}
.empty{text-align:center;color:var(--mut);font-size:12.5px;padding:26px 10px;background:var(--card);border:1px solid var(--line2);border-radius:16px}
/* control */
.rtable{width:100%;border-collapse:collapse;font-size:11px}
.rtable th{color:var(--mut);font-size:9px;letter-spacing:.07em;text-align:right;padding:6px 6px;border-bottom:1px solid var(--line2)}
.rtable td{padding:8px 6px;border-bottom:1px solid var(--line2);text-align:right;white-space:nowrap}
.twrap{overflow-x:auto}
.sw{position:relative;width:42px;height:24px;border-radius:99px;background:var(--line2);border:0;cursor:pointer;transition:.15s;flex:0 0 auto}
.sw.on{background:var(--grn)}
.sw::after{content:'';position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;transition:.15s}
.sw.on::after{left:21px}
.crow{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--line2)}
.crow b{font-size:12.5px}.crow span{font-size:10px;color:var(--mut);display:block}
.funchip{font-size:10px;color:var(--mut);background:var(--card2);border:1px solid var(--line2);border-radius:8px;padding:3px 8px;display:inline-block;margin:3px 3px 0 0}
/* tabs */
nav{position:fixed;bottom:0;left:0;right:0;z-index:45;display:grid;grid-template-columns:repeat(6,1fr);background:rgba(10,15,26,.96);backdrop-filter:blur(14px);border-top:1px solid var(--line2);padding:6px 4px calc(6px + var(--sab))}
nav button{background:none;border:0;color:var(--mut);font-family:inherit;font-size:9.5px;font-weight:700;display:grid;justify-items:center;gap:3px;cursor:pointer;padding:4px 0;border-radius:10px}
nav button svg{width:20px;height:20px}
nav button.on{color:var(--grn)}
nav button.on .tiline{width:16px;height:2.5px;border-radius:2px;background:var(--grn)}
.tiline{width:16px;height:2.5px;border-radius:2px;background:transparent}
/* detail sheet */
.sheetbg{position:fixed;inset:0;background:rgba(2,6,14,.6);backdrop-filter:blur(3px);z-index:60;display:none}
.sheet{position:fixed;left:0;right:0;bottom:0;z-index:61;background:#0e1626;border:1px solid var(--line);border-radius:22px 22px 0 0;padding:16px 16px calc(18px + var(--sab));transform:translateY(105%);transition:transform .22s ease;max-height:88vh;overflow-y:auto}
.sheet.on{transform:translateY(0)}
.sh1{display:flex;align-items:center;gap:10px}
.sh1 .sym{font-size:18px}.sh1 .code{font-size:10.5px;color:var(--mut);display:block}
.xbtn{margin-left:auto;width:34px;height:34px;border-radius:11px;background:var(--card);border:1px solid var(--line);color:var(--tx);font-size:14px;cursor:pointer}
.shtags{display:flex;gap:7px;margin:12px 0}
.shtags .tag{font-size:10.5px;padding:5px 11px}
.dtiles{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:12px 0}
.dtile{background:var(--card);border:1px solid var(--line2);border-radius:14px;padding:11px 12px}
.dtile span{font-size:10px;color:var(--mut);display:flex;align-items:center;gap:6px}
.dtile b{font-size:16px;display:block;margin-top:5px}
.drow{display:flex;justify-content:space-between;align-items:center;background:var(--card);border:1px solid var(--line2);border-radius:13px;padding:12px 14px;margin-bottom:8px;font-size:13px}
.drow span{color:var(--mut)}.drow b{font-weight:800}
.dchart{border:1px solid var(--line2);border-radius:14px;overflow:hidden;margin:10px 0}
.dchart img{width:100%;display:block;background:#fff}
.explain{font-size:12px;color:#c9d4e4;line-height:1.9;border-top:1px dashed var(--line);padding-top:9px;margin-top:9px;direction:rtl;text-align:right}
.demo{margin:0 0 10px;text-align:center;font-size:11px;color:var(--amb);background:rgba(255,176,32,.07);border:1px dashed rgba(255,176,32,.4);border-radius:10px;padding:6px}
.hero{display:flex;align-items:center;gap:12px;background:linear-gradient(135deg,#101a2c 0%,#0d2033 60%,#0e2436 100%);border:1px solid rgba(232,182,76,.28);border-radius:18px;padding:14px;margin:2px 0 12px}
.hero img{width:52px;height:52px;border-radius:14px;object-fit:cover;border:1px solid rgba(232,182,76,.5)}
.hero b{display:block;font-size:16.5px;letter-spacing:.03em;color:#e9d9a8}
.hero span{display:block;font-size:10.5px;color:var(--mut);margin-top:3px}
.about-hero{display:grid;justify-items:center;gap:6px;background:linear-gradient(160deg,#101a2c 0%,#0e2436 100%);border:1px solid rgba(232,182,76,.3);border-radius:18px;padding:20px 14px;margin:2px 0 12px;text-align:center}
.about-hero img{width:74px;height:74px;border-radius:18px;object-fit:cover;border:1px solid rgba(232,182,76,.5)}
.about-hero b{font-size:18px;color:#e9d9a8;letter-spacing:.04em}
.about-hero span{font-size:11px;color:var(--mut)}
.ab-sec{font-size:13.5px;font-weight:800;color:var(--amb);margin-bottom:8px}
.ab-fa{font-size:13px;line-height:2;color:#dbe4f0;text-align:right}
.ab-en{font-size:12.5px;line-height:1.8;color:#9fb2cb;direction:ltr;text-align:left}
.ab-chip{display:inline-block;font-size:10.5px;font-weight:700;color:#e9d9a8;background:rgba(232,182,76,.08);border:1px solid rgba(232,182,76,.35);border-radius:99px;padding:4px 11px;margin:3px 3px 0 0}
.ab-foot{margin-top:12px;padding-top:10px;border-top:1px dashed var(--line);font-size:10.5px;color:var(--mut);text-align:center;letter-spacing:.04em}
</style>
</head><body>
<header>
 <img class="logo" src="/app/icons/brand-logo.png" alt="VIVA">
 <div class="ht"><b>VIVA-MON.labs</b><span>VivaSignals Pro · SMC Scanner v7</span></div>
 <div class="hbtn" id="liveIco" title="live">📶</div>
 <div class="hbtn" id="refreshBtn" title="refresh">⟳</div>
</header>
<main>
 <div class="demo" id="demoBar" style="display:none">حالت نمایشی — دادهٔ زندهٔ متصل نیست</div>

 <section class="page on" id="pg-home">
  <div class="hero">
   <img src="/app/icons/brand-logo.png" alt="VIVA">
   <div><b>VIVA-MON.labs</b><span>Macro &amp; Political-Economy Strategy · SMC Scanner v7</span></div>
  </div>
  <h1 class="pg">Overview</h1><div class="sub">SMC Scanner Dashboard v7</div>
  <div class="tiles" id="homeTiles"></div>
  <div class="card">
   <div class="eq"><div><span>EQUITY CURVE</span><b class="t" id="eqTitle">—</b></div>
    <div style="text-align:right"><span>CUMULATIVE PNL</span><b class="t grn" id="eqCum">—</b></div></div>
   <div id="eqSvg" style="margin-top:8px"></div>
   <div class="eqfoot"><span id="eqN">—</span><span id="eqBest">—</span><span id="eqWorst">—</span></div>
  </div>
  <div class="card">
   <b style="font-size:15px">🥧 Result Distribution</b>
   <div class="donutwrap"><div id="donut"></div><div class="dlegend" id="dLegend"></div></div>
  </div>
  <div class="sect"><h2>TOP STRATEGIES</h2><a onclick="go('strategies')">See all ›</a></div>
  <div id="topStrats"></div>
  <div class="sect"><h2>RECENT SIGNALS</h2><a onclick="go('signals')">See all ›</a></div>
  <div id="recentSigs"></div>
 </section>

 <section class="page" id="pg-signals">
  <h1 class="pg">Signals</h1><div class="sub" id="sigCount">—</div>
  <div class="fchips" id="fchips"></div>
  <div id="sigList"></div>
 </section>

 <section class="page" id="pg-strategies">
  <h1 class="pg">Strategies</h1><div class="sub">عملکرد هر ستاپ — برد / باخت / میانگین</div>
  <div id="stratList"></div>
  <div class="sect"><h2>ARCHIVE (low activity)</h2></div>
  <div id="stratArch"></div>
 </section>

 <section class="page" id="pg-alerts">
  <h1 class="pg">Alerts</h1><div class="sub" id="alertSub">All caught up</div>
  <div class="card">
   <b style="font-size:14.5px">🔗 Notification Settings</b>
   <div class="note" id="noteState" style="margin-top:10px">…</div>
   <button id="noteBtn" class="hbtn" style="width:auto;padding:9px 14px;border-radius:11px;font-size:12px;font-weight:700;margin-top:10px">Enable notifications</button>
  </div>
  <div class="sect"><h2>ALERT HISTORY</h2></div>
  <div id="hitList"></div>
 </section>

 <section class="page" id="pg-about">
  <h1 class="pg">About</h1><div class="sub">معرفی — ویوا و پروژه</div>
  <div class="about-hero">
   <img src="/app/icons/brand-logo.png" alt="VIVA-MON.labs">
   <b>VIVA-MON.labs</b>
   <span>VivaSignals Pro · SMC Scanner v7</span>
  </div>

  <div class="card">
   <div class="ab-sec">👑 معرفی — وحید لسانی «ویوا»</div>
   <p class="ab-fa">کارشناس و تحلیلگر اقتصاد کلان و استراتژیست اقتصاد سیاسی؛ تریدر و فعال بازارهای مالی. تحصیلات آکادمیک در رشتهٔ مدیریت بانکی از دانشگاه شاهرود. فعال از سال ۱۳۹۶ در بازارهای مالی سهام و کریپتو — با نام مستعار <b>«ویوا»</b>.</p>
   <div class="ab-en">Macro-economics analyst &amp; political-economy strategist. Trader and financial-markets professional. Academic background in Banking Management — Shahroud University. Active in equities and crypto markets since 2017, known as <b>“Viva”</b> — project owner.</div>
   <div style="margin-top:10px">
    <span class="ab-chip">📊 تحلیل کلان</span><span class="ab-chip">📈 تریدر</span><span class="ab-chip">🏦 مدیریت بانکی</span><span class="ab-chip">⚡ از ۱۳۹۶</span>
   </div>
  </div>

  <div class="card">
   <div class="ab-sec">⚙️ دربارهٔ پروژه · About the Project</div>
   <div class="ab-en">VIVA-MON.labs is the private research &amp; signal engine behind the VivaSignals channels: a self-hosted Smart-Money-Concepts scanner that watches hundreds of crypto pairs across twelve timeframes, validates every setup through a multi-stage quality gate, and publishes only high-confidence, fully-managed trade plans — with live tracking, lifecycle updates and an honest, audited results ledger.</div>
   <p class="ab-fa" style="margin-top:8px">در گیتهاب، موتور اسکنر و اپلیکیشن به‌صورت خصوصی نگهداری می‌شود: معماری ماژولار (موتورهای ستاپ، مدیریت معامله، رندر چارت و اپ PWA)، تست‌محور با بیش از ۵۰۰ تست خودکار، و چرخهٔ انتشار کنترل‌شده. پروژه <b>در حال توسعهٔ مداوم</b> است و با هر نسخه، موتورها و همین اپلیکیشن کامل‌تر می‌شوند.</p>
   <div class="ab-en" style="margin-top:6px">The GitHub repository (private) hosts the scanner engine and this app: modular setup engines, trade management, a deterministic chart renderer and the PWA you are using — test-driven with 500+ automated tests and a controlled release chain. The project is under <b>continuous development</b> — engines, charts and this app keep evolving release by release.</div>
  </div>

  <div class="card">
   <div class="ab-sec">©️ مالکیت معنوی و تجاری · Intellectual Property</div>
   <p class="ab-fa">تمامی حقوق معنوی، <b>مالکیت تجاریِ ایده</b>، نشان تجاری و لوگوی «VIVA-MON.labs» و «VivaSignals»، اپلیکیشن VivaSignals Pro و مخزن گیتهابِ این پروژه، انحصاراً متعلق به <b>وحید لسانی (ویوا)</b> است. این پروژه در حال توسعهٔ مداوم است و هرگونه بازانتشار، بازتولید یا بهره‌برداری تجاری از ایده، سیگنال‌ها، چارت‌ها، متن‌ها و کدهای این مجموعه، بدون اجازهٔ کتبی مالک، ممنوع است و پیگرد قانونی دارد.</p>
   <div class="ab-en" style="margin-top:8px">All intellectual property rights, the <b>commercial ownership of the idea</b>, trademarks and branding of <b>VIVA-MON.labs</b> and <b>VivaSignals</b> — including the golden-diamond logo, the VivaSignals Pro application and the project's GitHub repository — are the exclusive property of <b>Vahid Lesani (“Viva”)</b>. The project is under continuous development. Redistribution, reproduction or commercial use of the idea or of any signal, chart, text or code from this project without the owner's written consent is strictly prohibited.</div>
  </div>

  <div class="card">
   <div class="ab-sec">⚠️ سلب مسئولیت · Disclaimer</div>
   <p class="ab-fa">از سوی اپلیکیشن و مالک پروژه، به هیچ شخص حقیقی یا حقوقی، هیچ‌گونه پیشنهاد یا توصیهٔ مالی ارائه نمی‌شود؛ محتوای این اپ صرفاً تحلیل فنی و آموزشی است. مسئولیت هرگونه ضرر و زیان ناشی از استفاده از سیگنال‌ها، کاملاً بر عهدهٔ کاربر است و پروژه و توسعه‌دهنده، هیچ‌گونه مسئولیت حقوقی در قبال ضرر و زیان احتمالی کاربران نخواهند داشت.</p>
   <div class="ab-en" style="margin-top:8px">Nothing in this application constitutes a financial offer, solicitation or investment advice to any individual or entity — all content is technical analysis only. Any loss or damage arising from the use of the signals is entirely at the user's own responsibility, and the project and its developer assume no legal liability for any potential user losses.</div>
   <div class="ab-foot">© 2026 VIVA-MON.labs · Vahid Lesani — All rights reserved</div>
  </div>
 </section>

 <section class="page" id="pg-control">
  <h1 class="pg">🎛 کنترل نتایج</h1><div class="sub">PnL به‌ازای لوریج و مارجین — همان امروز</div>
  <div class="tiles" id="ctlTiles"></div>
  <div class="card"><b style="font-size:13px">معاملاتِ بستهٔ امروز</b><div class="twrap" id="ctlTable" style="margin-top:8px"></div></div>
  <div class="card"><b style="font-size:13px">کنترل انتشار</b><div id="ctlSwitches" style="margin-top:6px"></div></div>
  <div class="card"><b style="font-size:13px">فانل اسکن</b><div id="ctlFunnel" style="margin-top:6px"></div></div>
 </section>
</main>

<div class="sheetbg" id="sheetbg" onclick="closeSheet()"></div>
<div class="sheet" id="sheet"></div>

<nav>
 <button data-t="home" class="on"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="8" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/><rect x="13" y="13" width="8" height="8" rx="2"/></svg>Home<span class="tiline"></span></button>
 <button data-t="signals"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12h2l2-7 3 14 3-9 2 2h4"/></svg>Signals<span class="tiline"></span></button>
 <button data-t="strategies"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 20V10M12 20V4M19 20v-7"/></svg>Strategies<span class="tiline"></span></button>
 <button data-t="alerts"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>Alerts<span class="tiline"></span></button>
 <button data-t="control"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h13M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>Control<span class="tiline"></span></button>
 <button data-t="about"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="3.2"/><path d="M5 20c.8-4 3.5-6 7-6s6.2 2 7 6"/></svg>About<span class="tiline"></span></button>
</nav>

<script>
let STATE=null,FILTER='ALL',PEND={paused:null,setups:null},NOTIF=new Set();

function fnum(v){return (v===null||v===undefined||v==='')?'—':String(v);}
function tehran(iso){try{const d=new Date(iso);return isNaN(d)?fnum(iso):d.toLocaleTimeString('fa-IR',{hour:'2-digit',minute:'2-digit'});}catch(e){return fnum(iso)}}
function ago(iso){try{const s=(Date.now()-new Date(iso).getTime())/1e3;if(!isFinite(s))return fnum(iso);
 if(s<3600)return Math.max(1,Math.round(s/60))+'m ago';if(s<86400)return Math.round(s/3600)+'h ago';return Math.round(s/86400)+'d ago'}catch(e){return fnum(iso)}}
function money(v){return '$'+Number(v).toFixed(2)}
function resTag(r){const m={WIN:'WIN',LOSS:'LOSS',PENDING:'PENDING'};return `<span class="tag ${m[r]||'BREAKEVEN'}">${fnum(m[r]||'BE')}</span>`}

async function load(){
 try{const r=await fetch('/app/api/state');if(r.status===401){location.href='/app/login';return}
  STATE=await r.json();render();}catch(e){}
}
function closed(){return (STATE.feed||[]).filter(x=>x.result==='WIN'||x.result==='LOSS')}
function equitySeries(){
 const rows=closed().slice().reverse();
 const usd=rows.every(x=>x.pnl_usd!==null&&x.pnl_usd!==undefined);
 let c=0;const pts=rows.map(x=>{c+=usd?Number(x.pnl_usd||0):Number(x.pnl||0);return {v:c,w:x.result==='WIN'}});
 return {pts,usd};
}
function donutSvg(w,l,b){
 const tot=Math.max(1,w+l+b),C=2*Math.PI*38;
 const seg=(v,off,col)=>{const f=C*v/tot;return `<circle cx="60" cy="60" r="38" fill="none" stroke="${col}" stroke-width="14" stroke-dasharray="${f} ${C-f}" stroke-dashoffset="${-off}" transform="rotate(-90 60 60)"/>`};
 return `<svg width="120" height="120" viewBox="0 0 120 120"><circle cx="60" cy="60" r="38" fill="none" stroke="#16223a" stroke-width="14"/>`
  +seg(w,0,'#2ce5a7')+seg(l,w,'#ff5c66')+seg(b,w+l,'#ffb020')
  +`<text x="60" y="58" text-anchor="middle" fill="#e7edf6" font-size="20" font-weight="800">${w+l+b}</text><text x="60" y="74" text-anchor="middle" fill="#8b9cb5" font-size="9">Trades</text></svg>`;
}
function eqSvg(pts){
 if(!pts.length)return '<div class="empty">هنوز معاملهٔ بسته‌ای امروز نیست</div>';
 const W=300,H=110,P=6,vs=pts.map(p=>p.v),mn=Math.min(...vs,0),mx=Math.max(...vs,1);
 const X=i=>P+i*(W-2*P)/Math.max(1,pts.length-1),Y=v=>H-P-(v-mn)*(H-2*P)/(mx-mn||1);
 const poly=pts.map((p,i)=>`${X(i).toFixed(1)},${Y(p.v).toFixed(1)}`).join(' ');
 const dots=pts.map((p,i)=>`<circle cx="${X(i).toFixed(1)}" cy="${Y(p.v).toFixed(1)}" r="2.4" fill="${p.w?'#2ce5a7':'#ff5c66'}"/>`).join('');
 return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto"><line x1="0" y1="${H-P}" x2="${W}" y2="${H-P}" stroke="#16223a" stroke-dasharray="3 4"/><polyline points="${poly}" fill="none" stroke="#2ce5a7" stroke-width="2"/>${dots}</svg>`;
}
function sigCard(x){
 const dir=x.spot?'up':(x.direction==='SHORT'?'dn':'up');
 const res=x.result,pc=(x.pnl!==null&&x.pnl!==undefined)?((x.pnl>0?'+':'')+x.pnl+'%'):'';
 const t3=(x.ladder_targets&&x.ladder_targets[2])?x.ladder_targets[2]:null;
 const slv=x.current_sl||x.sl;
 const lv=x.live;
 return `<div class="scard" onclick="openDetail('${x.signal_id}')">
  <div class="sr1"><div class="sico ${dir}">${dir==='up'?'📈':'📉'}</div>
   <div><div class="sym">${fnum(x.symbol)}</div><div class="ssub">${fnum(x.source)} • ${ago(x.time)}</div></div>
   <div class="sres"><b class="${res==='WIN'?'grn':res==='LOSS'?'red':'amb'}">${pc||resTag(res)}</b>
    <span>Score ${fnum(x.score)}/10 ${x.pnl_usd!=null?`• <b class="${x.pnl_usd>=0?'grn':'red'}">${money(x.pnl_usd)}</b>`:''}</span></div></div>
  <div class="spills">
   <div class="spill"><span>ENTRY</span><b>${fnum(x.entry)}</b></div>
   <div class="spill"><span>${x.sl_moved?'SL TRAIL':'SL'}</span><b class="${x.sl_moved?'amb':'red'}">${fnum(slv)}</b></div>
   <div class="spill"><span>TP1${x.tp1_hit?' ✓':''}</span><b class="grn">${fnum(x.tp1)}</b></div>
   <div class="spill"><span>TP2${x.tp2_hit?' ✓':''}</span><b class="grn">${fnum(x.tp2)}</b></div>
   ${t3?`<div class="spill"><span>TP3${x.tp3_hit?' ✓':''}</span><b class="grn">${fnum(t3)}</b></div>`:''}
   ${lv?`<div class="spill"><span>LIVE</span><b style="color:#e7edf6">${fnum(lv)}</b></div>`:''}
  </div></div>`;
}
function toast(msg){
 let t=document.getElementById('vivaToast');
 if(!t){t=document.createElement('div');t.id='vivaToast';
  t.style.cssText='position:fixed;bottom:86px;left:50%;transform:translateX(-50%);background:#1a2230;color:#e7edf6;border:1px solid rgba(232,182,76,.4);border-radius:14px;padding:10px 18px;font-size:12px;z-index:99;box-shadow:0 10px 30px rgba(0,0,0,.5);transition:opacity .3s;opacity:0;pointer-events:none';
  document.body.appendChild(t);}
 t.textContent=msg;t.style.opacity='1';
 clearTimeout(t._h);t._h=setTimeout(function(){t.style.opacity='0'},4000);
}
function fireTouch(k,x,msg){
 const key=x.signal_id+':'+k;if(TOUCH[key])return;TOUCH[key]=1;
 if(('Notification'in window)&&Notification.permission==='granted'){try{new Notification('VIVA · '+fnum(x.symbol),{body:msg})}catch(e){}}
 toast(fnum(x.symbol)+' · '+msg);
}
async function pollPrices(){
 try{
  const act=(STATE.feed||[]).filter(x=>x.result==='PENDING');
  if(!act.length)return;
  const syms=[...new Set(act.map(x=>x.symbol))].slice(0,24);
  const r=await fetch('/app/api/prices?symbols='+encodeURIComponent(syms.join(',')));
  if(r.status===401){location.href='/app/login';return}
  if(!r.ok)return;
  const j=await r.json();const P=j.prices||{};
  let dirty=false;
  act.forEach(x=>{
   const px=P[x.symbol];if(!px)return;
   x.live=px;dirty=true;
   const L=x.direction!=='SHORT';
   const tps=[[1,x.tp1,x.tp1_hit],[2,x.tp2,x.tp2_hit],[3,(x.ladder_targets&&x.ladder_targets[2]),x.tp3_hit]];
   tps.forEach(t=>{
     const n=t[0],lv=t[1],hit=t[2];
     if(!lv||hit)return;
     const crossed=L?(px>=parseFloat(lv)):(px<=parseFloat(lv));
     if(crossed)fireTouch('tp'+n,x,'هدف '+n+' ('+lv+') تاچ شد ✓');
   });
   if(x.sl&&x.result==='PENDING'){
     const s=L?(px<=parseFloat(x.sl)):(px>=parseFloat(x.sl));
     if(s)fireTouch('stop',x,'استاپ ('+x.sl+') خورد');
   }
  });
  if(dirty)render();
 }catch(e){}
}
let VER='';
async function pollV(){
 try{const r=await fetch('/app/api/version');if(r.status===401){location.href='/app/login';return}
  const j=await r.json();
  if(j.version&&j.version!==VER){const first=!VER;VER=j.version;if(!first)load();}
 }catch(e){}
}
function render(){
 if(!STATE)return;
 if(STATE.demo)document.getElementById('demoBar').style.display='block';
 const feed=STATE.feed||[],cl=closed();
 const wins=cl.filter(x=>x.result==='WIN').length,loss=cl.filter(x=>x.result==='LOSS').length;
 const be=cl.length-wins-loss;
 const pend=feed.filter(x=>x.result==='PENDING').length;
 const usdAll=(STATE.results||{}).usd_total;
 const usdOk=cl.every(x=>x.pnl_usd!==null&&x.pnl_usd!==undefined)&&cl.length>0;
 const cum=usdOk?money(usdAll):((cl.reduce((a,x)=>a+Number(x.pnl||0),0)).toFixed(2)+'%');
 const avg=cl.length?(cl.reduce((a,x)=>a+Number(x.pnl||0),0)/cl.length).toFixed(2)+'%':'—';
 const wr=cl.length?Math.round(wins*100/cl.length*10)/10:'—';
 document.getElementById('homeTiles').innerHTML=`
  <div class="tile"><span>TOTAL SIGNALS</span><b>${feed.length}</b><i>${pend} pending</i></div>
  <div class="tile"><span>WIN RATE</span><b class="grn">${wr}${wr==='—'?'':'%'}</b><i>${wins}W / ${loss}L</i></div>
  <div class="tile"><span>AVG PNL</span><b class="grn">${avg}</b><i>Per trade</i></div>
  <div class="tile"><span>CUM PNL</span><b class="${String(cum).startsWith('-')?'red':'grn'}">${cum}</b><i>All closed</i></div>`;
 // equity
 const eq=equitySeries();
 document.getElementById('eqTitle').textContent=cl.length?`${cl.length} closed trades`:'—';
 document.getElementById('eqCum').textContent=cum;
 document.getElementById('eqSvg').innerHTML=eqSvg(eq.pts);
 const best=cl.reduce((a,x)=>Math.max(a,Number(x.pnl||0)),0),worst=cl.reduce((a,x)=>Math.min(a,Number(x.pnl||0)),0);
 document.getElementById('eqN').textContent=`${cl.length} closed`;
 document.getElementById('eqBest').textContent=`Best: +${best.toFixed(2)}%`;
 document.getElementById('eqWorst').textContent=`Worst: ${worst.toFixed(2)}%`;
 // donut
 document.getElementById('donut').innerHTML=donutSvg(wins,loss,be);
 const pc=v=>Math.round(v*100/Math.max(1,cl.length)*10)/10;
 document.getElementById('dLegend').innerHTML=`
  <div class="row"><span class="dotk" style="background:#2ce5a7"></span>Wins<b class="grn">${wins} (${pc(wins)}%)</b></div>
  <div class="minitrack"><div style="width:${pc(wins)}%;background:#2ce5a7"></div></div>
  <div class="row"><span class="dotk" style="background:#ff5c66"></span>Losses<b class="red">${loss} (${pc(loss)}%)</b></div>
  <div class="minitrack"><div style="width:${pc(loss)}%;background:#ff5c66"></div></div>
  <div class="row"><span class="dotk" style="background:#ffb020"></span>Breakeven<b class="amb">${be} (${pc(be)}%)</b></div>
  <div class="minitrack"><div style="width:${pc(be)}%;background:#ffb020"></div></div>`;
 // top strategies
 const acts=(STATE.analytics&&STATE.analytics.rows_active)||[];
 const top=acts.slice().sort((a,b)=>(b.wr||0)-(a.wr||0)).slice(0,3);
 document.getElementById('topStrats').innerHTML=top.length?top.map(r=>`
  <div class="card" onclick="go('strategies')">
   <div class="sr1"><div><div class="sym" style="font-size:14px">${fnum(r.name)}</div><div class="ssub">${fnum(r.fa)}</div></div>
   <b class="grn" style="margin-left:auto;font-size:16px">${fnum(r.wr)}%</b></div>
   <div class="ssub" style="margin-top:7px">Total: ${fnum(r.total)} · <b class="grn">${fnum(r.wins)}W</b> · <b class="red">${fnum(r.losses)}L</b> · <span class="grn">${r.avg_pnl!=null?'+'+r.avg_pnl:'0'}%</span></div>
  </div>`).join(''):'<div class="empty">ستاپِ فعالی امروز نیست</div>';
 // recent signals
 document.getElementById('recentSigs').innerHTML=feed.length?feed.slice(0,5).map(sigCard).join(''):'<div class="empty">هشدار امروز ثبت نشده</div>';
 // signals tab
 const counts={ALL:feed.length,PENDING:pend,WIN:wins,LOSS:loss,SPOT:feed.filter(x=>x.spot).length};
 document.getElementById('sigCount').textContent=`${feed.length} total signals`;
 document.getElementById('fchips').innerHTML=Object.keys(counts).map(k=>
  `<button class="fchip ${FILTER===k?'on':''}" onclick="setFilter('${k}')">${k} ${counts[k]}</button>`).join('');
 const list=feed.filter(x=>FILTER==='ALL'||(FILTER==='SPOT'?x.spot:x.result===FILTER));
 document.getElementById('sigList').innerHTML=list.length?list.map(sigCard).join(''):'<div class="empty">موردی در این فیلتر نیست</div>';
 // strategies
 document.getElementById('stratList').innerHTML=acts.length?acts.map((r,i)=>`
  <div class="strat"><div class="r1"><div><b>${fnum(r.name)}</b><div class="fa">${fnum(r.fa)}</div></div>
   <span class="scoreb">★ ${r.avg_score!=null?r.avg_score:'—'}</span><span class="caret" onclick="tgl(${i})">▼</span></div>
   <div class="bar"><div style="width:${fnum(r.wr)}%"></div></div>
   <div class="ssub" style="margin-top:4px">Win Rate <b class="grn">${fnum(r.wr)}%</b></div>
   <div class="st3" id="st3-${i}" style="display:none">
    <div><span>TOTAL</span><b>${fnum(r.total)}</b></div><div><span>WINS</span><b class="grn">${fnum(r.wins)}</b></div>
    <div><span>LOSSES</span><b class="red">${fnum(r.losses)}</b></div>
    <div><span>AVG WIN</span><b class="grn">${r.avg_win!=null?'+'+r.avg_win+'%':'—'}</b></div>
    <div><span>AVG LOSS</span><b class="red">${r.avg_loss!=null?r.avg_loss+'%':'—'}</b></div>
    <div><span>NET AVG</span><b>${r.avg_pnl!=null?'+'+r.avg_pnl+'%':'—'}</b></div>
    <div><span>BEST</span><b class="grn">${r.best!=null?'+'+r.best+'%':'—'}</b></div>
    <div><span>WORST</span><b class="red">${r.worst!=null?r.worst+'%':'—'}</b></div>
    <div><span>LAST</span><b style="font-size:11px">${fnum(r.last)}</b></div>
   </div></div>`).join(''):'<div class="empty">داده‌ای نیست</div>';
 const arch=(STATE.analytics&&STATE.analytics.rows_archive)||[];
 document.getElementById('stratArch').innerHTML=arch.length?arch.map(r=>`
  <div class="card"><div class="sr1"><div><div class="sym" style="font-size:13px">${fnum(r.name)}</div><div class="ssub">${fnum(r.fa)}</div></div>
  <b style="margin-left:auto;font-size:13px" class="${(r.wr||0)>=50?'grn':'red'}">${fnum(r.wr)}%</b></div>
  <div class="ssub" style="margin-top:5px">${fnum(r.total)} trades • last ${fnum(r.last)}</div></div>`).join(''):'<div class="empty">—</div>';
 // alerts
 renderAlerts();
 // control
 const rb=STATE.results||{rows:[],usd_total:0,usd_win:0,usd_loss:0};
 document.getElementById('ctlTiles').innerHTML=`
  <div class="tile"><span>PnL خالص امروز</span><b class="${(rb.usd_total||0)>=0?'grn':'red'}">${money(rb.usd_total||0)}</b><i>مارجین</i></div>
  <div class="tile"><span>سودها</span><b class="grn">${money(rb.usd_win||0)}</b><i>—</i></div>`;
 document.getElementById('ctlTiles').innerHTML+=`
  <div class="tile"><span>باخت‌ها</span><b class="red">${money(rb.usd_loss||0)}</b><i>—</i></div>
  <div class="tile"><span>وضعیت اسکنر</span><b style="font-size:15px" class="${(STATE.scanner||{}).alive?'grn':'red'}">${(STATE.scanner||{}).alive?'فعال':'خاموش'}</b><i>${fnum((STATE.server_time||''))}</i></div>`;
 const rr=(rb.rows||[]);
 document.getElementById('ctlTable').innerHTML=rr.length?`<table class="rtable"><tr><th>SYMBOL</th><th>RES</th><th>PRICE</th><th>LEV</th><th>MARGIN PNL</th><th>USD</th></tr>`+
  rr.map(x=>`<tr><td><b>${fnum(x.symbol)}</b><br><span style="color:var(--mut);font-size:9px">${fnum(x.code)}</span></td>
   <td>${resTag(x.result)}</td><td>${x.pnl!=null?(x.pnl>0?'+':'')+x.pnl+'%':'—'}</td><td>${x.leverage?x.leverage+'×':'—'}</td>
   <td>${x.pnl_lev!=null?(x.pnl_lev>0?'+':'')+x.pnl_lev+'%':'—'}</td>
   <td class="${x.pnl_usd>=0?'grn':'red'}">${x.pnl_usd!=null?money(x.pnl_usd):'—'}</td></tr>`).join('')+'</table>'
  :'<div class="empty">امروز نتیجهٔ بسته‌ای ثبت نشده</div>';
 // switches
 const c=(STATE.control||{}),base=Object.assign({},c.setups||{},PEND.setups||{});
 let html=`<div class="crow"><div style="flex:1"><b>توقف کل انتشار</b><span>master pause</span></div>
  <button class="sw ${(PEND.paused===null?!!c.paused:PEND.paused)?'on':''}" onclick="flipPause()"></button></div>`;
 html+=Object.keys(base).map(k=>`<div class="crow"><div style="flex:1"><b>${fnum(k)}</b><span>${base[k]?'منتشر می‌شود':'مکث‌شده'}</span></div>
  <button class="sw ${base[k]?'on':''}" onclick="flipSetup('${k}')"></button></div>`).join('');
 document.getElementById('ctlSwitches').innerHTML=html;
 // funnel
 const fn=(STATE.funnel||{}).tally||{};
 document.getElementById('ctlFunnel').innerHTML=Object.keys(fn).map(k=>{
  const t=fn[k]||{};return `<b style="font-size:11px;color:var(--tx)">${k}</b><div>`+
   Object.keys(t).filter(kk=>typeof t[kk]==='number'&&t[kk]>0).map(kk=>`<span class="funchip">${kk}: ${t[kk]}</span>`).join('')+'</div>';
 }).join('')||'<span class="ssub">—</span>';
 // notify on new hits
 if(('Notification'in window)&&Notification.permission==='granted'){
  (STATE.hits||[]).forEach(h=>{if(!NOTIF.has(h.code+h.kind)){NOTIF.add(h.code+h.kind);
   try{new Notification('VIVA · '+fnum(h.symbol),{body:fnum(h.detail||h.kind)})}catch(e){}}});
 }
}
function tgl(i){const el=document.getElementById('st3-'+i);el.style.display=el.style.display==='none'?'grid':'none'}
function setFilter(f){FILTER=f;render()}
function renderAlerts(){
 const hits=STATE.hits||[];
 const el=document.getElementById('noteState');
 if(!('Notification'in window)){el.className='note bad';el.textContent='مرورگر شما Notification ندارد.';document.getElementById('noteBtn').style.display='none'}
 else if(Notification.permission==='granted'){el.className='note ok';el.textContent='Notifications enabled — هشدارهای جدید همین‌جا و به‌صورت نوتیف می‌آیند.';document.getElementById('noteBtn').style.display='none'}
 else if(Notification.permission==='denied'){el.className='note bad';el.textContent='Notifications are blocked. Please enable them in your browser settings to receive alerts.';document.getElementById('noteBtn').style.display='none'}
 else{el.className='note';el.textContent='برای دریافت هشدار، اجازهٔ نوتیفیکیشن را بده.'}
 document.getElementById('hitList').innerHTML=hits.length?hits.map(h=>`
  <div class="card"><div class="sr1"><div class="sico up">🔔</div>
   <div><div class="sym" style="font-size:13.5px">${fnum(h.symbol)}</div><div class="ssub">${fnum(h.kind)} • ${fnum(h.time)}</div></div>
   ${h.pnl!=null?`<b class="grn" style="margin-left:auto">${h.pnl>0?'+':''}${h.pnl}%</b>`:''}</div>
   <div class="ssub" style="margin-top:6px">${fnum(h.detail)}</div></div>`).join('')
  :'<div class="empty">🔕 No alerts yet.<br>Signal notifications will appear here.</div>';
}
function askNote(){
 if(!('Notification'in window))return;
 Notification.requestPermission().then(()=>renderAlerts());
}
document.getElementById('noteBtn').onclick=askNote;
function go(t){
 document.querySelectorAll('.page').forEach(p=>p.classList.remove('on'));
 document.getElementById('pg-'+t).classList.add('on');
 document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));
 window.scrollTo(0,0);
}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>go(b.dataset.t));
document.getElementById('refreshBtn').onclick=()=>{const b=document.getElementById('refreshBtn');b.classList.add('busy');load().finally(()=>setTimeout(()=>b.classList.remove('busy'),500))};
/* control api */
function renderCtrl(){render()}
function flipPause(){PEND.paused=!(PEND.paused===null?!!(STATE.control||{}).paused:PEND.paused);render()}
function flipSetup(k){const base=Object.assign({},(STATE.control||{}).setups||{},PEND.setups||{});base[k]=!base[k];PEND.setups=base;render()}
document.addEventListener('change',()=>{});
async function pushControl(){
 const body={paused:PEND.paused,setups:PEND.setups};
 const r=await fetch('/app/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(r.ok){const j=await r.json();STATE.control=j.control;PEND={paused:null,setups:null};render()}
}
setInterval(()=>{if(PEND.paused!==null||PEND.setups)pushControl()},700);
/* detail sheet */
function openDetail(sid){
 const x=(STATE.feed||[]).find(z=>z.signal_id===sid);if(!x)return;
 const dir=x.spot?'LONG':(x.direction||'LONG');
 document.getElementById('sheetbg').style.display='block';
 document.getElementById('sheet').classList.add('on');
 document.getElementById('sheet').innerHTML=`
  <div class="sh1"><div class="sico ${dir==='SHORT'?'dn':'up'}">${dir==='SHORT'?'📉':'📈'}</div>
   <div><span class="sym">${fnum(x.symbol)}</span><span class="code">${fnum(x.code)}</span></div>
   <button class="xbtn" onclick="closeSheet()">✕</button></div>
  <div class="shtags">${resTag(x.result)}<span class="tag PENDING">${fnum(x.source)}</span><span class="tag PENDING">${fnum(x.tf)}</span>${x.spot?'<span class="tag PENDING">SPOT</span>':''}</div>
  <div class="dtiles">
   <div class="dtile"><span>◎ Entry</span><b>${fnum(x.entry)}</b></div>
   <div class="dtile"><span>🛡 Stop Loss</span><b class="red">${fnum(x.sl)}</b></div>
   <div class="dtile"><span>◎ TP1${x.tp1_hit?' ✓':''}</span><b class="grn">${fnum(x.tp1)}</b></div>
   <div class="dtile"><span>◎ TP2${x.tp2_hit?' ✓':''}</span><b class="grn">${fnum(x.tp2)}</b></div>
  </div>
  <div class="drow"><span>⭐ Score</span><b class="amb">${fnum(x.score)}/10</b></div>
  <div class="drow"><span>⚡ Leverage</span><b>${x.leverage?fnum(x.leverage)+'×':'—'}</b></div>
  <div class="drow"><span>💵 Margin</span><b>${x.margin?'$'+Number(x.margin).toFixed(0):'—'}</b></div>
  <div class="drow"><span>PnL (قیمت)</span><b class="${(x.pnl||0)>=0?'grn':'red'}">${x.pnl!=null?(x.pnl>0?'+':'')+x.pnl+'%':'—'}</b></div>
  ${x.pnl_lev!=null?`<div class="drow"><span>PnL (مارجین)</span><b class="${x.pnl_lev>=0?'grn':'red'}">${(x.pnl_lev>0?'+':'')+x.pnl_lev}%</b></div>`:''}
  ${x.pnl_usd!=null?`<div class="drow"><span>PnL (دلاری)</span><b class="${x.pnl_usd>=0?'grn':'red'}">${money(x.pnl_usd)}</b></div>`:''}
  <div class="dchart"><img loading="lazy" src="/app/api/chart/${encodeURIComponent(sid)}" alt="chart ${fnum(x.symbol)}" onerror="this.style.display='none';this.parentNode.insertAdjacentHTML('beforeend','<div class=empty style=border:0;background:none>📊 نمودار این سیگنال در دسترس نیست</div>')"></div>
  ${x.telegram_text?`<div class="explain">${x.telegram_text}</div>`:(x.summary?`<div class="explain">${fnum(x.summary)}</div>`:'')}
  <div class="ssub" style="margin-top:8px">🕓 ${ago(x.time)} • ${tehran(x.time)}</div>`;
}
function closeSheet(){document.getElementById('sheetbg').style.display='none';document.getElementById('sheet').classList.remove('on')}
load();setInterval(pollV,10000);setInterval(pollPrices,10000);setInterval(load,300000);let TOUCH={};
/* r39 (Viva 09-26, «اپ آپدیت نمیشه»): on resume the PWA used to sit on the
   frozen snapshot until the next 60s tick — refresh the moment it returns. */
document.addEventListener('visibilitychange',()=>{if(!document.hidden)load()});
window.addEventListener('pageshow',e=>{if(e.persisted)load()});
</script></body></html>"""

