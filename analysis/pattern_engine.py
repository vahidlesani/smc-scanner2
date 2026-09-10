"""TechnoClassic pattern engine — VIVA stage-5 (user-directed, 2026-09-10).

Classical-geometry lifecycle on TOP-DOWN timeframes (4H and 1D), in BOTH
directions, for every validated shape the geometry fit supports:

    falling wedge  → LONG upper-edge break      (retest-first confirmation)
    rising wedge   → SHORT lower-edge break
    ascending triangle  → LONG upper break   | descending triangle → SHORT lower break
    symmetrical triangle / channel / major trendline → break of EITHER edge

Lifecycle per edge:  FORMING → EDGE_NEAR (warning chart) → BREAK_READY
(standby alert) → BREAK CLOSED (real TECHCLASSIC candidate that runs the
existing retest + lower-TF micro-BOS confirmation cascade).

Design rules (Viva's explicit constraints):
  * Scoring must be ADDITIVE only. Nothing in this module may reject a
    signal by itself — bonuses for compression/base proximity are added to
    other setups' scores; the pattern gate on TECHCLASSIC candidates is
    their own lifecycle, never TLBREAK/ALBROX internals.
  * Compression is a first-class citizen: squeeze score feeds READY/BREAK
    bonuses AND is reported on charts so a base before a break is visible.
  * Pattern lines are exported (viva_upper_points/viva_lower_points) so the
    high-DPI renderer draws them across the whole canvas including the
    future panel.
"""
from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import get_settings

STATE_NEAR = "EDGE_NEAR"
STATE_READY = "BREAK_READY"
STATE_BREAK = "BREAK_CLOSED"

# Which direction(s) a pattern break is actionable toward.
_EDGE_RULES = {
    "WEDGE_FALLING": {"upper": "LONG"},
    "WEDGE_RISING": {"lower": "SHORT"},
    "TRIANGLE_ASCENDING": {"upper": "LONG", "lower": "SHORT"},
    "TRIANGLE_DESCENDING": {"upper": "LONG", "lower": "SHORT"},
    "TRIANGLE_SYMMETRICAL": {"upper": "LONG", "lower": "SHORT"},
    "TRIANGLE": {"upper": "LONG", "lower": "SHORT"},
    "CHANNEL_ASCENDING": {"upper": "SHORT", "lower": "LONG"},
    "CHANNEL_DESCENDING": {"upper": "SHORT", "lower": "LONG"},
    "CHANNEL_FLAT": {"upper": "SHORT", "lower": "LONG"},
    "CHANNEL": {"upper": "SHORT", "lower": "LONG"},
    "TRENDLINE": {"upper": "SHORT", "lower": "LONG"},
    "HORIZONTAL_SR": {"upper": "SHORT", "lower": "LONG"},
}


# ── compression ───────────────────────────────────────────────────────────
def compression_metrics(df: pd.DataFrame) -> Dict:
    """Squeeze/compression profile of the most recent bars (Viva's ask:
    'dojis + small candles → compressed base' must be measurable)."""
    out = {"squeeze_ok": False, "doji_count": 0, "small_body_ratio": 0.0,
           "contraction": 1.0, "bars": 0}
    try:
        if df is None or len(df) < 30:
            return out
        d = df.tail(30).reset_index(drop=True)
        o, c = d["open"].astype(float), d["close"].astype(float)
        h, l = d["high"].astype(float), d["low"].astype(float)
        rng = (h - l)
        body = (c - o).abs()
        atr14 = float(rng.tail(14).mean())
        if atr14 <= 0:
            return out
        recent = d.tail(8)
        r_rng = (recent["high"] - recent["low"]).astype(float)
        r_body = (recent["close"] - recent["open"]).abs()
        doji = int(((r_body <= 0.15 * r_rng) & (r_rng > 0)).sum())
        small = float((r_rng <= 0.75 * atr14).mean())
        base_rng = float((d.head(14)["high"] - d.head(14)["low"]).mean())
        contraction = float((r_rng.mean() / base_rng)) if base_rng > 0 else 1.0
        out.update({
            "doji_count": doji,
            "small_body_ratio": round(small, 3),
            "contraction": round(contraction, 3),
            "bars": int(len(recent)),
        })
        out["squeeze_ok"] = bool(
            doji >= 2 and small >= 0.5 and contraction <= 0.60
        ) or bool(contraction <= 0.45)
        return out
    except Exception:
        return out


