"""Deterministic multi-target and trailing-stop lifecycle primitives.

This module has no database or Telegram dependency so every fill rule is unit
 testable before it is wired into the live monitor.
"""
from __future__ import annotations
import numpy as np
from typing import Dict, List, Optional

# Viva 09-19 ruling (WR73% / −22.68% diagnosis): the old hidden 5-segment
# ladder banked 70% of size inside the first half of the move (typical win
# +0.14R..0.42R, max +0.84R) against a full −1R loss — breakeven needed a
# 77–88% win rate. The aligned ladder exits ON the drawn levels instead:
#   3 exits 50/30/20 when the final target is ≥2R away,
#   2 exits 60/40 when it is ≥1R, single final exit below that.
# Viva 09-19/20 ruling (revisit of the ladder): the tool keeps its ORIGINAL
# five-pill shape (five equal price segments entry→final — the art he
# approved), TP1 distance stays exactly as before (no 1R floor: «نیاز نیست
# TP1 و استاپ هم‌اندازه باشن»), and the EXITS are 40/30/30 on TP1..TP3 while
# TP4/TP5 stay drawn as information-only levels (he may move to four TPs
# later; journal data decides). The P&L guards (net-BE, protection floors,
# ratchet, smart exit) stay on top of this geometry.
DEFAULT_WEIGHTS = (40.0, 30.0, 30.0, 0.0, 0.0)
FALLBACK_WEIGHTS_2 = (60.0, 40.0)
TP1_FLOOR_R = 1.0            # RETIRED 09-19/20 (Viva: TP1 و استاپ هم‌اندازه نیستند); kept for legacy state readers
STRUCTURAL_TP1_SHARE = 0.40  # detector TP1 = 40% of the entry→final path
# Viva 09-19 (his delegation: «اندازه فرمول باید انعطاف داشته باشد — تو بگو»):
# protection-floor ratios adapt to the WIDTH of each band in R — a wider band
# carries more give-back risk, so it protects a larger share of it. Clipped
# to the 0.20–0.50 corridor his professional spec §4 allows.
BAND_K_MIN = 0.30
BAND_K_MAX = 0.50
BAND_K_SLOPE = 0.10
BAND_K_MID = 0.5             # band width (in R) that maps to the α=0.40 baseline
BAND_K_FIRST = 0.40          # legacy default kept for v1 readers / tests
BAND_K_NEXT = 0.50
VOL_STOP_ATR_N = 1.0         # base volatility stop = recent swing ∓ n×ATR
SWING_BARS = 5
# Viva 09-19/20 protection ruling (verbatim): signs must never «رد بشه و فقط
# هشدار بمونه» — TWO concurrent signs close ALL remainder at that closed
# candle's close; ONE sign is a short warning. Runtime (repository monitor)
# always closed on score ≥ 2; these level constants now say the same thing.
SMART_EXIT_RED = 2           # ≥2 concurrent reversal signs → close ALL remainder
SMART_EXIT_ORANGE = 1        # 1 sign → short warning only, never a close

# ── «مدیریت ویوا» spec §4 (09-20): TF distance ceiling for targets ────────
# The final target may never sit further than this share of price away from
# the entry: 1d 10% · 4h 7% · 1h 5% · 15m 5% (the doc puts 15m on the 1h
# rule). Sub-15m frames follow the 15m ceiling until the owner rules
# otherwise (§13 ambiguity #3 — flagged, never invented). The 3%–5% band of
# the doc is a *choice range*; 5% is the hard ceiling we clamp to.
TARGET_MAX_PCT_BY_TF = {
    "1d": 15.0, "4h": 7.0, "2h": 5.0, "1h": 5.0, "30m": 5.0,
    "15m": 5.0, "5m": 5.0, "3m": 5.0, "1m": 5.0,
}


# Viva 09-20 (round 10, verbatim): «اگر کف و سقف معتبر نبود آن تایم یا تایم
# بالاتر، طبق درصدهای اعلان‌شده مثلا در ۱۵ دقیقه ۳ تا ۵ درصد قیمت در سمت هدف
# مشخص و از نقطه ورود تا آن‌جا به ۵ قسمت» → each trigger TF carries a NORM
# band, not only a ceiling: 15m/1h 3–5% · 4h 5–7% · 1d up to 10% (below 15m
# inherits the 15m band, flagged).
TARGET_BAND_PCT_BY_TF = {
    "1d": (5.0, 15.0), "4h": (5.0, 7.0), "2h": (3.0, 5.0), "1h": (3.0, 5.0),
    "30m": (3.0, 5.0), "15m": (3.0, 5.0), "5m": (3.0, 5.0),
    "3m": (3.0, 5.0), "1m": (3.0, 5.0),
}


def target_distance_cap_pct(trigger_tf: str) -> float:
    """Hard distance ceiling (percent of price) for the FINAL target."""
    return float(TARGET_MAX_PCT_BY_TF.get(str(trigger_tf or "15m").lower(),
                                          TARGET_MAX_PCT_BY_TF["15m"]))


def target_distance_floor_pct(trigger_tf: str) -> float:
    """Minimum distance at which a swing counts as the TF's «کف/سقف معتبر»."""
    return float(TARGET_BAND_PCT_BY_TF.get(str(trigger_tf or "15m").lower(),
                                           TARGET_BAND_PCT_BY_TF["15m"])[0])


# Viva 09-20 round 11 (verbatim): «بدون atr / پشت آخرین سویینگ با بافر» +
# «هم سقف و هم کف ۳ تا ۵ درصد بسته با موقعیت پوزیشن و سقف و کف قبلی» +
# «اگر سطح معتبر در سقف یا کف وجود داشت همان فاصله به ۵ قسمت» → the shared
# doctrine helpers. NO ATR anywhere in a stop or a target path.
STOP_BUFFER_PCT = 0.0010          # 0.10% of price — the «بافر» (never ATR)
LEVEL_MIN_PCT = 0.006             # absolute minimum for a level to count


