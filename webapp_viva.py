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
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, make_response, redirect, request, send_file

TEHRAN = ZoneInfo("Asia/Tehran")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ICON_DIR = os.path.join(_BASE_DIR, "assets", "app_icons")
_FONT_DIR = os.path.join(_BASE_DIR, "assets", "fonts")

DEFAULT_SETUPS = ["TLBREAK", "ALBROX", "PINWALLQ", "PINVAL", "TECHCLASSIC", "SPOT"]
ACTIVE_WINDOW_DAYS = 30          # «ستاپی که دوماهه خاموشه» → archive

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
    return dict(demo=True, feed=feed, chains=chains, analytics=analytics, hits=hits,
                control=control_state(), scanner=dict(alive=True, mode="نمایشی"),
                server_time=datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M"))


_FEED_SQL = """
    SELECT signal_id, symbol, source, strategy_fa, direction, entry, sl, tp1, tp2,
           result, pnl_pct, score, trade_style, public_code, trigger_timeframe,
           created_at, closed_at, confirmed, partial_win, market_json,
           tp1_hit, tp1_hit_at, sl_moved_to_be, description, entry_conditions,
           confirmations, setup_code, target_state_json
    FROM signals
    ORDER BY created_at DESC
    LIMIT 60
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


def _fetch_state() -> Dict[str, Any]:
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
            c.execute(_FEED_SQL)
            for r in c.fetchall():
                (sid, symbol, source, fa, direction, entry, sl, tp1, tp2, result, pnl, score,
                 style, code, tf, created_at, closed_at, confirmed, partial_win, market_json,
                 tp1_hit, tp1_hit_at, sl_moved, description, entry_conditions, confirmations,
                 setup_code, target_state_json) = r
                code = str(code or "")
                is_spot = _row_is_spot(code, source, market_json)
                res = "WIN" if (result == "WIN" or partial_win) else str(result or "PENDING")
                _acc = spot if is_spot else fut
                _acc["total"] += 1
                if res == "WIN":
                    _acc["wins"] += 1
                elif res == "LOSS":
                    _acc["losses"] += 1
                lh1, lh2 = _ladder_hits(target_state_json)
                tp1_hit = bool(tp1_hit or lh1)
                tp2_hit = bool(lh2)
                feed.append(dict(
                    signal_id=str(sid or ""), symbol=symbol, source=source, strategy_fa=fa,
                    direction=direction, entry=_fmt_price(entry), sl=_fmt_price(sl),
                    tp1=_fmt_price(tp1), tp2=_fmt_price(tp2), result=res,
                    pnl=(float(pnl) if pnl is not None else None), score=score,
                    style=style, code=code, tf=str(tf or "").upper(),
                    time=str(created_at or ""), spot=is_spot, confirmed=bool(confirmed),
                    tp1_hit=tp1_hit, tp2_hit=tp2_hit,
                    summary=str(description or fa or "")[:220],
                ))
            # ── winrate per setup: only setups ACTIVE in the last window
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
                ORDER BY MAX(created_at) DESC
            """)
            for r in c.fetchall():
                (name, fa, total, wins, losses, pending, avg_pnl, best, worst, avg_score, last) = r
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
                    best=(round(float(best), 2) if best is not None else None),
                    worst=(round(float(worst), 2) if worst is not None else None),
                    avg_score=(round(float(avg_score), 1) if avg_score is not None else None),
                    last=_rel_fa(last_iso), active=active,
                )
                (rows_active if active else rows_archive).append(row)
            # ── hit notifications (TP/SL/close/confirm lifecycle feed)
            c.execute("""
                SELECT symbol, public_code, tp1_hit_at, closed_at, result, pnl_pct,
                       created_at, confirmed_at, partial_win, tp1, tp2, sl
                FROM signals
                WHERE tp1_hit=TRUE OR result IN ('WIN','LOSS')
                   OR (confirmed=TRUE AND result='PENDING')
                ORDER BY COALESCE(closed_at, tp1_hit_at, confirmed_at, created_at) DESC
                LIMIT 40
            """)
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
                c2.execute("""
                    SELECT signal_id, symbol, source, direction, entry, sl, score,
                           public_code, trigger_timeframe, created_at
                    FROM signals
                    WHERE confirmed=TRUE AND result='PENDING' AND closed_at IS NULL
                    ORDER BY created_at DESC LIMIT 12
                """)
                for r in c2.fetchall():
                    (sid, symbol, source, direction, entry, sl, score, code, tf, created_at) = r
                    code = str(code or "")
                    chains.insert(0, dict(
                        signal_id=str(sid or ""), symbol=symbol, badge=str(source or ""),
                        direction=direction, status="CONFIRMED", score=score,
                        zone=_fmt_price(entry), updates=0, code=code,
                        tf=str(tf or "").upper(),
                        spot=_row_is_spot(code, source, ""),
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
        try:
            from flask import current_app
            thr = current_app.config.get("VIVA_SCANNER_THREAD")
            if thr is not None:
                scanner["alive"] = bool(thr.is_alive())
        except Exception:
            pass
        return dict(demo=False, feed=feed, chains=chains, analytics=analytics, hits=hits,
                    control=control_state(), scanner=scanner,
                    server_time=datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M"))
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
    """Rebuild the renderer's candidate from a `signals` row (live chart)."""
    from analysis.models import SignalCandidate
    is_spot = _row_is_spot(str(row.get("public_code") or ""), row.get("source"), row.get("market_json"))
    entry = float(row.get("entry") or 0)
    sl = float(row.get("sl") or 0)
    tp1 = float(row.get("tp1") or 0)
    tp2 = float(row.get("tp2") or entry * 1.02)
    def _rr(t: float) -> float:
        try:
            return round(abs(t - entry) / max(1e-12, abs(entry - sl)), 2)
        except Exception:
            return 0.0
    md = {
        "public_code": str(row.get("public_code") or ""),
        "market": "SPOT" if is_spot else "FUTURES",
        "target_ladder": {"targets": [tp1, tp2], "weights": [40, 30, 30]},
        "tool_entry_ts": str(row.get("confirmed_at") or row.get("created_at") or ""),
        "confirm_tf": str(row.get("trigger_timeframe") or ""),
    }
    return SignalCandidate(
        signal_id=str(row.get("signal_id") or ""), symbol=str(row.get("symbol") or ""),
        style=str(row.get("trade_style") or "SWING"),
        setup_code=str(row.get("setup_code") or row.get("source") or ""),
        setup_name=str(row.get("setup_code") or row.get("source") or ""),
        strategy_fa=str(row.get("strategy_fa") or ""), direction=str(row.get("direction") or "LONG"),
        score=int(row.get("score") or 0), status="CONFIRMED" if row.get("confirmed") else "WATCH",
        entry_zone_bottom=entry * 0.999, entry_zone_top=entry * 1.001, planned_entry=entry,
        sl=sl, tp1=tp1, tp2=tp2, rr_tp1=_rr(tp1), rr_tp2=_rr(tp2),
        bias="BULL" if str(row.get("direction")) == "LONG" else "BEAR",
        trigger_timeframe=str(row.get("trigger_timeframe") or "4h"),
        evidence=[], confirmations=[], warnings=[], mandatory_gates={},
        market={"asset_class": "CRYPTO", "venue": "BYBIT"}, metadata=md,
        created_at=str(row.get("created_at") or ""),
        confirmed_at=str(row.get("confirmed_at") or ""),
    )


_CHART_CACHE: Dict[str, Any] = {"key": "", "png": b"", "at": 0.0}


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
    if _CHART_CACHE["key"] == sid and _CHART_CACHE["png"] and now - _CHART_CACHE["at"] < 90:
        return _CHART_CACHE["png"]
    try:
        mirror = _app_mirror(sid, "chart") or {}
        fid = str(mirror.get("fid") or "")
        if fid:
            data = _tg_file_bytes(fid)
            if data:
                _CHART_CACHE.update(key=sid, png=data, at=now)
                return data
    except Exception:
        pass
    try:
        from database.db import db_cursor
        with db_cursor() as c:
            c.execute("""
                SELECT signal_id, symbol, source, strategy_fa, direction, entry, sl, tp1, tp2,
                       score, trade_style, public_code, trigger_timeframe, created_at,
                       confirmed_at, confirmed, market_json, setup_code
                FROM signals WHERE signal_id=%s
            """, (sid,))
            rows = c.fetchall()
        if not rows:
            return None
        cols = ["signal_id", "symbol", "source", "strategy_fa", "direction", "entry", "sl",
                "tp1", "tp2", "score", "trade_style", "public_code", "trigger_timeframe",
                "created_at", "confirmed_at", "confirmed", "market_json", "setup_code"]
        row = dict(zip(cols, rows[0]))
        from data.fetcher import get_klines
        tf = str(row.get("trigger_timeframe") or "4h")
        df = get_klines(str(row.get("symbol")), tf, 170, closed_only=False, use_cache=True)
        if df is None or len(df) < 40:
            return None
        cand = _candidate_from_row(row)
        from bot.messages_v7 import generate_chart
        png = generate_chart(df, cand, confirmed=bool(row.get("confirmed")))
        if png:
            _CHART_CACHE.update(key=sid, png=png, at=now)
        return png
    except Exception as exc:
        print(f"app chart render failed {sid}: {exc}")
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
                       confirmations, setup_code, target_state_json
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
                "entry_conditions", "confirmations", "setup_code", "target_state_json"]
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
        )
    except Exception as exc:
        print(f"app signal detail failed {sid}: {exc}")
        return None


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
    return send_file(io.BytesIO(png), mimetype="image/png", download_name=f"{sid}.png")


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
    e.respondWith(caches.open('viva-shell-v2').then(async c => {
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
 --bg:#0b0e14;--panel:#141924;--panel2:#1a212e;--line:rgba(232,182,76,.15);--line2:#232b3a;
 --gold:#e8b64c;--gold2:#c9962f;--text:#ece7dd;--muted:#8b93a1;
 --long:#1fae7c;--short:#e5484d;--tp1:#2fbf9b;--tp2:#4c8dff;--stop:#e5484d;--entry:#98a2b3;
 --amber:#e2a336;--chip:#1d2532;
 --sat:env(safe-area-inset-top,0px);--sab:env(safe-area-inset-bottom,0px);
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{background:radial-gradient(900px 420px at 80% -8%,#141b28 0%,var(--bg) 60%);color:var(--text);
 font-family:Vazirmatn,Segoe UI,Tahoma,sans-serif;font-size:14px;padding-bottom:calc(74px + var(--sab))}
/* ── header ── */
header{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:10px;padding:calc(10px + var(--sat)) 14px 10px;
 background:rgba(11,14,20,.88);backdrop-filter:blur(16px);border-bottom:1px solid var(--line)}
.hamb{background:none;border:0;color:var(--gold);cursor:pointer;padding:4px;display:flex}
header img{width:34px;height:34px;border-radius:9px}
.ht{flex:1;min-width:0}
.ht b{display:block;font-size:14.5px;letter-spacing:.05em;color:var(--gold)}
.ht span{font-size:10.5px;color:var(--muted)}
.live{display:flex;align-items:center;gap:6px;font-size:10.5px;color:var(--muted);background:var(--chip);padding:5px 9px;border-radius:20px;border:1px solid var(--line2)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--long);animation:pulse 1.8s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(31,174,124,.55)}70%{box-shadow:0 0 0 7px rgba(31,174,124,0)}100%{box-shadow:0 0 0 0 rgba(31,174,124,0)}}
main{padding:12px 12px 8px;max-width:680px;margin:0 auto}
.page{display:none}.page.on{display:block}
.demo{margin:0 0 10px;text-align:center;font-size:11px;color:var(--amber);background:rgba(226,163,54,.08);border:1px dashed rgba(226,163,54,.4);border-radius:10px;padding:6px}
.sect{display:flex;align-items:center;justify-content:space-between;margin:14px 2px 8px}
.sect h2{font-size:13px;color:var(--gold);letter-spacing:.04em}
.sect small{color:var(--muted);font-size:10.5px}
/* ── cards ── */
.card{background:linear-gradient(180deg,var(--panel) 0%,#121722 100%);border:1px solid var(--line2);border-radius:18px;padding:13px 14px;margin-bottom:10px;box-shadow:0 10px 28px rgba(0,0,0,.32);cursor:pointer;transition:transform .12s}
.card:active{transform:scale(.985);border-color:var(--line)}
.row1{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.sym{font-size:15.5px;font-weight:800;letter-spacing:.02em}
.badge{font-size:10px;font-weight:700;color:var(--gold);border:1px solid rgba(232,182,76,.4);background:rgba(232,182,76,.07);padding:2.5px 8px;border-radius:8px}
.chip{font-size:10px;font-weight:700;padding:2.5px 8px;border-radius:8px}
.chip.LONG{color:#39d9a4;background:rgba(31,174,124,.12);border:1px solid rgba(31,174,124,.35)}
.chip.SHORT{color:#ff7b80;background:rgba(229,72,77,.12);border:1px solid rgba(229,72,77,.35)}
.chip.SPOT{color:#9db7ff;background:rgba(76,141,255,.12);border:1px solid rgba(76,141,255,.35)}
.chip.score{color:var(--text);background:var(--chip);border:1px solid var(--line2)}
.hitflag{font-size:9.5px;font-weight:800;color:var(--tp1);background:rgba(47,191,155,.12);border:1px solid rgba(47,191,155,.4);padding:2px 7px;border-radius:8px}
.pills{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}
.pill{display:flex;align-items:center;justify-content:space-between;background:#0f141d;border:1px solid var(--line2);border-radius:10px;padding:7px 10px}
.pill i{font-style:normal;font-size:9.5px;font-weight:800;letter-spacing:.04em}
.pill b{font-size:12px;font-weight:700}
.pill.entry i{color:var(--entry)} .pill.stop i{color:var(--stop)}
.pill.tp1 i{color:var(--tp1)} .pill.tp2 i{color:var(--tp2)}
.pill.hit{border-color:rgba(47,191,155,.45)}
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
.sumline{font-size:11.5px;color:#b9c0cc;line-height:1.8;margin-top:8px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
/* ── perf ── */
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}
.tile{background:var(--panel);border:1px solid var(--line2);border-radius:14px;padding:11px 8px;text-align:center}
.tile b{display:block;font-size:17px}
.tile span{font-size:10px;color:var(--muted)}
.tile.gold b{color:var(--gold)} .tile.green b{color:#39d9a4} .tile.red b{color:#ff7b80}
.wr{height:6px;background:#0b0e14;border-radius:6px;margin-top:8px;overflow:hidden;border:1px solid var(--line2)}
.wr i{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,var(--gold2),var(--gold));transition:width .7s}
.strat{margin-bottom:8px}
.strat .nm{font-size:13px;font-weight:700;flex:1}
.mini{font-size:10px;color:var(--muted)}
.pnlp{color:#39d9a4}.pnln{color:#ff7b80}
.sf{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:4px}
.sf .tile{text-align:right;padding:12px}
.sf .tile small{display:block;margin-bottom:3px}
details.archive{margin:6px 0}
details.archive summary{cursor:pointer;font-size:11.5px;color:var(--muted);background:var(--chip);border:1px dashed var(--line2);border-radius:10px;padding:8px 12px;list-style:none}
details.archive summary::-webkit-details-marker{display:none}
details.archive .strat{opacity:.75}
/* ── hits ── */
.hitc{display:flex;align-items:center;gap:11px}
.hico{width:38px;height:38px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}
.hico.tp1,.hico.tp2{background:rgba(47,191,155,.13);border:1px solid rgba(47,191,155,.4)}
.hico.sl{background:rgba(229,72,77,.13);border:1px solid rgba(229,72,77,.4)}
.hico.win{background:rgba(31,174,124,.15);border:1px solid rgba(31,174,124,.45)}
.hico.loss{background:rgba(229,72,77,.13);border:1px solid rgba(229,72,77,.4)}
.hico.confirm{background:rgba(76,141,255,.13);border:1px solid rgba(76,141,255,.4)}
.hb{flex:1;min-width:0}
.hb b{font-size:13px;display:block}
.hb span{font-size:10.5px;color:var(--muted)}
.hright{text-align:left}
/* ── control ── */
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
/* ── drawer ── */
.backdrop{position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(3px);opacity:0;pointer-events:none;transition:.25s;z-index:80}
.backdrop.on{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;bottom:0;right:-88%;width:82%;max-width:320px;z-index:90;background:linear-gradient(180deg,#141924,#0e1219);
 border-left:1px solid var(--line);transition:right .28s cubic-bezier(.2,.8,.25,1);display:flex;flex-direction:column;box-shadow:-24px 0 60px rgba(0,0,0,.5)}
.drawer.on{right:0}
.dr-h{padding:calc(18px + var(--sat)) 18px 16px;border-bottom:1px solid var(--line2);display:flex;align-items:center;gap:12px}
.dr-h img{width:48px;height:48px;border-radius:13px;box-shadow:0 6px 18px rgba(232,182,76,.22)}
.dr-h b{display:block;font-size:14.5px;color:var(--gold);letter-spacing:.05em}
.dr-h span{font-size:10.5px;color:var(--muted)}
.dr-body{flex:1;overflow-y:auto;padding:10px}
.dr-item{display:flex;align-items:center;gap:12px;padding:12px 12px;border-radius:12px;color:#c9cfda;cursor:pointer;font-size:13.5px;border:1px solid transparent}
.dr-item:active{background:rgba(232,182,76,.06)}
.dr-item.on{background:rgba(232,182,76,.09);border-color:rgba(232,182,76,.22);color:var(--gold)}
.dr-item svg{width:20px;height:20px;flex-shrink:0}
.dr-item .cnt{margin-right:auto;font-size:10px;background:var(--short);color:#fff;border-radius:10px;padding:1.5px 7px;font-weight:800}
.dr-sep{height:1px;background:var(--line2);margin:8px 12px}
.dr-f{padding:12px 16px calc(14px + var(--sab));border-top:1px solid var(--line2);font-size:10.5px;color:var(--muted);line-height:2}
.dr-f b{color:#39d9a4}
.dr-f .out{color:#ff7b80;cursor:pointer}
/* ── bottom nav ── */
nav{position:fixed;bottom:0;right:0;left:0;z-index:60;display:flex;background:rgba(11,14,20,.94);backdrop-filter:blur(18px);border-top:1px solid var(--line);padding:8px 10px calc(8px + var(--sab))}
nav button{flex:1;background:none;border:0;color:var(--muted);font-family:inherit;font-size:10.5px;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;padding:4px;position:relative}
nav button svg{width:21px;height:21px}
nav button.on{color:var(--gold)}
nav .bdg{position:absolute;top:0;left:18%;background:var(--short);color:#fff;font-size:9px;font-weight:800;border-radius:9px;padding:1px 5px}
.empty{text-align:center;color:var(--muted);font-size:12px;padding:26px 0}
.refresh{position:fixed;top:calc(8px + var(--sat));left:12px;z-index:70;font-size:10px;color:var(--muted);background:rgba(11,14,20,.7);padding:3px 8px;border-radius:8px;opacity:0;transition:.3s}
.refresh.on{opacity:1}
/* ── detail page ── */
.dpage{position:fixed;inset:0;z-index:100;background:var(--bg);overflow-y:auto;display:none}
.dpage.on{display:block}
.dhead{position:sticky;top:0;display:flex;align-items:center;gap:10px;padding:calc(10px + var(--sat)) 12px 10px;background:rgba(11,14,20,.92);backdrop-filter:blur(16px);border-bottom:1px solid var(--line);z-index:5}
.backb{background:none;border:0;color:var(--gold);cursor:pointer;padding:4px;display:flex}
.dbody{padding:12px 12px 30px;max-width:680px;margin:0 auto}
.chartbox{background:#fff;border-radius:16px;overflow:hidden;border:1px solid var(--line2);box-shadow:0 14px 40px rgba(0,0,0,.4)}
.chartbox img{display:block;width:100%;height:auto}
.chartload{display:flex;align-items:center;justify-content:center;height:220px;color:var(--muted);font-size:12px;gap:8px}
.spin{width:16px;height:16px;border:2px solid var(--line2);border-top-color:var(--gold);border-radius:50%;animation:sp 1s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.dsec{margin-top:12px}
.dsec h3{font-size:12.5px;color:var(--gold);margin-bottom:8px;letter-spacing:.03em}
.prose{font-size:12.5px;line-height:2;color:#c9cfda;background:var(--panel);border:1px solid var(--line2);border-radius:14px;padding:12px 14px}
.prose.tgmsg{white-space:pre-wrap;word-break:break-word;font-size:13px}
.prose.tgmsg b{color:#fff}
.prose.tgmsg i,.prose.tgmsg code{color:#8ab4ff}
.conf{display:flex;align-items:center;gap:8px;font-size:12px;color:#c9cfda;padding:6px 2px}
.conf svg{width:15px;height:15px;color:var(--long);flex-shrink:0}
.tl{position:relative;padding-right:18px}
.tl::before{content:'';position:absolute;right:5px;top:6px;bottom:6px;width:2px;background:var(--line2);border-radius:2px}
.tli{position:relative;padding:7px 0}
.tli::before{content:'';position:absolute;right:-17px;top:13px;width:9px;height:9px;border-radius:50%;background:var(--gold);box-shadow:0 0 0 3px rgba(232,182,76,.15)}
.tli b{font-size:12.5px;display:block}
.tli span{font-size:10.5px;color:var(--muted)}
.sk{background:linear-gradient(100deg,var(--panel) 40%,#1c2432 50%,var(--panel) 60%);background-size:200% 100%;animation:sh 1.4s infinite;border-radius:14px;height:14px;margin-bottom:8px}
@keyframes sh{to{background-position:-200% 0}}
</style></head><body>
<div class="refresh" id="refresh">به‌روزرسانی…</div>
<header>
 <button class="hamb" onclick="drawer(true)" aria-label="منو"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h10"/></svg></button>
 <img src="/app/icons/icon-192.png" alt="">
 <div class="ht"><b>VIVA SIGNALS PRO</b><span>فید زنده • رصد سیگنال • کنترل</span></div>
 <div class="live"><span class="dot" id="dot"></span><span id="clock">—</span></div>
</header>

<div class="backdrop" id="backdrop" onclick="drawer(false)"></div>
<aside class="drawer" id="dr">
 <div class="dr-h">
  <img src="/app/icons/icon-192.png" alt="">
  <div><b>VIVA SIGNALS PRO</b><span>پنل مدیریت سیگنال‌ها</span></div>
 </div>
 <div class="dr-body">
  <div class="dr-item on" data-p="feed" onclick="go('feed')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>فید زندهٔ سیگنال‌ها</div>
  <div class="dr-item" data-p="hits" onclick="go('hits')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/></svg>اعلان برخوردها <span class="cnt" id="hitsBdg" style="display:none"></span></div>
  <div class="dr-item" data-p="perf" onclick="go('perf')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>عملکرد ستاپ‌ها</div>
  <div class="dr-item" data-p="ctrl" onclick="go('ctrl')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 8h10M18 8h2M4 16h2M10 16h10"/><circle cx="16" cy="8" r="2"/><circle cx="8" cy="16" r="2"/></svg>کنترل ربات</div>
  <div class="dr-sep"></div>
  <div class="dr-item" onclick="go('about')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/></svg>درباره و راهنما</div>
  <div class="dr-item" onclick="logout()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg><span style="color:#ff7b80">خروج از حساب</span></div>
 </div>
 <div class="dr-f">موتور اسکن: <b id="engState">—</b><br>زمان سرور: <span id="srvT">—</span> • نسخهٔ ۲٫۰</div>
</aside>

<main>
<div class="demo" id="demo" style="display:none">حالت نمایشی — متصل به دیتابیس زنده نیست</div>

<section class="page on" id="page-feed">
  <div class="sect"><h2>⛓ زنجیره‌های رصد فعال</h2><small id="chainsN"></small></div>
  <div id="chains"></div>
  <div class="sect"><h2>📡 فید سیگنال‌ها</h2><small>برای رصد، روی هر کارت بزن</small></div>
  <div id="feed"></div>
</section>

<section class="page" id="page-hits">
  <div class="sect"><h2>🎯 اعلان برخوردها</h2><small>TP / استاپ / نتیجهٔ نهایی</small></div>
  <div id="hits"></div>
</section>

<section class="page" id="page-perf">
  <div class="tiles" id="sumTiles"></div>
  <div class="sect"><h2>🏆 ستاپ‌های فعال</h2><small>۳۰ روز اخیر</small></div>
  <div id="stratsA"></div>
  <details class="archive" id="archBox">
    <summary>🗄 ستاپ‌های خاموش‌شده — آمار قدیمی (<span id="archN">۰</span>)</summary>
    <div id="stratsX" style="margin-top:8px"></div>
  </details>
  <div class="sect"><h2>💎 اسپات در برابر فیوچرز</h2></div>
  <div class="sf" id="sf"></div>
</section>

<section class="page" id="page-ctrl">
  <div class="sect"><h2>🎛 کنترل انتشار</h2><small id="ctrlSaved"></small></div>
  <div class="card master" style="cursor:default">
    <div class="toggle-row">
      <div class="tl"><b>توقف کل سیگنال‌های جدید</b><span>مانیتور زنجیره‌های باز ادامه دارد؛ فقط انتشارِ جدید متوقف می‌شود</span></div>
      <div class="sw" id="swPause" onclick="flipPause()"></div>
    </div>
  </div>
  <div class="sect"><h2>⚙️ ستاپ‌ها</h2><small>روشن/خاموش هر ستاپ</small></div>
  <div class="card" style="cursor:default" id="setups"></div>
  <button class="btn" onclick="saveCtrl()">ذخیرهٔ تنظیمات کنترل</button>
  <div class="statline" id="botstat"></div>
  <p class="hint">راهنما: «توقف کل» کلید اضطراری است — هیچ سیگنال جدیدی منتشر نمی‌شود تا وقتی خاموشش کنی. خاموش‌کردن یک ستاپ فقط مانع انتشارِ همان ستاپ می‌شود. تغییرات تا ۵ ثانیه بعد روی ربات اعمال می‌شود.</p>
</section>

<section class="page" id="page-about">
  <div class="sect"><h2>📖 دربارهٔ اپ</h2></div>
  <div class="card" style="cursor:default">
   <p class="hint" style="margin:0">
    <b style="color:var(--gold)">VIVA SIGNALS PRO</b> — آینهٔ کامل کانال تلگرام + داشبورد عملکرد + کنترل از راه دور.<br>
    • فید زنده = همهٔ سیگنال‌هایی که به کانال می‌روند، با چارت و اعدادِ همان سیگنال.<br>
    • روی هر کارت بزن → صفحهٔ رصد همان سیگنال: چارتِ زندهٔ ربات، توضیحات، شرایط ورود، تأییدها و تایم‌لاین کامل.<br>
    • تب «اعلان برخوردها» = TP1/TP2، استاپ و نتیجهٔ نهایی هر معامله به‌ترتیب زمان.<br>
    • «عملکرد ستاپ‌ها» فقط ستاپ‌های ۳۰ روز اخیر را مقایسه می‌کند؛ ستاپ‌های خاموش در آرشیو هستند.<br>
    • نصب روی آیفون: Share ← Add to Home Screen. نصب اندروید: فایل APK.<br>
    • امنیت: کل اپ پشت رمز مدیر است؛ نشست ۳۰ روز معتبر است.
   </p>
  </div>
</section>
</main>

<!-- ── صفحات داخلی (جزئیات سیگنال) ── -->
<div class="dpage" id="detail">
 <div class="dhead">
  <button class="backb" onclick="closeDetail()" aria-label="بازگشت"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg></button>
  <div class="ht"><b id="dTitle">—</b><span id="dSub">رصد زندهٔ سیگنال</span></div>
  <span class="res PENDING" id="dRes">—</span>
 </div>
 <div class="dbody" id="dBody"></div>
</div>

<nav>
 <button class="on" data-p="feed" onclick="go('feed')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>فید زنده</button>
 <button data-p="hits" onclick="go('hits')" style="position:relative"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/></svg>برخوردها<span class="bdg" id="navBdg" style="display:none"></span></button>
 <button data-p="perf" onclick="go('perf')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>عملکرد</button>
 <button data-p="ctrl" onclick="go('ctrl')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 8h10M18 8h2M4 16h2M10 16h10"/><circle cx="16" cy="8" r="2"/><circle cx="8" cy="16" r="2"/></svg>کنترل</button>
</nav>

<script>
const $=q=>document.querySelector(q);
let STATE=null;
const fnum=v=>{if(v===null||v===undefined||v==='')return '—';return String(v)};
function tehran(iso){try{const d=new Date(iso);if(isNaN(d))return iso||'';return d.toLocaleString('fa-IR',{timeZone:'Asia/Tehran',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}catch(e){return iso||''}}
function resFa(r){return {PENDING:'در جریان',WIN:'برد ✦',LOSS:'باخت',CANCELLED:'ابطال'}[r]||r}
function drawer(on){$('#dr').classList.toggle('on',on);$('#backdrop').classList.toggle('on',on)}
function go(p){drawer(false);document.querySelectorAll('.page').forEach(x=>x.classList.remove('on'));$('#page-'+p).classList.add('on');
 document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.p===p));
 document.querySelectorAll('.dr-item').forEach(d=>d.classList.toggle('on',d.dataset.p===p));window.scrollTo(0,0)}
function logout(){fetch('/app/logout',{method:'POST'}).finally(()=>location.href='/app/login')}
function feedCard(s){
 const dir=s.spot?'LONG':(s.direction||'');
 return `<div class="card" onclick="openDetail('${(s.signal_id||'').replace(/'/g,'')}')">
  <div class="row1"><span class="sym">${fnum(s.symbol)}</span>
   <span class="badge">${fnum(s.source)}</span>
   ${dir?`<span class="chip ${dir}">${dir==='LONG'?'خرید 🟢':'فروش 🔴'}</span>`:''}
   ${s.spot?'<span class="chip SPOT">اسپات</span>':''}
   ${s.tf?`<span class="chip score">${fnum(s.tf)}</span>`:''}
   ${s.score?`<span class="chip score">★ ${s.score}/10</span>`:''}</div>
  <div class="pills">
   <div class="pill entry"><i>ورود</i><b>${fnum(s.entry)}</b></div>
   <div class="pill stop"><i>استاپ</i><b>${fnum(s.sl)}</b></div>
   <div class="pill tp1 ${s.tp1_hit?'hit':''}"><i>TP1</i><b>${fnum(s.tp1)}${s.tp1_hit?' ✓':''}</b></div>
   <div class="pill tp2 ${s.tp2_hit?'hit':''}"><i>TP2</i><b>${fnum(s.tp2)}${s.tp2_hit?' ✓':''}</b></div></div>
  ${s.summary?`<div class="sumline">${fnum(s.summary)}</div>`:''}
  <div class="ftr"><span class="code">${fnum(s.code)}</span>
   <span class="res ${s.result}">${resFa(s.result)}${s.pnl!==null&&s.pnl!==undefined?` ${s.pnl>0?'+':''}${s.pnl}%`:''}</span>
   <span class="time">${tehran(s.time)}</span></div></div>`}
function chainCard(c){
 const dir=c.spot?'LONG':(c.direction||'');
 return `<div class="card chain" onclick="openDetail('${(c.signal_id||'').replace(/'/g,'')}')">
  <div class="row1"><span class="sym">${fnum(c.symbol)}</span>
   <span class="badge">${fnum(c.badge)}</span>
   ${dir?`<span class="chip ${dir}">${dir==='LONG'?'خرید 🟢':'فروش 🔴'}</span>`:''}
   ${c.spot?'<span class="chip SPOT">اسپات</span>':''}
   ${c.tf?`<span class="chip score">${fnum(c.tf)}</span>`:''}
   ${c.score?`<span class="chip score">★ ${c.score}/10</span>`:''}</div>
  <div class="row1"><span class="mini">ناحیه: ${fnum(c.zone)}</span>
   ${c.updates?`<span class="upd">آپدیت ${c.updates}</span>`:''}</div>
  <div class="ftr"><span class="code">${fnum(c.code)}</span><span class="res PENDING">${fnum(c.status)}</span></div></div>`}
const HITMETA={tp1:['🎯','هدف اول هیت شد'],tp2:['🎯','هدف دوم هیت شد'],sl:['🛑','استاپ هیت شد'],win:['✅','برد'],loss:['❌','باخت'],confirm:['⚡','تأیید جدید']};
function hitCard(h){const [ic,label]=HITMETA[h.kind]||['•',''];
 return `<div class="card" style="cursor:default"><div class="hitc">
  <div class="hico ${h.kind}">${ic}</div>
  <div class="hb"><b>${fnum(h.symbol)} — ${label}</b><span>${fnum(h.detail)} • ${fnum(h.code)}</span></div>
  <div class="hright"><b class="${(h.pnl??0)>=0?'pnlp':'pnln'}">${h.pnl!==null&&h.pnl!==undefined?((h.pnl>0?'+':'')+h.pnl+'%'):''}</b><br><span class="time">${tehran(h.time)}</span></div>
 </div></div>`}
function stratCard(r){return `
 <div class="card strat" style="cursor:default">
  <div class="row1"><span class="nm">${fnum(r.fa)}</span><span class="badge">${fnum(r.name)}</span>
   ${r.avg_score?`<span class="chip score">★ ${r.avg_score}</span>`:''}</div>
  <div class="row1"><span class="mini">${r.wins}W / ${r.losses}L / ${r.pending} باز • بهترین ${r.best??'—'}% • بدترین ${r.worst??'—'}% • ${r.last||''}</span>
   <span style="flex:1"></span><b class="${(r.avg_pnl??0)>=0?'pnlp':'pnln'}">${r.avg_pnl!==null&&r.avg_pnl!==undefined?(r.avg_pnl>0?'+':'')+r.avg_pnl+'%':'—'}</b></div>
  <div class="wr"><i style="width:${Math.max(2,Math.min(100,r.wr||0))}%"></i></div>
  <div class="mini" style="margin-top:3px">وین‌ریت ${r.wr}% از ${r.wins+r.losses} سیگنال بسته‌شده</div></div>`}
function render(){
 if(!STATE)return;
 $('#demo').style.display=STATE.demo?'block':'none';
 $('#clock').textContent=STATE.server_time||'—';
 $('#srvT').textContent=STATE.server_time||'—';
 $('#engState').textContent=(STATE.scanner&&STATE.scanner.alive)?'فعال ✅':'خاموش ⛔';
 $('#dot').style.background=(STATE.scanner&&STATE.scanner.alive)?'#1fae7c':'#e5484d';
 const chains=STATE.chains||[],feed=STATE.feed||[],hits=STATE.hits||[];
 $('#chains').innerHTML=chains.length?chains.map(chainCard).join(''):'<div class="empty">زنجیرهٔ فعالی نیست</div>';
 $('#feed').innerHTML=feed.length?feed.map(feedCard).join(''):'<div class="empty">سیگنالی ثبت نشده</div>';
 $('#chainsN').textContent=chains.length?`${chains.length} فعال`:'';
 const nB=$('#navBdg'),hB=$('#hitsBdg');
 if(hits.length){nB.textContent=hits.length;nB.style.display='block';hB.textContent=hits.length;hB.style.display='inline'}
 else{nB.style.display='none';hB.style.display='none'}
 $('#hits').innerHTML=hits.length?hits.map(hitCard).join(''):'<div class="empty">برخوردی ثبت نشده</div>';
 const a=STATE.analytics||{},sm=a.summary||{};
 $('#sumTiles').innerHTML=`
  <div class="tile gold"><b>${sm.total??'—'}</b><span>کل سیگنال‌ها</span></div>
  <div class="tile green"><b>${sm.wins??'—'}</b><span>برد</span></div>
  <div class="tile red"><b>${sm.losses??'—'}</b><span>باخت</span></div>
  <div class="tile gold"><b>%${sm.winrate??'—'}</b><span>وین‌ریت کل</span></div>
  <div class="tile gold"><b>${sm.avg_pnl??'—'}%</b><span>میانگین PnL</span></div>
  <div class="tile"><b>${(a.rows_active||[]).length}</b><span>ستاپ فعال</span></div>`;
 const act=a.rows_active||[],arc=a.rows_archive||[];
 $('#stratsA').innerHTML=act.length?act.map(stratCard).join(''):'<div class="empty">ستاپ فعالی در ۳۰ روز اخیر نیست</div>';
 $('#stratsX').innerHTML=arc.map(stratCard).join('');
 $('#archN').textContent=arc.length;
 $('#archBox').style.display=arc.length?'block':'none';
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
/* ── صفحهٔ جزئیات سیگنال ── */
let CUR=null;
async function openDetail(sid){
 if(!sid)return;
 $('#detail').classList.add('on');document.body.style.overflow='hidden';
 $('#dBody').innerHTML=`<div class="chartbox"><div class="chartload"><div class="spin"></div> در حال آماده‌سازی چارت زندهٔ ربات…</div></div>
  <div class="dsec"><div class="sk" style="width:60%"></div><div class="sk"></div><div class="sk" style="width:80%"></div></div>`;
 $('#dTitle').textContent='…';$('#dRes').textContent='—';
 try{
  const [d,cr]=await Promise.all([
    fetch('/app/api/signal/'+encodeURIComponent(sid)).then(r=>r.ok?r.json():null),
    fetch('/app/api/chart/'+encodeURIComponent(sid)).then(r=>r.ok?r.blob():null).catch(()=>null)
  ]);
  if(!d){$('#dBody').innerHTML='<div class="empty">این سیگنال پیدا نشد</div>';return}
  CUR=d;
  $('#dTitle').textContent=`${fnum(d.symbol)} • ${fnum(d.tf)}`;
  $('#dRes').className='res '+d.result;$('#dRes').textContent=resFa(d.result)+(d.pnl!==null&&d.pnl!==undefined?` ${d.pnl>0?'+':''}${d.pnl}%`:'');
  const dir=d.spot?'LONG':(d.direction||'');
  const confirmTxt=Array.isArray(d.confirmations)?d.confirmations:[];
  let chart='';
  if(cr){const url=URL.createObjectURL(cr);chart=`<div class="chartbox"><img src="${url}" alt="چارت ${fnum(d.symbol)}"></div>`}
  else chart=`<div class="chartbox"><div class="chartload">چارت این سیگنال در دسترس نیست (نماد/دادهٔ زنده پیدا نشد)</div></div>`;
  $('#dBody').innerHTML=`
   <div class="row1" style="margin-bottom:10px"><span class="sym" style="font-size:17px">${fnum(d.symbol)}</span>
    <span class="badge">${fnum(d.source)}</span>
    ${dir?`<span class="chip ${dir}">${dir==='LONG'?'خرید 🟢':'فروش 🔴'}</span>`:''}
    ${d.spot?'<span class="chip SPOT">اسپات</span>':''}
    ${d.score?`<span class="chip score">★ ${d.score}/10</span>`:''}</div>
   ${chart}
   <div class="pills" style="margin-top:12px">
    <div class="pill entry"><i>ورود</i><b>${fnum(d.entry)}</b></div>
    <div class="pill stop"><i>استاپ</i><b>${fnum(d.sl)}${d.sl_moved_to_be?' (BE)':''}</b></div>
    <div class="pill tp1 ${d.tp1_hit?'hit':''}"><i>TP1</i><b>${fnum(d.tp1)}${d.tp1_hit?' ✓':''}</b></div>
    <div class="pill tp2 ${d.tp2_hit?'hit':''}"><i>TP2</i><b>${fnum(d.tp2)}${d.tp2_hit?' ✓':''}</b></div></div>
   ${(d.hit_log&&d.hit_log.length)?`<div class="dsec"><h3>🎯 رویدادهای قیمتی</h3>${d.hit_log.map(h=>`<div class="conf" style="${h.ok?'':'color:#ef5350'}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="${h.ok?'M20 6L9 17l-5-5':'M18 6L6 18M6 6l12 12'}"/></svg><b>${h.label}</b><span>${tehran(h.time)}</span></div>`).join('')}</div>`:''}
   ${(d.messages&&d.messages.compact)?`<div class="dsec"><h3>📨 پیام مختصر (همان پیام کانال)</h3><div class="prose tgmsg">${d.messages.compact}</div></div>`:''}
   ${(d.messages&&(d.messages.confirmed||d.messages.confirm))?`<div class="dsec"><h3>✅ پیام کانفرمد (همان پیام کانال)</h3><div class="prose tgmsg">${d.messages.confirmed||d.messages.confirm}</div></div>`:''}
   ${d.summary?`<div class="dsec"><h3>📝 توضیحات</h3><div class="prose">${fnum(d.summary)}</div></div>`:''}
   ${d.entry_conditions?`<div class="dsec"><h3>⚖️ شرط ورود / تأیید</h3><div class="prose">${fnum(d.entry_conditions)}</div></div>`:''}
   ${confirmTxt.length?`<div class="dsec"><h3>✅ تأییدها</h3>${confirmTxt.map(c=>`<div class="conf"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M20 6L9 17l-5-5"/></svg>${fnum(c)}</div>`).join('')}</div>`:''}
   ${(d.timeline||[]).length?`<div class="dsec"><h3>🕒 تایم‌لاین زندگی سیگنال</h3><div class="tl">${d.timeline.map(t=>`<div class="tli"><b>${fnum(t.fa)}</b><span>${tehran(t.time)}</span></div>`).join('')}</div></div>`:''}
   <div class="dsec mini">شناسه: <span class="code">${fnum(d.code)}</span> • ثبت: ${tehran(d.created_at)} ${d.confirmed_at?'• تأیید: '+tehran(d.confirmed_at):''} ${d.closed_at?'• بستن: '+tehran(d.closed_at):''}</div>`;
 }catch(e){$('#dBody').innerHTML='<div class="empty">خطا در دریافت جزئیات</div>'}
}
function closeDetail(){$('#detail').classList.remove('on');document.body.style.overflow=''}
/* ── control ── */
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
