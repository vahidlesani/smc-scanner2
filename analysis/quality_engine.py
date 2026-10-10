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
        # mid-term swing trigger streams. Viva 09-16 gave TWO (1h, 4h);
        # r48 (Viva 09-27, «۳۰ دقیقه و ۲ ساعته بعنوان تریگر جدید به ۴ ستاپ
        # فیوچرز اضافه بشه») adds 30m and 2h. The zones come from the SAME
        # engines (his rule: «از فرمول بدست بیاد، دوباره اسکن نشه») — these
        # are extra streams over the identical bundle, and the 30m/2h tapes
        # are resampled locally from the 15m/4h bases (zero extra requests).
        from analysis import setups_v7
        out: List[SignalCandidate] = []
        for trig, profile in (("30m", ("2h", "1h", "30m")),
                              ("1h", ("1d", "4h", "1h")),
                              ("2h", ("1d", "4h", "2h")),
                              ("4h", ("1d", "4h", "4h"))):
            setups_v7.PROFILE_OVERRIDE["SWING"] = profile
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

    # R29 live execution-integrity layer: CORE/CONTEXT/EXECUTION stay separate.
    # This is additive metadata only; Telegram/public IDs/link chains are untouched.
    try:
        from analysis.execution_integrity_r29 import apply_r29
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
                _r29 = apply_r29(candidate, frames)
                candidate.metadata["r29_execution"] = _r29
                # Execution is a separate gate: preserve the observation and
                # expose the reason, but do not silently manufacture a CORE.
                candidate.metadata["r29_execution_state"] = _r29.get("EXECUTION_STATE", "UNKNOWN")
                candidate.metadata["r29_execution_reasons"] = list(
                    ((_r29.get("ExecutionGate") or {}).get("reasons") or [])
                )
            except Exception as _r29_exc:
                candidate.metadata["r29_execution_error"] = str(_r29_exc)[:240]
    except Exception as _r29_outer_exc:
        for candidate in candidates:
            candidate.metadata["r29_execution_error"] = str(_r29_outer_exc)[:240]

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
    # R31 free market-intelligence layer: one cached public-data snapshot per symbol.
    # Additive metadata only — no setup core, score, direction, ID, chart geometry,
    # Telegram format, or execution gate is changed here.
    try:
        from analysis.market_intelligence import build_market_intelligence
        _market_intel = build_market_intelligence(bundle)
        for candidate in candidates:
            candidate.metadata["market_intelligence"] = dict(_market_intel)
            # Persist the same evidence packet into market_json so the WebApp can
            # display it without creating a second scanner or analysis engine.
            market = dict(candidate.market or {})
            market["market_intelligence"] = dict(_market_intel)
            candidate.market = market
    except Exception as _mi_exc:
        for candidate in candidates:
            candidate.metadata["market_intelligence_error"] = str(_mi_exc)[:240]

    # R31 money-management evidence: calculate the existing deterministic risk plan
    # once and expose it as advisory metadata. It never changes setup geometry.
    try:
        from analysis.risk import build_money_management
        for candidate in candidates:
            try:
                candidate.metadata["money_management"] = build_money_management(candidate)
            except Exception as _mm_exc:
                candidate.metadata["money_management_error"] = str(_mm_exc)[:180]

    except Exception as _mm_outer_exc:
        for candidate in candidates:
            candidate.metadata["money_management_error"] = str(_mm_outer_exc)[:180]

    # R29: non-blocking MTF candle and classical-pattern explanations.
    try:
        from analysis.mtf_candles import analyze_mtf_candles, classic_pattern_explanations
        for candidate in candidates:
            try:
                mtf = analyze_mtf_candles(bundle, candidate.direction, candidate.trigger_timeframe)
                classic = classic_pattern_explanations(candidate.metadata or {})
                candidate.metadata["mtf_candle_evidence"] = mtf
                candidate.metadata["classic_pattern_explanations"] = classic
                market = dict(candidate.market or {})
                market["viva_analysis"] = {"mtf_candles": mtf, "classic_patterns": classic}
                candidate.market = market
            except Exception as exc:
                candidate.metadata["mtf_candle_error"] = str(exc)[:180]
    except Exception as exc:
        for candidate in candidates:
            candidate.metadata["mtf_candle_error"] = str(exc)[:180]
    return candidates

def _as_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_expired(candidate: SignalCandidate) -> bool:
    if not candidate.expires_at:
        return False
    return datetime.now(timezone.utc) >= _as_utc(candidate.expires_at)


def is_invalidated(candidate: SignalCandidate, current_price: float) -> bool:
    """r30 (Viva 09-26, «ابطال نمی‌تونه بین ناحیه باشه» + «موقع شکست نباید
    ابطال بشه»): (1) an invalidation line INSIDE the entry zone is meaningless
    — rallying INTO the zone (the whole point of a pre-confirm chain) crossed
    it and murdered the scenario (LTC 69.404 inside 63.6-70.9). A pre-confirm
    invalidation only counts when price CLOSES beyond a line that sits on the
    PROTECTIVE side of the zone. (2) Once a chain is confirmed, the trade
    lifecycle owns the stop — this gate steps aside."""
    try:
        px = float(current_price)
        sl = float(candidate.sl or 0)
        if sl <= 0:
            return False
        zb = float(candidate.entry_zone_bottom or 0)
        zt = float(candidate.entry_zone_top or 0)
        md = candidate.metadata or {}
        if md.get("technical_confirmation_complete"):
            if candidate.direction == "LONG":
                return px <= sl
            return px >= sl
        if candidate.direction == "LONG":
            if zb > 0 and sl >= zb:
                return False
            return px <= sl
        if candidate.direction == "SHORT":
            if zt > 0 and sl <= zt:
                return False
            return px >= sl
        return False
    except Exception:
        return False


def approaching_entry(candidate: SignalCandidate, current_price: float) -> Tuple[bool, float]:
    bottom, top = candidate.entry_zone_bottom, candidate.entry_zone_top
    atr_value = float(candidate.metadata.get("atr", 0) or abs(top - bottom) or current_price * 0.002)
    if bottom <= current_price <= top:
        return True, 0.0
    distance = bottom - current_price if current_price < bottom else current_price - top
    distance_atr = distance / atr_value if atr_value > 0 else 999.0
    # 10-10 EARLY-WATCH (his 0.5% law): the 0.30-ATR band sits ~0.1% from the
    # zone on fast frames — the final watch arrived AT the touch, not before
    # it. Either gate fires; the ATR gate keeps slow/high-TF behavior.
    try:
        _pct72 = distance / float(current_price) if current_price else 999.0
    except Exception:
        _pct72 = 999.0
    return (distance_atr <= 0.30) or (_pct72 <= 0.005), distance_atr


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
    "break_line_geo", "pattern_geo",
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
    if (watch or {}).get("geo"):
        # R62-ARENA (audit C3): the candidate's OWN fitted edge, projected
        # on its own slope — never a line from the render fitter.
        from analysis.confirm_r62 import project_line_geo
        _v = project_line_geo(watch["geo"], when)
        if _v <= 0:
            raise ValueError("degenerate own-edge geometry")
        return float(_v)
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


