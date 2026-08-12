# analysis/backtest.py - Backtest Module
# بک‌تست استراتژی‌ها روی داده‌های تاریخی

import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime

from data.fetcher import get_klines
from analysis.strategies import (
    detect_quasimodo, detect_engulfing, detect_pinbar,
    detect_fvg_signal, detect_ifvg_signal, detect_flipzone,
    detect_breakout, detect_orderblock_signal,
    detect_structure_change, detect_return_to_area
)
from analysis.structure import find_swing_points, classify_structure


@dataclass
class BacktestTrade:
    strategy: str
    symbol: str
    direction: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    entry_bar: int
    result: str = "PENDING"  # WIN, LOSS, TIMEOUT
    pnl_pct: float = 0
    bars_held: int = 0
    max_drawdown: float = 0
    exit_bar: int = 0
    exit_price: float = 0


def backtest_strategy(strategy_func, df: pd.DataFrame, htf_bias: str,
                      symbol: str, start_bar: int = 50,
                      partial_tp1: float = 60,
                      move_sl_to_be: bool = True) -> List[BacktestTrade]:
    """
    بک‌تست یک استراتژی روی داده‌های تاریخی
    
    منطق:
    ۱. هر کندل رو چک میکنه
    ۲. اگه سیگنال صادر شد → ورود
    ۳. TP1 → partial close (60%) + SL to BE
    ۴. TP2 → close remaining (40%)
    ۵. SL → loss
    """
    trades = []
    in_trade = False
    current_trade = None
    
    for i in range(start_bar, len(df)):
        window = df.iloc[:i+1].copy().reset_index(drop=True)
        
        if not in_trade:
            # دنبال سیگنال بگرد
            try:
                signal = strategy_func(window, htf_bias)
                if signal:
                    trade = BacktestTrade(
                        strategy=signal.strategy,
                        symbol=symbol,
                        direction=signal.direction,
                        entry=signal.entry,
                        sl=signal.sl,
                        tp1=signal.tp1,
                        tp2=signal.tp2,
                        entry_bar=i
                    )
                    current_trade = trade
                    in_trade = True
            except Exception:
                continue
        
        else:
            # چک کردن TP/SL
            candle = df.iloc[i]
            high = candle["high"]
            low = candle["low"]
            
            direction = current_trade.direction
            entry = current_trade.entry
            sl = current_trade.sl
            tp1 = current_trade.tp1
            tp2 = current_trade.tp2
            
            # محاسبه drawdown
            if direction == "LONG":
                dd = (entry - low) / entry * 100
            else:
                dd = (high - entry) / entry * 100
            current_trade.max_drawdown = max(
                current_trade.max_drawdown, dd
            )
            
            hit_sl = False
            hit_tp1 = False
            hit_tp2 = False
            
            if direction == "LONG":
                hit_sl = low <= sl
                hit_tp1 = high >= tp1
                hit_tp2 = high >= tp2
            else:
                hit_sl = high >= sl
                hit_tp1 = low <= tp1
                hit_tp2 = low <= tp2
            
            current_trade.bars_held += 1
            
            # Timeout: بیش از 100 کندل
            if current_trade.bars_held > 100:
                current_trade.result = "TIMEOUT"
                current_trade.exit_bar = i
                current_trade.exit_price = candle["close"]
                if direction == "LONG":
                    current_trade.pnl_pct = (
                        (candle["close"] - entry) / entry * 100
                    )
                else:
                    current_trade.pnl_pct = (
                        (entry - candle["close"]) / entry * 100
                    )
                trades.append(current_trade)
                in_trade = False
                current_trade = None
                continue
            
            # SL خورده (اگه TP1 قبلاً خورده → BE)
            if hit_sl:
                if current_trade.result == "TP1_HIT":
                    # SL breakeven → partial win
                    tp1_pnl = partial_tp1 / 100 * (
                        (abs(tp1 - entry) / entry * 100)
                    )
                    current_trade.pnl_pct = tp1_pnl
                    current_trade.result = "WIN"
                else:
                    if direction == "LONG":
                        current_trade.pnl_pct = (
                            (sl - entry) / entry * 100
                        )
                    else:
                        current_trade.pnl_pct = (
                            (entry - sl) / entry * 100
                        )
                    current_trade.result = "LOSS"
                
                current_trade.exit_bar = i
                current_trade.exit_price = sl
                trades.append(current_trade)
                in_trade = False
                current_trade = None
                continue
            
            # TP1 خورده
            if hit_tp1 and current_trade.result != "TP1_HIT":
                current_trade.result = "TP1_HIT"
                if move_sl_to_be:
                    current_trade.sl = entry  # SL به breakeven
            
            # TP2 خورده
            if hit_tp2:
                remaining = 100 - partial_tp1
                if direction == "LONG":
                    pnl_1 = partial_tp1 / 100 * (
                        (tp1 - entry) / entry * 100
                    )
                    pnl_2 = remaining / 100 * (
                        (tp2 - entry) / entry * 100
                    )
                else:
                    pnl_1 = partial_tp1 / 100 * (
                        (entry - tp1) / entry * 100
                    )
                    pnl_2 = remaining / 100 * (
                        (entry - tp2) / entry * 100
                    )
                current_trade.pnl_pct = pnl_1 + pnl_2
                current_trade.result = "WIN"
                current_trade.exit_bar = i
                current_trade.exit_price = tp2
                trades.append(current_trade)
                in_trade = False
                current_trade = None
                continue
    
    # اگه ترید باز مونده
    if in_trade and current_trade:
        last_close = df["close"].iloc[-1]
        if current_trade.direction == "LONG":
            current_trade.pnl_pct = (
                (last_close - current_trade.entry) / current_trade.entry * 100
            )
        else:
            current_trade.pnl_pct = (
                (current_trade.entry - last_close) / current_trade.entry * 100
            )
        current_trade.result = "OPEN"
        current_trade.exit_bar = len(df) - 1
        current_trade.exit_price = last_close
        trades.append(current_trade)
    
    return trades


