"""Deterministic multi-target and trailing-stop lifecycle primitives.

This module has no database or Telegram dependency so every fill rule is unit
 testable before it is wired into the live monitor.
"""
from __future__ import annotations
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
                 fee_pct: float = 0.0) -> Dict:
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
    final_price = proposed_final if valid_final else entry + sign * risk * 3
    dist = abs(final_price - entry)
    # Viva 09-19/20: five equal segments entry→final — the ORIGINAL approved
    # tool shape; TP1 distance exactly as before (structural share of the
    # path, no forced 1R). TP4/TP5 carry zero exit weight (INFO pills).
    targets = [entry + (final_price - entry) * i / 5.0 for i in range(1, 6)]
    weights = list(DEFAULT_WEIGHTS)
    if dist <= 1e-12:
        targets = [final_price]
        weights = [100.0]
    # after TP1 stop moves to net BE; afterwards just beyond the prior TP
    trail_stops = [entry + sign * be_gap]
    trail_stops += [targets[n] + sign * tick_gap for n in range(len(targets) - 1)]
    # Protection floors (spec §4, Viva 09-19 adaptive ruling): while price
    # travels from targets[i] toward targets[i+1], the trailing stop may rise
    # but never below this level. The ratio k adapts to the band's width in R
    # (wider band = more profit at risk = larger protected share).
    band_floors = []
    band_ks = []
    for i in range(len(targets) - 1):
        prev_lvl = entry if i == 0 else targets[i - 1]
        width_r = abs(targets[i] - prev_lvl) / risk
        # 0.5R band → 0.30 · 1R → 0.35 · 1.5R → 0.40 · ≥2.5R → 0.50
        k = min(BAND_K_MAX, max(BAND_K_MIN,
                                BAND_K_MIN + BAND_K_SLOPE * (width_r - BAND_K_MID)))
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
        out["level"] = "RED" if score >= SMART_EXIT_RED else ("ORANGE" if score >= SMART_EXIT_ORANGE else "")
    except Exception:
        pass
    return out


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
    if idx >= len(out["targets"]):
        out["closed"] = True
        events.append({"event": "LADDER_COMPLETE", "realized_r": out["realized_r"]})
    elif (100.0 - sum(float(w) for w in out["weights"][:idx])) <= 1e-9:
        # Viva 09-19/20: exits end at TP3 (40/30/30) — zero-weight TP4/TP5 are
        # information pills, so the position closes once weight is exhausted.
        out["closed"] = True
        events.append({"event": "LADDER_COMPLETE", "realized_r": out["realized_r"]})
    return {"state": out, "events": events}
