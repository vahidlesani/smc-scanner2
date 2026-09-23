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

SPOT_TRIGGERS = ("4h", "8h", "12h", "1d", "3d")
SPOT_SETUPS = ("TLBREAK", "TECHCLASSIC")

# ── ROUND 16 DECOUPLING (Viva 09-22, verbatim: «هیچ ارتباطی بین ستاپ‌های
# فیوچرز و اسپات نباید وجود داشته باشه»): the spot engine must never share a
# setup identity with the futures five — the previous phase wrongly stamped
# spot rows as TLBREAK/TECHCLASSIC, which collides with the futures licence
# keys on the same (symbol, tf). SPOTBREAK is spot's OWN setup code: its
# licence, chains, dedupe and statistics live in their own namespace. The
# engine only borrows the pattern-LIBRARY helpers (a shared vocabulary, not a
# shared setup).
SPOT_SETUP_CODE = "SPOTBREAK"

# his trigger set for spot (09-22): «۴ساعته · ۸ساعته · ۱۲ساعته · ۱روزه · ۳روزه»
# — the weekly is gone; 8h/12h come native from the venue (Bybit 360/720).

# his band law for these timeframes (round 15): the ladder never sits closer
# than this to the entry, whatever the structure says
MIN_PATH_PCT_BY_TF = {"4h": 5.0, "8h": 5.5, "12h": 6.0, "1d": 5.0, "3d": 6.0}
SPOT_WEIGHTS = (40.0, 30.0, 30.0)

# his stop law for spot (09-22): «استاپ هم ۱۰ درصد خوبه» — the structural stop
# never stretches beyond 10% even on the daily/3-day tape
SPOT_STOP_CAP_PCT = 10.0

_SPOT_STYLE_BY_TF = {"4h": "SWING", "8h": "SWING", "12h": "SWING",
                     "1d": "GRAND", "3d": "GRAND"}


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


def _fresh(d: pd.DataFrame, tf: str) -> bool:
    """The freshness law of round 15 (extracted so the alert ladder obeys the
    same rule): 4h/1d act on the just-closed candle, 3d/1w only at their own
    close — otherwise the «entry» would be a days-old price."""
    try:
        _now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
        _last = pd.Timestamp(d["timestamp"].iloc[-1])
        if _last.tzinfo is not None:
            _last = _last.tz_convert("UTC").tz_localize(None)
        _tf_hours = {"4h": 4, "8h": 8, "12h": 12, "1d": 24, "3d": 72,
                     "1w": 168}.get(tf, 24)
        _bucket_end = _last + pd.Timedelta(hours=_tf_hours)
        _age_h = (_now - _bucket_end).total_seconds() / 3600.0
        _limit_h = 24.0 if tf in ("4h", "8h", "12h", "1d") else 30.0
        return _age_h <= _limit_h
    except Exception:
        return True


def scan_spot_symbol(symbol: str, frames: Dict[str, pd.DataFrame],
                     buffer_pct: float = 0.10) -> List[dict]:
    """Confirmed spot setups for one symbol across 4h/1d/3d/1w.

    Returns plain dicts (the caller turns them into SignalCandidate rows), each
    already past the «first valid close above the shape» law.
    """
    from analysis.render_kit import detect_patterns
    from analysis.patterns import pattern_info, state_label
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
            if not _fresh(d, tf):
                continue
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


def _next_spot_public_code() -> str:
    """His ID format (09-22): VIVA-SPOT-E000000 — a monotonic counter in the
    KV store; a timestamp fallback keeps IDs unique even if the KV hiccups."""
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        cur = int((_g("spot_code_seq", {}) or {}).get("n", 0) or 0) + 1
        _s("spot_code_seq", {"n": cur})
        return f"VIVA-SPOT-E{cur:06d}"
    except Exception:
        return ("VIVA-SPOT-E"
                + datetime.now(timezone.utc).strftime("%H%M%S"))


