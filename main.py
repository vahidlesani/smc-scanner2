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
from typing import Dict, Optional, Tuple

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
    CHAT_ID_EXECUTION,
    send_approaching,
    send_candidate_cancelled,
    send_confirmed,
    send_educational_setup,
    send_setup_update,
    send_message,
    send_startup_message,
    purge_candidate_alert_posts,
    purge_pro_watch_post,
    send_tp1_event,
    send_ladder_event,
    send_trade_result,
    send_trade_close_event,
    send_stop_event_to_results,
    attach_results_link,
    send_no_fill_event,
)
from config import get_settings
from data.fetcher import get_klines, get_market_bundle
from data.universe import UNIVERSE
from database.candidate_store import (
    add_candidate,
    absorb_update_into_chain,
    chains_last_24h,
    open_chains_for,
    recent_lineage_zone,
    cleanup_candidates,
    get_active_candidates,
    init_candidate_store,
    update_candidate,
    supersede_similar,
    find_similar,
    is_material_update,
    supersede_alert_lineage,
)
from database.repository_v7 import (
    acquire_symbol_lock,
    cancel_staged_confirmation,
    has_unresolved_symbol,
    has_open_pre_tp1_signal,
    last_confirmed_entry,
    init_v7_schema,
    is_confirmation_published,
    mark_confirmation_published,
    monitor_confirmed_trades,
    repair_legacy_tp1_misclassified_results,
    release_symbol_lock,
    reserve_public_code,
    save_confirmed_signal,
    record_telegram_event,
    set_pro_message_id,
    set_first_tp_message_id,
    set_last_tp_message_id,
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
    # Viva 2026-09-14 «چارت ۱ ساعته میذاری پوزیشن رو ۱۵ دقیقه؟!» — the CHART
    # is the position: trigger timeframe, on EVERY setup, with no context-TF
    # preference. (Confirmation evaluation still receives the pattern-TF frame
    # through its own argument; only the picture had been wrong.)
    return bundle.get(candidate.trigger_timeframe)


# Viva 2026-09-14: an in-process dict dies with every deploy — that is what
# re-alerted the already-announced ATOM structure 80 seconds after the -11b
# boot. The alert memory now lives in bot_kv and survives redeploys.
_DEAD_GATE_ALERTED: Dict[str, float] = {}


def _kv_alerted(key: str, ttl_hours: float) -> bool:
    """Persistent first-alert dedup marker across restarts (KV, pruned to TTL)."""
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        now = time.time()
        data = {k: float(v) for k, v in (_g("alert_dedup", {}) or {}).items()
                if now - float(v) < max(0.25, float(ttl_hours)) * 3600}
        if key in data:
            return True
        data[key] = now
        _s("alert_dedup", data)
        return False
    except Exception:
        return False


def _iso_ts(value: str) -> float:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except Exception:
        return 0.0


def _update_too_fresh(holder: SignalCandidate) -> bool:
    """Viva 2026-09-13: «آپدیت الکی چه دردی داره» — an update may only report
    a price event that happened AFTER the alert (or after the previous
    update). Same-minute echoes are swallowed; the chain stays refreshed."""
    meta = getattr(holder, "metadata", None) or {}
    gap = max(120, int(getattr(SETTINGS, "update_min_gap_seconds", 300) or 300))
    anchor_t = _iso_ts(str(getattr(holder, "created_at", "") or ""))
    last_t = float(meta.get("last_update_ts") or 0.0)
    import time as _tt
    return (_tt.time() - max(anchor_t, last_t)) < gap


def _dead_gate_recently_alerted(candidate: SignalCandidate) -> bool:
    key = (
        f"{candidate.symbol}:{candidate.style}:{candidate.setup_code}:{candidate.direction}:"
        f"{round(float(candidate.metadata.get('structure_level', 0) or 0), 6)}"
    )
    from analysis.setups_v7 import expiry_hours_for
    expiry_hours = expiry_hours_for(candidate.style)
    return _kv_alerted(key, expiry_hours)


_SUPPRESSED_EDU_ALERTED: Dict[str, float] = {}


def _suppressed_edu_throttled(candidate) -> bool:
    """Viva 2026-09-11: a pre-TP1 capacity block must never swallow the FIRST
    detailed alert — the compact anchor still goes to the alerts channel,
    throttled per setup identity so 5-min rescans cannot spam it."""
    key = (f"{candidate.symbol}:{candidate.style}:{candidate.setup_code}:{candidate.direction}:"
           f"{round(float(candidate.entry_zone_bottom), 6)}")
    from analysis.setups_v7 import expiry_hours_for
    expiry_hours = expiry_hours_for(candidate.style)
    return _kv_alerted("sup:" + key, expiry_hours)


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
    # Viva 2026-09-11 («یهو ۱۰۰۰ تا هشدار میاد»): one scan cycle may open only a
    # bounded number of NEW detailed alerts; everything beyond that defers to
    # the next scan instead of flooding the channels in a single burst.
    _edu_budget = {"left": max(1, int(getattr(SETTINGS, "education_max_per_scan", 8) or 8))}

    def _educate(cand, frame):
        if _edu_budget["left"] <= 0:
            stats["edu_cycle_deferred"] = stats.get("edu_cycle_deferred", 0) + 1
            return False
        _edu_budget["left"] -= 1
        return send_educational_setup(cand, frame)
    # Observability only (no behaviour change): tally where each raw detector
    # candidate goes, per setup, so "0 confirmed" is diagnosable from logs.
    tally = {}

    def _t(cand):
        sc = str(getattr(cand, "setup_code", "?") or "?")
        return tally.setdefault(sc, {
            "seen": 0, "low_score": 0, "dead_gate": 0, "blocked": {},
            "suppressed_pre_tp1": 0, "dup": 0, "ready_new": 0,
        })
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
            # TechnoClassic pre-break previews (4H/1D edges). Never a signal;
            # cooldown-guarded; silently unavailable on any error.
            if getattr(SETTINGS, "technoclassic_preview_alerts", True):
                try:
                    from analysis.pattern_engine import send_prebreak_alerts
                    send_prebreak_alerts(bundle)
                except Exception as exc:
                    print(f"TECHCLASSIC prebreak skipped {symbol}: {exc}")
            stats["detected"] += len(candidates)
            for candidate in candidates:
                _t(candidate)["seen"] += 1
                if candidate.score < SETTINGS.educational_min_score:
                    _t(candidate)["low_score"] += 1
                    continue
                # Reserve before *any* public alert. A display code is a real
                # position identity, not a random label that may later change.
                try:
                    reserve_public_code(candidate)
                except Exception as exc:
                    stats["errors"] += 1
                    print(f"Public-code reservation failed {candidate.signal_id}: {exc}")
                    continue  # fail closed; never publish an unreserved code
                # ── Viva licence law (restated 2026-09-13, verbatim) ──────────
                # 3 rotating licences per (symbol, trigger timeframe, setup).
                # The next licence frees when the previous signal CONFIRMS;
                # while one chain is unresolved, a new detection on the same
                # tuple is absorbed into it. Different setup or different
                # trigger timeframe = fully independent. A new licence also
                # needs >=2% price distance from the last CONFIRMED price.
                if SETTINGS.chain_slot_gate_enabled:
                    try:
                        _trig = str(candidate.trigger_timeframe or "").lower()
                        live_chains = [
                            c for c in open_chains_for(candidate.symbol, candidate.setup_code, _trig)
                            if c.signal_id != candidate.signal_id
                            and str(c.direction).upper() == str(candidate.direction).upper()
                        ]
                    except Exception:
                        live_chains = []
                    if live_chains:
                        holder = live_chains[0]
                        stats["chain_absorbed"] = stats.get("chain_absorbed", 0) + 1
                        t = _t(candidate)
                        t["absorbed"] = t.get("absorbed", 0) + 1
                        try:
                            if is_material_update(holder, candidate):
                                absorb_note = absorb_update_into_chain(holder, candidate)
                                if _update_too_fresh(holder):
                                    # R-4/N2 (audit 09-15): observability only —
                                    # a MATERIAL update (zone moved ≥0.2×ATR or
                                    # structure changed) is never blocked; the
                                    # content-hash inside send_setup_update still
                                    # swallows identical repeats.
                                    stats["update_throttled"] = stats.get("update_throttled", 0) + 1
                                if send_setup_update(holder, _chart_frame(holder, bundle),
                                                        note_fa=absorb_note or "",
                                                        critical=True):
                                    hm = holder.metadata if isinstance(holder.metadata, dict) else {}
                                    import time as _tt
                                    hm["last_update_ts"] = _tt.time()
                                    holder.metadata = hm
                                    try:
                                        update_candidate(holder)
                                    except Exception:
                                        pass
                        except Exception as exc:
                            print(f"chain absorb warning {candidate.symbol}/{candidate.setup_code}: {exc}")
                        continue
                    try:
                        used = chains_last_24h(candidate.symbol, candidate.setup_code,
                                         str(candidate.trigger_timeframe or "").lower())
                    except Exception:
                        used = 0
                    if used >= max(1, int(getattr(SETTINGS, "chains_per_symbol_setup_24h", 3) or 3)):
                        stats["chain_license_cap"] = stats.get("chain_license_cap", 0) + 1
                        continue
                    # same-zone repeat dedupe: a zone already watched in 24h
                    # never re-alerts — that is noise control, not the licence
                    # distance rule (which is the fixed 2% below, Viva 2026-09-13).
                    _atr = max(float((candidate.metadata or {}).get("atr", 0) or 0), 1e-9)
                    try:
                        _quiet = recent_lineage_zone(
                            candidate.symbol, candidate.setup_code,
                            float(candidate.zone_mid),
                            max(_atr * 0.20, abs(float(candidate.zone_mid)) * 1e-4),
                            trigger_tf=str(candidate.trigger_timeframe or "").lower())
                    except Exception:
                        _quiet = None
                    if _quiet is not None and str(_quiet.signal_id) != str(candidate.signal_id):
                        stats["same_zone_quiet"] = stats.get("same_zone_quiet", 0) + 1
                        continue
                    # THE 2% LAW: the new licence may open only >=2% (fixed,
                    # identical for every setup) away from the price at which
                    # the last signal of this tuple was CONFIRMED.
                    try:
                        _sep = float(getattr(SETTINGS, "license_min_sep_pct", 0.02) or 0.0)
                        _last_px = last_confirmed_entry(candidate.symbol, candidate.trigger_timeframe,
                                                        candidate.setup_code)
                        _px = float(candidate.planned_entry or candidate.entry_zone_bottom or 0.0)
                        if (_sep > 0.0 and _last_px and _px
                                and abs(_px - float(_last_px)) < _sep * abs(float(_last_px))):
                            stats["license_sep_block"] = stats.get("license_sep_block", 0) + 1
                            t = _t(candidate); t["sep2pct"] = t.get("sep2pct", 0) + 1
                            print(
                                f"licence refused {candidate.symbol}/{candidate.setup_code}/"
                                f"{candidate.trigger_timeframe}: {_px:g} is only "
                                f"{abs(_px - float(_last_px)) / abs(float(_last_px)) * 100:.2f}% "
                                f"from last confirmed {_last_px:g} (<{_sep:.0%})"
                            )
                            continue
                    except Exception as exc:
                        print(f"licence distance gate skipped {candidate.signal_id}: {exc}")
                if SETTINGS.skip_dead_gate_candidates and not candidate.execution_ready:
                    # A failing mandatory gate can never be repaired later, so
                    # this candidate can never confirm. Keep it educational,
                    # but do not track it: no Approaching spam, no symbol lock.
                    blocked = [
                        gate for gate, valid in candidate.mandatory_gates.items() if not valid
                    ]
                    candidate.metadata["execution_blocked_gates"] = blocked
                    stats["dead_gate"] = stats.get("dead_gate", 0) + 1
                    t = _t(candidate); t["dead_gate"] += 1
                    for g in blocked:
                        t["blocked"][g] = t["blocked"].get(g, 0) + 1
                    # Viva 2026-09-13 «فقط سیگنال‌های به‌دیتابیس‌رسیده هشدار
                    # و آپدیت می‌گیرند»: a dead-on-arrival alert is recorded as
                    # a DEAD_GATE row (tracks the lineage, consumes NO licence,
                    # is never monitored) and only then may it post. An alert
                    # without a row is a ghost — no updates could ever attach.
                    candidate.status = "DEAD_GATE"
                    try:
                        _dead_saved = add_candidate(candidate)
                    except Exception:
                        _dead_saved = False
                    if _dead_saved and not _dead_gate_recently_alerted(candidate):
                        _educate(candidate, _chart_frame(candidate, bundle))
                    continue
                # Paper research permits several independent positions on a
                # symbol/trigger. Capacity is counted in confirmed positions;
                # it must never cause symbol-wide deletion of alerts.
                if has_open_pre_tp1_signal(candidate.symbol, candidate.trigger_timeframe,
                                                  candidate.setup_code):
                    stats["suppressed_pre_tp1"] = stats.get("suppressed_pre_tp1", 0) + 1
                    _t(candidate)["suppressed_pre_tp1"] += 1
                    if not _suppressed_edu_throttled(candidate):
                        _educate(candidate, _chart_frame(candidate, bundle))
                    continue
                previous = find_similar(candidate)
                # A generated candidate is a separate possible position.  Never
                # inherit an earlier candidate's public code merely because its
                # symbol/trigger matches: multiple paper trades are allowed on
                # that pair and each confirmed trade must retain its own links.
                if previous and not is_material_update(previous, candidate):
                    _t(candidate)["dup"] += 1
                    continue  # identical state: leave the visible alert alone
                # Delete Telegram posts only for a proven update of this same
                # scenario lineage. Same-symbol / same-trigger setups can be
                # independent and must remain visible.
                for prior in supersede_alert_lineage(candidate):
                    try:
                        release_symbol_lock(prior.symbol, prior.signal_id)
                    except Exception:
                        pass
                    purge_candidate_alert_posts(prior)
                    purge_pro_watch_post(prior)
                # Live alerts replace themselves on meaningful new information;
                # symbol locks would hide those updates, so discovery has no lock.
                if _edu_budget["left"] <= 0:
                    stats["edu_cycle_deferred"] = stats.get("edu_cycle_deferred", 0) + 1
                    continue  # not persisted; next scan retries when budget frees
                if not add_candidate(candidate):
                    _t(candidate)["dup"] += 1
                    continue
                # Advisory is asynchronous and isolated: a Gemini timeout can
                # never block detection, confirmation, risk or Telegram send.
                try:
                    from ai.gemini_advisor import request_advisory_async
                    request_advisory_async(candidate)
                except Exception as exc:
                    print(f"Gemini advisory enqueue warning {candidate.signal_id}: {exc}")
                # the detailed alert must exist BEFORE the row counts as a new
                # chain — when the cycle budget is exhausted the candidate is
                # left unpersisted so the very next scan retries it (nothing
                # lost, only smoothed).
                if not _educate(candidate, _chart_frame(candidate, bundle)):
                    continue
                stats["new"] += 1
                _t(candidate)["ready_new"] += 1
            if index % 10 == 0:
                print(f"  scanned {index}/{len(symbols)} • new educational setups: {stats['new']}")
        except Exception as exc:
            stats["errors"] += 1
            print(f"Discovery error {symbol}: {exc}")
    cleanup_candidates()
    try:  # Viva 2026-09-13: the funnel must be READABLE from the DB
        from database.bot_kv import get_json as _gkv, set_json as _skv
        try:
            from analysis.quality_engine import _live_styles as _ls
            _streams = ",".join(_ls())
        except Exception:
            _streams = "?"
        _summary = {
            "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "streams": _streams,
            "detected": stats.get("detected", 0), "new": stats.get("new", 0),
            "errors": stats.get("errors", 0),
            "absorbed": stats.get("chain_absorbed", 0),
            "quiet": stats.get("same_zone_quiet", 0),
            "liccap": stats.get("chain_license_cap", 0),
            "sep2pct": stats.get("license_sep_block", 0),
            "updthrottle": stats.get("update_throttled", 0),
            "deadgate": stats.get("dead_gate", 0),
            "pre_tp1": stats.get("suppressed_pre_tp1", 0),
            "deferred": stats.get("edu_cycle_deferred", 0),
            "tally": tally,
        }
        _skv("scan_summary", _summary)
        # keep the last 24 cycles so «چرا این سیکل پیام نداد» is always
        # answerable from the DB after the fact, not just for the newest one
        _hist = _gkv("scan_history", []) or []
        _hist.append(_summary)
        _skv("scan_history", _hist[-24:])
    except Exception:
        pass
    duration = time.monotonic() - started
    print(
        f"Discovery scan finished in {duration:.1f}s • "
        f"detected={stats['detected']} new={stats['new']} errors={stats['errors']} • "
        f"deadgate={stats.get('dead_gate', 0)} "
        f"absorbed={stats.get('chain_absorbed', 0)} quiet={stats.get('same_zone_quiet', 0)} "
        f"liccap={stats.get('chain_license_cap', 0)} sep2pct={stats.get('license_sep_block', 0)} "
        f"updthrottle={stats.get('update_throttled', 0)} "
        f"deferred={stats.get('edu_cycle_deferred', 0)}"
    )
    # Per-setup funnel (observability only): seen -> execution-ready/blocked.
    for sc in sorted(tally):
        t = tally[sc]
        blocked = ",".join(f"{g}:{n}" for g, n in sorted(t["blocked"].items())) or "-"
        print(
            f"  funnel {sc:8s} seen={t['seen']} ready_new={t['ready_new']} "
            f"dead_gate={t['dead_gate']}[{blocked}] low_score={t['low_score']} "
            f"dup={t['dup']} suppressed_preTp1={t['suppressed_pre_tp1']}"
        )
    try:
        import analysis.setups_experimental as _exp
        pol = _exp.drain_polarity_rejects()
        if pol:
            print("  polarity-rejects: " + ", ".join(f"{k}:{n}" for k, n in sorted(pol.items())))
        rec = _exp.drain_polarity_recovers()
        if rec:
            print("  polarity-recovers: " + ", ".join(f"{k}:{n}" for k, n in sorted(rec.items())))
    except Exception as _e:
        print(f"polarity-rejects diagnostic unavailable: {_e}")
    return stats


def _pinv_window_expired(candidate: SignalCandidate, closed: Optional[pd.DataFrame]) -> bool:
    """Count only closed bars of the pin trigger timeframe after alert creation."""
    if closed is None or closed.empty:
        return is_expired(candidate)
    md = candidate.metadata or {}
    tf = str(md.get("pin_tf") or candidate.trigger_timeframe)
    # Viva 2026-09-14: «روزانه است، ۱۵ دقیقه که نیست» — verdict windows count
    # candles of the pin's OWN timeframe; 4h/1d fell back to 5m before this.
    seconds = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600,
               "4h": 14400, "1d": 86400}.get(tf, 300)
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


