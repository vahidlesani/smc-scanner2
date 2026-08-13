# smc-scanner v6 - MTF + 5min scan + partial TP + approaching alerts
import time
import schedule
import os
import pandas as pd
from datetime import datetime

from data.fetcher import get_multi_tf, get_klines
from analysis.structure import find_swing_points, classify_structure, detect_bos_choch
from analysis.smc import find_order_blocks, detect_liquidity
from analysis.rtm import get_rtm_signal
from analysis.ict import get_ict_signal
from analysis.strategies import run_all_strategies, StrategySignal
from analysis.mtf import analyze_mtf_swing, analyze_mtf_scalp, get_mtf_confirmation_text
from bot.telegram_bot import (
    send_signal_with_chart, send_message,
    send_performance_report, attach_money_management,
    send_confirmation_signal, send_cancellation_signal,
    send_approaching_alert, send_tp1_hit_signal,
)
from bot.commands import start_command_listener
from database.db import (
    init_db, save_signal, save_active_signal,
    was_signal_sent_recently, get_performance_stats,
    check_open_signals, update_market_memory,
    get_market_memory, get_active_signals,
    cancel_active_signal, confirm_active_signal,
    mark_approaching_sent, mark_tp1_hit, mark_sl_moved_to_be,
)

ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", "1000"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.5"))
CHAT_ID_SIGNALS = os.environ.get("CHAT_ID_SIGNALS", "")
CHAT_ID_APPROACHING = os.environ.get("CHAT_ID_APPROACHING", "")  # کانال هشدار نزدیک شدن
CHAT_ID_ADMIN = os.environ.get("CHAT_ID", "")

CHANNEL_NAME = "vivasignalyst-Chanel"

SYMBOLS = sorted(set([
    # بزرگ‌ها (Majors)
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "PAXGUSDT", "XAGUSDT", "LINKUSDT", "LDOUSDT", "ICPUSDT",
    "BCHUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT",
    "TRXUSDT", "TONUSDT",
    # لایه ۱ (Layer 1)
    "ATOMUSDT", "NEARUSDT", "FTMUSDT", "ALGOUSDT", "EGLDUSDT",
    "KAVAUSDT", "ROSEUSDT", "ONEUSDT", "IOTXUSDT",
    # لایه ۲ (Layer 2)
    "LTCUSDT", "POLUSDT", "INJUSDT", "APTUSDT", "SUIUSDT",
    "ARBUSDT", "OPUSDT", "IMXUSDT", "MINAUSDT",
    # دیفای (DeFi)
    "AAVEUSDT", "MKRUSDT", "COMPUSDT", "SNXUSDT", "CRVUSDT",
    "UNIUSDT", "SUSHIUSDT", "DYDXUSDT", "1INCHUSDT",
    # هوش مصنوعی (AI)
    "FETUSDT", "RENDERUSDT", "AGIXUSDT", "OCEANUSDT",
    "WLDUSDT", "ARKMUSDT", "AIUSDT",
    # جدید و محبوب
    "SEIUSDT", "TIAUSDT", "JUPUSDT", "STXUSDT",
    "PYTHUSDT", "JTOUSDT", "WUSDT", "ENSUSDT",
    "PENDLEUSDT", "BLURUSDT", "HNTUSDT", "FILUSDT",
    "THETAUSDT", "APEUSDT", "GALAUSDT", "MANAUSDT",
    "SANDUSDT", "AXSUSDT",
]))


def calculate_trade_params(entry, sl, direction):
    sl_distance = abs(entry - sl)
    sl_pct = sl_distance / entry
    if sl_pct == 0:
        return None

    risk_amount = ACCOUNT_SIZE * (RISK_PERCENT / 100)
    position_size = risk_amount / sl_distance

    if direction == "LONG":
        tp1 = entry + sl_distance * 2
        tp2 = entry + sl_distance * 3
    else:
        tp1 = entry - sl_distance * 2
        tp2 = entry - sl_distance * 3

    return {
        "sl_pct": sl_pct * 100,
        "risk_amount": risk_amount,
        "position_size": position_size,
        "tp1": tp1,
        "tp2": tp2
    }


