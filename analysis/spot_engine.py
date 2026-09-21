"""SPOT engine — phase 1 (Viva 09-22: «هیچی از اسپات نگفتی، آماده است؟»).

Rules he fixed for spot, verbatim:

* two families only: **TLBREAK** + **TECHCLASSIC** («تی‌ال‌بریک و تکنیکال کلاسیک»);
* **LONG only**; only **bullish** patterns (falling wedge · descending trendline
  break · ascending/continuation triangle · bullish rectangle) «دقیقا دقیق همین»
  CryptoCove shapes;
* timeframes **4h · 1d · 3d · 1w** (3d/1w are aggregated from the daily tape);
* **LOG scale** chart; pivots extended; supply/demand boxes; a green vertical
  measured-move box (upward, with value + % label) — the box he wants on SPOT
  only (futures charts carry none);
* no lower-timeframe re-watch after the scan; **touch = final warning**,
  **close above the area = confirmation**;
* stop structural behind the last swing, else 12–15%; targets large and
  independent of the stop; volume / smart-money / on-chain may only ADVANCE
  confidence, never gate.

This module produces fully-formed, already-confirmed spot signals: the entry is
the closed candle that broke the shape's upper side, so there is no waiting
state on the spot channel.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

SPOT_TRIGGERS = ("4h", "1d", "3d", "1w")
SPOT_SETUPS = ("TLBREAK", "TECHCLASSIC")

# his band law for these timeframes (round 15): the ladder never sits closer
# than this to the entry, whatever the structure says
MIN_PATH_PCT_BY_TF = {"4h": 5.0, "1d": 5.0, "3d": 6.0, "1w": 8.0}
SPOT_WEIGHTS = (40.0, 30.0, 30.0)


def _atr(df: pd.DataFrame, k: int = 14) -> float:
    try:
        return float((df["high"] - df["low"]).tail(k).mean() or 0.0)
    except Exception:
        return 0.0


def _minor_swing_low(df: pd.DataFrame, lookback: int = 12) -> float:
    """The last swing low the bullish premise would be invalidated behind."""
    try:
        lows = df["low"].astype(float).to_numpy()
        n = len(lows)
        best = float(lows[-lookback:].min())
        for i in range(n - 3, max(2, n - 40), -1):
            if lows[i] <= lows[i - 1] and lows[i] <= lows[i + 1] and \
                    lows[i] <= lows[i - 2] and lows[i] <= lows[i + 2]:
                return float(lows[i]) if float(lows[i]) < best else best
        return best
    except Exception:
        return float(df["low"].tail(lookback).min())


def _upper_edge(pattern: dict, n: int) -> Optional[float]:
    """The pattern's upper side, projected to the newest bar."""
    try:
        lines = pattern.get("lines") or []
        vals = [float(l["slope"]) * n + float(l["intercept"]) for l in lines]
        if not vals:
            return None
        if pattern.get("shape") == "box":
            return float(max(vals))
        return float(max(vals))          # wedges/channels: the upper boundary
    except Exception:
        return None


def bullish_pattern_ok(pattern: dict, close: float, upper: Optional[float]) -> bool:
    """LONG-only filter: the shape must lean bullish, or be neutral and already
    broken to the upside (his «شکست صعودی = تأیید»)."""
    bias = str(pattern.get("bias") or "NEUTRAL").upper()
    if bias == "BULL":
        return True
    if bias == "BEAR":
        return False
    return upper is not None and close > float(upper)


