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


def calculate_position(
    entry: float,
    sl: float,
    direction: str,
    score: int,
    account: float,
    style: str = "SWING",
    venue_max_leverage: Optional[float] = None,
) -> Optional[Dict]:
    entry = float(entry)
    sl = float(sl)
    account = float(account)
    sl_distance = abs(entry - sl)
    sl_fraction = sl_distance / entry if entry > 0 else 0
    if sl_fraction <= 0 or account <= 0:
        return None

    plan = quality_plan(score)
    risk_pct = plan["risk_pct"]
    if risk_pct <= 0:
        return None
    desired_risk = account * risk_pct / 100
    leverage = suggested_leverage(score, sl_fraction, style, venue_max_leverage)
    desired_notional = desired_risk / sl_fraction

    target_margin_pct = float(plan["margin_pct"])
    if target_margin_pct <= 0:
        return None
    max_margin = account * target_margin_pct / 100
    max_notional = max_margin * leverage
    notional = min(desired_notional, max_notional)
    margin = notional / leverage
    actual_risk = notional * sl_fraction
    actual_risk_pct = actual_risk / account * 100

    if direction == "LONG":
        tp1 = entry + sl_distance * 2
        tp2 = entry + sl_distance * 3
    else:
        tp1 = entry - sl_distance * 2
        tp2 = entry - sl_distance * 3

    return {
        "sl_pct": sl_fraction * 100,
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
    )
    if not position:
        return {}
    notional = position["position_size"]
    if candidate.direction == "LONG":
        tp1_move = (candidate.tp1 - candidate.planned_entry) / candidate.planned_entry
        tp2_move = (candidate.tp2 - candidate.planned_entry) / candidate.planned_entry
    else:
        tp1_move = (candidate.planned_entry - candidate.tp1) / candidate.planned_entry
        tp2_move = (candidate.planned_entry - candidate.tp2) / candidate.planned_entry
    gross_tp1 = notional * tp1_move * SETTINGS.partial_tp1_percent / 100
    gross_tp2 = notional * tp2_move * SETTINGS.partial_tp2_percent / 100
    estimated_cost = notional * (SETTINGS.fee_rate_percent + SETTINGS.slippage_percent) / 100 * 2
    return {
        **position,
        "account": account,
        "partial_tp1": SETTINGS.partial_tp1_percent,
        "partial_tp2": SETTINGS.partial_tp2_percent,
        "tp1_profit": max(0.0, gross_tp1 - estimated_cost * SETTINGS.partial_tp1_percent / 100),
        "tp2_profit": max(0.0, gross_tp2 - estimated_cost * SETTINGS.partial_tp2_percent / 100),
        "total_profit": max(0.0, gross_tp1 + gross_tp2 - estimated_cost),
        "estimated_roundtrip_cost": estimated_cost,
        "max_loss_with_cost": position["risk_amount"] + estimated_cost,
    }