def compression_bonus(df: pd.DataFrame) -> Tuple[float, Dict]:
    m = compression_metrics(df)
    return (2.0 if m["squeeze_ok"] else 0.5 if m["small_body_ratio"] >= 0.4 else 0.0), m


def base_side_bonus(df: pd.DataFrame, price: float, direction: str) -> float:
    """Additive bonus when price sits ON or just ABOVE a swing-low base
    (LONG) or just BELOW a swing-high base (SHORT). Both directions score
    proximity; nothing is ever blocked for being far away (Viva rule)."""
    try:
        from analysis.setups_v7 import pivots
        d = df.tail(120)
        highs, lows = pivots(d, 2, 2)
        atr14 = float((d["high"] - d["low"]).tail(14).mean())
        if atr14 <= 0:
            return 0.0
        pts = lows if direction == "LONG" else highs
        for p in list(pts)[-4:]:
            lvl = float(p["price"])
            near = (0 <= price - lvl <= 1.0 * atr14) if direction == "LONG" \
                else (0 <= lvl - price <= 1.0 * atr14)
            on_top = abs(price - lvl) <= 0.25 * atr14
            if on_top:
                return 2.0
            if near:
                return 1.0
        return 0.0
    except Exception:
        return 0.0


# ── edge lifecycle ────────────────────────────────────────────────────────
def scan_edges(pattern_df: pd.DataFrame, trigger_df: pd.DataFrame,
               pattern_tf: str) -> List[Dict]:
    """Return per-edge events (NEAR/READY/BREAK) for the validated geometry
    fitted on `pattern_df` (4H or 1D frame)."""
    from analysis.viva_tlbreak import (classify_pattern_detailed,
                                       fit_validated_line, load_config,
                                       structure_score)
    events: List[Dict] = []
    if pattern_df is None or len(pattern_df) < 40 or trigger_df is None or len(trigger_df) < 6:
        return events
    cfg = load_config()
    upper = fit_validated_line(pattern_df, "HIGH", cfg)
    lower = fit_validated_line(pattern_df, "LOW", cfg)
    if upper is None and lower is None:
        return events
    n = len(pattern_df) - 1
    pattern = classify_pattern_detailed(upper, lower, n, cfg)
    rules = _EDGE_RULES.get(str(pattern).upper())
    if not rules:
        return events
    atr14 = float((pattern_df["high"] - pattern_df["low"]).tail(14).mean())
    if atr14 <= 0:
        return events
    comp = compression_metrics(pattern_df)
    comp_ok = comp["squeeze_ok"]
    last_close = float(trigger_df["close"].iloc[-1])
    for side, line in (("upper", upper), ("lower", lower)):
        if line is None:
            continue
        direction = rules.get(side)
        if not direction:
            continue
        line_now = float(line.price_at(n))
        # extend one bar into the future so an edge still "alive" projects
        dist_atr = (line_now - last_close) / atr14 if direction == "LONG" \
            else (last_close - line_now) / atr14
        crossed = last_close > line_now if direction == "LONG" else last_close < line_now
        body = abs(float(trigger_df["close"].iloc[-1]) - float(trigger_df["open"].iloc[-1]))
        rng = float(trigger_df["high"].iloc[-1]) - float(trigger_df["low"].iloc[-1])
        displacement = body >= 0.5 * atr14 and (rng <= 0 or body / max(rng, 1e-12) >= 0.55)
        if crossed and displacement:
            state = STATE_BREAK
        elif crossed or dist_atr <= 0.15:
            state = STATE_READY if (comp_ok or displacement) else STATE_NEAR
        elif dist_atr <= 1.2:
            state = STATE_NEAR
        else:
            continue
        events.append({
            "pattern": pattern, "pattern_fa": PATTERN_FA.get(pattern, pattern),
            "side": side, "direction": direction,
            "state": state, "line_price": line_now, "distance_atr": round(abs(dist_atr), 3),
            "touches": int(line.touch_count), "fit_error_atr": round(float(line.fit_residual_atr), 3),
            "structure_score": structure_score(line, cfg),
            "compression": comp, "pattern_tf": pattern_tf,
            "upper_points": [dict(p) for p in (upper.points if upper else ())],
            "lower_points": [dict(p) for p in (lower.points if lower else ())],
            "ref_ts": str(trigger_df["timestamp"].iloc[-1]),
        })
    return events


