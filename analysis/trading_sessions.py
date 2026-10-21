"""R99q28 — TRADING-SESSION LICENCES (Viva 10-19).

His words, verbatim:

    «سهمیه ها رو به نظرت چیکار کنیم ... من فکر میکنم باید سشن های معاملاتی رو
     مشخص بکنی ... و طبق اصول حرفه ای مثلا در سشن نیویورک به هر ستاپ مجوز ۱۵
     ستاپ داده بشه به سشن لندن ۱۵ مجوز به سشن توکیو ۱۰ مجوز و ...
     ۲۵ تا در روز کمه ... بقیه اوقات بین سشن ها کلا اسکن قطع بشه از ۱۵ دقیقه
     قبل از هر سشن اسکن پیدا کردن موقعیت رو اعمال بکنه.»

So the weekly wallet stops being the thing that fires every few hours. The day
is cut into the three real trading sessions, each setup gets its own licence
book per session, and discovery only runs inside a session window (opening
15 minutes early so a position is ready when the session actually starts).

Windows are UTC. Crypto trades 24/7 but the liquidity — and the breakouts that
matter — cluster in these hours, which is exactly why he asked for them.

Everything is env-tunable and fail-open:

    VIVA_SESSION_LICENCES=0          disable the whole rule (old behaviour)
    VIVA_SESSION_TOKYO_LICENCE=10    per setup per session
    VIVA_SESSION_LONDON_LICENCE=15
    VIVA_SESSION_NEWYORK_LICENCE=15
    VIVA_SESSION_PREROLL_MIN=15      how early discovery starts
    VIVA_SESSION_SCAN_GATE=0         keep scanning between sessions

The weekly wallet is still the outer ceiling — sessions only shape the day.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

# (name, start_hour_utc, end_hour_utc, default licence per setup)
SESSIONS = (
    ("TOKYO", 0, 9, 10),
    ("LONDON", 7, 16, 15),
    ("NEWYORK", 12, 21, 15),
)


def _enabled() -> bool:
    return str(os.getenv("VIVA_SESSION_LICENCES", "1") or "1").strip().lower() not in (
        "0", "false", "off", "no")


def sessions_enabled() -> bool:
    """Public: True when the session licence book owns the quota.

    main.py uses this to decide whether the OLD flat daily pace is still
    consulted. They must never both gate the same publish: whichever is
    tighter would silently win, which is exactly the 10-19 drought.
    """
    return _enabled()


def _scan_gate_enabled() -> bool:
    return str(os.getenv("VIVA_SESSION_SCAN_GATE", "1") or "1").strip().lower() not in (
        "0", "false", "off", "no")


def _preroll_minutes() -> int:
    try:
        return max(0, int(os.getenv("VIVA_SESSION_PREROLL_MIN", "15") or 15))
    except Exception:
        return 15


def session_licence_cap(name: str) -> int:
    """Licences one setup may spend in one session."""
    _key = f"VIVA_SESSION_{str(name or '').upper()}_LICENCE"
    _default = next((s[3] for s in SESSIONS if s[0] == str(name or "").upper()), 10)
    try:
        return max(1, int(os.getenv(_key, str(_default)) or _default))
    except Exception:
        return _default


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _window(session, preroll: int):
    """(start, end) datetimes for today's instance of a session."""
    _name, _h0, _h1, _cap = session
    base = None
    return _h0, _h1


def active_sessions(now: Optional[datetime] = None, preroll: Optional[int] = None):
    """Every session whose window contains `now`, LATEST-STARTING first.

    The order matters: when London and New York overlap, a breakout belongs to
    New York — the session that just opened is the one with the fresh
    liquidity. Same for Tokyo/London.
    """
    _n = _now(now)
    _pre = _preroll_minutes() if preroll is None else max(0, int(preroll))
    _mins = _n.hour * 60 + _n.minute
    hits = []
    for s in SESSIONS:
        _name, _h0, _h1, _cap = s
        _start = _h0 * 60 - _pre
        _end = _h1 * 60
        # The pre-roll can cross midnight (Tokyo opens at 00:00, so its window
        # starts at 23:45 the previous evening). Handle the wrap explicitly
        # rather than pretending it cannot happen.
        if _start < 0:
            _open = (_mins >= 1440 + _start) or (_mins < _end)
        else:
            _open = _start <= _mins < _end
        if _open:
            hits.append((_h0, s))
    hits.sort(key=lambda x: -x[0])
    return [s for _, s in hits]


def current_session(now: Optional[datetime] = None) -> Optional[str]:
    """The session a new signal belongs to, or None between sessions."""
    _hits = active_sessions(now)
    return _hits[0][0] if _hits else None


def in_scan_window(now: Optional[datetime] = None) -> bool:
    """True while discovery is allowed to look for NEW positions.

    Between sessions this is False — but monitoring of already-open chains is
    untouched (confirmations and hit/stop notices keep flowing; that is a
    separate loop).
    """
    if not _scan_gate_enabled():
        return True
    return bool(active_sessions(now))


def next_session(now: Optional[datetime] = None):
    """(name, starts_in_minutes) for the next session — for the log line."""
    _n = _now(now)
    _pre = _preroll_minutes()
    _mins = _n.hour * 60 + _n.minute
    best = None
    for s in SESSIONS:
        _name, _h0, _h1, _cap = s
        for _d in (0, 1440):
            _start = _h0 * 60 - _pre + _d
            _delta = _start - _mins
            if _delta > 0 and (best is None or _delta < best[1]):
                best = (_name, _delta)
    return best or ("TOKYO", 0)


def _day(now: Optional[datetime] = None) -> str:
    return _now(now).strftime("%Y-%m-%d")


def _kv():
    from database import bot_kv as kv
    return kv


def _key(session: str, setup: str, day: Optional[str] = None) -> str:
    return (f"tier_session_count:{day or _day()}:{str(session or '').upper()}:"
            f"{str(setup or '').strip().upper()}")


def session_count(setup: str, session: str, day: Optional[str] = None) -> int:
    try:
        return max(0, int(_kv().get_json(_key(session, setup, day), 0) or 0))
    except Exception:
        return 0


def session_licence_ok(setup_code: str, now: Optional[datetime] = None) -> bool:
    """May this setup publish ONE more alert in the session running now?

    Outside every session window the answer is False — if he wanted alerts at
    03:00 between sessions, the scan gate would have to be open anyway.
    Fail-open on any error so a KV hiccup can never silence the bot.
    """
    if not _enabled():
        return True
    try:
        _n = _now(now)
        _sess = current_session(_n)
        if _sess is None:
            return not _scan_gate_enabled()
        _cap = session_licence_cap(_sess)
        return session_count(setup_code, _sess, _day(_n)) < _cap
    except Exception:
        return True


def session_licence_incr(setup_code: str, now: Optional[datetime] = None) -> int:
    """Spend one session licence. Returns the new count, or -1 on error."""
    if not _enabled():
        return -1
    try:
        _n = _now(now)
        _sess = current_session(_n)
        if _sess is None:
            return -1
        _k = _key(_sess, setup_code, _day(_n))
        _cur = max(0, int(_kv().get_json(_k, 0) or 0)) + 1
        _kv().set_json(_k, _cur)
        return _cur
    except Exception:
        return -1


def session_snapshot(now: Optional[datetime] = None) -> dict:
    """Readable book for the log: {session: {setup: used/cap}}."""
    _n = _now(now)
    out = {}
    for _name, _h0, _h1, _cap in SESSIONS:
        out[_name] = {"cap": session_licence_cap(_name), "opened": _h0, "closed": _h1}
    return out
