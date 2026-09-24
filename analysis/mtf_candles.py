"""Non-blocking multi-timeframe candlestick intelligence for VIVA.

This module is evidence-only: it never creates or rejects a setup. It reads
closed candles on multiple frames, checks them against important local/HTF
levels, and returns human-readable evidence so a chart/app user can see why a
confirmation may come from another timeframe.
"""
from __future__ import annotations

from typing import Dict, Optional
import pandas as pd

TF_ORDER = ("1d", "4h", "1h", "30m", "15m", "5m", "3m", "1m")


def _candle(o, h, l, c):
    rng = max(float(h) - float(l), 1e-12)
    body = abs(float(c) - float(o))
    top, bot = max(float(o), float(c)), min(float(o), float(c))
    return {
        "range": rng, "body": body,
        "body_frac": body / rng,
        "upper_wick": float(h) - top,
        "lower_wick": bot - float(l),
        "bull": float(c) > float(o), "bear": float(c) < float(o),
        "close": float(c), "open": float(o), "high": float(h), "low": float(l),
    }


def _near(level: Optional[float], price: float, atr: float, mult: float = 0.75) -> bool:
    return bool(level and atr > 0 and abs(price - level) <= mult * atr)


def _levels(df: pd.DataFrame):
    tail = df.tail(80)
    atr = float((tail["high"] - tail["low"]).tail(14).mean() or 0)
    highs = tail["high"].astype(float)
    lows = tail["low"].astype(float)
    return atr, float(highs.max()), float(lows.min())


def _describe(tf: str, c: dict, prev: Optional[dict], direction: str, near_support: bool, near_resistance: bool):
    names = []
    if c["body_frac"] <= 0.15:
        names.append("Doji")
    if c["body_frac"] >= 0.75 and c["upper_wick"] <= 0.12*c["range"] and c["lower_wick"] <= 0.12*c["range"]:
        names.append("Marubozu")
    if prev:
        if c["bull"] and prev["bear"] and c["body"] >= prev["body"] * 1.05 and c["close"] >= prev["open"] and c["open"] <= prev["close"]:
            names.append("Bullish Engulfing")
        if c["bear"] and prev["bull"] and c["body"] >= prev["body"] * 1.05 and c["open"] >= prev["close"] and c["close"] <= prev["open"]:
            names.append("Bearish Engulfing")
    if c["lower_wick"] >= 2.0 * max(c["body"], 1e-12) and c["body_frac"] <= 0.35:
        names.append("Bullish Pin Bar" if c["bull"] or c["close"] >= c["low"] + 0.55*c["range"] else "Lower-Wick Rejection")
    if c["upper_wick"] >= 2.0 * max(c["body"], 1e-12) and c["body_frac"] <= 0.35:
        names.append("Bearish Pin Bar" if c["bear"] or c["close"] <= c["high"] - 0.55*c["range"] else "Upper-Wick Rejection")
    if not names:
        return None
    focus = "حمایت" if near_support else "مقاومت" if near_resistance else "سطح مهم مشخصی"
    dir_fa = "لانگ" if direction == "LONG" else "شورت"
    label = " / ".join(dict.fromkeys(names))
    text = f"{tf.upper()}: {label}"
    if near_support or near_resistance:
        text += f" روی/نزدیک {focus}؛ برای سناریوی {dir_fa} قابل تفسیر است."
    else:
        text += "؛ این الگو در تایم خودش دیده شده و به‌تنهایی تأیید نهایی نیست."
    return {"tf": tf, "pattern": label, "text": text,
            "relevance": "ZONE" if (near_support or near_resistance) else "CONTEXT"}


def analyze_mtf_candles(bundle: Dict, direction: str, trigger_tf: str = "") -> Dict:
    """Return closed-candle evidence across available TFs; never a gate."""
    out = {"items": [], "by_tf": {}, "summary": ""}
    direction = str(direction or "LONG").upper()
    for tf in TF_ORDER:
        df = bundle.get(tf) if bundle else None
        if df is None or len(df) < 25:
            continue
        try:
            d = df.tail(80).copy()
            atr, hi, lo = _levels(d)
            last = d.iloc[-1]
            prev = d.iloc[-2]
            c = _candle(last["open"], last["high"], last["low"], last["close"])
            p = _candle(prev["open"], prev["high"], prev["low"], prev["close"])
            item = _describe(tf, c, p, direction,
                             _near(lo, c["close"], atr), _near(hi, c["close"], atr))
            if item:
                out["items"].append(item); out["by_tf"][tf] = item
        except Exception:
            continue
    if out["items"]:
        preferred = [x for x in out["items"] if x["relevance"] == "ZONE"]
        chosen = preferred[:3] if preferred else out["items"][:3]
        out["summary"] = " | ".join(x["text"] for x in chosen)
    return out


def classic_pattern_explanations(metadata: Dict) -> list[str]:
    """Turn existing render-kit geometry into concise educational evidence."""
    md = metadata or {}
    result = []
    for p in (md.get("render_patterns") or [])[:3]:
        kind = str(p.get("type") or "").upper()
        name = str(p.get("name_fa") or kind)
        rule = str(p.get("rule_fa") or "")
        state = str(p.get("label") or kind)
        if name and rule:
            result.append(f"{name}: {rule} وضعیت فعلی: {state}.")
        elif name:
            result.append(f"{name} — وضعیت: {state}.")
    htf = str(md.get("render_htf_pattern") or "")
    if htf:
        result.append(f"الگوی کلاسیک تایم بالاتر: {htf}؛ این مورد کانتکست است و به‌تنهایی سیگنال جدید نمی‌سازد.")
    return result