def structural_buffer(price: float, market: Optional[Dict] = None) -> float:
    """The standard buffer for a stop behind structure: 5 venue ticks or
    0.10% of price — Viva 09-20: «بدون atr … پشت آخرین سویینگ با بافر»."""
    try:
        price = abs(float(price or 0.0))
        if price <= 0:
            return 0.0
        return float(max(5.0 * venue_tick(price, market), price * STOP_BUFFER_PCT))
    except Exception:
        return abs(float(price or 0.0)) * STOP_BUFFER_PCT


# ── Viva 09-21 (round 12, his third ruling, verbatim):
# «استاپ اصلا ساختاری اگر فاصله داشت حذف نشه و تا ۱.۲۵ قیمت نماد محاسبه بشه»
# → a far structural stop NEVER deletes the setup any more; it is pulled to
#   1.25% of the symbol's price.
# «۳ تا ۵ درصد … ۴ تا ۷ … ۷ تا ۱۰ … هم با تلورانس ۲۰ درصد بالایی پایینی سقف و
#   کف های اعلام شده برای تی پی ها اوکیه» → the announced TP band edges carry a
#   ±20% tolerance.
MAX_STOP_PCT = 2.00   # Viva 09-23: the 15m ceiling (legacy bare-call default)

# Viva 09-23 (round 20): TP1 is a HIGH-PROBABILITY TOUCH that arms the
# trailing — never the far end of the path. Per-trigger-TF distance ceiling
# (%) shared by every TP1 source (pattern engine, confirmed ladder).
TP1_CAP_BY_TF: Dict[str, float] = {"1d": 6.0, "4h": 3.5, "2h": 2.5, "1h": 2.0,
                                   "30m": 1.5, "15m": 1.2, "5m": 1.0,
                                   "3m": 1.0, "1m": 1.0}
BAND_TOLERANCE = 0.20

# ── Viva 09-21 (round 14, verbatim): «اون ۱.۲۵ صدم استاپ برای ۱۵ دقیقه است /
# ۱.۷۵ استاپ برای ۱ ساعته / استاپ ۲ تا ۲.۲۵ قیمت نماد در ۴ ساعته / استاپ ۲.۵ تا
# ۲.۷۵ قیمت در سویینگ‌های روزانه. این در صورتی هست که سویینگ ساختاری در چارت
# نداشته باشیم؛ اگر هم کف یا سقف داشته باشیم نباید از این اعداد استاپ با بافرش
# بزرگ‌تر باشه» → the ceiling is PER TIMEFRAME now. A structural swing keeps its
# own place as long as it stays inside the ceiling (+ its buffer); a farther
# swing is CUT at the ceiling («حذف نشه») — never a dropped scenario.
# Viva 09-23 («استاپها خیلی کوچیک و بلافاصله هانت میشه» + «استاپ باید از کف
# بیسِ تایم پایین‌تر دربیاد»): the ceilings widen so an LTF-structural stop
# actually FITS behind the base — the old numbers (1d 2.75%) kept slicing
# real 4h-base stops to a huntable 2.75%. Spot keeps its own 10% cap.
MAX_STOP_PCT_BY_TF = {
    "1m": 1.25, "3m": 1.25, "5m": 1.50, "15m": 2.00,
    "30m": 2.25, "1h": 2.75, "2h": 3.25,
    "4h": 4.50, "1d": 8.00,
}

# Trigger TF → the LOWER timeframe whose BASE defines the stop & TP1 zones.
LTF_BY_TRIGGER = {
    "1d": "4h", "4h": "1h", "2h": "1h", "1h": "15m",
    "30m": "5m", "15m": "5m", "5m": "1m", "3m": "1m", "1m": "1m",
}


def ltf_for_trigger(trigger_tf: str) -> str:
    """The lower timeframe that hosts the entry base / first resistance."""
    return LTF_BY_TRIGGER.get(str(trigger_tf or "").lower(), "15m")


def stop_ceiling_pct(trigger_tf: str) -> float:
    """The stop's hard ceiling for this trigger TF (percent of price)."""
    return float(MAX_STOP_PCT_BY_TF.get(str(trigger_tf or "15m").lower(),
                                        MAX_STOP_PCT_BY_TF["15m"]))


def tolerant_band_for_tf(trigger_tf: str) -> tuple:
    """(floor, cap) with the announced ±20% tolerance applied.

    Used by the CHECKERS (the sanity net and the confirmation gate), never by
    the ladder arithmetic: his tolerance widens what is accepted around the
    announced band — it must not silently move every path.  (Keeping the band
    itself stable is also what keeps the round-9/10/11 path tests honest.)"""
    lo, hi = band_for_tf(trigger_tf)
    return (float(lo) * (1.0 - BAND_TOLERANCE), float(hi) * (1.0 + BAND_TOLERANCE))


def tolerant_cap_pct(trigger_tf: str) -> float:
    return float(target_distance_cap_pct(trigger_tf)) * (1.0 + BAND_TOLERANCE)


def clamp_stop_price(entry: float, direction: str, stop: float,
                     trigger_tf: Optional[str] = None,
                     max_pct: Optional[float] = None) -> tuple:
    """(stop, clamped) — «استاپ … نباید بزرگ‌تر از این اعداد با بافرش باشه».

    Round 14: the ceiling is the trigger TF's own number (15m 1.25% · 1h 1.75% ·
    4h 2.25% · 1d 2.75%). The structural anchor keeps priority while it fits
    inside the ceiling; a farther swing is cut exactly at the ceiling instead of
    dropping the scenario (his VVV ruling). Callers pass the trigger TF; a bare
    call falls back to the 15m number.
    """
    try:
        entry = float(entry or 0.0)
        stop = float(stop or 0.0)
        if max_pct is None:
            max_pct = stop_ceiling_pct(trigger_tf or "")
        if entry <= 0 or stop <= 0 or max_pct <= 0:
            return stop, False
        limit = entry * float(max_pct) / 100.0
        if direction == "LONG":
            floor_stop = entry - limit
            if stop < floor_stop:
                return float(floor_stop), True
            return stop, False
        ceiling_stop = entry + limit
        if stop > ceiling_stop:
            return float(ceiling_stop), True
        return stop, False
    except Exception:
        return stop, False