def _stale_tp_1010(direction, tp1, executable_entry, close) -> bool:
    """Viva 10-10 ENTRY/TP LAW («تأیید بعد از عبور از ورود یا رسیدن به TP
    باگه»): the confirm close already printed AT or PAST TP1 → the trade is
    gone (True) — void with NO exemptions, not even the fresh-break bypass
    (a 5% runner with TP1 behind it is not an entry). The executable entry
    IS this close by design, so a consumed TP1 is exactly «passed entry».
    Degenerate ladders (no TP1, or TP1 on the wrong side) fail open."""
    try:
        t = float(tp1 or 0)
        e = float(executable_entry or 0)
        c = float(close or 0)
    except (TypeError, ValueError):
        return False
    if t <= 0 or e <= 0 or c <= 0:
        return False
    d = str(direction or "").upper()
    if d == "LONG":
        return bool(t > e and c >= t)
    if d == "SHORT":
        return bool(0 < t < e and c <= t)
    return False


def evaluate_confirmation(
    candidate: SignalCandidate, closed_df: pd.DataFrame,
    htf_closed_df: Optional[pd.DataFrame] = None,
    frame_tf_minutes: Optional[float] = None,
) -> Tuple[bool, SignalCandidate, str]:
    """Require a zone touch plus a closed LTF trigger candle.

    No live/incomplete candle can confirm a trade. A candidate score may gain one
    trigger point, but missing mandatory gates can never be compensated by score.
    """
    def reject(code: str, message: str) -> Tuple[bool, SignalCandidate, str]:
        candidate.metadata["last_reject_code"] = code
        # R64.1e CONFIRM-FUNNEL (his INJ/TLBREAK «تأیید دیر یا هیچ»): every
        # gate rejection prints ONE compact line — the boot log then answers
        # «چرا تایید نشد» without a database autopsy.
        try:
            print(f"CONFIRM_REJECT | {getattr(candidate, 'symbol', '?')} | "
                  f"{getattr(candidate, 'setup_code', '?')} | "
                  f"{getattr(candidate, 'trigger_timeframe', '?')} | {code}")
        except Exception:
            pass
        return False, candidate, message

    if closed_df is None or len(closed_df) < 20:
        return reject("NO_DATA", "داده کافی برای تأیید وجود ندارد.")

    # R28 execution boundary: scan_bundle candidates carry the R28 execution
    # record. Direct legacy callers/tests without that record keep their existing
    # confirmation contract; production candidates are checked here.
    if "r28_execution" in (candidate.metadata or {}):
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

    after = _bars_since_candidate(candidate, closed_df)
    if after is None or after.empty:
        return reject("NO_NEW_BAR", "هنوز کندلی بعد از ایجاد ستاپ بسته نشده است.")

    # ── r60 TOHOM-only lanes (Viva 09-29 §6): rejection scalps (TLBREAK/
    # ALBROX) confirm ONLY through the illusion engine — sub-TF directional
    # closes + rising volume + a confirming candle pattern at the line/zone.
    # A bare close may never confirm them. Candle patterns remain the
    # CONFIRMER here only; they still never veto break signals (fast lane
    # unchanged, per his law).
    _md60 = candidate.metadata or {}
    if _md60.get("rejection_scalp") and not _md60.get("tohom"):
        return reject("WAIT_TOHOM_SCALP", (
            "اسکلپ ریجکت فقط با تأیید موتور توهم صادر می‌شود: کندل‌های هم‌جهت تایم "
            "پایین‌تر + رشد حجم + الگوی کندلی روی خط/ناحیه؛ هنوز ثبت نشده است."))

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
    # ── Viva 10-09 PURE-BREAK LAW (surgical confirm fix): TECHCLASSIC and
    # TLBREAK confirm ONLY on the first valid close beyond the broken LINE
    # (single trendline / pattern upper-lower trend, projected on its own
    # slope) in the break direction. A zone edge may NEVER confirm them —
    # «تایید نواحی فقط در آلبروکس و پینوال». INTERNAL TLBREAK (ceiling↔floor
    # range trades) is exempt: it is not a breakout.
    _pure_break_setup = str(getattr(candidate, "setup_code", "") or "").upper() in {
        "TECHCLASSIC", "TLBREAK"}
    _pre_internal = str((candidate.metadata or {}).get("viva_entry_type") or "").upper() == "INTERNAL"
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
        # ── R62-ARENA: ONE shared edge for every lane (fast lane, TOHOM,
        # reclaim gate, live-break note) — the broken edge projected on its
        # own slope to each bar's close (C1/TH4/W7 of the 09-30 audit). The
        # old helper clamped the chord at its last anchor (a frozen level)
        # and was fed the frame's integer INDEX instead of the bar time.
        from analysis.confirm_r62 import (confirm_edge_at as _r62_edge_at,
                                          valid_break_candle as _r62_vbc,
                                          frame_minutes as _r62_fmin,
                                          tf_minutes as _r62_tfm)
        _major_src = str(_md.get("confirm_edge_source") or "") == "MAJOR_TL"

        def _edge_at(ts, static_edge: float) -> float:
            if _major_src or ts is None:
                return static_edge
            _v62 = _r62_edge_at(candidate, ts)
            return float(_v62) if _v62 > 0 else static_edge
        _is_long = candidate.direction == "LONG"
        _buf = 0.10 * _atr
        # ── R67.1 PIN DRAWN-LINE CLOSE (Viva 10-03, ENA: «ترندِ خوب اما با
        # بریک لانگ در اولین کلوز تایید نداده بود») — the line HE watches on
        # the chart is a confirm level for the pin family too: the FIRST of
        # (pin level, consistent-side drawn line) the market closes beyond
        # is the confirm level. Consistent side only (LONG → the HIGH-side
        # line, SHORT → the LOW-side); the OPPOSITE side stays the 09-21
        # veto's business. Nearest-to-price line wins; a line projected far
        # from the tape is context, not a trigger.
        _pin_line67 = None
        if str(getattr(candidate, "setup_code", "") or "").upper() in {"PINVAL", "PINWALLQ"}:
            try:
                _want67 = "HIGH" if _is_long else "LOW"
                _clast67 = float(closed_df["close"].iloc[-1])
                _cands67 = []
                for _l67 in (_md.get("render_line_watch") or []):
                    if str(_l67.get("side") or "").upper() != _want67:
                        continue
                    try:
                        _v67 = float(_project_watch_level(
                            _l67, pd.Timestamp(str(closed_df["timestamp"].iloc[-1]))))
                    except Exception:
                        continue
                    if _v67 > 0 and _atr > 0 and abs(_v67 - _clast67) <= 4.0 * _atr:
                        _cands67.append((abs(_v67 - _clast67), _l67))
                if _cands67:
                    _cands67.sort(key=lambda t: t[0])
                    _pin_line67 = _cands67[0][1]
            except Exception:
                _pin_line67 = None
        # R62: after a STALE verdict the old break bar may not confirm again —
        # only a later close, after a First-Time-Back touch of the edge.
        _stale_after = str(_md.get("stale_after_bar") or "")
        # ── r60.3 THE multi-TF law (Viva 09-30, twice-dictated): the ENTRY
        # break is the TRIGGER timeframe's own break — «شکست همون تایم تریگر
        # واسه ورود باید تایید بشه نه تایم بالاتر ... تایید اما از تایم
        # پایینتر». The pattern/HTF frame is NO LONGER a break source here
        # (it drew the line and confirmed on a frame the member never trades);
        # the EARLY lane is the LOWER timeframe (TOHOM illusion engine), which
        # stays exactly where r47 put it.
        for _frame, _tag in ((closed_df, "تایم تأیید"),):
            if _frame is None or len(_frame) < 2:
                continue
            _scan = _bars_since_candidate(candidate, _frame)
            if _scan is None or _scan.empty:
                continue
            # Viva 2026-09-14: thresholds speak the language of the frame they
            # judge (buffer scaled to the scanned frame's own ATR).
            _f_atr = _frame_atr(_frame, fallback=_atr)
            # Viva 09-21 (round 15): the FIRST closed candle whose close lands
            # beyond the level; only a tick-scale epsilon (2% of frame ATR).
            _f_buf = max(0.02 * _f_atr, 0.0)
            # R62-ARENA (Viva 09-30): «هر تایم‌فریم باید از تایم پایین‌تر
            # تأیید بگیره با دیدن الگوهای کندلی که نشانهٔ شکست معتبر باشن» —
            # when the scanned frame is FINER than the trigger TF, the
            # confirming candle must read as a valid break (power candle /
            # engulfing / hammer-pin / strong close); a shooting star or a
            # counter-colour close at the line is a fake-out and the scan
            # moves on to the next bar. The trigger TF's own close (late
            # lane) stays the plain one-close law — nothing ever stalls.
            _fm = float(frame_tf_minutes or 0.0) or _r62_fmin(_frame)
            _trig_m = _r62_tfm(getattr(candidate, "trigger_timeframe", ""), 0.0)
            _lower_tf = bool(_fm > 0 and _trig_m > 0 and _fm < _trig_m * 0.99)
            _ftb_seen = not _stale_after
            _prev_row = None
            for _ix, _r in _scan.iterrows():
                _bar_ts = _r["timestamp"] if "timestamp" in _scan.columns else _ix
                _bar_close_ts = None
                try:
                    _bar_close_ts = pd.Timestamp(_bar_ts) + pd.Timedelta(minutes=_fm or 0.0)
                except Exception:
                    _bar_close_ts = None
                _edge_t = _edge_at(_bar_close_ts, _edge if _edge > 0 else _zone_edge)
                if _pure_break_setup and not _pre_internal and not (_edge > 0):
                    # 10-09 pure-break law: no LINE on the chain → no fast
                    # lane (a pure-break setup never confirms on a zone edge)
                    _prev_row = _r
                    continue
                if _pin_line67 is not None and not _major_src:
                    try:
                        _lv67 = float(_project_watch_level(
                            _pin_line67, pd.Timestamp(str(_bar_ts))))
                        # first of (pin level, drawn line) the market gives
                        _edge_t = min(_edge_t, _lv67) if _is_long else max(_edge_t, _lv67)
                        candidate.metadata["confirm_edge_source"] = "PIN_LINE_WATCH"
                    except Exception:
                        pass
                if _stale_after:
                    try:
                        from analysis.confirm_r62 import _naive as _r62_naive
                        if _r62_naive(_bar_ts) <= _r62_naive(_stale_after):
                            _prev_row = _r
                            continue
                    except Exception:
                        pass
                    if not _ftb_seen:
                        _touch = (float(_r["low"]) <= _edge_t + 0.25 * _f_atr) if _is_long \
                            else (float(_r["high"]) >= _edge_t - 0.25 * _f_atr)
                        if _touch:
                            _ftb_seen = True
                        _prev_row = _r
                        continue
                _out = bool(float(_r["close"]) >= _edge_t + _f_buf) if _is_long \
                    else bool(float(_r["close"]) <= _edge_t - _f_buf)
                if not _out:
                    _prev_row = _r
                    continue
                _cndl = ""
                if _lower_tf:
                    _ok62, _cndl = _r62_vbc(_r, _prev_row, candidate.direction, _edge_t, _f_atr)
                    if not _ok62:
                        candidate.metadata["last_fakeout_candle"] = f"{str(_bar_ts)[:16]} {_cndl}"
                        _prev_row = _r
                        continue
                _body = abs(float(_r["close"]) - float(_r["open"])) / _f_atr
                _dist = abs(float(_r["close"]) - _edge_t) / _f_atr
                fast_lane = (f"اولین کلوزِ معتبر فراتر از خط/لبه ({_tag}، "
                             f"{_dist:.2f} ATR پشت سطح، Body {_body:.2f} ATR"
                             + (f"، {_cndl}" if _cndl else "") + ") — پولبک شرط نیست")
                candidate.metadata["fast_break_bar"] = str(_bar_ts)[:19]
                candidate.metadata["fast_break_close"] = float(_r["close"])
                candidate.metadata["fast_break_tf_min"] = float(_fm or 0.0)
                candidate.metadata["tl_fast_break"] = fast_lane
                candidate.metadata["confirm_level_used"] = float(_edge_t)
                if _cndl:
                    candidate.metadata["confirm_candle_pattern"] = _cndl
                candidate.metadata.setdefault("break_seen_at", str(_bar_ts)[:19])
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
            # R62-ARENA (audit C2): the curve is evaluated at x_last + bars
            # (its intercept sits at the fit window's x=0). Bands stored
            # before R62 carry no x_last → the log value at the alert bar is
            # the stored lo/hi, so project multiplicatively from it.
            import math as _m20

            def _proj20(_lg, _base, _slope_lin):
                if _lg.get("fit") and float(_lg.get("slope") or 0.0) != 0.0 and float(_base) > 0:
                    if _lg.get("x_last") is not None and float(_lg.get("intercept") or 0.0):
                        return float(10.0 ** (float(_lg["slope"]) * (float(_lg["x_last"]) + _bars20)
                                              + float(_lg["intercept"])))
                    return float(10.0 ** (_m20.log10(float(_base)) + float(_lg["slope"]) * _bars20))
                return float(_base) + float(_slope_lin or 0.0) * _bars20
            _band_lo20 = _proj20(_lo20, _band20["lo"], _band20.get("slope_lo"))
            _band_hi20 = _proj20(_hi20, _band20["hi"], _band20.get("slope_hi"))
        except Exception:
            _band_lo20 = _band_hi20 = None
    # ── R63 G1 (one geometry): when the detector stored BOTH of the traded
    # pattern's edges, the containment band IS those edges projected onto
    # this candle — never the render fitter's band.
    try:
        _pg63 = _md20.get("pattern_geo") or {}
        if isinstance(_pg63, dict) and _pg63.get("upper") and _pg63.get("lower"):
            from analysis.confirm_r62 import project_line_geo as _plg63
            _u63 = _plg63(_pg63["upper"], _row20["timestamp"])
            _l63 = _plg63(_pg63["lower"], _row20["timestamp"])
            if _u63 > 0 and _l63 > 0:
                _band_lo20, _band_hi20 = min(_u63, _l63), max(_u63, _l63)
    except Exception:
        pass
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
    # ── Viva 10-09 PINWALL COUNTER-TREND PERMISSION (pin family ONLY — «این
    # اجازه فقط مختص پینوال است»): when the detector-validated pinbar/engulf
    # premise (pin_high/pin_low present) has ALREADY resolved with the first
    # valid close beyond the pin extreme in the trade direction (fast lane)
    # AND the confirming tape shows rising counter-trend orders (last-bar
    # volume ≥ 1.3× the mean of the previous twenty AND above the previous
    # bar — the engine's own TOHOM definition of «حجم بالا رفته محسوس»),
    # the counter-break vetoes below are lifted FOR THIS TICK. The lift only
    # removes the veto — the confirmation itself still comes from the normal
    # lanes (fast lane / trigger-TF close / TOHOM). Computed lazily: veto
    # branches call it only when they are about to fire, so a chain with no
    # veto sees ZERO behavior change. Fail-closed on any doubt (no volume
    # column, no pin premise, no fast lane → False, old behavior).
    _pin_lift_cache = {}
    def _pin_countertrend_lift() -> bool:
        try:
            if "v" in _pin_lift_cache:
                return _pin_lift_cache["v"]
            _lift = False
            if str(getattr(candidate, "setup_code", "") or "").upper() in {"PINVAL", "PINWALLQ"}:
                _mdp = candidate.metadata or {}
                # 10-09: a TOHOM-blessed rejection scalp routed into the pin
                # family is a resolved premise too (sub-TF closes + pattern);
                # the rising-orders volume proof below still applies to it.
                if (fast_lane or _mdp.get("tl_fast_break")
                        or (_mdp.get("rejection_scalp") and _mdp.get("tohom"))) \
                        and float(_mdp.get("pin_high") or 0) > 0 \
                        and float(_mdp.get("pin_low") or 0) > 0:
                    try:
                        _vol = pd.to_numeric(closed_df["volume"], errors="coerce")
                        if len(_vol) >= 3 and bool(_vol.notna().iloc[-2:].all()):
                            _last_v = float(_vol.iloc[-1])
                            _prev_v = float(_vol.iloc[-2])
                            _base_v = float(_vol.iloc[:-1].tail(20).mean())
                            if _base_v > 0 and _prev_v > 0 and _last_v > _prev_v \
                                    and _last_v >= 1.3 * _base_v:
                                _lift = True
                                _mdp["countertrend_pin_lift"] = (
                                    f"vol {_last_v / _base_v:.2f}x + pin-level close")
                    except Exception:
                        _lift = False
            _pin_lift_cache["v"] = _lift
            return _lift
        except Exception:
            return False
    if not _is_internal and candidate.direction in ("LONG", "SHORT"):
        _watch = (candidate.metadata or {}).get("render_line_watch") or []
        # R62-ARENA (audit C3/G1): when the detector stored the pattern's OWN
        # two edges, THOSE are the lines that may veto — the render fitter
        # (different pivots/tolerances) used to veto confirmations with lines
        # the trade was never built on.
        _pg62 = (candidate.metadata or {}).get("pattern_geo") or {}
        if isinstance(_pg62, dict) and (_pg62.get("upper") or _pg62.get("lower")):
            _watch = [{"side": _sd, "geo": _g} for _sd, _g in
                      (("HIGH", _pg62.get("upper")), ("LOW", _pg62.get("lower"))) if _g]
        _side_wrong = ""
        for _ln in _watch:
            try:
                if not _ln.get("geo"):
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
                # r40 CONFIRM-GATE (Viva 09-26, «لانگ روی ترندی که رو به پایین
                # شکسته تأیید نشه» / SEI·POL 09-26): the old relevance filter
                # below skipped lines price had ALREADY walked away from —
                # exactly the freshly-broken ones. Scan the last 6 closed bars
                # FIRST: a close through the line AGAINST the trade direction
                # vetoes the confirmation outright, no matter where price sits
                # now. Closing through in the trade's OWN direction (the
                # break/retest lane) stays allowed.
                try:
                    for _bi in range(max(1, len(closed_df) - 6), len(closed_df)):
                        _brow = closed_df.iloc[_bi]
                        _blvl = _project_watch_level(_ln, pd.Timestamp(str(_brow["timestamp"])))
                        _bcl = float(_brow["close"])
                        _bs6 = str(_ln.get("side") or "").upper()
                        if _atr20 > 0 and candidate.direction == "LONG" and _bs6 == "LOW" \
                                and _bcl < _blvl - 0.10 * _atr20 \
                                and not _pin_countertrend_lift():
                            return reject("BREAK_SIDE_MISMATCH", (
                                f"ترند/خط حمایتی {_blvl:.8g} در ۶ کندل اخیر رو به پایین "
                                f"با کلوز {_bcl:.8g} شکسته شده؛ طبق قانون، لانگ روی "
                                "ساختارِ شکسته‌شده به پایین تأیید نمی‌شود."))
                        if _atr20 > 0 and candidate.direction == "SHORT" and _bs6 == "HIGH" \
                                and _bcl > _blvl + 0.10 * _atr20 \
                                and not _pin_countertrend_lift():
                            return reject("BREAK_SIDE_MISMATCH", (
                                f"ترند/خط مقاومتی {_blvl:.8g} در ۶ کندل اخیر رو به بالا "
                                f"با کلوز {_bcl:.8g} شکسته شده؛ طبق قانون، شورت روی "
                                "ساختارِ شکسته‌شده به بالا تأیید نمی‌شود."))
                except Exception:
                    pass
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
        if _side_wrong and not _pin_countertrend_lift():
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
        # r60: TECHCLASSIC breaks now carry the same canonical contract —
        # a break UP may only ever trade LONG, a break DOWN only SHORT.
        if _contract_kind in ("VIVA_TLBREAK", "TECHNOCLASSIC", "ALBROX_ZONE") and _contract_break in {"UP", "DOWN"}:
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
    # r40 CONFIRM-GATE (Viva 09-26, «داخل رنج/کانال فقط ابروکس و PINVAL اجازهٔ
    # تأیید دارند»): the INTERNAL edge-entry lane is a RANGE trade, not a
    # breakout — only the pin family (PINVAL/PINWALLQ legacy) and ALBROX may
    # take it. TECHCLASSIC/TLBREAK inside a range fall through to the
    # containment gate and are rejected (INSIDE_PATTERN_NO_BREAK).
    # 10-09 OVERRIDE (Viva: «داخلی سقف به کف و کف به سقف در تی ال بریک»):
    # TLBREAK JOINS this lane (ceiling↔floor inner trades). ALBROX + the pin
    # family keep their rights; TECHCLASSIC stays breakout-only.
    _internal_setup_ok = str(getattr(candidate, "setup_code", "") or "").upper() in {
        "ALBROX", "PINVAL", "PINWALLQ", "TLBREAK"}
    if (_band_lo20 is not None and _band_hi20 is not None
            and _internal_allowed20 and _internal_setup_ok
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
                        "tp1": _close20 + _path / 3.0 if _path > 0 else _wall,
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
                        "tp1": _close20 - _path / 3.0 if _path > 0 else _wall,
                        "tp2": _wall,
                        "pattern": str(_band20.get("kind") or "RANGE"),
                    }
        except Exception:
            _internal_plan = None
    if _internal_plan:
        _md20["viva_entry_type"] = "INTERNAL"
        # 10-09: the plan's own validated edge candle is the trigger event
        # (sticky across ticks like tl_fast_break — a downstream RR/chase
        # reject must not erase the fact that the edge candle printed).
        _md20["internal_trigger"] = True
        _md20["internal_entry"] = {k: (round(v, 10) if isinstance(v, float) else v)
                                   for k, v in _internal_plan.items()}
        _md20["internal_wall"] = float(_internal_plan.get("wall") or 0.0)
        _md20["internal_path_fa"] = (
            f"هدف: تا کف الگو ({_internal_plan['tp2']:.8g}) — نردبان سه‌پله‌ای، "
            f"TP3 روی ضلع مقابل." if _internal_plan["direction"] == "SHORT" else
            f"هدف: تا سقف الگو ({_internal_plan['tp2']:.8g}) — نردبان سه‌پله‌ای، "
            f"TP3 روی ضلع مقابل.")
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
    # Viva First-Close Breakout Law: When fast_lane confirms the first close beyond the trendline/edge,
    # higher-TF containment bands must NOT veto the confirmation!
    if (_band_lo20 is not None and _band_hi20 is not None and not _is_internal
            and _pattern_premise and not _fast_lane_ok):
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
            # R62-ARENA (audit C4): the DETECTOR owns the contract
            # (pattern_type/break_edge/break_direction). This gate used to
            # overwrite it from the render band every cycle — one mis-projected
            # bar flipped break_direction and the contract check vetoed the
            # chain forever (permanent BREAK_SIDE_MISMATCH). Observations now
            # live under observed_* keys; the contract is only filled when the
            # detector left it empty (legacy setups without a contract).
            _has_contract = str(_mdg.get("break_direction") or "").upper() in {"UP", "DOWN"}
            if not _mdg.get("pattern_type") or str(_mdg.get("pattern_type")) == "NONE":
                _mdg["pattern_type"] = _kind_g or "NONE"
            _mdg["observed_band_kind"] = _kind_g or "NONE"
            _mdg.setdefault("pattern_bias", _bias_g)
            _mdg["trade_direction"] = _dir_g
            if _brk_up and not _brk_dn:
                _mdg["observed_break_edge"] = "UPPER"
                _mdg["observed_break_direction"] = "UP"
                if not _has_contract:
                    _mdg["break_edge"] = "UPPER"
                    _mdg["break_direction"] = "UP"
            elif _brk_dn and not _brk_up:
                _mdg["observed_break_edge"] = "LOWER"
                _mdg["observed_break_direction"] = "DOWN"
                if not _has_contract:
                    _mdg["break_edge"] = "LOWER"
                    _mdg["break_direction"] = "DOWN"
            if _brk_up and not _brk_dn and _dir_g == "SHORT" and not _pin_countertrend_lift():
                return reject("BREAK_SIDE_MISMATCH", (
                    f"جهت شکست با جهت سناریو ناهمسو است: کلوز {_close20:.8g} از ضلع "
                    f"بالای {_mdg['pattern_type']} (بالای {float(_band_hi20):.8g}) "
                    "بیرون زده — یعنی شکست صعودی — اما سناریو شورت است. طبق قانون "
                    "«جهت معامله = جهت ضلع شکسته»، این سناریو تأیید نمی‌شود؛ اگر "
                    "شرایط لانگ کامل است، باید کاندیدای لانگِ تازه با شناسهٔ تازه "
                    "ساخته شود، نه تبدیل همین شورت."))
            if _brk_dn and not _brk_up and _dir_g == "LONG" and not _pin_countertrend_lift():
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
    # Viva Pure Breakout Law: TLBREAK and TECHCLASSIC confirm strictly on trendline close!
    _is_pure_break_setup = str(getattr(candidate, "setup_code", "") or "").upper() in {"TLBREAK", "TECHCLASSIC"}
    if _is_pure_break_setup and (fast_lane or (candidate.metadata or {}).get("tl_fast_break")):
        touched = True

    candidate.metadata["touched"] = touched
    if not touched:
        return reject("NO_TOUCH", "قیمت هنوز به لبهٔ ناحیه/خط نرسیده؛ با یک کلوزِ معتبرِ فراتر از لبه تأیید می‌شود.")

    row = closed_df.iloc[-1]
    previous = closed_df.iloc[-2]
    # ── r61.2 BREAK-RECLAIM CONFIRM GATE (Viva 09-30, BNB: the pattern broke
    # UP yet a SHORT confirmed hours later): between the alert and the
    # confirm the break must STILL hold. A trigger CLOSE back through the
    # break line (beyond a 0.10·ATR wick tolerance) is a FAILED break — the
    # chain verdicts instead of confirming an opposite-context entry. FTB is
    # safe (wick touches are pullbacks, not reclaims). Every setup carrying
    # the break line (TC viva_break_line / TLBREAK+ALBROX viva_breakout_line)
    # is covered — the law is for ALL setups, as he dictated.
    try:
        _bl61 = float((candidate.metadata or {}).get("viva_break_line")
                      or (candidate.metadata or {}).get("viva_breakout_line") or 0.0)
        # R62-ARENA: the reclaim is judged against the SAME sloped edge the
        # fast lane used (projected to this bar), and only once the break has
        # actually printed — a pre-break alert has nothing to reclaim.
        from analysis.confirm_r62 import (break_established as _r62_be,
                                          confirm_edge_at as _r62_e61,
                                          frame_minutes as _r62_fm61)
        if _bl61 > 0 and not _r62_be(candidate.metadata or {}):
            _bl61 = 0.0
        if _bl61 > 0:
            try:
                _t61 = pd.Timestamp(row["timestamp"]) + pd.Timedelta(
                    minutes=float(frame_tf_minutes or 0.0) or _r62_fm61(closed_df))
                _p61 = _r62_e61(candidate, _t61)
                if _p61 > 0:
                    _bl61 = float(_p61)
            except Exception:
                pass
            _atr61 = float((candidate.metadata or {}).get("atr") or 0.0) \
                or float((closed_df["high"] - closed_df["low"]).tail(14).mean() or 0.0)
            _sd61 = str((candidate.metadata or {}).get("break_edge")
                        or ("UPPER" if str(candidate.direction).upper() == "LONG" else "LOWER"))
            _c61 = float(row["close"])
            _bad61 = (_c61 < _bl61 - 0.10 * _atr61) if _sd61 == "UPPER" \
                else (_c61 > _bl61 + 0.10 * _atr61)
            if _atr61 > 0 and _bad61 and not fast_lane and not (candidate.metadata or {}).get("tl_fast_break"):
                return reject("BREAK_RECLAIMED", (
                    "شکستِ مبنا پس از هشدار پس گرفته شده — کلوز به سمتِ پیش از شکست برگشته است؛ "
                    "شکستِ نامعتبر تأیید نمی‌گیرد و سناریو باطل است."))
    except Exception:
        pass
    # ── r61.3-R62 PRE-BREAK CEILING LAW (his 10-01 correction on the four
    # PINWALL LONGs — ATOM K703651 / VVV K345418 / LIT K837132 / JUP K541811:
    # «قبل از شکست سیگنال در جهتِ شکستی که هنوز رخ نداده تأیید نشه؛ دنبال
    # ریجکت‌ها باش»): a pin/rejection chain may NOT CONFIRM toward a facing,
    # untouched wall (supply ahead of a LONG / demand ahead of a SHORT). The
    # confirming close itself is re-probed through the polarity engine; the
    # chain STAYS ALIVE — a later valid close beyond the wall confirms (the
    # break law). Break-lane setups (TC/TLBREAK/ALBROX) are exempt: their
    # validated break IS the confirmation event.
    try:
        _pinfam61 = (str(getattr(candidate, "setup_code", "") or "").upper() == "PINVAL"
                     or bool((candidate.metadata or {}).get("rejection_scalp")))
        if _pinfam61 and bool(getattr(SETTINGS, "confirm_ceiling_gate", True)):
            from analysis.zone_polarity import evaluate_polarity as _ep61
            _atr_c61 = float((candidate.metadata or {}).get("atr") or 0.0) \
                or float((closed_df["high"] - closed_df["low"]).tail(14).mean() or 0.0)
            if _atr_c61 > 0:
                _pol61 = _ep61(
                    closed_df, None, candidate.direction, float(row["close"]),
                    _atr_c61,
                    near_atr=float(getattr(SETTINGS, "pinv_polarity_near_atr", 1.2)),
                    block_atr=float(getattr(SETTINGS, "pinv_polarity_block_atr", 1.8)),
                    breakout_body_atr=float(getattr(SETTINGS, "pinv_polarity_breakout_body_atr", 0.5)),
                    include_fvg=True)
                if not _pol61.allowed and str(getattr(_pol61, "reason", "") or "") in                         {"UNDER_SUPPLY", "ABOVE_DEMAND"}:
                    return reject("CEILING_AHEAD", (
                        "پین جهت‌درست است اما دیوارِ دست‌نخوردهٔ عرضه/تقاضا مستقیم جلوی مسیر است؛ "
                        "قبل از شکستِ معتبرِ دیوار تأیید صادر نمی‌شود (قانون ۱۰-۰۱). "
                        "زنجیره زیر نظر می‌ماند — اولین کلوزِ معتبر فراتر از دیوار تأیید می‌دهد."))
    except Exception:
        pass
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
    # 10-09 (Viva: «داخلی سقف به کف و کف به سقف در تی ال بریک»): a TLBREAK
    # INTERNAL chain is a range trade, not a breakout — it skips the break
    # state machine and confirms on its candle plan. Scoped to TLBREAK only:
    # ALBROX lane-A (same variant) keeps its exact old path.
    _tlbreak_inner = _is_internal and str(
        getattr(candidate, "setup_code", "") or "").upper() == "TLBREAK"
    if candidate.metadata.get("strategy_variant") == "VIVA_TLBREAK" and not _tlbreak_inner:
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
        # ── r52 SUFFOCATION LAW (Viva 09-28, verbatim: «گیت گذاشتی باید پولبک
        # بزنه بعلاوه bos … اصلا نباید شرط تایید باشه — نقطه ورود پوزیشن
        # بعدی»): Retest → Rejection → Micro-BOS is NO LONGER a confirmation
        # path of THIS signal — not as a requirement and not as a fast lane.
        # The machine keeps running as the NEXT position's entry map
        # (pullback_entry_ready) and never gates the verdict. THIS signal
        # confirms ONLY on the first valid close beyond the edge (fast lane
        # / one-close law) or TOHOM — exactly what was dictated.
        if ready:
            machine = advance_viva_state(machine, "CONFIRM", max_retest_bars=int(candidate.metadata.get("viva_retest_window_bars", 16)))
            candidate.metadata["pullback_entry_ready"] = True
            candidate.metadata["pullback_entry_note"] = (
                "پولبک/ریجکشن/BOS کامل شد — نقشهٔ ورودِ پوزیشن بعدی؛ شرط تأییدِ این سیگنال نیست.")
            ready = False
        candidate.metadata["viva_state"] = state
        candidate.metadata["viva_state_machine"] = machine.payload()
        if not ready and alt is not None and state in ("S3_RETEST", "S4_REJECTION"):
            # r52: a rejection cluster at the pullback is entry-quality data
            # for the NEXT position — never a confirmation of this one.
            candidate.metadata["viva_fast_alt"] = str(getattr(alt, "kind", "") or "")
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
            return reject("WAIT_FIRST_CLOSE_" + state, "در انتظار اولین کلوزِ معتبرِ فراتر از خط/لبه (یا تأییدِ هوشمندِ توهم) — پولبک و BOS شرطِ تأیید نیستند.")
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
    # ── R67 PIN FIRST-CLOSE LAW (Viva 10-03, verbatim: «قوانین اولین کلوز
    # بعد از شکست کجا رفته؟؟») — ETC/ENA confirmed SECONDS after the alert on
    # a FINER frame's micro-BOS (a 5m «سقف Micro Structure» printed as 15M in
    # the message) without the promised close beyond the pin level ever
    # existing. For the pin family a frame finer than the trigger TF confirms
    # ONLY through the pin-level close (the fast lane above) or the TOHOM
    # engine; the MSS/engulfing/pinbar candle vocabulary stays a
    # TRIGGER-frame privilege. The own-TF close (late lane) is untouched.
    _pin_r67 = str(getattr(candidate, "setup_code", "") or "").upper() in {"PINVAL", "PINWALLQ"}
    if _pin_r67 and not fast_lane and not (candidate.metadata or {}).get("tohom"):
        try:
            from analysis.confirm_r62 import frame_minutes as _r62_fmin67, tf_minutes as _r62_tfm67
            _fm67 = float(frame_tf_minutes or 0.0) or _r62_fmin67(closed_df)
            _tm67 = _r62_tfm67(getattr(candidate, "trigger_timeframe", ""), 0.0)
            _finer67 = bool(_fm67 > 0 and _tm67 > 0 and _fm67 < _tm67 * 0.99)
        except Exception:
            _finer67 = False
        if _finer67:
            return reject("PIN_NEEDS_LEVEL_CLOSE", (
                "پین‌بار فقط با اولین کلوزِ فراتر از سطحِ خودِ پین (یا موتور توهم) "
                "تأیید می‌شود؛ شکستِ میکروساختارِ تایمِ پایین‌تر تأییدِ ورود نیست."))
    # Viva First-Close Breakout Law: A closed bar beyond the broken trendline/edge in the trade direction IS THE TRIGGER!
    # It does NOT require a rare candlestick pattern (engulfing/pinbar) to confirm a valid breakout!
    _is_break_trigger = bool(fast_lane or (candidate.metadata or {}).get("tl_fast_break"))
    # ── Viva 10-09 PURE-BREAK LAW (second half): without the first valid
    # close beyond the broken line (or S6/TOHOM blessing), a pure-break chain
    # may NOT confirm on candle vocabulary or a zone base — those lanes are
    # ALBROX's and the pin family's («تایید نواحی فقط در آلبروکس و پینوال»).
    # VIVA_TLBREAK-variant chains never reach here unready (early return
    # above); this gate bites legacy/unvarianted TC/TLBREAK chains.
    if (_pure_break_setup and not _is_internal and not _is_break_trigger
            and str((candidate.metadata or {}).get("viva_state") or "") != "S6_CONFIRMED"
            and not (candidate.metadata or {}).get("tohom")):
        return reject("WAIT_FIRST_CLOSE_BREAK", (
            "تکنوکلاسیک/تی‌ال‌بریک فقط با اولین کلوزِ معتبرِ فراتر از خطِ شکسته "
            "(در جهت بریک) یا تأیید توهم تأیید می‌شوند؛ تأیید ناحیه‌ای ندارند (قانون ۱۰-۰۹)."))
    trigger_valid = (
        _is_break_trigger
        or (
            directional
            and (structure_trigger or engulfing or pinbar)
            and displacement["body_atr"] >= SETTINGS.confirm_body_min_atr
        )
    )
    alt_only = False
    if not trigger_valid and str(candidate.metadata.get("viva_state") or "") == "S6_CONFIRMED" \
            and candidate.metadata.get("strategy_variant") == "VIVA_TLBREAK":
        trigger_valid = True  # the valid close that set S6 was the trigger
    if not trigger_valid and candidate.metadata.get("tl_fast_break"):
        trigger_valid = True
        candidate.metadata["trigger_note"] = "اولین کلوزِ معتبر پشت خط/لبه (بدون پولبک)"
    if (not trigger_valid
            and str(getattr(candidate, "setup_code", "") or "").upper() == "TLBREAK"
            and _is_internal
            and bool((candidate.metadata or {}).get("internal_trigger"))):
        # 10-09 (Viva: inner ceiling↔floor is TLBREAK's): the internal plan's
        # own edge candle (pin/engulf/close validated when the plan was
        # built) IS the confirmation event — a range trade has no break
        # close by definition. Other setups keep their exact trigger paths.
        trigger_valid = True
        candidate.metadata["trigger_note"] = "کندل تأیید داخلی از لبهٔ رنج/کانال (قانون ۱۰-۰۹)"
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
    # R62-ARENA (audit C6, evaluated): the executable entry stays the NEWEST
    # closed price — that is what a member can actually fill; the confirming
    # close is recorded next to it for the record (a break bar older than two
    # candles is disarmed by the stale guard in main, so the two stay close).
    try:
        _fbc62 = float((candidate.metadata or {}).get("fast_break_close") or 0.0)
        if fast_lane and _fbc62 > 0:
            candidate.metadata["confirm_break_close"] = _fbc62
            candidate.metadata["entry_source"] = "CONFIRM_TF_LAST_CLOSE"
    except Exception:
        pass
    risk = abs(executable_entry - candidate.sl)
    # ── his 09-21 ruling, verbatim: «استاپ اصلا ساختاری اگر فاصله داشت حذف نشه و
    # تا ۱.۲۵ قیمت نماد محاسبه بشه» — the confirmation uses a stop that is CUT at
    # 1.25% of price instead of refusing the scenario (the VVV 1h chain sat
    # «منتظر» for two days because DEGENERATE_GEOMETRY rejected every cycle).
    try:
        from analysis.trade_management import clamp_stop_price as _clamp_q
        # R67 (Viva 10-03): a corridor stop (3.5–5% pin law) is his NEWER
        # ceiling — the round-14 per-TF clamp must not cut it back to 2%.
        _q_sl = _q_clamped = None
        if not (candidate.metadata or {}).get("stop_corridor"):
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
        _fb_max = float(getattr(SETTINGS, "fast_break_max_chase_atr", 3.2))
        _fast_ok = bool(fast_lane or candidate.metadata.get("tl_fast_break")) and chase_atr <= _fb_max
        # ── Viva 10-09 INSTANT-CONFIRM LAW («در لحظه باید تایید بیاد»): a
        # violent first close beyond the edge is FAR from the zone by nature
        # — when the fast-lane bar IS the newest closed bar (age 0, nothing
        # chased yet) the chase gate stands down for the zone-confirming
        # family too (ALBROX + pins; pure-break setups were already exempt).
        # An AGED runner (fast bar older than the newest close) keeps the
        # exact old verdict. The distance still rides the caption (chase_note
        # below) — Viva decides the trade.
        _fresh_break_1009 = False
        try:
            _fbb = str((candidate.metadata or {}).get("fast_break_bar") or "")
            _fresh_break_1009 = bool(fast_lane) and bool(_fbb) and _fbb == str(row["timestamp"])[:19]
        except Exception:
            _fresh_break_1009 = False
        _zone_fam_1009 = str(getattr(candidate, "setup_code", "") or "").upper() in {
            "ALBROX", "PINVAL", "PINWALLQ"}
        # Viva Pure Breakout Law: TLBREAK and TECHCLASSIC breakouts confirm immediately on first close!
        if chase_atr > max_chase and not _fast_ok and not _is_pure_break_setup \
                and not (_fresh_break_1009 and _zone_fam_1009):
            return reject("ENTRY_TOO_FAR", f"کلوز تأیید {chase_atr:.2f} ATR از زون دور شده؛ Chase مجاز نیست.")
        if chase_atr > max_chase:
            # a fresh single-close break IS far from the zone by nature —
            # annotate the distance for the caption, Viva decides the trade.
            candidate.metadata["chase_note"] = f"{chase_atr:.2f} ATR از زون"
    # Viva 10-10: TP1 already consumed at confirm time → void, no exemptions.
    if _stale_tp_1010(candidate.direction, getattr(candidate, "tp1", 0),
                      executable_entry, close):
        return reject("TP_HIT_BEFORE_CONFIRM", (
            f"قیمت در لحظهٔ تأیید به TP1 رسیده ({float(close):.8g})؛ ورود بی‌معنی است."))
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
    # ── Absolute Structural Stop Law: Stop MUST strictly sit on the trade's side!
    from analysis.trade_management import structural_buffer as _sb_hard
    _buf_hard = float(_sb_hard(executable_entry, candidate.market))
    if candidate.direction == "LONG" and float(candidate.sl) >= executable_entry:
        _zb_h = float(candidate.entry_zone_bottom or 0.0)
        if 0 < _zb_h < executable_entry:
            candidate.sl = round(_zb_h - _buf_hard, 8)
        else:
            _atr_h = float(candidate.metadata.get("atr", 0) or 0) or 0.015 * executable_entry
            candidate.sl = round(executable_entry - max(1.5 * _atr_h, 0.015 * executable_entry), 8)
    elif candidate.direction == "SHORT" and float(candidate.sl) <= executable_entry:
        _zt_h = float(candidate.entry_zone_top or 0.0)
        if _zt_h > executable_entry:
            candidate.sl = round(_zt_h + _buf_hard, 8)
        else:
            _atr_h = float(candidate.metadata.get("atr", 0) or 0) or 0.015 * executable_entry
            candidate.sl = round(executable_entry + max(1.5 * _atr_h, 0.015 * executable_entry), 8)

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
            # ── r60 TC calibration (Viva 09-29, dictated law, his prime
            # suspect): for a TECHCLASSIC BREAK the validated break IS the
            # signal — a lagging parent-TF trend may no longer veto it
            # («چرا این ستاپ‌ها موقعیت رو می‌شناسن اما تایید نمی‌کنن؟»).
            # The opposed parent becomes a visible warning only. Counter-trend
            # FADEs and every other setup keep the hard veto untouched.
            # r60.6: contract-based, not setup-based — TECHCLASSIC, TLBREAK
            # and ALBROX (pattern & zone) all confirm the BREAK's direction;
            # «خلاف روند» is reserved for rejections (TLBREAK/ALBROX scalps).
            # ── 10-09 (Viva: «این اجازه فقط مختص پینوال است»): a rejection
            # scalp is not a break — the contract exemption is for validated
            # BREAKS only. The pin family escapes through its own evidence
            # instead (pin-level close + rising counter-trend orders).
            _tc_break60 = (
                str((candidate.metadata or {}).get("break_direction") or "").upper() in ("UP", "DOWN")
                and not (candidate.metadata or {}).get("rejection_scalp")
            )
            _pin_ct_1009 = False
            try:
                _pin_ct_1009 = bool(_pin_countertrend_lift())
            except Exception:
                _pin_ct_1009 = False
            if not _brk and not _tc_break60 and not _pin_ct_1009:
                return reject("COUNTER_TREND_TOUCH_ONLY", (
                    "سیگنال خلاف جهت ساختار است: برخورد به خط/ناحیه فقط هشدار است؛ "
                    "تأیید نیازمند کلوز معتبر فراتر از سوینگ هم‌جهت است "
                    "(سلرها/خریداران در برخورد شکار می‌شوند)."))
            if _pin_ct_1009:
                candidate.metadata["mtf_context_warning_pin"] = (
                    "خلاف روند والد اما پینوال: سطح پین با کلوز معتبر رد شد و حجم "
                    "خلاف روند بالا رفته است — طبق قانون ۱۰-۰۹ فقط پینوال این اجازه را دارد.")
            if _tc_break60:
                candidate.metadata["mtf_context_warning_tc"] = (
                    "روند تایم والد هنوز مخالف است؛ طبق قانون تکنوکلاسیک جهت با "
                    "شکستِ اعتبارسنجی‌شده قفل شد و این فقط هشدار زمینه است.")
            if _trg_tf == "1d" and _pdf is not None and len(_pdf) >= 12:
                _pp = _pdf.iloc[-11:-1]
                if candidate.direction == "SHORT":
                    _hbrk = float(_pdf["close"].iloc[-1]) < float(_pp["low"].min())
                else:
                    _hbrk = float(_pdf["close"].iloc[-1]) > float(_pp["high"].max())
                if not _hbrk:
                    candidate.metadata["mtf_context_warning_1d"] = (
                        "کانتکست خلاف جهت در روزانه ثبت شد؛ بریک ۴ساعته هنوز مستقل تأیید نشده است.")
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
                    candidate.metadata["mtf_opposing_zone_warning"] = (
                        f"نزدیک ناحیه مخالف در تایم والد ({_parent_tf})؛ این مورد به‌عنوان هشدار زمینه‌ای ثبت شد.")
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