def build_spot_candidate(item: dict):
    """Turn a scan_spot_symbol row into a CONFIRMED SignalCandidate (SPOT).

    The candidate is born confirmed (the break close already happened) and
    carries market=SPOT + log_scale, which is what switches on the LOG axis and
    the green measured-move box — and nothing of that appears on futures.
    Round 16: the setup identity is SPOTBREAK (never the futures TLBREAK/
    TECHCLASSIC codes) so licences, chains and stats stay fully decoupled, the
    trade tool anchors at the confirming candle, and the stop keeps the 10%
    spot ceiling («استاپ هم ۱۰ درصد خوبه»).
    """
    from analysis.models import SignalCandidate
    tf = str(item.get("tf") or "4h").lower()
    entry = float(item["entry"])
    sl = float(item["sl"])
    # ── Viva 09-22: SPOT's ceiling is HIS 10% law alone («در اسپات تا ۱۰
    # درصد هم باشه ایرادی نداره») — the futures per-TF table (2.75% on 1d …)
    # must never bind the spot engine.
    cap = float(SPOT_STOP_CAP_PCT) / 100.0
    if entry > 0 and sl > 0 and (entry - sl) / entry > cap:
        sl = entry * (1.0 - cap)
    targets = [float(x) for x in (item.get("targets") or [])]
    weights = [float(x) for x in (item.get("weights") or SPOT_WEIGHTS)]
    meta = {
        "market": "SPOT", "engine": "SPOT", "log_scale": True,
        "spot_measured_box": True,
        "public_code": _next_spot_public_code(),
        "atr": float(item.get("atr") or 0.0),
        "pattern_type": str(item.get("pattern") or ""),
        "pattern_state_label": str(item.get("label") or ""),
        "pattern_rule_fa": str(item.get("rule_fa") or ""),
        "render_patterns": list(item.get("pattern_commands") or []),
        "spot_break_bar": str(item.get("break_bar_ts") or ""),
        "tool_entry_ts": str(item.get("break_bar_ts") or ""),
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
        style=_SPOT_STYLE_BY_TF.get(tf, "SWING"),
        setup_code=SPOT_SETUP_CODE,
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


# ═══════════════════════════════════════════════════════════════════════════
# ROUND 16 — the spot ALERT LADDER (Viva 09-22, verbatim):
#   «هشدار نزدیک شدن به شکست یا بریک شدن رو میخوام .. هشدار برخورد اولیه به هر
#    سمتی از ترندهای بالا و پایین هر الگویی رو میخوام .. هشدار شکست هر دو جهت
#    رو میخوام اما چون اسپات هست فقط کلوز بعد از بریک در جهت لانگ تایید
#    سیگنال صعودی است و فقط همین تایید رو میخوام . بقیه فقط هشدار ها و
#    تحلیل های مختصر بشه»
# So: TOUCH (first contact with either side) → NEAR_BREAK (close hugging the
# edge) → BREAK_DOWN (valid bearish close below the shape) are WARNINGS ONLY;
# the upward valid close stays the ONE confirmation (scan_spot_symbol).
# ═══════════════════════════════════════════════════════════════════════════

STAGE_RANK = {"TOUCH": 1, "NEAR_BREAK": 2, "BREAK_DOWN": 3, "CONFIRM": 4}
_ALERT_TTL_H = 24 * 10                      # ladder state lives ten days
_STAGE_COOLDOWN_H = {"TOUCH": 24.0, "NEAR_BREAK": 12.0, "BREAK_DOWN": 0.0}


def _edges_at(pat: dict, n: int) -> tuple:
    """(upper, lower) side values of the shape at bar n. A single-line shape
    only owns the side its line sits on (resistance OR support)."""
    lines = list(pat.get("lines") or [])
    if not lines:
        return None, None
    vals = [float(l["slope"]) * n + float(l["intercept"]) for l in lines]
    if str(pat.get("shape") or "single") == "single":
        side = str(lines[0].get("side") or "").upper()
        return (vals[0], None) if side != "LOW" else (None, vals[0])
    return max(vals), min(vals)


def _stage_for_pattern(pat: dict, d: pd.DataFrame, atr: float, n: int) -> Optional[dict]:
    """One CLOSED candle vs one shape → the strongest alert stage it earns.

    BREAK_DOWN  valid bearish close ≥0.10·ATR beyond the lower side (body ≥0.25·ATR)
    NEAR_BREAK  close within 0.30·ATR of an edge — the break is imminent
    TOUCH       wick reached an edge (≤0.25·ATR) while the close stayed >0.30·ATR inside
    """
    if atr <= 0:
        return None
    upper, lower = _edges_at(pat, n)
    if upper is None and lower is None:
        return None
    o = float(d["open"].iloc[-1])
    c = float(d["close"].iloc[-1])
    h = float(d["high"].iloc[-1])
    l = float(d["low"].iloc[-1])
    eps_break = 0.10 * atr
    eps_wick = 0.25 * atr
    near = 0.30 * atr
    # 1) a valid break DOWN is the loudest event — his «هشدار شکست هر دو جهت»
    if lower is not None and c < lower - eps_break and (o - c) >= 0.25 * atr:
        return {"stage": "BREAK_DOWN", "side": "LOW", "edge": float(lower),
                "gap": float(lower - c)}
    # 2) break watch — close hugging either edge (the closer side wins)
    near_hits = []
    if upper is not None and c <= upper and (upper - c) <= near:
        near_hits.append({"stage": "NEAR_BREAK", "side": "HIGH",
                          "edge": float(upper), "gap": float(upper - c)})
    if lower is not None and c >= lower and (c - lower) <= near:
        near_hits.append({"stage": "NEAR_BREAK", "side": "LOW",
                          "edge": float(lower), "gap": float(c - lower)})
    if near_hits:
        return min(near_hits, key=lambda x: x["gap"])
    # 3) first contact — the wick kissed a side, the close stayed inside
    if upper is not None and abs(h - upper) <= eps_wick and (upper - c) > near:
        return {"stage": "TOUCH", "side": "HIGH", "edge": float(upper),
                "gap": float(upper - c)}
    if lower is not None and abs(l - lower) <= eps_wick and (c - lower) > near:
        return {"stage": "TOUCH", "side": "LOW", "edge": float(lower),
                "gap": float(c - lower)}
    return None


def _structural_high_above(d: pd.DataFrame, close: float,
                           lookback: int = 90) -> Optional[float]:
    """The most recent MAJOR swing high above the price — the CryptoCove box's
    «سقف بعدی ساختاری». None when no such pivot exists in the window."""
    try:
        highs = d["high"].astype(float).to_numpy()
        n = len(highs)
        start = max(3, n - lookback)
        for i in range(n - 3, start - 1, -1):
            if (highs[i] >= highs[i - 1] and highs[i] >= highs[i + 1]
                    and highs[i] >= highs[i - 2] and highs[i] >= highs[i + 2]
                    and float(highs[i]) > close * 1.01):
                return float(highs[i])
        return None
    except Exception:
        return None


def scan_spot_alerts(symbol: str, frames: Dict[str, pd.DataFrame]) -> List[dict]:
    """Pre-confirmation ladder items for one symbol across 4h/1d/3d/1w.

    Returns plain dicts (stage TOUCH / NEAR_BREAK / BREAK_DOWN); publication
    gating lives in the caller (spot_alert_check → send → spot_alert_commit).
    """
    from analysis.render_kit import detect_patterns
    from analysis.patterns import pattern_info
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
            if atr <= 0 or not _fresh(d, tf):
                continue
            n = len(d) - 1
            close = float(d["close"].iloc[-1])
            for pat in detect_patterns(d, "LONG"):
                if pat.get("child"):
                    continue                  # half a shape is not a shape
                _lns = list(pat.get("lines") or [])
                if not _lns:
                    continue
                if str(pat.get("shape") or "single") in ("converging", "parallel") \
                        and len(_lns) < 2:
                    continue
                hit = _stage_for_pattern(pat, d, atr, n)
                if not hit:
                    continue
                kind = str(pat.get("type") or "NONE").upper()
                box_top = _structural_high_above(d, close)
                if box_top:
                    box_top = box_top * 1.01  # «کمی بالاترش»
                try:
                    _v20 = float(d["volume"].tail(20).mean() or 0.0)
                    vol_ratio = (float(d["volume"].iloc[-1]) / _v20) if _v20 > 0 else 0.0
                except Exception:
                    vol_ratio = 0.0
                sig = (f"{symbol.upper()}|{tf}|{kind}|"
                       f"{int(float(_lns[0].get('x0', 0) or 0))}|"
                       f"{int(float(_lns[-1].get('x0', 0) or 0))}")
                out.append({
                    "stage": hit["stage"], "side": hit["side"],
                    "symbol": symbol.upper(), "tf": tf, "pattern": kind,
                    "pattern_fa": pattern_info(kind)["fa"],
                    "rule_fa": pattern_info(kind)["rule_fa"],
                    "close": close, "edge": float(hit["edge"]),
                    "distance_pct": round((float(hit["edge"]) - close)
                                          / close * 100.0, 3),
                    "atr": float(atr), "vol_ratio": round(vol_ratio, 2),
                    "box_top": float(box_top) if box_top else 0.0,
                    "pattern_commands": [pat], "sig": sig,
                    "bar_ts": str(d["timestamp"].iloc[-1]),
                    "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                })
        except Exception as exc:
            print(f"spot ladder warning {symbol} {tf}: {exc}")
            continue
    # strongest stage per shape-signature; never two items for one shape
    best: Dict[str, dict] = {}
    for item in out:
        cur = best.get(item["sig"])
        if cur is None or STAGE_RANK[item["stage"]] > STAGE_RANK[cur["stage"]]:
            best[item["sig"]] = item
    return list(best.values())


def spot_alert_check(item: dict) -> bool:
    """May this ladder item speak? Stage-advance always may; the same stage
    again only after its cooldown AND only on a NEW candle. Reads only — the
    marker is written by spot_alert_commit AFTER a successful send (handoff
    law: never store a dedup marker before the send succeeded)."""
    try:
        from database.bot_kv import get_json as _g
        import time as _t
        now = _t.time()
        state = {k: v for k, v in (_g("spot_alerts", {}) or {}).items()
                 if now - float((v or {}).get("ts", 0)) < _ALERT_TTL_H * 3600.0}
        prev = state.get(str(item.get("sig") or "")) or {}
        rank = STAGE_RANK.get(str(item.get("stage") or ""), 0)
        prev_rank = STAGE_RANK.get(str(prev.get("stage") or ""), 0)
        if not prev:
            return True
        if rank > prev_rank:
            return True
        if rank < prev_rank:
            return False                       # the ladder never walks backward
        cd = float(_STAGE_COOLDOWN_H.get(str(item.get("stage") or ""), 24.0)) * 3600.0
        return (cd > 0.0
                and (now - float(prev.get("ts", 0))) >= cd
                and str(prev.get("bar") or "") != str(item.get("bar_ts") or ""))
    except Exception:
        return False


def spot_alert_commit(item: dict) -> None:
    """Mark the stage as spoken (call only after a successful send)."""
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        import time as _t
        state = _g("spot_alerts", {}) or {}
        state[str(item.get("sig") or "")] = {
            "stage": str(item.get("stage") or ""),
            "rank": STAGE_RANK.get(str(item.get("stage") or ""), 0),
            "ts": _t.time(), "bar": str(item.get("bar_ts") or "")}
        _s("spot_alerts", state)
    except Exception:
        pass


def spot_alert_mark_confirmed(sig: str) -> None:
    """A published spot signal closes the ladder for its shape — the ladder
    never walks backward (CONFIRM outranks every warning)."""
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        import time as _t
        state = _g("spot_alerts", {}) or {}
        state[str(sig or "")] = {"stage": "CONFIRM",
                                 "rank": STAGE_RANK["CONFIRM"],
                                 "ts": _t.time(), "bar": ""}
        _s("spot_alerts", state)
    except Exception:
        pass


def build_spot_alert_candidate(item: dict):
    """A render-only candidate for a ladder warning (NEVER a trade signal):
    the same SPOT chart language from the FIRST warning — log axis, the green
    box riding to the next structural high, the shape's own lines — but no
    long/short tool (that belongs to confirmed charts only)."""
    from analysis.models import SignalCandidate
    stage = str(item.get("stage") or "TOUCH")
    tf = str(item.get("tf") or "4h").lower()
    close = float(item.get("close") or 0.0)
    edge = float(item.get("edge") or 0.0)
    atr = float(item.get("atr") or 0.0)
    top = float(item.get("box_top") or 0.0)
    kind = str(item.get("pattern") or "")
    meta = {
        "market": "SPOT", "engine": "SPOT", "log_scale": True,
        "spot_measured_box": True,
        "spot_box_top": top if top > close else 0.0,
        "spot_alert_stage": stage,
        "spot_alert_side": str(item.get("side") or ""),
        "atr": atr, "pattern_type": kind,
        "pattern_state_label": str(item.get("pattern_fa") or ""),
        "pattern_rule_fa": str(item.get("rule_fa") or ""),
        "render_patterns": list(item.get("pattern_commands") or []),
        "viva_state": "ALERT",
    }
    return SignalCandidate(
        signal_id=(f"viva-spotalert-{str(item.get('symbol') or '').upper()}-"
                   f"{tf}-{stage}-{str(item.get('bar_ts') or '')[:13].replace(' ', 'T')}"),
        symbol=str(item.get("symbol") or "").upper(),
        style=_SPOT_STYLE_BY_TF.get(tf, "SWING"),
        setup_code=SPOT_SETUP_CODE,
        setup_name=f"Spot {item.get('pattern_fa') or ''}".strip(),
        strategy_fa=str(item.get("rule_fa") or ""),
        direction="LONG", score=0, status="WATCH",
        entry_zone_bottom=min(close, edge) - 0.25 * atr,
        entry_zone_top=max(close, edge) + 0.25 * atr,
        planned_entry=close, sl=close * (1.0 - 0.12), tp1=0.0, tp2=0.0,
        rr_tp1=0.0, rr_tp2=0.0, bias="BULL",
        trigger_timeframe=tf, mandatory_gates={},
        created_at=str(item.get("detected_at") or ""), confirmed_at="",
        metadata=meta,
    )
