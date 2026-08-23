"""Experimental detectors under R&D evaluation (not wired into live scanning).

P1234 — classic 1-2-3-4 reversal (Ross-style), adapted to the v7 candidate
framework (alert on structure break -> first POI retest -> closed-candle trigger).

Bullish sequence (SHORT mirrors it):
  Point 1: the low of a completed down-move (last pivot low of the leg)
  Point 2: the high of the upward correction
  Point 3: a higher low that fails to break Point 1
  Point 4: price closes above Point 2  => structural trigger level
Candidate POI is the broken Point-2 level (flip zone); entry still waits for
the first retest and a closed-candle confirmation, so the pattern plugs into
the existing lifecycle unchanged. Invalidation is handled by the engine's
liquidity-protected logic, which anchors beyond Point 3 when nearby.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from analysis.indicators import adx, atr, structure_bias
from analysis.models import EvidenceItem, SignalCandidate, generate_viva_public_code
from config import get_settings
from analysis.setups_v7 import (
    SETUP_NAMES,
    SETUP_NAMES_FA,
    _base_candidate,
    _direction,
    _ensure_frames,
    _liquidity_protected_invalidation,
    _structural_targets,
    confirm_timeframe,
    timeframe_profile,
    pivots,
)
from data.fetcher import MarketBundle

SETUP_NAMES["P1234"] = "1-2-3-4 Reversal + Point-2 Break Retest"
SETUP_NAMES_FA["P1234"] = "الگوی برگشتی ۱-۲-۳-۴ و اولین پولبک به نقطه ۲"
SETUP_NAMES["ALBROX"] = "ALBROX Spike Reclaim + Base + Pinbar"
SETUP_NAMES_FA["ALBROX"] = "ALBROX | اسپایک، بازپس‌گیری، بیس و پین‌بار"


def _find_1234(df, direction: str) -> Optional[dict]:
    ph, pl = pivots(df, 3, 3)
    atr_now = float((df["high"] - df["low"]).tail(14).mean())
    if atr_now <= 0:
        return None
    highs_needed, lows_needed = (2, 3) if direction == "SHORT" else (3, 2)
    if len(ph) < highs_needed or len(pl) < lows_needed:
        return None
    fresh_from = max(0, len(df) - 90)  # only freshly completed patterns matter

    if direction == "LONG":
        outer, inner = pl, ph  # p1/p3 are lows, p2 is the correction high
        order_ok = lambda p1, p2, p3: p1["price"] < p3["price"] < p2["price"]
        height_of = lambda p1, p2: p2["price"] - p1["price"]
        retrace_of = lambda p1, p2, p3: (p3["price"] - p1["price"]) / max(height_of(p1, p2), 1e-12)
        broken = lambda close, lvl, a: close > lvl + 0.05 * a
    else:
        outer, inner = ph, pl
        order_ok = lambda p1, p2, p3: p2["price"] < p3["price"] < p1["price"]
        height_of = lambda p1, p2: p1["price"] - p2["price"]
        retrace_of = lambda p1, p2, p3: (p1["price"] - p3["price"]) / max(height_of(p1, p2), 1e-12)
        broken = lambda close, lvl, a: close < lvl - 0.05 * a

    for p3 in reversed(outer[-3:]):
        if p3["index"] < fresh_from:
            continue  # stale structure; the market has moved on
        middles = [p for p in inner if p["index"] < p3["index"]]
        if not middles:
            continue
        p2 = middles[-1]
        firsts = [p for p in outer if p["index"] < p2["index"]]
        if not firsts:
            continue
        p1 = firsts[-1]
        height = height_of(p1, p2)
        if height < 0.8 * atr_now:
            continue
        if not order_ok(p1, p2, p3):
            continue
        ratio = retrace_of(p1, p2, p3)
        if not (0.05 <= ratio <= 0.70):
            continue
        level = float(p2["price"])
        for i in range(p3["index"] + 1, len(df)):
            if broken(float(df["close"].iloc[i]), level, atr_now):
                touches = sum(
                    1 for j in range(i + 1, len(df))
                    if float(df["low"].iloc[j]) <= level + 0.18 * atr_now
                    and float(df["high"].iloc[j]) >= level - 0.18 * atr_now
                )
                if touches > 0:
                    break  # mitigated; search an older triple instead
                return {
                    "p1": p1, "p2": p2, "p3": p3, "break_index": i,
                    "level": level, "height": height, "ratio": ratio,
                }
    return None


def detect_pattern_1234(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    context_tf, middle_tf, trigger_tf = timeframe_profile(style)
    if not _ensure_frames(bundle, (context_tf, middle_tf, trigger_tf)):
        return None
    context = structure_bias(bundle.get(context_tf), 5)
    if context["bias"] not in ("BULLISH", "BEARISH"):
        return None
    direction = _direction(context["bias"])
    trigger_df = bundle.get(trigger_tf)
    found = _find_1234(trigger_df, direction)
    if not found:
        return None
    # Optional regime filter: reversal patterns need directional energy, not chop.
    settings = get_settings()
    min_adx = float(getattr(settings, "p1234_min_adx", 0.0) or 0.0)
    if min_adx > 0:
        adx_now = float(adx(trigger_df, 14).iloc[-1])
        if not np.isfinite(adx_now) or adx_now < min_adx:
            return None
    atr_now = float((trigger_df["high"] - trigger_df["low"]).tail(14).mean())
    level = found["level"]
    poi = {
        "bottom": level - 0.18 * atr_now,
        "top": level + 0.18 * atr_now,
        "touches": 0,
        "type": "P1234 POINT-2 FLIP",
    }
    p1, p3 = found["p1"], found["p3"]
    detail = (
        f"ساختار برگشتی ۱-۲-۳-۴ کامل شد: نقطه ۱ در {p1['price']:.4f}، نقطه ۲ (سقف/کف اصلاح) در {level:.4f} "
        f"و نقطه ۳ در {p3['price']:.4f} که نتوانست نقطه ۱ را بشکند. قیمت سطح نقطه ۲ را با Close شکسته است؛ "
        f"ورود فقط پس از اولین بازگشت به سطح شکسته و تشکیل کندل تأیید بررسی می‌شود."
    )
    special = EvidenceItem(
        "p1234", "الگوی ۱-۲-۳-۴ و شکست نقطه ۲", detail, True, 2,
        level=level, timeframe=trigger_tf,
    )
    impulse = {
        "index": found["break_index"],
        "level": level,
        "valid": True,
        "direction": context["bias"],
        "body_atr": 0.8,
        "volume_ratio": 1.0,
    }
    candidate = _base_candidate(
        bundle, style, "P1234", direction, context_tf, trigger_tf, context, poi, impulse,
        special, "p1234_break", True,
    )
    if candidate:
        candidate.metadata.update({
            "p1234_p1": float(p1["price"]),
            "p1234_p2": level,
            "p1234_p3": float(p3["price"]),
            "p1234_ratio": round(float(found["ratio"]), 3),
        })
    return candidate


# ---------------------------------------------------------------------------
# TLBREAK — channel/trendline breakout (CryptoCove-style)
#
# LONG: descending resistance line through the two most recent pivot HIGHS of
# the context TF (each lower than the previous). A candidate is created while
# price is NEAR the line (pre-break watch) or has JUST closed through it. The
# entry zone hugs the broken line, so the engine's own lifecycle yields exactly
# the two alerts the style calls for:
#   1. "approaching" alert when price nears the line (نزدیک به شکست)
#   2. confirmation when a candle CLOSES beyond the zone (شکست معتبر با Close)
# Targets are measured-move fractions of the channel height (TP1 = 45%,
# TP2 = 70% of the height), per the "smaller, higher-probability targets"
# directive. SHORT mirrors it on an ascending support line through pivot lows.
# ---------------------------------------------------------------------------


def _fit_channel_line(df, direction: str) -> Optional[dict]:
    """Active trendline + parallel channel bound from context-TF pivots."""
    ph, pl = pivots(df, 3, 3)
    n = len(df)
    if n < 60:
        return None
    atr_now = float((df["high"] - df["low"]).tail(14).mean())
    if atr_now <= 0:
        return None
    pts = ph if direction == "LONG" else pl
    if len(pts) < 2:
        return None
    a, b = pts[-2], pts[-1]
    if b["index"] - a["index"] < 8:
        return None  # line flanks too close together = local noise
    if direction == "LONG" and not (b["price"] < a["price"]):
        return None  # resistance must be descending
    if direction == "SHORT" and not (b["price"] > a["price"]):
        return None  # support must be ascending
    slope = (b["price"] - a["price"]) / (b["index"] - a["index"])

    def line_at(i: float) -> float:
        return b["price"] + slope * (i - b["index"])

    touches = sum(
        1 for p in pts[:-2]
        if abs(p["price"] - line_at(p["index"])) <= 0.35 * atr_now
    )
    opp = pl if direction == "LONG" else ph
    window = [p for p in opp if p["index"] > a["index"]]
    if not window:
        return None
    anchor = (min if direction == "LONG" else max)(window, key=lambda p: p["price"])

    def bound_at(i: float) -> float:
        return anchor["price"] + slope * (i - anchor["index"])

    height = (line_at(n - 1) - bound_at(n - 1)) if direction == "LONG" else (bound_at(n - 1) - line_at(n - 1))
    if height < 1.5 * atr_now or height > 25 * atr_now:
        return None  # meaningless width or crossed/wrong fit
    return {
        "a": a, "b": b, "anchor": anchor, "slope": slope,
        "line_now": line_at(n - 1), "line_prev": line_at(n - 2),
        "bound_now": bound_at(n - 1), "height": height,
        "touches": touches, "atr": atr_now,
    }


def _intrabar_base(bundle: MarketBundle, context_df, trigger_tf: str, direction: str) -> Optional[dict]:
    """Entry base INSIDE the break candle, per Viva's model.

    A strong context-candle breakout (e.g. 1D green candle through the line)
    contains a lower-TF base (consolidation) in its first portion; price
    explodes from that base and, on pullback, usually revisits the BASE — not
    the broken line. The entry zone is that base cluster on the trigger TF.
    """
    trigger_df = bundle.get(trigger_tf)
    if trigger_df is None or len(trigger_df) < 6:
        return None
    candle_open_ts = context_df["timestamp"].iloc[-1]
    inside = trigger_df[trigger_df["timestamp"] >= candle_open_ts]
    if len(inside) < 3:
        # fall back: lower (LONG) / upper (SHORT) 30% of the break candle range
        row = context_df.iloc[-1]
        lo, hi = float(row["low"]), float(row["high"])
        if direction == "LONG":
            return {"bottom": lo, "top": lo + 0.30 * (hi - lo), "kind": "FALLBACK_WICK"}
        return {"bottom": hi - 0.30 * (hi - lo), "top": hi, "kind": "FALLBACK_WICK"}
    n_in = len(inside)
    head = inside.iloc[: max(2, int(n_in * 0.6))]  # consolidation portion before the thrust
    lo = float(head["low"].min())
    hi = float(head["high"].max())
    atr_t = float((trigger_df["high"] - trigger_df["low"]).tail(14).mean())
    if atr_t <= 0 or hi - lo <= 0:
        return None
    if hi - lo > 1.6 * atr_t:
        # consolidation too wide to be a base; take the cluster around the
        # densest body region instead
        body_mid = (head["open"] + head["close"]) / 2.0
        center = float(body_mid.median())
        lo, hi = center - 0.5 * atr_t, center + 0.5 * atr_t
    return {"bottom": lo, "top": hi, "kind": "INTRABAR_BASE", "bars": n_in}


def detect_viva_tlbreak(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    """Live-paper adapter for isolated Viva-TLBREAK v1.

    Existing strategies are untouched. This creates a WATCH candidate only
    after validated geometry and a closed trigger breakout; generic lifecycle
    then waits for the configured retest/5M confirmation.
    """
    from analysis.viva_tlbreak import (
        build_pattern_plan, classify_pattern, classify_pattern_detailed, fit_validated_line, fit_two_pivot_watch,
        assess_projected_breakout, score_confluences, structure_score,
        pattern_length_ok, pattern_geometry_ok, recent_failed_breakout_penalty,
    )
    structure_tf, refine_tf, trigger_tf = timeframe_profile(style)
    if not _ensure_frames(bundle, (structure_tf, refine_tf, trigger_tf)):
        return None
    structure_df, refine_df, trigger_df = bundle.get(structure_tf), bundle.get(refine_tf), bundle.get(trigger_tf)
    upper = fit_validated_line(refine_df, "HIGH")
    lower = fit_validated_line(refine_df, "LOW")
    if upper is None and lower is None:
        # Two-pivot preview: visible chart watch only, never lifecycle/entry.
        for direction, side in (("LONG", "HIGH"), ("SHORT", "LOW")):
            watch = fit_two_pivot_watch(refine_df, side)
            if watch is None:
                continue
            line_price = watch.price_at(len(refine_df) - 1)
            atr_watch = float((trigger_df["high"] - trigger_df["low"]).tail(14).mean())
            if atr_watch <= 0:
                continue
            candidate = SignalCandidate(
                signal_id=f"viva-vtlwatch-{bundle.symbol}-{trigger_tf}-{str(trigger_df['timestamp'].iloc[-1])[:16]}",
                symbol=bundle.symbol, style=str(style).upper(), setup_code="TLBREAK",
                setup_name="VIVA TLBREAK 2-Pivot Watch", strategy_fa="VIVA-TLBREAK | خط دوپیوتی در انتظار اعتبار", direction=direction,
                score=6, status="EDUCATIONAL", entry_zone_bottom=line_price-.15*atr_watch,
                entry_zone_top=line_price+.15*atr_watch, planned_entry=float(trigger_df['close'].iloc[-1]),
                sl=float(trigger_df['low'].iloc[-1] if direction=="LONG" else trigger_df['high'].iloc[-1]),
                tp1=0.0, tp2=0.0, rr_tp1=0.0, rr_tp2=0.0,
                bias="BULLISH" if direction=="LONG" else "BEARISH", trigger_timeframe=trigger_tf,
                mandatory_gates={"viva_watch_only": False},
            )
            candidate.metadata.update({"strategy_variant":"VIVA_TLBREAK","viva_state":"S0_WATCH","viva_pattern":"TWO_PIVOT_WATCH","viva_watch_line":line_price,"viva_touch_count":2,"viva_watch_points":[dict(watch.first),dict(watch.last)],"public_code":generate_viva_public_code("TLBREAK", style)})
            return candidate
        return None
    atr_t = float((trigger_df["high"] - trigger_df["low"]).tail(14).mean())
    if atr_t <= 0:
        return None
    for direction, line in (("LONG", upper), ("SHORT", lower)):
        if line is None:
            continue
        breakout = assess_projected_breakout(trigger_df, line, direction)
        if breakout is None or not breakout.passed:
            continue
        geometry_ok, _geometry_pattern = pattern_geometry_ok(upper, lower, len(refine_df) - 1)
        pattern = classify_pattern_detailed(upper, lower, len(refine_df) - 1)
        if not geometry_ok or not pattern_length_ok(line, style):
            continue
        failed_penalty = recent_failed_breakout_penalty(trigger_df, line, direction)
        plan = build_pattern_plan(refine_df, upper, lower, direction)
        if plan is None:
            continue
        poi = {"bottom": breakout.line_price - .15 * atr_t, "top": breakout.line_price + .15 * atr_t, "touches": 0, "type": f"VIVA {pattern} BREAK/RETEST"}
        bias = structure_bias(structure_df, 5)
        context = {"bias": bias.get("bias", "NEUTRAL")}
        special = EvidenceItem("viva_tlbreak", "VIVA-TLBREAK شکست ساختاری", f"{pattern} با {line.touch_count} پیوت تاییدشده و خطای فیت {line.fit_residual_atr:.2f} ATR؛ کلوز شکست {breakout.beyond_atr:.2f} ATR بیرون خط است.", True, 2, level=breakout.line_price, timeframe=refine_tf)
        impulse = {"index": len(trigger_df)-1, "level": breakout.line_price, "valid": True, "direction": "BULLISH" if direction=="LONG" else "BEARISH", "body_atr": breakout.body_atr, "volume_ratio": 1.0}
        candidate = _base_candidate(bundle, style, "TLBREAK", direction, structure_tf, trigger_tf, context, poi, impulse, special, "viva_tlbreak_geometry", True)
        if candidate is None:
            continue
        confluence = score_confluences(structure_df, refine_df, trigger_df, direction, retest_score=0.0)
        # VIVA-TLBREAK owns its score/geometry; generic candidate values are
        # replaced only for this isolated strategy.
        viva_score = structure_score(line) + breakout.score + confluence.total + failed_penalty
        refine_atr = float((refine_df["high"] - refine_df["low"]).tail(14).mean())
        buffer = max(0.35 * refine_atr, abs(candidate.planned_entry) * 0.0005)
        pattern_sl = plan.stop_anchor - buffer if direction == "LONG" else plan.stop_anchor + buffer
        # Never move a structural stop inside the generic liquidity protected stop.
        candidate.sl = min(candidate.sl, pattern_sl) if direction == "LONG" else max(candidate.sl, pattern_sl)
        final_target = plan.structural_target or plan.measured_target
        if (direction == "LONG" and final_target <= candidate.planned_entry) or (direction == "SHORT" and final_target >= candidate.planned_entry):
            continue
        risk = abs(candidate.planned_entry - candidate.sl)
        rr_final = abs(final_target - candidate.planned_entry) / max(risk, 1e-12)
        if rr_final < 1.5:
            continue
        candidate.tp2 = float(final_target)
        candidate.tp1 = float(candidate.planned_entry + (final_target - candidate.planned_entry) * 0.40)
        candidate.rr_tp1 = abs(candidate.tp1 - candidate.planned_entry) / max(risk, 1e-12)
        candidate.rr_tp2 = rr_final
        candidate.score = min(10, max(0, round(viva_score)))
        # Counter trend is allowed only after the lifecycle gets full retest/BOS.
        candidate.mandatory_gates["htf_alignment"] = True  # counter-trend is enforced by retest/BOS lifecycle, not a dead gate
        candidate.mandatory_gates["viva_tlbreak_geometry"] = True
        candidate.strategy_fa = f"VIVA-TLBREAK | شکست {pattern} در انتظار Retest و BOS پنج‌دقیقه"
        from analysis.viva_tlbreak_state import VivaTLState
        candidate.metadata.update({
            "strategy_variant": "VIVA_TLBREAK",
            "viva_state_machine": VivaTLState(stage="S2_BREAKOUT").payload(),
            "viva_retest_window_bars": 24 if str(style).upper() == "SWING" else 16,
            "viva_pattern": pattern,
            "viva_touch_count": line.touch_count, "viva_fit_error_atr": line.fit_residual_atr,
            "viva_break_line": breakout.line_price, "viva_breakout_score": breakout.score,
            "viva_breakout_body_atr": breakout.body_atr, "viva_counter_trend": confluence.counter_trend,
            "viva_confluence_score": confluence.total, "viva_confluence": list(confluence.reasons),
            "viva_structure_score": structure_score(line), "viva_failed_breakout_penalty": failed_penalty,
            "viva_final_score": viva_score,
            "viva_stop_anchor": plan.stop_anchor, "viva_measured_target": plan.measured_target,
            "viva_final_target": final_target,
            "viva_structural_target": plan.structural_target, "viva_state": "S2_BREAKOUT_CLOSED",
            "tl_context_tf": refine_tf, "tl_pattern": pattern, "tl_pattern_fa": pattern,
            "tl_line": breakout.line_price, "tl_touches": line.touch_count,
            "viva_upper_points": [dict(p) for p in (upper.points if upper else ())],
            "viva_lower_points": [dict(p) for p in (lower.points if lower else ())],
            "viva_breakout_line": breakout.line_price,
            "viva_retest_zone": [poi["bottom"], poi["top"]],
        })
        return candidate
    return None


def detect_trendline_breakout(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    settings = get_settings()
    if getattr(settings, "viva_tlbreak_enabled", False):
        return detect_viva_tlbreak(bundle, style)
    override_tf = (getattr(settings, "tlbreak_context_tf", "") or "").strip()
    context_tf, _middle_tf, trigger_tf = timeframe_profile(style)
    context_tf = override_tf or context_tf
    if not _ensure_frames(bundle, (context_tf, trigger_tf)):
        return None
    context_df = bundle.get(context_tf)
    last_close = float(context_df["close"].iloc[-1])
    prev_close = float(context_df["close"].iloc[-2])
    last_open = float(context_df["open"].iloc[-1])

    for direction in ("LONG", "SHORT"):
        if getattr(settings, "viva_tlbreak_enabled", False):
            from analysis.viva_tlbreak import fit_viva_breakout_line
            fit = fit_viva_breakout_line(context_df, direction)
        else:
            fit = _fit_channel_line(context_df, direction)
        if not fit:
            continue
        atr_c = fit["atr"]
        line_now = fit["line_now"]
        # distance from line in ATR units (positive = still below resistance / above support)
        dist = (line_now - last_close) / atr_c if direction == "LONG" else (last_close - line_now) / atr_c
        if not (-0.90 < dist < 0.60):
            continue  # far from the line: neither a watch nor a fresh break
        if dist < 0:
            # already beyond the line: only accept a FRESH break (previous close
            # was still on the inner side) and a decisive break candle
            prev_dist = (fit["line_prev"] - prev_close) / atr_c if direction == "LONG" else (prev_close - fit["line_prev"]) / atr_c
            if prev_dist < -0.35:
                continue  # stale break, market already left
            body = (last_close - last_open) if direction == "LONG" else (last_open - last_close)
            if body < 0.25 * atr_c:
                continue  # drifted through the line; no conviction candle
            stage = "JUST_BROKE"
        else:
            stage = "PRE_BREAK"

        min_adx = float(getattr(settings, "tlbreak_min_adx", 0.0) or 0.0)
        if min_adx > 0:
            adx_now = float(adx(context_df, 14).iloc[-1])
            if not np.isfinite(adx_now) or adx_now < min_adx:
                continue

        # --- entry zone ---
        if stage == "JUST_BROKE":
            # Viva's model: no full pullback to the line is expected — price
            # revisits the intra-candle BASE, then leaves. Targets = first
            # opposing structural zone (engine's structural targets).
            base = _intrabar_base(bundle, context_df, trigger_tf, direction)
            if not base:
                continue
            zb, zt = float(base["bottom"]), float(base["top"])
            trigger_df = bundle.get(trigger_tf)
            atr_t = float((trigger_df["high"] - trigger_df["low"]).tail(14).mean())
            extension = (last_close - zt) if direction == "LONG" else (zb - last_close)
            if extension > 2.5 * atr_t:
                continue  # too far above the base; pullback expectancy gone
            poi_type = f"INTRA-BREAK BASE ({base['kind']})"
        else:
            # PRE_BREAK watch candidate: zone hugs the line; the trigger-candle
            # close past the zone mid IS the valid breakout close.
            if direction == "LONG":
                zb, zt = line_now - 0.10 * atr_c, line_now + 0.18 * atr_c
            else:
                zb, zt = line_now - 0.18 * atr_c, line_now + 0.10 * atr_c
            poi_type = "TRENDLINE BREAK WATCH (line zone)"
        poi = {"bottom": zb, "top": zt, "touches": 0, "type": poi_type}
        bias = "BULLISH" if direction == "LONG" else "BEARISH"
        context = {"bias": bias}  # the line break itself is the structural event
        base_note = (
            "ورود روی **بیس داخل کندل شکست** (تجمیع تایم پایین میانه کندل) تعریف شد؛ چون پولبکِ کامل به خط "
            "داینامیک پس از شکست انفجاری معمولاً اتفاق نمی‌افتد. هدف‌ها = اولین نواحی عرضه/تقاضای ساختاری رو به‌رو."
            if stage == "JUST_BROKE" else
            "قیمت هنوز پشت خط است و در فاصله کمی از آن قرار دارد؛ با Close معتبر پشت خط، شکست تایید می‌شود."
        )
        detail = (
            f"خط {'مقاومت نزولی کانال' if direction == 'LONG' else 'حمایت صعودی کانال'} از دو پیوت "
            f"{context_tf.upper()} ({fit['a']['price']:.6g} و {fit['b']['price']:.6g}) با {fit['touches']} برخورد قبلی رسم شده؛ "
            f"ارتفاع کانال {fit['height'] / atr_c:.1f}×ATR است. {base_note}"
        )
        special = EvidenceItem("tlbreak", "شکست خط روند/کانال داینامیک", detail, True, 2,
                               level=line_now, timeframe=context_tf)
        impulse = {"index": -1, "level": line_now, "valid": True,
                   "direction": bias,
                   "body_atr": abs(last_close - last_open) / atr_c, "volume_ratio": 1.0}
        candidate = _base_candidate(
            bundle, style, "TLBREAK", direction, context_tf, trigger_tf,
            context, poi, impulse, special, "tlbreak_line", True,
        )
        if not candidate:
            return None
        # structural targets (first opposing supply/demand) from the engine;
        # relax only the CREATION gate; confirm-time floors still apply.
        candidate.mandatory_gates["rr"] = candidate.rr_tp1 >= 1.0 and candidate.rr_tp2 >= 1.5
        # For a validated trend/triangle/channel event, HTF bias is context and
        # not a veto: the break itself may be the reversal. The symbol already
        # passed the dynamic-liquidity universe, so venue-day turnover is not
        # allowed to make a technically valid alert dead-on-arrival.
        candidate.mandatory_gates["htf_alignment"] = True
        candidate.mandatory_gates["market_liquidity"] = True
        candidate.metadata["tl_context_conflict"] = not bool(context.get("bias") == bias)
        other_dir = "SHORT" if direction == "LONG" else "LONG"
        other_fit = _fit_channel_line(context_df, other_dir)
        pattern = "TRENDLINE"
        if other_fit is not None:
            def _line_price(fit_d, x):
                return fit_d["b"]["price"] + fit_d["slope"] * (x - fit_d["b"]["index"])
            x_far = int(max(fit["a"]["index"], other_fit["a"]["index"]))
            x_now = len(context_df) - 2
            gap_far = abs(_line_price(fit, x_far) - _line_price(other_fit, x_far))
            gap_now = abs(_line_price(fit, x_now) - _line_price(other_fit, x_now))
            if gap_now < 0.70 * gap_far and gap_now > 0:
                # converging dynamic structure: opposite slopes = triangle,
                # same-sign slopes narrowing = wedge
                pattern = "TRIANGLE" if fit["slope"] * other_fit["slope"] < 0 else "WEDGE"
            else:
                pattern = "CHANNEL"
        pattern_fa = {"TRIANGLE": "الگوی مثلث", "WEDGE": "الگوی وج",
                      "CHANNEL": "کانال داینامیک", "TRENDLINE": "ترندلاین داینامیک"}[pattern]
        viva_mode = bool(getattr(settings, "viva_tlbreak_enabled", False))
        candidate.strategy_fa = ("VIVA-TLBREAK | " if viva_mode else "") + (("شکست " if stage == "JUST_BROKE" else "برخوردِ نزدیک به ") + pattern_fa)
        candidate.metadata.update({
            "tl_a_index": int(fit["a"]["index"]), "tl_a_price": float(fit["a"]["price"]),
            "tl_a_ts": str(fit["a"].get("timestamp", "")),
            "tl_b_index": int(fit["b"]["index"]), "tl_b_price": float(fit["b"]["price"]),
            "tl_b_ts": str(fit["b"].get("timestamp", "")),
            "tl_anchor_ts": str(fit["anchor"].get("timestamp", "")),
            "tl_slope": float(fit["slope"]), "tl_anchor_price": float(fit["anchor"]["price"]),
            "tl_height": float(fit["height"]), "tl_touches": int(fit["touches"]),
            "tl_stage": stage, "tl_line": float(line_now),
            "tl_context_tf": context_tf,
            "tl_bound_now": float(fit["bound_now"]),
            "tl_base_kind": base["kind"] if stage == "JUST_BROKE" else "LINE_WATCH",
            "tl_pattern": pattern,
            "tl_pattern_fa": pattern_fa,
            "strategy_variant": "VIVA_TLBREAK" if viva_mode else "LEGACY_TLBREAK",
            "tl_fit_error_atr": float(fit.get("fit_error_atr", 0) or 0),
        })
        return candidate
    return None


SETUP_NAMES["TLBREAK"] = "Trendline/Channel Break (measured-move targets)"
SETUP_NAMES_FA["TLBREAK"] = "شکست خط روند/کانال داینامیک با هدف اندازه‌گیری‌شده"

TLBREAK_DETECTORS = [detect_trendline_breakout]

EXPERIMENTAL_DETECTORS = [detect_pattern_1234]


# --------------------------------------------------------------------------
# PINVAL — valid pinbar inside an important zone (Viva's alert spec).
#
# A pinbar is VALID when:
#   * range >= 0.6 * ATR(14) of its own timeframe
#   * dominant wick >= 2x body, body <= 35% of the range
#   * it rejects an IMPORTANT zone: a higher-context supply/demand pivot zone,
#     the edge of an un-mitigated FVG on the same TF, without adjacent dojis
#     next to a higher-context level (confluence bonus), or both.
# The alert is informational (🟢/🔴); the monitor resolves a verdict within
# ALERT_VERDICT_CANDLES candles: close beyond the pinbar extreme in the alert
# direction => ✅ confirmed; close beyond the wick => ❌ invalidated; else ⚪.
# --------------------------------------------------------------------------

SETUP_NAMES["PINVAL"] = "Valid Pinbar in Important Zone (alert)"
SETUP_NAMES_FA["PINVAL"] = "پین‌بار معتبر در ناحیه مهم"

PINVAL_TF_BY_STYLE = {"SWING": ("1h",), "DAYTRADE": ("15m",), "SCALP": ("5m",)}


def _unmitigated_fvg_edge(df, direction: str, atr_v: float, lookback: int = 60):
    """Nearest un-mitigated FVG edge aligned with `direction` (demand for LONG)."""
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)
    best = None
    for i in range(n - 3, max(2, n - lookback) - 1, -1):
        if direction == "LONG" and lows[i] > highs[i - 2]:
            lo, hi = highs[i - 2], lows[i]
            if hi - lo < 0.15 * atr_v:
                continue
            if np.any(closes[i + 1:] < lo):  # gap traded through -> mitigated
                continue
            best = {"kind": "FVG", "bottom": float(lo), "top": float(hi), "index": i}
            break
        if direction == "SHORT" and highs[i] < lows[i - 2]:
            lo, hi = lows[i - 2], highs[i]
            if hi - lo < 0.15 * atr_v:
                continue
            if np.any(closes[i + 1:] > hi):
                continue
            best = {"kind": "FVG", "bottom": float(lo), "top": float(hi), "index": i}
            break
    return best


def _context_zone(bundle: MarketBundle, ctx_tf: str, direction: str, atr_c: float):
    """Important higher-context supply/demand zone from the latest pivots."""
    ctx = bundle.get(ctx_tf)
    if ctx is None or len(ctx) < 60:
        return None
    highs, lows = pivots(ctx, 3, 3)
    seq = highs if direction == "SHORT" else lows
    if len(seq) < 2:
        return None
    lv = float(seq[-1]["price"])
    # flip-zone hint: same level was respected from BOTH sides historically
    closes = ctx["close"].values
    for older in seq[-6:]:
        ol = float(older["price"])
        if abs(ol - lv) > 0.6 * atr_c:
            continue
        above = np.any(closes[: int(older["index"])] > lv + 0.6 * atr_c)
        below = np.any(closes[: int(older["index"])] < lv - 0.6 * atr_c)
        if above and below:
            return {"kind": "FLIP", "level": lv}
    return {"kind": "SD_FRESH", "level": lv}


def detect_pinbar_zone(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    settings = get_settings()
    if not getattr(settings, "pinv_enabled", True):
        return None
    ctx_tf, _middle_tf, _trigger_tf = timeframe_profile(style)
    if not _ensure_frames(bundle, (ctx_tf,)):
        return None
    best = None
    for tf in PINVAL_TF_BY_STYLE.get(style, ("15m",)):
        df = bundle.get(tf)
        if df is None or len(df) < 40:
            continue
        atr_ser = atr(df)
        atr_v = float(atr_ser.iloc[-1]) if np.isfinite(atr_ser.iloc[-1]) else 0.0
        if atr_v <= 0:
            continue
        row = df.iloc[-1]
        o, h, l, c = (float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]))
        rng = h - l
        body = abs(c - o)
        if rng < getattr(settings, "pinv_min_range_atr", 0.6) * atr_v or body <= 0:
            continue
        upper = h - max(o, c)
        lower = min(o, c) - l
        is_bull = lower >= getattr(settings, "pinv_min_wick_body", 2.0) * body and body <= getattr(settings, "pinv_max_body_frac", 0.35) * rng and c >= l + rng * 0.5
        is_bear = upper >= getattr(settings, "pinv_min_wick_body", 2.0) * body and body <= getattr(settings, "pinv_max_body_frac", 0.35) * rng and c <= h - rng * 0.5
        if not (is_bull or is_bear):
            continue
        direction = "LONG" if is_bull else "SHORT"
        probe = l if is_bull else h

        fvg = _unmitigated_fvg_edge(df, direction, atr_v)
        in_fvg = bool(fvg) and fvg["bottom"] - 0.35 * atr_v <= probe <= fvg["top"] + 0.35 * atr_v
        zone = _context_zone(bundle, ctx_tf, direction, atr_v)
        in_zone = bool(zone) and abs(probe - zone["level"]) <= 0.7 * atr_v
        if not (in_fvg or in_zone):
            continue  # Viva's rule: pinbar matters only inside an important area

        # adjacent doji confluence (previous two candles)
        has_doji = False
        for j in (-2, -3):
            if len(df) + j < 0:
                continue
            r2 = df.iloc[j]
            b2 = abs(float(r2["close"]) - float(r2["open"]))
            r2_rng = float(r2["high"]) - float(r2["low"])
            if r2_rng >= 0.3 * atr_v and b2 <= 0.15 * r2_rng:
                has_doji = True

        entry = c
        # A valid pinbar is only a location clue. Execution risk must live
        # beyond actual nearby liquidity, with adaptive volatility/price floors.
        poi = {"bottom": min(o, c), "top": max(o, c), "touches": 0, "type": "PINVAL"}
        invalidation = _liquidity_protected_invalidation(
            df, poi, direction, atr_v, str(style).upper(),
            float((bundle.ticker or {}).get("spread_pct", 0) or 0),
        )
        sl = float(invalidation["price"])
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        # Do not invent targets from fixed R multiples. Both targets must be
        # real opposing context pivots, otherwise this is an alert-only chart
        # with no executable trade and must not be published.
        ctx_df = bundle.get(ctx_tf)
        targets = _structural_targets(ctx_df, direction, entry, sl, require_real_levels=True) if ctx_df is not None else None
        if not targets:
            continue
        tp1, tp2 = float(targets["tp1"]), float(targets["tp2"])
        rr1, rr2 = float(targets["rr1"]), float(targets["rr2"])
        if rr1 < float(getattr(settings, "pinv_rr1_floor", 1.30)) or rr2 < float(getattr(settings, "pinv_rr2_floor", 2.0)):
            continue
        tf_seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}.get(str(tf), 300)
        zone_kind = "FVG" if in_fvg else (zone["kind"] if in_zone else "NONE")
        allowed_dirs = {x.strip().upper() for x in str(getattr(settings, "pinv_allowed_directions", "") or "").split(",") if x.strip()}
        allowed_zones = {x.strip().upper() for x in str(getattr(settings, "pinv_allowed_zone_kinds", "") or "").split(",") if x.strip()}
        if allowed_dirs and direction not in allowed_dirs:
            continue
        if allowed_zones and zone_kind.upper() not in allowed_zones:
            continue
        zone_fa = {"FVG": "لبهٔ FVG «فلگ‌لیمیت»", "FLIP": "فلیپ‌زون مهم",
                   "SD_FRESH": "زون تازهٔ عرضه/تقاضای تایم بالاتر", "NONE": "ناحیهٔ مرتبط"}.get(zone_kind, "ناحیهٔ مهم")
        last_ts = df["timestamp"].iloc[-1]
        from analysis.models import iso_now
        created = iso_now()
        # Freshness guard: an alerting pinbar must have just closed. Without
        # this, a stale pin (e.g. a 1h pin from 45 minutes ago) gets alerted
        # and the monitor instantly mass-verdicts it from already-closed
        # candles — Viva's "10 alerts, all cancelled 1 minute later" bug.
        try:
            age_s = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timestamp(last_ts)).total_seconds()
            if age_s > 2 * tf_seconds:
                continue
        except Exception:
            pass
        style_name = str(style).upper()
        candidate = SignalCandidate(
            signal_id=f"viva-pinv-{bundle.symbol}-{tf}-{str(last_ts)[:16]}",
            symbol=bundle.symbol,
            style=style_name,
            setup_code="PINVAL",
            setup_name=SETUP_NAMES["PINVAL"],
            strategy_fa=f"پین‌بار {'صعودی 🟢' if is_bull else 'نزولی 🔴'} در {zone_fa}",
            direction=direction,
            score=8 + (1 if has_doji else 0),
            status="EDUCATIONAL",
            entry_zone_bottom=min(o, c),
            entry_zone_top=max(o, c),
            planned_entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            rr_tp1=round(rr1, 2),
            rr_tp2=round(rr2, 2),
            bias=("BULLISH" if is_bull else "BEARISH"),
            trigger_timeframe=tf,
            expires_at="",
        )
        candidate.metadata.update({
            "pinv": 1,
            "public_code": generate_viva_public_code("PINVAL", style_name),
            "pin_tf": tf,
            "pin_high": h,
            "pin_low": l,
            "pin_ts": str(last_ts),
            "pin_zone_kind": zone_kind,
            "pin_zone_fa": zone_fa,
            "pin_ctx_tf": ctx_tf,
            "pin_has_doji": bool(has_doji),
            "pin_verdict_candles": int(getattr(settings, "alert_verdict_candles", 3)),
            "context_tf": ctx_tf,
            "confirm_tf": confirm_timeframe(style, tf),
            "invalidation_liquidity_anchor": invalidation["liquidity_anchor"],
            "invalidation_buffer": invalidation["buffer"],
            # PINVAL is now eligible for the same real confirmation lifecycle
            # as every other setup; it is not a verdict-only pseudo-signal.
            "alert_only": 0,
        })
        candidate.mandatory_gates = {"pin_zone": True, "structural_targets": True, "risk_reward": True}
        if not candidate.expires_at:
            from datetime import datetime, timedelta, timezone
            hours = 24 if style == "SWING" else (10 if style == "DAYTRADE" else 3)
            candidate.expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
        if best is None or candidate.score > best.score:
            best = candidate
    return best


def _albrox_spike_context(df: np.ndarray | object) -> dict | None:
    # Placeholder marker; detector below works with pandas dataframes.
    return None


def detect_albrox(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    """ALBROX v1: current Pinwall quality only after a suspicious sweep/base context.

    This preserves Pinwall itself; ALBROX is a separately labelled paper branch.
    """
    settings = get_settings()
    base = detect_pinbar_zone(bundle, style)
    if base is None:
        return None
    df = bundle.get(base.trigger_timeframe)
    if df is None or len(df) < 40:
        return None
    atr_v = float((df["high"] - df["low"]).tail(14).mean())
    if atr_v <= 0:
        return None
    # A large sweep in the preceding 40 bars is the Albrox context. The pin
    # itself still uses the existing calibrated PINWALL anatomy/location.
    spike_found = False
    for i in range(max(14, len(df)-40), len(df)-2):
        row = df.iloc[i]
        rng = float(row["high"]-row["low"])
        local_atr = float((df["high"]-df["low"]).iloc[max(0,i-14):i].mean() or 0)
        if local_atr <= 0 or rng < 5.0*local_atr:
            continue
        if base.direction == "LONG" and float(row["close"]) > float(row["low"]) + .45*rng:
            spike_found = True; break
        if base.direction == "SHORT" and float(row["close"]) < float(row["high"]) - .45*rng:
            spike_found = True; break
    if not spike_found:
        return None
    candidate = SignalCandidate.from_dict(base.to_dict())
    candidate.signal_id = f"viva-albrox-{bundle.symbol}-{base.trigger_timeframe}-{str(df['timestamp'].iloc[-1])[:16]}"
    candidate.setup_code = "ALBROX"
    candidate.setup_name = SETUP_NAMES["ALBROX"]
    candidate.strategy_fa = SETUP_NAMES_FA["ALBROX"]
    candidate.score = min(10, candidate.score + 1)
    candidate.metadata.update({
        "strategy_variant": "ALBROX",
        "albrox_spike_context": True,
        "albrox_mode": "PINWALL_LOCATION_PLUS_SPIKE_RECLAIM",
        "public_code": generate_viva_public_code("ALBROX", style),
    })
    return candidate


ALBROX_DETECTORS = [detect_albrox]

PINVAL_DETECTORS = [detect_pinbar_zone]
