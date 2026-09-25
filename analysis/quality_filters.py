"""R31.5 replay-backed quality filters — every one is OFF by default.

The walk-forward replay (docs/REPLAY_2026-09-25.md, 120d × 10 symbols, 1189
closed trades) found two filters that improved expectancy in BOTH halves
(IS and OOS) and in every main stream:

  HTF_TREND_GATE=4h   the trade direction must agree with the 4h close vs
                      its EMA50 (with trend −0.002 R vs against −0.081 R).
                      Implemented as a mandatory gate → an against-trend
                      candidate becomes DEAD_GATE (educational only).
  MIN_STOP_FLOOR=1    reject a confirmation whose stop is tighter than the
                      TF floor (15m 1.2% · 30m 1.4% · 1h 1.6% · 4h 2.5% ·
                      1d 4.0%); stops <1.2% won 54% at −0.10 R/trade —
                      Viva's own 09-23 note «استاپ‌ها خیلی کوچیک و بلافاصله
                      هانت میشه». A custom map may be passed instead of "1":
                      MIN_STOP_FLOOR="15m:1.0,1h:1.5".

  MIN_CONFIRM_BAR=1   (review B4) — REJECTED by the in-engine replay (round 3:
                      −0.035 R alone, −0.001 R on top of the trend gate; the
                      chain waits and enters later at a worse price). Kept only
                      so the A/B stays reproducible — do NOT enable. The bar must
                      have a body ≥ 0.3 × mean range(14) of its frame AND close
                      beyond the previous bar's extreme in the trade direction.
                      A weak bar is rejected (plan restored) — the chain stays
                      alive and a later strong close may still confirm.
                      Custom body ratio: MIN_CONFIRM_BAR=0.4.

In-engine replay round 3 (arm `prodfilters` = HTF_TREND_GATE=4h +
MIN_STOP_FLOOR=1): 585 trades, WR 76%, +0.028 R (IS +0.017 / OOS +0.051),
maxDD 13.6 R vs base 848 trades −0.024 R, maxDD 40.1 R.

All are opt-in so the live behaviour does not change until Viva decides.
"""
from __future__ import annotations

import os
from typing import Dict, Optional

DEFAULT_STOP_FLOOR_PCT: Dict[str, float] = {
    "15m": 1.2, "30m": 1.4, "1h": 1.6, "4h": 2.5, "1d": 4.0,
}


def trend_gate_tf() -> str:
    return str(os.getenv("HTF_TREND_GATE", "") or "").strip().lower()


def htf_trend_aligned(bundle, direction: str, tf: str = "4h", span: int = 50) -> Optional[bool]:
    """True/False = aligned/against; None = not enough data (never blocks)."""
    try:
        df = bundle.get(tf)
        if df is None or len(df) < span + 5:
            return None
        close = df["close"].astype(float)
        ema = close.ewm(span=span, adjust=False).mean()
        up = float(close.iloc[-1]) > float(ema.iloc[-1])
        return up if str(direction).upper() == "LONG" else (not up)
    except Exception:
        return None


def apply_trend_gate(bundle, candidates) -> None:
    tf = trend_gate_tf()
    if not tf:
        return
    for c in candidates:
        ok = htf_trend_aligned(bundle, c.direction, tf)
        if ok is None:
            continue
        gates = dict(c.mandatory_gates or {})
        gates[f"htf_trend_{tf}"] = bool(ok)
        c.mandatory_gates = gates
        if not ok:
            try:
                c.warnings = list(c.warnings or []) + [
                    f"جهت سناریو خلاف روند {tf} (کلوز نسبت به EMA50) است؛ طبق فیلتر replay فقط آموزشی."]
            except Exception:
                pass


def stop_floor_map() -> Dict[str, float]:
    raw = str(os.getenv("MIN_STOP_FLOOR", "") or "").strip()
    if not raw or raw.lower() in ("0", "false", "off", "no"):
        return {}
    if raw.lower() in ("1", "true", "on", "yes", "default"):
        return dict(DEFAULT_STOP_FLOOR_PCT)
    out: Dict[str, float] = {}
    for part in raw.split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            try:
                out[k.strip().lower()] = float(v)
            except ValueError:
                continue
    return out


def stop_floor_violation(candidate) -> Optional[str]:
    """Persian reason when the confirmed stop is tighter than the TF floor."""
    floors = stop_floor_map()
    if not floors:
        return None
    tf = str(getattr(candidate, "trigger_timeframe", "") or "").lower()
    floor = floors.get(tf)
    try:
        entry = float(candidate.planned_entry or 0.0)
        risk_pct = abs(entry - float(candidate.sl)) / entry * 100.0 if entry > 0 else 0.0
    except Exception:
        return None
    if not floor or risk_pct <= 0 or risk_pct >= floor:
        return None
    return (f"فاصلهٔ استاپ {risk_pct:.2f}% کمتر از کفِ {floor:.2f}% تایم {tf} است؛ "
            "استاپ‌های تنگ در replay بیشترین شکار را داشتند — تأیید صادر نشد.")


def confirm_bar_min_body() -> float:
    raw = str(os.getenv("MIN_CONFIRM_BAR", "") or "").strip().lower()
    if not raw or raw in ("0", "false", "off", "no"):
        return 0.0
    if raw in ("1", "true", "on", "yes", "default"):
        return 0.3
    try:
        v = float(raw)
        return v if 0.0 < v < 5.0 else 0.0
    except ValueError:
        return 0.0


def weak_confirm_bar(candidate, closed_df) -> Optional[str]:
    """Persian reason when the confirmation bar (closed_df's last row) is weak."""
    k = confirm_bar_min_body()
    if k <= 0:
        return None
    try:
        if closed_df is None or len(closed_df) < 3:
            return None
        last, prev = closed_df.iloc[-1], closed_df.iloc[-2]
        rng = float((closed_df["high"].astype(float) - closed_df["low"].astype(float)).tail(14).mean())
        if rng <= 0:
            return None
        body = abs(float(last["close"]) - float(last["open"])) / rng
        if str(getattr(candidate, "direction", "")).upper() == "LONG":
            beyond = float(last["close"]) > float(prev["high"])
        else:
            beyond = float(last["close"]) < float(prev["low"])
    except Exception:
        return None
    if body >= k and beyond:
        return None
    why = []
    if body < k:
        why.append(f"بدنه {body:.2f}× میانگین دامنه (< {k:.2f})")
    if not beyond:
        why.append("کلوز فراتر از سقف/کف کندل قبل نیست")
    return "کندل تأیید ضعیف است: " + " و ".join(why) + " — منتظر کلوز قوی‌تر می‌مانیم."
