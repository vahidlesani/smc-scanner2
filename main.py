"""Viva Signal Bot v7 entry point.

Quality-first architecture:
- dynamic high-liquidity Bybit universe
- one cached data bundle per symbol
- aligned 15-minute discovery scans
- independent Swing and Scalp engines
- local educational candidate lifecycle
- Supabase persistence only after closed-candle confirmation
"""
from __future__ import annotations

import os
import signal
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

import pandas as pd

from analysis.models import SignalCandidate
from analysis.quality_engine import (
    approaching_entry,
    evaluate_confirmation,
    is_expired,
    is_invalidated,
    scan_bundle,
)
from bot.commands import start_command_listener
from bot.messages_v7 import (
    send_approaching,
    send_candidate_cancelled,
    send_confirmed,
    send_educational_setup,
    send_message,
    send_startup_message,
    purge_candidate_alert_posts,
    purge_pro_watch_post,
    send_tp1_event,
    send_trade_result,
)
from config import get_settings
from data.fetcher import get_klines, get_market_bundle
from data.universe import UNIVERSE
from database.candidate_store import (
    add_candidate,
    cleanup_candidates,
    get_active_candidates,
    init_candidate_store,
    update_candidate,
    supersede_similar,
    find_similar,
    is_material_update,
    supersede_symbol_alerts,
)
from database.repository_v7 import (
    acquire_symbol_lock,
    cancel_staged_confirmation,
    has_unresolved_symbol,
    init_v7_schema,
    is_confirmation_published,
    mark_confirmation_published,
    monitor_confirmed_trades,
    release_symbol_lock,
    save_confirmed_signal,
    update_symbol_lock,
)

SETTINGS = get_settings()
_SHUTDOWN = False


def _request_shutdown(signum, _frame) -> None:
    global _SHUTDOWN
    print(f"Received signal {signum}; shutting down after current task")
    _SHUTDOWN = True


def _chart_frame(candidate: SignalCandidate, bundle) -> pd.DataFrame:
    # TLBREAK alerts show the channel break itself: chart the CONTEXT timeframe
    # (4h/1h/1d) where the trendline lives, not the fine-grained trigger chart.
    if candidate.setup_code == "TLBREAK":
        context_tf = candidate.metadata.get("tl_context_tf")
        if context_tf and bundle.get(context_tf) is not None:
            return bundle.get(context_tf)
    timeframe = candidate.trigger_timeframe
    return bundle.get(timeframe)


# Dead-gate candidates are no longer stored, so suppress repeat educational
# messages for the same setup idempotently in memory (survives one process).
_DEAD_GATE_ALERTED: Dict[str, float] = {}


def _dead_gate_recently_alerted(candidate: SignalCandidate) -> bool:
    key = (
        f"{candidate.symbol}:{candidate.style}:{candidate.setup_code}:{candidate.direction}:"
        f"{round(float(candidate.metadata.get('structure_level', 0) or 0), 6)}"
    )
    expiry_hours = (
        SETTINGS.candidate_expiry_hours_swing
        if candidate.style == "SWING"
        else SETTINGS.candidate_expiry_hours_scalp
    )
    now = time.monotonic()
    last = _DEAD_GATE_ALERTED.get(key)
    if last is not None and (now - last) < expiry_hours * 3600:
        return True
    _DEAD_GATE_ALERTED[key] = now
    return False