# ── pre-break alert cooldown (NEAR / READY only; BREAK goes full lifecycle) ─
_ALERT_SEEN: Dict[str, float] = {}


def _cooldown_ok(key: str, state: str) -> bool:
    hours = float(getattr(get_settings(), "technoclassic_cooldown_hours", 8.0) or 8.0)
    now = time.time()
    stamp = _ALERT_SEEN.get(key)
    window = hours * 3600.0 if state == STATE_NEAR else (hours / 2) * 3600.0
    if stamp and now - stamp < window:
        return False
    _ALERT_SEEN[key] = now
    return True


def evaluate_prebreak(symbol: str, pattern_df: pd.DataFrame, trigger_df: pd.DataFrame,
                      pattern_tf: str) -> List[Dict]:
    """NEAR/READY events that survived alert cooldown; caller decides sending."""
    out: List[Dict] = []
    for ev in scan_edges(pattern_df, trigger_df, pattern_tf):
        if ev["state"] == STATE_BREAK:
            continue
        key = f"{symbol}|{pattern_tf}|{ev['pattern']}|{ev['direction']}|{ev['side']}"
        if _cooldown_ok(key, ev["state"]):
            ev2 = dict(ev); ev2["symbol"] = symbol
            out.append(ev2)
    return out


# ── candidate builder (BREAK → real lifecycle) ─────────────────────────────
PATTERN_FA = {
    "WEDGE_FALLING": "گوه نزولی (فالینگ‌وج)",
    "WEDGE_RISING": "گوه صعودی (رایزینگ‌وج)",
    "TRIANGLE_ASCENDING": "مثلث صعودی",
    "TRIANGLE_DESCENDING": "مثلث نزولی",
    "TRIANGLE_SYMMETRICAL": "مثلث متقارن",
    "TRIANGLE": "مثلث",
    "CHANNEL_ASCENDING": "کانال صعودی",
    "CHANNEL_DESCENDING": "کانال نزولی",
    "CHANNEL_FLAT": "کانال افقی",
    "CHANNEL": "کانال",
    "TRENDLINE": "خط روند اصلی",
    "HORIZONTAL_SR": "سطح افقی مهم",
}


def _fit_geometry(pattern_df, cfg):
    from analysis.viva_tlbreak import classify_pattern_detailed, fit_validated_line
    upper = fit_validated_line(pattern_df, "HIGH", cfg)
    lower = fit_validated_line(pattern_df, "LOW", cfg)
    n = len(pattern_df) - 1
    pattern = classify_pattern_detailed(upper, lower, n, cfg)
    return upper, lower, pattern, n