def analyze_symbol(symbol):
    signals = []
    
    # ─── MTF Swing: 4H → 1H → 15M ───
    mtf_swing = analyze_mtf_swing(symbol)
    htf_bias = mtf_swing.get("bias")
    
    if not htf_bias or "NEUTRAL" in (htf_bias or ""):
        return signals, None

    # ─── MTF Scalp: 1H → 15M → 5M ───
    mtf_scalp = analyze_mtf_scalp(symbol)
    scalp_bias = mtf_scalp.get("bias")
    scalp_confirmed = mtf_scalp.get("htf_confirmed", False)
    scalp_ready = mtf_scalp.get("ltf_ready", False)

    tf_data = get_multi_tf(symbol)
    df_1d = tf_data.get("1d")
    df_4h = tf_data.get("4h")
    df_15m = tf_data.get("15m")

    if df_4h is None or df_15m is None:
        return signals, None

    current_price = df_15m["close"].iloc[-1]
    prev_memory = get_market_memory(symbol)
    
    mtf_text = get_mtf_confirmation_text(mtf_swing)
    mtf_confirmed = mtf_swing.get("htf_confirmed", False)

    # ─── SMC ───
    obs = find_order_blocks(df_4h, htf_bias, lookback=50)
    sh_15m, sl_15m = find_swing_points(df_15m, lookback=3)
    liquidity = detect_liquidity(df_15m, sh_15m, sl_15m)
    bos_15m = detect_bos_choch(df_15m, sh_15m, sl_15m)

    near_ob = False
    ob_top = 0
    ob_bottom = 0
    ob_strength = 0
    has_sweep = False
    has_choch = False

    for ob in obs[:2]:
        in_zone = ob.bottom <= current_price <= ob.top
        near_zone = (
            abs(current_price - ob.top) / current_price < 0.015
            or abs(current_price - ob.bottom) / current_price < 0.015
        )
        if not (in_zone or near_zone):
            continue

        near_ob = True
        ob_top = ob.top
        ob_bottom = ob.bottom
        ob_strength = ob.strength

        has_sweep = (
            (htf_bias == "BULLISH" and
             liquidity["sweep_type"] == "SWEEP_LOW") or
            (htf_bias == "BEARISH" and
             liquidity["sweep_type"] == "SWEEP_HIGH")
        )
        has_choch = bool(
            bos_15m
            and bos_15m.direction == htf_bias
            and bos_15m.type == "CHoCH"
        )

        prev_had_sweep = prev_memory.get("has_sweep", False)
        prev_had_choch = prev_memory.get("has_choch", False)
        prev_near_ob = prev_memory.get("near_ob", False)

        new_sweep = has_sweep and not prev_had_sweep
        new_choch = has_choch and not prev_had_choch
        just_entered_ob = near_ob and not prev_near_ob

        confirmations = []
        confirmations.append("✅ Sweep" if has_sweep else "⚠️ No Sweep")
        confirmations.append("✅ CHoCH" if has_choch else "⚠️ No CHoCH")

        if new_sweep: confirmations.append("🆕 Sweep جدید!")
        if new_choch: confirmations.append("🆕 CHoCH جدید!")
        if just_entered_ob: confirmations.append("🆕 ورود به OB!")
        if mtf_confirmed: confirmations.append("✅ تایید MTF")

        should_signal = new_sweep or new_choch or just_entered_ob

        direction = "LONG" if htf_bias == "BULLISH" else "SHORT"
        sl = ob_bottom * 0.998 if direction == "LONG" else ob_top * 1.002
        trade = calculate_trade_params(current_price, sl, direction)

        if trade and should_signal:
            signals.append({
                "source": "SMC", "symbol": symbol,
                "direction": direction, "entry": current_price,
                "sl": sl, "sl_original": sl,
                "tp1": trade["tp1"], "tp2": trade["tp2"],
                "ob_zone": f"{ob_bottom:.4f}-{ob_top:.4f}",
                "ob_strength": f"{ob_strength:.1f}x",
                "confirmations": confirmations,
                "bias": htf_bias, "trade_params": trade,
                "strategy_fa": "اسمارت مانی",
                "mtf_text": mtf_text,
                "mtf_confirmed": mtf_confirmed,
                "trade_style": "SWING",
            })

    # ─── RTM ───
    rtm = get_rtm_signal(df_4h, htf_bias)
    rtm_pattern = ""
    rtm_fresh = False

    if rtm:
        rtm_pattern = rtm["pattern"]
        rtm_fresh = True
        prev_rtm = prev_memory.get("rtm_pattern", "")

        sl = (rtm["base_bottom"] * 0.997 if rtm["direction"] == "LONG"
              else rtm["base_top"] * 1.003)
        trade = calculate_trade_params(current_price, sl, rtm["direction"])

        if trade and rtm_pattern != prev_rtm:
            signals.append({
                "source": "RTM", "symbol": symbol,
                "direction": rtm["direction"], "entry": current_price,
                "sl": sl, "sl_original": sl,
                "tp1": trade["tp1"], "tp2": trade["tp2"],
                "pattern": rtm["pattern"],
                "base_zone": f"{rtm['base_bottom']:.4f}-{rtm['base_top']:.4f}",
                "strength": rtm["strength"],
                "confirmations": [
                    f"Pattern: {rtm['pattern']}",
                    f"Strength: {rtm['strength']}",
                    "🆕 Pattern جدید!",
                    *([ "✅ تایید MTF"] if mtf_confirmed else [])
                ],
                "bias": htf_bias, "trade_params": trade,
                "strategy_fa": "RTM",
                "mtf_text": mtf_text,
                "mtf_confirmed": mtf_confirmed,
                "trade_style": "SWING",
            })

    # ─── ICT ───
    ict = get_ict_signal(df_4h, df_15m, df_1d, htf_bias)
    ict_in_ote = False
    ict_in_kz = False

    if ict:
        ict_in_ote = True
        prev_in_ote = prev_memory.get("ict_in_ote", False)

        entry = (ict["entry_top"] + ict["entry_bottom"]) / 2
        sl = (ict["entry_bottom"] * 0.997 if ict["direction"] == "LONG"
              else ict["entry_top"] * 1.003)
        trade = calculate_trade_params(entry, sl, ict["direction"])
        kz = ict.get("killzone")
        ict_in_kz = bool(kz)
        mss = ict.get("mss_confirmed", False)

        if trade and not prev_in_ote:
            signals.append({
                "source": "ICT", "symbol": symbol,
                "direction": ict["direction"], "entry": entry,
                "sl": sl, "sl_original": sl,
                "tp1": trade["tp1"], "tp2": trade["tp2"],
                "ote_zone": f"{ict['entry_bottom']:.4f}-{ict['entry_top']:.4f}",
                "killzone": kz, "in_killzone": ict_in_kz,
                "mss": mss, "pdh": ict.get("pdh"), "pdl": ict.get("pdl"),
                "confirmations": [
                    f"{'✅' if ict_in_kz else '⚠️'} KZ: {kz or 'None'}",
                    f"{'✅' if mss else '⚠️'} MSS",
                    "🆕 ورود به OTE!",
                    *([ "✅ تایید MTF"] if mtf_confirmed else [])
                ],
                "bias": htf_bias, "trade_params": trade,
                "strategy_fa": "ICT",
                "mtf_text": mtf_text,
                "mtf_confirmed": mtf_confirmed,
                "trade_style": "SWING",
            })

    # ─── اسکلپ سیگنال‌ها (5M) ───
    if scalp_bias and scalp_confirmed and scalp_ready:
        df_5m = get_klines(symbol, "5m", 100)
        if df_5m is not None:
            scalp_strategies = run_all_strategies(df_5m, scalp_bias)
            scalp_mtf_text = get_mtf_confirmation_text(mtf_scalp)
            
            for strat_signal in scalp_strategies:
                if was_signal_sent_recently(
                    symbol, strat_signal.strategy,
                    strat_signal.direction, hours=2
                ):
                    continue
                
                trade = calculate_trade_params(
                    strat_signal.entry, strat_signal.sl,
                    strat_signal.direction
                )
                
                if trade:
                    confirmations = strat_signal.confirmations.copy()
                    confirmations.append("✅ تایید MTF Scalp")
                    
                    # فقط اسکلپ واقعی (SL کمتر از 0.5%)
                    sl_pct = abs(strat_signal.entry - strat_signal.sl) / strat_signal.entry * 100
                    if sl_pct < 0.5:
                        signals.append({
                            "source": strat_signal.strategy,
                            "symbol": symbol,
                            "direction": strat_signal.direction,
                            "entry": strat_signal.entry,
                            "sl": strat_signal.sl,
                            "sl_original": strat_signal.sl,
                            "tp1": strat_signal.tp1,
                            "tp2": strat_signal.tp2,
                            "zone_top": strat_signal.zone_top,
                            "zone_bottom": strat_signal.zone_bottom,
                            "strength": strat_signal.strength,
                            "confirmations": confirmations,
                            "description": strat_signal.description,
                            "entry_conditions": strat_signal.entry_conditions,
                            "score_bonus": strat_signal.score_bonus,
                            "bias": scalp_bias,
                            "trade_params": trade,
                            "strategy_fa": strat_signal.strategy_fa,
                            "mtf_text": scalp_mtf_text,
                            "mtf_confirmed": True,
                            "trade_style": "SCALP",
                            "scalp_tf": "5m",
                        })

    # ─── استراتژی‌های جدید (Swing) ───
    new_strategies = run_all_strategies(df_15m, htf_bias)
    
    for strat_signal in new_strategies:
        if was_signal_sent_recently(
            symbol, strat_signal.strategy,
            strat_signal.direction, hours=4
        ):
            continue
        
        trade = calculate_trade_params(
            strat_signal.entry, strat_signal.sl, strat_signal.direction
        )
        
        if trade:
            confirmations = strat_signal.confirmations.copy()
            if mtf_confirmed:
                confirmations.append("✅ تایید MTF")
            
            signals.append({
                "source": strat_signal.strategy,
                "symbol": symbol,
                "direction": strat_signal.direction,
                "entry": strat_signal.entry,
                "sl": strat_signal.sl,
                "sl_original": strat_signal.sl,
                "tp1": strat_signal.tp1,
                "tp2": strat_signal.tp2,
                "zone_top": strat_signal.zone_top,
                "zone_bottom": strat_signal.zone_bottom,
                "strength": strat_signal.strength,
                "confirmations": confirmations,
                "description": strat_signal.description,
                "entry_conditions": strat_signal.entry_conditions,
                "score_bonus": strat_signal.score_bonus,
                "bias": htf_bias,
                "trade_params": trade,
                "strategy_fa": strat_signal.strategy_fa,
                "mtf_text": mtf_text,
                "mtf_confirmed": mtf_confirmed,
                "trade_style": "SWING",
            })

    # ذخیره حافظه
    update_market_memory(symbol, {
        "bias": htf_bias,
        "near_ob": near_ob,
        "ob_top": ob_top,
        "ob_bottom": ob_bottom,
        "ob_strength": ob_strength,
        "has_sweep": has_sweep,
        "has_choch": has_choch,
        "rtm_pattern": rtm_pattern,
        "rtm_fresh": rtm_fresh,
        "ict_in_ote": ict_in_ote,
        "ict_in_killzone": ict_in_kz,
        "current_price": current_price
    })

    return signals, df_15m