def run_discovery_scan() -> Dict[str, int]:
    """Find educational setups; never writes unconfirmed rows to Supabase."""
    started = time.monotonic()
    symbols, metrics = UNIVERSE.get()
    # Viva's priority rule: symbols with an open alert get scanned FIRST (in
    # the order their alerts were issued) so follow-up scenarios on them
    # surface before anything else.
    try:
        active_symbols = []
        for candidate in get_active_candidates():
            if candidate.setup_code == "PINVAL":
                continue
            if candidate.symbol in symbols and candidate.symbol not in active_symbols:
                active_symbols.append(candidate.symbol)
        if active_symbols:
            symbols = active_symbols + [s for s in symbols if s not in active_symbols]
    except Exception:
        pass
    stats = {"symbols": len(symbols), "detected": 0, "new": 0, "errors": 0}
    print(
        f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC] "
        f"Discovery scan started for {len(symbols)} dynamic symbols"
    )
    for index, symbol in enumerate(symbols, start=1):
        if _SHUTDOWN:
            break
        try:
            bundle = get_market_bundle(symbol, ticker=metrics.get(symbol, {}))
            candidates = scan_bundle(bundle)
            stats["detected"] += len(candidates)
            for candidate in candidates:
                if candidate.score < SETTINGS.educational_min_score:
                    continue
                if SETTINGS.skip_dead_gate_candidates and not candidate.execution_ready:
                    # A failing mandatory gate can never be repaired later, so
                    # this candidate can never confirm. Keep it educational,
                    # but do not track it: no Approaching spam, no symbol lock.
                    candidate.metadata["execution_blocked_gates"] = [
                        gate for gate, valid in candidate.mandatory_gates.items() if not valid
                    ]
                    stats["dead_gate"] = stats.get("dead_gate", 0) + 1
                    if not _dead_gate_recently_alerted(candidate):
                        send_educational_setup(candidate, _chart_frame(candidate, bundle))
                    continue
                # Same symbol + same trigger TF: remove the older alert package
                # and publish only the newest live scenario, so strong setups
                # never disappear inside Telegram clutter.
                previous = find_similar(candidate)
                if previous and not is_material_update(previous, candidate):
                    continue  # identical state: leave the visible alert alone
                # A materially newer scenario replaces every live alert package
                # of the same SYMBOL, even if its new signal id/timeframe differs.
                # This is Telegram hygiene, not a position lock.
                for prior in supersede_symbol_alerts(candidate.symbol, candidate.signal_id):
                    try:
                        release_symbol_lock(prior.symbol, prior.signal_id)
                    except Exception:
                        pass
                    purge_candidate_alert_posts(prior)
                    purge_pro_watch_post(prior)
                # Live alerts replace themselves on meaningful new information;
                # symbol locks would hide those updates, so discovery has no lock.
                if not add_candidate(candidate):
                    continue
                stats["new"] += 1
                send_educational_setup(candidate, _chart_frame(candidate, bundle))
            if index % 10 == 0:
                print(f"  scanned {index}/{len(symbols)} • new educational setups: {stats['new']}")
        except Exception as exc:
            stats["errors"] += 1
            print(f"Discovery error {symbol}: {exc}")
    cleanup_candidates()
    duration = time.monotonic() - started
    print(
        f"Discovery scan finished in {duration:.1f}s • "
        f"detected={stats['detected']} new={stats['new']} errors={stats['errors']}"
    )
    return stats


def _pinv_window_expired(candidate: SignalCandidate, closed: Optional[pd.DataFrame]) -> bool:
    """Count only closed bars of the pin trigger timeframe after alert creation."""
    if closed is None or closed.empty:
        return is_expired(candidate)
    md = candidate.metadata or {}
    tf = str(md.get("pin_tf") or candidate.trigger_timeframe)
    seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}.get(tf, 300)
    try:
        created = pd.Timestamp(str(candidate.created_at)).tz_localize(None)
        bars = closed[pd.to_datetime(closed["timestamp"]) >= created - pd.Timedelta(seconds=seconds)]
        return len(bars) >= int(md.get("pin_verdict_candles") or SETTINGS.alert_verdict_candles)
    except Exception:
        return is_expired(candidate)


