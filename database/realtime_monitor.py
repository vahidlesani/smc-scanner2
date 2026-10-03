"""Low-latency execution lifecycle monitor.

Closed candles decide analytical confirmation.  Once a position is filled,
price-touch TP/SL/trailing events are executed from fresh venue tickers so a
15-minute trigger does not add a 15-minute notification delay.
"""
from __future__ import annotations

import json
from typing import Dict, List

from config import get_settings
from database import db as legacy_db
from database.repository_v7 import _bool_value, _now
from analysis.trade_management import advance_ladder

SETTINGS = get_settings()


def _void_signal_row(cursor, signal_id: str, now: str, reason: str) -> None:
    """Settle a phantom PENDING position as result='VOID' (pnl 0).

    VOID is excluded from every WIN/LOSS statistic, board and the app's
    PENDING list by construction — the fake profit never reaches results."""
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    p = legacy_db._ph()
    cursor.execute(
        f"UPDATE signals SET result='VOID',pnl_pct=0,pnl_usd=0,closed_at={p} WHERE signal_id={p}",
        (now, signal_id))
    cursor.execute(
        f"UPDATE active_signals SET status='CLOSED',is_cancelled={truth} WHERE signal_id={p}",
        (signal_id,))
    cursor.execute(
        f"DELETE FROM signal_symbol_locks WHERE signal_id={p}",
        (signal_id,))
    print(f"VOID phantom position {signal_id}: {reason}")


def classify_phantom(rows, strategy_version: str = "") -> Dict[str, str]:
    """Pure r53 result-integrity rules — returns {signal_id: reason}.

    • WRONG-SIDE LADDER: a LONG whose ladder targets sit AT/BELOW entry (or a
      SHORT's above) can only «win» instantly and fictitiously — the daily
      SHIB phantom (+$309, «فروش روی 0.00001») was exactly this.
    • TWIN POSITION: the same (symbol, source, direction, trigger-TF) holding
      MORE THAN ONE PENDING paper position — the app re-registers an identical
      clone every day; only the NEWEST may live. r55: the trigger TF joined
      the key — the SAME symbol legitimately holds a 4h AND a 1d spot
      position at once; those were being VOIDed as "twins".
    rows: newest first, tuples (signal_id, symbol, source, direction, entry,
    target_state_json, trigger_timeframe)."""
    verdicts: Dict[str, str] = {}
    seen = {}
    for (signal_id, symbol, source, direction, entry,
         target_state_json, trigger_tf) in rows:
        signal_id = str(signal_id)
        try:
            entry_f = float(entry or 0)
        except Exception:
            entry_f = 0.0
        sign = 1.0 if str(direction or "").upper() == "LONG" else -1.0
        if entry_f > 0:
            try:
                ladder = json.loads(target_state_json or "{}")
            except Exception:
                ladder = {}
            # NOTE: JSON numbers stringify as "1e-05" for sub-pip coins —
            # parse with float(), never with a digit-string filter.
            targets = []
            for _t in (ladder.get("targets") or []):
                try:
                    targets.append(float(_t))
                except Exception:
                    continue
            if targets and all(sign * (t - entry_f) <= 1e-12 for t in targets):
                verdicts[signal_id] = "wrong-side ladder targets"
                continue
        key = (str(symbol or "").upper(), str(source or ""), str(direction or ""),
               str(trigger_tf or "").lower())
        if key in seen:
            verdicts[signal_id] = f"twin of {seen[key]}"
        else:
            seen[key] = signal_id
    return verdicts


def void_phantom_positions() -> int:
    """r53 RESULTS-PNL integrity sweep (his SHIB report) — runs once per
    realtime cycle, before any ladder advances."""
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    p = legacy_db._ph()
    try:
        with legacy_db.db_cursor() as cursor:
            cursor.execute(f"""
                SELECT signal_id, symbol, source, direction, entry, target_state_json,
                       trigger_timeframe
                FROM signals
                WHERE confirmed={truth} AND confirmation_sent={truth}
                  AND result='PENDING' AND closed_at IS NULL
                ORDER BY created_at DESC
            """)
            rows = cursor.fetchall()
        verdicts = classify_phantom(rows, str(SETTINGS.strategy_version or ""))
        if not verdicts:
            return 0
        now = _now()
        with legacy_db.db_cursor() as cursor:
            for signal_id, reason in verdicts.items():
                _void_signal_row(cursor, signal_id, now, reason)
        return len(verdicts)
    except Exception as exc:
        print(f"phantom sweep skipped: {exc}")
        return 0


