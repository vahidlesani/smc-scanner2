"""TIERED SCAN (R99c) — shared scanner infra (VIVA_USER_LAWS.md §2).

Layers:
  * GUARD  — the existing fast lanes (candidate monitor 10s, line-watch,
             urgent confirms). UNTOUCHED by this pack — they already watch
             every chain every few seconds, so the deep pass can breathe.
  * DEEP   — discovery cadence (TIER_DEEP_MINUTES, default honors FULL_SCAN).
  * SPOT   — spot pass cadence (TIER_SPOT_DEEP_MINUTES, default 60).

The aggregation stair-step already lives in data.fetcher.get_market_bundle
(R64: venue fetches only 5m/15m/1h/4h/1d; everything else is derived).
AGG_MAP here is the single source of truth, and aggregate_frame() is the
pure, tested reference implementation (epoch-aligned buckets, COMPLETE
buckets only — a forming bar must never pretend to be closed).

Quality law (§13): at most VIVA_MAX_SIGNALS_PER_DAY new publishes/day
(counted per lane, capped on the TOTAL) and VIVA_MAX_CONCURRENT_POSITIONS
open chains. Confirms of already-alerted chains are NEVER gated — the cap
only trims NEW mints. Per-setup score floors land with each setup's own
completion (starting TECHCLASSIC).
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

# derived TF -> (base TF, fold k). Verified against get_market_bundle (R99c).
AGG_MAP: Dict[str, Tuple[str, int]] = {
    "30m": ("15m", 2),
    "2h": ("1h", 2),
    "8h": ("4h", 2),
    "12h": ("4h", 3),
    "3d": ("1d", 3),
    "1w": ("1d", 7),
}
BASE_TFS = ("5m", "15m", "1h", "4h", "1d")
LANES = ("futures", "spot")


# ══════════════════════════════════════════════════════════════════════
# R99q7 — WEEKLY SETUP LICENCE (Viva 10-15 «قانون موقت جدید», dictated)
#   * setups trigger on FIVE frames: 15m, 30m, 1h, 2h, 4h  (the daily is
#     NOT a setup trigger — it exists only in spot; futures read 1d for
#     BIAS only, never as an entry trigger).
#   * each setup owns N licences PER WEEK (N = env; default 5 × scanned
#     symbols, his 40-symbols → 200 example), refreshed at week start.
#   * the pool is ONE wallet across the five trigger frames: whichever
#     frame's pattern/zones/trendlines are cleaner earns the licence
#     («بر اساس کیفیت پترن ... می‌تونه به هر تایم تریگر که ... بهتری
#     داشت داده بشه»). No per-frame sub-caps here.
#   * total Telegram alerts per setup per week never exceed that N.
# ══════════════════════════════════════════════════════════════════════
SETUP_TRIGGER_TFS = ("15m", "30m", "1h", "2h", "4h")
BIAS_TFS = ("1d",)
SPOT_EXTRA_TRIGGER_TFS = ("1d",)   # daily lives in spot only
LICENCE_TF_COUNT = len(SETUP_TRIGGER_TFS)


def trigger_tfs(venue: str = "futures"):
    """The law's trigger grid: 5 frames everywhere, +1d in spot."""
    if str(venue or "").lower() == "spot":
        return tuple(SETUP_TRIGGER_TFS) + tuple(SPOT_EXTRA_TRIGGER_TFS)
    return tuple(SETUP_TRIGGER_TFS)


def week_key(now=None) -> str:
    """ISO week stamp of the licence wallet (Monday 00:00 UTC)."""
    try:
        _d = now or datetime.now(timezone.utc)
        _y, _w, _ = _d.isocalendar()
        return f"{int(_y)}-W{int(_w):02d}"
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-W%W")


def scanned_symbol_count() -> int:
    """How many symbols this licence is priced against (his 5×symbols)."""
    for _name in ("VIVA_LICENCE_SYMBOLS", "VIVA_SCAN_SYMBOLS"):
        try:
            _v = str(os.getenv(_name, "") or "").strip()
            if _v:
                return max(1, int(_v))
        except Exception:
            pass
    try:
        from data.universe import UNIVERSE as _U
        _syms, _ = _U.get()
        if _syms:
            return max(1, len(_syms))
    except Exception:
        pass
    return 40  # his worked example


