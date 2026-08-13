"""Walk-forward, no-lookahead backtest using the same v7 setup engine as live.

The old implementation applied today's final HTF bias to the whole history.
This version slices every timeframe at each historical timestamp, waits for a
future retest/closed-candle confirmation, and uses conservative intrabar rules.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from analysis.models import SignalCandidate
from analysis.quality_engine import evaluate_confirmation
from analysis.setups_v7 import scan_setups
from config import get_settings
from data.fetcher import MarketBundle, get_klines_paginated

SETTINGS = get_settings()


@dataclass
class BacktestTrade:
    signal_id: str
    setup: str
    style: str
    symbol: str
    direction: str
    score: int
    detected_at: str
    confirmed_at: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    result: str
    pnl_pct: float
    gross_pnl_pct: float
    bars_held: int
    max_drawdown: float
    exit_price: float
    exit_reason: str


def _slice(frame: Optional[pd.DataFrame], timestamp, minimum: int = 0) -> Optional[pd.DataFrame]:
    if frame is None:
        return None
    result = frame.loc[pd.to_datetime(frame["timestamp"]) <= pd.Timestamp(timestamp)].copy().reset_index(drop=True)
    return result if len(result) >= minimum else None


def _historical_ticker(daily: Optional[pd.DataFrame], timestamp) -> Dict:
    available = _slice(daily, timestamp)
    turnover = float(available["turnover"].iloc[-1]) if available is not None and not available.empty and "turnover" in available else 100_000_000
    baseline = float(available["turnover"].tail(7).median()) if available is not None and len(available) >= 3 and "turnover" in available else turnover
    return {
        "turnover24h": turnover,
        "relative_volume": turnover / baseline if baseline > 0 else 1.0,
        "spread_pct": 0.06,  # conservative configurable historical proxy
    }


def _load_frames(symbol: str, style: str, days: int) -> Tuple[Dict[str, pd.DataFrame], str]:
    if style == "SWING":
        counts = {
            "1d": max(150, days + 120),
            "4h": days * 6 + 180,
            "1h": days * 24 + 240,
            "15m": days * 96 + 300,
        }
        trigger_tf = "15m"
    else:
        counts = {
            "1d": max(120, days + 90),
            "1h": days * 24 + 240,
            "15m": days * 96 + 300,
            "5m": days * 288 + 400,
        }
        trigger_tf = "5m"
    frames: Dict[str, pd.DataFrame] = {}
    for timeframe, count in counts.items():
        frame = get_klines_paginated(symbol, timeframe, count, closed_only=True)
        if frame is None or frame.empty:
            raise RuntimeError(f"No {timeframe} history for {symbol}")
        frames[timeframe] = frame
    return frames, trigger_tf


def _candidate_key(candidate: SignalCandidate) -> Tuple:
    return (
        candidate.style,
        candidate.setup_code,
        candidate.direction,
        int(candidate.metadata.get("impulse_index", -1)),
        round(float(candidate.metadata.get("structure_level", 0)), 8),
    )


def _wait_for_confirmation(
    candidate: SignalCandidate,
    trigger: pd.DataFrame,
    detection_index: int,
) -> Tuple[Optional[int], SignalCandidate]:
    max_bars = (36 * 4) if candidate.style == "SWING" else (6 * 12)
    end = min(len(trigger), detection_index + max_bars + 1)
    for index in range(detection_index + 1, end):
        candle = trigger.iloc[index]
        if candidate.direction == "LONG" and float(candle["low"]) <= candidate.sl:
            return None, candidate
        if candidate.direction == "SHORT" and float(candle["high"]) >= candidate.sl:
            return None, candidate
        confirmed, candidate, _ = evaluate_confirmation(candidate, trigger.iloc[: index + 1].copy())
        if confirmed:
            candidate.confirmed_at = pd.Timestamp(candle["timestamp"]).isoformat()
            return index, candidate
    return None, candidate


def _simulate_trade(candidate: SignalCandidate, trigger: pd.DataFrame, confirmed_index: int) -> BacktestTrade:
    tp1_hit = False
    bars_held = 0
    max_drawdown = 0.0
    entry, sl, tp1, tp2 = candidate.planned_entry, candidate.sl, candidate.tp1, candidate.tp2
    max_hold = 7 * 24 * 4 if candidate.style == "SWING" else 24 * 12
    result, gross, exit_price, reason = "TIMEOUT", 0.0, entry, "Time expiry"

    for index in range(confirmed_index + 1, min(len(trigger), confirmed_index + max_hold + 1)):
        row = trigger.iloc[index]
        high, low, close = float(row["high"]), float(row["low"]), float(row["close"])
        bars_held += 1
        adverse = (entry - low) / entry * 100 if candidate.direction == "LONG" else (high - entry) / entry * 100
        max_drawdown = max(max_drawdown, adverse)
        if candidate.direction == "LONG":
            stop_hit = low <= (entry if tp1_hit else sl)
            first_hit, final_hit = high >= tp1, high >= tp2
        else:
            stop_hit = high >= (entry if tp1_hit else sl)
            first_hit, final_hit = low <= tp1, low <= tp2

        # Conservative: unknown tick sequence means stop wins same-candle ambiguity.
        if stop_hit:
            if tp1_hit:
                move1 = abs(tp1 - entry) / entry * 100
                gross = move1 * SETTINGS.partial_tp1_percent / 100
                result, exit_price, reason = "WIN", entry, "TP1 then Breakeven"
            else:
                gross = -abs(sl - entry) / entry * 100
                result, exit_price, reason = "LOSS", sl, "Stop Loss"
            break
        if final_hit:
            move1 = abs(tp1 - entry) / entry * 100
            move2 = abs(tp2 - entry) / entry * 100
            gross = move1 * SETTINGS.partial_tp1_percent / 100 + move2 * SETTINGS.partial_tp2_percent / 100
            result, exit_price, reason = "WIN", tp2, "TP2"
            break
        if first_hit:
            tp1_hit = True
        if bars_held >= max_hold:
            gross = (close - entry) / entry * 100 if candidate.direction == "LONG" else (entry - close) / entry * 100
            exit_price = close

    roundtrip_cost = 2 * (SETTINGS.fee_rate_percent + SETTINGS.slippage_percent)
    net = gross - roundtrip_cost
    if result == "TIMEOUT":
        result = "WIN" if net > 0 else "LOSS"
    return BacktestTrade(
        signal_id=candidate.signal_id,
        setup=candidate.setup_code,
        style=candidate.style,
        symbol=candidate.symbol,
        direction=candidate.direction,
        score=candidate.score,
        detected_at=candidate.created_at,
        confirmed_at=candidate.confirmed_at,
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        result=result,
        pnl_pct=net,
        gross_pnl_pct=gross,
        bars_held=bars_held,
        max_drawdown=max_drawdown,
        exit_price=exit_price,
        exit_reason=reason,
    )


def _metrics(trades: List[BacktestTrade]) -> Dict:
    if not trades:
        return {
            "total": 0, "wins": 0, "losses": 0, "winrate": 0.0,
            "avg_pnl": 0.0, "total_pnl": 0.0, "expectancy": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0, "avg_bars": 0.0,
        }
    ordered = sorted(trades, key=lambda trade: trade.confirmed_at)
    returns = np.array([trade.pnl_pct for trade in ordered], dtype=float)
    wins = int(np.sum(returns > 0))
    losses = len(returns) - wins
    gross_profit = float(returns[returns > 0].sum())
    gross_loss = abs(float(returns[returns <= 0].sum()))
    equity = np.cumsum(returns)
    peaks = np.maximum.accumulate(np.concatenate(([0.0], equity)))
    drawdowns = peaks[1:] - equity
    return {
        "total": len(ordered),
        "wins": wins,
        "losses": losses,
        "winrate": wins / len(ordered) * 100,
        "avg_pnl": float(returns.mean()),
        "total_pnl": float(returns.sum()),
        "expectancy": float(returns.mean()),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "max_drawdown": float(drawdowns.max()) if len(drawdowns) else 0.0,
        "avg_bars": float(np.mean([trade.bars_held for trade in ordered])),
    }


def run_style_backtest(symbol: str, style: str, days: int = 14) -> Dict:
    style = style.upper()
    frames, trigger_tf = _load_frames(symbol, style, days)
    trigger = frames[trigger_tf]
    warmup = 180 if style == "SWING" else 240
    seen = set()
    trades: List[BacktestTrade] = []
    # End early enough to leave future bars for confirmation and result simulation.
    for index in range(warmup, len(trigger) - 5):
        timestamp = trigger["timestamp"].iloc[index]
        sliced = {timeframe: _slice(frame, timestamp) for timeframe, frame in frames.items()}
        if style == "SWING" and any(sliced.get(tf) is None for tf in ("4h", "1h", "15m")):
            continue
        if style == "SCALP" and any(sliced.get(tf) is None for tf in ("1h", "15m", "5m")):
            continue
        bundle = MarketBundle(
            symbol=symbol,
            frames=sliced,
            ticker=_historical_ticker(sliced.get("1d"), timestamp),
        )
        for candidate in scan_setups(bundle, style):
            key = _candidate_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            candidate.created_at = pd.Timestamp(timestamp).isoformat()
            expiry = pd.Timestamp(timestamp) + (timedelta(hours=36) if style == "SWING" else timedelta(hours=6))
            candidate.expires_at = expiry.isoformat()
            confirmed_index, candidate = _wait_for_confirmation(candidate, trigger, index)
            if confirmed_index is None:
                continue
            trades.append(_simulate_trade(candidate, trigger, confirmed_index))

    overall = _metrics(trades)
    by_setup = {}
    for setup in sorted({trade.setup for trade in trades}):
        by_setup[setup] = _metrics([trade for trade in trades if trade.setup == setup])
    return {
        "symbol": symbol,
        "style": style,
        "days": days,
        "metrics": overall,
        "by_setup": by_setup,
        "trades": [asdict(trade) for trade in trades],
        "methodology": {
            "lookahead": False,
            "closed_candle_confirmation": True,
            "same_candle_rule": "stop_first_conservative",
            "fees_percent_roundtrip": 2 * SETTINGS.fee_rate_percent,
            "slippage_percent_roundtrip": 2 * SETTINGS.slippage_percent,
            "strategy_version": SETTINGS.strategy_version,
        },
    }


def run_full_backtest(symbol: str = "BTCUSDT", days: int = 14, style: str = "BOTH") -> Dict:
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    styles = ["SWING", "SCALP"] if style.upper() == "BOTH" else [style.upper()]
    output = {"symbol": symbol, "days": days, "styles": {}, "error": ""}
    for item in styles:
        try:
            style_result = run_style_backtest(symbol, item, days)
            output["styles"][item] = style_result
            if os.getenv("PERSIST_BACKTEST_RESULTS", "true").lower() in {"1", "true", "yes"}:
                try:
                    from database.repository_v7 import init_v7_schema, save_backtest_run
                    init_v7_schema()
                    save_backtest_run(style_result)
                except Exception as persist_error:
                    print(f"Backtest persistence warning: {persist_error}")
        except Exception as exc:
            output["styles"][item] = {"error": str(exc), "metrics": _metrics([]), "by_setup": {}, "trades": []}
    if not output["styles"]:
        output["error"] = "No backtest data available"
    return output


def generate_backtest_report(results: Dict) -> str:
    if not results or (results.get("error") and not results.get("styles")):
        return f"❌ بک‌تست قابل اجرا نبود: {results.get('error', 'No data')}"
    lines = [
        "🧪 <b>Viva Walk-Forward Backtest v7</b>",
        f"🪙 {results.get('symbol')} • {results.get('days')} days",
        f"🧠 Strategy: {SETTINGS.strategy_version}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for style, data in results.get("styles", {}).items():
        if data.get("error"):
            lines.append(f"\n❌ <b>{style}</b>: {data['error']}")
            continue
        metric = data["metrics"]
        lines.extend([
            f"\n📊 <b>{style}</b>",
            f"├ Confirmed trades: {metric['total']}",
            f"├ Win/Loss: {metric['wins']}/{metric['losses']}",
            f"├ Win Rate: <b>{metric['winrate']:.1f}%</b>",
            f"├ Expectancy: <b>{metric['expectancy']:+.3f}%</b>",
            f"├ Profit Factor: <b>{metric['profit_factor']:.2f}</b>",
            f"├ Total PnL: <b>{metric['total_pnl']:+.2f}%</b>",
            f"└ Max Drawdown: <b>{metric['max_drawdown']:.2f}%</b>",
        ])
        for setup, setup_metric in data.get("by_setup", {}).items():
            lines.append(
                f"   • {setup}: {setup_metric['total']} trade • "
                f"WR {setup_metric['winrate']:.1f}% • PF {setup_metric['profit_factor']:.2f}"
            )
    lines.extend([
        "\n━━━━━━━━━━━━━━━━━━━━",
        "✅ Bias در هر نقطه تاریخی محاسبه شده است.",
        "✅ فقط کندل بسته‌شده تأیید ایجاد می‌کند.",
        "✅ کارمزد و Slippage لحاظ شده‌اند.",
        "⚠️ نتیجه گذشته تضمین عملکرد آینده نیست.",
    ])
    return "\n".join(lines)