_TF_SECONDS_LIVE = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
_TF_FA_LIVE = {"5m": "۵دقیقه‌ای", "15m": "۱۵دقیقه‌ای", "30m": "۳۰دقیقه‌ای",
               "1h": "یک‌ساعته", "4h": "۴ساعته", "1d": "روزانه"}


def _watch_edge_at(candidate, ts) -> float:
    """Value of the candidate's reference line AT TIME ts: the fitted
    trend/channel line when the detector stored its two defining points, the
    static breakout edge otherwise, the zone edge as a last resort."""
    md = candidate.metadata or {}
    try:
        _la = pd.Timestamp(str(md["tl_a_ts"])).tz_localize(None)
        _lb = pd.Timestamp(str(md["tl_b_ts"])).tz_localize(None)
        _pa, _pb = float(md["tl_a_price"]), float(md["tl_b_price"])
        _dt = (_lb - _la).total_seconds()
        if _dt:
            _frac = (pd.Timestamp(ts).tz_localize(None) - _la).total_seconds() / _dt
            return float(_pa + (_pb - _pa) * _frac)
    except Exception:
        pass
    for _k in ("viva_breakout_line", "viva_break_line", "viva_watch_line"):
        try:
            _v = float(md.get(_k) or 0.0)
        except Exception:
            _v = 0.0
        if _v > 0:
            return _v
    return float(candidate.entry_zone_top if candidate.direction == "LONG"
                 else candidate.entry_zone_bottom)


