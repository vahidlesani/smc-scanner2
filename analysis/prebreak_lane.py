"""R99q14 — قانونِ هشدارِ آموزشیِ ابتدایی، پیش از شکست (Viva 10-15, verbatim:

«وقتی که هشدار آموزشی و ابتدایی اومده عملا قیمت بریک رو انجام داده بوده و کار
از کار گذشته بوده؛ باید قبل از اینکه قیمت به اضلاع الگوها و یا در حال بریک
پترن‌ها و ترندلاین‌ها و نواحی ستاپ برسه اولین هشدار ابتدایی بده .. و بعد از
بریک تایید بده … دقیقا در اسپات اینرو داریم … ستاپ‌ها باید شبیه همون باشن از
این نظر … در همه ستاپ‌ها یکسانه … فقط بدون هر ستاپ جدا جدا جراحی بشه».

THE LAW (one law, every setup, each setup judged by its OWN engine):
  1. BEFORE the break — while price is still INSIDE the pattern or near its
     edges (trendlines, pattern sides, the setup's own zones/pins) — the FIRST
     alert goes out. It is a WATCH: the edge, the distance in ATR, the picture
     with the geometry. It is NOT a signal.
  2. AFTER the break — the confirm lane speaks (the same chain: the watch is
     the anchor, the confirmation is a reply under it).
  3. A watch is NEVER emitted once the edge has been broken (that is the
     confirm's job) and never re-emitted inside its own cooldown window.

Each setup answers through its own engine (`PROVIDERS`) — no shared detector is
allowed to speak for a setup that owns its own geometry.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

KV_KEY = "prebreak_seen"
_TTL = 14 * 86400

# ── the approach band («قیمت درون الگو یا نزدیک ترندلاین‌ها») ────────────────
_DEFAULT_BAND_ATR = 0.85          # distance to the OWN edge, in ATR
_DEFAULT_INSIDE_BAND_ATR = 2.40   # inside the pattern: still a valid watch

# ── cadence (his law: the first alert must be EARLY, so the gap is short) ────
_DEFAULT_GAP_MIN = 45.0
_DEFAULT_MAX_PER_CYCLE = 2        # per symbol/scan: separate lane, never eats the break budget
_DEFAULT_DAILY_CAP = 40

PROVIDERS: Dict[str, tuple] = {
    "TECHCLASSIC": ("analysis.techclassic", "techclassic_prebreak"),
    "ALBROX": ("analysis.albrox", "albrox_prebreak"),
    "PINVAL": ("analysis.pinval", "pinval_prebreak"),
    "PINWALLQ": ("analysis.pinval", "pinwall_prebreak"),
    "TLBREAK": ("analysis.tlbreak", "tlbreak_prebreak"),
}

# Each setup's own pattern timeframes (its own engine decides; these are the
# frames the lane feeds it — never a fetch of its own).
SETUP_TFS: Dict[str, tuple] = {
    "TECHCLASSIC": ("30m", "1h", "2h", "4h"),
    "ALBROX": ("30m", "1h", "2h", "4h"),
    "PINVAL": ("15m", "30m", "1h"),
    "PINWALLQ": ("15m", "30m", "1h"),
    "TLBREAK": ("30m", "1h", "4h"),
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, "") or "").strip() or default)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(str(os.getenv(name, "") or "").strip() or default))
    except Exception:
        return default


def band_atr() -> float:
    return max(0.10, _env_float("VIVA_PREBREAK_BAND_ATR", _DEFAULT_BAND_ATR))


def inside_band_atr() -> float:
    return max(band_atr(), _env_float("VIVA_PREBREAK_INSIDE_ATR", _DEFAULT_INSIDE_BAND_ATR))


def gap_minutes(setup: str = "") -> float:
    _base = _env_float("VIVA_PREBREAK_GAP_MIN", _DEFAULT_GAP_MIN)
    _per = _env_float(f"VIVA_PREBREAK_GAP_MIN_{str(setup or '').upper()}", 0.0)
    return max(5.0, _per or _base)


def max_per_cycle() -> int:
    return max(1, _env_int("VIVA_PREBREAK_MAX_PER_CYCLE", _DEFAULT_MAX_PER_CYCLE))


def daily_cap() -> int:
    return max(1, _env_int("VIVA_PREBREAK_DAILY_CAP", _DEFAULT_DAILY_CAP))


# ── durable cooldown (survives restarts) ───────────────────────────────────
_SEEN: Optional[Dict[str, float]] = None


def _seen() -> Dict[str, float]:
    global _SEEN
    if _SEEN is None:
        try:
            from database.bot_kv import get_json
            _SEEN = dict(get_json(KV_KEY, {}) or {})
        except Exception:
            _SEEN = {}
    return _SEEN


def _seen_store() -> None:
    try:
        from database.bot_kv import set_json
        now = time.time()
        set_json(KV_KEY, {k: v for k, v in _seen().items() if float(v or 0) > now - _TTL})
    except Exception:
        pass


def reset_seen_cache() -> None:
    """Test/debug helper."""
    global _SEEN
    _SEEN = None


def _key(symbol: str, setup: str, tf: str, side: str) -> str:
    return f"{str(symbol or '?').upper()}|{str(setup or '?').upper()}|{str(tf or '?').lower()}|{str(side or '?').lower()}"


def cooldown_ok(symbol: str, setup: str, tf: str, side: str) -> bool:
    """True when this edge may speak a fresh pre-break alert now."""
    k = _key(symbol, setup, tf, side)
    stamp = float(_seen().get(k) or 0.0)
    if stamp and (time.time() - stamp) < gap_minutes(setup) * 60.0:
        return False
    _seen()[k] = time.time()
    return True


def sent_today() -> int:
    now = time.time()
    return sum(1 for v in _seen().values() if float(v or 0) > now - 86400.0)


def stamp_only(symbol: str, setup: str, tf: str, side: str) -> None:
    _seen()[_key(symbol, setup, tf, side)] = time.time()
    _seen_store()


def provide(setup: str) -> Optional[Callable]:
    """The setup's OWN pre-break function, or None when the setup is off."""
    import importlib as _il
    _spec = PROVIDERS.get(str(setup or "").upper())
    if not _spec:
        return None
    try:
        return getattr(_il.import_module(_spec[0]), _spec[1])
    except Exception as exc:  # pragma: no cover - defensive
        print(f"prebreak provider {setup} unavailable: {exc}")
        return None