def run_full_backtest(symbol: str = "BTCUSDT",
                      days: int = 30) -> Dict:
    """
    بک‌تست کامل همه استراتژی‌ها روی یک نماد
    """
    # دریافت داده
    df_4h = get_klines(symbol, "4h", days * 6)
    df_15m = get_klines(symbol, "15m", days * 96)
    
    if df_4h is None or df_15m is None:
        return {"error": "No data available"}
    
    # بایاس کلی
    sh_4h, sl_4h = find_swing_points(df_4h, lookback=5)
    structure = classify_structure(sh_4h, sl_4h)
    htf_bias = structure["bias"]
    
    if not htf_bias or "NEUTRAL" in htf_bias:
        # اگه bias نداریم، هر دو رو تست کن
        biases = ["BULLISH", "BEARISH"]
    else:
        biases = [htf_bias]
    
    strategies = [
        ("QM", detect_quasimodo),
        ("ENGULFING", detect_engulfing),
        ("PINBAR", detect_pinbar),
        ("FVG", detect_fvg_signal),
        ("IFVG", detect_ifvg_signal),
        ("FLIPZONE", detect_flipzone),
        ("BREAKOUT", detect_breakout),
        ("ORDERBLOCK", detect_orderblock_signal),
        ("CHOCH", detect_structure_change),
        ("RETURN_AREA", detect_return_to_area),
    ]
    
    all_results = {}
    
    for bias in biases:
        for name, func in strategies:
            try:
                trades = backtest_strategy(
                    func, df_15m, bias, symbol
                )
                
                if trades:
                    wins = sum(1 for t in trades if t.result == "WIN")
                    losses = sum(1 for t in trades if t.result == "LOSS")
                    total = wins + losses
                    
                    all_results[f"{name}_{bias}"] = {
                        "strategy": name,
                        "bias": bias,
                        "total_trades": len(trades),
                        "wins": wins,
                        "losses": losses,
                        "winrate": (wins / total * 100) if total > 0 else 0,
                        "avg_pnl": np.mean([t.pnl_pct for t in trades]),
                        "total_pnl": sum(t.pnl_pct for t in trades),
                        "best_trade": max(t.pnl_pct for t in trades),
                        "worst_trade": min(t.pnl_pct for t in trades),
                        "avg_bars": np.mean([t.bars_held for t in trades]),
                        "max_dd": max(t.max_drawdown for t in trades),
                        "trades": [
                            {
                                "entry": t.entry,
                                "sl": t.sl,
                                "tp1": t.tp1,
                                "result": t.result,
                                "pnl": round(t.pnl_pct, 2),
                                "bars": t.bars_held,
                                "dd": round(t.max_drawdown, 2),
                            }
                            for t in trades[:10]  # آخرین ۱۰ ترید
                        ]
                    }
            except Exception as e:
                print(f"Backtest error {name}: {e}")
                continue
    
    return all_results


def generate_backtest_report(results: Dict) -> str:
    """گزارش بک‌تست به فرمت متن"""
    if not results or "error" in results:
        return "❌ داده‌ای برای بک‌تست موجود نیست"
    
    lines = [
        "📊 <b>Backtest Report</b>",
        "━━━━━━━━━━━━━━━━━━\n"
    ]
    
    # مرتب‌سازی بر اساس winrate
    sorted_results = sorted(
        results.items(),
        key=lambda x: x[1].get("winrate", 0),
        reverse=True
    )
    
    for key, data in sorted_results:
        strategy = data["strategy"]
        bias = data["bias"]
        winrate = data["winrate"]
        total = data["total_trades"]
        wins = data["wins"]
        losses = data["losses"]
        avg_pnl = data["avg_pnl"]
        total_pnl = data["total_pnl"]
        max_dd = data["max_dd"]
        
        emoji = "🏆" if winrate >= 70 else "⭐" if winrate >= 55 else "⚠️" if winrate >= 40 else "❌"
        
        lines.append(
            f"{emoji} <b>{strategy}</b> ({bias})\n"
            f"├ 📈 Trades: {total} (W:{wins} L:{losses})\n"
            f"├ 🎯 Winrate: {winrate:.1f}%\n"
            f"├ 💰 Avg PnL: {avg_pnl:+.2f}%\n"
            f"├ 📊 Total PnL: {total_pnl:+.2f}%\n"
            f"└ 📉 Max DD: {max_dd:.2f}%\n"
        )
    
    # خلاصه
    all_wins = sum(d["wins"] for d in results.values())
    all_losses = sum(d["losses"] for d in results.values())
    all_total = all_wins + all_losses
    overall_wr = (all_wins / all_total * 100) if all_total > 0 else 0
    
    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        f"🏆 <b>Overall</b>",
        f"├ Total Trades: {all_total}",
        f"├ Winrate: {overall_wr:.1f}%",
        f"└ Best: {max(results.values(), key=lambda x: x.get('winrate', 0))['strategy']}",
    ])
    
    return "\n".join(lines)
