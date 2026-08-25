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


def monitor_realtime_prices(prices: Dict[str, float]) -> List[Dict]:
    """Advance durable filled ladders using one fresh last-price snapshot."""
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
                target_r = float(ladder.get("target_r", [])[idx])
                event["leg_price_move_pct"] = target_r * risk_pct
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
                net = gross-2*(SETTINGS.fee_rate_percent+SETTINGS.slippage_percent)
                profit = notional*net/100
                result = "WIN" if net>0 else "LOSS"
                cursor.execute(f"UPDATE signals SET result={p},pnl_pct={p},pnl_usd={p},closed_at={p} WHERE signal_id={p}", (result,net,profit,now,signal_id))
                cursor.execute(f"UPDATE active_signals SET status='CLOSED',is_cancelled={truth} WHERE signal_id={p}",(signal_id,))
                cursor.execute(f"DELETE FROM signal_symbol_locks WHERE signal_id={p} AND strategy_version={p}",(signal_id,SETTINGS.strategy_version))
                emitted.append({**common,"event":"CLOSED","result":result,"pnl":net,"gross_pnl":gross,"profit_usd":profit,
                                "margin_roi_pct":profit/max(float(margin or 0),1e-12)*100,"live_price":price})
        events.extend(emitted)
    return events
