"""SPOT engine — phase 1 (Viva 09-22: «هیچی از اسپات نگفتی، آماده است؟»).

Rules he fixed for spot, verbatim:

* two families only: **TLBREAK** + **TECHCLASSIC** («تی‌ال‌بریک و تکنیکال کلاسیک»);
* **LONG only**; only **bullish** patterns (falling wedge · descending trendline
  break · ascending/continuation triangle · bullish rectangle) «دقیقا دقیق همین»
  CryptoCove shapes;
* timeframes **4h · 8h · 12h · 1d · 3d · 1w**; 4h/8h are short-term, 12h/1d mid-term, 3d/1w long-term (3d/1w are aggregated from the daily tape);
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

SPOT_SHORT_TFS = ("4h", "8h")
SPOT_MID_TFS = ("12h", "1d")
SPOT_LONG_TFS = ("3d", "1w")
SPOT_TRIGGERS = SPOT_SHORT_TFS + SPOT_MID_TFS + SPOT_LONG_TFS
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

# Spot horizon law: 4h/8h = short, 12h/1d = medium, 3d/1w = long.
# 8h/12h may be locally derived from the 4h structural tape; 3d/1w from 1d.
# This preserves the requested six spot views without changing message IDs/chains.

# his band law for these timeframes (round 15): the ladder never sits closer
# than this to the entry, whatever the structure says
# r57 (Viva: «ترند ۳ روزه شکسته واسش ۳ تا تی پی یک سنی اعلام شده؟؟ تناسب
# کجاست؟»): the path must be PROPORTIONAL to the timeframe — a 3d break
# cannot promise a one-hour move. Bigger candle → bigger honest path.
MIN_PATH_PCT_BY_TF = {"4h": 6.0, "8h": 8.0, "12h": 10.0,
                      "1d": 14.0, "3d": 20.0, "1w": 28.0}
# Viva TP Law 2026-10-08 (his CryptoCove box verdict: TP1/TP2/TP3 =
# 40/50/60% of the green-box path, 30/30/30 shares + 10% runner held
# to the path end) — supersedes the 40/30/30 split of 10-07.
SPOT_WEIGHTS = (30.0, 30.0, 30.0, 10.0)

# his stop law for spot (09-22): «استاپ هم ۱۰ درصد خوبه» — the structural stop
# never stretches beyond 10% even on the daily/3-day tape
SPOT_STOP_CAP_PCT = 10.0

_SPOT_STYLE_BY_TF = {"4h": "SWING", "8h": "SWING", "12h": "SWING",
                     "1d": "GRAND", "3d": "GRAND", "1w": "GRAND"}


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
        from analysis.render_kit import line_y as _ly     # calibrated (log) geometry
        vals = [float(_ly(l, n)) for l in lines]
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
    kind = str(pattern.get("type") or "NONE").upper()
    # CryptoCove Law (Viva 10-03): Breaking ABOVE a descending channel or
    # falling wedge is the classic bullish reversal breakout.
    if kind in ("CHANNEL_DESCENDING", "WEDGE_FALLING", "FALLING_WEDGE") and upper is not None:
        return close > float(upper)
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
        # Strict HTF Freshness: allow signals throughout full bar duration
        # (4h: 4h, 8h: 8h, 12h: 12h, 1d: 24h, 3d: 72h, 1w: 168h)
        _limit_h = float(_tf_hours) if tf in ("4h", "8h", "12h", "1d", "3d", "1w") else float(_tf_hours)
        return _age_h <= _limit_h
    except Exception:
        return True


def spot_risk_levels(close: float, upper: float, lower_vals: list,
                     atr: float, path_abs: float, swing_low: float,
                     df_highs=None) -> dict:
    """r37 (Viva 09-26, «تارگت‌ها احمقانه است گاهی و استاپ هم احمقانه است»).

    STOP — the invalidation is the MINOR SWING the breakout stands on. The
    old code took min(swing, pattern lower edges) which dragged every stop to
    the far pattern base and let the 10% cap print a mechanical «exactly
    −10%» number (DOGE 0.08905). The 10% ceiling law is unchanged; the stop
    just stops being gratuitously far.

    TARGETS — Viva TP Law 2026-10-08 (his CryptoCove verdict, supersedes
    the r37/10-07 structural rungs): TP1/TP2/TP3 are EXACTLY 40/50/60% of
    the green-box path, and 10% of the position is HELD (runner) to the
    path end. Output is always monotone tp1 < tp2 < tp3 < runner.

      close      entry (the confirming close)
      upper      the broken upper edge
      lower_vals pattern line values at the break bar (context only now)
      atr        ATR of the trigger TF (absolute price)
      path_abs   measured-move path in PRICE units (already ≥ TF floor)
      swing_low  minor swing low (absolute price)
      df_highs   iterable of recent highs (defaults to nothing)
    """
    close = float(close)
    path = float(path_abs)
    atr = float(atr) if atr and atr > 0 else path / 4.0
    # ── stop: the RAW minor swing (the caller applies its own buffer) ──
    sl = float(swing_low)
    if not (sl > 0 and sl < close):
        sl = close * (1.0 - 0.02)
    # ── targets: exact box-path fractions (his 10-08 law) ──
    tp1 = close + 0.40 * path
    tp2 = close + 0.50 * path
    tp3 = close + 0.60 * path
    runner = close + path
    return {"sl": float(sl), "targets": [float(tp1), float(tp2), float(tp3)],
            "runner": float(runner)}


def _structural_weight(pat: dict) -> float:
    """r58 SUPERIORITY LAW (Viva: «اگر از دورتر و با کندل‌های بیشتری ببینیم یک
    ترند دیگر بالای قیمت است یا ضلع یک الگو بالای قیمت است، آن معتبرتر است و
    باید ملاک قرار بگیره»): the reference structure is the WIDER-SPAN, MORE-
    TOUCH one — span of the drawn edges × their validated touch count."""
    try:
        x0 = min(float(l.get("x0", 0)) for l in (pat.get("lines") or []))
        x1 = max(float(l.get("x1", 0)) for l in (pat.get("lines") or []))
        touches = sum(len(l.get("points") or []) for l in (pat.get("lines") or []))
        span = max(1.0, x1 - x0)
        return span * max(1.0, float(touches))
    except Exception:
        return 0.0


def _spot_count(tf: str) -> int:
    """R64: the dictated candle count of a spot TF (analysis.candle_counts)."""
    try:
        from analysis.candle_counts import candle_count
        return candle_count(tf, 300)
    except Exception:
        return 300


def _sane_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """r57 (the WLD 3d blank chart): corrupt near-zero placeholder candles
    (OHLC ≈ 1e-9 with real volume) pass every >0 filter, draw invisible
    zero-height candles and crush the price axis. Rows beyond a median band
    are dead data — dropped before ANY scan or render touches them."""
    try:
        d = df.copy()
        med = float(pd.Series(d["close"]).astype(float).median() or 0.0)
        if med > 0:
            d = d[(d["close"].astype(float) > 0.02 * med)
                  & (d["close"].astype(float) < 50.0 * med)]
        return d if len(d) else df
    except Exception:
        return df


def _mtf_bias_fa(frames: Dict[str, pd.DataFrame]) -> List[str]:
    """r57 (his «در اسپات هم تحلیل مولتی تایم فریم فعاله؟ اگر نیست باید بشه»):
    the swing-structure verdict of 4h and 1d, as Persian lines for the spot
    card — data-only, never a gate."""
    out: List[str] = []
    try:
        from analysis.indicators import structure_bias
        _FA = {"BULLISH": "صعودی 🟢", "BEARISH": "نزولی 🔴", "NEUTRAL": "خنثی ⚪️"}
        for tf, name in (("4h", "۴ساعته"), ("1d", "روزانه")):
            f = frames.get(tf)
            if f is None or len(f) < 60:
                continue
            b = structure_bias(f.reset_index(drop=True))
            bias = str(b.get("bias") or "NEUTRAL").upper()
            out.append(f"ساختار تایم‌فریم {name}: {_FA.get(bias, bias)}")
    except Exception:
        pass
    return out


def scan_spot_symbol(symbol: str, frames: Dict[str, pd.DataFrame],
                     buffer_pct: float = 0.10) -> List[dict]:
    """Confirmed spot setups for one symbol across 4h/8h/12h/1d/3d/1w.

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
            d = _sane_ohlcv(df.reset_index(drop=True))
            # R64 CANDLE-COUNT LAW: detect on EXACTLY the candles the chart
            # shows (1d used to scan ~1,480 bars under a 210-bar picture).
            d = d.tail(_spot_count(tf)).reset_index(drop=True)
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
            pats = detect_patterns(d, "LONG", log_axis=True)
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
                # R62-ARENA (audit S1): the bias is the LIBRARY's bias of the
                # named shape when the item carries none (pivot patterns) — a
                # double top / H&S / rising wedge is never a spot LONG.
                _kind62 = str(pat.get("type") or "NONE").upper()
                _pat62 = pat if pat.get("bias") else {**pat, "bias": pattern_info(_kind62).get("bias")}
                if _kind62 in ("DOUBLE_TOP", "HEAD_SHOULDERS", "WEDGE_RISING", "FLAG_BEAR"):
                    continue
                if not bullish_pattern_ok(_pat62, close, upper):
                    continue
                eps = 0.02 * atr
                if upper is None or close <= upper + eps:
                    continue                      # no valid close above the area yet
                kind = str(pat.get("type") or "NONE").upper()
                _rect_fa = None
                if kind == "RANGE" and str(pat.get("break_direction") or "") != "DOWN":
                    _rect_fa = "مستطیل صعودی (شکست سقف رنج)"
                lower_vals = []
                for _l in (pat.get("lines") or []):
                    from analysis.render_kit import line_y as _ly2
                    lower_vals.append(float(_ly2(_l, n)))
                # r37: stop = minor swing − buffer (NOT the far pattern base,
                # which only dragged every stop to the 10% cap); targets anchor
                # on real overhead resistance — see spot_risk_levels.
                sl_struct = _minor_swing_low(d)
                measured = close + (upper - min(lower_vals)) if lower_vals else close * 1.06
                floor_path = close * MIN_PATH_PCT_BY_TF.get(tf, 5.0) / 100.0
                path = max(measured - close, floor_path)
                _risk = spot_risk_levels(
                    close, upper, lower_vals, atr, path, sl_struct,
                    df_highs=list(d["high"].tail(120)))
                sl = _risk["sl"] * (1.0 - float(buffer_pct) / 100.0)
                if sl >= close:
                    sl = close * (1.0 - 0.02)
                targets = _risk["targets"]
                # ── R65 A1 BREAK-BAR TRUTH: the entry/`tool_entry_ts` is the
                # candle that PRINTED the break, not merely «the newest close».
                # When the break is up to one bar old (the legal freshness
                # window) the picture now carries the real break bar and the
                # bars-since-break number, so nothing downstream can dress a
                # second-day price as «the break close».
                try:
                    _beps = 0.02 * atr
                    _bbar = find_break_bar(d, float(upper), _beps, lookback=6)
                    _bts = (str(d["timestamp"].iloc[_bbar]) if _bbar is not None
                            else str(d["timestamp"].iloc[-1]))
                    _bsb = (len(d) - 1 - int(_bbar)) if _bbar is not None else None
                except Exception:
                    _bts, _bsb = str(d["timestamp"].iloc[-1]), None
                # ── R65 BREAK MARKER TRUTH (found on the probe chart): the spot
                # painter draws the SCAN's own line dicts (chart ≡ trade), but
                # their bar indices live in the detection window while the
                # picture may be shorter — so the broken edge ran SOLID to the
                # live candle with no break marker (a descending trendline that
                # had already broken looked live). The exact break bar (time +
                # index, both of THIS frame) is stamped on the broken side, and
                # the painter's timestamp path takes over from there.
                try:
                    _bbar_i = find_break_bar(d, float(upper), 0.02 * atr, lookback=6) \
                        if upper is not None else None
                    if _bbar_i is not None:
                        for _cmd in (_pat62, pat):
                            for _ln2 in (_cmd.get("lines") or []):
                                if str(_ln2.get("side") or "").upper() == "HIGH":
                                    _ln2["break_ts"] = str(d["timestamp"].iloc[_bbar_i])
                                    _ln2["break_x"] = int(_bbar_i)
                except Exception:
                    pass
                # ── R65 BREAK RECENCY (his 3-day-late confirmation): the
                # publish must belong to the break bar (or the very next close)
                # and must not chase — anything older/أبعد belongs to the
                # retest lanes, not to a fresh-break confirmation.
                _chase = (close - float(upper)) / atr if atr > 0 else 99.0
                if not spot_break_recency_ok(_bsb, _chase):
                    if len(SPOT_BREAK_BLOCKS) < 200:
                        SPOT_BREAK_BLOCKS.append(
                            f"{symbol}|{tf}|age={_bsb}|chase={_chase:.1f}atr")
                    continue
                out.append({
                    "symbol": symbol.upper(), "tf": tf, "pattern": kind,
                    "horizon": ("SHORT" if tf in SPOT_SHORT_TFS else "MID" if tf in SPOT_MID_TFS else "LONG"),
                    "pattern_fa": (_rect_fa or pattern_info(kind)["fa"]),
                    "label": state_label(kind, str(pat.get("break_direction") or "")),
                    "rule_fa": pattern_info(kind)["rule_fa"],
                    "entry": close, "sl": float(sl), "targets": targets,
                    "runner": float(_risk.get("runner") or 0.0),
                    "weights": list(SPOT_WEIGHTS),
                    "path_pct": round(path / close * 100.0, 3),
                    "broken_level": float(upper),
                    "break_bar_ts": _bts,
                    "break_close": close,
                    "bars_since_break": _bsb,
                    "pattern_commands": [pat],
                    "atr": float(atr),
                    "mtf_fa": _mtf_bias_fa(frames),
                    "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                })
        except Exception as exc:
            print(f"spot scan warning {symbol} {tf}: {exc}")
            continue
    # one setup per (symbol, tf): r58 SUPERIORITY — the most VALID structure
    # (span × touches) is the reference; path breaks the tie. «معتبرتر ملاک».
    best: Dict[tuple, dict] = {}
    for item in out:
        key = (item["symbol"], item["tf"])
        _w = _structural_weight((item.get("pattern_commands") or [{}])[0])
        item["_weight"] = _w
        if key not in best or (_w, item["path_pct"]) > (
                best[key]["_weight"], best[key]["path_pct"]):
            best[key] = item
    return [b for b in best.values()]


# ── R65 SPOT URGENCY (Viva 10-02, verbatim): «ترند سه روزه چرا بعد از بریک
# تایید سیگنال نکرده و سه روز بعد تایید کرده؟ … باید بعد از بریک ناحیه و کلوز
# تایم تریگر خارج از ترندلاین یا ترند الگو که بریک شد تایید ورود صادر بشه …
# حتی اگر شرایط مهیا بود حتی قبل از کلوز تایم تریگر، بشرط اینکه قیمت بالای ناحیه
# بریک شده باشه، تایید پوزیشن داده».
# ONE step below every spot timeframe — the frame whose close is allowed to
# confirm the break without waiting for the pattern TF's own close:
#   4h←1h · 8h←1h · 12h←4h · 1d←4h · 3d←1d · 1w←1d
SPOT_CONFIRM_TF = {"4h": "1h", "8h": "4h", "12h": "4h", "1d": "4h",
                   "3d": "1d", "1w": "1d"}


# R65 BREAK-RECENCY LEDGER: spot breaks refused because the break was old
# (the «سه روز بعد تایید کرده» case) or the price had already run too far past
# the broken edge. Visible bookkeeping — a refusal is a decision, not a drop.
SPOT_BREAK_BLOCKS: List[str] = []
SPOT_BREAK_MAX_AGE_BARS = 1      # the break bar itself, or its immediate next
SPOT_BREAK_MAX_CHASE_ATR = 1.6   # entry never more than this many ATR past
                                 # the edge (≈ his own config's swing cap)


def drain_spot_break_blocks() -> List[str]:
    out = list(SPOT_BREAK_BLOCKS)
    SPOT_BREAK_BLOCKS.clear()
    return out


def spot_break_recency_ok(bars_since_break, chase_atr: float) -> bool:
    """Viva 10-02: a confirmation is the BREAK's own close — an entry quoted
    N bars (or days) later at a price already gone is the «سه روز بعد تایید
    کرده» bug. Fresh break (0-1 bars) and no chase (≤1 ATR past the edge) are
    the two conditions; the retest lanes keep ownership of everything older."""
    try:
        if bars_since_break is None:
            return False
        if int(bars_since_break) > int(SPOT_BREAK_MAX_AGE_BARS):
            return False
        return abs(float(chase_atr)) <= float(SPOT_BREAK_MAX_CHASE_ATR)
    except Exception:
        return False


def spot_confirm_tf(tf: str) -> Optional[str]:
    return SPOT_CONFIRM_TF.get(str(tf or "").lower())


# ── R65 SPOT TOHOM (Viva 10-02, verbatim: «تایید اسپات با موتور توهم هوشمند
# میتونه زودتر از کلوز تایم تریگر تایید ورود بده»): the smart engine reads the
# frame ONE STEP BELOW THE CONFIRM TF, so while the confirm candle is still
# forming, its closed sub-candles may confirm the entry — hours (1d/3d/1w) or
# minutes (4h) before the confirm candle itself closes.
SPOT_TOHOM_SUB = {"1h": "15m", "4h": "1h", "1d": "4h"}


def spot_tohom_tf(want_tf: str) -> Optional[str]:
    """The sub frame the smart (TOHOM) engine reads for a spot trigger TF."""
    ctf = SPOT_CONFIRM_TF.get(str(want_tf or "").lower())
    return SPOT_TOHOM_SUB.get(str(ctf or "").lower()) if ctf else None


def find_break_bar(d: pd.DataFrame, edge: float, eps: float,
                   lookback: int = 6) -> Optional[int]:
    """Index of the FIRST closed bar whose close cleared ``edge`` by ``eps``,
    searched inside the last ``lookback`` bars (the break bar — the candle the
    entry belongs to). None when no bar in the window broke the edge."""
    try:
        closes = d["close"].astype(float).to_numpy()
        n = len(closes)
        for i in range(max(0, n - lookback), n):
            if closes[i] > edge + eps:
                return int(i)
        return None
    except Exception:
        return None


def _edge_at_frac_index(pat: dict, x: float) -> Optional[float]:
    """The shape's UPPER side projected to a FRACTIONAL bar index ``x`` of the
    pattern frame (so a 1h close can be judged against a 4h-fitted edge)."""
    lines = list(pat.get("lines") or [])
    if not lines:
        return None
    try:
        from analysis.render_kit import line_y as _ly
        vals = [float(_ly(l, float(x))) for l in lines]
        return float(max(vals))
    except Exception:
        return None


SPOT_TF_MIN = {"4h": 240.0, "8h": 480.0, "12h": 720.0, "1d": 1440.0,
               "3d": 4320.0, "1w": 10080.0}


def lock_spot_snapshot(cand) -> str:
    """R65 SPOT DETECTION SNAPSHOT (Viva 10-02, verbatim: «در اسپات وقتی یک ترند
    یا الگو شناسایی میشه باید اسنپ‌شات بشه تا تکلیفش یا با شکست و بریک شدن
    تایید بشه یا اینکه ریجکت بشه و هشدار و پیامش بیاد»).

    The chain's drawn geometry is stamped into the per-code snapshot the MOMENT
    the chain is born (detection/publish), not at its first render: every later
    chart — the confirmation, the updates, the rejection alert — restores
    exactly this geometry, so the fate is judged and shown on ONE unchanged
    picture. Fail-open (KV down = the r63 stamp at first render still covers
    it). Returns "STAMPED" / "RESTORED" / "".
    """
    try:
        from analysis.snapshot_lock import lock_render_geometry
        return str(lock_render_geometry(cand) or "")
    except Exception:
        return ""


def _spot_bull_shapes(pats: list, price: float, x_index: float,
                      eps: float = 0.0):
    """The ONE shape-filter ladder of the spot lane: yields (pattern, upper)
    for every BULLISH shape whose upper edge at ``x_index`` price has cleared
    (single lines only when they are the resistance side; bearish families are
    refused — a rising wedge / double top is never a spot LONG)."""
    from analysis.patterns import pattern_info
    for pat in pats:
        if pat.get("child"):
            continue
        _shape = str(pat.get("shape") or "single")
        _lns = list(pat.get("lines") or [])
        if not _lns:
            continue
        if _shape in ("converging", "parallel") and len(_lns) < 2:
            continue
        if _shape == "single" and str(_lns[0].get("side") or "").upper() != "HIGH":
            continue
        _kind = str(pat.get("type") or "NONE").upper()
        if _kind in ("DOUBLE_TOP", "HEAD_SHOULDERS", "WEDGE_RISING", "FLAG_BEAR"):
            continue
        # Viva Doctrine 2026-10-08 (his «الگوی فلگ هرگز علت تایید نیست»):
        # no flag/pennant of either direction ever confirms a spot LONG.
        if _kind.startswith("FLAG") or _kind.startswith("PENNANT"):
            continue
        upper = _edge_at_frac_index(pat, x_index)
        if upper is None or price <= upper + eps:
            continue
        _biased = pat if pat.get("bias") else {**pat,
                                               "bias": pattern_info(_kind).get("bias")}
        if not bullish_pattern_ok(_biased, price, upper):
            continue
        yield pat, float(upper)


def _spot_sub_frame(sub_df: pd.DataFrame):
    """Sanitized sub frame + its closed-bar freshness in minutes."""
    from analysis.confirm_r62 import frame_minutes
    sub = _sane_ohlcv(sub_df.reset_index(drop=True)).reset_index(drop=True)
    bar_min = frame_minutes(sub) or 15.0
    return sub, float(bar_min)


def scan_spot_tohom_confirms(symbol: str, frames: Dict[str, pd.DataFrame],
                             want_tf: str, shape: Optional[dict] = None) -> List[dict]:
    """SMART (TOHOM) confirmation for a spot chain — Viva 10-02.

    The shape lives on ``want_tf``; its confirm TF is one step below; the smart
    engine reads ONE STEP BELOW THE CONFIRM TF, so the entry can confirm while
    the confirm candle is STILL FORMING (its closed sub-candles carry the
    evidence: directional closes beyond the broken edge, a noticeable volume
    jump and a supportive candle pattern). This is strictly EARLIER than
    ``scan_spot_urgent_confirms`` (which waits for the confirm candle itself)
    and far earlier than the trigger-TF close — the «سه روز بعد» delay dies
    here. Fail-closed: the engine may only ADD a confirmation the close law
    would grant later, never invent one.
    """
    from analysis.render_kit import detect_patterns
    from analysis.patterns import pattern_info, state_label
    from analysis.tohom import evaluate_tohom_confirmation
    out: List[dict] = []
    sub_tf = spot_tohom_tf(want_tf)
    if not sub_tf:
        return out
    pat_df = frames.get(want_tf)
    sub_df = frames.get(sub_tf)
    if pat_df is None or sub_df is None or len(pat_df) < 45 or len(sub_df) < 25:
        return out
    d = _sane_ohlcv(pat_df.reset_index(drop=True)).tail(
        _spot_count(want_tf)).reset_index(drop=True)
    atr = _atr(d)
    if atr <= 0 or len(d) < 45:
        return out
    sub, bar_min = _spot_sub_frame(sub_df)
    # the last closed sub candle must belong to NOW (≤2.5 of its own bars)
    try:
        _last = pd.Timestamp(sub["timestamp"].iloc[-1])
        _now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
        if _last.tzinfo is not None:
            _last = _last.tz_convert("UTC").tz_localize(None)
        if (_now - (_last + pd.Timedelta(minutes=bar_min))).total_seconds() / 60.0 \
                > 2.5 * bar_min:
            return out
    except Exception:
        pass
    # SNAPSHOT LAW: a shape stored by the ladder is judged AS DETECTED — the
    # live detector may pick different pivots on a shifted window, and a spot
    # chain's fate must belong to the drawing it was born with.
    pats = [shape] if shape else detect_patterns(d, "LONG", log_axis=True)
    if not pats:
        return out
    n_pat = len(d) - 1
    tf_min = SPOT_TF_MIN.get(want_tf, 1440.0)
    c_sub = float(sub["close"].iloc[-1])
    eps = 0.02 * atr
    _open_now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
    trigger_open = _open_now.floor(pd.Timedelta(minutes=tf_min))
    for pat, upper in _spot_bull_shapes(pats, c_sub, float(n_pat), eps):
        _kind = str(pat.get("type") or "NONE").upper()
        _lns = list(pat.get("lines") or [])
        _lower = []
        for _l in _lns:
            from analysis.render_kit import line_y as _ly3
            _lower.append(float(_ly3(_l, n_pat)))
        _sl_struct = _minor_swing_low(d)
        _measured = (c_sub + (float(upper) - min(_lower))) if _lower else c_sub * 1.06
        _floor = c_sub * MIN_PATH_PCT_BY_TF.get(want_tf, 5.0) / 100.0
        _path = max(_measured - c_sub, _floor)
        # ── Viva TOHOM Doctrine 2026-10-08 (his pre-close law): the spot
        # smart lane confirms ONLY with (touch≥2 on the break edge) + (sane
        # slope: the R68 vertical law) + (shock: last sub-volume ≥ 2.0× its
        # 20-bar mean) + (displacement: last sub-body ≥ 1.0× sub-ATR).
        # Fail-closed with a visible reason.
        _brk1008 = next((_l for _l in _lns
                         if str(_l.get("side") or "").upper() == "HIGH"), None)
        if _brk1008 is not None:
            if "points" in _brk1008 and len(list(_brk1008.get("points") or [])) < 2:
                print(f"spot tohom block {symbol} {want_tf}: touch<2")
                continue
            try:
                if _brk1008.get("log_fit"):
                    if abs(float(_brk1008.get("log_slope") or 0.0)) > 0.025:
                        print(f"spot tohom block {symbol} {want_tf}: slope")
                        continue
                elif atr > 0 and abs(float(_brk1008.get("slope") or 0.0)) > 2.2 * atr:
                    print(f"spot tohom block {symbol} {want_tf}: slope")
                    continue
            except Exception:
                pass
        try:
            _sv1008 = sub["volume"].astype(float).to_numpy()
            _base1008 = float(_sv1008[-21:-1].mean()) if len(_sv1008) >= 22 else 0.0
            _shock1008 = (float(_sv1008[-1]) / _base1008) if _base1008 > 0 else 0.0
        except Exception:
            _shock1008 = 0.0
        if _shock1008 < 2.0:
            print(f"spot tohom block {symbol} {want_tf}: shock={_shock1008:.2f}")
            continue
        try:
            _sr1008 = float((sub["high"] - sub["low"]).astype(float).tail(14).mean())
            _body1008 = abs(float(sub["close"].iloc[-1]) - float(sub["open"].iloc[-1]))
        except Exception:
            _sr1008, _body1008 = 0.0, 0.0
        if not (_sr1008 > 0 and _body1008 >= 1.0 * _sr1008):
            print(f"spot tohom block {symbol} {want_tf}: displacement")
            continue
        base_item = {
            "symbol": symbol.upper(), "tf": want_tf, "pattern": _kind,
            "horizon": ("SHORT" if want_tf in SPOT_SHORT_TFS
                        else "MID" if want_tf in SPOT_MID_TFS else "LONG"),
            "pattern_fa": pattern_info(_kind)["fa"],
            "label": state_label(_kind, "UP"),
            "rule_fa": pattern_info(_kind)["rule_fa"],
            "entry": c_sub, "sl": c_sub * 0.98,
            "targets": [c_sub * 1.05, c_sub * 1.10],
            "weights": list(SPOT_WEIGHTS), "path_pct": round(_path / c_sub * 100.0, 3),
            "broken_level": float(upper), "pattern_commands": [pat],
            "atr": float(atr), "mtf_fa": _mtf_bias_fa(frames),
            "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            cand = build_spot_candidate(base_item)
        except Exception:
            continue
        # the smart engine judges the SAME edge the trade uses
        cand.entry_zone_top = float(upper)
        cand.entry_zone_bottom = float(min(_lower) if _lower else c_sub * 0.98)
        cand.metadata["atr"] = float(atr)
        try:
            ok, cand2, why = evaluate_tohom_confirmation(
                cand, sub, trigger_open=trigger_open, sub_tf=sub_tf)
        except Exception:
            continue
        if not ok:
            continue
        md2 = cand2.metadata or {}
        entry = float(md2.get("tohom_confirm_close") or c_sub)
        if not spot_break_recency_ok(0, (entry - float(upper)) / atr if atr else 99.0):
            continue
        _risk = spot_risk_levels(entry, float(upper), _lower, atr, _path,
                                 _sl_struct, df_highs=list(d["high"].tail(120)))
        sl = float(_risk["sl"]) * (1.0 - 0.10 / 100.0)
        if sl >= entry:
            sl = entry * 0.98
        item = dict(base_item)
        item.update({
            "entry": entry, "sl": float(sl),
            "targets": list(_risk["targets"]),
            "runner": float(_risk.get("runner") or 0.0),
            "path_pct": round((max(_path, entry - float(upper))) / entry * 100.0, 3),
            "break_bar_ts": str(sub["timestamp"].iloc[-1]),
            "confirm_bar_ts": str(md2.get("tohom_confirm_bar")
                                  or sub["timestamp"].iloc[-1]),
            "urgent_confirm": True, "tohom_confirm": True,
            "confirm_tf": sub_tf,
            "confirm_candle_fa": f"تأیید زودهنگام توهم ({md2.get('tohom_pattern') or 'الگوی موافق'})",
            "tohom_note_fa": str(md2.get("tohom_note_fa") or why),
        })
        out.append(item)
    best: Dict[str, dict] = {}
    for item in out:
        key = (item["symbol"], item["tf"])
        _w = _structural_weight((item.get("pattern_commands") or [{}])[0])
        if key not in best or _w > best[key]["_w"]:
            item["_w"] = _w
            best[key] = item
    return list(best.values())


def scan_spot_urgent_confirms(symbol: str, frames: Dict[str, pd.DataFrame],
                              want_tf: str,
                              shape: Optional[dict] = None) -> List[dict]:
    """A spot CONFIRM that does not wait for the pattern TF to close.

    For the alerting timeframe ``want_tf`` (pinned by the ladder) the pattern is
    detected on its own tape, then the ONE-STEP-LOWER frame decides: if the last
    CLOSED sub-candle closed beyond the shape's upper edge with a valid break
    candle (confirm_r62 vocabulary — marubozu / engulfing / pin / strong close,
    shooting-star fake-outs refused), the confirmation is published NOW with the
    sub-close as entry. The pattern-TF close still confirms as before; this lane
    only makes it EARLY — it can never invent a break the tape did not print.
    """
    from analysis.render_kit import detect_patterns
    from analysis.patterns import pattern_info, state_label
    out: List[dict] = []
    sub_tf = spot_confirm_tf(want_tf)
    if not sub_tf:
        return out
    pat_df = frames.get(want_tf)
    sub_df = frames.get(sub_tf)
    if pat_df is None or sub_df is None or len(pat_df) < 45 or len(sub_df) < 20:
        return out
    try:
        from analysis.confirm_r62 import valid_break_candle, frame_minutes
    except Exception:
        return out
    d = _sane_ohlcv(pat_df.reset_index(drop=True)).tail(_spot_count(want_tf)).reset_index(drop=True)
    atr = _atr(d)
    if atr <= 0 or len(d) < 45:
        return out
    sub = _sane_ohlcv(sub_df.reset_index(drop=True)).reset_index(drop=True)
    # the sub-candle must be FRESH (closed within ~2 of its own bars) — a
    # days-old sub close is not "now"
    sub_bar_min = frame_minutes(sub) or 60.0
    try:
        last_ts = pd.Timestamp(sub["timestamp"].iloc[-1])
        now_ts = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
        if last_ts.tzinfo is not None:
            last_ts = last_ts.tz_convert("UTC").tz_localize(None)
        age_min = (now_ts - (last_ts + pd.Timedelta(minutes=sub_bar_min))).total_seconds() / 60.0
        if age_min > 2.5 * sub_bar_min:
            return out
    except Exception:
        pass
    pats = [shape] if shape else detect_patterns(d, "LONG", log_axis=True)
    if not pats:
        return out
    n_pat = len(d) - 1
    tf_min = SPOT_TF_MIN.get(want_tf, 1440.0)
    # fractional bar index of the LAST CLOSED sub candle on the pattern's axis
    try:
        t_pat_last = pd.Timestamp(d["timestamp"].iloc[-1])
        t_sub_last = pd.Timestamp(sub["timestamp"].iloc[-1])
        if t_pat_last.tzinfo is not None:
            t_pat_last = t_pat_last.tz_convert("UTC").tz_localize(None)
        if t_sub_last.tzinfo is not None:
            t_sub_last = t_sub_last.tz_convert("UTC").tz_localize(None)
        bars_ago = (t_pat_last - t_sub_last).total_seconds() / 60.0 / tf_min
        x_sub = float(n_pat) - float(bars_ago)
    except Exception:
        return out
    c_sub = float(sub["close"].iloc[-1])
    eps = 0.02 * atr
    for pat, upper in _spot_bull_shapes(pats, c_sub, x_sub, eps):
        _lns = list(pat.get("lines") or [])
        _kind = str(pat.get("type") or "NONE").upper()
        _sub_atr = float((sub["high"] - sub["low"]).tail(14).mean() or 0.0) or atr
        ok, candle_fa = valid_break_candle(sub.iloc[-1],
                                          sub.iloc[-2] if len(sub) > 1 else None,
                                          "LONG", float(upper), float(_sub_atr))
        if not ok:
            continue
        # ── A1: the break bar ON THE SUB FRAME is the entry's candle ──
        _bi = find_break_bar(sub, float(upper), eps, lookback=4)
        if _bi is None:
            continue
        # the urgent lane is EARLY, never late: the break bar must be the last
        # closed sub candle (or its immediate predecessor) and not a chase
        if not spot_break_recency_ok(len(sub) - 1 - int(_bi),
                                     (c_sub - float(upper)) / float(_sub_atr)):
            continue
        close = c_sub
        sl_struct = _minor_swing_low(d)
        lower_vals = []
        for _l in _lns:
            from analysis.render_kit import line_y as _ly2
            lower_vals.append(float(_ly2(_l, n_pat)))
        measured = close + (float(upper) - min(lower_vals)) if lower_vals else close * 1.06
        floor_path = close * MIN_PATH_PCT_BY_TF.get(want_tf, 5.0) / 100.0
        path = max(measured - close, floor_path)
        _risk = spot_risk_levels(close, float(upper), lower_vals, atr, path,
                                 sl_struct, df_highs=list(d["high"].tail(120)))
        sl = float(_risk["sl"]) * (1.0 - 0.10 / 100.0)
        if sl >= close:
            sl = close * 0.98
        out.append({
            "symbol": symbol.upper(), "tf": want_tf, "pattern": _kind,
            "horizon": ("SHORT" if want_tf in SPOT_SHORT_TFS
                        else "MID" if want_tf in SPOT_MID_TFS else "LONG"),
            "pattern_fa": pattern_info(_kind)["fa"],
            "label": state_label(_kind, "UP"),
            "rule_fa": pattern_info(_kind)["rule_fa"],
            "entry": close, "sl": float(sl), "targets": list(_risk["targets"]),
            "runner": float(_risk.get("runner") or 0.0),
            "weights": list(SPOT_WEIGHTS),
            "path_pct": round(path / close * 100.0, 3),
            "broken_level": float(upper),
            "break_bar_ts": str(sub["timestamp"].iloc[_bi]),
            "pattern_commands": [pat],
            "atr": float(atr),
            "mtf_fa": _mtf_bias_fa(frames),
            "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "urgent_confirm": True, "confirm_tf": sub_tf,
            "confirm_candle_fa": candle_fa,
            "confirm_bar_ts": str(sub["timestamp"].iloc[-1]),
        })
    best: Dict[str, dict] = {}
    for item in out:
        key = (item["symbol"], item["tf"])
        _w = _structural_weight((item.get("pattern_commands") or [{}])[0])
        if key not in best or _w > best[key]["_w"]:
            item["_w"] = _w
            best[key] = item
    return list(best.values())


def _next_spot_public_code() -> str:
    """His ID format (R64.2 dictation 10-03): VIVA-SPOT-Y###### — minted by
    the SAME engine every other family uses. The old E-counter died here: the
    ladder carried Y-codes while detection candidates still printed E-codes,
    which read as «کد یکتا هنوز نیست». Uniqueness is reserved atomically at
    publication by reserve_public_code; the timestamp fallback keeps IDs
    unique even if the code engine hiccups."""
    try:
        from analysis.models import generate_viva_public_code
        code = generate_viva_public_code("SPOT")
        if str(code or "").startswith("VIVA-SPOT-"):
            return str(code)
    except Exception:
        pass
    return ("VIVA-SPOT-Y"
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
    # r53 result-integrity: a LONG spot target AT/BELOW the entry can only
    # produce an instant fictitious win (the SHIB phantom family) — drop it
    # and rebuild the ladder from the default path when none survives.
    targets = [t for t in targets if entry > 0 and t > entry]
    if not targets:
        targets = [entry * 1.05, entry * 1.10]
    weights = [float(x) for x in (item.get("weights") or SPOT_WEIGHTS)]
    meta = {
        "market": "SPOT", "engine": "SPOT", "log_scale": True,
        "spot_measured_box": True,
        "public_code": _next_spot_public_code(),
        "atr": float(item.get("atr") or 0.0),
        "pattern_type": str(item.get("pattern") or ""),
        "spot_horizon": str(item.get("horizon") or ""),
        "pattern_state_label": str(item.get("label") or ""),
        "pattern_rule_fa": str(item.get("rule_fa") or ""),
        "render_patterns": list(item.get("pattern_commands") or []),
        "spot_break_bar": str(item.get("break_bar_ts") or ""),
        "spot_break_close": float(item.get("break_close") or item.get("entry") or 0.0),
        "spot_bars_since_break": item.get("bars_since_break"),
        "spot_urgent_confirm": bool(item.get("urgent_confirm")),
        "spot_confirm_tf": str(item.get("confirm_tf") or ""),
        "spot_confirm_candle_fa": str(item.get("confirm_candle_fa") or ""),
        "tool_entry_ts": str(item.get("confirm_bar_ts") or item.get("break_bar_ts") or ""),
        "spot_broken_level": float(item.get("broken_level") or 0.0),
        "target_ladder": {"targets": targets, "weights": weights,
                          "runner": float(item.get("runner") or 0.0),
                          "path_pct": float(item.get("path_pct") or 0.0)},
        "viva_state": "S6_CONFIRMED",
        "technical_confirmation_complete": True,
        "confirmed_snapshot_fa": "سیگنال اسپات روی کلوز معتبر بالای سقف الگو صادر شد.",
        "mtf_fa": list(item.get("mtf_fa") or []),
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

STAGE_RANK = {"TOUCH": 1, "NEAR_BREAK": 2, "BREAK_DOWN": 3, "BREAK_UP": 4, "CONFIRM": 5}
_ALERT_TTL_H = 24 * 10                      # ladder state lives ten days
_STAGE_COOLDOWN_H = {"TOUCH": 24.0, "NEAR_BREAK": 12.0, "BREAK_DOWN": 0.0, "BREAK_UP": 0.0}


def _edges_at(pat: dict, n: int) -> tuple:
    """(upper, lower) side values of the shape at bar n. A single-line shape
    only owns the side its line sits on (resistance OR support)."""
    lines = list(pat.get("lines") or [])
    if not lines:
        return None, None
    from analysis.render_kit import line_y as _ly3    # calibrated (log) geometry
    vals = [float(_ly3(l, n)) for l in lines]
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
    # 1) valid break UP or DOWN — his «هشدار شکست هر دو جهت»
    if upper is not None and c > upper + eps_break and (c - o) >= 0.20 * atr:
        return {"stage": "BREAK_UP", "side": "HIGH", "edge": float(upper),
                "gap": float(c - upper)}
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
    """Pre-confirmation ladder items for one symbol across 4h/8h/12h/1d/3d/1w.

    Returns plain dicts (stage TOUCH / NEAR_BREAK / BREAK_DOWN); publication
    gating lives in the caller (spot_alert_check → send → spot_alert_commit).
    """
    from analysis.render_kit import detect_patterns
    from analysis.patterns import pattern_info
    out: List[dict] = []
    if not frames:
        return out
    # r61.1 (Viva 09-30): parent/child multi-TF nesting REMOVED by his order —
    # «والد و بچه و اینام ولش کن کلا حذف کن؛ مولتی تایم فقط در بند توضیحات
    # تحلیل بشه». Multi-TF lives in the TEXT bias lines only.
    for tf in SPOT_TRIGGERS:
        df = frames.get(tf)
        if df is None or len(df) < 45:
            continue
        try:
            d = _sane_ohlcv(df.reset_index(drop=True))
            d = d.tail(_spot_count(tf)).reset_index(drop=True)   # R64: chart ≡ scan window
            atr = _atr(d)
            if atr <= 0 or not _fresh(d, tf):
                continue
            n = len(d) - 1
            close = float(d["close"].iloc[-1])
            for pat in detect_patterns(d, "LONG", log_axis=True):
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
                # Viva 10-09 SUPERIORITY law (his ADA 3d year-triangle vs the
                # live 12h channel: «الگوی برتر برنده … آخرین تاچ معتبر»): a
                # BREAK alert needs a TOUCH-VALIDATED pattern — its most
                # recent touch (max line x1) must sit inside 2× the live
                # block. Breaks of fossil lines are the fakeouts he hates —
                # they may still publish TOUCH/NEAR watches, never a BREAK.
                # the last VALID touch: the freshest line-point time across the
                # pattern's lines, aged in bars against the scanned frame (x1 is
                # the fit's right edge, NOT a touch — it reads 0 on live fits).
                _touch_age = 0
                try:
                    _tser = pd.to_datetime(d["timestamp"])
                    try:
                        _tser = _tser.dt.tz_convert("UTC").dt.tz_localize(None)
                    except Exception:
                        try:
                            _tser = _tser.dt.tz_localize(None)
                        except Exception:
                            pass
                    _ages = []
                    for _ln in _lns:
                        _pts = list(_ln.get("points") or [])
                        if not _pts:
                            continue
                        _t = pd.Timestamp(str((_pts[-1] or {}).get("ts") or ""))
                        if _t.tzinfo is not None:
                            _t = _t.tz_convert("UTC").tz_localize(None)
                        _ages.append(int((_tser > _t).sum()))
                    if _ages:
                        _touch_age = max(0, min(_ages))
                except Exception:
                    _touch_age = 0
                if str(hit.get("stage") or "") in ("BREAK_UP", "BREAK_DOWN"):
                    try:
                        from analysis.chart_window import live_block_for_tf as _lbtf109
                        _lim109 = 2 * max(20, int(_lbtf109(tf)))
                    except Exception:
                        _lim109 = 120
                    if _touch_age > _lim109:
                        continue  # fossil break — the live pattern wins
                kind = str(pat.get("type") or "NONE").upper()
                box_top = _structural_high_above(d, close)
                if box_top:
                    box_top = box_top * 1.01  # «کمی بالاترش»
                try:
                    _v20 = float(d["volume"].tail(20).mean() or 0.0)
                    vol_ratio = (float(d["volume"].iloc[-1]) / _v20) if _v20 > 0 else 0.0
                except Exception:
                    vol_ratio = 0.0
                # Viva Identity Law 2026-10-08 (his «چارت‌های تکراری»):
                # the sig is the shape's frozen ANCHOR TIMES (never the
                # sliding window x0 — that re-minted the identity every
                # candle and re-spoke every alert).
                def _anch_ts(_ln, _k="x0"):
                    try:
                        _pts = list(_ln.get("points") or [])
                        if _pts and str((_pts[0] or {}).get("ts") or ""):
                            return str(_pts[0].get("ts"))[:16]
                    except Exception:
                        pass
                    try:
                        _ix = max(0, min(int(float(_ln.get(_k, 0) or 0)), len(d) - 1))
                        return str(d["timestamp"].iloc[_ix])[:16]
                    except Exception:
                        return "?"
                sig = (f"{symbol.upper()}|{tf}|{kind}|"
                       f"{_anch_ts(_lns[0])}|{_anch_ts(_lns[-1])}")
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
                    "touch_age_bars": int(_touch_age),
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


def scan_spot_update_events(symbol: str, frames: Dict[str, pd.DataFrame],
                            cooldown_h: float = 12.0) -> List[dict]:
    """r57 (Viva: «الکی آپدیت نده» — only MAJOR events become spot updates):
      • حجم: the last candle's volume ≥ 1.8× its 20-candle average;
      • دیس‌پلیس‌منت: a body ≥ 1.5×ATR (either direction, with its side);
      • برخورد: price touching EITHER structural extreme of the pattern
        window (last-120-bar high or low) within 0.3×ATR.
    Deduped per (symbol, tf, kind) via bot_kv stamps (12h default) — reads
    only, markers are written by commit_spot_update_events AFTER a send."""
    from database.bot_kv import get_json as _g
    import time as _t
    now = _t.time()
    state = _g("spot_update_events", {}) or {}
    out: List[dict] = []
    for tf in SPOT_TRIGGERS:
        df = frames.get(tf)
        if df is None or len(df) < 45:
            continue
        try:
            d = _sane_ohlcv(df.reset_index(drop=True))
            atr = _atr(d)
            if atr <= 0 or not _fresh(d, tf):
                continue
            close = float(d["close"].iloc[-1])
            v20 = float(d["volume"].tail(20).mean() or 0.0)
            vlast = float(d["volume"].iloc[-1] or 0.0)
            vr = (vlast / v20) if v20 > 0 else 0.0
            body = abs(float(d["close"].iloc[-1]) - float(d["open"].iloc[-1]))
            hi120 = float(d["high"].tail(120).max())
            lo120 = float(d["low"].tail(120).min())
            cands = []
            if vr >= 1.8:
                side_fa = "خرید" if close >= float(d["open"].iloc[-1]) else "فروش"
                cands.append(("vol", f"جهش حجم ≈ {vr:.1f}× میانگین ۲۰کندله — سمتِ {side_fa}"))
            if body >= 1.5 * atr:
                dir_fa = "صعودی" if close >= float(d["open"].iloc[-1]) else "نزولی"
                cands.append(("disp", f"کندلِ دیس‌پلیس‌منت {dir_fa} (بدنه ≥ ۱٫۵×ATR)"))
            if hi120 - 0.3 * atr <= close <= hi120 + 0.3 * atr:
                cands.append(("touch_high", "برخورد به سقفِ ساختاری الگو/ترند"))
            elif lo120 + 0.3 * atr >= close >= lo120 - 0.3 * atr:
                cands.append(("touch_low", "برخورد به کفِ ساختاری الگو/ترند"))
            for kind, text_fa in cands:
                key = f"{symbol}|{tf}|{kind}"
                if now - float((state.get(key) or {}).get("ts", 0)) < cooldown_h * 3600.0:
                    continue
                out.append({"symbol": symbol.upper(), "tf": tf, "kind": kind,
                            "text_fa": text_fa, "event_key": key,
                            "close": close, "vol_ratio": vr,
                            "ts": str(d["timestamp"].iloc[-1])})
        except Exception as exc:
            print(f"spot update-event warning {symbol} {tf}: {exc}")
            continue
    return out


def commit_spot_update_events(events) -> None:
    """Stamp the sent events (handoff law: marker AFTER success)."""
    from database.bot_kv import get_json as _g, set_json as _s
    import time as _t
    now = _t.time()
    state = {k: v for k, v in (_g("spot_update_events", {}) or {}).items()
             if now - float((v or {}).get("ts", 0)) < 7 * 24 * 3600.0}
    for e in events or []:
        state[str(e.get("event_key") or "")] = {"ts": now}
    _s("spot_update_events", state)


def spot_alert_check(item: dict) -> bool:
    """May this ladder item speak? Stage-advance always may; the same stage
    again only after its cooldown AND only on a NEW candle. Reads only — the
    marker is written by spot_alert_commit AFTER a successful send (handoff
    law: never store a dedup marker before the send succeeded)."""
    try:
        sym = str(item.get("symbol") or "").upper()
        stage = str(item.get("stage") or "").upper()

        # Viva Strict Post-Confirmation Dedup Law (07-Oct Mandate):
        # Once a signal is confirmed active for this symbol, NEVER send pre-breakout TOUCH/NEAR_BREAK alerts!
        if stage in ("TOUCH", "NEAR_BREAK"):
            try:
                from database.db import get_active_signals
                _actives = get_active_signals()
                if any(str(s.get("symbol") or "").upper() == sym for s in _actives):
                    return False
            except Exception:
                pass
            try:
                from database.bot_kv import get_json as _g
                _recent_sigs = _g("recent_confirmed_symbols", {}) or {}
                import time as _t
                if sym in _recent_sigs and (_t.time() - float(_recent_sigs[sym])) < 86400.0 * 3:
                    return False
            except Exception:
                pass

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
        # 10-09 crash law: the dedup ledger never grows without bound
        if len(state) > 500:
            for _k in sorted(state, key=lambda k: float((state[k] or {}).get("ts", 0)))[:len(state) - 500]:
                state.pop(_k, None)
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
