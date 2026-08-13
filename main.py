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
    timeframe = candidate.trigger_timeframe
    return bundle.get(timeframe)


def run_discovery_scan() -> Dict[str, int]:
    """Find educational setups; never writes unconfirmed rows to Supabase."""
    started = time.monotonic()
    symbols, metrics = UNIVERSE.get()
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
                if has_unresolved_symbol(candidate.symbol):
                    continue
                if not add_candidate(candidate):
                    continue
                try:
                    locked = acquire_symbol_lock(candidate)
                except Exception as exc:
                    locked = False
                    print(f"Symbol-lock error {candidate.symbol}: {exc}")
                if not locked:
                    update_candidate(candidate, "CANCELLED")
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


def _candidate_market_frames(candidates) -> Dict[Tuple[str, str], Tuple[pd.DataFrame, pd.DataFrame, float]]:
    """One Bybit request per active symbol/style for monitor and confirmation."""
    frames: Dict[Tuple[str, str], Tuple[pd.DataFrame, pd.DataFrame, float]] = {}
    for candidate in candidates:
        key = (candidate.symbol, candidate.trigger_timeframe)
        if key in frames:
            continue
        live = get_klines(
            candidate.symbol,
            candidate.trigger_timeframe,
            140,
            closed_only=False,
            use_cache=False,
        )
        if live is None or len(live) < 20:
            continue
        # Bybit's newest row is forming; only prior rows may confirm an entry.
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
        key = (candidate.symbol, candidate.trigger_timeframe)
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
            if not publication_in_progress and is_expired(candidate):
                candidate.status = "EXPIRED"
                update_candidate(candidate)
                try:
                    cancel_staged_confirmation(candidate.signal_id)
                except Exception as exc:
                    print(f"Could not release staged symbol {candidate.signal_id}: {exc}")
                send_candidate_cancelled(candidate, "زمان اعتبار Setup به پایان رسید و تأیید ورود تشکیل نشد.")
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
                stats["cancelled"] += 1
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
                    elif send_confirmed(candidate, closed):
                        # send_confirmed sets durable component receipts in metadata;
                        # result monitoring remains disarmed until this DB update commits.
                        candidate.status = "APPROACHING"
                        candidate.metadata["publication_pending"] = True
                        try:
                            update_candidate(candidate)
                            mark_confirmation_published(candidate.signal_id)
                        except Exception as exc:
                            print(
                                f"Confirmation was published but DB gate remains pending "
                                f"for {candidate.signal_id}: {exc}"
                            )
                        else:
                            candidate.status = "CONFIRMED"
                            candidate.metadata["confirmation_sent"] = True
                            candidate.metadata.pop("publication_pending", None)
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
                f"confirmed={stats['confirmed']} cancelled={stats['cancelled']} trade_events={trade_events}"
            )
    except Exception as exc:
        print(f"Candidate monitor cycle error: {exc}")


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
    next_monitor = datetime.now(timezone.utc)
    last_daily_report = ""
    print(
        f"Scheduler active • next discovery {next_scan.isoformat(timespec='minutes')} • "
        f"monitor every {SETTINGS.monitor_minutes} minutes"
    )

    while not _SHUTDOWN:
        now = datetime.now(timezone.utc)
        if now >= next_monitor:
            run_monitor_cycle()
            next_monitor = now + timedelta(minutes=SETTINGS.monitor_minutes)
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
