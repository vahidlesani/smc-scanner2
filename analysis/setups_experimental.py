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

from analysis.indicators import adx, structure_bias
from analysis.models import EvidenceItem, SignalCandidate
from config import get_settings
from analysis.setups_v7 import (
    SETUP_NAMES,
    SETUP_NAMES_FA,
    _base_candidate,
    _direction,
    _ensure_frames,
    pivots,
)
from data.fetcher import MarketBundle

SETUP_NAMES["P1234"] = "1-2-3-4 Reversal + Point-2 Break Retest"
SETUP_NAMES_FA["P1234"] = "الگوی برگشتی ۱-۲-۳-۴ و اولین پولبک به نقطه ۲"


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
    context_tf, trigger_tf = ("4h", "15m") if style == "SWING" else ("1h", "5m")
    middle_tf = "1h" if style == "SWING" else "15m"
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


def detect_trendline_breakout(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    settings = get_settings()
    override_tf = (getattr(settings, "tlbreak_context_tf", "") or "").strip()
    context_tf = override_tf or (("4h" if style == "SWING" else "1h"))
    trigger_tf = "15m" if style == "SWING" else "5m"
    if not _ensure_frames(bundle, (context_tf, trigger_tf)):
        return None
    context_df = bundle.get(context_tf)
    last_close = float(context_df["close"].iloc[-1])
    prev_close = float(context_df["close"].iloc[-2])
    last_open = float(context_df["open"].iloc[-1])

    for direction in ("LONG", "SHORT"):
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
        })
        return candidate
    return None


SETUP_NAMES["TLBREAK"] = "Trendline/Channel Break (measured-move targets)"
SETUP_NAMES_FA["TLBREAK"] = "شکست خط روند/کانال داینامیک با هدف اندازه‌گیری‌شده"

TLBREAK_DETECTORS = [detect_trendline_breakout]

EXPERIMENTAL_DETECTORS = [detect_pattern_1234]
