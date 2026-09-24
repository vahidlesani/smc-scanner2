"""Orchestrates separate Swing/Scalp engines and candidate confirmation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

import pandas as pd

from analysis.indicators import atr, candle_displacement
from analysis.models import EvidenceItem, SignalCandidate, iso_now
from analysis.setups_v7 import scan_setups
from config import get_settings
from data.fetcher import MarketBundle

SETTINGS = get_settings()


class SwingEngine:
    name = "SWING"
    required_frames = ("1d", "4h", "1h")

    def scan(self, bundle: MarketBundle) -> List[SignalCandidate]:
        # mid-term swing = TWO trigger streams: 1h and 4h (Viva 09-16)
        from analysis import setups_v7
        out: List[SignalCandidate] = []
        for trig in ("1h", "4h"):
            setups_v7.PROFILE_OVERRIDE["SWING"] = ("1d", "4h", trig)
            try:
                out.extend(scan_setups(bundle, self.name))
            finally:
                setups_v7.PROFILE_OVERRIDE.pop("SWING", None)
        return out


class DayTradeEngine:
    """Viva 09-16: short swing — 4h context, 1h structure, 15m trigger/confirm."""
    name = "DAYTRADE"
    required_frames = ("4h", "1h", "15m")

    def scan(self, bundle: MarketBundle) -> List[SignalCandidate]:
        return scan_setups(bundle, self.name)


class ScalpEngine:
    name = "SCALP"
    required_frames = ("1h", "15m", "5m", "1m")

    def scan(self, bundle: MarketBundle) -> List[SignalCandidate]:
        turnover = float((bundle.ticker or {}).get("turnover24h", 0) or 0)
        spread = float((bundle.ticker or {}).get("spread_pct", 999) or 999)
        if turnover < SETTINGS.scalp_min_turnover_usd or spread > SETTINGS.scalp_max_spread_percent:
            return []
        return scan_setups(bundle, self.name)


class GrandEngine:
    """Viva 2026-09-13: 1D long-term swing stream — pattern on the daily
    chart, context 4H, one closed 4H candle confirms."""
    name = "GRAND"
    required_frames = ("1d", "4h", "1h")

    def scan(self, bundle: MarketBundle) -> List[SignalCandidate]:
        return scan_setups(bundle, self.name)


ENGINES = {"GRAND": GrandEngine(), "SWING": SwingEngine(),
           "DAYTRADE": DayTradeEngine(), "SCALP": ScalpEngine()}


def _live_styles() -> List[str]:
    raw = str(getattr(SETTINGS, "live_styles", "DAYTRADE,SWING") or "")
    styles = [x.strip().upper() for x in raw.split(",") if x.strip() in ENGINES]
    return styles or ["DAYTRADE", "SWING", "GRAND", "SCALP"]


def scan_bundle(bundle: MarketBundle) -> List[SignalCandidate]:
    """Run only the explicitly enabled tiers. Lower TF may still confirm a
    DAYTRADE/SWING entry even while standalone SCALP discovery is paused."""
    candidates: List[SignalCandidate] = []
    for style in _live_styles():
        candidates.extend(ENGINES[style].scan(bundle))
    from analysis.setups_v7 import enrich_candidate_context
    for candidate in candidates:
        try:
            enrich_candidate_context(bundle, candidate)
        except Exception:
            pass
    # R28 execution layer: attach CORE/CONTEXT/EXECUTION evidence only.
    # This does not alter Telegram templates, link-chain IDs, public codes, or
    # the five setup cores; it is a separate price/risk layer.
    try:
        from analysis.execution_integrity_r28 import apply_execution_integrity
        for candidate in candidates:
            try:
                frames = {}
                for _tf in ("1d", "4h", "2h", "1h", "30m", "15m", "5m", "3m", "1m"):
                    try:
                        _frame = bundle.get(_tf)
                    except Exception:
                        _frame = None
                    if _frame is not None and len(_frame) > 0:
                        frames[_tf] = _frame
                candidate.metadata["r28_execution"] = apply_execution_integrity(candidate, frames)
            except Exception as _r28_exc:
                candidate.metadata["r28_execution_error"] = str(_r28_exc)[:240]
    except Exception as _r28_outer_exc:
        for candidate in candidates:
            candidate.metadata["r28_execution_error"] = str(_r28_outer_exc)[:240]

    # TechnoClassic HTF-edge intelligence — SCORE-ONLY for all setups
    # (Viva 2026-09-10): a tested 1D/4H edge ahead of TP1 costs points, an
    # entry sitting ON such an edge earns them. Never a gate, never a reject.
    try:
        from analysis.pattern_engine import htf_pattern_adjustment
        for candidate in candidates:
            if str(candidate.setup_code) == "TECHCLASSIC":
                continue  # its own geometry is already priced by its detector
            try:
                delta, note = htf_pattern_adjustment(bundle, candidate)
                if delta or note:
                    candidate.score = int(max(0, min(10, candidate.score + delta)))
                    candidate.metadata["htf_edge_delta"] = int(delta)
                    candidate.metadata["htf_edge_note"] = str(note)
            except Exception:
                pass
    except Exception:
        pass
    return candidates

def _as_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_expired(candidate: SignalCandidate) -> bool:
    if not candidate.expires_at:
        return False
    return datetime.now(timezone.utc) >= _as_utc(candidate.expires_at)


def is_invalidated(candidate: SignalCandidate, current_price: float) -> bool:
    if candidate.direction == "LONG":
        return current_price <= candidate.sl
    return current_price >= candidate.sl


def approaching_entry(candidate: SignalCandidate, current_price: float) -> Tuple[bool, float]:
    bottom, top = candidate.entry_zone_bottom, candidate.entry_zone_top
    atr_value = float(candidate.metadata.get("atr", 0) or abs(top - bottom) or current_price * 0.002)
    if bottom <= current_price <= top:
        return True, 0.0
    distance = bottom - current_price if current_price < bottom else current_price - top
    distance_atr = distance / atr_value if atr_value > 0 else 999.0
    return distance_atr <= 0.30, distance_atr


def _bars_since_candidate(candidate: SignalCandidate, closed_df: pd.DataFrame) -> pd.DataFrame:
    if closed_df is None or closed_df.empty:
        return closed_df
    created = pd.Timestamp(candidate.created_at)
    if created.tzinfo is not None:
        created = created.tz_convert("UTC").tz_localize(None)
    timestamps = pd.to_datetime(closed_df["timestamp"])
    if getattr(timestamps.dt, "tz", None) is not None:
        timestamps = timestamps.dt.tz_convert("UTC").dt.tz_localize(None)
    # The alert candle is the information boundary. Including it (or falling
    # back to historical bars) can confirm a signal using pre-alert data.
    return closed_df.loc[timestamps > created].copy()


def _frame_atr(frame: pd.DataFrame, period: int = 14, fallback: float = 0.0) -> float:
    """Return one consistent true-range ATR for the frame being judged."""
    try:
        value = float(atr(frame, period).iloc[-1])
        if pd.notna(value) and value > 0:
            return value
    except Exception:
        pass
    return float(fallback or 0.0)


# ── Viva 09-21 (round 15 phase 2): «هر الگویی اسم داره . قوانین خودش رو داره»
# — one shared table that tells every setup which way its own pattern leans.
# The trade direction is then checked against the side that ACTUALLY broke.
_PATTERN_BIAS_MAP = {
    "WEDGE_FALLING": "BULL",
    "WEDGE_RISING": "BEAR",
    "TRIANGLE_ASCENDING": "BULL",
    "TRIANGLE_DESCENDING": "BEAR",
    "TRIANGLE_SYMMETRICAL": "NEUTRAL",
    "TRIANGLE": "NEUTRAL",
    "CHANNEL_ASCENDING": "BULL",
    "CHANNEL_DESCENDING": "BEAR",
    "CHANNEL": "NEUTRAL",
    "BULL_FLAG": "BULL",
    "BEAR_FLAG": "BEAR",
    "FLAG": "NEUTRAL",
    "RECTANGLE": "NEUTRAL",
    "RANGE": "NEUTRAL",
    "TRENDLINE": "NEUTRAL",
    "NONE": "NEUTRAL",
}


def pattern_bias_of(kind: str) -> str:
    """BULL / BEAR / NEUTRAL for a validated pattern name (never raises)."""
    k = str(kind or "").upper()
    if k in _PATTERN_BIAS_MAP:
        return _PATTERN_BIAS_MAP[k]
    if "FALLING" in k or "ASCENDING" in k or "BULL" in k:
        return "BULL"
    if "RISING" in k or "DESCENDING" in k or "BEAR" in k:
        return "BEAR"
    return "NEUTRAL"


CONFIRMED_SNAPSHOT_KEYS = (
    "pattern_band", "render_patterns", "render_zones", "tl_a_ts", "tl_a_price",
    "tl_b_ts", "tl_b_price", "tool_entry_ts", "tool_anchor_ts", "pattern_type",
    "pattern_bias", "break_edge", "break_direction", "pattern_state_label",
)


def freeze_confirmed_snapshot(candidate) -> dict:
    """Viva 09-21/22 — «اون اسنپ‌شات که گفتی چی شد؟ انجام بده دیگه».

    The moment a scenario is CONFIRMED, the whole decision is frozen: entry,
    stop, the target ladder (targets + weights), the pattern/zone/line render
    commands and the tool anchors. Later scans, absorbs or updates may move
    nothing here — only the moving parts of the lifecycle (hit index, trailing
    stop) are allowed to evolve. «استاپی که در زمان Confirmed ذخیره شد، نباید
    توسط آپدیت بعدی یا absorb جابه‌جا شود؛ مگر صراحتاً trailing».
    """
    md = candidate.metadata if getattr(candidate, "metadata", None) is not None else {}
    if isinstance(md.get("confirmed_snapshot"), dict):
        return md["confirmed_snapshot"]
    ladder = dict(md.get("target_ladder") or {})
    snap = {
        "entry": float(getattr(candidate, "planned_entry", 0) or 0.0),
        "sl": float(getattr(candidate, "sl", 0) or 0.0),
        "tp1": float(getattr(candidate, "tp1", 0) or 0.0),
        "tp2": float(getattr(candidate, "tp2", 0) or 0.0),
        "targets": [float(x) for x in (ladder.get("targets") or [])],
        "weights": [float(x) for x in (ladder.get("weights") or [])],
        "direction": str(getattr(candidate, "direction", "") or ""),
        "setup_code": str(getattr(candidate, "setup_code", "") or ""),
        "trigger_timeframe": str(getattr(candidate, "trigger_timeframe", "") or ""),
        "confirmed_at": str(getattr(candidate, "confirmed_at", "") or ""),
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    for key in CONFIRMED_SNAPSHOT_KEYS:
        if key in md:
            snap[key] = md[key]
    md["confirmed_snapshot"] = snap
    md["confirmed_snapshot_fa"] = (
        "اسنپ‌شات تأیید قفل شد: ورود، استاپ، نردبان هدف و خطوط همان لحظهٔ تأیید "
        "تثبیت شدند و آپدیت‌های بعدی آن‌ها را جابه‌جا نمی‌کنند (فقط تریلینگ و "
        "تی‌پی‌های زده‌شده جلو می‌روند).")
    return snap


def apply_confirmed_snapshot(candidate) -> bool:
    """Re-impose the frozen decision after any absorb/update. True when applied."""
    md = candidate.metadata or {}
    snap = md.get("confirmed_snapshot")
    if not isinstance(snap, dict):
        return False
    try:
        if float(snap.get("entry") or 0) > 0:
            candidate.planned_entry = float(snap["entry"])
        if float(snap.get("sl") or 0) > 0:
            candidate.sl = float(snap["sl"])
        if float(snap.get("tp1") or 0) > 0:
            candidate.tp1 = float(snap["tp1"])
        if float(snap.get("tp2") or 0) > 0:
            candidate.tp2 = float(snap["tp2"])
        ladder = dict(md.get("target_ladder") or {})
        if snap.get("targets"):
            ladder["targets"] = [float(x) for x in snap["targets"]]
        if snap.get("weights"):
            ladder["weights"] = [float(x) for x in snap["weights"]]
        if ladder:
            md["target_ladder"] = ladder
        for key in CONFIRMED_SNAPSHOT_KEYS:
            if key in snap:
                md[key] = snap[key]
        md["snapshot_reapplied_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return True
    except Exception:
        return False


def enforce_confirmed_snapshot(candidate) -> str:
    """Freeze on first sight of CONFIRMED; re-apply on every later sight.

    One call per monitor cycle keeps a confirmed plan immutable no matter which
    path (scan absorb, monitor update, restart rehydrate) touched it in between.
    """
    status = str(getattr(candidate, "status", "") or "").upper()
    md = candidate.metadata or {}
    has_snap = isinstance(md.get("confirmed_snapshot"), dict)
    if status == "CONFIRMED" and not has_snap:
        freeze_confirmed_snapshot(candidate)
        return "frozen"
    if has_snap:
        apply_confirmed_snapshot(candidate)
        return "applied"
    return ""


def _tz_match(ts_target, ref):
    """Two pandas timestamps on ONE tz plane. The 09-24 audit found the real
    production killer: live frames are tz-aware, metadata anchors are naive →
    the subtraction raised TypeError, the break-side veto silently skipped and
    BTC/ADA/RENDER-style LONGs confirmed UNDER their broken support line."""
    a, b = pd.Timestamp(ts_target), pd.Timestamp(ref)
    if a.tzinfo is not None and b.tzinfo is None:
        b = b.tz_localize(a.tzinfo)
    elif a.tzinfo is None and b.tzinfo is not None:
        a = a.tz_convert("UTC").tz_localize(None)
    return a, b


def _project_watch_level(watch: dict, when) -> float:
    """Value of a watched line at `when`. Log-calibrated lines are interpolated
    in log space between their own anchors (identical to the chord otherwise) —
    R16 phase 3, so the veto level is the line the chart actually paints."""
    p0 = (watch or {}).get("p0") or {}
    p1 = (watch or {}).get("p1") or {}
    t0 = pd.Timestamp(str(p0.get("ts")))
    t1 = pd.Timestamp(str(p1.get("ts")))
    y0, y1 = float(p0.get("price")), float(p1.get("price"))
    t1, t0 = _tz_match(t1, t0)
    dt = (t1 - t0).total_seconds()
    if dt <= 0 or not (y0 > 0 and y1 > 0):
        raise ValueError("degenerate watch anchors")
    t = pd.Timestamp(when)
    t, t1 = _tz_match(t, t1)
    if watch.get("log_fit"):
        import math as _m
        _tm2, _t02 = _tz_match(t, t0)
        f = (_tm2 - _t02).total_seconds() / dt
        return float(10.0 ** (_m.log10(y0) + (_m.log10(y1) - _m.log10(y0)) * f))
    return y1 + (y1 - y0) / dt * (t - t1).total_seconds()


def evaluate_confirmation(
    candidate: SignalCandidate, closed_df: pd.DataFrame,
    htf_closed_df: Optional[pd.DataFrame] = None,
) -> Tuple[bool, SignalCandidate, str]:
    """Require a zone touch plus a closed LTF trigger candle.

    No live/incomplete candle can confirm a trade. A candidate score may gain one
    trigger point, but missing mandatory gates can never be compensated by score.
    """
    def reject(code: str, message: str) -> Tuple[bool, SignalCandidate, str]:
        candidate.metadata["last_reject_code"] = code
        return False, candidate, message

    if closed_df is None or len(closed_df) < 20:
    # R28 execution boundary: core candidates may remain visible as context,
    # but an executable confirmation cannot use an invalid/wrong-side stop.
    try:
        from analysis.execution_integrity_r28 import structural_stop
        _r28_stop = structural_stop(
            float(candidate.planned_entry or 0.0),
            str(candidate.direction or ""),
            float(candidate.sl or 0.0),
            str(candidate.trigger_timeframe or ""),
        )
        if not _r28_stop.valid:
            _code = "STOP_TOO_TIGHT" if _r28_stop.stop_quality == "TOO_TIGHT" else (
                "RISK_INVALID" if _r28_stop.stop_quality == "RISK_INVALID" else "STOP_INVALID")
            return reject(_code, f"R28 execution stop rejected: {_r28_stop.stop_reason}")
        if str((candidate.metadata or {}).get("market") or "").upper() == "SPOT" and str(candidate.direction).upper() != "LONG":
            return reject("SPOT_SHORT_FORBIDDEN", "اسپات فقط LONG قابل تأیید است.")
    except Exception as _r28_exc:
        candidate.metadata["r28_confirmation_check_error"] = str(_r28_exc)[:240]

        return reject("NO_DATA", "داده کافی برای تأیید وجود ندارد.")
    after = _bars_since_candidate(candidate, closed_df)
    if after is None or after.empty:
        return reject("NO_NEW_BAR", "هنوز کندلی بعد از ایجاد ستاپ بسته نشده است.")

    # ── ONE-CLOSE LAW, EVERY SETUP (Viva 2026-09-12, final) ──────────────
    # «کی به تو گفته تأیید سیگنال حتماً باید ریتست ناحیه باشه؟!» — nobody.
    # Confirmation is exactly ONE closed candle of the confirm timeframe that
    # prints a valid close beyond the break edge: the fitted line when the
    # setup has one, else the zone's entry edge, ≥0.10 ATR past it, directional
    # with body ≥0.25 ATR. First break is confirmable WITHOUT any pullback; a
    # missing zone-touch may never hard-reject it. Everything else (invalidation,
    # expiry, RR floor, mandatory gates) keeps full veto.
    fast_lane = ""
    _edge = 0.0
    # ── Viva 09-21: the level the ENGINE waits for must be the exact level the
    # MESSAGE names. For the pinbar family the alert prints the pin's own
    # extreme («کلوز بالای ۰.۷۴۸۲»), so that is the edge — not the entry-zone
    # edge, which sat 0.7% below it in the ETHFIUSDT case and would have
    # confirmed at a price the member was never told about.
    try:
        _md_pin = candidate.metadata or {}
        _setup_pin = str(getattr(candidate, "setup_code", "") or "").upper()
        if _setup_pin in {"PINVAL", "PINWALLQ"}:
            _pin_lvl = float(_md_pin.get("pin_high" if str(candidate.direction).upper() == "LONG"
                                         else "pin_low") or 0.0)
            if _pin_lvl > 0:
                _edge = _pin_lvl
    except Exception:
        pass
    for _k in ("viva_breakout_line", "viva_break_line", "viva_watch_line"):
        try:
            _v = float(candidate.metadata.get(_k) or 0.0)
        except Exception:
            _v = 0.0
        if _v > 0 and _edge <= 0:
            _edge = _v
            break
    # ── Viva 09-23 (round 20 ENTRY LAW, verbatim): «ورود با کلوز بالای خط
    # روندِ اصلی تأیید می‌شود». Breaking the tool's own line is necessary, not
    # sufficient: when a MAJOR-pivot trendline (the HTF validated line stored
    # at detection) still stands BEYOND the tool edge in the break direction,
    # the first confirmable close is a close beyond the MAJOR line. If price
    # already cleared the major line (HYPEUSDT: the 1D TL cross had happened),
    # nothing changes. Sane-bound + fail-open.
    try:
        _maj = float((candidate.metadata or {}).get("viva_major_break_line") or 0.0)
        if _maj > 0 and _edge > 0:
            _is_l = candidate.direction == "LONG"
            _beyond = (_maj > _edge) if _is_l else (_maj < _edge)
            _atr_m = float(candidate.metadata.get("atr", 0) or 0)
            _sane = abs(_maj - float(getattr(candidate, "planned_entry", _maj) or _maj)) <= max(
                0.04 * _maj, 2.5 * _atr_m)
            if _beyond and _sane:
                _edge = _maj
                candidate.metadata["confirm_edge_source"] = "MAJOR_TL"
    except Exception:
        pass
    _zone_edge = float(candidate.entry_zone_top if candidate.direction == "LONG"
                       else candidate.entry_zone_bottom)
    _atr = float(candidate.metadata.get("atr", 0) or 0) or _frame_atr(closed_df)
    touched = bool(candidate.metadata.get("touched", False))
    # Viva 2026-09-13 «اولین کلوز بالا/پایین هر ترند یا ضلعِ وج/مثلث/کانال
    # تأیید است»: EVERY closed bar since the alert can fire the confirmation
    # (not just the newest one — fast runaways used to settle two bars ago and
    # expire unconfirmed), the fitted line is evaluated AT THE BAR'S OWN TIME
    # (sloped trend/channel sides move under price), and a pattern-timeframe
    # close counts as much as the confirm-timeframe one.
    if _atr > 0:
        _md = candidate.metadata or {}
        _la = _lb = None
        try:
            _la = (pd.Timestamp(str(_md["tl_a_ts"])), float(_md["tl_a_price"]))
            _lb = (pd.Timestamp(str(_md["tl_b_ts"])), float(_md["tl_b_price"]))
        except Exception:
            _la = _lb = None
        def _edge_at(ts, static_edge: float) -> float:
            if _la is not None and _lb is not None and _lb[0] != _la[0]:
                _dt = (_lb[0] - _la[0]).total_seconds()
                if _dt:
                    _frac = max(0.0, min(1.0, (
                        (pd.Timestamp(ts) - _la[0]).total_seconds() / _dt
                    )))
                    return float(_la[1] + (_lb[1] - _la[1]) * _frac)
            return static_edge
        _is_long = candidate.direction == "LONG"
        _buf = 0.10 * _atr
        for _frame, _tag in ((closed_df, "تایم تأیید"), (htf_closed_df, "تایم الگو")):
            if _frame is None or len(_frame) < 2:
                continue
            _scan = _bars_since_candidate(candidate, _frame)
            if _scan is None or _scan.empty:
                continue
            # Viva 2026-09-14: thresholds speak the language of the frame they
            # judge. A 1D pattern's ATR applied to a 15m confirm candle is an
            # almost-impossible bar nobody stated — «اولین کلوز معتبر» means
            # valid FOR THAT CANDLE, so the buffer/body are scaled to the
            # scanned frame's own average range (14 bars, high-low).
            _f_atr = _frame_atr(_frame, fallback=_atr)
            # ── Viva 09-21 (round 15), his verbatim law, fourth time stated:
            # «اولین کلوز بالای یا زیر هر نوع ناحیه‌های داخل ستاپ / کلوز بالا یا
            # پایین هر تول ترند نزولی و صعودی / هر نوع الگو باید تایید بشه» and
            # «چرا این ستاپ‌ها مثل احمق‌ها موقعیت رو می‌شناسن اما تایید نمی‌کنن؟»
            # Root cause of that complaint: the fast lane added thresholds the
            # message never mentioned — 0.10×ATR beyond the edge AND a body of
            # 0.25×ATR. A banner 15m candle that closed cleanly above the named
            # level could still fail both, so the channel kept sending updates
            # while the level was demonstrably broken. The law now is what the
            # message says: the FIRST closed candle of the confirm/pattern
            # timeframe whose close lands beyond the level. The only remaining
            # guard is a tick-scale epsilon (2% of the frame's own ATR) so a
            # mathematically equal close is not treated as a break.
            _f_buf = max(0.02 * _f_atr, 0.0)
            for _ts, _r in _scan.iterrows():
                _edge_t = _edge_at(_ts, _edge if _edge > 0 else _zone_edge)
                _out = bool(float(_r["close"]) >= _edge_t + _f_buf) if _is_long \
                    else bool(float(_r["close"]) <= _edge_t - _f_buf)
                if not _out:
                    continue
                _body = abs(float(_r["close"]) - float(_r["open"])) / _f_atr
                _dist = abs(float(_r["close"]) - _edge_t) / _f_atr
                fast_lane = (f"اولین کلوزِ معتبر فراتر از خط/لبه ({_tag}، "
                             f"{_dist:.2f} ATR پشت سطح، Body {_body:.2f} ATR) — پولبک شرط نیست")
                candidate.metadata["fast_break_bar"] = str(_ts)[:16]
                candidate.metadata["tl_fast_break"] = fast_lane
                candidate.metadata["confirm_level_used"] = float(_edge_t)
                break
            if fast_lane:
                break
    if not touched:
        touched = bool(fast_lane) or bool(
            (
                (after["low"] <= candidate.entry_zone_top)
                & (after["high"] >= candidate.entry_zone_bottom)
            ).any()
        )
    # ── Viva 09-20: pattern containment + deep-pullback law ───────────────
    # «الان همه سیگنال‌هایی که استاپ شدند قیمت هنوز داخل وج یا کانال یا مثلث
    # قرار داره اما سیگنال تایید شده .. این اشتباهه» → a BREAKOUT confirmation
    # must have a close OUTSIDE the pattern's own edges (projected to this bar).
    # «درصورتی که پولبک فقط روی ترندلاین/ضلع/ناحیه انجام بشه یا حتی با شدو داخل
    # بره و کلوزش دوباره بیرون باشه، دیگر منتظر شکست نباید باشیم» → a close back
    # outside the pattern keeps the candle-confirmation lane alive with no new
    # break. But «اگر قیمت به زیر/بالای ناحیهٔ شکست وارد شده باشد دوباره باید
    # بریک و کلوز بدهد» → a DEEP re-entry (close >0.5×ATR inside) demands a fresh
    # break+close and never a bare pin at the zone. Internal entries (entering
    # from inside the channel/side-range on candle confirmation) are exempt by
    # design and carry their own structural stop.
    _md20 = candidate.metadata or {}
    _is_internal = str(_md20.get("viva_entry_type") or "BREAKOUT").upper() == "INTERNAL"
    _row20 = closed_df.iloc[-1]
    _close20 = float(_row20["close"])
    _atr20 = float((closed_df["high"] - closed_df["low"]).tail(14).mean() or 0.0) or _atr
    _band20 = _md20.get("pattern_band") or {}
    _band_lo20 = _band_hi20 = None
    if _band20 and float(_band20.get("tf_minutes") or 0) > 0:
        try:
            _ts_last20 = pd.Timestamp(str(_band20.get("ts_last")))
            _ts_now20 = pd.Timestamp(str(_row20["timestamp"]))
            _bars20 = max(0.0, (_ts_now20 - _ts_last20).total_seconds() / 60.0
                          / float(_band20["tf_minutes"]))
            # R16 phase 3: a log-calibrated edge must be projected on its OWN
            # curve — the linear tangent would drift away from the line the
            # chart shows (bands without log geometry keep the old maths).
            _lo20 = _band20.get("log_lo") or {}
            _hi20 = _band20.get("log_hi") or {}
            if _lo20.get("fit") and float(_lo20.get("intercept") or 0.0):
                _x20 = float(_lo20["slope"]) * _bars20 + float(_lo20["intercept"])
                _band_lo20 = float(10.0 ** _x20)
            else:
                _band_lo20 = float(_band20["lo"]) + float(_band20.get("slope_lo") or 0.0) * _bars20
            if _hi20.get("fit") and float(_hi20.get("intercept") or 0.0):
                _x21 = float(_hi20["slope"]) * _bars20 + float(_hi20["intercept"])
                _band_hi20 = float(10.0 ** _x21)
            else:
                _band_hi20 = float(_band20["hi"]) + float(_band20.get("slope_hi") or 0.0) * _bars20
        except Exception:
            _band_lo20 = _band_hi20 = None
    # ── Viva 09-21 (round 12) — BREAK-SIDE LAW, enforced on every setup ───
    # His verbatim question: «چرا بعد از شکست ترند رو به بالا پوزیشن شورت
    # اعلان میشه توی برخی ستاپها؟» و «چرا بعد از شکست الگوها یا ترند به سمت
    # پایین و کلوز بعدش … لانگ اعلام میکنه؟» → a trade may never be confirmed
    # against the side the market just broke. Each validated line travels on
    # the candidate (render_line_watch with its anchor points); projected onto
    # THIS candle it tells which edge price closed through:
    #   • a LONG closing clearly BELOW a low-side (support) line = the support
    #     was broken down → the long premise is gone;
    #   • a SHORT closing clearly ABOVE a high-side (resistance) line = the
    #     resistance was broken up → the short premise is gone.
    # Closing THROUGH a line in the trade's own direction stays allowed (that
    # is the break/retest lane), and INTERNAL/fade lanes are exempt by design.
    if not _is_internal and candidate.direction in ("LONG", "SHORT"):
        _watch = (candidate.metadata or {}).get("render_line_watch") or []
        _side_wrong = ""
        for _ln in _watch:
            try:
                _p0 = _ln.get("p0") or {}
                _p1 = _ln.get("p1") or {}
                _t0 = pd.Timestamp(str(_p0.get("ts")))
                _t1 = pd.Timestamp(str(_p1.get("ts")))
                _y0, _y1 = float(_p0.get("price")), float(_p1.get("price"))
                _dt = (_t1 - _t0).total_seconds()
                if _dt <= 0 or not (_y0 > 0 and _y1 > 0):
                    continue
                _tnow = pd.Timestamp(str(_row20["timestamp"]))
                _lvl = _project_watch_level(_ln, _tnow)
                # only lines that are still RELEVANT to the live price may veto
                # (a dead line projected far away is history, not context)
                # relevant = the line is still within a few ATR of the price
                # (a genuinely broken line is a couple of ATR away, a dead one
                # projected far off is history and must not veto anything)
                if _atr20 > 0 and abs(_lvl - _close20) > 3.0 * _atr20:
                    continue
                _buf = 0.10 * _atr20
                _side = str(_ln.get("side") or "").upper()
                if candidate.direction == "LONG" and _side == "LOW" and _close20 < _lvl - _buf:
                    _side_wrong = f"کف/خط حمایتی {_lvl:.8g}"
                    break
                if candidate.direction == "SHORT" and _side == "HIGH" and _close20 > _lvl + _buf:
                    _side_wrong = f"سقف/خط مقاومتی {_lvl:.8g}"
                    break
            except Exception as _exc:
                # a silent skip here once disabled the whole law in production
                print(f"break-side watch skip {getattr(candidate, 'signal_id', '?')}: {_exc}")
                continue
        if _side_wrong:
            return reject("BREAK_SIDE_MISMATCH", (
                f"جهت سیگنال با جهت شکست ناهمسو است: بازار {_side_wrong} را "
                f"در جهت مخالف سناریو با کلوز شکسته است (کلوز {_close20:.8g}). "
                "طبق قانون، پس از شکست و کلوزِ معتبر، پوزیشن فقط در جهت ضلعِ "
                "شکسته معنا دارد؛ این سناریو باطل می‌شود."))
    # TECHCLASSIC carries an explicit canonical contract from the detector.
    # Never allow a later generic/internal path to reverse that contract.
    if not _is_internal:
        _contract = (candidate.metadata or {})
        _contract_kind = str(_contract.get("strategy_variant") or "").upper()
        _contract_break = str(_contract.get("break_direction") or "").upper()
        if _contract_kind == "VIVA_TLBREAK" and _contract_break in {"UP", "DOWN"}:
            _expected = "LONG" if _contract_break == "UP" else "SHORT"
            if str(candidate.direction).upper() != _expected:
                return reject("BREAK_SIDE_MISMATCH", (
                    f"قرارداد ماهیت الگو نقض شده است: شکست {_contract_break} است، "
                    f"اما جهت معامله {candidate.direction} ثبت شده؛ فقط {_expected} مجاز است."))
    # ── Viva 09-20 (round 9) — INTERNAL-ENTRY lane ───────────────────────
    # Verbatim: «داخل کانال یا رنجِ جانبی فقط از کف مجاز به لانگ هستیم با
    # تأیید کندل و استاپ پشت کانال با بافر، و اهداف زیر سقف کانال؛ شورت هم
    # آینهٔ همین.» So an entry that happens INSIDE a channel/side-range is a
    # legitimately different trade: it is taken only from the correct edge,
    # it needs a closed confirmation candle, its stop lives behind the
    # channel edge (with buffer) and its targets stay UNDER the channel
    # ceiling (LONG) / ABOVE the channel floor (SHORT). Marked INTERNAL so the
    # breakout-containment gate exempts it by design.
    _internal_plan = None
    _pattern_kind20 = str((_band20 or {}).get("kind") or "").upper()
    _internal_allowed20 = (
        _pattern_kind20 in {"RANGE", "RECTANGLE", "CHANNEL"}
        or _pattern_kind20.startswith("CHANNEL_")
    )
    if (_band_lo20 is not None and _band_hi20 is not None
            and _internal_allowed20
            and str(_md20.get("viva_entry_type") or "").upper() != "INTERNAL"):
        try:
            _w20 = max(_band_hi20 - _band_lo20, 1e-12)
            _o20 = float(_row20["open"])
            _h20 = float(_row20["high"])
            _l20 = float(_row20["low"])
            _body20 = abs(_close20 - _o20)
            _rng20 = max(_h20 - _l20, 1e-12)
            _prev_o20 = float(closed_df.iloc[-2]["open"])
            _prev_c20 = float(closed_df.iloc[-2]["close"])
            # Viva 09-20 round 11: «بدون atr … پشت آخرین سویینگ با بافر» →
            # the internal-lane buffer is the standard price allowance.
            from analysis.trade_management import structural_buffer
            _buf20i = structural_buffer(_close20)
            if candidate.direction == "LONG" and _close20 <= _band_lo20 + 0.20 * _w20:
                _bull_pin = ((min(_o20, _close20) - _l20) >= 2.0 * max(_body20, 1e-12)
                             and (_h20 - _close20) <= 0.35 * _rng20)
                _bull_engulf = (_prev_c20 < _prev_o20 and _close20 > _o20
                                and _o20 <= _prev_c20 and _close20 >= _prev_o20)
                _bull_close = _close20 > _o20 and _close20 > _prev_c20
                if _bull_pin or _bull_engulf or _bull_close:
                    # Viva 09-20 round 10 (verbatim): «هدف در شورت کف الگو و در
                    # صعودی زیر سقف الگو» → the PATH is entry→opposite wall;
                    # TP1 is one fifth of it and the exits (TP1..TP3) land at
                    # 60% of the way, i.e. strictly UNDER the wall.
                    _wall = _band_hi20 - _buf20i
                    _path = max(_wall - _close20, 0.0)
                    # his verbatim stop rule for the internal lane: «استاپ پشت
                    # کانال و بافر از آخرین سویینگ طبق عکس چارت» → behind the
                    # channel edge AND behind the last swing low that built
                    # the floor, plus the buffer.
                    _swing_lo20 = float(closed_df["low"].tail(20).min())
                    _sl_base = min(_band_lo20, _swing_lo20)
                    _internal_plan = {
                        "direction": "LONG", "entry": _close20,
                        "sl": _sl_base - _buf20i,
                        "wall": float(_band_hi20),
                        "tp1": _close20 + _path / 5.0 if _path > 0 else _wall,
                        "tp2": _wall,
                        "pattern": str(_band20.get("kind") or "RANGE"),
                    }
            elif candidate.direction == "SHORT" and _close20 >= _band_hi20 - 0.20 * _w20:
                _bear_pin = ((_h20 - max(_o20, _close20)) >= 2.0 * max(_body20, 1e-12)
                             and (_close20 - _l20) <= 0.35 * _rng20)
                _bear_engulf = (_prev_c20 > _prev_o20 and _close20 < _o20
                                and _o20 >= _prev_c20 and _close20 <= _prev_o20)
                _bear_close = _close20 < _o20 and _close20 < _prev_c20
                if _bear_pin or _bear_engulf or _bear_close:
                    _wall = _band_lo20 + _buf20i
                    _path = max(_close20 - _wall, 0.0)
                    # mirror: behind the channel ceiling AND the last swing
                    # high that built it, plus the buffer.
                    _swing_hi20 = float(closed_df["high"].tail(20).max())
                    _sl_base = max(_band_hi20, _swing_hi20)
                    _internal_plan = {
                        "direction": "SHORT", "entry": _close20,
                        "sl": _sl_base + _buf20i,
                        "wall": float(_band_lo20),
                        "tp1": _close20 - _path / 5.0 if _path > 0 else _wall,
                        "tp2": _wall,
                        "pattern": str(_band20.get("kind") or "RANGE"),
                    }
        except Exception:
            _internal_plan = None
    if _internal_plan:
        _md20["viva_entry_type"] = "INTERNAL"
        _md20["internal_entry"] = {k: (round(v, 10) if isinstance(v, float) else v)
                                   for k, v in _internal_plan.items()}
        _md20["internal_wall"] = float(_internal_plan.get("wall") or 0.0)
        _md20["internal_path_fa"] = (
            f"هدف: تا کف الگو ({_internal_plan['tp2']:.8g}) — خروج در TP1..TP3 یعنی "
            f"۶۰٪ مسیر، پیش از رسیدن به ضلع مقابل." if _internal_plan["direction"] == "SHORT" else
            f"هدف: تا سقف الگو ({_internal_plan['tp2']:.8g}) — خروج در TP1..TP3 یعنی "
            f"۶۰٪ مسیر، پیش از رسیدن به ضلع مقابل.")
        _md20["internal_entry_note_fa"] = (
            f"ورود از کف {_internal_plan['pattern']} با تأیید کندل بسته‌شده؛ استاپ پشت "
            "کانال با بافر و اهداف زیر سقف کانال." if _internal_plan["direction"] == "LONG" else
            f"ورود از سقف {_internal_plan['pattern']} با تأیید کندل بسته‌شده؛ استاپ بالای "
            "کانال با بافر و اهداف بالای کف کانال.")
        candidate.planned_entry = float(_internal_plan["entry"])
        candidate.sl = float(_internal_plan["sl"])
        candidate.tp1 = float(_internal_plan["tp1"])
        candidate.tp2 = float(_internal_plan["tp2"])
        _is_internal = True
    # ── Viva 09-21 (round 15), verbatim: «دقیقاً چرا این ستاپ‌ها مثل احمق‌ها
    # موقعیت رو می‌شناسن اما تایید نمی‌کنن؟» — the live case was ETHFIUSDT 1h:
    # the fast lane DID find the first valid close beyond the named pin level
    # (0.7482), and then this containment gate vetoed it with
    # INSIDE_PATTERN_NO_BREAK because a fitted wedge band still contained the
    # price. Two corrections:
    #   • a PINBAR premise (PINVAL/PINWALLQ) is a level, not a pattern, so a
    #     pattern band may never veto it;
    #   • once the engine has evidence of a valid close beyond the named level,
    #     containment cannot contradict it — the level is the authority
    #     («اولین کلوز بالا یا پایین هر ناحیه/ترند = تأیید»).
    _pattern_premise = str(getattr(candidate, "setup_code", "") or "").upper() in {
        "TLBREAK", "TECHCLASSIC", "ALBROX"}
    _fast_lane_ok = bool((candidate.metadata or {}).get("tl_fast_break"))
    # …and when the fast lane fired, containment only speaks if the level that
    # was actually cleared sits INSIDE the pattern (a mirror-zone edge, not the
    # pattern's own side). Clearing the pattern's own side is the breakout.
    _lvl_used20 = float((candidate.metadata or {}).get("confirm_level_used") or 0.0)
    _inside_band20 = False
    if _fast_lane_ok and _lvl_used20 > 0 and _band_lo20 is not None and _band_hi20 is not None:
        _inside_band20 = (float(_band_lo20) + 1e-12) < _lvl_used20 < (float(_band_hi20) - 1e-12)
    if (_band_lo20 is not None and _band_hi20 is not None and not _is_internal
            and _pattern_premise and (not _fast_lane_ok or _inside_band20)):
        _dir20 = 1.0 if candidate.direction == "LONG" else -1.0
        _buf20 = 0.10 * _atr20
        _outside20 = (_close20 >= _band_hi20 + _buf20) if _dir20 > 0 \
            else (_close20 <= _band_lo20 - _buf20)
        if not _outside20:
            _opposite = (_close20 < _band_lo20 - _buf20) if _dir20 > 0 \
                else (_close20 > _band_hi20 + _buf20)
            if _opposite:
                return reject("BREAK_SIDE_MISMATCH", (
                    f"جهت شکست ناهمسو است: کلوز {_close20:.8g} بیرون ضلع "
                    f"{'پایین' if _dir20 > 0 else 'بالای'} الگوی "
                    f"{_band20.get('kind')} رفته، در حالی که سناریو "
                    f"{'لانگ' if _dir20 > 0 else 'شورت'} است؛ تأیید صادر نمی‌شود."))
            return reject("INSIDE_PATTERN_NO_BREAK", (
                f"قیمت هنوز داخل الگو ({_band20.get('kind')}) است — کلوز "
                f"{_close20:.8g} داخل باند {_band_lo20:.8g}–{_band_hi20:.8g}؛ "
                "تأیید فقط با کلوزِ بیرونِ ضلع پایین/بالای الگو (شکست + کلوز) معتبر است."))
        _md20["pattern_cleared"] = True
    # ── Viva 09-21 (round 15 phase 2) — ONE break-side law for ALL five setups.
    # His verbatim: «شورت روی شکست خط روند صعودی» (an ascending/long trend line
    # broken UP and the system still publishing SHORT) plus his own chart list
    # where a FALLING WEDGE — a bullish compression — went out as SHORT although
    # price had closed ABOVE that wedge. He asked for the metadata set
    # (pattern_type · pattern_bias · break_edge · break_direction ·
    # trade_direction · direction_reason) and for one shared law:
    # «اگر pattern_bias با break_direction و trade_direction سازگار نیست:
    # سیگنال تأیید نشود». So: whatever side actually broke must BE the trade
    # direction; the opposite is void. A bias that conflicts with the broken
    # side is not void — it is a BREAK of that pattern and must be published
    # under a different STATE NAME (his words), never as the pattern's reversal.
    if not _is_internal and _atr20 > 0:
        try:
            _mdg = candidate.metadata if candidate.metadata is not None else {}
            _kind_g = str((_band20 or {}).get("kind") or "").upper()
            _bias_g = pattern_bias_of(_kind_g)
            _dir_g = str(candidate.direction or "").upper()
            _buf_g = 0.10 * _atr20
            _brk_up = _brk_dn = False
            if _band_lo20 is not None and _band_hi20 is not None:
                _brk_up = bool(_close20 >= float(_band_hi20) + _buf_g)
                _brk_dn = bool(_close20 <= float(_band_lo20) - _buf_g)
            _mdg["pattern_type"] = _kind_g or "NONE"
            _mdg["pattern_bias"] = _bias_g
            _mdg["trade_direction"] = _dir_g
            if _brk_up and not _brk_dn:
                _mdg["break_edge"] = "UPPER"
                _mdg["break_direction"] = "UP"
            elif _brk_dn and not _brk_up:
                _mdg["break_edge"] = "LOWER"
                _mdg["break_direction"] = "DOWN"
            if _brk_up and not _brk_dn and _dir_g == "SHORT":
                return reject("BREAK_SIDE_MISMATCH", (
                    f"جهت شکست با جهت سناریو ناهمسو است: کلوز {_close20:.8g} از ضلع "
                    f"بالای {_mdg['pattern_type']} (بالای {float(_band_hi20):.8g}) "
                    "بیرون زده — یعنی شکست صعودی — اما سناریو شورت است. طبق قانون "
                    "«جهت معامله = جهت ضلع شکسته»، این سناریو تأیید نمی‌شود؛ اگر "
                    "شرایط لانگ کامل است، باید کاندیدای لانگِ تازه با شناسهٔ تازه "
                    "ساخته شود، نه تبدیل همین شورت."))
            if _brk_dn and not _brk_up and _dir_g == "LONG":
                return reject("BREAK_SIDE_MISMATCH", (
                    f"جهت شکست با جهت سناریو ناهمسو است: کلوز {_close20:.8g} از ضلع "
                    f"پایین {_mdg['pattern_type']} (زیر {float(_band_lo20):.8g}) "
                    "بیرون زده — یعنی شکست نزولی — اما سناریو لانگ است. طبق قانون "
                    "«جهت معامله = جهت ضلع شکسته»، این سناریو تأیید نمی‌شود."))
            if _bias_g == "BULL" and _brk_dn:
                _mdg["pattern_state_label"] = f"{_mdg['pattern_type']} · BREAKDOWN"
                _mdg["direction_reason"] = (
                    "شکست نزولی از ضلع پایین الگو — این حالت «شکست» است، نه "
                    "برگشتِ صعودیِ الگو؛ نام وضعیت روی چارت با همین برچسب می‌آید.")
            elif _bias_g == "BEAR" and _brk_up:
                _mdg["pattern_state_label"] = f"{_mdg['pattern_type']} · BREAKOUT_UP"
                _mdg["direction_reason"] = (
                    "شکست صعودی از ضلع بالای الگو — این حالت «شکست» است، نه "
                    "برگشتِ نزولیِ الگو؛ نام وضعیت روی چارت با همین برچسب می‌آید.")
            elif _bias_g == "BULL":
                _mdg["direction_reason"] = "شکست صعودی در جهت الگوی صعودی"
            elif _bias_g == "BEAR":
                _mdg["direction_reason"] = "شکست نزولی در جهت الگوی نزولی"
            elif _brk_up or _brk_dn:
                _mdg["direction_reason"] = "شکست در جهت معامله (الگوی خنثی)"
            # the state name must reach the canvas: the chart reads render_patterns
            _lbl_g = _mdg.get("pattern_state_label")
            if _lbl_g:
                for _rp in (_mdg.get("render_patterns") or []):
                    try:
                        if str(_rp.get("type") or "").upper() == _mdg["pattern_type"]:
                            _rp["label"] = _lbl_g
                    except Exception:
                        continue
        except Exception:
            pass
    # deep re-entry: close back beyond the broken line/zone by >0.5×ATR inside
    _edge20 = _edge if _edge > 0 else _zone_edge
    _deep20 = False
    if not _is_internal:
        _deep20 = (_close20 < _edge20 - 0.5 * _atr20) if candidate.direction == "LONG" \
            else (_close20 > _edge20 + 0.5 * _atr20)
    if _deep20:
        _md20["deep_pullback"] = True
        _md20["deep_pullback_at"] = str(_row20["timestamp"])[:16]
    elif _close20 != 0:
        # price is back on the correct side of the broken edge → the touch/
        # near-touch pullback lane is open again (no new break required)
        _md20.pop("deep_pullback", None)
    candidate.metadata = _md20
    candidate.metadata["touched"] = touched
    if not touched:
        return reject("NO_TOUCH", "قیمت هنوز به لبهٔ ناحیه/خط نرسیده؛ با یک کلوزِ معتبرِ فراتر از لبه تأیید می‌شود.")

    row = closed_df.iloc[-1]
    previous = closed_df.iloc[-2]
    # --- alternative multi-candle / higher-TF trigger evaluation ----------
    # The pin bar is one sign among several; a base of 2..N closed trigger
    # candles that aggregates into a pin / doji-break / engulf / reclaim at
    # the zone is an equally valid trigger. Computed once, consumed by both
    # the Viva state machine and the generic trigger below.
    alt = None
    if bool(getattr(SETTINGS, "alt_triggers_enabled", True)):
        _atr_alt = float(candidate.metadata.get("atr", 0) or 0)
        if _atr_alt <= 0:
            _atr_alt = float((closed_df["high"] - closed_df["low"]).tail(14).mean() or 0.0)
        try:
            from analysis.trigger_patterns import multi_candle_trigger
            alt = multi_candle_trigger(
                closed_df, candidate.direction,
                float(candidate.entry_zone_bottom), float(candidate.entry_zone_top),
                _atr_alt,
                max_base=int(getattr(SETTINGS, "alt_cluster_max_base", 9)),
                min_body_atr=float(getattr(SETTINGS, "alt_cluster_min_body_atr", 0.30)),
                require_zone_mid=bool(SETTINGS.confirm_require_zone_mid),
                mtf_enabled=bool(getattr(SETTINGS, "alt_mtf_enabled", True)),
                fibo_enabled=bool(getattr(SETTINGS, "alt_fibo_confluence", True)),
            )
        except Exception as _alt_exc:
            alt = None
            candidate.metadata["alt_trigger_error"] = str(_alt_exc)[:120]
    # Isolated Viva-TLBREAK state machine: retest, then rejection, then a
    # later closed micro-BOS. Other strategies keep their existing behavior.
    if candidate.metadata.get("strategy_variant") == "VIVA_TLBREAK":
        from analysis.viva_tlbreak import advance_live_state
        atr_state = float(candidate.metadata.get("atr", 0) or 0)
        if atr_state <= 0:
            atr_state = float((closed_df["high"] - closed_df["low"]).tail(14).mean())
        state, ready = advance_live_state(candidate.metadata, row, previous, candidate.direction, zone_low=candidate.entry_zone_bottom, zone_high=candidate.entry_zone_top, atr_value=atr_state)
        from analysis.viva_tlbreak_state import VivaTLState, advance as advance_viva_state
        machine = VivaTLState.from_payload(candidate.metadata.get("viva_state_machine"))
        event_map = {"S3_RETEST": "RETEST", "S4_REJECTION": "REJECTION", "S5_MICRO_BOS": "MICRO_BOS"}
        if state in event_map:
            machine = advance_viva_state(machine, event_map[state], max_retest_bars=int(candidate.metadata.get("viva_retest_window_bars", 16)))
        if ready:
            machine = advance_viva_state(machine, "CONFIRM", max_retest_bars=int(candidate.metadata.get("viva_retest_window_bars", 16)))
        candidate.metadata["viva_state"] = state
        candidate.metadata["viva_state_machine"] = machine.payload()
        if not ready and alt is not None and state in ("S3_RETEST", "S4_REJECTION"):
            # Cluster/MTF rejection at the retest counts as the rejection+BOS
            # event pair compressed into one base — the state machine may
            # confirm through it (fast lane), never the other way around.
            ready = True
            state = "S5_MICRO_BOS"
            machine = advance_viva_state(machine, "CONFIRM", max_retest_bars=int(candidate.metadata.get("viva_retest_window_bars", 16)))
            candidate.metadata["viva_state"] = state
            candidate.metadata["viva_state_machine"] = machine.payload()
            candidate.metadata["viva_fast_alt"] = alt.kind
        if not ready and fast_lane:
            machine = advance_viva_state(machine, "FAST_CONFIRM",
                                         max_retest_bars=int(candidate.metadata.get("viva_retest_window_bars", 16)))
            candidate.metadata["viva_state_machine"] = machine.payload()
            candidate.metadata["viva_state"] = "S6_CONFIRMED"
            ready, state = True, "S6_CONFIRMED"
        if not ready and str(candidate.metadata.get("viva_state") or "") == "S6_CONFIRMED":
            # Viva 2026-09-12: once the ONE-CLOSE law has fired (fast lane set
            # S6 on an earlier tick), the verdict must survive — a downstream
            # RR/chase rejection on that tick used to freeze the chain in
            # WAIT_S6_CONFIRMED forever, which is exactly what killed the
            # runaways («یه چیزی داره جلوی تاییدها رو میگیره»). Invalidation and
            # expiry keep full veto over the scenario; the close itself does not.
            state, ready = "S6_CONFIRMED", True
        if not ready:
            return reject("VIVA_TLBREAK_WAIT_" + state, "VIVA-TLBREAK در انتظار Retest → Rejection → BOS پنج‌دقیقه‌ای است.")
    close, open_price = float(row["close"]), float(row["open"])
    previous_high, previous_low = float(previous["high"]), float(previous["low"])
    displacement = candle_displacement(closed_df, -1, atr_multiple=0.55)
    zone_mid = candidate.zone_mid

    candle_range = max(float(row["high"]) - float(row["low"]), 1e-12)
    body_top, body_bottom = max(open_price, close), min(open_price, close)
    upper_wick = float(row["high"]) - body_top
    lower_wick = body_bottom - float(row["low"])
    require_mid = SETTINGS.confirm_require_zone_mid
    if candidate.direction == "LONG":
        directional = close > open_price and (close > zone_mid if require_mid else True)
        structure_trigger = close > previous_high
        engulfing = open_price <= float(previous["close"]) and close >= float(previous["open"])
        pinbar = lower_wick >= 0.55 * candle_range and upper_wick <= 0.20 * candle_range
        invalid = close <= candidate.sl
    else:
        directional = close < open_price and (close < zone_mid if require_mid else True)
        structure_trigger = close < previous_low
        engulfing = open_price >= float(previous["close"]) and close <= float(previous["open"])
        pinbar = upper_wick >= 0.55 * candle_range and lower_wick <= 0.20 * candle_range
        invalid = close >= candidate.sl

    if invalid:
        return reject("CLOSE_THROUGH_INVALIDATION", "کندل بسته‌شده از سطح ابطال عبور کرده است.")
    trigger_valid = (
        directional
        and (structure_trigger or engulfing or pinbar)
        and displacement["body_atr"] >= SETTINGS.confirm_body_min_atr
    )
    alt_only = False
    if not trigger_valid and str(candidate.metadata.get("viva_state") or "") == "S6_CONFIRMED" \
            and candidate.metadata.get("strategy_variant") == "VIVA_TLBREAK":
        trigger_valid = True  # the valid close that set S6 was the trigger
    if not trigger_valid and candidate.metadata.get("tl_fast_break"):
        trigger_valid = True
        candidate.metadata["trigger_note"] = "اولین کلوزِ معتبر پشت خط/لبه (بدون پولبک)"
    if not trigger_valid and alt is not None:
        trigger_valid = True
        alt_only = True
    if not trigger_valid:
        return reject("NO_TRIGGER", (
            "Retest انجام شده، اما هنوز نه کندل تکی تأییدی و نه بیس چندکندلی/تایم‌بالاتری "
            "شدنِ Rejection را نساخته‌اند."
        ))
    # Viva 09-20 (his own OR): after a deep re-entry into the broken zone the
    # confirmation must come EITHER from a fresh break+close (the fast lane) OR
    # from a valid closed price-action pattern (Brooks pin/engulf at the zone) —
    # a bare touch is never enough (that is enforced by trigger_valid below).
    if candidate.metadata.get("deep_pullback"):
        candidate.metadata["deep_pullback_note"] = (
            "پولبک عمیق به ناحیهٔ شکسته — تأیید با کلوزِ معتبرِ کندلی (پرایس‌اکشن) "
            "یا شکست و کلوز تازه صادر شده است."
            if (trigger_valid or fast_lane) else
            "پولبک عمیق به ناحیهٔ شکسته؛ هنوز نه کندل تأییدی و نه شکست تازه.")

    # The executable entry is the confirmation close, not the historical POI
    # midpoint. Reject a late confirmation if its real risk/reward has degraded.
    executable_entry = close
    risk = abs(executable_entry - candidate.sl)
    # ── his 09-21 ruling, verbatim: «استاپ اصلا ساختاری اگر فاصله داشت حذف نشه و
    # تا ۱.۲۵ قیمت نماد محاسبه بشه» — the confirmation uses a stop that is CUT at
    # 1.25% of price instead of refusing the scenario (the VVV 1h chain sat
    # «منتظر» for two days because DEGENERATE_GEOMETRY rejected every cycle).
    try:
        from analysis.trade_management import clamp_stop_price as _clamp_q
        _q_sl, _q_clamped = _clamp_q(executable_entry, candidate.direction, candidate.sl,
                                     str(candidate.trigger_timeframe or ""))
        if _q_clamped:
            candidate.sl = float(_q_sl)
            candidate.metadata["stop_clamped"] = True
            candidate.metadata["stop_clamp_note"] = (
                "استاپ ساختاری دورتر از سقفِ این تایم‌فریم بود؛ طبق قانون ۰۹-۲۱ استاپ "
                "روی همان سقف تنظیم شد و سناریو حفظ شد.")
            risk = abs(executable_entry - float(candidate.sl))
    except Exception:
        pass
    if risk <= 0:
        return reject("RISK_INVALID", "فاصله Entry تأییدشده تا حد ضرر معتبر نیست.")
    # R28: confirmation must not turn a tiny structural stop into a trade.
    # The initial stop remains the candidate's structural invalidation; if its
    # distance is below the timeframe floor, reject instead of moving it closer
    # to the entry or silently manufacturing risk geometry.
    try:
        from analysis.trade_management import initial_stop_is_valid
        if not initial_stop_is_valid(executable_entry, candidate.direction,
                                     float(candidate.sl), str(candidate.trigger_timeframe or "15m")):
            return reject("STOP_TOO_TIGHT",
                          "استاپ اولیه نسبت به تایم‌فریم بسیار نزدیک است؛ "
                          "سناریو بدون ساختار معتبرِ ابطال منتشر نمی‌شود.")
    except Exception:
        pass
    # ── «مدیریت ویوا» §4 (09-20): TF distance ceiling for the FINAL target ──
    # A structural level 19% away on a 15m trade is a different trade; the
    # ceiling (1d 10% · 4h 7% · 1h/15m 5%) clamps TP2 so the five-segment
    # ladder stays inside a distance this timeframe can travel. Nothing here
    # derives a target from stop distance or a fixed R:R ratio (§3.3/§11).
    try:
        from analysis.trade_management import cap_final_target
        _capped_tp2, _was_capped, _cap_pct = cap_final_target(
            executable_entry, candidate.tp2, candidate.direction,
            str(candidate.trigger_timeframe or "15m"))
        if _was_capped:
            candidate.metadata["target_cap_note"] = (
                f"هدف نهایی مطابق سقف فاصلهٔ تایم‌فریم ({_cap_pct:.0f}% قیمت) "
                f"محدود شد؛ هدف ساختاری خام {candidate.tp2:.8g} بود.")
            candidate.metadata["raw_structural_tp2"] = float(candidate.tp2)
            candidate.tp2 = float(_capped_tp2)
            # keep the five-part doctrine intact after the clamp: TP1 is one
            # fifth of the CAPPED path (round 11), never a leftover ratio.
            if candidate.direction == "LONG" and candidate.tp2 > executable_entry:
                candidate.tp1 = executable_entry + (candidate.tp2 - executable_entry) / 5.0
            elif candidate.direction == "SHORT" and candidate.tp2 < executable_entry:
                candidate.tp1 = executable_entry - (executable_entry - candidate.tp2) / 5.0
    except Exception:
        pass
    atr_value = float(candidate.metadata.get("atr", 0) or 0)
    if atr_value > 0:
        chase_atr = abs(executable_entry - zone_mid) / atr_value
        max_chase = float(getattr(SETTINGS, "confirm_max_chase_atr", 0.80))
        # the fast-break lane may confirm a little beyond the zone, never from
        # a runaway price (his VVV case: 12.88 ATR away and still «in progress»).
        _fb_max = float(getattr(SETTINGS, "fast_break_max_chase_atr", 1.5))
        _fast_ok = bool(candidate.metadata.get("tl_fast_break")) and chase_atr <= _fb_max
        if chase_atr > max_chase and not _fast_ok:
            return reject("ENTRY_TOO_FAR", f"کلوز تأیید {chase_atr:.2f} ATR از زون دور شده؛ Chase مجاز نیست.")
        if chase_atr > max_chase:
            # a fresh single-close break IS far from the zone by nature —
            # annotate the distance for the caption, Viva decides the trade.
            candidate.metadata["chase_note"] = f"{chase_atr:.2f} ATR از زون"
    rr1 = (
        (candidate.tp1 - executable_entry) / risk
        if candidate.direction == "LONG"
        else (executable_entry - candidate.tp1) / risk
    )
    rr2 = (
        (candidate.tp2 - executable_entry) / risk
        if candidate.direction == "LONG"
        else (executable_entry - candidate.tp2) / risk
    )
    # ── Viva 09-20 (verbatim, third time): «هیچ ارتباطی بین اندازه فاصله قیمت
    # تا استاپ یا تارگت‌ها قرار نده ... من نمی‌خوام فرمول ریسک به ریوارد ...
    # اصلا اهمیت نداره» → R:R NEVER gates an entry. It is REPORTED only.
    # The old degraded-ratio rejection is gone; the ratio rides the message.
    candidate.metadata["rr_readout"] = f"R/R (فقط گزارش): {rr1:.2f}R / {rr2:.2f}R — مبنای تصمیم نیست"
    # Hard geometry sanity stays, but it no longer speaks the language of R:R
    # (his stop distance must not define the tool). Two absolute defects are
    # still rejected: a tool whose whole target span is a rounding error
    # («ابزار بی‌معنی»), and a stop absurdly far for this timeframe (the SUI
    # 1D case: a 64%-away invalidation against a 10% daily ceiling).
    try:
        from analysis.trade_management import target_distance_cap_pct
        _cap_abs = executable_entry * target_distance_cap_pct(
            str(candidate.trigger_timeframe or "15m")) / 100.0
        _span_frac = abs(float(candidate.tp2) - executable_entry) / max(executable_entry, 1e-12)
        _sl_frac = risk / max(executable_entry, 1e-12)
        _atr_abs = float(candidate.metadata.get("atr", 0) or 0) or \
            float((closed_df["high"] - closed_df["low"]).tail(14).mean() or 0.0)
        _span_floor = max(0.6 * _atr_abs / max(executable_entry, 1e-12), 0.003)
        # ── round 12 (his «هنوز باگ داریم»): the stop must sit on the side of
        # THIS scenario, measured from the price the confirmation trades from.
        _wrong_side = ((candidate.direction == "LONG" and float(candidate.sl) >= executable_entry)
                       or (candidate.direction == "SHORT" and float(candidate.sl) <= executable_entry))
        if _wrong_side:
            return reject("STOP_WRONG_SIDE", (
                f"استاپ در سمت اشتباه سناریو است: برای "
                f"{'لانگ باید زیر ورود' if candidate.direction == 'LONG' else 'شورت باید بالای ورود'} "
                f"باشد (ورود {executable_entry:.8g} · استاپ {float(candidate.sl):.8g})؛ "
                "پیام صادر نمی‌شود تا هندسه تصحیح شود."))
        # ── Viva 09-21 (round 15 phase 2): «R:R -0.07 / 0.42 و PATH 0.00%
        # ولی سیگنال Confirmed» — a ladder whose first rung is not even on the
        # trade's side of the entry, or whose whole path is a rounding error,
        # is a broken tool and must never confirm.
        _lad_g = (candidate.metadata or {}).get("target_ladder") or {}
        _path_g = float(_lad_g.get("path_pct") or 0.0)
        _tp1_bad = ((str(candidate.direction).upper() == "LONG" and float(candidate.tp1) <= executable_entry)
                    or (str(candidate.direction).upper() == "SHORT" and float(candidate.tp1) >= executable_entry))
        if _tp1_bad:
            return reject("ENTRY_AFTER_TARGET", (
                f"نردبان هدف معکوس است: ورود {executable_entry:.8g} ولی TP1 "
                f"{float(candidate.tp1):.8g} در سمت اشتباه است؛ ابزار نامعتبر و "
                "تأییدی صادر نمی‌شود."))
        if 0.0 < _path_g < 0.5:
            return reject("ZERO_TARGET_PATH", (
                f"مسیر هدف تقریباً صفر است ({_path_g:.3f}٪ از ورود) — نردبانی که "
                "حرکت ندارد ابزار نیست؛ سناریو فقط هشدار/تحلیل می‌ماند."))
        _tol_cap_abs = _cap_abs * 1.20 if _cap_abs > 0 else 0.0   # ±20% tolerance
        if _span_frac < _span_floor or (_tol_cap_abs > 0 and risk > _tol_cap_abs):
            return reject("DEGENERATE_GEOMETRY", (
                f"هندسهٔ ابزار بی‌معنی است: استاپ {_sl_frac * 100:.1f}% از ورود دور است "
                f"در حالی که افق همین تایم‌فریم "
                f"{target_distance_cap_pct(str(candidate.trigger_timeframe or '15m')):.0f}% است "
                f"(مسیر هدف {_span_frac * 100:.2f}%)؛ سناریو فقط هشدار/تحلیل می‌ماند. "
                "طبق قانون ۰۹-۲۱ استاپ باید پشت آخرین سویینگ با بافر و داخل همین افق باشد."))
    except Exception:
        pass
    candidate.planned_entry = executable_entry
    candidate.rr_tp1 = rr1
    candidate.rr_tp2 = rr2

    if not candidate.execution_ready:
        missing = [name for name, valid in candidate.mandatory_gates.items() if not valid]
        return reject("GATES_INCOMPLETE", f"شروط اجباری تکمیل نیست: {', '.join(missing)}")


    if structure_trigger:
        trigger_type = f"{'سقف' if candidate.direction == 'LONG' else 'کف'} Micro Structure قبلی را شکست"
    elif engulfing:
        trigger_type = "یک Engulfing معتبر در جهت سناریو تشکیل داد"
    elif pinbar:
        trigger_type = "یک Pin Bar معتبر با رد قیمت از ناحیه تشکیل داد"
    else:
        # Viva 09-19 hotfix (AVAX PINWALL-Q crash): the S6/fast-break lanes
        # validate the trigger WITHOUT any candle pattern, so alt can still
        # be None here — describe(None) used to kill the candidate cycle.
        if alt is not None:
            from analysis.trigger_patterns import describe as describe_alt_trigger
            trigger_type = describe_alt_trigger(alt, candidate.direction)
        elif str(candidate.metadata.get("viva_state") or "") == "S6_CONFIRMED" \
                and candidate.metadata.get("strategy_variant") == "VIVA_TLBREAK":
            trigger_type = "کلوز معتبرِ سازندهٔ S6 (Retest→Rejection→BOS)"
        else:
            trigger_type = "اولین کلوز معتبر پشت خط/لبه (بدون پولبک)"
    if alt_only:
        trigger_detail = (
            f"پس از اولین تماس با ناحیه، هیچ کندل تکیِ پین‌باری وجود نداشت؛ خودِ {trigger_type} "
            f"تاییدیه‌ی بسته‌شدنِ بیس است. تأیید بر اساس کندل‌های بسته‌شده صادر شده، نه قیمت لحظه‌ای."
        )
        candidate.metadata["alt_trigger_kind"] = alt.kind
    else:
        trigger_detail = (
            f"پس از اولین تماس با ناحیه، کندل {candidate.trigger_timeframe.upper()} در جهت {candidate.direction} بسته شد و {trigger_type}. "
            f"بدنه کندل {displacement['body_atr']:.2f} برابر ATR بود. بنابراین تأیید بر اساس کندل بسته‌شده صادر شده، "
            f"نه قیمت لحظه‌ای یا Wick موقت."
        )
    # Replace a previous trigger item without inflating score on publication retries.
    had_trigger = any(item.key == "entry_trigger" for item in candidate.evidence)
    candidate.evidence = [item for item in candidate.evidence if item.key != "entry_trigger"]
    candidate.evidence.append(EvidenceItem("entry_trigger", "کندل تأیید ورود", trigger_detail, True, 1, timeframe=candidate.trigger_timeframe))
    if not had_trigger:
        candidate.score = min(10, candidate.score + 1)
    if candidate.score < SETTINGS.execution_min_score:
        return reject("SCORE_LOW", f"امتیاز نهایی {candidate.score} کمتر از حد اجرای {SETTINGS.execution_min_score} است.")
    candidate.status = "CONFIRMED"
    candidate.confirmed_at = candidate.confirmed_at or iso_now()
    candidate.metadata["technical_confirmation_complete"] = True
    # ── Viva 09-19/20 counter-trend & MTF-zone confirmation laws ──────────
    # (a) A TOUCH is never a confirmation against the structure: counter
    #     setups need a closed structure break in the trade direction (close
    #     beyond the nearest swing); 1D counters additionally need the 4H
    #     structure break first (ZEC ruling: sellers get hunted at the touch).
    # (b) No LONG confirmation at the edge of a parent-TF supply cluster and
    #     no SHORT at a parent-TF demand cluster (0.5×ATR(parent) band) —
    #     fractal chain 15m→1h→4h→1d, never small-TF-vs-daily.
    try:
        from data.fetcher import get_klines as _gk
        _trg_tf = str(candidate.trigger_timeframe or "").lower()
        _close_px = float(close)
        _parent_tf = {"5m": "15m", "15m": "1h", "30m": "1h", "1h": "4h",
                      "2h": "4h", "4h": "1d"}.get(_trg_tf)
        _pdf = None
        if _parent_tf:
            _pdf = _gk(candidate.symbol, _parent_tf, 200, closed_only=True)
        _counter = bool(candidate.metadata.get("tl_context_conflict"))
        if _pdf is not None and len(_pdf) >= 40 and not _counter:
            _pc = float(_pdf["close"].iloc[-1])
            _pc0 = float(_pdf["close"].iloc[-30])
            _counter = ((candidate.direction == "LONG" and _pc < _pc0)
                        or (candidate.direction == "SHORT" and _pc > _pc0))
        if _counter and len(closed_df) >= 12:
            _prior = closed_df.iloc[-11:-1]
            if candidate.direction == "SHORT":
                _brk = _close_px < float(_prior["low"].min())
            else:
                _brk = _close_px > float(_prior["high"].max())
            if not _brk:
                return reject("COUNTER_TREND_TOUCH_ONLY", (
                    "سیگنال خلاف جهت ساختار است: برخورد به خط/ناحیه فقط هشدار است؛ "
                    "تأیید نیازمند کلوز معتبر فراتر از سوینگ هم‌جهت است "
                    "(سلرها/خریداران در برخورد شکار می‌شوند)."))
            if _trg_tf == "1d" and _pdf is not None and len(_pdf) >= 12:
                _pp = _pdf.iloc[-11:-1]
                if candidate.direction == "SHORT":
                    _hbrk = float(_pdf["close"].iloc[-1]) < float(_pp["low"].min())
                else:
                    _hbrk = float(_pdf["close"].iloc[-1]) > float(_pp["high"].max())
                if not _hbrk:
                    return reject("COUNTER_1D_NEEDS_4H_BREAK", (
                        "خلاف جهت در تایم روزانه: ابتدا کلوزِ بریک ساختار در ۴ساعته لازم است، "
                        "سپس کلوز روزانه فراتر از ضلع پایین/بالای الگو."))
        if _pdf is not None and len(_pdf) >= 40:
            from analysis.indicators import pivots as _pv
            _ph, _pl = _pv(_pdf.reset_index(), 3, 3)
            _patr = float((_pdf["high"] - _pdf["low"]).tail(14).mean() or 0.0)
            if _patr > 0 and _ph and _pl:
                _band = 0.5 * _patr
                if candidate.direction == "LONG":
                    _near = [float(x["price"]) for x in _ph[-6:]
                             if 0.0 <= (float(x["price"]) - _close_px) <= _band]
                else:
                    _near = [float(x["price"]) for x in _pl[-6:]
                             if 0.0 <= (_close_px - float(x["price"])) <= _band]
                if _near:
                    return reject("NEAR_OPPOSING_ZONE_MTF", (
                        f"قیمت در آستانهٔ ناحیه مخالف در تایم والد ({_parent_tf}) است "
                        f"(فاصله ≤ ۰٫۵×ATR والد): لانگ زیر سقف/عرضه و شورت بالای کف/تقاضا "
                        "تأیید نمی‌شود؛ ابتدا شکست معتبر، سپس تأیید در پولبک."))
    except Exception as _gexc:
        candidate.metadata["mtf_gate_error"] = str(_gexc)[:120]

    # a confirmed scenario must never keep a stale reject code (the ETHFIUSDT
    # replay showed last_reject_code="INSIDE_PATTERN_NO_BREAK" on a CONFIRMED
    # row — the log then blamed a gate that had already been overruled).
    try:
        candidate.metadata.pop("last_reject_code", None)
        candidate.metadata.pop("last_reject_fa", None)
    except Exception:
        pass
    return True, candidate, "تأیید ورود با کندل بسته‌شده صادر شد."
