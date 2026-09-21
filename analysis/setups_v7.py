"""High-selectivity SMC/ICT setup detectors for Viva Signal Bot v7.

A detector creates a candidate only after objective structural evidence exists.
The candidate still needs a first retest and LTF candle confirmation before it
can become a trade. Candlestick patterns and RSI divergence are confirmations,
never standalone signals.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from analysis.indicators import (
    atr,
    candle_displacement,
    detect_rsi_divergence,
    pivots,
    premium_discount,
    rsi,
    session_name,
    structure_bias,
)
from analysis.models import EvidenceItem, SignalCandidate, generate_viva_signal_id, generate_viva_public_code, utc_now
from config import get_settings
from data.fetcher import MarketBundle

SETTINGS = get_settings()

SETUP_NAMES = {
    "LSR": "Liquidity Sweep + MSS + POI Retest",
    "BOS1": "BOS Continuation + First Pullback",
    "TLR": "Trendline Break + First Retest",
    "SDR": "Supply/Demand Break + First Retest",
    "IFVG": "Breaker / Inverse FVG Retest",
}
SETUP_NAMES_FA = {
    "LSR": "جمع‌آوری نقدینگی، تغییر ساختار و بازگشت به ناحیه",
    "BOS1": "شکست ساختار و اولین پولبک",
    "TLR": "شکست خط روند و اولین پولبک",
    "SDR": "شکست ناحیه عرضه/تقاضا و اولین پولبک",
    "IFVG": "بریکر بلاک / معکوس FVG",
}

# Viva's confirmation grid: zone detection stays on the trigger TF
# (5m scalp / 15m swing), but entry CONFIRMATION listens on the finer TF
# below it so a valid retest is confirmed within ~1-3 minutes, not after a
# full 5m/15m candle close. SCALP: confirm on 1m; SWING: confirm on 5m.
CONFIRM_TF = {
    # Viva 09-17: تأیید از تایم مانیتورِ پایین‌تر گرفته می‌شود، نه از خود تریگر
    "SCALP": "3m",
    "DAYTRADE": "3m",
    "SWING": "3m",
    "GRAND": "1h",
}

# Viva's confirmation grid (2026-08): the finer TF that confirms a scenario
# depends on the TRIGGER timeframe, not the trade style:
#   5m trigger  -> 1m confirm (scalp reacts within ~60s)
#   15m trigger -> 5m confirm
#   1h trigger  -> 5m confirm
CONFIRM_TF_BY_TRIGGER = {
    # Viva 09-19/20 restated ladder (verbatim): each TF confirms ONE step
    # below itself — 15m from 3m (Ourbit HAS 3m), 1h from 15m, 4h from 1h,
    # 1D from 4H. Finer-than-that closes are noise, not evidence.
    "15m": "5m",   # Viva 09-19/20: «تایم ۵ دقیقه رو نیاز داریم» — signs live on 5m
    "1h": "15m",
    "4h": "1h",
    "1d": "4h",
}

# late bound: if the monitor TF missed, the scan/structure candle still confirms
CONFIRM_LATE_BY_TRIGGER = {
    # Last resort ONLY: if the one-step-below candle never printed the valid
    # close, the pattern TF's OWN closed candle confirms (never stalls).
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


def confirm_late_tf(trigger_tf: str):
    return CONFIRM_LATE_BY_TRIGGER.get(str(trigger_tf or "").lower())

# Viva 2026-09-11 confirmation ladder (his explicit rule): a scenario is
# confirmed by ONE closed candle of the timeframe ONE STEP BELOW the PATTERN
# timeframe — never a chain of closes, never the pattern TF's own candle:
#   1D → 4H close   4H → 1H close   1H → 15m close   15m → 5m close
# If that single close is weak, Viva filters the trade himself — the scanner
# must not burn the zone waiting for ceremony.
CONFIRM_TF_BY_PATTERN = {"1d": "4h", "4h": "1h", "1h": "15m", "15m": "5m"}


def confirm_timeframe_for_pattern(pattern_tf: str, style: str, trigger_tf: str) -> str:
    tf = str(pattern_tf or "").strip().lower()
    if tf in CONFIRM_TF_BY_PATTERN:
        return CONFIRM_TF_BY_PATTERN[tf]
    return confirm_timeframe(style, trigger_tf)


def confirm_timeframe(style: str, fallback: str) -> str:
    """Trigger-TF-driven confirmation grid (see CONFIRM_TF_BY_TRIGGER)."""
    tf = str(fallback or "").lower()
    if tf in CONFIRM_TF_BY_TRIGGER:
        return CONFIRM_TF_BY_TRIGGER[tf]
    return CONFIRM_TF.get(style.upper(), fallback)


# A trade style must not decide both the zone and entry timeframe implicitly.
# These are the actual research tiers:
# SCALP:    1h context → 15m structure → 5m zone → 1m confirmation
# DAYTRADE: 4h context → 1h structure  → 15m zone → 5m confirmation
# SWING:    1d context → 4h structure  → 1h zone  → 5m confirmation
TIMEFRAME_PROFILES = {
    # Viva 2026-09-13 ladder (his words, all four streams live):
    #   1D = سویینگ بلندمدت (structure 1D, confirmed by a closed 4H),
    #   4H = سویینگ میان‌مدت (higher structure 1D, confirmed by a closed 1H),
    #   1H = سویینگ میان‌مدت (context 4H, confirmed by a closed 15m),
    #   15m = کوتاه‌مدت (context 1H, confirmed by a closed 5m).
    # The alert/licence timeframe is the TRIGGER entry = the pattern TF the
    # alert names, so «۳ مجوز روی هر تایم تریگر» counts exactly what a human
    # reads on the message.
    # Viva 09-16 night-2 four-TF world: 15m short swing, 1h+4h mid swing,
    # 1d long swing.  SCALP/5m retired; SWING carries BOTH mid triggers via
    # PROFILE_OVERRIDE (see timeframe_profile).
    "GRAND": ("1d", "4h", "1d"),
    "SWING": ("1d", "4h", "1h"),
    "DAYTRADE": ("4h", "1h", "15m"),
    "SCALP": ("15m", "1h", "15m"),  # dormant stream, not in live_styles
}

# SwingEngine sets this while scanning its second (4h) trigger stream.
PROFILE_OVERRIDE: Dict[str, tuple] = {}


# Viva 09-17 (his base-forming argument): a 1d/4h base can take 6-10 candles —
# the watch window must outlive the SLOWEST reasonable base on that TF, else
# the chain expires before its confirmation ever arrives (why 1d never spoke).
# Global doctrine: confirmation is event-based (zone invalidated = dead),
# never a candle count; expiry is hygiene only, so it stays generous.
EXPIRY_HOURS_BY_TRIGGER = {"15m": 36, "1h": 96, "4h": 240, "1d": 360}


def expiry_hours_for(style: str, trigger_tf: str = "") -> int:
    """Watch window of an unconfirmed scenario — by TRIGGER timeframe first
    (a SWING 4h chain and a SWING 1h chain are different animals), style as
    the legacy fallback."""
    tf = str(trigger_tf or "").lower()
    if tf in EXPIRY_HOURS_BY_TRIGGER:
        return EXPIRY_HOURS_BY_TRIGGER[tf]
    st = str(style or "").upper()
    if st == "GRAND":
        return int(getattr(SETTINGS, "candidate_expiry_hours_grand", 96) or 96)
    if st == "SWING":
        return int(SETTINGS.candidate_expiry_hours_swing)
    if st == "DAYTRADE":
        return int(getattr(SETTINGS, "candidate_expiry_hours_daytrade", 24) or 24)
    return int(SETTINGS.candidate_expiry_hours_scalp)


def timeframe_profile(style: str):
    key = str(style).upper()
    if key in PROFILE_OVERRIDE:
        return PROFILE_OVERRIDE[key]
    return TIMEFRAME_PROFILES.get(key, TIMEFRAME_PROFILES["DAYTRADE"])


# ──────────────────────────────────────────────────────────────────────────
# Multi-timeframe narrative enrichment (Viva v7.6 spec)
#
# Every alert/signal must (a) state WHY it exists, (b) describe the higher-TF
# context timeframe-by-timeframe, and (c) name the zones price is near
# (flip zones / FVG / OB / swing highs-lows). We compute that ONCE at scan
# time and cache it in `metadata` so message builders stay pure and cheap.
# ──────────────────────────────────────────────────────────────────────────

_MTF_ORDER = ["1d", "4h", "1h", "15m", "5m"]
_TF_FA = {"1d": "روزانه", "4h": "۴ساعته", "1h": "۱ساعته", "15m": "۱۵دقیقه", "5m": "۵دقیقه", "1m": "۱دقیقه"}
_BIAS_FA = {"BULLISH": "صعودی 🟢", "BEARISH": "نزولی 🔴", "NEUTRAL": "خنثی ⚪"}


def _tf_bias_fa(df) -> str:
    if df is None or len(df) < 30:
        return "دیتای کافی نیست"
    try:
        bias = structure_bias(df, 3).get("bias", "NEUTRAL")
    except Exception:
        bias = "NEUTRAL"
    return _BIAS_FA.get(bias, "خنثی ⚪")


def _nearest_levels(df, price: float, atr_value: float, max_each: int = 2) -> Dict[str, List[float]]:
    """Closest pivot highs above and lows below current price (S/R shelf)."""
    if df is None or len(df) < 30 or atr_value <= 0:
        return {"above": [], "below": []}
    ph, pl = pivots(df, 3, 3)
    above = sorted({float(p["price"]) for p in ph if float(p["price"]) > price})[:max_each]
    below = sorted({float(p["price"]) for p in pl if float(p["price"]) < price}, reverse=True)[:max_each]
    return {"above": above, "below": below}


def enrich_candidate_context(bundle: MarketBundle, candidate: SignalCandidate) -> None:
    """Attach Viva's narrative blocks to `candidate.metadata`:
    - mtf_fa:    per-timeframe structure read (+ RSI value, divergence tags)
    - zones_fa:  nearest important zones with distance in ATR
    - div_fa:    RSI divergence note when present on the trigger TF
    Never raises; enrichment is best-effort cosmetics over the real setup.
    """
    md = candidate.metadata if isinstance(candidate.metadata, dict) else {}
    mtf_lines: List[str] = []
    mtf_struct: Dict[str, Dict] = {}
    zone_lines: List[str] = []
    nearest_zones: List[Dict] = []
    try:
        trigger_tf = candidate.trigger_timeframe
        last_row = bundle.get(trigger_tf)
        last_price = float(last_row["close"].iloc[-1]) if last_row is not None and len(last_row) else 0.0
        atr_now = candidate.metadata.get("atr")
        if last_row is not None and len(last_row) >= 20:
            _atr = atr(last_row)
            if pd.notna(_atr.iloc[-1]):
                atr_now = float(_atr.iloc[-1])
        atr_now = float(atr_now or 0)

        for tf in _MTF_ORDER:
            df = bundle.get(tf)
            if df is None or len(df) < 30:
                continue
            try:
                bias_tf = structure_bias(df, 3).get("bias", "NEUTRAL")
            except Exception:
                bias_tf = "NEUTRAL"
            rsi_now = None
            try:
                _r = rsi(df).iloc[-1]
                rsi_now = float(_r) if pd.notna(_r) else None
            except Exception:
                pass
            mtf_struct[tf] = {"bias": bias_tf, "rsi": rsi_now}
            line = f"• تایم {_TF_FA.get(tf, tf)}: ساختار {_BIAS_FA.get(bias_tf, 'خنثی ⚪')}"
            if rsi_now is not None:
                tag = ""
                if rsi_now >= 70:
                    tag = " (اوربایت ⚠️)"
                elif rsi_now <= 30:
                    tag = " (اورسلد ⚠️)"
                line += f" • RSI≈{rsi_now:.0f}{tag}"
            if tf == trigger_tf:
                div = detect_rsi_divergence(df, candidate.direction)
                if div:
                    kind = {
                        "REGULAR_BULLISH": "واگرایی معمولی مثبت",
                        "REGULAR_BEARISH": "واگرایی معمولی منفی",
                        "HIDDEN_BULLISH": "واگرایی مخفی مثبت",
                        "HIDDEN_BEARISH": "واگرایی مخفی منفی",
                    }.get(div["type"], div["type"])
                    line += f" • {kind} RSI 🔄"
                    md["div_fa"] = f"{kind} RSI روی تایم تریگر دیده می‌شود."
            mtf_lines.append(line)

        # Zone proximity scan: context frames' shelves around current price.
        if last_price > 0 and atr_now > 0:
            for tf in ("4h", "1h", "15m"):
                df = bundle.get(tf)
                if df is None or len(df) < 30:
                    continue
                levels = _nearest_levels(df, last_price, atr_now)
                tf_fa = _TF_FA.get(tf, tf)
                for level in levels.get("above", []):
                    dist = (level - last_price) / atr_now
                    if dist <= 6:
                        zone_lines.append(
                            f"⬆️ مقاومت {tf_fa} در {_fmt(level)} — فاصله ≈{dist:.1f} ATR از قیمت فعلی"
                        )
                        nearest_zones.append({"tf": tf, "side": "above", "level": float(level), "dist_atr": round(float(dist), 2)})
                for level in levels.get("below", []):
                    dist = (last_price - level) / atr_now
                    if dist <= 6:
                        zone_lines.append(
                            f"⬇️ حمایت {tf_fa} در {_fmt(level)} — فاصله ≈{dist:.1f} ATR از قیمت فعلی"
                        )
                        nearest_zones.append({"tf": tf, "side": "below", "level": float(level), "dist_atr": round(float(dist), 2)})
            # the candidate's own POI is the most important zone — say its kind
            poi_type = str(md.get("poi_type") or "").upper()
            poi_fa = {
                "FVG": "فلگ‌لیمیت (FVG)",
                "OB": "اوردر بلاک",
                "IFVG": "FVG معکوس‌شده",
                "FLIP": "فلیپ‌زون",
            }.get(poi_type)
            if poi_fa:
                zone_lines.insert(
                    0,
                    f"🎯 ناحیه ورود: {poi_fa} بین {_fmt(candidate.entry_zone_bottom)} و {_fmt(candidate.entry_zone_top)}",
                )
    except Exception as exc:
        print(f"Context enrichment skipped for {candidate.signal_id}: {exc}")
        return
    if mtf_lines:
        md["mtf_fa"] = mtf_lines
    if mtf_struct:
        md["mtf_struct"] = mtf_struct
        # Viva 2026-09-13 «تأییدهای کمکی در همه پیام‌ها»: EMA-21/51/100/200
        # position, Fibo level of the current swing and RSI divergence —
        # computed once on the pattern (trigger) frame, rendered by every
        # lifecycle message (detailed, compact, update, final alert).
        try:
            # Viva 2026-09-14 «باید توضیح بده، نه لیستِ کلمه‌ای» — every aid is
            # a full sentence from the curated banks (15 Fibo / 15 EMA / 15 RSI
            # + a per-session note), state-aware: cross vs hold vs near pick
            # different families; the seed keeps phrasing stable WITHIN a candle
            # so updates never look like re-rolls.
            _aids: List[str] = []
            _pdf = bundle.get(candidate.trigger_timeframe)
            if _pdf is not None and len(_pdf) >= 40:
                import pandas as _pd
                from analysis.aids_bank import ema_note, fibo_note, rsi_note, session_note
                _cl = _pd.to_numeric(_pdf["close"])
                _live = float(_cl.iloc[-1])
                try:
                    _bts = str(_pdf["timestamp"].iloc[-1])[:16]
                except Exception:
                    _bts = str(len(_pdf))
                _tfname = str(candidate.trigger_timeframe or "")
                _sess = session_note(str(md.get("session") or ""))
                if _sess:
                    _aids.append(f"🕐 {_sess}")
                _ema = {n: _cl.ewm(span=n, adjust=False).mean() for n in (21, 51, 100, 200)}
                for n in (21, 51, 200):
                    _v = float(_ema[n].iloc[-1])
                    _pv = float(_cl.iloc[-4]) if len(_cl) >= 4 else _live
                    _ev = float(_ema[n].iloc[-4]) if len(_ema[n]) >= 4 else _v
                    _d = (_live - _v) / max(_v, 1e-12) * 100
                    if _live >= _v and _pv < _ev:
                        _m = "CROSS_UP"
                    elif _live <= _v and _pv > _ev:
                        _m = "CROSS_DOWN"
                    elif abs(_d) < 0.35:
                        _m = "NEAR"
                    else:
                        _m = "ABOVE" if _live >= _v else "BELOW"
                    _aids.append("📊 " + ema_note(n, _d, _m, candidate.symbol, _tfname, _bts,
                                                  direction=candidate.direction))
                _aids.append("📊 EMA تایم الگو → " + " • ".join(
                    ("بالای" if _live >= float(_ema[n].iloc[-1]) else "زیرِ") + f" {n}"
                    for n in (21, 51, 100, 200)))
                _win = _pdf.tail(48)
                _wh = float(_pd.to_numeric(_win["high"]).max())
                _wl = float(_pd.to_numeric(_win["low"]).min())
                if _wh > _wl > 0:
                    _rng = _wh - _wl
                    _rat = (_wh - _live) / _rng if str(candidate.direction).upper() == "LONG" \
                        else (_live - _wl) / _rng
                    _lvls = (0, 23.6, 38.2, 50.0, 61.8, 78.6, 88.6)
                    _lv = min(_lvls, key=lambda k: abs(k - _rat * 100.0))
                    _nx = _lvls[min(len(_lvls) - 1, _lvls.index(_lv) + 1)]
                    _dist = abs(_rat * 100.0 - _lv) / 100.0 * _rng / max(_live, 1e-12) * 100
                    _fm = "EXT" if _lv >= 88.6 else ("ON" if _dist < 0.35 else "RETEST")
                    _aids.append("🌀 " + fibo_note(_lv, _dist, _fm,
                                                   "بالا" if str(candidate.direction).upper() == "LONG" else "پایین",
                                                   _nx, candidate.symbol, _tfname, _bts))
                try:
                    _d1 = _cl.diff()
                    _up = _d1.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                    _dn = (-_d1.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
                    _rsi = 100 - 100 / (1 + _up / _dn.replace(0, 1e-12))
                    _rv = float(_rsi.iloc[-1])
                    _rp = float(_rsi.iloc[-2]) if len(_rsi) > 1 else _rv
                    _avg = float(_rsi.tail(10).mean())
                    _rm = ("OB" if _rv >= 70 else "OS" if _rv <= 30
                           else "CROSS_UP" if _rp < 50 <= _rv
                           else "CROSS_DOWN" if _rp > 50 >= _rv else "NEUTRAL")
                    _aids.append("📈 " + rsi_note(_rv, _avg, _rm, candidate.symbol, _tfname, _bts,
                                                  direction=candidate.direction))
                except Exception:
                    pass
                if md.get("div_fa"):
                    _aids.append(f"📈 {md['div_fa']}")
            if _aids:
                md["tech_aids"] = _aids[:6]
        except Exception:
            pass
    if zone_lines:
        md["zones_fa"] = zone_lines[:8]
    if nearest_zones:
        md["nearest_zones"] = sorted(nearest_zones, key=lambda z: z["dist_atr"])[:6]
    candidate.metadata = md


def _fmt(value: float) -> str:
    """Viva 09-17: max 2 decimals in messages; sub-1 -> 2 significant digits."""
    value = float(value)
    absolute = abs(value)
    if absolute >= 1000:
        return f"{value:,.2f}"
    if absolute >= 100:
        s = f"{value:.2f}"
    elif absolute >= 1:
        s = f"{value:.3f}"          # Viva 09-17: 1-99 -> 3 decimals
    elif value == 0:
        return "0"
    else:
        import math as _math        # sub-$1 -> 4 significant digits
        s = f"{value:.{max(1, 3 - _math.floor(_math.log10(absolute)))}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _direction(bias: str) -> str:
    return "LONG" if bias == "BULLISH" else "SHORT"


def _ensure_frames(bundle: MarketBundle, required: Sequence[str]) -> bool:
    return all(bundle.get(tf) is not None and len(bundle.get(tf)) >= 60 for tf in required)


def _find_sweep(df: pd.DataFrame, direction: str, recent_bars: int = 14) -> Optional[Dict]:
    ph, pl = pivots(df, 3, 3)
    atrs = atr(df)
    candidates = pl if direction == "LONG" else ph
    if not candidates:
        return None
    start = max(10, len(df) - recent_bars)
    for i in range(len(df) - 1, start - 1, -1):
        a = float(atrs.iloc[i]) if pd.notna(atrs.iloc[i]) else 0.0
        prior = [point for point in candidates if point["index"] <= i - 3]
        if not prior or a <= 0:
            continue
        # Most recent external pivot is operationally more relevant than a remote extreme.
        level_point = prior[-1]
        level = float(level_point["price"])
        row = df.iloc[i]
        if direction == "LONG":
            swept = row["low"] < level - 0.03 * a and row["close"] > level
            rejection = (row["close"] - row["low"]) / max(row["high"] - row["low"], 1e-12)
        else:
            swept = row["high"] > level + 0.03 * a and row["close"] < level
            rejection = (row["high"] - row["close"]) / max(row["high"] - row["low"], 1e-12)
        if swept and rejection >= 0.35:
            return {
                "index": i,
                "level": level,
                "extreme": float(row["low"] if direction == "LONG" else row["high"]),
                "timestamp": row["timestamp"],
                "rejection": float(rejection),
                "atr": a,
            }
    return None


def _find_structure_break_after(df: pd.DataFrame, direction: str, after_index: int) -> Optional[Dict]:
    ph, pl = pivots(df, 2, 2)
    opposing = ph if direction == "LONG" else pl
    reference = [point for point in opposing if point["index"] < after_index]
    if not reference:
        return None
    level_point = reference[-1]
    level = float(level_point["price"])
    for i in range(after_index + 1, len(df)):
        close = float(df["close"].iloc[i])
        broken = close > level if direction == "LONG" else close < level
        displacement = candle_displacement(df, i, atr_multiple=0.65)
        expected = "BULLISH" if direction == "LONG" else "BEARISH"
        if broken and displacement["direction"] == expected and displacement["valid"]:
            return {
                "index": i,
                "level": level,
                "timestamp": df["timestamp"].iloc[i],
                **displacement,
            }
    return None


def _find_recent_bos(df: pd.DataFrame, direction: str, recent_bars: int = 10) -> Optional[Dict]:
    ph, pl = pivots(df, 3, 3)
    points = ph if direction == "LONG" else pl
    if not points:
        return None
    for i in range(max(20, len(df) - recent_bars), len(df)):
        previous = [point for point in points if point["index"] <= i - 3]
        if not previous:
            continue
        level = float(previous[-1]["price"])
        close = float(df["close"].iloc[i])
        prev_close = float(df["close"].iloc[i - 1])
        crossed = (
            prev_close <= level < close if direction == "LONG"
            else prev_close >= level > close
        )
        displacement = candle_displacement(df, i, atr_multiple=0.8)
        expected = "BULLISH" if direction == "LONG" else "BEARISH"
        if crossed and displacement["valid"] and displacement["direction"] == expected:
            return {"index": i, "level": level, "timestamp": df["timestamp"].iloc[i], **displacement}
    return None


def _find_fvg_near(df: pd.DataFrame, direction: str, around_index: int) -> Optional[Dict]:
    start = max(1, around_index - 3)
    end = min(len(df) - 1, around_index + 3)
    for middle in range(end - 1, start - 1, -1):
        left = df.iloc[middle - 1]
        right = df.iloc[middle + 1]
        if direction == "LONG" and float(right["low"]) > float(left["high"]):
            bottom, top = float(left["high"]), float(right["low"])
        elif direction == "SHORT" and float(right["high"]) < float(left["low"]):
            bottom, top = float(right["high"]), float(left["low"])
        else:
            continue
        touches = 0
        for j in range(middle + 2, len(df)):
            if float(df["low"].iloc[j]) <= top and float(df["high"].iloc[j]) >= bottom:
                touches += 1
        return {"bottom": bottom, "top": top, "origin_index": middle, "touches": touches, "type": "FVG"}
    return None


def _find_order_block(df: pd.DataFrame, direction: str, impulse_index: int) -> Optional[Dict]:
    for i in range(impulse_index - 1, max(-1, impulse_index - 7), -1):
        row = df.iloc[i]
        opposite = row["close"] < row["open"] if direction == "LONG" else row["close"] > row["open"]
        if not opposite:
            continue
        if direction == "LONG":
            bottom, top = float(row["low"]), float(max(row["open"], row["close"]))
        else:
            bottom, top = float(min(row["open"], row["close"])), float(row["high"])
        touches = 0
        for j in range(impulse_index + 1, len(df)):
            if float(df["low"].iloc[j]) <= top and float(df["high"].iloc[j]) >= bottom:
                touches += 1
        return {"bottom": bottom, "top": top, "origin_index": i, "touches": touches, "type": "ORDER_BLOCK"}
    return None


def _select_poi(df: pd.DataFrame, direction: str, impulse_index: int) -> Optional[Dict]:
    fvg = _find_fvg_near(df, direction, impulse_index)
    ob = _find_order_block(df, direction, impulse_index)
    options = [poi for poi in (fvg, ob) if poi and poi["touches"] <= 1]
    if not options:
        return None
    # An untouched FVG gets priority; otherwise use the narrowest fresh POI.
    options.sort(key=lambda item: (item["touches"], item["top"] - item["bottom"]))
    chosen = dict(options[0])
    if fvg and ob and max(fvg["bottom"], ob["bottom"]) < min(fvg["top"], ob["top"]):
        chosen.update({
            "bottom": max(fvg["bottom"], ob["bottom"]),
            "top": min(fvg["top"], ob["top"]),
            "type": "OB + FVG CONFLUENCE",
            "touches": max(fvg["touches"], ob["touches"]),
        })
    return chosen


def _five_tick_gap(price: float, market: Optional[Dict] = None) -> float:
    """Five venue ticks beyond the valid base; uses a safe price-scale fallback
    when a venue has not provided its tick size."""
    market = market or {}
    try:
        tick = float(market.get("tick_size") or market.get("price_tick") or 0)
    except (TypeError, ValueError):
        tick = 0.0
    if tick <= 0:
        p = abs(float(price))
        tick = 0.1 if p >= 10_000 else (0.01 if p >= 10 else (0.0001 if p >= 1 else (0.00001 if p >= 0.1 else 0.000001)))
    return 5.0 * tick


def _liquidity_protected_invalidation(
    trigger_df: pd.DataFrame,
    poi: Dict,
    direction: str,
    atr_value: float,
    style: str,
    spread_pct: float = 0.0,
    market: Optional[Dict] = None,
) -> Dict:
    """Stop behind the LAST swing + buffer — NO ATR (Viva 09-20 round 11).

    Verbatim: «بدون atr / پشت آخرین سویینگ با بافر» → the anchor is the most
    recent opposite swing of the trigger TF (the last pivot high above entry
    for a SHORT, the last pivot low below entry for a LONG); when no such
    pivot exists the POI edge is used. The buffer is the standard price-based
    allowance (5 venue ticks or 0.10% of price, plus the spread) — the old ATR
    volatility floors and percentage floors are gone, so a 15m stop is no
    longer born 2–3% wide.
    """
    from analysis.trade_management import structural_buffer
    pivot_highs, pivot_lows = pivots(trigger_df, 3, 3)
    edge = float(poi["bottom"] if direction == "LONG" else poi["top"])
    points = (pivot_lows if direction == "LONG" else pivot_highs)[-20:]
    anchor = edge
    picked = 0
    if direction == "LONG":
        below = [(int(p.get("index", 0)), float(p["price"])) for p in points
                 if float(p["price"]) < edge]
        if below:
            # the MOST RECENT swing (largest index) — not the farthest one
            below.sort(key=lambda t: t[0])
            anchor = below[-1][1]
            picked = len(below)
    else:
        above = [(int(p.get("index", 0)), float(p["price"])) for p in points
                 if float(p["price"]) > edge]
        if above:
            above.sort(key=lambda t: t[0])
            anchor = above[-1][1]
            picked = len(above)
    base_gap = _five_tick_gap(anchor, market)
    buffer_value = structural_buffer(anchor, market)
    spread_buffer = abs(anchor) * max(0.0, float(spread_pct)) / 100 * 2.0
    buffer_value = max(buffer_value, spread_buffer, base_gap)
    invalidation = anchor - buffer_value if direction == "LONG" else anchor + buffer_value
    # ── Viva 09-21: «استاپ اصلا ساختاری اگر فاصله داشت حذف نشه و تا ۱.۲۵ قیمت
    # نماد محاسبه بشه» — the clamp itself runs where the ENTRY is known (the
    # builder + the scan funnel); here the anchor keeps its structural value.
    return {
        "price": float(invalidation),
        "liquidity_anchor": float(anchor),
        "buffer": float(buffer_value),
        "protected_pivots": int(picked),
        "base_gap": float(base_gap),
        "no_atr": True,
        "stop_clamped": False,
    }


def _structural_targets(
    df: pd.DataFrame, direction: str, entry: float, sl: float, *,
    extra_df: Optional[pd.DataFrame] = None, atr_value: float = 0.0,
    trigger_tf: str = "", require_real_levels: bool = False,
    min_gap_atr: float = 0.6,
) -> Optional[Dict]:
    """Target path per Viva 09-20 round 11 (verbatim).

    1. «اگر سطح معتبر در سقف یا کف وجود داشت همان فاصله به ۵ قسمت تقسیم» →
       a valid ceiling/floor (of the trigger TF, else the higher TF) sets the
       path; only the TF distance ceiling may clamp it.
    2. «اگر کف و سقف معتبر نبود … هم سقف و هم کف ۳ تا ۵ درصد بسته با موقعیت
       پوزیشن و سقف و کف قبلی» → otherwise the path is the distance to the
       PREVIOUS opposite extreme clamped into the TF band (3–5% for 15m/1h,
       5–7% for 4h, up to 10% for 1d); no previous extreme → the band middle.
    3. TP1 is always one fifth of that path and the ladder exits 40/30/30 at
       TP1..TP3 (60% of the path) — «۴۰ درصد در تی‌پی۱ و دو تا ۳۰ درصد تا ۲ و
       ۳ خالی بشه».
    NO ATR and NO stop distance anywhere in this arithmetic.
    """
    try:
        entry = float(entry)
        risk = abs(entry - float(sl))
        if entry <= 0:
            return None
        from analysis.trade_management import doctrine_path, band_for_tf
        band_lo, band_hi = band_for_tf(trigger_tf or "15m")
        floor_dist = entry * band_lo / 100.0
        cap_dist = entry * band_hi / 100.0
        # levels: trigger TF first, then the higher TF (important zones)
        levels: List[float] = []
        for _frame in (df, extra_df):
            if _frame is None or len(_frame) < 20:
                continue
            try:
                _ph, _pl = pivots(_frame, 3, 3)
            except Exception:
                continue
            for _pt in (_ph if direction == "LONG" else _pl):
                try:
                    _lv = float(_pt["price"])
                except Exception:
                    continue
                if levels and any(abs(_lv - _e) <= 0.0015 * entry for _e in levels):
                    continue
                levels.append(_lv)
        if direction == "LONG":
            valid = sorted(lv for lv in levels if lv > entry)
            extreme = max((lv for lv in levels if lv <= entry), default=0.0)  # previous low
        else:
            valid = sorted((lv for lv in levels if lv < entry), reverse=True)
            extreme = min((lv for lv in levels if lv >= entry), default=0.0)  # previous high
        # nearest level inside the band counts as «سطح معتبر»; beyond the band
        # the cap rules (round 9); closer than the floor is not a target.
        level = 0.0
        for _lv in valid:
            if abs(_lv - entry) >= max(floor_dist, 0.006 * entry):
                level = _lv
                break
        path, source = doctrine_path(entry, trigger_tf or "15m", level=level,
                                     prev_extreme=extreme)
        if path <= 0:
            return None
        if require_real_levels and level <= 0:
            return None
        step = path / 5.0
        tp1 = entry + (step if direction == "LONG" else -step)
        tp2 = entry + (path if direction == "LONG" else -path)
        return {
            "tp1": float(tp1),
            "tp2": float(tp2),
            "far_level": float(level or 0.0),
            "prev_extreme": float(extreme or 0.0),
            "path_pct": float(path / entry * 100.0),
            "source": source,
            "no_atr": True,
            "rr1": abs(tp1 - entry) / risk if risk else 0,
            "rr2": abs(tp2 - entry) / risk if risk else 0,
        }
    except Exception:
        return None


def _market_quality(bundle: MarketBundle, style: str) -> Tuple[bool, str, int]:
    ticker = bundle.ticker or {}
    day_turnover = float(ticker.get("trading_day_turnover", ticker.get("turnover24h", 0)) or 0)
    projected_turnover = float(ticker.get("projected_day_turnover", day_turnover) or day_turnover)
    relative = float(ticker.get("relative_volume", 1) or 1)
    # Viva 2026-09-14: missing feed data is UNKNOWN, not a veto — ASTER and
    # twelve others died at the liquidity gate purely because the ticker
    # payload carried no spread/turnover. When a number exists and is bad,
    # the veto stands exactly as before.
    _has_turn = bool(ticker.get("trading_day_turnover") or ticker.get("turnover24h"))
    _has_spread = ticker.get("spread_pct") is not None
    spread = float(ticker.get("spread_pct", 0) or 0)
    _min_turn = SETTINGS.scalp_min_turnover_usd if style == "SCALP" else SETTINGS.watchlist_min_turnover_usd
    _max_spread = SETTINGS.scalp_max_spread_percent if style == "SCALP" else SETTINGS.watchlist_max_spread_percent
    valid = ((not _has_turn) or projected_turnover >= _min_turn) \
        and ((not _has_spread) or spread <= _max_spread)
    points = 1 if valid and (relative >= 1.1 or projected_turnover >= SETTINGS.scalp_min_turnover_usd) else 0
    detail = (
        f"گردش مالی ثبت‌شده از ابتدای روز معاملاتی UTC حدود ${day_turnover:,.0f} "
        f"(برآورد آهنگ روزانه ${projected_turnover:,.0f})، اسپرد تقریبی {spread:.2f}% "
        f"و آهنگ حجم نسبی {relative:.2f} برابر میانه روزهای اخیر است. "
        + ("نقدشوندگی برای این نوع معامله قابل قبول ارزیابی شده است." if valid else "نقدشوندگی روز جاری یا اسپرد هنوز استاندارد لازم برای اجرای معامله را ندارد.")
    )
    return valid, detail, points


def _base_candidate(
    bundle: MarketBundle,
    style: str,
    setup_code: str,
    direction: str,
    context_tf: str,
    trigger_tf: str,
    context: Dict,
    poi: Dict,
    impulse: Dict,
    special_evidence: EvidenceItem,
    special_gate_name: str,
    special_gate_value: bool,
) -> Optional[SignalCandidate]:
    context_df = bundle.get(context_tf)
    trigger_df = bundle.get(trigger_tf)
    if context_df is None or trigger_df is None:
        return None
    bias = context["bias"]
    expected_bias = "BULLISH" if direction == "LONG" else "BEARISH"
    context_aligned = bias == expected_bias
    _profile_context, lower_context_tf, _profile_trigger = timeframe_profile(style)
    lower_context = structure_bias(bundle.get(lower_context_tf), 3) if bundle.get(lower_context_tf) is not None else {"bias": "NEUTRAL"}
    lower_aligned = lower_context["bias"] in (expected_bias, "NEUTRAL")
    pd_location = premium_discount(context_df)
    location_ok = (
        pd_location["location"] in ("DISCOUNT", "EQUILIBRIUM")
        if direction == "LONG"
        else pd_location["location"] in ("PREMIUM", "EQUILIBRIUM")
    )

    atr_values = atr(trigger_df)
    atr_value = float(atr_values.iloc[-1]) if pd.notna(atr_values.iloc[-1]) else abs(poi["top"] - poi["bottom"])
    entry = (float(poi["bottom"]) + float(poi["top"])) / 2
    invalidation = _liquidity_protected_invalidation(
        trigger_df,
        poi,
        direction,
        atr_value,
        style,
        float((bundle.ticker or {}).get("spread_pct", 0) or 0),
        dict(bundle.ticker or {}),
    )
    sl = float(invalidation["price"])
    if invalidation.get("stop_clamped"):
        stop_clamped_note = True
    else:
        stop_clamped_note = False
    if entry <= 0 or abs(entry - sl) / entry < 0.0008:
        return None
    # Viva 09-20: the TRIGGER timeframe's own next high/low is the primary
    # target; the higher (context) TF only contributes its important zones.
    targets = _structural_targets(
        trigger_df, direction, entry, sl, extra_df=context_df,
        atr_value=atr_value, trigger_tf=trigger_tf)
    if targets is None:
        return None
    # Optional Viva range-fraction targets (his rule for the previous system):
    # when aligned with the range EDGE (LONG in DISCOUNT / SHORT in PREMIUM),
    # aim for 40%/70% of the dealing-range height measured from the boundary
    # instead of the far structure — smaller, higher-probability targets.
    range_mode = bool(getattr(SETTINGS, "range_fraction_targets", False))
    if range_mode:
        raw_syms = getattr(SETTINGS, "range_fraction_symbols", "") or ""
        allowed = {x.strip().upper() for x in raw_syms.split(",") if x.strip()}
        if allowed and bundle.symbol.upper() not in allowed:
            range_mode = False
    if range_mode:
        _h = float(pd_location["high"]) - float(pd_location["low"])
        _loc = pd_location["location"]
        _edge = ((direction == "LONG" and _loc == "DISCOUNT")
                 or (direction == "SHORT" and _loc == "PREMIUM"))
        if _edge and _h > 0:
            if direction == "LONG":
                _tp1 = float(pd_location["low"]) + 0.40 * _h
                _tp2 = float(pd_location["low"]) + 0.70 * _h
            else:
                _tp1 = float(pd_location["high"]) - 0.40 * _h
                _tp2 = float(pd_location["high"]) - 0.70 * _h
            if (direction == "LONG" and _tp1 > entry) or (direction == "SHORT" and _tp1 < entry):
                _risk = abs(entry - sl)
                targets = {
                    **targets,
                    "tp1": float(_tp1),
                    "tp2": float(_tp2),
                    "rr1": (abs(_tp1 - entry) / _risk) if _risk > 0 else 0.0,
                    "rr2": (abs(_tp2 - entry) / _risk) if _risk > 0 else 0.0,
                }
    # Viva 09-20 (third time, verbatim): «فرمول ریسک به ریوارد ... اصلا اهمیت
    # نداره» → R:R never gates an entry; the TF distance ceiling + structure
    # decide the targets. Kept as a REPORTED value only.
    rr_ok = True
    _rr_report = (f"R/R (فقط گزارش): {targets['rr1']:.2f}R / {targets['rr2']:.2f}R — "
                  "مبنای انتخاب هدف یا تصمیم ورود نیست")
    market_ok, market_detail, market_points = _market_quality(bundle, style)

    htf_detail = (
        f"ساختار {context_tf.upper()} در وضعیت {bias} قرار دارد و تایم‌فریم میانی "
        f"{lower_context_tf.upper()} وضعیت {lower_context['bias']} را نشان می‌دهد. "
        f"قیمت نسبت به محدوده معاملاتی اخیر در بخش {pd_location['location']} قرار گرفته است. "
        + ("این چیدمان با جهت سناریو هم‌خوان است." if context_aligned and lower_aligned and location_ok else "بخشی از هم‌راستایی تایم‌فریم‌ها هنوز ضعیف است و امتیاز آن کاهش یافته است.")
    )
    poi_detail = (
        f"ناحیه {poi.get('type', 'POI')} بین {_fmt(poi['bottom'])} و {_fmt(poi['top'])} "
        f"از حرکت شکست اخیر استخراج شده است. این ناحیه {int(poi.get('touches', 0))} بار لمس شده و "
        + ("هنوز Fresh محسوب می‌شود؛ اولین بازگشت به آن برای بررسی ورود اولویت دارد." if poi.get("touches", 0) <= 1 else "به‌دلیل Mitigationهای متعدد کیفیت لازم را ندارد.")
    )
    displacement_detail = (
        f"کندل شکست با بدنه‌ای معادل {float(impulse.get('body_atr', 0)):.2f} برابر ATR و "
        f"حجم {float(impulse.get('volume_ratio', 0)):.2f} برابر میانه حجم اخیر بسته شده است. "
        f"سطح ساختاری {_fmt(float(impulse.get('level', 0)))} با Close شکسته شده؛ بنابراین شکست صرفاً یک Wick محسوب نمی‌شود."
    )
    rr_detail = (
        f"قیمت ابطال تحلیل در {_fmt(sl)}، آن‌سوی مرجع نقدینگی {_fmt(invalidation['liquidity_anchor'])} "
        f"و با بافر پویا {_fmt(invalidation['buffer'])} قرار گرفته است؛ بنابراین مستقیماً روی Pivot/نقدینگی آشکار نیست. "
        f"هدف اول {_fmt(targets['tp1'])} (یک‌پنجم مسیر) و هدف نهایی {_fmt(targets['tp2'])} "
        f"از سطح معتبر تایم تریگر/تایم بالاتر یا نُرم همان تایم انتخاب شده‌اند "
        f"(منبع: {targets.get('source', '')} • مسیر {float(targets.get('path_pct') or 0):.1f}٪). "
        f"{_rr_report}."
    )

    evidence = [
        EvidenceItem("htf", "ساختار و موقعیت تایم‌فریم بالاتر", htf_detail, context_aligned and lower_aligned and location_ok, 2),
        special_evidence,
        EvidenceItem("displacement", "شکست ساختار و Displacement", displacement_detail, bool(impulse.get("valid")), 2),
        EvidenceItem("poi", "ناحیه ورود و Freshness", poi_detail, poi.get("touches", 0) <= 1, 2),
        EvidenceItem("rr", "اهداف ساختاری (مستقل از استاپ)", rr_detail, rr_ok, 1),
        EvidenceItem("market", "نقدشوندگی و شرایط بازار", market_detail, market_ok, market_points),
    ]

    divergence = detect_rsi_divergence(trigger_df, direction)
    confirmations: List[str] = []
    if divergence:
        confirmations.append(
            f"واگرایی {divergence['type']} RSI بین Pivotهای هم‌زمان قیمت دیده شده است؛ این مورد فقط تأیید کمکی است."
        )

    dealing_high, dealing_low = pd_location["high"], pd_location["low"]
    dealing_range = dealing_high - dealing_low
    if direction == "LONG":
        ote_bottom = dealing_high - 0.79 * dealing_range
        ote_top = dealing_high - 0.62 * dealing_range
    else:
        ote_bottom = dealing_low + 0.62 * dealing_range
        ote_top = dealing_low + 0.79 * dealing_range
    overlaps_ote = max(float(poi["bottom"]), ote_bottom) <= min(float(poi["top"]), ote_top)
    if overlaps_ote:
        confirmations.append(
            f"ناحیه POI با محدوده OTE فیبوناچی 62% تا 79% ({_fmt(ote_bottom)} تا {_fmt(ote_top)}) هم‌پوشانی دارد؛ OTE به‌تنهایی دلیل ورود نیست."
        )

    last_session = session_name(trigger_df["timestamp"].iloc[-1])
    # Viva 2026-09-16: the session line lives in the 🧩 aids (with its 🕐 and
    # Persian name) — repeating it in confirmations printed it TWICE.

    # Score ranks quality; gates decide eligibility. They intentionally are
    # not the same mechanism, otherwise every eligible signal becomes a 10/10.
    score = 4
    score += 1 if context_aligned and lower_aligned else 0
    score += 1 if location_ok else 0
    score += 1 if special_gate_value else 0
    score += 1 if float(impulse.get("body_atr", 0) or 0) >= 0.80 else 0
    score += 1 if poi.get("touches", 0) == 0 else 0
    score += 1 if targets["rr1"] >= 2.0 and targets["rr2"] >= 3.0 else 0
    relative_volume = float((bundle.ticker or {}).get("relative_volume", 1) or 1)
    score += 1 if market_ok and relative_volume >= 1.10 else 0
    score = min(10, max(0, int(score)))
    gates = {
        "htf_alignment": context_aligned and lower_aligned and location_ok,
        special_gate_name: special_gate_value,
        "displacement": bool(impulse.get("valid")),
        "fresh_poi": poi.get("touches", 0) <= 1,
        "rr": rr_ok,
        "market_liquidity": market_ok,
    }
    # Viva 2026-09-14 «ببین کجا موقعیت‌ها خفه می‌شن»: on LINE setups a
    # repeatedly touched trendline/wedge/triangle/channel side is a STRONGER
    # reference, not a disqualifier — DOGE's 10/10 TechnoClassic died here
    # yesterday. Freshness stays as visible evidence and score; it never
    # vetoes a break that must confirm. Zone-entry setups keep the gate.
    if str(setup_code) in ("TLBREAK", "TECHCLASSIC"):
        gates.pop("fresh_poi", None)
        # …and the RR floor never vetoes a LINE ALERT either — ATOM's 4H
        # TechnoClassic (score 8) died there five cycles running. Ratios are
        # printed for the reader; the alert and its monitor life are unconditional.
        gates.pop("rr", None)
    # ── Viva 09-21 (round 12): a stop may never live beyond the horizon the
    # targets are allowed to travel («حدود ۱۲ درصد استاپ؟؟» — SEI 9.7%, LIT
    # 14% on 15m/1h). The TF distance ceiling (15m/1h 5% · 4h 7% · 1d 10%) is
    # the same horizon used for targets, so a farther invalidation means the
    # premise is not in this timeframe's trade: «حذف نشه» — the stop is CUT at
    # 1.25% of price instead and the alert keeps its honest note.
    try:
        from analysis.trade_management import (clamp_stop_price as _clamp_12,
                                               MAX_STOP_PCT as _max_stop_12)
        sl, _clamped12 = _clamp_12(entry, direction, sl, str(trigger_tf or ""))
        if _clamped12 or stop_clamped_note:
            candidate_stop_clamped = True
        else:
            candidate_stop_clamped = False
    except Exception:
        candidate_stop_clamped = False
    expiry_hours = expiry_hours_for(style, trigger_tf)
    expires = utc_now() + timedelta(hours=expiry_hours)
    signal_id = generate_viva_signal_id(bundle.symbol, style, setup_code)
    public_code = generate_viva_public_code(setup_code, style)
    _cand = SignalCandidate(
        signal_id=signal_id,
        symbol=bundle.symbol,
        style=style,
        setup_code=setup_code,
        setup_name=SETUP_NAMES[setup_code],
        strategy_fa=SETUP_NAMES_FA[setup_code],
        direction=direction,
        score=score,
        status="EDUCATIONAL",
        entry_zone_bottom=float(poi["bottom"]),
        entry_zone_top=float(poi["top"]),
        planned_entry=float(entry),
        sl=float(sl),
        tp1=targets["tp1"],
        tp2=targets["tp2"],
        rr_tp1=targets["rr1"],
        rr_tp2=targets["rr2"],
        bias=bias,
        trigger_timeframe=trigger_tf,
        evidence=evidence,
        confirmations=confirmations,
        warnings=[
            "این تحلیل تا بسته‌شدن کندلِ تأییدیِ معتبر، دستور ورود نیست.",
            f"لمس/عبور معتبر قیمت از {_fmt(sl)} سناریوی تحلیلی را باطل می‌کند.",
            (
                "در Swing این قیمت مرز ابطال تحلیل است؛ محل سفارش استاپ و مدیریت خروج باید توسط خود معامله‌گر تعیین شود."
                if style == "SWING"
                else "استاپ و اندازه پوزیشن پیشنهادی‌اند و باید با مدیریت شخصی معامله‌گر تطبیق داده شوند."
            ),
        ],
        mandatory_gates=gates,
        market=dict(bundle.ticker or {}),
        metadata={
            "impulse_index": int(impulse.get("index", -1)),
            "structure_level": float(impulse.get("level", 0)),
            "poi_type": poi.get("type", "POI"),
            "atr": atr_value,
            "invalidation_liquidity_anchor": invalidation["liquidity_anchor"],
            "invalidation_buffer": invalidation["buffer"],
            "protected_liquidity_pivots": invalidation["protected_pivots"],
            "session": last_session,
            "public_code": public_code,
            "strategy_version": SETTINGS.strategy_version,
            # Historical visits affect freshness, never satisfy the future
            # retest requirement. Only candles after created_at may set this.
            "touched": False,
            "historical_visit_count": int(poi.get("touches", 0)),
            "stop_clamped": bool(candidate_stop_clamped),
            "confirm_tf": confirm_timeframe_for_pattern(context_tf, style, trigger_tf),
        },
        expires_at=expires.isoformat(timespec="seconds"),
    )
    # FORMAT-3 (Viva 09-16): «مهم‌ترین نشانهٔ داخلی روی ناحیه + تحلیل دوخطی» —
    # whichever of engulfing/pin/doji/compression actually formed near the
    # zone travels with the candidate, so every detailed message analyzes it
    # in the setup's own voice.
    _zt = detect_zone_trigger(trigger_df, direction, float(poi["bottom"]),
                              float(poi["top"]), atr_value)
    if _zt:
        _cand.metadata["zone_trigger"] = _zt
    # CHART-8 (Viva 09-16): every setup stores detect→render commands so ALL
    # setups paint their zones/patterns, plus HTF zones for context awareness.
    try:
        from analysis.render_kit import enrich_render
        enrich_render(_cand, trigger_df, htf_df=context_df)
    except Exception as exc:
        print(f"render kit warning {setup_code}: {exc}")
    # continuation doctrine: mid-box / wrong-edge candidates do not trade —
    # EXCEPT the break/watch streams, which ARE the doctrine's own trigger
    # (break + first close = entry; watch = the warning itself)
    _code8 = str(_cand.setup_code or "").upper()
    _var8 = str((_cand.metadata or {}).get("strategy_variant") or "").upper()
    _watch8 = str((_cand.metadata or {}).get("viva_state") or "").upper()
    if not (_code8 in ("TLBREAK", "TECHCLASSIC", "ALBROX")
            or _var8 in ("VIVA_TLBREAK", "TECHNOCLASSIC", "PINWALL_QUALITY")
            or _watch8.startswith("S0_WATCH")):
        if str(_cand.metadata.get("base_gate", "ALLOW")).startswith(("REJECT", "WARN")):
            return None
    return _cand


def detect_zone_trigger(df, direction: str, zone_bottom: float, zone_top: float,
                        atr_value: float) -> Optional[dict]:
    """The active internal sign ON the zone, with a two-line Persian analysis
    (Viva 09-16: «انگالف/پین‌بار/فشردگی/... که اتفاق افتاده را بگو و تحلیل
    بکن»). Deterministic, closed-candle only, priority: engulfing → pin →
    doji/key-bar → compression."""
    if df is None or getattr(df, "empty", True) or len(df) < 8 or atr_value <= 0:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    o, h, l, c = (float(last["open"]), float(last["high"]),
                  float(last["low"]), float(last["close"]))
    rng = max(h - l, 1e-12)
    body = abs(c - o)
    po, pc = float(prev["open"]), float(prev["close"])
    pbody = abs(pc - po)
    long_side = str(direction).upper() == "LONG"
    if body >= 0.9 * max(pbody, 1e-12) and (
            (long_side and c > o and pc < po and c >= po and o <= pc)
            or (not long_side and c < o and pc > po and c <= po and o >= pc)):
        return {"title_fa": f"انگالفینگ {'صعودی' if long_side else 'نزولی'} روی ناحیه",
                "lines": [
                    f"کندل آخر با بدنهٔ {body / atr_value:.2f} برابر ATR، بدنهٔ کندل پیشین را کامل پوشاند — ورود پول به جهت سناریو روی ناحیه.",
                    "اگر کلوز بعدی بیرون بدنهٔ انگالف بماند ادامهٔ حرکت محتمل است؛ برگشت به میانهٔ بدنه یعنی ضعف نشانه."]}
    main_wick = (min(o, c) - l) if long_side else (h - max(o, c))
    if main_wick >= 2.0 * max(body, 1e-12) and body <= 0.35 * rng:
        return {"title_fa": f"پین‌بار {'صعودی' if long_side else 'نزولی'} روی ناحیه",
                "lines": [
                    f"شدوی {main_wick / rng:.0%} دامنه، نقدینگیِ سمت ناحیه را جارو کرد و کلوز برگشت — امضای کلاسیک ریجکت.",
                    "نشانه تا شکسته‌شدن نوک شدو با کلوز معتبر است؛ کلوز در جهت سناریو آن را فعال می‌کند."]}
    if body <= 0.10 * rng:
        return {"title_fa": "دوجی / کی‌بار روی ناحیه",
                "lines": [
                    "کندل با بدنهٔ بسیار کوچک و شدوهای دوطرفه بسته شد — تعادل موقت خریدار و فروشنده روی لبهٔ ناحیه.",
                    "شکست سقف/کف همین کندل به جهت سناریو، اولین نشانهٔ فعال‌شدن است."]}
    recent = df.iloc[-5:]
    avg = float((recent["high"] - recent["low"]).mean())
    if avg < 0.6 * atr_value:
        return {"title_fa": "فشردگی / کامپرشن روی ناحیه",
                "lines": [
                    f"میانگین دامنهٔ ۵ کندل اخیر {avg / atr_value:.2f} برابر ATR است — فشرده‌سازی پیش از انفجار حرکت.",
                    "کلوز بیرون از سقف/کف این پیله به جهت سناریو، نشانهٔ فعال‌شدن سناریو است."]}
    return None


def detect_liquidity_reversal(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    context_tf, middle_tf, trigger_tf = timeframe_profile(style)
    if not _ensure_frames(bundle, (context_tf, middle_tf, trigger_tf)):
        return None
    context = structure_bias(bundle.get(context_tf), 5)
    if context["bias"] not in ("BULLISH", "BEARISH"):
        return None
    direction = _direction(context["bias"])
    trigger_df = bundle.get(trigger_tf)
    sweep = _find_sweep(trigger_df, direction)
    if not sweep:
        return None
    mss = _find_structure_break_after(trigger_df, direction, sweep["index"])
    if not mss:
        return None
    poi = _select_poi(trigger_df, direction, mss["index"])
    if not poi:
        return None
    detail = (
        f"قیمت در کندل {pd.Timestamp(sweep['timestamp']).strftime('%Y-%m-%d %H:%M UTC')} از سطح نقدینگی "
        f"{_fmt(sweep['level'])} عبور کرده و تا {_fmt(sweep['extreme'])} نفوذ داشته، اما دوباره آن‌سوی سطح بسته شده است. "
        f"میزان Rejection حدود {sweep['rejection'] * 100:.0f}% دامنه کندل است. این رفتار یک Liquidity Raid معتبر است، "
        f"ولی ورود فقط بعد از MSS و Retest بررسی می‌شود."
    )
    special = EvidenceItem("liquidity", "جمع‌آوری نقدینگی", detail, True, 2, level=sweep["level"], timeframe=trigger_tf)
    candidate = _base_candidate(
        bundle, style, "LSR", direction, context_tf, trigger_tf, context, poi, mss,
        special, "liquidity_sweep", True,
    )
    if candidate:
        candidate.metadata.update({"sweep_level": sweep["level"], "sweep_index": sweep["index"], "mss_level": mss["level"]})
    return candidate


def detect_bos_first_pullback(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    context_tf, middle_tf, trigger_tf = timeframe_profile(style)
    if not _ensure_frames(bundle, (context_tf, middle_tf, trigger_tf)):
        return None
    context = structure_bias(bundle.get(context_tf), 5)
    if context["bias"] not in ("BULLISH", "BEARISH"):
        return None
    direction = _direction(context["bias"])
    trigger_df = bundle.get(trigger_tf)
    bos = _find_recent_bos(trigger_df, direction)
    if not bos:
        return None
    poi = _select_poi(trigger_df, direction, bos["index"])
    if not poi or poi["touches"] > 0:
        return None
    detail = (
        f"قیمت سطح ساختاری {_fmt(bos['level'])} را با بسته‌شدن کندل و در جهت Bias تایم‌فریم بالاتر شکسته است. "
        f"پس از شکست هنوز بازگشت معتبری به ناحیه مبدأ انجام نشده؛ بنابراین تنها اولین پولبک بررسی می‌شود. "
        f"پولبک دوم یا سوم به‌علت مصرف‌شدن سفارش‌های ناحیه، ستاپ جدید محسوب نخواهد شد."
    )
    special = EvidenceItem("first_pullback", "BOS و اولین پولبک", detail, True, 2, level=bos["level"], timeframe=trigger_tf)
    return _base_candidate(
        bundle, style, "BOS1", direction, context_tf, trigger_tf, context, poi, bos,
        special, "first_pullback", True,
    )


def _trendline_break(df: pd.DataFrame, direction: str, recent_bars: int = 8) -> Optional[Dict]:
    ph, pl = pivots(df, 3, 3)
    points = ph if direction == "LONG" else pl
    if len(points) < 3:
        return None
    points = points[-4:]
    x = np.array([point["index"] for point in points], dtype=float)
    y = np.array([point["price"] for point in points], dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    expected_slope = slope < 0 if direction == "LONG" else slope > 0
    if not expected_slope:
        return None
    atr_now = float(atr(df).iloc[-1])
    fitted = slope * x + intercept
    max_error = float(np.max(np.abs(y - fitted)))
    if atr_now <= 0 or max_error > 0.45 * atr_now:
        return None
    start = max(points[-1]["index"] + 1, len(df) - recent_bars)
    for i in range(start, len(df)):
        level = float(slope * i + intercept)
        prev_level = float(slope * (i - 1) + intercept)
        close, prev_close = float(df["close"].iloc[i]), float(df["close"].iloc[i - 1])
        crossed = prev_close <= prev_level and close > level if direction == "LONG" else prev_close >= prev_level and close < level
        displacement = candle_displacement(df, i, 0.75)
        expected = "BULLISH" if direction == "LONG" else "BEARISH"
        if crossed and displacement["valid"] and displacement["direction"] == expected:
            later_touches = 0
            for j in range(i + 1, len(df)):
                projected = slope * j + intercept
                if float(df["low"].iloc[j]) <= projected + 0.15 * atr_now and float(df["high"].iloc[j]) >= projected - 0.15 * atr_now:
                    later_touches += 1
            current_level = float(slope * (len(df) - 1) + intercept)
            return {
                "index": i, "level": level, "current_level": current_level,
                "slope": float(slope), "intercept": float(intercept),
                "touches": later_touches, "line_points": len(points), "fit_error_atr": max_error / atr_now,
                **displacement,
            }
    return None


def detect_trendline_first_retest(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    context_tf, middle_tf, trigger_tf = timeframe_profile(style)
    if not _ensure_frames(bundle, (context_tf, middle_tf, trigger_tf)):
        return None
    context = structure_bias(bundle.get(context_tf), 5)
    if context["bias"] not in ("BULLISH", "BEARISH"):
        return None
    direction = _direction(context["bias"])
    trigger_df = bundle.get(trigger_tf)
    broken = _trendline_break(trigger_df, direction)
    if not broken or broken["touches"] > 0:
        return None
    atr_now = float(broken.get("atr") or atr(trigger_df).iloc[-1])
    poi = {
        "bottom": broken["current_level"] - 0.18 * atr_now,
        "top": broken["current_level"] + 0.18 * atr_now,
        "touches": broken["touches"],
        "type": "BROKEN TRENDLINE",
    }
    detail = (
        f"خط روند از {broken['line_points']} Pivot معتبر ساخته شده و شیب آن با ساختار قبلی سازگار است. "
        f"حداکثر خطای تماس Pivotها {broken['fit_error_atr']:.2f} برابر ATR بوده است؛ بنابراین خط به‌صورت دلخواه رسم نشده است. "
        f"قیمت خط را در {_fmt(broken['level'])} با Close و Displacement شکسته و هنوز پولبک ثبت نشده؛ فقط First Retest قابل بررسی است."
    )
    special = EvidenceItem("trendline", "اعتبار خط روند و شکست", detail, True, 2, level=broken["level"], timeframe=trigger_tf)
    candidate = _base_candidate(
        bundle, style, "TLR", direction, context_tf, trigger_tf, context, poi, broken,
        special, "valid_trendline_break", True,
    )
    if candidate:
        candidate.metadata.update({"trendline_slope": broken["slope"], "trendline_intercept": broken["intercept"]})
    return candidate


def _cluster_level(points: List[Dict], atr_value: float, minimum_touches: int = 2) -> Optional[Dict]:
    if len(points) < minimum_touches or atr_value <= 0:
        return None
    best = None
    for anchor in reversed(points[-10:]):
        cluster = [point for point in points[-15:] if abs(point["price"] - anchor["price"]) <= 0.30 * atr_value]
        if len(cluster) >= minimum_touches:
            candidate = {"level": float(np.mean([point["price"] for point in cluster])), "touches": len(cluster), "last_index": max(point["index"] for point in cluster)}
            if best is None or candidate["last_index"] > best["last_index"]:
                best = candidate
    return best


def _supply_demand_break(df: pd.DataFrame, direction: str) -> Optional[Dict]:
    ph, pl = pivots(df, 3, 3)
    atr_value = float(atr(df).iloc[-1])
    cluster = _cluster_level(ph if direction == "LONG" else pl, atr_value)
    if not cluster:
        return None
    for i in range(max(cluster["last_index"] + 2, len(df) - 10), len(df)):
        level = cluster["level"]
        close, prev_close = float(df["close"].iloc[i]), float(df["close"].iloc[i - 1])
        crossed = prev_close <= level and close > level + 0.08 * atr_value if direction == "LONG" else prev_close >= level and close < level - 0.08 * atr_value
        displacement = candle_displacement(df, i, 0.8)
        expected = "BULLISH" if direction == "LONG" else "BEARISH"
        if crossed and displacement["valid"] and displacement["direction"] == expected:
            retests = sum(
                1 for j in range(i + 1, len(df))
                if float(df["low"].iloc[j]) <= level + 0.18 * atr_value
                and float(df["high"].iloc[j]) >= level - 0.18 * atr_value
            )
            return {"index": i, "level": level, "touches_before": cluster["touches"], "touches": retests, **displacement}
    return None


def detect_supply_demand_retest(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    context_tf, middle_tf, trigger_tf = timeframe_profile(style)
    if not _ensure_frames(bundle, (context_tf, middle_tf, trigger_tf)):
        return None
    context = structure_bias(bundle.get(context_tf), 5)
    if context["bias"] not in ("BULLISH", "BEARISH"):
        return None
    direction = _direction(context["bias"])
    trigger_df = bundle.get(trigger_tf)
    broken = _supply_demand_break(trigger_df, direction)
    if not broken or broken["touches"] > 0:
        return None
    atr_now = float(broken.get("atr") or atr(trigger_df).iloc[-1])
    poi = {
        "bottom": broken["level"] - 0.18 * atr_now,
        "top": broken["level"] + 0.18 * atr_now,
        "touches": 0,
        "type": "SUPPLY/DEMAND FLIP",
    }
    zone_name = "عرضه" if direction == "LONG" else "تقاضا"
    detail = (
        f"سطح {_fmt(broken['level'])} از تجمع {broken['touches_before']} Pivot معتبر ساخته شده و یک ناحیه مهم {zone_name} بوده است. "
        f"قیمت با Close و حرکت Impulsive از ناحیه عبور کرده و آن را به Flip Zone تبدیل کرده است. "
        f"از زمان شکست هنوز Retest رخ نداده؛ بنابراین فقط اولین بازگشت و حفظ سمت جدید سطح قابل معامله است."
    )
    special = EvidenceItem("supply_demand", "شکست ناحیه عرضه/تقاضا", detail, True, 2, level=broken["level"], timeframe=trigger_tf)
    return _base_candidate(
        bundle, style, "SDR", direction, context_tf, trigger_tf, context, poi, broken,
        special, "valid_supply_demand_break", True,
    )


def detect_ifvg_breaker(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    context_tf, middle_tf, trigger_tf = timeframe_profile(style)
    if not _ensure_frames(bundle, (context_tf, middle_tf, trigger_tf)):
        return None
    context = structure_bias(bundle.get(context_tf), 5)
    if context["bias"] not in ("BULLISH", "BEARISH"):
        return None
    direction = _direction(context["bias"])
    df = bundle.get(trigger_tf)
    atr_now = float(atr(df).iloc[-1])
    if atr_now <= 0:
        return None
    # Locate an old opposite FVG that was decisively invalidated in HTF direction.
    for middle in range(len(df) - 8, max(2, len(df) - 60), -1):
        left, right = df.iloc[middle - 1], df.iloc[middle + 1]
        if direction == "LONG" and float(left["low"]) > float(right["high"]):
            bottom, top = float(right["high"]), float(left["low"])
            violated = lambda close: close > top
        elif direction == "SHORT" and float(right["low"]) > float(left["high"]):
            bottom, top = float(left["high"]), float(right["low"])
            violated = lambda close: close < bottom
        else:
            continue
        for i in range(middle + 2, len(df)):
            displacement = candle_displacement(df, i, 0.8)
            expected = "BULLISH" if direction == "LONG" else "BEARISH"
            if violated(float(df["close"].iloc[i])) and displacement["valid"] and displacement["direction"] == expected:
                touches = sum(
                    1 for j in range(i + 1, len(df))
                    if float(df["low"].iloc[j]) <= top and float(df["high"].iloc[j]) >= bottom
                )
                if touches > 0:
                    # This gap has already been mitigated; inspect an older fresh one.
                    break
                poi = {"bottom": bottom, "top": top, "touches": 0, "type": "INVERSE FVG / BREAKER"}
                impulse = {"index": i, "level": top if direction == "LONG" else bottom, **displacement}
                detail = (
                    f"FVG مخالف بین {_fmt(bottom)} و {_fmt(top)} با یک کندل Displacement در جهت Bias شکسته و بی‌اعتبار شده است. "
                    f"این ناحیه اکنون نقش Inverse FVG یا Breaker را دارد. هنوز بازگشتی به آن ثبت نشده و فقط اولین Retest، "
                    f"به‌همراه حفظ ساختار و کندل تأیید، اجازه ورود خواهد داد."
                )
                special = EvidenceItem("ifvg", "تبدیل FVG به Breaker", detail, True, 2, level=(bottom + top) / 2, timeframe=trigger_tf)
                return _base_candidate(
                    bundle, style, "IFVG", direction, context_tf, trigger_tf, context, poi, impulse,
                    special, "valid_breaker", True,
                )
    return None


DETECTORS = [
    detect_liquidity_reversal,
    detect_bos_first_pullback,
    detect_trendline_first_retest,
    detect_supply_demand_retest,
    detect_ifvg_breaker,
]


def _active_detectors() -> List:
    """Production detectors plus env-flagged experimental ones (lazy import to
    avoid a module cycle: setups_experimental imports helpers from here).

    Viva-era default: the five legacy core detectors are OFF (no standalone
    edge in the 90d/4-sample R&D review) unless CORE_V7_SETUPS_ENABLED=true.
    The validated paths (P1234+ADX, TLBREAK pattern alerts) and the PINVAL
    pinbar alert run whenever their own flags allow."""
    detectors = list(DETECTORS) if getattr(SETTINGS, "core_v7_setups_enabled", False) else []
    try:
        import analysis.setups_experimental as exp
        if getattr(SETTINGS, "experimental_p1234_enabled", False):
            detectors.extend(exp.EXPERIMENTAL_DETECTORS)
        if getattr(SETTINGS, "experimental_tlbreak_enabled", False) or getattr(SETTINGS, "viva_tlbreak_enabled", False):
            detectors.extend(exp.TLBREAK_DETECTORS)
        # DROUGHT-3 (audit 09-15, ruling R-5): the pin-drought killer was the
        # old `elif` here — with Pinwall-Quality ON, a base pin that Q rejects
        # on score alone (observed: ETH 52, AAVE 47 vs gate 78) was published
        # by NOBODY; ~100 real reversal swings went unspoken. PINVAL now ALWAYS
        # registers as the family fallback, and scan_setups dedupes the
        # same-bar pair so we never emit two near-identical pinbar messages
        # (the richer Q message wins whenever it survived its own gate).
        pinwall_q = bool(getattr(SETTINGS, "pinwall_quality_enabled", False))
        if pinwall_q:
            detectors.extend(exp.PINWALL_QUALITY_DETECTORS)
        if getattr(SETTINGS, "pinv_enabled", True):
            detectors.extend(exp.PINVAL_DETECTORS)
        if getattr(SETTINGS, "albrox_enabled", False):
            detectors.extend(exp.ALBROX_DETECTORS)
        if getattr(SETTINGS, "technoclassic_enabled", False):
            detectors.extend(exp.TECHCLASSIC_DETECTORS)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Experimental detectors unavailable: {exc}")
    return detectors


def _experimental_symbol_allowed(detector_name: str, symbol: str) -> bool:
    if detector_name == "detect_pattern_1234":
        raw = getattr(SETTINGS, "experimental_p1234_symbols", "") or ""
    elif detector_name in ("detect_pinbar_zone", "detect_pinwall_quality"):
        raw = getattr(SETTINGS, "pinv_symbols", "") or ""
    elif detector_name == "detect_albrox":
        raw = getattr(SETTINGS, "albrox_symbols", "") or ""
    elif detector_name == "detect_technoclassic":
        raw = getattr(SETTINGS, "technoclassic_symbols", "") or ""
    else:
        raw = getattr(SETTINGS, "experimental_tlbreak_symbols", "") or ""
    allowed = {x.strip().upper() for x in raw.split(",") if x.strip()}
    return not allowed or symbol.upper() in allowed


# ── Viva 09-21 (round 12, second pass) — «مطمئنم هنوز باگ داریم در برخی منطق
# ها یا ستاپها»: the horizon gate lived INSIDE one builder, so a detector that
# assembles its own candidate (TECHCLASSIC) could still override the stop and
# the targets AFTER the gate and publish nonsense: DASH 15m went out with a 24%
# stop and a 34% target, and a DASH LONG carried its stop ABOVE the entry.
# Every lane now ends in ONE net: the stop must sit on the correct side of the
# entry this candidate itself will trade from, the stop distance must fit the
# timeframe horizon, and both targets must sit on the correct side inside that
# same horizon. Nothing is published otherwise (and confirmations re-check it).
_SANITY_REJECT_LOG: List[str] = []


def drain_sanity_rejects() -> List[str]:
    """Test/debug helper: reasons collected since the last drain."""
    out = list(_SANITY_REJECT_LOG)
    _SANITY_REJECT_LOG.clear()
    return out


def sanity_reject(candidate) -> Optional[str]:
    """Round-12 hard geometry net — returns a reject code or None when clean."""
    try:
        from analysis.trade_management import target_distance_cap_pct
        entry = float(getattr(candidate, "planned_entry", 0) or 0)
        sl = float(getattr(candidate, "sl", 0) or 0)
        tp1 = float(getattr(candidate, "tp1", 0) or 0)
        tp2 = float(getattr(candidate, "tp2", 0) or 0)
        direction = str(getattr(candidate, "direction", "") or "").upper()
        tf = str(getattr(candidate, "trigger_timeframe", "") or "15m")
        if entry <= 0 or sl <= 0 or tp1 <= 0 or tp2 <= 0:
            return "GEOMETRY_MISSING"
        cap = float(target_distance_cap_pct(tf)) or 5.0
        try:
            from analysis.trade_management import tolerant_cap_pct as _tcap
            cap = float(_tcap(tf)) or cap
        except Exception:
            pass
        if direction == "LONG":
            if sl >= entry:
                return "STOP_WRONG_SIDE"
            if tp1 <= entry or tp2 <= entry:
                return "TARGET_WRONG_SIDE"
        elif direction == "SHORT":
            if sl <= entry:
                return "STOP_WRONG_SIDE"
            if tp1 >= entry or tp2 >= entry:
                return "TARGET_WRONG_SIDE"
        else:
            return "DIRECTION_MISSING"
        # Round 14: the stop's own ceiling for THIS timeframe (15m 1.25% ·
        # 1h 1.75% · 4h 2.25% · 1d 2.75%), not the TP band. Upstream every lane
        # already clamps to it; anything still past it (2% rounding slack) means
        # the geometry is broken some other way.
        try:
            from analysis.trade_management import stop_ceiling_pct as _scp14
            _stop_ceiling14 = float(_scp14(tf))
        except Exception:
            _stop_ceiling14 = 1.25
        if abs(entry - sl) / entry * 100.0 > _stop_ceiling14 * 1.02:
            return "STOP_HORIZON"
        # 2% tolerance: rounding in the ladder must not kill a legitimate path.
        if abs(tp2 - entry) / entry * 100.0 > cap * 1.02:
            return "TARGET_HORIZON"
        if abs(tp1 - entry) / entry * 100.0 > cap * 1.02:
            return "TARGET_HORIZON"
    except Exception:
        # Fail-open on our own bug: a broken check must not silence the scanner.
        return None
    return None


def _fatal_side_stop(frame, direction: str, entry: float, buffer: float) -> Optional[float]:
    """Round-14b: a structural invalidation level on the fatal side of `entry`.

    Why this exists: a lane whose stop came from the last candle's own extreme
    collapsed onto the entry whenever that candle closed ON its extreme
    (TRXUSDT 09-21 00:16 SHORT: entry=sl=0.34352 → the sanity net dropped the
    whole scenario). Viva's law is «حذف نشه» — the premise level is rebuilt
    from the recent structural extreme of the fatal side plus the standard
    buffer (5 venue ticks / 0.10%), never from the entry itself.
    """
    try:
        if frame is None or not len(frame):
            return None
        entry = float(entry or 0.0)
        win = frame.tail(8)
        buf = float(buffer or 0.0)
        if entry <= 0:
            entry = float(win["close"].iloc[-1])
        if str(direction).upper() == "LONG":
            return float(min(float(win["low"].min()), entry) - buf)
        return float(max(float(win["high"].max()), entry) + buf)
    except Exception:
        return None


def scan_setups(bundle: MarketBundle, style: str) -> List[SignalCandidate]:
    candidates: List[SignalCandidate] = []
    for detector in _active_detectors():
        if getattr(detector, "__module__", "").endswith("setups_experimental") and not _experimental_symbol_allowed(detector.__name__, bundle.symbol):
            continue
        try:
            result = detector(bundle, style)
            if result and result.score >= SETTINGS.educational_min_score:
                candidates.append(result)
        except Exception as exc:
            print(f"Setup detector error {detector.__name__} {bundle.symbol} {style}: {exc}")
    # DROUGHT-3 dedup: PINWALLQ wraps PINVAL — when both fired for the same
    # symbol+direction on this scan, the richer Q message represents the bar
    # and the legacy PINVAL twin is dropped (never two pinbar messages for
    # one pin). When Q rejected the bar (score below its gate), PINVAL alone
    # survives and the pin still speaks — that is the whole point of R-5.
    _q_dirs = {c.direction for c in candidates if c.setup_code == "PINWALLQ"}
    if _q_dirs:
        candidates = [c for c in candidates
                      if not (c.setup_code == "PINVAL" and c.direction in _q_dirs)]
    # Avoid several highly correlated messages from the same move: keep the two strongest,
    # preferring execution-ready candidates and then score/RR.
    # Viva 2026-09-14 «پیام‌های همهٔ ستاپ‌ها باید بیاید»: the old keep-two cap
    # silently strangled a full-score detection behind two fitter siblings.
    # The per-licence law (3 rotating per symbol/trigger-TF/setup) owns the
    # channel volume now — so four candidates per symbol×style may present.
    candidates.sort(key=lambda c: (c.execution_ready, c.score, c.rr_tp1), reverse=True)
    # ── the single net every lane must pass (see sanity_reject above).
    kept: List[SignalCandidate] = []
    for cand in candidates:
        # ── Round-14b guard: a stop that ended up on the wrong side of its own
        # entry — or closer to it than one standard buffer — is re-anchored on
        # the trigger frame's fatal-side structure before anything else runs,
        # so the geometry net never has to drop the scenario.
        try:
            from analysis.trade_management import structural_buffer as _sb_g
            _e_g = float(getattr(cand, "planned_entry", 0) or 0)
            _s_g = float(getattr(cand, "sl", 0) or 0)
            _d_g = str(getattr(cand, "direction", "") or "").upper()
            _tf_g = str(getattr(cand, "trigger_timeframe", "") or "15m")
            _buf_g = _sb_g(_e_g)
            _bad_g = _e_g > 0 and (
                _s_g <= 0
                or (_d_g == "LONG" and _s_g >= _e_g)
                or (_d_g == "SHORT" and _s_g <= _e_g)
                or abs(_e_g - _s_g) < _buf_g
            )
            if _bad_g:
                _frame_g = None
                for _key_g in (_tf_g, "15m", "5m", "1h", "4h"):
                    try:
                        _f_try = bundle.get(_key_g)
                    except Exception:
                        _f_try = None
                    if _f_try is not None and len(_f_try):
                        _frame_g = _f_try
                        break
                _new_g = _fatal_side_stop(_frame_g, _d_g, _e_g, _buf_g)
                if _new_g:
                    cand.sl = float(_new_g)
                    _md_g = getattr(cand, "metadata", None)
                    if isinstance(_md_g, dict):
                        _md_g["stop_reanchored"] = True
        except Exception:
            pass
        # ── his 09-21 ruling, applied once at the funnel: a structural stop
        # farther than 1.25% of price is CUT there — never a dropped scenario.
        try:
            from analysis.trade_management import clamp_stop_price as _clamp_f
            _new_sl, _was_clamped = _clamp_f(getattr(cand, "planned_entry", 0) or 0,
                                             getattr(cand, "direction", ""), getattr(cand, "sl", 0) or 0,
                                             str(getattr(cand, "trigger_timeframe", "") or ""))
            if _was_clamped:
                cand.sl = float(_new_sl)
                _md_f = getattr(cand, "metadata", None)
                if isinstance(_md_f, dict):
                    _md_f["stop_clamped"] = True
        except Exception:
            pass
        # ── a WATCH-stage candidate (the two-pivot TLBREAK preview) legitimately
        # arrives without explicit targets: the doctrine fills them here instead
        # of the net dropping a preview Viva asked for.
        if not float(getattr(cand, "tp1", 0) or 0) or not float(getattr(cand, "tp2", 0) or 0):
            try:
                from analysis.trade_management import doctrine_path as _dp_f
                _entry_f = float(getattr(cand, "planned_entry", 0) or 0)
                _path_f, _src_f = _dp_f(_entry_f, str(getattr(cand, "trigger_timeframe", "") or "15m"))
                if _entry_f > 0 and _path_f > 0:
                    if str(getattr(cand, "direction", "")).upper() == "LONG":
                        cand.tp2 = _entry_f + _path_f
                        cand.tp1 = _entry_f + _path_f / 5.0
                    else:
                        cand.tp2 = _entry_f - _path_f
                        cand.tp1 = _entry_f - _path_f / 5.0
                    _md_f = getattr(cand, "metadata", None)
                    if isinstance(_md_f, dict):
                        _md_f["tp_source"] = _src_f
            except Exception:
                pass
        why = sanity_reject(cand)
        if why:
            line = (f"🧱 SANITY_REJECT {why} • {bundle.symbol} {style} "
                    f"{getattr(cand, 'setup_code', '?')} {getattr(cand, 'direction', '?')} "
                    f"entry={getattr(cand, 'planned_entry', 0)} sl={getattr(cand, 'sl', 0)} "
                    f"tp1={getattr(cand, 'tp1', 0)} tp2={getattr(cand, 'tp2', 0)} "
                    f"tf={getattr(cand, 'trigger_timeframe', '?')}")
            _SANITY_REJECT_LOG.append(line)
            print(line)
            continue
        kept.append(cand)
    return kept[:4]
