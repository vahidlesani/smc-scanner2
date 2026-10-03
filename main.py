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
    send_reentry_note,
    send_trailing_note,
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
    expiry_hours = expiry_hours_for(candidate.style, candidate.trigger_timeframe)
    return _kv_alerted(key, expiry_hours)


_SUPPRESSED_EDU_ALERTED: Dict[str, float] = {}


def _suppressed_edu_throttled(candidate) -> bool:
    """Viva 2026-09-11: a pre-TP1 capacity block must never swallow the FIRST
    detailed alert — the compact anchor still goes to the alerts channel,
    throttled per setup identity so 5-min rescans cannot spam it."""
    key = (f"{candidate.symbol}:{candidate.style}:{candidate.setup_code}:{candidate.direction}:"
           f"{round(float(candidate.entry_zone_bottom), 6)}")
    from analysis.setups_v7 import expiry_hours_for
    expiry_hours = expiry_hours_for(candidate.style, candidate.trigger_timeframe)
    return _kv_alerted("sup:" + key, expiry_hours)


_QUIET_RUN = 0

# Structural quality lanes are exempt from the generic PinWall-oriented
# unresolved-chain / same-zone / 24h licence suppression. Their own detector
# geometry, score, sanity and duplicate checks remain active.
_STRUCTURAL_QUALITY_LANES = frozenset({"ALBROX", "TLBREAK", "TECHCLASSIC"})


# ── Round-15 cost guard (Viva 09-21: «ببین استفاده الکی نداشته باشیم»).
# A symbol whose four detection timeframes produced no new CLOSED candle cannot
# yield a new detection — re-analysing it every 5 minutes was pure waste. The
# guard keeps a 15-minute freshness window so a budget-deferred scenario is
# still retried, and it never skips a symbol that has an open chain.
_LAST_CLOSED_STAMPS: Dict[str, tuple] = {}
_LAST_FULL_SCAN_AT: Dict[str, float] = {}
_UNCHANGED_RETRY_SECONDS = 900


def _closed_stamp(bundle) -> tuple:
    out = []
    for tf in ("15m", "30m", "1h", "2h", "4h", "1d"):
        try:
            df = bundle.get(tf)
            out.append(str(df["timestamp"].iloc[-1]) if df is not None and len(df) else "-")
        except Exception:
            out.append("?")
    return tuple(out)


def _symbol_may_skip(symbol: str, bundle, open_symbols: set) -> bool:
    """True when this symbol has no new closed candle and no open chain."""
    try:
        stamp = _closed_stamp(bundle)
        prev = _LAST_CLOSED_STAMPS.get(symbol)
        _LAST_CLOSED_STAMPS[symbol] = stamp
        if prev is None or prev != stamp:
            return False
        if symbol in open_symbols:
            return False
        return (time.monotonic() - _LAST_FULL_SCAN_AT.get(symbol, 0.0)) < _UNCHANGED_RETRY_SECONDS
    except Exception:
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
    _open_syms: set = set()
    try:
        for _c in get_active_candidates():
            _open_syms.add(_c.symbol)
    except Exception:
        pass
    # Viva 2026-09-11 («یهو ۱۰۰۰ تا هشدار میاد»): one scan cycle may open only a
    # bounded number of NEW detailed alerts; everything beyond that defers to
    # the next scan instead of flooding the channels in a single burst.
    _edu_budget = {"left": max(1, int(getattr(SETTINGS, "education_max_per_scan", 8) or 8))}
    # Viva 09-17 seesaw fix: WATCH/previews live on a SEPARATE small budget —
    # a flood of two-pivot watches can never starve pins/other families again.
    _watch_budget = {"left": 4}
    # R63 (audit W3): the 8-alert cycle budget was FIRST-COME across all
    # setups — the symbol loop order let one noisy family (zones/pins on the
    # first symbols) eat the whole budget and defer time-critical pattern
    # BREAKS to the next cycle (a late break alert = a chased entry). Each
    # setup now has its own share of the cycle, and the break lanes keep a
    # small reserve on top of the shared pool.
    _per_setup_cap = max(2, int(getattr(SETTINGS, "education_max_per_setup_per_scan", 4) or 4))
    _setup_used: Dict[str, int] = {}
    _break_reserve = {"left": 2}
    _BREAK_LANES63 = {"TECHCLASSIC", "ALBROX", "TLBREAK"}

    def _budget_ok(cand) -> bool:
        _sc = str(getattr(cand, "setup_code", "") or "").upper()
        if _setup_used.get(_sc, 0) >= _per_setup_cap:
            return False
        if _edu_budget["left"] > 0:
            return True
        return _sc in _BREAK_LANES63 and _break_reserve["left"] > 0

    def _educate(cand, frame):
        _md9 = getattr(cand, "metadata", None) or {}
        _is_watch = str(_md9.get("viva_state") or "").upper().startswith("S0_WATCH")
        _sc9 = str(getattr(cand, "setup_code", "") or "").upper()
        if not _is_watch and not _budget_ok(cand):
            stats["edu_cycle_deferred"] = stats.get("edu_cycle_deferred", 0) + 1
            return False
        _b9 = _watch_budget if _is_watch else _edu_budget
        if _is_watch and _b9["left"] <= 0:
            stats["edu_cycle_deferred"] = stats.get("edu_cycle_deferred", 0) + 1
            return False
        if not _is_watch:
            _setup_used[_sc9] = _setup_used.get(_sc9, 0) + 1
            if _edu_budget["left"] <= 0:
                _b9 = _break_reserve
        _b9["left"] -= 1
        # ── r60.2 send-idempotency (his duplicate-post reports: INJ×2, OKB×2,
        # LINK 1d×2, ALGO PINVAL K795612×2 within one minute): two lanes can
        # carry the SAME candidate id (main scan + pinned mini-pass) and each
        # posts its own message. ONE Telegram post per signal id, ever — the
        # guard is set only AFTER a successful send, so budget-deferred
        # candidates still retry on the next pass.
        _post_key = ""
        try:
            from database.bot_kv import get_json as _gj60
            import time as _t60
            _post_key = f"posted|{str(getattr(cand, 'signal_id', '') or '')}"
            _prev = _gj60(_post_key, {}) or {}
            if float(_prev.get("ts") or 0) > _t60.time() - 36 * 3600:
                stats["dup_send_blocked"] = stats.get("dup_send_blocked", 0) + 1
                return True   # already posted — treat as success, no second post
        except Exception:
            _post_key = ""
        _sent = send_educational_setup(cand, frame)
        if _sent and _post_key:
            try:
                from database.bot_kv import set_json as _sj60
                _sj60(_post_key, {"ts": _t60.time()})
            except Exception:
                pass
        return _sent
    # Observability only (no behaviour change): tally where each raw detector
    # candidate goes, per setup, so "0 confirmed" is diagnosable from logs.
    tally = {}

    def _t(cand):
        sc = str(getattr(cand, "setup_code", "?") or "?")
        return tally.setdefault(sc, {
            "seen": 0, "low_score": 0, "dead_gate": 0, "blocked": {},
            "suppressed_pre_tp1": 0, "dup": 0, "ready_new": 0,
            "absorbed": 0, "license_cap": 0, "same_zone_quiet": 0, "sep2pct": 0,
            "budget_deferred": 0, "add_failed": 0, "educate_failed": 0, "chain_slot": 0,
        })
    print(
        f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC] "
        f"Discovery scan started for {len(symbols)} dynamic symbols"
    )
    for index, symbol in enumerate(symbols, start=1):
        if _SHUTDOWN:
            break
        try:
            # r48 (Viva 09-27): the futures discovery bundle carries the two
            # NEW trigger frames (30m, 2h) — derived locally, zero extra calls.
            bundle = get_market_bundle(
                symbol, ("1d", "4h", "2h", "1h", "30m", "15m", "5m"),
                ticker=metrics.get(symbol, {}))
            # ── Round-15: no new closed candle on any detection timeframe and no
            # open chain on this symbol ⇒ nothing can be detected that the last
            # pass did not already see. (Guarded, fail-open, 15-min window.)
            if _symbol_may_skip(symbol, bundle, _open_syms):
                stats["skipped_unchanged"] = stats.get("skipped_unchanged", 0) + 1
                if index % 10 == 0:
                    print(f"  scanned {index}/{len(symbols)} • new educational setups: {stats['new']}")
                continue
            _LAST_FULL_SCAN_AT[symbol] = time.monotonic()
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
                # r30 anti-flood: this exact scenario was cancelled/expired
                # recently — do NOT resurrect it as a «new» chain (the LTC
                # invalidate→re-find→invalidate loop flooded 113 msgs/20min).
                if _tombstone_hit(candidate):
                    _t(candidate)["dup"] += 1
                    continue
                if candidate.score < SETTINGS.educational_min_score:
                    _t(candidate)["low_score"] += 1
                    continue
                # ── Viva 09-23: the mobile-app CONTROL gate (master pause +
                # per-setup switches from bot_kv['webapp_control']). Fail-open:
                # if the app/KV is unreachable the scanner publishes as before.
                try:
                    from webapp_viva import publish_allowed
                    if not publish_allowed(candidate):
                        stats["gated"] = stats.get("gated", 0) + 1
                        continue
                except Exception:
                    pass
                # Reserve before *any* public alert. A display code is a real
                # position identity, not a random label that may later change.
                # r32: publish-time score snapshot — the chart info box of
                # lifecycle/legacy renders reads this when the row score is 0.
                try:
                    candidate.metadata["publish_score"] = int(candidate.score or 0)
                except Exception:
                    pass
                try:
                    reserve_public_code(candidate)
                except Exception as exc:
                    stats["errors"] += 1
                    print(f"Public-code reservation failed {candidate.signal_id}: {exc}")
                    continue  # fail closed; never publish an unreserved code
                _quality_lane = str(getattr(candidate, "setup_code", "") or "").upper() in _STRUCTURAL_QUALITY_LANES
                # ── Viva licence law (restated 2026-09-13, verbatim) ──────────
                # 3 rotating licences per (symbol, trigger timeframe, setup).
                # The next licence frees when the previous signal CONFIRMS;
                # while one chain is unresolved, a new detection on the same
                # tuple is absorbed into it. Different setup or different
                # trigger timeframe = fully independent. A new licence also
                # needs >=2% price distance from the last CONFIRMED price.
                if SETTINGS.chain_slot_gate_enabled and not _quality_lane:
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
                        t["chain_slot"] = t.get("chain_slot", 0) + 1
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
                        _t(candidate)["license_cap"] = _t(candidate).get("license_cap", 0) + 1
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
                        _t(candidate)["same_zone_quiet"] = _t(candidate).get("same_zone_quiet", 0) + 1
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
                # R62-ARENA (audit W1): the budget is checked BEFORE the prior
                # lineage is superseded — a deferred replacement used to delete
                # the live chain's posts and then never publish its successor.
                _is_watch62 = str((candidate.metadata or {}).get("viva_state") or "").upper().startswith("S0_WATCH")
                if (not _is_watch62 and not _budget_ok(candidate)) or (_is_watch62 and _watch_budget["left"] <= 0):
                    stats["edu_cycle_deferred"] = stats.get("edu_cycle_deferred", 0) + 1
                    _t(candidate)["budget_deferred"] = _t(candidate).get("budget_deferred", 0) + 1
                    continue  # not persisted; next scan retries when budget frees
                for prior in supersede_alert_lineage(candidate):
                    try:
                        release_symbol_lock(prior.symbol, prior.signal_id)
                    except Exception:
                        pass
                    purge_candidate_alert_posts(prior)
                    purge_pro_watch_post(prior)
                # Live alerts replace themselves on meaningful new information;
                # symbol locks would hide those updates, so discovery has no lock.
                if not add_candidate(candidate):
                    _t(candidate)["add_failed"] = _t(candidate).get("add_failed", 0) + 1
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
                    _t(candidate)["educate_failed"] = _t(candidate).get("educate_failed", 0) + 1
                    # R62-ARENA (audit W2): a stored row whose alert never
                    # posted is a GHOST chain (monitored, confirmable, with no
                    # message to reply to). Retire it so the next scan re-mints.
                    try:
                        from database.candidate_store import set_status as _set_st62
                        _set_st62(candidate.signal_id, "UNPOSTED")
                    except Exception as _gh_exc:
                        print(f"ghost-chain retire failed {candidate.signal_id}: {_gh_exc}")
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
    # Viva 09-17 silence pulse: four consecutive empty scans (or any error)
    # prints ONE diagnostic line to the results chat so «چرا پیام نیامد» is
    # answerable from the channel itself, with the exact gate counters.
    global _QUIET_RUN
    if stats.get("detected", 0) == 0 and stats.get("new", 0) == 0:
        _QUIET_RUN += 1
    else:
        _QUIET_RUN = 0
    if _QUIET_RUN >= 4 or stats.get("errors", 0) > 0:
        try:
            from bot.messages_v7 import send_message as _sm9, CHAT_ID_RESULTS, CHAT_ID_ADMIN
            _t9 = tally or {}
            _seen9 = sum(t["seen"] for t in _t9.values())
            _low9 = sum(t["low_score"] for t in _t9.values())
            _sm9(
                f"🩺 پالس اسکن • {len(symbols)} نماد • seen={_seen9} • "
                f"absorbed={stats.get('chain_absorbed', 0)} • "
                f"liccap={stats.get('chain_license_cap', 0)} • "
                f"quiet={stats.get('same_zone_quiet', 0)} • "
                f"low_score={_low9} • errors={stats.get('errors', 0)} • "
                f"پیام نیامد چون هیچ ستاپی از گیت‌ها عبور نکرد",
                CHAT_ID_RESULTS or CHAT_ID_ADMIN,
            )
            _QUIET_RUN = 0
        except Exception as _p9:
            print(f"scan pulse skipped: {_p9}")
    try:
        from analysis import onchain_free as _oc2
        _ctx_line = _oc2.context_line_fa()
        if _ctx_line:
            print(f"Flow context (context only, never a gate): {_ctx_line}")
            stats["flow_context"] = _ctx_line
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
            f"dup={t['dup']} absorbed={t.get('absorbed',0)} quiet={t.get('same_zone_quiet',0)} "
            f"liccap={t.get('license_cap',0)} sep2={t.get('sep2pct',0)} preTp1={t['suppressed_pre_tp1']} "
            f"budget={t.get('budget_deferred',0)} addfail={t.get('add_failed',0)} edufail={t.get('educate_failed',0)}"
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


