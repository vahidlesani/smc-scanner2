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
    session_name,
    structure_bias,
)
from analysis.models import EvidenceItem, SignalCandidate, generate_viva_signal_id, utc_now
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


def _fmt(value: float) -> str:
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


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


def _structural_targets(
    context_df: pd.DataFrame, direction: str, entry: float, sl: float
) -> Dict:
    risk = abs(entry - sl)
    ph, pl = pivots(context_df, 3, 3)
    levels = sorted({float(point["price"]) for point in (ph if direction == "LONG" else pl)})
    if direction == "LONG":
        valid = [level for level in levels if level >= entry + 1.5 * risk]
        tp1 = valid[0] if valid else entry + 2.0 * risk
        tp2_options = [level for level in valid if level >= tp1 + 0.5 * risk]
        tp2 = tp2_options[0] if tp2_options else max(entry + 3.0 * risk, tp1 + risk)
    else:
        valid = sorted([level for level in levels if level <= entry - 1.5 * risk], reverse=True)
        tp1 = valid[0] if valid else entry - 2.0 * risk
        tp2_options = [level for level in valid if level <= tp1 - 0.5 * risk]
        tp2 = tp2_options[0] if tp2_options else min(entry - 3.0 * risk, tp1 - risk)
    return {
        "tp1": float(tp1),
        "tp2": float(tp2),
        "rr1": abs(tp1 - entry) / risk if risk else 0,
        "rr2": abs(tp2 - entry) / risk if risk else 0,
    }


def _market_quality(bundle: MarketBundle, style: str) -> Tuple[bool, str, int]:
    ticker = bundle.ticker or {}
    turnover = float(ticker.get("turnover24h", 0) or 0)
    spread = float(ticker.get("spread_pct", 999) or 999)
    relative = float(ticker.get("relative_volume", 1) or 1)
    if style == "SCALP":
        valid = turnover >= SETTINGS.scalp_min_turnover_usd and spread <= SETTINGS.scalp_max_spread_percent
    else:
        valid = turnover >= SETTINGS.watchlist_min_turnover_usd and spread <= SETTINGS.watchlist_max_spread_percent
    points = 1 if valid and (relative >= 1.1 or turnover >= SETTINGS.scalp_min_turnover_usd) else 0
    detail = (
        f"گردش مالی ۲۴ ساعته نماد حدود ${turnover:,.0f}، اسپرد تقریبی {spread:.3f}% "
        f"و حجم نسبی {relative:.2f} برابر میانگین اخیر است. "
        + ("نقدشوندگی برای این نوع معامله قابل قبول ارزیابی شده است." if valid else "نقدشوندگی یا اسپرد هنوز استاندارد لازم برای اجرای معامله را ندارد.")
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
    lower_context_tf = "1h" if style == "SWING" else "15m"
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
    if direction == "LONG":
        sl = float(poi["bottom"]) - 0.25 * atr_value
    else:
        sl = float(poi["top"]) + 0.25 * atr_value
    if entry <= 0 or abs(entry - sl) / entry < 0.0008:
        return None
    targets = _structural_targets(context_df, direction, entry, sl)
    rr_ok = targets["rr1"] >= 1.5 and targets["rr2"] >= 2.2
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
        f"حد ضرر پشت ناحیه و با بافر ATR در {_fmt(sl)} قرار می‌گیرد. هدف اول {_fmt(targets['tp1'])} "
        f"و هدف دوم {_fmt(targets['tp2'])} بر اساس نقدینگی و ساختار مقابل انتخاب شده‌اند. "
        f"نسبت سود به زیان تقریبی اهداف به‌ترتیب {targets['rr1']:.2f}R و {targets['rr2']:.2f}R است."
    )

    evidence = [
        EvidenceItem("htf", "ساختار و موقعیت تایم‌فریم بالاتر", htf_detail, context_aligned and lower_aligned and location_ok, 2),
        special_evidence,
        EvidenceItem("displacement", "Displacement و شکست ساختار", displacement_detail, bool(impulse.get("valid")), 2),
        EvidenceItem("poi", "ناحیه ورود و Freshness", poi_detail, poi.get("touches", 0) <= 1, 2),
        EvidenceItem("rr", "اهداف ساختاری و نسبت سود به زیان", rr_detail, rr_ok, 1),
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
    confirmations.append(f"سشن آخرین کندل بسته‌شده: {last_session}")

    score = min(10, sum(item.points for item in evidence if item.confirmed))
    gates = {
        "htf_alignment": context_aligned and lower_aligned and location_ok,
        special_gate_name: special_gate_value,
        "displacement": bool(impulse.get("valid")),
        "fresh_poi": poi.get("touches", 0) <= 1,
        "rr": rr_ok,
        "market_liquidity": market_ok,
    }
    expiry_hours = SETTINGS.candidate_expiry_hours_swing if style == "SWING" else SETTINGS.candidate_expiry_hours_scalp
    expires = utc_now() + timedelta(hours=expiry_hours)
    signal_id = generate_viva_signal_id(bundle.symbol, style, setup_code)
    return SignalCandidate(
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
            "این تحلیل تا قبل از Retest و بسته‌شدن کندل تأییدی، دستور ورود نیست.",
            f"بسته‌شدن معتبر قیمت آن‌سوی {_fmt(sl)} سناریو را باطل می‌کند.",
        ],
        mandatory_gates=gates,
        market=dict(bundle.ticker or {}),
        metadata={
            "impulse_index": int(impulse.get("index", -1)),
            "structure_level": float(impulse.get("level", 0)),
            "poi_type": poi.get("type", "POI"),
            "atr": atr_value,
            "session": last_session,
            "strategy_version": SETTINGS.strategy_version,
            "touched": poi.get("touches", 0) > 0,
        },
        expires_at=expires.isoformat(timespec="seconds"),
    )


def detect_liquidity_reversal(bundle: MarketBundle, style: str) -> Optional[SignalCandidate]:
    context_tf, trigger_tf = ("4h", "15m") if style == "SWING" else ("1h", "5m")
    middle_tf = "1h" if style == "SWING" else "15m"
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
    context_tf, trigger_tf = ("4h", "15m") if style == "SWING" else ("1h", "5m")
    middle_tf = "1h" if style == "SWING" else "15m"
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
    context_tf, trigger_tf = ("4h", "15m") if style == "SWING" else ("1h", "5m")
    middle_tf = "1h" if style == "SWING" else "15m"
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
    context_tf, trigger_tf = ("4h", "15m") if style == "SWING" else ("1h", "5m")
    middle_tf = "1h" if style == "SWING" else "15m"
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
    context_tf, trigger_tf = ("4h", "15m") if style == "SWING" else ("1h", "5m")
    middle_tf = "1h" if style == "SWING" else "15m"
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


def scan_setups(bundle: MarketBundle, style: str) -> List[SignalCandidate]:
    candidates: List[SignalCandidate] = []
    for detector in DETECTORS:
        try:
            result = detector(bundle, style)
            if result and result.score >= SETTINGS.educational_min_score:
                candidates.append(result)
        except Exception as exc:
            print(f"Setup detector error {detector.__name__} {bundle.symbol} {style}: {exc}")
    # Avoid several highly correlated messages from the same move: keep the two strongest,
    # preferring execution-ready candidates and then score/RR.
    candidates.sort(key=lambda c: (c.execution_ready, c.score, c.rr_tp1), reverse=True)
    return candidates[:2]
