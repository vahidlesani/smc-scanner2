"""TOHOM — the early-confirmation engine (Viva 2026-09-27, verbatim: «یه
انجین هوشمند واسه ورود قبل از کلوز تایم تریگر … دقیقا شبیه همین خروج هوشمند
استاپ تریلینگ برای ورود هم از تایم پایین‌تر مجازه که فرصت خوب از دست نره»).

His law, operationalised:
  • Every trigger TF has a HALF ladder step under it. While the trigger candle
    is still FORMING, its first N closed sub-candles may confirm the entry:
    N = 3 normally («کلوز سوم کندل تایم پایین‌ترش»), N = 2 when confidence is
    high («حتی ساعت دوم اگر اطمینان بالا بود»).
  • Evidence (LONG; mirrored for SHORT):
      – every sub-close makes progress and the last sub-candle is directional;
      – the last sub-CLOSE is beyond the SAME break edge the one-close law
        waits for (pin extreme → viva lines → major line → zone edge);
      – volume is UP noticeably («حجم بالا رفته محسوس»): last sub-volume
        ≥ 1.3× the mean of the previous twenty and above the previous sub's
        volume (high-confidence lane: ≥ 2.0×);
      – a direction-aligned pattern on the last three subs: pin bar,
        engulfing, or a power candle.
    High confidence = score ≥ 9 AND volume ≥ 2.0× AND a strong pattern.
  • Fail-closed on every doubt — TOHOM may only ADD a confirmation the normal
    close law would later grant anyway, never loosen it. Kill switch:
    TOHOM_ENABLED=0 restores the pure one-close law.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd

from analysis.models import SignalCandidate

# the HALF ladder: trigger TF → the sub-TF whose candles tile it
TOHOM_LOWER_TF = {"1d": "4h", "4h": "1h", "2h": "30m", "1h": "15m",
                  "30m": "5m", "15m": "5m"}
TF_MIN = {"1m": 1.0, "3m": 3.0, "5m": 5.0, "15m": 15.0, "30m": 30.0,
          "1h": 60.0, "2h": 120.0, "4h": 240.0, "1d": 1440.0,
          "8h": 480.0, "12h": 720.0, "3d": 4320.0, "1w": 10080.0}


def _direction(sign_meta) -> int:
    return 1 if str(sign_meta or "").upper() == "LONG" else -1


def _break_edge(candidate: SignalCandidate) -> float:
    """The SAME edge the one-close law waits for (priority order mirrored from
    quality_engine.evaluate_confirmation): pin extreme → viva lines → major
    line → the zone's entry edge."""
    md = candidate.metadata or {}
    direction = str(candidate.direction or "").upper()
    edge = 0.0
    try:
        setup = str(getattr(candidate, "setup_code", "") or "").upper()
        if setup in {"PINVAL", "PINWALLQ"}:
            lvl = float(md.get("pin_high" if direction == "LONG" else "pin_low") or 0)
            if lvl > 0:
                edge = lvl
    except Exception:
        pass
    if edge <= 0:
        for key in ("viva_breakout_line", "viva_break_line", "viva_watch_line"):
            try:
                v = float(md.get(key) or 0)
            except Exception:
                v = 0.0
            if v > 0:
                edge = v
                break
    if edge <= 0:
        try:
            maj = float(md.get("viva_major_break_line") or 0)
            planned = float(getattr(candidate, "planned_entry", 0) or 0)
            atr = float(md.get("atr", 0) or 0)
            sane = abs(maj - planned) <= max(0.04 * maj, 2.5 * atr) if maj > 0 else False
            if maj > 0 and sane:
                edge = maj
        except Exception:
            pass
    if edge <= 0:
        zt = float(getattr(candidate, "entry_zone_top", 0) or 0)
        zb = float(getattr(candidate, "entry_zone_bottom", 0) or 0)
        edge = zt if direction == "LONG" else zb
    return float(edge)


def _pin_like(row: pd.Series, direction: int) -> bool:
    hi, lo = float(row["high"]), float(row["low"])
    op, cl = float(row["open"]), float(row["close"])
    rng = max(hi - lo, 1e-12)
    body = abs(cl - op)
    if direction > 0:
        lower_wick = min(op, cl) - lo
        return lower_wick >= 1.5 * body and (cl - lo) >= 0.6 * rng
    upper_wick = hi - max(op, cl)
    return upper_wick >= 1.5 * body and (hi - cl) >= 0.6 * rng


def _engulfing(prev: pd.Series, cur: pd.Series, direction: int) -> bool:
    po, pc = float(prev["open"]), float(prev["close"])
    co, cc = float(cur["open"]), float(cur["close"])
    if direction > 0:
        return pc < po and cc > co and cc >= po and co <= pc
    return pc > po and cc < co and cc <= po and co >= pc


def _power_candle(row: pd.Series, direction: int) -> bool:
    hi, lo = float(row["high"]), float(row["low"])
    op, cl = float(row["open"]), float(row["close"])
    rng = max(hi - lo, 1e-12)
    body = abs(cl - op)
    if direction > 0 and cl <= op:
        return False
    if direction < 0 and cl >= op:
        return False
    return body >= 0.65 * rng