def band_for_tf(trigger_tf: str) -> tuple:
    """The 3–5% style band of a trigger TF (4h 5–7%, 1d 5–10%)."""
    return TARGET_BAND_PCT_BY_TF.get(str(trigger_tf or "15m").lower(),
                                     TARGET_BAND_PCT_BY_TF["15m"])


def doctrine_path(entry: float, trigger_tf: str, level: float = 0.0,
                  prev_extreme: float = 0.0) -> tuple:
    """(path_distance, source) — the price distance the ladder splits in five.

    1. «اگر سطح معتبر در سقف یا کف وجود داشت همان فاصله به ۵ قسمت» → a level
       inside the TF band sets the path; farther than the ceiling it is capped
       (round-9 rule: a level beyond the ceiling is a different trade); closer
       than the floor it is the next structure, not a target.
    2. otherwise «هم سقف و هم کف ۳ تا ۵ درصد بسته با موقعیت پوزیشن و سقف و کف
       قبلی» → the distance to the PREVIOUS opposite extreme (previous ceiling
       for a long / previous floor for a short) clamped into the TF band — the
       position decides the value inside the band.
    3. no previous extreme at all → the middle of the TF band.
    The stop distance never appears here (his ruling, repeated three times).
    """
    try:
        entry = float(entry or 0.0)
        if entry <= 0:
            return 0.0, "NONE"
        lo_pct, hi_pct = band_for_tf(trigger_tf)
        lo, hi = entry * lo_pct / 100.0, entry * hi_pct / 100.0
        lvl = float(level or 0.0)
        if lvl > 0:
            d = abs(lvl - entry)
            _min_level = max(lo, entry * LEVEL_MIN_PCT)
            if d >= _min_level:
                return (float(min(d, hi)) if hi > 0 else float(d),
                        "STRUCTURE_LEVEL" if d <= hi else "STRUCTURE_LEVEL_CAPPED")
        prev = float(prev_extreme or 0.0)
        if prev > 0:
            d = abs(prev - entry)
            if d > 0:
                return float(min(max(d, lo), hi)), "BAND_FROM_PREVIOUS_EXTREME"
        return float((lo + hi) / 2.0), "BAND_MID"
    except Exception:
        return 0.0, "NONE"


def _swing_highs(df, left: int = 2, right: int = 2) -> list:
    """Fractal swing highs of a frame (high column) — pure, no network."""
    try:
        hi = df["high"].to_numpy(float)
    except Exception:
        return []
    out = []
    for i in range(left, len(hi) - right):
        w = hi[i - left:i + right + 1]
        if hi[i] >= max(w):
            out.append((i, float(hi[i])))
    return out


def ltf_structural_stop(entry: float, direction: str, ltf_df,
                        buffer_pct: float = 0.0010,
                        lookback: int = 12) -> float:
    """Stop = BEHIND the LTF base low/high (Viva 09-23: «استاپ از کف بیس ۴
    ساعته دربیاد»). The base = the lowest low (LONG) / highest high (SHORT) of
    the last `lookback` LTF candles before the break. 0.0 when nothing sane
    comes out (fail-open)."""
    try:
        entry = float(entry or 0.0)
        if entry <= 0 or ltf_df is None or len(ltf_df) < 4:
            return 0.0
        lo = ltf_df["low"].to_numpy(float)[-lookback:]
        hi = ltf_df["high"].to_numpy(float)[-lookback:]
        if str(direction).upper() == "LONG":
            base = float(np.min(lo))
            stop = base * (1.0 - float(buffer_pct))
            return float(stop) if 0 < stop < entry * 0.994 else 0.0
        base = float(np.max(hi))
        stop = base * (1.0 + float(buffer_pct))
        return float(stop) if stop > entry * 1.006 else 0.0
    except Exception:
        return 0.0


def ltf_tp1(entry: float, direction: str, ltf_df, path: float = 0.0,
            cap_pct: float = 6.0, floor_pct: float = 1.2) -> float:
    """TP1 = the NEAREST LTF swing above entry — the high-probability touch
    that arms the trailing stop («تی‌پی یک باید جایی باشه که به احتمال بالا
    تاچ بشه»). No structure → a fraction of the doctrine path, capped by the
    caller's per-TF number. 0.0 when unusable."""
    try:
        entry = float(entry or 0.0)
        if entry <= 0:
            return 0.0
        long = str(direction).upper() == "LONG"
        cands = []
        if ltf_df is not None and len(ltf_df) >= 8:
            for _i, px in _swing_highs(ltf_df):
                if long and px >= entry * (1.0 + floor_pct / 100.0):
                    cands.append(px)
                elif not long and px <= entry * (1.0 - floor_pct / 100.0):
                    cands.append(px)
        hard_cap = entry * (1.0 + cap_pct / 100.0) if long             else entry * (1.0 - cap_pct / 100.0)
        if cands:
            nearest = min(cands, key=lambda v: abs(v - entry))
            return float(min(nearest, hard_cap)) if long else float(max(nearest, hard_cap))
        frac = abs(float(path or 0.0)) * 0.35
        cap_frac = abs(hard_cap - entry)
        d = min(frac, cap_frac) if frac > 0 else cap_frac
        if d < entry * floor_pct / 100.0:
            d = min(entry * floor_pct / 100.0, abs(cap_frac))
        return float(entry + d if long else entry - d)
    except Exception:
        return 0.0