# ── SPOT lane (round 15, phase 5) ─────────────────────────────────────────
# Viva 09-22: «هیچی از اسپات نگفتی، آماده است؟» + he handed over VIVA-MON-SPOT.
# The lane runs the SPOT engine (LONG only · bullish shapes only · TLBREAK +
# TECHCLASSIC · 4h/1d/3d/1w · LOG-scale chart · green measured box) on the same
# liquidity watchlist, one full pass per hour, and publishes ONLY fully-formed
# signals — NO daily budget (Viva 09-28, r56: «محدودیت اسپات نداریم … هر وقت
# موقعیت بود بیام بده»): a symbol may break an important pattern/trend area in
# SEVERAL timeframes the same day and every one of them is delivered. The only
# anti-spam layer is the per (symbol, tf, shape) stamp window.
def _spot_enabled() -> bool:
    return str(os.getenv("SPOT_ENGINE_ENABLED", "1")).strip().lower() in {"1", "true", "on", "yes"}


def _spot_stamp(key: str, window_hours: float, commit: bool = True) -> bool:
    """True when this exact spot signal was already published inside the window.

    r29 (Viva 09-25, «موتور اسپات از ۲ روز قبل هیچ فعالیتی نداره»): the old
    call STAMPED BEFORE the send, so one failed chart/Telegram attempt burned
    that (symbol, tf, shape) for the whole dedupe window — with sends failing
    the lane went silent while `found` kept counting. The check is now
    read-only (commit=False); the marker is written ONLY after a successful
    publish."""
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        now = time.time()
        data = {k: float(v) for k, v in (_g("spot_published", {}) or {}).items()
                if now - float(v) < 24 * 3600 * max(1.0, float(window_hours) / 24.0)}
        if key in data:
            return True
        if commit:
            data[key] = now
            _s("spot_published", data)
        return False
    except Exception:
        return False


def _spot_status_write(reason: str, stats: Optional[Dict[str, int]] = None) -> None:
    """Viva 09-23/24 («چرا اسپات رو فعال نمیکنی؟؟»): the lane's liveness is
    VISIBLE — reason + last-pass counters in KV, surfaced in the app."""
    try:
        from bot.messages_v7 import CHAT_ID_SPOT
        from database.bot_kv import set_json
        set_json("spot_lane_status", {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "enabled": _spot_enabled(), "chat_set": bool(CHAT_ID_SPOT),
            "reason": str(reason or ""), "stats": dict(stats or {}),
        })
    except Exception:
        pass


def _spot_alert_mid_kv(symbol: str, tf: str, pattern: str) -> dict:
    """The stored mid of this lane's FIRST WARNING (r57 reply-chain law)."""
    try:
        from database.bot_kv import get_json
        return get_json(f"spot_alert_mid|{str(symbol or '').upper()}|"
                        f"{str(tf or '').lower()}|{str(pattern or '').upper()}",
                        {}) or {}
    except Exception:
        return {}