def check_approaching_entry(sig_data: dict, df_15m: pd.DataFrame) -> bool:
    """چک میکنه آیا قیمت 80% به Entry نزدیک شده"""
    if df_15m is None:
        return False
    
    current_price = df_15m["close"].iloc[-1]
    entry = sig_data["entry"]
    sl = sig_data["sl"]
    direction = sig_data["direction"]
    
    # محاسبه فاصله فعلی از Entry
    distance = abs(current_price - entry)
    sl_distance = abs(entry - sl)
    
    if sl_distance == 0:
        return False
    
    # اگه قیمت 80% مسیر به Entry رو طی کرده
    if direction == "LONG":
        # قیمت باید پایین Entry باشه و داره بالا میاد
        if current_price < entry:
            progress = 1 - (distance / sl_distance)
            return progress >= 0.8
    else:
        # قیمت باید بالای Entry باشه و داره پایین میاد
        if current_price > entry:
            progress = 1 - (distance / sl_distance)
            return progress >= 0.8
    
    return False


def check_signal_confirmation(sig_data: dict, df_15m: pd.DataFrame) -> bool:
    """چک میکنه آیا پوزیشن تایید ورود گرفته"""
    if df_15m is None:
        return False

    current_close = df_15m["close"].iloc[-1]
    entry = sig_data["entry"]
    direction = sig_data["direction"]

    if direction == "LONG" and current_close > entry * 1.001:
        return True
    if direction == "SHORT" and current_close < entry * 0.999:
        return True
    return False


