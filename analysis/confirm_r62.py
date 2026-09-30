"""R62-ARENA — one shared confirmation core (2026-09-30).

Viva's request that opened this round (verbatim intent): «هر تایم‌فریم باید از
تایم پایین‌تر تأیید بگیره با دیدن الگوهای کندلی که نشانهٔ شکستِ معتبر باشن؛
حتی موتور هوشمند (توهم) باید زودتر تأیید بکنه و نه یک‌بار». The DOT 1h case:
the 1h candle closed above the trend around 13:00 but the position was
confirmed at 17:00 — the chain was listening on the 4h frame because its
confirm TF had been derived from the PATTERN/context TF (1d → 4h), not from
the trigger TF.

This module owns the pieces every confirmation lane must agree on:

* ``confirm_tf_for_trigger``  — the ONE-STEP ladder keyed by the TRIGGER TF
  (15m←5m, 30m←15m, 1h←15m, 2h←30m, 4h←1h, 1d←4h). The trigger TF's own
  close stays the late fallback (never stall).
* ``tohom_sub_tf``            — the smart engine listens one step BELOW the
  confirm TF so it can confirm before the confirm candle closes.
* ``confirm_edge_at``         — the break level at a given bar time, projected
  along the broken edge's own slope (linear or log). Fast lane, TOHOM, the
  reclaim gate and the live-break note all read this one function, so the
  level the engine waits for is the level the chart draws.
* ``valid_break_candle``      — the candle vocabulary that proves a valid
  break on the lower TF (power candle / engulfing / hammer-pin / strong
  close) and rejects the fake-out shapes (shooting star at the breakout,
  counter-colour close in the wrong half).

Nothing here formats a Telegram message; message templates, the reply-chain
and public codes are untouched by design.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

import pandas as pd

TF_MINUTES: Dict[str, float] = {
    "1m": 1.0, "3m": 3.0, "5m": 5.0, "15m": 15.0, "30m": 30.0, "1h": 60.0,
    "2h": 120.0, "4h": 240.0, "8h": 480.0, "12h": 720.0, "1d": 1440.0,
    "3d": 4320.0, "1w": 10080.0,
}

# ONE step below the trigger (Viva 09-11 / 09-19 ladder, now keyed by TRIGGER).
CONFIRM_LADDER: Dict[str, str] = {
    "5m": "1m",
    "15m": "5m",
    "30m": "15m",
    "1h": "15m",
    "2h": "30m",
    "4h": "1h",
    "1d": "4h",
}

# The smart engine sits one step below the CONFIRM TF.
TOHOM_SUB_OF_CONFIRM: Dict[str, str] = {
    "4h": "1h",
    "1h": "15m",
    "30m": "5m",
    "15m": "5m",
    "5m": "1m",
}


def tf_minutes(tf: Any, default: float = 15.0) -> float:
    return float(TF_MINUTES.get(str(tf or "").lower(), default))


def confirm_tf_for_trigger(trigger_tf: Any, fallback: Optional[str] = None) -> Optional[str]:
    tf = str(trigger_tf or "").lower()
    return CONFIRM_LADDER.get(tf, fallback)


def tohom_sub_tf(trigger_tf: Any) -> Optional[str]:
    """Sub-TF the smart engine reads for a chain on ``trigger_tf``."""
    ctf = confirm_tf_for_trigger(trigger_tf)
    if not ctf:
        return None
    return TOHOM_SUB_OF_CONFIRM.get(ctf)


def normalize_confirm_tf(candidate) -> Optional[str]:
    """Force the ladder onto a (possibly old) chain; returns the confirm TF.

    Chains minted before R62 carry a confirm TF derived from the pattern TF
    (1h trigger → 4h confirm). They are re-pointed to the trigger ladder the
    first time the monitor sees them; the old value is kept for the record.
    """
    md = candidate.metadata if isinstance(getattr(candidate, "metadata", None), dict) else None
    if md is None:
        return None
    want = confirm_tf_for_trigger(getattr(candidate, "trigger_timeframe", ""))
    if not want:
        return md.get("confirm_tf")
    cur = str(md.get("confirm_tf") or "")
    if cur != want:
        if cur and "confirm_tf_legacy" not in md:
            md["confirm_tf_legacy"] = cur
        md["confirm_tf"] = want
    return want


# ── the broken edge, projected in time ─────────────────────────────────────
def _naive(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t


def line_geo_from(line, frame: pd.DataFrame, n: int, tf: str, back: int = 20) -> Dict[str, Any]:
    """Serializable geometry of a fitted edge: value at bar ``n`` + value
    ``back`` bars earlier, the timestamp of bar ``n`` and the bar length.
    Works for linear and log-calibrated lines (price_at handles both)."""
    try:
        n = int(n)
        b = max(1, min(int(back), n)) if n > 0 else 1
        p_now = float(line.price_at(n))
        p_back = float(line.price_at(n - b))
        ts = str(frame["timestamp"].iloc[n])
        if not (p_now > 0 and p_back > 0 and math.isfinite(p_now) and math.isfinite(p_back)):
            return {}
        out = {"ts": ts, "price": p_now, "price_back": p_back, "back_bars": int(b),
               "tf_min": tf_minutes(tf, 60.0), "log": bool(getattr(line, "log_fit", False))}
        try:   # pattern start (the chart keeps it on the canvas — smart zoom)
            fi = int(getattr(line, "first_index", -1))
            if 0 <= fi <= n:
                out["a_ts"] = str(frame["timestamp"].iloc[fi])
        except Exception:
            pass
        return out
    except Exception:
        return {}


def project_line_geo(geo: Dict[str, Any], when) -> float:
    """Value of a stored edge at time ``when`` (0.0 when unusable)."""
    try:
        if not geo:
            return 0.0
        p1, p0 = float(geo["price"]), float(geo["price_back"])
        bars_back = float(geo.get("back_bars") or 0)
        tfm = float(geo.get("tf_min") or 0)
        if not (p1 > 0 and p0 > 0 and bars_back > 0 and tfm > 0):
            return 0.0
        dt_bars = (_naive(when) - _naive(geo["ts"])).total_seconds() / 60.0 / tfm
        if geo.get("log"):
            k = (math.log10(p1) - math.log10(p0)) / bars_back
            return float(10.0 ** (math.log10(p1) + k * dt_bars))
        k = (p1 - p0) / bars_back
        val = p1 + k * dt_bars
        return float(val) if val > 0 else 0.0
    except Exception:
        return 0.0


def _static_edge(candidate) -> Tuple[float, str]:
    """The priority the one-close law has always used (pin → viva lines →
    major line → zone edge). Returns (level, source)."""
    md = getattr(candidate, "metadata", None) or {}
    direction = str(getattr(candidate, "direction", "") or "").upper()
    setup = str(getattr(candidate, "setup_code", "") or "").upper()
    if setup in {"PINVAL", "PINWALLQ"}:
        try:
            lvl = float(md.get("pin_high" if direction == "LONG" else "pin_low") or 0)
            if lvl > 0:
                return lvl, "PIN"
        except Exception:
            pass
    for key in ("viva_breakout_line", "viva_break_line", "viva_watch_line"):
        try:
            v = float(md.get(key) or 0)
        except Exception:
            v = 0.0
        if v > 0:
            return v, "LINE"
    try:
        zt = float(getattr(candidate, "entry_zone_top", 0) or 0)
        zb = float(getattr(candidate, "entry_zone_bottom", 0) or 0)
        return (zt if direction == "LONG" else zb), "ZONE"
    except Exception:
        return 0.0, "NONE"


def confirm_edge_at(candidate, when=None) -> float:
    """THE break level at bar time ``when``.

    * PIN family: the pin extreme (a level, never sloped).
    * Structural lanes with a stored edge geometry (``break_line_geo``):
      the broken edge projected to ``when`` on its own slope — a falling
      trendline keeps falling after the alert, so a later close is judged
      against the line the chart shows, not a frozen alert-time value.
    * legacy TLBREAK anchors (tl_a/tl_b): chord projection, extrapolated.
    * otherwise the static level (line value at alert / zone edge).
    The MAJOR-line upgrade (round 20 entry law) is applied by the caller.
    """
    md = getattr(candidate, "metadata", None) or {}
    static, source = _static_edge(candidate)
    if source == "PIN" or when is None:
        return float(static or 0.0)
    geo = md.get("break_line_geo") or {}
    if geo and source == "LINE":
        v = project_line_geo(geo, when)
        if v > 0:
            # a projection that ran absurdly far from the alert value is a
            # broken geometry, not a line — fall back to the static level
            if static <= 0 or abs(v - static) <= 0.25 * static:
                return v
    try:
        if source == "LINE" and md.get("tl_a_ts") and md.get("tl_b_ts"):
            ta, tb = _naive(md["tl_a_ts"]), _naive(md["tl_b_ts"])
            pa, pb = float(md["tl_a_price"]), float(md["tl_b_price"])
            dt = (tb - ta).total_seconds()
            if dt > 0 and pa > 0 and pb > 0:
                v = pb + (pb - pa) / dt * (_naive(when) - tb).total_seconds()
                if v > 0 and (static <= 0 or abs(v - static) <= 0.25 * static):
                    return float(v)
    except Exception:
        pass
    return float(static or 0.0)


def break_established(md: Dict[str, Any]) -> bool:
    """True once the chain's break has actually printed (detector BREAK event
    or a close beyond the edge seen by the fast lane). A pre-break alert
    that sits below its line has nothing to 'reclaim'."""
    if not md:
        return False
    if md.get("fast_break_bar") or md.get("tl_fast_break") or md.get("break_seen_at"):
        return True
    tc = md.get("technoclassic") or {}
    if isinstance(tc, dict) and str(tc.get("kind") or "") == "break":
        return True
    st = str(md.get("viva_state") or "").upper()
    return st.startswith("S2_BREAKOUT") or st.startswith("S6")


# ── candle vocabulary of a VALID break on the lower TF ─────────────────────
def valid_break_candle(row, prev, direction: str, edge: float,
                       atr: float = 0.0) -> Tuple[bool, str]:
    """(ok, name_fa). ``row`` already closed beyond ``edge``.

    Valid (LONG; SHORT mirrored):
      • کندل قدرتی/ماروبوزو — bullish body ≥ 55% of range
      • انگلفینگ صعودی     — bullish body engulfs a bearish previous body
      • پین‌بار/چکش         — lower wick ≥ 1.5× body, close in the top 40%
      • کلوز قوی           — bullish close in the top third of the range
    Invalid (the fake-out shapes):
      • ستارهٔ دنباله‌دار روی شکست — upper wick ≥ 2× body, close in lower 40%
      • کندل خلاف‌جهت با کلوز در نیمهٔ مخالف
    Any other bullish close beyond the edge passes as «کلوز صعودی پشت خط».
    """
    try:
        o, h, l, c = (float(row["open"]), float(row["high"]),
                      float(row["low"]), float(row["close"]))
    except Exception:
        return True, ""
    rng = max(h - l, 1e-12)
    body = abs(c - o)
    long_ = str(direction or "").upper() == "LONG"
    up_wick = h - max(o, c)
    lo_wick = min(o, c) - l
    pos = (c - l) / rng          # 0 = closed on the low, 1 = on the high
    if not long_:
        pos = 1.0 - pos
        up_wick, lo_wick = lo_wick, up_wick
    directional = (c > o) if long_ else (c < o)
    # fake-outs first
    if up_wick >= 2.0 * max(body, 1e-12) and pos <= 0.40:
        return False, ("ستارهٔ دنباله‌دار روی شکست" if long_ else "چکشِ برگشتی روی شکست")
    if not directional and pos < 0.5:
        return False, "کندل خلاف‌جهت با کلوز در نیمهٔ مخالف"
    if directional and body >= 0.55 * rng:
        return True, "کندل قدرتی (ماروبوزو)"
    try:
        if prev is not None:
            po, pc = float(prev["open"]), float(prev["close"])
            if long_ and pc < po and c > o and c >= po and o <= pc:
                return True, "انگلفینگ صعودی"
            if (not long_) and pc > po and c < o and c <= po and o >= pc:
                return True, "انگلفینگ نزولی"
    except Exception:
        pass
    if lo_wick >= 1.5 * max(body, 1e-12) and pos >= 0.60:
        return True, ("پین‌بار/چکش" if long_ else "پین‌بار/ستارهٔ دنباله‌دار")
    if directional and pos >= 2.0 / 3.0:
        return True, "کلوز قوی"
    if directional:
        return True, ("کلوز صعودی پشت خط" if long_ else "کلوز نزولی پشت خط")
    # a counter-colour candle that still closed in its good half (doji-ish
    # hold above the line) — accepted, it is a hold, not a rejection
    return True, "دوجی/نگه‌داشت پشت خط"


def frame_minutes(frame: Optional[pd.DataFrame]) -> float:
    """Median bar length of a frame in minutes (0.0 when unknown)."""
    try:
        if frame is None or len(frame) < 3 or "timestamp" not in frame.columns:
            return 0.0
        ts = pd.to_datetime(frame["timestamp"])
        d = ts.diff().dt.total_seconds().dropna()
        return float(d.median() / 60.0) if len(d) else 0.0
    except Exception:
        return 0.0