def run_spot_scan() -> Dict[str, int]:
    """One full spot pass: 4h/8h short · 12h/1d mid · 3d/1w long."""
    stats: Dict[str, int] = {"symbols": 0, "found": 0, "published": 0,
                             "alerts": 0, "errors": 0}
    if not _spot_enabled():
        _spot_status_write("disabled", stats)
        return stats
    try:
        from analysis.spot_engine import spot_signals_for, SPOT_TRIGGERS
        from bot.messages_v7 import (CHAT_ID_SPOT, generate_chart,
                                     tf_channel_publish_confirmed)
        from data.fetcher import get_market_bundle
    except Exception as exc:
        print(f"spot lane import failed: {exc}")
        _spot_status_write(f"import_failed: {exc}", stats)
        return stats
    if not CHAT_ID_SPOT:
        print("spot lane idle: CHAT_ID_SPOT is not set")
        _spot_status_write("no_spot_channel", stats)
        return stats
    try:
        symbols, _metrics = UNIVERSE.get()
    except Exception:
        symbols = []
    limit = max(5, int(os.getenv("SPOT_SYMBOL_LIMIT", "24") or 24))
    # ── free flow context (fail-open, never a gate) ──────────────────────
    # The spot pass owns a small symbol budget, so it is the one lane where
    # ORDER decides what gets looked at. The first few names of the watchlist
    # keep their place (the classics never starve); the rest is ordered by 24h
    # turnover so an active tape can win a seat. Nothing here can confirm,
    # reject, delay or resize a signal — a dead API just returns today's list.
    _flow_note = ""
    try:
        from analysis import onchain_free as _oc
        _head = max(0, int(os.getenv("SPOT_FLOW_HEAD", "6") or 6))
        _ordered = _oc.order_symbols(symbols, head=_head)
        if _ordered and _ordered != list(symbols):
            _promoted = [s for s in _ordered[:limit] if s not in list(symbols)[:limit]]
            symbols = _ordered
            stats["flow_ranked"] = len(_promoted)
            if _promoted:
                _flow_note = f" · flow promoted: {', '.join(_promoted[:4])}"
        _ctx = _oc.context_line_fa()
        if _ctx:
            _flow_note = f" · {_ctx}" + _flow_note
    except Exception as _oc_exc:
        print(f"spot flow order skipped: {_oc_exc}")
    symbols = list(symbols)[:limit]
    stats["symbols"] = len(symbols)
    if _flow_note:
        print(f"Spot lane order (context only, never a gate){_flow_note}")
    started = time.monotonic()
    pending = []
    ladder = []          # round 16: TOUCH / NEAR_BREAK / BREAK_DOWN warnings
    bundles = {}         # one fetched bundle per symbol; charts reuse it
    for symbol in symbols:
        try:
            bundle = get_market_bundle(
                symbol, tuple(SPOT_TRIGGERS),
                # r50 CryptoCove counts: the chart must HAVE as many candles
                # as it renders (1w:140 needs ~985 daily bars — inside the
                # venue's 1000-bar single call, per the round-15 aggregator).
                # r52 CryptoCove counts (his dictation 09-28): 4h/8h→170,
                # 12h/1d→210, 3d→300, 1w→210 candles — the deep dailies come
                # from the one-time history store, not per-scan downloads.
                # R64 (his 10-02 «۲۵۰ تا ۳۵۰ کندل … هم اسپات»): the ONE map.
                limits=__import__("analysis.candle_counts", fromlist=["fetch_limits"]).fetch_limits())
            bundles[symbol.upper()] = bundle
            for cand in spot_signals_for(symbol, bundle):
                stats["found"] += 1
                pending.append(cand)
            # the ladder rides the SAME fetched frames — zero extra downloads
            try:
                from analysis.spot_engine import scan_spot_alerts
                _items58 = scan_spot_alerts(symbol, bundle)
                ladder.extend(_items58)
                # pin per SYMBOL|TF so the recheck scans one TF, not six
                import time as _time      # R62: `_time` was undefined → spot pins never saved
                # R65 SNAPSHOT: the ladder pins the SHAPE ITSELF (not just the
                # symbol) — the later recheck judges the geometry the alert was
                # born with, so a shifted window can never swap the drawing.
                _pin58 = {}
                for _i58 in _items58:
                    # R64.4: BREAK_DOWN pins TOO — the break already printed,
                    # that is exactly when the confirm lane must be awake. And
                    # the pin lives as long as the BREAKOUT WINDOW of its TF:
                    # the old flat 1h TTL died long before a 4h/1d/3d pattern
                    # broke, so «با بریک و کلوز بازم تایید نمیده» — the urgent
                    # lane was simply asleep at the break. (his 10-03)
                    if str(_i58.get("stage")) not in ("NEAR_BREAK", "TOUCH", "BREAK_DOWN"):
                        continue
                    _k58 = f"{symbol}|{str(_i58.get('tf') or '')}"
                    _pin58[_k58] = {
                        "ts": _time.time(), "stage": str(_i58.get("stage") or ""),
                        "shape": (_i58.get("pattern_commands") or [None])[0],
                        "level": float(_i58.get("edge") or 0.0) or None,
                        "side": str(_i58.get("side") or "")}
                if _pin58:
                    from database.bot_kv import get_json as _g58, set_json as _s58
                    _w58 = _g58("spot_urgent_watch", {}) or {}
                    _w58.update(_pin58)
                    _s58("spot_urgent_watch", _w58)
                    # R64.4: the SAME pins feed the ticker line-watch — instant
                    # touch/break alerts for every watched edge (1d/3d/1w
                    # included) with ~one ticker request per 30s TOTAL.
                    try:
                        from analysis.line_watch import upsert as _lwu
                        for _k58, _v58 in _pin58.items():
                            _sym58, _, _tf58 = _k58.partition("|")
                            if _v58.get("level"):
                                _lwu(_sym58, _tf58,
                                     level=float(_v58["level"]),
                                     side=str(_v58.get("side") or "HIGH"),
                                     stage=str(_v58.get("stage") or ""))
                    except Exception as _lw58:
                        print(f"line watch pin warning {symbol}: {_lw58}")
            except Exception as exc:
                print(f"spot ladder scan warning {symbol}: {exc}")
            # r57: MAJOR-EVENT updates only (volume surge / displacement /
            # structural touch) — «الکی آپدیت نده»
            try:
                from analysis.spot_engine import (scan_spot_update_events,
                                                  commit_spot_update_events)
                from bot.messages_v7 import send_spot_event
                _evs57 = scan_spot_update_events(symbol, bundle)
                _sent57 = []
                # ── R64.4 THE SPOT CHART ECONOMY (Viva 10-03, verbatim: «آپدیت
                #‌ها هنوز همگی با چارت لایو میان و مصرف بشدت بالا بردن») — these
                # generic vol/displacement/touch events are REPLIES, never chart
                # posts. A spot chart renders ONLY at the chain's key stages
                # (detection / touch / break / confirm / final target) inside
                # send_spot_alert + the confirm publisher. Zero renders here.
                for _ev57 in _evs57:
                    if send_spot_event(_ev57):
                        _sent57.append(_ev57)
                if _sent57:
                    commit_spot_update_events(_sent57)
                    stats["update_events"] = stats.get("update_events", 0) + len(_sent57)
            except Exception as exc:
                print(f"spot update-event warning {symbol}: {exc}")
        except Exception as exc:
            stats["errors"] += 1
            print(f"spot scan warning {symbol}: {exc}")
    # strongest path first — the daily budget only ever spends on the best
    pending.sort(key=lambda c: float(((c.metadata or {}).get("target_ladder") or {})
                                     .get("path_pct") or 0.0), reverse=True)
    for cand in pending:   # r56: no budget — every fresh (symbol,tf,shape) publishes
        key = (f"spot|{cand.symbol}|{cand.trigger_timeframe}|"
               f"{(cand.metadata or {}).get('pattern_type')}")
        window = 72.0 if str(cand.trigger_timeframe) == "3d" else 36.0
        if _spot_stamp(key, window, commit=False):
            stats["stamp_skip"] = stats.get("stamp_skip", 0) + 1
            continue
        # R65 SNAPSHOT AT DETECTION (spot): the shape/trend is frozen the
        # moment its chain is born, so the confirmation or the rejection is
        # always judged and drawn on the SAME geometry.
        try:
            from analysis.spot_engine import lock_spot_snapshot as _lss65b
            _lss65b(cand)
        except Exception:
            pass
        try:
            _bundle_for_chart = bundles.get(cand.symbol.upper())
            frame = (_bundle_for_chart.get(cand.trigger_timeframe)
                     if _bundle_for_chart is not None else None)
            chart = generate_chart(frame, cand, confirmed=True) if frame is not None else None
            if not chart:
                stats["chart_fail"] = stats.get("chart_fail", 0) + 1
                stats["last_error"] = f"chart None {cand.symbol}:{cand.trigger_timeframe}"
            if chart:
                # r57 (Viva: «آپدیتهای شکست و تایید به اولین هشدار ریپلای
                # بشه، بعدی با قبلی و همینجوری»): the spot confirm QUOTES its
                # own first ladder warning; the returned mid becomes the
                # chain head that every later spot update quotes.
                _alert_kv = _spot_alert_mid_kv(
                    cand.symbol, cand.trigger_timeframe,
                    str((cand.metadata or {}).get("pattern_type") or ""))
                _pub_mid = tf_channel_publish_confirmed(
                    cand, chart=chart, chat_override=CHAT_ID_SPOT,
                    reply_to=int(_alert_kv.get("mid") or 0))
                if _pub_mid:
                    stats["published"] += 1
                    _spot_stamp(key, window)      # marker ONLY after success
                    try:
                        from bot.messages_v7 import (_public_code as _pc57,
                                                     _spot_chain_get as _scg57,
                                                     _spot_chain_set as _scs57)
                        _code57 = _pc57(cand)
                        _chain57 = _scg57(_code57)
                        _chain57.update({"alert": int(_alert_kv.get("mid") or 0),
                                         "confirm": int(_pub_mid),
                                         "last": int(_pub_mid)})
                        _scs57(_code57, _chain57)
                    except Exception as _ch57_exc:
                        print(f"spot chain store skipped: {_ch57_exc}")
                else:
                    stats["send_fail"] = stats.get("send_fail", 0) + 1
                    stats["last_error"] = f"publish returned 0 {cand.symbol} code={str((cand.metadata or {}).get('public_code') or cand.signal_id)[:28]}"
                    # round 16: a SEND FAILURE does not close the ladder for
                    # its shape (only a real publish does, via the stamp)
            if not chart:
                # chart_fail: nothing was sent — keep the alert ladder warm
                pass
        except Exception as exc:
            stats["errors"] += 1
            stats["last_error"] = f"{type(exc).__name__}: {exc}"[:160]
            print(f"spot publish warning {cand.symbol}: {exc}")
    # ── round 16: the ladder — warnings are analysis, they never spend the
    # signal budget, but they carry their own daily cap and their own dedup.
    # Order: strongest stage first so the cap never eats a BREAK_DOWN to feed
    # a TOUCH.
    _stage_rank = {"BREAK_DOWN": 3, "NEAR_BREAK": 2, "TOUCH": 1}
    ladder.sort(key=lambda it: _stage_rank.get(str(it.get("stage") or ""), 0),
                reverse=True)
    try:
        from bot.messages_v7 import send_spot_alert as _send_spot_alert
        from analysis.spot_engine import (spot_alert_check, spot_alert_commit,
                                          build_spot_alert_candidate)
        for aitem in ladder:   # r56: no budget — cooldown stamps are the layer
            try:
                if not spot_alert_check(aitem):
                    continue
                cand = build_spot_alert_candidate(aitem)
                _bundle_for_alert = bundles.get(cand.symbol.upper())
                frame = (_bundle_for_alert.get(cand.trigger_timeframe)
                         if _bundle_for_alert is not None else None)
                chart = (generate_chart(frame, cand, confirmed=False)
                         if frame is not None else None)
                if _send_spot_alert(aitem, chart):
                    spot_alert_commit(aitem)      # marker only AFTER the send
                    stats["alerts"] = stats.get("alerts", 0) + 1
            except Exception as exc:
                stats["errors"] += 1
                print(f"spot alert warning {aitem.get('symbol')}: {exc}")
    except ImportError as exc:
        print(f"spot ladder import failed: {exc}")
    stats["dur_s"] = round(time.monotonic() - started, 1)
    if stats["found"] and not stats["published"] and not stats.get("alerts"):
        # the lane LIVES but nothing reaches the channel — make that state
        # loud in the app instead of a green «فعال» hiding a dead sender
        _spot_status_write("zero_sent", stats)
    else:
        _spot_status_write("ok", stats)
    print(f"🪙 SPOT pass finished in {stats['dur_s']}s • "
          f"symbols={stats['symbols']} found={stats['found']} "
          f"published={stats['published']} stamp_skip={stats.get('stamp_skip', 0)} "
          f"send_fail={stats.get('send_fail', 0)} chart_fail={stats.get('chart_fail', 0)} "
          f"errors={stats['errors']}")
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
        # Viva 09-17: NO candle-count limit — the verdict window ends only
        # with expiry/invalidation, whether the confirming close prints on
        # the 5th, 20th or 100th monitor candle.
        return is_expired(candidate)
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
    # R65: canonical table (30m/2h/3d were missing — a 2h pin got a 300 s
    # verdict window and the monitor mass-verdicted it before it could run).
    from analysis.candle_counts import tf_seconds as _tfsec65
    tf_seconds = _tfsec65(str(pin_tf))
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
    for _, row in after.iterrows():   # no candle cap (Viva 09-17)
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
    if is_expired(candidate):
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
_TF_MINUTES_LIVE = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60,
                    "2h": 120, "4h": 240, "1d": 1440}
_TF_FA_LIVE = {"5m": "۵دقیقه‌ای", "15m": "۱۵دقیقه‌ای", "30m": "۳۰دقیقه‌ای",
               "1h": "یک‌ساعته", "4h": "۴ساعته", "1d": "روزانه"}


def _watch_edge_at(candidate, ts) -> float:
    """Value of the candidate's reference line AT TIME ts: the fitted
    trend/channel line when the detector stored its two defining points, the
    static breakout edge otherwise, the zone edge as a last resort."""
    md = candidate.metadata or {}
    # R62-ARENA (audit W7): the ⚡ live note reads the SAME sloped edge the
    # close law and TOHOM use — one level everywhere.
    try:
        from analysis.confirm_r62 import confirm_edge_at as _r62_cea
        _v62 = float(_r62_cea(candidate, ts) or 0.0)
        if _v62 > 0 and str(md.get("confirm_edge_source") or "") != "MAJOR_TL":
            return _v62
    except Exception:
        pass
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