def check_signal_cancellation(sig_data: dict, df_15m: pd.DataFrame) -> bool:
    """چک میکنه آیا سیگنال باطل شده"""
    if df_15m is None:
        return False

    current_close = df_15m["close"].iloc[-1]
    entry = sig_data["entry"]
    sl = sig_data["sl"]
    direction = sig_data["direction"]

    sl_distance = abs(entry - sl)

    if direction == "LONG":
        cancel_level = entry - (sl_distance * 0.5)
        return current_close < cancel_level
    else:
        cancel_level = entry + (sl_distance * 0.5)
        return current_close > cancel_level


def monitor_active_signals():
    """
    مانیتورینگ سیگنال‌های فعال:
    ۱. هشدار نزدیک شدن (80%) → کانال هشدار
    ۲. تایید ورود → کانال اصلی
    ۳. باطل شدن → کانال اصلی
    ۴. TP1 hit + SL to BE
    """
    active = get_active_signals()

    for sig_data in active:
        try:
            symbol = sig_data["symbol"]
            signal_id = sig_data["signal_id"]

            df_15m = get_klines(symbol, "15m", 10, closed_only=False)
            if df_15m is None:
                continue

            current_price = df_15m['close'].iloc[-1]

            # ۱. هشدار نزدیک شدن (80%) → کانال هشدار
            if not sig_data.get("approaching_sent"):
                if check_approaching_entry(sig_data, df_15m):
                    mark_approaching_sent(signal_id)
                    # ارسال به کانال هشدار
                    from bot.telegram_bot import send_approaching_alert_to_channel
                    send_approaching_alert_to_channel(sig_data, signal_id, current_price)

            # ۲. تایید ورود → کانال اصلی
            if check_signal_confirmation(sig_data, df_15m):
                confirm_active_signal(signal_id)
                send_confirmation_signal(sig_data, signal_id, current_price)

            # ۳. باطل شدن → کانال اصلی
            elif check_signal_cancellation(sig_data, df_15m):
                cancel_active_signal(signal_id)
                send_cancellation_signal(sig_data, signal_id)

        except Exception as e:
            print(f"Monitor error {sig_data.get('signal_id')}: {e}")