def clamp_path_to_band(entry: float, trigger_tf: str, distance: float) -> tuple:
    """(path_distance, source) — a PROJECTED distance clamped into the TF band.

    Viva 09-21 (round 12): the measured-move projection of a broken pattern is
    not a live level, it is a projection. It keeps its own distance while it
    sits inside the timeframe band, and is pulled to the nearest band edge when
    it does not («هم سقف و هم کف ۳ تا ۵ درصد» — a projection may never drive the
    ladder to a 34% target, DASH 15m).
    """
    try:
        entry = float(entry or 0.0)
        d = float(distance or 0.0)
        if entry <= 0 or d <= 0:
            return 0.0, "NONE"
        lo_pct, hi_pct = band_for_tf(trigger_tf)
        lo, hi = entry * lo_pct / 100.0, entry * hi_pct / 100.0
        if d > hi:
            return float(hi), "MEASURED_CAPPED"
        if d < lo:
            return float(lo), "MEASURED_FLOORED"
        return float(d), "MEASURED"
    except Exception:
        return 0.0, "NONE"


def tf_target_distance(entry: float, trigger_tf: str, structural_level: float = 0.0,
                       direction: str = "LONG", wall_level: float = 0.0) -> float:
    """The path the ladder splits in five (legacy signature, doctrine inside).

    WALL first — a range/channel entry aims at the opposite side («تی‌پی فاصله
    تا سقف کانال یا تریدینگ رنج»), and that distance is honoured even below
    the TF band. Then the round-11 doctrine. Only the TF ceiling may shorten a
    distance; NO ATR and NO stop distance anywhere.
    """
    try:
        entry = float(entry or 0.0)
        if entry <= 0:
            return 0.0
        hi = entry * target_distance_cap_pct(trigger_tf) / 100.0
        wall = float(wall_level or 0.0)
        if wall > 0:
            d = abs(wall - entry)
            if d > 0:
                return float(min(d, hi))
        path, _src = doctrine_path(entry, trigger_tf,
                                   level=float(structural_level or 0.0))
        return float(min(path, hi) if hi > 0 else path)
    except Exception:
        return 0.0


def cap_final_target(entry: float, final_target: float, direction: str,
                     trigger_tf: str) -> tuple[float, bool, float]:
    """Clamp the final target to the TF ceiling — returns (price, capped, cap%).

    «مدیریت ویوا» §4 + §11: targets come from structure, but a structural
    level 19% away on a 15m trade is not a target — it is a different trade.
    The cap keeps the five-segment ladder meaningful (15m: TP1≈1%, TP5=5%).
    """
    try:
        entry = float(entry)
        final = float(final_target or 0)
        if entry <= 0 or final <= 0:
            return float(final_target or 0), False, 0.0
        cap_pct = target_distance_cap_pct(trigger_tf)
        limit = abs(entry) * cap_pct / 100.0
        dist = abs(final - entry)
        if dist <= limit + 1e-12:
            return final, False, cap_pct
        sign = 1.0 if str(direction).upper() == "LONG" else -1.0
        return entry + sign * limit, True, cap_pct
    except Exception:
        return final_target, False, 0.0


def entry_touched(entry: float, candle_high: float, candle_low: float) -> bool:
    """True only when the confirmed limit entry was tradeable in this candle.

    A signal is a scenario, not a filled position.  We deliberately require a
    real OHLC touch and do not infer a fill merely because price later reached
    a stop or target.
    """
    return float(candle_low) <= float(entry) <= float(candle_high)


def venue_tick(price: float, market: Optional[Dict] = None) -> float:
    market = market or {}
    try:
        tick = float(market.get("tick_size") or market.get("price_tick") or 0)
    except (TypeError, ValueError):
        tick = 0.0
    if tick > 0:
        return tick
    p = abs(float(price))
    return 0.1 if p >= 10_000 else (0.01 if p >= 10 else (0.0001 if p >= 1 else (0.00001 if p >= .1 else .000001)))


