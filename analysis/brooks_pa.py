"""R63 ENTRY-SIDE ENGINE — Al Brooks price-action rules, coded precisely.

Viva 10-01: «موتور سمت ورود هم باید خیلی حرفه‌ای باشه — از کدوم سمت وارد
الگو شده، ادامه‌دهنده یا برگشتی — پرایس اکشن ال بروکس: خواندن کندل، واکنش‌ها،
بریک‌اوت‌ها که فالوترو میخوان.»

Sources (rules paraphrased, thresholds scale-free in ATR / bar anatomy):

* Al Brooks, *Trading Price Action — Trends / Trading Ranges / Reversals*:
  - A **strong breakout bar** is a trend bar in the breakout direction: a big
    body (≥ ½ of its range), closing near its extreme (in the outer third),
    bigger than the recent average bar, with small tails. «Most breakouts
    fail» when the breakout bar is weak (doji / big tail against it).
  - A breakout needs **follow-through**: the next bar(s) must not reverse it —
    no close back inside the pattern; a follow-through bar closing beyond the
    breakout bar's close makes the breakout «successful».
  - A **climactic** breakout (a bar far bigger than recent bars, late in an
    extended move) is more often an exhaustion — do not chase it.
  - **Reversal** patterns need something to reverse: a prior trend into the
    pattern (and a test of the extreme — the second top/bottom = the MTR /
    double top-bottom test). A **continuation** pattern is entered WITH the
    prior trend and breaks out in its direction.
* Edwards & Magee, *Technical Analysis of Stock Trends*: reversal formations
  require a prior trend; confirmation is a decisive close through the
  neckline (penetration filter), throwbacks/pullbacks to the neckline are
  common and allowed.
* Bulkowski, *Encyclopedia of Chart Patterns*: tops within a small tolerance,
  the confirmation = close beyond the valley/neckline, measured target =
  pattern height projected from the neckline; price beyond the tops before
  the breakout invalidates the pattern.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd


def _f(x, d=0.0) -> float:
    try:
        v = float(x)
        return v if v == v else d
    except Exception:
        return d


def atr(df: pd.DataFrame, n: int = 14) -> float:
    try:
        return _f((df["high"].astype(float) - df["low"].astype(float)).tail(n).mean())
    except Exception:
        return 0.0


def bar_anatomy(o: float, h: float, l: float, c: float) -> Dict[str, float]:
    rng = max(h - l, 1e-12)
    body = abs(c - o)
    return {"range": rng, "body": body, "body_ratio": body / rng,
            "close_pos": (c - l) / rng,            # 1.0 = closed on its high
            "upper_tail": (h - max(o, c)) / rng, "lower_tail": (min(o, c) - l) / rng}


def breakout_bar_quality(df: pd.DataFrame, idx: int, direction: str,
                         level: float) -> Dict[str, Any]:
    """Brooks breakout-bar grade of bar ``idx`` crossing ``level``.

    grade: STRONG (trend bar, closes in the outer third, bigger than the recent
    average) · OK (closes beyond with a decent body) · WEAK (doji / closes in
    the wrong half / tail against — a likely failed breakout) · CLIMAX
    (≥ 3× the recent average range — exhaustion, do not chase)."""
    out = {"grade": "WEAK", "ok": False, "notes": []}
    try:
        n = len(df)
        if idx < 0:
            idx = n + idx
        if not (0 <= idx < n):
            return out
        o, h, l, c = (float(df[k].iloc[idx]) for k in ("open", "high", "low", "close"))
        a = bar_anatomy(o, h, l, c)
        prior = df.iloc[max(0, idx - 10):idx]
        avg_rng = _f((prior["high"] - prior["low"]).mean(), a["range"]) if len(prior) else a["range"]
        avg_body = _f((prior["close"] - prior["open"]).abs().mean(), a["body"]) if len(prior) else a["body"]
        long_ = str(direction).upper() == "LONG"
        beyond = (c > level) if long_ else (c < level)
        with_dir = (c > o) if long_ else (c < o)
        outer = a["close_pos"] >= 0.667 if long_ else a["close_pos"] <= 0.333
        wrong_half = a["close_pos"] < 0.5 if long_ else a["close_pos"] > 0.5
        tail_against = a["upper_tail"] if long_ else a["lower_tail"]
        out.update({"body_ratio": round(a["body_ratio"], 3), "close_pos": round(a["close_pos"], 3),
                    "range_x_avg": round(a["range"] / max(avg_rng, 1e-12), 2)})
        if not beyond:
            out["notes"].append("close did not cross the level")
            return out
        # Brooks: a huge bar is a CLIMAX only LATE in a move (the preceding
        # bars already ran in the breakout direction); the same bar leaving a
        # tight range is the strongest kind of breakout.
        _run = 0.0
        if len(prior) >= 3:
            _run = (float(prior["close"].iloc[-1]) - float(prior["open"].iloc[0]))
            _run = _run if long_ else -_run
        if avg_rng > 0 and a["range"] >= 3.0 * avg_rng and a["body"] >= 2.5 * max(avg_body, 1e-12) \
                and _run >= 2.5 * avg_rng:
            out.update(grade="CLIMAX", ok=False)
            out["notes"].append("climactic breakout bar (≥3× average) — exhaustion risk, Brooks: don't chase")
            return out
        if a["body_ratio"] < 0.30 or wrong_half or not with_dir or tail_against >= 0.45:
            out.update(grade="WEAK", ok=False)
            out["notes"].append("weak breakout bar (doji / tail against / closed in the wrong half)")
            return out
        if a["body_ratio"] >= 0.50 and outer and a["body"] >= 0.8 * max(avg_body, 1e-12):
            out.update(grade="STRONG", ok=True)
            out["notes"].append("strong breakout trend bar (big body, outer-third close)")
            return out
        out.update(grade="OK", ok=True)
        out["notes"].append("acceptable breakout bar")
        return out
    except Exception:
        return out


def follow_through(df: pd.DataFrame, break_idx: int, direction: str,
                   level: float, tol: float = 0.0) -> Dict[str, Any]:
    """Brooks follow-through after a breakout bar at ``break_idx``.

    status: PENDING (no bar yet) · CONFIRMED (a later close beyond the
    breakout bar's close, no close back inside) · HOLDING (still beyond the
    level, no extension yet) · FAILED (a close back inside the pattern)."""
    try:
        n = len(df)
        if break_idx < 0:
            break_idx = n + break_idx
        after = df.iloc[break_idx + 1:]
        if not len(after):
            return {"status": "PENDING", "ok": True}
        long_ = str(direction).upper() == "LONG"
        bc = float(df["close"].iloc[break_idx])
        closes = after["close"].astype(float)
        if long_:
            if (closes < level - tol).any():
                return {"status": "FAILED", "ok": False}
            return {"status": "CONFIRMED" if (closes > bc).any() else "HOLDING", "ok": True}
        if (closes > level + tol).any():
            return {"status": "FAILED", "ok": False}
        return {"status": "CONFIRMED" if (closes < bc).any() else "HOLDING", "ok": True}
    except Exception:
        return {"status": "PENDING", "ok": True}


def first_cross_index(df: pd.DataFrame, level: float, direction: str,
                      lookback: int = 6) -> Optional[int]:
    """Index of the FIRST close beyond ``level`` inside the last ``lookback``
    bars that follows a close on the other side (None = no fresh cross)."""
    try:
        c = df["close"].astype(float).to_numpy()
        n = len(c)
        long_ = str(direction).upper() == "LONG"
        lo = max(1, n - int(lookback))
        for i in range(lo, n):
            beyond = c[i] > level if long_ else c[i] < level
            prev_in = c[i - 1] <= level if long_ else c[i - 1] >= level
            if beyond and prev_in:
                return i
        return None
    except Exception:
        return None


def entry_side(df: pd.DataFrame, first_idx: int, level: float, height: float,
               lookback: int = 25) -> Dict[str, Any]:
    """Which side price ENTERED the pattern from (the move into its first
    pivot). ``from``=BELOW means price rose into the pattern; ABOVE = fell
    into it. ``prior_move`` is the size of that approach in pattern heights."""
    try:
        i0 = max(0, int(first_idx) - int(lookback))
        seg = df.iloc[i0:max(i0 + 1, int(first_idx) + 1)]
        # the DIRECTION of the approach leg decides the side: a leg rising
        # into the first pivot entered from BELOW (a top can reverse it); a
        # falling leg entered from ABOVE (a bottom can reverse it).
        start = float(seg["close"].iloc[0])
        end = float(seg["close"].iloc[-1])
        net = end - start
        side = "BELOW" if net > 0 else "ABOVE"
        return {"from": side, "prior_move": round(abs(net) / max(height, 1e-12), 2)}
    except Exception:
        return {"from": "", "prior_move": 0.0}


# pivot-pattern doctrine: (trade direction, role, required entry side)
PIVOT_DOCTRINE = {
    "DOUBLE_TOP": ("SHORT", "REVERSAL", "BELOW"),
    "HEAD_SHOULDERS": ("SHORT", "REVERSAL", "BELOW"),
    "DOUBLE_BOTTOM": ("LONG", "REVERSAL", "ABOVE"),
    "INV_HEAD_SHOULDERS": ("LONG", "REVERSAL", "ABOVE"),
    "CUP_HANDLE": ("LONG", "CONTINUATION", "BELOW"),
}