def _live_break_watch(candidate, live_frame) -> Tuple[str, str]:
    """Viva 2026-09-14: an open pattern candle that has already thrust beyond
    the daily/wedge/triangle/channel side is REPORTED NOW, with the live chart
    and the countdown to its close («نباید بگوید فردا در کلوز خبر می‌دهم»).
    One alert per candle; if price falls back inside the flag resets so a
    fresh thrust can speak again. The close still owns confirmation.
    Returns (note, dedup_key); the caller persists dedup_key ONLY after a
    successful Telegram send (HOT-4)."""
    md = candidate.metadata or {}
    tf = str(candidate.trigger_timeframe or "")
    secs = _TF_SECONDS_LIVE.get(tf, 3600)
    if live_frame is None or getattr(live_frame, "empty", True) or len(live_frame) < 3:
        return "", ""
    _row = live_frame.iloc[-1]
    try:
        _ts = pd.Timestamp(_row["timestamp"] if "timestamp" in live_frame.columns
                           else live_frame.index[-1])
    except Exception:
        return "", ""
    now = pd.Timestamp.utcnow().tz_localize(None)
    if (now - _ts).total_seconds() > secs:
        return "", ""        # newest row is already a closed candle; close owns it
    atr = float(md.get("atr") or 0.0) or float(
        (live_frame["high"] - live_frame["low"]).tail(14).mean() or 0.0)
    if atr <= 0:
        return "", ""
    edge = _watch_edge_at(candidate, _ts)
    px = float(_row["close"])
    beyond = px >= edge + 0.05 * atr if candidate.direction == "LONG"         else px <= edge - 0.05 * atr
    _key = _ts.isoformat()
    if not beyond:
        if md.get("live_break_bar"):
            md.pop("live_break_bar", None)
            candidate.metadata = md
            try:
                update_candidate(candidate)
            except Exception:
                pass
        return "", ""
    if str(md.get("live_break_bar") or "") == _key:
        return "", ""
    # HOT-4 (audit 09-15): the dedup marker is persisted by the CALLER only
    # after the Telegram send succeeded — a failed send must never eat the
    # one-and-only ⚡ alert of this pattern candle.
    rem_min = max(1, int((_ts.timestamp() + secs - now.timestamp()) // 60))
    side = "بالای" if candidate.direction == "LONG" else "زیرِ"
    return ((f"⚡ عبورِ {side}ِ خط/لبه در لحظه — کندلِ {_TF_FA_LIVE.get(tf, tf)} هنوز باز است "
             f"و حدود {rem_min} دقیقه تا کلوزِ آن باقی مانده (قیمت {px:g} در برابر مرجع {edge:.6g}). "
             "با کلوزِ معتبر، قانونِ یک‌کلوز تأیید می‌کند؛ بازگشت تا پیش از کلوز نقض است."), _key)


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

            # ── live-break watch (Viva 2026-09-14) — report the crossing the
            # moment the OPEN pattern candle thrusts beyond the line/edge.
            if not candidate.metadata.get("technical_confirmation_complete"):
                try:
                    _pat_frames = frames.get((candidate.symbol, str(candidate.trigger_timeframe or "")))
                    _live_note, _lb_key = _live_break_watch(candidate, (_pat_frames or (None, None, None))[0])
                    if _live_note and send_setup_update(
                            candidate, (_pat_frames or (None, None, None))[0],
                            note_fa=_live_note, critical=True):
                        stats["live_break"] = stats.get("live_break", 0) + 1
                        _md = candidate.metadata or {}
                        _md["live_break_bar"] = _lb_key
                        candidate.metadata = _md
                        try:
                            update_candidate(candidate)
                        except Exception:
                            pass
                except Exception as _lb_exc:
                    print(f"live-break watch {candidate.symbol}: {_lb_exc}")

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
                _pat_frame = None
                try:
                    _cf = str(candidate.metadata.get("confirm_tf") or "")
                    _trg = str(candidate.trigger_timeframe or "")
                    if _cf and _cf != _trg:
                        # Viva 2026-09-13: a pattern-timeframe close breaking the
                        # line/wedge/triangle side confirms too — hand that frame
                        # to the evaluator instead of watching only the confirm TF.
                        _pat_frame = (frames.get((candidate.symbol, _trg)) or (None, None, None))[1]
                except Exception:
                    _pat_frame = None
                confirmed, candidate, reason = evaluate_confirmation(candidate, closed, htf_closed_df=_pat_frame)

            if not confirmed:
                code = str(candidate.metadata.get("last_reject_code") or "UNKNOWN")
                stats["rejects"] = stats.get("rejects", {})
                stats["rejects"][code] = int(stats["rejects"].get(code, 0)) + 1
                # ── per-pattern-candle heartbeat (Viva 2026-09-14): «۱ ساعته هر یک ساعت،
                # ۴ ساعته هر ۴ ساعت، روزانه هر روز — تا پایانِ تأیید یا عدم‌تأیید».
                # Every closed candle of the pattern timeframe produces exactly ONE
                # status update on the chain's live slot while unresolved.
                try:
                    _trg = str(candidate.trigger_timeframe or "")
                    if _trg in ("1h", "4h", "1d") and not publication_in_progress:
                        _pat = frames.get((candidate.symbol, _trg)) or (None, None, None)
                        _pfr = _pat[1]
                        if _pfr is not None and not _pfr.empty:
                            _last = pd.Timestamp(_pfr["timestamp"].iloc[-1]
                                                 if "timestamp" in _pfr.columns
                                                 else _pfr.index[-1])
                            _bts = _last.isoformat()[:16]
                            if str(candidate.metadata.get("hb_bar") or "") != _bts:
                                _dur = _TF_SECONDS_LIVE.get(_trg, 3600)
                                _rem = max(1, int((_last.timestamp() + 2 * _dur
                                                    - pd.Timestamp.utcnow().tz_localize(None).timestamp()) // 60))
                                _hb_note = (f"🕐 گزارشِ پایانِ کندلِ {_TF_FA_LIVE.get(_trg, _trg)} — این کندل بسته شد "
                                            f"و کلوزِ معتبرِ فراتر از لبه هنوز در کارنامه نیست؛ "
                                            f"کندلِ بعدی حدود {_rem} دقیقهٔ دیگر کلوز می‌دهد. زنجیره زنده و زیر نظر است.")
                                if send_setup_update(candidate, _pat[0], note_fa=_hb_note):
                                    stats["heartbeat"] = stats.get("heartbeat", 0) + 1
                                    # HOT-4 (audit 09-15): the once-per-candle
                                    # marker is set ONLY after a successful send;
                                    # a failed/throttled send retries next cycle
                                    # instead of losing this candle's heartbeat.
                                    candidate.metadata["hb_bar"] = _bts
                                    try:
                                        update_candidate(candidate)
                                    except Exception:
                                        pass
                except Exception as _hb_exc:
                    print(f"heartbeat watch {candidate.symbol}: {_hb_exc}")
            if confirmed:
                # Viva 2026-09-11: five identical SOL confirmations on the same
                # trigger were USELESS. A new confirmed signal must bring NEW
                # points; an (almost) identical re-fire is cancelled silently.
                try:
                    from database.repository_v7 import recent_geometry_duplicate
                    if not candidate.metadata.get("persistence_staged") and recent_geometry_duplicate(
                            candidate.symbol, candidate.direction,
                            candidate.planned_entry or candidate.entry_zone_bottom,
                            candidate.sl, candidate.tp1):
                        stats["suppressed_geo_dup"] = stats.get("suppressed_geo_dup", 0) + 1
                        # HOT-2 (audit 09-15): `_t()` only exists inside
                        # run_discovery_scan; the NameError here killed the
                        # gate silently and the duplicate got published anyway.
                        candidate.status = "CANCELLED"
                        candidate.metadata["geo_dup_cancelled"] = True
                        candidate.metadata["cancel_note_fa"] = (
                            "نقاط این سیگنال با سیگنالِ تأییدشدهِ ۲۴ ساعتِ اخیرِ همین نماد "
                            "تقریباً یکسان بود؛ تا تشکیلِ ناحیه‌ی جدید (نقاطِ تازه) منتشر نمی‌شود")
                        update_candidate(candidate)
                        continue
                except RuntimeError as exc:
                    print(f"geometry-dup gate skipped {candidate.signal_id}: {exc}")
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
                            if candidate.metadata.get("confirmation_chart_message_id"):
                                confirmed_mid = record_telegram_event(
                                    candidate.signal_id, "CONFIRMED",
                                    str(CHAT_ID_EXECUTION or ""),
                                    int(candidate.metadata["confirmation_chart_message_id"]),
                                )
                                # Keep legacy column as a same-signal fallback;
                                # canonical linking is the immutable receipt above.
                                set_pro_message_id(candidate.signal_id, confirmed_mid or int(candidate.metadata["confirmation_chart_message_id"]))
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


_EXECUTION_PUBLISH_LOCK = threading.Lock()
_CANDIDATE_MONITOR_LOCK = threading.Lock()


def _publish_trade_events(events) -> int:
    """Serialize lifecycle publication so ticker and candle monitors cannot race."""
    for event in events:
        kind = str(event.get("event") or "")
        if kind.startswith("TP"):
            pro_tp_mid = send_ladder_event(event)
            if pro_tp_mid:
                canonical_mid = record_telegram_event(
                    event["signal_id"], str(event.get("event") or "TP"),
                    str(CHAT_ID_EXECUTION or ""), int(pro_tp_mid),
                )
                # Use the stored first receipt, not the last same-symbol post.
                event["pro_event_message_id"] = canonical_mid or int(pro_tp_mid)
                set_last_tp_message_id(event["signal_id"], event["pro_event_message_id"])
                if event.get("event") == "TP1":
                    set_first_tp_message_id(event["signal_id"], event["pro_event_message_id"])
                    event["first_tp_message_id"] = event["pro_event_message_id"]
            res_mid = send_tp1_event(event)  # Win Rate mirror, links to this TP receipt
            if res_mid and pro_tp_mid:
                # Viva 2026-09-14: main ↔ win-rate link is TWO-WAY via the
                # unique code so the chain walks from either channel.
                attach_results_link(int(pro_tp_mid), int(res_mid))
        elif kind in {"TRAIL_STOP", "STOP"}:
            lifecycle_mid = send_ladder_event(event)
            if lifecycle_mid:
                # Keep the protected-exit/stop receipt attached to this exact
                # position too. Final WIN anchors to the last TP reached; the
                # final result now anchors to the STOP-HIT message itself and
                # the stop receipt is mirrored into the win-rate channel,
                # two-way linked (link-chain law).
                record_telegram_event(
                    event["signal_id"], kind,
                    str(CHAT_ID_EXECUTION or ""), int(lifecycle_mid),
                )
                res_mid = send_stop_event_to_results(event, int(lifecycle_mid))
                if res_mid:
                    attach_results_link(int(lifecycle_mid), int(res_mid))
        elif kind == "NO_FILL":
            send_no_fill_event(event)
        elif kind == "CLOSED":
            close_mid = send_trade_close_event(event)
            res_mid = send_trade_result(event)
            if close_mid and res_mid:
                attach_results_link(int(close_mid), int(res_mid))
    return len(events)


def monitor_confirmed_results() -> int:
    with _EXECUTION_PUBLISH_LOCK:
        return _publish_trade_events(monitor_confirmed_trades())


def run_realtime_execution_cycle() -> int:
    """Fresh ticker path: TP/SL messages must not wait for trigger candle close."""
    try:
        from data.ourbit import get_ourbit_tickers
        from data.fetcher import get_tickers
        from database.realtime_monitor import monitor_realtime_prices
        prices = {}
        try:
            for row in get_ourbit_tickers(use_cache=False):
                if float(row.get("last_price") or 0) > 0:
                    prices[str(row.get("symbol") or "").upper()] = float(row["last_price"])
        except Exception as exc:
            print(f"Realtime Ourbit ticker warning: {exc}")
        if not prices:
            for row in get_tickers(use_cache=False):
                if float(row.get("lastPrice") or 0) > 0:
                    prices[str(row.get("symbol") or "").upper()] = float(row["lastPrice"])
        if not prices:
            return 0
        with _EXECUTION_PUBLISH_LOCK:
            events = monitor_realtime_prices(prices)
            return _publish_trade_events(events)
    except Exception as exc:
        print(f"Realtime execution monitor error: {exc}")
        return 0


def run_monitor_cycle() -> None:
    try:
        trade_events = monitor_confirmed_results()
    except Exception as exc:
        print(f"Confirmed trade monitor error: {exc}")
        trade_events = 0
    try:
        with _CANDIDATE_MONITOR_LOCK:
            stats = monitor_candidates()
        if stats["active"] or trade_events:
            print(
                f"Monitor • candidates={stats['active']} approaching={stats['approaching']} "
                f"confirmed={stats['confirmed']} cancelled={stats['cancelled']} trade_events={trade_events} "
                f"rejects={stats.get('rejects', {})}"
            )
        try:  # Viva 2026-09-14: live proof of the watch/heartbeat machine
            from datetime import timezone as _tz
            from database.bot_kv import set_json as _skv
            _skv("monitor_summary", {
                "when": datetime.now(_tz.utc).isoformat(timespec="seconds"),
                "active": int(stats.get("active", 0)),
                "live_break": int(stats.get("live_break", 0)),
                "heartbeat": int(stats.get("heartbeat", 0)),
                "confirmed": int(stats.get("confirmed", 0)),
                "cancelled": int(stats.get("cancelled", 0)),
                "rejects": stats.get("rejects", {}),
            })
        except Exception:
            pass
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


def _realtime_execution_loop() -> None:
    """Independent daemon so lengthy discovery scans cannot delay exits."""
    interval = max(2, int(SETTINGS.realtime_execution_seconds))
    while not _SHUTDOWN:
        started = time.monotonic()
        run_realtime_execution_cycle()
        time.sleep(max(0.2, interval - (time.monotonic() - started)))


def _candidate_monitor_loop() -> None:
    """Confirmation/final-watch monitor independent of long discovery scans."""
    interval = max(5, int(SETTINGS.candidate_monitor_seconds))
    while not _SHUTDOWN:
        started = time.monotonic()
        try:
            with _CANDIDATE_MONITOR_LOCK:
                monitor_candidates()
        except Exception as exc:
            print(f"Realtime candidate monitor error: {exc}")
        time.sleep(max(0.5, interval - (time.monotonic() - started)))


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
    # Viva 2026-09-11: deploy heartbeat — the DB becomes proof-of-life, so we
    # never have to guess whether the NEW build is actually running.
    try:
        from database.bot_kv import set_json as _boot_set
        # Viva 2026-09-14: no more hand-edited build strings — the truth is the
        # stamped commit (BUILD_INFO, committed one ref behind by design) plus
        # the Railway APP_VERSION env. If either is stale, it is stale visibly.
        _bi = "local"
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "BUILD_INFO")) as _bif:
                _bi = _bif.read().strip()[:40]
        except Exception:
            _bi = os.getenv("COMMIT_SHA", "local")[:12]
        _boot_set("boot_version", {
            "sha": _bi,
            "build": os.getenv("APP_VERSION", "dev"),
            "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    except Exception as _boot_exc:
        print(f"boot_version heartbeat skipped: {_boot_exc}")
    try:
        repaired = repair_legacy_tp1_misclassified_results()
        print(f"🔎 Legacy protected-exit audit: repaired={repaired}")
    except Exception as exc:
        print(f"Legacy TP1 repair skipped: {exc}")
    symbols, _ = UNIVERSE.get()
    if SETTINGS.startup_message_enabled:
        send_startup_message(len(symbols))
    try:
        start_command_listener()
        print("🤖 Telegram command listener active")
    except Exception as exc:
        print(f"Command listener error: {exc}")

    threading.Thread(target=_realtime_execution_loop, name="viva-realtime-execution", daemon=True).start()
    threading.Thread(target=_candidate_monitor_loop, name="viva-candidate-monitor", daemon=True).start()
    print(f"⚡ Realtime execution monitor active • every {SETTINGS.realtime_execution_seconds}s")
    print(f"⚡ Candidate monitor active • every {SETTINGS.candidate_monitor_seconds}s")

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
    last_weekly_digest = ""
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
        # PROP-3 (Viva 09-16): Friday 19:00 Tehran — one chic per-setup
        # results digest into the results + journal channels.
        teh_now = datetime.now(timezone(timedelta(hours=3, minutes=30)))
        _iso = teh_now.isocalendar()
        week_key = f"{_iso[0]}-W{_iso[1]:02d}"
        if (teh_now.weekday() == 4 and teh_now.hour == 19 and teh_now.minute < 2
                and week_key != last_weekly_digest):
            try:
                from bot.messages_v7 import send_weekly_results_digest
                send_weekly_results_digest()
            except Exception as exc:
                print(f"Weekly digest error: {exc}")
            last_weekly_digest = week_key
        time.sleep(5)
    print("Viva Signal Bot stopped cleanly")


if __name__ == "__main__":
    main()