def scan_spot_symbol(symbol: str, frames: Dict[str, pd.DataFrame],
                     buffer_pct: float = 0.10) -> List[dict]:
    """Confirmed spot setups for one symbol across 4h/1d/3d/1w.

    Returns plain dicts (the caller turns them into SignalCandidate rows), each
    already past the «first valid close above the shape» law.
    """
    from analysis.render_kit import detect_patterns
    from analysis.patterns import classify, pattern_info, state_label
    out: List[dict] = []
    if not frames:
        return out
    for tf in SPOT_TRIGGERS:
        df = frames.get(tf)
        if df is None or len(df) < 45:
            continue
        try:
            d = df.reset_index(drop=True)
            atr = _atr(d)
            if atr <= 0:
                continue
            # ── FRESHNESS (spot is a swing engine, not an archive reader): a
            # 4h/1d break must be from the candle that has just closed, and a
            # 3d/1w break is only published at ITS OWN close — otherwise the
            # «entry» would be a days-old price. Everything else stays context.
            try:
                _now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
                _last = pd.Timestamp(d["timestamp"].iloc[-1])
                if _last.tzinfo is not None:
                    _last = _last.tz_convert("UTC").tz_localize(None)
                _tf_hours = {"4h": 4, "1d": 24, "3d": 72, "1w": 168}.get(tf, 24)
                _bucket_end = _last + pd.Timedelta(hours=_tf_hours)
                _age_h = (_now - _bucket_end).total_seconds() / 3600.0
                _limit_h = 24.0 if tf in ("4h", "1d") else 30.0
                if _age_h > _limit_h:
                    continue
            except Exception:
                pass
            close = float(d["close"].iloc[-1])
            n = len(d) - 1
            pats = detect_patterns(d, "LONG")
            for pat in pats:
                if pat.get("child"):
                    continue
                _lns = list(pat.get("lines") or [])
                _shape = str(pat.get("shape") or "single")
                if not _lns:
                    continue
                if _shape in ("converging", "parallel") and len(_lns) < 2:
                    continue                      # half a shape is not a shape
                if _shape == "single":
                    # his list names «شکست خط روند نزولی» explicitly: a single
                    # line only qualifies when it is the RESISTANCE side (a
                    # descending trendline) that price closed above. A broken
                    # support under the price is not a bullish break.
                    if str(_lns[0].get("side") or "").upper() != "HIGH":
                        continue
                upper = _upper_edge(pat, n)
                if not bullish_pattern_ok(pat, close, upper):
                    continue
                eps = 0.02 * atr
                if upper is None or close <= upper + eps:
                    continue                      # no valid close above the area yet
                kind = str(pat.get("type") or "NONE").upper()
                lower_vals = []
                for _l in (pat.get("lines") or []):
                    lower_vals.append(float(_l["slope"]) * n + float(_l["intercept"]))
                sl_struct = _minor_swing_low(d)
                if lower_vals:
                    sl_struct = min(sl_struct, min(lower_vals))
                sl = sl_struct * (1.0 - float(buffer_pct) / 100.0)
                if sl >= close:
                    sl = close * (1.0 - 0.02)
                # targets: the shape's own measured move, never closer than the
                # timeframe's band, always independent of the stop
                measured = close + (upper - min(lower_vals)) if lower_vals else close * 1.06
                floor_path = close * MIN_PATH_PCT_BY_TF.get(tf, 5.0) / 100.0
                path = max(measured - close, floor_path)
                targets = [close + path * f for f in (0.2, 0.6, 1.0)]
                out.append({
                    "symbol": symbol.upper(), "tf": tf, "pattern": kind,
                    "pattern_fa": pattern_info(kind)["fa"],
                    "label": state_label(kind, str(pat.get("break_direction") or "")),
                    "rule_fa": pattern_info(kind)["rule_fa"],
                    "entry": close, "sl": float(sl), "targets": targets,
                    "weights": list(SPOT_WEIGHTS),
                    "path_pct": round(path / close * 100.0, 3),
                    "broken_level": float(upper),
                    "break_bar_ts": str(d["timestamp"].iloc[-1]),
                    "pattern_commands": [pat],
                    "atr": float(atr),
                    "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                })
        except Exception as exc:
            print(f"spot scan warning {symbol} {tf}: {exc}")
            continue
    # one setup per (symbol, tf): the strongest shape (largest path) wins
    best: Dict[tuple, dict] = {}
    for item in out:
        key = (item["symbol"], item["tf"])
        if key not in best or item["path_pct"] > best[key]["path_pct"]:
            best[key] = item
    return list(best.values())


def build_spot_candidate(item: dict):
    """Turn a scan_spot_symbol row into a CONFIRMED SignalCandidate (SPOT).

    The candidate is born confirmed (the break close already happened) and
    carries market=SPOT + log_scale, which is what switches on the LOG axis and
    the green measured-move box — and nothing of that appears on futures.
    """
    from analysis.models import SignalCandidate
    from analysis.trade_management import stop_ceiling_pct
    tf = str(item.get("tf") or "4h").lower()
    entry = float(item["entry"])
    sl = float(item["sl"])
    # the timeframe's own stop ceiling still governs (round 14 table), applied
    # here as the spot engine's arithmetic so the message and the chart agree
    cap = float(stop_ceiling_pct(tf)) / 100.0
    if entry > 0 and sl > 0 and (entry - sl) / entry > cap:
        sl = entry * (1.0 - cap)
    targets = [float(x) for x in (item.get("targets") or [])]
    weights = [float(x) for x in (item.get("weights") or SPOT_WEIGHTS)]
    meta = {
        "market": "SPOT", "engine": "SPOT", "log_scale": True,
        "spot_measured_box": True,
        "atr": float(item.get("atr") or 0.0),
        "pattern_type": str(item.get("pattern") or ""),
        "pattern_state_label": str(item.get("label") or ""),
        "pattern_rule_fa": str(item.get("rule_fa") or ""),
        "render_patterns": list(item.get("pattern_commands") or []),
        "spot_break_bar": str(item.get("break_bar_ts") or ""),
        "spot_broken_level": float(item.get("broken_level") or 0.0),
        "target_ladder": {"targets": targets, "weights": weights,
                          "path_pct": float(item.get("path_pct") or 0.0)},
        "viva_state": "S6_CONFIRMED",
        "technical_confirmation_complete": True,
        "confirmed_snapshot_fa": "سیگنال اسپات روی کلوز معتبر بالای سقف الگو صادر شد.",
    }
    cand = SignalCandidate(
        signal_id=f"viva-spot-{str(item.get('symbol') or '').upper()}-{tf}-"
                  f"{str(item.get('break_bar_ts') or '')[:13].replace(' ', 'T')}",
        symbol=str(item.get("symbol") or "").upper(),
        style={"4h": "SWING", "1d": "GRAND", "3d": "GRAND", "1w": "GRAND"}.get(tf, "SWING"),
        setup_code="TLBREAK" if item.get("pattern") in ("TRENDLINE", "HORIZONTAL_SR")
                    else "TECHCLASSIC",
        setup_name=f"Spot {item.get('pattern_fa') or ''}".strip(),
        strategy_fa=str(item.get("rule_fa") or ""),
        direction="LONG", score=8, status="CONFIRMED",
        entry_zone_bottom=float(item.get("broken_level") or entry),
        entry_zone_top=entry,
        planned_entry=entry, sl=float(sl),
        tp1=targets[0] if targets else entry * 1.05,
        tp2=targets[-1] if targets else entry * 1.10,
        rr_tp1=0.0, rr_tp2=0.0, bias="BULL",
        trigger_timeframe=tf, mandatory_gates={"zone": True},
        created_at=str(item.get("detected_at") or ""),
        confirmed_at=str(item.get("detected_at") or ""),
        metadata=meta,
    )
    return cand


def spot_signals_for(symbol: str, bundle) -> List:
    """Convenience: frames → confirmed spot candidates (LONG, bullish only)."""
    frames = {tf: bundle.get(tf) for tf in SPOT_TRIGGERS}
    return [build_spot_candidate(_it) for _it in scan_spot_symbol(symbol, frames)]