def _heal_zone_stop(candidate, live_price) -> bool:
    """r33 (Viva 09-26, «هنوز عدد ابطال بین ناحیه هست»): chains created before
    the r30 clamp still carry (and DISPLAY) an invalidation inside the entry
    zone. One protective repair: LONG stop below the zone floor, SHORT stop
    above the ceiling, using the standard structural buffer. Persists once."""
    try:
        zb = float(candidate.entry_zone_bottom)
        zt = float(candidate.entry_zone_top)
        sl = float(candidate.sl or 0)
        direction = str(candidate.direction or "").upper()
        if zb <= 0 or zt <= 0 or sl <= 0 or not (0 < zb < zt):
            return False
        if (candidate.metadata or {}).get("technical_confirmation_complete"):
            return False
        from analysis.trade_management import structural_buffer
        buf = structural_buffer(float(live_price or sl))
        if direction == "LONG" and sl >= zb:
            candidate.sl = round(zb - buf, 8)
        elif direction == "SHORT" and sl <= zt:
            candidate.sl = round(zt + buf, 8)
        else:
            return False
        candidate.metadata["stop_clamped"] = True
        candidate.metadata["stop_clamp_reason"] = "r33_zone_heal"
        try:
            from database.candidate_store import update_candidate as _uc33
            _uc33(candidate)
        except Exception:
            pass  # the in-memory repair still governs this pass
        print(f"🛠 zone-stop heal {candidate.symbol} {candidate.signal_id} → {candidate.sl}")
        return True
    except Exception:
        return False


def _tombstone_key(candidate) -> str:
    """r30 anti-flood tombstone: a CANCELLED/EXPIRED scenario fingerprint."""
    try:
        zm = (float(candidate.entry_zone_bottom) + float(candidate.entry_zone_top)) / 2.0
        return "canceltomb|%s|%s|%s|%.4f" % (
            candidate.symbol, candidate.setup_code, candidate.direction,
            round(zm, 6))
    except Exception:
        return ""


def _tombstone_write(candidate, hours: float = 12.0) -> None:
    key = _tombstone_key(candidate)
    if not key:
        return
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        data = _g("cancel_tombstones", {}) or {}
        data[key] = time.time()
        # prune anything older than 24h
        data = {k: v for k, v in data.items()
                if time.time() - float(v) < 24 * 3600}
        _s("cancel_tombstones", data)
    except Exception as exc:
        print(f"tombstone write skipped: {exc}")


def _tombstone_hit(candidate, hours: float = 12.0) -> bool:
    key = _tombstone_key(candidate)
    if not key:
        return False
    try:
        from database.bot_kv import get_json as _g
        data = _g("cancel_tombstones", {}) or {}
        ts = float(data.get(key) or 0)
        return ts > 0 and time.time() - ts < hours * 3600
    except Exception:
        return False


def _structural_break_edge(candidate) -> float:
    """r51 CONFIRM-TIMING LAW: the break reference of a structural chain —
    the stored breakout/trend line when the lane kept one, else the
    scenario-side zone edge (LONG breaks UP through the top, SHORT down
    through the bottom). 0.0 when the chain carries no edge at all."""
    md = candidate.metadata or {}
    try:   # R62-ARENA: the edge NOW, on its own slope (shared core)
        from analysis.confirm_r62 import confirm_edge_at as _r62_cea
        if md.get("break_line_geo"):
            _v62 = float(_r62_cea(candidate, pd.Timestamp.utcnow()) or 0.0)
            if _v62 > 0:
                return _v62
    except Exception:
        pass
    for _k51 in ("viva_breakout_line", "tl_line"):
        try:
            _v51 = float(md.get(_k51) or 0)
            if _v51 > 0:
                return _v51
        except Exception:
            pass
    try:
        _zt51 = float(candidate.entry_zone_top or 0)
        _zb51 = float(candidate.entry_zone_bottom or 0)
        if candidate.direction == "LONG" and _zt51 > 0:
            return _zt51
        if candidate.direction == "SHORT" and _zb51 > 0:
            return _zb51
    except Exception:
        pass
    return 0.0