def run_scan():
    try:
        print(f"[{datetime.utcnow().strftime('%H:%M')}] "
              f"Scanning {len(SYMBOLS)} symbols...")

        # چک سیگنال‌های باز (WIN/LOSS + TP1)
        try:
            closed = check_open_signals()
            for c in closed:
                from bot.telegram_bot import send_result_to_channel
                send_result_to_channel(
                    symbol=c["symbol"],
                    signal_id=c.get("signal_id", "N/A"),
                    result=c["result"],
                    pnl=c["pnl"],
                    leverage=c.get("leverage", 5),
                    margin_usd=c.get("margin_usd", 0)
                )
        except Exception as e:
            print(f"Check closed signals error: {e}")

        # مانیتورینگ سیگنال‌های فعال
        try:
            monitor_active_signals()
        except Exception as e:
            print(f"Monitor active signals error: {e}")

        # اسکن نمادها
        MIN_SCORE_TO_SEND = 7  # فقط سیگنال‌های بالای امتیاز ۷ بفرست
        
        for symbol in SYMBOLS:
            try:
                signals, df_15m = analyze_symbol(symbol)

                for sig in signals:
                    try:
                        if was_signal_sent_recently(
                            symbol, sig["source"],
                            sig["direction"], hours=4
                        ):
                            continue

                        attach_money_management(sig)
                        
                        # ذخیره در دیتابیس (همه سیگنال‌ها)
                        save_signal(sig)
                        save_active_signal(sig)
                        
                        # فقط سیگنال‌های با امتیاز بالای ۷ به کانال بفرست
                        score = sig.get("score", 0)
                        if score >= MIN_SCORE_TO_SEND:
                            send_signal_with_chart(sig, df_15m)
                            time.sleep(2)
                        else:
                            print(f"[{symbol}] Score {score} < {MIN_SCORE_TO_SEND}, skipped sending")

                    except Exception as e:
                        print(f"Signal send error {symbol}: {e}")

            except Exception as e:
                print(f"Error {symbol}: {e}")

        print(f"[{datetime.utcnow().strftime('%H:%M')}] Scan done.")

    except Exception as e:
        print(f"Critical scan error: {e}")