def weekly_licence_cap(setup_code=None) -> int:
    """Licences per setup per week: env first (his tunable), else 5×symbols."""
    _code = str(setup_code or "").strip().upper()
    try:
        if _code:
            _v = str(os.getenv(f"VIVA_WEEKLY_LICENCE_{_code}", "") or "").strip()
            if _v:
                return max(1, int(_v))
        _v = str(os.getenv("VIVA_SETUP_WEEKLY_LICENCE", "") or "").strip()
        if _v:
            return max(1, int(_v))
    except Exception:
        pass
    try:
        return max(1, LICENCE_TF_COUNT * scanned_symbol_count())
    except Exception:
        return 200


def _week_key_name(week: str, setup_code: str) -> str:
    return f"tier_week_count:{week}:{str(setup_code or '').strip().upper()}"


def weekly_count(week=None, setup_code=None) -> int:
    """Alerts already spent by this setup in the ISO week."""
    try:
        return max(0, int(_kv().get_json(
            _week_key_name(week or week_key(), setup_code), 0) or 0))
    except Exception:
        return 0


def weekly_licence_ok(setup_code=None, week=None) -> bool:
    """True while this setup still holds a licence this week."""
    try:
        return weekly_count(week, setup_code) < weekly_licence_cap(setup_code)
    except Exception:
        return True


# ── R99q30 HOURLY CADENCE (his 10-20, verbatim: «الان اگر مصرف ریلوی میشه
# بستن هشدار ها چه فایده ای داره؟؟ ... می‌خوای ساعتی ۱۰ هشدار برای هرستاپ و
# اسپات تعیین بکنیم؟؟ ... فعلا که خشکه باید ساعتی کنیم اینجوری فایده نداره»).
#
# The weekly pace subdivided a 200-licence wallet into a DAILY share and then
# spread it across the clock — measured on 10-20: PINVAL pace=92, ALBROX
# pace=14, TECHCLASSIC pace=5, TLBREAK pace=1 and ready_new=0 in EVERY scan.
# A cap that is never reached is not a cap, it is an outage. The cadence he
# asked for is the replacement: at most N alerts per setup per clock hour,
# spot included. The weekly wallet (200) stays the outer bound.
#
# VIVA_HOURLY_CAP=0 disables the hourly shape entirely (back to the wallet).
def hourly_cap() -> int:
    try:
        return max(0, int(os.getenv("VIVA_HOURLY_CAP", "10") or 10))
    except Exception:
        return 10


def _hour_setup_key(hour_tag: str, setup_code: str) -> str:
    return f"tier_hour_setup:{hour_tag}:{str(setup_code or '').strip().upper()}"


def hourly_pace_ok(setup_code=None, now=None) -> bool:
    """True while this setup may still publish in the CURRENT clock hour."""
    _cap = hourly_cap()
    if _cap <= 0:
        return True
    try:
        _n = now or datetime.now(timezone.utc)
        _tag = _n.strftime("%Y-%m-%dT%H")
        return max(0, int(_kv().get_json(_hour_setup_key(_tag, setup_code), 0) or 0)) < _cap
    except Exception:
        return True


def spend_publish_licence(setup_code=None, lane: str = "futures") -> dict:
    """R99q31h — the ONE place a real publish spends its quota.

    The end-of-cycle retry posts for real, so it must spend for real. Rather
    than bolting a third copy of the five counters into `main.py` (the codebase
    pins exactly two wallet spend sites there, and that pin is a good one),
    the retry spends through this helper: weekly licence, daily set counter,
    lane day counter, hourly pace, session slot — fail-open, each step
    independently guarded so one closed book never blocks a publish.
    """
    out = {}
    for _name, _fn, _arg in (
            ("weekly", weekly_licence_incr, setup_code),
            ("daily_setup", daily_setup_incr, setup_code),
            ("hourly_pace", hourly_pace_incr, setup_code),
            ("session", session_licence_incr, setup_code)):
        try:
            out[_name] = _fn(_arg) if _arg is not None else _fn()
        except Exception as exc:
            out[_name] = -1
            print(f"licence spend warning ({_name}): {exc}")
    try:
        daily_count_incr(lane)
        out["lane"] = lane
    except Exception as exc:
        out["lane"] = -1
        print(f"licence spend warning (lane): {exc}")
    return out