def setup_enabled(setup: str) -> bool:
    try:
        from config import get_settings
        s = get_settings()
        return bool({
            "TECHCLASSIC": getattr(s, "technoclassic_enabled", False),
            "ALBROX": getattr(s, "albrox_enabled", False),
            "PINVAL": getattr(s, "pinv_enabled", False),
            "PINWALLQ": getattr(s, "pinwall_quality_enabled", False),
            "TLBREAK": getattr(s, "tlbreak_enabled", True),
        }.get(str(setup or "").upper(), False))
    except Exception:
        return False


# ── the event contract ─────────────────────────────────────────────────────
EVENT_FIELDS = (
    "setup", "setup_name", "symbol", "tf", "pattern_tf", "side", "direction",
    "pattern", "pattern_fa", "edge", "distance_atr", "line_geo", "pattern_geo",
    "measured", "touches", "score", "note_fa", "atr", "chart_tf",
)


def normalize(ev: Dict[str, Any], *, symbol: str, setup: str, tf: str) -> Optional[Dict[str, Any]]:
    """One shape for every setup's answer (the law is identical everywhere).

    Everything the provider returned rides along (the chart's own geometry —
    upper_points/lower_points/edge_points/zones/pin_high… — is the engine's
    evidence and must never be dropped by the lane).
    """
    if not isinstance(ev, dict):
        return None
    out = {k: v for k, v in ev.items() if not str(k).startswith("_")}
    out["symbol"] = str(ev.get("symbol") or symbol or "").upper()
    out["setup"] = str(ev.get("setup") or setup or "").upper()
    out["tf"] = str(ev.get("tf") or tf or "").lower()
    out.setdefault("chart_tf", out["tf"])
    try:
        out["edge"] = float(out.get("edge") or 0.0)
        out["distance_atr"] = float(out.get("distance_atr"))
    except Exception:
        return None
    if out["edge"] <= 0:
        return None
    out["side"] = str(out.get("side") or "upper").lower()
    out["direction"] = str(out.get("direction") or ("LONG" if out["side"] == "upper" else "SHORT")).upper()
    try:
        out["score"] = float(out.get("score") or 0.0)
    except Exception:
        out["score"] = 0.0
    return out


