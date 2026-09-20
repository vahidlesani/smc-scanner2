"""Portfolio-aware, capped money management for confirmed Viva signals."""
from __future__ import annotations

from typing import Dict, Optional

from config import get_settings

SETTINGS = get_settings()


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def quality_plan(score: int) -> Dict:
    """Map quality to risk, margin allocation and a leverage ceiling.

    Margin is posted collateral, not the amount a trader is expected to lose.
    The invalidation distance remains a second independent risk constraint.
    """
    score = int(score or 0)
    tiers = {
        10: (SETTINGS.max_risk_percent, 5.0, 20, "A+", "فوق‌العاده"),
        9: (min(1.15, SETTINGS.max_risk_percent), 4.0, 15, "A", "عالی"),
        8: (min(1.00, SETTINGS.max_risk_percent), 3.5, 10, "B+", "بسیار خوب"),
        7: (min(0.75, SETTINGS.max_risk_percent), 3.0, 5, "B", "خوب"),
        6: (min(0.50, SETTINGS.max_risk_percent), 0.0, 1, "C", "آموزشی/محتاط"),
    }
    risk, margin, leverage, grade, label = tiers.get(
        score, (0.0, 0.0, 1, "REJECTED", "غیرقابل اجرا")
    )
    return {
        "risk_pct": risk,
        "margin_pct": min(margin, SETTINGS.max_margin_percent),
        "leverage_cap": leverage,
        "grade": grade,
        "quality": label,
    }


def max_safe_leverage(sl_fraction: float, style: str = "SWING") -> int:
    """Keep estimated liquidation distance well beyond analysis invalidation."""
    if sl_fraction <= 0:
        return 1
    # Approximate liquidation distance is 1/leverage. Requiring it to be at
    # least ~2.5x the invalidation distance leaves a conservative safety gap.
    safety_adjusted = int(0.40 / sl_fraction)
    return _clamp(safety_adjusted, 1, 20)


def suggested_leverage(
    score: int,
    sl_fraction: float,
    style: str = "SWING",
    venue_max_leverage: Optional[float] = None,
) -> int:
    quality_cap = int(quality_plan(score)["leverage_cap"])
    venue_cap = int(float(venue_max_leverage or 20))
    return max(1, min(quality_cap, max_safe_leverage(sl_fraction, style), venue_cap, 20))


# ── «مدیریت ویوا» §8 (09-20): a SEPARATE management profile ──────────────
# Fixed base size per position by symbol price, flat 20× leverage — kept
# strictly apart from «مدیریت سرمایه استاندارد» (the score/quality engine
# above). The doc's exact boundaries: <5 → 30$, 5 to <50 → 40$, ≥50 → 50$.
VIVA_MARGIN_TABLE = ((5.0, 30.0, 20), (50.0, 40.0, 20), (float("inf"), 50.0, 20))


def viva_management_profile_enabled() -> bool:
    """True while «مدیریت ویوا» is the active profile (Viva 09-20: ON).

    Reads the live settings object; falls back to re-reading config so a
    runtime env flag (VIVA_MANAGEMENT_PROFILE) is always honoured.
    """
    try:
        return bool(getattr(SETTINGS, "viva_management_profile", False))
    except Exception:
        pass
    try:
        from config import get_settings
        return bool(getattr(get_settings(), "viva_management_profile", False))
    except Exception:
        return False