def hourly_pace_incr(setup_code=None, now=None) -> int:
    """Spend one slot in this hour. Returns the new count, or -1 on error."""
    _cap = hourly_cap()
    if _cap <= 0:
        return -1
    try:
        _n = now or datetime.now(timezone.utc)
        _tag = _n.strftime("%Y-%m-%dT%H")
        _k = _hour_setup_key(_tag, setup_code)
        _cur = max(0, int(_kv().get_json(_k, 0) or 0)) + 1
        _kv().set_json(_k, _cur)
        return _cur
    except Exception:
        return -1


def days_left_in_week(now=None) -> int:
    """Days remaining in the ISO week, TODAY included (Mon..Sun → 7..1)."""
    try:
        _d = now or datetime.now(timezone.utc)
        return max(1, 7 - int(_d.isoweekday()) + 1)
    except Exception:
        return 1


def _day_setup_key(day: str, setup_code: str) -> str:
    return f"tier_day_setup:{day}:{str(setup_code or '').strip().upper()}"


def daily_setup_count(setup_code=None, day=None) -> int:
    """How many licences THIS setup spent today (pace evidence)."""
    try:
        _d = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return max(0, int(_kv().get_json(_day_setup_key(_d, setup_code), 0) or 0))
    except Exception:
        return 0


def daily_setup_incr(setup_code=None, day=None) -> int:
    try:
        _d = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _k = _day_setup_key(_d, setup_code)
        _n = max(0, int(_kv().get_json(_k, 0) or 0)) + 1
        _kv().set_json(_k, _n)
        return _n
    except Exception:
        return -1


def weekly_pace_ok(setup_code=None, week=None, now=None) -> bool:
    """R99q24 — A WEEKLY WALLET MUST LAST THE WEEK.

    Viva 10-17 measured the drying directly: PINVAL's and ALBROX's 200-licence
    wallets were EMPTY by 16:05/17:48 on day 4 of the week, because a burst
    night (23 alerts/hour) can spend a whole week in a few hours. This is the
    *pacing* rule, not a new cap: today may spend at most the honest daily
    share of what is LEFT —

        pace = ceil(left / days_left_in_week)      (today included)
        allow while today_used < pace  (one spare so a single good setup in a
                                        quiet week is never starved)

    Fail-open everywhere: any error, or `VIVA_WEEKLY_PACE=0`, allows the
    publish exactly as before.
    """
    if str(os.getenv("VIVA_WEEKLY_PACE", "1") or "1").strip().lower() in (
            "0", "false", "off", "no"):
        return True
    try:
        _cap = weekly_licence_cap(setup_code)
        _left = _cap - weekly_count(week, setup_code)
        if _left <= 0:
            return False                    # the wallet itself is empty
        _now = now or datetime.now(timezone.utc)
        _days = days_left_in_week(_now)
        _pace = max(1, int(math.ceil(_left / float(_days))))
        # R99q27 (Viva 10-19, verbatim: «از ساعت ۱۰ صبح هیچ هشداری نیامده …
        # ۲۷ پیام اومده و ستاپ‌ها هیچ هشداری ندادن»): the daily share used to be
        # spendable in ONE burst. Measured on 10-19: ALBROX spent its 25 by
        # 01:32, PINVAL by 01:02, TECHCLASSIC by 06:34, TLBREAK by 07:02 UTC —
        # and then every setup sat silent for the rest of the day because
        # `today_used < pace` was false. The weekly cap is NOT touched; only
        # the SHAPE of the spend changes: the same daily quota is released
        # across the 24 hours, so after h hours at most ceil(pace*(h+1)/24)
        # may have been spent. At the end of the day the full quota is
        # available exactly as before.
        # VIVA_WEEKLY_PACE_SPREAD=0 restores the old flat behaviour.
        _spread = str(os.getenv("VIVA_WEEKLY_PACE_SPREAD", "1") or "1").strip().lower()
        if _spread in ("0", "false", "off", "no"):
            _by_now = _pace
        else:
            _by_now = max(1, int(math.ceil(_pace * (_now.hour + 1) / 24.0)))
        _day = _now.strftime("%Y-%m-%d")
        return daily_setup_count(setup_code, day=_day) < _by_now
    except Exception:
        return True