def pending_filled_count() -> int:
    """R67.2 cost gate: how many filled PENDING positions exist right now.

    The 5-second realtime lane exists ONLY to catch price-touch TP/SL/trail
    events for LIVE positions («fresh ticker path»). With zero filled
    positions it has nothing to detect — the caller skips the venue ticker
    fetch entirely (one bulk HTTP + JSON parse every 5s = ~17k calls/day of
    pure waste). One indexed COUNT is the replacement cost. Fail-open: any
    DB problem returns 1 so the lane keeps running exactly as before.
    """
    try:
        truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
        with legacy_db.db_cursor() as cursor:
            cursor.execute(f"""
                SELECT COUNT(*) FROM signals
                WHERE confirmed={truth} AND confirmation_sent={truth}
                  AND status='CONFIRMED' AND result='PENDING'
                  AND entry_filled={truth} AND strategy_version={legacy_db._ph()}
            """, (SETTINGS.strategy_version,))
            row = cursor.fetchone()
        return int(row[0] or 0)
    except Exception:
        return 1


def monitor_realtime_prices(prices: Dict[str, float]) -> List[Dict]:
    """Advance durable filled ladders using one fresh last-price snapshot."""
    try:
        void_phantom_positions()
    except Exception:
        pass
    truth = "TRUE" if legacy_db.USE_POSTGRES else "1"
    p = legacy_db._ph()
    with legacy_db.db_cursor() as cursor:
        cursor.execute(f"""
            SELECT signal_id,symbol,direction,entry,sl_original,leverage,margin_usd,
                   trade_style,confirmed_at,source,strategy_fa,strategy_version,
                   pro_message_id,target_state_json,public_code,trigger_timeframe
            FROM signals
            WHERE confirmed={truth} AND confirmation_sent={truth}
              AND status='CONFIRMED' AND result='PENDING'
              AND entry_filled={truth} AND strategy_version={p}
        """, (SETTINGS.strategy_version,))
        rows = cursor.fetchall()

    events: List[Dict] = []
    for row in rows:
        (signal_id,symbol,direction,entry,original_sl,leverage,margin,style,
         confirmed_at,source,strategy_fa,strategy_version,pro_message_id,
         target_state_json,public_code,trigger_tf) = row
        price = float(prices.get(str(symbol).upper()) or 0)
        if price <= 0:
            continue
        try:
            ladder = json.loads(target_state_json or "{}")
        except Exception:
            ladder = {}
        if not ladder or not ladder.get("targets") or ladder.get("closed"):
            continue
        step = advance_ladder(ladder, price, price)
        ladder = step["state"]
        raw_events = step["events"]
        if not raw_events:
            continue
        now = _now()
        risk_pct = abs(float(entry)-float(original_sl)) / max(float(entry), 1e-12) * 100
        notional = float(margin or 0) * int(leverage or 1)
        common = {
            "signal_id":signal_id,"symbol":symbol,"direction":direction,"style":style,
            "source":source,"strategy_fa":strategy_fa,"strategy_version":strategy_version,
            "confirmed_at":str(confirmed_at),"confirmation_sent":True,
            "pro_message_id":int(pro_message_id or 0),"public_code":public_code,
            "entry":float(entry),"original_sl":float(original_sl),"sl":float(ladder["current_sl"]),
            "leverage":int(leverage or 1),"margin":float(margin or 0),"live_price":price,
            "event_at":now,"trigger_timeframe":str(trigger_tf or ""),
            "targets":list(ladder["targets"]),"hit_index":int(ladder["hit_index"]),
        }
        emitted = []
        for raw in raw_events:
            kind = str(raw.get("event") or "")
            if kind == "LADDER_COMPLETE":
                continue
            event = dict(common); event.update(raw)
            if kind.startswith("TP"):
                idx = int(kind[2:])-1
                # round 14: the leg's move is a pure price distance to that TP —
                # nothing here is derived from the stop.
                _tg = list(ladder.get("targets") or [])
                if entry and idx < len(_tg):
                    event["leg_price_move_pct"] = abs(float(_tg[idx]) - float(entry)) / abs(float(entry)) * 100.0
                else:
                    event["leg_price_move_pct"] = float(ladder.get("target_r", [])[idx]) * risk_pct
                event["leg_pnl_pct"] = event["leg_price_move_pct"] * float(event.get("weight",0)) / 100
                event["leg_profit_usd"] = notional * event["leg_pnl_pct"] / 100
                event["leg_margin_roi_pct"] = event["leg_profit_usd"] / max(float(margin or 0),1e-12)*100
                event["leg_full_roi_pct"] = event["leg_price_move_pct"] * int(leverage or 1)
            else:
                event["realized_pnl_pct"] = float(ladder.get("realized_r",0))*risk_pct
                event["realized_profit_usd"] = notional*event["realized_pnl_pct"]/100
                event["realized_margin_roi_pct"] = event["realized_profit_usd"]/max(float(margin or 0),1e-12)*100
            emitted.append(event)
        with legacy_db.db_cursor() as cursor:
            if int(ladder.get("hit_index") or 0) >= 1:
                cursor.execute(f"UPDATE signals SET tp1_hit={truth}, partial_win={truth}, target_state_json={p}, sl={p}, last_checked_at={p} WHERE signal_id={p}",
                               (json.dumps(ladder),float(ladder["current_sl"]),now,signal_id))
                cursor.execute(f"UPDATE active_signals SET tp1_hit={truth}, partial_win={truth}, target_state_json={p}, sl={p}, last_checked_at={p} WHERE signal_id={p}",
                               (json.dumps(ladder),float(ladder["current_sl"]),now,signal_id))
            else:
                cursor.execute(f"UPDATE signals SET target_state_json={p}, sl={p}, last_checked_at={p} WHERE signal_id={p}", (json.dumps(ladder),float(ladder["current_sl"]),now,signal_id))
                cursor.execute(f"UPDATE active_signals SET target_state_json={p}, sl={p}, last_checked_at={p} WHERE signal_id={p}", (json.dumps(ladder),float(ladder["current_sl"]),now,signal_id))
            if ladder.get("closed"):
                gross = float(ladder.get("realized_r",0))*risk_pct
                # Viva 2026-09-14 (ZEC PINWALLQ K120563): a position that
                # BANKED TP1 then exited at the BE-locked trail was booked as
                # a LOSS — settlement charged fee AND invented slippage on the
                # full notional in one round trip. Settlement is gross minus
                # the exchange's own round-trip fee; slippage stays a display
                # note, never a hidden second cut.
                net = gross-2*SETTINGS.fee_rate_percent
                profit = notional*net/100
                result = "WIN" if net>0 else "LOSS"
                cursor.execute(f"UPDATE signals SET result={p},pnl_pct={p},pnl_usd={p},closed_at={p} WHERE signal_id={p}", (result,net,profit,now,signal_id))
                cursor.execute(f"UPDATE active_signals SET status='CLOSED',is_cancelled={truth} WHERE signal_id={p}",(signal_id,))
                cursor.execute(f"DELETE FROM signal_symbol_locks WHERE signal_id={p} AND strategy_version={p}",(signal_id,SETTINGS.strategy_version))
                emitted.append({**common,"event":"CLOSED","result":result,"pnl":net,"gross_pnl":gross,"profit_usd":profit,
                                "margin_roi_pct":profit/max(float(margin or 0),1e-12)*100,"live_price":price,
                                "trailing_used": bool(int(ladder.get("hit_index") or 0)>0
                                                       and abs(float(ladder.get("current_sl") or 0)-float(original_sl))>1e-9)})
        events.extend(emitted)
    return events