def viva_position(entry: float, direction: str, sl: Optional[float] = None,
                  tp1: Optional[float] = None, tp2: Optional[float] = None,
                  market: Optional[Dict] = None) -> Optional[Dict]:
    """«مدیریت ویوا» sizing: fixed margin + flat leverage from the table.

    Kept independent of the standard engine so the two profiles can be
    compared and either one switched off without touching the other (§14).
    Liquidation distance is reported, never silently capped: at 20× the
    exchange liquidates roughly 5% away, so a wider invalidation means the
    stop would be reached after liquidation — the caller surfaces a warning.
    """
    try:
        entry = float(entry)
        if entry <= 0:
            return None
        margin = leverage = None
        for upper, m, lev in VIVA_MARGIN_TABLE:
            if entry < upper:
                margin, leverage = float(m), int(lev)
                break
        if not margin:
            return None
        notional = margin * leverage
        sl_distance = abs(entry - float(sl)) if sl and float(sl) > 0 else 0.0
        sl_pct = sl_distance / entry * 100.0 if sl_distance else 0.0
        liq_pct = 100.0 / leverage
        out = {
            "profile": "VIVA",
            "margin": margin,
            "leverage": leverage,
            "position_size": notional,
            "quantity": notional / entry,
            "sl_pct": sl_pct,
            "liq_distance_pct": liq_pct,
            "risk_amount": notional * sl_distance / entry if sl_distance else 0.0,
        }
        # ≥2.5× headroom is the standard engine's rule; in the Viva profile it
        # is REPORTED as a warning instead of resizing (his table is explicit).
        out["liq_headroom"] = (liq_pct / sl_pct) if sl_pct > 0 else None
        if sl_pct > 0 and liq_pct < 1.5 * sl_pct:
            out["liq_warning_fa"] = (
                f"هشدار: با اهرم {leverage}× فاصلهٔ لیکوئید ≈{liq_pct:.1f}% است و "
                f"استاپ در {sl_pct:.1f}% دورتر — لیکوئید قبل از استاپ می‌خورد؛ "
                "مارجین این پوزیشن باید کمتر شود یا اهرم پایین‌تر بیاید.")
        return out
    except Exception:
        return None


def calculate_position(
    entry: float,
    sl: float,
    direction: str,
    score: int,
    account: float,
    style: str = "SWING",
    venue_max_leverage: Optional[float] = None,
    tp1: Optional[float] = None,
    tp2: Optional[float] = None,
) -> Optional[Dict]:
    entry = float(entry)
    sl = float(sl)
    account = float(account)
    sl_distance = abs(entry - sl)
    sl_fraction = sl_distance / entry if entry > 0 else 0
    if sl_fraction <= 0 or account <= 0:
        return None
    # «مدیریت ویوا» profile: when switched on, sizing comes from his fixed
    # table/leverage instead of the standard risk engine (never mixed).
    if viva_management_profile_enabled():
        _viva = viva_position(entry, direction, sl, tp1, tp2)
        if _viva:
            _viva.update({
                "cost_pct": 2.0 * (SETTINGS.fee_rate_percent + SETTINGS.slippage_percent),
                "quality": "VIVA-MANAGEMENT",
                "grade": "VIVA",
                "quality_leverage_cap": _viva["leverage"],
                "margin_pct": _viva["margin"] / account * 100 if account else 0,
                "margin_limit_pct": _viva["margin"] / account * 100 if account else 0,
                "tp1": tp1 if tp1 is not None else entry + sl_fraction * entry * 2,
                "tp2": tp2 if tp2 is not None else entry + sl_fraction * entry * 3,
                "max_safe_leverage": max_safe_leverage(sl_fraction, style),
                "margin_capped": False,
                "risk_pct": (_viva["risk_amount"] / account * 100) if account else 0,
            })
            return _viva

    plan = quality_plan(score)
    risk_pct = plan["risk_pct"]
    if risk_pct <= 0:
        return None
    # Viva 09-19/20 refine (his «روی محاسبات و لوریج رضایت ندارم»):
    # (1) wide-stop volatility penalty — a 20%+ invalidation distance is a
    #     different animal than a 2% one; size it as such.
    if sl_fraction > 0.30:
        return None                      # not a sizeable trade at all
    if sl_fraction > 0.18:
        risk_pct *= 0.35
    elif sl_fraction > 0.10:
        risk_pct *= 0.60
    # (2) the round-trip fee+slippage is part of the real loss at the stop,
    #     so it belongs INSIDE the effective risk per unit (spec §6).
    cost_fraction = 2.0 * (SETTINGS.fee_rate_percent + SETTINGS.slippage_percent) / 100.0
    eff_fraction = sl_fraction + cost_fraction
    desired_risk = account * risk_pct / 100
    leverage = suggested_leverage(score, sl_fraction, style, venue_max_leverage)
    # (3) RR-aware leverage trim: a degraded first target must not ride on
    #     full leverage.
    if tp1 and sl_distance > 0:
        _rr1 = abs(float(tp1) - entry) / sl_distance
        if _rr1 < 1.0:
            leverage = max(1, min(int(leverage), 2))
    desired_notional = desired_risk / eff_fraction

    target_margin_pct = float(plan["margin_pct"])
    if target_margin_pct <= 0:
        return None
    max_margin = account * target_margin_pct / 100
    max_notional = max_margin * leverage
    notional = min(desired_notional, max_notional)
    margin = notional / leverage
    actual_risk = notional * sl_fraction
    actual_risk_pct = actual_risk / account * 100
    eff_risk_pct = notional * eff_fraction / account * 100

    # Legacy callers without structural targets retain a fallback only for UI
    # compatibility. Live v7 candidates always pass their own targets below.
    if tp1 is None or tp2 is None:
        if direction == "LONG":
            tp1, tp2 = entry + sl_distance * 2, entry + sl_distance * 3
        else:
            tp1, tp2 = entry - sl_distance * 2, entry - sl_distance * 3

    return {
        "sl_pct": sl_fraction * 100,
        "cost_pct": cost_fraction * 100,
        "eff_risk_pct": eff_risk_pct,
        "risk_amount": actual_risk,
        "risk_pct": actual_risk_pct,
        "requested_risk_pct": risk_pct,
        "position_size": notional,
        "quantity": notional / entry,
        "leverage": leverage,
        "quality_leverage_cap": plan["leverage_cap"],
        "margin": margin,
        "margin_pct": margin / account * 100,
        "margin_limit_pct": target_margin_pct,
        "tp1": tp1,
        "tp2": tp2,
        "quality": plan["quality"],
        "grade": plan["grade"],
        "max_safe_leverage": max_safe_leverage(sl_fraction, style),
        "margin_capped": desired_notional > max_notional,
    }