def collect(bundle, *, setups: Optional[List[str]] = None,
            frames: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Ask EVERY enabled setup's own engine for its pre-break events.

    Cost-shaped: the frames come from the discovery bundle (no fetch here), and
    a setup whose frames are missing simply stays silent.
    """
    symbol = str(getattr(bundle, "symbol", "") or "").upper()
    out: List[Dict[str, Any]] = []
    for setup in (setups or list(PROVIDERS.keys())):
        if not setup_enabled(setup):
            continue
        fn = provide(setup)
        if fn is None:
            continue
        for tf in SETUP_TFS.get(str(setup).upper(), ()):
            df = (frames or {}).get(tf)
            if df is None and bundle is not None:
                try:
                    df = bundle.get(tf)
                except Exception:
                    df = None
            if df is None or len(df) < 40:
                continue
            try:
                events = fn(df, tf, symbol=symbol,
                            bundle=bundle) or []
            except TypeError:
                # providers that take (df, tf) only
                try:
                    events = fn(df, tf) or []
                except Exception as exc:
                    print(f"prebreak {setup} {symbol} {tf} skipped: {exc}")
                    continue
            except Exception as exc:
                print(f"prebreak {setup} {symbol} {tf} skipped: {exc}")
                continue
            for ev in events:
                norm = normalize(ev, symbol=symbol, setup=setup, tf=tf)
                if norm is not None:
                    out.append(norm)
    return out


def watch_event(events: List[Dict[str, Any]], *, band: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """The nearest unbroken edge inside the band — one watch per symbol/cycle."""
    _band = band if band is not None else band_atr()
    best = None
    for ev in events:
        d = float(ev.get("distance_atr") or 0.0)
        if d > _band:
            continue
        if best is None or d < float(best.get("distance_atr") or 9e9):
            best = ev
    return best


def edge_broken(ev: Dict[str, Any], df) -> bool:
    """True when the edge is ALREADY broken (a close beyond it) — then the
    confirm lane owns the moment and this lane must stay silent."""
    try:
        edge = float(ev.get("edge") or 0.0)
        side = str(ev.get("side") or "upper").lower()
        if edge <= 0 or df is None or len(df) < 3:
            return False
        _last = float(df["close"].iloc[-1])
        _prev = float(df["close"].iloc[-2])
        _tol = 0.10 * float(ev.get("atr") or 0.0)
        if side == "upper":
            return bool(_last > edge + _tol and _prev > edge)
        return bool(_last < edge - _tol and _prev < edge)
    except Exception:
        return False


# ── the watch chain (one chain per edge: watch → confirm) ───────────────────
_CONFIRM_TF_BELOW = {"5m": "1m", "15m": "5m", "30m": "15m", "1h": "15m",
                     "2h": "30m", "4h": "1h", "8h": "2h", "1d": "4h", "3d": "1d"}
_SETUP_FA = {"TECHCLASSIC": "TECNOCLASIC", "ALBROX": "ALBROX",
             "PINVAL": "PINVAL", "PINWALLQ": "PINWALL QUALITY", "TLBREAK": "VIVA-TLBREAK"}


def _confirm_tf_for(tf: str, setup: str) -> str:
    """The confirm TF is one step BELOW the trigger TF (R62 ladder: 1h←15m,
    4h←1h, 30m←15m) — the same law every other chain follows."""
    try:
        from analysis.confirm_r62 import confirm_tf_for_trigger as _cft
        _w = _cft(str(tf))
        if _w:
            return str(_w)
    except Exception:
        pass
    return _CONFIRM_TF_BELOW.get(str(tf), "15m")


def _render_patterns(ev: Dict[str, Any], edge_ts: str = "") -> list:
    """The chart's geometry, taken from the OWN engine's pivots (never invented)."""
    lns = []
    for key, side in (("upper_points", "upper"), ("lower_points", "lower")):
        pts = []
        for p in (ev.get(key) or []):
            try:
                pts.append({"ts": str(p.get("timestamp") or p.get("ts")),
                            "price": float(p.get("price"))})
            except Exception:
                continue
        if len(pts) >= 2:
            lns.append({"side": side, "points": pts})
    if not lns:
        for _k in ("trendline_points", "pin_points"):
            pts = []
            for p in (ev.get(_k) or []):
                try:
                    pts.append({"ts": str(p.get("ts") or p.get("timestamp")),
                                "price": float(p.get("price"))})
                except Exception:
                    continue
            if len(pts) >= 2:
                lns.append({"side": str(ev.get("side") or "upper"), "points": pts})
            elif len(pts) == 1 and edge_ts:
                lns.append({"side": str(ev.get("side") or "upper"),
                            "points": [pts[0], {"ts": edge_ts, "price": float(ev.get("edge") or 0)}]})
    if not lns:
        return []
    return [{"type": str(ev.get("pattern") or "PATTERN"), "lines": lns}]


def build_watch_candidate(ev: Dict[str, Any], frame=None):
    """The pre-break WATCH chain — the anchor the confirmation later replies to."""
    from analysis.models import SignalCandidate, generate_viva_public_code
    _sym = str(ev.get("symbol") or "").upper()
    _setup = str(ev.get("setup") or "").upper()
    _tf = str(ev.get("tf") or "1h").lower()
    _edge = float(ev.get("edge") or 0.0)
    _atr = float(ev.get("atr") or 0.0) or max(_edge * 0.004, 1e-9)
    _dir = str(ev.get("direction") or "LONG").upper()
    _side = str(ev.get("side") or "upper").lower()
    _measured = ev.get("measured") or {}
    _height = 0.0
    try:
        _height = abs(float(_measured.get("height") or 0.0))
    except Exception:
        _height = 0.0
    _height = _height or (2.0 * _atr)
    _ts = ""
    try:
        _ts = str(pd.Timestamp(frame["timestamp"].iloc[-1])) if frame is not None else ""
    except Exception:
        _ts = ""
    _sgn = 1.0 if _dir == "LONG" else -1.0
    cand = SignalCandidate(
        signal_id=f"viva-pb-{_sym}-{_setup}-{_tf}-{time.strftime('%y%m%d%H%M', time.gmtime())}",
        symbol=_sym, style=("DAYTRADE" if _tf in ("15m", "30m") else "SWING"),
        setup_code=_setup, setup_name=f"{_SETUP_FA.get(_setup, _setup)} · هشدار ابتدایی",
        strategy_fa=f"{_SETUP_FA.get(_setup, _setup)} | نزدیک شدن به ضلع، پیش از شکست",
        direction=_dir, score=max(6, int(float(ev.get("score") or 6))),
        status="EDUCATIONAL",
        # ── R99q14 BOX CALIBRATION (his 10-15 law: «باکس باید … روی بالای ترند
        # بالایی برای لانگ و زیر ترند پایین پترن برای شورت بصورت کالیبره روی و
        # زیر اضلاع پترنها قرار بگیره»): the watch box sits exactly ON the edge
        # and extends AWAY from the pattern (long: above the upper edge, short:
        # below the lower) — never straddling the line.
        entry_zone_bottom=(float(_edge) if _dir == "LONG" else float(_edge) - 0.30 * _atr),
        entry_zone_top=(float(_edge) + 0.30 * _atr if _dir == "LONG" else float(_edge)),
        planned_entry=float(_edge),
        sl=float(_edge) - _sgn * 1.5 * _atr,
        tp1=float(_edge) + _sgn * 0.8 * _height,
        tp2=float(_edge) + _sgn * 1.5 * _height,
        rr_tp1=0.0, rr_tp2=0.0,
        bias=("BULLISH" if _dir == "LONG" else "BEARISH"),
        trigger_timeframe=_tf,
        expires_at="",
        # R99q14: the watch is born from a VALIDATED edge of the owning engine,
        # so the confirmation's mandatory-gate line is satisfied by construction
        # (the only remaining condition is the one-close law itself). The old
        # `viva_watch_only: False` shape blocked every two-pivot watch chain.
        mandatory_gates={"viva_prebreak_watch": True, "pattern_validated": True},
    )
    _geom_ts = _ts
    md = dict(ev.get("metadata") or {})
    md.update({
        "public_code": generate_viva_public_code(_setup, cand.style),
        "market": "FUTURES",
        "viva_state": "S0_WATCH",
        "alert_stage": "PREBREAK",
        "prebreak": True,
        "prebreak_setup": _setup,
        "prebreak_edge": float(_edge),
        "prebreak_side": _side,
        "prebreak_distance_atr": float(ev.get("distance_atr") or 0.0),
        "prebreak_state": str(ev.get("state") or "EDGE_NEAR"),
        "viva_watch_line": float(_edge),
        "viva_break_line": float(_edge),          # the confirm lane's own edge
        "viva_breakout_line": float(_edge),
        "viva_pattern": str(ev.get("pattern") or ""),
        "viva_pattern_fa": str(ev.get("pattern_fa") or ""),
        "pattern_geo": dict(ev.get("pattern_geo") or {}),
        "line_geo": dict(ev.get("line_geo") or {}),
        "viva_upper_points": list(ev.get("upper_points") or []),
        "viva_lower_points": list(ev.get("lower_points") or []),
        "viva_watch_points": list(ev.get("edge_points") or ev.get("trendline_points")
                                  or ev.get("pin_points") or []),
        "viva_touch_count": int(ev.get("touches") or 0),
        "atr": float(ev.get("atr") or 0.0),
        "confirm_tf": _confirm_tf_for(_tf, _setup),
        "chart_view_tf": _tf,
        "touched": False,
        "measured": dict(_measured),
        "render_patterns": _render_patterns(ev, _geom_ts),
        "prebreak_note_fa": str(ev.get("note_fa") or ""),
    })
    if ev.get("zones"):
        md["render_zones"] = list(ev.get("zones") or [])
    if ev.get("pin_high") is not None:
        md["pin_high"] = float(ev.get("pin_high") or 0.0)
        md["pin_low"] = float(ev.get("pin_low") or 0.0)
    cand.metadata = md
    return cand

def enabled() -> bool:
    return str(os.getenv("VIVA_PREBREAK_ENABLED", "1") or "1").strip() != "0"


# ── cost guards (his standing «مصرف Railway» ruling): the lane is a WATCH lane
# with a 45-minute cadence, so it does not need to re-fit every engine on every
# 5-minute pass, and a setup whose break lane already spoke this scan has
# nothing to pre-warn about.
_LAST_RUN: Dict[str, float] = {}


def every_minutes() -> float:
    return max(1.0, _env_float("VIVA_PREBREAK_EVERY_MIN", 15.0))


def due(symbol: str) -> bool:
    try:
        _now = time.time()
        _last = float(_LAST_RUN.get(str(symbol).upper()) or 0.0)
        if _last and (_now - _last) < every_minutes() * 60.0:
            return False
        _LAST_RUN[str(symbol).upper()] = _now
        if len(_LAST_RUN) > 2000:
            _LAST_RUN.clear()
        return True
    except Exception:
        return True

def prebreak_candidates(bundle, *, cap: Optional[int] = None,
                        skip_setups: Optional[Any] = None) -> List[Any]:
    """Mint the pre-break WATCH candidates for one symbol (the scan's own
    education lane posts them, with the chart and the standard watch budget).

    Nothing is ever sent from here: the caller (`run_discovery_scan`) hands the
    returned candidates to the SAME educational dispatch every other setup uses
    — one message law, one chart law, one set of Telegram receipts.
    """
    out: List[Any] = []
    if not enabled():
        return out
    _cap = int(cap if cap is not None else max_per_cycle())
    if sent_today() >= daily_cap():
        return out
    symbol = str(getattr(bundle, "symbol", "") or "").upper()
    if not due(symbol):
        return out
    _skip = {str(x).upper() for x in (skip_setups or ())}
    _all: List[Dict[str, Any]] = []
    for setup in list(PROVIDERS.keys()):
        if len(out) >= _cap:
            break
        if not setup_enabled(setup):
            continue
        if str(setup).upper() in _skip:
            continue          # its break lane already spoke this scan
        fn = provide(setup)
        if fn is None:
            continue
        _minted: List[Dict[str, Any]] = []
        for tf in SETUP_TFS.get(str(setup).upper(), ()):
            try:
                df = bundle.get(tf)
            except Exception:
                df = None
            if df is None or len(df) < 45:
                continue
            try:
                events = fn(df, tf, symbol=symbol, bundle=bundle) or []
            except TypeError:
                try:
                    events = fn(df, tf) or []
                except Exception as exc:
                    print(f"prebreak {setup} {symbol} {tf} skipped: {exc}")
                    continue
            except Exception as exc:
                print(f"prebreak {setup} {symbol} {tf} skipped: {exc}")
                continue
            for ev in events:
                norm = normalize(ev, symbol=symbol, setup=setup, tf=tf)
                if norm is None:
                    continue
                if edge_broken(norm, df):
                    continue                       # the confirm lane owns that moment
                norm["_frame"] = df
                _minted.append(norm)
        if not _minted:
            continue
        _inside = inside_band_atr()
        for _e in _minted:
            if float(_e.get("distance_atr") or 9e9) <= _inside:
                _all.append(_e)
    if not _all:
        return out
    # ONE watch per EDGE: the same level answered by two setups (PINVAL and its
    # PINWALL QUALITY twin, or a shared line) speaks once — the closest, then
    # the better-scored answer wins.
    _all.sort(key=lambda e: (float(e.get("distance_atr") or 9e9),
                             -float(e.get("score") or 0.0)))
    _kept: List[Dict[str, Any]] = []
    for _e in _all:
        _dup = False
        for _k in _kept:
            try:
                if str(_k.get("side")) != str(_e.get("side")):
                    continue
                _gap = abs(float(_k.get("edge") or 0) - float(_e.get("edge") or 0))
                if _gap <= max(0.05 * float(_k.get("atr") or 1), 1e-9) or \
                        _gap <= 0.0006 * abs(float(_e.get("edge") or 1)):
                    _dup = True
                    break
            except Exception:
                continue
        if not _dup:
            _kept.append(_e)
    for ev in _kept[: max(1, _cap - len(out))]:
        if len(out) >= _cap or sent_today() + len(out) >= daily_cap():
            break
        if not cooldown_ok(str(ev.get("symbol")), str(ev.get("setup")),
                           str(ev.get("tf")), str(ev.get("side"))):
            continue
        try:
            cand = build_watch_candidate(ev, ev.get("_frame"))
        except Exception as exc:
            print(f"prebreak candidate failed {ev.get('symbol')} {ev.get('setup')}: {exc}")
            continue
        try:
            stamp_only(str(ev.get("symbol")), str(ev.get("setup")),
                       str(ev.get("tf")), str(ev.get("side")))
        except Exception:
            pass
        print(f"⏸ PRE-BREAK WATCH {cand.symbol} {cand.setup_code} {cand.trigger_timeframe} "
              f"edge={ev.get('edge')} dist={ev.get('distance_atr')} ATR "
              f"({str(ev.get('state') or '')})")
        out.append(cand)
    return out