def detect_technoclassic(bundle, style: str):
    """5th live setup: 4H/1D classical-pattern break → existing retest+BOS
    lifecycle. Additive scoring only; never touches other setups' gates."""
    settings = get_settings()
    if not getattr(settings, "technoclassic_enabled", False):
        return None
    from analysis.viva_tlbreak import (assess_projected_breakout,
                                      build_pattern_plan, load_config,
                                      pattern_geometry_ok, pattern_length_ok,
                                      score_confluences, structure_score)
    from analysis.indicators import structure_bias
    from analysis.models import EvidenceItem, generate_viva_public_code
    from analysis.setups_v7 import _base_candidate, _ensure_frames, timeframe_profile
    cfg = load_config()
    structure_tf, refine_tf, trigger_tf = timeframe_profile(style)
    if not _ensure_frames(bundle, (structure_tf, trigger_tf)):
        return None
    pattern_df = bundle.get(structure_tf)
    trigger_df = bundle.get(trigger_tf)
    if pattern_df is None or len(pattern_df) < 60 or trigger_df is None or len(trigger_df) < 6:
        return None
    upper, lower, pattern, n = _fit_geometry(pattern_df, cfg)
    if upper is None and lower is None:
        return None
    rules = _EDGE_RULES.get(str(pattern).upper()) or {}
    atr_p = float((pattern_df["high"] - pattern_df["low"]).tail(14).mean())
    atr_t = float((trigger_df["high"] - trigger_df["low"]).tail(14).mean())
    if atr_p <= 0 or atr_t <= 0:
        return None
    comp_bonus, comp = compression_bonus(pattern_df)
    for side, line in (("upper", upper), ("lower", lower)):
        if line is None:
            continue
        direction = rules.get(side)
        if not direction:
            continue
        ok_geo, _ = pattern_geometry_ok(upper, lower, n)
        if not ok_geo or not pattern_length_ok(line, style):
            continue
        breakout = assess_projected_breakout(trigger_df, line, direction)
        if breakout is None or not breakout.passed:
            continue
        # failed-breakout guard from the same engine TLBREAK uses
        try:
            from analysis.viva_tlbreak import recent_failed_breakout_penalty
            penalty = recent_failed_breakout_penalty(trigger_df, line, direction)
        except Exception:
            penalty = 0.0
        plan = build_pattern_plan(pattern_df, upper, lower, direction)
        if plan is None:
            continue
        last_price = float(trigger_df["close"].iloc[-1])
        b_bonus = base_side_bonus(pattern_df, last_price, direction)
        poi = {"bottom": breakout.line_price - .15 * atr_t,
               "top": breakout.line_price + .15 * atr_t,
               "touches": 0, "type": f"TECHNOCLASSIC {pattern} BREAK/RETEST"}
        bias = structure_bias(pattern_df, 5)
        context = {"bias": bias.get("bias", "NEUTRAL")}
        impulse = {"index": len(trigger_df) - 1, "level": breakout.line_price,
                   "valid": True, "direction": "BULLISH" if direction == "LONG" else "BEARISH",
                   "body_atr": breakout.body_atr, "volume_ratio": 1.0}
        special = EvidenceItem(
            "technoclassic", "تکنوکلاسیک | شکست کلاسیک HTF",
            f"{PATTERN_FA.get(pattern, pattern)} روی {structure_tf} با {line.touch_count} "
            f"پیوت معتبر (خطای فیت {line.fit_residual_atr:.2f} ATR)؛ کلوز شکست "
            f"{breakout.beyond_atr:.2f} ATR فراتر از خط. کامپرشن: "
            f"{'فعال' if comp['squeeze_ok'] else 'ضعیف'} ({comp['doji_count']} دوجی).",
            True, 2, level=breakout.line_price, timeframe=structure_tf)
        candidate = _base_candidate(bundle, style, "TECHCLASSIC", direction,
                                   structure_tf, trigger_tf,
                                   context, poi, impulse, special, "technoclassic_break_closed", True)
        if candidate is None:
            continue
        confluence = 0.0
        try:
            refine_df = bundle.get(refine_tf)
            if refine_df is not None and len(refine_df) > 30:
                confluence = score_confluences(pattern_df, refine_df, trigger_df,
                                               direction, retest_score=0.0).total
        except Exception:
            pass
        raw = structure_score(line, cfg) + breakout.score + confluence + comp_bonus + b_bonus + penalty
        candidate.score = min(10, max(6, round(raw)))
        buffer = max(0.35 * atr_p, abs(candidate.planned_entry) * 0.0005)
        pattern_sl = plan.stop_anchor - buffer if direction == "LONG" else plan.stop_anchor + buffer
        candidate.sl = min(candidate.sl, pattern_sl) if direction == "LONG" else max(candidate.sl, pattern_sl)
        final_target = plan.structural_target or plan.measured_target
        if (direction == "LONG" and final_target <= candidate.planned_entry) or \
           (direction == "SHORT" and final_target >= candidate.planned_entry):
            continue
        risk = abs(candidate.planned_entry - candidate.sl)
        rr_final = abs(final_target - candidate.planned_entry) / max(risk, 1e-12)
        if rr_final < 1.5:
            continue
        candidate.tp2 = float(final_target)
        candidate.tp1 = float(candidate.planned_entry + (final_target - candidate.planned_entry) * 0.40)
        candidate.rr_tp1 = abs(candidate.tp1 - candidate.planned_entry) / max(risk, 1e-12)
        candidate.rr_tp2 = rr_final
        candidate.mandatory_gates["htf_alignment"] = True
        from analysis.viva_tlbreak_state import VivaTLState
        candidate.strategy_fa = f"تکنوکلاسیک | شکست {PATTERN_FA.get(pattern, pattern)} | پولبک اول + BOS تایم پایین"
        candidate.metadata.update({
            "strategy_variant": "VIVA_TLBREAK",
            "technoclassic": {"pattern": pattern, "pattern_tf": structure_tf,
                              "side": side, "compression": comp,
                              "base_bonus": b_bonus, "compression_bonus": comp_bonus},
            "viva_state_machine": VivaTLState(stage="S2_BREAKOUT").payload(),
            "viva_retest_window_bars": 40 if str(style).upper() == "SWING" else 32,
            "viva_pattern": pattern, "tl_pattern": pattern,
            "tl_pattern_fa": PATTERN_FA.get(pattern, pattern),
            "viva_touch_count": line.touch_count, "viva_fit_error_atr": line.fit_residual_atr,
            "viva_break_line": breakout.line_price, "viva_breakout_score": breakout.score,
            "viva_breakout_body_atr": breakout.body_atr,
            "viva_structure_score": structure_score(line, cfg),
            "viva_final_score": raw, "viva_stop_anchor": plan.stop_anchor,
            "viva_measured_target": plan.measured_target, "viva_final_target": final_target,
            "viva_structural_target": plan.structural_target,
            "viva_state": "S2_BREAKOUT_CLOSED",
            "tl_context_tf": structure_tf, "tl_line": breakout.line_price,
            "tl_touches": line.touch_count,
            "viva_upper_points": [dict(p) for p in (upper.points if upper else ())],
            "viva_lower_points": [dict(p) for p in (lower.points if lower else ())],
            "viva_breakout_line": breakout.line_price,
            "viva_retest_zone": [poi["bottom"], poi["top"]],
            "public_code": generate_viva_public_code("TLBREAK", style),
        })
        return candidate
    return None