def _scenario_out_of_reach(candidate, price) -> bool:
    """Viva 09-21 («۵۱ آپدیت از ۱۸ دلار رفته ۲۸ دلار ربات هنوز منتظر مونده؟»).

    An unconfirmed scenario whose zone is far behind the market is not
    «waiting» — its premise is gone. Distance > `scenario_out_of_reach_atr`
    (default 2.0) from the zone middle, in the scenario's own direction, closes
    the chain with a clear message instead of an hourly heartbeat for days.
    A fresh fast break (≤ fast_break_max_chase_atr) is unaffected.
    """
    try:
        if price is None:
            return False
        md = candidate.metadata or {}
        atr = float(md.get("atr") or 0) or 0.0
        if atr <= 0:
            return False
        px = float(price)
        # r30 (Viva 09-26, «موقع بریک نباید ابطال بشه — باید آپدیت و بعد
        # تأیید بیاد»): a chain the market has ALREADY TOUCHED (or broken)
        # that then ran beyond the zone in the scenario direction is a
        # breakout in progress — the 09-21 close-out was for zones the
        # market never came near, not for this. Monitor, alert the break,
        # confirm on completion; never cancel success.
        # r33 (Viva 09-26, FIL 4H T818632: live 1.018 INSIDE the 0.889-1.05
        # zone was «4.59 ATR away» → cancelled; LTC T101855 72.35 inside
        # 63.37-72.4 → cancelled): distance is measured from the NEAREST zone
        # EDGE, and a price inside the zone is NEVER out of reach — the old
        # mid-based measure murdered approaching chains and «الکی موقعیت‌ها
        # رو خراب می‌کرد». The 09-21 law only ever meant: the market walked
        # far PAST the zone and never gave the entry.
        try:
            _zb = float(candidate.entry_zone_bottom)
            _zt = float(candidate.entry_zone_top)
            if _zb <= px <= _zt:
                return False
            # r30 law kept: a TOUCHED chain that ran BEYOND the zone in the
            # scenario direction is a breakout in progress — monitor, alert,
            # confirm; never cancel success.
            _md30 = candidate.metadata or {}
            # r61.3-R62 (his LTC T739534 fury: the trend broke UP and the
            # chain was cancelled «6.56 ATR away» moments later): an
            # ESTABLISHED break (detector event or a closed close beyond the
            # edge) is a breakout in progress — R62's confirm ladder owns it
            # now; the 09-21 distance close-out never fires on success.
            try:
                from analysis.confirm_r62 import break_established as _be61
                _est61 = bool(_be61(_md30))
            except Exception:
                _est61 = False
            if _est61 or bool(_md30.get("touched")) or bool(_md30.get("live_break_bar")) \
                    or str(_md30.get("tl_stage") or "") == "JUST_BROKE":
                if candidate.direction == "LONG" and px > _zt:
                    return False
                if candidate.direction == "SHORT" and px < _zb:
                    return False
            _edge = _zt if px > _zt else _zb
            return abs(px - _edge) / atr > float(getattr(SETTINGS, "scenario_out_of_reach_atr", 2.0))
        except Exception:
            return False
    except Exception:
        return False


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
    # ── round 12: «⚡ عبورِ در لحظه» must mean a CROSSING, not a price that has
    # been far beyond the line for days (the VVV chain said «در لحظه» while the
    # price sat 12.88 ATR above the edge). The previous closed candle has to be
    # on the near side, or the price has to be within 2 ATR of the edge.
    try:
        _prev_close = float(live_frame.iloc[-2]["close"])
        if candidate.direction == "LONG":
            _crossed_now = _prev_close < edge <= px
        else:
            _crossed_now = _prev_close > edge >= px
        if not (_crossed_now or abs(px - edge) <= 2.0 * atr):
            return "", ""
    except Exception:
        pass
    # HOT-4 (audit 09-15): the dedup marker is persisted by the CALLER only
    # after the Telegram send succeeded — a failed send must never eat the
    # one-and-only ⚡ alert of this pattern candle.
    rem_min = max(1, int((_ts.timestamp() + secs - now.timestamp()) // 60))
    side = "بالای" if candidate.direction == "LONG" else "زیرِ"
    return ((f"⚡ عبورِ {side}ِ خط/لبه در لحظه — کندلِ {_TF_FA_LIVE.get(tf, tf)} هنوز باز است "
             f"و حدود {rem_min} دقیقه تا کلوزِ آن باقی مانده (قیمت {px:g} در برابر مرجع {edge:.6g}). "
             "با کلوزِ معتبر، قانونِ یک‌کلوز تأیید می‌کند؛ بازگشت تا پیش از کلوز نقض است."), _key)


def _r62_reset_stale(candidate) -> None:
    """R62-ARENA (audit C5): a stale confirmation is DISARMED, not retried.
    The chain stays alive (his 09-21 law) but the old break bar can never
    confirm again: only a later close after a First-Time-Back touch of the
    edge (FTB law, 09-29 §6) or a fresh TOHOM read may confirm it."""
    md = candidate.metadata if isinstance(candidate.metadata, dict) else {}
    bar = md.get("fast_break_bar") or md.get("tohom_confirm_bar")
    if bar:
        md["stale_after_bar"] = str(bar)[:19]
    for k in ("technical_confirmation_complete", "tl_fast_break", "fast_break_bar",
              "fast_break_close", "confirm_level_used", "tohom", "tohom_note_fa",
              "confirm_candle_pattern"):
        md.pop(k, None)
    if str(md.get("viva_state") or "").upper() == "S6_CONFIRMED":
        md["viva_state"] = "S2_BREAKOUT_CLOSED"
    if str(getattr(candidate, "status", "") or "").upper() == "CONFIRMED":
        candidate.status = "APPROACHING"
    candidate.confirmed_at = ""
    candidate.metadata = md


def _r62_tohom_attempt(candidate, current_price, stats, confirmed=False, reason=""):
    """R62-ARENA — the smart engine (TOHOM) as a continuous listener.

    Audit TH1–TH3: TOHOM used to run once per chain (a stamp set before any
    check), only inside the confirm TF's fetch window, on cached sub-frames.
    Now, for every pre-confirm chain whose live price is at/through its break
    edge, the sub-TF one step below the confirm TF (1h trigger → 5m) is
    fetched FRESH at most once per new sub-candle and judged by the dictated
    evidence (directional sub-closes, rising volume, confirming candle beyond
    the shared sloped edge). Returns (confirmed, candidate, reason).
    """
    if confirmed:
        return confirmed, candidate, reason
    try:
        md = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        if md.get("technical_confirmation_complete"):
            return confirmed, candidate, reason
        from analysis.tohom import evaluate_tohom_confirmation, tohom_frame_tf
        sub = tohom_frame_tf(candidate)
        if not sub:
            return confirmed, candidate, reason
        px = float(current_price or 0.0)
        if px > 0:
            try:
                from analysis.confirm_r62 import confirm_edge_at as _cea
                _edge = float(_cea(candidate, pd.Timestamp.utcnow()) or 0.0)
            except Exception:
                _edge = 0.0
            _atr = float(md.get("atr") or 0.0) or px * 0.01
            if _edge > 0:
                _near = (px >= _edge - 0.25 * _atr) if candidate.direction == "LONG" \
                    else (px <= _edge + 0.25 * _atr)
                if not _near:
                    return confirmed, candidate, reason     # nothing to confirm; no fetch
        # once per NEW sub-candle (Railway diet): the bar that is forming now
        _mins = float(_TF_MINUTES_LIVE.get(sub, 5) or 5)
        _bar = pd.Timestamp.utcnow().tz_localize(None).floor(pd.Timedelta(minutes=_mins))
        _bar_key = str(_bar)[:16]
        if md.get("tohom_fetch_bar") == _bar_key:
            return confirmed, candidate, reason
        md["tohom_fetch_bar"] = _bar_key
        live = get_klines(candidate.symbol, sub, 80, closed_only=False, use_cache=False)
        if live is None or len(live) < 26:
            return confirmed, candidate, reason
        closed_sub = live.iloc[:-1].reset_index(drop=True)   # forming row dropped (TH3)
        ok, candidate, why = evaluate_tohom_confirmation(candidate, closed_sub, sub_tf=sub)
        if ok:
            # the entry is the sub-close that confirmed (tool anchored there),
            # as long as it sits between the stop and TP1 of this scenario
            try:
                _c = float(candidate.metadata.get("tohom_confirm_close") or 0.0)
                _sl, _t1 = float(candidate.sl or 0.0), float(candidate.tp1 or 0.0)
                _okc = (_sl < _c < _t1) if candidate.direction == "LONG" else (_t1 < _c < _sl)
                if _c > 0 and _sl > 0 and _t1 > 0 and _okc:
                    candidate.planned_entry = _c
                    candidate.metadata["entry_source"] = "TOHOM_SUB_CLOSE"
                    candidate.metadata["fast_break_bar"] = candidate.metadata.get("tohom_confirm_bar")
                    candidate.metadata["fast_break_tf_min"] = _mins
            except Exception:
                pass
            stats["tohom_confirms"] = stats.get("tohom_confirms", 0) + 1
            print(f"⚡ TOHOM {candidate.symbol} {candidate.setup_code}: early confirm on "
                  f"{candidate.metadata.get('tohom_sub_tf')} x{candidate.metadata.get('tohom_subs')} "
                  f"vol x{candidate.metadata.get('tohom_vol_ratio')}")
            return True, candidate, why
        return confirmed, candidate, (reason or why)
    except Exception as exc:
        print(f"TOHOM check skipped {getattr(candidate, 'signal_id', '?')}: {exc}")
        return confirmed, candidate, reason


def _tf_fetch_window(tf: str) -> bool:
    """Railway cost guard (Viva 09-17), WIDENED 09-21 (round 13).

    His report, verbatim: «من هنوز سیگنال روزانه ندیدم که تأیید بشه یا واسش آپدیت
    بیاد .. ۴ ساعته هم زیاد ندیدم .. حالا دقیق بررسی کن اگر کندل‌ها فقط در تایم
    خودشون آپدیت میشن کلا ول معطل هستیم».

    The old windows were 4 minutes once per candle: a 4h chain was looked at ~6% of
    the day and a daily chain ~1% — and ANY restart inside those four minutes ate
    the whole candle (no confirmation, no update, no heartbeat, forever). Windows
    now span several 3-minute monitor cycles, so a candle close can never be missed,
    while the duty cycle stays small and the cost bounded.
    """
    now = datetime.now(timezone.utc)
    m = now.minute
    tf = str(tf or "").lower()
    if tf in ("1m", "3m", "5m"):
        return True
    if tf == "15m":
        return m % 15 < 6
    if tf == "30m":
        return m % 30 < 10
    if tf == "1h":
        return m < 12
    if tf == "2h":
        return m < 12 and now.hour % 2 == 0
    if tf == "4h":
        return m < 20 and now.hour % 4 == 0
    if tf == "1d":
        return now.hour == 0 and m < 45
    # R63 (audit W5): the spot/HTF frames used to fall through to «always» —
    # a fetch on EVERY monitor cycle for a candle that closes every 8h–1w.
    if tf == "8h":
        return m < 25 and now.hour % 8 == 0
    if tf == "12h":
        return m < 30 and now.hour % 12 == 0
    if tf in ("3d", "1w"):
        return now.hour == 0 and m < 45
    return True


_PRICE_MAP: Dict[str, float] = {}
_PRICE_MAP_AT: float = 0.0


def _live_price_map() -> Dict[str, float]:
    """One venue ticker call per cycle: {SYMBOL: live price} for every chain.

    Round 13: a chain's liveness (invalidation, approach watch, «از ناحیه دور شد»)
    must NOT depend on whether a kline window happens to be open — that dependency
    is exactly why 4h/1d chains looked dead. The ticker is cached by the venue
    layer, so this costs nothing per candidate.
    """
    global _PRICE_MAP, _PRICE_MAP_AT
    now = time.monotonic()
    if _PRICE_MAP and now - _PRICE_MAP_AT < 40:
        return _PRICE_MAP
    prices: Dict[str, float] = {}
    try:
        from data.ourbit import get_ourbit_tickers
        for row in get_ourbit_tickers(use_cache=True):
            _px = float(row.get("last_price") or 0)
            if _px > 0:
                prices[str(row.get("symbol") or "").upper()] = _px
    except Exception as exc:
        print(f"live price map (ourbit) warning: {exc}")
    if not prices:
        try:
            from data.fetcher import get_tickers
            for row in get_tickers():
                _px = float(row.get("last_price") or 0)
                if _px > 0:
                    prices[str(row.get("symbol") or "").upper()] = _px
        except Exception as exc:
            print(f"live price map warning: {exc}")
    if prices:
        _PRICE_MAP, _PRICE_MAP_AT = prices, now
    return _PRICE_MAP or prices


def _confirmation_stale_minutes(candidate, closed_df) -> Optional[int]:
    """Minutes between the confirming candle and now (None while it is fresh).

    The confirming bar is the one that satisfied the one-close law
    (`fast_break_bar` when the pattern lane fired), else the newest closed bar of
    the confirm timeframe. Past two candles of that timeframe the entry is a
    market of the past — his 09-21 rule, applied to confirmations too.
    """
    try:
        md = getattr(candidate, "metadata", None) or {}
        tf = str(md.get("confirm_tf") or getattr(candidate, "trigger_timeframe", "") or "15m").lower()
        mins = float(_TF_MINUTES_LIVE.get(tf, 15) or 15)
        # R62-ARENA (audit C5): the stamp is a real bar timestamp now (the old
        # fast lane stored the frame's integer INDEX, so this guard parsed
        # garbage) and age is measured from the bar's CLOSE on its own TF.
        bar_mins = float(md.get("fast_break_tf_min") or 0.0) or mins
        stamp = md.get("fast_break_bar") or md.get("confirm_bar")
        if not stamp and closed_df is not None and len(closed_df):
            stamp = closed_df["timestamp"].iloc[-1]
            bar_mins = mins
        if not stamp:
            return None
        ts = pd.Timestamp(stamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ts = ts + pd.Timedelta(minutes=bar_mins)
        age_min = (datetime.now(timezone.utc) - ts.to_pydatetime()).total_seconds() / 60.0
        if age_min > 2 * max(mins, bar_mins):
            return int(age_min)
        return None
    except Exception:
        return None


def _candidate_market_frames(candidates) -> Dict[Tuple[str, str], Tuple[pd.DataFrame, pd.DataFrame, float]]:
    """One Bybit request per active symbol/TF for monitor and confirmation.

    Confirmation now runs on the candidate's finer `confirm_tf` (1m scalp /
    5m swing) when present, so a valid retest is confirmed inside minutes;
    charts keep using the trigger TF (see `_chart_frame`)."""
    frames: Dict[Tuple[str, str], Tuple[pd.DataFrame, pd.DataFrame, float]] = {}
    for candidate in candidates:
        # R62-ARENA (audit C7): every chain listens ONE step below its TRIGGER
        # TF (1h←15m, 4h←1h …) — old chains re-pointed from pattern-keyed TFs.
        try:
            from analysis.confirm_r62 import normalize_confirm_tf as _r62_norm
            _r62_norm(candidate)
        except Exception:
            pass
        confirm_tf = candidate.metadata.get("confirm_tf") or candidate.trigger_timeframe
        from analysis.setups_v7 import confirm_late_tf as _late_tf
        _late = _late_tf(candidate.trigger_timeframe)
        for tf in {confirm_tf, candidate.trigger_timeframe, _late} - {None}:
            if not _tf_fetch_window(tf):
                continue   # Viva 09-17 cost ruling: fetch only near candle close
            key = (candidate.symbol, tf)
            if key in frames:
                continue
            # R63 RAILWAY DIET (audit W5 + «مصرف Railway خیلی بالا رفته»): the
            # window spans several monitor cycles; once THIS chain has already
            # been evaluated on the newest CLOSED bar of this TF, re-fetching
            # the same closed candles is pure cost. A fetch that has not yet
            # seen the rolled-over bar (venue latency) is retried as before.
            _exp63 = _expected_closed_bar(tf)
            if _exp63 and _SEEN_CLOSED.get((str(candidate.signal_id), str(tf))) == _exp63:
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
            try:
                _last63 = _bar_key63(closed["timestamp"].iloc[-1])
                for _c63 in candidates:
                    if str(getattr(_c63, "symbol", "")) == str(candidate.symbol):
                        _SEEN_CLOSED[(str(_c63.signal_id), str(tf))] = _last63
                if len(_SEEN_CLOSED) > 4000:
                    _SEEN_CLOSED.clear()
            except Exception:
                pass
    return frames


# R63 (W5): (signal_id, tf) → newest CLOSED bar already evaluated.
_SEEN_CLOSED: Dict[Tuple[str, str], str] = {}


def _bar_key63(ts) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return str(t)[:16]


def _expected_closed_bar(tf: str) -> str:
    """Start time (UTC, naive, 'YYYY-MM-DD HH:MM') of the newest CLOSED bar
    of ``tf`` right now; '' for TFs we cannot floor exactly."""
    try:
        mins = int(_TF_MINUTES_LIVE.get(str(tf).lower()) or 0)
        if mins <= 0:
            return ""
        now = pd.Timestamp.utcnow().tz_localize(None) if pd.Timestamp.utcnow().tzinfo is None \
            else pd.Timestamp.utcnow().tz_convert("UTC").tz_localize(None)
        cur = now.floor(pd.Timedelta(minutes=mins))
        return str(cur - pd.Timedelta(minutes=mins))[:16]
    except Exception:
        return ""


def monitor_candidates() -> Dict[str, int]:
    """Approaching → closed-candle confirmation → confirmed persistence."""
    candidates = get_active_candidates()
    stats = {"active": len(candidates), "approaching": 0, "confirmed": 0, "cancelled": 0}
    if not candidates:
        return stats
    frames = _candidate_market_frames(candidates)
    prices = _live_price_map()
    # ── Viva 09-21/22: every cycle, a confirmed plan is re-frozen/re-applied so
    # no absorb, update or restart can slide its entry/stop/ladder.
    try:
        from analysis.quality_engine import enforce_confirmed_snapshot as _enforce_snap
        for _c in candidates:
            _enforce_snap(_c)
    except Exception as _snap_exc:
        print(f"snapshot enforcement skipped: {_snap_exc}")
    for candidate in candidates:
        key = (candidate.symbol, candidate.metadata.get("confirm_tf") or candidate.trigger_timeframe)
        market_data = frames.get(key)
        if market_data is None:
            # Viva 09-19/20: a missing finer confirm frame must NEVER stall
            # the candidate (the 09-17→09-19 Ourbit 3m gap did exactly that).
            from analysis.setups_v7 import confirm_late_tf as _fb_late
            for _fb in (candidate.trigger_timeframe, _fb_late(candidate.trigger_timeframe)):
                if _fb:
                    market_data = frames.get((candidate.symbol, _fb))
                    if market_data:
                        candidate.metadata["confirm_tf_fallback"] = _fb
                        break
        publication_in_progress = bool(
            candidate.metadata.get("technical_confirmation_complete")
            and (
                candidate.metadata.get("confirmation_chart_sent")
                or candidate.metadata.get("confirmation_message_sent")
            )
        )
        # Once one Confirmed component is public, finish the exact same
        # confirmation even if market data is temporarily unavailable.
        live, closed, current_price = market_data if market_data else (None, None, None)
        if (current_price is None or current_price <= 0) and prices:
            # ── round 13: outside a candle window the chain is still ALIVE and
            # still guarded — the venue ticker answers for its price. Only the
            # closed-candle CONFIRMATION waits for the frame (by law it must be a
            # closed candle); everything else runs every cycle for every TF.
            current_price = prices.get(str(candidate.symbol or "").upper())
        have_frames = market_data is not None
        if current_price is None and not publication_in_progress:
            continue
        # ── r51 CONFIRM-TIMING LAW (Viva 09-27, «بلافاصله بعد از شکست تایید
        # بدن — یا اولین کلوز بعد از شکست»): DASH T242271 swept 63→74 while
        # its chain sat silent for 1670 minutes — the duty-cycle fetch window
        # simply had no frame to judge. A structural chain whose LIVE price
        # is beyond its break edge is a break IN PROGRESS: the confirm frame
        # is fetched NOW (throttled to one forced fetch / 10 min / chain) —
        # the cost window never gates a real break.
        if (not have_frames and not publication_in_progress
                and candidate.setup_code in _STRUCTURAL_QUALITY_LANES
                and current_price):
            try:
                _md51 = candidate.metadata if isinstance(candidate.metadata, dict) else {}
                _now51 = time.time()
                if _now51 - float(_md51.get("break_bypass_at") or 0) > 600:
                    _edge51 = _structural_break_edge(candidate)
                    _px51 = float(current_price)
                    _atr51 = float(_md51.get("atr") or 0) or abs(_px51) * 0.01
                    if _edge51 > 0 and _atr51 > 0:
                        _beyond51 = (_px51 > _edge51 + 0.05 * _atr51
                                     if candidate.direction == "LONG"
                                     else _px51 < _edge51 - 0.05 * _atr51)
                        if _beyond51:
                            _tf51 = str(_md51.get("confirm_tf")
                                        or candidate.trigger_timeframe or "15m")
                            _live51 = get_klines(candidate.symbol, _tf51, 140,
                                                 closed_only=False, use_cache=False)
                            if _live51 is not None and len(_live51) >= 20:
                                market_data = (_live51, _live51.iloc[:-1].reset_index(drop=True),
                                               float(_live51["close"].iloc[-1]))
                                live, closed, current_price = market_data
                                have_frames = True
                                _md51["break_bypass_at"] = _now51
                                candidate.metadata = _md51
                                stats["break_bypass"] = stats.get("break_bypass", 0) + 1
            except Exception as _bp51_exc:
                print(f"r51 break-bypass {candidate.symbol}: {_bp51_exc}")
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

            # ── r60.4 THE update law (Viva 09-30, verbatim): «آپدیت فقط برای
            # هشدار نهایی و آماده‌سازی بیاد» — the old live-break chatter
            # (an update + LIVE CHART per bar while price hovered at the edge:
            # his 23:46 initial + 3 «هنوز در همان ناحیه» repeats, ~1000 msgs /
            # 2 h, plus Railway render cost) is DEMOTED to metadata: the note
            # is still computed and stored as evidence, it just never posts.
            # Updates that still send: approaching (final-watch), stale/analysis
            # note, material zone move, confirmation, verdicts.
            if not candidate.metadata.get("technical_confirmation_complete"):
                try:
                    _pat_frames = frames.get((candidate.symbol, str(candidate.trigger_timeframe or "")))
                    _live_note, _lb_key = _live_break_watch(candidate, (_pat_frames or (None, None, None))[0])
                    if _live_note:
                        _md = candidate.metadata or {}
                        if _md.get("live_break_bar") != _lb_key:
                            stats["live_break"] = stats.get("live_break", 0) + 1
                            _md["live_break_bar"] = _lb_key
                            _md["live_break_note"] = str(_live_note)[:220]
                            candidate.metadata = _md
                            try:   # r60.4: ONE metadata write per new bar (Railway diet)
                                update_candidate(candidate)
                            except Exception:
                                pass
                except Exception as _lb_exc:
                    print(f"live-break watch {candidate.symbol}: {_lb_exc}")

            if not candidate.metadata.get("technical_confirmation_complete"):
                _heal_zone_stop(candidate, current_price)
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
            elif not have_frames:
                # window closed: no closed candle to judge — never a NO_DATA
                # reject (it used to stamp the chain's last_reject_code and hide
                # the real reason from the log/UI)
                confirmed, reason = False, "پنجرهٔ کندلِ تأیید باز نیست؛ بررسی در کلوزِ بعدی"
                # R62-ARENA (audit TH2): the smart engine is NOT tied to the
                # confirm TF's fetch window — it has its own (finer) clock.
                confirmed, candidate, reason = _r62_tohom_attempt(
                    candidate, current_price, stats, confirmed, reason)
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
                _key_tf = str(candidate.metadata.get("confirm_tf_fallback") or key[1] or "")
                confirmed, candidate, reason = evaluate_confirmation(
                    candidate, closed, htf_closed_df=_pat_frame,
                    frame_tf_minutes=float(_TF_MINUTES_LIVE.get(_key_tf, 0) or 0))
                if not confirmed:
                    # Viva 09-17 late bound: the scan/structure candle confirms
                    # when the finer monitor TF never printed the valid close
                    from analysis.setups_v7 import confirm_late_tf as _ltf
                    _lt = _ltf(candidate.trigger_timeframe)
                    _lf = frames.get((candidate.symbol, _lt)) if _lt else None
                    if _lf and _lt != key[1]:
                        confirmed, candidate, reason = evaluate_confirmation(
                            candidate, _lf[1], htf_closed_df=_pat_frame,
                            frame_tf_minutes=float(_TF_MINUTES_LIVE.get(str(_lt), 0) or 0))
                if not confirmed:
                    # ── r47 TOHOM (Viva 09-27, «انجین هوشمند ورود قبل از کلوز
                    # تایم تریگر»): sub-TF directional closes with rising volume
                    # and a confirming pattern beyond the same break edge may
                    # confirm NOW. R62: re-evaluated on every new sub-candle
                    # (no one-shot), one step below the confirm TF, fresh data.
                    # (evaluate_tohom_confirmation lives in _r62_tohom_attempt)
                    try:
                        confirmed, candidate, reason = _r62_tohom_attempt(
                            candidate, current_price, stats, confirmed, reason)
                    except Exception as exc:
                        print(f"TOHOM check skipped {candidate.signal_id}: {exc}")

            if confirmed:
                # ── Viva 09-21/22: the confirmation moment FROZENS the plan
                # (entry/stop/ladder/lines) so no later update or absorb can
                # slide the tool he photographed as «کش اومده».
                try:
                    from analysis.quality_engine import freeze_confirmed_snapshot
                    freeze_confirmed_snapshot(candidate)
                except Exception as _snap_exc:
                    print(f"snapshot freeze skipped: {_snap_exc}")
            if (not confirmed and have_frames
                    and str(candidate.metadata.get("last_reject_code") or "") == "BREAK_RECLAIMED"
                    and not candidate.metadata.get("technical_confirmation_complete")):
                # ── R62-ARENA (audit C8 / r61.2 law «ری‌کلیم = مرگِ شکست»): a
                # break the market took back is a FAILED break — the chain is
                # closed with the standard cancel message instead of sitting
                # on a non-terminal reject forever.
                candidate.status = "CANCELLED"
                candidate.metadata["cancel_reason"] = "BREAK_RECLAIMED"
                update_candidate(candidate)
                try:
                    cancel_staged_confirmation(candidate.signal_id)
                except Exception:
                    pass
                send_candidate_cancelled(
                    candidate,
                    "شکستِ مبنا پس از هشدار پس گرفته شد (کلوز به سمتِ پیش از شکست برگشت)؛ "
                    "شکستِ نامعتبر تأیید نمی‌گیرد و سناریو باطل شد.")
                try:
                    from bot.messages_v7 import send_verdict_reply
                    send_verdict_reply(candidate, False, "شکست پس گرفته شد؛ سناریو باطل شد.")
                except Exception:
                    pass
                stats["cancelled"] = int(stats.get("cancelled", 0)) + 1
                continue
            if not confirmed:
                # ── premise-dead closure (his 09-21 VVV report). Checked before
                # every heartbeat/update so a runaway market can never keep a
                # chain alive for days.
                if not candidate.metadata.get("technical_confirmation_complete") \
                        and _scenario_out_of_reach(candidate, current_price):
                    _zb33 = float(candidate.entry_zone_bottom)
                    _zt33 = float(candidate.entry_zone_top)
                    _edge33 = _zt33 if float(current_price) > _zt33 else _zb33
                    _zone_mid = (_zb33 + _zt33) / 2.0
                    _atr_md = float((candidate.metadata or {}).get("atr") or 0) or 0.0
                    _far = abs(float(current_price) - _edge33) / _atr_md if _atr_md else 0.0
                    candidate.status = "CANCELLED"
                    candidate.metadata["cancel_reason"] = "OUT_OF_REACH"
                    update_candidate(candidate)
                    _tombstone_write(candidate)
                    try:
                        cancel_staged_confirmation(candidate.signal_id)
                    except Exception:
                        pass
                    send_candidate_cancelled(
                        candidate,
                        f"قیمت {_far:.2f} ATR از ناحیهٔ ورود دور شد و کندلِ تأییدِ معتبر "
                        f"شکل نگرفت؛ سناریو از دست رفت و از پیگیری خارج می‌شود "
                        f"(قیمت {float(current_price):g} در برابر ناحیه {_zone_mid:.6g}).",
                    )
                    try:
                        from bot.messages_v7 import send_verdict_reply
                        send_verdict_reply(candidate, False,
                                           "ناحیه از دست رفت؛ به‌جای انتظار بی‌پایان، سناریو بسته شد.")
                    except Exception:
                        pass
                    stats["cancelled"] = int(stats.get("cancelled", 0)) + 1
                    print(f"⛔ OUT_OF_REACH {candidate.symbol} {candidate.setup_code}: "
                          f"{_far:.2f} ATR from the zone — chain closed")
                    continue
                code = str(candidate.metadata.get("last_reject_code") or "UNKNOWN")
                stats["rejects"] = stats.get("rejects", {})
                stats["rejects"][code] = int(stats["rejects"].get(code, 0)) + 1
                # ── r51 UPDATE-EVENT LAW (Viva 09-27, «فقط زمانی آپدیت بیاد که
                # ورود تایید بشه یا ابطال بشه یا هشدار نهایی و آمادگی ورود
                # باشه»): the old per-pattern-candle heartbeat («زنجیره زنده و
                # زیر نظر است» — DASH T242271's only sign of life in 1670
                # minutes) carried ZERO information and is retired. Updates
                # now speak ONLY on confirmation, invalidation/cancellation,
                # or final readiness (the ⚡ live-break note above).
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
                # ── round 13, the same law extended to confirmations: the
                # confirmed entry is born on ONE closed candle — if that candle is
                # older than two candles of the confirm timeframe (restart, missed
                # window, a chain frozen since the fetch-gate era), the entry is
                # NOT tradeable any more. The family still speaks: an analysis note
                # goes out, the ladder stays disarmed, the chain stays alive.
                _stale_conf = _confirmation_stale_minutes(candidate, closed)
                if _stale_conf is not None and candidate.metadata.get("stale_note_sent"):
                    # R62-ARENA (audit C5): ONE analysis note per chain — the old
                    # loop re-sent «⏳ …» every cycle because the retry lane kept
                    # re-confirming the same stale bar.
                    _r62_reset_stale(candidate)
                    update_candidate(candidate)
                    continue
                if _stale_conf is not None:
                    try:
                        send_setup_update(
                            candidate, (frames.get((candidate.symbol, candidate.trigger_timeframe)) or (None, closed, None))[1],
                            note_fa=(f"⏳ تأییدِ فنی روی کندلی ثبت شد که {_stale_conf} دقیقه از آن گذشته است "
                                     f"(بیش از دو کندلِ {candidate.metadata.get('confirm_tf') or candidate.trigger_timeframe}). "
                                     "طبق قانون، ورودِ گذشته‌بازار صادر نمی‌شود؛ این مورد به‌جای سیگنال ورود، فقط گزارش تحلیلی است. "
                                     "زنجیره زیر نظر می‌ماند تا ناحیه یا تأییدِ تازه شکل بگیرد."),
                            critical=True)
                    except Exception as exc:
                        print(f"stale-confirmation note failed {candidate.signal_id}: {exc}")
                    candidate.metadata["stale_confirmation_minutes"] = int(_stale_conf)
                    candidate.metadata["stale_note_sent"] = True
                    _r62_reset_stale(candidate)
                    stats["stale_confirmation"] = stats.get("stale_confirmation", 0) + 1
                    update_candidate(candidate)
                    continue
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
        elif kind in {"PROFIT_FLOOR", "EXIT_WARNING"}:
            # Viva 09-19: short trailing lifecycle notes (main + journal
            # mirror, no chart) — never spam per-candle micro-moves.
            send_trailing_note(event)
        elif kind == "REENTRY_SIGNAL":
            # Viva 09-20 (round 9): the pullback after a protected exit is a
            # fresh entry on the same code (banked TP1 stays locked).
            send_reentry_note(event)
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
        events = list(monitor_confirmed_trades())
        # Viva 09-20: one bounded pass for re-entry signals on ladders whose
        # remainder was closed by the protection phase (pullback entries).
        try:
            from database.repository_v7 import reentry_scan_events
            events.extend(reentry_scan_events())
        except Exception as exc:
            print(f"reentry scan skipped: {exc}")
        return _publish_trade_events(events)


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


def _pin_ttl_sec(tf: str) -> float:
    """R64.4: how long a spot confirm-pin stays awake, per TF — must outlive
    the pattern's approach phase, not the clock of a 15m chart."""
    return {"15m": 2 * 3600.0, "30m": 2 * 3600.0,
            "1h": 8 * 3600.0, "2h": 8 * 3600.0,
            "4h": 36 * 3600.0, "8h": 60 * 3600.0, "12h": 60 * 3600.0,
            "1d": 96 * 3600.0, "3d": 216 * 3600.0, "1w": 384 * 3600.0,
            }.get(str(tf or "").lower(), 3600.0)


def _spot_urgent_recheck() -> int:
    """r58 (Viva: «روشی پیدا بکن که هم موقعیت‌های اسپوت از بین نره هم مصرف
    بهینه ریلوی») — symbols whose ladder showed NEAR_BREAK/TOUCH are pinned
    in kv; every monitor cycle (5 min) a MINI-pass re-scans ONLY those few
    symbols, so a confirmation lands within ≤5 min of its close instead of
    waiting up to an hour for the full pass. Railway cost stays flat: 2-6
    symbols × 6 TFs (history store), not 24. Dedup stamps prevent doubles."""
    try:
        from database.bot_kv import get_json as _g, set_json as _s
        import time as _t
        # r59.3 Railway-diet: pins are per (SYMBOL|TF) and live 1h — the
        # mini-pass re-scans ONLY the alerting timeframe (6× less detector
        # work) instead of all six TFs of the symbol.
        # R64.4: the pin lives as long as its TF's breakout window (was a flat
        # 1h — the confirm lane slept through every slow break).
        watch = {k: v for k, v in (_g("spot_urgent_watch", {}) or {}).items()
                 if _t.time() - float((v or {}).get("ts", 0)) < _pin_ttl_sec(k.partition("|")[2])}
        if not watch:
            return 0
        syms = sorted(watch.keys())[:6]   # keys are "SYMBOL|TF"
        from analysis.spot_engine import (spot_signals_for, scan_spot_urgent_confirms,
                                          scan_spot_tohom_confirms, spot_confirm_tf,
                                          spot_tohom_tf, build_spot_candidate,
                                          SPOT_TRIGGERS)
        from bot.messages_v7 import (CHAT_ID_SPOT, generate_chart,
                                     tf_channel_publish_confirmed)
        from data.fetcher import get_market_bundle
        published = 0
        for key58 in syms:
            symbol, _, _want_tf = key58.partition("|")
            _tfs58 = (_want_tf,) if _want_tf else tuple(SPOT_TRIGGERS)
            # R65: the pinned SHAPE (snapshot) of this symbol|TF, if any
            _pin_entry58 = watch.get(key58) or {}
            _pin_shape58 = (_pin_entry58.get("shape")
                            if isinstance(_pin_entry58, dict) else None)
            # ── R65 URGENT CONFIRM (Viva 10-02: «ترند سه روزه چرا بعد از بریک
            # تایید سیگنال نکرده و سه روز بعد تایید کرده؟ … باید بعد از بریک،
            # کلوز معتبر خارج از ترندلاین تایید ورود صادر بشه — حتی قبل از کلوز
            # تایم تریگر»): the pinned timeframe's shape is judged against the
            # ONE-STEP-LOWER frame's last closed candle. A valid break close
            # there publishes the confirmation NOW (minutes after that close)
            # instead of waiting for the pattern TF (up to 3 days on 3d).
            # The sub frame is fetched in the same bundle — no extra pass.
            _sub58 = spot_confirm_tf(_want_tf) if _want_tf else ""
            if _sub58 and _sub58 not in _tfs58:
                _tfs58 = tuple(_tfs58) + (_sub58,)
            # R65 SPOT-TOHOM (Viva 10-02: «تایید اسپات با موتور توهم هوشمند
            # میتونه زودتر از کلوز تایم تریگر تایید ورود بده»): the smart engine
            # reads ONE STEP BELOW THE CONFIRM TF, so while the confirm candle is
            # still forming its closed sub-candles may confirm — the same bundle
            # carries the frame, zero extra requests.
            _th58 = spot_tohom_tf(_want_tf) if _want_tf else ""
            if _th58 and _th58 not in _tfs58:
                _tfs58 = tuple(_tfs58) + (_th58,)
            try:
                bundle = get_market_bundle(
                    symbol, _tfs58,
                    limits=__import__("analysis.candle_counts", fromlist=["fetch_limits"]).fetch_limits())
                _urgent58 = []
                if _want_tf:
                    try:
                        _urgent58 = scan_spot_urgent_confirms(
                            symbol, bundle, _want_tf, shape=_pin_shape58)
                    except Exception as _u58:
                        print(f"spot urgent confirm warning {symbol}: {_u58}")
                    # the SMART lane first: TOHOM may confirm on the forming
                    # confirm candle, i.e. strictly earlier than the urgent lane
                    try:
                        _urgent58 = (scan_spot_tohom_confirms(
                            symbol, bundle, _want_tf, shape=_pin_shape58)
                                     + list(_urgent58))
                    except Exception as _t58:
                        print(f"spot tohom confirm warning {symbol}: {_t58}")
                for _u58item in _urgent58:
                    try:
                        _uc58 = build_spot_candidate(_u58item)
                    except Exception as _ub58:
                        print(f"spot urgent candidate warning {symbol}: {_ub58}")
                        continue
                    # R65 SNAPSHOT AT DETECTION: freeze the geometry now, so the
                    # first chart and every later update/alert draw ONE picture.
                    try:
                        from analysis.spot_engine import lock_spot_snapshot as _lss65
                        _lss65(_uc58)
                    except Exception:
                        pass
                    key = (f"spot|{_uc58.symbol}|{_uc58.trigger_timeframe}|"
                           f"{(_uc58.metadata or {}).get('pattern_type')}")
                    window = 72.0 if str(_uc58.trigger_timeframe) == "3d" else 36.0
                    if _spot_stamp(key, window, commit=False):
                        continue
                    _frame58 = bundle.get(_uc58.trigger_timeframe)
                    chart = (generate_chart(_frame58, _uc58, confirmed=True)
                             if _frame58 is not None else None)
                    if not chart:
                        continue
                    _alert_kv = _spot_alert_mid_kv(
                        _uc58.symbol, _uc58.trigger_timeframe,
                        str((_uc58.metadata or {}).get("pattern_type") or ""))
                    mid = tf_channel_publish_confirmed(
                        _uc58, chart=chart, chat_override=CHAT_ID_SPOT,
                        reply_to=int(_alert_kv.get("mid") or 0))
                    if mid:
                        _spot_stamp(key, window)
                        published += 1
                        print(f"🪙 spot urgent confirm published {_uc58.symbol} "
                              f"{_uc58.trigger_timeframe} (confirm "
                              f"{(_uc58.metadata or {}).get('spot_confirm_tf')})")
                        try:
                            from bot.messages_v7 import (_public_code as _pc,
                                                         _spot_chain_get as _scg,
                                                         _spot_chain_set as _scs)
                            _chain = _scg(_pc(_uc58))
                            _chain.update({"alert": int(_alert_kv.get("mid") or 0),
                                           "confirm": int(mid), "last": int(mid)})
                            _scs(_pc(_uc58), _chain)
                        except Exception:
                            pass
                for cand in spot_signals_for(symbol, bundle):
                    key = (f"spot|{cand.symbol}|{cand.trigger_timeframe}|"
                           f"{(cand.metadata or {}).get('pattern_type')}")
                    window = 72.0 if str(cand.trigger_timeframe) == "3d" else 36.0
                    if _spot_stamp(key, window, commit=False):
                        continue
                    frame = bundle.get(cand.trigger_timeframe)
                    chart = (generate_chart(frame, cand, confirmed=True)
                             if frame is not None else None)
                    if not chart:
                        continue
                    _alert_kv = _spot_alert_mid_kv(
                        cand.symbol, cand.trigger_timeframe,
                        str((cand.metadata or {}).get("pattern_type") or ""))
                    mid = tf_channel_publish_confirmed(
                        cand, chart=chart, chat_override=CHAT_ID_SPOT,
                        reply_to=int(_alert_kv.get("mid") or 0))
                    if mid:
                        _spot_stamp(key, window)
                        published += 1
                        try:
                            from bot.messages_v7 import (_public_code as _pc,
                                                         _spot_chain_get as _scg,
                                                         _spot_chain_set as _scs)
                            _chain = _scg(_pc(cand))
                            _chain.update({"alert": int(_alert_kv.get("mid") or 0),
                                           "confirm": int(mid), "last": int(mid)})
                            _scs(_pc(cand), _chain)
                        except Exception:
                            pass
            except Exception as exc:
                print(f"spot urgent recheck warning {symbol}: {exc}")
        if published:
            print(f"🪙 spot urgent recheck published={published} syms={syms}")
        return published
    except Exception as exc:
        print(f"spot urgent recheck skipped: {exc}")
        return 0


def run_monitor_cycle() -> None:
    try:
        trade_events = monitor_confirmed_results()
    except Exception as exc:
        print(f"Confirmed trade monitor error: {exc}")
        trade_events = 0
    try:   # r58: pinned near-break symbols confirm within the 5-min cycle
        _spot_urgent_recheck()
    except Exception:
        pass
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
        # R64.4 LINE-WATCH: ticker-priced edge cross alerts (~1 request/30s
        # per market, ALL watched symbols) — instant 1d/3d/1w break/touch
        # without fetching a single candle early.
        try:
            from analysis.line_watch import run_once as _lw_run
            _lw_run()
        except Exception as exc:
            print(f"Line watch error: {exc}")
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

    # ── Viva 09-21 (round-12 incident): a schema hiccup at boot used to kill the
    # scanner thread → the container restarted in a loop → detections, updates
    # and monitors went silent while the dashboard still looked healthy. Boot
    # steps now retry, and a failure is loud but never fatal.
    for _label, _fn in (("candidate store", init_candidate_store),
                        ("v7 schema", init_v7_schema)):
        for _attempt in range(1, 4):
            try:
                _fn()
                break
            except Exception as _boot_exc:
                print(f"⚠️ Boot step '{_label}' failed (attempt {_attempt}/3): {_boot_exc}")
                if _attempt >= 3:
                    print(f"❌ Boot step '{_label}' gave up — scanner continues, "
                          f"schema problems will be retried next cycle.")
                else:
                    time.sleep(5 * _attempt)
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

    def _write_heartbeat(payload: dict) -> None:
        """Liveness proof (round-12 incident): the first discovery scan takes
        ~11 minutes, so the heartbeat is written BEFORE it starts too — the bot
        can never look silent-and-alive at the same time again."""
        payload = dict(payload)
        payload["when"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload["pid"] = os.getpid()
        try:
            from database.bot_kv import set_json as _hb_set
            _hb_set("scanner_heartbeat", payload)
        except Exception as _hb_exc:
            print(f"heartbeat write skipped: {_hb_exc}")
        print(f"♥ HEARTBEAT • {payload['when']} • {payload.get('stage', 'loop')} • "
              f"scans={payload.get('scans', 0)} monitors={payload.get('monitors', 0)}")
    _write_heartbeat({"stage": "boot", "scans": 0, "monitors": 0})
    if SETTINGS.run_scan_on_start:
        run_discovery_scan()
    next_scan = _next_aligned_scan(datetime.now(timezone.utc))
    next_spot = datetime.now(timezone.utc) + timedelta(minutes=2)
    # Monitor on a candle-close grid: each cycle sees the most decisive final
    # minute of the smallest trigger timeframe (5m), and every 12th/48th/288th
    # cycle coincides with the 1h/4h/1D close.
    next_monitor = _next_aligned(
        datetime.now(timezone.utc), SETTINGS.monitor_minutes, SETTINGS.monitor_offset_minute
    )
    last_daily_report = ""
    last_weekly_digest = ""
    _SPOT_THREAD = [None]   # r56: single-flight spot-pass slot
    print(
        f"Scheduler active • next discovery {next_scan.isoformat(timespec='minutes')} • "
        f"monitor every {SETTINGS.monitor_minutes} minutes"
    )

    # ── Viva 09-21 (round-12 incident): the outage was invisible — the web part
    # was healthy while the scanner thread was dead, and nothing on the outside
    # proved silence. The scanner now writes a heartbeat every 5 minutes, to the
    # log AND to the durable KV store, so liveness is checkable from outside.
    _hb = {"next": 0.0, "loops": 0, "scans": 0, "monitors": 0,
           "last_scan": None, "last_monitor": None, "stats": {}, "mon_stats": {}}
    while not _SHUTDOWN:
        now = datetime.now(timezone.utc)
        _hb["loops"] += 1
        if now >= next_monitor:
            _hb["monitors"] += 1
            _hb["last_monitor"] = now.strftime("%H:%M")
            _hb["mon_stats"] = dict(run_monitor_cycle() or {})
            next_monitor = _next_aligned(
                datetime.now(timezone.utc), SETTINGS.monitor_minutes, SETTINGS.monitor_offset_minute
            )
        if now >= next_scan:
            _hb["scans"] += 1
            _hb["last_scan"] = now.strftime("%H:%M")
            _hb["stats"] = dict(run_discovery_scan() or {})
            next_scan = _next_aligned_scan(datetime.now(timezone.utc))
        # ── spot lane on its own cadence (never blocks the futures scan).
        # r56 RAILWAY OPTIMISATION (his «بهینه‌سازی ریلوی فراموش نشه»): the
        # pass takes ~8.5 min (24 symbols × 6 TFs) and used to run INLINE in
        # this loop — every monitor/confirm cycle stalled for it («ستاپ‌ها
        # کم‌کار شدند» had a second, mechanical cause). It now runs in its
        # own single-flight thread; a still-running pass skips its slot
        # instead of stacking.
        if now >= next_spot:
            if _SPOT_THREAD[0] is not None and _SPOT_THREAD[0].is_alive():
                print("spot pass still running — slot skipped, no stacking")
            else:
                _hb["spot_runs"] = _hb.get("spot_runs", 0) + 1

                def _spot_pass_job():
                    try:
                        _hb["spot_stats"] = dict(run_spot_scan() or {})
                    except Exception as _sp_exc:
                        print(f"spot pass thread failed: {_sp_exc}")
                _SPOT_THREAD[0] = threading.Thread(
                    target=_spot_pass_job, name="viva-spot-pass", daemon=True)
                _SPOT_THREAD[0].start()
            next_spot = now + timedelta(
                minutes=max(15, int(os.getenv("SPOT_SCAN_MINUTES", "60") or 60)))
        if time.time() >= _hb["next"]:
            _hb["next"] = time.time() + 300
            _write_heartbeat({
                "stage": "loop",
                "scans": _hb["scans"], "monitors": _hb["monitors"],
                "last_scan": _hb["last_scan"], "last_monitor": _hb["last_monitor"],
                "scan_stats": _hb["stats"], "monitor_stats": _hb["mon_stats"],
            })
            try:
                from data.fetcher import cost_counters as _cc
                _c = _cc()
                print(f"📉 COST · kline calls={_c['kline_calls']} "
                      f"(cache hits={_c['kline_cache_hits']}) • "
                      f"last scan skipped_unchanged={_hb['stats'].get('skipped_unchanged', 0)}"
                      f"/{_hb['stats'].get('symbols', 0)}")
            except Exception:
                pass
            print(f"   last discovery={_hb['last_scan']} {_hb['stats']} • "
                  f"last monitor={_hb['last_monitor']}")
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