def _resolve_pinv_verdict(candidate: SignalCandidate, closed: Optional[pd.DataFrame]) -> None:
    """Pinbar alert lifecycle: within N trigger candles, a close beyond the
    pinbar's confirming extreme = ✅ تأیید; a close beyond the wick = ❌ تأیید
    نشد; running out of candles or expiry = ⚪ بدون تأیید. Every outcome is a
    Telegram reply under the original alert so the loop visibly closes."""
    from bot.messages_v7 import send_verdict_reply
    if closed is None or len(closed) < 2:
        if is_expired(candidate):
            candidate.status = "VERDICT_TIMEOUT"
            update_candidate(candidate)
            send_verdict_reply(candidate, None, "مهلت هشدار تمام شد؛ حرکت تأییدکننده شکل نگرفت.")
        return
    md = candidate.metadata or {}
    pin_ts = str(md.get("pin_ts") or "")
    pin_high = float(md.get("pin_high") or 0)
    pin_low = float(md.get("pin_low") or 0)
    n_candles = int(md.get("pin_verdict_candles") or SETTINGS.alert_verdict_candles)
    if not pin_high or not pin_low:
        candidate.status = "VERDICT_TIMEOUT"
        update_candidate(candidate)
        return
    # Verdict window = N closed candles AFTER THE ALERT, on the pin's own
    # timeframe. (Earlier versions counted candles after the pin candle
    # itself, so a pin one candle old at detection exhausted the whole
    # verdict window before anyone could act — the "cancelled after 21
    # candles in 1 minute" bug.)
    pin_tf = str(md.get("pin_tf") or candidate.trigger_timeframe)
    tf_seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(pin_tf, 300)
    try:
        det = pd.Timestamp(str(candidate.created_at)).tz_localize(None)
        threshold = det - pd.Timedelta(seconds=tf_seconds)
        after = closed[pd.to_datetime(closed["timestamp"]) >= threshold]
    except Exception:
        try:
            ts = pd.Timestamp(pin_ts)
            after = closed[pd.to_datetime(closed["timestamp"]) > ts]
        except Exception:
            after = closed.tail(n_candles)
    direction = candidate.direction
    for _, row in after.head(n_candles).iterrows():
        c = float(row["close"])
        if direction == "LONG":
            if c > pin_high:
                _pinv_done(candidate, True, f"کلوز بالای {pin_high:g} — حرکت صعودی پین‌بار تأیید شد. مدیریت با خودت.")
                return
            if c < pin_low:
                _pinv_done(candidate, False, f"کلوز پایین کف پین‌بار ({pin_low:g}) — سناریو باطل شد.")
                return
        else:
            if c < pin_low:
                _pinv_done(candidate, True, f"کلوز زیر {pin_low:g} — حرکت نزولی پین‌بار تأیید شد. مدیریت با خودت.")
                return
            if c > pin_high:
                _pinv_done(candidate, False, f"کلوز بالای سقف پین‌بار ({pin_high:g}) — سناریو باطل شد.")
                return
    if len(after) >= n_candles or is_expired(candidate):
        candidate.status = "VERDICT_TIMEOUT"
        update_candidate(candidate)
        tf_fa = {"1m": "۱دقیقه‌ای", "5m": "۵دقیقه‌ای", "15m": "۱۵دقیقه‌ای", "1h": "۱ساعته"}.get(pin_tf, pin_tf)
        send_verdict_reply(candidate, None,
                         f"پس از {len(after)} کندل {tf_fa} (از زمان هشدار) کلوز تأییدکننده نیامد؛ هشدار بدون اجرا بسته شد.")


def _pinv_done(candidate: SignalCandidate, ok: bool, why: str) -> None:
    from bot.messages_v7 import send_verdict_reply
    candidate.status = "VERDICT_YES" if ok else "VERDICT_NO"
    print(f"PINVAL verdict {candidate.signal_id}: {candidate.status}")
    send_verdict_reply(candidate, ok, why)
    update_candidate(candidate)


def _candidate_market_frames(candidates) -> Dict[Tuple[str, str], Tuple[pd.DataFrame, pd.DataFrame, float]]:
    """One Bybit request per active symbol/TF for monitor and confirmation.

    Confirmation now runs on the candidate's finer `confirm_tf` (1m scalp /
    5m swing) when present, so a valid retest is confirmed inside minutes;
    charts keep using the trigger TF (see `_chart_frame`)."""
    frames: Dict[Tuple[str, str], Tuple[pd.DataFrame, pd.DataFrame, float]] = {}
    for candidate in candidates:
        confirm_tf = candidate.metadata.get("confirm_tf") or candidate.trigger_timeframe
        for tf in {confirm_tf, candidate.trigger_timeframe}:
            key = (candidate.symbol, tf)
            if key in frames:
                continue
            live = get_klines(
                candidate.symbol,
                tf,
                140,
                closed_only=False,
                use_cache=False,
            )
            if live is None or len(live) < 20:
                continue
            # Bybit's newest row is forming; only prior rows may confirm.
            closed = live.iloc[:-1].reset_index(drop=True)
            current_price = float(live["close"].iloc[-1])
            frames[key] = (live, closed, current_price)
    return frames


