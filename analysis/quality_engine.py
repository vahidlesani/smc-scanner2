"""Orchestrates separate Swing/Scalp engines and candidate confirmation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

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
        return scan_setups(bundle, self.name)


class DayTradeEngine:
    """Primary live tier: 4h context, 1h structure, 15m POI, 5m confirmation."""
    name = "DAYTRADE"
    required_frames = ("4h", "1h", "15m", "5m")

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


ENGINES = {"SWING": SwingEngine(), "DAYTRADE": DayTradeEngine(), "SCALP": ScalpEngine()}


def _live_styles() -> List[str]:
    raw = str(getattr(SETTINGS, "live_styles", "DAYTRADE,SWING") or "")
    styles = [x.strip().upper() for x in raw.split(",") if x.strip() in ENGINES]
    return styles or ["DAYTRADE", "SWING"]


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
    after = closed_df.loc[timestamps >= created].copy()
    return after if not after.empty else closed_df.tail(2).copy()


def evaluate_confirmation(
    candidate: SignalCandidate, closed_df: pd.DataFrame
) -> Tuple[bool, SignalCandidate, str]:
    """Require a zone touch plus a closed LTF trigger candle.

    No live/incomplete candle can confirm a trade. A candidate score may gain one
    trigger point, but missing mandatory gates can never be compensated by score.
    """
    def reject(code: str, message: str) -> Tuple[bool, SignalCandidate, str]:
        candidate.metadata["last_reject_code"] = code
        return False, candidate, message

    if closed_df is None or len(closed_df) < 20:
        return reject("NO_DATA", "داده کافی برای تأیید وجود ندارد.")
    after = _bars_since_candidate(candidate, closed_df)
    if after is None or after.empty:
        return reject("NO_NEW_BAR", "هنوز کندلی بعد از ایجاد ستاپ بسته نشده است.")

    # ── FAST BREAK FOLLOW-THROUGH (Viva 2026-09-11) ──────────────────────
    # TLBREAK doctrine: the FIRST BREAK is a valid entry — «بگرد ببین چی جلوی
    # کانفرمد رو گرفته که موقعیت‌ها رو می‌سوزونه». When price broke the fitted
    # line and prints two consecutive closes beyond it (no close back inside
    # for the last 4) with a real displacement body, that IS the confirmation:
    # no retest may be demanded, and NO_TOUCH must not veto it. Scoring stays
    # additive: the lane never loosens invalidation/chase/RR guards.
    fast_lane = ""
    if (candidate.metadata.get("strategy_variant") == "VIVA_TLBREAK"
            and not candidate.metadata.get("touched", False)):
        _line = candidate.metadata.get("viva_breakout_line") or candidate.metadata.get("viva_break_line")
        try:
            _line = float(_line) if _line else 0.0
        except Exception:
            _line = 0.0
        if _line > 0:
            _atr = float(candidate.metadata.get("atr", 0) or 0) or float(
                (closed_df["high"] - closed_df["low"]).tail(14).mean() or 0.0)
            if _atr > 0 and len(after) >= 2:
                _is_long = candidate.direction == "LONG"
                _buf = 0.10 * _atr
                _tail2 = after.tail(2)
                _out = [bool(float(r["close"]) >= _line + _buf) if _is_long
                        else bool(float(r["close"]) <= _line - _buf)
                        for _, r in _tail2.iterrows()]
                _bodies = [abs(float(r["close"]) - float(r["open"])) / _atr
                           for _, r in _tail2.iterrows()]
                _recent = after.tail(4)
                _back = (bool((_recent["close"] <= _line - _buf).any()) if _is_long
                         else bool((_recent["close"] >= _line + _buf).any()))
                if all(_out) and max(_bodies) >= 0.35 and not _back:
                    fast_lane = (f"دو کلوز متوالیِ معتبر پشت خطِ شکسته (≥{_buf/_atr:.2f} ATR) "
                                 f"بدون بازگشتِ کلوز به داخل؛ Body حداکثر {max(_bodies):.2f} ATR")
                    candidate.metadata["tl_fast_break"] = fast_lane

    touched = bool(candidate.metadata.get("touched", False)) or bool(fast_lane)
    if not touched:
        touched = bool(
            (
                (after["low"] <= candidate.entry_zone_top)
                & (after["high"] >= candidate.entry_zone_bottom)
            ).any()
        )
    candidate.metadata["touched"] = touched
    if not touched:
        return reject("NO_TOUCH", "قیمت هنوز اولین Retest ناحیه ورود را انجام نداده است.")

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
    if not trigger_valid and candidate.metadata.get("tl_fast_break"):
        trigger_valid = True
        candidate.metadata["trigger_note"] = "شکستِ معتبر + دو کلوز پشت خط (بدون پولبک)"
    if not trigger_valid and alt is not None:
        trigger_valid = True
        alt_only = True
    if not trigger_valid:
        return reject("NO_TRIGGER", (
            "Retest انجام شده، اما هنوز نه کندل تکی تأییدی و نه بیس چندکندلی/تایم‌بالاتری "
            "شدنِ Rejection را نساخته‌اند."
        ))

    # The executable entry is the confirmation close, not the historical POI
    # midpoint. Reject a late confirmation if its real risk/reward has degraded.
    executable_entry = close
    risk = abs(executable_entry - candidate.sl)
    if risk <= 0:
        return reject("RISK_INVALID", "فاصله Entry تأییدشده تا حد ضرر معتبر نیست.")
    atr_value = float(candidate.metadata.get("atr", 0) or 0)
    if atr_value > 0:
        chase_atr = abs(executable_entry - zone_mid) / atr_value
        max_chase = float(getattr(SETTINGS, "confirm_max_chase_atr", 0.80))
        if chase_atr > max_chase:
            return reject("ENTRY_TOO_FAR", f"کلوز تأیید {chase_atr:.2f} ATR از زون دور شده؛ Chase مجاز نیست.")
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
    if rr1 < SETTINGS.confirm_rr1_floor or rr2 < SETTINGS.confirm_rr2_floor:
        return reject("RR_DEGRADED", (
            f"تأیید دیر صادر شده و R/R واقعی به {rr1:.2f}R و {rr2:.2f}R کاهش یافته است."
        ))
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
        from analysis.trigger_patterns import describe as describe_alt_trigger
        trigger_type = describe_alt_trigger(alt, candidate.direction)
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
    return True, candidate, "تأیید ورود با کندل بسته‌شده صادر شد."