# ── R99q28 sessions ──────────────────────────────────────────────────────
# main.py gates the futures lane through this module (`_tier99j`); the session
# helpers live in their own file so they can be tested without touching the
# scan loop. Re-exported here so the call site stays one import.
from analysis.trading_sessions import (  # noqa: E402,F401
    active_sessions, current_session, in_scan_window, next_session,
    session_count, session_licence_cap, session_licence_incr,
    session_licence_ok, session_snapshot, sessions_enabled,
)


def weekly_licence_incr(setup_code=None, week=None, n: int = 1) -> int:
    """Spend n licences after a successful publish. Returns the new count."""
    try:
        _wk = week or week_key()
        _key = _week_key_name(_wk, setup_code)
        _cur = max(0, int(_kv().get_json(_key, 0) or 0)) + max(1, int(n or 1))
        _kv().set_json(_key, _cur)
        return _cur
    except Exception:
        return -1


def weekly_licence_snapshot(setups=None, week=None) -> dict:
    """Readable wallet: {setup: {"used", "cap", "left"}} for the summary."""
    _wk = week or week_key()
    _codes = list(setups or ("PINVAL", "ALBROX", "TLBREAK", "TECHCLASSIC",
                             "SPOT", "PINWALL LEGACY"))
    _out = {}
    for _c in _codes:
        try:
            _cap = weekly_licence_cap(_c)
            _used = weekly_count(_wk, _c)
            _out[str(_c)] = {"used": _used, "cap": _cap,
                             "left": max(0, _cap - _used)}
        except Exception:
            continue
    return _out


def aggregate_frame(df, k: int, base_seconds: int = 86400,
                    monday_shift: bool = False):
    """Fold k base candles into one higher-TF candle (pure; tested).

    Epoch-aligned buckets, complete buckets only. monday_shift=True moves
    weekly buckets to Mon→Sun (TradingView week, same as _aggregate_daily).
    base_seconds = one base candle in seconds (900 for 15m, 3600 for 1h…).
    """
    try:
        import pandas as pd  # local import: module stays light
        if df is None or getattr(df, "empty", True):
            return None
        k = int(k)
        _bs = int(base_seconds or 0)
        if k < 2 or _bs <= 0:
            return None
        d = df.reset_index(drop=True).copy()
        d["timestamp"] = pd.to_datetime(d["timestamp"])
        d = d.sort_values("timestamp")
        _ts = d["timestamp"]
        if getattr(_ts.dt, "tz", None) is not None:
            _ts = _ts.dt.tz_convert("UTC").dt.tz_localize(None)
        _epochs = (_ts.astype("int64") // 1_000_000_000)
        _shift = 3 * 86400 if (monday_shift and _bs == 86400) else 0
        d["_g"] = ((_epochs + _shift) // (_bs * k)).astype("int64")
        if d.empty or len(d) < k * 2:
            return None
        rows = []
        for _, g in d.groupby("_g"):
            if len(g) < k:
                continue
            rows.append({
                "timestamp": pd.Timestamp(g["timestamp"].iloc[0]),
                "open": float(g["open"].iloc[0]),
                "high": float(g["high"].max()),
                "low": float(g["low"].min()),
                "close": float(g["close"].iloc[-1]),
                "volume": float(g["volume"].sum()) if "volume" in g else 0.0,
            })
        if not rows:
            return None
        return pd.DataFrame(rows)
    except Exception:
        return None


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, "") or "").strip() or default)
    except Exception:
        return default


