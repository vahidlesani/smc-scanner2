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

