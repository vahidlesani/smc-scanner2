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
    return _break_edge_src(candidate)[0]


def _break_edge_src(candidate: SignalCandidate):
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
    src = "PIN" if edge > 0 else ""
    if edge <= 0:
        for key in ("viva_breakout_line", "viva_break_line", "viva_watch_line"):
            try:
                v = float(md.get(key) or 0)
            except Exception:
                v = 0.0
            if v > 0:
                edge = v
                src = "LINE"
                break
    if edge <= 0:
        try:
            maj = float(md.get("viva_major_break_line") or 0)
            planned = float(getattr(candidate, "planned_entry", 0) or 0)
            atr = float(md.get("atr", 0) or 0)
            sane = abs(maj - planned) <= max(0.04 * maj, 2.5 * atr) if maj > 0 else False
            if maj > 0 and sane:
                edge = maj
                src = "MAJOR"
        except Exception:
            pass
    if edge <= 0:
        zt = float(getattr(candidate, "entry_zone_top", 0) or 0)
        zb = float(getattr(candidate, "entry_zone_bottom", 0) or 0)
        edge = zt if direction == "LONG" else zb
        src = "ZONE"
    return float(edge), src


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


def _doji_like(row: pd.Series) -> bool:
    """r60 (Viva 09-29 §6): the dojo/dogi is part of his confirming candle
    vocabulary — a genuine indecision pause (tiny body on a real range) that
    rides along WITH the directional sub-closes and volume."""
    rng = float(row["high"]) - float(row["low"])
    return rng > 0 and abs(float(row["close"]) - float(row["open"])) <= 0.12 * rng


def _reverse_pin(row: pd.Series, direction: int) -> bool:
    """r60 (Viva 09-29 §6): «پین‌بار معکوس» — the wick pokes BACK toward the
    broken line (against the trade direction: the failed retest) while the
    body closes on the trade's side. Exactly the FTB rejection candle."""
    rng = max(float(row["high"]) - float(row["low"]), 1e-12)
    mid = (float(row["high"]) + float(row["low"])) / 2.0
    body_top = max(float(row["close"]), float(row["open"]))
    body_bottom = min(float(row["close"]), float(row["open"]))
    if direction > 0:
        return (float(row["high"]) - body_top) >= 0.40 * rng and float(row["close"]) >= mid
    return (body_bottom - float(row["low"])) >= 0.40 * rng and float(row["close"]) <= mid


def tohom_frame_tf(candidate) -> Optional[str]:
    """R62-ARENA: the sub-TF the smart engine reads for this chain — one step
    below the chain's CONFIRM TF (1h trigger → 15m confirm → 5m TOHOM), so the
    engine can confirm BEFORE the lower-TF confirm candle closes. Falls back
    to the r47 half-ladder for TFs outside the ladder."""
    tf = str(getattr(candidate, "trigger_timeframe", "") or "").lower()
    try:
        from analysis.confirm_r62 import tohom_sub_tf
        sub = tohom_sub_tf(tf)
        if sub:
            return sub
    except Exception:
        pass
    return TOHOM_LOWER_TF.get(tf)