def _now_utc_s() -> str:
    try:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def deep_minutes() -> int:
    """Discovery cadence (R99q15, his 10-16 verbatim: «هر ۶۰ دقیقه نیازه که
    دوباره اسکن عمیق بکنه .. مگر اینکه موارد خوبی پیدا بکنه بین ۲۰۰ کوین برتر
    اول مارکت کپ»).

    base = TIER_DEEP_MINUTES else FULL_SCAN_MINUTES else 10 — and while a recent
    pass DID find good setups among the top-200 the cadence bursts to
    TIER_DEEP_BURST_MINUTES until the burst window expires. So the market is
    watched every 60 min when it is quiet and every 5 min while it is paying.
    """
    if str(os.getenv("TIER_DEEP_MINUTES", "") or "").strip():
        base = max(2, _int_env("TIER_DEEP_MINUTES", 60))
    else:
        base = max(2, _int_env("FULL_SCAN_MINUTES", 10))
    try:
        _until = str(_kv().get_json("tier_deep_burst_until", "") or "")
        if _until and _now_utc_s() and _until > _now_utc_s():
            return max(2, _int_env("TIER_DEEP_BURST_MINUTES", 5))
    except Exception:
        pass
    return base


def mark_deep_result(hits: int) -> None:
    """A deep pass that found good setups starts/extends the burst window."""
    try:
        _thr = max(1, _int_env("TIER_DEEP_BURST_MIN_HITS", 1))
        if int(hits or 0) < _thr:
            return
        from datetime import datetime, timedelta, timezone
        _win = max(1, _int_env("TIER_DEEP_BURST_WINDOW_MINUTES", 30))
        _until = ((datetime.now(timezone.utc) + timedelta(minutes=_win))
                  .strftime("%Y-%m-%dT%H:%M:%SZ"))
        _kv().set_json("tier_deep_burst_until", _until)
    except Exception:
        pass


def guard_seconds() -> int:
    return max(15, _int_env("TIER_GUARD_SECONDS", 60))


def guard_enabled() -> bool:
    return str(os.getenv("TIER_GUARD_ENABLED", "1") or "1").strip().lower() in {
        "1", "true", "on", "yes"}


def spot_deep_minutes() -> int:
    if str(os.getenv("TIER_SPOT_DEEP_MINUTES", "") or "").strip():
        return max(15, _int_env("TIER_SPOT_DEEP_MINUTES", 60))
    return max(15, _int_env("SPOT_SCAN_MINUTES", 60))


def daily_cap() -> int:
    """Max NEW publishes/day TOTAL across lanes (quality law §13; 25)."""
    return max(1, _int_env("VIVA_MAX_SIGNALS_PER_DAY", 25))


def concurrent_cap() -> int:
    """Max concurrent open chains (quality law §13; default 3)."""
    return max(1, _int_env("VIVA_MAX_CONCURRENT_POSITIONS", 3))


def guard_band_pct() -> float:
    try:
        return max(0.1, float(os.getenv("TIER_GUARD_BAND_PCT", "1.0") or 1.0))
    except Exception:
        return 1.0


def _kv():
    from database import bot_kv as _bkv
    return _bkv


def _day_key(day: str, lane: str) -> str:
    return f"tier_day_count:{day}:{lane}"


def daily_count(day=None, lane: Optional[str] = None) -> int:
    """Published-signals counter: one lane, or TOTAL when lane is None."""
    try:
        _day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _lanes = (lane,) if lane else LANES
        return sum(max(0, int(_kv().get_json(_day_key(_day, _l), 0) or 0))
                   for _l in _lanes)
    except Exception:
        return 0


