def _clamp(n, lo, hi):
    return max(lo, min(hi, n))


def quality_plan(score: int) -> dict:
    score = int(score or 0)

    if score >= 9:
        return {
            "risk_pct": 2.0,
            "lev_min": 15,
            "lev_max": 20,
            "quality": "عالی",
            "style": "حمله کنترل‌شده"
        }
    if score >= 7:
        return {
            "risk_pct": 1.5,
            "lev_min": 12,
            "lev_max": 15,
            "quality": "خوب",
            "style": "استاندارد حرفه‌ای"
        }
    if score >= 5:
        return {
            "risk_pct": 1.0,
            "lev_min": 8,
            "lev_max": 12,
            "quality": "متوسط",
            "style": "محافظه‌کار"
        }
    if score >= 3:
        return {
            "risk_pct": 0.5,
            "lev_min": 5,
            "lev_max": 8,
            "quality": "ضعیف",
            "style": "تست کوچک"
        }
    return {
        "risk_pct": 0.25,
        "lev_min": 5,
        "lev_max": 5,
        "quality": "خیلی ضعیف",
        "style": "حداقلی"
    }


def max_safe_leverage(sl_pct: float) -> int:
    """
    اهرمی که قبل از رسیدن به SL لیکویید نکند.
    sl_pct به صورت اعشار است (مثلاً 0.01 = 1%).
    """
    if sl_pct <= 0:
        return 5

    theoretical = 1.0 / sl_pct
    safe = int(theoretical * 0.35)
    return _clamp(safe, 5, 20)


def suggested_leverage(score: int, sl_pct: float) -> int:
    plan = quality_plan(score)
    safe = max_safe_leverage(sl_pct)

    if sl_pct <= 0.008:
        wanted = plan["lev_max"]
    elif sl_pct <= 0.015:
        wanted = int((plan["lev_min"] + plan["lev_max"]) / 2)
    else:
        wanted = plan["lev_min"]

    return _clamp(min(wanted, safe), 5, 20)


def calculate_position(entry: float, sl: float, direction: str,
                       score: int, account: float) -> dict:
    sl_distance = abs(entry - sl)
    sl_pct = sl_distance / entry if entry else 0
    if sl_pct <= 0:
        return None

    plan = quality_plan(score)
    risk_pct = plan["risk_pct"]
    risk_amount = account * (risk_pct / 100.0)

    notional = risk_amount / sl_pct
    leverage = suggested_leverage(score, sl_pct)
    margin = notional / leverage
    margin_pct = (margin / account) * 100 if account else 0

    if direction == "LONG":
        tp1 = entry + sl_distance * 2
        tp2 = entry + sl_distance * 3
    else:
        tp1 = entry - sl_distance * 2
        tp2 = entry - sl_distance * 3

    return {
        "sl_pct": sl_pct * 100,
        "risk_amount": risk_amount,
        "risk_pct": risk_pct,
        "position_size": notional,
        "leverage": leverage,
        "margin": margin,
        "margin_pct": margin_pct,
        "tp1": tp1,
        "tp2": tp2,
        "quality": plan["quality"],
        "style": plan["style"],
        "max_safe_leverage": max_safe_leverage(sl_pct),
    }