def evaluate_tohom_confirmation(
    candidate: SignalCandidate, lower_closed_df: Optional[pd.DataFrame],
    trigger_open: Optional[pd.Timestamp] = None,
    now: Optional[pd.Timestamp] = None,
) -> Tuple[bool, SignalCandidate, str]:
    """TOHOM gate — returns (confirmed, candidate, reason_fa). Fail-closed."""
    md = candidate.metadata or {}
    if md.get("tohom_checked"):
        return False, candidate, "توهم قبلاً بررسی شده است."
    md["tohom_checked"] = True

    def reject(code: str, msg: str):
        md["last_reject_code"] = code
        return False, candidate, msg

    direction = _direction(getattr(candidate, "direction", ""))
    tf = str(getattr(candidate, "trigger_timeframe", "") or "").lower()
    sub_tf = TOHOM_LOWER_TF.get(tf)
    if not sub_tf:
        return reject("TOHOM_TF", "برای این تایم‌فریم پلهٔ پایین تعریف نشده است.")
    try:
        from config import get_settings
        if not getattr(get_settings(), "tohom_enabled", True):
            return reject("TOHOM_OFF", "انجین توهم خاموش است.")
    except Exception:
        pass
    if lower_closed_df is None or len(lower_closed_df) < 25:
        return reject("TOHOM_NO_DATA", "کندل تایم پایین‌تر کافی نیست.")

    if now is None:
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    if getattr(lower_closed_df["timestamp"].dtype, "tz", None) is not None:
        now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    if trigger_open is None:
        trigger_open = now.floor(pd.Timedelta(minutes=TF_MIN.get(tf, 60.0)))

    frame = lower_closed_df.copy()
    ts = pd.to_datetime(frame["timestamp"])
    if getattr(ts.dtype, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)
    frame["timestamp"] = ts

    closed = frame[frame["timestamp"].shift(1) + pd.Timedelta(minutes=TF_MIN.get(sub_tf, 5.0)) <= now]
    closed = closed[closed["timestamp"] >= pd.Timestamp(trigger_open)] if getattr(trigger_open, "tzinfo", None) is None \
        else closed[closed["timestamp"] >= pd.Timestamp(trigger_open).tz_localize(None)]
    subs = closed.tail(4)  # keep a little context
    n_subs = len(subs)
    need = 3
    score = float(getattr(candidate, "score", 0) or 0)
    last_row = subs.iloc[-1] if n_subs else None
    vol_ratio = 0.0
    if last_row is not None and n_subs >= 2:
        hist = frame[frame["timestamp"] < subs.iloc[0]["timestamp"]]["volume"].tail(20)
        base = float(hist.mean()) if len(hist) else 0.0
        vol_ratio = (float(last_row["volume"]) / base) if base > 0 else 0.0
        strong = vol_ratio >= 2.0 and score >= 9.0
        if strong:
            need = 2
    if n_subs < need:
        return reject("TOHOM_WAIT", f"تنها {n_subs} کندلِ {sub_tf} از این کندلِ {tf} بسته شده است.")

    last3 = subs.tail(need)
    closes = [float(v) for v in last3["close"]]
    opens = [float(v) for v in last3["open"]]
    direction_ok = True
    for i in range(1, len(closes)):
        if direction > 0 and closes[i] < closes[i - 1]:
            direction_ok = False
        if direction < 0 and closes[i] > closes[i - 1]:
            direction_ok = False
    last = last3.iloc[-1]
    if direction > 0 and float(last["close"]) <= float(last["open"]):
        direction_ok = False
    if direction < 0 and float(last["close"]) >= float(last["open"]):
        direction_ok = False
    if not direction_ok:
        return reject("TOHOM_DIR", "کندل‌های تایم پایین‌تر جهتِ یکنواخت ندارند.")

    edge = _break_edge(candidate)
    atr = float(md.get("atr", 0) or 0)
    if edge <= 0:
        return reject("TOHOM_EDGE", "لبهٔ شکست برای توهم پیدا نشد.")
    margin = 0.10 * atr if atr > 0 else 0.0002 * edge
    beyond = (float(last["close"]) >= edge + margin) if direction > 0 \
        else (float(last["close"]) <= edge - margin)
    if not beyond:
        return reject("TOHOM_BEYOND", "کلوزِ تایم پایین‌تر هنوز از لبهٔ شکست عبور نکرده است.")

    if vol_ratio < 1.3 or float(last["volume"]) <= float(subs.iloc[-2]["volume"]):
        return reject("TOHOM_VOL", "رشد حجمِ محسوس روی تایم پایین‌تر دیده نشد.")

    pattern = ""
    for i in range(max(0, n_subs - 3), n_subs):
        row = subs.iloc[i]
        if _pin_like(row, direction):
            pattern = "پین‌بار"
        elif i > 0 and _engulfing(subs.iloc[i - 1], row, direction):
            pattern = "انگلفینگ"
        elif _power_candle(row, direction):
            pattern = "کندلِ قدرتی"
        if pattern:
            break
    if not pattern:
        return reject("TOHOM_PATTERN", "الگوی موافق (پین‌بار/انگلفینگ/قدرتی) روی سه کندلِ اخیر نیست.")

    md["tohom"] = 1
    md["tohom_sub_tf"] = sub_tf
    md["tohom_subs"] = int(need)
    md["tohom_vol_ratio"] = round(vol_ratio, 2)
    md["tohom_pattern"] = pattern
    md["technical_confirmation_complete"] = True
    reason = (f"⚡ تأیید زودهنگام توهم: {need} کلوزِ پیوستهٔ تایم {sub_tf.upper()} در جهت "
              f"{'صعودی' if direction > 0 else 'نزولی'} با رشد حجم {vol_ratio:.1f}× و الگوی {pattern}، "
              "بیش از لبهٔ شکست.")
    md["tohom_note_fa"] = reason
    return True, candidate, reason