def daily_budget_ok(day=None) -> bool:
    """RETIRED (R99q — Viva 10-15, verbatim: «گفتم گیت خشک‌کننده سیگنال‌های
    ستاپ‌ها رو برداررررر»): the 25-signal/day TOTAL cap used to dry EVERY
    setup at once (today: 21/25 by 04:40 Tehran, then silence). The licence
    seats (3 concurrent per symbol/setup/trigger-TF, his 10-15 restatement)
    and each setup's OWN concurrent slots (R99n) are the only caps now.
    Kept as a function so old call sites never crash; always True."""
    return True


def daily_count_incr(lane: str, day=None):
    """Increment one lane's counter after a successful publish (-1=skipped)."""
    try:
        if lane not in LANES:
            return -1
        _day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _n = max(0, int(_kv().get_json(_day_key(_day, lane), 0) or 0)) + 1
        _kv().set_json(_day_key(_day, lane), _n)
        return _n
    except Exception:
        return -1


def concurrent_ok(open_n: int) -> bool:
    try:
        return int(open_n or 0) < concurrent_cap()
    except Exception:
        return True


def spot_unchanged_skip(symbol: str, bundle,
                         tfs=("4h", "8h", "12h", "1d", "3d", "1w")) -> bool:
    """True when no spot TF closed a new candle since the last pass.

    Same idea as the discovery skip (Round-15): no new closed candle and
    the pass cannot see anything it did not already see. Stamp lives in
    durable kv (survives restarts). Fail-open: False (never skip on doubt).
    """
    try:
        _stamp = []
        for _tf in tfs:
            try:
                _df = bundle.get(_tf)
                _stamp.append(str(_df["timestamp"].iloc[-1])
                              if _df is not None and len(_df) else "-")
            except Exception:
                _stamp.append("?")
        _stamp = tuple(_stamp)
        _key = f"tier_spot_stamp:{str(symbol or '').upper()}"
        _prev = _kv().get_json(_key, None)
        _kv().set_json(_key, list(_stamp))
        return bool(_prev is not None and tuple(_prev) == _stamp
                    and "?" not in _stamp)
    except Exception:
        return False



# ══════════════════════════════════════════════════════════════════════
# R99q15 — SPOT PER-TF CLOSED-BAR GATE (Viva 10-16, verbatim: «هر ۶۰دقیقه
# نیازه که دوباره اسکن عمیق بکنه … هر ساعت ۸.۵ دقیقه رو من نمی‌فهمم چرا
# باید اینقدر زمان ببره و مصرف بکنه ریلوی رو … قطعا راه حلی می‌تونی بکار
# ببری که این مشکل و مصرف ریلوی بهینه و اصلاح بشه»)
#
# A pattern can only CHANGE when one of its candles closes, so an hourly pass
# over the top-200 symbols does NOT need to re-fit 6 frames × 200 symbols: it
# only needs the frames whose newest CLOSED candle is new. The stamps are per
# (symbol, TF) in durable KV and are written only after a TF has actually been
# processed, so a crash mid-pass can never eat a bar.
#   * 4h → 6 closes/day · 8h → 3 · 12h → 2 · 1d → 1 · 3d → ⅓ · 1w → 1/7
#   * naive hourly deep pass = 6 frames/symbol/hour
#   * gated = ≈0.52 frames/symbol/hour  → ~11× less engine work
# ══════════════════════════════════════════════════════════════════════
SPOT_GATE_TFS = ("4h", "8h", "12h", "1d", "3d", "1w")


def spot_bar_ts(bundle, tf) -> str:
    """Newest CLOSED candle stamp of one frame ('' when unreadable)."""
    try:
        df = bundle.get(tf)
        if df is None or not len(df):
            return ""
        try:
            return str(df["timestamp"].iloc[-1])
        except Exception:
            return str(df.index[-1])
    except Exception:
        return ""