def monitor_candidates() -> Dict[str, int]:
    """Approaching → closed-candle confirmation → confirmed persistence."""
    candidates = get_active_candidates()
    stats = {"active": len(candidates), "approaching": 0, "confirmed": 0, "cancelled": 0}
    if not candidates:
        return stats
    frames = _candidate_market_frames(candidates)
    for candidate in candidates:
        key = (candidate.symbol, candidate.metadata.get("confirm_tf") or candidate.trigger_timeframe)
        market_data = frames.get(key)
        publication_in_progress = bool(
            candidate.metadata.get("technical_confirmation_complete")
            and (
                candidate.metadata.get("confirmation_chart_sent")
                or candidate.metadata.get("confirmation_message_sent")
            )
        )
        # Once one Confirmed component is public, finish the exact same
        # confirmation even if market data is temporarily unavailable.
        if not market_data and not publication_in_progress:
            continue
        live, closed, current_price = market_data if market_data else (None, None, None)
        try:
            if candidate.setup_code == "PINVAL":
                # PINVAL now uses the same lower-timeframe confirmation engine
                # as every executable setup. Its native timeframe only limits
                # how long the alert may wait; it never counts LTF bars here.
                md_pin = candidate.metadata or {}
                pin_tf = str(md_pin.get("pin_tf") or candidate.trigger_timeframe)
                pin_frame = frames.get((candidate.symbol, pin_tf))
                # No arbitrary 3/4-candle verdict timeout: a meaningful new
                # alert supersedes this one; only real invalidation/expiry ends it.
            if not publication_in_progress and is_expired(candidate):
                candidate.status = "EXPIRED"
                update_candidate(candidate)
                try:
                    cancel_staged_confirmation(candidate.signal_id)
                except Exception as exc:
                    print(f"Could not release staged symbol {candidate.signal_id}: {exc}")
                send_candidate_cancelled(candidate, "زمان اعتبار Setup به پایان رسید و تأیید ورود تشکیل نشد.")
                try:
                    from bot.messages_v7 import send_verdict_reply
                    send_verdict_reply(candidate, None, "مهلت ستاپ تمام شد؛ کندل تأییدکننده شکل نگرفت.")
                except Exception:
                    pass
                stats["cancelled"] += 1
                continue
            if not publication_in_progress and is_invalidated(candidate, current_price):
                candidate.status = "CANCELLED"
                update_candidate(candidate)
                try:
                    cancel_staged_confirmation(candidate.signal_id)
                except Exception as exc:
                    print(f"Could not release staged symbol {candidate.signal_id}: {exc}")
                send_candidate_cancelled(
                    candidate,
                    f"قیمت پیش از تأیید از سطح ابطال {candidate.sl} عبور کرد.",
                )
                try:
                    from bot.messages_v7 import send_verdict_reply
                    send_verdict_reply(candidate, False, f"قیمت از سطح ابطال {candidate.sl:g} گذشت؛ سناریو باطل شد.")
                except Exception:
                    pass
                stats["cancelled"] += 1
                continue

            if SETTINGS.skip_dead_gate_candidates and not candidate.execution_ready:
                # Legacy dead-on-arrival candidate from before the gate fix:
                # cannot ever confirm; expiry/invalidation above will close it.
                continue

            if not candidate.metadata.get("technical_confirmation_complete"):
                is_near, distance_atr = approaching_entry(candidate, current_price)
                if is_near and not candidate.approaching_sent:
                    if send_approaching(candidate, current_price, distance_atr):
                        candidate.approaching_sent = True
                        candidate.status = "APPROACHING"
                        stats["approaching"] += 1

            if (
                candidate.metadata.get("technical_confirmation_complete")
                and not candidate.metadata.get("confirmation_sent")
            ):
                # Retry publication of the original confirmed setup. Do not move
                # Entry/confirmed_at to a later candle or inflate its score.
                candidate.status = "CONFIRMED"
                confirmed, reason = True, "تلاش مجدد برای تکمیل انتشار"
            else:
                confirmed, candidate, reason = evaluate_confirmation(candidate, closed)

            if not confirmed:
                code = str(candidate.metadata.get("last_reject_code") or "UNKNOWN")
                stats["rejects"] = stats.get("rejects", {})
                stats["rejects"][code] = int(stats["rejects"].get(code, 0)) + 1
            if confirmed:
                was_staged = bool(candidate.metadata.get("persistence_staged"))
                try:
                    # Stage first, but with AWAITING_PUBLICATION and a false gate.
                    # Portfolio rejection therefore cannot publish an untracked trade.
                    save_confirmed_signal(candidate)
                    candidate.metadata["persistence_staged"] = True
                except Exception as exc:
                    if was_staged or publication_in_progress:
                        candidate.status = "APPROACHING"
                        candidate.metadata["publication_pending"] = True
                        print(f"Staged confirmation lookup failed {candidate.signal_id}: {exc}")
                    else:
                        candidate.status = "CANCELLED"
                        send_candidate_cancelled(candidate, f"تأیید تکنیکال ایجاد شد اما کنترل ریسک اجازه اجرا نداد: {exc}")
                        stats["cancelled"] += 1
                else:
                    gate_lookup_ok = True
                    try:
                        already_published = is_confirmation_published(candidate.signal_id)
                    except Exception as exc:
                        gate_lookup_ok = False
                        already_published = False
                        candidate.status = "APPROACHING"
                        candidate.metadata["publication_pending"] = True
                        print(f"Confirmation gate lookup failed {candidate.signal_id}: {exc}")

                    if already_published:
                        candidate.status = "CONFIRMED"
                        candidate.metadata["confirmation_sent"] = True
                        candidate.metadata.pop("publication_pending", None)
                    elif not gate_lookup_ok:
                        pass  # Fail closed; never republish while DB state is unknown.
                    elif send_confirmed(candidate, (frames.get((candidate.symbol, candidate.trigger_timeframe)) or (None, closed, None))[1]):
                        # send_confirmed sets durable component receipts in metadata;
                        # result monitoring remains disarmed until this DB update commits.
                        candidate.status = "APPROACHING"
                        candidate.metadata["publication_pending"] = True
                        try:
                            update_candidate(candidate)
                            mark_confirmation_published(candidate.signal_id)
                            # Confirmed is a reply under the final-watch chart in Pro;
                            # the full educational alert remains reachable through its link.
                        except Exception as exc:
                            print(
                                f"Confirmation was published but DB gate remains pending "
                                f"for {candidate.signal_id}: {exc}"
                            )
                        else:
                            candidate.status = "CONFIRMED"
                            candidate.metadata["confirmation_sent"] = True
                            candidate.metadata.pop("publication_pending", None)
                            try:
                                from bot.messages_v7 import send_verdict_reply
                                send_verdict_reply(candidate, True, "تأیید ورود با کندل بسته‌شده صادر شد — پیام کانفرمد جداگانه آمد.")
                            except Exception:
                                pass
                            stats["confirmed"] += 1
                    else:
                        candidate.status = "APPROACHING"
                        candidate.metadata["publication_pending"] = True
                        print(
                            f"Confirmation publication pending {candidate.signal_id}; "
                            "trade results remain disarmed"
                        )
            update_candidate(candidate)
            try:
                if candidate.status in {"EDUCATIONAL", "APPROACHING", "CONFIRMED"}:
                    update_symbol_lock(candidate)
                else:
                    release_symbol_lock(candidate.symbol, candidate.signal_id)
            except Exception as exc:
                print(f"Could not update symbol lock {candidate.signal_id}: {exc}")
        except Exception as exc:
            print(f"Candidate monitor error {candidate.signal_id}: {exc}")
    return stats