def run_daily_report():
    try:
        stats = get_performance_stats()
        send_performance_report(stats)
    except Exception as e:
        print(f"Daily report error: {e}")
        send_message("📊 گزارش روزانه: هنوز سیگنال بسته‌ای نداریم.")


def main():
    if not os.environ.get("TELEGRAM_TOKEN"):
        print("WARNING: TELEGRAM_TOKEN is not set")

    try:
        init_db()
    except Exception as e:
        print(f"DB init error: {e}")

    send_message(
        f"🚀 <b>Scanner v6 Started</b>\n"
        f"📢 کانال: <b>{CHANNEL_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 SMC | 🔷 RTM | 💎 ICT\n"
        f"🔮 QM | 🔥 Engulfing | 📌 PinBar\n"
        f"📐 FVG | 🔄 IFVG | 🔁 FlipZone\n"
        f"💥 Breakout | 🧱 OB | ⚡ CHoCH\n"
        f"🎯 Return to Area\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔄 Multi-Timeframe: 4H→1H→15M (Swing) | 1H→15M→5M (Scalp)\n"
        f"⏱ Scan: 5min (24/7)\n"
        f"📊 Partial TP: 60% TP1 + 40% TP2\n"
        f"🔒 SL to Breakeven after TP1\n"
        f"🔔 3-Phase Alerts: Initial → Approaching → Confirmed\n"
        f"🆔 IDs start with: viva-\n"
        f"🧠 Smart Memory Active\n"
        f"📌 {len(SYMBOLS)} Symbols\n"
        f"🤖 Commands: /help /stats /backtest /strategies\n"
        f"🎯 Min Score to Send: 7/10"
    )

    # شروع گوش دادن به دستورات تلگرام
    try:
        start_command_listener()
        print("🤖 Telegram commands active: /help /stats /backtest /strategies")
    except Exception as e:
        print(f"Command listener error: {e}")

    # هر 5 دقیقه اسکن
    schedule.every(5).minutes.do(run_scan)
    # گزارش روزانه
    schedule.every().day.at("08:00").do(run_daily_report)

    run_scan()

    while True:
        try:
            schedule.run_pending()
            time.sleep(30)
        except Exception as e:
            print(f"Scheduler error: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