def spot_due_tfs(symbol: str, bundle, tfs=SPOT_GATE_TFS,
                 force: bool = False, pinned=()) -> list:
    """Which spot TFs closed a NEW candle since the last pass (R99q15).

    `pinned` = TFs with an open urgent-watch pin (a live edge must stay
    watched even between closes — the ticker line-watch replies on touch).
    Fail-open: an unreadable frame or KV means the TF IS scanned."""
    _out = []
    for _tf in tfs:
        try:
            _ts = spot_bar_ts(bundle, _tf)
            if not _ts:
                _out.append(_tf)
                continue
            if force or str(_tf) in {str(x) for x in (pinned or ())}:
                _out.append(_tf)
                continue
            _prev = _kv().get_json(f"spot_tf_bar:{str(symbol or '').upper()}|{_tf}", None)
            if _prev != _ts:
                _out.append(_tf)
        except Exception:
            _out.append(_tf)
    return _out


def spot_tf_mark(symbol: str, bundle, tfs) -> None:
    """Stamp the bars a TF was PROCESSED on (call only after the work ran)."""
    for _tf in (tfs or ()):
        try:
            _ts = spot_bar_ts(bundle, _tf)
            if _ts:
                _kv().set_json(f"spot_tf_bar:{str(symbol or '').upper()}|{_tf}", _ts)
        except Exception:
            pass


class _TfSubset:
    """A read-only bundle view exposing only the due TFs (spot lane R99q15).

    The engines keep their own fetch policy — this only decides WHICH frames
    they are handed this pass; the full bundle stays cached for the chart."""

    def __init__(self, bundle, tfs):
        self._b = bundle
        self._tfs = set(str(x) for x in (tfs or ()))

    def get(self, tf):
        if str(tf) not in self._tfs:
            return None
        return self._b.get(tf) if self._b is not None else None

    def __getattr__(self, item):
        return getattr(self._b, item)

def dist_to_entry_pct(side: str, entry, live) -> Optional[float]:
    """|live-entry|/entry in % (None when unusable)."""
    try:
        _e, _l = float(entry or 0), float(live or 0)
        if _e <= 0 or _l <= 0:
            return None
        return abs(_l - _e) / _e * 100.0
    except Exception:
        return None


def guard_should_fire(side: str, entry, live) -> bool:
    """True when a chain is inside the guard band (pure; tested)."""
    _d = dist_to_entry_pct(side, entry, live)
    return bool(_d is not None and _d <= guard_band_pct())
SETUP_SLOT_MODULES = {
    "PINVAL": "analysis.pinval",
    "ALBROX": "analysis.albrox",
    "TLBREAK": "analysis.tlbreak",
    "TECHCLASSIC": "analysis.techclassic",
    "SPOT": "analysis.spot",
}


def setup_cap(setup_code: str) -> int:
    """Concurrent-chain allowance OWNED by one setup (R99n).

    <SETUP>_MAX_CONCURRENT_CHAINS env wins; else the setup's own engine
    file (OWN_MAX_CONCURRENT_CHAINS); else 30. Fail-open: 30.
    """
    _code = str(setup_code or "").strip().upper()
    try:
        _env = (os.getenv(f"{_code}_MAX_CONCURRENT_CHAINS", "") or "").strip()
        if _env:
            return max(1, int(_env))
    except Exception:
        pass
    _mod = SETUP_SLOT_MODULES.get(_code)
    if _mod:
        try:
            import importlib as _il99n
            _v = getattr(_il99n.import_module(_mod),
                         "OWN_MAX_CONCURRENT_CHAINS", None)
            if _v is not None:
                return max(1, int(_v))
        except Exception:
            pass
    return 30


def count_open_by_setup(actives) -> dict:
    """Group open chains per setup (R99n). Fail-open: {}."""
    _out: dict = {}
    try:
        for _c in (actives or []):
            _k = str(getattr(_c, "setup_code", "") or "").strip().upper()
            if not _k:
                continue
            _out[_k] = int(_out.get(_k, 0) or 0) + 1
    except Exception:
        return {}
    return _out


def concurrent_ok_for_setup(setup_code, open_by_setup=None) -> bool:
    """True while THIS setup is under its own allowance (R99n)."""
    try:
        _code = str(setup_code or "").strip().upper()
        _n = int((open_by_setup or {}).get(_code, 0) or 0)
        return _n < setup_cap(_code)
    except Exception:
        return True
