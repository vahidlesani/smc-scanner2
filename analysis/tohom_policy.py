"""R99q31i — PER-SETUP CONFIRMATION POLICY (his 10-20, verbatim).

«نواحی رو به پین‌وال بسپری و بقیه طبق قوانین خودشون تایید انجام بدن»

The smart engine had ONE shape of proof for every family: «a lower-TF close
beyond the break edge, plus volume and a candle pattern». That is correct for
a LINE engine and wrong for a ZONE engine — a zone is not broken, it is
REACTED to. Demanding a break on a zone lane either confirms late (after price
has already left the band) or never.

So the ownership is now explicit:

  * **Zone lanes** (PINVAL, PINWALL, PINWALLQ, ZONE, RANGE) confirm through
    PINVAL's own anatomy — price on the band, a rejection candle in the
    scenario's direction, volume support. No break required.
  * **Every other setup confirms by ITS OWN rule** — the line-break proof for
    TLBREAK, the pattern-edge proof for TECHCLASSIC, the base break for
    ALBROX, the spot rule for SPOTBREAK — all of them still judged by
    `analysis.tohom.evaluate_tohom_confirmation`, whose edge is exactly the
    geometry that setup drew.

Fail-closed, fail-open on error: an unknown code keeps the old behaviour.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

# the code → who judges it
_POLICY: Dict[str, str] = {
    # zone lanes: delegated to PINVAL's pin anatomy
    "PINVAL": "PINVAL_PIN",
    "PINWALL": "PINVAL_PIN",
    "PINWALLQ": "PINVAL_PIN",
    "ZONE": "PINVAL_PIN",
    "RANGE": "PINVAL_PIN",
    # line / pattern lanes: their own edge is the judge
    "TLBREAK": "LINE_BREAK",
    "TECHCLASSIC": "PATTERN_BREAK",
    "ALBROX": "BASE_BREAK",
    "SPOTBREAK": "SPOT_BREAK",
    "P1234": "P1234_LEG",
    "LSR": "LEVEL_REJECTION",
    "SDR": "LEVEL_REJECTION",
}

ZONE_POLICY = "PINVAL_PIN"


def policy_for(setup_code: str) -> str:
    """The confirmation law a setup is judged by (default: its own edge)."""
    return _POLICY.get(str(setup_code or "").upper(), "LINE_BREAK")


def delegates_to_pinval(setup_code: str) -> bool:
    """True for the zone lanes — his «نواحی رو به پین‌وال بسپری»."""
    return policy_for(setup_code) == ZONE_POLICY


def _dir_sign(direction) -> int:
    d = str(direction or "").upper()
    return 1 if d in ("LONG", "BULL", "BULLISH", "BUY") else -1


def _closed_since(df: Optional[pd.DataFrame], after: Optional[pd.Timestamp],
                  now: Optional[pd.Timestamp]) -> pd.DataFrame:
    if df is None or "timestamp" not in df.columns:
        return pd.DataFrame()
    frame = df.copy()
    ts = pd.to_datetime(frame["timestamp"])
    if getattr(ts.dtype, "tz", None) is not None:
        ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    frame["timestamp"] = ts
    if now is not None:
        n = pd.Timestamp(now)
        n = n.tz_convert("UTC").tz_localize(None) if n.tzinfo is not None else n
        frame = frame[frame["timestamp"] <= n]
    if after is not None:
        a = pd.Timestamp(after)
        a = a.tz_convert("UTC").tz_localize(None) if a.tzinfo is not None else a
        frame = frame[frame["timestamp"] >= a]
    return frame.reset_index(drop=True)


def evaluate_zone_confirmation(candidate, lower_closed_df: Optional[pd.DataFrame],
                               now: Optional[pd.Timestamp] = None
                               ) -> Tuple[bool, str, Dict]:
    """PINVAL's anatomy judges a ZONE lane: touch, rejection, volume.

    A zone is reacted to, never «broken». The band is the candidate's own PD
    array (the POI every zone candidate already carries); the proof is that
    price traded inside it and closed back out our way on a rejection candle.
    """
    md = candidate.metadata if isinstance(getattr(candidate, "metadata", None), dict) else {}
    info: Dict = {"policy": ZONE_POLICY, "why": ""}
    try:
        lo = float(getattr(candidate, "entry_zone_bottom", 0) or 0)
        hi = float(getattr(candidate, "entry_zone_top", 0) or 0)
        if not (hi > lo > 0):
            info["why"] = "ناحیهٔ ورود روی این کاندید تعریف نشده است."
            return False, info["why"], info
        d = _dir_sign(getattr(candidate, "direction", ""))
        start = None
        try:
            ca = getattr(candidate, "created_at", None)
            if ca:
                start = pd.Timestamp(str(ca))
        except Exception:
            start = None
        subs = _closed_since(lower_closed_df, start, now)
        if len(subs) < 2:
            info["why"] = "هنوز کندلِ بسته‌شدهٔ کافی روی تایم پایین‌تر نداریم."
            return False, info["why"], info
        # 1) price must actually reach the band (a reaction needs a touch)
        touched = ((subs["low"].astype(float) <= hi) & (subs["high"].astype(float) >= lo))
        if not bool(touched.any()):
            info["why"] = "قیمت هنوز به ناحیه نرسیده است."
            return False, info["why"], info
        last = subs.iloc[-1]
        prev = subs.iloc[-2] if len(subs) >= 2 else last
        # 2) the LAST closed sub-candle must come back out toward the scenario
        lc = float(last["close"])
        if d > 0 and lc < lo:
            info["why"] = "کلوزِ آخر هنوز زیرِ ناحیه ماند؛ بازگشت تأیید نشد."
            return False, info["why"], info
        if d < 0 and lc > hi:
            info["why"] = "کلوزِ آخر هنوز بالای ناحیه ماند؛ بازگشت تأیید نشد."
            return False, info["why"], info
        # 3) PINVAL's anatomy: a rejection or an engulfing at the band
        from analysis.tohom import _engulfing, _pin_like, _power_candle
        anatomy = ""
        if _pin_like(last, d):
            anatomy = "پین‌بار"
        elif _engulfing(prev, last, d):
            anatomy = "انگلفینگ"
        elif _power_candle(last, d):
            anatomy = "کندلِ قدرتی"
        if not anatomy:
            info["why"] = "پین‌بار/انگلفینگِ هم‌جهت روی ناحیه دیده نشد."
            return False, info["why"], info
        # 4) volume must speak too — a silent zone is not a reaction
        base = 0.0
        try:
            hist = pd.to_numeric(subs["volume"], errors="coerce").tail(21)[:-1]
            base = float(hist.mean()) if len(hist) else 0.0
        except Exception:
            base = 0.0
        vol_ratio = (float(last["volume"]) / base) if base > 0 else 0.0
        if base > 0 and vol_ratio < 1.3:
            info["why"] = "رشد حجم روی ناحیه دیده نشد."
            return False, info["why"], info
        info.update({"why": "", "pattern": anatomy, "vol_ratio": round(vol_ratio, 2),
                     "zone": [lo, hi]})
        reason = (f"⚡ تأیید زودهنگام ناحیه (به قاضیِ پین‌وال): قیمت به ناحیهٔ "
                  f"{lo:g}–{hi:g} رسید و {anatomy} در جهت سناریو با حجم "
                  f"{vol_ratio:.1f}× بسته شد — بدون نیاز به کلوزِ کندلِ بالاتر.")
        md["tohom_policy"] = ZONE_POLICY
        md["tohom_pattern"] = anatomy
        md["tohom_vol_ratio"] = round(vol_ratio, 2)
        md["tohom_note_fa"] = reason
        md["technical_confirmation_complete"] = True
        try:
            candidate.status = "CONFIRMED"
            from analysis.models import iso_now
            if not getattr(candidate, "confirmed_at", None):
                candidate.confirmed_at = iso_now()
        except Exception:
            pass
        return True, reason, info
    except Exception as exc:
        info["why"] = f"خطای موتور ناحیه: {exc}"
        return False, info["why"], info


def confirm_by_policy(candidate, lower_closed_df: Optional[pd.DataFrame],
                      **kw) -> Tuple[bool, object, str]:
    """Route a candidate to the law that owns it.

    Zone lanes → PINVAL's anatomy (this module). Everything else → the existing
    edge-based engine, which already judges each family by the geometry it drew.
    """
    code = str(getattr(candidate, "setup_code", "") or "")
    if delegates_to_pinval(code):
        ok, reason, _info = evaluate_zone_confirmation(
            candidate, lower_closed_df, kw.get("now"))
        if ok:
            return True, candidate, reason
        # the zone judge said no — the generic engine may still see a clean
        # break of that lane's own edge; never confirm twice, never block it.
    from analysis.tohom import evaluate_tohom_confirmation as _gen
    return _gen(candidate, lower_closed_df, **kw)