def build_ladder(entry: float, sl: float, direction: str, market: Optional[Dict] = None,
                 final_target: Optional[float] = None, structural_tp1: Optional[float] = None,
                 fee_pct: float = 0.0, trigger_tf: str = "",
                 wall_level: Optional[float] = None,
                 ltf_df=None, ltf_cap_pct: float = 0.0) -> Dict:
    """Five-pill exit ladder — the ORIGINAL approved tool shape (Viva
    09-19/20 revisit): five equal price segments entry→final, TP1 distance
    exactly as before (no 1R floor), exits 40/30/30 on TP1..TP3, TP4/TP5
    information-only (zero weight).

      • After TP1 the stop moves to NET breakeven (entry plus the round-trip
        fee/slippage allowance — professional point 5), after each later
        target to just beyond the previous target (5 ticks).
      • Between targets a formula-based protection floor trails the stop
        (band_trailing) — adaptive ratios, ratchet-only, never loosens.
      • The position closes when the exit weight is exhausted (TP3) or the
        last segment prints; smart exit can close earlier on RED signs.
    """
    entry, sl = float(entry), float(sl)
    risk = abs(entry - sl)
    if entry <= 0 or risk <= 0:
        raise ValueError("entry/sl must define positive risk")
    sign = 1.0 if str(direction).upper() == "LONG" else -1.0
    tick_gap = 5.0 * venue_tick(entry, market)
    # NET breakeven: BE must clear round-trip cost so a BE exit is truly
    # non-negative, not merely the raw entry price.
    be_gap = max(tick_gap, abs(entry) * max(0.0, float(fee_pct or 0.0)))
    proposed_final = float(final_target or 0)
    valid_final = (proposed_final > entry if sign > 0 else proposed_final < entry)
    if not valid_final:
        # Viva 09-20 round 11: no R-based fallback any more — with no level the
        # path is the TF band (3–5% for 15m/1h, 5–7% for 4h, up to 10% for 1d).
        _fb_path, _ = doctrine_path(entry, str(trigger_tf or "15m"))
        proposed_final = entry + sign * (_fb_path or abs(entry) * 0.04)
    final_price = proposed_final
    # «مدیریت ویوا» §4: the TF distance ceiling clamps the FINAL target, so
    # the five equal segments stay inside a distance this TF can actually
    # travel (a 15m trade may not carry a 19% target).
    _cap_tf = str(trigger_tf or (market or {}).get("trigger_timeframe") or "15m")
    _capped_final, _was_capped, _cap_pct = cap_final_target(entry, final_price, direction, _cap_tf)
    if _was_capped and (abs(_capped_final - entry) > 1e-12):
        final_price = _capped_final
    # ── Viva 09-20 (round 10) — his doctrine, restated verbatim ───────────
    # «فاصله نقطه ورود تا آن‌جا [کف/سقف معتبر] به ۵ قسمت اما خروج در تی‌پی ۱
    # تا ۳» + «اگر کف و سقف معتبر نبود … طبق درصدهای اعلان‌شده … از نقطه ورود
    # تا آن‌جا به ۵ قسمت». So the PATH is a **price distance**, chosen in this
    # order: the opposite wall of the pattern → a valid TF ceiling/floor →
    # the TF norm distance — and it is split into five equal parts. TP1..TP3
    # (40/30/30) exit at 20/40/60% of that path, always BEFORE the wall.
    # The stop never enters this arithmetic (his repeated ruling).
    _path = tf_target_distance(entry, _cap_tf, structural_level=final_price,
                               direction=direction, wall_level=float(wall_level or 0.0))
    if _path <= 0:
        _path = abs(final_price - entry)
    # hard TF ceiling on the path
    _limit = abs(entry) * target_distance_cap_pct(_cap_tf) / 100.0
    if _limit > 0 and _path > _limit:
        _path = _limit
    final_price = entry + sign * _path
    dist = abs(final_price - entry)
    step = _path / 5.0                      # the five-part split
    tp1 = entry + sign * step
    # a structural first level may SNAP the first pill, but only when it is
    # within ±20% of the five-part step (a deeper level is a different trade,
    # and forcing it produced the cramped ladders Viva crossed out).
    _struct_tp1 = float(structural_tp1 or 0.0)
    if _struct_tp1 > 0:
        _before_final = (_struct_tp1 < final_price) if sign > 0 else (_struct_tp1 > final_price)
        _ahead_of_entry = (_struct_tp1 > entry) if sign > 0 else (_struct_tp1 < entry)
        if _before_final and _ahead_of_entry and abs(abs(_struct_tp1 - entry) - step) <= 0.20 * step:
            tp1 = _struct_tp1
    # ── Viva 09-23 (round 20, verbatim): «اگر استاپ و تی‌پی‌ها رو از نواحی
    # تایم پایین‌تر از تایم تریگر در بیاریم خیلی بهتر بشه» + «TP1 = لمسِ
    # پراحتمال». When the lower-TF frame is supplied, the first pill snaps to
    # the NEAREST lower-TF swing (inside the path, at most half of it) — the
    # old ±20%-of-step rule discarded exactly the level a member watches get
    # touched. Fail-open: any problem keeps today's geometry.
    try:
        if ltf_df is not None and len(ltf_df) >= 5:
            _lp = ltf_tp1(entry, direction, ltf_df, path=_path,
                          cap_pct=float(ltf_cap_pct or TP1_CAP_BY_TF.get(_cap_tf, 2.0)))
            _lp_ahead = ((_lp - entry) * sign) > 0
            _lp_before = ((final_price - _lp) * sign) > 0
            _lp_sane = ((_lp - entry) * sign) <= 0.5 * max(_path, 1e-12)
            if _lp > 0 and _lp_ahead and _lp_before and _lp_sane:
                tp1 = float(_lp)
    except Exception:
        pass
    targets = []
    for i in range(5):
        _lv = tp1 + sign * min(step, max(0.4 * step, abs(final_price - tp1) / 4.0)) * i
        if sign > 0:
            _lv = min(_lv, final_price)
        else:
            _lv = max(_lv, final_price)
        targets.append(float(_lv))
    targets[-1] = float(final_price)
    # strictly monotonic pills (duplicates would print the same price twice)
    _dedup = []
    for _lv in targets:
        if not _dedup or abs(_lv - _dedup[-1]) > 1e-12:
            _dedup.append(_lv)
    targets = _dedup
    if len(targets) == 1:
        targets = [float(final_price)]
    _space = min(step, max(0.4 * step, abs(final_price - tp1) / 4.0))
    weights = list(DEFAULT_WEIGHTS)
    if len(targets) < len(weights):
        # a collapsed ladder keeps the FIRST exit weight on its single pill
        weights = weights[:len(targets)]
    if dist <= 1e-12:
        targets = [final_price]
        weights = [100.0]
    # after TP1 stop moves to net BE; afterwards just beyond the prior TP
    trail_stops = [entry + sign * be_gap]
    trail_stops += [targets[n] + sign * tick_gap for n in range(len(targets) - 1)]
    # Protection floors (spec §4, Viva 09-19 adaptive ruling): while price
    # travels from targets[i] toward targets[i+1], the trailing stop may rise
    # but never below this level. Viva 09-21 round 14 (verbatim): «لطفا ارتباطی
    # بین تی پی و استاپ نذار» — the adaptive ratio is measured in LADDER STEPS
    # now (a pure price distance), never in R/risk: the TP path owes nothing to
    # the stop.
    band_floors = []
    band_ks = []
    for i in range(len(targets) - 1):
        prev_lvl = entry if i == 0 else targets[i - 1]
        width_step = abs(targets[i] - prev_lvl) / max(step, 1e-12)
        # half a step → 0.30 · a full step → 0.35 · 1.5 steps → 0.40 · ≥2.5 → 0.50
        k = min(BAND_K_MAX, max(BAND_K_MIN,
                                BAND_K_MIN + BAND_K_SLOPE * (width_step - BAND_K_MID)))
        band_ks.append(k)
        # (targets[i] − prev_lvl) already carries the direction sign.
        band_floors.append(prev_lvl + k * (targets[i] - prev_lvl))
    return {
        "version": 2,
        "direction": str(direction).upper(),
        "entry": entry,
        "original_sl": sl,
        "current_sl": sl,
        "risk": risk,
        "final_target": final_price,
        "tick_gap": tick_gap,
        "be_gap": be_gap,
        "targets": targets,
        "target_r": [abs(t - entry) / risk for t in targets],
        # round 14 audit trail: the same distances as PERCENT of price — the way
        # they are shown to Viva (no R read-out anywhere he can see)
        "target_pct": [abs(t - entry) / max(abs(entry), 1e-12) * 100.0 for t in targets],
        "trail_stops": trail_stops,
        "band_floors": band_floors,
        "band_ks": band_ks,
        "weights": weights,
        "hit_index": 0,
        "realized_r": 0.0,
        "closed": False,
        "band_extreme": None,
        "band_hit_index": 0,
        "floor_announced": 0,
        "warned_band": 0,
        "close_reason": "",
        "exit_reasons_fa": [],
        "structural_tp1": float(structural_tp1 or 0.0),
        # «مدیریت ویوا» §4 audit trail: how far the raw structural target was
        # and whether the TF ceiling clamped it
        "cap_pct": float(_cap_pct),
        "target_capped": bool(_was_capped),
        "raw_final_target": float(proposed_final or 0.0),
        "trigger_tf": str(_cap_tf),
        # round-9 ladder audit: uniform spacing proof (no TP1→TP2 balloon)
        "seg_step": float(step),
        "path_distance": float(_path),
        "path_pct": float(_path / abs(entry) * 100.0),
        "tp_gap": float(_space),
        "tp1_source": "STRUCTURE_SNAP" if _struct_tp1 and abs(tp1 - _struct_tp1) < 1e-12 else "FIVE_PART_SPLIT",
    }


