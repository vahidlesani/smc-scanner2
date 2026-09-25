"""Non-blocking multi-timeframe candlestick intelligence for VIVA.

This module is evidence-only: it never creates or rejects a setup. It reads
closed candles on multiple frames, checks them against important local/HTF
levels, and returns human-readable evidence so a chart/app user can see why a
confirmation may come from another timeframe.
"""
from __future__ import annotations

from typing import Dict, Optional
import pandas as pd

TF_ORDER = ("1w", "3d", "1d", "12h", "8h", "4h", "1h", "30m", "15m", "5m", "3m", "1m")


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
    # R31.7 audit #6: a pin has ONE long wick — the opposite wick is capped
    # (a long-legged doji used to be labelled bullish AND bearish pin).
    if c["lower_wick"] >= 2.0 * max(c["body"], 1e-12) and c["body_frac"] <= 0.35 \
            and c["upper_wick"] <= 0.30 * c["range"]:
        names.append("Bullish Pin Bar" if c["bull"] or c["close"] >= c["low"] + 0.55*c["range"] else "Lower-Wick Rejection")
    if c["upper_wick"] >= 2.0 * max(c["body"], 1e-12) and c["body_frac"] <= 0.35 \
            and c["lower_wick"] <= 0.30 * c["range"]:
        names.append("Bearish Pin Bar" if c["bear"] or c["close"] <= c["high"] - 0.55*c["range"] else "Upper-Wick Rejection")
    if not names:
        return None
    focus = "حمایت" if near_support else "مقاومت" if near_resistance else "سطح مهم مشخصی"
    dir_fa = "لانگ" if direction == "LONG" else "شورت"
    label = " / ".join(dict.fromkeys(names))
    text = f"{tf.upper()}: {label}"
    # R31.7 audit #7: the sentence used to call EVERY candle «قابل تفسیر برای
    # سناریوی لانگ/شورت» — a Bearish Engulfing under a LONG included.
    _bull = {"Bullish Engulfing", "Bullish Pin Bar", "Lower-Wick Rejection"}
    _bear = {"Bearish Engulfing", "Bearish Pin Bar", "Upper-Wick Rejection"}
    if "Marubozu" in names:
        (_bull if c["bull"] else _bear).add("Marubozu")
    _nb, _ns = any(x in _bull for x in names), any(x in _bear for x in names)
    bias = "BULL" if _nb and not _ns else "BEAR" if _ns and not _nb else "NEUTRAL"
    against = (bias == "BEAR" and direction == "LONG") or (bias == "BULL" and direction == "SHORT")
    if (near_support or near_resistance) and against:
        text += f" روی/نزدیک {focus}؛ این کندل خلافِ سناریوی {dir_fa} است — هشدار، نه تأیید."
    elif (near_support or near_resistance) and bias == "NEUTRAL":
        text += f" روی/نزدیک {focus}؛ کندلِ بی‌طرف/تردید — منتظر کندل بعدی."
    elif near_support or near_resistance:
        text += f" روی/نزدیک {focus}؛ برای سناریوی {dir_fa} قابل تفسیر است."
    else:
        text += "؛ این الگو در تایم خودش دیده شده و به‌تنهایی تأیید نهایی نیست."
    source = (
        "DIRECT" if tf in ("1d", "4h", "15m", "5m", "3m", "1m")
        else "RESAMPLED"
    )
    return {"tf": tf, "pattern": label, "text": text, "bias": bias,
            "relevance": "ZONE" if (near_support or near_resistance) else "CONTEXT",
            "source": source}


def analyze_mtf_candles(bundle: Dict, direction: str, trigger_tf: str = "") -> Dict:
    """Return closed-candle evidence across available TFs; never a gate."""
    out = {"items": [], "by_tf": {}, "summary": ""}
    direction = str(direction or "LONG").upper()
    _bundle = dict(bundle or {})
    # Macro context is derived from closed daily candles so 3D/weekly structure
    # can explain a daily setup even when the venue has no native 3D/1W feed.
    try:
        d1 = _bundle.get("1d")
        if d1 is not None and len(d1) >= 21:
            _d = d1.copy()
            _d["timestamp"] = pd.to_datetime(_d["timestamp"])
            _d = _d.set_index("timestamp").sort_index()
            # R31.7 audit #5: daily rows are stamped with their OPEN time, so
            # bins are left-closed/left-labelled; weekly candles start on
            # MONDAY (exchange convention, not "7 days from the data start"),
            # 3D bins are epoch-anchored (stable as the window slides), and
            # an incomplete (still-forming) bucket is dropped.
            for tf, rule, need, kw in (("3d", "3D", 3, {"origin": "epoch"}),
                                       ("1w", "W-MON", 7, {})):
                _rs = _d.resample(rule, label="left", closed="left", **kw)
                _a = _rs.agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
                _a = _a[_rs["close"].count().reindex(_a.index).fillna(0) >= need].dropna()
                if len(_a) >= 8:
                    _a = _a.reset_index()
                    _bundle[tf] = _a
    except Exception:
        pass
    # TF_ORDER already contains 3d/1w; do not append them a second time.
    for tf in TF_ORDER:
        df = _bundle.get(tf) if _bundle else None
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
        trigger_items = [x for x in out["items"] if x["tf"] == str(trigger_tf or "").lower()]
        pool = trigger_items + [x for x in preferred if x not in trigger_items]
        chosen = pool[:3] if pool else out["items"][:3]
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