def evaluate_tohom_confirmation(
    candidate: SignalCandidate, lower_closed_df: Optional[pd.DataFrame],
    trigger_open: Optional[pd.Timestamp] = None,
    now: Optional[pd.Timestamp] = None,
    sub_tf: Optional[str] = None,
) -> Tuple[bool, SignalCandidate, str]:
    """TOHOM gate — returns (confirmed, candidate, reason_fa). Fail-closed.

    R62-ARENA (audit TH1–TH4): no longer ONE-SHOT. The old code stamped
    ``tohom_checked`` BEFORE looking at anything, so the very first look
    (usually «only one sub-candle closed yet») killed the engine for the
    chain's whole life. Now the engine re-evaluates on every NEW closed
    sub-candle (dedupe = last sub-bar timestamp), the break level is the
    shared sloped edge (``confirm_r62.confirm_edge_at``) and the sub-candles
    are those closed after the alert was minted.
    """
    md = candidate.metadata if isinstance(getattr(candidate, "metadata", None), dict) else {}
    if getattr(candidate, "metadata", None) is None:
        try:
            candidate.metadata = md
        except Exception:
            pass

    def reject(code: str, msg: str):
        md["last_reject_code"] = code
        md["tohom_last_reject"] = code
        return False, candidate, msg

    direction = _direction(getattr(candidate, "direction", ""))
    tf = str(getattr(candidate, "trigger_timeframe", "") or "").lower()
    sub_tf = sub_tf or tohom_frame_tf(candidate)
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
    _explicit_open = trigger_open is not None
    if trigger_open is None:
        trigger_open = now.floor(pd.Timedelta(minutes=TF_MIN.get(tf, 60.0)))

    frame = lower_closed_df.copy()
    ts = pd.to_datetime(frame["timestamp"])
    if getattr(ts.dtype, "tz", None) is not None:
        ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    frame["timestamp"] = ts
    _now_n = pd.Timestamp(now)
    if _now_n.tzinfo is not None:
        _now_n = _now_n.tz_convert("UTC").tz_localize(None)
    _open_n = pd.Timestamp(trigger_open)
    if _open_n.tzinfo is not None:
        _open_n = _open_n.tz_convert("UTC").tz_localize(None)

    # The caller hands CLOSED sub-candles (main drops the forming row of a
    # fresh, uncached fetch — audit TH3); nothing stamped after `now` counts.
    closed = frame[frame["timestamp"] <= _now_n]
    # information boundary: sub-candles after the alert was minted; without
    # a creation stamp (legacy callers) the forming trigger candle is the window.
    _start = _open_n
    try:
        _ca = None if _explicit_open else getattr(candidate, "created_at", None)
        if _ca:
            _cat = pd.Timestamp(str(_ca))
            if _cat.tzinfo is not None:
                _cat = _cat.tz_convert("UTC").tz_localize(None)
            _start = _cat
    except Exception:
        pass
    closed = closed[closed["timestamp"] >= _start]
    if len(closed):
        _last_bar = str(closed["timestamp"].iloc[-1])[:19]
        if md.get("tohom_last_sub_bar") == _last_bar:
            return False, candidate, "توهم این کندلِ تایم پایین را قبلاً سنجیده است؛ منتظر کندلِ بعدی."
        md["tohom_last_sub_bar"] = _last_bar
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
    # r60 FTB (Viva 09-29 §6): at the First Time Back the LTF has usually just
    # printed its pullback candle — a perfectly monotonic streak would reject
    # exactly the retest he wants confirmed early. ONE counter step inside the
    # window is allowed; the LAST sub-candle must still close our way.
    _bad = 0
    for i in range(1, len(closes)):
        if direction > 0 and closes[i] < closes[i - 1]:
            _bad += 1
        if direction < 0 and closes[i] > closes[i - 1]:
            _bad += 1
    direction_ok = _bad <= (1 if len(closes) >= 3 else 0)
    last = last3.iloc[-1]
    if direction > 0 and float(last["close"]) <= float(last["open"]):
        direction_ok = False
    if direction < 0 and float(last["close"]) >= float(last["open"]):
        direction_ok = False
    if not direction_ok:
        return reject("TOHOM_DIR", "کندل‌های تایم پایین‌تر جهتِ یکنواخت ندارند.")

    edge, _src = _break_edge_src(candidate)
    if _src == "LINE":
        # R62-ARENA (audit TH4): the SAME sloped edge the close law judges
        try:
            from analysis.confirm_r62 import confirm_edge_at
            _when = pd.Timestamp(last["timestamp"]) + pd.Timedelta(minutes=TF_MIN.get(sub_tf, 5.0))
            _proj = confirm_edge_at(candidate, _when)
            if _proj > 0:
                edge = float(_proj)
        except Exception:
            pass
    atr = float(md.get("atr", 0) or 0)
    if edge <= 0:
        return reject("TOHOM_EDGE", "لبهٔ شکست برای توهم پیدا نشد.")
    margin = 0.10 * atr if atr > 0 else 0.0002 * edge
    # ── r60 FTB: the retest touch means price is ON the broken line by
    # definition — demanding the fresh-break clearance there waits for a
    # second break that may never print. Halve the clearance once the
    # candidate has touched back (his FTB early-confirm law).
    _ftb60 = bool(md.get("touched")) or str(md.get("viva_state") or "").upper().startswith("S3")
    if _ftb60:
        margin *= 0.5
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
        elif _doji_like(row):
            pattern = "دوجی"
        elif _reverse_pin(row, direction):
            pattern = "پین‌بار معکوس"
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
    candidate.status = "CONFIRMED"
    from analysis.models import iso_now
    candidate.confirmed_at = candidate.confirmed_at or iso_now()
    reason = (f"⚡ تأیید زودهنگام توهم{' در First Time Back (FTB)' if _ftb60 else ''}: "
              f"{need} کلوزِ پیوستهٔ تایم {sub_tf.upper()} در جهت "
              f"{'صعودی' if direction > 0 else 'نزولی'} با رشد حجم {vol_ratio:.1f}× و الگوی {pattern}، "
              f"{'روی' if _ftb60 else 'بیش از'} لبهٔ شکست ثبت شد — به همین دلیل ورود پیش از "
              f"کلوزِ کندلِ {str(tf).upper()} تأیید شد.")
    md["tohom_note_fa"] = reason
    md["tohom_edge"] = float(edge)
    md["tohom_confirm_bar"] = str(last["timestamp"])[:19]
    md["tohom_confirm_close"] = float(last["close"])
    return True, candidate, reason