def _window_atr(candles: List[Dict]) -> float:
    """True-range mean over the last ≤14 monitor-TF candles."""
    trs: List[float] = []
    for i in range(1, len(candles)):
        h, l, pc = float(candles[i]["high"]), float(candles[i]["low"]), float(candles[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        trs.append(max(float(candles[0]["high"]) - float(candles[0]["low"]), 1e-12))
    trs = trs[-14:]
    return sum(trs) / len(trs)


def band_trailing(state: Dict, candles: List[Dict], atr_n: Optional[float] = None) -> Dict:
    """Formula-based profit-floor trailing between targets (spec §4/§5).

    Runs on every CLOSED monitor candle once the first target has printed.
    The stop interpolates from its post-TP level toward the band's protection
    floor as price progresses to the next target, may be pushed further by the
    volatility stop (recent swing ∓ n×ATR), and only ever ratchets — in a LONG
    it never moves down, in a SHORT never up (his professional point list:
    «استاپ پله‌ای و غیرقابل‌برگشت»). Updates happen once per closed candle,
    never per tick (professional point 6).

    ``atr_n`` lets the caller scale the volatility stop to the monitor TF
    (n_monitor = n_base × √(trade_tf / monitor_tf)) so a finer candle stream
    does not tighten the stop in absolute terms (Viva 09-19 flexibility
    ruling: formulas adapt to timeframe, target size and symbol price — all
    other components are already R/ATR-relative, hence price-scale-free).
    """
    events: List[Dict] = []
    out = dict(state)
    try:
        if int(out.get("version") or 1) < 2 or out.get("closed") or not candles:
            return {"state": out, "events": events}
        hit = int(out.get("hit_index") or 0)
        targets = [float(t) for t in (out.get("targets") or [])]
        floors = [float(f) for f in (out.get("band_floors") or [])]
        if hit < 1 or hit >= len(targets) or hit - 1 >= len(floors):
            return {"state": out, "events": events}
        entry = float(out["entry"])
        sign = 1.0 if str(out.get("direction") or "LONG").upper() == "LONG" else -1.0
        tick_gap = float(out.get("tick_gap") or 0.0)
        ts = [float(x) for x in (out.get("trail_stops") or [])] or [entry]
        base = ts[min(max(hit - 1, 0), len(ts) - 1)]
        floor = floors[hit - 1]
        if int(out.get("band_hit_index") or 0) != hit:
            out["band_hit_index"] = hit
            out["band_extreme"] = targets[hit - 1]
        extreme = float(out.get("band_extreme") if out.get("band_extreme") is not None else targets[hit - 1])
        last = candles[-1]
        extreme = max(extreme, float(last["high"])) if sign > 0 else min(extreme, float(last["low"]))
        out["band_extreme"] = extreme
        span = targets[hit] - targets[hit - 1]
        if abs(span) <= 1e-12:
            return {"state": out, "events": events}
        p = min(1.0, max(0.0, (extreme - targets[hit - 1]) / span))
        interp = base + p * (floor - base)
        atr = _window_atr(candles)
        n = float(atr_n if atr_n is not None else state.get("vol_atr_n") or VOL_STOP_ATR_N)
        current = float(out.get("current_sl") or base)
        if sign > 0:
            swing = min(float(c["low"]) for c in candles[-SWING_BARS:])
            candidate = max(interp, swing - n * atr)
            new_sl = max(current, candidate)
            improved = new_sl - current > max(tick_gap, 1e-12)
        else:
            swing = max(float(c["high"]) for c in candles[-SWING_BARS:])
            candidate = min(interp, swing + n * atr)
            new_sl = min(current, candidate)
            improved = current - new_sl > max(tick_gap, 1e-12)
        if improved:
            out["current_sl"] = new_sl
        final_sl = float(out.get("current_sl") or base)
        reached = (final_sl >= floor - max(tick_gap, 1e-12)) if sign > 0 \
            else (final_sl <= floor + max(tick_gap, 1e-12))
        if reached and int(out.get("floor_announced") or 0) != hit:
            out["floor_announced"] = hit
            events.append({"event": "PROFIT_FLOOR", "floor": floor, "new_sl": final_sl,
                           "hit_index": hit, "target_index": hit - 1})
    except Exception:
        pass
    return {"state": out, "events": events}


def smart_exit_scan(direction: str, candles: List[Dict], state: Optional[Dict] = None) -> Dict:
    """Reversal-pressure score on the monitor TF (spec §7/§9, Viva 09-19).

    Armed only AFTER the first target prints (profit-protection phase). Each
    independent sign scores +1; ONE sign = ORANGE (short warning, no close),
    TWO or more = RED (close ALL remaining size at that closed candle's
    close, with the explainable reason list) — Viva 09-19/20 ruling: in the
    protection phase signs never stay warn-only. A lone doji/pin never closes
    a position — the small TF is noisy (spec §15.3). Exchange klines carry no
    taker-side split, so selling/buying pressure is proxied by directional
    candles + volume surge + consecutive closes (spec §8 composite, subset).
    """
    out = {"level": "", "score": 0, "reasons": []}
    try:
        if not candles or len(candles) < 21:
            return out
        st = state or {}
        if int(st.get("hit_index") or 0) < 1 or st.get("closed"):
            return out
        c = candles
        o1, h1, l1, cl1, v1 = (float(c[-1][k] or 0) for k in ("open", "high", "low", "close", "volume"))
        o2, cl2 = (float(c[-2][k] or 0) for k in ("open", "close"))
        cl3, cl4, cl5, cl6 = (float(c[-i]["close"] or 0) for i in (3, 4, 5, 6))
        v3, v4, v5, v6 = (float(c[-i]["volume"] or 0) for i in (3, 4, 5, 6))
        rng1 = max(h1 - l1, 1e-12)
        body1 = abs(cl1 - o1)
        vols = [float(x["volume"] or 0) for x in c[-21:-1]]
        avg_vol = (sum(vols) / len(vols)) if vols else 0.0
        dojis = sum(1 for x in c[-3:]
                    if abs(float(x["close"] or 0) - float(x["open"] or 0))
                    <= 0.15 * max(float(x["high"] or 0) - float(x["low"] or 0), 1e-12))
        score = 0
        reasons: List[str] = []
        if str(direction).upper() == "LONG":
            prior = [float(x["low"] or 0) for x in c[-11:-1]]
            if prior and cl1 < min(prior):
                score += 1
                reasons.append("شکست کف ساختاری در تایم مانیتور")
            if cl2 > o2 and cl1 < o1 and o1 >= cl2 and cl1 <= o2 and body1 >= abs(cl2 - o2):
                score += 1
                reasons.append("انگالف نزولی معتبر روی کندل بسته‌شده")
            if (h1 - max(o1, cl1)) >= 2.0 * max(body1, 1e-12) and (cl1 - l1) <= 0.35 * rng1:
                score += 1
                reasons.append("پین‌بار معکوس (شدوی بلند بالا، بستهٔ پایین)")
            if avg_vol > 0 and v1 >= 1.8 * avg_vol and cl1 < o1:
                score += 1
                reasons.append("جهش حجم روی کندل فروش (≥۱٫۸× میانگین ۲۰ کندل)")
            if dojis >= 2 and cl1 - cl6 > 0:
                score += 1
                reasons.append("خوشهٔ دوجی پس از رشد ممتد (بلاتکلیفی در بالا)")
            if cl1 < cl2 < cl3 and (v1 + float(c[-2]["volume"] or 0) + v3) > (v4 + v5 + v6):
                score += 1
                reasons.append("سه بستهٔ نزولی پیاپی با حجم رو به افزایش")
        else:
            prior = [float(x["high"] or 0) for x in c[-11:-1]]
            if prior and cl1 > max(prior):
                score += 1
                reasons.append("شکست سقف ساختاری در تایم مانیتور")
            if cl2 < o2 and cl1 > o1 and o1 <= cl2 and cl1 >= o2 and body1 >= abs(cl2 - o2):
                score += 1
                reasons.append("انگالف صعودی معتبر روی کندل بسته‌شده")
            if (min(o1, cl1) - l1) >= 2.0 * max(body1, 1e-12) and (h1 - cl1) <= 0.35 * rng1:
                score += 1
                reasons.append("پین‌بار معکوس (شدوی بلند پایین، بستهٔ بالا)")
            if avg_vol > 0 and v1 >= 1.8 * avg_vol and cl1 > o1:
                score += 1
                reasons.append("جهش حجم روی کندل خرید (≥۱٫۸× میانگین ۲۰ کندل)")
            if dojis >= 2 and cl1 - cl6 < 0:
                score += 1
                reasons.append("خوشهٔ دوجی پس از ریزش ممتد (بلاتکلیفی در پایین)")
            if cl1 > cl2 > cl3 and (v1 + float(c[-2]["volume"] or 0) + v3) > (v4 + v5 + v6):
                score += 1
                reasons.append("سه بستهٔ صعودی پیاپی با حجم رو به افزایش")
        out["score"] = score
        out["reasons"] = reasons
        # Viva 09-20 (round 9): «اولین پین‌بارِ بسته‌شدهٔ معکوس ... = خروج
        # فوری باقی‌مانده» — the flag lets the monitor treat ONE closed
        # reverse pin as a red exit on its own, not merely an orange sign.
        out["reverse_pin"] = any("پین‌بار" in str(_r) for _r in reasons)
        out["level"] = "RED" if score >= SMART_EXIT_RED else ("ORANGE" if score >= SMART_EXIT_ORANGE else "")
    except Exception:
        pass
    return out


def reentry_setup(direction: str, candles: List[Dict], state: Dict,
                  atr: float = 0.0) -> Optional[Dict]:
    """Viva 09-20 (round 9) — re-entry after a protected profit exit.

    Verbatim: «اگر قیمت فقط یک پول‌بک بود، سیگنال ورود مجدد روی همان
    پول‌بک داده بشه؛ سود اولیه باید گرفته بشه و قفل بشه.» So after TP1 was
    banked (stop already at net-BE) and the remainder was closed by the
    protection rules, a PULLBACK back to the first-target area that holds
    with a confirmation candle is a fresh entry — the banked profit stays
    locked (the re-entry never risks below the original protected stop).

    Returns None unless: the position was closed by SMART_EXIT during the
    TP1→TP2 range, price pulled back to TP1's area, and the closed candle in
    the trade's direction confirms (pin/engulf or a clean directional close).
    """
    try:
        st = state or {}
        if not st.get("closed") or str(st.get("close_reason") or "") != "SMART_EXIT":
            return None
        if int(st.get("hit_index") or 0) < 1 or st.get("reentry_signaled"):
            return None
        if not candles or len(candles) < 6:
            return None
        targets = [float(t) for t in (st.get("targets") or [])]
        hit = int(st.get("hit_index") or 0)
        if hit >= len(targets):
            return None
        tp1 = targets[hit - 1]
        band_lo, band_hi = sorted((tp1, targets[hit]))     # TP1 → next pill band
        span = max(band_hi - band_lo, 1e-12)
        c = candles
        last = c[-1]
        close = float(last["close"] or 0)
        long_side = str(direction).upper() == "LONG"
        # price must be back at the banked first target's area (a pullback),
        # not far beyond the exit and not crashed through the original stop
        if long_side:
            if not (tp1 - 0.5 * span <= close <= tp1 + 0.35 * span):
                return None
        else:
            if not (tp1 - 0.35 * span <= close <= tp1 + 0.5 * span):
                return None
        o, h, l = float(last["open"] or 0), float(last["high"] or 0), float(last["low"] or 0)
        body = abs(close - o)
        rng = max(h - l, 1e-12)
        o2, c2 = float(c[-2]["open"] or 0), float(c[-2]["close"] or 0)
        _pin = ((min(o, close) - l) >= 2.0 * max(body, 1e-12) and (h - close) <= 0.35 * rng) \
            if long_side else \
            ((h - max(o, close)) >= 2.0 * max(body, 1e-12) and (close - l) <= 0.35 * rng)
        _engulf = (c2 < o2 and close > o and o <= c2 and close >= o2) if long_side else \
            (c2 > o2 and close < o and o >= c2 and close <= o2)
        _clean = (close > o and close > c2) if long_side else (close < o and close < c2)
        if not (_pin or _engulf or _clean):
            return None
        _buf = max(0.35 * float(atr or 0), 0.0015 * close)
        if long_side:
            swing = min(float(x["low"] or 0) for x in c[-6:])
            sl = swing - _buf
            later = [t for t in targets[hit:] if t > close + 0.25 * span]
        else:
            swing = max(float(x["high"] or 0) for x in c[-6:])
            sl = swing + _buf
            later = [t for t in targets[hit:] if t < close - 0.25 * span]
        return {
            "entry": close,
            "sl": float(sl),
            "tp1": float(later[0]) if later else float(band_hi if long_side else band_lo),
            "tp2": float(later[-1]) if later else float(band_hi if long_side else band_lo),
            "kind": "REENTRY_PULLBACK",
            "note_fa": ("پول‌بک به ناحیهٔ هدف اول با تأیید کندل بسته‌شده؛ ورود مجدد "
                        "با استاپ پشت سوینگ پول‌بک — سود اولیه در حساب قفل می‌ماند."),
        }
    except Exception:
        return None


def advance_ladder(state: Dict, high: float, low: float) -> Dict:
    """Advance on one *closed* candle.

    Conservative ordering: when current stop and next target coexist in one
    candle, stop is assumed first. This avoids optimistic backtests.
    """
    out = dict(state)
    out["targets"] = list(state["targets"])
    out["weights"] = list(state["weights"])
    out["trail_stops"] = list(state["trail_stops"])
    out["target_r"] = list(state.get("target_r") or [abs(t - out["entry"]) / out["risk"] for t in out["targets"]])
    events: List[Dict] = []
    if out.get("closed"):
        return {"state": out, "events": events}
    direction = out["direction"]
    stop = float(out["current_sl"])
    stop_hit = low <= stop if direction == "LONG" else high >= stop
    if stop_hit:
        remaining = 100.0 - sum(out["weights"][:int(out["hit_index"])])
        stop_r = ((stop - out["entry"]) / out["risk"]) if direction == "LONG" else ((out["entry"] - stop) / out["risk"])
        out["realized_r"] = float(out["realized_r"]) + stop_r * remaining / 100.0
        out["closed"] = True
        events.append({"event": "TRAIL_STOP" if out["hit_index"] else "STOP", "stop": stop, "realized_r": out["realized_r"]})
        return {"state": out, "events": events}

    idx = int(out["hit_index"])
    while idx < len(out["targets"]):
        target = float(out["targets"][idx])
        hit = high >= target if direction == "LONG" else low <= target
        if not hit:
            break
        weight = float(out["weights"][idx])
        out["realized_r"] = float(out["realized_r"]) + float(out["target_r"][idx]) * weight / 100.0
        out["current_sl"] = float(out["trail_stops"][idx])
        idx += 1
        out["hit_index"] = idx
        events.append({"event": f"TP{idx}", "target": target, "weight": weight, "new_sl": out["current_sl"]})
        # Viva 09-19/20 + «مدیریت ویوا» §5: exits end at TP3 (40/30/30).
        # A zero-weight INFO pill is not an exit level — once the weight is
        # exhausted the position closes on this candle, even when the same
        # candle also prints the later informational pills (with the 09-20
        # TF ceiling the five pills sit close together, so this matters).
        if (100.0 - sum(float(w) for w in out["weights"][:idx])) <= 1e-9:
            break
    if idx >= len(out["targets"]):
        out["closed"] = True
        events.append({"event": "LADDER_COMPLETE", "realized_r": out["realized_r"]})
    elif (100.0 - sum(float(w) for w in out["weights"][:idx])) <= 1e-9:
        # Viva 09-19/20: exits end at TP3 (40/30/30) — zero-weight TP4/TP5 are
        # information pills, so the position closes once weight is exhausted.
        out["closed"] = True
        events.append({"event": "LADDER_COMPLETE", "realized_r": out["realized_r"]})
    return {"state": out, "events": events}