def send_prebreak_alerts(bundle) -> Dict[str, int]:
    """NEAR/READY chart alerts on 4H and 1D edges (Viva's 'approaching the
    edge / ready-for-first-break' request). Never a signal; cooldown-guarded."""
    settings = get_settings()
    counts = {"near": 0, "ready": 0, "sent": 0}
    if not getattr(settings, "technoclassic_enabled", False):
        return counts
    if not getattr(settings, "technoclassic_preview_alerts", True):
        return counts
    from data.fetcher import get_klines
    trig = None
    for tf in ("15m", "1h"):
        trig = bundle.get(tf)
        if trig is not None and len(trig) > 6:
            break
    if trig is None:
        try:
            trig = get_klines(bundle.symbol, "15m", 120)
        except Exception:
            return counts
    for pattern_tf in ("4h", "1d"):
        pdf = bundle.get(pattern_tf)
        if pdf is None or len(pdf) < 60:
            try:
                pdf = get_klines(bundle.symbol, pattern_tf, 260)
            except Exception:
                continue
        if pdf is None or len(pdf) < 60:
            continue
        for ev in evaluate_prebreak(str(bundle.symbol), pdf, trig, pattern_tf):
            if ev["state"] == STATE_NEAR:
                counts["near"] += 1
            else:
                counts["ready"] += 1
            counts["sent"] += 1
            try:
                from bot.messages_v7 import send_technoclassic_preview
                send_technoclassic_preview(ev)
            except Exception as exc:
                print(f"TECHCLASSIC preview send skipped: {exc}")
    if counts["sent"]:
        print(f"📐 TECHCLASSIC previews • {bundle.symbol} near={counts['near']} ready={counts['ready']}")
    return counts