def build_money_management(candidate, account: Optional[float] = None) -> Dict:
    account = float(account if account is not None else SETTINGS.account_size)
    position = calculate_position(
        candidate.planned_entry,
        candidate.sl,
        candidate.direction,
        candidate.score,
        account,
        candidate.style,
        candidate.market.get("max_leverage"),
        candidate.tp1,
        candidate.tp2,
    )
    if not position:
        return {}
    # Viva 09-19 ladder ruling: profit display follows the ACTUAL exit ladder
    # (the levels/weights the monitor executes), not the legacy two-target
    # partial settings. tp2_profit = the remaining size at the final target.
    _lad = (getattr(candidate, "metadata", None) or {}).get("target_ladder") or {}
    _tgts = [float(t) for t in (_lad.get("targets") or [])]
    _wts = [float(w) for w in (_lad.get("weights") or [])]
    tp_first = _tgts[0] if _tgts else candidate.tp1
    tp_final = _tgts[-1] if _tgts else candidate.tp2
    w_first = _wts[0] if _wts else SETTINGS.partial_tp1_percent
    w_rest = (100.0 - w_first) if _wts else SETTINGS.partial_tp2_percent
    notional = position["position_size"]
    if candidate.direction == "LONG":
        tp1_move = (tp_first - candidate.planned_entry) / candidate.planned_entry
        tp2_move = (tp_final - candidate.planned_entry) / candidate.planned_entry
    else:
        tp1_move = (candidate.planned_entry - tp_first) / candidate.planned_entry
        tp2_move = (candidate.planned_entry - tp_final) / candidate.planned_entry
    gross_tp1 = notional * tp1_move * w_first / 100
    gross_tp2 = notional * tp2_move * w_rest / 100
    estimated_cost = notional * (SETTINGS.fee_rate_percent + SETTINGS.slippage_percent) / 100 * 2
    return {
        **position,
        "account": account,
        "partial_tp1": w_first,
        "partial_tp2": w_rest,
        "tp1_profit": gross_tp1 - estimated_cost * w_first / 100,
        "tp2_profit": gross_tp2 - estimated_cost * w_rest / 100,
        "total_profit": gross_tp1 + gross_tp2 - estimated_cost,
        "estimated_roundtrip_cost": estimated_cost,
        "max_loss_with_cost": position["risk_amount"] + estimated_cost,
    }