def monitor_confirmed_results() -> int:
    events = monitor_confirmed_trades()
    for event in events:
        if event.get("event") == "TP1":
            send_tp1_event(event)
        elif event.get("event") == "CLOSED":
            send_trade_result(event)
    return len(events)


def run_monitor_cycle() -> None:
    try:
        trade_events = monitor_confirmed_results()
    except Exception as exc:
        print(f"Confirmed trade monitor error: {exc}")
        trade_events = 0
    try:
        stats = monitor_candidates()
        if stats["active"] or trade_events:
            print(
                f"Monitor • candidates={stats['active']} approaching={stats['approaching']} "
                f"confirmed={stats['confirmed']} cancelled={stats['cancelled']} trade_events={trade_events} "
                f"rejects={stats.get('rejects', {})}"
            )
    except Exception as exc:
        print(f"Candidate monitor cycle error: {exc}")


def _next_aligned(now: datetime, interval: int, offset: int) -> datetime:
    """Next grid-aligned time `offset` minutes into each `interval` block."""
    interval = max(1, int(interval))
    offset = int(offset) % interval
    base = now.replace(second=0, microsecond=0)
    minute = base.minute
    next_minute = ((minute - offset) // interval + 1) * interval + offset
    if next_minute >= 60:
        return (base.replace(minute=offset) + timedelta(hours=1))
    candidate = base.replace(minute=next_minute)
    return candidate if candidate > now else candidate + timedelta(minutes=interval)


def _next_aligned_scan(now: datetime) -> datetime:
    """Next :01/:16/:31/:46 UTC, shortly after a 15m candle closes."""
    interval = max(1, SETTINGS.full_scan_minutes)
    offset = SETTINGS.scan_offset_minute % interval
    base = now.replace(second=0, microsecond=0)
    minute = base.minute
    next_minute = ((minute - offset) // interval + 1) * interval + offset
    if next_minute >= 60:
        return (base.replace(minute=offset) + timedelta(hours=1))
    candidate = base.replace(minute=next_minute)
    return candidate if candidate > now else candidate + timedelta(minutes=interval)


def _daily_report() -> None:
    try:
        from database.db import get_dashboard_summary, get_strategy_performance
        summary = get_dashboard_summary()
        strategies = get_strategy_performance()[:5]
        lines = [
            "📊 <b>گزارش روزانه سیگنال‌های Confirmed</b>",
            f"کل: {summary['total_signals']} • Win: {summary['wins']} • Loss: {summary['losses']}",
            f"Win Rate: <b>{summary['winrate']}%</b> • Avg PnL: <b>{summary['avg_pnl']:+.2f}%</b>",
            "",
            "🏆 <b>عملکرد Setupها</b>",
        ]
        for item in strategies:
            lines.append(
                f"• {item['strategy_fa']}: {item['wins']}W/{item['losses']}L • {item['winrate']:.1f}%"
            )
        send_message("\n".join(lines))
        from bot.messages_v7 import purge_resolved_alert_posts
        removed = purge_resolved_alert_posts()
        print(f"Daily alert cleanup: removed {removed} resolved posts")
    except Exception as exc:
        print(f"Daily report error: {exc}")


def main() -> None:
    # Combined Railway service runs the scanner in a background thread while
    # Waitress owns the main thread. Python only permits signal handlers in the
    # process main thread, so register them conditionally.
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _request_shutdown)
        signal.signal(signal.SIGINT, _request_shutdown)
    if not os.getenv("TELEGRAM_TOKEN"):
        print("WARNING: TELEGRAM_TOKEN is not set")

    init_candidate_store()
    init_v7_schema()
    symbols, _ = UNIVERSE.get()
    send_startup_message(len(symbols))
    try:
        start_command_listener()
        print("🤖 Telegram command listener active")
    except Exception as exc:
        print(f"Command listener error: {exc}")

    now = datetime.now(timezone.utc)
    if SETTINGS.run_scan_on_start:
        run_discovery_scan()
    next_scan = _next_aligned_scan(datetime.now(timezone.utc))
    # Monitor on a candle-close grid: each cycle sees the most decisive final
    # minute of the smallest trigger timeframe (5m), and every 12th/48th/288th
    # cycle coincides with the 1h/4h/1D close.
    next_monitor = _next_aligned(
        datetime.now(timezone.utc), SETTINGS.monitor_minutes, SETTINGS.monitor_offset_minute
    )
    last_daily_report = ""
    print(
        f"Scheduler active • next discovery {next_scan.isoformat(timespec='minutes')} • "
        f"monitor every {SETTINGS.monitor_minutes} minutes"
    )

    while not _SHUTDOWN:
        now = datetime.now(timezone.utc)
        if now >= next_monitor:
            run_monitor_cycle()
            next_monitor = _next_aligned(
                datetime.now(timezone.utc), SETTINGS.monitor_minutes, SETTINGS.monitor_offset_minute
            )
        if now >= next_scan:
            run_discovery_scan()
            next_scan = _next_aligned_scan(datetime.now(timezone.utc))
        report_key = now.strftime("%Y-%m-%d")
        if now.hour == 8 and now.minute < 2 and report_key != last_daily_report:
            _daily_report()
            last_daily_report = report_key
        time.sleep(5)
    print("Viva Signal Bot stopped cleanly")


if __name__ == "__main__":
    main()
